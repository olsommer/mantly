from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request

from automail.addon.gmail import cards
from automail.addon.gmail.auth import GmailAddonAuthError, resolve_addon_identity, verify_google_request
from automail.addon.gmail.events import (
    GMAIL_CURRENT_ACTION_COMPOSE_SCOPE,
    GMAIL_CURRENT_MESSAGE_READONLY_SCOPE,
    USERINFO_EMAIL_SCOPE,
    GmailAddonEvent,
    GmailAddonEventError,
)
from automail.addon.gmail.gmail_client import GmailClientError, create_reply_draft, fetch_current_email
from automail.api.admin.actions import ActionTriggerRequest, execute_action_webhook
from automail.api.feedback import submit_feedback_for_context
from automail.api.process import _resolve_process_project_id, process_email_for_context
from automail.db.pocketbase.client import (
    approve_issue_action_execution,
    approve_issue_reply,
    create_issue_reply,
    deliver_issue_reply,
    get_chat,
    get_chat_project,
    get_issue,
    get_issue_by_chat_id,
    get_user_project_role,
    issue_reply_delivery_readiness,
    issue_reply_readiness_error,
    reject_issue_action_execution,
    request_issue_reply_changes,
    update_issue,
    upsert_issue_from_chat,
)
from automail.models import EmailResponse, FeedbackRequest, IntentAction, Message, ProcessEmailRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/addons/gmail", tags=["gmail-addon"])


def _addon_project_role(identity: Any, project_id: str, *, min_role: str = "viewer") -> str:
    if identity.payload is None:
        return "editor"
    role = str(get_user_project_role(identity.payload.user_id, project_id) or "").strip().lower()
    ranks = {"viewer": 0, "editor": 1, "admin": 2, "root": 3}
    if role not in ranks or ranks[role] < ranks[min_role]:
        raise HTTPException(status_code=403, detail="Gmail user has no required project access")
    return role


def _require_addon_reply_access(reply: dict[str, Any]) -> None:
    if reply.get("knowledgeOutputRestricted") is True:
        raise HTTPException(
            status_code=403,
            detail="Project admin review is required for this restricted knowledge answer",
        )


