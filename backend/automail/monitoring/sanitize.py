"""Sanitizing helpers for monitor records."""

from __future__ import annotations

from typing import Any

TEXT_LIMIT = 4000
ERROR_LIMIT = 1000


def clip(value: Any, limit: int = TEXT_LIMIT) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def safe_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    blocked_exact = {"authorization", "cookie", "set-cookie", "api_key", "apikey", "password", "secret", "token"}
    blocked_fragments = {"auth_token", "access_token", "refresh_token", "id_token", "api-key", "apikey"}
    out: dict[str, Any] = {}
    for key, item in value.items():
        key_str = str(key)
        key_lower = key_str.lower()
        if key_lower in blocked_exact or any(part in key_lower for part in blocked_fragments):
            out[key_str] = "[redacted]"
        elif isinstance(item, str):
            out[key_str] = clip(item)
        elif isinstance(item, (int, float, bool)) or item is None:
            out[key_str] = item
        elif isinstance(item, list):
            out[key_str] = item[:20]
        elif isinstance(item, dict):
            out[key_str] = safe_dict(item)
        else:
            out[key_str] = clip(item)
    return out
