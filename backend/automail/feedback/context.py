"""Build compact context for feedback learning."""

from __future__ import annotations

import json
from typing import Any

_REDACTED_KEYS = {
    "base64",
    "contentBase64",
    "content_base64",
    "rawUsage",
    "raw_usage",
    "tokenUsage",
    "token_usage",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize(item)
            for key, item in value.items()
            if key not in _REDACTED_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def feedback_message_context(chat: dict) -> tuple[str, str]:
    """Return original email plus one sanitized pipeline result payload."""

    original_email = ""
    pipeline_result: str | dict[str, Any] = ""

    for msg in chat.get("messages") or []:
        if msg.get("role") == "email" and not original_email:
            content = msg.get("content", "")
            original_email = content if isinstance(content, str) else str(content)
        if msg.get("role") == "response" and not pipeline_result:
            content = msg.get("content", {})
            if isinstance(content, dict):
                pipeline_result = _sanitize(content)
            elif isinstance(content, str):
                pipeline_result = content

    if isinstance(pipeline_result, dict):
        return original_email, json.dumps(pipeline_result, ensure_ascii=False, default=str)[:6000]
    return original_email, pipeline_result
