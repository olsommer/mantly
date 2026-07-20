"""Conservative value-level filtering for untrusted tool evidence."""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEY_FRAGMENTS = (
    "apikey",
    "authorization",
    "credential",
    "password",
    "privatekey",
    "recoverycode",
    "secret",
    "token",
)
_CREDENTIAL_LABEL_RE = re.compile(
    r"\b(?:authorization|bearer|credentials?|passwords?|passwd|secrets?|"
    r"api[-_\s]*keys?|(?:api|access|auth(?:entication)?|refresh|session)[-_\s]*tokens?|"
    r"private[-_\s]*keys?|recovery[-_\s]*codes?|mfa|otp|pins?)\b",
    re.IGNORECASE,
)
_KNOWN_CREDENTIAL_FORMAT_RE = re.compile(
    r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----|"
    r"\bssh-(?:rsa|ed25519)\s+[A-Za-z0-9+/=]{16,}|"
    r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9_-]{8,}|"
    r"\bsk-[A-Za-z0-9_-]{8,}|"
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,})|"
    r"\bglpat-[A-Za-z0-9_-]{8,}|"
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|"
    r"\bAIza[0-9A-Za-z_-]{12,}|"
    r"\bxox[baprs]-[A-Za-z0-9-]{8,}|"
    r"\bSG\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|"
    r"\bwhsec_[A-Za-z0-9_-]{8,}|"
    r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b|"
    r"\bbasic\s+[A-Za-z0-9+/=]{8,}",
    re.IGNORECASE,
)
_CREDENTIAL_URI_RE = re.compile(
    r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@",
    re.IGNORECASE,
)


def contains_sensitive_credential(value: str) -> bool:
    """Return true for high-confidence credential labels or token formats."""

    compact = " ".join(value.split())
    return bool(
        compact
        and (
            _CREDENTIAL_LABEL_RE.search(compact)
            or _KNOWN_CREDENTIAL_FORMAT_RE.search(compact)
            or _CREDENTIAL_URI_RE.search(compact)
        )
    )


def _sensitive_key(value: str) -> bool:
    normalized = "".join(character for character in value.casefold() if character.isalnum())
    return normalized == "pin" or any(
        fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS
    )


def sanitize_tool_response_facts(value: Any) -> Any | None:
    """Drop credential-bearing scalars from current or historical tool facts."""

    if isinstance(value, dict):
        explicit_path = value.get("path")
        if isinstance(explicit_path, str) and "value" in value:
            path_segments = re.split(r"[.\[\]]+", explicit_path)
            if any(_sensitive_key(segment) for segment in path_segments if segment):
                return None
            raw_scalar = value.get("value")
            if isinstance(raw_scalar, str) and contains_sensitive_credential(raw_scalar):
                return None
        sanitized: dict[Any, Any] = {}
        for key, child in value.items():
            if isinstance(key, str) and _sensitive_key(key):
                continue
            safe_child = sanitize_tool_response_facts(child)
            if safe_child is not None:
                sanitized[key] = safe_child
        return sanitized or None
    if isinstance(value, list):
        sanitized_items = [
            safe_child
            for child in value
            if (safe_child := sanitize_tool_response_facts(child)) is not None
        ]
        return sanitized_items or None
    if isinstance(value, str) and contains_sensitive_credential(value):
        return None
    return value