def _public_base_url(request: Request) -> str:
    explicit = os.getenv("GMAIL_ADDON_BASE_URL", "").strip() or os.getenv("PUBLIC_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}".rstrip("/")


def _app_url() -> str:
    return (
        os.getenv("GMAIL_ADDON_APP_URL", "").strip()
        or os.getenv("APP_PUBLIC_URL", "").strip()
        or "https://app.mantly.io"
    )


def _url_with_params(path: str, params: dict[str, str]) -> str:
    base = f"{_app_url().rstrip('/')}{path}"
    clean = {key: value for key, value in params.items() if value}
    return f"{base}?{urlencode(clean)}" if clean else base


def _connect_url(*, email: str = "", reason: str = "") -> str:
    return _url_with_params("/gmail/connect", {"source": "gmail", "email": email, "reason": reason})


def _signup_url(*, email: str = "") -> str:
    return _url_with_params("/gmail/connect", {"source": "gmail", "view": "signup", "email": email})


def _issue_url(*, tenant_id: str | None, project_id: str | None, issue_id: str | None) -> str:
    if not tenant_id or not project_id or not issue_id:
        return ""
    return f"{_app_url().rstrip('/')}/{tenant_id}/{project_id}/inbox/{issue_id}"


def _action_url(request: Request) -> str:
    return f"{_public_base_url(request)}/addons/gmail/action"


def _audience(request: Request) -> str:
    return os.getenv("GOOGLE_ADDON_AUDIENCE", "").strip() or f"{_public_base_url(request)}{request.url.path}"


def _issue_for_chat(
    chat_id: str,
    *,
    tenant_id: str | None,
    source: str,
    project_id: str | None = None,
    actor_email: str = "",
    actor_role: str = "viewer",
) -> tuple[str | None, dict[str, Any] | None]:
    project_id = project_id or get_chat_project(chat_id, tenant_id=tenant_id)
    if not project_id:
        return None, None
    issue = get_issue_by_chat_id(
        chat_id,
        tenant_id=tenant_id,
        project_id=project_id,
        actor_email=actor_email,
        actor_role=actor_role,
    )
    if issue:
        return project_id, issue
    chat = get_chat(chat_id, tenant_id=tenant_id, project_id=project_id)
    if not chat:
        return project_id, None
    created = upsert_issue_from_chat(
        chat,
        tenant_id=tenant_id,
        project_id=project_id,
        source=source,
    )
    created_id = str(created.get("id") or "") if created else ""
    if not created_id:
        return project_id, None
    return project_id, get_issue(
        created_id,
        tenant_id=tenant_id,
        project_id=project_id,
        actor_email=actor_email,
        actor_role=actor_role,
    )


def _event(payload: dict[str, Any]) -> GmailAddonEvent:
    return GmailAddonEvent.from_payload(payload)


def _scope_response(event: GmailAddonEvent, scopes: list[str]) -> dict[str, Any] | None:
    missing = event.missing_scopes(scopes)
    return cards.request_scopes(missing) if missing else None


def _error_response(message: str) -> dict[str, Any]:
    return cards.update_card(cards.build_error_card(message))


def _auth_response(exc: GmailAddonAuthError, *, update: bool) -> dict[str, Any]:
    if exc.code == "google_identity_missing":
        card = cards.build_authorize_card(app_url=_connect_url(reason=exc.code))
    elif exc.code == "mantly_tenant_missing":
        card = cards.build_tenant_missing_card(
            email=exc.email,
            connect_url=_connect_url(email=exc.email, reason=exc.code),
        )
    else:
        card = cards.build_connect_card(
            email=exc.email,
            connect_url=_connect_url(email=exc.email, reason=exc.code),
            signup_url=_signup_url(email=exc.email),
        )
    return cards.update_card(card) if update else cards.push_card(card)


@router.post("/homepage")
async def gmail_homepage(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    verify_google_request(request, audience=_audience(request))
    return cards.push_card(cards.build_home_card(app_url=_connect_url()))


@router.post("/message")
async def gmail_message(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    verify_google_request(request, audience=_audience(request))
    event = _event(payload)
    scope_response = _scope_response(event, [USERINFO_EMAIL_SCOPE, GMAIL_CURRENT_MESSAGE_READONLY_SCOPE])
    if scope_response:
        return scope_response

    try:
        resolve_addon_identity(event)
        email = fetch_current_email(event)
    except GmailAddonAuthError as exc:
        return _auth_response(exc, update=False)
    except (GmailAddonEventError, GmailClientError) as exc:
        logger.info("Gmail message card failed: %s", exc)
        return cards.push_card(cards.build_error_card(str(exc)))

    return cards.push_card(cards.build_message_card(email, action_url=_action_url(request)))


@router.post("/action")
async def gmail_action(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    verify_google_request(request, audience=_audience(request))
    event = _event(payload)

    try:
        if event.action == "analyze":
            return _analyze(event, request)
        if event.action == "applyResponse":
            return _apply_response(event)
        if event.action == "retryFailedDelivery":
            return _retry_failed_delivery(event, request)
        if event.action == "approveIssueReply":
            return _approve_issue_replies(event, request, send=False)
        if event.action == "approveSendIssueReply":
            return _approve_issue_replies(event, request, send=True)
        if event.action == "requestIssueReplyChanges":
            return _request_issue_reply_changes(event, request)
        if event.action == "queueIssueReply":
            return _queue_issue_reply(event, request)
        if event.action == "approveIssueAction":
            return _review_issue_action(event, request, mode="approve")
        if event.action == "rejectIssueAction":
            return _review_issue_action(event, request, mode="reject")
        if event.action == "claimIssue":
            return _claim_issue(event, request)
        if event.action == "markIssueDone":
            return _mark_issue_done(event, request)
        if event.action == "triggerIntentAction":
            return await _trigger_intent_action(event, request)
        if event.action == "feedback":
            return _feedback(event)
    except GmailAddonAuthError as exc:
        return _auth_response(exc, update=True)
    except HTTPException as exc:
        return _error_response(str(exc.detail))
    except (GmailAddonEventError, GmailClientError) as exc:
        logger.info("Gmail add-on action failed: %s", exc)
        return _error_response(str(exc))
    except Exception:
        logger.exception("Unexpected Gmail add-on action failure")
        return _error_response("Mantly could not complete this action.")

    return _error_response("Unknown Gmail add-on action.")


def _analyze(event: GmailAddonEvent, request: Request) -> dict[str, Any]:
    scope_response = _scope_response(
        event,
        [USERINFO_EMAIL_SCOPE, GMAIL_CURRENT_MESSAGE_READONLY_SCOPE],
    )
    if scope_response:
        return scope_response

    identity = resolve_addon_identity(event)
    email = fetch_current_email(event)
    body = ProcessEmailRequest(email=email, creator=identity.email, action="respond")
    project_id = get_chat_project(email.id, tenant_id=identity.tenant_id)
    if not project_id:
        project_id = _resolve_process_project_id(body, identity.payload)
    if not project_id:
        raise HTTPException(status_code=400, detail="Select a Mantly project before analyzing Gmail")
    role = _addon_project_role(identity, project_id, min_role="viewer")
    messages = process_email_for_context(
        body,
        tenant_id=identity.tenant_id,
        payload=identity.payload,
        source="gmail",
        project_id_override=project_id,
    )
    issue: dict[str, Any] | None = None
    try:
        project_id, issue = _issue_for_chat(
            email.id,
            tenant_id=identity.tenant_id,
            source="gmail",
            project_id=project_id,
            actor_email=identity.email,
            actor_role=role,
        )
    except HTTPException:
        raise
    except Exception:
        logger.warning("Failed to load Gmail support issue for %s", email.id, exc_info=True)
        issue = None
    return cards.update_card(cards.build_result_card(
        messages,
        chat_id=email.id,
        action_url=_action_url(request),
        issue=issue,
        issue_url=_issue_url(
            tenant_id=identity.tenant_id,
            project_id=project_id,
            issue_id=str(issue.get("id") or "") if issue else "",
        ),
    ))


def _project_id_for_chat(chat_id: str, *, tenant_id: str | None) -> str:
    project_id = get_chat_project(chat_id, tenant_id=tenant_id)
    if not project_id:
        raise HTTPException(status_code=404, detail="Gmail action project not found")
    return project_id


def _response_from_chat(chat_id: str, *, tenant_id: str | None, project_id: str | None) -> EmailResponse:
    chat = get_chat(chat_id, tenant_id=tenant_id, project_id=project_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Gmail action context not found")

    for raw_message in reversed(chat.get("messages") or []):
        message = Message.model_validate(raw_message)
        if message.role != "response":
            continue
        content = message.content
        if isinstance(content, EmailResponse):
            return content
        if isinstance(content, dict):
            return EmailResponse.model_validate(content)

    raise HTTPException(status_code=404, detail="Gmail action response not found")


def _apply_response(event: GmailAddonEvent) -> dict[str, Any]:
    scope_response = _scope_response(
        event,
        [USERINFO_EMAIL_SCOPE, GMAIL_CURRENT_MESSAGE_READONLY_SCOPE, GMAIL_CURRENT_ACTION_COMPOSE_SCOPE],
    )
    if scope_response:
        return scope_response

    identity = resolve_addon_identity(event)
    chat_id = event.parameters.get("chatId", "")
    if not chat_id:
        raise HTTPException(status_code=400, detail="Response chat id missing")

    project_id = _project_id_for_chat(chat_id, tenant_id=identity.tenant_id)
    _addon_project_role(identity, project_id, min_role="viewer")
    response = _response_from_chat(chat_id, tenant_id=identity.tenant_id, project_id=project_id)
    if not response.email_body.strip():
        raise HTTPException(status_code=400, detail="No generated response available")

    email = fetch_current_email(event)
    draft = create_reply_draft(event, email, response)
    draft_id = draft.get("id", "")
    if not draft_id:
        raise HTTPException(status_code=502, detail="Gmail draft id missing")
    return cards.open_created_draft(draft_id=draft_id, thread_id=draft.get("threadId", event.thread_id))


def _retry_failed_delivery(event: GmailAddonEvent, request: Request) -> dict[str, Any]:
    scope_response = _scope_response(event, [USERINFO_EMAIL_SCOPE])
    if scope_response:
        return scope_response

    identity = resolve_addon_identity(event)
    chat_id = event.parameters.get("chatId", "")
    issue_id = event.parameters.get("issueId", "")
    if not chat_id or not issue_id:
        raise HTTPException(status_code=400, detail="Retry delivery parameters missing")

    project_id = _project_id_for_chat(chat_id, tenant_id=identity.tenant_id)
    role = _addon_project_role(identity, project_id, min_role="editor")
    issue = get_issue(
        issue_id,
        tenant_id=identity.tenant_id,
        project_id=project_id,
        actor_email=identity.email,
        actor_role=role,
    )
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    failed_replies = [
        reply for reply in issue.get("outboundMessages", [])
        if str(reply.get("status") or "") == "failed" and str(reply.get("id") or "")
    ]
    if not failed_replies:
        return cards.notification("No failed delivery to retry")

    errors: list[str] = []
    for reply in failed_replies:
        _require_addon_reply_access(reply)
        reply_id = str(reply.get("id") or "")
        try:
            retried = deliver_issue_reply(
                issue_id,
                reply_id,
                tenant_id=identity.tenant_id,
                project_id=project_id,
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not retried:
            errors.append("Reply not found")

    if errors and len(errors) == len(failed_replies):
        raise HTTPException(status_code=400, detail=errors[0] or "Delivery retry failed")

    refreshed_issue = get_issue(
        issue_id,
        tenant_id=identity.tenant_id,
        project_id=project_id,
        actor_email=identity.email,
        actor_role=role,
    ) or issue
    response = _response_from_chat(chat_id, tenant_id=identity.tenant_id, project_id=project_id)
    return cards.update_card(cards.build_result_card(
        [Message(role="response", user="response", content=response)],
        chat_id=chat_id,
        action_url=_action_url(request),
        issue=refreshed_issue,
        issue_url=_issue_url(
            tenant_id=identity.tenant_id,
            project_id=project_id,
            issue_id=str(refreshed_issue.get("id") or issue_id),
        ),
    ))


def _issue_action_context(event: GmailAddonEvent) -> tuple[Any, str, str, str, dict[str, Any]]:
    scope_response = _scope_response(event, [USERINFO_EMAIL_SCOPE])
    if scope_response:
        raise HTTPException(status_code=401, detail="Gmail identity scope required")

    identity = resolve_addon_identity(event)
    chat_id = event.parameters.get("chatId", "")
    issue_id = event.parameters.get("issueId", "")
    if not chat_id or not issue_id:
        raise HTTPException(status_code=400, detail="Issue action parameters missing")

    project_id = _project_id_for_chat(chat_id, tenant_id=identity.tenant_id)
    role = _addon_project_role(identity, project_id, min_role="editor")
    issue = get_issue(
        issue_id,
        tenant_id=identity.tenant_id,
        project_id=project_id,
        actor_email=identity.email,
        actor_role=role,
    )
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return identity, chat_id, issue_id, project_id, issue


def _reply_requires_approval(reply: dict[str, Any]) -> bool:
    metadata = reply.get("metadata") if isinstance(reply.get("metadata"), dict) else {}
    review_status = str(metadata.get("reviewStatus") or "pending").strip().lower()
    return (
        str(reply.get("status") or "").strip().lower() != "sent"
        and metadata.get("approvalRequired") is True
        and metadata.get("approved") is not True
        and review_status != "changes_requested"
    )


def _pending_approval_replies(issue: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        reply for reply in issue.get("outboundMessages", [])
        if isinstance(reply, dict) and str(reply.get("id") or "").strip() and _reply_requires_approval(reply)
    ]


def _issue_update_card(
    *,
    event: GmailAddonEvent,
    request: Request,
    chat_id: str,
    project_id: str,
    issue: dict[str, Any],
    tenant_id: str | None,
) -> dict[str, Any]:
    response = _response_from_chat(chat_id, tenant_id=tenant_id, project_id=project_id)
    return cards.update_card(cards.build_result_card(
        [Message(role="response", user="response", content=response)],
        chat_id=chat_id,
        action_url=_action_url(request),
        issue=issue,
        issue_url=_issue_url(
            tenant_id=tenant_id,
            project_id=project_id,
            issue_id=str(issue.get("id") or event.parameters.get("issueId", "")),
        ),
    ))


def _approve_issue_replies(event: GmailAddonEvent, request: Request, *, send: bool) -> dict[str, Any]:
    identity, chat_id, issue_id, project_id, issue = _issue_action_context(event)
    pending_replies = _pending_approval_replies(issue)
    if not pending_replies:
        return cards.notification("No pending approval reply")

    errors: list[str] = []
    processed = 0
    for reply in pending_replies:
        _require_addon_reply_access(reply)
        reply_id = str(reply.get("id") or "").strip()
        if send:
            readiness = issue_reply_delivery_readiness(
                issue,
                reply,
                tenant_id=identity.tenant_id,
                project_id=project_id,
            )
            if not readiness.get("ready"):
                errors.append(issue_reply_readiness_error(readiness))
                continue
        try:
            approved = approve_issue_reply(
                issue_id,
                reply_id,
                tenant_id=identity.tenant_id,
                project_id=project_id,
                approved_by=identity.email,
            )
            if not approved:
                errors.append("Reply not found")
                continue
            if send:
                delivered = deliver_issue_reply(
                    issue_id,
                    reply_id,
                    tenant_id=identity.tenant_id,
                    project_id=project_id,
                    actor_email=identity.email,
                )
                if not delivered:
                    errors.append("Reply not found")
                    continue
            processed += 1
        except ValueError as exc:
            errors.append(str(exc))

    if processed == 0:
        detail = errors[0] if errors else "Approval failed"
        raise HTTPException(status_code=400, detail=detail)

    refreshed_issue = get_issue(issue_id, tenant_id=identity.tenant_id, project_id=project_id) or issue
    return _issue_update_card(
        event=event,
        request=request,
        chat_id=chat_id,
        project_id=project_id,
        issue=refreshed_issue,
        tenant_id=identity.tenant_id,
    )


def _request_issue_reply_changes(event: GmailAddonEvent, request: Request) -> dict[str, Any]:
    identity, chat_id, issue_id, project_id, issue = _issue_action_context(event)
    pending_replies = _pending_approval_replies(issue)
    if not pending_replies:
        return cards.notification("No pending approval reply")

    note = event.form_string("replyChangeNote", "").strip() or "Requested from Gmail add-on"
    errors: list[str] = []
    processed = 0
    for reply in pending_replies:
        _require_addon_reply_access(reply)
        reply_id = str(reply.get("id") or "").strip()
        try:
            requested = request_issue_reply_changes(
                issue_id,
                reply_id,
                tenant_id=identity.tenant_id,
                project_id=project_id,
                requested_by=identity.email,
                note=note,
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not requested:
            errors.append("Reply not found")
            continue
        processed += 1

    if processed == 0:
        detail = errors[0] if errors else "Change request failed"
        raise HTTPException(status_code=400, detail=detail)

    refreshed_issue = get_issue(issue_id, tenant_id=identity.tenant_id, project_id=project_id) or issue
    return _issue_update_card(
        event=event,
        request=request,
        chat_id=chat_id,
        project_id=project_id,
        issue=refreshed_issue,
        tenant_id=identity.tenant_id,
    )


def _review_issue_action(event: GmailAddonEvent, request: Request, *, mode: str) -> dict[str, Any]:
    identity, chat_id, issue_id, project_id, issue = _issue_action_context(event)
    action_id = event.parameters.get("actionId", "").strip()
    if not action_id:
        raise HTTPException(status_code=400, detail="Action id missing")

    try:
        result = approve_issue_action_execution(
            issue_id,
            action_id,
            tenant_id=identity.tenant_id,
            project_id=project_id,
            approved_by=identity.email,
            authorization_header=request.headers.get("Authorization", ""),
        ) if mode == "approve" else reject_issue_action_execution(
            issue_id,
            action_id,
            tenant_id=identity.tenant_id,
            project_id=project_id,
            rejected_by=identity.email,
            note="Rejected from Gmail add-on",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Action not found")

    refreshed_issue = result.get("issue") if isinstance(result.get("issue"), dict) else None
    refreshed_issue = refreshed_issue or get_issue(issue_id, tenant_id=identity.tenant_id, project_id=project_id) or issue
    return _issue_update_card(
        event=event,
        request=request,
        chat_id=chat_id,
        project_id=project_id,
        issue=refreshed_issue,
        tenant_id=identity.tenant_id,
    )


def _queue_issue_reply(event: GmailAddonEvent, request: Request) -> dict[str, Any]:
    identity, chat_id, issue_id, project_id, issue = _issue_action_context(event)
    if _pending_approval_replies(issue):
        return cards.notification("Approval already pending")

    response = _response_from_chat(chat_id, tenant_id=identity.tenant_id, project_id=project_id)
    if not response.email_body.strip():
        raise HTTPException(status_code=400, detail="No generated response available")

    metadata = {"approvalRequired": True, "approved": False, "reviewStatus": "pending"}
    queued = create_issue_reply(
        issue_id,
        tenant_id=identity.tenant_id,
        project_id=project_id,
        author_email=identity.email,
        body=response.email_body,
        status="queued",
        source="gmail_addon",
        metadata=metadata,
        attachments=response.email_attachments,
    )
    if not queued:
        raise HTTPException(status_code=404, detail="Issue not found")

    refreshed_issue = get_issue(issue_id, tenant_id=identity.tenant_id, project_id=project_id) or issue
    return _issue_update_card(
        event=event,
        request=request,
        chat_id=chat_id,
        project_id=project_id,
        issue=refreshed_issue,
        tenant_id=identity.tenant_id,
    )


def _claim_issue(event: GmailAddonEvent, request: Request) -> dict[str, Any]:
    identity, chat_id, issue_id, project_id, issue = _issue_action_context(event)
    if str(issue.get("assigneeEmail") or "").strip():
        updated_issue = issue
    else:
        updated_issue = update_issue(
            issue_id,
            tenant_id=identity.tenant_id,
            project_id=project_id,
            updates={
                "assignee_email": identity.email,
                "workflow_source": "gmail_addon_claim",
            },
        ) or issue
    return _issue_update_card(
        event=event,
        request=request,
        chat_id=chat_id,
        project_id=project_id,
        issue=updated_issue,
        tenant_id=identity.tenant_id,
    )


def _mark_issue_done(event: GmailAddonEvent, request: Request) -> dict[str, Any]:
    identity, chat_id, issue_id, project_id, issue = _issue_action_context(event)
    updated_issue = update_issue(
        issue_id,
        tenant_id=identity.tenant_id,
        project_id=project_id,
        updates={
            "status": "done",
            "workflow_source": "gmail_addon_done",
        },
    ) or issue
    return _issue_update_card(
        event=event,
        request=request,
        chat_id=chat_id,
        project_id=project_id,
        issue=updated_issue,
        tenant_id=identity.tenant_id,
    )


def _action_from_response(response: EmailResponse, action_name: str) -> IntentAction:
    if not response.intent_result or not response.intent_result.matched:
        raise HTTPException(status_code=400, detail="No matched intent action available")

    for action in response.intent_result.actions:
        if action.name == action_name:
            return action
    raise HTTPException(status_code=404, detail="Gmail action not found")


def _action_form_values(event: GmailAddonEvent, response: EmailResponse) -> dict[str, str]:
    if not response.intent_result:
        return {}
    return {
        action.name: event.form_string(action.name, "")
        for action in response.intent_result.actions
        if (action.type or "button") != "button"
    }


def _action_payload(event: GmailAddonEvent, action: IntentAction, response: EmailResponse) -> dict[str, Any]:
    base_payload: dict[str, Any] = {
        **(action.payload or {}),
        "actionName": action.name,
        "actionLabel": action.label,
        "chatId": event.parameters.get("chatId", ""),
    }
    effective_type = action.type or "button"
    if effective_type == "button":
        return {**base_payload, **_action_form_values(event, response)}
    return {**base_payload, action.name: event.form_string(action.name, "")}


async def _trigger_intent_action(event: GmailAddonEvent, request: Request) -> dict[str, Any]:
    identity = resolve_addon_identity(event)
    chat_id = event.parameters.get("chatId", "")
    action_name = event.parameters.get("actionName", "")
    if not chat_id or not action_name:
        raise HTTPException(status_code=400, detail="Gmail action parameters missing")

    project_id = _project_id_for_chat(chat_id, tenant_id=identity.tenant_id)
    _addon_project_role(identity, project_id, min_role="editor")

    response = _response_from_chat(chat_id, tenant_id=identity.tenant_id, project_id=project_id)
    action = _action_from_response(response, action_name)
    if not action.webhook:
        raise HTTPException(status_code=400, detail="Gmail action has no webhook")

    await execute_action_webhook(
        ActionTriggerRequest(
            webhook=action.webhook,
            method=action.method,
            payload=_action_payload(event, action, response),
            headers=action.headers,
            query=action.query,
            body=action.body,
        ),
        tenant_id=identity.tenant_id or "",
        project_id=project_id,
        user_email=identity.email,
        authorization_header=request.headers.get("Authorization", ""),
    )
    return cards.notification("Action completed")


def _feedback(event: GmailAddonEvent) -> dict[str, Any]:
    identity = resolve_addon_identity(event)
    rating = event.parameters.get("rating", "")
    chat_id = event.parameters.get("chatId", "")
    if not chat_id:
        raise HTTPException(status_code=400, detail="Feedback chat id missing")
    project_id = _project_id_for_chat(chat_id, tenant_id=identity.tenant_id)
    _addon_project_role(identity, project_id, min_role="viewer")

    submit_feedback_for_context(
        FeedbackRequest(
            chat_id=chat_id,
            project_id=project_id,
            user=identity.email,
            rating=rating,
            affected_stages=["response_text"] if rating == "dislike" else [],
            feedback_text=event.form_string("feedbackText", ""),
        ),
        tenant_id=identity.tenant_id,
        project_id=project_id,
        user_email=identity.email,
    )
    return cards.notification("Feedback saved")
