"""Admin support analytics endpoints."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request

from automail.api.admin import automations as automation_admin
from automail.api.admin import channels as channel_admin
from automail.api.admin import issues as issue_admin
from automail.api.admin import support_delivery as support_delivery_admin
from automail.api.admin.deps import AuthDep, ProjectEditorDep, ProjectViewerDep
from automail.db.pocketbase.client import (
    approve_issue_reply,
    create_account_insight,
    create_issue_note,
    create_issue_reply,
    create_knowledge_article,
    create_knowledge_article_from_gap,
    create_web_chat_session,
    deliver_issue_reply,
    ingest_channel_webhook,
    list_channel_webhook_events,
    list_channels,
    list_issues,
    list_knowledge_articles,
    list_knowledge_gaps,
    list_launch_proof_runs,
    record_delivery_run,
    record_launch_proof_run,
    rematch_channel_webhook_event,
    support_analytics,
    support_launch_proof,
    update_issue,
    upsert_channel,
)
from automail.support.crm import sync_support_crm_connectors
from automail.support.ingestion import ingest_email_webhook
from automail.support.scheduler import run_scheduled_support_sla_escalations

router = APIRouter()

ActionRunner = Callable[[], Awaitable[dict[str, Any]]]


def _blocked_channels(launch_proof: dict[str, Any]) -> list[dict[str, Any]]:
    channels = launch_proof.get("channels") if isinstance(launch_proof.get("channels"), dict) else {}
    items = channels.get("items") if isinstance(channels.get("items"), list) else []
    return [
        item for item in items
        if isinstance(item, dict) and bool(item.get("required")) and not bool(item.get("ready"))
    ]


def _blocker_keys(channel: dict[str, Any]) -> set[str]:
    blockers = channel.get("blockers") if isinstance(channel.get("blockers"), list) else []
    return {
        str(blocker.get("key") or "")
        for blocker in blockers
        if isinstance(blocker, dict) and str(blocker.get("key") or "")
    }


def _has_any_blocker(channels: list[dict[str, Any]], keys: set[str]) -> bool:
    return any(_blocker_keys(channel) & keys for channel in channels)


def _run_status(result: dict[str, Any]) -> str:
    if result.get("ready") is False:
        return "failed"
    status = str(result.get("status") or "").strip().lower()
    if status in {"skipped", "skip"}:
        return "skipped"
    if status in {"failed", "error"}:
        return "failed"
    if status in {"partial", "degraded"}:
        return "partial"
    failed = int(result.get("failed") or 0)
    if failed:
        return "partial"
    return "success"


async def _async_value(value: dict[str, Any]) -> dict[str, Any]:
    return value


async def _run_action(actions: list[dict[str, Any]], key: str, label: str, runner: ActionRunner) -> None:
    try:
        result = await runner()
    except Exception as exc:
        actions.append({
            "key": key,
            "label": label,
            "status": "failed",
            "error": str(exc),
            "result": {},
        })
        return
    actions.append({
        "key": key,
        "label": label,
        "status": _run_status(result),
        "error": str(result.get("error") or ""),
        "result": result,
    })


def _append_skip(actions: list[dict[str, Any]], key: str, label: str, detail: str) -> None:
    actions.append({
        "key": key,
        "label": label,
        "status": "skipped",
        "error": "",
        "result": {"detail": detail},
    })


def _session_issue_id(session: dict[str, Any]) -> str:
    issue_id = str(session.get("issueId") or "").strip()
    if issue_id:
        return issue_id
    issue = session.get("issue") if isinstance(session.get("issue"), dict) else {}
    return str(issue.get("id") or "").strip()


def _complete_launch_proof_issue(
    issue_id: str,
    *,
    tenant_id: str | None,
    project_id: str,
    workflow_source: str,
) -> dict[str, Any]:
    clean_issue_id = issue_id.strip()
    if not clean_issue_id:
        return {}
    try:
        updated = update_issue(
            clean_issue_id,
            tenant_id=tenant_id,
            project_id=project_id,
            updates={
                "status": "done",
                "workflow_source": workflow_source,
            },
        )
    except Exception as exc:
        return {
            "issueId": clean_issue_id,
            "status": "failed",
            "error": str(exc),
        }
    return {
        "issueId": clean_issue_id,
        "status": str(updated.get("status") or "done") if isinstance(updated, dict) else "done",
        "workflowSource": workflow_source,
    }


def _web_chat_launch_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    channel_key: str,
    actor_email: str,
) -> dict[str, Any]:
    session = create_web_chat_session(
        tenant_id=tenant_id,
        project_id=project_id,
        channel_key=channel_key,
        visitor_email="launch-proof@example.com",
        visitor_name="Launch Proof",
        page_url="admin://launch-proof",
        initial_message="Launch proof web chat message.",
        metadata={"source": "admin_launch_proof"},
    )
    issue_id = _session_issue_id(session)
    if not issue_id:
        raise ValueError("Web chat proof did not create a ticket")
    reviewer_email = actor_email or "support-agent@example.com"
    reply = create_issue_reply(
        issue_id,
        tenant_id=tenant_id,
        project_id=project_id,
        author_email=reviewer_email,
        body="Launch proof web chat reply.",
        status="queued",
        source="admin_launch_proof",
        metadata={
            "approvalRequired": True,
            "approved": False,
            "reviewStatus": "pending",
            "webChatSessionId": str(session.get("id") or ""),
            "smoke": "web_chat_launch_proof",
        },
    )
    if not reply:
        raise ValueError("Could not create web chat proof reply")
    reply_id = str(reply.get("id") or "").strip()
    approved = approve_issue_reply(
        issue_id,
        reply_id,
        tenant_id=tenant_id,
        project_id=project_id,
        approved_by=reviewer_email,
    )
    if not approved:
        raise ValueError("Could not approve web chat proof reply")
    delivered = deliver_issue_reply(
        issue_id,
        reply_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    if not delivered:
        raise ValueError("Could not deliver web chat proof reply")
    sent = str(delivered.get("status") or "").strip().lower() == "sent"
    cleanup = (
        _complete_launch_proof_issue(
            issue_id,
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_source="admin-web-chat-launch-proof-cleanup",
        )
        if sent
        else {}
    )
    return {
        "status": "success" if sent else "failed",
        "processed": 1,
        "sent": 1 if sent else 0,
        "failed": 0 if sent else 1,
        "session": session,
        "issueId": issue_id,
        "replyId": reply_id,
        "delivery": delivered,
        "cleanup": cleanup,
        "error": "" if sent else str(delivered.get("error") or "Web chat proof reply was not sent"),
    }


def _email_launch_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    channel_key: str,
    actor_email: str,
) -> dict[str, Any]:
    reviewer_email = actor_email.strip() or "support-agent@example.com"
    message_id = f"launch-proof-{uuid4().hex}"
    inbound = ingest_email_webhook(
        channel_key,
        tenant_id=tenant_id,
        project_id=project_id,
        actor_email="launch-proof@example.com",
        source="admin-email-launch-proof",
        payload={
            "email": {
                "messageId": message_id,
                "threadId": message_id,
                "fromAddress": "launch-proof@example.com",
                "fromName": "Launch Proof",
                "subject": "Launch proof email channel",
                "body": "Launch proof inbound email message.",
            },
            "metadata": {
                "source": "admin_launch_proof",
                "channelKey": channel_key,
            },
        },
    )
    items = inbound.get("items") if isinstance(inbound.get("items"), list) else []
    issue_id = ""
    for item in items:
        if isinstance(item, dict) and str(item.get("issueId") or "").strip():
            issue_id = str(item.get("issueId") or "").strip()
            break
    if not issue_id:
        raise ValueError("Email proof did not create a ticket")
    reply = create_issue_reply(
        issue_id,
        tenant_id=tenant_id,
        project_id=project_id,
        author_email=reviewer_email,
        body="Launch proof email reply.",
        status="queued",
        source="admin_launch_proof",
        metadata={
            "approvalRequired": True,
            "approved": False,
            "reviewStatus": "pending",
            "smoke": "email_launch_proof",
            "channelKey": channel_key,
        },
    )
    if not reply:
        raise ValueError("Could not create email proof reply")
    reply_id = str(reply.get("id") or "").strip()
    approved = approve_issue_reply(
        issue_id,
        reply_id,
        tenant_id=tenant_id,
        project_id=project_id,
        approved_by=reviewer_email,
    )
    if not approved:
        raise ValueError("Could not approve email proof reply")
    delivery_error = ""
    delivered: dict[str, Any] | None = None
    try:
        delivered = deliver_issue_reply(
            issue_id,
            reply_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
    except Exception as exc:
        delivery_error = str(exc)
    sent = str((delivered or {}).get("status") or "").strip().lower() == "sent"
    result = {
        "status": "success" if sent else "failed",
        "processed": 1,
        "sent": 1 if sent else 0,
        "failed": 0 if sent else 1,
        "blocked": 0,
        "deferred": 0,
        "retryFailed": False,
        "items": [delivered] if delivered else [],
        "error": "" if sent else delivery_error or str((delivered or {}).get("error") or "Email proof reply was not sent"),
    }
    started_at = datetime.now(timezone.utc).isoformat()
    delivery_run = record_delivery_run(
        tenant_id=tenant_id,
        project_id=project_id,
        source="admin-email-launch-proof",
        result=result,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    if not sent:
        raise ValueError(result["error"])
    cleanup = _complete_launch_proof_issue(
        issue_id,
        tenant_id=tenant_id,
        project_id=project_id,
        workflow_source="admin-email-launch-proof-cleanup",
    )
    return {
        **result,
        "inbound": inbound,
        "issueId": issue_id,
        "replyId": reply_id,
        "delivery": delivered,
        "deliveryRun": delivery_run,
        "cleanup": cleanup,
    }


def _default_web_chat_channel_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    actor_email: str,
) -> dict[str, Any]:
    owner_email = actor_email.strip().lower() or "support-agent@example.com"
    channel = upsert_channel(
        tenant_id=tenant_id,
        project_id=project_id,
        channel_key="web-chat",
        channel_type="chat",
        name="Web chat",
        status="active",
        config={
            "adapter": "web_chat",
            "ticketCreationMode": "per_message",
            "autoPrepareAgentReply": True,
            "autoPrepareAgentReplyOnUpdate": True,
            "defaultAssigneeEmail": owner_email,
            "defaultQueueKey": "support",
            "defaultQueueName": "Support",
        },
    )
    proof = _web_chat_launch_proof(
        tenant_id=tenant_id,
        project_id=project_id,
        channel_key=str(channel.get("channelKey") or "web-chat"),
        actor_email=owner_email,
    )
    return {"channel": channel, **proof}


def _channel_config_defaults_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    actor_email: str,
    blocked_channels: list[dict[str, Any]],
) -> dict[str, Any]:
    owner_email = actor_email.strip().lower() or "support-agent@example.com"
    blocked_ids = {
        str(channel.get("channelId") or "").strip()
        for channel in blocked_channels
        if str(channel.get("channelId") or "").strip()
    }
    blocked_keys = {
        str(channel.get("channelKey") or "").strip()
        for channel in blocked_channels
        if str(channel.get("channelKey") or "").strip()
    }
    channels = list_channels(
        tenant_id=tenant_id,
        project_id=project_id,
        limit=200,
    )
    items: list[dict[str, Any]] = []
    patched = 0
    for channel in channels:
        channel_id = str(channel.get("id") or "").strip()
        channel_key = str(channel.get("channelKey") or "").strip()
        if blocked_ids or blocked_keys:
            if channel_id not in blocked_ids and channel_key not in blocked_keys:
                continue
        if str(channel.get("status") or "active").strip().lower() != "active":
            continue
        config = dict(channel.get("config") if isinstance(channel.get("config"), dict) else {})
        before = dict(config)
        config["ticketCreationMode"] = "per_message"
        config["autoPrepareAgentReply"] = True
        config["autoPrepareAgentReplyOnUpdate"] = True
        if not str(config.get("defaultAssigneeEmail") or config.get("default_assignee_email") or "").strip():
            config["defaultAssigneeEmail"] = owner_email
        if not str(config.get("defaultQueueKey") or config.get("default_queue_key") or "").strip():
            config["defaultQueueKey"] = "support"
        if not str(config.get("defaultQueueName") or config.get("default_queue_name") or "").strip():
            config["defaultQueueName"] = "Support"
        changed = config != before
        if changed:
            patched += 1
            channel = upsert_channel(
                tenant_id=tenant_id,
                project_id=project_id,
                channel_key=channel_key,
                channel_type=str(channel.get("type") or "webhook"),
                name=str(channel.get("name") or channel_key or "Support channel"),
                status=str(channel.get("status") or "active"),
                config=config,
            )
        items.append({
            "channelId": channel.get("id", channel_id),
            "channelKey": channel.get("channelKey", channel_key),
            "type": channel.get("type", ""),
            "patched": changed,
            "config": {
                "ticketCreationMode": config.get("ticketCreationMode"),
                "autoPrepareAgentReply": config.get("autoPrepareAgentReply"),
                "autoPrepareAgentReplyOnUpdate": config.get("autoPrepareAgentReplyOnUpdate"),
                "defaultAssigneeEmail": config.get("defaultAssigneeEmail") or config.get("default_assignee_email") or "",
                "defaultQueueKey": config.get("defaultQueueKey") or config.get("default_queue_key") or "",
                "defaultQueueName": config.get("defaultQueueName") or config.get("default_queue_name") or "",
            },
        })
    return {
        "status": "success",
        "processed": len(items),
        "patched": patched,
        "failed": 0,
        "items": items,
    }


def _assign_unassigned_issues_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    actor_email: str,
    limit: int = 100,
) -> dict[str, Any]:
    owner_email = actor_email.strip().lower() or "support-agent@example.com"
    issues = list_issues(
        tenant_id=tenant_id,
        project_id=project_id,
        status="all",
        limit=max(1, min(limit, 200)),
    )
    items: list[dict[str, Any]] = []
    failed = 0
    assigned = 0
    for issue in issues:
        issue_id = str(issue.get("id") or "").strip()
        if not issue_id or str(issue.get("assigneeEmail") or issue.get("assignee_email") or "").strip():
            continue
        try:
            updated = update_issue(
                issue_id,
                tenant_id=tenant_id,
                project_id=project_id,
                updates={"assignee_email": owner_email, "assigned_by": owner_email},
            )
        except Exception as exc:
            failed += 1
            items.append({"issueId": issue_id, "status": "failed", "error": str(exc)})
            continue
        if not updated:
            failed += 1
            items.append({"issueId": issue_id, "status": "failed", "error": "Ticket not found"})
            continue
        assigned += 1
        items.append({
            "issueId": issue_id,
            "status": "assigned",
            "assigneeEmail": updated.get("assigneeEmail") or owner_email,
        })
    return {
        "status": "partial" if failed and assigned else "failed" if failed else "success",
        "processed": len(items),
        "assigned": assigned,
        "failed": failed,
        "items": items,
    }


def _knowledge_gap_article_drafts_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    limit: int = 10,
) -> dict[str, Any]:
    gaps = list_knowledge_gaps(
        tenant_id=tenant_id,
        project_id=project_id,
        status="open",
        limit=max(1, min(limit, 50)),
    )
    items: list[dict[str, Any]] = []
    created = 0
    failed = 0
    for gap in gaps:
        gap_id = str(gap.get("id") or "").strip()
        if not gap_id:
            continue
        try:
            article = create_knowledge_article_from_gap(
                gap_id,
                tenant_id=tenant_id,
                project_id=project_id,
                status="draft",
            )
        except Exception as exc:
            failed += 1
            items.append({
                "gapId": gap_id,
                "issueId": str(gap.get("issueId") or ""),
                "status": "failed",
                "error": str(exc),
            })
            continue
        if not article:
            failed += 1
            items.append({
                "gapId": gap_id,
                "issueId": str(gap.get("issueId") or ""),
                "status": "failed",
                "error": "Knowledge gap not found",
            })
            continue
        created += 1
        items.append({
            "gapId": gap_id,
            "issueId": str(gap.get("issueId") or ""),
            "articleId": str(article.get("id") or ""),
            "title": str(article.get("title") or gap.get("suggestedArticleTitle") or gap.get("title") or ""),
            "status": "draft_created",
            "article": article,
        })
    status = "partial" if failed and created else "failed" if failed else "success"
    return {
        "status": status,
        "processed": len(items),
        "created": created,
        "resolved": created,
        "failed": failed,
        "items": items,
    }


def _empty_knowledge_base_starter_proof(
    *,
    tenant_id: str | None,
    project_id: str,
) -> dict[str, Any]:
    existing = list_knowledge_articles(
        tenant_id=tenant_id,
        project_id=project_id,
        status="all",
        limit=1,
    )
    if existing:
        return {
            "status": "skipped",
            "detail": "Knowledge base already has an article.",
            "processed": 0,
            "created": 0,
            "failed": 0,
            "items": [],
        }

    body = """# Support response standards

