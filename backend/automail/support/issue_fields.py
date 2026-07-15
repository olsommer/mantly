"""Ticket custom-field extraction."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_SYSTEM_PROMPT = (_PROMPTS_DIR / "issue_field_extraction_system_prompt.md").read_text(encoding="utf-8").strip()
_USER_TEMPLATE = (_PROMPTS_DIR / "issue_field_extraction_user_prompt.md").read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class IssueFieldExtraction:
    custom_fields: dict[str, Any]
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
        "channel": _string_from(issue.get("channel")),
        "queue": _string_from(issue.get("queueName") or issue.get("queueKey")),
        "account": _string_from(issue.get("accountName") or issue.get("accountDomain")),
        "contact": _string_from(issue.get("contactEmail") or issue.get("fromAddress")),
        "summary": _string_from(issue.get("aiSummary")),
        "runbook": _string_from(issue.get("activatedIntent") or issue.get("activated_intent")),
    }


def _field_definition_context(definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "key": _string_from(definition.get("key")),
            "label": _string_from(definition.get("label")),
            "type": _string_from(definition.get("type") or "text"),
            "required": bool(definition.get("required")),
            "options": definition.get("options") if isinstance(definition.get("options"), list) else [],
        }
        for definition in definitions
        if _string_from(definition.get("key"))
    ]


def _combined_text(issue: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    parts = [
        _string_from(issue.get("subject")),
        _string_from(issue.get("aiSummary")),
        _string_from(issue.get("accountName")),
        _string_from(issue.get("accountDomain")),
        _string_from(issue.get("contactEmail")),
    ]
    for message in messages[-8:]:
        parts.append(_string_from(message.get("body")))
    return "\n".join(part for part in parts if part)


def _field_terms(definition: dict[str, Any]) -> list[str]:
    raw = " ".join([_string_from(definition.get("key")).replace("_", " "), _string_from(definition.get("label"))])
    terms = [term.lower() for term in re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", raw)]
    return list(dict.fromkeys(terms))


def _parse_number(value: str) -> int | float | None:
    clean = value.replace(",", "")
    try:
        number = float(clean)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _fallback_field_values(
    *,
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
    field_definitions: list[dict[str, Any]],
    current_fields: dict[str, Any],
    only_missing: bool,
) -> dict[str, Any]:
    text = _combined_text(issue, messages)
    lower_text = text.lower()
    fields: dict[str, Any] = {}
    for definition in field_definitions:
        key = _string_from(definition.get("key"))
        if not key or (only_missing and key in current_fields):
            continue
        field_type = _string_from(definition.get("type") or "text")
        options = definition.get("options") if isinstance(definition.get("options"), list) else []
        if field_type == "select":
            for option in options:
                clean_option = _string_from(option)
                if clean_option and re.search(rf"(?<!\w){re.escape(clean_option.lower())}(?!\w)", lower_text):
                    fields[key] = clean_option
                    break
            continue
        if field_type == "number":
            terms = _field_terms(definition)
            for term in terms:
                near = re.search(rf"{re.escape(term)}[\s:=-]{{0,8}}([0-9][0-9,]*(?:\.\d+)?)", lower_text)
                if not near:
                    near = re.search(rf"([0-9][0-9,]*(?:\.\d+)?)\s+(?:{re.escape(term)})", lower_text)
                if near:
                    number = _parse_number(near.group(1))
                    if number is not None:
                        fields[key] = number
                        break
            continue
        if field_type == "url":
            match = re.search(r"https?://[^\s)>\"]+", text)
            if match:
                fields[key] = match.group(0).rstrip(".,")
    return fields


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


def _clean_confidence(value: Any, *, has_fields: bool) -> str:
    clean = _string_from(value).lower()
    if clean in {"high", "medium", "low"}:
        return clean
    return "medium" if has_fields else "low"


def draft_issue_field_values(
    *,
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
    field_definitions: list[dict[str, Any]],
    current_fields: dict[str, Any],
    tenant_id: str | None,
    project_id: str,
    only_missing: bool = True,
) -> IssueFieldExtraction:
    """Return ticket custom-field suggestions, falling back offline when no LLM is configured."""
    fallback_fields = _fallback_field_values(
        issue=issue,
        messages=messages,
        field_definitions=field_definitions,
        current_fields=current_fields,
        only_missing=only_missing,
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
            field_definitions=_json(_field_definition_context(field_definitions)),
            current_fields=_json(current_fields),
        )
        with llm_stage("issue_field_extraction"):
            response = llm.invoke([("system", _SYSTEM_PROMPT), ("human", user_prompt)])
        record_usage_from_result(response, usage_context)
        parsed = _json_object_from_text(message_content_text(getattr(response, "content", response)))
        raw_fields = parsed.get("customFields") or parsed.get("custom_fields") or parsed.get("fields") or {}
        custom_fields = raw_fields if isinstance(raw_fields, dict) else {}
        if only_missing:
            custom_fields = {key: value for key, value in custom_fields.items() if key not in current_fields}
        if not custom_fields:
            custom_fields = fallback_fields
        return IssueFieldExtraction(
            custom_fields=custom_fields,
            confidence=_clean_confidence(parsed.get("confidence"), has_fields=bool(custom_fields)),
            generation_mode="llm",
            rationale=_string_from(parsed.get("rationale") or parsed.get("summary"))[:1000],
        )
    except Exception as exc:
        logger.info("Falling back to deterministic ticket field extraction: %s", exc)
        return IssueFieldExtraction(
            custom_fields=fallback_fields,
            confidence="medium" if fallback_fields else "low",
            generation_mode="deterministic_fallback",
            rationale="Matched configured field options or numeric labels in the ticket text." if fallback_fields else "",
            error=str(exc),
        )
