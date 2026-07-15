"""Ticket triage suggestions."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_SYSTEM_PROMPT = (_PROMPTS_DIR / "issue_triage_system_prompt.md").read_text(encoding="utf-8").strip()
_USER_TEMPLATE = (_PROMPTS_DIR / "issue_triage_user_prompt.md").read_text(encoding="utf-8").strip()

_PRIORITIES = {"urgent", "high", "normal", "low"}
_STATUSES = {"open", "ongoing"}


@dataclass(frozen=True)
class IssueTriageSuggestion:
    priority: str
    status: str
    assignee_email: str
    queue_key: str
    queue_name: str
    tags: list[str]
    confidence: str
    generation_mode: str
    rationale: str = ""
    error: str = ""


def _string_from(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _json_object_from_text(value: str) -> dict[str, Any]:
    clean = value.strip()
    if clean.startswith("```"):
        clean = clean.strip("`").strip()
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(clean[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_confidence(value: Any, *, has_signal: bool) -> str:
    clean = _string_from(value).lower()
    if clean in {"high", "medium", "low"}:
        return clean
    return "medium" if has_signal else "low"


def _message_context(messages: list[dict[str, Any]], limit: int = 8) -> list[dict[str, str]]:
    context: list[dict[str, str]] = []
    for message in messages[-limit:]:
        body = _string_from(message.get("body"))
        if not body:
            content = message.get("content")
            if isinstance(content, str):
                body = content.strip()
            elif isinstance(content, dict):
                body = _string_from(content.get("emailBody") or content.get("email_body") or content.get("responseText"))
        if not body:
            continue
        context.append(
            {
                "direction": _string_from(message.get("direction") or message.get("user") or message.get("role")),
                "sender": _string_from(message.get("sender") or message.get("from") or message.get("authorEmail")),
                "body": body[:2000],
                "occurredAt": _string_from(message.get("occurredAt") or message.get("created")),
            }
        )
    return context


def _ticket_context(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _string_from(issue.get("id")),
        "subject": _string_from(issue.get("subject")),
        "status": _string_from(issue.get("status") or issue.get("workflowStatus")),
        "priority": _string_from(issue.get("priority")),
        "assigneeEmail": _string_from(issue.get("assigneeEmail") or issue.get("assignee_email")),
        "queueKey": _string_from(issue.get("queueKey") or issue.get("queue_key")),
        "queueName": _string_from(issue.get("queueName") or issue.get("queue_name")),
        "tags": issue.get("tags") if isinstance(issue.get("tags"), list) else [],
        "channel": _string_from(issue.get("channel")),
        "account": _string_from(issue.get("accountName") or issue.get("accountDomain")),
        "contact": _string_from(issue.get("contactEmail") or issue.get("fromAddress")),
        "summary": _string_from(issue.get("aiSummary")),
        "runbook": _string_from(issue.get("activatedIntent") or issue.get("activated_intent")),
    }


def _queue_context(queues: list[dict[str, Any]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for queue in queues:
        key = _string_from(queue.get("queueKey") or queue.get("queue_key") or queue.get("key"))
        name = _string_from(queue.get("name") or queue.get("queueName") or queue.get("queue_name"))
        if not key and not name:
            continue
        items.append(
            {
                "queueKey": key,
                "queueName": name,
                "defaultAssigneeEmail": _string_from(
                    queue.get("defaultAssigneeEmail") or queue.get("default_assignee_email")
                ),
                "description": _string_from(queue.get("description")),
            }
        )
    return items


def _assignee_context(candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for candidate in candidates:
        email = _clean_email(candidate.get("email") or candidate.get("assigneeEmail") or candidate.get("assignee_email"))
        if not email:
            continue
        items.append(
            {
                "email": email,
                "name": _string_from(candidate.get("name")),
                "source": _string_from(candidate.get("source")),
            }
        )
    return items


def _combined_text(issue: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    parts = [
        _string_from(issue.get("subject")),
        _string_from(issue.get("aiSummary")),
        _string_from(issue.get("accountName")),
        _string_from(issue.get("accountDomain")),
        _string_from(issue.get("contactEmail")),
    ]
    for tag in issue.get("tags") if isinstance(issue.get("tags"), list) else []:
        parts.append(_string_from(tag))
    for message in messages[-8:]:
        parts.append(_string_from(message.get("body")))
    return "\n".join(part for part in parts if part)


def _clean_email(value: Any) -> str:
    clean = _string_from(value).lower()
    if not clean or "@" not in clean or clean.startswith("automation"):
        return ""
    return clean[:254]


def _clean_priority(value: Any) -> str:
    clean = _string_from(value).lower()
    return clean if clean in _PRIORITIES else ""


def _clean_status(value: Any, *, assignee_email: str) -> str:
    clean = _string_from(value).lower()
    if clean not in _STATUSES:
        return ""
    if clean == "ongoing" and not assignee_email:
        return "open"
    return clean


def _clean_tags(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else []
    seen: set[str] = set()
    tags: list[str] = []
    for item in raw_items:
        clean = re.sub(r"[^a-z0-9_-]+", "-", _string_from(item).lower()).strip("-_")
        if not clean or clean in seen:
            continue
        seen.add(clean)
        tags.append(clean[:40])
    return tags[:8]


def _queue_by_key_or_name(queues: list[dict[str, Any]], key_or_name: str) -> dict[str, Any] | None:
    clean = key_or_name.strip().lower()
    if not clean:
        return None
    for queue in queues:
        queue_key = _string_from(queue.get("queueKey") or queue.get("queue_key") or queue.get("key")).lower()
        queue_name = _string_from(queue.get("name") or queue.get("queueName") or queue.get("queue_name")).lower()
        if clean in {queue_key, queue_name}:
            return queue
    return None


def _first_queue(queues: list[dict[str, Any]]) -> dict[str, Any] | None:
    return queues[0] if queues else None


def _clean_queue(
    *,
    queue_key: Any,
    queue_name: Any,
    issue: dict[str, Any],
    queues: list[dict[str, Any]],
) -> tuple[str, str]:
    queue = _queue_by_key_or_name(queues, _string_from(queue_key)) or _queue_by_key_or_name(queues, _string_from(queue_name))
    if not queue:
        existing_key = _string_from(issue.get("queueKey") or issue.get("queue_key"))
        existing_name = _string_from(issue.get("queueName") or issue.get("queue_name"))
        queue = _queue_by_key_or_name(queues, existing_key) or _queue_by_key_or_name(queues, existing_name)
    if not queue:
        queue = _first_queue(queues)
    if not queue:
        return "", ""
    return (
        _string_from(queue.get("queueKey") or queue.get("queue_key") or queue.get("key")),
        _string_from(queue.get("name") or queue.get("queueName") or queue.get("queue_name")),
    )


def _assignee_from_candidates(value: Any, candidates: list[dict[str, Any]]) -> str:
    requested = _clean_email(value)
    candidate_emails = {
        _clean_email(candidate.get("email") or candidate.get("assigneeEmail") or candidate.get("assignee_email"))
        for candidate in candidates
    }
    candidate_emails.discard("")
    if requested and (not candidate_emails or requested in candidate_emails):
        return requested
    return ""


def _fallback_priority(text: str, issue: dict[str, Any]) -> str:
    existing = _clean_priority(issue.get("priority"))
    lower = text.lower()
    if re.search(r"\b(production down|outage|sev[ -]?1|urgent|security|breach|cannot log in|can't log in|blocked)\b", lower):
        return "urgent"
    if re.search(r"\b(escalat|vip|enterprise|billing|payment|renewal|blocked|deadline)\b", lower):
        return "high"
    return existing or "normal"


def _fallback_tags(text: str, issue: dict[str, Any]) -> list[str]:
    lower = text.lower()
    tags = _clean_tags(issue.get("tags"))
    additions: list[str] = []
    if re.search(r"\b(outage|production down|incident|sev[ -]?1)\b", lower):
        additions.append("incident")
    if re.search(r"\b(billing|invoice|payment|renewal|subscription)\b", lower):
        additions.append("billing")
    if re.search(r"\b(vip|enterprise|strategic)\b", lower):
        additions.append("vip")
    if re.search(r"\b(feature request|enhancement|roadmap|would like)\b", lower):
        additions.append("feature-request")
    if re.search(r"\b(security|breach|sso|saml|scim)\b", lower):
        additions.append("security")
    return _clean_tags([*tags, *additions])


def _fallback_assignee(
    *,
    issue: dict[str, Any],
    queues: list[dict[str, Any]],
    assignee_candidates: list[dict[str, Any]],
) -> str:
    existing = _clean_email(issue.get("assigneeEmail") or issue.get("assignee_email"))
    if existing:
        return existing
    existing_queue = _queue_by_key_or_name(queues, _string_from(issue.get("queueKey") or issue.get("queue_key")))
    queue = existing_queue or _first_queue(queues)
    queue_assignee = _clean_email((queue or {}).get("defaultAssigneeEmail") or (queue or {}).get("default_assignee_email"))
    if queue_assignee:
        return queue_assignee
    for candidate in assignee_candidates:
        assignee = _clean_email(candidate.get("email") or candidate.get("assigneeEmail") or candidate.get("assignee_email"))
        if assignee:
            return assignee
    return ""


def _fallback_triage(
    *,
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
    queues: list[dict[str, Any]],
    assignee_candidates: list[dict[str, Any]],
    error: str = "",
) -> IssueTriageSuggestion:
    text = _combined_text(issue, messages)
    assignee_email = _fallback_assignee(issue=issue, queues=queues, assignee_candidates=assignee_candidates)
    queue_key, queue_name = _clean_queue(queue_key="", queue_name="", issue=issue, queues=queues)
    priority = _fallback_priority(text, issue)
    tags = _fallback_tags(text, issue)
    has_signal = bool(assignee_email or queue_key or tags or priority != (_clean_priority(issue.get("priority")) or "normal"))
    return IssueTriageSuggestion(
        priority=priority,
        status="ongoing" if assignee_email else "open",
        assignee_email=assignee_email,
        queue_key=queue_key,
        queue_name=queue_name,
        tags=tags,
        confidence="medium" if has_signal else "low",
        generation_mode="fallback",
        rationale="Deterministic triage based on ticket text, queue defaults, and assignee candidates.",
        error=error,
    )


def _suggestion_from_parsed(
    *,
    parsed: dict[str, Any],
    fallback: IssueTriageSuggestion,
    issue: dict[str, Any],
    queues: list[dict[str, Any]],
    assignee_candidates: list[dict[str, Any]],
    generation_mode: str,
) -> IssueTriageSuggestion:
    assignee_email = _assignee_from_candidates(
        parsed.get("assigneeEmail") or parsed.get("assignee_email") or parsed.get("ownerEmail") or parsed.get("owner_email"),
        assignee_candidates,
    ) or fallback.assignee_email
    queue_key, queue_name = _clean_queue(
        queue_key=parsed.get("queueKey") or parsed.get("queue_key"),
        queue_name=parsed.get("queueName") or parsed.get("queue_name"),
        issue=issue,
        queues=queues,
    )
    tags = _clean_tags(parsed.get("tags") or parsed.get("labels")) or fallback.tags
    priority = _clean_priority(parsed.get("priority")) or fallback.priority
    status = _clean_status(parsed.get("status"), assignee_email=assignee_email) or fallback.status
    has_signal = bool(priority or status or assignee_email or queue_key or tags)
    return IssueTriageSuggestion(
        priority=priority,
        status=status,
        assignee_email=assignee_email,
        queue_key=queue_key,
        queue_name=queue_name,
        tags=tags,
        confidence=_clean_confidence(parsed.get("confidence"), has_signal=has_signal),
        generation_mode=generation_mode,
        rationale=_string_from(parsed.get("rationale") or parsed.get("summary"))[:1000],
    )


def draft_issue_triage(
    *,
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
    queues: list[dict[str, Any]],
    assignee_candidates: list[dict[str, Any]],
    tenant_id: str | None,
    project_id: str,
) -> IssueTriageSuggestion:
    """Return ticket triage suggestion, falling back offline when no LLM is configured."""
    fallback = _fallback_triage(
        issue=issue,
        messages=messages,
        queues=queues,
        assignee_candidates=assignee_candidates,
    )
    try:
        from automail.core.config import read_config
        from automail.llm import create_llm, message_content_text, resolve_effective_config
        from automail.llm.usage import llm_stage, record_usage_from_result

        config = resolve_effective_config(read_config(), tenant_id, project_id)
        llm = create_llm(config, timeout=90, max_retries=2, temperature=0)
        usage_context = getattr(llm, "_mantly_usage_context", None)
        user_prompt = _USER_TEMPLATE.format(
            ticket=_json(_ticket_context(issue)),
            messages=_json(_message_context(messages)),
            queues=_json(_queue_context(queues)),
            assignee_candidates=_json(_assignee_context(assignee_candidates)),
        )
        with llm_stage("issue_triage"):
            response = llm.invoke([("system", _SYSTEM_PROMPT), ("human", user_prompt)])
        record_usage_from_result(response, usage_context)
        parsed = _json_object_from_text(message_content_text(getattr(response, "content", response)))
        return _suggestion_from_parsed(
            parsed=parsed,
            fallback=fallback,
            issue=issue,
            queues=queues,
            assignee_candidates=assignee_candidates,
            generation_mode="llm",
        )
    except Exception as exc:
        logger.info("Issue triage LLM unavailable; using fallback", exc_info=exc)
        return _fallback_triage(
            issue=issue,
            messages=messages,
            queues=queues,
            assignee_candidates=assignee_candidates,
            error=str(exc),
        )
