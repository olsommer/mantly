"""PocketBase chat and usage persistence."""

import json
import logging
from typing import Any, List, Optional

from automail.core.background import enqueue_io
from automail.db.pocketbase.base import _escape_pb, _first, _list_all, _patch, _post, generate_id

logger = logging.getLogger(__name__)

def _row_to_chat(rec: dict) -> dict:
    """Map a PocketBase chats record to the shape callers expect.

    PocketBase returns JSON fields as already-parsed Python objects (httpx
    parses the outer JSON); guard against string-encoded JSON just in case.
    """
    def _parse(value: Any, expected_type: type) -> Any:
        if isinstance(value, expected_type):
            return value
        if value and isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return expected_type()

    messages = _parse(rec.get("messages"), list)
    members = _parse(rec.get("members"), list)
    identity = _parse(rec.get("identity_result"), dict) if rec.get("identity_result") else None
    intent = _parse(rec.get("intent_result"), dict) if rec.get("intent_result") else None
    phishing = _parse(rec.get("phishing_result"), dict) if rec.get("phishing_result") else None
    prompt_injection = (
        _parse(rec.get("prompt_injection_result"), dict)
        if rec.get("prompt_injection_result")
        else None
    )
    token_usage = _parse(rec.get("token_usage"), dict) if rec.get("token_usage") else None
    metadata = _parse(rec.get("metadata"), dict) if rec.get("metadata") else {}

    return {
        "record_id": rec["id"],
        # Use email_id as the logical chat ID so the external contract is
        # identical to the SQLite implementation (where id == email_id).
        "id": rec.get("email_id") or rec["id"],
        "email_id": rec.get("email_id", ""),
        "creator": rec.get("creator", ""),
        "messages": messages,
        "subject": rec.get("subject") or "",
        "from_address": rec.get("from_address") or "",
        "thread_id": rec.get("thread_id") or "",
        "message_id": rec.get("message_id") or "",
        "metadata": metadata,
        "project_id": rec.get("project") or "",
        "created_at": rec.get("created", ""),
        "status": rec.get("status", "created"),
        "members": members,
        "activated_intent": rec.get("activated_intent"),
        "requires_human": bool(rec.get("requires_human", False)),
        "identity_result": identity,
        "intent_result": intent,
        "phishing_result": phishing,
        "prompt_injection_result": prompt_injection,
        "token_usage": token_usage,
    }



# ── Public API — mirrors db.py function signatures ────────────────────────────