Use this internal starter article as the first source for agent drafts and human review.

## When a new ticket arrives
- Confirm the customer, account, channel, priority, and assignee.
- Summarize the customer request in one or two sentences.
- Check existing product docs, past tickets, and account context before answering.

## Reply checklist
- Answer the customer question directly.
- State any action taken or the next owner and timing.
- Ask only for missing information that is required to proceed.
- Keep internal uncertainty out of customer-facing replies.

## Escalation checklist
- Escalate urgent production impact, security/privacy concerns, billing disputes, and SLA risk.
- Add an internal note with the reason for escalation and expected next step.
- Keep the ticket open or ongoing until the customer-facing next step is complete.
"""
    article = create_knowledge_article(
        tenant_id=tenant_id,
        project_id=project_id,
        title="Support response standards",
        body=body,
        status="draft",
        visibility="internal",
        tags=["starter", "support-standards"],
    )
    return {
        "status": "success",
        "processed": 1,
        "created": 1,
        "failed": 0,
        "articleId": str(article.get("id") or ""),
        "title": str(article.get("title") or "Support response standards"),
        "items": [{
            "articleId": str(article.get("id") or ""),
            "title": str(article.get("title") or "Support response standards"),
            "status": "draft_created",
            "visibility": str(article.get("visibility") or "internal"),
            "article": article,
        }],
    }


def _crm_sync_recovery_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    limit: int = 25,
) -> dict[str, Any]:
    result = sync_support_crm_connectors(
        tenant_id=tenant_id,
        project_id=project_id,
        limit=max(1, min(limit, 100)),
        source="admin-launch-proof",
    )
    connectors = int(result.get("connectors") or 0)
    failed = int(result.get("failed") or 0)
    processed = int(result.get("processed") or 0)
    if connectors == 0:
        return {
            **result,
            "status": "skipped",
            "detail": "No active CRM connectors to re-sync; review external sync evidence on the affected accounts.",
        }
    return {
        **result,
        "status": "partial" if failed and processed else "failed" if failed else "success",
    }


def _low_csat_followups_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    actor_email: str,
    limit: int = 25,
) -> dict[str, Any]:
    owner_email = actor_email.strip().lower() or "support-agent@example.com"
    issues = list_issues(
        tenant_id=tenant_id,
        project_id=project_id,
        status="low-csat",
        limit=max(1, min(limit, 100)),
    )
    items: list[dict[str, Any]] = []
    failed = 0
    updated_count = 0
    note_count = 0
    insight_count = 0
    for issue in issues:
        issue_id = str(issue.get("id") or "").strip()
        if not issue_id:
            continue
        tags = [str(tag).strip() for tag in issue.get("tags", []) if str(tag).strip()]
        tagged = "low-csat-followup" in {tag.lower() for tag in tags}
        updates: dict[str, Any] = {
            "actor_email": owner_email,
            "workflow_source": "admin-launch-proof-low-csat",
        }
        if not tagged:
            updates["tags"] = [*tags, "low-csat-followup"]
        priority = str(issue.get("priority") or "normal").strip().lower()
        if priority not in {"high", "urgent"}:
            updates["priority"] = "high"
        status = str(issue.get("status") or "").strip().lower()
        if status == "done":
            updates["status"] = "ongoing"
        if not str(issue.get("assigneeEmail") or issue.get("assignee_email") or "").strip():
            updates["assignee_email"] = owner_email
            updates["assigned_by"] = owner_email
        patch_fields = {
            key: value
            for key, value in updates.items()
            if key in {"tags", "priority", "status", "assignee_email"}
        }
        patch_updates = {
            key: value
            for key, value in updates.items()
            if key in {"tags", "priority", "status", "assignee_email", "assigned_by", "actor_email", "workflow_source"}
        }

        updated: dict[str, Any] | None = issue
        if patch_fields:
            try:
                updated = update_issue(
                    issue_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    updates=patch_updates,
                )
            except Exception as exc:
                failed += 1
                items.append({"issueId": issue_id, "status": "failed", "error": str(exc)})
                continue
            if not updated:
                failed += 1
                items.append({"issueId": issue_id, "status": "failed", "error": "Ticket not found"})
                continue
            updated_count += 1

        latest_rating = int(issue.get("latestCsatRating") or 0)
        latest_comment = str(issue.get("latestCsatComment") or "").strip()
        note: dict[str, Any] | None = None
        item_errors: list[str] = []
        if not tagged:
            note_body = "Low CSAT follow-up queued. Review customer feedback, contact the account owner, and send a recovery reply."
            if latest_rating:
                note_body += f" Latest rating: {latest_rating}/5."
            if latest_comment:
                note_body += f" Customer comment: {latest_comment}"
            try:
                note = create_issue_note(
                    issue_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    author_email=owner_email,
                    body=note_body,
                )
            except Exception as exc:
                item_errors.append(str(exc))
            else:
                if note:
                    note_count += 1

        insight: dict[str, Any] | None = None
        account_id = str(issue.get("accountId") or issue.get("account_id") or "").strip()
        if account_id:
            try:
                insight = create_account_insight(
                    account_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    insight_type="risk",
                    title="Low CSAT follow-up needed",
                    body=(
                        f"Ticket {issue_id} received low customer satisfaction feedback. "
                        "Review the ticket, recover with the customer, and update account health."
                    ),
                    severity="warning",
                    status="open",
                    source_issue_id=issue_id,
                    insight_key=f"low-csat:{issue_id}",
                    metadata={
                        "source": "admin_launch_proof",
                        "rating": latest_rating,
                        "comment": latest_comment,
                    },
                )
            except Exception as exc:
                item_errors.append(str(exc))
            else:
                if insight:
                    insight_count += 1

        if item_errors:
            failed += 1

        items.append({
            "issueId": issue_id,
            "accountId": account_id,
            "status": "partial" if item_errors else "followup_ready" if not tagged else "already_followed_up",
            "priority": updated.get("priority") or "high",
            "assigneeEmail": updated.get("assigneeEmail") or owner_email,
            "noteId": str(note.get("id") or "") if note else "",
            "insightId": str(insight.get("id") or "") if insight else "",
            "error": "; ".join(item_errors),
        })
    status = "partial" if failed and updated_count else "failed" if failed else "success"
    return {
        "status": status,
        "processed": len(items),
        "updated": updated_count,
        "notes": note_count,
        "insights": insight_count,
        "failed": failed,
        "items": items,
    }


def _due_soon_sla_watch_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    actor_email: str,
    limit: int = 25,
) -> dict[str, Any]:
    owner_email = actor_email.strip().lower() or "support-agent@example.com"
    issues = list_issues(
        tenant_id=tenant_id,
        project_id=project_id,
        status="due-soon-sla",
        limit=max(1, min(limit, 100)),
    )
    items: list[dict[str, Any]] = []
    failed = 0
    updated_count = 0
    note_count = 0
    insight_count = 0
    for issue in issues:
        issue_id = str(issue.get("id") or "").strip()
        if not issue_id:
            continue
        tags = [str(tag).strip() for tag in issue.get("tags", []) if str(tag).strip()]
        watched = "sla-due-soon-watch" in {tag.lower() for tag in tags}
        updates: dict[str, Any] = {
            "actor_email": owner_email,
            "workflow_source": "admin-launch-proof-sla-due-soon",
        }
        if not watched:
            updates["tags"] = [*tags, "sla-due-soon-watch"]
        priority = str(issue.get("priority") or "normal").strip().lower()
        if priority not in {"high", "urgent"}:
            updates["priority"] = "high"
        if not str(issue.get("assigneeEmail") or issue.get("assignee_email") or "").strip():
            updates["assignee_email"] = owner_email
            updates["assigned_by"] = owner_email
        status = str(issue.get("status") or "").strip().lower()
        if status not in {"ongoing", "done"}:
            updates["status"] = "ongoing"
            if "assignee_email" not in updates:
                updates["assignee_email"] = str(issue.get("assigneeEmail") or issue.get("assignee_email") or owner_email).strip()
        patch_fields = {
            key: value
            for key, value in updates.items()
            if key in {"tags", "priority", "status", "assignee_email"}
        }
        patch_updates = {
            key: value
            for key, value in updates.items()
            if key in {"tags", "priority", "status", "assignee_email", "assigned_by", "actor_email", "workflow_source"}
        }

        updated: dict[str, Any] | None = issue
        if patch_fields:
            try:
                updated = update_issue(
                    issue_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    updates=patch_updates,
                )
            except Exception as exc:
                failed += 1
                items.append({"issueId": issue_id, "status": "failed", "error": str(exc)})
                continue
            if not updated:
                failed += 1
                items.append({"issueId": issue_id, "status": "failed", "error": "Ticket not found"})
                continue
            updated_count += 1

        target_at = str(issue.get("nextSlaTargetAt") or "").strip()
        event_type = str(issue.get("nextSlaEventType") or "sla").strip() or "sla"
        note: dict[str, Any] | None = None
        item_errors: list[str] = []
        if not watched:
            note_body = "SLA watch queued. Review the ticket, confirm the next owner action, and respond before the due-soon target."
            if event_type:
                note_body += f" SLA event: {event_type}."
            if target_at:
                note_body += f" Target: {target_at}."
            try:
                note = create_issue_note(
                    issue_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    author_email=owner_email,
                    body=note_body,
                )
            except Exception as exc:
                item_errors.append(str(exc))
            else:
                if note:
                    note_count += 1

        insight: dict[str, Any] | None = None
        account_id = str(issue.get("accountId") or issue.get("account_id") or "").strip()
        if account_id:
            try:
                insight = create_account_insight(
                    account_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    insight_type="risk",
                    title="SLA due soon",
                    body=(
                        f"Ticket {issue_id} has an SLA target due soon. "
                        "Keep ownership clear and resolve the next customer-facing step before breach."
                    ),
                    severity="warning",
                    status="open",
                    source_issue_id=issue_id,
                    insight_key=f"sla-due-soon:{issue_id}:{event_type}",
                    metadata={
                        "source": "admin_launch_proof",
                        "eventType": event_type,
                        "targetAt": target_at,
                    },
                )
            except Exception as exc:
                item_errors.append(str(exc))
            else:
                if insight:
                    insight_count += 1

        if item_errors:
            failed += 1

        items.append({
            "issueId": issue_id,
            "accountId": account_id,
            "status": "partial" if item_errors else "watch_ready" if not watched else "already_watched",
            "priority": updated.get("priority") or "high",
            "assigneeEmail": updated.get("assigneeEmail") or owner_email,
            "nextSlaTargetAt": target_at,
            "nextSlaEventType": event_type,
            "noteId": str(note.get("id") or "") if note else "",
            "insightId": str(insight.get("id") or "") if insight else "",
            "error": "; ".join(item_errors),
        })
    status = "partial" if failed and updated_count else "failed" if failed else "success"
    return {
        "status": status,
        "processed": len(items),
        "updated": updated_count,
        "notes": note_count,
        "insights": insight_count,
        "failed": failed,
        "items": items,
    }


async def _channel_ingestion_recovery_proof(
    *,
    ctx: ProjectEditorDep,
    auth: AuthDep,
    sync_limit: int = 25,
    webhook_limit: int = 25,
) -> dict[str, Any]:
    sync_result = await channel_admin.sync_channels(ctx, auth, limit=sync_limit)
    channels = list_channels(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=200,
    )
    channel_keys = {
        str(channel.get("id") or ""): str(channel.get("channelKey") or "").strip()
        for channel in channels
        if str(channel.get("id") or "") and str(channel.get("channelKey") or "").strip()
    }
    failed_events = list_channel_webhook_events(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        status="failed",
        limit=webhook_limit,
    )
    unmatched_events = list_channel_webhook_events(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        status="unmatched",
        limit=webhook_limit,
    )
    items: list[dict[str, Any]] = []
    retried_failed = 0
    rematched = 0
    still_unmatched = 0
    failed = int(sync_result.get("failed") or 0)
    sync_status = str(sync_result.get("status") or "").strip().lower()
    if sync_status in {"failed", "error"} and failed == 0:
        failed += 1

    for event in failed_events:
        event_id = str(event.get("id") or "").strip()
        channel_id = str(event.get("channelId") or "").strip()
        channel_key = channel_keys.get(channel_id, "")
        if not event_id or not channel_key:
            failed += 1
            items.append({
                "eventId": event_id,
                "channelId": channel_id,
                "status": "failed",
                "error": "Channel key not found for failed webhook retry",
            })
            continue
        try:
            result = ingest_channel_webhook(
                channel_key,
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                payload=event.get("payload") if isinstance(event.get("payload"), dict) else {},
                source="admin-launch-proof-retry",
            )
        except Exception as exc:
            failed += 1
            items.append({
                "eventId": event_id,
                "channelKey": channel_key,
                "status": "failed",
                "error": str(exc),
            })
            continue
        result_status = str(result.get("status") or "").strip().lower()
        if result_status in {"failed", "error"} or int(result.get("failed") or 0):
            failed += 1
        elif result_status == "unmatched" or int(result.get("unmatched") or 0):
            still_unmatched += 1
        else:
            retried_failed += 1
        items.append({
            "eventId": event_id,
            "channelKey": channel_key,
            "status": result_status or "unknown",
            "result": result,
        })

    seen_unmatched_ids: set[str] = set()
    for event in unmatched_events:
        event_id = str(event.get("id") or "").strip()
        if not event_id or event_id in seen_unmatched_ids:
            continue
        seen_unmatched_ids.add(event_id)
        try:
            result = rematch_channel_webhook_event(
                event_id,
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
            )
        except Exception as exc:
            failed += 1
            items.append({"eventId": event_id, "status": "failed", "error": str(exc)})
            continue
        if not result:
            failed += 1
            items.append({"eventId": event_id, "status": "failed", "error": "Webhook event not found"})
            continue
        result_status = str(result.get("status") or "").strip().lower()
        if result_status == "processed":
            rematched += 1
        elif result_status == "unmatched":
            still_unmatched += 1
        else:
            failed += 1
        items.append({"eventId": event_id, "status": result_status or "unknown", "result": result})

    status = "success"
    if failed:
        status = "partial"
    elif still_unmatched or sync_status in {"partial", "degraded", "blocked"}:
        status = "partial"
    return {
        "status": status,
        "processed": int(sync_result.get("processed") or 0) + len(failed_events) + len(seen_unmatched_ids),
        "failed": failed,
        "sync": sync_result,
        "failedWebhookEvents": len(failed_events),
        "retriedFailedWebhookEvents": retried_failed,
        "unmatchedWebhookEvents": len(seen_unmatched_ids),
        "rematchedWebhookEvents": rematched,
        "stillUnmatchedWebhookEvents": still_unmatched,
        "items": items,
    }


@router.get("/projects/{pid}/support/analytics")
async def get_support_analytics(ctx: ProjectViewerDep) -> dict[str, Any]:
    return support_analytics(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )


@router.get("/projects/{pid}/support/launch-proof")
async def get_support_launch_proof(ctx: ProjectViewerDep) -> dict[str, Any]:
    return support_launch_proof(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )


@router.get("/projects/{pid}/support/launch-proof/runs")
async def get_support_launch_proof_runs(ctx: ProjectViewerDep, limit: int = 10) -> dict[str, Any]:
    return {
        "items": list_launch_proof_runs(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            limit=max(1, min(limit, 50)),
        )
    }


@router.post("/projects/{pid}/support/launch-proof/run")
async def run_support_launch_proof(ctx: ProjectEditorDep, request: Request, auth: AuthDep) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    launch_proof = support_launch_proof(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    blocked = _blocked_channels(launch_proof)
    email_channels = [
        channel for channel in blocked
        if str(channel.get("proofKind") or "") == "email_sync_delivery"
        or str(channel.get("type") or "").strip().lower() == "email"
    ]
    web_chat_channels = [
        channel for channel in blocked
        if str(channel.get("proofKind") or "") == "web_chat_session_delivery"
        or str(channel.get("type") or "").strip().lower() in {"chat", "web_chat"}
    ]
    external_channels = [
        channel for channel in blocked
        if str(channel.get("proofKind") or "") == "external_smoke"
        or str(channel.get("type") or "").strip().lower() not in {"email", "chat", "web_chat"}
    ]
    actions: list[dict[str, Any]] = []
    launch_blocker_keys = {
        str(item.get("key") or "")
        for item in launch_proof.get("blockers", [])
        if isinstance(item, dict)
    }
    launch_warning_keys = {
        str(item.get("key") or "")
        for item in launch_proof.get("warnings", [])
        if isinstance(item, dict)
    }
    config_default_blocker_keys = {
        "channel_ticket_mode",
        "channel_auto_prepare_disabled",
        "channel_owner_routing_missing",
    }
    config_defaults_ran = False

    if "workflow_lifecycle_proof_missing" in launch_blocker_keys:
        await _run_action(
            actions,
            "workflow_lifecycle",
            "Ticket workflow lifecycle",
            lambda: _async_value(issue_admin.run_workflow_lifecycle_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                actor_email=auth.email,
            )),
        )
    if "no_active_channels" in launch_blocker_keys:
        await _run_action(
            actions,
            "default_web_chat_channel",
            "Default web chat channel",
            lambda: _async_value(_default_web_chat_channel_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                actor_email=auth.email,
            )),
        )
    if launch_blocker_keys & config_default_blocker_keys:
        config_defaults_ran = True
        await _run_action(
            actions,
            "channel_config_defaults",
            "Channel launch config defaults",
            lambda: _async_value(_channel_config_defaults_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                actor_email=auth.email,
                blocked_channels=blocked,
            )),
        )
    if "unassigned_issues" in launch_blocker_keys:
        await _run_action(
            actions,
            "assign_unassigned_tickets",
            "Assign unassigned tickets",
            lambda: _async_value(_assign_unassigned_issues_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                actor_email=auth.email,
            )),
        )
    if "overdue_sla" in launch_blocker_keys:
        await _run_action(
            actions,
            "sla_escalations",
            "SLA escalations",
            lambda: _async_value(run_scheduled_support_sla_escalations(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                limit=100,
                source="admin-launch-proof",
            )),
        )
    if "delivery_failures" in launch_blocker_keys:
        await _run_action(
            actions,
            "support_delivery_retry_failed",
            "Retry failed support delivery",
            lambda: support_delivery_admin.run_support_delivery(ctx, limit=25, retry_failed=True),
        )
    if "channel_failures" in launch_blocker_keys:
        await _run_action(
            actions,
            "channel_ingestion_recovery",
            "Channel ingestion recovery",
            lambda: _channel_ingestion_recovery_proof(ctx=ctx, auth=auth),
        )
    if "no_human_loop_automation" in launch_blocker_keys:
        await _run_action(
            actions,
            "human_loop_automation_setup",
            "Human-loop agent automation setup",
            lambda: _async_value(automation_admin.run_human_loop_automation_setup_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                actor_email=auth.email,
            )),
        )
    elif "automation_proof_missing" in launch_blocker_keys:
        await _run_action(
            actions,
            "human_loop_automation",
            "Human-loop agent automation",
            lambda: _async_value(automation_admin.run_human_loop_automation_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                actor_email=auth.email,
            )),
        )
    if "open_knowledge_gaps" in launch_warning_keys:
        await _run_action(
            actions,
            "knowledge_gap_article_drafts",
            "Knowledge gap article drafts",
            lambda: _async_value(_knowledge_gap_article_drafts_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
            )),
        )
    if "empty_knowledge_base" in launch_warning_keys:
        await _run_action(
            actions,
            "knowledge_base_starter",
            "Knowledge base starter draft",
            lambda: _async_value(_empty_knowledge_base_starter_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
            )),
        )
    if "external_sync_failures" in launch_warning_keys:
        await _run_action(
            actions,
            "crm_sync_recovery",
            "CRM sync recovery",
            lambda: _async_value(_crm_sync_recovery_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
            )),
        )
    if "low_csat" in launch_warning_keys:
        await _run_action(
            actions,
            "low_csat_followups",
            "Low CSAT follow-ups",
            lambda: _async_value(_low_csat_followups_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                actor_email=auth.email,
            )),
        )
    if "due_soon_sla" in launch_warning_keys:
        await _run_action(
            actions,
            "sla_due_soon_watch",
            "SLA due-soon watch",
            lambda: _async_value(_due_soon_sla_watch_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                actor_email=auth.email,
            )),
        )

    manual_config_keys = {"email_auth", "live_smoke_target"} if config_defaults_ran else {
        "email_auth",
        "ticket_mode",
        "auto_prepare",
        "owner_routing",
        "live_smoke_target",
    }
    manual_channels = [
        channel for channel in blocked
        if _blocker_keys(channel) & manual_config_keys
    ]
    if manual_channels:
        _append_skip(
            actions,
            "channel_config",
            "Channel config",
            "Set ticket mode, autopilot prep, default owner routing, email inbound auth, and live provider smoke targets on blocked channels before proof can pass.",
        )
    target_ready_external_channels = [
        channel for channel in external_channels
        if "live_smoke_target" not in _blocker_keys(channel)
    ]

    for channel in external_channels:
        channel_id = str(channel.get("channelId") or "")
        if channel_id and "provider_validation" in _blocker_keys(channel):
            await _run_action(
                actions,
                f"provider_validation:{channel_id}",
                f"Validate {channel.get('name') or channel.get('channelKey') or channel_id}",
                lambda channel_id=channel_id: channel_admin.validate_channel_setup(channel_id, ctx, request),
            )

    email_lifecycle_channels = [
        channel for channel in email_channels
        if _blocker_keys(channel) & {"email_sync", "email_delivery", "channel_autopilot"}
        and "email_auth" not in _blocker_keys(channel)
    ]
    for channel in email_lifecycle_channels:
        channel_key = str(channel.get("channelKey") or "").strip()
        if not channel_key:
            _append_skip(
                actions,
                "email_lifecycle",
                "Email lifecycle proof",
                "Email channel is missing channel key.",
            )
            continue
        label = f"Email lifecycle proof {channel.get('name') or channel_key}"
        await _run_action(
            actions,
            f"email_lifecycle:{channel_key}",
            label,
            lambda channel_key=channel_key: _async_value(_email_launch_proof(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                channel_key=channel_key,
                actor_email=auth.email,
            )),
        )

    if _has_any_blocker(web_chat_channels, {"web_chat_session", "web_chat_delivery", "channel_autopilot"}):
        for channel in web_chat_channels:
            channel_key = str(channel.get("channelKey") or "web-chat").strip() or "web-chat"
            label = f"Web chat proof {channel.get('name') or channel_key}"

            async def run_web_chat(channel_key: str = channel_key) -> dict[str, Any]:
                return _web_chat_launch_proof(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    channel_key=channel_key,
                    actor_email=auth.email,
                )

            await _run_action(actions, f"web_chat_lifecycle:{channel_key}", label, run_web_chat)

    if _has_any_blocker(target_ready_external_channels, {"inbound_smoke", "channel_autopilot"}):
        await _run_action(
            actions,
            "external_inbound_smoke",
            "External inbound HTTP smoke",
            lambda: channel_admin.smoke_channels(
                channel_admin.ChannelTestMessageInput(
                    body="Launch proof external channel message.",
                    author_name="Launch Proof",
                    author_email="launch-proof@example.com",
                    transport="http",
                ),
                ctx,
                request,
                limit=25,
            ),
        )

    if _has_any_blocker(target_ready_external_channels, {"outbound_smoke"}):
        await _run_action(
            actions,
            "external_outbound_smoke",
            "External outbound smoke",
            lambda: channel_admin.smoke_channels_outbound(
                channel_admin.ChannelOutboundSmokeInput(
                    body="Launch proof support reply.",
                    to_address="launch-proof@example.com",
                    from_address=auth.email or "support-agent@example.com",
                ),
                ctx,
                request,
                limit=25,
            ),
        )

    if _has_any_blocker(target_ready_external_channels, {"lifecycle_smoke"}):
        await _run_action(
            actions,
            "external_lifecycle_smoke",
            "External lifecycle HTTP smoke",
            lambda: channel_admin.smoke_channels_lifecycle(
                channel_admin.ChannelLifecycleSmokeInput(
                    body="Launch proof lifecycle channel message.",
                    reply_body="Launch proof approved reply.",
                    author_name="Launch Proof",
                    author_email="launch-proof@example.com",
                    from_address=auth.email or "support-agent@example.com",
                    transport="http",
                ),
                ctx,
                request,
                auth,
                limit=25,
            ),
        )

    if _has_any_blocker(target_ready_external_channels, {"attachment_lifecycle_smoke"}):
        await _run_action(
            actions,
            "external_attachment_lifecycle_smoke",
            "External attachment lifecycle HTTP smoke",
            lambda: channel_admin.smoke_channels_lifecycle(
                channel_admin.ChannelLifecycleSmokeInput(
                    body="",
                    reply_body="Launch proof approved reply for attachment.",
                    author_name="Launch Proof",
                    author_email="launch-proof@example.com",
                    from_address=auth.email or "support-agent@example.com",
                    transport="http",
                    attachments=[
                        {
                            "filename": "launch-proof-attachment.txt",
                            "contentType": "text/plain",
                            "size": 42,
                        }
                    ],
                    reply_attachments=[
                        {
                            "filename": "launch-proof-reply.txt",
                            "contentType": "text/plain",
                            "base64": "b2s=",
                            "size": 2,
                        }
                    ],
                ),
                ctx,
                request,
                auth,
                limit=25,
            ),
        )

    summary = support_analytics(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    completed_at = datetime.now(timezone.utc).isoformat()
    result = {
        "actions": actions,
        "ran": sum(1 for action in actions if action.get("status") != "skipped"),
        "failed": sum(1 for action in actions if action.get("status") == "failed"),
        "skipped": sum(1 for action in actions if action.get("status") == "skipped"),
        "launchReadiness": summary.get("launchReadiness") if isinstance(summary.get("launchReadiness"), dict) else {},
        "launchProof": summary.get("launchProof") or support_launch_proof(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        ),
    }
    try:
        recorded = record_launch_proof_run(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            result=result,
            started_at=started_at,
            completed_at=completed_at,
        )
    except Exception as exc:
        return {
            **result,
            "status": str(result.get("launchReadiness", {}).get("status") or "unknown"),
            "error": str(exc),
            "startedAt": started_at,
            "completedAt": completed_at,
        }
    return {**result, **recorded}
