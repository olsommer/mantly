"""Email processing endpoint."""

import base64
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request

from automail.api.attachments import load_attachment_files, parse_email_attachments
from automail.core.auth import TokenPayload, get_current_tenant, get_token_payload
from automail.core.rate_limit import limiter
from automail.db.pocketbase.client import (
    get_chat,
    get_project,
    get_user_default_project,
    get_user_projects,
    list_tenant_projects,
    store_email_analysis,
    upsert_issue_from_chat,
)
from automail.models import EmailResponse, Message, ProcessEmailRequest, TokenUsage
from automail.monitoring import (
    RunRecorder,
    actions_from_intent,
    email_input_summary,
    pipeline_output_summary,
)
from automail.pipeline import run_pipeline
from automail.pipeline.drafts import ensure_draft_exists, get_live_source
from automail.pipeline.intent.consumers import resolve_intent_action_payloads

logger = logging.getLogger(__name__)

MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS = 8_000
MAX_EXTRACTED_ATTACHMENT_TEXT_TOTAL_CHARS = 24_000

router = APIRouter()


def _sync_issue_from_chat(
    chat: dict,
    *,
    tenant_id: str | None,
    project_id: str | None,
    source: str,
) -> None:
    if not project_id:
        return
    try:
        upsert_issue_from_chat(
            chat,
            tenant_id=tenant_id,
            project_id=project_id,
            source=source,
        )
    except Exception:
        logger.warning("Failed to sync support issue for chat %s", chat.get("email_id") or chat.get("id"), exc_info=True)


def _decoded_attachment_size(raw_base64: str) -> int:
    payload = (raw_base64 or "").strip()
    if not payload:
        return 0
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]
    try:
        return len(base64.b64decode(payload, validate=False))
    except Exception:
        return 0


def _email_attachment_metadata(
    email,
    parsed_attachments: dict[str, str] | None = None,
) -> list[dict]:
    attachments = getattr(email, "attachments", None) or []
    items: list[dict] = []
    remaining_extracted_chars = MAX_EXTRACTED_ATTACHMENT_TEXT_TOTAL_CHARS
    for attachment in attachments:
        filename = str(getattr(attachment, "filename", "") or "").strip()
        if not filename:
            continue
        raw_base64 = str(getattr(attachment, "base64", "") or "")
        content_type = str(
            getattr(attachment, "content_type", "")
            or getattr(attachment, "contentType", "")
            or ""
        ).strip()
        if not content_type and raw_base64.startswith("data:") and "," in raw_base64:
            content_type = raw_base64.split(",", 1)[0].removeprefix("data:").split(";", 1)[0].strip()
        item: dict = {"filename": filename}
        if content_type:
            item["contentType"] = content_type
        size = _decoded_attachment_size(raw_base64)
        if size:
            item["size"] = size
        extracted_text = str((parsed_attachments or {}).get(filename) or "").strip()
        if extracted_text:
            if remaining_extracted_chars > 0:
                text_limit = min(MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS, remaining_extracted_chars)
                bounded_text = extracted_text[:text_limit]
                item["extractedText"] = bounded_text
                remaining_extracted_chars -= len(bounded_text)
            else:
                bounded_text = ""
            if len(bounded_text) < len(extracted_text):
                item["extractedTextTruncated"] = True
        items.append(item)
    return items


def _email_thread_metadata(
    email,
    parsed_attachments: dict[str, str] | None = None,
) -> dict:
    refs = [str(item).strip() for item in (email.references or []) if str(item).strip()]
    return {
        key: value
        for key, value in {
            "threadId": email.thread_id or "",
            "messageId": email.message_id or email.id,
            "internetMessageId": email.internet_message_id or "",
            "inReplyTo": email.in_reply_to or "",
            "references": refs,
            "attachments": _email_attachment_metadata(email, parsed_attachments),
        }.items()
        if value
    }


def _resolve_process_project_id(body: ProcessEmailRequest, payload: Optional[TokenPayload]) -> str | None:
    """Resolve project scope for add-in processing.

    Explicit request project wins. User default remains fallback for older add-ins.
    """
    if not payload or not payload.user_id:
        return None

    projects = get_user_projects(payload.user_id)
    allowed_project_ids = {str(project.get("id", "")) for project in projects}
    requested_project_id = (body.project_id or "").strip()
    if payload.is_root or payload.is_platform_admin:
        if requested_project_id:
            project = get_project(requested_project_id)
            if not project or project.get("tenant") != payload.tenant_id:
                raise HTTPException(status_code=403, detail="You are not a member of that project")
            return requested_project_id

        default_project_id = get_user_default_project(payload.user_id)
        if default_project_id:
            project = get_project(default_project_id)
            if project and project.get("tenant") == payload.tenant_id:
                return default_project_id

        tenant_projects = list_tenant_projects(payload.tenant_id)
        if len(tenant_projects) == 1:
            return str(tenant_projects[0]["id"])
        return None

    if requested_project_id:
        if requested_project_id not in allowed_project_ids:
            raise HTTPException(status_code=403, detail="You are not a member of that project")
        return requested_project_id

    default_project_id = get_user_default_project(payload.user_id)
    if default_project_id:
        if default_project_id not in allowed_project_ids:
            raise HTTPException(status_code=403, detail="Default project is not accessible")
        return default_project_id

    if len(projects) == 1:
        return str(projects[0]["id"])

    return None