def get_chat(
    chat_id: str,
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Optional[dict]:
    """Return a chat record by its email_id, tenant/project-scoped when provided."""
    filter_str = f"email_id='{_escape_pb(chat_id)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    rec = _first("chats", filter_str)
    return _row_to_chat(rec) if rec else None


def store_email_analysis(
    email_id: str,
    creator: str,
    messages: list[dict[str, Any]],
    subject: str = "",
    from_address: str = "",
    activated_intent: str | None = None,
    requires_human: bool = False,
    tenant_id: Optional[str] = None,
    identity_result: dict | None = None,
    intent_result: dict | None = None,
    phishing_result: dict | None = None,
    prompt_injection_result: dict | None = None,
    token_usage: dict | None = None,
    thread_id: str = "",
    message_id: str = "",
    metadata: dict | None = None,
    project_id: Optional[str] = None,
    status: str = "analyzed",
    sync_addons: bool = True,
) -> str:
    """Store an email analysis. Returns the PocketBase record ID."""
    data: dict[str, Any] = {
        "id": generate_id(),
        "email_id": email_id,
        "creator": creator,
        "messages": messages,
        "status": status,
        "members": [],
        "subject": subject or "",
        "from_address": from_address or "",
        "thread_id": thread_id or "",
        "message_id": message_id or "",
        "metadata": metadata or {},
        "activated_intent": activated_intent,
        "requires_human": requires_human,
        "identity_result": identity_result,
        "intent_result": intent_result,
        "phishing_result": phishing_result,
        "prompt_injection_result": prompt_injection_result,
        "token_usage": token_usage,
    }
    if tenant_id:
        data["tenant"] = tenant_id
    if project_id:
        data["project"] = project_id
    rec = _post("/api/collections/chats/records", data)
    if tenant_id and sync_addons:
        try:
            from automail.billing.addons import sync_stripe_addons_best_effort
            sync_stripe_addons_best_effort(tenant_id)
        except Exception:
            logger.warning("Failed to sync Stripe email add-ons", exc_info=True)
    return rec["id"]


def upsert_email_analysis(
    email_id: str,
    creator: str,
    messages: list[dict[str, Any]],
    subject: str = "",
    from_address: str = "",
    activated_intent: str | None = None,
    requires_human: bool = False,
    tenant_id: Optional[str] = None,
    identity_result: dict | None = None,
    intent_result: dict | None = None,
    phishing_result: dict | None = None,
    prompt_injection_result: dict | None = None,
    token_usage: dict | None = None,
    thread_id: str = "",
    message_id: str = "",
    metadata: dict | None = None,
    project_id: Optional[str] = None,
    status: str = "analyzed",
) -> str:
    """Create or replace an email analysis row for a logical email_id."""
    filter_str = f"email_id='{_escape_pb(email_id)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"

    rec = _first("chats", filter_str)
    if not rec:
        return store_email_analysis(
            email_id,
            creator,
            messages,
            subject=subject,
            from_address=from_address,
            activated_intent=activated_intent,
            requires_human=requires_human,
            tenant_id=tenant_id,
            identity_result=identity_result,
            intent_result=intent_result,
            phishing_result=phishing_result,
            prompt_injection_result=prompt_injection_result,
            token_usage=token_usage,
            thread_id=thread_id,
            message_id=message_id,
            metadata=metadata,
            project_id=project_id,
            status=status,
            sync_addons=status == "analyzed",
        )

    data: dict[str, Any] = {
        "creator": creator,
        "messages": messages,
        "status": status,
        "subject": subject or "",
        "from_address": from_address or "",
        "thread_id": thread_id or "",
        "message_id": message_id or "",
        "metadata": metadata or {},
        "activated_intent": activated_intent,
        "requires_human": requires_human,
        "identity_result": identity_result,
        "intent_result": intent_result,
        "phishing_result": phishing_result,
        "prompt_injection_result": prompt_injection_result,
        "token_usage": token_usage,
    }
    _patch(f"/api/collections/chats/records/{rec['id']}", data)
    return rec["id"]


def store_llm_usage_events(
    calls: list[dict[str, Any]],
    *,
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
    chat_record_id: Optional[str] = None,
    eval_run_id: Optional[str] = None,
    run_id: str = "",
    background: bool = True,
) -> None:
    if background:
        enqueue_io(
            "llm_usage_events.store",
            store_llm_usage_events,
            list(calls),
            tenant_id=tenant_id,
            project_id=project_id,
            chat_record_id=chat_record_id,
            eval_run_id=eval_run_id,
            run_id=run_id,
            background=False,
        )
        return

    for call in calls:
        data: dict[str, Any] = {
            "id": generate_id(),
            "run_id": run_id,
            "stage": call.get("stage") or "unknown",
            "stage_execution_id": call.get("stageExecutionId") or "",
            "usage_record_id": call.get("usageRecordId") or "",
            "duration_scope": call.get("durationScope") or "",
            "provider": call.get("provider") or "",
            "model": call.get("model") or "",
            "billing_mode": call.get("billingMode") or "",
            "metadata_available": bool(call.get("metadataAvailable", False)),
            "raw_usage": call.get("rawUsage") or {},
        }
        numeric_fields = {
            "duration_ms": call.get("durationMs"),
            "usage_payload_index": call.get("usagePayloadIndex"),
            "usage_payload_count": call.get("usagePayloadCount"),
            "input_tokens": call.get("inputTokens"),
            "output_tokens": call.get("outputTokens"),
            "cached_input_tokens": call.get("cachedInputTokens"),
            "total_tokens": call.get("totalTokens"),
            "raw_cost_usd_micros": call.get("rawCostUsdMicros"),
            "billed_cost_usd_micros": call.get("billedCostUsdMicros"),
            "cost_markup": call.get("costMarkup"),
        }
        data.update({key: value for key, value in numeric_fields.items() if value is not None})
        if tenant_id:
            data["tenant"] = tenant_id
        if project_id:
            data["project"] = project_id
        if chat_record_id:
            data["chat"] = chat_record_id
        if eval_run_id:
            data["eval_run"] = eval_run_id
        rec = _post("/api/collections/llm_usage_events/records", data)
        try:
            from automail.billing.llm_metering import report_llm_usage_event_to_stripe
            report_llm_usage_event_to_stripe(tenant_id, rec)
        except Exception:
            logger.warning("Failed to enqueue Stripe LLM usage reporting", exc_info=True)


def update_chat(
    chat_id: str, messages_dict: List[dict], tenant_id: Optional[str] = None
) -> int:
    """Update a chat's messages. Returns 1 on success.

    chat_id is the email_id used as the logical identifier throughout the system.
    """
    filter_str = f"email_id='{_escape_pb(chat_id)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    rec = _first("chats", filter_str)
    if not rec:
        raise ValueError(f"Chat '{chat_id}' not found")
    _patch(f"/api/collections/chats/records/{rec['id']}", {"messages": messages_dict})
    return 1


def add_user(
    chat_id: str, user_email: str, tenant_id: Optional[str] = None
) -> bool:
    """Add a user to the chat members list. Returns True on success."""
    filter_str = f"email_id='{_escape_pb(chat_id)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    rec = _first("chats", filter_str)
    if not rec:
        return False

    members: list = rec.get("members") or []
    if isinstance(members, str):
        members = json.loads(members)

    if user_email not in members:
        members.append(user_email)
        _patch(f"/api/collections/chats/records/{rec['id']}", {"members": members})
    return True


def get_chats(user: str, tenant_id: Optional[str] = None) -> List[dict]:
    """Return all chats where the user is a member or creator."""
    filter_str = ""
    if tenant_id:
        filter_str = f"tenant='{_escape_pb(tenant_id)}'"
    records = _list_all("chats", filter_str)

    result = []
    for rec in records:
        try:
            members: list = rec.get("members") or []
            if isinstance(members, str):
                members = json.loads(members)
            creator = rec.get("creator", "")
            if user in members or creator == user:
                is_reviewed = rec.get("status") == "reviewed"
                result.append({
                    "id": rec.get("email_id") or rec["id"],
                    "subject": rec.get("subject") or "",
                    "from": rec.get("from_address") or "",
                    "requiresHuman": bool(rec.get("requires_human")) and not is_reviewed,
                })
        except (json.JSONDecodeError, KeyError):
            continue
    return result


def mark_chat_reviewed(
    chat_id: str, tenant_id: Optional[str] = None
) -> bool:
    """Mark a chat as reviewed. Returns True if found and updated."""
    filter_str = f"email_id='{_escape_pb(chat_id)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    rec = _first("chats", filter_str)
    if not rec:
        return False
    _patch(f"/api/collections/chats/records/{rec['id']}", {"status": "reviewed"})
    return True


def get_analytics(tenant_id: Optional[str] = None) -> dict:
    """Return aggregate email processing statistics (tenant-scoped when provided).

    Fetches all records and aggregates in Python because PocketBase does not
    expose SQL GROUP BY / COUNT through its REST API.
    """
    filter_str = f"tenant='{_escape_pb(tenant_id)}'" if tenant_id else ""
    records = _list_all("chats", filter_str)

    total = len(records)
    requires_human_count = sum(1 for r in records if r.get("requires_human"))
    intent_matched_count = sum(1 for r in records if r.get("activated_intent"))

    intent_counts: dict[str, int] = {}
    for r in records:
        intent_name = r.get("activated_intent")
        if intent_name:
            intent_counts[intent_name] = intent_counts.get(intent_name, 0) + 1

    top_intents = sorted(intent_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "totalEmails": total,
        "intentMatched": intent_matched_count,
        "requiresHuman": requires_human_count,
        "topIntents": [{"intent": intent_name, "count": count} for intent_name, count in top_intents],
    }
