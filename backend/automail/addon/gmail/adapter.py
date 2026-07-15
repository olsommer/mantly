from __future__ import annotations

import base64
import re
from email.utils import parseaddr
from typing import Any, Iterable

from automail.models import Email


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in payload.get("headers", [])
        if isinstance(item, dict) and item.get("name")
    }


def _decode_base64url(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")


def _walk_parts(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield payload
    for part in payload.get("parts", []) or []:
        if isinstance(part, dict):
            yield from _walk_parts(part)


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</p\s*>", "\n\n", value)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _extract_body(payload: dict[str, Any], snippet: str = "") -> tuple[str, str | None]:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in _walk_parts(payload):
        body_value = part.get("body")
        body: dict[str, Any] = body_value if isinstance(body_value, dict) else {}
        data = body.get("data")
        if not data:
            continue

        mime_type = str(part.get("mimeType") or "").lower()
        decoded = _decode_base64url(str(data))
        if mime_type == "text/plain":
            plain_parts.append(decoded)
        elif mime_type == "text/html":
            html_parts.append(decoded)

    body_html = "\n".join(html_parts).strip() or None
    body_text = "\n".join(plain_parts).strip()
    if not body_text and body_html:
        body_text = _html_to_text(body_html)
    if not body_text:
        body_text = snippet

    return body_text, body_html


def gmail_message_to_email(message: dict[str, Any]) -> Email:
    payload_value = message.get("payload")
    payload: dict[str, Any] = payload_value if isinstance(payload_value, dict) else {}
    headers = _headers(payload)
    subject = headers.get("subject") or "(No subject)"
    from_header = headers.get("from") or ""
    _, from_address = parseaddr(from_header)
    body, body_html = _extract_body(payload, snippet=str(message.get("snippet") or ""))
    references = [
        item.strip("<> ")
        for item in (headers.get("references") or "").split()
        if item.strip("<> ")
    ]

    return Email(
        id=f"gmail:{message.get('id') or 'current-message'}",
        thread_id=f"gmail:{message.get('threadId')}" if message.get("threadId") else None,
        message_id=f"gmail:{message.get('id')}" if message.get("id") else None,
        internet_message_id=(headers.get("message-id") or "").strip("<> ") or None,
        in_reply_to=(headers.get("in-reply-to") or "").strip("<> ") or None,
        references=references,
        subject=subject,
        from_address=from_address or from_header,
        body=body,
        body_html=body_html,
        attachments=[],
    )
