"""Deterministic cleanup for unsafe or incomplete generated reply sign-offs."""

from __future__ import annotations

import re
from typing import Any

_CUSTOMER_DIRECTIONS = {"customer", "email", "user", "visitor"}
_DANGLING_CLOSINGS = {
    "best regards",
    "beste grüße",
    "cordialement",
    "cordiali saluti",
    "cordially",
    "freundliche grüße",
    "kind regards",
    "mit freundlichen grüßen",
    "regards",
    "saludos cordiales",
    "sincerely",
    "thank you",
    "yours faithfully",
    "yours sincerely",
}
_TERMINAL_THANK_YOU_RE = re.compile(
    r"^thank\s+you(?:[,.\u201a\u2026\u3002\uff0c])*$",
    re.IGNORECASE,
)
_FEEDBACK_LINK_SUFFIX_RE = re.compile(
    r"^Rate this support experience:\s+https?://\S+$",
    re.IGNORECASE,
)
_SIGNER_PLACEHOLDER_RE = re.compile(
    r"""^\[\s*(?:
        (?:agent|responder|support|your)\s+name
        |
        (?:your\s+)?(?:law\s+)?(?:firm|company|organi[sz]ation)
        (?:['’]s)?(?:\s+name)?
    )\s*\]$""",
    re.IGNORECASE | re.VERBOSE,
)
_SIGNATURE_ROLE_TERMS = {
    "department",
    "desk",
    "director",
    "manager",
    "office",
    "operations",
    "service",
    "support",
    "team",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalized_line(value: str) -> str:
    return " ".join(value.split()).rstrip(" ,.!:;-—").casefold()


def _message_body(message: dict[str, Any]) -> str:
    body = _text(message.get("body"))
    if body:
        return body
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return _text(
            content.get("emailBody")
            or content.get("email_body")
            or content.get("responseText")
        )
    return ""


def _looks_like_signature_line(value: str) -> bool:
    if not value or len(value) > 80 or any(char.isdigit() for char in value):
        return False
    if any(char in value for char in "?!:"):
        return False
    words = re.findall(r"[^\W\d_]+", value, re.UNICODE)
    if not 1 <= len(words) <= 6:
        return False
    if any(word.casefold() in _SIGNATURE_ROLE_TERMS for word in words):
        return True
    return len(words) <= 4 and all(word[0].isupper() for word in words)


def _latest_customer_signature_lines(messages: list[dict[str, Any]]) -> set[str]:
    """Return the latest customer's short, blank-line-separated signature block."""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        direction = _text(
            message.get("direction") or message.get("user") or message.get("role")
        ).casefold()
        if direction not in _CUSTOMER_DIRECTIONS:
            continue
        lines = _message_body(message).rstrip().splitlines()
        blank_indices = [index for index, line in enumerate(lines) if not line.strip()]
        if not blank_indices:
            return set()
        block = [line.strip() for line in lines[blank_indices[-1] + 1:] if line.strip()]
        if not 1 <= len(block) <= 4 or any(len(line) > 80 for line in block):
            return set()
        return {
            normalized
            for line in block
            if (normalized := _normalized_line(line))
            and normalized not in _DANGLING_CLOSINGS
            and _looks_like_signature_line(line)
        }
    return set()


def clean_reply_signoff(
    answer: str,
    *,
    messages: list[dict[str, Any]] | None = None,
    signer_name: str = "",
) -> str:
    """Repair only deterministic terminal sign-off failures.

    An exact copy of the latest customer's detached signature or a signer-name
    placeholder is replaced by the configured signer when available. A closing
    without any signer is completed the same way, or removed when no authorized
    signer exists. A standalone terminal ``Thank you`` closing follows the same
    signer rule even when a feedback-link footer follows it. Other final lines
    are preserved verbatim.
    """
    lines = answer.strip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""

    feedback_suffix = ""
    if _FEEDBACK_LINK_SUFFIX_RE.fullmatch(lines[-1].strip()):
        feedback_suffix = lines.pop().strip()
        while lines and not lines[-1].strip():
            lines.pop()

    configured_signer = " ".join(signer_name.split()).strip()
    if lines and _TERMINAL_THANK_YOU_RE.fullmatch(lines[-1].strip()):
        if configured_signer:
            lines.append(configured_signer)
        else:
            lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()

    if not lines:
        return feedback_suffix

    configured_normalized = _normalized_line(configured_signer)
    customer_signatures = _latest_customer_signature_lines(messages or [])
    final_line = lines[-1].strip()
    final_normalized = _normalized_line(final_line)
    previous_is_closing = bool(
        len(lines) > 1 and _normalized_line(lines[-2]) in _DANGLING_CLOSINGS
    )
    authorized_signature = bool(
        configured_normalized
        and (
            final_normalized == configured_normalized
            or final_normalized.startswith(f"{configured_normalized} ")
        )
    )
    unsafe_signer = bool(
        _SIGNER_PLACEHOLDER_RE.fullmatch(final_line)
        or (
            final_normalized in customer_signatures
            and final_normalized != configured_normalized
        )
        or (
            previous_is_closing
            and _looks_like_signature_line(final_line)
            and not authorized_signature
        )
    )

    if unsafe_signer:
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
        if configured_signer:
            lines.append(configured_signer)

    if lines and _normalized_line(lines[-1]) in _DANGLING_CLOSINGS:
        if configured_signer:
            lines.append(configured_signer)
        else:
            lines.pop()

    while lines and not lines[-1].strip():
        lines.pop()
    cleaned = "\n".join(lines).strip()
    if feedback_suffix:
        return f"{cleaned}\n\n{feedback_suffix}" if cleaned else feedback_suffix
    return cleaned
