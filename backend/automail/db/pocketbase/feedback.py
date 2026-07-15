"""PocketBase feedback and learning persistence."""

import json
from typing import Any, List, Optional

from automail.db.pocketbase.base import _delete, _escape_pb, _first, _get, _list_all, _patch, _post, generate_id

MAX_ACTIVE_INTENT_LEARNINGS = 50


def _paged_records(path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = 1
    while True:
        data = _get(path, {**params, "page": page})
        items = data.get("items", [])
        if not isinstance(items, list):
            break
        records.extend(item for item in items if isinstance(item, dict))
        total_pages = int(data.get("totalPages") or 1)
        if page >= total_pages or len(items) < int(params.get("perPage") or 50):
            break
        page += 1
    return records


def _stage_values(value: Any) -> list[str]:
    if not value:
        return []
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = [raw]
    if not isinstance(raw, list):
        return []
    return [
        str(stage).strip()
        for stage in raw
        if str(stage).strip()
    ]


def store_feedback(
    chat_id: str,
    user_email: str,
    rating: str,
    affected_stages: list[str] | None = None,
    feedback_text: str = "",
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> str:
    """Store structured like/dislike feedback. Returns the PocketBase record ID."""
    data: dict[str, Any] = {
        "id": generate_id(),
        "chat_id": chat_id,
        "user_email": user_email,
        "rating": rating,
        "affected_stages": affected_stages or [],
        "feedback_text": feedback_text,
    }
    if tenant_id:
        data["tenant"] = tenant_id
    if project_id:
        data["project"] = project_id

    # Derive intent_name from the chat's activated_intent
    chat_filter = f"email_id='{_escape_pb(chat_id)}'"
    if tenant_id:
        chat_filter += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        chat_filter += f" && project='{_escape_pb(project_id)}'"
    chat_rec = _first("chats", chat_filter)
    if chat_rec and chat_rec.get("activated_intent"):
        data["intent_name"] = chat_rec["activated_intent"]

    rec = _post("/api/collections/feedback/records", data)
    return rec["id"]


def get_chat_project(chat_id: str, tenant_id: Optional[str] = None) -> Optional[str]:
    """Return the project ID for a chat, or None."""
    filter_str = f"email_id='{_escape_pb(chat_id)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    rec = _first("chats", filter_str)
    return rec.get("project") if rec else None


def get_feedback_for_intent(
    intent_name: str,
    stage_filter: list[str] | None = None,
    tenant_id: Optional[str] = None,
    limit: int = 10,
) -> List[str]:
    """Return recent dislike feedback texts for a given intent.

    Only returns dislikes with non-empty feedback_text.  When *stage_filter*
    is provided, records are post-filtered to those whose ``affected_stages``
    JSON array overlaps with the filter list.

    Returns a list of feedback_text strings (most-recent first).
    """
    filter_str = (
        f"rating='dislike'"
        f" && feedback_text!=''"
        f" && intent_name='{_escape_pb(intent_name)}'"
    )
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"

    # Fetch more than `limit` when post-filtering, to compensate for skipped rows
    fetch_limit = limit * 3 if stage_filter else limit
    params: dict[str, Any] = {
        "perPage": fetch_limit,
        "sort": "-created",
        "filter": filter_str,
    }
    data = _get("/api/collections/feedback/records", params)
    items: list[dict] = data.get("items", [])

    results: list[str] = []
    stage_set = set(_stage_values(stage_filter)) if stage_filter else None
    for item in items:
        if stage_set:
            affected = _stage_values(item.get("affected_stages"))
            if not stage_set.intersection(affected):
                continue
        results.append(item["feedback_text"])
        if len(results) >= limit:
            break

    return results


# ── Intent learnings (AI-generated from feedback) ─────────────────────────────


def store_intent_learning(
    intent_name: str,
    learning: str,
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
    source_feedback_id: str = "",
    affected_stages: list[str] | None = None,
) -> str:
    """Store a single AI-generated learning rule. Returns the record ID."""
    data: dict[str, Any] = {
        "id": generate_id(),
        "intent_name": intent_name,
        "learning": learning,
        "source_feedback_id": source_feedback_id,
        "affected_stages": affected_stages or [],
    }
    if tenant_id:
        data["tenant"] = tenant_id
    if project_id:
        data["project"] = project_id
    rec = _post("/api/collections/intent_learnings/records", data)
    return rec["id"]


_RESPONSE_LEARNING_STAGES = {
    "response",
    "response_text",
    "email_response",
    "answer",
}

_PROCESSING_LEARNING_STAGES = {
    "customer",
    "customer_identification",
    "identity",
    "intent",
    "intent_recognition",
    "skill",
    "action",
    "actions",
    "action_fills",
    "tool",
    "tools",
    "tool_usage",
    "workflow",
    "intent_processing",
}


def _learning_applies_to_target(affected_stages: Any, target: str | None) -> bool:
    if not target:
        return True
    if not affected_stages:
        return True
    if not isinstance(affected_stages, list):
        return True

    stages = {
        str(stage).strip().lower().replace("-", "_")
        for stage in affected_stages
        if str(stage).strip()
    }
    if not stages:
        return True
    has_response = bool(stages.intersection(_RESPONSE_LEARNING_STAGES))
    has_processing = bool(stages.intersection(_PROCESSING_LEARNING_STAGES)) or any(
        stage.startswith(("action:", "tool:"))
        for stage in stages
    )
    if not has_response and not has_processing:
        return True
    if target == "response":
        return has_response
    if target == "processing":
        return has_processing
    return True


def get_intent_learnings(
    intent_name: str,
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
    stage_filter: list[str] | None = None,
    target: str | None = None,
) -> List[str]:
    """Return learning texts for an intent (for prompt injection).

    Returns oldest-first so the prompt reads chronologically.
    Old records without stage metadata apply to both processing and response.
    """
    filter_str = f"intent_name='{_escape_pb(intent_name)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    records = _paged_records(
        "/api/collections/intent_learnings/records",
        {"perPage": 50, "sort": "created", "filter": filter_str},
    )
    from automail.db.pocketbase.learning_proposals import (
        apply_learning_proposal_evaluation_override,
    )

    items = apply_learning_proposal_evaluation_override(
        records,
        intent_name=intent_name,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    if len(items) > MAX_ACTIVE_INTENT_LEARNINGS:
        raise RuntimeError(
            f"Intent '{intent_name}' exceeds the safe active-learning limit "
            f"of {MAX_ACTIVE_INTENT_LEARNINGS}",
        )
    stage_set = set(_stage_values(stage_filter))
    learnings: list[str] = []
    for item in items:
        if stage_set and not stage_set.intersection(_stage_values(item.get("affected_stages"))):
            continue
        if not _learning_applies_to_target(item.get("affected_stages"), target):
            continue
        learnings.append(item["learning"])
    return learnings


def get_intent_learnings_records(
    intent_name: str,
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> List[dict]:
    """Return full learning records for an intent (for admin UI).

    Each dict has id, learning, source_feedback_id, created.
    """
    filter_str = f"intent_name='{_escape_pb(intent_name)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    records = _paged_records(
        "/api/collections/intent_learnings/records",
        {"perPage": 50, "sort": "-created", "filter": filter_str},
    )
    return [
        {
            "id": item["id"],
            "learning": item.get("learning", ""),
            "source_feedback_id": item.get("source_feedback_id", ""),
            "affected_stages": item.get("affected_stages") or [],
            "created": item.get("created", ""),
        }
        for item in records
    ]


def update_intent_learning(
    learning_id: str,
    learning_text: str,
    *,
    intent_name: str | None = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> bool:
    """Update one learning only when it belongs to the supplied scope."""
    filter_str = f"id='{_escape_pb(learning_id)}'"
    if intent_name:
        filter_str += f" && intent_name='{_escape_pb(intent_name)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    if not _first("intent_learnings", filter_str):
        return False
    _patch(f"/api/collections/intent_learnings/records/{learning_id}", {
        "learning": learning_text,
    })
    return True


def delete_intent_learning(
    learning_id: str,
    *,
    intent_name: str | None = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> bool:
    """Delete one learning only when it belongs to the supplied scope."""
    filter_str = f"id='{_escape_pb(learning_id)}'"
    if intent_name:
        filter_str += f" && intent_name='{_escape_pb(intent_name)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    if not _first("intent_learnings", filter_str):
        return False
    return _delete(f"/api/collections/intent_learnings/records/{learning_id}")


def delete_intent_learnings_for_feedback(
    feedback_id: str,
    *,
    intent_name: str | None = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> int:
    """Remove legacy active learnings directly derived from deleted evidence."""
    filter_str = f"source_feedback_id='{_escape_pb(feedback_id)}'"
    if intent_name:
        filter_str += f" && intent_name='{_escape_pb(intent_name)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    records = _list_all("intent_learnings", filter_str)
    removed = 0
    for item in records:
        if not _delete(f"/api/collections/intent_learnings/records/{item['id']}"):
            raise RuntimeError("Failed to remove legacy intent learning")
        removed += 1
    return removed


def get_intent_feedback(
    intent_name: str,
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
    stage_filter: list[str] | None = None,
    limit: int = 20,
) -> List[dict]:
    """Return recent feedback records for an intent (for admin UI display).

    Returns dicts with rating, affected_stages, feedback_text, user_email, created.
    """
    filter_str = f"intent_name='{_escape_pb(intent_name)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    fetch_limit = limit * 3 if stage_filter else limit
    params: dict[str, Any] = {
        "perPage": fetch_limit,
        "sort": "-created",
        "filter": filter_str,
    }
    data = _get("/api/collections/feedback/records", params)
    results: List[dict] = []
    stage_set = set(_stage_values(stage_filter))
    for item in data.get("items", []):
        affected = _stage_values(item.get("affected_stages"))
        if stage_set and not stage_set.intersection(affected):
            continue
        results.append({
            "id": item["id"],
            "chat_id": item.get("chat_id", ""),
            "rating": item.get("rating", ""),
            "affected_stages": affected,
            "feedback_text": item.get("feedback_text", ""),
            "user_email": item.get("user_email", ""),
            "created": item.get("created", ""),
        })
        if len(results) >= limit:
            break
    return results


def get_feedback_record(
    feedback_id: str,
    *,
    intent_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> dict | None:
    """Return one feedback record, optionally scoped to intent/tenant/project."""
    filter_str = f"id='{_escape_pb(feedback_id)}'"
    if intent_name:
        filter_str += f" && intent_name='{_escape_pb(intent_name)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    item = _first("feedback", filter_str)
    if not item:
        return None
    affected = _stage_values(item.get("affected_stages"))
    return {
        "id": item["id"],
        "chat_id": item.get("chat_id", ""),
        "rating": item.get("rating", ""),
        "affected_stages": affected,
        "feedback_text": item.get("feedback_text", ""),
        "user_email": item.get("user_email", ""),
        "created": item.get("created", ""),
    }


def delete_feedback(
    feedback_id: str,
    *,
    intent_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> bool:
    """Delete a feedback record, optionally scoped to intent/tenant/project."""
    filter_str = f"id='{_escape_pb(feedback_id)}'"
    if intent_name:
        filter_str += f" && intent_name='{_escape_pb(intent_name)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    if not _first("feedback", filter_str):
        return False
    return _delete(f"/api/collections/feedback/records/{feedback_id}")


def delete_intent_learnings_for_intent(
    intent_name: str,
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
    stage_filter: list[str] | None = None,
) -> None:
    """Delete all generated learning records for an intent."""
    filter_str = f"intent_name='{_escape_pb(intent_name)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    stage_set = set(_stage_values(stage_filter))
    for item in _list_all("intent_learnings", filter_str):
        if stage_set:
            affected = _stage_values(item.get("affected_stages"))
            if not stage_set.intersection(affected):
                continue
        _delete(f"/api/collections/intent_learnings/records/{item['id']}")
