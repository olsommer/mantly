"""Pipeline input/output summaries for monitor runs."""

from __future__ import annotations

from typing import Any

from automail.monitoring.sanitize import clip, safe_dict


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    if isinstance(value, dict):
        return value
    return {}


def _tool_usage_summary(tools_used: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summarized: dict[tuple[str, str], dict[str, Any]] = {}
    for item in tools_used:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        method = str(item.get("method") or "").strip().upper()
        if not name:
            continue
        key = (name, method)
        current = summarized.setdefault(
            key,
            {"name": name, "method": method, "status": "success", "count": 0},
        )
        current["count"] += 1
        status = str(item.get("status") or "").strip()
        if status and status != "success":
            current["status"] = status
    return list(summarized.values())


def email_input_summary(email: Any) -> dict[str, Any]:
    attachments = []
    for item in getattr(email, "attachments", []) or []:
        attachments.append({
            "filename": getattr(item, "filename", ""),
            "contentType": getattr(item, "content_type", "") or getattr(item, "contentType", ""),
        })
    return {
        "emailId": getattr(email, "id", ""),
        "subject": clip(getattr(email, "subject", "")),
        "from": clip(getattr(email, "from_address", "")),
        "body": clip(getattr(email, "body", "")),
        "attachments": attachments,
    }


def pipeline_output_summary(pipeline_result: Any) -> dict[str, Any]:
    agent_response = getattr(pipeline_result, "agent_response", None)
    identity_result = getattr(pipeline_result, "identity_result", None)
    intent_result = getattr(pipeline_result, "intent_result", None)
    token_usage = getattr(pipeline_result, "token_usage", None)
    tools_used = _tool_usage_summary(getattr(pipeline_result, "tools_used", []) or [])
    return {
        "responseText": clip(getattr(agent_response, "response_text", "")),
        "requiresHuman": bool(getattr(agent_response, "requires_human", False)),
        "requiresHumanReason": clip(getattr(agent_response, "requires_human_reason", "")),
        "activatedIntent": getattr(agent_response, "activated_intent", None),
        "toolsUsed": safe_dict({"items": tools_used}).get("items", []),
        "identityResult": _model_dump(identity_result),
        "intentResult": _model_dump(intent_result),
        "phishingResult": _model_dump(getattr(pipeline_result, "phishing_result", None)),
        "promptInjectionResult": _model_dump(getattr(pipeline_result, "prompt_injection_result", None)),
        "tokenUsage": safe_dict(token_usage) if isinstance(token_usage, dict) else {},
    }


def actions_from_intent(intent_result: Any) -> list[dict[str, Any]]:
    actions = []
    for action in getattr(intent_result, "actions", []) or []:
        action_data = _model_dump(action)
        actions.append({
            "type": action_data.get("type", ""),
            "label": action_data.get("label", ""),
            "method": action_data.get("method", ""),
            "status": "available",
        })
    return actions