def process_email_for_context(
    body: ProcessEmailRequest,
    *,
    tenant_id: Optional[str],
    payload: Optional[TokenPayload],
    source: str = "addin",
    project_id_override: str | None = None,
    creator_override: str = "",
) -> List[Message]:
    # Resolve project for pipeline scoping. Explicit request project wins;
    # user default exists only as a backwards-compatible fallback.
    config_source = None
    project_id = None
    if project_id_override:
        project_id = project_id_override
        ensure_draft_exists(project_id, tenant_id=tenant_id)
        config_source = get_live_source(project_id, tenant_id=tenant_id)
    elif payload and payload.user_id:
        project_id = _resolve_process_project_id(body, payload)
        if project_id:
            ensure_draft_exists(project_id, tenant_id=tenant_id)
            config_source = get_live_source(project_id, tenant_id=tenant_id)

    # Enforce plan limits on email processing (SaaS only)
    if tenant_id:
        from automail.billing.usage import check_limit
        check_limit(tenant_id, "emails_per_month")

    """
    Process an incoming email and determine the appropriate action.

    This endpoint checks if the email was already analyzed in the database.
    If yes, it loads and returns the stored messages.
    If no, it analyzes the email, stores the original email and agent response as messages,
    and returns them.

    Args:
        body: ProcessEmailRequest containing:
            - email: Email object with subject, from_address, body, etc.
            - action: Action to perform (currently only 'respond' is supported)

    Returns:
        List of Messages:
            - First message: Original email (role='email')
            - Second message: Agent's analysis and response (role='ai')
    """

    recorder: RunRecorder | None = None
    try:
        # Extract email from body
        creator = creator_override or (payload.email if payload and payload.email else body.creator)
        email = body.email
        email_id = email.id
        recorder = RunRecorder(
            tenant_id=tenant_id,
            project_id=project_id,
            source=source,
            user_email=payload.email if payload else creator,
            input_data=email_input_summary(email),
        )

        # Check if email was already analyzed (tenant-scoped)
        existing_record = get_chat(email_id, tenant_id=tenant_id, project_id=project_id)

        if existing_record:
            logger.info("Email %s already analyzed, returning stored messages", email_id)
            _sync_issue_from_chat(
                existing_record,
                tenant_id=tenant_id,
                project_id=project_id,
                source=source,
            )
            # Convert stored messages dict to Message objects
            messages = []
            for msg_data in existing_record['messages']:
                try:
                    # Pydantic will automatically validate and convert
                    messages.append(Message(**msg_data))
                except Exception as e:
                    logger.error("Error reconstructing message: %s", e)
                    raise ValueError(f"Failed to reconstruct message from database: {str(e)}")

            if recorder:
                recorder.finish(
                    status="success",
                    output={"cached": True, "activatedIntent": existing_record.get("activated_intent")},
                )
            return messages

        # Email not analyzed yet - run the pipeline
        logger.info("Analyzing new email %s", email_id)

        try:
            # Parse email attachments with Docling
            parsed_attachments = parse_email_attachments(email)

            # Run pipeline (identity, intent, optional response drafting)
            pipeline_result = run_pipeline(
                email,
                parsed_attachments,
                creator=creator,
                tenant_id=tenant_id,
                project_id=project_id if project_id else None,
                config_source=config_source,
                # Connected channels create and ground the single final draft
                # from the persisted Inbox ticket. Add-in calls still need the
                # same composer synchronously in their response payload.
                compose_response=not source.startswith("channel:"),
            )
        except Exception as e:
            logger.error("Error during pipeline processing: %s", e)
            if recorder:
                recorder.finish(status="failed", error=str(e))
            raise ValueError(f"Pipeline processing error: {str(e)}")

        result = pipeline_result.agent_response
        identity_result = pipeline_result.identity_result
        intent_result = pipeline_result.intent_result
        phishing_result = pipeline_result.phishing_result
        prompt_injection_result = pipeline_result.prompt_injection_result
        token_usage = pipeline_result.token_usage

        logger.info(
            "Pipeline result: intent=%s, requires_human=%s",
            result.activated_intent, result.requires_human,
        )

        # Load attachment files if any
        attachments = load_attachment_files(
            result,
            intents_dir=config_source,
            intent_result=intent_result,
            strict_intent_ownership=True,
        )
        attachment_list = attachments if attachments else []

        # Create message for original email
        email_message = Message(
            user="email",
            role="email",
            content=f"Subject: {email.subject}\nFrom: {email.from_address}\n\n{email.body}"
        )

        # Resolve action payloads with identity data so the add-in can POST them to webhooks
        if intent_result and identity_result and identity_result.data:
            resolve_intent_action_payloads(intent_result, identity_result.data)

        # Create message for agent response (includes v3 pipeline results)
        ai_message = Message(
            user="response",
            role="response",
            content=EmailResponse(
                email_body=result.response_text,
                email_attachments=attachment_list,
                requires_human=result.requires_human,
                requires_human_reason=result.requires_human_reason,
                identity_result=identity_result,
                intent_result=intent_result,
                phishing_result=phishing_result,
                prompt_injection_result=prompt_injection_result,
                token_usage=TokenUsage.model_validate(token_usage) if token_usage else None,
                activated_intent=result.activated_intent,
            )
        )

        # Store both messages in database
        messages_to_store = [
            email_message.model_dump(),
            ai_message.model_dump()
        ]

        try:
            pipeline_tools_used = list(getattr(pipeline_result, "tools_used", []) or [])
            email_metadata = _email_thread_metadata(email, parsed_attachments)
            if pipeline_tools_used:
                # Persist the bounded name/method/status audit emitted by the HTTP
                # tool collector so a later cached re-sync retains provenance.
                email_metadata["toolsUsed"] = pipeline_tools_used
            record_id = store_email_analysis(
                email_id,
                creator,
                messages_to_store,
                subject=email.subject,
                from_address=email.from_address,
                activated_intent=result.activated_intent,
                requires_human=result.requires_human,
                tenant_id=tenant_id,
                identity_result=identity_result.model_dump() if identity_result else None,
                intent_result=intent_result.model_dump() if intent_result else None,
                phishing_result=phishing_result.model_dump() if phishing_result else None,
                prompt_injection_result=prompt_injection_result.model_dump() if prompt_injection_result else None,
                token_usage=token_usage,
                thread_id=email.thread_id or "",
                message_id=email.message_id or email.id,
                metadata=email_metadata,
                project_id=project_id,
            )
            try:
                from automail.db.pocketbase.client import store_llm_usage_events
                store_llm_usage_events(
                    token_usage.get("calls", []) if isinstance(token_usage, dict) else [],
                    tenant_id=tenant_id,
                    project_id=project_id,
                    chat_record_id=record_id,
                    run_id=email_id,
                )
            except Exception:
                logger.warning("Failed to store LLM usage events", exc_info=True)
            logger.info("Stored email analysis with ID: %s for email: %s", record_id, email_id)
            _sync_issue_from_chat(
                {
                    "record_id": record_id,
                    "email_id": email_id,
                    "creator": creator,
                    "messages": messages_to_store,
                    "subject": email.subject,
                    "from_address": email.from_address,
                    "thread_id": email.thread_id or "",
                    "message_id": email.message_id or email.id,
                    "metadata": email_metadata,
                    "activated_intent": result.activated_intent,
                    "requires_human": result.requires_human,
                    "identity_result": identity_result.model_dump(by_alias=True) if identity_result else None,
                    "intent_result": intent_result.model_dump(by_alias=True) if intent_result else None,
                    "phishing_result": phishing_result.model_dump(by_alias=True) if phishing_result else None,
                    "prompt_injection_result": (
                        prompt_injection_result.model_dump(by_alias=True) if prompt_injection_result else None
                    ),
                    "token_usage": token_usage,
                    "tools_used": pipeline_tools_used,
                    "project_id": project_id,
                },
                tenant_id=tenant_id,
                project_id=project_id,
                source=source,
            )
        except Exception as e:
            logger.error("Error storing email analysis: %s", e)
            # Continue even if storage fails

        if recorder:
            recorder.finish(
                status="needs_human" if result.requires_human else "success",
                output=pipeline_output_summary(pipeline_result),
                actions=actions_from_intent(intent_result),
            )

        # Return both messages
        return [email_message, ai_message]

    except ValueError:
        if recorder:
            try:
                recorder.finish(status="failed", error="Email processing failed")
            except Exception:
                pass
        logger.exception("Agent error processing email")
        raise HTTPException(status_code=500, detail="Email processing failed")

    except Exception:
        if recorder:
            try:
                recorder.finish(status="failed", error="Email processing failed")
            except Exception:
                pass
        logger.exception("Unexpected error processing email")
        raise HTTPException(status_code=500, detail="Email processing failed")


@router.post("/process", response_model=List[Message])
@limiter.limit("30/minute")
async def process_email(body: ProcessEmailRequest, request: Request) -> List[Message]:
    tenant_id: Optional[str] = get_current_tenant(request)
    payload = get_token_payload(request)
    return process_email_for_context(body, tenant_id=tenant_id, payload=payload, source="addin")
