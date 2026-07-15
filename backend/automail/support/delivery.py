"""Support channel delivery adapters."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx

DISCORD_API_BASE = "https://discord.com/api/v10"
SLACK_API_BASE = "https://slack.com/api"
TELEGRAM_API_BASE = "https://api.telegram.org"
LINE_API_BASE = "https://api.line.me"
VIBER_API_BASE = "https://chatapi.viber.com/pa"
TWILIO_API_BASE = "https://api.twilio.com"
WHATSAPP_GRAPH_API_BASE = "https://graph.facebook.com/v20.0"
MESSENGER_GRAPH_API_BASE = "https://graph.facebook.com/v20.0"
INSTAGRAM_GRAPH_API_BASE = "https://graph.facebook.com/v20.0"
X_API_BASE = "https://api.x.com"
TEAMS_TOKEN_URL = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
TEAMS_TOKEN_SCOPE = "https://api.botframework.com/.default"
SLACK_TEXT_LIMIT = 40_000
DISCORD_CONTENT_LIMIT = 2_000
TELEGRAM_TEXT_LIMIT = 4_096
LINE_TEXT_LIMIT = 5_000
VIBER_TEXT_LIMIT = 7_000
WHATSAPP_TEXT_LIMIT = 4_096
MESSENGER_TEXT_LIMIT = 2_000
INSTAGRAM_TEXT_LIMIT = 1_000
X_DM_TEXT_LIMIT = 10_000
SMS_TEXT_LIMIT = 1_600


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    provider: str
    provider_message_id: str = ""
    error: str = ""
    retry_after_seconds: int = 0
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class DeliveryAttachment:
    filename: str
    content: bytes
    content_type: str

    @property
    def size(self) -> int:
        return len(self.content)


def _smtp_config() -> dict[str, Any]:
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587") or "587"),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from": (os.getenv("SMTP_FROM", "").strip() or os.getenv("SMTP_USER", "").strip()),
    }


def send_support_email_reply(
    *,
    message_id: str,
    to_address: str,
    from_address: str,
    subject: str,
    body: str,
    attachments: list[dict[str, Any]] | None = None,
    channel_config: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    secrets: dict[str, str] | None = None,
) -> DeliveryResult:
    adapter_config = channel_config or {}
    clean_metadata = {**(metadata or {})}
    if attachments and not isinstance(clean_metadata.get("attachments"), list):
        clean_metadata["attachments"] = attachments
    if adapter_config and _resolve_webhook_url(adapter_config, secrets):
        return send_support_channel_reply(
            message_id=message_id,
            channel="email",
            channel_config=adapter_config,
            to_address=to_address,
            from_address=from_address,
            subject=subject,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )

    config = _smtp_config()
    if not config["host"]:
        return DeliveryResult(
            status="failed",
            provider="smtp",
            error="SMTP_HOST is not configured",
        )
    if not config["from"]:
        return DeliveryResult(
            status="failed",
            provider="smtp",
            error="SMTP_FROM or SMTP_USER is required",
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config["from"]
    msg["To"] = to_address
    attempt_key = _metadata_string(clean_metadata, "deliveryAttemptKey", "delivery_attempt_key") or f"support-outbound:{message_id}"
    msg["Message-ID"] = f"<{sha256(attempt_key.encode('utf-8')).hexdigest()}@mantly.delivery>"
    _, reply_to_email = parseaddr(from_address or "")
    if reply_to_email and "@" in reply_to_email and reply_to_email != config["from"]:
        msg["Reply-To"] = from_address
    msg.set_content(body)
    for attachment in attachments or []:
        filename = str(attachment.get("filename") or attachment.get("name") or "").strip()
        raw_base64 = str(attachment.get("base64") or attachment.get("contentBase64") or attachment.get("content_base64") or "").strip()
        if not filename or not raw_base64:
            continue
        try:
            payload = base64.b64decode(raw_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            return DeliveryResult(
                status="failed",
                provider="smtp",
                error=f"Invalid attachment payload for {filename}: {exc}",
            )
        content_type = str(attachment.get("contentType") or attachment.get("content_type") or "application/octet-stream").strip()
        maintype, _, subtype = content_type.partition("/")
        msg.add_attachment(
            payload,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=filename,
        )

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=30) as server:
            server.ehlo()
            server.starttls()
            if config["user"] and config["password"]:
                server.login(config["user"], config["password"])
            server.send_message(msg)
    except Exception as exc:  # pragma: no cover - exercised with monkeypatch in tests
        return DeliveryResult(
            status="failed",
            provider="smtp",
            error=str(exc),
            metadata={
                "deliveryAttemptKey": attempt_key,
                "deliveryCertainty": "uncertain",
            },
        )

    return DeliveryResult(
        status="sent",
        provider="smtp",
        provider_message_id=f"smtp:{message_id}",
    )


def _config_string(config: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = config.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _secret_value(env_name: str, secrets: dict[str, str] | None) -> str:
    clean_name = env_name.strip()
    if not clean_name:
        return ""
    if secrets is not None:
        secret_value = str(secrets.get(clean_name) or "").strip()
        if secret_value:
            return secret_value
    return os.getenv(clean_name, "").strip()


def _resolve_secret_template(template: str, secrets: dict[str, str] | None) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return _secret_value(key, secrets) or match.group(0)

    return re.sub(r"\{([^}]+)\}", replace, template)


def _resolve_webhook_url(config: dict[str, Any], secrets: dict[str, str] | None) -> str:
    env_name = _config_string(config, "outboundWebhookUrlEnv", "outbound_webhook_url_env")
    webhook_url = _config_string(config, "outboundWebhookUrl", "outbound_webhook_url")
    if env_name:
        webhook_url = _secret_value(env_name, secrets) or webhook_url
    if webhook_url:
        return webhook_url
    template = _config_string(config, "outboundWebhookUrlTemplate", "outbound_webhook_url_template")
    if not template:
        return ""
    resolved = _resolve_secret_template(template, secrets).strip()
    if "{" in resolved or "}" in resolved:
        return ""
    return resolved


def _metadata_string(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _metadata_attachments(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    raw_attachments = metadata.get("attachments")
    if not isinstance(raw_attachments, list):
        return []
    attachments: list[dict[str, Any]] = []
    for item in raw_attachments:
        if isinstance(item, dict):
            attachments.append(item)
    return attachments


def _attachment_display_name(attachment: dict[str, Any]) -> str:
    return str(
        attachment.get("filename")
        or attachment.get("fileName")
        or attachment.get("name")
        or "attachment"
    ).strip() or "attachment"


def _attachment_url(attachment: dict[str, Any]) -> str:
    return str(
        attachment.get("url")
        or attachment.get("downloadUrl")
        or attachment.get("download_url")
        or attachment.get("contentUrl")
        or attachment.get("content_url")
        or ""
    ).strip()


def _attachment_notice_from(attachments: list[dict[str, Any]]) -> str:
    if not attachments:
        return ""
    lines = ["Attachments:"]
    for attachment in attachments[:10]:
        name = _attachment_display_name(attachment)
        url = _attachment_url(attachment)
        lines.append(f"- {name}: {url}" if url else f"- {name}")
    if len(attachments) > 10:
        lines.append(f"- +{len(attachments) - 10} more")
    return "\n".join(lines)


def _attachment_notice(metadata: dict[str, Any]) -> str:
    return _attachment_notice_from(_metadata_attachments(metadata))


def _body_with_attachment_notice(
    body: str,
    metadata: dict[str, Any],
    *,
    attachments: list[dict[str, Any]] | None = None,
) -> str:
    notice = _attachment_notice_from(_metadata_attachments(metadata) if attachments is None else attachments)
    if not notice:
        return body
    clean_body = body.rstrip()
    if not clean_body:
        return notice
    if notice in clean_body:
        return clean_body
    return f"{clean_body}\n\n{notice}"


def _attachment_base64(attachment: dict[str, Any]) -> str:
    return str(
        attachment.get("base64")
        or attachment.get("contentBase64")
        or attachment.get("content_base64")
        or ""
    ).strip()


def _uploadable_attachments(metadata: dict[str, Any]) -> tuple[list[DeliveryAttachment], list[dict[str, Any]], str]:
    uploadable: list[DeliveryAttachment] = []
    skipped: list[dict[str, Any]] = []
    for attachment in _metadata_attachments(metadata):
        raw_base64 = _attachment_base64(attachment)
        if not raw_base64:
            skipped.append(attachment)
            continue
        filename = _attachment_display_name(attachment)
        try:
            content = base64.b64decode(raw_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            return [], [], f"Invalid attachment payload for {filename}: {exc}"
        content_type = str(
            attachment.get("contentType")
            or attachment.get("content_type")
            or attachment.get("mimeType")
            or attachment.get("mime_type")
            or "application/octet-stream"
        ).strip() or "application/octet-stream"
        uploadable.append(DeliveryAttachment(filename=filename, content=content, content_type=content_type))
    return uploadable, skipped, ""


def _attachment_delivery_metadata(
    *,
    provider: str,
    uploaded: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not uploaded and not skipped:
        return None
    return {
        "attachmentDelivery": {
            "provider": provider,
            "uploaded": len(uploaded),
            "skipped": len(skipped),
            "items": [
                *uploaded,
                *[
                    {
                        "filename": _attachment_display_name(item),
                        "status": "notice_only",
                        **({"url": _attachment_url(item)} if _attachment_url(item) else {}),
                    }
                    for item in skipped
                ],
            ],
        }
    }


def _multipart_file_parts(attachments: list[DeliveryAttachment]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        (f"files[{index}]", (attachment.filename, attachment.content, attachment.content_type))
        for index, attachment in enumerate(attachments)
    ]


def _discord_payload_attachments(attachments: list[DeliveryAttachment]) -> list[dict[str, Any]]:
    return [
        {"id": index, "filename": attachment.filename}
        for index, attachment in enumerate(attachments)
    ]


def _discord_uploaded_attachment_items(
    attachments: list[DeliveryAttachment],
    response_data: Any,
) -> list[dict[str, Any]]:
    response_attachments = response_data.get("attachments") if isinstance(response_data, dict) else []
    response_by_filename: dict[str, dict[str, Any]] = {}
    if isinstance(response_attachments, list):
        for item in response_attachments:
            if isinstance(item, dict):
                filename = str(item.get("filename") or "").strip()
                if filename:
                    response_by_filename[filename] = item
    uploaded: list[dict[str, Any]] = []
    for attachment in attachments:
        response_item = response_by_filename.get(attachment.filename, {})
        uploaded.append({
            "filename": attachment.filename,
            "contentType": attachment.content_type,
            "size": attachment.size,
            "status": "uploaded",
            **({"providerFileId": str(response_item.get("id"))} if response_item.get("id") else {}),
        })
    return uploaded


def _append_query(url: str, values: dict[str, str]) -> str:
    if not values:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in values.items():
        if value and key not in query:
            query[key] = value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _generic_channel_payload(
    *,
    message_id: str,
    channel: str,
    to_address: str,
    from_address: str,
    subject: str,
    body: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "messageId": message_id,
        "channel": channel,
        "toAddress": to_address,
        "fromAddress": from_address,
        "subject": subject,
        "body": body,
        "metadata": metadata,
    }
    attachments = metadata.get("attachments")
    if isinstance(attachments, list):
        payload["attachments"] = attachments
    for key in (
        "provider",
        "workspaceId",
        "channelId",
        "threadId",
        "threadTs",
        "sourceIssueId",
        "sourceMessageId",
        "providerMessageId",
        "eventId",
        "webChatSessionId",
    ):
        value = metadata.get(key)
        if value:
            payload[key] = value
    return payload


def _slack_payload(*, body: str, metadata: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"text": body}
    channel_id = _metadata_string(metadata, "channelId", "channel_id")
    thread_ts = _metadata_string(metadata, "threadTs", "thread_ts", "threadId", "thread_id", "providerMessageId")
    if channel_id:
        payload["channel"] = channel_id
    if thread_ts:
        payload["thread_ts"] = thread_ts
    return payload


def _teams_payload(*, body: str, subject: str, metadata: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"text": body}
    if subject:
        payload["title"] = subject
    thread_id = _metadata_string(metadata, "threadId", "thread_id")
    channel_id = _metadata_string(metadata, "channelId", "channel_id")
    if channel_id:
        payload["channelId"] = channel_id
    if thread_id:
        payload["threadId"] = thread_id
    return payload


def _teams_app_credential_envs(config: dict[str, Any]) -> tuple[str, str]:
    app_id_env = _config_string(config, "teamsAppIdEnv", "teams_app_id_env") or "SUPPORT_TEAMS_APP_ID"
    app_password_env = _config_string(config, "teamsAppPasswordEnv", "teams_app_password_env") or "SUPPORT_TEAMS_APP_PASSWORD"
    return app_id_env, app_password_env


def _teams_bot_transport_enabled(channel: str, config: dict[str, Any], webhook_url: str, secrets: dict[str, str] | None) -> bool:
    if channel.strip().lower() != "teams":
        return False
    transport = _outbound_transport(config)
    if transport in {"bot", "teams_bot", "bot_framework", "bot_api", "provider_api"}:
        return True
    if webhook_url:
        return False
    app_id_env, app_password_env = _teams_app_credential_envs(config)
    return bool(_secret_value(app_id_env, secrets) and _secret_value(app_password_env, secrets))


def _slack_bot_token_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "slackBotTokenEnv",
        "slack_bot_token_env",
        "botTokenEnv",
        "bot_token_env",
        "outboundWebhookTokenEnv",
        "outbound_webhook_token_env",
    ) or "SUPPORT_SLACK_BOT_TOKEN"


def _slack_bot_transport_enabled(channel: str, config: dict[str, Any], webhook_url: str, secrets: dict[str, str] | None) -> bool:
    if channel.strip().lower() != "slack":
        return False
    transport = _outbound_transport(config)
    if transport in {"bot", "slack_bot", "bot_api", "provider_api"}:
        return True
    if webhook_url:
        return False
    return bool(_secret_value(_slack_bot_token_env(config), secrets))


def _discord_payload(*, body: str, from_address: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": body,
        "allowed_mentions": {"parse": []},
    }
    if from_address:
        payload["username"] = from_address.split("@", 1)[0][:80]
    return payload


def _provider_text_limit(mode: str) -> int:
    if mode == "slack":
        return SLACK_TEXT_LIMIT
    if mode == "discord":
        return DISCORD_CONTENT_LIMIT
    if mode == "telegram":
        return TELEGRAM_TEXT_LIMIT
    if mode == "line":
        return LINE_TEXT_LIMIT
    if mode == "viber":
        return VIBER_TEXT_LIMIT
    if mode == "whatsapp":
        return WHATSAPP_TEXT_LIMIT
    if mode == "messenger":
        return MESSENGER_TEXT_LIMIT
    if mode == "instagram":
        return INSTAGRAM_TEXT_LIMIT
    if mode in {"twitter", "x"}:
        return X_DM_TEXT_LIMIT
    if mode in {"sms", "twilio"}:
        return SMS_TEXT_LIMIT
    return 0


def _multipart_suffix(index: int, total: int) -> str:
    return f"\n\n[{index}/{total}]"


def _preferred_split_index(text: str, *, start: int, hard_end: int) -> int:
    for separator in ("\n\n", "\n", " "):
        index = text.rfind(separator, start, hard_end + 1)
        if index > start:
            candidate = index + len(separator)
            return candidate if candidate <= hard_end else index
    return hard_end


def _split_text_without_suffix(text: str, limit: int) -> list[str]:
    if limit <= 0 or len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cursor = 0
    while cursor < len(text):
        hard_end = min(cursor + limit, len(text))
        if hard_end >= len(text):
            chunks.append(text[cursor:])
            break
        split_at = _preferred_split_index(text, start=cursor, hard_end=hard_end)
        if split_at <= cursor:
            split_at = hard_end
        chunks.append(text[cursor:split_at])
        cursor = split_at
    return chunks or [""]


def _limited_text_parts(text: str, limit: int) -> list[str]:
    if limit <= 0 or len(text) <= limit:
        return [text]
    if limit <= len(_multipart_suffix(1, 1)):
        return _split_text_without_suffix(text, limit)

    total = 1
    while True:
        payload_limit = limit - len(_multipart_suffix(total, total))
        chunks = _split_text_without_suffix(text, payload_limit)
        if len(chunks) == total:
            break
        total = len(chunks)

    return [chunk + _multipart_suffix(index, total) for index, chunk in enumerate(chunks, start=1)]


def _body_sha256(body: str) -> str:
    return sha256(body.encode("utf-8")).hexdigest()


def _multipart_progress_from_metadata(
    metadata: dict[str, Any],
    *,
    provider: str,
    body: str,
    total_parts: int,
) -> dict[int, str]:
    state = metadata.get("multipartDelivery") or metadata.get("multipart_delivery")
    if not isinstance(state, dict):
        return {}
    if str(state.get("provider") or "") != provider:
        return {}
    if str(state.get("bodySha256") or state.get("body_sha256") or "") != _body_sha256(body):
        return {}
    try:
        if int(state.get("totalParts") or state.get("total_parts") or 0) != total_parts:
            return {}
    except (TypeError, ValueError):
        return {}
    completed: dict[int, str] = {}
    raw_parts = state.get("completedParts") or state.get("completed_parts") or []
    if not isinstance(raw_parts, list):
        return {}
    for raw_part in raw_parts:
        if not isinstance(raw_part, dict):
            continue
        try:
            index = int(raw_part.get("index") or 0)
        except (TypeError, ValueError):
            continue
        provider_message_id = str(raw_part.get("providerMessageId") or raw_part.get("provider_message_id") or "").strip()
        if 1 <= index <= total_parts and provider_message_id:
            completed[index] = provider_message_id
    return completed


def _multipart_progress_metadata(
    *,
    provider: str,
    body: str,
    total_parts: int,
    completed_parts: dict[int, str],
) -> dict[str, Any]:
    return {
        "multipartDelivery": {
            "provider": provider,
            "bodySha256": _body_sha256(body),
            "totalParts": total_parts,
            "completedParts": [
                {"index": index, "providerMessageId": provider_message_id}
                for index, provider_message_id in sorted(completed_parts.items())
            ],
        }
    }


def _telegram_payload(*, body: str, metadata: dict[str, Any], to_address: str) -> dict[str, Any]:
    chat_id = _metadata_string(metadata, "channelId", "channel_id", "chatId", "chat_id") or to_address
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": body,
    }
    thread_id = _metadata_string(metadata, "threadId", "thread_id")
    if thread_id:
        payload["message_thread_id"] = thread_id
    reply_to = _metadata_string(metadata, "providerMessageId", "messageId", "sourceMessageId")
    if reply_to:
        payload["reply_to_message_id"] = reply_to.rsplit(":", 1)[-1]
    return payload


def _whatsapp_payload(*, body: str, metadata: dict[str, Any], to_address: str) -> dict[str, Any]:
    recipient = _metadata_string(metadata, "chatId", "chat_id", "waId", "wa_id", "senderId", "sender_id") or to_address
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": body,
        },
    }
    reply_to = _metadata_string(metadata, "providerMessageId", "messageId", "sourceMessageId")
    if reply_to:
        payload["context"] = {"message_id": reply_to.rsplit(":", 1)[-1]}
    return payload


def _messenger_payload(*, body: str, metadata: dict[str, Any], to_address: str) -> dict[str, Any]:
    recipient = (
        _metadata_string(metadata, "senderId", "sender_id", "psid", "recipientId", "recipient_id", "chatId", "chat_id")
        or to_address
    )
    return {
        "messaging_type": "RESPONSE",
        "recipient": {"id": recipient},
        "message": {"text": body},
    }


def _instagram_reply_target(metadata: dict[str, Any], to_address: str) -> str:
    return (
        _metadata_string(
            metadata,
            "senderId",
            "sender_id",
            "igid",
            "instagramScopedUserId",
            "instagram_scoped_user_id",
            "recipientId",
            "recipient_id",
            "chatId",
            "chat_id",
            "conversationId",
            "conversation_id",
            "to",
        )
        or to_address
    )


def _instagram_payload(*, body: str, metadata: dict[str, Any], to_address: str) -> dict[str, Any]:
    return {
        "recipient": {"id": _instagram_reply_target(metadata, to_address)},
        "message": {"text": body},
    }


def _twitter_dm_target(metadata: dict[str, Any], to_address: str) -> str:
    return (
        _metadata_string(
            metadata,
            "senderId",
            "sender_id",
            "twitterUserId",
            "twitter_user_id",
            "xUserId",
            "x_user_id",
            "recipientId",
            "recipient_id",
            "chatId",
            "chat_id",
            "to",
        )
        or to_address
    )


def _twitter_dm_conversation_id(metadata: dict[str, Any]) -> str:
    return _metadata_string(
        metadata,
        "dmConversationId",
        "dm_conversation_id",
        "xDmConversationId",
        "x_dm_conversation_id",
    )


def _twitter_payload(*, body: str) -> dict[str, Any]:
    return {"text": body}


def _line_reply_target(metadata: dict[str, Any], to_address: str) -> str:
    return (
        _metadata_string(
            metadata,
            "chatId",
            "chat_id",
            "conversationId",
            "conversation_id",
            "groupId",
            "group_id",
            "roomId",
            "room_id",
            "lineUserId",
            "line_user_id",
            "userId",
            "user_id",
            "senderId",
            "sender_id",
            "to",
        )
        or to_address
    )


def _line_push_payload(*, body: str, metadata: dict[str, Any], to_address: str) -> dict[str, Any]:
    return {
        "to": _line_reply_target(metadata, to_address),
        "messages": [{"type": "text", "text": body}],
    }


def _viber_reply_target(metadata: dict[str, Any], to_address: str) -> str:
    return (
        _metadata_string(
            metadata,
            "chatId",
            "chat_id",
            "conversationId",
            "conversation_id",
            "viberUserId",
            "viber_user_id",
            "userId",
            "user_id",
            "senderId",
            "sender_id",
            "to",
        )
        or to_address
    )


def _viber_payload(
    *,
    body: str,
    metadata: dict[str, Any],
    to_address: str,
    sender_name: str = "Support",
    sender_avatar: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "receiver": _viber_reply_target(metadata, to_address),
        "type": "text",
        "text": body,
        "sender": {"name": sender_name or "Support"},
    }
    if sender_avatar:
        payload["sender"]["avatar"] = sender_avatar
    tracking_data = _metadata_string(metadata, "sourceIssueId", "issueId", "eventId", "trackingData", "tracking_data")
    if tracking_data:
        payload["tracking_data"] = tracking_data[:4000]
    return payload


def _telegram_document_data(*, metadata: dict[str, Any], to_address: str) -> dict[str, str]:
    payload = _telegram_payload(body="", metadata=metadata, to_address=to_address)
    payload.pop("text", None)
    return {key: str(value) for key, value in payload.items() if value not in ("", None)}


def _telegram_bot_token_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "telegramBotTokenEnv",
        "telegram_bot_token_env",
        "botTokenEnv",
        "bot_token_env",
    ) or "SUPPORT_TELEGRAM_BOT_TOKEN"


def _telegram_bot_transport_enabled(channel: str, config: dict[str, Any], webhook_url: str, secrets: dict[str, str] | None) -> bool:
    if channel.strip().lower() != "telegram":
        return False
    transport = _outbound_transport(config)
    if transport in {"bot", "telegram_bot", "bot_api", "provider_api"}:
        return True
    if webhook_url:
        return False
    return bool(_secret_value(_telegram_bot_token_env(config), secrets))


def _line_channel_access_token_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "lineChannelAccessTokenEnv",
        "line_channel_access_token_env",
        "channelAccessTokenEnv",
        "channel_access_token_env",
        "accessTokenEnv",
        "access_token_env",
        "outboundWebhookTokenEnv",
        "outbound_webhook_token_env",
    ) or "SUPPORT_LINE_CHANNEL_ACCESS_TOKEN"


def _line_transport_enabled(channel: str, config: dict[str, Any], webhook_url: str, secrets: dict[str, str] | None) -> bool:
    if channel.strip().lower() != "line":
        return False
    transport = _outbound_transport(config)
    if transport in {"line", "line_messaging", "line_messaging_api", "provider_api"}:
        return True
    payload_mode = _config_string(config, "outboundPayloadMode", "outbound_payload_mode", "payloadMode", "payload_mode").lower()
    if payload_mode in {"line", "provider"}:
        return True
    if webhook_url:
        return False
    return bool(_secret_value(_line_channel_access_token_env(config), secrets))


def _viber_auth_token_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "viberAuthTokenEnv",
        "viber_auth_token_env",
        "authTokenEnv",
        "auth_token_env",
        "accessTokenEnv",
        "access_token_env",
        "outboundWebhookTokenEnv",
        "outbound_webhook_token_env",
    ) or "SUPPORT_VIBER_AUTH_TOKEN"


def _viber_transport_enabled(channel: str, config: dict[str, Any], webhook_url: str, secrets: dict[str, str] | None) -> bool:
    if channel.strip().lower() != "viber":
        return False
    transport = _outbound_transport(config)
    if transport in {"viber", "viber_bot", "bot_api", "provider_api"}:
        return True
    payload_mode = _config_string(config, "outboundPayloadMode", "outbound_payload_mode", "payloadMode", "payload_mode").lower()
    if payload_mode in {"viber", "provider"}:
        return True
    if webhook_url:
        return False
    return bool(_secret_value(_viber_auth_token_env(config), secrets))


def _whatsapp_access_token_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "whatsappAccessTokenEnv",
        "whatsapp_access_token_env",
        "accessTokenEnv",
        "access_token_env",
        "outboundWebhookTokenEnv",
        "outbound_webhook_token_env",
    ) or "SUPPORT_WHATSAPP_ACCESS_TOKEN"


def _whatsapp_phone_number_id_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "phoneNumberIdEnv",
        "phone_number_id_env",
        "whatsappPhoneNumberIdEnv",
        "whatsapp_phone_number_id_env",
    ) or "SUPPORT_WHATSAPP_PHONE_NUMBER_ID"


def _whatsapp_phone_number_id(config: dict[str, Any], secrets: dict[str, str] | None) -> str:
    direct = _config_string(config, "phoneNumberId", "phone_number_id", "whatsappPhoneNumberId", "whatsapp_phone_number_id")
    return direct or _secret_value(_whatsapp_phone_number_id_env(config), secrets)


def _whatsapp_transport_enabled(channel: str, config: dict[str, Any], webhook_url: str, secrets: dict[str, str] | None) -> bool:
    if channel.strip().lower() != "whatsapp":
        return False
    transport = _outbound_transport(config)
    if transport in {"whatsapp", "whatsapp_cloud", "whatsapp_cloud_api", "cloud_api", "provider_api"}:
        return True
    if webhook_url:
        return False
    return bool(
        _secret_value(_whatsapp_access_token_env(config), secrets)
        and _whatsapp_phone_number_id(config, secrets)
    )


def _messenger_page_access_token_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "messengerPageAccessTokenEnv",
        "messenger_page_access_token_env",
        "pageAccessTokenEnv",
        "page_access_token_env",
        "accessTokenEnv",
        "access_token_env",
        "outboundWebhookTokenEnv",
        "outbound_webhook_token_env",
    ) or "SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN"


def _messenger_page_id_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "messengerPageIdEnv",
        "messenger_page_id_env",
        "pageIdEnv",
        "page_id_env",
    ) or "SUPPORT_MESSENGER_PAGE_ID"


def _messenger_page_id(config: dict[str, Any], secrets: dict[str, str] | None) -> str:
    direct = _config_string(config, "messengerPageId", "messenger_page_id", "pageId", "page_id")
    return direct or _secret_value(_messenger_page_id_env(config), secrets)


def _messenger_transport_enabled(channel: str, config: dict[str, Any], webhook_url: str, secrets: dict[str, str] | None) -> bool:
    normalized = channel.strip().lower()
    if normalized not in {"messenger", "facebook_messenger"}:
        return False
    transport = _outbound_transport(config)
    if transport in {"messenger", "facebook_messenger", "messenger_api", "facebook_messenger_api", "provider_api"}:
        return True
    if webhook_url:
        return False
    return bool(
        _secret_value(_messenger_page_access_token_env(config), secrets)
        and _messenger_page_id(config, secrets)
    )


def _instagram_access_token_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "instagramAccessTokenEnv",
        "instagram_access_token_env",
        "accessTokenEnv",
        "access_token_env",
        "outboundWebhookTokenEnv",
        "outbound_webhook_token_env",
    ) or "SUPPORT_INSTAGRAM_ACCESS_TOKEN"


def _instagram_account_id_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "instagramAccountIdEnv",
        "instagram_account_id_env",
        "businessAccountIdEnv",
        "business_account_id_env",
    ) or "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID"


def _instagram_account_id(config: dict[str, Any], secrets: dict[str, str] | None) -> str:
    direct = _config_string(
        config,
        "instagramAccountId",
        "instagram_account_id",
        "businessAccountId",
        "business_account_id",
    )
    return direct or _secret_value(_instagram_account_id_env(config), secrets)


def _instagram_transport_enabled(channel: str, config: dict[str, Any], webhook_url: str, secrets: dict[str, str] | None) -> bool:
    if channel.strip().lower() != "instagram":
        return False
    transport = _outbound_transport(config)
    if transport in {"instagram", "instagram_messaging", "instagram_graph", "instagram_graph_api", "provider_api"}:
        return True
    payload_mode = _config_string(config, "outboundPayloadMode", "outbound_payload_mode", "payloadMode", "payload_mode").lower()
    if payload_mode in {"instagram", "provider"}:
        return True
    if webhook_url:
        return False
    return bool(
        _secret_value(_instagram_access_token_env(config), secrets)
        and _instagram_account_id(config, secrets)
    )


def _twitter_user_access_token_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "twitterUserAccessTokenEnv",
        "twitter_user_access_token_env",
        "xUserAccessTokenEnv",
        "x_user_access_token_env",
        "userAccessTokenEnv",
        "user_access_token_env",
        "twitterBearerTokenEnv",
        "twitter_bearer_token_env",
        "xBearerTokenEnv",
        "x_bearer_token_env",
        "bearerTokenEnv",
        "bearer_token_env",
        "outboundWebhookTokenEnv",
        "outbound_webhook_token_env",
    ) or "SUPPORT_X_USER_ACCESS_TOKEN"


def _twitter_transport_enabled(channel: str, config: dict[str, Any], webhook_url: str, secrets: dict[str, str] | None) -> bool:
    if channel.strip().lower() not in {"twitter", "x"}:
        return False
    transport = _outbound_transport(config)
    if transport in {"twitter", "x", "x_dm", "twitter_dm", "x_api", "provider_api"}:
        return True
    payload_mode = _config_string(config, "outboundPayloadMode", "outbound_payload_mode", "payloadMode", "payload_mode").lower()
    if payload_mode in {"twitter", "x", "provider"}:
        return True
    if webhook_url:
        return False
    return bool(_secret_value(_twitter_user_access_token_env(config), secrets))


def _twilio_account_sid_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "twilioAccountSidEnv",
        "twilio_account_sid_env",
        "accountSidEnv",
        "account_sid_env",
    ) or "SUPPORT_TWILIO_ACCOUNT_SID"


def _twilio_auth_token_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "twilioAuthTokenEnv",
        "twilio_auth_token_env",
        "authTokenEnv",
        "auth_token_env",
    ) or "SUPPORT_TWILIO_AUTH_TOKEN"


def _twilio_from_number_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "twilioFromNumberEnv",
        "twilio_from_number_env",
        "fromNumberEnv",
        "from_number_env",
    ) or "SUPPORT_TWILIO_FROM_NUMBER"


def _twilio_messaging_service_sid_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "twilioMessagingServiceSidEnv",
        "twilio_messaging_service_sid_env",
        "messagingServiceSidEnv",
        "messaging_service_sid_env",
    ) or "SUPPORT_TWILIO_MESSAGING_SERVICE_SID"


def _twilio_secret_or_config(
    config: dict[str, Any],
    secrets: dict[str, str] | None,
    *,
    direct_keys: tuple[str, ...],
    env_name: str,
) -> str:
    direct = _config_string(config, *direct_keys)
    return direct or _secret_value(env_name, secrets)


def _twilio_transport_enabled(channel: str, config: dict[str, Any], webhook_url: str, secrets: dict[str, str] | None) -> bool:
    if channel.strip().lower() not in {"sms", "twilio"}:
        return False
    transport = _outbound_transport(config)
    if transport in {"sms", "twilio", "twilio_sms", "provider_api"}:
        return True
    payload_mode = _config_string(config, "outboundPayloadMode", "outbound_payload_mode", "payloadMode", "payload_mode").lower()
    if payload_mode in {"sms", "twilio", "provider"}:
        return True
    if webhook_url:
        return False
    account_sid = _secret_value(_twilio_account_sid_env(config), secrets)
    auth_token = _secret_value(_twilio_auth_token_env(config), secrets)
    from_number = _twilio_secret_or_config(
        config,
        secrets,
        direct_keys=("twilioFromNumber", "twilio_from_number", "fromNumber", "from_number"),
        env_name=_twilio_from_number_env(config),
    )
    messaging_service_sid = _twilio_secret_or_config(
        config,
        secrets,
        direct_keys=("twilioMessagingServiceSid", "twilio_messaging_service_sid", "messagingServiceSid", "messaging_service_sid"),
        env_name=_twilio_messaging_service_sid_env(config),
    )
    return bool(account_sid and auth_token and (from_number or messaging_service_sid))


def _discord_bot_token_env(config: dict[str, Any]) -> str:
    return _config_string(
        config,
        "discordBotTokenEnv",
        "discord_bot_token_env",
        "botTokenEnv",
        "bot_token_env",
    ) or "SUPPORT_DISCORD_BOT_TOKEN"


def _outbound_transport(config: dict[str, Any]) -> str:
    return _config_string(config, "outboundTransport", "outbound_transport", "transport").lower()


def _discord_bot_transport_enabled(channel: str, config: dict[str, Any], webhook_url: str, secrets: dict[str, str] | None) -> bool:
    if channel.strip().lower() != "discord":
        return False
    transport = _outbound_transport(config)
    if transport in {"bot", "discord_bot", "bot_api", "provider_api"}:
        return True
    if webhook_url:
        return False
    return bool(_secret_value(_discord_bot_token_env(config), secrets))


def _discord_bot_channel_id(metadata: dict[str, Any]) -> str:
    return _metadata_string(metadata, "threadId", "thread_id") or _metadata_string(metadata, "channelId", "channel_id")


def _discord_bot_payload(*, body: str, metadata: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": body,
        "allowed_mentions": {"parse": []},
    }
    source_message_id = _metadata_string(metadata, "providerMessageId", "messageId", "sourceMessageId")
    channel_id = _discord_bot_channel_id(metadata)
    if source_message_id and channel_id:
        payload["message_reference"] = {
            "message_id": source_message_id.rsplit(":", 1)[-1],
            "channel_id": channel_id,
            "fail_if_not_exists": False,
        }
    return payload


def _teams_service_url(config: dict[str, Any], metadata: dict[str, Any]) -> str:
    return (
        _metadata_string(metadata, "serviceUrl", "service_url")
        or _config_string(config, "teamsServiceUrl", "teams_service_url", "serviceUrl", "service_url")
    ).rstrip("/")


def _teams_conversation_id(metadata: dict[str, Any]) -> str:
    return _metadata_string(metadata, "conversationId", "conversation_id", "threadId", "thread_id", "channelId", "channel_id")


def _teams_reply_activity_id(metadata: dict[str, Any]) -> str:
    return _metadata_string(metadata, "replyToId", "reply_to_id", "providerMessageId", "messageId", "sourceMessageId").rsplit(":", 1)[-1]


def _teams_bot_payload(*, body: str) -> dict[str, Any]:
    return {
        "type": "message",
        "text": body,
    }


def _channel_payload_mode(channel: str, channel_config: dict[str, Any]) -> str:
    raw = _config_string(channel_config, "outboundPayloadMode", "outbound_payload_mode", "payloadMode", "payload_mode").lower()
    if raw in {
        "generic",
        "adapter",
        "provider",
        "email",
        "slack",
        "teams",
        "discord",
        "telegram",
        "line",
        "viber",
        "whatsapp",
        "messenger",
        "instagram",
        "twitter",
        "x",
        "sms",
        "twilio",
    }:
        return raw
    normalized_channel = channel.strip().lower()
    if normalized_channel in {
        "slack",
        "teams",
        "discord",
        "telegram",
        "line",
        "viber",
        "whatsapp",
        "messenger",
        "facebook_messenger",
        "instagram",
        "twitter",
        "x",
        "sms",
    }:
        if normalized_channel == "facebook_messenger":
            return "messenger"
        return normalized_channel
    return "generic"


def _normalized_payload_mode(mode: str, channel: str) -> str:
    if mode == "provider":
        return channel.strip().lower()
    return mode


def _channel_payload(
    *,
    mode: str,
    message_id: str,
    channel: str,
    to_address: str,
    from_address: str,
    subject: str,
    body: str,
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    mode = _normalized_payload_mode(mode, channel)
    if mode == "slack":
        return _slack_payload(body=body, metadata=metadata), {}
    if mode == "teams":
        return _teams_payload(body=body, subject=subject, metadata=metadata), {}
    if mode == "discord":
        thread_id = _metadata_string(metadata, "threadId", "thread_id")
        return _discord_payload(body=body, from_address=from_address), {"thread_id": thread_id} if thread_id else {}
    if mode == "telegram":
        return _telegram_payload(body=body, metadata=metadata, to_address=to_address), {}
    if mode == "line":
        return _line_push_payload(body=body, metadata=metadata, to_address=to_address), {}
    if mode == "viber":
        return _viber_payload(body=body, metadata=metadata, to_address=to_address), {}
    if mode == "whatsapp":
        return _whatsapp_payload(body=body, metadata=metadata, to_address=to_address), {}
    if mode == "messenger":
        return _messenger_payload(body=body, metadata=metadata, to_address=to_address), {}
    if mode == "instagram":
        return _instagram_payload(body=body, metadata=metadata, to_address=to_address), {}
    if mode in {"twitter", "x"}:
        return _twitter_payload(body=body), {}
    return _generic_channel_payload(
        message_id=message_id,
        channel=channel,
        to_address=to_address,
        from_address=from_address,
        subject=subject,
        body=body,
        metadata=metadata,
    ), {}


def _provider_message_id_from_response(
    *,
    channel: str,
    fallback: str,
    data: Any,
) -> str:
    if not isinstance(data, dict):
        return fallback
    direct = data.get("providerMessageId") or data.get("provider_message_id")
    if direct:
        return str(direct)
    normalized_channel = channel.strip().lower()
    response_message_id = data.get("messageId") or data.get("message_id")
    if normalized_channel in {"messenger", "facebook_messenger"} and response_message_id:
        return f"messenger:{response_message_id}"
    if normalized_channel == "whatsapp" and response_message_id:
        return f"whatsapp:{response_message_id}"
    if normalized_channel == "instagram" and response_message_id:
        return f"instagram:{response_message_id}"
    if response_message_id:
        return str(response_message_id)
    if normalized_channel == "slack":
        ts = str(data.get("ts") or "").strip()
        channel_id = str(data.get("channel") or "").strip()
        if ts and channel_id:
            return f"slack:{channel_id}:{ts}"
        if ts:
            return ts
    if normalized_channel == "telegram":
        result = data.get("result")
        if isinstance(result, dict):
            message_id = result.get("message_id")
            chat = result.get("chat")
            chat_id = chat.get("id") if isinstance(chat, dict) else None
            if message_id and chat_id:
                return f"telegram:{chat_id}:{message_id}"
            if message_id:
                return str(message_id)
    if normalized_channel == "line":
        sent_messages = data.get("sentMessages") or data.get("sent_messages")
        if isinstance(sent_messages, list) and sent_messages and isinstance(sent_messages[0], dict):
            message_id = sent_messages[0].get("id")
            if message_id:
                return f"line:{message_id}"
        request_id = data.get("requestId") or data.get("request_id") or data.get("x-line-request-id")
        if request_id:
            return f"line:{request_id}"
    if normalized_channel == "viber":
        message_token = data.get("message_token") or data.get("messageToken")
        if message_token:
            return f"viber:{message_token}"
    if normalized_channel == "whatsapp":
        messages = data.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            message_id = messages[0].get("id")
            if message_id:
                return f"whatsapp:{message_id}"
    if normalized_channel in {"messenger", "facebook_messenger"}:
        message_id = data.get("message_id") or data.get("messageId")
        if message_id:
            return f"messenger:{message_id}"
    if normalized_channel == "instagram":
        message_id = data.get("message_id") or data.get("messageId")
        if message_id:
            return f"instagram:{message_id}"
    if normalized_channel in {"twitter", "x"}:
        result = data.get("data")
        if isinstance(result, dict):
            event_id = result.get("dm_event_id") or result.get("id")
            if event_id:
                return f"twitter:{event_id}"
        event_id = data.get("dm_event_id") or data.get("dmEventId") or data.get("id")
        if event_id:
            return f"twitter:{event_id}"
    if normalized_channel in {"sms", "twilio"}:
        sid = data.get("sid") or data.get("Sid")
        if sid:
            return f"twilio:{sid}"
    if normalized_channel == "discord" and data.get("id"):
        return f"discord:{data['id']}"
    if normalized_channel == "teams" and data.get("id"):
        return str(data["id"])
    return fallback


def _provider_success_error(*, channel: str, data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    normalized_channel = channel.strip().lower()
    if normalized_channel in {"slack", "telegram"} and data.get("ok") is False:
        error = data.get("error") or data.get("description") or data.get("message")
        return str(error or f"{normalized_channel} provider rejected message").strip()
    if normalized_channel == "teams":
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
            return str(message or "Teams provider rejected message").strip()
    if normalized_channel == "whatsapp":
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or error.get("type")
            return str(message or "WhatsApp provider rejected message").strip()
    if normalized_channel in {"messenger", "facebook_messenger"}:
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or error.get("type")
            return str(message or "Messenger provider rejected message").strip()
    if normalized_channel == "instagram":
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or error.get("type")
            return str(message or "Instagram provider rejected message").strip()
    if normalized_channel in {"twitter", "x"}:
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                message = first.get("message") or first.get("detail") or first.get("title") or first.get("type")
                return str(message or "X provider rejected message").strip()
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail") or error.get("title") or error.get("type")
            return str(message or "X provider rejected message").strip()
        if error:
            return str(error).strip()
    if normalized_channel == "line":
        message = data.get("message") or data.get("error") or data.get("details")
        if message:
            return str(message or "LINE provider rejected message").strip()
    if normalized_channel == "viber" and data.get("status") not in {None, 0, "0"}:
        message = data.get("status_message") or data.get("message") or data.get("error")
        return str(message or "Viber provider rejected message").strip()
    if normalized_channel in {"sms", "twilio"} and data.get("code") and data.get("message"):
        return str(data.get("message") or "Twilio provider rejected message").strip()
    return ""


def _json_retry_after_seconds(data: Any) -> int:
    if not isinstance(data, dict):
        return 0
    values = [
        data.get("retry_after"),
        data.get("retryAfter"),
    ]
    parameters = data.get("parameters")
    if isinstance(parameters, dict):
        values.extend([parameters.get("retry_after"), parameters.get("retryAfter")])
    response_metadata = data.get("response_metadata")
    if isinstance(response_metadata, dict):
        values.extend([response_metadata.get("retry_after"), response_metadata.get("retryAfter")])
    for value in values:
        if value is None:
            continue
        retry_after = _retry_after_seconds(str(value))
        if retry_after > 0:
            return retry_after
    return 0


def _retry_after_seconds(value: str) -> int:
    clean = (value or "").strip()
    if not clean:
        return 0
    try:
        return max(0, min(int(float(clean)), 24 * 60 * 60))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(clean)
    except (TypeError, ValueError):
        return 0
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    delta = retry_at - datetime.now(timezone.utc)
    return max(0, min(int(delta.total_seconds()), 24 * 60 * 60))


def _transient_http_retry_after(response: httpx.Response) -> int:
    if response.status_code not in {408, 425, 429, 500, 502, 503, 504}:
        return 0
    retry_after = _retry_after_seconds(response.headers.get("Retry-After", ""))
    if retry_after > 0:
        return retry_after
    try:
        json_retry_after = _json_retry_after_seconds(response.json())
    except ValueError:
        json_retry_after = 0
    if json_retry_after > 0:
        return json_retry_after
    if response.status_code == 429:
        return 60
    if response.status_code in {500, 502, 503, 504}:
        return 120
    return 30


def _http_error_message(response: httpx.Response) -> str:
    try:
        detail = response.json()
    except ValueError:
        detail = response.text
    if isinstance(detail, dict):
        for key in ("error", "message", "detail", "description"):
            value = detail.get(key)
            if value:
                return f"HTTP {response.status_code}: {value}"
    if isinstance(detail, str) and detail.strip():
        return f"HTTP {response.status_code}: {detail.strip()[:240]}"
    return f"HTTP {response.status_code}: {response.reason_phrase}"


def _safe_url_for_metadata(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ""
    path_segments = [segment for segment in parts.path.split("/") if segment]
    redacted: list[str] = []
    redact_next = False
    for segment in path_segments:
        lower = segment.lower()
        if lower.startswith("bot") and len(segment) > 3:
            redacted.append("bot[redacted]")
            continue
        if redact_next:
            redacted.append("[redacted]")
            redact_next = False
            continue
        redacted.append(segment)
        if lower == "webhooks":
            # Discord/custom webhook path: /webhooks/{id}/{secret-token}
            redact_next = False
        elif len(redacted) >= 2 and redacted[-2].lower() == "webhooks":
            redact_next = True
    safe_path = "/" + "/".join(redacted) if redacted else ""
    return urlunsplit((parts.scheme, parts.netloc, safe_path, "", ""))


def _safe_response_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 40:
                cleaned["__truncated__"] = True
                break
            clean_key = str(key)
            lower_key = clean_key.lower()
            if any(marker in lower_key for marker in ("token", "secret", "password", "authorization")):
                cleaned[clean_key] = "[redacted]"
            else:
                cleaned[clean_key] = _safe_response_value(item, depth=depth + 1)
        return cleaned
    if isinstance(value, list):
        result = [_safe_response_value(item, depth=depth + 1) for item in value[:20]]
        if len(value) > 20:
            result.append("[truncated]")
        return result
    if isinstance(value, str):
        return value if len(value) <= 600 else f"{value[:597]}..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:600]


def _delivery_route_metadata(
    *,
    provider: str,
    channel: str,
    transport: str,
    target_url: str = "",
    payload_mode: str = "",
    metadata: dict[str, Any] | None = None,
    part_count: int = 1,
) -> dict[str, Any]:
    clean_metadata = metadata or {}
    attachments = _metadata_attachments(clean_metadata)
    route: dict[str, Any] = {
        "provider": provider,
        "channel": channel.strip().lower(),
        "transport": transport,
    }
    if target_url:
        route["targetUrl"] = _safe_url_for_metadata(target_url)
    if payload_mode:
        route["payloadMode"] = payload_mode
    if part_count > 1:
        route["partCount"] = part_count
    for key in (
        "workspaceId",
        "teamId",
        "channelId",
        "chatId",
        "threadId",
        "threadTs",
        "conversationId",
        "replyToId",
        "providerMessageId",
        "sourceMessageId",
        "lineUserId",
        "lineGroupId",
        "lineRoomId",
        "senderId",
        "instagramAccountId",
        "igid",
        "twitterUserId",
        "xUserId",
        "dmConversationId",
    ):
        value = _metadata_string(clean_metadata, key, _camel_to_snake(key))
        if value:
            route[key] = value
    if attachments:
        route["attachmentCount"] = len(attachments)
        route["attachmentNames"] = [_attachment_display_name(item) for item in attachments[:10]]
    return {"deliveryRoute": {key: value for key, value in route.items() if value}}


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"_\1", value).lower()


def _provider_response_metadata(response_data: Any, *, status_code: int = 0) -> dict[str, Any]:
    response: dict[str, Any] = {}
    if status_code:
        response["statusCode"] = status_code
    if response_data is not None:
        response["body"] = _safe_response_value(response_data)
    return {"providerResponse": response} if response else {}


def _response_status_code(response: Any) -> int:
    try:
        return int(getattr(response, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _merge_result_metadata(*parts: dict[str, Any] | None) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for part in parts:
        if part:
            merged.update(part)
    return merged or None


def _response_data(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _fetch_teams_bot_token(channel_config: dict[str, Any], secrets: dict[str, str] | None) -> tuple[str, str]:
    app_id_env, app_password_env = _teams_app_credential_envs(channel_config)
    app_id = _secret_value(app_id_env, secrets)
    app_password = _secret_value(app_password_env, secrets)
    missing = [env for env, value in ((app_id_env, app_id), (app_password_env, app_password)) if not value]
    if missing:
        return "", f"Teams app credential env missing: {', '.join(missing)}"
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(
                TEAMS_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": app_id,
                    "client_secret": app_password,
                    "scope": TEAMS_TOKEN_SCOPE,
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return "", _http_error_message(exc.response)
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return "", str(exc)
    try:
        data = response.json()
    except ValueError:
        return "", "Teams token endpoint returned invalid JSON"
    token = str(data.get("access_token") if isinstance(data, dict) else "").strip()
    if not token:
        return "", "Teams token endpoint did not return an access token"
    return token, ""


def _send_slack_bot_reply(
    *,
    message_id: str,
    channel_config: dict[str, Any],
    body: str,
    metadata: dict[str, Any],
    secrets: dict[str, str] | None,
) -> DeliveryResult:
    token_env = _slack_bot_token_env(channel_config)
    token = _secret_value(token_env, secrets)
    if not token:
        return DeliveryResult(
            status="failed",
            provider="slack_bot",
            error=f"{token_env} is not configured",
        )
    channel_id = _metadata_string(metadata, "channelId", "channel_id")
    if not channel_id:
        return DeliveryResult(
            status="failed",
            provider="slack_bot",
            error="Slack channelId is required",
        )

    uploadable_attachments, skipped_attachments, attachment_error = _uploadable_attachments(metadata)
    if attachment_error:
        return DeliveryResult(status="failed", provider="slack_bot", error=attachment_error)

    delivery_body = _body_with_attachment_notice(
        body,
        metadata,
        attachments=skipped_attachments if uploadable_attachments else None,
    )
    api_base = _config_string(channel_config, "slackApiBaseUrl", "slack_api_base_url") or SLACK_API_BASE
    url = f"{api_base.rstrip('/')}/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    auth_headers = {"Authorization": f"Bearer {token}"}
    parts = _limited_text_parts(delivery_body, SLACK_TEXT_LIMIT) if delivery_body.strip() else []
    route_metadata = _delivery_route_metadata(
        provider="slack_bot",
        channel="slack",
        transport="bot_api",
        target_url=url,
        payload_mode="slack",
        metadata=metadata,
        part_count=len(parts),
    )
    completed_parts = _multipart_progress_from_metadata(
        metadata,
        provider="slack_bot",
        body=delivery_body,
        total_parts=len(parts),
    ) if parts else {}
    provider_message_ids: list[str] = []
    last_response_data: Any = None
    last_status_code = 0
    attachment_delivery_metadata = _attachment_delivery_metadata(
        provider="slack_bot",
        uploaded=[],
        skipped=skipped_attachments,
    )
    try:
        with httpx.Client(timeout=15) as client:
            for index, part in enumerate(parts, start=1):
                if index in completed_parts:
                    provider_message_ids.append(completed_parts[index])
                    continue
                try:
                    response = client.post(url, json=_slack_payload(body=part, metadata=metadata), headers=headers)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="slack_bot",
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            _multipart_progress_metadata(
                                provider="slack_bot",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                response_data: Any = _response_data(response)
                last_response_data = response_data
                last_status_code = _response_status_code(response)
                provider_error = _provider_success_error(channel="slack", data=response_data)
                if provider_error:
                    retry_after = _json_retry_after_seconds(response_data)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="slack_bot",
                        provider_message_id=";".join(provider_message_ids),
                        error=provider_error,
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(response_data, status_code=_response_status_code(response)),
                            _multipart_progress_metadata(
                                provider="slack_bot",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                fallback = f"slack:{message_id}:{index}" if len(parts) > 1 else f"slack:{message_id}"
                provider_message_ids.append(
                    _provider_message_id_from_response(
                        channel="slack",
                        fallback=fallback,
                        data=response_data,
                    )
                )
                completed_parts[index] = provider_message_ids[-1]
            if uploadable_attachments:
                upload_url_endpoint = f"{api_base.rstrip('/')}/files.getUploadURLExternal"
                complete_url = f"{api_base.rstrip('/')}/files.completeUploadExternal"
                slack_files: list[dict[str, str]] = []
                uploaded_items: list[dict[str, Any]] = []
                for attachment in uploadable_attachments:
                    try:
                        response = client.post(
                            upload_url_endpoint,
                            data={"filename": attachment.filename, "length": str(attachment.size)},
                            headers=auth_headers,
                        )
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        retry_after = _transient_http_retry_after(exc.response)
                        return DeliveryResult(
                            status="queued" if retry_after else "failed",
                            provider="slack_bot",
                            provider_message_id=";".join(provider_message_ids),
                            error=_http_error_message(exc.response),
                            retry_after_seconds=retry_after,
                            metadata=_merge_result_metadata(
                                route_metadata,
                                _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                                _multipart_progress_metadata(
                                    provider="slack_bot",
                                    body=delivery_body,
                                    total_parts=len(parts),
                                    completed_parts=completed_parts,
                                ) if len(parts) > 1 else None,
                            ),
                        )
                    response_data = _response_data(response)
                    last_response_data = response_data
                    last_status_code = _response_status_code(response)
                    provider_error = _provider_success_error(channel="slack", data=response_data)
                    if provider_error:
                        retry_after = _json_retry_after_seconds(response_data)
                        return DeliveryResult(
                            status="queued" if retry_after else "failed",
                            provider="slack_bot",
                            provider_message_id=";".join(provider_message_ids),
                            error=provider_error,
                            retry_after_seconds=retry_after,
                            metadata=_merge_result_metadata(
                                route_metadata,
                                _provider_response_metadata(response_data, status_code=last_status_code),
                                _multipart_progress_metadata(
                                    provider="slack_bot",
                                    body=delivery_body,
                                    total_parts=len(parts),
                                    completed_parts=completed_parts,
                                ) if len(parts) > 1 else None,
                            ),
                        )
                    upload_url = str(response_data.get("upload_url") if isinstance(response_data, dict) else "").strip()
                    file_id = str(response_data.get("file_id") if isinstance(response_data, dict) else "").strip()
                    if not upload_url or not file_id:
                        return DeliveryResult(
                            status="failed",
                            provider="slack_bot",
                            provider_message_id=";".join(provider_message_ids),
                            error="Slack upload URL response did not include upload_url and file_id",
                            metadata=_merge_result_metadata(
                                route_metadata,
                                _provider_response_metadata(response_data, status_code=last_status_code),
                            ),
                        )
                    try:
                        upload_response = client.post(
                            upload_url,
                            content=attachment.content,
                            headers={"Content-Type": attachment.content_type},
                        )
                        upload_response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        retry_after = _transient_http_retry_after(exc.response)
                        return DeliveryResult(
                            status="queued" if retry_after else "failed",
                            provider="slack_bot",
                            provider_message_id=";".join(provider_message_ids),
                            error=_http_error_message(exc.response),
                            retry_after_seconds=retry_after,
                            metadata=_merge_result_metadata(
                                route_metadata,
                                _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            ),
                        )
                    slack_files.append({"id": file_id, "title": attachment.filename})
                    uploaded_items.append({
                        "filename": attachment.filename,
                        "contentType": attachment.content_type,
                        "size": attachment.size,
                        "status": "uploaded",
                        "providerFileId": file_id,
                    })
                complete_payload: dict[str, Any] = {
                    "files": slack_files,
                    "channel_id": channel_id,
                }
                thread_ts = _metadata_string(metadata, "threadTs", "thread_ts", "threadId", "thread_id", "providerMessageId")
                if thread_ts:
                    complete_payload["thread_ts"] = thread_ts
                try:
                    complete_response = client.post(complete_url, json=complete_payload, headers=headers)
                    complete_response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="slack_bot",
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                        ),
                    )
                complete_data = _response_data(complete_response)
                last_response_data = complete_data
                last_status_code = _response_status_code(complete_response)
                provider_error = _provider_success_error(channel="slack", data=complete_data)
                if provider_error:
                    retry_after = _json_retry_after_seconds(complete_data)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="slack_bot",
                        provider_message_id=";".join(provider_message_ids),
                        error=provider_error,
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(complete_data, status_code=last_status_code),
                        ),
                    )
                provider_message_ids.extend(f"slack_file:{item['providerFileId']}" for item in uploaded_items)
                attachment_delivery_metadata = _attachment_delivery_metadata(
                    provider="slack_bot",
                    uploaded=uploaded_items,
                    skipped=skipped_attachments,
                )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider="slack_bot",
            provider_message_id=";".join(provider_message_ids),
            error=str(exc),
            metadata=_merge_result_metadata(
                route_metadata,
                _multipart_progress_metadata(
                    provider="slack_bot",
                    body=delivery_body,
                    total_parts=len(parts),
                    completed_parts=completed_parts,
                ) if len(parts) > 1 else None,
            ),
        )

    return DeliveryResult(
        status="sent",
        provider="slack_bot",
        provider_message_id=";".join(provider_message_ids),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(last_response_data, status_code=last_status_code),
            attachment_delivery_metadata,
            _multipart_progress_metadata(
                provider="slack_bot",
                body=delivery_body,
                total_parts=len(parts),
                completed_parts=completed_parts,
            ) if len(parts) > 1 else None,
        ),
    )


def _send_teams_bot_reply(
    *,
    message_id: str,
    channel_config: dict[str, Any],
    body: str,
    metadata: dict[str, Any],
    secrets: dict[str, str] | None,
) -> DeliveryResult:
    service_url = _teams_service_url(channel_config, metadata)
    if not service_url:
        return DeliveryResult(
            status="failed",
            provider="teams_bot",
            error="Teams serviceUrl is required",
        )
    if urlsplit(service_url).scheme != "https":
        return DeliveryResult(
            status="failed",
            provider="teams_bot",
            error="Teams serviceUrl must use https",
        )
    conversation_id = _teams_conversation_id(metadata)
    if not conversation_id:
        return DeliveryResult(
            status="failed",
            provider="teams_bot",
            error="Teams conversationId or threadId is required",
        )
    token, token_error = _fetch_teams_bot_token(channel_config, secrets)
    if token_error:
        return DeliveryResult(
            status="failed",
            provider="teams_bot",
            error=token_error,
        )

    reply_to_id = _teams_reply_activity_id(metadata)
    base_url = f"{service_url}/v3/conversations/{quote(conversation_id, safe='')}/activities"
    url = f"{base_url}/{quote(reply_to_id, safe='')}" if reply_to_id else base_url
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    delivery_body = _body_with_attachment_notice(body, metadata)
    route_metadata = _delivery_route_metadata(
        provider="teams_bot",
        channel="teams",
        transport="bot_api",
        target_url=url,
        payload_mode="teams",
        metadata=metadata,
    )
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(url, json=_teams_bot_payload(body=delivery_body), headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        retry_after = _transient_http_retry_after(exc.response)
        return DeliveryResult(
            status="queued" if retry_after else "failed",
            provider="teams_bot",
            error=_http_error_message(exc.response),
            retry_after_seconds=retry_after,
            metadata=_merge_result_metadata(
                route_metadata,
                _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
            ),
        )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider="teams_bot",
            error=str(exc),
            metadata=route_metadata,
        )
    response_data: Any = _response_data(response)
    return DeliveryResult(
        status="sent",
        provider="teams_bot",
        provider_message_id=_provider_message_id_from_response(
            channel="teams",
            fallback=f"teams:{message_id}",
            data=response_data,
        ),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(response_data, status_code=_response_status_code(response)),
        ),
    )


def _send_telegram_bot_reply(
    *,
    message_id: str,
    channel_config: dict[str, Any],
    to_address: str,
    body: str,
    metadata: dict[str, Any],
    secrets: dict[str, str] | None,
) -> DeliveryResult:
    token_env = _telegram_bot_token_env(channel_config)
    token = _secret_value(token_env, secrets)
    if not token:
        return DeliveryResult(
            status="failed",
            provider="telegram_bot",
            error=f"{token_env} is not configured",
        )
    chat_id = _metadata_string(metadata, "channelId", "channel_id", "chatId", "chat_id") or to_address
    if not chat_id:
        return DeliveryResult(
            status="failed",
            provider="telegram_bot",
            error="Telegram chatId or toAddress is required",
        )

    uploadable_attachments, skipped_attachments, attachment_error = _uploadable_attachments(metadata)
    if attachment_error:
        return DeliveryResult(status="failed", provider="telegram_bot", error=attachment_error)

    delivery_body = _body_with_attachment_notice(
        body,
        metadata,
        attachments=skipped_attachments if uploadable_attachments else None,
    )
    api_base = _config_string(channel_config, "telegramApiBaseUrl", "telegram_api_base_url") or TELEGRAM_API_BASE
    url = f"{api_base.rstrip('/')}/bot{token}/sendMessage"
    document_url = f"{api_base.rstrip('/')}/bot{token}/sendDocument"
    headers = {"Content-Type": "application/json"}
    parts = _limited_text_parts(delivery_body, TELEGRAM_TEXT_LIMIT) if delivery_body.strip() else []
    route_metadata = _delivery_route_metadata(
        provider="telegram_bot",
        channel="telegram",
        transport="bot_api",
        target_url=url,
        payload_mode="telegram",
        metadata=metadata,
        part_count=len(parts),
    )
    completed_parts = _multipart_progress_from_metadata(
        metadata,
        provider="telegram_bot",
        body=delivery_body,
        total_parts=len(parts),
    ) if parts else {}
    provider_message_ids: list[str] = []
    last_response_data: Any = None
    last_status_code = 0
    attachment_delivery_metadata = _attachment_delivery_metadata(
        provider="telegram_bot",
        uploaded=[],
        skipped=skipped_attachments,
    )
    try:
        with httpx.Client(timeout=15) as client:
            for index, part in enumerate(parts, start=1):
                if index in completed_parts:
                    provider_message_ids.append(completed_parts[index])
                    continue
                try:
                    response = client.post(url, json=_telegram_payload(body=part, metadata=metadata, to_address=to_address), headers=headers)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="telegram_bot",
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            _multipart_progress_metadata(
                                provider="telegram_bot",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                response_data: Any = _response_data(response)
                last_response_data = response_data
                last_status_code = _response_status_code(response)
                provider_error = _provider_success_error(channel="telegram", data=response_data)
                if provider_error:
                    retry_after = _json_retry_after_seconds(response_data)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="telegram_bot",
                        provider_message_id=";".join(provider_message_ids),
                        error=provider_error,
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(response_data, status_code=_response_status_code(response)),
                            _multipart_progress_metadata(
                                provider="telegram_bot",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                fallback = f"telegram:{message_id}:{index}" if len(parts) > 1 else f"telegram:{message_id}"
                provider_message_ids.append(
                    _provider_message_id_from_response(
                        channel="telegram",
                        fallback=fallback,
                        data=response_data,
                    )
                )
                completed_parts[index] = provider_message_ids[-1]
            if uploadable_attachments:
                uploaded_items: list[dict[str, Any]] = []
                for index, attachment in enumerate(uploadable_attachments, start=1):
                    try:
                        response = client.post(
                            document_url,
                            data=_telegram_document_data(metadata=metadata, to_address=to_address),
                            files={"document": (attachment.filename, attachment.content, attachment.content_type)},
                        )
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        retry_after = _transient_http_retry_after(exc.response)
                        return DeliveryResult(
                            status="queued" if retry_after else "failed",
                            provider="telegram_bot",
                            provider_message_id=";".join(provider_message_ids),
                            error=_http_error_message(exc.response),
                            retry_after_seconds=retry_after,
                            metadata=_merge_result_metadata(
                                route_metadata,
                                _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                                _multipart_progress_metadata(
                                    provider="telegram_bot",
                                    body=delivery_body,
                                    total_parts=len(parts),
                                    completed_parts=completed_parts,
                                ) if len(parts) > 1 else None,
                            ),
                        )
                    response_data = _response_data(response)
                    last_response_data = response_data
                    last_status_code = _response_status_code(response)
                    provider_error = _provider_success_error(channel="telegram", data=response_data)
                    if provider_error:
                        retry_after = _json_retry_after_seconds(response_data)
                        return DeliveryResult(
                            status="queued" if retry_after else "failed",
                            provider="telegram_bot",
                            provider_message_id=";".join(provider_message_ids),
                            error=provider_error,
                            retry_after_seconds=retry_after,
                            metadata=_merge_result_metadata(
                                route_metadata,
                                _provider_response_metadata(response_data, status_code=last_status_code),
                                _multipart_progress_metadata(
                                    provider="telegram_bot",
                                    body=delivery_body,
                                    total_parts=len(parts),
                                    completed_parts=completed_parts,
                                ) if len(parts) > 1 else None,
                            ),
                        )
                    provider_message_id = _provider_message_id_from_response(
                        channel="telegram",
                        fallback=f"telegram:{message_id}:file:{index}",
                        data=response_data,
                    )
                    provider_message_ids.append(provider_message_id)
                    uploaded_items.append({
                        "filename": attachment.filename,
                        "contentType": attachment.content_type,
                        "size": attachment.size,
                        "status": "uploaded",
                        "providerMessageId": provider_message_id,
                    })
                attachment_delivery_metadata = _attachment_delivery_metadata(
                    provider="telegram_bot",
                    uploaded=uploaded_items,
                    skipped=skipped_attachments,
                )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider="telegram_bot",
            provider_message_id=";".join(provider_message_ids),
            error=str(exc),
            metadata=_merge_result_metadata(
                route_metadata,
                _multipart_progress_metadata(
                    provider="telegram_bot",
                    body=delivery_body,
                    total_parts=len(parts),
                    completed_parts=completed_parts,
                ) if len(parts) > 1 else None,
            ),
        )

    return DeliveryResult(
        status="sent",
        provider="telegram_bot",
        provider_message_id=";".join(provider_message_ids),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(last_response_data, status_code=last_status_code),
            attachment_delivery_metadata,
            _multipart_progress_metadata(
                provider="telegram_bot",
                body=delivery_body,
                total_parts=len(parts),
                completed_parts=completed_parts,
            ) if len(parts) > 1 else None,
        ),
    )


def _send_whatsapp_cloud_reply(
    *,
    message_id: str,
    channel_config: dict[str, Any],
    to_address: str,
    body: str,
    metadata: dict[str, Any],
    secrets: dict[str, str] | None,
) -> DeliveryResult:
    token_env = _whatsapp_access_token_env(channel_config)
    token = _secret_value(token_env, secrets)
    if not token:
        return DeliveryResult(
            status="failed",
            provider="whatsapp",
            error=f"{token_env} is not configured",
        )
    phone_number_id = _whatsapp_phone_number_id(channel_config, secrets)
    if not phone_number_id:
        return DeliveryResult(
            status="failed",
            provider="whatsapp",
            error=f"{_whatsapp_phone_number_id_env(channel_config)} is not configured",
        )
    recipient = _metadata_string(metadata, "chatId", "chat_id", "waId", "wa_id", "senderId", "sender_id", "to") or to_address
    if not recipient:
        return DeliveryResult(
            status="failed",
            provider="whatsapp",
            error="WhatsApp recipient phone number is required",
        )

    api_base = (
        _config_string(
            channel_config,
            "whatsappGraphBaseUrl",
            "whatsapp_graph_base_url",
            "graphApiBaseUrl",
            "graph_api_base_url",
            "apiBaseUrl",
            "api_base_url",
        )
        or WHATSAPP_GRAPH_API_BASE
    )
    url = f"{api_base.rstrip('/')}/{quote(phone_number_id, safe='')}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    delivery_body = _body_with_attachment_notice(body, metadata)
    parts = _limited_text_parts(delivery_body, WHATSAPP_TEXT_LIMIT)
    route_metadata = _delivery_route_metadata(
        provider="whatsapp",
        channel="whatsapp",
        transport="provider_api",
        target_url=url,
        payload_mode="whatsapp",
        metadata=metadata,
        part_count=len(parts),
    )
    completed_parts = _multipart_progress_from_metadata(
        metadata,
        provider="whatsapp",
        body=delivery_body,
        total_parts=len(parts),
    )
    provider_message_ids: list[str] = []
    last_response_data: Any = None
    last_status_code = 0
    try:
        with httpx.Client(timeout=15) as client:
            for index, part in enumerate(parts, start=1):
                if index in completed_parts:
                    provider_message_ids.append(completed_parts[index])
                    continue
                try:
                    response = client.post(
                        url,
                        json=_whatsapp_payload(body=part, metadata={**metadata, "chatId": recipient}, to_address=recipient),
                        headers=headers,
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="whatsapp",
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            _multipart_progress_metadata(
                                provider="whatsapp",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                response_data: Any = _response_data(response)
                last_response_data = response_data
                last_status_code = _response_status_code(response)
                provider_error = _provider_success_error(channel="whatsapp", data=response_data)
                if provider_error:
                    retry_after = _json_retry_after_seconds(response_data)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="whatsapp",
                        provider_message_id=";".join(provider_message_ids),
                        error=provider_error,
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(response_data, status_code=last_status_code),
                            _multipart_progress_metadata(
                                provider="whatsapp",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                fallback = f"whatsapp:{message_id}:{index}" if len(parts) > 1 else f"whatsapp:{message_id}"
                provider_message_ids.append(
                    _provider_message_id_from_response(channel="whatsapp", fallback=fallback, data=response_data)
                )
                completed_parts[index] = provider_message_ids[-1]
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider="whatsapp",
            provider_message_id=";".join(provider_message_ids),
            error=str(exc),
            metadata=_merge_result_metadata(
                route_metadata,
                _multipart_progress_metadata(
                    provider="whatsapp",
                    body=delivery_body,
                    total_parts=len(parts),
                    completed_parts=completed_parts,
                ) if len(parts) > 1 else None,
            ),
        )

    return DeliveryResult(
        status="sent",
        provider="whatsapp",
        provider_message_id=";".join(provider_message_ids),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(last_response_data, status_code=last_status_code),
            _multipart_progress_metadata(
                provider="whatsapp",
                body=delivery_body,
                total_parts=len(parts),
                completed_parts=completed_parts,
            ) if len(parts) > 1 else None,
        ),
    )


def _send_line_reply(
    *,
    message_id: str,
    channel_config: dict[str, Any],
    to_address: str,
    body: str,
    metadata: dict[str, Any],
    secrets: dict[str, str] | None,
) -> DeliveryResult:
    token_env = _line_channel_access_token_env(channel_config)
    token = _secret_value(token_env, secrets)
    if not token:
        return DeliveryResult(
            status="failed",
            provider="line",
            error=f"{token_env} is not configured",
        )
    recipient = _line_reply_target(metadata, to_address)
    if not recipient:
        return DeliveryResult(
            status="failed",
            provider="line",
            error="LINE reply target user, group, or room ID is required",
        )

    api_base = _config_string(channel_config, "lineApiBaseUrl", "line_api_base_url", "apiBaseUrl", "api_base_url") or LINE_API_BASE
    url = f"{api_base.rstrip('/')}/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    delivery_body = _body_with_attachment_notice(body, metadata)
    parts = _limited_text_parts(delivery_body, LINE_TEXT_LIMIT)
    route_metadata = _delivery_route_metadata(
        provider="line",
        channel="line",
        transport="provider_api",
        target_url=url,
        payload_mode="line",
        metadata={**metadata, "chatId": recipient},
        part_count=len(parts),
    )
    completed_parts = _multipart_progress_from_metadata(
        metadata,
        provider="line",
        body=delivery_body,
        total_parts=len(parts),
    )
    provider_message_ids: list[str] = []
    last_response_data: Any = None
    last_status_code = 0
    try:
        with httpx.Client(timeout=15) as client:
            for index, part in enumerate(parts, start=1):
                if index in completed_parts:
                    provider_message_ids.append(completed_parts[index])
                    continue
                try:
                    response = client.post(
                        url,
                        json=_line_push_payload(body=part, metadata={**metadata, "chatId": recipient}, to_address=recipient),
                        headers=headers,
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="line",
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            _multipart_progress_metadata(
                                provider="line",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                response_data: Any = _response_data(response)
                last_response_data = response_data
                last_status_code = _response_status_code(response)
                provider_error = _provider_success_error(channel="line", data=response_data)
                if provider_error:
                    retry_after = _json_retry_after_seconds(response_data)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="line",
                        provider_message_id=";".join(provider_message_ids),
                        error=provider_error,
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(response_data, status_code=last_status_code),
                            _multipart_progress_metadata(
                                provider="line",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                fallback = f"line:{message_id}:{index}" if len(parts) > 1 else f"line:{message_id}"
                provider_message_ids.append(
                    _provider_message_id_from_response(channel="line", fallback=fallback, data=response_data)
                )
                completed_parts[index] = provider_message_ids[-1]
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider="line",
            provider_message_id=";".join(provider_message_ids),
            error=str(exc),
            metadata=_merge_result_metadata(
                route_metadata,
                _multipart_progress_metadata(
                    provider="line",
                    body=delivery_body,
                    total_parts=len(parts),
                    completed_parts=completed_parts,
                ) if len(parts) > 1 else None,
            ),
        )

    return DeliveryResult(
        status="sent",
        provider="line",
        provider_message_id=";".join(provider_message_ids),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(last_response_data, status_code=last_status_code),
            _multipart_progress_metadata(
                provider="line",
                body=delivery_body,
                total_parts=len(parts),
                completed_parts=completed_parts,
            ) if len(parts) > 1 else None,
        ),
    )


def _send_viber_reply(
    *,
    message_id: str,
    channel_config: dict[str, Any],
    to_address: str,
    body: str,
    metadata: dict[str, Any],
    secrets: dict[str, str] | None,
) -> DeliveryResult:
    token_env = _viber_auth_token_env(channel_config)
    token = _secret_value(token_env, secrets)
    if not token:
        return DeliveryResult(
            status="failed",
            provider="viber",
            error=f"{token_env} is not configured",
        )
    recipient = _viber_reply_target(metadata, to_address)
    if not recipient:
        return DeliveryResult(
            status="failed",
            provider="viber",
            error="Viber reply target subscriber ID is required",
        )

    api_base = _config_string(channel_config, "viberApiBaseUrl", "viber_api_base_url", "apiBaseUrl", "api_base_url") or VIBER_API_BASE
    url = f"{api_base.rstrip('/')}/send_message"
    headers = {
        "X-Viber-Auth-Token": token,
        "Content-Type": "application/json",
    }
    sender_name = _config_string(channel_config, "viberSenderName", "viber_sender_name", "senderName", "sender_name") or "Support"
    sender_avatar = _config_string(channel_config, "viberSenderAvatar", "viber_sender_avatar", "senderAvatar", "sender_avatar")
    delivery_body = _body_with_attachment_notice(body, metadata)
    parts = _limited_text_parts(delivery_body, VIBER_TEXT_LIMIT)
    route_metadata = _delivery_route_metadata(
        provider="viber",
        channel="viber",
        transport="provider_api",
        target_url=url,
        payload_mode="viber",
        metadata={**metadata, "chatId": recipient, "viberUserId": recipient},
        part_count=len(parts),
    )
    completed_parts = _multipart_progress_from_metadata(
        metadata,
        provider="viber",
        body=delivery_body,
        total_parts=len(parts),
    )
    provider_message_ids: list[str] = []
    last_response_data: Any = None
    last_status_code = 0
    try:
        with httpx.Client(timeout=15) as client:
            for index, part in enumerate(parts, start=1):
                if index in completed_parts:
                    provider_message_ids.append(completed_parts[index])
                    continue
                try:
                    response = client.post(
                        url,
                        json=_viber_payload(
                            body=part,
                            metadata={**metadata, "chatId": recipient, "viberUserId": recipient},
                            to_address=recipient,
                            sender_name=sender_name,
                            sender_avatar=sender_avatar,
                        ),
                        headers=headers,
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="viber",
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            _multipart_progress_metadata(
                                provider="viber",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                response_data: Any = _response_data(response)
                last_response_data = response_data
                last_status_code = _response_status_code(response)
                provider_error = _provider_success_error(channel="viber", data=response_data)
                if provider_error:
                    retry_after = _json_retry_after_seconds(response_data)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="viber",
                        provider_message_id=";".join(provider_message_ids),
                        error=provider_error,
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(response_data, status_code=last_status_code),
                            _multipart_progress_metadata(
                                provider="viber",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                fallback = f"viber:{message_id}:{index}" if len(parts) > 1 else f"viber:{message_id}"
                provider_message_ids.append(
                    _provider_message_id_from_response(channel="viber", fallback=fallback, data=response_data)
                )
                completed_parts[index] = provider_message_ids[-1]
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider="viber",
            provider_message_id=";".join(provider_message_ids),
            error=str(exc),
            metadata=_merge_result_metadata(
                route_metadata,
                _multipart_progress_metadata(
                    provider="viber",
                    body=delivery_body,
                    total_parts=len(parts),
                    completed_parts=completed_parts,
                ) if len(parts) > 1 else None,
            ),
        )

    return DeliveryResult(
        status="sent",
        provider="viber",
        provider_message_id=";".join(provider_message_ids),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(last_response_data, status_code=last_status_code),
            _multipart_progress_metadata(
                provider="viber",
                body=delivery_body,
                total_parts=len(parts),
                completed_parts=completed_parts,
            ) if len(parts) > 1 else None,
        ),
    )


def _send_messenger_reply(
    *,
    message_id: str,
    channel_config: dict[str, Any],
    to_address: str,
    body: str,
    metadata: dict[str, Any],
    secrets: dict[str, str] | None,
) -> DeliveryResult:
    token_env = _messenger_page_access_token_env(channel_config)
    token = _secret_value(token_env, secrets)
    if not token:
        return DeliveryResult(
            status="failed",
            provider="messenger",
            error=f"{token_env} is not configured",
        )
    page_id = _messenger_page_id(channel_config, secrets)
    if not page_id:
        return DeliveryResult(
            status="failed",
            provider="messenger",
            error=f"{_messenger_page_id_env(channel_config)} is not configured",
        )
    recipient = (
        _metadata_string(metadata, "senderId", "sender_id", "psid", "recipientId", "recipient_id", "chatId", "chat_id")
        or to_address
    )
    if not recipient:
        return DeliveryResult(
            status="failed",
            provider="messenger",
            error="Messenger PSID recipient is required",
        )

    api_base = (
        _config_string(
            channel_config,
            "messengerGraphBaseUrl",
            "messenger_graph_base_url",
            "graphApiBaseUrl",
            "graph_api_base_url",
            "apiBaseUrl",
            "api_base_url",
        )
        or MESSENGER_GRAPH_API_BASE
    )
    url = f"{api_base.rstrip('/')}/{quote(page_id, safe='')}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    delivery_body = _body_with_attachment_notice(body, metadata)
    parts = _limited_text_parts(delivery_body, MESSENGER_TEXT_LIMIT)
    route_metadata = _delivery_route_metadata(
        provider="messenger",
        channel="messenger",
        transport="provider_api",
        target_url=url,
        payload_mode="messenger",
        metadata={**metadata, "senderId": recipient},
        part_count=len(parts),
    )
    completed_parts = _multipart_progress_from_metadata(
        metadata,
        provider="messenger",
        body=delivery_body,
        total_parts=len(parts),
    )
    provider_message_ids: list[str] = []
    last_response_data: Any = None
    last_status_code = 0
    try:
        with httpx.Client(timeout=15) as client:
            for index, part in enumerate(parts, start=1):
                if index in completed_parts:
                    provider_message_ids.append(completed_parts[index])
                    continue
                try:
                    response = client.post(
                        url,
                        json=_messenger_payload(body=part, metadata={**metadata, "senderId": recipient}, to_address=recipient),
                        headers=headers,
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="messenger",
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            _multipart_progress_metadata(
                                provider="messenger",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                response_data: Any = _response_data(response)
                last_response_data = response_data
                last_status_code = _response_status_code(response)
                provider_error = _provider_success_error(channel="messenger", data=response_data)
                if provider_error:
                    retry_after = _json_retry_after_seconds(response_data)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="messenger",
                        provider_message_id=";".join(provider_message_ids),
                        error=provider_error,
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(response_data, status_code=last_status_code),
                            _multipart_progress_metadata(
                                provider="messenger",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                fallback = f"messenger:{message_id}:{index}" if len(parts) > 1 else f"messenger:{message_id}"
                provider_message_ids.append(
                    _provider_message_id_from_response(channel="messenger", fallback=fallback, data=response_data)
                )
                completed_parts[index] = provider_message_ids[-1]
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider="messenger",
            provider_message_id=";".join(provider_message_ids),
            error=str(exc),
            metadata=_merge_result_metadata(
                route_metadata,
                _multipart_progress_metadata(
                    provider="messenger",
                    body=delivery_body,
                    total_parts=len(parts),
                    completed_parts=completed_parts,
                ) if len(parts) > 1 else None,
            ),
        )

    return DeliveryResult(
        status="sent",
        provider="messenger",
        provider_message_id=";".join(provider_message_ids),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(last_response_data, status_code=last_status_code),
            _multipart_progress_metadata(
                provider="messenger",
                body=delivery_body,
                total_parts=len(parts),
                completed_parts=completed_parts,
            ) if len(parts) > 1 else None,
        ),
    )


def _send_instagram_reply(
    *,
    message_id: str,
    channel_config: dict[str, Any],
    to_address: str,
    body: str,
    metadata: dict[str, Any],
    secrets: dict[str, str] | None,
) -> DeliveryResult:
    token_env = _instagram_access_token_env(channel_config)
    token = _secret_value(token_env, secrets)
    if not token:
        return DeliveryResult(
            status="failed",
            provider="instagram",
            error=f"{token_env} is not configured",
        )
    account_id = _instagram_account_id(channel_config, secrets)
    if not account_id:
        return DeliveryResult(
            status="failed",
            provider="instagram",
            error=f"{_instagram_account_id_env(channel_config)} is not configured",
        )
    recipient = _instagram_reply_target(metadata, to_address)
    if not recipient:
        return DeliveryResult(
            status="failed",
            provider="instagram",
            error="Instagram scoped user ID recipient is required",
        )

    api_base = (
        _config_string(
            channel_config,
            "instagramGraphBaseUrl",
            "instagram_graph_base_url",
            "graphApiBaseUrl",
            "graph_api_base_url",
            "apiBaseUrl",
            "api_base_url",
        )
        or INSTAGRAM_GRAPH_API_BASE
    )
    url = f"{api_base.rstrip('/')}/{quote(account_id, safe='')}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    delivery_body = _body_with_attachment_notice(body, metadata)
    parts = _limited_text_parts(delivery_body, INSTAGRAM_TEXT_LIMIT)
    route_metadata = _delivery_route_metadata(
        provider="instagram",
        channel="instagram",
        transport="provider_api",
        target_url=url,
        payload_mode="instagram",
        metadata={**metadata, "senderId": recipient, "instagramAccountId": account_id},
        part_count=len(parts),
    )
    completed_parts = _multipart_progress_from_metadata(
        metadata,
        provider="instagram",
        body=delivery_body,
        total_parts=len(parts),
    )
    provider_message_ids: list[str] = []
    last_response_data: Any = None
    last_status_code = 0
    try:
        with httpx.Client(timeout=15) as client:
            for index, part in enumerate(parts, start=1):
                if index in completed_parts:
                    provider_message_ids.append(completed_parts[index])
                    continue
                try:
                    response = client.post(
                        url,
                        json=_instagram_payload(body=part, metadata={**metadata, "senderId": recipient}, to_address=recipient),
                        headers=headers,
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="instagram",
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            _multipart_progress_metadata(
                                provider="instagram",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                response_data: Any = _response_data(response)
                last_response_data = response_data
                last_status_code = _response_status_code(response)
                provider_error = _provider_success_error(channel="instagram", data=response_data)
                if provider_error:
                    retry_after = _json_retry_after_seconds(response_data)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="instagram",
                        provider_message_id=";".join(provider_message_ids),
                        error=provider_error,
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(response_data, status_code=last_status_code),
                            _multipart_progress_metadata(
                                provider="instagram",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                fallback = f"instagram:{message_id}:{index}" if len(parts) > 1 else f"instagram:{message_id}"
                provider_message_ids.append(
                    _provider_message_id_from_response(channel="instagram", fallback=fallback, data=response_data)
                )
                completed_parts[index] = provider_message_ids[-1]
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider="instagram",
            provider_message_id=";".join(provider_message_ids),
            error=str(exc),
            metadata=_merge_result_metadata(
                route_metadata,
                _multipart_progress_metadata(
                    provider="instagram",
                    body=delivery_body,
                    total_parts=len(parts),
                    completed_parts=completed_parts,
                ) if len(parts) > 1 else None,
            ),
        )

    return DeliveryResult(
        status="sent",
        provider="instagram",
        provider_message_id=";".join(provider_message_ids),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(last_response_data, status_code=last_status_code),
            _multipart_progress_metadata(
                provider="instagram",
                body=delivery_body,
                total_parts=len(parts),
                completed_parts=completed_parts,
            ) if len(parts) > 1 else None,
        ),
    )


def _send_twitter_dm_reply(
    *,
    message_id: str,
    channel_config: dict[str, Any],
    to_address: str,
    body: str,
    metadata: dict[str, Any],
    secrets: dict[str, str] | None,
) -> DeliveryResult:
    token_env = _twitter_user_access_token_env(channel_config)
    token = _secret_value(token_env, secrets)
    if not token:
        return DeliveryResult(
            status="failed",
            provider="twitter",
            error=f"{token_env} is not configured",
        )
    recipient = _twitter_dm_target(metadata, to_address)
    conversation_id = _twitter_dm_conversation_id(metadata)
    if not recipient and not conversation_id:
        return DeliveryResult(
            status="failed",
            provider="twitter",
            error="X user ID or DM conversation ID recipient is required",
        )

    api_base = (
        _config_string(
            channel_config,
            "twitterApiBaseUrl",
            "twitter_api_base_url",
            "xApiBaseUrl",
            "x_api_base_url",
            "apiBaseUrl",
            "api_base_url",
        )
        or X_API_BASE
    )
    if conversation_id:
        url = f"{api_base.rstrip('/')}/2/dm_conversations/{quote(conversation_id, safe='')}/messages"
    else:
        url = f"{api_base.rstrip('/')}/2/dm_conversations/with/{quote(recipient, safe='')}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    delivery_body = _body_with_attachment_notice(body, metadata)
    parts = _limited_text_parts(delivery_body, X_DM_TEXT_LIMIT)
    route_metadata = _delivery_route_metadata(
        provider="twitter",
        channel="twitter",
        transport="provider_api",
        target_url=url,
        payload_mode="twitter",
        metadata={**metadata, "senderId": recipient, "dmConversationId": conversation_id},
        part_count=len(parts),
    )
    completed_parts = _multipart_progress_from_metadata(
        metadata,
        provider="twitter",
        body=delivery_body,
        total_parts=len(parts),
    )
    provider_message_ids: list[str] = []
    last_response_data: Any = None
    last_status_code = 0
    try:
        with httpx.Client(timeout=15) as client:
            for index, part in enumerate(parts, start=1):
                if index in completed_parts:
                    provider_message_ids.append(completed_parts[index])
                    continue
                try:
                    response = client.post(url, json=_twitter_payload(body=part), headers=headers)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="twitter",
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            _multipart_progress_metadata(
                                provider="twitter",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                response_data: Any = _response_data(response)
                last_response_data = response_data
                last_status_code = _response_status_code(response)
                provider_error = _provider_success_error(channel="twitter", data=response_data)
                if provider_error:
                    retry_after = _json_retry_after_seconds(response_data)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="twitter",
                        provider_message_id=";".join(provider_message_ids),
                        error=provider_error,
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(response_data, status_code=last_status_code),
                            _multipart_progress_metadata(
                                provider="twitter",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                fallback = f"twitter:{message_id}:{index}" if len(parts) > 1 else f"twitter:{message_id}"
                provider_message_ids.append(
                    _provider_message_id_from_response(channel="twitter", fallback=fallback, data=response_data)
                )
                completed_parts[index] = provider_message_ids[-1]
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider="twitter",
            provider_message_id=";".join(provider_message_ids),
            error=str(exc),
            metadata=_merge_result_metadata(
                route_metadata,
                _multipart_progress_metadata(
                    provider="twitter",
                    body=delivery_body,
                    total_parts=len(parts),
                    completed_parts=completed_parts,
                ) if len(parts) > 1 else None,
            ),
        )

    return DeliveryResult(
        status="sent",
        provider="twitter",
        provider_message_id=";".join(provider_message_ids),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(last_response_data, status_code=last_status_code),
            _multipart_progress_metadata(
                provider="twitter",
                body=delivery_body,
                total_parts=len(parts),
                completed_parts=completed_parts,
            ) if len(parts) > 1 else None,
        ),
    )


def _send_discord_bot_reply(
    *,
    message_id: str,
    channel_config: dict[str, Any],
    body: str,
    metadata: dict[str, Any],
    secrets: dict[str, str] | None,
) -> DeliveryResult:
    token_env = _discord_bot_token_env(channel_config)
    token = _secret_value(token_env, secrets)
    if not token:
        return DeliveryResult(
            status="failed",
            provider="discord_bot",
            error=f"{token_env} is not configured",
        )
    channel_id = _discord_bot_channel_id(metadata)
    if not channel_id:
        return DeliveryResult(
            status="failed",
            provider="discord_bot",
            error="Discord channelId or threadId is required",
        )

    uploadable_attachments, skipped_attachments, attachment_error = _uploadable_attachments(metadata)
    if attachment_error:
        return DeliveryResult(status="failed", provider="discord_bot", error=attachment_error)

    delivery_body = _body_with_attachment_notice(
        body,
        metadata,
        attachments=skipped_attachments if uploadable_attachments else None,
    )
    api_base = _config_string(channel_config, "discordApiBaseUrl", "discord_api_base_url") or DISCORD_API_BASE
    url = f"{api_base.rstrip('/')}/channels/{quote(channel_id, safe='')}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }
    multipart_headers = {"Authorization": f"Bot {token}"}
    parts = _limited_text_parts(delivery_body, DISCORD_CONTENT_LIMIT) if delivery_body.strip() else [""]
    route_metadata = _delivery_route_metadata(
        provider="discord_bot",
        channel="discord",
        transport="bot_api",
        target_url=url,
        payload_mode="discord",
        metadata=metadata,
        part_count=len(parts),
    )
    completed_parts = _multipart_progress_from_metadata(
        metadata,
        provider="discord_bot",
        body=delivery_body,
        total_parts=len(parts),
    )
    provider_message_ids: list[str] = []
    last_response_data: Any = None
    last_status_code = 0
    attachment_delivery_metadata = _attachment_delivery_metadata(
        provider="discord_bot",
        uploaded=[],
        skipped=skipped_attachments,
    )
    try:
        with httpx.Client(timeout=15) as client:
            for index, part in enumerate(parts, start=1):
                if index in completed_parts:
                    provider_message_ids.append(completed_parts[index])
                    continue
                try:
                    payload = _discord_bot_payload(body=part, metadata=metadata)
                    if uploadable_attachments and index == 1:
                        payload["attachments"] = _discord_payload_attachments(uploadable_attachments)
                        response = client.post(
                            url,
                            data={"payload_json": json.dumps(payload)},
                            files=_multipart_file_parts(uploadable_attachments),
                            headers=multipart_headers,
                        )
                    else:
                        response = client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="discord_bot",
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            _multipart_progress_metadata(
                                provider="discord_bot",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )

                response_data: Any = _response_data(response)
                last_response_data = response_data
                last_status_code = _response_status_code(response)
                if uploadable_attachments and index == 1:
                    attachment_delivery_metadata = _attachment_delivery_metadata(
                        provider="discord_bot",
                        uploaded=_discord_uploaded_attachment_items(uploadable_attachments, response_data),
                        skipped=skipped_attachments,
                    )
                fallback = f"discord:{message_id}:{index}" if len(parts) > 1 else f"discord:{message_id}"
                provider_message_ids.append(
                    _provider_message_id_from_response(
                        channel="discord",
                        fallback=fallback,
                        data=response_data,
                    )
                )
                completed_parts[index] = provider_message_ids[-1]
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider="discord_bot",
            provider_message_id=";".join(provider_message_ids),
            error=str(exc),
            metadata=_merge_result_metadata(
                route_metadata,
                _multipart_progress_metadata(
                    provider="discord_bot",
                    body=delivery_body,
                    total_parts=len(parts),
                    completed_parts=completed_parts,
                ) if len(parts) > 1 else None,
            ),
        )

    return DeliveryResult(
        status="sent",
        provider="discord_bot",
        provider_message_id=";".join(provider_message_ids),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(last_response_data, status_code=last_status_code),
            attachment_delivery_metadata,
            _multipart_progress_metadata(
                provider="discord_bot",
                body=delivery_body,
                total_parts=len(parts),
                completed_parts=completed_parts,
            ) if len(parts) > 1 else None,
        ),
    )


def _send_twilio_sms_reply(
    *,
    message_id: str,
    channel_config: dict[str, Any],
    to_address: str,
    body: str,
    metadata: dict[str, Any],
    secrets: dict[str, str] | None,
) -> DeliveryResult:
    account_sid_env = _twilio_account_sid_env(channel_config)
    auth_token_env = _twilio_auth_token_env(channel_config)
    account_sid = _secret_value(account_sid_env, secrets)
    auth_token = _secret_value(auth_token_env, secrets)
    if not account_sid or not auth_token:
        missing = [name for name, value in ((account_sid_env, account_sid), (auth_token_env, auth_token)) if not value]
        return DeliveryResult(
            status="failed",
            provider="twilio_sms",
            error=f"Twilio credential env missing: {', '.join(missing)}",
        )
    recipient = _metadata_string(metadata, "chatId", "chat_id", "conversationId", "conversation_id", "phone", "to") or to_address
    if not recipient:
        return DeliveryResult(status="failed", provider="twilio_sms", error="SMS reply target phone number is required")
    from_number = _twilio_secret_or_config(
        channel_config,
        secrets,
        direct_keys=("twilioFromNumber", "twilio_from_number", "fromNumber", "from_number"),
        env_name=_twilio_from_number_env(channel_config),
    )
    messaging_service_sid = _twilio_secret_or_config(
        channel_config,
        secrets,
        direct_keys=("twilioMessagingServiceSid", "twilio_messaging_service_sid", "messagingServiceSid", "messaging_service_sid"),
        env_name=_twilio_messaging_service_sid_env(channel_config),
    )
    if not from_number and not messaging_service_sid:
        messaging_service_sid_env = _twilio_messaging_service_sid_env(channel_config)
        return DeliveryResult(
            status="failed",
            provider="twilio_sms",
            error=f"Twilio sender env missing: {_twilio_from_number_env(channel_config)} or {messaging_service_sid_env}",
        )
    api_base = _config_string(channel_config, "twilioApiBaseUrl", "twilio_api_base_url", "apiBaseUrl", "api_base_url") or TWILIO_API_BASE
    url = f"{api_base.rstrip('/')}/2010-04-01/Accounts/{quote(account_sid, safe='')}/Messages.json"
    delivery_body = _body_with_attachment_notice(body, metadata)
    parts = _limited_text_parts(delivery_body, SMS_TEXT_LIMIT)
    route_metadata = _delivery_route_metadata(
        provider="twilio_sms",
        channel="sms",
        transport="provider_api",
        target_url=url,
        payload_mode="twilio",
        metadata=metadata,
        part_count=len(parts),
    )
    completed_parts = _multipart_progress_from_metadata(
        metadata,
        provider="twilio_sms",
        body=delivery_body,
        total_parts=len(parts),
    )
    provider_message_ids: list[str] = []
    last_response_data: Any = None
    last_status_code = 0
    status_callback = _config_string(channel_config, "twilioStatusCallbackUrl", "twilio_status_callback_url", "statusCallbackUrl", "status_callback_url")
    try:
        with httpx.Client(timeout=15) as client:
            for index, part in enumerate(parts, start=1):
                if index in completed_parts:
                    provider_message_ids.append(completed_parts[index])
                    continue
                form_data = {
                    "To": recipient,
                    "Body": part,
                }
                if messaging_service_sid:
                    form_data["MessagingServiceSid"] = messaging_service_sid
                else:
                    form_data["From"] = from_number
                if status_callback:
                    form_data["StatusCallback"] = status_callback
                try:
                    response = client.post(url, data=form_data, auth=(account_sid, auth_token))
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="twilio_sms",
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            _multipart_progress_metadata(
                                provider="twilio_sms",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                response_data: Any = _response_data(response)
                last_response_data = response_data
                last_status_code = _response_status_code(response)
                provider_error = _provider_success_error(channel="sms", data=response_data)
                if provider_error:
                    retry_after = _json_retry_after_seconds(response_data)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider="twilio_sms",
                        provider_message_id=";".join(provider_message_ids),
                        error=provider_error,
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(response_data, status_code=_response_status_code(response)),
                            _multipart_progress_metadata(
                                provider="twilio_sms",
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                fallback = f"twilio:{message_id}:{index}" if len(parts) > 1 else f"twilio:{message_id}"
                provider_message_ids.append(
                    _provider_message_id_from_response(channel="sms", fallback=fallback, data=response_data)
                )
                completed_parts[index] = provider_message_ids[-1]
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider="twilio_sms",
            provider_message_id=";".join(provider_message_ids),
            error=str(exc),
            metadata=_merge_result_metadata(
                route_metadata,
                _multipart_progress_metadata(
                    provider="twilio_sms",
                    body=delivery_body,
                    total_parts=len(parts),
                    completed_parts=completed_parts,
                ) if len(parts) > 1 else None,
            ),
        )
    return DeliveryResult(
        status="sent",
        provider="twilio_sms",
        provider_message_id=";".join(provider_message_ids),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(last_response_data, status_code=last_status_code),
            _multipart_progress_metadata(
                provider="twilio_sms",
                body=delivery_body,
                total_parts=len(parts),
                completed_parts=completed_parts,
            ) if len(parts) > 1 else None,
        ),
    )


def send_support_channel_reply(
    *,
    message_id: str,
    channel: str,
    channel_config: dict[str, Any],
    to_address: str,
    from_address: str,
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
    secrets: dict[str, str] | None = None,
) -> DeliveryResult:
    """Send a non-email reply through a configured channel adapter or provider webhook."""
    webhook_url = _resolve_webhook_url(channel_config, secrets)
    clean_metadata = metadata or {}
    if _slack_bot_transport_enabled(channel, channel_config, webhook_url, secrets):
        return _send_slack_bot_reply(
            message_id=message_id,
            channel_config=channel_config,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )
    if _teams_bot_transport_enabled(channel, channel_config, webhook_url, secrets):
        return _send_teams_bot_reply(
            message_id=message_id,
            channel_config=channel_config,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )
    if _discord_bot_transport_enabled(channel, channel_config, webhook_url, secrets):
        return _send_discord_bot_reply(
            message_id=message_id,
            channel_config=channel_config,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )
    if _telegram_bot_transport_enabled(channel, channel_config, webhook_url, secrets):
        return _send_telegram_bot_reply(
            message_id=message_id,
            channel_config=channel_config,
            to_address=to_address,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )
    if _line_transport_enabled(channel, channel_config, webhook_url, secrets):
        return _send_line_reply(
            message_id=message_id,
            channel_config=channel_config,
            to_address=to_address,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )
    if _viber_transport_enabled(channel, channel_config, webhook_url, secrets):
        return _send_viber_reply(
            message_id=message_id,
            channel_config=channel_config,
            to_address=to_address,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )
    if _whatsapp_transport_enabled(channel, channel_config, webhook_url, secrets):
        return _send_whatsapp_cloud_reply(
            message_id=message_id,
            channel_config=channel_config,
            to_address=to_address,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )
    if _messenger_transport_enabled(channel, channel_config, webhook_url, secrets):
        return _send_messenger_reply(
            message_id=message_id,
            channel_config=channel_config,
            to_address=to_address,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )
    if _instagram_transport_enabled(channel, channel_config, webhook_url, secrets):
        return _send_instagram_reply(
            message_id=message_id,
            channel_config=channel_config,
            to_address=to_address,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )
    if _twitter_transport_enabled(channel, channel_config, webhook_url, secrets):
        return _send_twitter_dm_reply(
            message_id=message_id,
            channel_config=channel_config,
            to_address=to_address,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )
    if _twilio_transport_enabled(channel, channel_config, webhook_url, secrets):
        return _send_twilio_sms_reply(
            message_id=message_id,
            channel_config=channel_config,
            to_address=to_address,
            body=body,
            metadata=clean_metadata,
            secrets=secrets,
        )
    if not webhook_url:
        return DeliveryResult(
            status="failed",
            provider=f"{channel}_webhook",
            error=f"{channel} outbound webhook is not configured",
        )
    token_env = _config_string(channel_config, "outboundWebhookTokenEnv", "outbound_webhook_token_env")
    token = _secret_value(token_env, secrets) if token_env else ""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    attempt_key = _metadata_string(clean_metadata, "deliveryAttemptKey", "delivery_attempt_key")
    if attempt_key:
        headers["Idempotency-Key"] = attempt_key
    mode = _channel_payload_mode(channel, channel_config)
    normalized_mode = _normalized_payload_mode(mode, channel)
    uploadable_attachments: list[DeliveryAttachment] = []
    skipped_attachments: list[dict[str, Any]] = []
    if normalized_mode == "discord":
        uploadable_attachments, skipped_attachments, attachment_error = _uploadable_attachments(clean_metadata)
        if attachment_error:
            return DeliveryResult(status="failed", provider=f"{channel}_webhook", error=attachment_error)
    delivery_body = (
        _body_with_attachment_notice(
            body,
            clean_metadata,
            attachments=skipped_attachments if uploadable_attachments else None,
        )
        if normalized_mode in {"slack", "teams", "discord", "telegram", "line", "viber", "whatsapp", "messenger", "instagram", "twitter", "x"}
        else body
    )
    parts = _limited_text_parts(delivery_body, _provider_text_limit(normalized_mode))
    result_provider = f"{channel}_webhook"
    route_metadata = _delivery_route_metadata(
        provider=result_provider,
        channel=channel,
        transport="webhook",
        target_url=webhook_url,
        payload_mode=normalized_mode,
        metadata=clean_metadata,
        part_count=len(parts),
    )
    completed_parts = _multipart_progress_from_metadata(
        clean_metadata,
        provider=result_provider,
        body=delivery_body,
        total_parts=len(parts),
    )
    provider_message_ids: list[str] = []
    last_response_data: Any = None
    last_status_code = 0
    attachment_delivery_metadata = _attachment_delivery_metadata(
        provider=result_provider,
        uploaded=[],
        skipped=skipped_attachments,
    )
    try:
        with httpx.Client(timeout=15) as client:
            for index, part in enumerate(parts, start=1):
                if index in completed_parts:
                    provider_message_ids.append(completed_parts[index])
                    continue
                payload, query = _channel_payload(
                    mode=mode,
                    message_id=message_id,
                    channel=channel,
                    to_address=to_address,
                    from_address=from_address,
                    subject=subject,
                    body=part,
                    metadata=clean_metadata,
                )
                target_url = _append_query(webhook_url, query)
                try:
                    if normalized_mode == "discord" and uploadable_attachments and index == 1:
                        payload["attachments"] = _discord_payload_attachments(uploadable_attachments)
                        multipart_headers = {
                            key: value
                            for key, value in headers.items()
                            if key.lower() != "content-type"
                        }
                        response = client.post(
                            target_url,
                            data={"payload_json": json.dumps(payload)},
                            files=_multipart_file_parts(uploadable_attachments),
                            headers=multipart_headers,
                        )
                    else:
                        response = client.post(target_url, json=payload, headers=headers)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    retry_after = _transient_http_retry_after(exc.response)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider=result_provider,
                        provider_message_id=";".join(provider_message_ids),
                        error=_http_error_message(exc.response),
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(_response_data(exc.response), status_code=exc.response.status_code),
                            _multipart_progress_metadata(
                                provider=result_provider,
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )

                response_data: Any = _response_data(response)
                last_response_data = response_data
                last_status_code = _response_status_code(response)
                if normalized_mode == "discord" and uploadable_attachments and index == 1:
                    attachment_delivery_metadata = _attachment_delivery_metadata(
                        provider=result_provider,
                        uploaded=_discord_uploaded_attachment_items(uploadable_attachments, response_data),
                        skipped=skipped_attachments,
                    )
                provider_error = _provider_success_error(channel=channel, data=response_data)
                if provider_error:
                    retry_after = _json_retry_after_seconds(response_data)
                    return DeliveryResult(
                        status="queued" if retry_after else "failed",
                        provider=result_provider,
                        provider_message_id=";".join(provider_message_ids),
                        error=provider_error,
                        retry_after_seconds=retry_after,
                        metadata=_merge_result_metadata(
                            route_metadata,
                            _provider_response_metadata(response_data, status_code=_response_status_code(response)),
                            _multipart_progress_metadata(
                                provider=result_provider,
                                body=delivery_body,
                                total_parts=len(parts),
                                completed_parts=completed_parts,
                            ) if len(parts) > 1 else None,
                        ),
                    )
                fallback = f"{channel}:{message_id}:{index}" if len(parts) > 1 else f"{channel}:{message_id}"
                if response_data is None:
                    provider_message_ids.append(fallback)
                else:
                    provider_message_ids.append(
                        _provider_message_id_from_response(
                            channel=channel,
                            fallback=fallback,
                            data=response_data,
                        )
                    )
                completed_parts[index] = provider_message_ids[-1]
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return DeliveryResult(
            status="failed",
            provider=result_provider,
            provider_message_id=";".join(provider_message_ids),
            error=str(exc),
            metadata=_merge_result_metadata(
                route_metadata,
                {
                    "deliveryAttemptKey": attempt_key,
                    "deliveryCertainty": "uncertain",
                },
                _multipart_progress_metadata(
                    provider=result_provider,
                    body=delivery_body,
                    total_parts=len(parts),
                    completed_parts=completed_parts,
                ) if len(parts) > 1 else None,
            ),
        )
    return DeliveryResult(
        status="sent",
        provider=result_provider,
        provider_message_id=";".join(provider_message_ids),
        metadata=_merge_result_metadata(
            route_metadata,
            _provider_response_metadata(last_response_data, status_code=last_status_code),
            attachment_delivery_metadata,
            _multipart_progress_metadata(
                provider=result_provider,
                body=delivery_body,
                total_parts=len(parts),
                completed_parts=completed_parts,
            ) if len(parts) > 1 else None,
        ),
    )
