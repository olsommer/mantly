from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

import httpx

from automail.addon.gmail.adapter import gmail_message_to_email
from automail.addon.gmail.events import GmailAddonEvent
from automail.models import Email, EmailResponse

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"


class GmailClientError(RuntimeError):
    """Raised when Gmail API access fails."""


def _gmail_headers(event: GmailAddonEvent) -> dict[str, str]:
    event.require_oauth_token()
    headers = {"Authorization": f"Bearer {event.user_oauth_token}"}
    if event.message_access_token:
        headers["X-Goog-Gmail-Access-Token"] = event.message_access_token
    return headers


def fetch_current_message(event: GmailAddonEvent) -> dict[str, Any]:
    event.require_message_context()
    url = f"{GMAIL_API_BASE}/users/me/messages/{event.message_id}"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url, headers=_gmail_headers(event), params={"format": "full"})
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise GmailClientError(f"Gmail API returned {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise GmailClientError("Gmail API request failed") from exc
    return response.json()


def fetch_current_email(event: GmailAddonEvent) -> Email:
    return gmail_message_to_email(fetch_current_message(event))


def _reply_subject(subject: str) -> str:
    normalized = subject.strip()
    if normalized.lower().startswith("re:"):
        return normalized
    return f"Re: {normalized}" if normalized else "Re:"


def _attachment_content(item: dict[str, Any]) -> bytes | None:
    encoded = item.get("content_base64") or item.get("contentBase64") or item.get("base64")
    if not encoded:
        return None
    try:
        return base64.b64decode(str(encoded), validate=True)
    except (ValueError, TypeError):
        return None


def _draft_raw_message(email: Email, response: EmailResponse) -> str:
    message = EmailMessage()
    if email.from_address:
        message["To"] = email.from_address
    message["Subject"] = _reply_subject(email.subject)
    message.set_content(response.email_body)

    for item in response.email_attachments:
        if not isinstance(item, dict):
            continue
        content = _attachment_content(item)
        filename = str(item.get("filename") or "attachment").strip()
        content_type = str(item.get("content_type") or item.get("contentType") or "application/octet-stream")
        if not content or not filename:
            continue
        maintype, _, subtype = content_type.partition("/")
        message.add_attachment(
            content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=filename,
        )

    return base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")


def create_reply_draft(event: GmailAddonEvent, email: Email, response: EmailResponse) -> dict[str, str]:
    event.require_message_context()
    payload: dict[str, Any] = {
        "message": {
            "raw": _draft_raw_message(email, response),
        }
    }
    if event.thread_id:
        payload["message"]["threadId"] = event.thread_id

    url = f"{GMAIL_API_BASE}/users/me/drafts"
    try:
        with httpx.Client(timeout=20.0) as client:
            api_response = client.post(url, headers=_gmail_headers(event), json=payload)
        api_response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise GmailClientError(f"Gmail draft API returned {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise GmailClientError("Gmail draft API request failed") from exc

    data = api_response.json()
    message_data = data.get("message") if isinstance(data.get("message"), dict) else {}
    return {
        "id": str(data.get("id") or ""),
        "threadId": str(message_data.get("threadId") or event.thread_id),
    }
