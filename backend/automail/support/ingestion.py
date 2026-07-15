"""Inbound support channel ingestion adapters."""

from __future__ import annotations

import base64
import imaplib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import parseaddr
from typing import Any

from automail.api.process import process_email_for_context
from automail.core.auth import TokenPayload
from automail.db.pocketbase.client import (
    get_channel,
    get_channel_by_key,
    get_channel_cursor,
    get_issue_by_chat_id,
    list_channels,
    list_syncable_channels,
    record_channel_sync_run,
    upsert_channel_cursor,
)
from automail.models import Email, ProcessEmailRequest


@dataclass(frozen=True)
class IncomingSupportMessage:
    id: str
    subject: str
    from_address: str
    body: str
    cursor_value: str = ""
    body_html: str = ""
    thread_id: str = ""
    message_id: str = ""
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)


def _string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _adapter_kind(config: dict[str, Any]) -> str:
    return (_string(config.get("adapter") or config.get("mode") or config.get("source")) or "buffer").lower()


def _explicit_adapter_kind(config: dict[str, Any]) -> str:
    return _string(config.get("adapter") or config.get("mode") or config.get("source")).lower()


def _config_bool(config: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        if key not in config:
            continue
        value = config.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            clean = value.strip().lower()
            if clean in {"1", "true", "yes", "on"}:
                return True
            if clean in {"0", "false", "no", "off"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
    return None


def _has_buffer_messages(config: dict[str, Any]) -> bool:
    return isinstance(config.get("inboundMessages"), list) or isinstance(config.get("messages"), list)


def _channel_sync_enabled(channel: dict[str, Any]) -> bool:
    status = (_string(channel.get("status")) or "active").lower()
    if status != "active":
        return False
    channel_type = _string(channel.get("type")).lower()
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    sync_enabled = _config_bool(
        config,
        "syncEnabled",
        "sync_enabled",
        "inboundSyncEnabled",
        "inbound_sync_enabled",
        "pollingEnabled",
        "polling_enabled",
    )
    if sync_enabled is False:
        return False
    explicit_adapter = _explicit_adapter_kind(config)
    adapter = explicit_adapter or ("buffer" if channel_type == "email" else "")
    if sync_enabled is True and (adapter in {"", "buffer", "imap"}):
        return True
    if adapter in {"buffer", "imap"} and (channel_type == "email" or explicit_adapter or _has_buffer_messages(config)):
        return True
    return False


def _cursor_key_part(value: Any, *, default: str = "default") -> str:
    clean = re.sub(r"[^a-z0-9_.:-]+", "-", _string(value).lower()).strip("-")
    return clean or default


def _channel_cursor_key(config: dict[str, Any]) -> str:
    explicit = _string(config.get("cursorKey") or config.get("cursor_key") or config.get("inboundCursorKey"))
    if explicit:
        return explicit
    adapter = _adapter_kind(config)
    if adapter == "imap":
        host = _cursor_key_part(config.get("host"), default="host")
        username = _cursor_key_part(config.get("username") or config.get("user"), default="account")
        mailbox = _cursor_key_part(config.get("mailbox") or "INBOX", default="inbox")
        return f"inbound:imap:{host}:{username}:{mailbox}"
    if adapter == "buffer":
        source = _cursor_key_part(config.get("sourceKey") or config.get("source_key") or config.get("name"), default="")
        return f"inbound:buffer:{source}" if source else "inbound:buffer"
    return f"inbound:{_cursor_key_part(adapter, default='buffer')}"


def _processed_ids(cursor: dict[str, Any] | None) -> set[str]:
    metadata = cursor.get("metadata") if cursor else {}
    if not isinstance(metadata, dict):
        return set()
    ids = metadata.get("processedIds")
    if not isinstance(ids, list):
        return set()
    return {_string(item) for item in ids if _string(item)}


def _record_to_message(record: dict[str, Any]) -> IncomingSupportMessage | None:
    message_id = _string(
        record.get("id")
        or record.get("messageId")
        or record.get("message_id")
        or record.get("MessageID")
        or record.get("Message-Id")
        or record.get("Message-ID")
        or record.get("uid")
    )
    thread_id = _string(record.get("threadId") or record.get("thread_id") or record.get("conversationId"))
    subject = _string(record.get("subject") or record.get("Subject"))
    from_address = _string(record.get("fromAddress") or record.get("from") or record.get("sender") or record.get("From"))
    body = _string(record.get("body") or record.get("text") or record.get("bodyText") or record.get("TextBody"))
    body_html = _string(record.get("bodyHtml") or record.get("html") or record.get("HtmlBody"))
    raw_references = record.get("references")
    references = [_string(item) for item in raw_references if _string(item)] if isinstance(raw_references, list) else []
    attachments = record.get("attachments")
    if not message_id or not from_address or not (body or body_html):
        return None
    return IncomingSupportMessage(
        id=message_id,
        subject=subject,
        from_address=from_address,
        body=body or body_html,
        cursor_value=message_id,
        body_html=body_html,
        thread_id=thread_id,
        message_id=_string(record.get("messageId") or record.get("message_id") or message_id),
        in_reply_to=_string(record.get("inReplyTo") or record.get("in_reply_to") or record.get("InReplyTo")),
        references=references,
        attachments=attachments if isinstance(attachments, list) else [],
    )


def _email_webhook_record(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("email", "message", "payload"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return nested
    return payload


def _buffer_messages(
    config: dict[str, Any],
    *,
    cursor: dict[str, Any] | None,
    limit: int,
) -> tuple[list[IncomingSupportMessage], int]:
    raw_messages = config.get("inboundMessages") or config.get("messages") or []
    if not isinstance(raw_messages, list):
        return [], 0
    processed = _processed_ids(cursor)
    messages: list[IncomingSupportMessage] = []
    skipped = 0
    for raw in raw_messages:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        message = _record_to_message(raw)
        if not message:
            skipped += 1
            continue
        if message.id in processed:
            skipped += 1
            continue
        messages.append(message)
        if len(messages) >= limit:
            break
    return messages, skipped


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _message_text(parsed: Any, *, html: bool = False) -> str:
    wanted_type = "text/html" if html else "text/plain"
    if parsed.is_multipart():
        for part in parsed.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() != wanted_type:
                continue
            try:
                return part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    if parsed.get_content_type() != wanted_type:
        return ""
    try:
        return parsed.get_content()
    except Exception:
        payload = parsed.get_payload(decode=True) or b""
        return payload.decode(parsed.get_content_charset() or "utf-8", errors="replace")


def _message_attachments(parsed: Any) -> list[dict[str, str]]:
    if not parsed.is_multipart():
        return []
    attachments: list[dict[str, str]] = []
    for part in parsed.walk():
        if part.is_multipart():
            continue
        if part.get_content_disposition() != "attachment":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        filename = _decode_header(part.get_filename() or "") or f"attachment-{len(attachments) + 1}"
        item = {
            "filename": filename,
            "base64": base64.b64encode(payload).decode("ascii"),
        }
        content_type = _string(part.get_content_type())
        if content_type:
            item["contentType"] = content_type
        attachments.append(item)
    return attachments


def _parse_imap_message(uid: str, raw: bytes) -> IncomingSupportMessage | None:
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    subject = _decode_header(parsed.get("Subject"))
    from_address = parseaddr(parsed.get("From") or "")[1] or _decode_header(parsed.get("From"))
    message_id = _string(parsed.get("Message-ID")).strip("<>") or f"imap:{uid}"
    in_reply_to = _string(parsed.get("In-Reply-To")).strip("<>")
    references = [
        item.strip("<> ")
        for item in _string(parsed.get("References")).split()
        if item.strip("<> ")
    ]
    thread_id = references[0] if references else in_reply_to
    body = _message_text(parsed)
    body_html = _message_text(parsed, html=True)
    if not from_address or not (body or body_html):
        return None
    return IncomingSupportMessage(
        id=message_id,
        subject=subject,
        from_address=from_address,
        body=body or body_html,
        cursor_value=uid,
        body_html=body_html,
        thread_id=thread_id,
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        attachments=_message_attachments(parsed),
    )


def _imap_password(config: dict[str, Any]) -> str:
    password = _string(config.get("password"))
    if password:
        return password
    password_env = _string(config.get("passwordEnv") or config.get("password_env"))
    return os.getenv(password_env, "").strip() if password_env else ""


def _imap_messages(
    config: dict[str, Any],
    *,
    cursor: dict[str, Any] | None,
    limit: int,
) -> tuple[list[IncomingSupportMessage], int]:
    host = _string(config.get("host"))
    username = _string(config.get("username") or config.get("user"))
    password = _imap_password(config)
    if not host or not username or not password:
        raise ValueError("IMAP host, username, and password/passwordEnv are required")
    mailbox = _string(config.get("mailbox")) or "INBOX"
    port = int(config.get("port") or 993)
    last_uid = 0
    if cursor and str(cursor.get("cursorValue", "")).isdigit():
        last_uid = int(str(cursor.get("cursorValue")))
    messages: list[IncomingSupportMessage] = []
    with imaplib.IMAP4_SSL(host, port) as client:
        client.login(username, password)
        client.select(mailbox)
        status, search_data = client.uid("SEARCH", None, f"UID {last_uid + 1}:*")
        if status != "OK":
            raise ValueError("IMAP UID search failed")
        uids = search_data[0].split() if search_data and search_data[0] else []
        for uid_bytes in uids[:limit]:
            uid = uid_bytes.decode("ascii", errors="ignore")
            status, fetch_data = client.uid("FETCH", uid, "(RFC822)")
            if status != "OK":
                continue
            raw = next((item[1] for item in fetch_data if isinstance(item, tuple)), None)
            if not isinstance(raw, bytes):
                continue
            parsed = _parse_imap_message(uid, raw)
            if parsed:
                messages.append(parsed)
    return messages, 0


def _load_messages(
    config: dict[str, Any],
    *,
    cursor: dict[str, Any] | None,
    limit: int,
) -> tuple[str, list[IncomingSupportMessage], int]:
    adapter = _adapter_kind(config)
    if adapter == "imap":
        messages, skipped = _imap_messages(config, cursor=cursor, limit=limit)
        return adapter, messages, skipped
    messages, skipped = _buffer_messages(config, cursor=cursor, limit=limit)
    return "buffer", messages, skipped


def _email_id(channel_key: str, message_id: str) -> str:
    return f"channel:{channel_key}:{message_id}"


def _record_sync_run(
    *,
    tenant_id: str | None,
    project_id: str,
    channel_id: str,
    source: str,
    result: dict[str, Any],
    started_at: str,
) -> None:
    try:
        record_channel_sync_run(
            tenant_id=tenant_id,
            project_id=project_id,
            channel_id=channel_id,
            source=source,
            result=result,
            started_at=started_at,
            completed_at=_now_iso(),
        )
    except Exception:
        pass


def _issue_resolver_result(issue: dict[str, Any] | None) -> dict[str, Any]:
    if not issue:
        return {}
    metadata = issue.get("metadata") if isinstance(issue.get("metadata"), dict) else {}
    resolver = metadata.get("resolver") if isinstance(metadata.get("resolver"), dict) else {}
    result = {
        "issueId": _string(issue.get("id")),
        "ticketCreationMode": _string(metadata.get("ticketCreationMode") or resolver.get("ticketCreationMode")),
        "sourceIssueId": _string(metadata.get("sourceIssueId") or resolver.get("sourceIssueId")),
        "sourceMessageId": _string(metadata.get("sourceMessageId") or resolver.get("sourceMessageId")),
    }
    if resolver:
        result["resolver"] = resolver
    return {key: value for key, value in result.items() if value}


def ingest_email_webhook(
    channel_key: str,
    *,
    payload: Any,
    tenant_id: str | None,
    project_id: str,
    actor_email: str = "email-webhook",
    source: str = "email-webhook",
) -> dict[str, Any]:
    """Ingest one provider-pushed email message and record launch-proof evidence."""
    started_at = _now_iso()
    channel = get_channel_by_key(channel_key, tenant_id=tenant_id, project_id=project_id)
    if not channel:
        raise ValueError("Channel not found")
    if _string(channel.get("type")).lower() != "email":
        raise ValueError("Channel is not an email channel")

    channel_id = _string(channel.get("id"))
    clean_channel_key = _string(channel.get("channelKey")) or channel_key
    record = _email_webhook_record(payload)
    message = _record_to_message(record)
    if not message:
        raise ValueError("Email webhook payload requires messageId/id, fromAddress/from, and body/text/html")

    if _string(channel.get("status")) not in {"", "active"}:
        result = {
            "channelId": channel_id,
            "channelKey": clean_channel_key,
            "adapter": "email_webhook",
            "cursorKey": "",
            "status": "skipped",
            "processed": 0,
            "failed": 0,
            "skipped": 1,
            "cursorValue": message.cursor_value or message.id,
            "items": [],
            "error": "Channel is not active",
        }
        _record_sync_run(
            tenant_id=tenant_id,
            project_id=project_id,
            channel_id=channel_id,
            source=source,
            result=result,
            started_at=started_at,
        )
        return result

    logical_email_id = _email_id(clean_channel_key, message.id)
    actor = actor_email or _string(record.get("creator") or record.get("actorEmail")) or "email-webhook"
    item: dict[str, Any] = {
        "id": message.id,
        "emailId": logical_email_id,
        "subject": message.subject,
        "status": "processed",
        "issueId": "",
    }
    try:
        process_email_for_context(
            ProcessEmailRequest(
                email=Email(
                    id=logical_email_id,
                    subject=message.subject,
                    from_address=message.from_address,
                    body=message.body,
                    body_html=message.body_html or None,
                    thread_id=message.thread_id or None,
                    message_id=message.message_id or message.id,
                    in_reply_to=message.in_reply_to or None,
                    references=message.references,
                    attachments=message.attachments,
                ),
                creator=actor,
                project_id=project_id,
            ),
            tenant_id=tenant_id,
            payload=None,
            source=f"channel:{clean_channel_key}",
            project_id_override=project_id,
            creator_override=actor,
        )
        issue = get_issue_by_chat_id(logical_email_id, tenant_id=tenant_id, project_id=project_id)
        item["issueId"] = issue.get("id", "") if issue else ""
        item.update(_issue_resolver_result(issue))
        result = {
            "channelId": channel_id,
            "channelKey": clean_channel_key,
            "adapter": "email_webhook",
            "cursorKey": "",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "skipped": 0,
            "cursorValue": message.cursor_value or message.id,
            "items": [item],
            "error": "",
        }
    except Exception as exc:
        item["status"] = "failed"
        item["error"] = str(exc)
        result = {
            "channelId": channel_id,
            "channelKey": clean_channel_key,
            "adapter": "email_webhook",
            "cursorKey": "",
            "status": "failed",
            "processed": 0,
            "failed": 1,
            "skipped": 0,
            "cursorValue": message.cursor_value or message.id,
            "items": [item],
            "error": str(exc),
        }
    _record_sync_run(
        tenant_id=tenant_id,
        project_id=project_id,
        channel_id=channel_id,
        source=source,
        result=result,
        started_at=started_at,
    )
    return result


def sync_support_channel(
    channel_id: str,
    *,
    tenant_id: str | None,
    project_id: str,
    actor_email: str,
    payload: TokenPayload | None = None,
    limit: int = 25,
    source: str = "admin",
) -> dict[str, Any]:
    started_at = _now_iso()
    channel = get_channel(channel_id, tenant_id=tenant_id, project_id=project_id)
    if not channel:
        raise ValueError("Channel not found")
    channel_key = _string(channel.get("channelKey"))
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    adapter = _adapter_kind(config)
    cursor_key = _channel_cursor_key(config)
    legacy_cursor_key = "inbound" if cursor_key != "inbound" else ""
    cursor = get_channel_cursor(channel_id, tenant_id=tenant_id, project_id=project_id, cursor_key=cursor_key)
    legacy_cursor = None
    if cursor is None and legacy_cursor_key:
        legacy_cursor = get_channel_cursor(
            channel_id,
            tenant_id=tenant_id,
            project_id=project_id,
            cursor_key=legacy_cursor_key,
        )
        cursor = legacy_cursor
    if _string(channel.get("status")) not in {"", "active"}:
        result = {
            "channelId": channel_id,
            "channelKey": channel_key,
            "adapter": adapter,
            "cursorKey": cursor_key,
            "status": "skipped",
            "processed": 0,
            "failed": 0,
            "skipped": 0,
            "cursorValue": cursor.get("cursorValue", "") if cursor else "",
            "items": [],
            "error": "Channel is not active",
        }
        _record_sync_run(
            tenant_id=tenant_id,
            project_id=project_id,
            channel_id=channel_id,
            source=source,
            result=result,
            started_at=started_at,
        )
        return result

    processed_ids = _processed_ids(cursor)
    items: list[dict[str, Any]] = []
    cursor_value = cursor.get("cursorValue", "") if cursor else ""
    skipped = 0
    error = ""
    try:
        adapter, messages, skipped = _load_messages(config, cursor=cursor, limit=max(1, min(limit, 100)))
    except Exception as exc:
        error = str(exc)
        upsert_channel_cursor(
            channel_id,
            tenant_id=tenant_id,
            project_id=project_id,
            cursor_key=cursor_key,
            cursor_value=_string(cursor_value),
            status="failed",
            last_error=error,
            metadata={
                "adapter": adapter,
                "cursorKey": cursor_key,
                "migratedFromCursorKey": legacy_cursor_key if legacy_cursor else "",
                "processedIds": sorted(processed_ids)[-500:],
            },
        )
        result = {
            "channelId": channel_id,
            "channelKey": channel_key,
            "adapter": adapter,
            "cursorKey": cursor_key,
            "status": "failed",
            "processed": 0,
            "failed": 0,
            "skipped": skipped,
            "cursorValue": _string(cursor_value),
            "items": [],
            "error": error,
        }
        _record_sync_run(
            tenant_id=tenant_id,
            project_id=project_id,
            channel_id=channel_id,
            source=source,
            result=result,
            started_at=started_at,
        )
        return result

    for message in messages:
        logical_email_id = _email_id(channel_key, message.id)
        try:
            process_email_for_context(
                ProcessEmailRequest(
                    email=Email(
                        id=logical_email_id,
                        subject=message.subject,
                        from_address=message.from_address,
                        body=message.body,
                        body_html=message.body_html or None,
                        thread_id=message.thread_id or None,
                        message_id=message.message_id or message.id,
                        in_reply_to=message.in_reply_to or None,
                        references=message.references,
                        attachments=message.attachments,
                    ),
                    creator=actor_email,
                    project_id=project_id,
                ),
                tenant_id=tenant_id,
                payload=payload,
                source=f"channel:{channel_key}",
                project_id_override=project_id,
                creator_override=actor_email,
            )
            issue = get_issue_by_chat_id(logical_email_id, tenant_id=tenant_id, project_id=project_id)
            processed_ids.add(message.id)
            cursor_value = message.cursor_value or message.id
            item = {
                "id": message.id,
                "emailId": logical_email_id,
                "subject": message.subject,
                "status": "processed",
                "issueId": issue.get("id", "") if issue else "",
            }
            item.update(_issue_resolver_result(issue))
            items.append(item)
        except Exception as exc:
            items.append(
                {
                    "id": message.id,
                    "emailId": logical_email_id,
                    "subject": message.subject,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    failed = sum(1 for item in items if item["status"] == "failed")
    processed = sum(1 for item in items if item["status"] == "processed")
    status = "failed" if failed and not processed else "partial" if failed else "success"
    if not items and not error:
        status = "idle"
    upsert_channel_cursor(
        channel_id,
        tenant_id=tenant_id,
        project_id=project_id,
        cursor_key=cursor_key,
        cursor_value=_string(cursor_value),
        status=status,
        last_error=next((item.get("error", "") for item in items if item["status"] == "failed"), ""),
        metadata={
            "adapter": adapter,
            "cursorKey": cursor_key,
            "migratedFromCursorKey": legacy_cursor_key if legacy_cursor else "",
            "processedIds": sorted(processed_ids)[-500:],
        },
    )
    result = {
        "channelId": channel_id,
        "channelKey": channel_key,
        "adapter": adapter,
        "cursorKey": cursor_key,
        "status": status,
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "cursorValue": _string(cursor_value),
        "items": items,
        "error": error,
    }
    _record_sync_run(
        tenant_id=tenant_id,
        project_id=project_id,
        channel_id=channel_id,
        source=source,
        result=result,
        started_at=started_at,
    )
    return result


def sync_support_channels(
    *,
    tenant_id: str | None,
    project_id: str,
    actor_email: str,
    payload: TokenPayload | None = None,
    limit: int = 25,
    source: str = "admin",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for channel in list_channels(tenant_id=tenant_id, project_id=project_id, limit=200):
        if not _channel_sync_enabled(channel):
            continue
        results.append(
            sync_support_channel(
                _string(channel.get("id")),
                tenant_id=tenant_id,
                project_id=project_id,
                actor_email=actor_email,
                payload=payload,
                limit=limit,
                source=source,
            )
        )
    return {
        "channels": len(results),
        "processed": sum(result["processed"] for result in results),
        "failed": sum(result["failed"] for result in results),
        "skipped": sum(result["skipped"] for result in results),
        "items": results,
    }


def sync_support_channels_for_scope(
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    actor_email: str = "support-sync",
    payload: TokenPayload | None = None,
    limit: int = 25,
    source: str = "scheduler",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for channel in list_syncable_channels(tenant_id=tenant_id, project_id=project_id, limit=500):
        if not _channel_sync_enabled(channel):
            continue
        channel_project_id = _string(channel.get("projectId") or project_id)
        if not channel_project_id:
            continue
        results.append(
            sync_support_channel(
                _string(channel.get("id")),
                tenant_id=_string(channel.get("tenantId")) or tenant_id,
                project_id=channel_project_id,
                actor_email=actor_email,
                payload=payload,
                limit=limit,
                source=source,
            )
        )
    return {
        "channels": len(results),
        "processed": sum(result["processed"] for result in results),
        "failed": sum(result["failed"] for result in results),
        "skipped": sum(result["skipped"] for result in results),
        "items": results,
    }
