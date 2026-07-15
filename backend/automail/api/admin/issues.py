"""Admin issue inbox endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from automail.api.admin.deps import AuthDep, ProjectEditorDep, ProjectViewerDep
from automail.db.pocketbase.client import (
    approve_issue_action_execution,
    archive_reply_macro,
    create_customer_portal_session,
    create_issue_action_execution,
    create_issue_agent_answer,
    create_issue_agent_chat_message,
    create_issue_note,
    create_issue_reply,
    create_manual_issue,
    delete_inbox_view,
    deliver_issue_reply,
    get_chat,
    get_issue,
    get_issue_by_chat_id,
    issue_answer_workspace,
    issue_kanban_board,
    issue_reply_delivery_readiness,
    issue_reply_readiness_error,
    list_inbox_views,
    list_issue_notifications,
    list_issue_watchers,
    list_issues,
    list_reply_macros,
    list_support_queues,
    mark_issue_notification_read,
    merge_issues,
    prepare_issue_custom_fields,
    prepare_issue_triage,
    redact_issue_agent_answer_for_principal,
    redact_issue_reply_for_principal,
    reject_issue_action_execution,
    render_reply_macro,
    request_issue_reply_changes,
    split_issue_message,
    suggest_issue_duplicates,
    support_analytics,
    unwatch_issue,
    update_issue,
    update_issue_reply,
    upsert_inbox_view,
    upsert_issue_from_chat,
    upsert_reply_macro,
    upsert_support_queue,
    watch_issue,
)
from automail.db.pocketbase.client import (
    approve_issue_reply as approve_issue_reply_record,
)
from automail.models import CamelCaseModel

router = APIRouter()


class IssueUpdate(CamelCaseModel):
    status: str | None = None
    priority: str | None = None
    assignee_email: str | None = None
    queue_key: str | None = None
    queue_name: str | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None
    workflow_source: str | None = None


class IssueCreate(CamelCaseModel):
    subject: str = ""
    from_address: str
    body: str
    account_id: str = ""
    contact_id: str = ""
    contact_name: str = ""
    account_name: str = ""
    priority: str = "normal"
    assignee_email: str = ""
    queue_key: str = ""
    queue_name: str = ""


class IssueBulkUpdate(CamelCaseModel):
    issue_ids: list[str]
    status: str | None = None
    priority: str | None = None
    assignee_email: str | None = None
    queue_key: str | None = None
    queue_name: str | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None
    workflow_source: str | None = None


def _workflow_proof_result(
    *,
    issue: dict[str, Any],
    tenant_id: str | None,
    project_id: str,
) -> dict[str, Any]:
    analytics = support_analytics(
        tenant_id=tenant_id,
        project_id=project_id,
    )
    launch_readiness = analytics.get("launchReadiness") if isinstance(analytics, dict) else {}
    return {
        "issue": issue,
        "launchReadiness": launch_readiness if isinstance(launch_readiness, dict) else {},
        "workflowTransitionEvents": analytics.get("workflowTransitionEvents", 0),
        "workflowOngoingTransitions": analytics.get("workflowOngoingTransitions", 0),
        "workflowDoneTransitions": analytics.get("workflowDoneTransitions", 0),
        "successfulWorkflowLifecycleProofs": analytics.get("successfulWorkflowLifecycleProofs", 0),
    }


def run_workflow_lifecycle_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    actor_email: str,
) -> dict[str, Any]:
    clean_actor = actor_email.strip().lower()
    if not clean_actor:
        raise ValueError("Signed-in agent email is required")
    issue = create_manual_issue(
        tenant_id=tenant_id,
        project_id=project_id,
        creator_email=clean_actor,
        subject="Launch proof: workflow lifecycle",
        from_address="launch-proof@example.invalid",
        contact_name="Launch Proof",
        account_name="Launch Proof",
        body="Synthetic ticket proving Inbox workflow lifecycle: open to ongoing to done.",
        priority="normal",
        assignee_email=clean_actor,
        queue_key="support",
        queue_name="Support",
        run_automations=False,
    )
    issue_id = str(issue.get("id") or "")
    if not issue_id:
        raise ValueError("Workflow proof ticket was not created")
    ongoing = update_issue(
        issue_id,
        tenant_id=tenant_id,
        project_id=project_id,
        updates={
            "status": "ongoing",
            "actor_email": clean_actor,
            "tags": ["launch-proof", "workflow-proof"],
            "workflow_source": "launch_proof",
        },
    )
    if not ongoing:
        raise ValueError("Workflow proof ticket could not move to ongoing")
    done = update_issue(
        issue_id,
        tenant_id=tenant_id,
        project_id=project_id,
        updates={
            "status": "done",
            "actor_email": clean_actor,
            "workflow_source": "launch_proof",
        },
    )
    if not done:
        raise ValueError("Workflow proof ticket could not move to done")
    return _workflow_proof_result(
        issue=done,
        tenant_id=tenant_id,
        project_id=project_id,
    )


class IssueBulkLabels(CamelCaseModel):
    issue_ids: list[str]
    tags: list[str]


class IssueMerge(CamelCaseModel):
    target_issue_id: str
    note: str = ""


class IssueMessageSplit(CamelCaseModel):
    message_id: str
    subject: str = ""
    note: str = ""
    run_automations: bool = True


class SupportQueueUpsert(CamelCaseModel):
    queue_key: str = ""
    name: str = ""
    description: str = ""
    default_assignee_email: str = ""
    status: str = "active"
    metadata: dict[str, Any] | None = None


class InboxViewUpsert(CamelCaseModel):
    id: str = ""
    name: str = ""
    visibility: str = "private"
    filters: dict[str, Any] | None = None
    sort_order: int = 0


class ReplyMacroUpsert(CamelCaseModel):
    id: str = ""
    title: str = ""
    body: str = ""
    visibility: str = "shared"
    status: str = "active"
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class ReplyMacroRenderInput(CamelCaseModel):
    issue_id: str


class IssueBulkApproveSend(CamelCaseModel):
    issue_ids: list[str]


class IssueBulkReplyChanges(CamelCaseModel):
    issue_ids: list[str]
    note: str = ""


class IssueBulkActionApproval(CamelCaseModel):
    issue_ids: list[str]
    note: str = ""


class IssueNoteCreate(CamelCaseModel):
    body: str


class IssueReplyCreate(CamelCaseModel):
    body: str
    status: str = "draft"
    approval_required: bool = False
    include_feedback_link: bool = False
    attachments: list[dict[str, Any]] | None = None


class IssueReplyUpdate(CamelCaseModel):
    body: str | None = None
    status: str | None = None


class IssueReplySend(CamelCaseModel):
    force_retry: bool = False


class IssueReplyChangesRequest(CamelCaseModel):
    note: str = ""


class IssueReplyReviseRequest(CamelCaseModel):
    note: str = ""
    include_feedback_link: bool = False


class IssueActionExecutionCreate(CamelCaseModel):
    action_key: str
    label: str
    type: str = "manual"
    status: str = "running"
    result: dict[str, Any] | None = None
    error: str = ""
    metadata: dict[str, Any] | None = None


class IssueActionExecutionReject(CamelCaseModel):
    note: str = ""


class IssuePortalSessionCreate(CamelCaseModel):
    expires_hours: int = 168


class IssueAgentAnswerCreate(CamelCaseModel):
    question: str = ""
    create_draft: bool = True
    include_feedback_link: bool = False
    approval_required: bool = True
    auto_send: bool = False


class IssueCustomFieldPrepare(CamelCaseModel):
    approval_required: bool = True
    only_missing: bool = True


class IssueTriagePrepare(CamelCaseModel):
    approval_required: bool = True


@router.get("/projects/{pid}/notifications")
async def get_notifications(
    ctx: ProjectViewerDep,
    auth: AuthDep,
    status: str = "unread",
    limit: int = 50,
) -> dict[str, Any]:
    items = list_issue_notifications(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        recipient_email=auth.email,
        status=status,
        limit=max(1, min(limit, 200)),
    )
    return {"items": items}


@router.post("/projects/{pid}/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, ctx: ProjectViewerDep, auth: AuthDep) -> dict[str, Any]:
    item = mark_issue_notification_read(
        notification_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        recipient_email=auth.email,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Notification not found")
    return item


@router.get("/projects/{pid}/issues")
async def get_issues(
    ctx: ProjectViewerDep,
    status: str = "all",
    queue_key: str = "",
    account_key: str = "",
    channel: str = "",
    assignee_email: str = "",
    tag: str = "",
    query: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    items = list_issues(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        status=status,
        queue_key=queue_key,
        account_key=account_key,
        channel=channel,
        assignee_email=assignee_email,
        tag=tag,
        query=query,
        limit=max(1, min(limit, 200)),
    )
    return {"items": items}


@router.get("/projects/{pid}/issues/board")
async def get_issue_board(
    ctx: ProjectViewerDep,
    status: str = "all",
    queue_key: str = "",
    account_key: str = "",
    channel: str = "",
    assignee_email: str = "",
    tag: str = "",
    query: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    return issue_kanban_board(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        status=status,
        queue_key=queue_key,
        account_key=account_key,
        channel=channel,
        assignee_email=assignee_email,
        tag=tag,
        query=query,
        limit=max(1, min(limit, 200)),
    )


@router.get("/projects/{pid}/support/queues")
async def get_support_queues(
    ctx: ProjectViewerDep,
    status: str = "active",
    include_workload: bool = False,
) -> dict[str, Any]:
    items = list_support_queues(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        status=status,
        include_owner_workload=include_workload,
    )
    return {"items": items}


@router.post("/projects/{pid}/support/queues")
async def save_support_queue(body: SupportQueueUpsert, ctx: ProjectEditorDep) -> dict[str, Any]:
    try:
        return upsert_support_queue(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            queue_key=body.queue_key,
            name=body.name,
            description=body.description,
            default_assignee_email=body.default_assignee_email,
            status=body.status,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{pid}/support/inbox-views")
async def get_inbox_views(ctx: ProjectViewerDep, auth: AuthDep) -> dict[str, Any]:
    items = list_inbox_views(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        owner_email=auth.email,
    )
    return {"items": items}


@router.post("/projects/{pid}/support/inbox-views")
async def save_inbox_view(body: InboxViewUpsert, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    try:
        return upsert_inbox_view(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            owner_email=auth.email,
            view_id=body.id,
            name=body.name,
            visibility=body.visibility,
            filters=body.filters,
            sort_order=body.sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/projects/{pid}/support/inbox-views/{view_id}")
async def remove_inbox_view(view_id: str, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, str]:
    try:
        deleted = delete_inbox_view(
            view_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            owner_email=auth.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Inbox view not found")
    return {"status": "deleted"}


@router.get("/projects/{pid}/support/reply-macros")
async def get_reply_macros(
    ctx: ProjectViewerDep,
    auth: AuthDep,
    status: str = "active",
    limit: int = 200,
) -> dict[str, Any]:
    items = list_reply_macros(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        owner_email=auth.email,
        status=status,
        limit=max(1, min(limit, 200)),
    )
    return {"items": items}


@router.post("/projects/{pid}/support/reply-macros")
async def save_reply_macro(body: ReplyMacroUpsert, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    try:
        return upsert_reply_macro(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            owner_email=auth.email,
            macro_id=body.id,
            title=body.title,
            body=body.body,
            visibility=body.visibility,
            status=body.status,
            tags=body.tags,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{pid}/support/reply-macros/{macro_id}/render")
async def render_reply_macro_endpoint(
    macro_id: str,
    body: ReplyMacroRenderInput,
    ctx: ProjectViewerDep,
    auth: AuthDep,
) -> dict[str, Any]:
    try:
        rendered = render_reply_macro(
            macro_id,
            issue_id=body.issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            owner_email=auth.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not rendered:
        raise HTTPException(status_code=404, detail="Reply macro not found")
    return rendered


@router.delete("/projects/{pid}/support/reply-macros/{macro_id}")
async def remove_reply_macro(macro_id: str, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    try:
        archived = archive_reply_macro(
            macro_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            owner_email=auth.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not archived:
        raise HTTPException(status_code=404, detail="Reply macro not found")
    return archived


@router.post("/projects/{pid}/issues")
async def create_issue(body: IssueCreate, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    assignee_email = body.assignee_email.strip() or auth.email.strip().lower()
    try:
        return create_manual_issue(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            creator_email=auth.email,
            subject=body.subject,
            from_address=body.from_address,
            body=body.body,
            account_id=body.account_id,
            contact_id=body.contact_id,
            contact_name=body.contact_name,
            account_name=body.account_name,
            priority=body.priority,
            assignee_email=assignee_email,
            queue_key=body.queue_key,
            queue_name=body.queue_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{pid}/support/workflow-proof/run")
async def run_support_workflow_proof(ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    try:
        return run_workflow_lifecycle_proof(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{pid}/issues/bulk-update")
async def bulk_update_issues(body: IssueBulkUpdate, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    issue_ids = [issue_id.strip() for issue_id in body.issue_ids if issue_id.strip()]
    if not issue_ids:
        raise HTTPException(status_code=400, detail="No issues selected")
    if len(issue_ids) > 100:
        raise HTTPException(status_code=400, detail="Bulk updates are limited to 100 issues")

    updates = body.model_dump(exclude={"issue_ids"}, exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    updates["assigned_by"] = auth.email
    updates["run_automations"] = True

    items: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for issue_id in issue_ids:
        try:
            issue = update_issue(
                issue_id,
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                updates=updates,
            )
        except ValueError as exc:
            failed.append({"id": issue_id, "error": str(exc)})
            continue
        if not issue:
            failed.append({"id": issue_id, "error": "Issue not found"})
            continue
        items.append(issue)

    return {"items": items, "failed": failed}


def _clean_label_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        clean = tag.strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        cleaned.append(clean)
        if len(cleaned) >= 20:
            break
    return cleaned


async def _bulk_issue_labels(
    body: IssueBulkLabels,
    ctx: ProjectEditorDep,
    auth: AuthDep,
    *,
    mode: str,
) -> dict[str, Any]:
    issue_ids = [issue_id.strip() for issue_id in body.issue_ids if issue_id.strip()]
    if not issue_ids:
        raise HTTPException(status_code=400, detail="No issues selected")
    if len(issue_ids) > 100:
        raise HTTPException(status_code=400, detail="Bulk label updates are limited to 100 issues")
    clean_tags = _clean_label_tags(body.tags)
    if not clean_tags:
        raise HTTPException(status_code=400, detail="No labels provided")
    tag_keys = {tag.lower() for tag in clean_tags}

    items: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for issue_id in issue_ids:
        issue = get_issue(issue_id, tenant_id=ctx.tenant_id, project_id=ctx.project_id)
        if not issue:
            failed.append({"id": issue_id, "error": "Issue not found"})
            continue
        current_tags = _clean_label_tags([str(tag) for tag in issue.get("tags", [])])
        if mode == "add":
            next_tags = current_tags[:]
            existing = {tag.lower() for tag in next_tags}
            for tag in clean_tags:
                if tag.lower() not in existing:
                    next_tags.append(tag)
                    existing.add(tag.lower())
        else:
            next_tags = [tag for tag in current_tags if tag.lower() not in tag_keys]
        try:
            updated = update_issue(
                issue_id,
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                updates={
                    "tags": next_tags,
                    "actor_email": auth.email,
                    "run_automations": True,
                },
            )
        except ValueError as exc:
            failed.append({"id": issue_id, "error": str(exc)})
            continue
        if not updated:
            failed.append({"id": issue_id, "error": "Issue not found"})
            continue
        items.append(updated)

    return {"items": items, "failed": failed}


@router.post("/projects/{pid}/issues/labels/bulk-add")
async def bulk_add_issue_labels(body: IssueBulkLabels, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    return await _bulk_issue_labels(body, ctx, auth, mode="add")


@router.post("/projects/{pid}/issues/labels/bulk-remove")
async def bulk_remove_issue_labels(body: IssueBulkLabels, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    return await _bulk_issue_labels(body, ctx, auth, mode="remove")


def _text_from(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _clip_text(value: str, limit: int = 1800) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _issue_reply_by_id(issue: dict[str, Any], reply_id: str) -> dict[str, Any] | None:
    for reply in issue.get("outboundMessages", []):
        if isinstance(reply, dict) and _text_from(reply.get("id")) == reply_id:
            return reply
    return None


def _require_reply_knowledge_access(reply: dict[str, Any], *, actor_role: str) -> None:
    if (
        reply.get("knowledgeOutputRestricted") is True
        and actor_role not in {"root", "admin"}
    ):
        raise HTTPException(
            status_code=403,
            detail="Project admin access is required for this restricted knowledge answer",
        )


def _reply_knowledge_output_admin_only(reply: dict[str, Any]) -> bool:
    metadata = reply.get("metadata") if isinstance(reply.get("metadata"), dict) else {}
    policy = metadata.get("knowledgeAccessPolicy")
    if isinstance(policy, dict) and policy.get("outputAdminOnly") is True:
        return True
    return any(
        isinstance(citation, dict)
        and _text_from(citation.get("visibility")).lower() == "private"
        and citation.get("automationAllowed") is not True
        for citation in metadata.get("citations", [])
    )


def _project_actor_role(ctx: Any) -> str:
    role = str(getattr(ctx, "role", "") or "viewer").strip().lower()
    return role if role in {"root", "admin", "editor", "viewer"} else "viewer"


def _reply_response_for_actor(
    reply: dict[str, Any],
    *,
    ctx: Any,
    actor_email: str,
) -> dict[str, Any]:
    return redact_issue_reply_for_principal(
        reply,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        actor_email=actor_email,
        actor_role=_project_actor_role(ctx),
    )


def _agent_answer_response_for_actor(
    answer: dict[str, Any],
    *,
    ctx: Any,
    actor_email: str,
) -> dict[str, Any]:
    return redact_issue_agent_answer_for_principal(
        answer,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        actor_email=actor_email,
        actor_role=_project_actor_role(ctx),
    )


def _issue_reply_for_actor(
    issue_id: str,
    reply_id: str,
    *,
    ctx: Any,
    actor_email: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    issue = get_issue(
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        actor_email=actor_email,
        actor_role=_project_actor_role(ctx),
    )
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    reply = _issue_reply_by_id(issue, reply_id)
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    _require_reply_knowledge_access(reply, actor_role=_project_actor_role(ctx))
    return issue, reply


def _reply_revision_question(reply: dict[str, Any], note: str) -> str:
    prior_body = _clip_text(_text_from(reply.get("body")), 3000)
    clean_note = note.strip() or "Revise the draft so it is ready for approval."
    return "\n\n".join(
        [
            "Revise this customer-facing support reply draft for human approval.",
            f"Reviewer note:\n{clean_note}",
            f"Existing draft:\n{prior_body}",
            "Return only the revised reply body. Do not include internal notes or markdown fences.",
        ]
    )


def _reply_requires_approval(reply: dict[str, Any]) -> bool:
    metadata = reply.get("metadata") if isinstance(reply.get("metadata"), dict) else {}
    review_status = str(metadata.get("reviewStatus") or "pending")
    return (
        metadata.get("approvalRequired") is True
        and metadata.get("approved") is not True
        and review_status != "changes_requested"
    )


def _pending_approval_replies(issue: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        reply for reply in issue.get("outboundMessages", [])
        if reply.get("status") != "sent" and _reply_requires_approval(reply)
    ]


def _action_execution_requires_approval(execution: dict[str, Any]) -> bool:
    metadata = execution.get("metadata") if isinstance(execution.get("metadata"), dict) else {}
    review_status = str(metadata.get("reviewStatus") or "pending")
    return (
        execution.get("status") == "pending"
        and metadata.get("approvalRequired") is True
        and review_status == "pending"
    )


def _pending_approval_actions(issue: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        execution for execution in issue.get("actionExecutions", [])
        if _action_execution_requires_approval(execution)
    ]


@router.post("/projects/{pid}/issues/replies/bulk-approve")
async def bulk_approve_issue_replies(
    body: IssueBulkApproveSend,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    issue_ids = [issue_id.strip() for issue_id in body.issue_ids if issue_id.strip()]
    if not issue_ids:
        raise HTTPException(status_code=400, detail="No issues selected")
    if len(issue_ids) > 100:
        raise HTTPException(status_code=400, detail="Bulk approvals are limited to 100 issues")

    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for issue_id in issue_ids:
        issue = get_issue(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
            actor_role=_project_actor_role(ctx),
        )
        if not issue:
            failed.append({"id": issue_id, "error": "Issue not found"})
            continue
        pending_replies = _pending_approval_replies(issue)
        if not pending_replies:
            failed.append({"id": issue_id, "error": "No pending approval reply"})
            issues.append(issue)
            continue

        for reply in pending_replies:
            try:
                _require_reply_knowledge_access(reply, actor_role=_project_actor_role(ctx))
            except HTTPException as exc:
                failed.append({"id": issue_id, "replyId": str(reply.get("id") or ""), "error": str(exc.detail)})
                continue
            reply_id = str(reply.get("id") or "")
            if not reply_id:
                failed.append({"id": issue_id, "error": "Reply missing id"})
                continue
            try:
                approved = approve_issue_reply_record(
                    issue_id,
                    reply_id,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    approved_by=auth.email,
                )
            except ValueError as exc:
                failed.append({"id": issue_id, "replyId": reply_id, "error": str(exc)})
                continue
            if not approved:
                failed.append({"id": issue_id, "replyId": reply_id, "error": "Reply not found"})
                continue
            items.append({
                "issueId": issue_id,
                "replyId": reply_id,
                "status": approved.get("status", ""),
                "error": approved.get("error", ""),
                "reply": _reply_response_for_actor(approved, ctx=ctx, actor_email=auth.email),
            })

        refreshed = get_issue(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
            actor_role=_project_actor_role(ctx),
        )
        if refreshed:
            issues.append(refreshed)

    return {
        "processed": len(items),
        "approved": len(items),
        "sent": 0,
        "failed": failed,
        "items": items,
        "issues": issues,
    }


@router.post("/projects/{pid}/issues/replies/bulk-approve-send")
async def bulk_approve_send_issue_replies(
    body: IssueBulkApproveSend,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    issue_ids = [issue_id.strip() for issue_id in body.issue_ids if issue_id.strip()]
    if not issue_ids:
        raise HTTPException(status_code=400, detail="No issues selected")
    if len(issue_ids) > 100:
        raise HTTPException(status_code=400, detail="Bulk approvals are limited to 100 issues")

    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for issue_id in issue_ids:
        issue = get_issue(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
            actor_role=_project_actor_role(ctx),
        )
        if not issue:
            failed.append({"id": issue_id, "error": "Issue not found"})
            continue
        pending_replies = _pending_approval_replies(issue)
        if not pending_replies:
            failed.append({"id": issue_id, "error": "No pending approval reply"})
            issues.append(issue)
            continue

        for reply in pending_replies:
            try:
                _require_reply_knowledge_access(reply, actor_role=_project_actor_role(ctx))
            except HTTPException as exc:
                failed.append({"id": issue_id, "replyId": str(reply.get("id") or ""), "error": str(exc.detail)})
                continue
            reply_id = str(reply.get("id") or "")
            if not reply_id:
                failed.append({"id": issue_id, "error": "Reply missing id"})
                continue
            readiness = issue_reply_delivery_readiness(
                issue,
                reply,
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
            )
            if not readiness.get("ready"):
                failed.append({"id": issue_id, "replyId": reply_id, "error": issue_reply_readiness_error(readiness)})
                continue
            try:
                approved = approve_issue_reply_record(
                    issue_id,
                    reply_id,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    approved_by=auth.email,
                )
                if not approved:
                    failed.append({"id": issue_id, "replyId": reply_id, "error": "Reply not found"})
                    continue
                sent = deliver_issue_reply(
                    issue_id,
                    reply_id,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    actor_email=auth.email,
                )
                if not sent:
                    failed.append({"id": issue_id, "replyId": reply_id, "error": "Reply not found"})
                    continue
            except ValueError as exc:
                failed.append({"id": issue_id, "replyId": reply_id, "error": str(exc)})
                continue
            items.append({
                "issueId": issue_id,
                "replyId": reply_id,
                "status": sent.get("status", ""),
                "error": sent.get("error", ""),
                "reply": _reply_response_for_actor(sent, ctx=ctx, actor_email=auth.email),
            })

        refreshed = get_issue(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
            actor_role=_project_actor_role(ctx),
        )
        if refreshed:
            issues.append(refreshed)

    return {
        "processed": len(items),
        "sent": sum(1 for item in items if item.get("status") == "sent"),
        "failed": failed,
        "items": items,
        "issues": issues,
    }


@router.post("/projects/{pid}/issues/replies/bulk-changes")
async def bulk_request_issue_reply_changes(
    body: IssueBulkReplyChanges,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    issue_ids = [issue_id.strip() for issue_id in body.issue_ids if issue_id.strip()]
    if not issue_ids:
        raise HTTPException(status_code=400, detail="No issues selected")
    if len(issue_ids) > 100:
        raise HTTPException(status_code=400, detail="Bulk change requests are limited to 100 issues")

    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    note = body.note.strip()
    for issue_id in issue_ids:
        issue = get_issue(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
            actor_role=_project_actor_role(ctx),
        )
        if not issue:
            failed.append({"id": issue_id, "error": "Issue not found"})
            continue
        pending_replies = _pending_approval_replies(issue)
        if not pending_replies:
            failed.append({"id": issue_id, "error": "No pending approval reply"})
            issues.append(issue)
            continue

        for reply in pending_replies:
            try:
                _require_reply_knowledge_access(reply, actor_role=_project_actor_role(ctx))
            except HTTPException as exc:
                failed.append({"id": issue_id, "replyId": str(reply.get("id") or ""), "error": str(exc.detail)})
                continue
            reply_id = str(reply.get("id") or "")
            if not reply_id:
                failed.append({"id": issue_id, "error": "Reply missing id"})
                continue
            try:
                requested = request_issue_reply_changes(
                    issue_id,
                    reply_id,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    requested_by=auth.email,
                    note=note,
                )
            except ValueError as exc:
                failed.append({"id": issue_id, "replyId": reply_id, "error": str(exc)})
                continue
            if not requested:
                failed.append({"id": issue_id, "replyId": reply_id, "error": "Reply not found"})
                continue
            items.append({
                "issueId": issue_id,
                "replyId": reply_id,
                "status": requested.get("status", ""),
                "error": requested.get("error", ""),
                "reply": _reply_response_for_actor(requested, ctx=ctx, actor_email=auth.email),
            })

        refreshed = get_issue(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
            actor_role=_project_actor_role(ctx),
        )
        if refreshed:
            issues.append(refreshed)

    return {
        "processed": len(items),
        "changesRequested": len(items),
        "sent": 0,
        "failed": failed,
        "items": items,
        "issues": issues,
    }


async def _bulk_review_issue_actions(
    body: IssueBulkActionApproval,
    ctx: ProjectEditorDep,
    auth: AuthDep,
    *,
    mode: str,
) -> dict[str, Any]:
    issue_ids = [issue_id.strip() for issue_id in body.issue_ids if issue_id.strip()]
    if not issue_ids:
        raise HTTPException(status_code=400, detail="No issues selected")
    if len(issue_ids) > 100:
        raise HTTPException(status_code=400, detail="Bulk action approvals are limited to 100 issues")

    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for issue_id in issue_ids:
        issue = get_issue(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        )
        if not issue:
            failed.append({"id": issue_id, "error": "Issue not found"})
            continue
        pending_actions = _pending_approval_actions(issue)
        if not pending_actions:
            failed.append({"id": issue_id, "error": "No pending approval action"})
            issues.append(issue)
            continue

        latest_issue: dict[str, Any] | None = None
        for execution in pending_actions:
            execution_id = str(execution.get("id") or "")
            if not execution_id:
                failed.append({"id": issue_id, "error": "Action missing id"})
                continue
            try:
                result = approve_issue_action_execution(
                    issue_id,
                    execution_id,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    approved_by=auth.email,
                ) if mode == "approve" else reject_issue_action_execution(
                    issue_id,
                    execution_id,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    rejected_by=auth.email,
                    note=body.note,
                )
            except ValueError as exc:
                failed.append({"id": issue_id, "executionId": execution_id, "error": str(exc)})
                continue
            if not result:
                failed.append({"id": issue_id, "executionId": execution_id, "error": "Action not found"})
                continue
            action_execution = result.get("execution") if isinstance(result, dict) else None
            latest_issue = result.get("issue") if isinstance(result, dict) and isinstance(result.get("issue"), dict) else latest_issue
            items.append({
                "issueId": issue_id,
                "executionId": execution_id,
                "status": action_execution.get("status", "") if isinstance(action_execution, dict) else "",
                "error": action_execution.get("error", "") if isinstance(action_execution, dict) else "",
                "execution": action_execution or execution,
            })

        if latest_issue:
            issues.append(latest_issue)
        else:
            refreshed = get_issue(
                issue_id,
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
            )
            if refreshed:
                issues.append(refreshed)

    reviewed_key = "approved" if mode == "approve" else "rejected"
    return {
        "processed": len(items),
        reviewed_key: len(items),
        "failed": failed,
        "items": items,
        "issues": issues,
    }


@router.post("/projects/{pid}/issues/actions/bulk-approve")
async def bulk_approve_issue_actions(
    body: IssueBulkActionApproval,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    return await _bulk_review_issue_actions(body, ctx, auth, mode="approve")


@router.post("/projects/{pid}/issues/actions/bulk-reject")
async def bulk_reject_issue_actions(
    body: IssueBulkActionApproval,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    return await _bulk_review_issue_actions(body, ctx, auth, mode="reject")


@router.post("/projects/{pid}/issues/replies/bulk-retry-failed")
async def bulk_retry_failed_issue_replies(
    body: IssueBulkApproveSend,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    issue_ids = [issue_id.strip() for issue_id in body.issue_ids if issue_id.strip()]
    if not issue_ids:
        raise HTTPException(status_code=400, detail="No issues selected")
    if len(issue_ids) > 100:
        raise HTTPException(status_code=400, detail="Bulk retries are limited to 100 issues")

    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for issue_id in issue_ids:
        issue = get_issue(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
            actor_role=_project_actor_role(ctx),
        )
        if not issue:
            failed.append({"id": issue_id, "error": "Issue not found"})
            continue
        failed_replies = [
            reply for reply in issue.get("outboundMessages", [])
            if reply.get("status") == "failed"
        ]
        if not failed_replies:
            failed.append({"id": issue_id, "error": "No failed reply"})
            issues.append(issue)
            continue

        for reply in failed_replies:
            try:
                _require_reply_knowledge_access(reply, actor_role=_project_actor_role(ctx))
            except HTTPException as exc:
                failed.append({"id": issue_id, "replyId": str(reply.get("id") or ""), "error": str(exc.detail)})
                continue
            reply_id = str(reply.get("id") or "")
            if not reply_id:
                failed.append({"id": issue_id, "error": "Reply missing id"})
                continue
            try:
                retried = deliver_issue_reply(
                    issue_id,
                    reply_id,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    actor_email=auth.email,
                )
                if not retried:
                    failed.append({"id": issue_id, "replyId": reply_id, "error": "Reply not found"})
                    continue
            except ValueError as exc:
                failed.append({"id": issue_id, "replyId": reply_id, "error": str(exc)})
                continue
            items.append({
                "issueId": issue_id,
                "replyId": reply_id,
                "status": retried.get("status", ""),
                "error": retried.get("error", ""),
                "reply": _reply_response_for_actor(retried, ctx=ctx, actor_email=auth.email),
            })

        refreshed = get_issue(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        )
        if refreshed:
            issues.append(refreshed)

    return {
        "processed": len(items),
        "sent": sum(1 for item in items if item.get("status") == "sent"),
        "failed": failed,
        "items": items,
        "issues": issues,
    }


@router.get("/projects/{pid}/issues/by-chat/{chat_id:path}")
async def get_issue_for_chat(chat_id: str, ctx: ProjectViewerDep, auth: AuthDep) -> dict[str, Any]:
    issue = get_issue_by_chat_id(
        chat_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        actor_email=auth.email,
        actor_role=_project_actor_role(ctx),
    )
    if not issue:
        chat = get_chat(chat_id, tenant_id=ctx.tenant_id, project_id=ctx.project_id)
        if chat:
            metadata = chat.get("metadata") if isinstance(chat.get("metadata"), dict) else {}
            source = str(metadata.get("source") or chat.get("source") or "addin").strip() or "addin"
            issue = upsert_issue_from_chat(
                chat,
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                source=source,
            )
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@router.get("/projects/{pid}/issues/{issue_id}")
async def get_issue_detail(issue_id: str, ctx: ProjectViewerDep, auth: AuthDep) -> dict[str, Any]:
    issue = get_issue(
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        actor_email=auth.email,
        actor_role=_project_actor_role(ctx),
    )
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@router.get("/projects/{pid}/issues/{issue_id}/answer-workspace")
async def get_issue_answer_workspace(issue_id: str, ctx: ProjectViewerDep, auth: AuthDep) -> dict[str, Any]:
    workspace = issue_answer_workspace(
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        actor_email=auth.email,
        actor_role=_project_actor_role(ctx),
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Issue not found")
    return workspace


@router.get("/projects/{pid}/issues/{issue_id}/duplicate-suggestions")
async def get_issue_duplicate_suggestions(
    issue_id: str,
    ctx: ProjectViewerDep,
    auth: AuthDep,
    limit: int = 5,
) -> dict[str, Any]:
    if not get_issue(
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        actor_email=auth.email,
        actor_role=_project_actor_role(ctx),
    ):
        raise HTTPException(status_code=404, detail="Issue not found")
    items = suggest_issue_duplicates(
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=max(1, min(limit, 20)),
    )
    return {"items": items}


@router.get("/projects/{pid}/issues/{issue_id}/watchers")
async def get_issue_watchers(issue_id: str, ctx: ProjectViewerDep) -> dict[str, Any]:
    items = list_issue_watchers(
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    return {"items": items}


@router.post("/projects/{pid}/issues/{issue_id}/watchers/me")
async def watch_issue_as_current_user(issue_id: str, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    watcher = watch_issue(
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        watcher_email=auth.email,
        added_by=auth.email,
    )
    if not watcher:
        raise HTTPException(status_code=404, detail="Issue not found")
    return watcher


@router.delete("/projects/{pid}/issues/{issue_id}/watchers/me")
async def unwatch_issue_as_current_user(issue_id: str, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    watcher = unwatch_issue(
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        watcher_email=auth.email,
    )
    if not watcher:
        raise HTTPException(status_code=404, detail="Watcher not found")
    return watcher


@router.patch("/projects/{pid}/issues/{issue_id}")
async def patch_issue(issue_id: str, body: IssueUpdate, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    try:
        updates = body.model_dump(exclude_unset=True)
        updates["assigned_by"] = auth.email
        updates["run_automations"] = True
        issue = update_issue(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            updates=updates,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@router.post("/projects/{pid}/issues/{issue_id}/merge")
async def merge_issue(issue_id: str, body: IssueMerge, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    try:
        issue = merge_issues(
            issue_id,
            target_issue_id=body.target_issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@router.post("/projects/{pid}/issues/{issue_id}/split-message")
async def split_issue_message_endpoint(
    issue_id: str,
    body: IssueMessageSplit,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    try:
        issue = split_issue_message(
            issue_id,
            message_id=body.message_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
            subject=body.subject,
            note=body.note,
            run_automations=body.run_automations,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not issue:
        raise HTTPException(status_code=404, detail="Issue message not found")
    return issue


@router.post("/projects/{pid}/issues/{issue_id}/notes")
async def add_issue_note(issue_id: str, body: IssueNoteCreate, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    try:
        note = create_issue_note(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            author_email=auth.email,
            body=body.body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not note:
        raise HTTPException(status_code=404, detail="Issue not found")
    return note


@router.post("/projects/{pid}/issues/{issue_id}/replies")
async def add_issue_reply(issue_id: str, body: IssueReplyCreate, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    reply_metadata: dict[str, Any] = {}
    if body.approval_required:
        reply_metadata.update({"approvalRequired": True, "approved": False, "reviewStatus": "pending"})
    if body.include_feedback_link:
        reply_metadata["includeFeedbackLink"] = True
    try:
        kwargs: dict[str, Any] = {}
        if body.attachments is not None:
            kwargs["attachments"] = body.attachments
        reply = create_issue_reply(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            author_email=auth.email,
            body=body.body,
            status=body.status,
            metadata=reply_metadata or None,
            **kwargs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not reply:
        raise HTTPException(status_code=404, detail="Issue not found")
    return reply


@router.patch("/projects/{pid}/issues/{issue_id}/replies/{reply_id}")
async def patch_issue_reply(
    issue_id: str,
    reply_id: str,
    body: IssueReplyUpdate,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    _issue_reply_for_actor(issue_id, reply_id, ctx=ctx, actor_email=auth.email)
    try:
        reply = update_issue_reply(
            issue_id,
            reply_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            editor_email=auth.email,
            body=body.body,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    return _reply_response_for_actor(reply, ctx=ctx, actor_email=auth.email)


@router.post("/projects/{pid}/issues/{issue_id}/replies/{reply_id}/send")
async def send_issue_reply(
    issue_id: str,
    reply_id: str,
    ctx: ProjectEditorDep,
    auth: AuthDep,
    body: IssueReplySend | None = None,
) -> dict[str, Any]:
    _issue_reply_for_actor(issue_id, reply_id, ctx=ctx, actor_email=auth.email)
    try:
        reply = deliver_issue_reply(
            issue_id,
            reply_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
            force_retry=bool(body.force_retry) if body else False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    return _reply_response_for_actor(reply, ctx=ctx, actor_email=auth.email)


@router.post("/projects/{pid}/issues/{issue_id}/replies/{reply_id}/approve")
async def approve_issue_reply(issue_id: str, reply_id: str, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    _issue_reply_for_actor(issue_id, reply_id, ctx=ctx, actor_email=auth.email)
    try:
        reply = approve_issue_reply_record(
            issue_id,
            reply_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            approved_by=auth.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    return _reply_response_for_actor(reply, ctx=ctx, actor_email=auth.email)


@router.post("/projects/{pid}/issues/{issue_id}/replies/{reply_id}/changes")
async def request_reply_changes(
    issue_id: str,
    reply_id: str,
    body: IssueReplyChangesRequest,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    _issue_reply_for_actor(issue_id, reply_id, ctx=ctx, actor_email=auth.email)
    try:
        reply = request_issue_reply_changes(
            issue_id,
            reply_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            requested_by=auth.email,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    return _reply_response_for_actor(reply, ctx=ctx, actor_email=auth.email)


@router.post("/projects/{pid}/issues/{issue_id}/replies/{reply_id}/revise")
async def revise_issue_reply(
    issue_id: str,
    reply_id: str,
    body: IssueReplyReviseRequest,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    issue, reply = _issue_reply_for_actor(
        issue_id,
        reply_id,
        ctx=ctx,
        actor_email=auth.email,
    )
    if _reply_knowledge_output_admin_only(reply):
        raise HTTPException(
            status_code=400,
            detail="Enable automation access for the private source or edit this reply manually",
        )
    if _text_from(reply.get("status")) == "sent":
        raise HTTPException(status_code=400, detail="Sent replies cannot be revised")

    metadata = reply.get("metadata") if isinstance(reply.get("metadata"), dict) else {}
    lineage = [
        item
        for item in metadata.get("knowledgeLineage", [])
        if isinstance(item, dict)
    ]
    if not lineage:
        lineage = [
            {
                "articleId": _text_from(citation.get("id") or citation.get("articleId")),
                "visibility": _text_from(citation.get("visibility")),
                "public": citation.get("public") is True,
                "automationAllowed": citation.get("automationAllowed") is True,
            }
            for citation in metadata.get("citations", [])
            if isinstance(citation, dict)
            and _text_from(citation.get("id") or citation.get("articleId"))
        ]
    knowledge_article_ids = sorted(
        {
            _text_from(article_id)
            for key in (
                "knowledgeArticleIds",
                "knowledgeAccessedArticleIds",
                "knowledgeContextArticleIds",
            )
            for article_id in (metadata.get(key) if isinstance(metadata.get(key), list) else [])
            if _text_from(article_id)
        }
        | {
            _text_from(item.get("articleId"))
            for item in lineage
            if _text_from(item.get("articleId"))
        }
    )
    note = body.note.strip() or _text_from(metadata.get("changesNote"))
    revision_context = {
        "source": "reply_revision",
        "revisionOfReplyId": reply_id,
        "revisionRequestedBy": _text_from(metadata.get("changesRequestedBy")),
        "revisionRequestedAt": _text_from(metadata.get("changesRequestedAt")),
        "revisionNote": note,
        "previousReplyBody": _clip_text(_text_from(reply.get("body")), 1200),
        "knowledgeArticleIds": knowledge_article_ids,
        "knowledgeLineage": lineage,
    }
    answer = await run_in_threadpool(
        create_issue_agent_answer,
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        author_email=auth.email,
        question=_reply_revision_question(reply, note),
        create_draft=True,
        include_feedback_link=body.include_feedback_link,
        approval_required=True,
        revision_context=revision_context,
        use_knowledge_agent=True,
        knowledge_actor_role="automation",
    )
    if not answer:
        raise HTTPException(status_code=404, detail="Issue not found")
    return _agent_answer_response_for_actor(answer, ctx=ctx, actor_email=auth.email)


@router.post("/projects/{pid}/issues/{issue_id}/agent-answer")
async def prepare_issue_agent_answer(
    issue_id: str,
    body: IssueAgentAnswerCreate,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    answer = await run_in_threadpool(
        create_issue_agent_answer,
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        author_email=auth.email,
        question=body.question,
        create_draft=body.create_draft,
        include_feedback_link=body.include_feedback_link,
        approval_required=body.approval_required,
        auto_send=body.auto_send,
        use_knowledge_agent=True,
        knowledge_actor_role="automation",
    )
    if not answer:
        raise HTTPException(status_code=404, detail="Issue not found")
    return _agent_answer_response_for_actor(answer, ctx=ctx, actor_email=auth.email)


@router.post("/projects/{pid}/issues/{issue_id}/agent-chat")
async def create_issue_agent_chat(
    issue_id: str,
    body: IssueAgentAnswerCreate,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    answer = await run_in_threadpool(
        create_issue_agent_chat_message,
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        author_email=auth.email,
        question=body.question,
        create_draft=body.create_draft,
        include_feedback_link=body.include_feedback_link,
        approval_required=body.approval_required,
        auto_send=body.auto_send,
        knowledge_actor_role="automation",
    )
    if not answer:
        raise HTTPException(status_code=404, detail="Issue not found")
    return _agent_answer_response_for_actor(answer, ctx=ctx, actor_email=auth.email)


@router.post("/projects/{pid}/issues/{issue_id}/agent-fields")
async def prepare_issue_agent_fields(
    issue_id: str,
    body: IssueCustomFieldPrepare,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    try:
        result = prepare_issue_custom_fields(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            author_email=auth.email,
            approval_required=body.approval_required,
            only_missing=body.only_missing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Issue not found")
    return result


@router.post("/projects/{pid}/issues/{issue_id}/agent-triage")
async def prepare_issue_agent_triage(
    issue_id: str,
    body: IssueTriagePrepare,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    try:
        result = prepare_issue_triage(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            author_email=auth.email,
            approval_required=body.approval_required,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Issue not found")
    return result


@router.post("/projects/{pid}/issues/{issue_id}/actions")
async def add_issue_action_execution(
    issue_id: str,
    body: IssueActionExecutionCreate,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    try:
        execution = create_issue_action_execution(
            issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            requested_by=auth.email,
            action_key=body.action_key,
            label=body.label,
            action_type=body.type,
            status=body.status,
            result=body.result,
            error=body.error,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not execution:
        raise HTTPException(status_code=404, detail="Issue not found")
    return execution


@router.post("/projects/{pid}/issues/{issue_id}/actions/{execution_id}/approve")
async def approve_issue_action(
    issue_id: str,
    execution_id: str,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    try:
        result = approve_issue_action_execution(
            issue_id,
            execution_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            approved_by=auth.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Action not found")
    return result


@router.post("/projects/{pid}/issues/{issue_id}/actions/{execution_id}/reject")
async def reject_issue_action(
    issue_id: str,
    execution_id: str,
    body: IssueActionExecutionReject,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    try:
        result = reject_issue_action_execution(
            issue_id,
            execution_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            rejected_by=auth.email,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Action not found")
    return result


@router.post("/projects/{pid}/issues/{issue_id}/portal-sessions")
async def create_issue_portal_session(
    issue_id: str,
    body: IssuePortalSessionCreate,
    request: Request,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    session = create_customer_portal_session(
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        created_by=auth.email,
        expires_hours=max(1, min(body.expires_hours, 24 * 90)),
    )
    if not session:
        raise HTTPException(status_code=404, detail="Issue not found")
    token = str(session.pop("token"))
    base_url = str(request.base_url).rstrip("/")
    return {
        **session,
        "url": f"{base_url}/support/portal/{token}",
        "apiUrl": f"{base_url}/api/support/portal/{token}",
    }
