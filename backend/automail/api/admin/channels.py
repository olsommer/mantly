"""Admin support channel endpoints."""

import asyncio
import base64
import hashlib
import hmac
import html
import json
import math
import os
import re
import shlex
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import Field

from automail.api.admin.deps import AuthDep, ProjectEditorDep, ProjectViewerDep, _require_ctx_capability
from automail.core.runtime_secrets import load_runtime_secrets
from automail.db.pocketbase.client import (
    approve_issue_reply,
    create_issue_reply,
    deliver_issue_reply,
    get_channel,
    get_channel_by_key,
    get_project_secrets,
    ingest_channel_webhook,
    ingest_slack_event,
    ingest_teams_event,
    list_channel_cursors,
    list_channel_sync_runs,
    list_channel_webhook_events,
    list_channels,
    list_crm_connectors,
    list_crm_sync_runs,
    list_crm_webhook_events,
    list_web_chat_sessions,
    record_channel_sync_run,
    record_delivery_run,
    rematch_channel_webhook_event,
    support_launch_proof,
    update_issue,
    update_project_secrets,
    upsert_channel,
    upsert_crm_connector,
)
from automail.models import CamelCaseModel
from automail.support.channel_test_jobs import enqueue_channel_test_message, get_channel_test_job_status
from automail.support.crm import sync_support_crm_connector, sync_support_crm_connectors, validate_crm_connector
from automail.support.delivery import send_support_channel_reply
from automail.support.ingestion import ingest_email_webhook, sync_support_channel, sync_support_channels

router = APIRouter()

CHANNEL_SURFACE_TARGETS: tuple[tuple[str, str], ...] = (
    ("email", "Email"),
    ("chat", "Web chat"),
    ("slack", "Slack"),
    ("discord", "Discord"),
    ("teams", "Teams"),
    ("telegram", "Telegram"),
    ("line", "LINE"),
    ("viber", "Viber"),
    ("whatsapp", "WhatsApp"),
    ("messenger", "Messenger"),
    ("instagram", "Instagram DM"),
    ("twitter", "X DM"),
    ("sms", "SMS"),
    ("webhook", "Webhook"),
)
INITIAL_PROVIDER_SURFACES = {"email", "chat", "slack", "discord"}


class ChannelInput(CamelCaseModel):
    channel_key: str = ""
    type: str
    name: str
    status: str = "active"
    config: dict[str, Any] = Field(default_factory=dict)


class ChannelActivationBootstrapInput(CamelCaseModel):
    surfaces: list[str] | None = None
    status: str = "paused"


class ChannelActivationReadyInput(CamelCaseModel):
    surfaces: list[str] | None = None


class ChannelTestMessageInput(CamelCaseModel):
    body: str = "Test support message"
    author_name: str = "Test customer"
    author_email: str = "customer@example.com"
    author_id: str = "admin-test-customer"
    provider: str = ""
    channel_id: str = ""
    thread_id: str = ""
    message_id: str = ""
    event_id: str = ""
    transport: str = "direct"
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ChannelOutboundSmokeInput(CamelCaseModel):
    body: str = "Test support reply from channel setup."
    to_address: str = ""
    from_address: str = "support-agent@example.com"
    subject: str = "Support reply smoke"
    channel_id: str = ""
    thread_id: str = ""
    message_id: str = ""
    provider_message_id: str = ""
    event_id: str = ""
    conversation_id: str = ""
    reply_to_id: str = ""
    service_url: str = ""


class ChannelLifecycleSmokeInput(CamelCaseModel):
    body: str = "Test support message"
    reply_body: str = "Thanks for reaching out. We are checking this now."
    author_name: str = "Test customer"
    author_email: str = "customer@example.com"
    author_id: str = "admin-test-customer"
    from_address: str = "support-agent@example.com"
    channel_id: str = ""
    thread_id: str = ""
    message_id: str = ""
    event_id: str = ""
    transport: str = "direct"
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    reply_attachments: list[dict[str, Any]] = Field(default_factory=list)


class ChannelWebhookRematchInput(CamelCaseModel):
    outbound_message_id: str = ""


class SmokeHttpTimeoutError(ValueError):
    """The provider-facing HTTP smoke did not finish within its bounded wait."""


class SlackInstallUrlInput(CamelCaseModel):
    channel_key: str = "slack-main"
    name: str = "Slack"
    scopes: str = ""


class TelegramWebhookInput(CamelCaseModel):
    allowed_updates: list[str] = Field(default_factory=lambda: ["message", "edited_message", "channel_post", "edited_channel_post"])
    drop_pending_updates: bool = False


class CrmConnectorInput(CamelCaseModel):
    connector_key: str = ""
    provider: str
    name: str
    status: str = "active"
    config: dict[str, Any] = Field(default_factory=dict)


def _config_text(config: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = config.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _base_url(request: Request) -> str:
    explicit = os.getenv("PUBLIC_URL", "").strip() or os.getenv("API_PUBLIC_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}".rstrip("/")


def _scoped_query(ctx: ProjectViewerDep) -> str:
    params = {"project_id": ctx.project_id}
    if ctx.tenant_id:
        params["tenant_id"] = ctx.tenant_id
    return urlencode(params)


def _url(request: Request, path: str, query: str) -> str:
    return f"{_base_url(request)}{path}?{query}" if query else f"{_base_url(request)}{path}"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _slack_oauth_secret(secrets: dict[str, str] | None, *names: str) -> str:
    for name in names:
        value = _secret_value(name, secrets)
        if value:
            return value
    return ""


def _slack_oauth_redirect_uri(request: Request, project_id: str) -> str:
    return f"{_base_url(request)}/api/admin/projects/{quote(project_id, safe='')}/channels/slack/oauth/callback"


def _slack_oauth_state_secret(secrets: dict[str, str] | None) -> str:
    return _slack_oauth_secret(
        secrets,
        "SUPPORT_SLACK_OAUTH_STATE_SECRET",
        "SUPPORT_SLACK_CLIENT_SECRET",
        "SLACK_CLIENT_SECRET",
    )


def _telegram_bot_token_env(config: dict[str, Any]) -> str:
    token_env = str(config.get("botTokenEnv") or config.get("bot_token_env") or "").strip()
    if token_env:
        return token_env
    template = str(config.get("outboundWebhookUrlTemplate") or config.get("outbound_webhook_url_template") or "").strip()
    return next(iter(_template_secret_names(template)), "SUPPORT_TELEGRAM_BOT_TOKEN")


def _slack_bot_token_env(config: dict[str, Any]) -> str:
    return str(
        config.get("slackBotTokenEnv")
        or config.get("slack_bot_token_env")
        or config.get("botTokenEnv")
        or config.get("bot_token_env")
        or config.get("outboundWebhookTokenEnv")
        or config.get("outbound_webhook_token_env")
        or "SUPPORT_SLACK_BOT_TOKEN"
    ).strip() or "SUPPORT_SLACK_BOT_TOKEN"


def _discord_bot_token_env(config: dict[str, Any]) -> str:
    return str(
        config.get("discordBotTokenEnv")
        or config.get("discord_bot_token_env")
        or config.get("botTokenEnv")
        or config.get("bot_token_env")
        or "SUPPORT_DISCORD_BOT_TOKEN"
    ).strip() or "SUPPORT_DISCORD_BOT_TOKEN"


def _discord_uses_bot_outbound(config: dict[str, Any]) -> bool:
    transport = str(config.get("outboundTransport") or config.get("outbound_transport") or "").strip().lower()
    return transport in {"bot", "discord_bot", "bot_api", "provider_api"}


def _slack_uses_bot_outbound(config: dict[str, Any]) -> bool:
    transport = str(config.get("outboundTransport") or config.get("outbound_transport") or "").strip().lower()
    return transport in {"bot", "slack_bot", "bot_api", "provider_api"}


def _telegram_uses_bot_outbound(config: dict[str, Any]) -> bool:
    transport = str(config.get("outboundTransport") or config.get("outbound_transport") or "").strip().lower()
    return transport in {"bot", "telegram_bot", "bot_api", "provider_api"}


def _has_outbound_webhook(config: dict[str, Any], secrets: dict[str, str] | None) -> bool:
    return bool(
        config.get("outboundWebhookUrl")
        or config.get("outbound_webhook_url")
        or _resolved_outbound_url(config, secrets)
    )


def _telegram_secret_token_env(config: dict[str, Any]) -> str:
    return str(
        config.get("telegramSecretTokenEnv")
        or config.get("telegram_secret_token_env")
        or config.get("secretTokenEnv")
        or config.get("secret_token_env")
        or "SUPPORT_TELEGRAM_SECRET_TOKEN"
    ).strip() or "SUPPORT_TELEGRAM_SECRET_TOKEN"


def _whatsapp_access_token_env(config: dict[str, Any]) -> str:
    return str(
        config.get("whatsappAccessTokenEnv")
        or config.get("whatsapp_access_token_env")
        or config.get("accessTokenEnv")
        or config.get("access_token_env")
        or config.get("outboundWebhookTokenEnv")
        or config.get("outbound_webhook_token_env")
        or "SUPPORT_WHATSAPP_ACCESS_TOKEN"
    ).strip() or "SUPPORT_WHATSAPP_ACCESS_TOKEN"


def _whatsapp_phone_number_id_env(config: dict[str, Any]) -> str:
    return str(
        config.get("phoneNumberIdEnv")
        or config.get("phone_number_id_env")
        or "SUPPORT_WHATSAPP_PHONE_NUMBER_ID"
    ).strip() or "SUPPORT_WHATSAPP_PHONE_NUMBER_ID"


def _whatsapp_phone_number_id(config: dict[str, Any], secrets: dict[str, str] | None) -> tuple[str, str]:
    direct = str(config.get("phoneNumberId") or config.get("phone_number_id") or "").strip()
    if direct:
        return direct, ""
    env_name = _whatsapp_phone_number_id_env(config)
    return _secret_value(env_name, secrets), env_name


def _messenger_page_access_token_env(config: dict[str, Any]) -> str:
    return str(
        config.get("messengerPageAccessTokenEnv")
        or config.get("messenger_page_access_token_env")
        or config.get("pageAccessTokenEnv")
        or config.get("page_access_token_env")
        or config.get("accessTokenEnv")
        or config.get("access_token_env")
        or config.get("outboundWebhookTokenEnv")
        or config.get("outbound_webhook_token_env")
        or "SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN"
    ).strip() or "SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN"


def _messenger_page_id_env(config: dict[str, Any]) -> str:
    return str(
        config.get("messengerPageIdEnv")
        or config.get("messenger_page_id_env")
        or config.get("pageIdEnv")
        or config.get("page_id_env")
        or "SUPPORT_MESSENGER_PAGE_ID"
    ).strip() or "SUPPORT_MESSENGER_PAGE_ID"


def _messenger_page_id(config: dict[str, Any], secrets: dict[str, str] | None) -> tuple[str, str]:
    direct = str(config.get("messengerPageId") or config.get("messenger_page_id") or config.get("pageId") or config.get("page_id") or "").strip()
    if direct:
        return direct, ""
    env_name = _messenger_page_id_env(config)
    return _secret_value(env_name, secrets), env_name


def _instagram_access_token_env(config: dict[str, Any]) -> str:
    return str(
        config.get("instagramAccessTokenEnv")
        or config.get("instagram_access_token_env")
        or config.get("pageAccessTokenEnv")
        or config.get("page_access_token_env")
        or config.get("accessTokenEnv")
        or config.get("access_token_env")
        or "SUPPORT_INSTAGRAM_ACCESS_TOKEN"
    ).strip() or "SUPPORT_INSTAGRAM_ACCESS_TOKEN"


def _instagram_account_id_env(config: dict[str, Any]) -> str:
    return str(
        config.get("instagramAccountIdEnv")
        or config.get("instagram_account_id_env")
        or config.get("businessAccountIdEnv")
        or config.get("business_account_id_env")
        or "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID"
    ).strip() or "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID"


def _instagram_account_id(config: dict[str, Any], secrets: dict[str, str] | None) -> tuple[str, str]:
    direct = str(
        config.get("instagramAccountId")
        or config.get("instagram_account_id")
        or config.get("businessAccountId")
        or config.get("business_account_id")
        or ""
    ).strip()
    if direct:
        return direct, ""
    env_name = _instagram_account_id_env(config)
    return _secret_value(env_name, secrets), env_name


def _twitter_consumer_secret_env(config: dict[str, Any]) -> str:
    return str(
        config.get("twitterConsumerSecretEnv")
        or config.get("twitter_consumer_secret_env")
        or config.get("xConsumerSecretEnv")
        or config.get("x_consumer_secret_env")
        or config.get("consumerSecretEnv")
        or config.get("consumer_secret_env")
        or "SUPPORT_X_CONSUMER_SECRET"
    ).strip() or "SUPPORT_X_CONSUMER_SECRET"


def _twitter_bearer_token_env(config: dict[str, Any]) -> str:
    return str(
        config.get("twitterBearerTokenEnv")
        or config.get("twitter_bearer_token_env")
        or config.get("xBearerTokenEnv")
        or config.get("x_bearer_token_env")
        or config.get("bearerTokenEnv")
        or config.get("bearer_token_env")
        or "SUPPORT_X_BEARER_TOKEN"
    ).strip() or "SUPPORT_X_BEARER_TOKEN"


def _twitter_user_access_token_env(config: dict[str, Any]) -> str:
    return str(
        config.get("twitterUserAccessTokenEnv")
        or config.get("twitter_user_access_token_env")
        or config.get("xUserAccessTokenEnv")
        or config.get("x_user_access_token_env")
        or config.get("userAccessTokenEnv")
        or config.get("user_access_token_env")
        or "SUPPORT_X_USER_ACCESS_TOKEN"
    ).strip() or "SUPPORT_X_USER_ACCESS_TOKEN"


def _twitter_user_id_env(config: dict[str, Any]) -> str:
    return str(
        config.get("twitterUserIdEnv")
        or config.get("twitter_user_id_env")
        or config.get("xUserIdEnv")
        or config.get("x_user_id_env")
        or config.get("userIdEnv")
        or config.get("user_id_env")
        or "SUPPORT_X_USER_ID"
    ).strip() or "SUPPORT_X_USER_ID"


def _twitter_user_id(config: dict[str, Any], secrets: dict[str, str] | None) -> tuple[str, str]:
    direct = str(
        config.get("twitterUserId")
        or config.get("twitter_user_id")
        or config.get("xUserId")
        or config.get("x_user_id")
        or config.get("userId")
        or config.get("user_id")
        or ""
    ).strip()
    if direct:
        return direct, ""
    env_name = _twitter_user_id_env(config)
    return _secret_value(env_name, secrets), env_name


def _line_channel_secret_env(config: dict[str, Any]) -> str:
    return str(
        config.get("lineChannelSecretEnv")
        or config.get("line_channel_secret_env")
        or config.get("channelSecretEnv")
        or config.get("channel_secret_env")
        or "SUPPORT_LINE_CHANNEL_SECRET"
    ).strip() or "SUPPORT_LINE_CHANNEL_SECRET"


def _line_channel_access_token_env(config: dict[str, Any]) -> str:
    return str(
        config.get("lineChannelAccessTokenEnv")
        or config.get("line_channel_access_token_env")
        or config.get("channelAccessTokenEnv")
        or config.get("channel_access_token_env")
        or config.get("accessTokenEnv")
        or config.get("access_token_env")
        or config.get("outboundWebhookTokenEnv")
        or config.get("outbound_webhook_token_env")
        or "SUPPORT_LINE_CHANNEL_ACCESS_TOKEN"
    ).strip() or "SUPPORT_LINE_CHANNEL_ACCESS_TOKEN"


def _viber_auth_token_env(config: dict[str, Any]) -> str:
    return str(
        config.get("viberAuthTokenEnv")
        or config.get("viber_auth_token_env")
        or config.get("authTokenEnv")
        or config.get("auth_token_env")
        or config.get("accessTokenEnv")
        or config.get("access_token_env")
        or config.get("outboundWebhookTokenEnv")
        or config.get("outbound_webhook_token_env")
        or "SUPPORT_VIBER_AUTH_TOKEN"
    ).strip() or "SUPPORT_VIBER_AUTH_TOKEN"


def _twilio_account_sid_env(config: dict[str, Any]) -> str:
    return str(
        config.get("twilioAccountSidEnv")
        or config.get("twilio_account_sid_env")
        or config.get("accountSidEnv")
        or config.get("account_sid_env")
        or "SUPPORT_TWILIO_ACCOUNT_SID"
    ).strip() or "SUPPORT_TWILIO_ACCOUNT_SID"


def _twilio_auth_token_env(config: dict[str, Any]) -> str:
    return str(
        config.get("twilioAuthTokenEnv")
        or config.get("twilio_auth_token_env")
        or config.get("authTokenEnv")
        or config.get("auth_token_env")
        or "SUPPORT_TWILIO_AUTH_TOKEN"
    ).strip() or "SUPPORT_TWILIO_AUTH_TOKEN"


def _twilio_from_number_env(config: dict[str, Any]) -> str:
    return str(
        config.get("twilioFromNumberEnv")
        or config.get("twilio_from_number_env")
        or config.get("fromNumberEnv")
        or config.get("from_number_env")
        or "SUPPORT_TWILIO_FROM_NUMBER"
    ).strip() or "SUPPORT_TWILIO_FROM_NUMBER"


def _twilio_messaging_service_sid_env(config: dict[str, Any]) -> str:
    return str(
        config.get("twilioMessagingServiceSidEnv")
        or config.get("twilio_messaging_service_sid_env")
        or config.get("messagingServiceSidEnv")
        or config.get("messaging_service_sid_env")
        or "SUPPORT_TWILIO_MESSAGING_SERVICE_SID"
    ).strip() or "SUPPORT_TWILIO_MESSAGING_SERVICE_SID"


def _twilio_config_or_secret(
    config: dict[str, Any],
    secrets: dict[str, str] | None,
    *,
    direct_keys: tuple[str, ...],
    env_name: str,
) -> str:
    for key in direct_keys:
        value = str(config.get(key) or "").strip()
        if value:
            return value
    return _secret_value(env_name, secrets) if env_name else ""


def _twilio_sender(config: dict[str, Any], secrets: dict[str, str] | None) -> tuple[str, str, str, str]:
    from_env = _twilio_from_number_env(config)
    service_env = _twilio_messaging_service_sid_env(config)
    from_number = _twilio_config_or_secret(
        config,
        secrets,
        direct_keys=("twilioFromNumber", "twilio_from_number", "fromNumber", "from_number"),
        env_name=from_env,
    )
    service_sid = _twilio_config_or_secret(
        config,
        secrets,
        direct_keys=("twilioMessagingServiceSid", "twilio_messaging_service_sid", "messagingServiceSid", "messaging_service_sid"),
        env_name=service_env,
    )
    return from_number, from_env, service_sid, service_env


def _twilio_uses_provider_outbound(config: dict[str, Any]) -> bool:
    transport = str(config.get("outboundTransport") or config.get("outbound_transport") or "").strip().lower()
    payload_mode = str(
        config.get("outboundPayloadMode")
        or config.get("outbound_payload_mode")
        or config.get("payloadMode")
        or config.get("payload_mode")
        or ""
    ).strip().lower()
    return transport in {"sms", "twilio", "twilio_sms", "provider_api"} or payload_mode in {"sms", "twilio", "provider"}


PROVIDER_SIGNATURE_SECRET_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "teams": ("teamsSigningSecretEnv", "teams_signing_secret_env"),
    "discord": ("discordSigningSecretEnv", "discord_signing_secret_env"),
    "telegram": ("telegramSigningSecretEnv", "telegram_signing_secret_env"),
    "line": ("lineChannelSecretEnv", "line_channel_secret_env", "channelSecretEnv", "channel_secret_env"),
    "viber": ("viberAuthTokenEnv", "viber_auth_token_env", "authTokenEnv", "auth_token_env"),
    "whatsapp": ("whatsappSigningSecretEnv", "whatsapp_signing_secret_env", "appSecretEnv", "app_secret_env"),
    "messenger": ("messengerSigningSecretEnv", "messenger_signing_secret_env", "appSecretEnv", "app_secret_env"),
    "facebook_messenger": ("messengerSigningSecretEnv", "messenger_signing_secret_env", "appSecretEnv", "app_secret_env"),
    "instagram": ("instagramSigningSecretEnv", "instagram_signing_secret_env", "appSecretEnv", "app_secret_env"),
    "twitter": (
        "twitterConsumerSecretEnv",
        "twitter_consumer_secret_env",
        "xConsumerSecretEnv",
        "x_consumer_secret_env",
        "consumerSecretEnv",
        "consumer_secret_env",
    ),
    "x": (
        "twitterConsumerSecretEnv",
        "twitter_consumer_secret_env",
        "xConsumerSecretEnv",
        "x_consumer_secret_env",
        "consumerSecretEnv",
        "consumer_secret_env",
    ),
    "sms": ("twilioSigningSecretEnv", "twilio_signing_secret_env", "smsSigningSecretEnv", "sms_signing_secret_env"),
    "twilio": ("twilioSigningSecretEnv", "twilio_signing_secret_env", "smsSigningSecretEnv", "sms_signing_secret_env"),
}


def _provider_signature_secret_env(
    config: dict[str, Any],
    provider: str,
    *,
    default_env: str,
    default_configured: bool,
) -> tuple[str, bool, str]:
    for key in (
        *PROVIDER_SIGNATURE_SECRET_CONFIG_KEYS.get(provider.strip().lower(), ()),
        "signatureSecretEnv",
        "webhookSignatureSecretEnv",
        "signature_secret_env",
    ):
        env_name = str(config.get(key) or "").strip()
        if env_name:
            return env_name, True, key
    return default_env, default_configured, "signatureSecretEnv"


def _signature_timestamp_config(config: dict[str, Any]) -> tuple[bool, str, int]:
    required = _config_bool(
        config,
        "signatureTimestampRequired",
        "signature_timestamp_required",
        "signatureReplayProtection",
        "signature_replay_protection",
    )
    header = str(
        config.get("signatureTimestampHeader")
        or config.get("signature_timestamp_header")
        or "X-Support-Signature-Timestamp"
    ).strip() or "X-Support-Signature-Timestamp"
    tolerance = _config_int(
        config,
        "signatureToleranceSeconds",
        "signature_tolerance_seconds",
        "signatureTimestampToleranceSeconds",
        "signature_timestamp_tolerance_seconds",
        default=300,
    )
    return required, header, tolerance


def _validate_telegram_secret_token(secret_token: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret_token):
        raise HTTPException(
            status_code=400,
            detail="Telegram secret token must be 1-256 chars using A-Z, a-z, 0-9, _ or -",
        )


def _sign_slack_oauth_state(payload: dict[str, Any], secret: str) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = _b64url_encode(raw)
    signature = _b64url_encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def _unsigned_slack_oauth_state(state: str) -> dict[str, Any]:
    try:
        body, _signature = state.split(".", 1)
        decoded = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid Slack OAuth state") from exc
    return decoded if isinstance(decoded, dict) else {}


def _verify_slack_oauth_state(state: str, secret: str) -> dict[str, Any]:
    if not secret:
        raise ValueError("Slack OAuth state secret is not configured")
    try:
        body, signature = state.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid Slack OAuth state") from exc
    expected = _b64url_encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid Slack OAuth state")
    payload = _unsigned_slack_oauth_state(state)
    try:
        expires_at = datetime.fromisoformat(str(payload.get("expiresAt") or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid Slack OAuth state expiry") from exc
    if expires_at < datetime.now(timezone.utc):
        raise ValueError("Slack OAuth state expired")
    return payload


def _config_bool(config: dict[str, Any], *keys: str, default: bool = False) -> bool:
    for key in keys:
        if key not in config:
            continue
        value = config.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        raw = str(value).strip().lower()
        if raw in {"1", "true", "yes", "on", "enabled"}:
            return True
        if raw in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def _config_int(config: dict[str, Any], *keys: str, default: int) -> int:
    for key in keys:
        if key not in config:
            continue
        try:
            value = int(config.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return default


def _env_present(env_name: str, secrets: dict[str, str] | None = None) -> bool:
    if not env_name:
        return False
    if secrets and str(secrets.get(env_name, "")).strip():
        return True
    return bool(os.getenv(env_name, "").strip())


def _secret_value(env_name: str, secrets: dict[str, str] | None = None) -> str:
    clean_name = env_name.strip()
    if not clean_name:
        return ""
    if secrets:
        secret_value = str(secrets.get(clean_name) or "").strip()
        if secret_value:
            return secret_value
    return os.getenv(clean_name, "").strip()


def _env_status(
    env_name: str,
    purpose: str,
    *,
    required: bool = False,
    secrets: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "name": env_name,
        "purpose": purpose,
        "required": required,
        "configured": _env_present(env_name, secrets),
    }


_SECRET_PLACEHOLDER_RE = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")


def _template_secret_names(template: str) -> list[str]:
    names: list[str] = []
    seen = set()
    for match in _SECRET_PLACEHOLDER_RE.finditer(template):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _template_ready(template: str, secrets: dict[str, str] | None) -> bool:
    if not template:
        return False
    names = _template_secret_names(template)
    if not names:
        return True
    return all(_env_present(name, secrets) for name in names)


def _resolve_secret_template(template: str, secrets: dict[str, str] | None) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return _secret_value(key, secrets) or match.group(0)

    return re.sub(r"\{([^}]+)\}", replace, template)


def _resolved_outbound_url(config: dict[str, Any], secrets: dict[str, str] | None) -> str:
    webhook_url_env = str(config.get("outboundWebhookUrlEnv") or config.get("outbound_webhook_url_env") or "").strip()
    webhook_url = str(config.get("outboundWebhookUrl") or config.get("outbound_webhook_url") or "").strip()
    if webhook_url_env:
        webhook_url = _secret_value(webhook_url_env, secrets) or webhook_url
    if webhook_url:
        return webhook_url
    template = str(config.get("outboundWebhookUrlTemplate") or config.get("outbound_webhook_url_template") or "").strip()
    if not template:
        return ""
    resolved = _resolve_secret_template(template, secrets).strip()
    return "" if "{" in resolved or "}" in resolved else resolved


def _provider_name(channel_type: str) -> str:
    labels = {
        "email": "Email",
        "slack": "Slack",
        "teams": "Teams",
        "discord": "Discord",
        "telegram": "Telegram",
        "line": "LINE",
        "viber": "Viber",
        "whatsapp": "WhatsApp",
        "messenger": "Facebook Messenger",
        "facebook_messenger": "Facebook Messenger",
        "instagram": "Instagram DM",
        "twitter": "X DM",
        "x": "X DM",
        "sms": "SMS",
        "chat": "Web chat",
        "web_chat": "Web chat",
        "webhook": "Webhook",
    }
    return labels.get(channel_type, channel_type.title() if channel_type else "Channel")


def _provider_steps(channel_type: str, config: dict[str, Any] | None = None) -> list[str]:
    config = config if isinstance(config, dict) else {}
    if channel_type == "email":
        return [
            "Configure IMAP polling or point an inbound email gateway at the email webhook URL.",
            "Send a real customer email through the configured surface and confirm a ticket appears in Inbox.",
            "Configure SMTP or an email outbound webhook adapter for replies, then run delivery proof.",
        ]
    if channel_type == "slack":
        return [
            "Create a Slack app and subscribe it to message events.",
            "Set the Slack event request URL to the provider webhook URL.",
            "Configure Slack signing secret or webhook token env.",
            "Set the Slack bot token env for outbound replies.",
            "Send a test message from this page and open the created ticket.",
        ]
    if channel_type == "teams":
        return [
            "Create a Teams bot or Graph change notification bridge.",
            "Set the Teams notification URL to the provider webhook URL.",
            "Configure the Teams webhook token env or per-channel HMAC secret.",
            "Send a test message from this page and open the created ticket.",
        ]
    if channel_type == "discord":
        if _discord_uses_bot_outbound(config):
            return [
                "Create a Discord bot and enable Guild Messages, Direct Messages, and Message Content intent when message text is required.",
                "Run the Discord Gateway worker or bridge sidecar from the install package.",
                "Set the Discord bot token env for Gateway ingest and replies.",
                "Configure the Discord webhook token env or per-channel HMAC secret for bridge forwarding.",
                "Run lifecycle smoke to confirm Gateway ingest, ticket creation, approval, and bot reply delivery.",
            ]
        return [
            "Forward Discord message events to the provider webhook URL.",
            "Configure Discord webhook token env or per-channel HMAC secret.",
            "Set the outbound Discord execute-webhook URL env for replies.",
            "Send a test message from this page and open the created ticket.",
        ]
    if channel_type == "telegram":
        return [
            "Set the Telegram Bot API webhook URL to the provider webhook URL.",
            "Configure Telegram secret token, webhook token, or per-channel HMAC secret.",
            "Set the Telegram bot token env for outbound replies.",
            "Send a test message from this page and open the created ticket.",
        ]
    if channel_type == "line":
        return [
            "Create a LINE Messaging API channel and set the webhook URL to the provider webhook URL.",
            "Configure the LINE channel secret for X-Line-Signature verification.",
            "Set the LINE channel access token env for outbound replies.",
            "Send a test message from this page and open the created ticket.",
        ]
    if channel_type == "viber":
        return [
            "Create a Viber bot and set the webhook URL with the set_webhook API.",
            "Configure the Viber auth token env for X-Viber-Content-Signature verification.",
            "Use the same Viber auth token env for outbound send_message replies.",
            "Send a test message from this page and open the created ticket.",
        ]
    if channel_type == "whatsapp":
        return [
            "Create a Meta WhatsApp Cloud API app and subscribe it to messages.",
            "Set the callback URL to the provider webhook URL and verify with the configured token.",
            "Configure the app secret signature or webhook token env.",
            "Set the Cloud API messages URL and access token env for outbound replies.",
            "Send a test message from this page and open the created ticket.",
        ]
    if channel_type in {"messenger", "facebook_messenger"}:
        return [
            "Create a Meta app with Messenger webhook subscriptions.",
            "Set the Messenger callback URL to the provider webhook URL and verify with the configured token.",
            "Configure the app secret signature or webhook token env.",
            "Set the Page ID and Page Access Token env for outbound replies.",
            "Send a test message from this page and open the created ticket.",
        ]
    if channel_type == "instagram":
        return [
            "Create a Meta app with Instagram Messaging webhook subscriptions.",
            "Set the Instagram callback URL to the provider webhook URL and verify with the configured token.",
            "Configure the app secret signature or webhook token env.",
            "Set the Instagram account ID and access token env for provider validation.",
            "Send a test DM from this page and open the created ticket.",
        ]
    if channel_type in {"twitter", "x"}:
        return [
            "Create an X developer app with Account Activity API access.",
            "Set the X webhook URL to the provider webhook URL and complete CRC validation with the configured consumer secret.",
            "Subscribe the support account so direct_message_events are delivered.",
            "Configure the X webhook signature secret or bridge token env.",
            "Send a test DM from this page and open the created ticket.",
        ]
    if channel_type == "sms":
        return [
            "Create a Twilio phone number or Messaging Service.",
            "Set the incoming message webhook and status callback URL to the provider webhook URL.",
            "Configure the Twilio webhook token or per-channel HMAC secret for bridge auth.",
            "Set Twilio Account SID, Auth Token, and sender env for outbound replies.",
            "Run lifecycle smoke to confirm SMS ingest, ticket creation, approval, and reply delivery.",
        ]
    if channel_type in {"chat", "web_chat"}:
        return [
            "Install the web chat embed script on the customer-facing site.",
            "Use the hosted web chat URL when an embedded widget is not available.",
            "Send a visitor test message.",
            "Open the created ticket from Inbox.",
        ]
    return [
        "Point the external adapter at the inbound webhook URL.",
        "Configure webhook token env or per-channel HMAC secret.",
        "Send a test message from this page and open the created ticket.",
    ]


def _preset_env(name: str, purpose: str, *, required: bool = False) -> dict[str, Any]:
    return {"name": name, "purpose": purpose, "required": required}


def _channel_preset(channel_type: str) -> dict[str, Any]:
    clean_type = channel_type.strip().lower() or "webhook"
    provider = _provider_name(clean_type)
    key = "web-chat" if clean_type in {"chat", "web_chat"} else f"{clean_type}-main"
    outbound_url_env = f"SUPPORT_{clean_type.upper()}_OUTBOUND_URL".replace("-", "_")
    outbound_token_env = f"SUPPORT_{clean_type.upper()}_OUTBOUND_TOKEN".replace("-", "_")
    preset: dict[str, Any] = {
        "type": clean_type,
        "providerName": provider,
        "name": provider,
        "channelKey": key,
        "ticketCreationMode": "per_message",
        "outboundPayloadMode": "provider" if clean_type in {"slack", "teams", "discord", "telegram", "line", "viber", "whatsapp", "messenger"} else "generic",
        "autoPrepareTriage": True,
        "autoPrepareCustomFields": True,
        "autoPrepareAgentReply": True,
        "autoPrepareAgentReplyOnUpdate": True,
        "agentAutoSend": False,
        "defaultQueueKey": "support",
        "defaultQueueName": "Support",
        "supportDefaults": {
            "ticketCreation": "new_ticket_per_message",
            "autopilotPrep": ["triage", "custom_fields", "approval_draft"],
            "humanReview": True,
        },
        "outboundWebhookUrlEnv": outbound_url_env,
        "outboundWebhookTokenEnv": outbound_token_env,
        "authEnvVars": [
            _preset_env("SUPPORT_CHANNEL_WEBHOOK_TOKEN", "Generic channel webhook token"),
            _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
        ],
        "outboundEnvVars": [
            _preset_env(outbound_url_env, f"{provider} outbound webhook URL"),
            _preset_env(outbound_token_env, f"{provider} outbound webhook token"),
        ],
        "config": {
            "adapter": clean_type,
            "ticketCreationMode": "per_message",
            "outboundPayloadMode": "provider" if clean_type in {"slack", "teams", "discord", "telegram", "line", "viber", "whatsapp", "messenger"} else "generic",
            "autoPrepareTriage": True,
            "autoPrepareCustomFields": True,
            "autoPrepareAgentReply": True,
            "autoPrepareAgentReplyOnUpdate": True,
            "agentAutoSend": False,
            "defaultQueueKey": "support",
            "defaultQueueName": "Support",
            "outboundWebhookUrlEnv": outbound_url_env,
            "outboundWebhookTokenEnv": outbound_token_env,
            "smokeChannelId": "",
            "smokeThreadId": "",
            "smokeProviderMessageId": "",
            "smokeToAddress": "",
            "smokeConversationId": "",
            "smokeReplyToId": "",
            "smokeServiceUrl": "",
        },
        "testMessage": {
            "provider": clean_type,
            "channelId": f"{clean_type}-customer-channel",
            "threadId": "",
            "body": "Customer test message from channel setup.",
        },
    }
    if clean_type == "slack":
        slack_bot_token_env = "SUPPORT_SLACK_BOT_TOKEN"
        preset.update({
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": "",
            "outboundEnvVars": [
                _preset_env(slack_bot_token_env, "Slack bot token with chat:write", required=True),
            ],
        })
        preset["authEnvVars"] = [
            _preset_env("SUPPORT_SLACK_SIGNING_SECRET", "Slack signing secret"),
            _preset_env("SUPPORT_SLACK_WEBHOOK_TOKEN", "Slack webhook token"),
            _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
        ]
        preset["config"].update({
            "teamId": "",
            "workspaceName": "",
            "botUserId": "",
            "userNames": {},
            "slackBotTokenEnv": slack_bot_token_env,
            "outboundTransport": "bot",
            "outboundWebhookTokenEnv": "",
            "outboundTokenRequired": True,
            "smokeChannelId": "",
            "smokeThreadTs": "",
        })
        preset["config"].pop("outboundWebhookUrlEnv", None)
        preset["config"].pop("outboundWebhookUrl", None)
    elif clean_type == "teams":
        teams_app_id_env = "SUPPORT_TEAMS_APP_ID"
        teams_app_password_env = "SUPPORT_TEAMS_APP_PASSWORD"
        preset["authEnvVars"] = [
            _preset_env(teams_app_id_env, "Teams Bot Framework app ID", required=True),
            _preset_env(teams_app_password_env, "Teams Bot Framework app password", required=True),
            _preset_env("SUPPORT_TEAMS_WEBHOOK_TOKEN", "Teams webhook token"),
            _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
        ]
        preset.update({
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": "",
            "outboundEnvVars": [
                _preset_env(teams_app_id_env, "Teams Bot Framework app ID", required=True),
                _preset_env(teams_app_password_env, "Teams Bot Framework app password", required=True),
            ],
        })
        preset["config"].update({
            "teamId": "",
            "teamName": "",
            "botUserId": "",
            "teamsAppIdEnv": teams_app_id_env,
            "teamsAppPasswordEnv": teams_app_password_env,
            "outboundTransport": "bot",
            "outboundWebhookTokenEnv": "",
            "smokeConversationId": "",
            "smokeReplyToId": "",
            "smokeServiceUrl": "",
        })
        preset["config"].pop("outboundWebhookUrlEnv", None)
    elif clean_type == "discord":
        discord_bot_token_env = "SUPPORT_DISCORD_BOT_TOKEN"
        preset["authEnvVars"] = [
            _preset_env(discord_bot_token_env, "Discord bot token for Gateway and replies", required=True),
            _preset_env("SUPPORT_DISCORD_WEBHOOK_TOKEN", "Discord webhook token"),
            _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
        ]
        preset["config"].update({
            "guildId": "",
            "guildName": "",
            "botUserId": "",
            "discordBotTokenEnv": discord_bot_token_env,
            "outboundTransport": "bot",
            "smokeChannelId": "",
            "smokeThreadId": "",
            "smokeProviderMessageId": "",
        })
        preset.update({
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": "",
            "outboundEnvVars": [
                _preset_env(discord_bot_token_env, "Discord bot token with Send Messages", required=True),
            ],
        })
        preset["config"].pop("outboundWebhookUrlEnv", None)
        preset["config"]["outboundWebhookTokenEnv"] = ""
    elif clean_type == "telegram":
        telegram_bot_token_env = "SUPPORT_TELEGRAM_BOT_TOKEN"
        preset["authEnvVars"] = [
            _preset_env("SUPPORT_TELEGRAM_SECRET_TOKEN", "Telegram native secret token"),
            _preset_env("SUPPORT_TELEGRAM_WEBHOOK_TOKEN", "Telegram webhook token"),
            _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
        ]
        preset.update({
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": "",
            "outboundEnvVars": [
                _preset_env(telegram_bot_token_env, "Telegram bot token", required=True),
            ],
        })
        preset["config"].update({
            "botUsername": "",
            "botTokenEnv": telegram_bot_token_env,
            "outboundTransport": "bot",
            "outboundWebhookTokenEnv": "",
            "smokeChatId": "",
            "smokeThreadId": "",
            "smokeProviderMessageId": "",
        })
        preset["config"].pop("outboundWebhookUrlEnv", None)
        preset["config"].pop("outboundWebhookUrlTemplate", None)
    elif clean_type == "line":
        line_channel_secret_env = "SUPPORT_LINE_CHANNEL_SECRET"
        line_access_token_env = "SUPPORT_LINE_CHANNEL_ACCESS_TOKEN"
        preset.update({
            "providerName": "LINE",
            "name": "LINE",
            "channelKey": "line-main",
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": line_access_token_env,
            "outboundPayloadMode": "provider",
            "authEnvVars": [
                _preset_env(line_channel_secret_env, "LINE channel secret for X-Line-Signature", required=True),
                _preset_env("SUPPORT_LINE_WEBHOOK_TOKEN", "LINE bridge webhook token"),
                _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
            ],
            "outboundEnvVars": [
                _preset_env(line_access_token_env, "LINE channel access token", required=True),
            ],
        })
        preset["config"].update({
            "adapter": "line",
            "lineChannelSecretEnv": line_channel_secret_env,
            "lineChannelAccessTokenEnv": line_access_token_env,
            "signatureHeader": "X-Line-Signature",
            "outboundTransport": "line",
            "outboundWebhookTokenEnv": line_access_token_env,
            "outboundPayloadMode": "line",
            "outboundTokenRequired": True,
            "smokeChannelId": "",
            "smokeConversationId": "",
            "smokeToAddress": "",
        })
        preset["config"].pop("outboundWebhookUrlEnv", None)
        preset["config"].pop("outboundWebhookUrlTemplate", None)
    elif clean_type == "viber":
        viber_auth_token_env = "SUPPORT_VIBER_AUTH_TOKEN"
        preset.update({
            "providerName": "Viber",
            "name": "Viber",
            "channelKey": "viber-main",
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": viber_auth_token_env,
            "outboundPayloadMode": "provider",
            "authEnvVars": [
                _preset_env(viber_auth_token_env, "Viber bot auth token for API and X-Viber-Content-Signature", required=True),
                _preset_env("SUPPORT_VIBER_WEBHOOK_TOKEN", "Viber bridge webhook token"),
                _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
            ],
            "outboundEnvVars": [
                _preset_env(viber_auth_token_env, "Viber bot auth token", required=True),
            ],
        })
        preset["config"].update({
            "adapter": "viber",
            "viberAuthTokenEnv": viber_auth_token_env,
            "signatureHeader": "X-Viber-Content-Signature",
            "outboundTransport": "viber",
            "outboundWebhookTokenEnv": viber_auth_token_env,
            "outboundPayloadMode": "viber",
            "outboundTokenRequired": True,
            "viberSenderName": "",
            "viberSenderAvatar": "",
            "smokeChannelId": "",
            "smokeConversationId": "",
            "smokeToAddress": "",
        })
        preset["config"].pop("outboundWebhookUrlEnv", None)
        preset["config"].pop("outboundWebhookUrlTemplate", None)
    elif clean_type == "whatsapp":
        whatsapp_token_env = "SUPPORT_WHATSAPP_ACCESS_TOKEN"
        whatsapp_phone_env = "SUPPORT_WHATSAPP_PHONE_NUMBER_ID"
        preset["authEnvVars"] = [
            _preset_env("SUPPORT_WHATSAPP_VERIFY_TOKEN", "WhatsApp webhook verification token", required=True),
            _preset_env("SUPPORT_WHATSAPP_APP_SECRET", "WhatsApp app secret for X-Hub-Signature-256"),
            _preset_env("SUPPORT_WHATSAPP_WEBHOOK_TOKEN", "WhatsApp bridge webhook token"),
            _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
        ]
        preset.update({
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": whatsapp_token_env,
            "outboundEnvVars": [
                _preset_env(whatsapp_phone_env, "WhatsApp phone number ID", required=True),
                _preset_env(whatsapp_token_env, "WhatsApp Cloud API access token", required=True),
            ],
        })
        preset["config"].update({
            "businessAccountId": "",
            "phoneNumberIdEnv": whatsapp_phone_env,
            "verifyTokenEnv": "SUPPORT_WHATSAPP_VERIFY_TOKEN",
            "whatsappSigningSecretEnv": "SUPPORT_WHATSAPP_APP_SECRET",
            "signatureHeader": "X-Hub-Signature-256",
            "outboundTransport": "whatsapp",
            "outboundWebhookUrlTemplate": f"https://graph.facebook.com/v20.0/{{{whatsapp_phone_env}}}/messages",
            "outboundWebhookTokenEnv": whatsapp_token_env,
            "outboundPayloadMode": "whatsapp",
            "outboundTokenRequired": True,
            "smokeChannelId": "",
            "smokeConversationId": "",
            "smokeToAddress": "",
        })
        preset["config"].pop("outboundWebhookUrlEnv", None)
    elif clean_type == "messenger":
        messenger_token_env = "SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN"
        messenger_page_env = "SUPPORT_MESSENGER_PAGE_ID"
        preset["authEnvVars"] = [
            _preset_env("SUPPORT_MESSENGER_VERIFY_TOKEN", "Messenger webhook verification token", required=True),
            _preset_env("SUPPORT_MESSENGER_APP_SECRET", "Messenger app secret for X-Hub-Signature-256"),
            _preset_env("SUPPORT_MESSENGER_WEBHOOK_TOKEN", "Messenger bridge webhook token"),
            _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
        ]
        preset.update({
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": messenger_token_env,
            "outboundEnvVars": [
                _preset_env(messenger_page_env, "Facebook Page ID", required=True),
                _preset_env(messenger_token_env, "Messenger Page Access Token", required=True),
            ],
        })
        preset["config"].update({
            "pageIdEnv": messenger_page_env,
            "verifyTokenEnv": "SUPPORT_MESSENGER_VERIFY_TOKEN",
            "messengerSigningSecretEnv": "SUPPORT_MESSENGER_APP_SECRET",
            "signatureHeader": "X-Hub-Signature-256",
            "outboundTransport": "messenger",
            "outboundWebhookUrlTemplate": f"https://graph.facebook.com/v20.0/{{{messenger_page_env}}}/messages",
            "outboundWebhookTokenEnv": messenger_token_env,
            "outboundPayloadMode": "messenger",
            "outboundTokenRequired": True,
            "smokeChannelId": "",
            "smokeConversationId": "",
            "smokeToAddress": "",
        })
        preset["config"].pop("outboundWebhookUrlEnv", None)
    elif clean_type == "instagram":
        instagram_token_env = "SUPPORT_INSTAGRAM_ACCESS_TOKEN"
        instagram_account_env = "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID"
        preset.update({
            "providerName": "Instagram DM",
            "name": "Instagram DM",
            "channelKey": "instagram-main",
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": instagram_token_env,
            "outboundPayloadMode": "provider",
            "authEnvVars": [
                _preset_env("SUPPORT_INSTAGRAM_VERIFY_TOKEN", "Instagram webhook verification token", required=True),
                _preset_env("SUPPORT_INSTAGRAM_APP_SECRET", "Instagram app secret for X-Hub-Signature-256"),
                _preset_env("SUPPORT_INSTAGRAM_WEBHOOK_TOKEN", "Instagram bridge webhook token"),
                _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
            ],
            "outboundEnvVars": [
                _preset_env(instagram_account_env, "Instagram business account ID", required=True),
                _preset_env(instagram_token_env, "Instagram access token", required=True),
            ],
        })
        preset["config"].update({
            "adapter": "instagram",
            "instagramAccountIdEnv": instagram_account_env,
            "instagramAccessTokenEnv": instagram_token_env,
            "verifyTokenEnv": "SUPPORT_INSTAGRAM_VERIFY_TOKEN",
            "instagramSigningSecretEnv": "SUPPORT_INSTAGRAM_APP_SECRET",
            "signatureHeader": "X-Hub-Signature-256",
            "outboundTransport": "instagram",
            "outboundWebhookUrlTemplate": f"https://graph.facebook.com/v20.0/{{{instagram_account_env}}}/messages",
            "outboundWebhookTokenEnv": instagram_token_env,
            "outboundPayloadMode": "instagram",
            "outboundTokenRequired": True,
            "smokeChannelId": "",
            "smokeConversationId": "",
            "smokeToAddress": "",
        })
        preset["config"].pop("outboundWebhookUrlEnv", None)
    elif clean_type in {"twitter", "x"}:
        twitter_consumer_secret_env = "SUPPORT_X_CONSUMER_SECRET"
        twitter_bearer_token_env = "SUPPORT_X_BEARER_TOKEN"
        twitter_user_access_token_env = "SUPPORT_X_USER_ACCESS_TOKEN"
        twitter_user_id_env = "SUPPORT_X_USER_ID"
        preset.update({
            "type": "twitter",
            "providerName": "X DM",
            "name": "X DM",
            "channelKey": "twitter-main",
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": twitter_user_access_token_env,
            "outboundPayloadMode": "provider",
            "authEnvVars": [
                _preset_env(twitter_consumer_secret_env, "X API consumer secret for CRC and webhook signatures", required=True),
                _preset_env("SUPPORT_X_WEBHOOK_TOKEN", "X bridge webhook token"),
                _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
            ],
            "outboundEnvVars": [
                _preset_env(twitter_bearer_token_env, "X API bearer token for provider validation", required=True),
                _preset_env(twitter_user_access_token_env, "X user access token for DM sends", required=True),
                _preset_env(twitter_user_id_env, "Subscribed X user ID", required=True),
            ],
        })
        preset["config"].update({
            "adapter": "twitter",
            "twitterConsumerSecretEnv": twitter_consumer_secret_env,
            "twitterBearerTokenEnv": twitter_bearer_token_env,
            "twitterUserAccessTokenEnv": twitter_user_access_token_env,
            "twitterUserIdEnv": twitter_user_id_env,
            "signatureHeader": "x-twitter-webhooks-signature",
            "outboundTransport": "twitter",
            "outboundWebhookTokenEnv": twitter_user_access_token_env,
            "outboundPayloadMode": "twitter",
            "outboundTokenRequired": True,
            "smokeChannelId": "",
            "smokeConversationId": "",
            "smokeToAddress": "",
        })
        preset["config"].pop("outboundWebhookUrlEnv", None)
    elif clean_type == "sms":
        twilio_account_env = "SUPPORT_TWILIO_ACCOUNT_SID"
        twilio_auth_env = "SUPPORT_TWILIO_AUTH_TOKEN"
        twilio_from_env = "SUPPORT_TWILIO_FROM_NUMBER"
        twilio_service_env = "SUPPORT_TWILIO_MESSAGING_SERVICE_SID"
        preset.update({
            "providerName": "SMS",
            "name": "SMS",
            "channelKey": "sms-main",
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": "",
            "outboundPayloadMode": "provider",
            "authEnvVars": [
                _preset_env("SUPPORT_TWILIO_WEBHOOK_TOKEN", "Twilio inbound webhook token"),
                _preset_env("SUPPORT_SYNC_TOKEN", "Fallback support automation token"),
            ],
            "outboundEnvVars": [
                _preset_env(twilio_account_env, "Twilio Account SID", required=True),
                _preset_env(twilio_auth_env, "Twilio Auth Token", required=True),
                _preset_env(twilio_from_env, "Twilio sender phone number"),
                _preset_env(twilio_service_env, "Twilio Messaging Service SID"),
            ],
        })
        preset["config"].update({
            "adapter": "sms",
            "provider": "twilio",
            "accountSidEnv": twilio_account_env,
            "authTokenEnv": twilio_auth_env,
            "fromNumberEnv": twilio_from_env,
            "messagingServiceSidEnv": twilio_service_env,
            "outboundPayloadMode": "provider",
            "outboundTransport": "twilio",
            "smokeChannelId": "",
            "smokeConversationId": "",
            "smokeToAddress": "",
        })
        preset["config"].pop("outboundWebhookUrlEnv", None)
        preset["config"].pop("outboundWebhookTokenEnv", None)
    elif clean_type == "email":
        preset.update({
            "ticketCreationMode": "per_message",
            "outboundPayloadMode": "generic",
            "outboundWebhookUrlEnv": "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_URL",
            "outboundWebhookTokenEnv": "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_TOKEN",
            "authEnvVars": [_preset_env("SUPPORT_IMAP_PASSWORD", "IMAP password secret")],
            "outboundEnvVars": [
                _preset_env("SMTP_HOST", "SMTP host", required=True),
                _preset_env("SMTP_FROM", "SMTP sender"),
                _preset_env("SMTP_PASSWORD", "SMTP password secret"),
                _preset_env("SUPPORT_EMAIL_OUTBOUND_WEBHOOK_URL", "Email outbound webhook URL"),
                _preset_env("SUPPORT_EMAIL_OUTBOUND_WEBHOOK_TOKEN", "Email outbound webhook token"),
            ],
        })
        preset["config"] = {
            "adapter": "imap",
            "ticketCreationMode": "per_message",
            "outboundPayloadMode": "generic",
            "outboundWebhookUrlEnv": "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_URL",
            "outboundWebhookTokenEnv": "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_TOKEN",
            "autoPrepareTriage": True,
            "autoPrepareCustomFields": True,
            "autoPrepareAgentReply": True,
            "autoPrepareAgentReplyOnUpdate": True,
            "agentAutoSend": False,
            "defaultQueueKey": "support",
            "defaultQueueName": "Support",
            "host": "",
            "port": 993,
            "username": "support@example.com",
            "passwordEnv": "SUPPORT_IMAP_PASSWORD",
            "mailbox": "INBOX",
        }
    elif clean_type in {"chat", "web_chat"}:
        preset.update({
            "type": "chat",
            "providerName": "Web chat",
            "name": "Web chat",
            "channelKey": "web-chat",
            "ticketCreationMode": "per_message",
            "outboundPayloadMode": "generic",
            "outboundWebhookUrlEnv": "",
            "outboundWebhookTokenEnv": "",
            "authEnvVars": [],
            "outboundEnvVars": [],
        })
        preset["config"] = {
            "adapter": "web_chat",
            "ticketCreationMode": "per_message",
            "autoPrepareTriage": True,
            "autoPrepareCustomFields": True,
            "autoPrepareAgentReply": True,
            "autoPrepareAgentReplyOnUpdate": True,
            "agentAutoSend": False,
            "defaultQueueKey": "support",
            "defaultQueueName": "Support",
        }
    return preset


def _setup_step(key: str, label: str, status: str, detail: str = "") -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
    }


def _setup_health_summary(setup: dict[str, Any]) -> dict[str, Any]:
    checklist = setup.get("setupChecklist") if isinstance(setup.get("setupChecklist"), list) else []
    env_vars = setup.get("envVars") if isinstance(setup.get("envVars"), list) else []
    missing_checks = [check for check in checklist if check.get("status") == "missing"]
    warning_checks = [check for check in checklist if check.get("status") == "warning"]
    configured_env = [env for env in env_vars if env.get("configured")]
    missing_env = [env for env in env_vars if not env.get("configured")]
    required_missing_env = [env for env in missing_env if env.get("required")]
    inbound_ready = bool(setup.get("inboundReady"))
    outbound_ready = bool(setup.get("outboundReady"))
    auth_configured = bool(setup.get("authConfigured"))
    ready = inbound_ready and outbound_ready and not missing_checks and not required_missing_env
    if ready:
        status = "ready"
    elif inbound_ready and auth_configured:
        status = "degraded"
    else:
        status = "needs_setup"
    return {
        "status": status,
        "ready": ready,
        "inboundReady": inbound_ready,
        "outboundReady": outbound_ready,
        "authConfigured": auth_configured,
        "checks": len(checklist),
        "missing": len(missing_checks),
        "warnings": len(warning_checks),
        "envConfigured": len(configured_env),
        "envTotal": len(env_vars),
        "envMissing": len(missing_env),
        "missingEnvVars": [env.get("name", "") for env in missing_env if env.get("name")],
        "requiredMissingEnvVars": [env.get("name", "") for env in required_missing_env if env.get("name")],
    }


def _channel_requires_launch_smoke(channel_type: str) -> bool:
    return channel_type not in {"email", "chat", "web_chat"}


def _channel_requires_attachment_lifecycle_smoke(channel_type: str) -> bool:
    return _channel_requires_launch_smoke(channel_type)


def _run_ready_value(run: dict[str, Any]) -> bool:
    result = run.get("result") if isinstance(run.get("result"), dict) else {}
    return result.get("ready") is not False


def _run_processed(run: dict[str, Any]) -> int:
    try:
        return int(run.get("processed") or 0)
    except (TypeError, ValueError):
        return 0


def _run_failed_count(run: dict[str, Any]) -> int:
    try:
        return int(run.get("failed") or 0)
    except (TypeError, ValueError):
        return 0


def _run_result(run: dict[str, Any]) -> dict[str, Any]:
    return run.get("result") if isinstance(run.get("result"), dict) else {}


def _result_text(result: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _run_issue_id(run: dict[str, Any]) -> str:
    result = _run_result(run)
    issue_id = _result_text(result, "issueId", "issue_id")
    if issue_id:
        return issue_id
    inbound = result.get("inbound") if isinstance(result.get("inbound"), dict) else {}
    issue_id = _result_text(inbound, "issueId", "issue_id")
    if issue_id:
        return issue_id
    items = result.get("items") if isinstance(result.get("items"), list) else []
    for item in items:
        if isinstance(item, dict):
            issue_id = _result_text(item, "issueId", "issue_id")
            if issue_id:
                return issue_id
    return ""


def _run_reply_id(run: dict[str, Any]) -> str:
    result = _run_result(run)
    reply_id = _result_text(result, "replyId", "reply_id", "outboundMessageId", "outbound_message_id")
    if reply_id:
        return reply_id
    delivery = result.get("delivery") if isinstance(result.get("delivery"), dict) else {}
    return _result_text(delivery, "id", "replyId", "reply_id", "outboundMessageId", "outbound_message_id")


def _run_provider_message_id(run: dict[str, Any]) -> str:
    result = _run_result(run)
    provider_message_id = _result_text(result, "providerMessageId", "provider_message_id")
    if provider_message_id:
        return provider_message_id
    delivery = result.get("delivery") if isinstance(result.get("delivery"), dict) else {}
    return _result_text(delivery, "providerMessageId", "provider_message_id")


def _run_delivery_metadata(run: dict[str, Any]) -> dict[str, Any]:
    result = _run_result(run)
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    delivery = result.get("delivery") if isinstance(result.get("delivery"), dict) else {}
    delivery_metadata = delivery.get("metadata") if isinstance(delivery.get("metadata"), dict) else {}
    return {**metadata, **delivery_metadata}


def _run_delivery_route(run: dict[str, Any]) -> dict[str, Any]:
    result = _run_result(run)
    route = result.get("deliveryRoute") if isinstance(result.get("deliveryRoute"), dict) else {}
    if route:
        return route
    delivery = result.get("delivery") if isinstance(result.get("delivery"), dict) else {}
    route = delivery.get("deliveryRoute") if isinstance(delivery.get("deliveryRoute"), dict) else {}
    if route:
        return route
    metadata = _run_delivery_metadata(run)
    return metadata.get("deliveryRoute") if isinstance(metadata.get("deliveryRoute"), dict) else {}


def _run_provider_response(run: dict[str, Any]) -> dict[str, Any]:
    result = _run_result(run)
    response = result.get("providerResponse") if isinstance(result.get("providerResponse"), dict) else {}
    if response:
        return response
    delivery = result.get("delivery") if isinstance(result.get("delivery"), dict) else {}
    response = delivery.get("providerResponse") if isinstance(delivery.get("providerResponse"), dict) else {}
    if response:
        return response
    metadata = _run_delivery_metadata(run)
    return metadata.get("providerResponse") if isinstance(metadata.get("providerResponse"), dict) else {}


def _webhook_event_result(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("result") if isinstance(event.get("result"), dict) else {}


def _webhook_event_issue_id(event: dict[str, Any]) -> str:
    result = _webhook_event_result(event)
    issue_id = _result_text(result, "issueId", "issue_id")
    if issue_id:
        return issue_id
    items = result.get("items") if isinstance(result.get("items"), list) else []
    for item in items:
        if isinstance(item, dict):
            issue_id = _result_text(item, "issueId", "issue_id")
            if issue_id:
                return issue_id
    return ""


def _latest_inbound_ticket_webhook_event(
    channel_id: str,
    webhook_events: list[dict[str, Any]],
) -> dict[str, Any]:
    for event in webhook_events:
        if str(event.get("channelId") or event.get("channel") or "").strip() != channel_id:
            continue
        status = str(event.get("status") or "").strip().lower()
        if status not in {"processed", "success"}:
            continue
        result = _webhook_event_result(event)
        if str(result.get("kind") or "").strip() != "inbound_message":
            continue
        if _webhook_event_issue_id(event):
            return event
    return {}


def _inbound_ticket_event_step(event: dict[str, Any]) -> dict[str, Any]:
    issue_id = _webhook_event_issue_id(event)
    return {
        "key": "inbound_ticket_event",
        "label": "Provider message created ticket",
        "status": "done",
        "detail": "A provider webhook message created a support ticket",
        "action": "open_ticket",
        "runId": str(event.get("id") or ""),
        "source": "provider-webhook",
        "runStatus": str(event.get("status") or ""),
        "processed": 1,
        "failed": 0,
        "transport": "webhook",
        "startedAt": str(event.get("receivedAt") or event.get("created") or ""),
        "completedAt": str(event.get("processedAt") or event.get("updated") or ""),
        "provider": str(event.get("provider") or ""),
        "providerMessageId": str(event.get("providerMessageId") or ""),
        "deliveryRoute": {},
        "providerResponse": {},
        "authMode": "",
        "signatureTimestampHeader": "",
        "attachmentCount": 0,
        "fileOnly": False,
        "issueId": issue_id,
        "replyId": "",
    }


def _launch_check_issue_id(check: dict[str, Any]) -> str:
    return str(check.get("issueId") or check.get("issue_id") or "").strip()


def _launch_check_reply_id(check: dict[str, Any]) -> str:
    return str(check.get("replyId") or check.get("reply_id") or "").strip()


def _launch_with_real_channel_handoff(launch: dict[str, Any]) -> dict[str, Any]:
    checklist = launch.get("checklist") if isinstance(launch.get("checklist"), list) else []
    if any(isinstance(item, dict) and item.get("key") == "real_channel_handoff" for item in checklist):
        return launch
    inbound = next(
        (
            item for item in checklist
            if isinstance(item, dict)
            and item.get("key") == "inbound_ticket_event"
            and item.get("status") == "done"
            and _launch_check_issue_id(item)
        ),
        {},
    )
    if not inbound:
        return launch
    issue_id = _launch_check_issue_id(inbound)
    autopilot = next(
        (
            item for item in checklist
            if isinstance(item, dict)
            and item.get("key") == "channel_autopilot"
            and item.get("status") == "done"
            and _launch_check_issue_id(item) == issue_id
            and _launch_check_reply_id(item)
        ),
        {},
    )
    if not autopilot:
        return launch
    step = {
        "key": "real_channel_handoff",
        "label": "Real channel handoff proof",
        "status": "done",
        "detail": "Real provider message created a ticket and channel autopilot prepared the approval draft",
        "action": "open_ticket",
        "runId": str(autopilot.get("runId") or inbound.get("runId") or ""),
        "source": "provider-webhook",
        "runStatus": "prepared",
        "processed": 1,
        "failed": 0,
        "transport": str(inbound.get("transport") or "webhook"),
        "startedAt": str(inbound.get("startedAt") or autopilot.get("startedAt") or ""),
        "completedAt": str(autopilot.get("completedAt") or autopilot.get("startedAt") or ""),
        "provider": str(inbound.get("provider") or ""),
        "providerMessageId": str(inbound.get("providerMessageId") or ""),
        "deliveryRoute": {},
        "providerResponse": {},
        "authMode": str(inbound.get("authMode") or ""),
        "signatureTimestampHeader": str(inbound.get("signatureTimestampHeader") or ""),
        "attachmentCount": int(inbound.get("attachmentCount") or 0),
        "fileOnly": bool(inbound.get("fileOnly")),
        "issueId": issue_id,
        "replyId": _launch_check_reply_id(autopilot),
        "aiRunId": str(autopilot.get("aiRunId") or autopilot.get("ai_run_id") or ""),
    }
    updated_checklist = [step, *checklist]
    blockers = launch.get("blockers") if isinstance(launch.get("blockers"), list) else []
    passed = sum(1 for item in updated_checklist if isinstance(item, dict) and item.get("status") == "done")
    return {
        **launch,
        "checks": len(updated_checklist),
        "passed": passed,
        "missing": sum(1 for item in updated_checklist if isinstance(item, dict) and item.get("status") == "missing"),
        "failed": sum(1 for item in updated_checklist if isinstance(item, dict) and item.get("status") == "warning"),
        "ready": bool(launch.get("ready")) or (passed == len(updated_checklist) and not blockers),
        "lastCheckedAt": max(
            (
                str(item.get("startedAt") or item.get("completedAt") or "")
                for item in updated_checklist
                if isinstance(item, dict)
            ),
            default=str(launch.get("lastCheckedAt") or ""),
        ),
        "checklist": updated_checklist,
    }


def _launch_with_inbound_ticket_event(
    launch: dict[str, Any],
    channel: dict[str, Any],
    webhook_events: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    event = _latest_inbound_ticket_webhook_event(str(channel.get("id") or ""), webhook_events or [])
    if not event:
        return _launch_with_real_channel_handoff(launch)
    checklist = launch.get("checklist") if isinstance(launch.get("checklist"), list) else []
    if any(isinstance(item, dict) and item.get("key") == "inbound_ticket_event" for item in checklist):
        return _launch_with_real_channel_handoff(launch)
    updated_checklist = [_inbound_ticket_event_step(event), *checklist]
    passed = sum(1 for item in updated_checklist if isinstance(item, dict) and item.get("status") == "done")
    missing = sum(1 for item in updated_checklist if isinstance(item, dict) and item.get("status") == "missing")
    failed = sum(1 for item in updated_checklist if isinstance(item, dict) and item.get("status") == "warning")
    blockers = launch.get("blockers") if isinstance(launch.get("blockers"), list) else []
    all_done = passed == len(updated_checklist)
    last_checked = max(
        (
            str(item.get("startedAt") or item.get("completedAt") or "")
            for item in updated_checklist
            if isinstance(item, dict)
        ),
        default=str(launch.get("lastCheckedAt") or ""),
    )
    updated_launch = {
        **launch,
        "checks": len(updated_checklist),
        "passed": passed,
        "missing": missing,
        "failed": failed,
        "ready": bool(launch.get("ready")) or (all_done and not blockers),
        "lastCheckedAt": last_checked,
        "checklist": updated_checklist,
    }
    return _launch_with_real_channel_handoff(updated_launch)


def _run_attachment_count(run: dict[str, Any]) -> int:
    result = _run_result(run)
    value = result.get("attachmentCount") or result.get("attachment_count")
    if value is None:
        inbound = result.get("inbound") if isinstance(result.get("inbound"), dict) else {}
        value = inbound.get("attachmentCount") or inbound.get("attachment_count")
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _run_file_only(run: dict[str, Any]) -> bool:
    result = _run_result(run)
    value = result.get("fileOnly") if "fileOnly" in result else result.get("file_only")
    if value is None:
        inbound = result.get("inbound") if isinstance(result.get("inbound"), dict) else {}
        value = inbound.get("fileOnly") if "fileOnly" in inbound else inbound.get("file_only")
    return bool(value)


def _run_has_attachment_only_proof(run: dict[str, Any]) -> bool:
    return _run_file_only(run) and _run_attachment_count(run) > 0


def _run_has_provider_delivery_proof(run: dict[str, Any]) -> bool:
    return bool(_run_delivery_route(run)) and bool(_run_provider_response(run))


def _provider_delivery_proof_detail(run: dict[str, Any]) -> str:
    has_route = bool(_run_delivery_route(run))
    has_response = bool(_run_provider_response(run))
    if not has_route and not has_response:
        return "Provider delivery did not record delivery route and provider response"
    if not has_route:
        return "Provider delivery did not record delivery route"
    if not has_response:
        return "Provider delivery did not record provider response"
    return ""


def _smoke_transport(run: dict[str, Any]) -> str:
    result = _run_result(run)
    transport = str(result.get("transport") or "").strip().lower()
    if transport:
        return transport
    inbound = result.get("inbound") if isinstance(result.get("inbound"), dict) else {}
    transport = str(inbound.get("transport") or "").strip().lower()
    if transport:
        return transport
    http_result = result.get("http") if isinstance(result.get("http"), dict) else {}
    if http_result:
        return "http"
    return ""


def _smoke_uses_provider_surface(run: dict[str, Any]) -> bool:
    return _smoke_transport(run) == "http"


def _signature_timestamp_required(channel: dict[str, Any]) -> bool:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    return _config_bool(
        config,
        "signatureTimestampRequired",
        "signature_timestamp_required",
        "signatureReplayProtection",
        "signature_replay_protection",
    )


def _signature_auth_mode_required(channel: dict[str, Any], runtime_secrets: dict[str, str] | None = None) -> str:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    channel_type = str(channel.get("type") or "").strip().lower()
    generic_signature = bool(
        config.get("signatureSecretEnv")
        or config.get("webhookSignatureSecretEnv")
        or config.get("signature_secret_env")
    )
    if channel_type == "slack":
        slack_signature_env = str(
            config.get("slackSigningSecretEnv")
            or config.get("slack_signing_secret_env")
            or config.get("signatureSecretEnv")
            or config.get("webhookSignatureSecretEnv")
            or config.get("signature_secret_env")
            or "SUPPORT_SLACK_SIGNING_SECRET"
        ).strip()
        if (
            config.get("slackSigningSecretEnv")
            or config.get("slack_signing_secret_env")
            or generic_signature
            or _env_present(slack_signature_env, runtime_secrets)
        ):
            return "slack_signature"
        return ""
    if channel_type == "telegram":
        provider_keys = PROVIDER_SIGNATURE_SECRET_CONFIG_KEYS.get(channel_type, ())
        if any(str(config.get(key) or "").strip() for key in provider_keys) or generic_signature:
            return "hmac_signature"
        telegram_secret_env = _telegram_secret_token_env(config)
        if _env_present(telegram_secret_env, runtime_secrets):
            return "telegram_secret_token"
        return ""
    if channel_type in {"sms", "twilio"}:
        twilio_auth_token_env = _twilio_auth_token_env(config)
        if _env_present(twilio_auth_token_env, runtime_secrets):
            return "twilio_signature"
        provider_keys = PROVIDER_SIGNATURE_SECRET_CONFIG_KEYS.get(channel_type, ())
        if any(str(config.get(key) or "").strip() for key in provider_keys) or generic_signature:
            return "hmac_signature"
        return ""
    provider_keys = PROVIDER_SIGNATURE_SECRET_CONFIG_KEYS.get(channel_type, ())
    if any(str(config.get(key) or "").strip() for key in provider_keys) or generic_signature:
        return "hmac_signature"
    return ""


def _run_http_auth(run: dict[str, Any]) -> dict[str, Any]:
    result = _run_result(run)
    http_result = result.get("http") if isinstance(result.get("http"), dict) else {}
    inbound = result.get("inbound") if isinstance(result.get("inbound"), dict) else {}
    inbound_http = inbound.get("http") if isinstance(inbound.get("http"), dict) else {}
    for candidate in (
        result.get("auth"),
        http_result.get("auth"),
        inbound_http.get("auth"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def _run_has_timestamp_auth(run: dict[str, Any]) -> bool:
    auth = _run_http_auth(run)
    return bool(str(auth.get("timestampHeader") or auth.get("timestamp_header") or "").strip())


def _run_auth_mode(run: dict[str, Any]) -> str:
    return str(_run_http_auth(run).get("mode") or "").strip().lower()


def _run_has_signature_auth(run: dict[str, Any], required_mode: str) -> bool:
    if not required_mode:
        return True
    return _run_auth_mode(run) == required_mode


def _required_auth_mode_detail(required_mode: str) -> str:
    if required_mode == "telegram_secret_token":
        return "Smoke run did not record required Telegram secret-token auth"
    if required_mode == "twilio_signature":
        return "Smoke run did not record required Twilio signature auth"
    return "Smoke run did not record required signature auth"


def _validation_run_passed(run: dict[str, Any]) -> bool:
    if not run or _run_processed(run) <= 0 or _run_failed_count(run) > 0:
        return False
    result = _run_result(run)
    provider_validation = result.get("providerValidation") if isinstance(result.get("providerValidation"), dict) else {}
    if not provider_validation:
        return False
    if provider_validation.get("checked") is False:
        return False
    status = str(run.get("status") or "").strip().lower()
    return (
        status in {"success", "ready"}
        and result.get("ready") is not False
        and str(provider_validation.get("status") or "").strip().lower() == "ready"
    )


def _smoke_run_passed(
    run: dict[str, Any],
    *,
    delivery_required: bool = False,
    provider_surface_required: bool = False,
    issue_required: bool = False,
    reply_required: bool = False,
    provider_message_required: bool = False,
    provider_delivery_proof_required: bool = False,
    attachment_only_required: bool = False,
    signature_auth_mode_required: str = "",
    timestamp_auth_required: bool = False,
) -> bool:
    status = str(run.get("status") or "").strip().lower()
    result = _run_result(run)
    if not run or not _run_ready_value(run) or _run_processed(run) <= 0 or _run_failed_count(run) > 0:
        return False
    if issue_required and not _run_issue_id(run):
        return False
    if reply_required and not _run_reply_id(run):
        return False
    if provider_message_required and not _run_provider_message_id(run):
        return False
    if provider_delivery_proof_required and not _run_has_provider_delivery_proof(run):
        return False
    if attachment_only_required and not _run_has_attachment_only_proof(run):
        return False
    if not _run_has_signature_auth(run, signature_auth_mode_required):
        return False
    if timestamp_auth_required and not _run_has_timestamp_auth(run):
        return False
    if delivery_required:
        delivery_passed = status in {"sent", "success"} and bool(result.get("sent") or status == "sent")
        return delivery_passed and (not provider_surface_required or _smoke_uses_provider_surface(run))
    return status == "success" and (not provider_surface_required or _smoke_uses_provider_surface(run))


def _latest_smoke_runs(channel_id: str, sync_runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for run in sync_runs:
        run_channel = str(run.get("channelId") or run.get("channel") or "").strip()
        if run_channel != channel_id:
            continue
        source = str(run.get("source") or "").strip()
        key = ""
        if source in {"admin-smoke-run", "admin-smoke"}:
            key = "inbound_smoke"
        elif source == "admin-outbound-smoke":
            key = "outbound_smoke"
        elif source == "admin-lifecycle-smoke":
            key = "lifecycle_smoke"
        elif source == "admin-validation":
            key = "provider_validation"
        if key and key not in latest:
            latest[key] = run
        if source == "admin-lifecycle-smoke" and _run_has_attachment_only_proof(run):
            latest.setdefault("attachment_lifecycle_smoke", run)
    return latest


def _smoke_detail(
    run: dict[str, Any],
    missing_detail: str,
    *,
    provider_surface_detail: str = "",
    issue_required: bool = False,
    reply_required: bool = False,
    provider_message_required: bool = False,
    provider_delivery_proof_required: bool = False,
    attachment_only_required: bool = False,
    signature_auth_mode_required: str = "",
    timestamp_auth_required: bool = False,
    target_match_required: bool = False,
    target_match_passed: bool = True,
    target_match_detail: str = "",
) -> str:
    if not run:
        return missing_detail
    error = str(run.get("error") or "").strip()
    if error:
        return error
    result = _run_result(run)
    result_error = str(result.get("error") or "").strip()
    if result_error:
        return result_error
    if (
        provider_surface_detail
        and _run_ready_value(run)
        and _run_processed(run) > 0
        and _run_failed_count(run) == 0
        and not _smoke_uses_provider_surface(run)
    ):
        return provider_surface_detail
    if issue_required and not _run_issue_id(run):
        return "Smoke run did not record a created ticket"
    if reply_required and not _run_reply_id(run):
        return "Lifecycle smoke did not record an approved reply"
    if provider_message_required and not _run_provider_message_id(run):
        return "Provider delivery did not record a provider message ID"
    if provider_delivery_proof_required and not _run_has_provider_delivery_proof(run):
        return _provider_delivery_proof_detail(run)
    if target_match_required and not target_match_passed:
        return target_match_detail or "Smoke run target does not match current live proof target"
    if attachment_only_required and not _run_has_attachment_only_proof(run):
        return "Lifecycle smoke did not prove an attachment-only inbound message"
    if not _run_has_signature_auth(run, signature_auth_mode_required):
        return _required_auth_mode_detail(signature_auth_mode_required)
    if timestamp_auth_required and not _run_has_timestamp_auth(run):
        return "Smoke run did not record timestamp-bound HMAC auth"
    status = str(run.get("status") or "").strip()
    processed = _run_processed(run)
    failed = _run_failed_count(run)
    return f"{status or 'unknown'}: {processed} processed, {failed} failed"


def _launch_step(
    *,
    key: str,
    label: str,
    run: dict[str, Any],
    passed: bool,
    missing_detail: str,
    provider_surface_detail: str = "",
    issue_required: bool = False,
    reply_required: bool = False,
    provider_message_required: bool = False,
    provider_delivery_proof_required: bool = False,
    attachment_only_required: bool = False,
    signature_auth_mode_required: str = "",
    timestamp_auth_required: bool = False,
    target_match_required: bool = False,
    target_match_passed: bool = True,
    target_match_detail: str = "",
) -> dict[str, Any]:
    auth = _run_http_auth(run)
    status = "done" if passed else "warning" if run else "missing"
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": _smoke_detail(
            run,
            missing_detail,
            provider_surface_detail=provider_surface_detail,
            issue_required=issue_required,
            reply_required=reply_required,
            provider_message_required=provider_message_required,
            provider_delivery_proof_required=provider_delivery_proof_required,
            attachment_only_required=attachment_only_required,
            signature_auth_mode_required=signature_auth_mode_required,
            timestamp_auth_required=timestamp_auth_required,
            target_match_required=target_match_required,
            target_match_passed=target_match_passed,
            target_match_detail=target_match_detail,
        ),
        "action": key,
        "runId": str(run.get("id") or ""),
        "source": str(run.get("source") or ""),
        "runStatus": str(run.get("status") or ""),
        "processed": _run_processed(run),
        "failed": _run_failed_count(run),
        "transport": _smoke_transport(run),
        "startedAt": str(run.get("startedAt") or ""),
        "completedAt": str(run.get("completedAt") or ""),
        "providerMessageId": _run_provider_message_id(run),
        "deliveryRoute": _run_delivery_route(run),
        "providerResponse": _run_provider_response(run),
        "authMode": str(auth.get("mode") or ""),
        "signatureTimestampHeader": str(auth.get("timestampHeader") or auth.get("timestamp_header") or ""),
        "attachmentCount": _run_attachment_count(run),
        "fileOnly": _run_file_only(run),
        "issueId": _run_issue_id(run),
        "replyId": _run_reply_id(run),
    }


def _launch_status_from_checklist(checklist: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for item in checklist if item["status"] == "done")
    missing = sum(1 for item in checklist if item["status"] == "missing")
    failed = sum(1 for item in checklist if item["status"] == "warning")
    checked_at = max((str(item.get("startedAt") or "") for item in checklist), default="")
    blockers = [
        {
            "key": str(item.get("key") or ""),
            "label": str(item.get("label") or ""),
            "status": str(item.get("status") or ""),
            "detail": str(item.get("detail") or ""),
            "action": str(item.get("action") or item.get("key") or ""),
            "runId": str(item.get("runId") or ""),
        }
        for item in checklist
        if item.get("status") != "done"
    ]
    return {
        "required": True,
        "ready": passed == len(checklist),
        "checks": len(checklist),
        "passed": passed,
        "missing": missing,
        "failed": failed,
        "lastCheckedAt": checked_at,
        "blockers": blockers,
        "checklist": checklist,
    }


def _email_sync_run_passed(run: dict[str, Any]) -> bool:
    status = str(run.get("status") or "").strip().lower()
    return status == "success" and _run_processed(run) > 0 and _run_failed_count(run) == 0 and bool(_run_issue_id(run))


def _email_sync_detail(run: dict[str, Any]) -> str:
    if not run:
        return "Run email channel sync to prove inbound mail creates tickets"
    error = str(run.get("error") or "").strip()
    if error:
        return error
    result = _run_result(run)
    result_error = str(result.get("error") or "").strip()
    if result_error:
        return result_error
    if _run_processed(run) > 0 and _run_failed_count(run) == 0 and not _run_issue_id(run):
        return "Sync run did not record a created ticket"
    status = str(run.get("status") or "").strip()
    return f"{status or 'unknown'}: {_run_processed(run)} processed, {_run_failed_count(run)} failed"


def _email_sync_launch_step(run: dict[str, Any]) -> dict[str, Any]:
    passed = _email_sync_run_passed(run)
    return {
        "key": "email_sync",
        "label": "Email sync passed",
        "status": "done" if passed else "warning" if run else "missing",
        "detail": _email_sync_detail(run),
        "action": "email_sync",
        "runId": str(run.get("id") or ""),
        "source": str(run.get("source") or ""),
        "runStatus": str(run.get("status") or ""),
        "processed": _run_processed(run),
        "failed": _run_failed_count(run),
        "sent": 0,
        "startedAt": str(run.get("startedAt") or ""),
        "completedAt": str(run.get("completedAt") or ""),
        "issueId": _run_issue_id(run),
    }


def _missing_launch_step(*, key: str, label: str, detail: str, source: str = "") -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": "missing",
        "detail": detail,
        "action": key,
        "runId": "",
        "source": source,
        "runStatus": "",
        "processed": 0,
        "failed": 0,
        "sent": 0,
        "startedAt": "",
        "completedAt": "",
        "issueId": "",
        "replyId": "",
    }


def _latest_non_smoke_run(channel_id: str, sync_runs: list[dict[str, Any]]) -> dict[str, Any]:
    smoke_sources = {
        "admin-smoke",
        "admin-smoke-run",
        "admin-outbound-smoke",
        "admin-lifecycle-smoke",
        "admin-validation",
    }
    for run in sync_runs:
        run_channel = str(run.get("channelId") or run.get("channel") or "").strip()
        if run_channel != channel_id:
            continue
        if str(run.get("source") or "").strip() in smoke_sources:
            continue
        return run
    return {}


def _email_inbound_auth_launch_step(
    channel: dict[str, Any],
    runtime_secrets: dict[str, str] | None = None,
) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    signature_env = _config_text(config, "signatureSecretEnv", "webhookSignatureSecretEnv", "signature_secret_env")
    token_env = (
        _config_text(
            config,
            "webhookTokenEnv",
            "webhook_token_env",
            "emailWebhookTokenEnv",
            "email_webhook_token_env",
            "providerTokenEnv",
            "provider_token_env",
        )
        or "SUPPORT_EMAIL_WEBHOOK_TOKEN"
    )
    has_signature = bool(signature_env and _env_present(signature_env, runtime_secrets))
    has_token = bool(_env_present(token_env, runtime_secrets) or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets))
    ready = has_signature or has_token
    return {
        "key": "email_auth",
        "label": "Email ingress auth configured",
        "status": "done" if ready else "missing",
        "detail": (
            "Email inbound webhook auth is configured"
            if ready
            else f"Set {token_env}, SUPPORT_SYNC_TOKEN, or a per-channel HMAC secret before launch proof"
        ),
        "action": "email_auth",
        "runId": "",
        "source": "config",
        "runStatus": "configured" if ready else "missing",
        "processed": 1 if ready else 0,
        "failed": 0 if ready else 1,
        "sent": 0,
        "startedAt": "",
        "completedAt": "",
        "issueId": "",
        "replyId": "",
        "transport": "token" if has_token else "hmac" if has_signature else "",
    }


def _email_channel_launch_status(
    channel: dict[str, Any],
    sync_runs: list[dict[str, Any]],
    runtime_secrets: dict[str, str] | None = None,
) -> dict[str, Any]:
    channel_id = str(channel.get("id") or "")
    checklist = [
        _email_inbound_auth_launch_step(channel, runtime_secrets),
        _email_sync_launch_step(_latest_non_smoke_run(channel_id, sync_runs)),
        _missing_launch_step(
            key="email_delivery",
            label="Email delivery passed",
            detail="Run support delivery to prove email replies leave the app",
            source="support_delivery",
        ),
    ]
    return _launch_status_from_checklist(checklist)


def _web_chat_channel_launch_status() -> dict[str, Any]:
    checklist = [
        _missing_launch_step(
            key="web_chat_session",
            label="Web chat session created",
            detail="Open web chat and create a ticket from a visitor message",
            source="web_chat",
        ),
        _missing_launch_step(
            key="web_chat_delivery",
            label="Web chat reply delivered",
            detail="Send an Inbox web chat reply to prove replies reach visitors",
            source="web_chat",
        ),
    ]
    return _launch_status_from_checklist(checklist)


def _provider_delivery_artifact_required(
    channel: dict[str, Any],
    runtime_secrets: dict[str, str] | None = None,
) -> bool:
    channel_type = str(channel.get("type") or "").strip().lower()
    if channel_type not in {"slack", "teams", "discord", "telegram", "line", "viber", "whatsapp", "messenger", "sms"}:
        return False
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    transport = str(config.get("outboundTransport") or config.get("outbound_transport") or "").strip().lower()
    if transport in {
        "bot",
        "slack_bot",
        "teams_bot",
        "telegram_bot",
        "discord_bot",
        "line",
        "line_messaging",
        "line_messaging_api",
        "viber",
        "viber_bot",
        "whatsapp_api",
        "messenger",
        "messenger_api",
        "facebook_messenger",
        "facebook_messenger_api",
        "twilio",
        "twilio_sms",
        "sms",
        "bot_api",
        "provider_api",
        "bot_framework",
    }:
        return True
    payload_mode = str(
        config.get("outboundPayloadMode")
        or config.get("outbound_payload_mode")
        or config.get("payloadMode")
        or config.get("payload_mode")
        or ""
    ).strip().lower()
    if payload_mode in {"provider", channel_type, "line", "viber", "twilio"}:
        return True
    if _resolved_outbound_url(config, runtime_secrets):
        return False
    if channel_type == "slack":
        return _env_present(_slack_bot_token_env(config), runtime_secrets)
    if channel_type == "teams":
        app_id_env, app_password_env = _teams_app_credential_envs(config)
        return _env_present(app_id_env, runtime_secrets) and _env_present(app_password_env, runtime_secrets)
    if channel_type == "discord":
        return _env_present(_discord_bot_token_env(config), runtime_secrets)
    if channel_type == "telegram":
        return _env_present(_telegram_bot_token_env(config), runtime_secrets)
    if channel_type == "line":
        return _env_present(_line_channel_access_token_env(config), runtime_secrets)
    if channel_type == "viber":
        return _env_present(_viber_auth_token_env(config), runtime_secrets)
    if channel_type == "whatsapp":
        return _env_present(_whatsapp_access_token_env(config), runtime_secrets)
    if channel_type in {"messenger", "facebook_messenger"}:
        return _env_present(_messenger_page_access_token_env(config), runtime_secrets)
    if channel_type == "sms":
        account_sid = _env_present(_twilio_account_sid_env(config), runtime_secrets)
        auth_token = _env_present(_twilio_auth_token_env(config), runtime_secrets)
        from_number, _from_env, messaging_service_sid, _service_env = _twilio_sender(config, runtime_secrets)
        return account_sid and auth_token and bool(from_number or messaging_service_sid)
    return False


SMOKE_TARGET_PLACEHOLDERS = {
    "123456789",
    "15551234567",
    "+15551234567",
    "+15550001111",
    "1710000000.000100",
    "c0123456789",
    "channel-id",
    "thread-id",
    "message-id",
    "conversation-id",
    "activity-id",
    "whatsapp-phone-number-id",
    "smxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
}


def _live_smoke_target_value(value: str) -> bool:
    clean = value.strip()
    if not clean:
        return False
    normalized = clean.lower()
    if normalized in SMOKE_TARGET_PLACEHOLDERS:
        return False
    if normalized.startswith("admin-smoke"):
        return False
    if normalized.startswith("+1555") or normalized.startswith("1555"):
        return False
    return True


def _live_smoke_target_configured(channel: dict[str, Any]) -> tuple[bool, str]:
    channel_type = str(channel.get("type") or "").strip().lower()
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}

    def has_any(*keys: str) -> bool:
        return any(_live_smoke_target_value(_config_text(config, key)) for key in keys)

    if channel_type == "slack":
        ready = has_any("smokeChannelId", "smoke_channel_id", "channelId", "channel_id")
        return ready, "Set smokeChannelId to a real Slack channel ID before launch proof"
    if channel_type == "teams":
        has_service_url = has_any("smokeServiceUrl", "smoke_service_url", "serviceUrl", "service_url")
        has_conversation = has_any(
            "smokeConversationId",
            "smoke_conversation_id",
            "conversationId",
            "conversation_id",
            "smokeThreadId",
            "smoke_thread_id",
            "smokeChannelId",
            "smoke_channel_id",
            "channelId",
            "channel_id",
        )
        return (
            has_service_url and has_conversation,
            "Set smokeServiceUrl plus a real Teams conversation/channel target before launch proof",
        )
    if channel_type == "discord":
        ready = has_any(
            "smokeChannelId",
            "smoke_channel_id",
            "channelId",
            "channel_id",
            "smokeThreadId",
            "smoke_thread_id",
        )
        return ready, "Set smokeChannelId or smokeThreadId to a real Discord target before launch proof"
    if channel_type == "telegram":
        ready = has_any(
            "smokeChatId",
            "smoke_chat_id",
            "chatId",
            "chat_id",
            "smokeChannelId",
            "smoke_channel_id",
            "channelId",
            "channel_id",
            "smokeToAddress",
            "smoke_to_address",
        )
        return ready, "Set smokeChatId to a real Telegram chat ID before launch proof"
    if channel_type == "line":
        ready = has_any(
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
            "lineUserId",
            "line_user_id",
            "userId",
            "user_id",
            "groupId",
            "group_id",
            "roomId",
            "room_id",
            "chatId",
            "chat_id",
        )
        return ready, "Set smokeToAddress to a real LINE user, group, or room ID before launch proof"
    if channel_type == "viber":
        ready = has_any(
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
            "viberUserId",
            "viber_user_id",
            "userId",
            "user_id",
            "senderId",
            "sender_id",
            "chatId",
            "chat_id",
        )
        return ready, "Set smokeToAddress to a real Viber subscriber ID before launch proof"
    if channel_type == "whatsapp":
        ready = has_any(
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
            "waId",
            "wa_id",
            "senderId",
            "sender_id",
            "chatId",
            "chat_id",
        )
        return ready, "Set smokeToAddress to a real WhatsApp recipient before launch proof"
    if channel_type in {"messenger", "facebook_messenger"}:
        ready = has_any(
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
            "psid",
            "senderId",
            "sender_id",
            "chatId",
            "chat_id",
        )
        return ready, "Set smokeToAddress to a real Messenger PSID before launch proof"
    if channel_type == "instagram":
        ready = has_any(
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
            "senderId",
            "sender_id",
            "igid",
            "chatId",
            "chat_id",
        )
        return ready, "Set smokeToAddress to a real Instagram scoped user ID before launch proof"
    if channel_type in {"twitter", "x"}:
        ready = has_any(
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
            "senderId",
            "sender_id",
            "twitterUserId",
            "twitter_user_id",
            "xUserId",
            "x_user_id",
            "chatId",
            "chat_id",
        )
        return ready, "Set smokeToAddress to a real X user ID before launch proof"
    if channel_type in {"sms", "twilio"}:
        ready = has_any(
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
            "smokeChannelId",
            "smoke_channel_id",
        )
        return ready, "Set smokeToAddress to a real SMS recipient before launch proof"
    return True, ""


def _live_target_value(config: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _config_text(config, key)
        if _live_smoke_target_value(value):
            return value.strip()
    return ""


def _live_smoke_target_requirements(channel: dict[str, Any]) -> list[dict[str, str]]:
    channel_type = str(channel.get("type") or "").strip().lower()
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    requirements: list[dict[str, str]] = []

    def add(key: str, label: str, value: str) -> None:
        clean = str(value or "").strip()
        if _live_smoke_target_value(clean):
            requirements.append({"key": key, "label": label, "value": clean})

    if channel_type == "slack":
        add("smokeChannelId", "Slack channel", _live_target_value(config, "smokeChannelId", "smoke_channel_id", "channelId", "channel_id"))
        add(
            "smokeThreadTs",
            "Slack thread",
            _live_target_value(
                config,
                "smokeThreadTs",
                "smoke_thread_ts",
                "threadTs",
                "thread_ts",
                "smokeThreadId",
                "smoke_thread_id",
                "threadId",
                "thread_id",
            ),
        )
    elif channel_type == "teams":
        add("smokeServiceUrl", "Teams service URL", _live_target_value(config, "smokeServiceUrl", "smoke_service_url", "serviceUrl", "service_url"))
        add(
            "smokeConversationId",
            "Teams conversation",
            _live_target_value(
                config,
                "smokeConversationId",
                "smoke_conversation_id",
                "conversationId",
                "conversation_id",
                "smokeThreadId",
                "smoke_thread_id",
                "smokeChannelId",
                "smoke_channel_id",
                "channelId",
                "channel_id",
            ),
        )
    elif channel_type == "discord":
        add("smokeChannelId", "Discord channel", _live_target_value(config, "smokeChannelId", "smoke_channel_id", "channelId", "channel_id"))
        add("smokeThreadId", "Discord thread", _live_target_value(config, "smokeThreadId", "smoke_thread_id", "threadId", "thread_id"))
    elif channel_type == "telegram":
        add(
            "smokeChatId",
            "Telegram chat",
            _live_target_value(
                config,
                "smokeChatId",
                "smoke_chat_id",
                "chatId",
                "chat_id",
                "smokeChannelId",
                "smoke_channel_id",
                "channelId",
                "channel_id",
                "smokeToAddress",
                "smoke_to_address",
            ),
        )
    elif channel_type == "line":
        add(
            "smokeToAddress",
            "LINE user/group/room",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "lineUserId",
                "line_user_id",
                "userId",
                "user_id",
                "groupId",
                "group_id",
                "roomId",
                "room_id",
                "chatId",
                "chat_id",
            ),
        )
    elif channel_type == "viber":
        add(
            "smokeToAddress",
            "Viber subscriber",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "viberUserId",
                "viber_user_id",
                "userId",
                "user_id",
                "senderId",
                "sender_id",
                "chatId",
                "chat_id",
            ),
        )
    elif channel_type == "viber":
        add(
            "smokeToAddress",
            "Viber subscriber",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "viberUserId",
                "viber_user_id",
                "userId",
                "user_id",
                "senderId",
                "sender_id",
                "chatId",
                "chat_id",
            ),
        )
    elif channel_type == "whatsapp":
        add(
            "smokeToAddress",
            "WhatsApp recipient",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "waId",
                "wa_id",
                "senderId",
                "sender_id",
                "chatId",
                "chat_id",
            ),
        )
    elif channel_type in {"messenger", "facebook_messenger"}:
        add(
            "smokeToAddress",
            "Messenger recipient",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "senderId",
                "sender_id",
                "psid",
                "chatId",
                "chat_id",
            ),
        )
    elif channel_type == "instagram":
        add(
            "smokeToAddress",
            "Instagram recipient",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "senderId",
                "sender_id",
                "igid",
                "chatId",
                "chat_id",
            ),
        )
    elif channel_type in {"twitter", "x"}:
        add(
            "smokeToAddress",
            "X recipient",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "senderId",
                "sender_id",
                "twitterUserId",
                "twitter_user_id",
                "xUserId",
                "x_user_id",
                "chatId",
                "chat_id",
            ),
        )
    elif channel_type in {"sms", "twilio"}:
        add(
            "smokeToAddress",
            "SMS recipient",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "smokeChannelId",
                "smoke_channel_id",
            ),
        )
    return requirements


def _live_inbound_smoke_target_requirements(channel: dict[str, Any]) -> list[dict[str, str]]:
    channel_type = str(channel.get("type") or "").strip().lower()
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    requirements: list[dict[str, str]] = []

    def add(key: str, label: str, value: str) -> None:
        clean = str(value or "").strip()
        if _live_smoke_target_value(clean):
            requirements.append({"key": key, "label": label, "value": clean})

    if channel_type == "slack":
        add("smokeChannelId", "Slack channel", _live_target_value(config, "smokeChannelId", "smoke_channel_id", "channelId", "channel_id"))
        add(
            "smokeThreadTs",
            "Slack thread",
            _live_target_value(
                config,
                "smokeThreadTs",
                "smoke_thread_ts",
                "threadTs",
                "thread_ts",
                "smokeThreadId",
                "smoke_thread_id",
                "threadId",
                "thread_id",
            ),
        )
    elif channel_type == "teams":
        add(
            "smokeConversationId",
            "Teams conversation",
            _live_target_value(
                config,
                "smokeConversationId",
                "smoke_conversation_id",
                "conversationId",
                "conversation_id",
                "smokeThreadId",
                "smoke_thread_id",
                "smokeChannelId",
                "smoke_channel_id",
                "channelId",
                "channel_id",
            ),
        )
    elif channel_type == "discord":
        add("smokeChannelId", "Discord channel", _live_target_value(config, "smokeChannelId", "smoke_channel_id", "channelId", "channel_id"))
    elif channel_type == "telegram":
        add(
            "smokeChatId",
            "Telegram chat",
            _live_target_value(
                config,
                "smokeChatId",
                "smoke_chat_id",
                "chatId",
                "chat_id",
                "smokeChannelId",
                "smoke_channel_id",
                "channelId",
                "channel_id",
                "smokeToAddress",
                "smoke_to_address",
            ),
        )
    elif channel_type == "line":
        add(
            "smokeToAddress",
            "LINE user/group/room",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "lineUserId",
                "line_user_id",
                "userId",
                "user_id",
                "groupId",
                "group_id",
                "roomId",
                "room_id",
                "chatId",
                "chat_id",
            ),
        )
    elif channel_type == "whatsapp":
        add(
            "smokeToAddress",
            "WhatsApp recipient",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "waId",
                "wa_id",
                "senderId",
                "sender_id",
                "chatId",
                "chat_id",
            ),
        )
    elif channel_type in {"messenger", "facebook_messenger"}:
        add(
            "smokeToAddress",
            "Messenger recipient",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "senderId",
                "sender_id",
                "psid",
                "chatId",
                "chat_id",
            ),
        )
    elif channel_type in {"sms", "twilio"}:
        add(
            "smokeToAddress",
            "SMS recipient",
            _live_target_value(
                config,
                "smokeToAddress",
                "smoke_to_address",
                "smokeConversationId",
                "smoke_conversation_id",
                "smokeChannelId",
                "smoke_channel_id",
            ),
        )
    return requirements


def _event_token(value: str) -> str:
    clean = []
    for char in (value or "").strip().lower():
        clean.append(char if char.isalnum() else "_")
    return "_".join(part for part in "".join(clean).split("_") if part)


def _target_tokens_for_value(value: Any) -> set[str]:
    clean = " ".join(str(value or "").strip().lower().split())
    if not clean:
        return set()
    tokens = {clean}
    phone_chars = set("+0123456789 -().")
    digits = "".join(char for char in clean if char.isdigit())
    if len(digits) >= 6 and all(char in phone_chars for char in clean):
        tokens.add(digits)
        if clean.startswith("+"):
            tokens.add(f"+{digits}")
    return tokens


def _run_target_tokens(run: dict[str, Any], *, include_inbound: bool = True) -> set[str]:
    target_keys = {
        _event_token(key)
        for key in (
            "channelId",
            "channel_id",
            "chatId",
            "chat_id",
            "conversationId",
            "conversation_id",
            "threadId",
            "thread_id",
            "threadTs",
            "thread_ts",
            "toAddress",
            "to_address",
            "recipient",
            "recipientId",
            "recipient_id",
            "senderId",
            "sender_id",
            "serviceUrl",
            "service_url",
            "target",
            "targetId",
            "target_id",
            "phone",
            "phoneNumber",
            "phone_number",
            "waId",
            "wa_id",
            "psid",
            "lineUserId",
            "line_user_id",
            "viberUserId",
            "viber_user_id",
            "groupId",
            "group_id",
            "roomId",
            "room_id",
        )
    }
    tokens: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                token_key = _event_token(str(key))
                if not include_inbound and token_key == "inbound":
                    continue
                if token_key in target_keys:
                    tokens.update(_target_tokens_for_value(nested))
                if isinstance(nested, (dict, list)):
                    collect(nested)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    collect(item)

    collect(_run_result(run))
    return tokens


def _missing_target_requirements(
    requirements: list[dict[str, str]],
    run: dict[str, Any],
    *,
    include_inbound: bool,
) -> list[dict[str, str]]:
    run_tokens = _run_target_tokens(run, include_inbound=include_inbound)
    missing: list[dict[str, str]] = []
    for requirement in requirements:
        required_tokens = _target_tokens_for_value(requirement.get("value"))
        if required_tokens and run_tokens.isdisjoint(required_tokens):
            missing.append(requirement)
    return missing


def _target_mismatch_detail(missing: list[dict[str, str]], prefix: str) -> str:
    if not missing:
        return ""
    rendered = ", ".join(f"{item['key']}={item['value']}" for item in missing)
    return f"{prefix}: {rendered}"


def _live_smoke_target_match_required(
    channel: dict[str, Any],
    runtime_secrets: dict[str, str] | None = None,
) -> bool:
    return _live_provider_smoke_target_required(channel, runtime_secrets) and bool(_live_smoke_target_requirements(channel))


def _live_inbound_smoke_target_match_required(
    channel: dict[str, Any],
    runtime_secrets: dict[str, str] | None = None,
) -> bool:
    return _live_provider_smoke_target_required(channel, runtime_secrets) and bool(_live_inbound_smoke_target_requirements(channel))


def _live_smoke_target_run_matches(channel: dict[str, Any], run: dict[str, Any], runtime_secrets: dict[str, str] | None = None) -> bool:
    if not _live_smoke_target_match_required(channel, runtime_secrets):
        return True
    return bool(run) and not _missing_target_requirements(_live_smoke_target_requirements(channel), run, include_inbound=False)


def _live_inbound_smoke_target_run_matches(
    channel: dict[str, Any],
    run: dict[str, Any],
    runtime_secrets: dict[str, str] | None = None,
) -> bool:
    if not _live_inbound_smoke_target_match_required(channel, runtime_secrets):
        return True
    return bool(run) and not _missing_target_requirements(_live_inbound_smoke_target_requirements(channel), run, include_inbound=True)


def _live_smoke_target_mismatch_detail(channel: dict[str, Any], run: dict[str, Any]) -> str:
    return _target_mismatch_detail(
        _missing_target_requirements(_live_smoke_target_requirements(channel), run, include_inbound=False),
        "Smoke run target does not match current live proof target",
    )


def _live_inbound_smoke_target_mismatch_detail(channel: dict[str, Any], run: dict[str, Any]) -> str:
    return _target_mismatch_detail(
        _missing_target_requirements(_live_inbound_smoke_target_requirements(channel), run, include_inbound=True),
        "Inbound smoke target does not match current live proof target",
    )


def _live_provider_smoke_target_required(
    channel: dict[str, Any],
    runtime_secrets: dict[str, str] | None = None,
) -> bool:
    channel_type = str(channel.get("type") or "").strip().lower()
    return channel_type in {"slack", "teams", "discord", "telegram", "line", "viber", "whatsapp", "messenger", "sms", "twilio"} and (
        _provider_delivery_artifact_required(channel, runtime_secrets)
    )


def _live_provider_smoke_target_step(
    channel: dict[str, Any],
    runtime_secrets: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if not _live_provider_smoke_target_required(channel, runtime_secrets):
        return None
    ready, missing_detail = _live_smoke_target_configured(channel)
    return {
        "key": "live_smoke_target",
        "label": "Live proof target configured",
        "status": "done" if ready else "missing",
        "detail": "Live provider smoke target is configured" if ready else missing_detail,
        "action": "configure_smoke_target",
        "runId": "",
        "source": "config",
        "runStatus": "configured" if ready else "missing",
        "processed": 1 if ready else 0,
        "failed": 0 if ready else 1,
        "transport": "",
        "startedAt": "",
        "completedAt": "",
        "providerMessageId": "",
        "deliveryRoute": {},
        "providerResponse": {},
        "authMode": "",
        "signatureTimestampHeader": "",
        "attachmentCount": 0,
        "fileOnly": False,
        "issueId": "",
        "replyId": "",
    }


def _provider_validation_required(
    channel: dict[str, Any],
    runtime_secrets: dict[str, str] | None = None,
) -> bool:
    return _provider_delivery_artifact_required(channel, runtime_secrets)


def _channel_launch_status(
    channel: dict[str, Any],
    sync_runs: list[dict[str, Any]],
    runtime_secrets: dict[str, str] | None = None,
) -> dict[str, Any]:
    channel_type = str(channel.get("type") or "").strip().lower()
    if channel_type == "email":
        return _email_channel_launch_status(channel, sync_runs, runtime_secrets)
    if channel_type in {"chat", "web_chat"}:
        return _web_chat_channel_launch_status()
    required = _channel_requires_launch_smoke(channel_type)
    if not required:
        return {
            "required": False,
            "ready": True,
            "checks": 0,
            "passed": 0,
            "missing": 0,
            "failed": 0,
            "lastCheckedAt": "",
            "blockers": [],
            "checklist": [],
        }

    runs = _latest_smoke_runs(str(channel.get("id") or ""), sync_runs)
    provider_message_required = _provider_delivery_artifact_required(channel, runtime_secrets)
    provider_validation_required = _provider_validation_required(channel, runtime_secrets)
    signature_auth_mode_required = _signature_auth_mode_required(channel, runtime_secrets)
    timestamp_auth_required = _signature_timestamp_required(channel)
    live_target_step = _live_provider_smoke_target_step(channel, runtime_secrets)
    inbound = runs.get("inbound_smoke", {})
    outbound = runs.get("outbound_smoke", {})
    lifecycle = runs.get("lifecycle_smoke", {})
    attachment_lifecycle = runs.get("attachment_lifecycle_smoke", {})
    inbound_target_match_required = _live_inbound_smoke_target_match_required(channel, runtime_secrets)
    live_target_match_required = _live_smoke_target_match_required(channel, runtime_secrets)
    inbound_target_matched = _live_inbound_smoke_target_run_matches(channel, inbound, runtime_secrets)
    outbound_target_matched = _live_smoke_target_run_matches(channel, outbound, runtime_secrets)
    lifecycle_target_matched = _live_smoke_target_run_matches(channel, lifecycle, runtime_secrets)
    attachment_target_matched = _live_smoke_target_run_matches(channel, attachment_lifecycle, runtime_secrets)
    checklist = [
        _launch_step(
            key="inbound_smoke",
            label="Inbound smoke passed",
            run=inbound,
            passed=(
                _smoke_run_passed(
                    inbound,
                    provider_surface_required=True,
                    issue_required=True,
                    signature_auth_mode_required=signature_auth_mode_required,
                    timestamp_auth_required=timestamp_auth_required,
                )
                and inbound_target_matched
            ),
            missing_detail="Run HTTP channel smoke to prove provider endpoint/auth creates a ticket",
            provider_surface_detail="Run HTTP channel smoke to prove provider endpoint/auth creates a ticket",
            issue_required=True,
            signature_auth_mode_required=signature_auth_mode_required,
            timestamp_auth_required=timestamp_auth_required,
            target_match_required=inbound_target_match_required,
            target_match_passed=inbound_target_matched,
            target_match_detail=_live_inbound_smoke_target_mismatch_detail(channel, inbound),
        ),
    ]
    if live_target_step:
        checklist.insert(0, live_target_step)
    if provider_validation_required:
        checklist.append(
            _launch_step(
                key="provider_validation",
                label="Provider credentials validated",
                run=runs.get("provider_validation", {}),
                passed=_validation_run_passed(runs.get("provider_validation", {})),
                missing_detail="Run setup validation to prove provider credentials work",
            )
        )
    checklist.extend([
        _launch_step(
            key="outbound_smoke",
            label="Outbound smoke passed",
            run=outbound,
            passed=(
                _smoke_run_passed(
                    outbound,
                    delivery_required=True,
                    provider_message_required=provider_message_required,
                    provider_delivery_proof_required=provider_message_required,
                )
                and outbound_target_matched
            ),
            missing_detail="Run outbound smoke to prove replies leave the app",
            provider_message_required=provider_message_required,
            provider_delivery_proof_required=provider_message_required,
            target_match_required=live_target_match_required,
            target_match_passed=outbound_target_matched,
            target_match_detail=_live_smoke_target_mismatch_detail(channel, outbound),
        ),
        _launch_step(
            key="lifecycle_smoke",
            label="Lifecycle smoke passed",
            run=lifecycle,
            passed=(
                _smoke_run_passed(
                    lifecycle,
                    delivery_required=True,
                    provider_surface_required=True,
                    issue_required=True,
                    reply_required=True,
                    provider_message_required=provider_message_required,
                    provider_delivery_proof_required=provider_message_required,
                    signature_auth_mode_required=signature_auth_mode_required,
                    timestamp_auth_required=timestamp_auth_required,
                )
                and lifecycle_target_matched
            ),
            missing_detail="Run HTTP lifecycle smoke to prove provider endpoint, ticket, approval, and delivery",
            provider_surface_detail="Run HTTP lifecycle smoke to prove provider endpoint, ticket, approval, and delivery",
            issue_required=True,
            reply_required=True,
            provider_message_required=provider_message_required,
            provider_delivery_proof_required=provider_message_required,
            signature_auth_mode_required=signature_auth_mode_required,
            timestamp_auth_required=timestamp_auth_required,
            target_match_required=live_target_match_required,
            target_match_passed=lifecycle_target_matched,
            target_match_detail=_live_smoke_target_mismatch_detail(channel, lifecycle),
        ),
    ])
    if _channel_requires_attachment_lifecycle_smoke(channel_type):
        provider_label = channel_type.replace("_", " ").title() or "Provider"
        checklist.append(
            _launch_step(
                key="attachment_lifecycle_smoke",
                label="Attachment lifecycle smoke passed",
                run=attachment_lifecycle,
                passed=(
                    _smoke_run_passed(
                        attachment_lifecycle,
                        delivery_required=True,
                        provider_surface_required=True,
                        issue_required=True,
                        reply_required=True,
                        provider_message_required=provider_message_required,
                        provider_delivery_proof_required=provider_message_required,
                        attachment_only_required=True,
                        signature_auth_mode_required=signature_auth_mode_required,
                        timestamp_auth_required=timestamp_auth_required,
                    )
                    and attachment_target_matched
                ),
                missing_detail=(
                    f"Run attachment-only HTTP lifecycle smoke to prove {provider_label} files create tickets and replies deliver"
                ),
                provider_surface_detail=(
                    f"Run attachment-only HTTP lifecycle smoke to prove {provider_label} files create tickets and replies deliver"
                ),
                issue_required=True,
                reply_required=True,
                provider_message_required=provider_message_required,
                provider_delivery_proof_required=provider_message_required,
                attachment_only_required=True,
                signature_auth_mode_required=signature_auth_mode_required,
                timestamp_auth_required=timestamp_auth_required,
                target_match_required=live_target_match_required,
                target_match_passed=attachment_target_matched,
                target_match_detail=_live_smoke_target_mismatch_detail(channel, attachment_lifecycle),
            )
        )
    return _launch_status_from_checklist(checklist)


def _channel_launch_status_from_proof(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    raw_checklist = item.get("checklist") if isinstance(item.get("checklist"), list) else []
    checklist = []
    for check in raw_checklist:
        if not isinstance(check, dict):
            continue
        key = str(check.get("key") or "")
        checklist.append({
            "key": key,
            "label": str(check.get("label") or ""),
            "status": str(check.get("status") or ""),
            "detail": str(check.get("detail") or ""),
            "action": str(check.get("action") or key),
            "runId": str(check.get("runId") or ""),
            "source": str(check.get("source") or ""),
            "runStatus": str(check.get("runStatus") or ""),
            "processed": _run_processed(check),
            "failed": _run_failed_count(check),
            "sent": int(check.get("sent") or 0),
            "transport": str(check.get("transport") or ""),
            "startedAt": str(check.get("startedAt") or ""),
            "completedAt": str(check.get("completedAt") or ""),
            "sessionId": str(check.get("sessionId") or ""),
            "provider": str(check.get("provider") or ""),
            "providerMessageId": str(check.get("providerMessageId") or ""),
            "inboundProviderMessageId": str(check.get("inboundProviderMessageId") or ""),
            "deliveryRoute": check.get("deliveryRoute") if isinstance(check.get("deliveryRoute"), dict) else {},
            "providerResponse": check.get("providerResponse") if isinstance(check.get("providerResponse"), dict) else {},
            "authMode": str(check.get("authMode") or ""),
            "signatureTimestampHeader": str(check.get("signatureTimestampHeader") or ""),
            "attachmentCount": int(check.get("attachmentCount") or 0),
            "fileOnly": bool(check.get("fileOnly")),
            "issueId": str(check.get("issueId") or ""),
            "replyId": str(check.get("replyId") or ""),
            "aiRunId": str(check.get("aiRunId") or check.get("ai_run_id") or ""),
            "approvedBy": str(check.get("approvedBy") or check.get("approved_by") or ""),
            "approvedAt": str(check.get("approvedAt") or check.get("approved_at") or ""),
            "approvalSource": str(check.get("approvalSource") or check.get("approval_source") or ""),
            "approvalEventId": str(check.get("approvalEventId") or check.get("approval_event_id") or ""),
        })
    blockers = [
        {
            "key": str(blocker.get("key") or ""),
            "label": str(blocker.get("label") or ""),
            "status": str(blocker.get("status") or ""),
            "detail": str(blocker.get("detail") or ""),
            "action": str(blocker.get("action") or blocker.get("key") or ""),
            "runId": str(blocker.get("runId") or ""),
        }
        for blocker in item.get("blockers", [])
        if isinstance(blocker, dict)
    ]
    missing = sum(1 for check in checklist if check.get("status") == "missing")
    failed = sum(1 for check in checklist if check.get("status") == "warning")
    return {
        "required": bool(item.get("required", True)),
        "ready": bool(item.get("ready")),
        "checks": int(item.get("checks") or len(checklist)),
        "passed": int(item.get("passed") or 0),
        "missing": missing,
        "failed": failed,
        "lastCheckedAt": str(item.get("lastCheckedAt") or ""),
        "blockers": blockers,
        "checklist": checklist,
    }


def _channel_install_package(channel: dict[str, Any], ctx: ProjectViewerDep, setup: dict[str, Any]) -> dict[str, Any]:
    env_vars = setup.get("envVars") if isinstance(setup.get("envVars"), list) else []
    checklist = setup.get("setupChecklist") if isinstance(setup.get("setupChecklist"), list) else []
    provider_steps = setup.get("providerSteps") if isinstance(setup.get("providerSteps"), list) else []
    package: dict[str, Any] = {
        "version": 1,
        "projectId": ctx.project_id,
        "channel": {
            "id": channel.get("id", ""),
            "key": channel.get("channelKey", ""),
            "type": channel.get("type", ""),
            "name": channel.get("name", ""),
            "status": channel.get("status", ""),
        },
        "inbound": {
            "primaryUrl": setup.get("providerWebhookUrl") or setup.get("inboundWebhookUrl") or setup.get("webChatUrl") or "",
            "genericWebhookUrl": setup.get("inboundWebhookUrl", ""),
            "genericWebhookPath": setup.get("inboundWebhookPath", ""),
            "providerWebhookUrl": setup.get("providerWebhookUrl", ""),
            "providerWebhookPath": setup.get("providerWebhookPath", ""),
            "smsWebhookUrl": setup.get("smsWebhookUrl", ""),
            "smsWebhookPath": setup.get("smsWebhookPath", ""),
            "webChatUrl": setup.get("webChatUrl", ""),
            "webChatEmbedScriptUrl": setup.get("webChatEmbedScriptUrl", ""),
            "webChatEmbedSnippet": setup.get("webChatEmbedSnippet", ""),
        },
        "auth": {
            "tokenHeader": setup.get("tokenHeader", ""),
            "tokenEnv": setup.get("providerTokenEnv") or setup.get("tokenEnv", ""),
            "fallbackTokenEnv": setup.get("fallbackTokenEnv", ""),
            "signatureHeader": setup.get("signatureHeader", ""),
            "signatureEnv": setup.get("signatureEnv", ""),
            "signatureRequired": bool(setup.get("signatureRequired")),
            "signatureTimestampHeader": setup.get("signatureTimestampHeader", ""),
            "signatureTimestampRequired": bool(setup.get("signatureTimestampRequired")),
            "signatureToleranceSeconds": int(setup.get("signatureToleranceSeconds") or 300),
            "providerSecretHeader": setup.get("providerSecretHeader", ""),
            "providerSecretEnv": setup.get("providerSecretEnv", ""),
        },
        "outbound": {
            "webhookUrl": setup.get("outboundWebhookUrl", ""),
            "webhookUrlEnv": setup.get("outboundWebhookUrlEnv", ""),
            "webhookUrlTemplate": setup.get("outboundWebhookUrlTemplate", ""),
            "webhookTokenEnv": setup.get("outboundWebhookTokenEnv", ""),
            "tokenRequired": bool(setup.get("outboundTokenRequired")),
            "configured": bool(setup.get("outboundWebhookConfigured")),
            "ready": bool(setup.get("outboundReady")),
            "configKeys": setup.get("outboundConfigKeys", []),
        },
        "ticketing": {
            "ticketCreationMode": setup.get("ticketCreationMode", ""),
            "ticketCreationConfigKey": setup.get("ticketCreationConfigKey", ""),
            "autoPrepareTriage": bool(setup.get("autoPrepareTriage")),
            "autoPrepareCustomFields": bool(setup.get("autoPrepareCustomFields")),
            "autoPrepareAgentReply": bool(setup.get("autoPrepareAgentReply")),
            "autoPrepareAgentReplyOnUpdate": bool(setup.get("autoPrepareAgentReplyOnUpdate")),
            "agentAutoSend": bool(setup.get("agentAutoSend")),
            "autoPrepareConfigKeys": setup.get("autoPrepareConfigKeys", []),
        },
        "payloadExamples": {
            "message": setup.get("messagePayloadExample", {}),
            "receipt": setup.get("receiptPayloadExample", {}),
        },
        "health": setup.get("health", {}),
        "launch": setup.get("launch", {}),
        "launchPlaybook": setup.get("launchPlaybook", []),
        "installSteps": provider_steps,
        "envVars": [
            {
                "name": env.get("name", ""),
                "purpose": env.get("purpose", ""),
                "required": bool(env.get("required")),
                "configured": bool(env.get("configured")),
            }
            for env in env_vars
        ],
        "checklist": checklist,
    }
    if ctx.tenant_id:
        package["tenantId"] = ctx.tenant_id
    if setup.get("slackManifest"):
        package["slackManifest"] = setup["slackManifest"]
    if setup.get("teamsBridgeConfig"):
        package["teamsBridgeConfig"] = setup["teamsBridgeConfig"]
    if setup.get("discordBridgeConfig"):
        package["discordBridgeConfig"] = setup["discordBridgeConfig"]
    if setup.get("telegramWebhookConfig"):
        package["telegramWebhookConfig"] = setup["telegramWebhookConfig"]
    if setup.get("lineWebhookConfig"):
        package["lineWebhookConfig"] = setup["lineWebhookConfig"]
    if setup.get("viberWebhookConfig"):
        package["viberWebhookConfig"] = setup["viberWebhookConfig"]
    if setup.get("metaBridgeConfig"):
        package["metaBridgeConfig"] = setup["metaBridgeConfig"]
    if setup.get("whatsappWebhookConfig"):
        package["whatsappWebhookConfig"] = setup["whatsappWebhookConfig"]
    if setup.get("messengerWebhookConfig"):
        package["messengerWebhookConfig"] = setup["messengerWebhookConfig"]
    if setup.get("instagramWebhookConfig"):
        package["instagramWebhookConfig"] = setup["instagramWebhookConfig"]
    if setup.get("twitterWebhookConfig"):
        package["twitterWebhookConfig"] = setup["twitterWebhookConfig"]
    if setup.get("twitterBridgeConfig"):
        package["twitterBridgeConfig"] = setup["twitterBridgeConfig"]
    if setup.get("twilioWebhookConfig"):
        package["twilioWebhookConfig"] = setup["twilioWebhookConfig"]
    return package


def _playbook_step(
    key: str,
    label: str,
    status: str,
    detail: str,
    *,
    action: str = "",
    run_action: str = "",
    copy_label: str = "",
    copy_value: str = "",
    smoke_command: str = "",
    target_url: str = "",
) -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "action": action,
        "runAction": run_action,
        "copyLabel": copy_label,
        "copyValue": copy_value,
        "smokeCommand": smoke_command,
        "targetUrl": target_url,
    }


def _channel_lifecycle_smoke_command(
    channel: dict[str, Any],
    project_id: str,
    *,
    attachment_only: bool = False,
) -> str:
    channel_key = str(channel.get("channelKey") or channel.get("channel_key") or channel.get("id") or "").strip()
    if not channel_key:
        return ""
    parts = [
        f"SUPPORT_PROJECT_ID={shlex.quote(project_id or '<project-id>')}",
        "ADMIN_AUTH_TOKEN=<admin-api-token>",
        "./support-channel-lifecycle-smoke.sh",
        "--channel-key",
        shlex.quote(channel_key),
        "--transport",
        "http",
    ]
    if attachment_only:
        parts.extend([
            "--body",
            '""',
            "--attachment",
            shlex.quote('{"id":"smoke-file","filename":"incident.txt","url":"https://files.example/incident.txt"}'),
        ])
    return " ".join(parts)


def _channel_launch_playbook(channel: dict[str, Any], setup: dict[str, Any], project_id: str = "<project-id>") -> list[dict[str, str]]:
    channel_type = str(channel.get("type") or "").strip().lower()
    launch = setup.get("launch") if isinstance(setup.get("launch"), dict) else {}
    launch_checklist = setup.get("launchChecklist") if isinstance(setup.get("launchChecklist"), list) else []
    launch_blockers = launch.get("blockers") if isinstance(launch.get("blockers"), list) else []
    setup_health = setup.get("health") if isinstance(setup.get("health"), dict) else {}
    missing_env_vars = setup_health.get("requiredMissingEnvVars")
    if not isinstance(missing_env_vars, list):
        missing_env_vars = []
    endpoint = str(
        setup.get("providerWebhookUrl")
        or setup.get("webChatUrl")
        or setup.get("inboundWebhookUrl")
        or ""
    )
    endpoint_label = "Provider URL" if setup.get("providerWebhookUrl") else "Inbound URL"
    if setup.get("webChatUrl"):
        endpoint_label = "Web chat URL"

    def _launch_status(*keys: str) -> str:
        for check in launch_checklist:
            if isinstance(check, dict) and str(check.get("key") or "") in keys:
                return str(check.get("status") or "")
        return ""

    def _has_blocker(*keys: str) -> bool:
        return any(
            isinstance(blocker, dict) and str(blocker.get("key") or blocker.get("action") or "") in keys
            for blocker in launch_blockers
        )

    playbook: list[dict[str, str]] = [
        _playbook_step(
            "endpoint",
            "Connect inbound surface",
            "done" if endpoint else "missing",
            f"Copy {endpoint_label.lower()} into {_provider_name(channel_type)} setup.",
            action="copy",
            copy_label=endpoint_label,
            copy_value=endpoint,
            target_url=endpoint if setup.get("webChatUrl") else "",
        )
    ]
    if missing_env_vars:
        env_names = "\n".join(str(name) for name in missing_env_vars if name)
        playbook.append(_playbook_step(
            "secrets",
            "Configure secrets",
            "missing",
            "Set required env: " + ", ".join(str(name) for name in missing_env_vars if name),
            action="copy",
            copy_label="Env names",
            copy_value=env_names,
        ))
    else:
        playbook.append(_playbook_step(
            "secrets",
            "Configure secrets",
            "done",
            "Required channel secrets are configured.",
        ))

    if channel_type == "slack":
        playbook.append(_playbook_step(
            "provider_install",
            "Install Slack app",
            "done" if _launch_status("inbound_smoke", "channel_autopilot") == "done" else "manual",
            "Use Slack OAuth, then validate credentials and run smoke.",
            action="install_slack",
        ))
    elif channel_type == "telegram":
        playbook.append(_playbook_step(
            "provider_install",
            "Set Telegram webhook",
            "done" if _launch_status("inbound_smoke", "channel_autopilot") == "done" else "manual",
            "Register the provider webhook URL with Telegram Bot API.",
            action="set_telegram_webhook",
        ))
    elif channel_type == "line" and setup.get("lineWebhookConfig"):
        playbook.append(_playbook_step(
            "provider_install",
            "Configure LINE webhook",
            "done" if _launch_status("inbound_smoke", "channel_autopilot") == "done" else "manual",
            "Set the LINE Messaging API webhook URL and enable webhook delivery.",
            action="copy",
            copy_label="LINE webhook config",
            copy_value=json.dumps(setup.get("lineWebhookConfig"), indent=2),
        ))
    elif channel_type == "viber" and setup.get("viberWebhookConfig"):
        playbook.append(_playbook_step(
            "provider_install",
            "Set Viber webhook",
            "done" if _launch_status("inbound_smoke", "channel_autopilot") == "done" else "manual",
            "Call Viber set_webhook with this provider webhook URL and auth token.",
            action="copy",
            copy_label="Viber webhook config",
            copy_value=json.dumps(setup.get("viberWebhookConfig"), indent=2),
        ))
    elif channel_type == "whatsapp" and setup.get("whatsappWebhookConfig"):
        bridge_config = setup.get("metaBridgeConfig")
        playbook.append(_playbook_step(
            "provider_install",
            "Configure WhatsApp webhook",
            "done" if _launch_status("inbound_smoke", "channel_autopilot") == "done" else "manual",
            "Set the Meta callback URL and verify token. Use the bridge config when the core app is private.",
            action="copy",
            copy_label="WhatsApp bridge config" if bridge_config else "WhatsApp webhook config",
            copy_value=json.dumps(bridge_config or setup.get("whatsappWebhookConfig"), indent=2),
        ))
    elif channel_type in {"messenger", "facebook_messenger"} and setup.get("messengerWebhookConfig"):
        bridge_config = setup.get("metaBridgeConfig")
        playbook.append(_playbook_step(
            "provider_install",
            "Configure Messenger webhook",
            "done" if _launch_status("inbound_smoke", "channel_autopilot") == "done" else "manual",
            "Set the Meta Messenger callback URL and verify token on the Facebook app. Use the bridge config when the core app is private.",
            action="copy",
            copy_label="Messenger bridge config" if bridge_config else "Messenger webhook config",
            copy_value=json.dumps(bridge_config or setup.get("messengerWebhookConfig"), indent=2),
        ))
    elif channel_type == "instagram" and setup.get("instagramWebhookConfig"):
        bridge_config = setup.get("metaBridgeConfig")
        playbook.append(_playbook_step(
            "provider_install",
            "Configure Instagram webhook",
            "done" if _launch_status("inbound_smoke", "channel_autopilot") == "done" else "manual",
            "Set the Meta Instagram callback URL and verify token. Use the bridge config when the core app is private.",
            action="copy",
            copy_label="Instagram bridge config" if bridge_config else "Instagram webhook config",
            copy_value=json.dumps(bridge_config or setup.get("instagramWebhookConfig"), indent=2),
        ))
    elif channel_type in {"twitter", "x"} and setup.get("twitterWebhookConfig"):
        bridge_config = setup.get("twitterBridgeConfig")
        playbook.append(_playbook_step(
            "provider_install",
            "Configure X webhook",
            "done" if _launch_status("inbound_smoke", "channel_autopilot") == "done" else "manual",
            "Set the X webhook URL and confirm CRC validation. Use the bridge config when the core app is private.",
            action="copy",
            copy_label="X bridge config" if bridge_config else "X webhook config",
            copy_value=json.dumps(bridge_config or setup.get("twitterWebhookConfig"), indent=2),
        ))
    elif channel_type == "sms" and setup.get("twilioWebhookConfig"):
        playbook.append(_playbook_step(
            "provider_install",
            "Configure Twilio webhooks",
            "done" if _launch_status("inbound_smoke", "channel_autopilot") == "done" else "manual",
            "Set the Twilio incoming message webhook and status callback to the provider URL.",
            action="copy",
            copy_label="Twilio webhook config",
            copy_value=json.dumps(setup.get("twilioWebhookConfig"), indent=2),
        ))
    elif channel_type == "email" and setup.get("emailWebhookConfig"):
        playbook.append(_playbook_step(
            "provider_install",
            "Configure email ingress",
            "done" if _launch_status("email_sync") == "done" else "manual",
            "Configure IMAP polling or copy this JSON webhook contract into the inbound email gateway.",
            action="copy",
            copy_label="Email webhook config",
            copy_value=json.dumps(setup.get("emailWebhookConfig"), indent=2),
        ))
    elif channel_type == "teams" and setup.get("teamsBridgeConfig"):
        playbook.append(_playbook_step(
            "provider_install",
            "Configure Teams bridge",
            "manual",
            "Copy the bridge config into the Teams bot or adapter service.",
            action="copy",
            copy_label="Teams bridge config",
            copy_value=json.dumps(setup.get("teamsBridgeConfig"), indent=2),
        ))
    elif channel_type == "discord" and setup.get("discordBridgeConfig"):
        playbook.append(_playbook_step(
            "provider_install",
            "Configure Discord bridge",
            "manual",
            "Run the Discord Gateway worker or bridge with this config.",
            action="copy",
            copy_label="Discord bridge config",
            copy_value=json.dumps(setup.get("discordBridgeConfig"), indent=2),
        ))
    elif setup.get("webChatEmbedSnippet"):
        playbook.append(_playbook_step(
            "provider_install",
            "Install web chat",
            "manual",
            "Copy the embed snippet into the customer-facing site.",
            action="copy",
            copy_label="Embed snippet",
            copy_value=str(setup.get("webChatEmbedSnippet") or ""),
            target_url=str(setup.get("webChatUrl") or ""),
        ))

    config_ready = not _has_blocker("support_mode", "ticket_mode", "auto_prepare", "owner_routing")
    config_detail = "New messages create tickets, autopilot prepares replies, and owner routing is set."
    config_action = ""
    if _has_blocker("support_mode"):
        config_detail = "Enable ticket-per-message, autopilot prep, follow-up prep, and human approval."
        config_action = "support_mode"
    elif _has_blocker("ticket_mode"):
        config_detail = "Set ticket creation to one ticket per message."
        config_action = "ticket_mode"
    elif _has_blocker("auto_prepare"):
        config_detail = "Enable autopilot prep for triage, custom fields, and approval drafts."
        config_action = "auto_prepare"
    elif _has_blocker("owner_routing"):
        config_detail = "Set channel, queue, or project default owner routing."
        config_action = "owner_routing"
    playbook.append(_playbook_step(
        "ticket_defaults",
        "Confirm ticket defaults",
        "done" if config_ready else "missing",
        config_detail,
        run_action=config_action,
    ))

    live_target_status = _launch_status("live_smoke_target")
    if live_target_status:
        playbook.append(_playbook_step(
            "live_smoke_target",
            "Set live proof target",
            live_target_status,
            "Configure real provider target IDs or recipient addresses for launch proof.",
            run_action="configure_smoke_target",
        ))

    health_status = str(setup_health.get("status") or "")
    playbook.append(_playbook_step(
        "validate_setup",
        "Validate setup",
        "done" if setup_health.get("ready") else "warning" if health_status == "degraded" else "missing",
        "Run provider credential and setup validation.",
        run_action="provider_validation",
    ))

    if channel_type == "email":
        playbook.append(_playbook_step(
            "inbound_proof",
            "Prove email sync",
            _launch_status("email_sync") or "missing",
            "Sync an email channel and create a support ticket.",
            run_action="email_sync",
        ))
        playbook.append(_playbook_step(
            "outbound_proof",
            "Prove email delivery",
            _launch_status("email_delivery") or "missing",
            "Deliver a queued support reply through the email adapter.",
            run_action="email_delivery",
        ))
    elif channel_type in {"chat", "web_chat"}:
        playbook.append(_playbook_step(
            "inbound_proof",
            "Prove visitor session",
            _launch_status("web_chat_session") or "missing",
            "Open web chat and create a ticket from a visitor message.",
            action="open_url",
            run_action="web_chat_session",
            target_url=str(setup.get("webChatUrl") or ""),
        ))
        playbook.append(_playbook_step(
            "outbound_proof",
            "Prove chat reply",
            _launch_status("web_chat_delivery") or "missing",
            "Send an Inbox reply back into the web chat session.",
            run_action="web_chat_delivery",
        ))
    else:
        playbook.append(_playbook_step(
            "inbound_proof",
            "Run inbound HTTP smoke",
            _launch_status("inbound_smoke", "channel_autopilot") or "missing",
            "Post a provider-shaped message through the public provider endpoint.",
            run_action="inbound_smoke",
        ))
        playbook.append(_playbook_step(
            "outbound_proof",
            "Run outbound smoke",
            _launch_status("outbound_smoke") or "missing",
            "Send an app reply through the configured provider adapter.",
            run_action="outbound_smoke",
        ))
        playbook.append(_playbook_step(
            "lifecycle_proof",
            "Run lifecycle smoke",
            _launch_status("lifecycle_smoke") or "missing",
            "Prove endpoint auth, ticket creation, approval, and provider delivery together.",
            run_action="lifecycle_smoke",
            smoke_command=_channel_lifecycle_smoke_command(channel, project_id),
        ))
        if any(isinstance(check, dict) and str(check.get("key") or "") == "attachment_lifecycle_smoke" for check in launch_checklist):
            playbook.append(_playbook_step(
                "attachment_lifecycle_proof",
                "Run attachment lifecycle smoke",
                _launch_status("attachment_lifecycle_smoke") or "missing",
                "Prove provider file-only messages create tickets and replies deliver.",
                run_action="attachment_lifecycle_smoke",
                smoke_command=_channel_lifecycle_smoke_command(channel, project_id, attachment_only=True),
            ))

    return playbook


def _config_list(config: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        value = config.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [item for item in re.split(r"[\s,]+", value.strip()) if item]
    return []


def _slack_manifest_scopes(config: dict[str, Any], secrets: dict[str, str] | None) -> list[str]:
    scopes = _config_list(config, "oauthScopes", "oauth_scopes")
    if not scopes:
        scopes = [scope for scope in re.split(r"[\s,]+", _default_slack_oauth_scopes(secrets)) if scope]
    return sorted(set(scopes))


def _slack_manifest_bot_events(config: dict[str, Any]) -> list[str]:
    events = _config_list(config, "botEvents", "bot_events")
    if events:
        return events
    return ["message.channels", "message.groups", "message.im", "message.mpim", "app_mention"]


def _slack_app_manifest(
    channel: dict[str, Any],
    setup: dict[str, Any],
    request: Request,
    ctx: ProjectViewerDep,
    secrets: dict[str, str] | None,
) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    scopes = _slack_manifest_scopes(config, secrets)
    bot_events = _slack_manifest_bot_events(config)
    if "app_mention" in bot_events and "app_mentions:read" not in scopes:
        scopes.append("app_mentions:read")
        scopes = sorted(set(scopes))
    app_name = str(
        config.get("appDisplayName")
        or config.get("app_display_name")
        or channel.get("name")
        or "Mantly Support"
    ).strip() or "Mantly Support"
    bot_name = str(config.get("botDisplayName") or config.get("bot_display_name") or "Support Bot").strip() or "Support Bot"
    return {
        "display_information": {
            "name": app_name,
            "description": "Omnichannel support inbox for customer messages.",
            "background_color": "#1F2937",
        },
        "features": {
            "bot_user": {
                "display_name": bot_name,
                "always_online": False,
            },
        },
        "oauth_config": {
            "redirect_urls": [_slack_oauth_redirect_uri(request, ctx.project_id)],
            "scopes": {"bot": scopes},
        },
        "settings": {
            "event_subscriptions": {
                "request_url": str(setup.get("providerWebhookUrl") or ""),
                "bot_events": bot_events,
            },
            "interactivity": {"is_enabled": False},
            "org_deploy_enabled": False,
            "socket_mode_enabled": False,
            "token_rotation_enabled": False,
        },
    }


def _validation_url_template(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}validationToken={{validationToken}}"


def _teams_bridge_config(channel: dict[str, Any], setup: dict[str, Any], ctx: ProjectViewerDep) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    app_id_env, app_password_env = _teams_app_credential_envs(config)
    activity_types = _config_list(config, "activityTypes", "activity_types") or ["message"]
    token_env = str(setup.get("providerTokenEnv") or setup.get("tokenEnv") or "SUPPORT_TEAMS_WEBHOOK_TOKEN")
    token_header = str(setup.get("tokenHeader") or "X-Support-Sync-Token")
    signature_env = str(setup.get("signatureEnv") or "")
    signature_header = str(setup.get("signatureHeader") or "X-Support-Signature")
    signature_timestamp_header = str(setup.get("signatureTimestampHeader") or "X-Support-Signature-Timestamp")
    provider_url = str(setup.get("providerWebhookUrl") or "")
    payload_wrapper: dict[str, Any] = {
        "projectId": ctx.project_id,
        "payload": "<teams activity>",
    }
    if ctx.tenant_id:
        payload_wrapper["tenantId"] = ctx.tenant_id
    return {
        "version": 1,
        "provider": "teams",
        "mode": "bot_activity_bridge",
        "botFramework": {
            "appIdEnv": app_id_env or "SUPPORT_TEAMS_APP_ID",
            "appPasswordEnv": app_password_env or "SUPPORT_TEAMS_APP_PASSWORD",
            "activityTypes": activity_types,
        },
        "sidecar": {
            "module": "automail.support.bridge_app",
            "command": "uvicorn automail.support.bridge_app:app --host 0.0.0.0 --port 8095",
            "publicPath": f"/bridge/teams/{channel.get('channelKey') or ''}",
            "env": {
                "SUPPORT_BRIDGE_CORE_URL": "<core-api-base-url>",
                "SUPPORT_BRIDGE_PROJECT_ID": ctx.project_id,
                "SUPPORT_BRIDGE_TENANT_ID": ctx.tenant_id or "",
                "SUPPORT_BRIDGE_TOKEN_ENV": token_env,
                "SUPPORT_BRIDGE_INBOUND_TOKEN": "<optional-shared-bridge-token>",
                "SUPPORT_BRIDGE_SIGNATURE_SECRET_ENV": signature_env if setup.get("signatureRequired") else "",
                "SUPPORT_BRIDGE_SIGNATURE_HEADER": signature_header if setup.get("signatureRequired") else "",
                "SUPPORT_BRIDGE_SIGNATURE_TIMESTAMP_HEADER": signature_timestamp_header if setup.get("signatureRequired") else "",
            },
        },
        "validation": {
            "method": "GET",
            "urlTemplate": _validation_url_template(provider_url),
            "queryParam": "validationToken",
        },
        "forward": {
            "method": "POST",
            "url": provider_url,
            "headers": {
                token_header: f"${{{token_env}}}",
            },
            "payloadWrapper": payload_wrapper,
        },
        "signature": {
            "enabled": bool(setup.get("signatureRequired")),
            "header": signature_header,
            "timestampHeader": signature_timestamp_header,
            "timestampRequired": bool(setup.get("signatureTimestampRequired")),
            "toleranceSeconds": int(setup.get("signatureToleranceSeconds") or 300),
            "secretEnv": signature_env,
            "algorithm": "hmac_sha256_timestamp_dot_raw_body",
            "prefix": "sha256=",
        },
        "payloadExample": {
            "type": "message",
            "id": "teams-activity-id",
            "text": "Customer message",
            "conversation": {"id": "teams-conversation-id"},
            "from": {"id": "teams-user-id", "name": "Customer"},
            "channelData": {
                "team": {"id": "teams-team-id"},
                "channel": {"id": "teams-channel-id"},
            },
        },
        "ignore": {
            "ownBotUserIdConfigKey": "botUserId",
            "nonMessageActivities": True,
        },
        "notes": [
            "Run this in a Teams Bot Framework or Graph notification bridge.",
            "Forward message activities to the provider webhook URL.",
            "Use the validation URL template for flows that require echoing validationToken.",
        ],
    }


def _discord_bridge_config(channel: dict[str, Any], setup: dict[str, Any], ctx: ProjectViewerDep) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    bot_token_env = str(config.get("discordBotTokenEnv") or config.get("discord_bot_token_env") or "SUPPORT_DISCORD_BOT_TOKEN").strip()
    gateway_intents = _config_list(config, "gatewayIntents", "gateway_intents") or [
        "Guilds",
        "GuildMessages",
        "DirectMessages",
        "MessageContent",
    ]
    gateway_events = _config_list(config, "gatewayEvents", "gateway_events") or ["MESSAGE_CREATE"]
    token_env = str(setup.get("providerTokenEnv") or setup.get("tokenEnv") or "SUPPORT_DISCORD_WEBHOOK_TOKEN")
    token_header = str(setup.get("tokenHeader") or "X-Support-Sync-Token")
    signature_env = str(setup.get("signatureEnv") or "")
    signature_header = str(setup.get("signatureHeader") or "X-Support-Signature")
    signature_timestamp_header = str(setup.get("signatureTimestampHeader") or "X-Support-Signature-Timestamp")
    payload_wrapper: dict[str, Any] = {
        "projectId": ctx.project_id,
        "payload": "<discord gateway event>",
    }
    if ctx.tenant_id:
        payload_wrapper["tenantId"] = ctx.tenant_id
    return {
        "version": 1,
        "provider": "discord",
        "mode": "gateway_bridge",
        "botTokenEnv": bot_token_env or "SUPPORT_DISCORD_BOT_TOKEN",
        "gatewayIntents": gateway_intents,
        "gatewayEvents": gateway_events,
        "sidecar": {
            "module": "automail.support.bridge_app",
            "command": "uvicorn automail.support.bridge_app:app --host 0.0.0.0 --port 8095",
            "publicPath": f"/bridge/discord/{channel.get('channelKey') or ''}",
            "env": {
                "SUPPORT_BRIDGE_CORE_URL": "<core-api-base-url>",
                "SUPPORT_BRIDGE_PROJECT_ID": ctx.project_id,
                "SUPPORT_BRIDGE_TENANT_ID": ctx.tenant_id or "",
                "SUPPORT_BRIDGE_TOKEN_ENV": token_env,
                "SUPPORT_BRIDGE_INBOUND_TOKEN": "<optional-shared-bridge-token>",
                "SUPPORT_BRIDGE_SIGNATURE_SECRET_ENV": signature_env if setup.get("signatureRequired") else "",
                "SUPPORT_BRIDGE_SIGNATURE_HEADER": signature_header if setup.get("signatureRequired") else "",
                "SUPPORT_BRIDGE_SIGNATURE_TIMESTAMP_HEADER": signature_timestamp_header if setup.get("signatureRequired") else "",
            },
        },
        "gatewayWorker": {
            "module": "automail.support.discord_gateway",
            "command": "python -m automail.support.discord_gateway",
            "env": {
                "SUPPORT_DISCORD_BOT_TOKEN": f"${{{bot_token_env or 'SUPPORT_DISCORD_BOT_TOKEN'}}}",
                "SUPPORT_BRIDGE_CORE_URL": "<core-api-base-url>",
                "SUPPORT_BRIDGE_PROJECT_ID": ctx.project_id,
                "SUPPORT_BRIDGE_TENANT_ID": ctx.tenant_id or "",
                "SUPPORT_BRIDGE_DISCORD_CHANNEL_KEY": str(channel.get("channelKey") or ""),
                "SUPPORT_BRIDGE_DISCORD_GATEWAY_EVENTS": ",".join(gateway_events),
                "SUPPORT_BRIDGE_DISCORD_GATEWAY_INTENTS": ",".join(gateway_intents),
                "SUPPORT_BRIDGE_TOKEN_ENV": token_env,
                "SUPPORT_BRIDGE_SIGNATURE_SECRET_ENV": signature_env if setup.get("signatureRequired") else "",
                "SUPPORT_BRIDGE_SIGNATURE_HEADER": signature_header if setup.get("signatureRequired") else "",
                "SUPPORT_BRIDGE_SIGNATURE_TIMESTAMP_HEADER": signature_timestamp_header if setup.get("signatureRequired") else "",
            },
        },
        "forward": {
            "method": "POST",
            "url": str(setup.get("providerWebhookUrl") or ""),
            "headers": {
                token_header: f"${{{token_env}}}",
            },
            "payloadWrapper": payload_wrapper,
        },
        "signature": {
            "enabled": bool(setup.get("signatureRequired")),
            "header": signature_header,
            "timestampHeader": signature_timestamp_header,
            "timestampRequired": bool(setup.get("signatureTimestampRequired")),
            "toleranceSeconds": int(setup.get("signatureToleranceSeconds") or 300),
            "secretEnv": signature_env,
            "algorithm": "hmac_sha256_timestamp_dot_raw_body",
            "prefix": "sha256=",
        },
        "payloadExample": {
            "t": "MESSAGE_CREATE",
            "d": {
                "id": "discord-message-id",
                "channel_id": "discord-channel-id",
                "guild_id": "discord-guild-id",
                "content": "Customer message",
                "author": {"id": "discord-user-id", "username": "Customer"},
            },
        },
        "ignore": {
            "bots": True,
            "ownBotUserIdConfigKey": "botUserId",
        },
        "notes": [
            "Run this in a Discord bot/gateway bridge; Discord does not send MESSAGE_CREATE events to arbitrary outgoing webhooks.",
            "Enable Message Content intent in the Discord Developer Portal when the bridge must read message text.",
            "Forward MESSAGE_CREATE gateway events to the provider webhook URL.",
        ],
    }


def _telegram_webhook_config(channel: dict[str, Any], setup: dict[str, Any], _ctx: ProjectViewerDep) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    bot_token_env = _telegram_bot_token_env(config)
    secret_token_env = str(setup.get("providerSecretEnv") or _telegram_secret_token_env(config))
    secret_header = str(setup.get("providerSecretHeader") or "X-Telegram-Bot-Api-Secret-Token")
    allowed_updates = _config_list(config, "telegramAllowedUpdates", "telegram_allowed_updates") or [
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
    ]
    drop_pending_updates = _config_bool(config, "telegramDropPendingUpdates", "telegram_drop_pending_updates")
    provider_url = str(setup.get("providerWebhookUrl") or "")
    payload_example = {
        "update_id": 123456,
        "message": {
            "message_id": 456,
            "chat": {"id": "telegram-chat-id", "title": "Customer chat", "type": "group"},
            "from": {"id": "telegram-user-id", "first_name": "Customer", "username": "customer"},
            "text": "Customer message",
        },
    }
    return {
        "version": 1,
        "provider": "telegram",
        "mode": "bot_api_webhook",
        "botTokenEnv": bot_token_env,
        "secretTokenEnv": secret_token_env,
        "secretTokenHeader": secret_header,
        "webhookUrl": provider_url,
        "allowedUpdates": allowed_updates,
        "dropPendingUpdates": drop_pending_updates,
        "setWebhook": {
            "method": "POST",
            "urlTemplate": f"https://api.telegram.org/bot{{{bot_token_env}}}/setWebhook",
            "json": {
                "url": provider_url,
                "secret_token": f"${{{secret_token_env}}}",
                "allowed_updates": allowed_updates,
                "drop_pending_updates": drop_pending_updates,
            },
        },
        "deleteWebhook": {
            "method": "POST",
            "urlTemplate": f"https://api.telegram.org/bot{{{bot_token_env}}}/deleteWebhook",
        },
        "payloadExample": payload_example,
        "notes": [
            "Telegram posts updates directly to the provider webhook URL after setWebhook succeeds.",
            "Keep the secret token out of logs; Telegram sends it in X-Telegram-Bot-Api-Secret-Token.",
            "Use the Set Telegram webhook button when runtime secrets are configured.",
        ],
    }


def _line_webhook_config(channel: dict[str, Any], setup: dict[str, Any], _ctx: ProjectViewerDep) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    channel_secret_env = _line_channel_secret_env(config)
    channel_access_token_env = _line_channel_access_token_env(config)
    provider_url = str(setup.get("providerWebhookUrl") or "")
    payload_example = {
        "destination": "line-bot-user-id",
        "events": [
            {
                "type": "message",
                "mode": "active",
                "timestamp": 1710000000000,
                "webhookEventId": "line-webhook-event-id",
                "replyToken": "line-reply-token",
                "source": {
                    "type": "user",
                    "userId": "line-user-id",
                },
                "message": {
                    "id": "line-message-id",
                    "type": "text",
                    "text": "Customer message",
                },
            }
        ],
    }
    return {
        "version": 1,
        "provider": "line",
        "mode": "messaging_api_webhook",
        "webhookUrl": provider_url,
        "signatureHeader": "X-Line-Signature",
        "channelSecretEnv": channel_secret_env,
        "channelAccessTokenEnv": channel_access_token_env,
        "botInfoEndpoint": "https://api.line.me/v2/bot/info",
        "pushEndpoint": "https://api.line.me/v2/bot/message/push",
        "replyEndpoint": "https://api.line.me/v2/bot/message/reply",
        "payloadExample": payload_example,
        "notes": [
            "LINE sends webhook event objects to this provider webhook URL after webhook delivery is enabled.",
            "The core verifies X-Line-Signature with the configured channel secret before ingestion.",
            "Outbound replies use the LINE Messaging API push endpoint with the configured channel access token.",
        ],
    }


def _viber_webhook_config(channel: dict[str, Any], setup: dict[str, Any], _ctx: ProjectViewerDep) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    auth_token_env = _viber_auth_token_env(config)
    provider_url = str(setup.get("providerWebhookUrl") or "")
    payload_example = {
        "event": "message",
        "timestamp": 1710000000000,
        "message_token": 491266184665523145,
        "sender": {
            "id": "viber-user-id",
            "name": "Customer",
            "avatar": "https://example.com/customer.jpg",
            "country": "US",
            "language": "en",
            "api_version": 1,
        },
        "message": {
            "type": "text",
            "text": "Customer message",
            "tracking_data": "support-ticket",
        },
    }
    return {
        "version": 1,
        "provider": "viber",
        "mode": "bot_api_webhook",
        "webhookUrl": provider_url,
        "signatureHeader": "X-Viber-Content-Signature",
        "authTokenEnv": auth_token_env,
        "setWebhookEndpoint": "https://chatapi.viber.com/pa/set_webhook",
        "accountInfoEndpoint": "https://chatapi.viber.com/pa/get_account_info",
        "sendMessageEndpoint": "https://chatapi.viber.com/pa/send_message",
        "setWebhook": {
            "method": "POST",
            "url": "https://chatapi.viber.com/pa/set_webhook",
            "headers": {"X-Viber-Auth-Token": f"${{{auth_token_env}}}"},
            "json": {
                "url": provider_url,
                "event_types": ["delivered", "seen", "failed", "conversation_started"],
                "send_name": True,
                "send_photo": True,
            },
        },
        "payloadExample": payload_example,
        "notes": [
            "Viber posts callbacks directly to this provider webhook URL after set_webhook succeeds.",
            "The core verifies X-Viber-Content-Signature with the configured Viber auth token before ingestion.",
            "Outbound replies use Viber send_message with the same auth token.",
        ],
    }


def _whatsapp_webhook_config(channel: dict[str, Any], setup: dict[str, Any], _ctx: ProjectViewerDep) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    verify_token_env = str(
        config.get("whatsappVerifyTokenEnv")
        or config.get("whatsapp_verify_token_env")
        or config.get("verifyTokenEnv")
        or config.get("verify_token_env")
        or "SUPPORT_WHATSAPP_VERIFY_TOKEN"
    ).strip() or "SUPPORT_WHATSAPP_VERIFY_TOKEN"
    phone_number_id_env = str(
        config.get("phoneNumberIdEnv")
        or config.get("phone_number_id_env")
        or "SUPPORT_WHATSAPP_PHONE_NUMBER_ID"
    ).strip() or "SUPPORT_WHATSAPP_PHONE_NUMBER_ID"
    access_token_env = str(
        setup.get("outboundWebhookTokenEnv")
        or config.get("outboundWebhookTokenEnv")
        or config.get("outbound_webhook_token_env")
        or "SUPPORT_WHATSAPP_ACCESS_TOKEN"
    ).strip() or "SUPPORT_WHATSAPP_ACCESS_TOKEN"
    provider_url = str(setup.get("providerWebhookUrl") or "")
    payload_example = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "whatsapp-business-account-id",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {
                                "display_phone_number": "+15550001111",
                                "phone_number_id": "whatsapp-phone-number-id",
                            },
                            "contacts": [
                                {
                                    "wa_id": "15551234567",
                                    "profile": {"name": "Customer"},
                                }
                            ],
                            "messages": [
                                {
                                    "from": "15551234567",
                                    "id": "wamid.customer-message-id",
                                    "timestamp": "1710000000",
                                    "text": {"body": "Customer message"},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    return {
        "version": 1,
        "provider": "whatsapp",
        "mode": "cloud_api_webhook",
        "webhookUrl": provider_url,
        "verifyTokenEnv": verify_token_env,
        "signatureHeader": "X-Hub-Signature-256",
        "signatureEnv": str(setup.get("signatureEnv") or ""),
        "phoneNumberIdEnv": phone_number_id_env,
        "accessTokenEnv": access_token_env,
        "messagesEndpointTemplate": f"https://graph.facebook.com/v20.0/{{{phone_number_id_env}}}/messages",
        "payloadExample": payload_example,
        "notes": [
            "Meta verifies this callback with hub.mode=subscribe, hub.verify_token, and hub.challenge.",
            "Meta sends message changes to this provider webhook URL after webhook subscription succeeds.",
            "Outbound replies use the Cloud API messages endpoint with the configured access token env.",
        ],
    }


def _messenger_webhook_config(channel: dict[str, Any], setup: dict[str, Any], _ctx: ProjectViewerDep) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    verify_token_env = str(
        config.get("messengerVerifyTokenEnv")
        or config.get("messenger_verify_token_env")
        or config.get("verifyTokenEnv")
        or config.get("verify_token_env")
        or "SUPPORT_MESSENGER_VERIFY_TOKEN"
    ).strip() or "SUPPORT_MESSENGER_VERIFY_TOKEN"
    page_id_env = _messenger_page_id_env(config)
    access_token_env = str(
        setup.get("outboundWebhookTokenEnv")
        or config.get("outboundWebhookTokenEnv")
        or config.get("outbound_webhook_token_env")
        or _messenger_page_access_token_env(config)
    ).strip() or "SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN"
    provider_url = str(setup.get("providerWebhookUrl") or "")
    payload_example = {
        "object": "page",
        "entry": [
            {
                "id": "facebook-page-id",
                "time": 1710000000000,
                "messaging": [
                    {
                        "sender": {"id": "customer-psid"},
                        "recipient": {"id": "facebook-page-id"},
                        "timestamp": 1710000000000,
                        "message": {
                            "mid": "m_customer_message_id",
                            "text": "Customer message",
                        },
                    }
                ],
            }
        ],
    }
    return {
        "version": 1,
        "provider": "messenger",
        "mode": "facebook_page_messenger_webhook",
        "webhookUrl": provider_url,
        "verifyTokenEnv": verify_token_env,
        "signatureHeader": "X-Hub-Signature-256",
        "signatureEnv": str(setup.get("signatureEnv") or ""),
        "pageIdEnv": page_id_env,
        "pageAccessTokenEnv": access_token_env,
        "messagesEndpointTemplate": f"https://graph.facebook.com/v20.0/{{{page_id_env}}}/messages",
        "payloadExample": payload_example,
        "notes": [
            "Meta verifies this callback with hub.mode=subscribe, hub.verify_token, and hub.challenge.",
            "Messenger sends page messaging events to this provider webhook URL after subscription succeeds.",
            "Outbound replies use the Graph API Page messages endpoint with the configured Page Access Token env.",
        ],
    }


def _instagram_webhook_config(channel: dict[str, Any], setup: dict[str, Any], _ctx: ProjectViewerDep) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    verify_token_env = str(
        config.get("instagramVerifyTokenEnv")
        or config.get("instagram_verify_token_env")
        or config.get("verifyTokenEnv")
        or config.get("verify_token_env")
        or "SUPPORT_INSTAGRAM_VERIFY_TOKEN"
    ).strip() or "SUPPORT_INSTAGRAM_VERIFY_TOKEN"
    account_id_env = _instagram_account_id_env(config)
    access_token_env = str(
        config.get("instagramAccessTokenEnv")
        or config.get("instagram_access_token_env")
        or _instagram_access_token_env(config)
    ).strip() or "SUPPORT_INSTAGRAM_ACCESS_TOKEN"
    provider_url = str(setup.get("providerWebhookUrl") or "")
    payload_example = {
        "object": "instagram",
        "entry": [
            {
                "id": "instagram-business-account-id",
                "time": 1710000000000,
                "messaging": [
                    {
                        "sender": {"id": "instagram-scoped-user-id"},
                        "recipient": {"id": "instagram-business-account-id"},
                        "timestamp": 1710000000000,
                        "message": {
                            "mid": "ig_mid_customer_message_id",
                            "text": "Customer message",
                        },
                    }
                ],
            }
        ],
    }
    return {
        "version": 1,
        "provider": "instagram",
        "mode": "instagram_messaging_webhook",
        "webhookUrl": provider_url,
        "verifyTokenEnv": verify_token_env,
        "signatureHeader": "X-Hub-Signature-256",
        "signatureEnv": str(setup.get("signatureEnv") or ""),
        "instagramAccountIdEnv": account_id_env,
        "accessTokenEnv": access_token_env,
        "messagesEndpointTemplate": f"https://graph.facebook.com/v20.0/{{{account_id_env}}}/messages",
        "payloadExample": payload_example,
        "notes": [
            "Meta verifies this callback with hub.mode=subscribe, hub.verify_token, and hub.challenge.",
            "Instagram sends messaging events to this provider webhook URL after subscription succeeds.",
            "Outbound replies use the Graph API messages endpoint with the configured Instagram access token env.",
        ],
    }


def _twitter_webhook_config(channel: dict[str, Any], setup: dict[str, Any], _ctx: ProjectViewerDep) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    consumer_secret_env = _twitter_consumer_secret_env(config)
    bearer_token_env = _twitter_bearer_token_env(config)
    user_access_token_env = _twitter_user_access_token_env(config)
    user_id_env = _twitter_user_id_env(config)
    provider_url = str(setup.get("providerWebhookUrl") or "")
    payload_example = {
        "for_user_id": "4337869213",
        "direct_message_events": [
            {
                "type": "message_create",
                "id": "954491830116155396",
                "created_timestamp": "1516403560557",
                "message_create": {
                    "target": {"recipient_id": "4337869213"},
                    "sender_id": "3001969357",
                    "source_app_id": "13090192",
                    "message_data": {
                        "text": "Customer message",
                        "entities": {"hashtags": [], "symbols": [], "user_mentions": [], "urls": []},
                    },
                },
            }
        ],
        "users": {
            "3001969357": {"id": "3001969357", "name": "Customer", "screen_name": "customer"},
            "4337869213": {"id": "4337869213", "name": "Support", "screen_name": "support"},
        },
    }
    return {
        "version": 1,
        "provider": "twitter",
        "mode": "x_account_activity_webhook",
        "webhookUrl": provider_url,
        "crc": {
            "method": "GET",
            "queryParam": "crc_token",
            "responseJsonKey": "response_token",
            "consumerSecretEnv": consumer_secret_env,
        },
        "signatureHeader": "x-twitter-webhooks-signature",
        "signatureEnv": str(setup.get("signatureEnv") or consumer_secret_env),
        "bearerTokenEnv": bearer_token_env,
        "userAccessTokenEnv": user_access_token_env,
        "subscribedUserIdEnv": user_id_env,
        "sendMessageEndpointTemplate": "https://api.x.com/2/dm_conversations/with/{participant_id}/messages",
        "payloadExample": payload_example,
        "notes": [
            "X validates this callback by sending crc_token and expecting a JSON response_token signed with the consumer secret.",
            "X signs POST bodies with x-twitter-webhooks-signature using the same consumer secret.",
            "Outbound replies use the X API v2 Manage Direct Messages endpoint with a user access token.",
        ],
    }


def _twitter_bridge_config(channel: dict[str, Any], setup: dict[str, Any], ctx: ProjectViewerDep) -> dict[str, Any]:
    channel_key = str(channel.get("channelKey") or channel.get("channel_key") or "").strip()
    public_path = f"/bridge/twitter/{channel_key}"
    token_env = str(setup.get("providerTokenEnv") or setup.get("tokenEnv") or "").strip()
    token_header = str(setup.get("tokenHeader") or "X-Support-Sync-Token")
    signature_env = str(setup.get("signatureEnv") or "")
    signature_header = str(setup.get("signatureHeader") or "x-twitter-webhooks-signature")
    payload_wrapper: dict[str, Any] = {
        "projectId": ctx.project_id,
        "payload": "<twitter webhook event>",
    }
    if ctx.tenant_id:
        payload_wrapper["tenantId"] = ctx.tenant_id
    return {
        "version": 1,
        "provider": "twitter",
        "mode": "x_webhook_bridge",
        "sidecar": {
            "module": "automail.support.bridge_app",
            "command": "uvicorn automail.support.bridge_app:app --host 0.0.0.0 --port 8095",
            "publicPath": public_path,
            "publicUrlTemplate": f"<bridge-public-base-url>{public_path}",
            "env": {
                "SUPPORT_BRIDGE_CORE_URL": "<core-api-base-url>",
                "SUPPORT_BRIDGE_PROJECT_ID": ctx.project_id,
                "SUPPORT_BRIDGE_TENANT_ID": ctx.tenant_id or "",
                "SUPPORT_BRIDGE_TOKEN_ENV": token_env,
                "SUPPORT_BRIDGE_INBOUND_TOKEN": "<optional-shared-bridge-token>",
                "SUPPORT_BRIDGE_SIGNATURE_SECRET_ENV": signature_env if setup.get("signatureRequired") else "",
                "SUPPORT_BRIDGE_SIGNATURE_HEADER": signature_header if setup.get("signatureRequired") else "",
                "SUPPORT_BRIDGE_SIGNATURE_TIMESTAMP_HEADER": str(setup.get("signatureTimestampHeader") or ""),
            },
        },
        "validation": {
            "method": "GET",
            "publicPath": public_path,
            "callbackUrlTemplate": f"<bridge-public-base-url>{public_path}",
            "queryParams": {"crc_token": "{crc_token}"},
            "coreUrl": str(setup.get("providerWebhookUrl") or ""),
            "response": {"jsonKey": "response_token"},
        },
        "forward": {
            "method": "POST",
            "publicPath": public_path,
            "coreUrl": str(setup.get("providerWebhookUrl") or ""),
            "headers": {
                token_header: f"${{{token_env}}}" if token_env else "<forward-token>",
            },
            "payloadWrapper": payload_wrapper,
        },
        "signature": {
            "enabled": bool(setup.get("signatureRequired")),
            "header": signature_header,
            "secretEnv": signature_env,
            "algorithm": "hmac_sha256_raw_body",
            "prefix": "sha256=",
            "note": "Bridge forwards CRC validation to core and signs wrapped POST bodies for the core endpoint.",
        },
        "notes": [
            "Use this when X can reach the bridge but the core API is private.",
            "Set the X webhook URL to <bridge-public-base-url> plus publicPath.",
            "Keep the X consumer secret in runtime env or project secrets; it is needed for CRC and signatures.",
        ],
    }


def _meta_bridge_config(
    channel: dict[str, Any],
    setup: dict[str, Any],
    ctx: ProjectViewerDep,
    *,
    provider: str,
) -> dict[str, Any]:
    channel_key = str(channel.get("channelKey") or channel.get("channel_key") or "").strip()
    public_path = f"/bridge/{provider}/{channel_key}"
    verify_token_env = str(setup.get("providerVerifyTokenEnv") or "").strip()
    token_env = str(setup.get("providerTokenEnv") or setup.get("tokenEnv") or "").strip()
    token_header = str(setup.get("tokenHeader") or "X-Support-Sync-Token")
    signature_env = str(setup.get("signatureEnv") or "")
    signature_header = str(setup.get("signatureHeader") or "X-Hub-Signature-256")
    signature_timestamp_header = str(setup.get("signatureTimestampHeader") or "X-Support-Signature-Timestamp")
    payload_label = f"<{provider} webhook event>"
    payload_wrapper: dict[str, Any] = {
        "projectId": ctx.project_id,
        "payload": payload_label,
    }
    if ctx.tenant_id:
        payload_wrapper["tenantId"] = ctx.tenant_id
    return {
        "version": 1,
        "provider": provider,
        "mode": "meta_webhook_bridge",
        "sidecar": {
            "module": "automail.support.bridge_app",
            "command": "uvicorn automail.support.bridge_app:app --host 0.0.0.0 --port 8095",
            "publicPath": public_path,
            "publicUrlTemplate": f"<bridge-public-base-url>{public_path}",
            "env": {
                "SUPPORT_BRIDGE_CORE_URL": "<core-api-base-url>",
                "SUPPORT_BRIDGE_PROJECT_ID": ctx.project_id,
                "SUPPORT_BRIDGE_TENANT_ID": ctx.tenant_id or "",
                "SUPPORT_BRIDGE_TOKEN_ENV": token_env,
                "SUPPORT_BRIDGE_INBOUND_TOKEN": "<optional-shared-bridge-token>",
                "SUPPORT_BRIDGE_SIGNATURE_SECRET_ENV": signature_env if setup.get("signatureRequired") else "",
                "SUPPORT_BRIDGE_SIGNATURE_HEADER": signature_header if setup.get("signatureRequired") else "",
                "SUPPORT_BRIDGE_SIGNATURE_TIMESTAMP_HEADER": signature_timestamp_header if setup.get("signatureRequired") else "",
            },
        },
        "validation": {
            "method": "GET",
            "publicPath": public_path,
            "callbackUrlTemplate": f"<bridge-public-base-url>{public_path}",
            "queryParams": {
                "hub.mode": "subscribe",
                "hub.verify_token": f"${{{verify_token_env}}}" if verify_token_env else "<verify-token>",
                "hub.challenge": "{hub.challenge}",
            },
            "coreUrl": str(setup.get("providerWebhookUrl") or ""),
        },
        "forward": {
            "method": "POST",
            "publicPath": public_path,
            "coreUrl": str(setup.get("providerWebhookUrl") or ""),
            "headers": {
                token_header: f"${{{token_env}}}" if token_env else "<forward-token>",
            },
            "payloadWrapper": payload_wrapper,
        },
        "signature": {
            "enabled": bool(setup.get("signatureRequired")),
            "header": signature_header,
            "timestampHeader": signature_timestamp_header,
            "timestampRequired": bool(setup.get("signatureTimestampRequired")),
            "toleranceSeconds": int(setup.get("signatureToleranceSeconds") or 300),
            "secretEnv": signature_env,
            "algorithm": "hmac_sha256_timestamp_dot_raw_body",
            "prefix": "sha256=",
            "note": "Bridge signs the wrapped forward body for the core endpoint; Meta signs the original provider body before it reaches the bridge.",
        },
        "notes": [
            "Use this when Meta can reach the bridge but the core API is private.",
            "Set the Meta callback URL to <bridge-public-base-url> plus publicPath.",
            "Keep the verify token and app secret in runtime env or project secrets; do not paste secret values into the app UI.",
        ],
    }


def _twilio_webhook_config(channel: dict[str, Any], setup: dict[str, Any], _ctx: ProjectViewerDep) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    provider_url = str(setup.get("providerWebhookUrl") or "")
    sms_url = str(setup.get("smsWebhookUrl") or "")
    payload_example = {
        "MessageSid": "SMXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "SmsSid": "SMXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "AccountSid": "ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "From": str(config.get("smokeToAddress") or "+15551234567"),
        "To": str(config.get("smokeChannelId") or "+15550001111"),
        "Body": "Customer SMS message",
        "NumMedia": "0",
        "SmsStatus": "received",
    }
    receipt_payload_example = {
        "MessageSid": "SMXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "AccountSid": "ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "From": str(config.get("smokeChannelId") or "+15550001111"),
        "To": str(config.get("smokeToAddress") or "+15551234567"),
        "MessageStatus": "delivered",
    }
    return {
        "version": 1,
        "provider": "twilio",
        "mode": "sms_webhook",
        "webhookUrl": provider_url,
        "smsWebhookUrl": sms_url,
        "alternateWebhookUrls": [sms_url] if sms_url and sms_url != provider_url else [],
        "method": "POST",
        "contentType": "application/x-www-form-urlencoded",
        "tokenHeader": setup.get("tokenHeader", "X-Support-Sync-Token"),
        "tokenEnv": setup.get("providerTokenEnv", "SUPPORT_TWILIO_WEBHOOK_TOKEN"),
        "nativeSignatureHeader": setup.get("twilioSignatureHeader", "X-Twilio-Signature"),
        "nativeSignatureAuthTokenEnv": setup.get("twilioSignatureAuthTokenEnv", _twilio_auth_token_env(config)),
        "nativeSignatureReady": bool(setup.get("twilioNativeSignatureReady")),
        "signatureHeader": setup.get("signatureHeader", "X-Support-Signature"),
        "signatureEnv": setup.get("signatureEnv", ""),
        "signatureRequired": bool(setup.get("signatureRequired")),
        "accountSidEnv": _twilio_account_sid_env(config),
        "authTokenEnv": _twilio_auth_token_env(config),
        "fromNumberEnv": _twilio_from_number_env(config),
        "incomingMessage": {
            "url": sms_url or provider_url,
            "providerUrl": provider_url,
            "contentType": "application/x-www-form-urlencoded",
            "payload": payload_example,
        },
        "statusCallback": {
            "url": sms_url or provider_url,
            "providerUrl": provider_url,
            "contentType": "application/x-www-form-urlencoded",
            "payload": receipt_payload_example,
        },
        "payloadExample": payload_example,
        "receiptPayloadExample": receipt_payload_example,
        "notes": [
            "Twilio posts incoming SMS and delivery status callbacks as form data.",
            "Set both incoming message webhook and status callback to the SMS webhook URL or Twilio provider URL.",
            "Direct Twilio calls are verified with X-Twilio-Signature and the configured Auth Token when present.",
            "Outbound replies use Twilio Messages API with the configured Account SID, Auth Token, and sender.",
        ],
    }


def _email_webhook_config(channel: dict[str, Any], setup: dict[str, Any], ctx: ProjectViewerDep) -> dict[str, Any]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    provider_url = str(setup.get("providerWebhookUrl") or setup.get("emailWebhookUrl") or "")
    payload_example = {
        "projectId": ctx.project_id,
        "email": {
            "messageId": "provider-message-123",
            "threadId": "customer-thread-123",
            "subject": "Need help with onboarding",
            "fromAddress": "customer@example.com",
            "body": "Can you help me finish setup?",
            "bodyHtml": "<p>Can you help me finish setup?</p>",
            "attachments": [
                {
                    "filename": "context.txt",
                    "contentType": "text/plain",
                    "base64": "Y29udGV4dA==",
                }
            ],
        },
    }
    if ctx.tenant_id:
        payload_example["tenantId"] = ctx.tenant_id
    return {
        "version": 1,
        "provider": "email",
        "mode": "email_json_webhook",
        "webhookUrl": provider_url,
        "method": "POST",
        "contentType": "application/json",
        "tokenHeader": setup.get("tokenHeader", "X-Support-Sync-Token"),
        "tokenEnv": setup.get("providerTokenEnv", "SUPPORT_EMAIL_WEBHOOK_TOKEN"),
        "signatureHeader": setup.get("signatureHeader", "X-Support-Signature"),
        "signatureEnv": setup.get("signatureEnv", ""),
        "signatureRequired": bool(setup.get("signatureRequired")),
        "imapAdapter": {
            "enabled": str(config.get("adapter") or "").strip().lower() == "imap",
            "host": str(config.get("host") or ""),
            "mailbox": str(config.get("mailbox") or "INBOX"),
            "username": str(config.get("username") or config.get("user") or ""),
            "passwordEnv": str(config.get("passwordEnv") or config.get("password_env") or "SUPPORT_IMAP_PASSWORD"),
        },
        "payloadExample": payload_example,
        "notes": [
            "Use this endpoint for inbound email gateways that can POST normalized email JSON.",
            "IMAP polling remains supported when adapter=imap is configured.",
            "A successful webhook records an email sync run and creates or updates the support ticket.",
            "Outbound replies can use SMTP or the email outbound webhook adapter.",
        ],
    }


def _channel_setup(
    channel: dict[str, Any],
    ctx: ProjectViewerDep,
    request: Request,
    sync_runs: list[dict[str, Any]] | None = None,
    launch_proof_items: dict[str, dict[str, Any]] | None = None,
    webhook_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    channel_key = str(channel.get("channelKey") or "").strip()
    encoded_key = quote(channel_key, safe="")
    query = _scoped_query(ctx)
    channel_type = str(channel.get("type") or "").strip().lower()
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    runtime_secrets = load_runtime_secrets(ctx.tenant_id, ctx.project_id) or {}
    signature_header = str(config.get("signatureHeader") or config.get("signature_header") or "X-Support-Signature").strip()
    signature_env = str(
        config.get("signatureSecretEnv")
        or config.get("webhookSignatureSecretEnv")
        or config.get("signature_secret_env")
        or f"SUPPORT_CHANNEL_{channel_key.upper().replace(':', '_').replace('-', '_')}_SIGNING_SECRET"
    ).strip()
    signature_timestamp_required, signature_timestamp_header, signature_tolerance_seconds = _signature_timestamp_config(config)
    generic_path = f"/api/internal/support/channel-webhooks/{encoded_key}"
    ticket_creation_mode = str(
        config.get("ticketCreationMode")
        or config.get("ticket_creation_mode")
        or "per_message"
    ).strip() or "per_message"
    if ticket_creation_mode not in {"per_message", "per_thread"}:
        ticket_creation_mode = "per_message"
    auto_prepare_triage = _config_bool(config, "autoPrepareTriage", "auto_prepare_triage", default=True)
    auto_prepare_custom_fields = _config_bool(
        config,
        "autoPrepareCustomFields",
        "auto_prepare_custom_fields",
        default=True,
    )
    auto_prepare_agent_reply = _config_bool(config, "autoPrepareAgentReply", "auto_prepare_agent_reply")
    auto_prepare_agent_reply_on_update = _config_bool(
        config,
        "autoPrepareAgentReplyOnUpdate",
        "auto_prepare_agent_reply_on_update",
    )
    agent_auto_send = _config_bool(
        config,
        "agentAutoSend",
        "agent_auto_send",
        "autoSendAgentReply",
        "auto_send_agent_reply",
    )
    outbound_webhook_url = str(config.get("outboundWebhookUrl") or config.get("outbound_webhook_url") or "").strip()
    outbound_webhook_url_env = str(config.get("outboundWebhookUrlEnv") or config.get("outbound_webhook_url_env") or "").strip()
    outbound_webhook_url_template = str(
        config.get("outboundWebhookUrlTemplate") or config.get("outbound_webhook_url_template") or ""
    ).strip()
    outbound_webhook_token_env = str(config.get("outboundWebhookTokenEnv") or config.get("outbound_webhook_token_env") or "").strip()
    outbound_token_required = _config_bool(config, "outboundTokenRequired", "outbound_token_required")
    inbound_webhook_token_env = str(
        config.get("webhookTokenEnv")
        or config.get("webhook_token_env")
        or config.get("emailWebhookTokenEnv")
        or config.get("email_webhook_token_env")
        or config.get("providerTokenEnv")
        or config.get("provider_token_env")
        or "SUPPORT_CHANNEL_WEBHOOK_TOKEN"
    ).strip()
    provider_name = _provider_name(channel_type)
    provider_token_env = ""
    provider_secret_env = ""
    provider_secret_header = ""
    auth_envs = [
        _env_status(inbound_webhook_token_env, "Generic channel webhook token", secrets=runtime_secrets),
        _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
    ]
    outbound_envs: list[dict[str, Any]] = []
    signature_configured = bool(
        config.get("signatureSecretEnv")
        or config.get("webhookSignatureSecretEnv")
        or config.get("signature_secret_env")
    )
    auth_configured = (
        _env_present(signature_env, runtime_secrets)
        if signature_configured
        else _env_present(inbound_webhook_token_env, runtime_secrets)
        or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
    )
    if signature_configured:
        auth_envs = [_env_status(signature_env, "Per-channel webhook HMAC secret", required=True, secrets=runtime_secrets)]
    outbound_url_ready = bool(
        outbound_webhook_url
        or (outbound_webhook_url_env and _env_present(outbound_webhook_url_env, runtime_secrets))
        or _template_ready(outbound_webhook_url_template, runtime_secrets)
    )
    outbound_token_ready = bool(
        not outbound_token_required
        or (outbound_webhook_token_env and _env_present(outbound_webhook_token_env, runtime_secrets))
    )
    outbound_ready = outbound_url_ready and outbound_token_ready
    setup: dict[str, Any] = {
        "providerName": provider_name,
        "inboundWebhookUrl": _url(request, generic_path, query),
        "inboundWebhookPath": generic_path,
        "tokenHeader": "X-Support-Sync-Token",
        "tokenEnv": inbound_webhook_token_env,
        "fallbackTokenEnv": "SUPPORT_SYNC_TOKEN",
        "signatureHeader": signature_header or "X-Support-Signature",
        "signatureEnv": signature_env,
        "signatureConfigKey": "signatureSecretEnv",
        "signatureTimestampHeader": signature_timestamp_header,
        "signatureTimestampRequired": signature_timestamp_required,
        "signatureToleranceSeconds": signature_tolerance_seconds,
        "signatureRequired": bool(
            config.get("signatureSecretEnv")
            or config.get("webhookSignatureSecretEnv")
            or config.get("signature_secret_env")
        ),
        "ticketCreationMode": ticket_creation_mode,
        "ticketCreationConfigKey": "ticketCreationMode",
        "autoPrepareTriage": auto_prepare_triage,
        "autoPrepareCustomFields": auto_prepare_custom_fields,
        "autoPrepareAgentReply": auto_prepare_agent_reply,
        "autoPrepareAgentReplyOnUpdate": auto_prepare_agent_reply_on_update,
        "agentAutoSend": agent_auto_send,
        "autoPrepareConfigKeys": [
            "autoPrepareTriage",
            "autoPrepareCustomFields",
            "autoPrepareAgentReply",
            "autoPrepareAgentReplyOnUpdate",
            "agentAutoSend",
            "agentQuestion",
        ],
        "outboundWebhookUrl": outbound_webhook_url,
        "outboundWebhookUrlEnv": outbound_webhook_url_env,
        "outboundWebhookUrlTemplate": outbound_webhook_url_template,
        "outboundWebhookTokenEnv": outbound_webhook_token_env,
        "outboundTokenRequired": outbound_token_required,
        "outboundWebhookConfigured": bool(outbound_webhook_url or outbound_webhook_url_env or outbound_webhook_url_template),
        "outboundReady": outbound_ready,
        "outboundConfigKeys": [
            "outboundWebhookUrl",
            "outboundWebhookUrlEnv",
            "outboundWebhookUrlTemplate",
            "outboundWebhookTokenEnv",
            "outboundTokenRequired",
            "outboundPayloadMode",
        ],
        "messagePayloadExample": {
            "eventId": "msg_123",
            "eventType": "message_created",
            "provider": channel_type or "channel",
            "channelId": "customer-channel",
            "threadId": "customer-thread",
            "messageId": "msg_123",
            "content": "Customer message",
            "author": {"id": "user_123", "name": "Customer"},
        },
        "receiptPayloadExample": {
            "eventId": "delivered_123",
            "eventType": "delivered",
            "providerMessageId": "provider-message-id",
        },
    }
    if channel_type == "email":
        provider_path = f"/api/internal/support/email/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_EMAIL_WEBHOOK_TOKEN"
        email_outbound_webhook_url_env = outbound_webhook_url_env or "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_URL"
        email_outbound_webhook_token_env = outbound_webhook_token_env or "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_TOKEN"
        auth_configured = (
            _env_present(signature_env, runtime_secrets)
            if signature_configured
            else _env_present(provider_token_env, runtime_secrets) or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
        )
        auth_envs = [
            _env_status(provider_token_env, "Email inbound webhook token", secrets=runtime_secrets),
            _env_status(
                signature_env,
                "Per-channel email webhook HMAC secret",
                required=signature_configured,
                secrets=runtime_secrets,
            ) if signature_configured else None,
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        outbound_envs = [
            _env_status("SMTP_HOST", "SMTP host for outbound email replies", required=True, secrets=runtime_secrets),
            _env_status("SMTP_FROM", "SMTP sender address", secrets=runtime_secrets),
            _env_status("SMTP_USER", "SMTP username and optional sender fallback", secrets=runtime_secrets),
            _env_status("SMTP_PASSWORD", "SMTP password secret", secrets=runtime_secrets),
            _env_status(
                email_outbound_webhook_url_env,
                "Email outbound webhook URL for reply delivery adapter",
                secrets=runtime_secrets,
            ),
            _env_status(
                email_outbound_webhook_token_env,
                "Email outbound webhook bearer token",
                required=outbound_token_required,
                secrets=runtime_secrets,
            ),
        ]
        smtp_outbound_ready = _env_present("SMTP_HOST", runtime_secrets) and (
            _env_present("SMTP_FROM", runtime_secrets) or _env_present("SMTP_USER", runtime_secrets)
        )
        email_outbound_webhook_ready = bool(
            outbound_webhook_url
            or _env_present(email_outbound_webhook_url_env, runtime_secrets)
            or _template_ready(outbound_webhook_url_template, runtime_secrets)
        ) and (not outbound_token_required or _env_present(email_outbound_webhook_token_env, runtime_secrets))
        outbound_ready = smtp_outbound_ready or email_outbound_webhook_ready
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "emailWebhookUrl": _url(request, provider_path, query),
            "emailWebhookPath": provider_path,
            "providerTokenEnv": provider_token_env,
            "signatureEnv": signature_env,
            "signatureRequired": signature_configured,
            "providerSignatureConfigKey": "signatureSecretEnv",
            "outboundReady": outbound_ready,
            "outboundTransport": "smtp",
            "outboundDeliveryModes": ["smtp", "email_webhook"],
            "outboundWebhookUrlEnv": email_outbound_webhook_url_env,
            "outboundWebhookTokenEnv": email_outbound_webhook_token_env,
            "emailOutboundWebhookUrlEnv": email_outbound_webhook_url_env,
            "emailOutboundWebhookTokenEnv": email_outbound_webhook_token_env,
            "emailOutboundWebhookReady": email_outbound_webhook_ready,
            "emailOutboundWebhookConfigured": bool(
                outbound_webhook_url
                or outbound_webhook_url_env
                or outbound_webhook_url_template
                or _env_present(email_outbound_webhook_url_env, runtime_secrets)
            ),
            "smtpOutboundReady": smtp_outbound_ready,
            "outboundWebhookConfigured": True,
            "outboundProviderCredentialEnvVars": ["SMTP_HOST", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD"],
            "outboundConfigKeys": [
                *setup.get("outboundConfigKeys", []),
                "SMTP_HOST",
                "SMTP_FROM",
                "SMTP_USER",
                "SMTP_PASSWORD",
                "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_URL",
                "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_TOKEN",
            ],
        })
        email_config = _email_webhook_config(channel, setup, ctx)
        setup["emailWebhookConfig"] = email_config
        setup["messagePayloadExample"] = email_config["payloadExample"]
    elif channel_type == "slack":
        provider_path = f"/api/internal/support/slack/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_SLACK_WEBHOOK_TOKEN"
        slack_bot_token_env = _slack_bot_token_env(config)
        slack_bot_outbound = _slack_uses_bot_outbound(config) or (
            not _has_outbound_webhook(config, runtime_secrets)
            and _env_present(slack_bot_token_env, runtime_secrets)
        )
        slack_signature_configured = bool(
            config.get("slackSigningSecretEnv")
            or config.get("slack_signing_secret_env")
            or config.get("signatureSecretEnv")
            or config.get("webhookSignatureSecretEnv")
            or config.get("signature_secret_env")
        )
        slack_signature_env = str(
            config.get("slackSigningSecretEnv")
            or config.get("slack_signing_secret_env")
            or config.get("signatureSecretEnv")
            or config.get("webhookSignatureSecretEnv")
            or config.get("signature_secret_env")
            or "SUPPORT_SLACK_SIGNING_SECRET"
        ).strip()
        slack_signature_required = slack_signature_configured or _env_present(slack_signature_env, runtime_secrets)
        auth_configured = (
            _env_present(slack_signature_env, runtime_secrets)
            if slack_signature_required
            else _env_present(provider_token_env, runtime_secrets) or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
        )
        auth_envs = [
            _env_status(slack_signature_env, "Slack signing secret", required=slack_signature_required, secrets=runtime_secrets),
            _env_status(provider_token_env, "Slack webhook token", secrets=runtime_secrets),
            _env_status(slack_bot_token_env, "Slack bot token with chat:write", required=slack_bot_outbound, secrets=runtime_secrets),
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        if slack_bot_outbound:
            outbound_ready = _env_present(slack_bot_token_env, runtime_secrets)
            setup.update({
                "outboundReady": outbound_ready,
                "outboundTransport": "bot",
                "outboundBotTokenEnv": slack_bot_token_env,
                "outboundWebhookConfigured": True,
            })
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "providerTokenEnv": provider_token_env,
            "signatureEnv": slack_signature_env,
            "signatureHeader": "X-Slack-Signature",
            "signatureRequired": slack_signature_required,
            "providerSignatureConfigKey": "slackSigningSecretEnv",
            "providerSignatureFallbackConfigKey": "signatureSecretEnv",
        })
        setup["slackManifest"] = _slack_app_manifest(channel, setup, request, ctx, runtime_secrets)
    elif channel_type == "teams":
        provider_path = f"/api/internal/support/teams/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_TEAMS_WEBHOOK_TOKEN"
        teams_app_id_env, teams_app_password_env = _teams_app_credential_envs(config)
        teams_bot_outbound = _teams_uses_bot_outbound(config) or (
            not _has_outbound_webhook(config, runtime_secrets)
            and _env_present(teams_app_id_env, runtime_secrets)
            and _env_present(teams_app_password_env, runtime_secrets)
        )
        teams_signature_env, teams_signature_configured, teams_signature_config_key = _provider_signature_secret_env(
            config,
            "teams",
            default_env=signature_env,
            default_configured=signature_configured,
        )
        auth_configured = (
            _env_present(teams_signature_env, runtime_secrets)
            if teams_signature_configured
            else _env_present(provider_token_env, runtime_secrets) or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
        )
        auth_envs = [
            _env_status(teams_app_id_env, "Teams Bot Framework app ID", required=True, secrets=runtime_secrets),
            _env_status(teams_app_password_env, "Teams Bot Framework app password", required=True, secrets=runtime_secrets),
            _env_status(provider_token_env, "Teams webhook token", secrets=runtime_secrets),
            _env_status(
                teams_signature_env,
                "Per-channel Teams HMAC secret",
                required=teams_signature_configured,
                secrets=runtime_secrets,
            ),
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        if teams_bot_outbound:
            outbound_ready = (
                _env_present(teams_app_id_env, runtime_secrets)
                and _env_present(teams_app_password_env, runtime_secrets)
            )
            setup.update({
                "outboundReady": outbound_ready,
                "outboundTransport": "bot",
                "outboundBotCredentialEnvVars": [teams_app_id_env, teams_app_password_env],
                "outboundWebhookConfigured": True,
            })
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "providerTokenEnv": provider_token_env,
            "signatureEnv": teams_signature_env,
            "signatureRequired": teams_signature_configured,
            "providerSignatureConfigKey": teams_signature_config_key,
        })
        setup["teamsBridgeConfig"] = _teams_bridge_config(channel, setup, ctx)
    elif channel_type == "discord":
        provider_path = f"/api/internal/support/discord/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_DISCORD_WEBHOOK_TOKEN"
        discord_bot_token_env = _discord_bot_token_env(config)
        discord_bot_outbound = _discord_uses_bot_outbound(config) or (
            not _has_outbound_webhook(config, runtime_secrets)
            and _env_present(discord_bot_token_env, runtime_secrets)
        )
        discord_signature_env, discord_signature_configured, discord_signature_config_key = _provider_signature_secret_env(
            config,
            "discord",
            default_env=signature_env,
            default_configured=signature_configured,
        )
        auth_configured = (
            _env_present(discord_signature_env, runtime_secrets)
            if discord_signature_configured
            else _env_present(provider_token_env, runtime_secrets) or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
        )
        auth_envs = [
            _env_status(discord_bot_token_env, "Discord bot token for Gateway and replies", required=True, secrets=runtime_secrets),
            _env_status(provider_token_env, "Discord webhook token", secrets=runtime_secrets),
            _env_status(
                discord_signature_env,
                "Per-channel Discord HMAC secret",
                required=discord_signature_configured,
                secrets=runtime_secrets,
            ),
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        if discord_bot_outbound:
            outbound_ready = _env_present(discord_bot_token_env, runtime_secrets)
            setup.update({
                "outboundReady": outbound_ready,
                "outboundTransport": "bot",
                "outboundBotTokenEnv": discord_bot_token_env,
                "outboundWebhookConfigured": True,
            })
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "providerTokenEnv": provider_token_env,
            "signatureEnv": discord_signature_env,
            "signatureRequired": discord_signature_configured,
            "providerSignatureConfigKey": discord_signature_config_key,
        })
        setup["discordBridgeConfig"] = _discord_bridge_config(channel, setup, ctx)
    elif channel_type == "telegram":
        provider_path = f"/api/internal/support/telegram/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_TELEGRAM_WEBHOOK_TOKEN"
        provider_secret_env = _telegram_secret_token_env(config)
        telegram_bot_token_env = _telegram_bot_token_env(config)
        telegram_bot_outbound = _telegram_uses_bot_outbound(config) or (
            not _has_outbound_webhook(config, runtime_secrets)
            and _env_present(telegram_bot_token_env, runtime_secrets)
        )
        provider_secret_header = "X-Telegram-Bot-Api-Secret-Token"
        telegram_signature_env, telegram_signature_configured, telegram_signature_config_key = _provider_signature_secret_env(
            config,
            "telegram",
            default_env=signature_env,
            default_configured=signature_configured,
        )
        auth_configured = (
            _env_present(telegram_signature_env, runtime_secrets)
            if telegram_signature_configured
            else _env_present(provider_secret_env, runtime_secrets)
            or _env_present(provider_token_env, runtime_secrets)
            or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
        )
        auth_envs = [
            _env_status(provider_secret_env, "Telegram native secret token", secrets=runtime_secrets),
            _env_status(provider_token_env, "Telegram webhook token", secrets=runtime_secrets),
            _env_status(
                telegram_signature_env,
                "Per-channel Telegram HMAC secret",
                required=telegram_signature_configured,
                secrets=runtime_secrets,
            ),
            _env_status(telegram_bot_token_env, "Telegram bot token", required=telegram_bot_outbound, secrets=runtime_secrets),
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        if telegram_bot_outbound:
            outbound_ready = _env_present(telegram_bot_token_env, runtime_secrets)
            setup.update({
                "outboundReady": outbound_ready,
                "outboundTransport": "bot",
                "outboundBotTokenEnv": telegram_bot_token_env,
                "outboundWebhookConfigured": True,
            })
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "providerTokenEnv": provider_token_env,
            "providerSecretHeader": provider_secret_header,
            "providerSecretEnv": provider_secret_env,
            "signatureEnv": telegram_signature_env,
            "signatureRequired": telegram_signature_configured,
            "providerSignatureConfigKey": telegram_signature_config_key,
        })
        telegram_config = _telegram_webhook_config(channel, setup, ctx)
        setup["telegramWebhookConfig"] = telegram_config
        setup["messagePayloadExample"] = telegram_config["payloadExample"]
    elif channel_type == "line":
        provider_path = f"/api/internal/support/line/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_LINE_WEBHOOK_TOKEN"
        line_signature_env, line_signature_configured, line_signature_config_key = _provider_signature_secret_env(
            config,
            "line",
            default_env=_line_channel_secret_env(config),
            default_configured=bool(
                config.get("lineChannelSecretEnv")
                or config.get("line_channel_secret_env")
                or config.get("channelSecretEnv")
                or config.get("channel_secret_env")
                or signature_configured
            ),
        )
        access_token_env = _line_channel_access_token_env(config)
        auth_configured = (
            _env_present(line_signature_env, runtime_secrets)
            if line_signature_configured
            else _env_present(provider_token_env, runtime_secrets)
            or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
        )
        auth_envs = [
            _env_status(
                line_signature_env,
                "LINE channel secret for X-Line-Signature",
                required=line_signature_configured,
                secrets=runtime_secrets,
            ),
            _env_status(provider_token_env, "LINE bridge webhook token", secrets=runtime_secrets),
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        outbound_envs = [
            _env_status(access_token_env, "LINE channel access token", required=True, secrets=runtime_secrets),
        ]
        outbound_ready = _env_present(access_token_env, runtime_secrets)
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "providerTokenEnv": provider_token_env,
            "signatureEnv": line_signature_env,
            "signatureHeader": "X-Line-Signature",
            "signatureRequired": line_signature_configured,
            "providerSignatureConfigKey": line_signature_config_key,
            "outboundReady": outbound_ready,
            "outboundTransport": "provider_api",
            "outboundWebhookConfigured": True,
            "outboundProviderCredentialEnvVars": [access_token_env],
            "outboundConfigKeys": [
                *setup.get("outboundConfigKeys", []),
                "lineChannelAccessTokenEnv",
                "lineChannelSecretEnv",
            ],
        })
        line_config = _line_webhook_config(channel, setup, ctx)
        setup["lineWebhookConfig"] = line_config
        setup["messagePayloadExample"] = line_config["payloadExample"]
    elif channel_type == "viber":
        provider_path = f"/api/internal/support/viber/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_VIBER_WEBHOOK_TOKEN"
        viber_auth_env, _viber_signature_configured, viber_signature_config_key = _provider_signature_secret_env(
            config,
            "viber",
            default_env=_viber_auth_token_env(config),
            default_configured=bool(
                config.get("viberAuthTokenEnv")
                or config.get("viber_auth_token_env")
                or config.get("authTokenEnv")
                or config.get("auth_token_env")
                or signature_configured
            ),
        )
        auth_configured = _env_present(viber_auth_env, runtime_secrets)
        auth_envs = [
            _env_status(
                viber_auth_env,
                "Viber auth token for X-Viber-Content-Signature",
                required=True,
                secrets=runtime_secrets,
            ),
            _env_status(provider_token_env, "Viber bridge webhook token", secrets=runtime_secrets),
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        outbound_envs = [
            _env_status(viber_auth_env, "Viber bot auth token", required=True, secrets=runtime_secrets),
        ]
        outbound_ready = _env_present(viber_auth_env, runtime_secrets)
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "providerTokenEnv": provider_token_env,
            "signatureEnv": viber_auth_env,
            "signatureHeader": "X-Viber-Content-Signature",
            "signatureRequired": True,
            "providerSignatureConfigKey": viber_signature_config_key,
            "signatureAuthMode": "hmac_signature",
            "outboundReady": outbound_ready,
            "outboundTransport": "provider_api",
            "outboundWebhookConfigured": True,
            "outboundWebhookTokenEnv": viber_auth_env,
            "outboundProviderCredentialEnvVars": [viber_auth_env],
            "outboundConfigKeys": [
                *setup.get("outboundConfigKeys", []),
                "viberAuthTokenEnv",
                "viberSenderName",
                "viberSenderAvatar",
            ],
        })
        viber_config = _viber_webhook_config(channel, setup, ctx)
        setup["viberWebhookConfig"] = viber_config
        setup["messagePayloadExample"] = viber_config["payloadExample"]
    elif channel_type == "whatsapp":
        provider_path = f"/api/internal/support/whatsapp/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_WHATSAPP_WEBHOOK_TOKEN"
        verify_token_env = str(
            config.get("whatsappVerifyTokenEnv")
            or config.get("whatsapp_verify_token_env")
            or config.get("verifyTokenEnv")
            or config.get("verify_token_env")
            or "SUPPORT_WHATSAPP_VERIFY_TOKEN"
        ).strip() or "SUPPORT_WHATSAPP_VERIFY_TOKEN"
        whatsapp_signature_env, whatsapp_signature_configured, whatsapp_signature_config_key = _provider_signature_secret_env(
            config,
            "whatsapp",
            default_env="SUPPORT_WHATSAPP_APP_SECRET",
            default_configured=bool(
                config.get("whatsappSigningSecretEnv")
                or config.get("whatsapp_signing_secret_env")
                or config.get("appSecretEnv")
                or config.get("app_secret_env")
                or signature_configured
            ),
        )
        auth_configured = (
            _env_present(verify_token_env, runtime_secrets)
            and (
                _env_present(whatsapp_signature_env, runtime_secrets)
                if whatsapp_signature_configured
                else _env_present(provider_token_env, runtime_secrets)
                or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
            )
        )
        auth_envs = [
            _env_status(verify_token_env, "WhatsApp webhook verification token", required=True, secrets=runtime_secrets),
            _env_status(
                whatsapp_signature_env,
                "WhatsApp app secret for X-Hub-Signature-256",
                required=whatsapp_signature_configured,
                secrets=runtime_secrets,
            ),
            _env_status(provider_token_env, "WhatsApp bridge webhook token", secrets=runtime_secrets),
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "providerTokenEnv": provider_token_env,
            "providerVerifyTokenEnv": verify_token_env,
            "signatureEnv": whatsapp_signature_env,
            "signatureHeader": "X-Hub-Signature-256",
            "signatureRequired": whatsapp_signature_configured,
            "providerSignatureConfigKey": whatsapp_signature_config_key,
        })
        whatsapp_config = _whatsapp_webhook_config(channel, setup, ctx)
        setup["whatsappWebhookConfig"] = whatsapp_config
        setup["metaBridgeConfig"] = _meta_bridge_config(channel, setup, ctx, provider="whatsapp")
        setup["messagePayloadExample"] = whatsapp_config["payloadExample"]
    elif channel_type in {"messenger", "facebook_messenger"}:
        provider_path = f"/api/internal/support/messenger/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_MESSENGER_WEBHOOK_TOKEN"
        verify_token_env = str(
            config.get("messengerVerifyTokenEnv")
            or config.get("messenger_verify_token_env")
            or config.get("verifyTokenEnv")
            or config.get("verify_token_env")
            or "SUPPORT_MESSENGER_VERIFY_TOKEN"
        ).strip() or "SUPPORT_MESSENGER_VERIFY_TOKEN"
        messenger_signature_env, messenger_signature_configured, messenger_signature_config_key = _provider_signature_secret_env(
            config,
            "messenger",
            default_env="SUPPORT_MESSENGER_APP_SECRET",
            default_configured=bool(
                config.get("messengerSigningSecretEnv")
                or config.get("messenger_signing_secret_env")
                or config.get("appSecretEnv")
                or config.get("app_secret_env")
                or signature_configured
            ),
        )
        page_token_env = _messenger_page_access_token_env(config)
        page_id, page_id_env = _messenger_page_id(config, runtime_secrets)
        auth_configured = (
            _env_present(verify_token_env, runtime_secrets)
            and (
                _env_present(messenger_signature_env, runtime_secrets)
                if messenger_signature_configured
                else _env_present(provider_token_env, runtime_secrets)
                or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
            )
        )
        auth_envs = [
            _env_status(verify_token_env, "Messenger webhook verification token", required=True, secrets=runtime_secrets),
            _env_status(
                messenger_signature_env,
                "Messenger app secret for X-Hub-Signature-256",
                required=messenger_signature_configured,
                secrets=runtime_secrets,
            ),
            _env_status(provider_token_env, "Messenger bridge webhook token", secrets=runtime_secrets),
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        outbound_envs = [
            _env_status(page_id_env or "SUPPORT_MESSENGER_PAGE_ID", "Facebook Page ID", required=True, secrets=runtime_secrets),
            _env_status(page_token_env, "Messenger Page Access Token", required=True, secrets=runtime_secrets),
        ]
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "providerTokenEnv": provider_token_env,
            "providerVerifyTokenEnv": verify_token_env,
            "signatureEnv": messenger_signature_env,
            "signatureHeader": "X-Hub-Signature-256",
            "signatureRequired": messenger_signature_configured,
            "providerSignatureConfigKey": messenger_signature_config_key,
            "outboundReady": bool(page_id and _env_present(page_token_env, runtime_secrets)),
            "outboundTransport": "provider_api",
            "outboundWebhookConfigured": True,
            "outboundProviderCredentialEnvVars": [page_id_env or "SUPPORT_MESSENGER_PAGE_ID", page_token_env],
            "outboundConfigKeys": [
                *setup.get("outboundConfigKeys", []),
                "pageIdEnv",
                "pageAccessTokenEnv",
            ],
        })
        messenger_config = _messenger_webhook_config(channel, setup, ctx)
        setup["messengerWebhookConfig"] = messenger_config
        setup["metaBridgeConfig"] = _meta_bridge_config(channel, setup, ctx, provider="messenger")
        setup["messagePayloadExample"] = messenger_config["payloadExample"]
    elif channel_type == "instagram":
        provider_path = f"/api/internal/support/instagram/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_INSTAGRAM_WEBHOOK_TOKEN"
        verify_token_env = str(
            config.get("instagramVerifyTokenEnv")
            or config.get("instagram_verify_token_env")
            or config.get("verifyTokenEnv")
            or config.get("verify_token_env")
            or "SUPPORT_INSTAGRAM_VERIFY_TOKEN"
        ).strip() or "SUPPORT_INSTAGRAM_VERIFY_TOKEN"
        instagram_signature_env, instagram_signature_configured, instagram_signature_config_key = _provider_signature_secret_env(
            config,
            "instagram",
            default_env="SUPPORT_INSTAGRAM_APP_SECRET",
            default_configured=bool(
                config.get("instagramSigningSecretEnv")
                or config.get("instagram_signing_secret_env")
                or config.get("appSecretEnv")
                or config.get("app_secret_env")
                or signature_configured
            ),
        )
        account_id, account_id_env = _instagram_account_id(config, runtime_secrets)
        access_token_env = _instagram_access_token_env(config)
        auth_configured = (
            _env_present(verify_token_env, runtime_secrets)
            and (
                _env_present(instagram_signature_env, runtime_secrets)
                if instagram_signature_configured
                else _env_present(provider_token_env, runtime_secrets)
                or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
            )
        )
        auth_envs = [
            _env_status(verify_token_env, "Instagram webhook verification token", required=True, secrets=runtime_secrets),
            _env_status(
                instagram_signature_env,
                "Instagram app secret for X-Hub-Signature-256",
                required=instagram_signature_configured,
                secrets=runtime_secrets,
            ),
            _env_status(provider_token_env, "Instagram bridge webhook token", secrets=runtime_secrets),
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        outbound_envs = [
            _env_status(
                account_id_env or "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID",
                "Instagram business account ID",
                required=True,
                secrets=runtime_secrets,
            ),
            _env_status(access_token_env, "Instagram access token for provider validation and replies", required=True, secrets=runtime_secrets),
        ]
        native_outbound_ready = bool(account_id and _env_present(access_token_env, runtime_secrets))
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "providerTokenEnv": provider_token_env,
            "providerVerifyTokenEnv": verify_token_env,
            "signatureEnv": instagram_signature_env,
            "signatureHeader": "X-Hub-Signature-256",
            "signatureRequired": instagram_signature_configured,
            "providerSignatureConfigKey": instagram_signature_config_key,
            "outboundReady": native_outbound_ready,
            "outboundTransport": "provider_api",
            "outboundWebhookConfigured": True,
            "outboundWebhookTokenEnv": access_token_env,
            "outboundProviderCredentialEnvVars": [
                account_id_env or "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID",
                access_token_env,
            ],
            "outboundConfigKeys": [
                *setup.get("outboundConfigKeys", []),
                "instagramAccountIdEnv",
                "instagramAccessTokenEnv",
            ],
        })
        instagram_config = _instagram_webhook_config(channel, setup, ctx)
        setup["instagramWebhookConfig"] = instagram_config
        setup["metaBridgeConfig"] = _meta_bridge_config(channel, setup, ctx, provider="instagram")
        setup["messagePayloadExample"] = instagram_config["payloadExample"]
    elif channel_type in {"twitter", "x"}:
        provider_path = f"/api/internal/support/twitter/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_X_WEBHOOK_TOKEN"
        twitter_signature_env, twitter_signature_configured, twitter_signature_config_key = _provider_signature_secret_env(
            config,
            "twitter",
            default_env=_twitter_consumer_secret_env(config),
            default_configured=bool(
                config.get("twitterConsumerSecretEnv")
                or config.get("twitter_consumer_secret_env")
                or config.get("xConsumerSecretEnv")
                or config.get("x_consumer_secret_env")
                or config.get("consumerSecretEnv")
                or config.get("consumer_secret_env")
                or signature_configured
            ),
        )
        bearer_token_env = _twitter_bearer_token_env(config)
        user_access_token_env = _twitter_user_access_token_env(config)
        user_id, user_id_env = _twitter_user_id(config, runtime_secrets)
        auth_configured = (
            _env_present(twitter_signature_env, runtime_secrets)
            if twitter_signature_configured
            else _env_present(provider_token_env, runtime_secrets)
            or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
        )
        auth_envs = [
            _env_status(
                twitter_signature_env,
                "X API consumer secret for CRC and x-twitter-webhooks-signature",
                required=twitter_signature_configured,
                secrets=runtime_secrets,
            ),
            _env_status(provider_token_env, "X bridge webhook token", secrets=runtime_secrets),
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        outbound_envs = [
            _env_status(bearer_token_env, "X API bearer token for provider validation", required=True, secrets=runtime_secrets),
            _env_status(user_access_token_env, "X user access token for DM sends", required=True, secrets=runtime_secrets),
            _env_status(user_id_env or "SUPPORT_X_USER_ID", "Subscribed X user ID", required=True, secrets=runtime_secrets),
        ]
        native_outbound_ready = bool(_env_present(user_access_token_env, runtime_secrets))
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "providerTokenEnv": provider_token_env,
            "signatureEnv": twitter_signature_env,
            "signatureHeader": "x-twitter-webhooks-signature",
            "signatureRequired": twitter_signature_configured,
            "providerSignatureConfigKey": twitter_signature_config_key,
            "outboundReady": native_outbound_ready,
            "outboundTransport": "provider_api",
            "outboundWebhookConfigured": True,
            "outboundWebhookTokenEnv": user_access_token_env,
            "outboundProviderCredentialEnvVars": [
                user_access_token_env,
                bearer_token_env,
                user_id_env or "SUPPORT_X_USER_ID",
            ],
            "outboundConfigKeys": [
                *setup.get("outboundConfigKeys", []),
                "twitterBearerTokenEnv",
                "twitterUserAccessTokenEnv",
                "twitterUserIdEnv",
            ],
        })
        twitter_config = _twitter_webhook_config(channel, setup, ctx)
        setup["twitterWebhookConfig"] = twitter_config
        setup["twitterBridgeConfig"] = _twitter_bridge_config(channel, setup, ctx)
        setup["messagePayloadExample"] = twitter_config["payloadExample"]
    elif channel_type == "sms":
        sms_path = f"/api/internal/support/sms/{encoded_key}"
        provider_path = f"/api/internal/support/twilio/{encoded_key}"
        provider_token_env = inbound_webhook_token_env if inbound_webhook_token_env != "SUPPORT_CHANNEL_WEBHOOK_TOKEN" else "SUPPORT_TWILIO_WEBHOOK_TOKEN"
        sms_signature_env, sms_signature_configured, sms_signature_config_key = _provider_signature_secret_env(
            config,
            "sms",
            default_env=signature_env,
            default_configured=signature_configured,
        )
        account_sid_env = _twilio_account_sid_env(config)
        auth_token_env = _twilio_auth_token_env(config)
        from_number, from_number_env, messaging_service_sid, messaging_service_sid_env = _twilio_sender(config, runtime_secrets)
        account_sid = _secret_value(account_sid_env, runtime_secrets)
        auth_token = _secret_value(auth_token_env, runtime_secrets)
        twilio_native_signature_ready = bool(auth_token)
        auth_configured = (
            _env_present(sms_signature_env, runtime_secrets)
            if sms_signature_configured
            else (
                twilio_native_signature_ready
                or _env_present(provider_token_env, runtime_secrets)
                or _env_present("SUPPORT_SYNC_TOKEN", runtime_secrets)
            )
        )
        auth_envs = [
            _env_status(auth_token_env, "Twilio Auth Token for native webhook signatures", secrets=runtime_secrets),
            _env_status(provider_token_env, "Twilio inbound webhook token", secrets=runtime_secrets),
            _env_status(
                sms_signature_env,
                "Per-channel SMS HMAC secret",
                required=sms_signature_configured,
                secrets=runtime_secrets,
            ),
            _env_status("SUPPORT_SYNC_TOKEN", "Fallback support automation token", secrets=runtime_secrets),
        ]
        outbound_envs = [
            _env_status(account_sid_env, "Twilio Account SID", required=True, secrets=runtime_secrets),
            _env_status(auth_token_env, "Twilio Auth Token", required=True, secrets=runtime_secrets),
            _env_status(from_number_env, "Twilio sender phone number", required=not messaging_service_sid, secrets=runtime_secrets),
        ]
        if messaging_service_sid_env:
            outbound_envs.append(
                _env_status(
                    messaging_service_sid_env,
                    "Twilio Messaging Service SID",
                    required=not from_number,
                    secrets=runtime_secrets,
                )
            )
        outbound_ready = bool(account_sid and auth_token and (from_number or messaging_service_sid))
        sms_webhook_url = _url(request, sms_path, query)
        setup.update({
            "providerWebhookUrl": _url(request, provider_path, query),
            "providerWebhookPath": provider_path,
            "smsWebhookUrl": sms_webhook_url,
            "smsWebhookPath": sms_path,
            "providerTokenEnv": provider_token_env,
            "signatureEnv": sms_signature_env,
            "signatureRequired": sms_signature_configured,
            "providerSignatureConfigKey": sms_signature_config_key,
            "twilioSignatureHeader": "X-Twilio-Signature",
            "twilioSignatureAuthTokenEnv": auth_token_env,
            "twilioNativeSignatureReady": twilio_native_signature_ready,
            "outboundReady": outbound_ready,
            "outboundTransport": "provider_api",
            "outboundWebhookConfigured": True,
            "outboundProviderCredentialEnvVars": [
                account_sid_env,
                auth_token_env,
                from_number_env,
                *([messaging_service_sid_env] if messaging_service_sid_env else []),
            ],
            "outboundConfigKeys": [
                *setup.get("outboundConfigKeys", []),
                "accountSidEnv",
                "authTokenEnv",
                "fromNumberEnv",
                "messagingServiceSidEnv",
                "twilioStatusCallbackUrl",
            ],
        })
        twilio_config = _twilio_webhook_config(channel, setup, ctx)
        setup["twilioWebhookConfig"] = twilio_config
        setup["messagePayloadExample"] = twilio_config["payloadExample"]
    if channel_type in {"chat", "web_chat"}:
        web_chat_query = urlencode({"channel_key": channel_key})
        web_chat_url = _url(
            request,
            f"/support/web-chat/{quote(ctx.project_id, safe='')}",
            web_chat_query,
        )
        embed_script_url = _url(
            request,
            f"/support/web-chat/{quote(ctx.project_id, safe='')}/embed.js",
            web_chat_query,
        )
        setup["webChatUrl"] = web_chat_url
        setup["webChatEmbedScriptUrl"] = embed_script_url
        setup["webChatEmbedSnippet"] = f'<script async src="{embed_script_url}"></script>'
        auth_configured = True
        auth_envs = []
        outbound_ready = True
        setup["outboundReady"] = True
        setup["outboundTransport"] = "internal"
    setup["authConfigured"] = auth_configured
    setup["inboundReady"] = bool(channel_key and channel.get("status") == "active" and auth_configured)
    template_envs = [
        _env_status(name, "Outbound URL template secret", required=True, secrets=runtime_secrets)
        for name in _template_secret_names(outbound_webhook_url_template)
    ]
    setup["envVars"] = [
        env
        for env in [
            *auth_envs,
            *outbound_envs,
            _env_status(outbound_webhook_url_env, "Outbound webhook URL", secrets=runtime_secrets) if outbound_webhook_url_env else None,
            *template_envs,
            _env_status(outbound_webhook_token_env, "Outbound webhook token", required=outbound_token_required, secrets=runtime_secrets) if outbound_webhook_token_env else None,
        ]
        if env and env["name"]
    ]
    final_outbound_ready = bool(setup.get("outboundReady"))
    final_outbound_configured = bool(setup.get("outboundWebhookConfigured") or setup.get("outboundTransport"))
    setup["providerSteps"] = _provider_steps(channel_type, config)
    setup["setupChecklist"] = [
        _setup_step(
            "status",
            "Channel active",
            "done" if channel.get("status") == "active" else "missing",
            str(channel.get("status") or "inactive"),
        ),
        _setup_step(
            "inbound_url",
            "Inbound URL ready",
            "done" if setup.get("providerWebhookUrl") or setup.get("inboundWebhookUrl") or setup.get("webChatUrl") else "missing",
            str(setup.get("providerWebhookUrl") or setup.get("inboundWebhookUrl") or setup.get("webChatUrl") or ""),
        ),
        _setup_step(
            "auth",
            "Webhook auth configured",
            "done" if auth_configured else "missing",
            "Env present" if auth_configured else "Set provider token, signing secret, or fallback sync token",
        ),
        _setup_step(
            "outbound",
            "Outbound replies",
            "done" if final_outbound_ready else ("warning" if final_outbound_configured else "missing"),
            "Ready" if final_outbound_ready else (
                "Outbound token env missing"
                if outbound_url_ready and outbound_token_required
                else "Env missing" if final_outbound_configured else "Configure outbound webhook for app replies"
            ),
        ),
        _setup_step(
            "test",
            "Test message",
            "manual",
            "Use Send test, then open the created ticket",
        ),
    ]
    setup["health"] = _setup_health_summary(setup)
    launch = (
        _channel_launch_status_from_proof((launch_proof_items or {}).get(str(channel.get("id") or "")))
        or _channel_launch_status(channel, sync_runs or [], runtime_secrets)
    )
    launch = _launch_with_inbound_ticket_event(launch, channel, webhook_events)
    setup["launch"] = launch
    setup["launchChecklist"] = launch["checklist"]
    setup["launchPlaybook"] = _channel_launch_playbook(channel, setup, ctx.project_id)
    setup["installPackage"] = _channel_install_package(channel, ctx, setup)
    return setup


def _with_channel_setup(
    channel: dict[str, Any],
    ctx: ProjectViewerDep,
    request: Request,
    sync_runs: list[dict[str, Any]] | None = None,
    launch_proof_items: dict[str, dict[str, Any]] | None = None,
    webhook_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        **channel,
        "setup": _channel_setup(
            channel,
            ctx,
            request,
            sync_runs=sync_runs,
            launch_proof_items=launch_proof_items,
            webhook_events=webhook_events,
        ),
    }


def _safe_channel_sync_runs(ctx: ProjectViewerDep, *, channel_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
    try:
        return list_channel_sync_runs(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            channel_id=channel_id,
            limit=limit,
        )
    except Exception:
        return []


def _safe_channel_webhook_events(ctx: ProjectViewerDep, *, channel_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
    try:
        return list_channel_webhook_events(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            channel_id=channel_id,
            limit=limit,
        )
    except Exception:
        return []


def _safe_support_launch_items(ctx: ProjectViewerDep) -> dict[str, dict[str, Any]]:
    try:
        proof = support_launch_proof(tenant_id=ctx.tenant_id, project_id=ctx.project_id)
    except Exception:
        return {}
    channels = proof.get("channels") if isinstance(proof.get("channels"), dict) else {}
    items = channels.get("items") if isinstance(channels.get("items"), list) else []
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        channel_id = str(item.get("channelId") or "")
        if channel_id:
            result[channel_id] = item
    return result


def _surface_channel_type(channel_type: str) -> str:
    clean = str(channel_type or "").strip().lower()
    if clean == "web_chat":
        return "chat"
    if clean == "facebook_messenger":
        return "messenger"
    return clean


def _first_config_text(config: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _config_text(config, key)
        if value:
            return value
    return ""


def _activation_target_row(
    config: dict[str, Any],
    *,
    key: str,
    label: str,
    config_key: str,
    value_keys: tuple[str, ...],
    required: bool = True,
) -> dict[str, Any]:
    value = _first_config_text(config, *value_keys)
    return {
        "key": key,
        "label": label,
        "configKey": config_key,
        "required": required,
        "configured": _live_smoke_target_value(value),
        "value": value,
    }


def _activation_live_target_rows(channel: dict[str, Any]) -> list[dict[str, Any]]:
    channel_type = _surface_channel_type(str(channel.get("type") or ""))
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    if channel_type == "slack":
        return [
            _activation_target_row(
                config,
                key="smokeChannelId",
                label="Slack channel ID",
                config_key="smokeChannelId",
                value_keys=("smokeChannelId", "smoke_channel_id", "channelId", "channel_id"),
            ),
            _activation_target_row(
                config,
                key="smokeThreadTs",
                label="Slack thread TS",
                config_key="smokeThreadTs",
                value_keys=("smokeThreadTs", "smoke_thread_ts", "threadTs", "thread_ts", "smokeThreadId", "smoke_thread_id", "threadId", "thread_id"),
                required=False,
            ),
        ]
    if channel_type == "teams":
        return [
            _activation_target_row(
                config,
                key="smokeServiceUrl",
                label="Teams service URL",
                config_key="smokeServiceUrl",
                value_keys=("smokeServiceUrl", "smoke_service_url", "serviceUrl", "service_url"),
            ),
            _activation_target_row(
                config,
                key="smokeConversationId",
                label="Teams conversation target",
                config_key="smokeConversationId",
                value_keys=("smokeConversationId", "smoke_conversation_id", "conversationId", "conversation_id", "smokeThreadId", "smoke_thread_id", "smokeChannelId", "smoke_channel_id", "channelId", "channel_id"),
            ),
            _activation_target_row(
                config,
                key="smokeReplyToId",
                label="Teams reply activity",
                config_key="smokeReplyToId",
                value_keys=("smokeReplyToId", "smoke_reply_to_id", "replyToId", "reply_to_id"),
                required=False,
            ),
        ]
    if channel_type == "discord":
        value = _first_config_text(config, "smokeChannelId", "smoke_channel_id", "channelId", "channel_id", "smokeThreadId", "smoke_thread_id", "threadId", "thread_id")
        return [{
            "key": "discordTarget",
            "label": "Discord channel or thread",
            "configKey": "smokeChannelId or smokeThreadId",
            "required": True,
            "configured": _live_smoke_target_value(value),
            "value": value,
        }]
    if channel_type == "telegram":
        return [_activation_target_row(
            config,
            key="smokeChatId",
            label="Telegram chat ID",
            config_key="smokeChatId",
            value_keys=("smokeChatId", "smoke_chat_id", "chatId", "chat_id", "smokeChannelId", "smoke_channel_id", "channelId", "channel_id", "smokeToAddress", "smoke_to_address"),
        )]
    if channel_type == "line":
        return [_activation_target_row(
            config,
            key="smokeToAddress",
            label="LINE user/group/room ID",
            config_key="smokeToAddress",
            value_keys=("smokeToAddress", "smoke_to_address", "smokeConversationId", "smoke_conversation_id", "lineUserId", "line_user_id", "userId", "user_id", "groupId", "group_id", "roomId", "room_id", "chatId", "chat_id"),
        )]
    if channel_type == "viber":
        return [_activation_target_row(
            config,
            key="smokeToAddress",
            label="Viber subscriber ID",
            config_key="smokeToAddress",
            value_keys=("smokeToAddress", "smoke_to_address", "smokeConversationId", "smoke_conversation_id", "viberUserId", "viber_user_id", "userId", "user_id", "senderId", "sender_id", "chatId", "chat_id"),
        )]
    if channel_type == "whatsapp":
        return [_activation_target_row(
            config,
            key="smokeToAddress",
            label="WhatsApp recipient",
            config_key="smokeToAddress",
            value_keys=("smokeToAddress", "smoke_to_address", "smokeConversationId", "smoke_conversation_id", "waId", "wa_id", "senderId", "sender_id", "chatId", "chat_id"),
        )]
    if channel_type == "messenger":
        return [_activation_target_row(
            config,
            key="smokeToAddress",
            label="Messenger PSID",
            config_key="smokeToAddress",
            value_keys=("smokeToAddress", "smoke_to_address", "smokeConversationId", "smoke_conversation_id", "senderId", "sender_id", "psid", "chatId", "chat_id"),
        )]
    if channel_type == "instagram":
        return [_activation_target_row(
            config,
            key="smokeToAddress",
            label="Instagram scoped user ID",
            config_key="smokeToAddress",
            value_keys=("smokeToAddress", "smoke_to_address", "smokeConversationId", "smoke_conversation_id", "senderId", "sender_id", "igid", "chatId", "chat_id"),
        )]
    if channel_type in {"twitter", "x"}:
        return [_activation_target_row(
            config,
            key="smokeToAddress",
            label="X user ID",
            config_key="smokeToAddress",
            value_keys=("smokeToAddress", "smoke_to_address", "smokeConversationId", "smoke_conversation_id", "senderId", "sender_id", "twitterUserId", "twitter_user_id", "xUserId", "x_user_id", "chatId", "chat_id"),
        )]
    if channel_type in {"sms", "twilio"}:
        return [_activation_target_row(
            config,
            key="smokeToAddress",
            label="SMS recipient",
            config_key="smokeToAddress",
            value_keys=("smokeToAddress", "smoke_to_address", "smokeConversationId", "smoke_conversation_id", "smokeChannelId", "smoke_channel_id"),
        )]
    return []


def _activation_env_vars(channel: dict[str, Any] | None, preset: dict[str, Any]) -> list[dict[str, Any]]:
    setup = channel.get("setup") if isinstance(channel, dict) and isinstance(channel.get("setup"), dict) else {}
    env_vars = setup.get("envVars") if isinstance(setup.get("envVars"), list) else []
    if env_vars:
        return [
            {
                "name": str(item.get("name") or ""),
                "purpose": str(item.get("purpose") or ""),
                "required": bool(item.get("required")),
                "configured": bool(item.get("configured")),
            }
            for item in env_vars
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
    preset_envs = []
    for key in ("authEnvVars", "outboundEnvVars"):
        values = preset.get(key) if isinstance(preset.get(key), list) else []
        preset_envs.extend(item for item in values if isinstance(item, dict))
    return [
        {
            "name": str(item.get("name") or ""),
            "purpose": str(item.get("purpose") or ""),
            "required": bool(item.get("required")),
            "configured": False,
        }
        for item in preset_envs
        if str(item.get("name") or "").strip()
    ]


def _activation_setup_package(setup: dict[str, Any]) -> dict[str, Any] | None:
    if not setup:
        return None
    return {
        "installPackage": setup.get("installPackage"),
        "slackManifest": setup.get("slackManifest"),
        "teamsBridgeConfig": setup.get("teamsBridgeConfig"),
        "discordBridgeConfig": setup.get("discordBridgeConfig"),
        "metaBridgeConfig": setup.get("metaBridgeConfig"),
        "telegramWebhookConfig": setup.get("telegramWebhookConfig"),
        "lineWebhookConfig": setup.get("lineWebhookConfig"),
        "viberWebhookConfig": setup.get("viberWebhookConfig"),
        "whatsappWebhookConfig": setup.get("whatsappWebhookConfig"),
        "messengerWebhookConfig": setup.get("messengerWebhookConfig"),
        "instagramWebhookConfig": setup.get("instagramWebhookConfig"),
        "twitterWebhookConfig": setup.get("twitterWebhookConfig"),
        "twitterBridgeConfig": setup.get("twitterBridgeConfig"),
        "twilioWebhookConfig": setup.get("twilioWebhookConfig"),
    }


def _activation_provider_steps(surface_type: str, config: dict[str, Any], setup: dict[str, Any]) -> list[str]:
    setup_steps = setup.get("providerSteps") if isinstance(setup.get("providerSteps"), list) else []
    steps = [str(item).strip() for item in setup_steps if str(item).strip()]
    return steps or _provider_steps(surface_type, config)


def _activation_setup_package_keys(setup_package: dict[str, Any] | None) -> list[str]:
    if not setup_package:
        return []
    return [key for key, value in setup_package.items() if value]


def _activation_proof_actions(launch_checklist: list[Any], launch_commands: list[dict[str, str]]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in launch_checklist:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("action") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        actions.append({
            "key": key,
            "label": str(item.get("label") or key).strip(),
            "status": str(item.get("status") or "").strip(),
            "detail": str(item.get("detail") or "").strip(),
            "action": str(item.get("action") or key).strip(),
            "runId": str(item.get("runId") or "").strip(),
        })
    for command in launch_commands:
        key = str(command.get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        actions.append({
            "key": key,
            "label": str(command.get("label") or key).strip(),
            "status": "",
            "detail": "",
            "action": key,
            "runId": "",
        })
    return actions


def _activation_runbook_phase(
    *,
    channel: dict[str, Any] | None,
    required_missing_env_vars: list[str],
    missing_live_targets: list[str],
    config_blockers: list[str],
    launch_required: bool,
    launch_ready: bool,
) -> str:
    if not channel:
        return "create"
    if required_missing_env_vars:
        return "secrets"
    if missing_live_targets:
        return "targets"
    if config_blockers:
        return "config"
    if str(channel.get("status") or "") != "active":
        return "activate"
    if launch_required and not launch_ready:
        return "proof"
    return "ready"


def _activation_surface_item(surface_type: str, label: str, channel: dict[str, Any] | None) -> dict[str, Any]:
    preset = _channel_preset("web_chat" if surface_type == "chat" else surface_type)
    setup = channel.get("setup") if isinstance(channel, dict) and isinstance(channel.get("setup"), dict) else {}
    config = channel.get("config") if isinstance(channel, dict) and isinstance(channel.get("config"), dict) else {}
    health = setup.get("health") if isinstance(setup.get("health"), dict) else {}
    ticket_mode = str(setup.get("ticketCreationMode") or config.get("ticketCreationMode") or config.get("ticket_creation_mode") or preset.get("ticketCreationMode") or "per_message")
    inbound_ready = bool(health.get("inboundReady")) if "inboundReady" in health else bool(setup.get("inboundReady"))
    outbound_ready = bool(health.get("outboundReady")) if "outboundReady" in health else bool(setup.get("outboundReady"))
    auto_prepare_triage = bool(setup.get("autoPrepareTriage")) if "autoPrepareTriage" in setup else _config_bool(config, "autoPrepareTriage", "auto_prepare_triage", default=True)
    auto_prepare_custom_fields = bool(setup.get("autoPrepareCustomFields")) if "autoPrepareCustomFields" in setup else _config_bool(config, "autoPrepareCustomFields", "auto_prepare_custom_fields", default=True)
    auto_draft = bool(setup.get("autoPrepareAgentReply")) if "autoPrepareAgentReply" in setup else _config_bool(config, "autoPrepareAgentReply", "auto_prepare_agent_reply")
    auto_follow_up = bool(setup.get("autoPrepareAgentReplyOnUpdate")) if "autoPrepareAgentReplyOnUpdate" in setup else _config_bool(config, "autoPrepareAgentReplyOnUpdate", "auto_prepare_agent_reply_on_update")
    agent_auto_send = bool(setup.get("agentAutoSend")) if "agentAutoSend" in setup else _config_bool(config, "agentAutoSend", "agent_auto_send")
    human_review = not agent_auto_send
    owner_routing = bool(_config_text(config, "defaultAssigneeEmail", "default_assignee_email") or _config_text(config, "defaultQueueKey", "default_queue_key") or preset.get("defaultQueueKey"))
    launch = setup.get("launch") if isinstance(setup.get("launch"), dict) else {}
    launch_required = bool(launch.get("required")) if "required" in launch else (bool(channel) and _channel_requires_launch_smoke(surface_type))
    launch_ready = (not launch_required) or bool(launch.get("ready"))
    channel_status = str(channel.get("status") or "") if isinstance(channel, dict) else ""
    live_targets = _activation_live_target_rows(channel) if channel else []
    missing_live_targets = [row["configKey"] for row in live_targets if row.get("required") and not row.get("configured")]
    automation_ready = auto_prepare_triage and auto_prepare_custom_fields and auto_draft and auto_follow_up and human_review
    ready = bool(channel and channel_status == "active" and inbound_ready and outbound_ready and automation_ready and ticket_mode == "per_message" and owner_routing and launch_ready)
    launch_blockers = launch.get("blockers") if isinstance(launch.get("blockers"), list) else []
    launch_blocker_detail = next(
        (str(item.get("detail") or item.get("label") or "") for item in launch_blockers if isinstance(item, dict) and (item.get("detail") or item.get("label"))),
        "",
    )
    blockers = [
        "Missing" if not channel else "",
        "Paused" if channel and channel_status != "active" else "",
        "No inbound" if channel and not inbound_ready else "",
        "No outbound" if channel and not outbound_ready else "",
        "Manual triage" if channel and not auto_prepare_triage else "",
        "Manual fields" if channel and not auto_prepare_custom_fields else "",
        "Manual prep" if channel and not auto_draft else "",
        "Manual follow-up" if channel and not auto_follow_up else "",
        "No approval gate" if channel and not human_review else "",
        "Thread updates" if channel and ticket_mode != "per_message" else "",
        "No owner routing" if channel and not owner_routing else "",
        (launch_blocker_detail or "No launch smoke") if channel and not launch_ready else "",
    ]
    env_vars = _activation_env_vars(channel, preset)
    missing_env_vars = [item["name"] for item in env_vars if not item["configured"]]
    required_missing_env_vars = [item["name"] for item in env_vars if item["required"] and not item["configured"]]
    setup_checklist = setup.get("setupChecklist") if isinstance(setup.get("setupChecklist"), list) else []
    launch_checklist = setup.get("launchChecklist") if isinstance(setup.get("launchChecklist"), list) else launch.get("checklist") if isinstance(launch.get("checklist"), list) else []
    playbook = setup.get("launchPlaybook") if isinstance(setup.get("launchPlaybook"), list) else []
    setup_package = _activation_setup_package(setup)
    all_blockers = [
        {"key": "channel_surface", "label": detail, "detail": detail, "status": "missing", "action": ""}
        for detail in blockers
        if detail
    ]
    all_blockers.extend(item for item in launch_blockers if isinstance(item, dict))
    all_blockers.extend(item for item in launch_checklist if isinstance(item, dict) and item.get("status") != "done")
    all_blockers.extend(item for item in setup_checklist if isinstance(item, dict) and item.get("status") != "done")
    launch_commands = [
        {"key": str(item.get("key") or ""), "label": str(item.get("label") or ""), "command": str(item.get("smokeCommand") or "")}
        for item in playbook
        if isinstance(item, dict) and str(item.get("smokeCommand") or "").strip()
    ]
    config_blockers = [
        blocker
        for blocker in blockers
        if blocker in {
            "Paused",
            "No inbound",
            "No outbound",
            "Manual triage",
            "Manual fields",
            "Manual prep",
            "Manual follow-up",
            "No approval gate",
            "Thread updates",
            "No owner routing",
        }
    ]
    provider_runbook = {
        "kind": "support_channel_provider_runbook",
        "surfaceType": surface_type,
        "surfaceLabel": label,
        "launchWave": "initial" if surface_type in INITIAL_PROVIDER_SURFACES else "later",
        "initialProvider": surface_type in INITIAL_PROVIDER_SURFACES,
        "channelId": str(channel.get("id") or "") if channel else "",
        "channelKey": str(channel.get("channelKey") or channel.get("channel_key") or "") if channel else "",
        "channelStatus": channel_status or ("configured" if channel else "missing"),
        "ready": ready,
        "phase": _activation_runbook_phase(
            channel=channel,
            required_missing_env_vars=required_missing_env_vars,
            missing_live_targets=missing_live_targets,
            config_blockers=config_blockers,
            launch_required=launch_required,
            launch_ready=launch_ready,
        ),
        "providerSteps": _activation_provider_steps(surface_type, config, setup),
        "secretEnvVars": env_vars,
        "requiredMissingEnvVars": required_missing_env_vars,
        "liveTargets": live_targets,
        "missingLiveTargets": missing_live_targets,
        "proofActions": _activation_proof_actions(launch_checklist, launch_commands),
        "commands": launch_commands,
        "setupPackageKeys": _activation_setup_package_keys(setup_package),
        "blockers": [item for item in blockers if item],
    }
    return {
        "surface": {
            "type": surface_type,
            "label": label,
            "ready": ready,
            "configured": bool(channel),
            "blockers": [item for item in blockers if item],
        },
        "channel": {
            "id": str(channel.get("id") or ""),
            "key": str(channel.get("channelKey") or channel.get("channel_key") or ""),
            "name": str(channel.get("name") or ""),
            "type": str(channel.get("type") or ""),
            "status": channel_status,
            "providerName": str(setup.get("providerName") or preset.get("providerName") or ""),
        } if channel else None,
        "ticketing": {
            "ticketCreationMode": ticket_mode,
            "everyMessage": ticket_mode == "per_message",
            "ownerRouting": owner_routing,
            "defaultAssigneeEmail": _config_text(config, "defaultAssigneeEmail", "default_assignee_email"),
            "defaultQueueKey": _config_text(config, "defaultQueueKey", "default_queue_key") or str(preset.get("defaultQueueKey") or ""),
            "defaultQueueName": _config_text(config, "defaultQueueName", "default_queue_name") or str(preset.get("defaultQueueName") or ""),
        },
        "automation": {
            "autoPrepareTriage": auto_prepare_triage,
            "autoPrepareCustomFields": auto_prepare_custom_fields,
            "autoPrepareAgentReply": auto_draft,
            "autoPrepareAgentReplyOnUpdate": auto_follow_up,
            "agentAutoSend": agent_auto_send,
            "humanReview": human_review,
        },
        "inbound": {
            "ready": inbound_ready,
            "webhookUrl": str(setup.get("inboundWebhookUrl") or ""),
            "providerWebhookUrl": str(setup.get("providerWebhookUrl") or ""),
            "smsWebhookUrl": str(setup.get("smsWebhookUrl") or ""),
            "webChatUrl": str(setup.get("webChatUrl") or ""),
            "webChatEmbedScriptUrl": str(setup.get("webChatEmbedScriptUrl") or ""),
        },
        "outbound": {
            "ready": outbound_ready,
            "transport": str(setup.get("outboundTransport") or config.get("outboundTransport") or config.get("outbound_transport") or ""),
            "payloadMode": str(config.get("outboundPayloadMode") or config.get("outbound_payload_mode") or preset.get("outboundPayloadMode") or ""),
            "webhookUrl": str(setup.get("outboundWebhookUrl") or ""),
            "webhookUrlEnv": str(setup.get("outboundWebhookUrlEnv") or preset.get("outboundWebhookUrlEnv") or ""),
            "webhookTokenEnv": str(setup.get("outboundWebhookTokenEnv") or preset.get("outboundWebhookTokenEnv") or ""),
            "botTokenEnv": str(setup.get("outboundBotTokenEnv") or ""),
        },
        "environment": {
            "configured": sum(1 for item in env_vars if item["configured"]),
            "total": len(env_vars),
            "missing": missing_env_vars,
            "requiredMissing": health.get("requiredMissingEnvVars") if isinstance(health.get("requiredMissingEnvVars"), list) and health.get("requiredMissingEnvVars") else required_missing_env_vars,
            "vars": env_vars,
        },
        "launch": {
            "required": launch_required,
            "ready": launch_ready,
            "summary": {
                "checks": int(launch.get("checks") or 0),
                "passed": int(launch.get("passed") or 0),
                "missing": int(launch.get("missing") or 0),
                "failed": int(launch.get("failed") or 0),
                "lastCheckedAt": str(launch.get("lastCheckedAt") or ""),
            } if launch else None,
            "liveTargets": live_targets,
            "missingLiveTargets": missing_live_targets,
            "checklist": launch_checklist,
            "blockers": all_blockers,
            "playbook": playbook,
            "commands": launch_commands,
        },
        "setupPackage": setup_package,
        "providerRunbook": provider_runbook,
    }


def _activation_next_action(item: dict[str, Any], index: int) -> dict[str, Any] | None:
    surface = item.get("surface") if isinstance(item.get("surface"), dict) else {}
    channel = item.get("channel") if isinstance(item.get("channel"), dict) else None
    label = str(surface.get("label") or surface.get("type") or "Channel")
    surface_type = str(surface.get("type") or "")
    base = {
        "surfaceType": surface_type,
        "surfaceLabel": label,
        "channelId": str((channel or {}).get("id") or ""),
        "channelKey": str((channel or {}).get("key") or ""),
    }
    if not channel:
        return {
            **base,
            "phase": "create",
            "priority": 10 + index,
            "title": f"Create {label} channel",
            "detail": f"Apply the {label} preset so incoming messages can become tickets.",
            "action": "create_channel",
            "envVars": [],
            "liveTargets": [],
        }

    env = item.get("environment") if isinstance(item.get("environment"), dict) else {}
    missing_env = list(dict.fromkeys(str(name) for name in env.get("requiredMissing", []) if name))
    if missing_env:
        shown = ", ".join(missing_env[:3])
        suffix = f" and {len(missing_env) - 3} more" if len(missing_env) > 3 else ""
        return {
            **base,
            "phase": "secrets",
            "priority": 20 + index,
            "title": f"Configure {label} secrets",
            "detail": f"Add required runtime secrets: {shown}{suffix}.",
            "action": "configure_secrets",
            "envVars": missing_env,
            "liveTargets": [],
        }

    launch = item.get("launch") if isinstance(item.get("launch"), dict) else {}
    missing_targets = [str(name) for name in launch.get("missingLiveTargets", []) if name]
    if missing_targets:
        return {
            **base,
            "phase": "targets",
            "priority": 30 + index,
            "title": f"Set {label} smoke target",
            "detail": f"Configure live proof target keys: {', '.join(missing_targets)}.",
            "action": "configure_smoke_target",
            "envVars": [],
            "liveTargets": missing_targets,
        }

    ticketing = item.get("ticketing") if isinstance(item.get("ticketing"), dict) else {}
    automation = item.get("automation") if isinstance(item.get("automation"), dict) else {}
    config_gaps = [
        "ticketCreationMode" if not ticketing.get("everyMessage") else "",
        "ownerRouting" if not ticketing.get("ownerRouting") else "",
        "autoPrepareTriage" if not automation.get("autoPrepareTriage") else "",
        "autoPrepareCustomFields" if not automation.get("autoPrepareCustomFields") else "",
        "autoPrepareAgentReply" if not automation.get("autoPrepareAgentReply") else "",
        "autoPrepareAgentReplyOnUpdate" if not automation.get("autoPrepareAgentReplyOnUpdate") else "",
        "approvalRequired" if not automation.get("humanReview") else "",
    ]
    config_gaps = [gap for gap in config_gaps if gap]
    if config_gaps:
        return {
            **base,
            "phase": "config",
            "priority": 40 + index,
            "title": f"Fix {label} ticket defaults",
            "detail": f"Set {', '.join(config_gaps)} before launch proof.",
            "action": "ticket_defaults",
            "envVars": [],
            "liveTargets": [],
        }

    if str(channel.get("status") or "") != "active":
        return {
            **base,
            "phase": "activate",
            "priority": 50 + index,
            "title": f"Activate {label} channel",
            "detail": "Set channel status to active after secrets, targets, and ticket defaults are ready.",
            "action": "activate_channel",
            "envVars": [],
            "liveTargets": [],
        }

    blockers = [blocker for blocker in launch.get("blockers", []) if isinstance(blocker, dict)]
    first_blocker = blockers[0] if blockers else {}
    run_action = str(first_blocker.get("action") or first_blocker.get("runAction") or "")
    commands = [command for command in launch.get("commands", []) if isinstance(command, dict)]
    first_command = commands[0] if commands else {}
    return {
        **base,
        "phase": "proof",
        "priority": 60 + index,
        "title": f"Run {label} launch proof",
        "detail": str(first_blocker.get("detail") or first_blocker.get("label") or "Run provider validation and lifecycle smoke."),
        "action": run_action or "launch_proof",
        "runAction": run_action,
        "command": str(first_command.get("command") or ""),
        "envVars": [],
        "liveTargets": [],
    }


def _channel_activation_backlog(
    *,
    project_id: str,
    channels: list[dict[str, Any]],
) -> dict[str, Any]:
    by_surface: dict[str, list[dict[str, Any]]] = {}
    for channel in channels:
        by_surface.setdefault(_surface_channel_type(str(channel.get("type") or "")), []).append(channel)
    items: list[dict[str, Any]] = []
    for surface_type, label in CHANNEL_SURFACE_TARGETS:
        candidates = by_surface.get(surface_type, [])
        channel = next((item for item in candidates if str(item.get("status") or "") == "active"), None)
        if channel is None and candidates:
            channel = candidates[0]
        items.append(_activation_surface_item(surface_type, label, channel))
    backlog = [item for item in items if not item["surface"]["ready"] or (item.get("channel") or {}).get("status") != "active"]
    next_actions = [
        action
        for index, item in enumerate(backlog)
        if (action := _activation_next_action(item, index)) is not None
    ]
    next_action_phases = {
        phase: sum(1 for action in next_actions if action["phase"] == phase)
        for phase in ("create", "secrets", "targets", "config", "activate", "proof")
    }
    payload = {
        "kind": "support_channel_activation_backlog",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "projectId": project_id,
        "summary": {
            "totalSurfaces": len(items),
            "configuredSurfaces": sum(1 for item in items if item["surface"]["configured"]),
            "activeSurfaces": sum(1 for item in items if (item.get("channel") or {}).get("status") == "active"),
            "readySurfaces": sum(1 for item in items if item["surface"]["ready"]),
            "backlogSurfaces": len(backlog),
            "missingSurfaces": sum(1 for item in items if not item["surface"]["configured"]),
            "requiredMissingEnvVars": sorted({name for item in backlog for name in item["environment"]["requiredMissing"]}),
            "missingLiveTargets": sorted({target for item in backlog for target in item["launch"]["missingLiveTargets"]}),
            "nextActionCount": len(next_actions),
            "nextActionPhases": next_action_phases,
        },
        "channels": backlog,
        "surfaces": items,
        "nextActions": sorted(next_actions, key=lambda action: int(action["priority"])),
    }
    adapter_matrix = _channel_activation_adapter_matrix(payload)
    payload["adapterMatrix"] = adapter_matrix
    payload["summary"]["adapterMatrixRows"] = len(adapter_matrix)
    payload["summary"]["adapterMatrixReady"] = sum(1 for row in adapter_matrix if row.get("ready"))
    payload["summary"]["adapterMatrixBlocked"] = sum(1 for row in adapter_matrix if not row.get("ready"))
    payload["summary"]["providerRunbookRows"] = len(items)
    payload["summary"]["providerRunbookReady"] = sum(1 for item in items if (item.get("providerRunbook") or {}).get("ready"))
    payload["summary"]["providerRunbookBlocked"] = sum(1 for item in items if not (item.get("providerRunbook") or {}).get("ready"))
    payload["summary"]["initialProviderRows"] = sum(1 for item in items if (item.get("providerRunbook") or {}).get("initialProvider"))
    payload["summary"]["initialProviderReady"] = sum(1 for item in items if (item.get("providerRunbook") or {}).get("initialProvider") and (item.get("providerRunbook") or {}).get("ready"))
    payload["summary"]["initialProviderBlocked"] = sum(1 for item in items if (item.get("providerRunbook") or {}).get("initialProvider") and not (item.get("providerRunbook") or {}).get("ready"))
    return payload


def _activation_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clean for item in value if (clean := str(item or "").strip())]


def _activation_first_text(*values: Any) -> str:
    for value in values:
        clean = str(value or "").strip()
        if clean:
            return clean
    return ""


def _channel_activation_adapter_matrix(backlog: dict[str, Any]) -> list[dict[str, Any]]:
    next_actions = [
        action
        for action in backlog.get("nextActions", [])
        if isinstance(action, dict)
    ]
    next_by_surface: dict[str, dict[str, Any]] = {}
    for action in next_actions:
        surface_type = str(action.get("surfaceType") or "")
        if surface_type and surface_type not in next_by_surface:
            next_by_surface[surface_type] = action

    rows: list[dict[str, Any]] = []
    for item in backlog.get("surfaces", []):
        if not isinstance(item, dict):
            continue
        surface = item.get("surface") if isinstance(item.get("surface"), dict) else {}
        channel = item.get("channel") if isinstance(item.get("channel"), dict) else {}
        ticketing = item.get("ticketing") if isinstance(item.get("ticketing"), dict) else {}
        automation = item.get("automation") if isinstance(item.get("automation"), dict) else {}
        inbound = item.get("inbound") if isinstance(item.get("inbound"), dict) else {}
        outbound = item.get("outbound") if isinstance(item.get("outbound"), dict) else {}
        environment = item.get("environment") if isinstance(item.get("environment"), dict) else {}
        launch = item.get("launch") if isinstance(item.get("launch"), dict) else {}
        surface_type = str(surface.get("type") or "")
        next_action = next_by_surface.get(surface_type, {})
        rows.append({
            "surfaceType": surface_type,
            "surfaceLabel": str(surface.get("label") or surface_type),
            "configured": bool(surface.get("configured")),
            "ready": bool(surface.get("ready")),
            "channelId": str(channel.get("id") or ""),
            "channelKey": str(channel.get("key") or ""),
            "channelStatus": str(channel.get("status") or ("configured" if channel else "missing")),
            "providerName": str(channel.get("providerName") or ""),
            "inbound": {
                "adapter": surface_type,
                "ready": bool(inbound.get("ready")),
                "path": _activation_first_text(
                    inbound.get("providerWebhookUrl"),
                    inbound.get("smsWebhookUrl"),
                    inbound.get("webChatUrl"),
                    inbound.get("webhookUrl"),
                    inbound.get("webChatEmbedScriptUrl"),
                ),
            },
            "outbound": {
                "adapter": _activation_first_text(
                    outbound.get("transport"),
                    outbound.get("payloadMode"),
                    surface_type,
                ),
                "ready": bool(outbound.get("ready")),
                "target": _activation_first_text(
                    outbound.get("webhookUrl"),
                    outbound.get("webhookUrlEnv"),
                    outbound.get("webhookTokenEnv"),
                    outbound.get("botTokenEnv"),
                ),
            },
            "ticketing": {
                "everyMessage": bool(ticketing.get("everyMessage")),
                "ownerRouting": bool(ticketing.get("ownerRouting")),
            },
            "automation": {
                "autoPrepareAgentReply": bool(automation.get("autoPrepareAgentReply")),
                "autoPrepareAgentReplyOnUpdate": bool(automation.get("autoPrepareAgentReplyOnUpdate")),
                "humanReview": bool(automation.get("humanReview")),
            },
            "requiredMissingEnvVars": _activation_text_list(environment.get("requiredMissing")),
            "missingLiveTargets": _activation_text_list(launch.get("missingLiveTargets")),
            "nextAction": {
                "phase": str(next_action.get("phase") or ""),
                "title": str(next_action.get("title") or ""),
                "detail": str(next_action.get("detail") or ""),
                "action": str(next_action.get("action") or ""),
            } if next_action else None,
        })
    return rows


def _channel_activation_secret_groups(surfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for item in surfaces:
        surface = item.get("surface") if isinstance(item.get("surface"), dict) else {}
        environment = item.get("environment") if isinstance(item.get("environment"), dict) else {}
        env_vars: list[str] = []
        seen: set[str] = set()
        for name in _activation_text_list(environment.get("requiredMissing")):
            if name in seen:
                continue
            seen.add(name)
            env_vars.append(name)
        if not env_vars:
            continue
        groups.append({
            "surfaceLabel": str(surface.get("label") or surface.get("type") or "Channel"),
            "surfaceType": str(surface.get("type") or ""),
            "envVars": env_vars,
        })
    return groups


def _channel_activation_secret_template(groups: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for group in groups:
        lines = [f"# {group.get('surfaceLabel') or 'Channel'}"]
        lines.extend(f"{name}=" for name in _activation_text_list(group.get("envVars")))
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _channel_activation_plan(*, project_id: str, backlog: dict[str, Any]) -> dict[str, Any]:
    next_actions = [
        action for action in backlog.get("nextActions", [])
        if isinstance(action, dict)
    ]
    backlog_surfaces = [
        item for item in backlog.get("surfaces", [])
        if isinstance(item, dict)
    ]
    secret_groups = _channel_activation_secret_groups(backlog_surfaces)
    secret_names = sorted({
        name
        for group in secret_groups
        for name in _activation_text_list(group.get("envVars"))
    })
    surfaces: list[dict[str, Any]] = []
    for item in backlog_surfaces:
        surface = item.get("surface") if isinstance(item.get("surface"), dict) else {}
        channel = item.get("channel") if isinstance(item.get("channel"), dict) else {}
        ticketing = item.get("ticketing") if isinstance(item.get("ticketing"), dict) else {}
        automation = item.get("automation") if isinstance(item.get("automation"), dict) else {}
        inbound = item.get("inbound") if isinstance(item.get("inbound"), dict) else {}
        outbound = item.get("outbound") if isinstance(item.get("outbound"), dict) else {}
        environment = item.get("environment") if isinstance(item.get("environment"), dict) else {}
        launch = item.get("launch") if isinstance(item.get("launch"), dict) else {}
        surface_type = str(surface.get("type") or "")
        surfaces.append({
            "surfaceType": surface_type,
            "surfaceLabel": str(surface.get("label") or surface_type),
            "channelKey": str(channel.get("key") or ""),
            "channelStatus": str(channel.get("status") or ("configured" if channel else "missing")),
            "ready": bool(surface.get("ready")),
            "blockers": _activation_text_list(surface.get("blockers")),
            "requiredMissingEnvVars": _activation_text_list(environment.get("requiredMissing")),
            "missingLiveTargets": _activation_text_list(launch.get("missingLiveTargets")),
            "nextActions": [action for action in next_actions if str(action.get("surfaceType") or "") == surface_type],
            "ticketing": {
                "ticketCreationMode": str(ticketing.get("ticketCreationMode") or ""),
                "everyMessage": bool(ticketing.get("everyMessage")),
                "ownerRouting": bool(ticketing.get("ownerRouting")),
                "defaultAssigneeEmail": str(ticketing.get("defaultAssigneeEmail") or ""),
                "defaultQueueKey": str(ticketing.get("defaultQueueKey") or ""),
                "defaultQueueName": str(ticketing.get("defaultQueueName") or ""),
            },
            "automation": {
                "autoPrepareTriage": bool(automation.get("autoPrepareTriage")),
                "autoPrepareCustomFields": bool(automation.get("autoPrepareCustomFields")),
                "autoPrepareAgentReply": bool(automation.get("autoPrepareAgentReply")),
                "autoPrepareAgentReplyOnUpdate": bool(automation.get("autoPrepareAgentReplyOnUpdate")),
                "humanReview": bool(automation.get("humanReview")),
                "agentAutoSend": bool(automation.get("agentAutoSend")),
            },
            "inbound": {
                "ready": bool(inbound.get("ready")),
                "webhookUrl": str(inbound.get("webhookUrl") or ""),
                "providerWebhookUrl": str(inbound.get("providerWebhookUrl") or ""),
                "webChatUrl": str(inbound.get("webChatUrl") or ""),
                "webChatEmbedScriptUrl": str(inbound.get("webChatEmbedScriptUrl") or ""),
            },
            "outbound": {
                "ready": bool(outbound.get("ready")),
                "transport": str(outbound.get("transport") or ""),
                "payloadMode": str(outbound.get("payloadMode") or ""),
                "webhookUrlEnv": str(outbound.get("webhookUrlEnv") or ""),
                "webhookTokenEnv": str(outbound.get("webhookTokenEnv") or ""),
                "botTokenEnv": str(outbound.get("botTokenEnv") or ""),
            },
            "liveTargets": launch.get("liveTargets") if isinstance(launch.get("liveTargets"), list) else [],
            "setupCommands": launch.get("commands") if isinstance(launch.get("commands"), list) else [],
            "setupPackage": item.get("setupPackage") if isinstance(item.get("setupPackage"), dict) else None,
            "providerRunbook": item.get("providerRunbook") if isinstance(item.get("providerRunbook"), dict) else None,
        })
    return {
        "kind": "support_channel_activation_plan",
        "generatedAt": str(backlog.get("generatedAt") or datetime.now(timezone.utc).isoformat()),
        "projectId": project_id,
        "source": "api",
        "summary": backlog.get("summary") if isinstance(backlog.get("summary"), dict) else {},
        "nextActions": next_actions,
        "secrets": {
            "missingEnvVars": secret_names,
            "groups": secret_groups,
            "template": _channel_activation_secret_template(secret_groups),
        },
        "surfaces": surfaces,
        "adapterMatrix": _channel_activation_adapter_matrix(backlog),
    }


def _preset_bootstrap_config(preset: dict[str, Any], actor_email: str) -> dict[str, Any]:
    config = dict(preset.get("config") if isinstance(preset.get("config"), dict) else {})
    config["ticketCreationMode"] = "per_message"
    config["autoPrepareTriage"] = True
    config["autoPrepareCustomFields"] = True
    config["autoPrepareAgentReply"] = True
    config["autoPrepareAgentReplyOnUpdate"] = True
    config["agentAutoSend"] = False
    config["defaultQueueKey"] = str(preset.get("defaultQueueKey") or config.get("defaultQueueKey") or "support")
    config["defaultQueueName"] = str(preset.get("defaultQueueName") or config.get("defaultQueueName") or "Support")
    clean_actor = actor_email.strip().lower()
    if clean_actor and not str(config.get("defaultAssigneeEmail") or "").strip():
        config["defaultAssigneeEmail"] = clean_actor
    return config


def _clean_bootstrap_surfaces(surfaces: list[str] | None) -> set[str]:
    allowed = {surface_type for surface_type, _label in CHANNEL_SURFACE_TARGETS}
    if not surfaces:
        return set(allowed)
    cleaned: set[str] = set()
    for surface in surfaces:
        normalized = _surface_channel_type(str(surface or "").strip().lower())
        if normalized in allowed:
            cleaned.add(normalized)
    return cleaned


def _bootstrap_channel_surface_setups(
    *,
    ctx: ProjectEditorDep,
    request: Request,
    actor_email: str,
    surfaces: list[str] | None,
    status: str,
) -> dict[str, Any]:
    target_surfaces = _clean_bootstrap_surfaces(surfaces)
    clean_status = status.strip().lower() or "paused"
    if clean_status not in {"paused", "active"}:
        clean_status = "paused"
    existing = list_channels(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=200,
    )
    configured_surfaces = {
        _surface_channel_type(str(channel.get("type") or ""))
        for channel in existing
    }
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for surface_type, label in CHANNEL_SURFACE_TARGETS:
        if surface_type not in target_surfaces:
            continue
        if surface_type in configured_surfaces:
            skipped.append({
                "surfaceType": surface_type,
                "surfaceLabel": label,
                "reason": "configured",
            })
            continue
        preset = _channel_preset("web_chat" if surface_type == "chat" else surface_type)
        channel = upsert_channel(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            channel_key=str(preset.get("channelKey") or f"{surface_type}-main"),
            channel_type=str(preset.get("type") or surface_type),
            name=str(preset.get("name") or label),
            status=clean_status,
            config=_preset_bootstrap_config(preset, actor_email),
        )
        created.append(channel)
        configured_surfaces.add(surface_type)
    refreshed = list_channels(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=200,
    )
    sync_runs = _safe_channel_sync_runs(ctx, limit=200)
    webhook_events = _safe_channel_webhook_events(ctx, limit=200)
    launch_proof_items = _safe_support_launch_items(ctx)
    hydrated = [
        _with_channel_setup(
            channel,
            ctx,
            request,
            sync_runs=sync_runs,
            launch_proof_items=launch_proof_items,
            webhook_events=webhook_events,
        )
        for channel in refreshed
    ]
    created_ids = {str(channel.get("id") or "") for channel in created}
    created_keys = {str(channel.get("channelKey") or "") for channel in created}
    created_hydrated = [
        channel for channel in hydrated
        if str(channel.get("id") or "") in created_ids
        or str(channel.get("channelKey") or "") in created_keys
    ]
    bootstrap_runs: list[dict[str, str]] = []
    completed_at = datetime.now(timezone.utc).isoformat()
    for channel in created_hydrated:
        channel_id = str(channel.get("id") or "").strip()
        channel_key = str(channel.get("channelKey") or "").strip()
        channel_type = _surface_channel_type(str(channel.get("type") or ""))
        result = {
            "status": "success",
            "processed": 1,
            "failed": 0,
            "skipped": 0,
            "created": True,
            "channelId": channel_id,
            "channelKey": channel_key,
            "channelType": str(channel.get("type") or ""),
            "surfaceType": channel_type,
            "activation": {
                "ticketCreationMode": "per_message",
                "autoPrepareTriage": True,
                "autoPrepareCustomFields": True,
                "autoPrepareAgentReply": True,
                "autoPrepareAgentReplyOnUpdate": True,
                "agentAutoSend": False,
            },
            "proof": {
                "kind": "activation_bootstrap",
                "channelId": channel_id,
                "channelKey": channel_key,
                "surfaceType": channel_type,
            },
        }
        try:
            run = record_channel_sync_run(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                channel_id=channel_id,
                source="admin-activation-bootstrap",
                result=result,
                started_at=completed_at,
                completed_at=completed_at,
            )
            bootstrap_runs.append({
                "channelId": channel_id,
                "channelKey": channel_key,
                "surfaceType": channel_type,
                "runId": str(run.get("id") or ""),
                "status": "recorded",
                "error": "",
            })
        except Exception as exc:
            bootstrap_runs.append({
                "channelId": channel_id,
                "channelKey": channel_key,
                "surfaceType": channel_type,
                "runId": "",
                "status": "failed",
                "error": str(exc),
            })
    return {
        "created": len(created_hydrated),
        "skipped": skipped,
        "items": created_hydrated,
        "bootstrapRuns": bootstrap_runs,
        "activationBacklog": _channel_activation_backlog(project_id=ctx.project_id, channels=hydrated),
    }


def _hydrated_channel_surface_setups(
    *,
    ctx: ProjectEditorDep | ProjectViewerDep,
    request: Request,
) -> list[dict[str, Any]]:
    channels = list_channels(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=200,
    )
    sync_runs = _safe_channel_sync_runs(ctx, limit=200)
    webhook_events = _safe_channel_webhook_events(ctx, limit=200)
    launch_proof_items = _safe_support_launch_items(ctx)
    return [
        _with_channel_setup(
            channel,
            ctx,
            request,
            sync_runs=sync_runs,
            launch_proof_items=launch_proof_items,
            webhook_events=webhook_events,
        )
        for channel in channels
    ]


def _activate_ready_channel_surface_setups(
    *,
    ctx: ProjectEditorDep,
    request: Request,
    surfaces: list[str] | None,
) -> dict[str, Any]:
    target_surfaces = _clean_bootstrap_surfaces(surfaces)
    hydrated = _hydrated_channel_surface_setups(ctx=ctx, request=request)
    backlog = _channel_activation_backlog(project_id=ctx.project_id, channels=hydrated)
    activate_actions = [
        action for action in backlog.get("nextActions", [])
        if isinstance(action, dict)
        and str(action.get("phase") or "") == "activate"
        and str(action.get("surfaceType") or "") in target_surfaces
    ]
    by_id = {str(channel.get("id") or ""): channel for channel in hydrated}
    by_key = {str(channel.get("channelKey") or ""): channel for channel in hydrated}
    activated: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    activation_runs: list[dict[str, str]] = []
    completed_at = datetime.now(timezone.utc).isoformat()
    for action in activate_actions:
        channel_id = str(action.get("channelId") or "").strip()
        channel_key = str(action.get("channelKey") or "").strip()
        channel = by_id.get(channel_id) or by_key.get(channel_key)
        if not channel:
            skipped.append({
                "surfaceType": str(action.get("surfaceType") or ""),
                "surfaceLabel": str(action.get("surfaceLabel") or ""),
                "channelId": channel_id,
                "channelKey": channel_key,
                "reason": "not_found",
            })
            continue
        config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
        updated = upsert_channel(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            channel_key=str(channel.get("channelKey") or channel.get("channel_key") or channel_key),
            channel_type=str(channel.get("type") or ""),
            name=str(channel.get("name") or action.get("surfaceLabel") or ""),
            status="active",
            config=config,
        )
        activated.append(updated)
        run_result = {
            "status": "success",
            "processed": 1,
            "failed": 0,
            "skipped": 0,
            "activated": True,
            "channelId": str(updated.get("id") or channel_id),
            "channelKey": str(updated.get("channelKey") or channel.get("channelKey") or channel_key),
            "channelType": str(updated.get("type") or channel.get("type") or ""),
            "surfaceType": str(action.get("surfaceType") or ""),
            "proof": {
                "kind": "activation_ready",
                "channelId": str(updated.get("id") or channel_id),
                "channelKey": str(updated.get("channelKey") or channel.get("channelKey") or channel_key),
                "surfaceType": str(action.get("surfaceType") or ""),
            },
        }
        try:
            run = record_channel_sync_run(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                channel_id=str(updated.get("id") or channel_id),
                source="admin-activation-ready",
                result=run_result,
                started_at=completed_at,
                completed_at=completed_at,
            )
            activation_runs.append({
                "channelId": str(updated.get("id") or channel_id),
                "channelKey": str(updated.get("channelKey") or channel.get("channelKey") or channel_key),
                "surfaceType": str(action.get("surfaceType") or ""),
                "runId": str(run.get("id") or ""),
                "status": "recorded",
                "error": "",
            })
        except Exception as exc:
            activation_runs.append({
                "channelId": str(updated.get("id") or channel_id),
                "channelKey": str(updated.get("channelKey") or channel.get("channelKey") or channel_key),
                "surfaceType": str(action.get("surfaceType") or ""),
                "runId": "",
                "status": "failed",
                "error": str(exc),
            })

    refreshed = _hydrated_channel_surface_setups(ctx=ctx, request=request)
    activated_ids = {str(channel.get("id") or "") for channel in activated}
    activated_keys = {str(channel.get("channelKey") or "") for channel in activated}
    activated_hydrated = [
        channel for channel in refreshed
        if str(channel.get("id") or "") in activated_ids
        or str(channel.get("channelKey") or "") in activated_keys
    ]
    return {
        "activated": len(activated_hydrated),
        "skipped": skipped,
        "items": activated_hydrated,
        "activationRuns": activation_runs,
        "activationBacklog": _channel_activation_backlog(project_id=ctx.project_id, channels=refreshed),
    }


def _provider_validation_skip(provider: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": "skipped",
        "checked": False,
        "detail": detail,
        **{key: value for key, value in extra.items() if value},
    }


def _provider_validation_error(provider: str, detail: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": "failed",
        "checked": True,
        "detail": detail,
    }


def _provider_validation_ready(provider: str, detail: str, identity: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": "ready",
        "checked": True,
        "detail": detail,
        "identity": identity or {},
    }


def _remediation_step(
    key: str,
    label: str,
    detail: str,
    *,
    severity: str = "warning",
    action: str = "",
    run_action: str = "",
    copy_label: str = "",
    copy_value: str = "",
) -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "detail": detail,
        "severity": severity,
        "action": action,
        "runAction": run_action,
        "copyLabel": copy_label,
        "copyValue": copy_value,
    }


def _dedupe_remediation(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in items:
        key = str(item.get("key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _provider_validation_remediation(
    provider_validation: dict[str, Any],
    *,
    setup: dict[str, Any],
) -> list[dict[str, str]]:
    status = str(provider_validation.get("status") or "")
    if status == "ready":
        return []
    provider = str(provider_validation.get("provider") or "provider")
    detail = str(provider_validation.get("detail") or "").strip()
    lower_detail = detail.lower()
    env_vars = provider_validation.get("envVars") if isinstance(provider_validation.get("envVars"), list) else []
    token_env = str(provider_validation.get("tokenEnv") or "").strip()
    env_names = [str(name) for name in [*env_vars, token_env] if str(name).strip()]
    items: list[dict[str, str]] = []
    if env_names:
        items.append(_remediation_step(
            f"{provider}_provider_env",
            "Set provider credentials",
            "Configure required provider env: " + ", ".join(env_names),
            severity="critical" if provider_validation.get("required") else "warning",
            action="copy",
            copy_label="Env names",
            copy_value="\n".join(env_names),
        ))
    if status == "skipped":
        items.append(_remediation_step(
            f"{provider}_provider_validation_skipped",
            "Run credential validation",
            detail or "Provider credential check was skipped because required config is missing.",
            run_action="provider_validation",
        ))
        return _dedupe_remediation(items)
    if any(token_marker in lower_detail for token_marker in ("invalid_auth", "unauthorized", "401", "token", "invalid token")):
        items.append(_remediation_step(
            f"{provider}_provider_token",
            "Rotate provider token",
            f"{provider.title()} rejected credentials. Check bot token env and reinstall/rotate the provider app.",
            severity="critical",
            run_action="provider_validation",
        ))
    elif any(scope_marker in lower_detail for scope_marker in ("403", "missing_scope", "not_allowed", "forbidden", "insufficient")):
        items.append(_remediation_step(
            f"{provider}_provider_scopes",
            "Fix provider permissions",
            f"{provider.title()} accepted the credential path but rejected permissions. Check bot scopes, channel access, and app install.",
            severity="critical",
            run_action="provider_validation",
        ))
    elif any(network_marker in lower_detail for network_marker in ("timeout", "connection", "connect", "dns", "name resolution")):
        items.append(_remediation_step(
            f"{provider}_provider_network",
            "Check provider reachability",
            "The backend could not reach the provider API. Check outbound network, proxy, DNS, and provider status.",
            run_action="provider_validation",
        ))
    elif "invalid json" in lower_detail:
        items.append(_remediation_step(
            f"{provider}_provider_response",
            "Inspect provider response",
            "Provider endpoint returned non-JSON or unexpected JSON. Confirm the configured API/webhook URL.",
            run_action="provider_validation",
        ))
    else:
        items.append(_remediation_step(
            f"{provider}_provider_error",
            "Review provider error",
            detail or "Provider validation failed. Fix provider credentials or setup and validate again.",
            severity="critical",
            run_action="provider_validation",
        ))
    outbound_envs = setup.get("outboundBotCredentialEnvVars")
    if isinstance(outbound_envs, list) and outbound_envs:
        items.append(_remediation_step(
            "outbound_bot_credentials",
            "Confirm bot reply credentials",
            "Native provider replies need bot credentials: " + ", ".join(str(env) for env in outbound_envs),
            action="copy",
            copy_label="Bot env names",
            copy_value="\n".join(str(env) for env in outbound_envs),
        ))
    elif setup.get("outboundBotTokenEnv"):
        bot_env = str(setup.get("outboundBotTokenEnv") or "")
        items.append(_remediation_step(
            "outbound_bot_credentials",
            "Confirm bot reply token",
            f"Native provider replies need {bot_env}.",
            action="copy",
            copy_label="Bot token env",
            copy_value=bot_env,
        ))
    return _dedupe_remediation(items)


def _setup_remediation(
    *,
    setup: dict[str, Any],
    checks: list[dict[str, Any]],
    env_vars: list[dict[str, Any]],
    provider_validation: dict[str, Any],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    missing_required_env = [
        str(env.get("name") or "")
        for env in env_vars
        if env.get("required") and not env.get("configured") and env.get("name")
    ]
    if missing_required_env:
        items.append(_remediation_step(
            "required_env",
            "Set required environment",
            "Missing required env: " + ", ".join(missing_required_env),
            severity="critical",
            action="copy",
            copy_label="Env names",
            copy_value="\n".join(missing_required_env),
        ))
    for check in checks:
        if not isinstance(check, dict) or str(check.get("status") or "") not in {"missing", "warning"}:
            continue
        key = str(check.get("key") or "")
        label = str(check.get("label") or key or "Setup check")
        detail = str(check.get("detail") or "Fix this setup check.")
        if key == "inbound_url":
            items.append(_remediation_step("inbound_url", label, detail, severity="critical"))
        elif key == "auth":
            items.append(_remediation_step("webhook_auth", label, detail, severity="critical"))
        elif key == "outbound":
            copy_value = "\n".join(
                str(value)
                for value in [
                    setup.get("outboundWebhookUrlEnv"),
                    setup.get("outboundWebhookTokenEnv"),
                    setup.get("outboundBotTokenEnv"),
                    *(setup.get("outboundBotCredentialEnvVars") if isinstance(setup.get("outboundBotCredentialEnvVars"), list) else []),
                ]
                if str(value or "").strip()
            )
            items.append(_remediation_step(
                "outbound_reply_path",
                label,
                detail,
                severity="critical",
                action="copy" if copy_value else "",
                copy_label="Outbound env names" if copy_value else "",
                copy_value=copy_value,
            ))
        else:
            items.append(_remediation_step(f"setup_{key}", label, detail))
    items.extend(_provider_validation_remediation(provider_validation, setup=setup))
    return _dedupe_remediation(items)[:6]


def _smoke_remediation(result: dict[str, Any], *, phase: str) -> list[dict[str, str]]:
    validation = result.get("validation") if isinstance(result.get("validation"), dict) else {}
    items = list(validation.get("remediation") if isinstance(validation.get("remediation"), list) else [])
    error = str(result.get("error") or "")
    if phase == "inbound" and not str(result.get("issueId") or ""):
        items.append(_remediation_step(
            "smoke_no_ticket",
            "Check inbound ticket creation",
            error or "Smoke did not create a ticket. Check provider URL/auth, payload shape, and channel ticket mode.",
            severity="critical",
            run_action="inbound_smoke",
        ))
    if phase == "outbound" and bool(result.get("failed")):
        items.append(_remediation_step(
            "smoke_reply_failed",
            "Check reply delivery",
            error or "Outbound smoke failed. Check provider bot/webhook credentials and channel/thread routing ids.",
            severity="critical",
            run_action="outbound_smoke",
        ))
    if phase == "lifecycle" and bool(result.get("failed")):
        items.append(_remediation_step(
            "smoke_lifecycle_failed",
            "Check full channel lifecycle",
            error or "Lifecycle smoke failed before completing ticket creation, approval, and provider delivery.",
            severity="critical",
            run_action="lifecycle_smoke",
        ))
    return _dedupe_remediation(items)[:6]


def _teams_app_credential_envs(config: dict[str, Any]) -> tuple[str, str]:
    app_id_env = str(config.get("teamsAppIdEnv") or config.get("teams_app_id_env") or "SUPPORT_TEAMS_APP_ID").strip()
    app_password_env = str(
        config.get("teamsAppPasswordEnv")
        or config.get("teams_app_password_env")
        or "SUPPORT_TEAMS_APP_PASSWORD"
    ).strip()
    return app_id_env or "SUPPORT_TEAMS_APP_ID", app_password_env or "SUPPORT_TEAMS_APP_PASSWORD"


def _teams_uses_bot_outbound(config: dict[str, Any]) -> bool:
    transport = str(config.get("outboundTransport") or config.get("outbound_transport") or "").strip().lower()
    return transport in {"bot", "teams_bot", "bot_framework", "bot_api", "provider_api"}


def _http_response_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    if isinstance(body, dict):
        for key in ("error", "message", "detail", "description"):
            value = body.get(key)
            if value:
                if isinstance(value, dict):
                    nested = value.get("message") or value.get("code") or value.get("type")
                    return f"HTTP {response.status_code}: {nested or value}"
                return f"HTTP {response.status_code}: {value}"
    if isinstance(body, str) and body.strip():
        return f"HTTP {response.status_code}: {body.strip()[:160]}"
    return f"HTTP {response.status_code}"


def _slack_provider_validation(config: dict[str, Any], setup: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    token_env = _slack_bot_token_env(config)
    token = _secret_value(token_env, secrets)
    if not token:
        return _provider_validation_skip("slack", "Slack bot token env missing", tokenEnv=token_env)
    try:
        with httpx.Client(timeout=8) as client:
            response = client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return _provider_validation_error("slack", str(exc))
    if response.status_code >= 400:
        return _provider_validation_error("slack", _http_response_error(response))
    try:
        data = response.json()
    except ValueError:
        return _provider_validation_error("slack", "Slack returned invalid JSON")
    if not isinstance(data, dict) or data.get("ok") is not True:
        return _provider_validation_error("slack", str(data.get("error") if isinstance(data, dict) else "Slack auth failed"))
    identity = {
        key: data.get(key)
        for key in ("team", "team_id", "user", "user_id", "bot_id", "url")
        if data.get(key)
    }
    return _provider_validation_ready("slack", "Slack bot token accepted", identity)


def _telegram_provider_validation(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    token_env = _telegram_bot_token_env(config)
    token = _secret_value(token_env, secrets)
    if not token:
        return _provider_validation_skip("telegram", "Telegram bot token env missing", tokenEnv=token_env)
    try:
        with httpx.Client(timeout=8) as client:
            response = client.get(f"https://api.telegram.org/bot{token}/getMe")
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return _provider_validation_error("telegram", str(exc))
    if response.status_code >= 400:
        return _provider_validation_error("telegram", _http_response_error(response))
    try:
        data = response.json()
    except ValueError:
        return _provider_validation_error("telegram", "Telegram returned invalid JSON")
    if not isinstance(data, dict) or data.get("ok") is not True:
        detail = data.get("description") or data.get("error") if isinstance(data, dict) else "Telegram auth failed"
        return _provider_validation_error("telegram", str(detail))
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    identity = {
        key: result.get(key)
        for key in ("id", "username", "first_name")
        if result.get(key)
    }
    return _provider_validation_ready("telegram", "Telegram bot token accepted", identity)


def _teams_provider_validation(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    app_id_env, app_password_env = _teams_app_credential_envs(config)
    app_id = _secret_value(app_id_env, secrets)
    app_password = _secret_value(app_password_env, secrets)
    missing_envs = [env for env, value in ((app_id_env, app_id), (app_password_env, app_password)) if not value]
    if missing_envs:
        return _provider_validation_skip(
            "teams",
            f"Teams app credential env missing: {', '.join(missing_envs)}",
            required=True,
            envVars=missing_envs,
        )
    try:
        with httpx.Client(timeout=8) as client:
            response = client.post(
                "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": app_id,
                    "client_secret": app_password,
                    "scope": "https://api.botframework.com/.default",
                },
            )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return _provider_validation_error("teams", str(exc))
    if response.status_code >= 400:
        return _provider_validation_error("teams", _http_response_error(response))
    try:
        data = response.json()
    except ValueError:
        return _provider_validation_error("teams", "Teams token endpoint returned invalid JSON")
    if not isinstance(data, dict) or not data.get("access_token"):
        return _provider_validation_error("teams", "Teams token endpoint did not return an access token")
    identity = {
        "appId": app_id,
        "tokenType": data.get("token_type", ""),
        "expiresIn": data.get("expires_in", ""),
    }
    return _provider_validation_ready("teams", "Teams Bot Framework credentials accepted", identity)


def _discord_provider_validation(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    if _discord_uses_bot_outbound(config):
        bot_token_env = _discord_bot_token_env(config)
        bot_token = _secret_value(bot_token_env, secrets)
        if not bot_token:
            return _provider_validation_skip(
                "discord",
                f"Discord bot token env missing: {bot_token_env}",
                required=True,
                envVars=[bot_token_env],
            )
        api_base = str(config.get("discordApiBaseUrl") or config.get("discord_api_base_url") or "https://discord.com/api/v10").strip()
        try:
            with httpx.Client(timeout=8) as client:
                response = client.get(
                    f"{api_base.rstrip('/')}/users/@me",
                    headers={"Authorization": f"Bot {bot_token}"},
                )
        except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
            return _provider_validation_error("discord", str(exc))
        if response.status_code >= 400:
            return _provider_validation_error("discord", _http_response_error(response))
        try:
            data = response.json()
        except ValueError:
            return _provider_validation_error("discord", "Discord returned invalid JSON")
        identity = {}
        if isinstance(data, dict):
            identity = {
                key: data.get(key)
                for key in ("id", "username", "global_name")
                if data.get(key)
            }
        return _provider_validation_ready("discord", "Discord bot token accepted", identity)

    webhook_url = _resolved_outbound_url(config, secrets)
    if not webhook_url:
        return _provider_validation_skip("discord", "Discord webhook URL missing")
    try:
        with httpx.Client(timeout=8) as client:
            response = client.get(webhook_url)
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return _provider_validation_error("discord", str(exc))
    if response.status_code >= 400:
        return _provider_validation_error("discord", _http_response_error(response))
    try:
        data = response.json()
    except ValueError:
        return _provider_validation_error("discord", "Discord returned invalid JSON")
    identity = {}
    if isinstance(data, dict):
        identity = {
            key: data.get(key)
            for key in ("id", "name", "channel_id", "guild_id")
            if data.get(key)
        }
    return _provider_validation_ready("discord", "Discord webhook accepted", identity)


def _whatsapp_provider_validation(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    token_env = _whatsapp_access_token_env(config)
    token = _secret_value(token_env, secrets)
    phone_number_id, phone_number_id_env = _whatsapp_phone_number_id(config, secrets)
    missing_envs = []
    if not token:
        missing_envs.append(token_env)
    if not phone_number_id:
        missing_envs.append(phone_number_id_env or "phoneNumberId")
    if missing_envs:
        return _provider_validation_skip(
            "whatsapp",
            f"WhatsApp Cloud API credential env missing: {', '.join(missing_envs)}",
            required=True,
            envVars=missing_envs,
        )
    graph_base = str(
        config.get("whatsappGraphBaseUrl")
        or config.get("whatsapp_graph_base_url")
        or config.get("graphBaseUrl")
        or config.get("graph_base_url")
        or "https://graph.facebook.com/v20.0"
    ).strip() or "https://graph.facebook.com/v20.0"
    try:
        with httpx.Client(timeout=8) as client:
            response = client.get(
                f"{graph_base.rstrip('/')}/{quote(phone_number_id, safe='')}",
                params={"fields": "id,display_phone_number,verified_name,quality_rating"},
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return _provider_validation_error("whatsapp", str(exc))
    if response.status_code >= 400:
        return _provider_validation_error("whatsapp", _http_response_error(response))
    try:
        data = response.json()
    except ValueError:
        return _provider_validation_error("whatsapp", "WhatsApp Graph API returned invalid JSON")
    if not isinstance(data, dict) or not data.get("id"):
        return _provider_validation_error("whatsapp", "WhatsApp Graph API did not return a phone number identity")
    identity = {
        key: data.get(key)
        for key in ("id", "display_phone_number", "verified_name", "quality_rating")
        if data.get(key)
    }
    return _provider_validation_ready("whatsapp", "WhatsApp Cloud API access token accepted", identity)


def _messenger_provider_validation(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    token_env = _messenger_page_access_token_env(config)
    token = _secret_value(token_env, secrets)
    page_id, page_id_env = _messenger_page_id(config, secrets)
    missing_envs = []
    if not token:
        missing_envs.append(token_env)
    if not page_id:
        missing_envs.append(page_id_env or "pageId")
    if missing_envs:
        return _provider_validation_skip(
            "messenger",
            f"Messenger Graph API credential env missing: {', '.join(missing_envs)}",
            required=True,
            envVars=missing_envs,
        )
    graph_base = str(
        config.get("messengerGraphBaseUrl")
        or config.get("messenger_graph_base_url")
        or config.get("graphBaseUrl")
        or config.get("graph_base_url")
        or "https://graph.facebook.com/v20.0"
    ).strip() or "https://graph.facebook.com/v20.0"
    try:
        with httpx.Client(timeout=8) as client:
            response = client.get(
                f"{graph_base.rstrip('/')}/{quote(page_id, safe='')}",
                params={"fields": "id,name,username,category"},
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return _provider_validation_error("messenger", str(exc))
    if response.status_code >= 400:
        return _provider_validation_error("messenger", _http_response_error(response))
    try:
        data = response.json()
    except ValueError:
        return _provider_validation_error("messenger", "Messenger Graph API returned invalid JSON")
    if not isinstance(data, dict) or not data.get("id"):
        return _provider_validation_error("messenger", "Messenger Graph API did not return a page identity")
    identity = {
        key: data.get(key)
        for key in ("id", "name", "username", "category")
        if data.get(key)
    }
    return _provider_validation_ready("messenger", "Messenger Page Access Token accepted", identity)


def _instagram_provider_validation(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    token_env = _instagram_access_token_env(config)
    token = _secret_value(token_env, secrets)
    account_id, account_id_env = _instagram_account_id(config, secrets)
    missing_envs = []
    if not token:
        missing_envs.append(token_env)
    if not account_id:
        missing_envs.append(account_id_env or "instagramAccountId")
    if missing_envs:
        return _provider_validation_skip(
            "instagram",
            f"Instagram Graph API credential env missing: {', '.join(missing_envs)}",
            required=True,
            envVars=missing_envs,
        )
    graph_base = str(
        config.get("instagramGraphBaseUrl")
        or config.get("instagram_graph_base_url")
        or config.get("graphBaseUrl")
        or config.get("graph_base_url")
        or "https://graph.facebook.com/v20.0"
    ).strip() or "https://graph.facebook.com/v20.0"
    try:
        with httpx.Client(timeout=8) as client:
            response = client.get(
                f"{graph_base.rstrip('/')}/{quote(account_id, safe='')}",
                params={"fields": "id,username,name"},
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return _provider_validation_error("instagram", str(exc))
    if response.status_code >= 400:
        return _provider_validation_error("instagram", _http_response_error(response))
    try:
        data = response.json()
    except ValueError:
        return _provider_validation_error("instagram", "Instagram Graph API returned invalid JSON")
    if not isinstance(data, dict) or not data.get("id"):
        return _provider_validation_error("instagram", "Instagram Graph API did not return an account identity")
    identity = {
        key: data.get(key)
        for key in ("id", "username", "name")
        if data.get(key)
    }
    return _provider_validation_ready("instagram", "Instagram Graph API access token accepted", identity)


def _twitter_provider_validation(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    token_env = _twitter_bearer_token_env(config)
    token = _secret_value(token_env, secrets)
    user_id, user_id_env = _twitter_user_id(config, secrets)
    missing_envs = []
    if not token:
        missing_envs.append(token_env)
    if not user_id:
        missing_envs.append(user_id_env or "twitterUserId")
    if missing_envs:
        return _provider_validation_skip(
            "twitter",
            f"X API credential env missing: {', '.join(missing_envs)}",
            required=True,
            envVars=missing_envs,
        )
    api_base = str(
        config.get("twitterApiBaseUrl")
        or config.get("twitter_api_base_url")
        or config.get("xApiBaseUrl")
        or config.get("x_api_base_url")
        or config.get("apiBaseUrl")
        or config.get("api_base_url")
        or "https://api.x.com"
    ).strip() or "https://api.x.com"
    try:
        with httpx.Client(timeout=8) as client:
            response = client.get(
                f"{api_base.rstrip('/')}/2/users/{quote(user_id, safe='')}",
                params={"user.fields": "id,name,username"},
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return _provider_validation_error("twitter", str(exc))
    if response.status_code >= 400:
        return _provider_validation_error("twitter", _http_response_error(response))
    try:
        data = response.json()
    except ValueError:
        return _provider_validation_error("twitter", "X API returned invalid JSON")
    identity = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    if not isinstance(identity, dict) or not identity.get("id"):
        return _provider_validation_error("twitter", "X API did not return a user identity")
    clean_identity = {
        key: identity.get(key)
        for key in ("id", "name", "username")
        if identity.get(key)
    }
    return _provider_validation_ready("twitter", "X API bearer token accepted", clean_identity)


def _line_provider_validation(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    token_env = _line_channel_access_token_env(config)
    token = _secret_value(token_env, secrets)
    if not token:
        return _provider_validation_skip(
            "line",
            f"LINE channel access token env missing: {token_env}",
            required=True,
            envVars=[token_env],
        )
    api_base = str(
        config.get("lineApiBaseUrl")
        or config.get("line_api_base_url")
        or config.get("apiBaseUrl")
        or config.get("api_base_url")
        or "https://api.line.me"
    ).strip() or "https://api.line.me"
    try:
        with httpx.Client(timeout=8) as client:
            response = client.get(
                f"{api_base.rstrip('/')}/v2/bot/info",
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return _provider_validation_error("line", str(exc))
    if response.status_code >= 400:
        return _provider_validation_error("line", _http_response_error(response))
    try:
        data = response.json()
    except ValueError:
        return _provider_validation_error("line", "LINE Messaging API returned invalid JSON")
    if not isinstance(data, dict) or not data.get("userId"):
        return _provider_validation_error("line", "LINE Messaging API did not return a bot identity")
    identity = {
        key: data.get(key)
        for key in ("userId", "basicId", "displayName", "premiumId")
        if data.get(key)
    }
    return _provider_validation_ready("line", "LINE channel access token accepted", identity)


def _viber_provider_validation(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    token_env = _viber_auth_token_env(config)
    token = _secret_value(token_env, secrets)
    if not token:
        return _provider_validation_skip(
            "viber",
            f"Viber auth token env missing: {token_env}",
            required=True,
            envVars=[token_env],
        )
    api_base = str(
        config.get("viberApiBaseUrl")
        or config.get("viber_api_base_url")
        or config.get("apiBaseUrl")
        or config.get("api_base_url")
        or "https://chatapi.viber.com/pa"
    ).strip() or "https://chatapi.viber.com/pa"
    try:
        with httpx.Client(timeout=8) as client:
            response = client.post(
                f"{api_base.rstrip('/')}/get_account_info",
                headers={"X-Viber-Auth-Token": token},
                json={},
            )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return _provider_validation_error("viber", str(exc))
    if response.status_code >= 400:
        return _provider_validation_error("viber", _http_response_error(response))
    try:
        data = response.json()
    except ValueError:
        return _provider_validation_error("viber", "Viber Bot API returned invalid JSON")
    if not isinstance(data, dict) or data.get("status") not in {0, "0", None}:
        detail = data.get("status_message") or data.get("message") or data.get("error") if isinstance(data, dict) else "Viber auth failed"
        return _provider_validation_error("viber", str(detail or "Viber auth failed"))
    identity = {
        key: data.get(key)
        for key in ("id", "name", "uri", "country", "subscribers_count", "webhook")
        if data.get(key)
    }
    if not identity:
        return _provider_validation_error("viber", "Viber Bot API did not return a bot identity")
    return _provider_validation_ready("viber", "Viber auth token accepted", identity)


def _twilio_provider_validation(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    account_sid_env = _twilio_account_sid_env(config)
    auth_token_env = _twilio_auth_token_env(config)
    account_sid = _secret_value(account_sid_env, secrets)
    auth_token = _secret_value(auth_token_env, secrets)
    missing_envs = []
    if not account_sid:
        missing_envs.append(account_sid_env)
    if not auth_token:
        missing_envs.append(auth_token_env)
    from_number, from_number_env, messaging_service_sid, messaging_service_sid_env = _twilio_sender(config, secrets)
    if not from_number and not messaging_service_sid:
        missing_envs.extend(name for name in (from_number_env, messaging_service_sid_env) if name)
    if missing_envs:
        return _provider_validation_skip(
            "sms",
            f"Twilio credential env missing: {', '.join(missing_envs)}",
            required=True,
            envVars=missing_envs,
        )
    api_base = str(
        config.get("twilioApiBaseUrl")
        or config.get("twilio_api_base_url")
        or config.get("apiBaseUrl")
        or config.get("api_base_url")
        or "https://api.twilio.com"
    ).strip() or "https://api.twilio.com"
    try:
        with httpx.Client(timeout=8) as client:
            response = client.get(
                f"{api_base.rstrip('/')}/2010-04-01/Accounts/{quote(account_sid, safe='')}.json",
                auth=(account_sid, auth_token),
            )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        return _provider_validation_error("sms", str(exc))
    if response.status_code >= 400:
        return _provider_validation_error("sms", _http_response_error(response))
    try:
        data = response.json()
    except ValueError:
        return _provider_validation_error("sms", "Twilio API returned invalid JSON")
    if not isinstance(data, dict) or not data.get("sid"):
        return _provider_validation_error("sms", "Twilio API did not return an account identity")
    identity = {
        key: data.get(key)
        for key in ("sid", "friendly_name", "status", "type")
        if data.get(key)
    }
    identity["sender"] = messaging_service_sid or from_number
    return _provider_validation_ready("sms", "Twilio API credentials accepted", identity)


def _provider_validation(channel: dict[str, Any], setup: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    channel_type = str(channel.get("type") or "").strip().lower()
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    if channel_type == "slack":
        return _slack_provider_validation(config, setup, secrets)
    if channel_type == "teams":
        return _teams_provider_validation(config, secrets)
    if channel_type == "telegram":
        return _telegram_provider_validation(config, secrets)
    if channel_type == "discord":
        return _discord_provider_validation(config, secrets)
    if channel_type == "line":
        return _line_provider_validation(config, secrets)
    if channel_type == "viber":
        return _viber_provider_validation(config, secrets)
    if channel_type == "whatsapp":
        return _whatsapp_provider_validation(config, secrets)
    if channel_type in {"messenger", "facebook_messenger"}:
        return _messenger_provider_validation(config, secrets)
    if channel_type == "instagram":
        return _instagram_provider_validation(config, secrets)
    if channel_type in {"twitter", "x"}:
        return _twitter_provider_validation(config, secrets)
    if channel_type == "sms":
        return _twilio_provider_validation(config, secrets)
    return _provider_validation_skip(_provider_name(channel_type).lower(), "Provider credential check is not available")


def _slack_oauth_client_config(secrets: dict[str, str] | None) -> tuple[str, str]:
    client_id = _slack_oauth_secret(secrets, "SUPPORT_SLACK_CLIENT_ID", "SLACK_CLIENT_ID")
    client_secret = _slack_oauth_secret(secrets, "SUPPORT_SLACK_CLIENT_SECRET", "SLACK_CLIENT_SECRET")
    return client_id, client_secret


def _default_slack_oauth_scopes(secrets: dict[str, str] | None) -> str:
    configured = _slack_oauth_secret(secrets, "SUPPORT_SLACK_OAUTH_SCOPES", "SLACK_OAUTH_SCOPES")
    if configured:
        return configured
    return (
        "chat:write,channels:history,groups:history,im:history,mpim:history,"
        "channels:read,groups:read,users:read,app_mentions:read"
    )


def _slack_oauth_error_page(title: str, detail: str, status_code: int = 400) -> HTMLResponse:
    body = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{html.escape(title)}</title></head>
<body>
<h1>{html.escape(title)}</h1>
<p>{html.escape(detail)}</p>
</body>
</html>"""
    return HTMLResponse(body, status_code=status_code)


def _slack_oauth_success_page(team_name: str, channel_key: str) -> HTMLResponse:
    detail = f"Slack workspace {team_name or 'Slack'} installed for channel {channel_key}."
    body = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Slack installed</title></head>
<body>
<h1>Slack installed</h1>
<p>{html.escape(detail)}</p>
<p>You can close this tab and return to Channels.</p>
</body>
</html>"""
    return HTMLResponse(body)


def _merge_slack_channel_config(existing: dict[str, Any] | None, install: dict[str, Any], channel_key: str) -> dict[str, Any]:
    existing_config = existing.get("config") if isinstance(existing, dict) and isinstance(existing.get("config"), dict) else {}
    team = install.get("team") if isinstance(install.get("team"), dict) else {}
    enterprise = install.get("enterprise") if isinstance(install.get("enterprise"), dict) else {}
    return {
        **existing_config,
        "adapter": "slack",
        "teamId": str(team.get("id") or install.get("team_id") or existing_config.get("teamId") or "").strip(),
        "workspaceName": str(team.get("name") or existing_config.get("workspaceName") or "").strip(),
        "enterpriseId": str(enterprise.get("id") or existing_config.get("enterpriseId") or "").strip(),
        "appId": str(install.get("app_id") or existing_config.get("appId") or "").strip(),
        "botUserId": str(install.get("bot_user_id") or existing_config.get("botUserId") or "").strip(),
        "channelKey": channel_key,
        "ticketCreationMode": str(existing_config.get("ticketCreationMode") or "per_message"),
        "outboundPayloadMode": "provider",
        "autoPrepareTriage": existing_config.get("autoPrepareTriage", True),
        "autoPrepareCustomFields": existing_config.get("autoPrepareCustomFields", True),
        "autoPrepareAgentReply": existing_config.get("autoPrepareAgentReply", True),
        "autoPrepareAgentReplyOnUpdate": existing_config.get("autoPrepareAgentReplyOnUpdate", True),
        "defaultQueueKey": str(existing_config.get("defaultQueueKey") or "support"),
        "defaultQueueName": str(existing_config.get("defaultQueueName") or "Support"),
        "webhookTokenEnv": str(existing_config.get("webhookTokenEnv") or "SUPPORT_SLACK_WEBHOOK_TOKEN"),
        "slackSigningSecretEnv": str(existing_config.get("slackSigningSecretEnv") or "SUPPORT_SLACK_SIGNING_SECRET"),
        "slackBotTokenEnv": str(existing_config.get("slackBotTokenEnv") or "SUPPORT_SLACK_BOT_TOKEN"),
        "outboundTransport": "bot",
        "outboundWebhookUrl": "",
        "outboundWebhookUrlEnv": "",
        "outboundWebhookTokenEnv": "",
        "outboundTokenRequired": True,
    }


def _store_slack_install(
    *,
    tenant_id: str | None,
    project_id: str,
    channel_key: str,
    name: str,
    install: dict[str, Any],
) -> dict[str, Any]:
    access_token = str(install.get("access_token") or "").strip()
    if not access_token:
        raise ValueError("Slack OAuth response did not include a bot token")
    current_secrets = get_project_secrets(project_id)
    update_project_secrets(project_id, {**current_secrets, "SUPPORT_SLACK_BOT_TOKEN": access_token})
    existing = get_channel_by_key(channel_key, tenant_id=tenant_id, project_id=project_id)
    config = _merge_slack_channel_config(existing, install, channel_key)
    team = install.get("team") if isinstance(install.get("team"), dict) else {}
    channel_name = name.strip() or str(team.get("name") or "Slack")
    return upsert_channel(
        tenant_id=tenant_id,
        project_id=project_id,
        channel_key=channel_key,
        channel_type="slack",
        name=channel_name,
        status="active",
        config=config,
    )


def _exchange_slack_oauth_code(code: str, *, client_id: str, client_secret: str, redirect_uri: str) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=12) as client:
            response = client.post(
                "https://slack.com/api/oauth.v2.access",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        raise ValueError(str(exc)) from exc
    if response.status_code >= 400:
        raise ValueError(_http_response_error(response))
    try:
        data = response.json()
    except ValueError as exc:
        raise ValueError("Slack OAuth returned invalid JSON") from exc
    if not isinstance(data, dict) or data.get("ok") is not True:
        detail = data.get("error") if isinstance(data, dict) else "Slack OAuth failed"
        raise ValueError(str(detail or "Slack OAuth failed"))
    return data


def _telegram_webhook_response(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: data.get(key)
        for key in ("ok", "result", "description")
        if key in data
    }


def _channel_setup_validation(channel: dict[str, Any], ctx: ProjectViewerDep, request: Request) -> dict[str, Any]:
    channel_id = str(channel.get("id") or "")
    setup = _channel_setup(
        channel,
        ctx,
        request,
        launch_proof_items=_safe_support_launch_items(ctx),
        webhook_events=_safe_channel_webhook_events(ctx, channel_id=channel_id, limit=50),
    )
    runtime_secrets = load_runtime_secrets(ctx.tenant_id, ctx.project_id) or {}
    provider_validation = _provider_validation(channel, setup, runtime_secrets)
    checks = setup.get("setupChecklist") if isinstance(setup.get("setupChecklist"), list) else []
    env_vars = setup.get("envVars") if isinstance(setup.get("envVars"), list) else []
    missing_checks = [check for check in checks if check.get("status") == "missing"]
    warning_checks = [check for check in checks if check.get("status") == "warning"]
    manual_checks = [check for check in checks if check.get("status") == "manual"]
    configured_env = [env for env in env_vars if env.get("configured")]
    missing_env = [env for env in env_vars if not env.get("configured")]
    provider_failed = provider_validation.get("status") == "failed"
    provider_required_missing = bool(provider_validation.get("required")) and provider_validation.get("status") != "ready"
    remediation = _setup_remediation(
        setup=setup,
        checks=checks,
        env_vars=env_vars,
        provider_validation=provider_validation,
    )
    ready = (
        bool(setup.get("inboundReady"))
        and bool(setup.get("outboundReady"))
        and not missing_checks
        and not provider_failed
        and not provider_required_missing
    )
    status = "ready" if ready else "needs_setup"
    return {
        "channelId": channel.get("id", ""),
        "channelKey": channel.get("channelKey", ""),
        "type": channel.get("type", ""),
        "status": status,
        "ready": ready,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "checks": len(checks),
            "missing": len(missing_checks),
            "warnings": len(warning_checks),
            "manual": len(manual_checks),
            "envConfigured": len(configured_env),
            "envMissing": len(missing_env),
        },
        "checks": checks,
        "envVars": env_vars,
        "providerValidation": provider_validation,
        "remediation": remediation,
        "setup": setup,
    }


def _record_validation_run(
    channel: dict[str, Any],
    *,
    ctx: ProjectViewerDep,
    validation: dict[str, Any],
    started_at: str,
) -> str:
    channel_id = str(channel.get("id") or validation.get("channelId") or "")
    if not channel_id:
        return ""
    provider_validation = (
        validation.get("providerValidation")
        if isinstance(validation.get("providerValidation"), dict)
        else {}
    )
    remediation = (
        validation.get("remediation")
        if isinstance(validation.get("remediation"), list)
        else []
    )
    ready = bool(validation.get("ready"))
    detail = str(provider_validation.get("detail") or "").strip()
    result = {
        "status": "success" if ready else "failed",
        "ready": ready,
        "processed": 1,
        "failed": 0 if ready else 1,
        "skipped": 0,
        "detail": detail,
        "error": "" if ready else detail,
        "providerValidation": provider_validation,
        "remediation": remediation,
        "summary": validation.get("summary") if isinstance(validation.get("summary"), dict) else {},
        "proof": {
            "kind": "provider_validation",
            "channelId": channel_id,
            "channelKey": str(channel.get("channelKey") or channel.get("channel_key") or ""),
            "channelType": str(channel.get("type") or ""),
            "ready": ready,
            "provider": str(provider_validation.get("provider") or ""),
            "providerStatus": str(provider_validation.get("status") or ""),
            "checked": bool(provider_validation.get("checked")),
            "required": bool(provider_validation.get("required")),
            "remediationCount": len(remediation),
        },
    }
    try:
        run = record_channel_sync_run(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            channel_id=channel_id,
            source="admin-validation",
            result=result,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        validation["recordingError"] = str(exc)
        return ""
    return str(run.get("id") or "")


def _smoke_attachments(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for index, raw in enumerate(items or [], start=1):
        if not isinstance(raw, dict):
            continue
        filename = str(raw.get("filename") or raw.get("name") or raw.get("title") or raw.get("displayName") or "").strip()
        attachment_id = str(raw.get("id") or raw.get("fileId") or raw.get("file_id") or "").strip()
        url = str(raw.get("url") or raw.get("contentUrl") or raw.get("content_url") or raw.get("downloadUrl") or raw.get("url_private") or "").strip()
        content_type = str(raw.get("contentType") or raw.get("content_type") or raw.get("mimeType") or raw.get("mime_type") or raw.get("mimetype") or "").strip()
        base64_payload = str(raw.get("base64") or raw.get("contentBase64") or raw.get("content_base64") or "").strip()
        size_value = raw.get("size") or raw.get("sizeBytes") or raw.get("size_bytes") or raw.get("fileSize") or raw.get("file_size")
        try:
            size = int(size_value)
        except (TypeError, ValueError):
            size = 0
        if not filename and attachment_id:
            filename = attachment_id
        if not filename and url:
            filename = url.rsplit("/", 1)[-1] or f"attachment-{index}"
        if not filename and not url and not attachment_id:
            continue
        item: dict[str, Any] = {
            "filename": filename or f"attachment-{index}",
        }
        if attachment_id:
            item["id"] = attachment_id
        if url:
            item["url"] = url
        if content_type:
            item["contentType"] = content_type
        if base64_payload:
            item["base64"] = base64_payload
        if size > 0:
            item["size"] = size
        attachments.append(item)
    return attachments


def _slack_smoke_files(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for index, item in enumerate(attachments, start=1):
        filename = str(item.get("filename") or item.get("id") or f"attachment-{index}").strip()
        file_id = str(item.get("id") or f"F_ADMIN_SMOKE_{index}").strip()
        content_type = str(item.get("contentType") or "application/octet-stream").strip()
        file_item: dict[str, Any] = {
            "id": file_id,
            "name": filename,
            "title": filename,
            "mimetype": content_type,
            "filetype": content_type.split("/", 1)[-1] if "/" in content_type else content_type,
        }
        if item.get("url"):
            file_item["url_private"] = str(item.get("url") or "")
        if item.get("size"):
            file_item["size"] = item.get("size")
        files.append(file_item)
    return files


def _teams_smoke_attachments(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in attachments:
        attachment: dict[str, Any] = {
            "name": item.get("filename"),
            "contentType": item.get("contentType") or "application/octet-stream",
        }
        if item.get("url"):
            attachment["contentUrl"] = item.get("url")
        if item.get("id"):
            attachment["id"] = item.get("id")
        items.append(attachment)
    return items


def _discord_smoke_attachments(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, item in enumerate(attachments):
        attachment: dict[str, Any] = {
            "id": str(item.get("id") or index),
            "filename": item.get("filename"),
        }
        if item.get("contentType"):
            attachment["content_type"] = item.get("contentType")
        if item.get("url"):
            attachment["url"] = item.get("url")
        if item.get("size"):
            attachment["size"] = item.get("size")
        items.append(attachment)
    return items


def _telegram_smoke_attachment(attachments: list[dict[str, Any]]) -> dict[str, Any]:
    first = attachments[0] if attachments else {}
    if not first:
        return {}
    return {
        "file_id": str(first.get("id") or "admin-smoke-file"),
        "file_unique_id": str(first.get("id") or "admin-smoke-file"),
        "file_name": str(first.get("filename") or "attachment"),
        "mime_type": str(first.get("contentType") or "application/octet-stream"),
        "file_size": int(first.get("size") or 0),
    }


def _whatsapp_smoke_media(attachments: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    first = attachments[0] if attachments else {}
    if not first:
        return "", {}
    content_type = str(first.get("contentType") or "application/octet-stream").strip()
    media_type = "document"
    if content_type.startswith("image/"):
        media_type = "image"
    elif content_type.startswith("video/"):
        media_type = "video"
    elif content_type.startswith("audio/"):
        media_type = "audio"
    media = {
        "id": str(first.get("id") or "admin-smoke-media"),
        "mime_type": content_type,
        "sha256": str(first.get("sha256") or "admin-smoke-sha256"),
    }
    if media_type == "document":
        media["filename"] = str(first.get("filename") or "attachment")
    if first.get("caption"):
        media["caption"] = str(first.get("caption") or "")
    return media_type, media


def _generic_test_message_payload(channel_key: str, channel_type: str, body: ChannelTestMessageInput) -> tuple[dict[str, Any], str, str]:
    event_id = body.event_id.strip() or f"admin-test-{uuid4().hex}"
    message_id = body.message_id.strip() or event_id
    provider = body.provider.strip() or channel_type or "webhook"
    attachments = _smoke_attachments(body.attachments)
    payload = {
        "eventId": event_id,
        "eventType": "message_created",
        "provider": provider,
        "channelId": body.channel_id.strip() or f"admin-test-{channel_key}",
        "threadId": body.thread_id.strip(),
        "messageId": message_id,
        "content": body.body.strip(),
        "author": {
            "id": body.author_id.strip() or "admin-test-customer",
            "name": body.author_name.strip() or "Test customer",
            "email": body.author_email.strip() or "customer@example.com",
        },
        "metadata": {
            "source": "admin_test_message",
        },
    }
    if attachments:
        payload["attachments"] = attachments
    return payload, event_id, message_id


def _provider_smoke_payload(channel_key: str, channel_type: str, body: ChannelTestMessageInput) -> tuple[dict[str, Any], str, str, str]:
    event_id = body.event_id.strip() or f"admin-smoke-{uuid4().hex}"
    message_id = body.message_id.strip() or event_id
    channel_ref = body.channel_id.strip()
    thread_ref = body.thread_id.strip()
    text = body.body.strip()
    author_id = body.author_id.strip() or "admin-smoke-customer"
    author_name = body.author_name.strip() or "Test customer"
    author_email = body.author_email.strip() or "customer@example.com"
    attachments = _smoke_attachments(body.attachments)
    if channel_type == "email":
        subject = next((line.strip() for line in text.splitlines() if line.strip()), "Admin support smoke")[:160]
        return (
            {
                "email": {
                    "messageId": message_id,
                    "threadId": thread_ref or message_id,
                    "subject": subject,
                    "fromAddress": author_email,
                    "fromName": author_name,
                    "body": text,
                    "attachments": attachments,
                },
                "metadata": {
                    "source": "admin_smoke",
                    "channelKey": channel_key,
                    "eventId": event_id,
                },
            },
            "email",
            event_id,
            message_id,
        )
    if channel_type == "slack":
        slack_ts = message_id
        event: dict[str, Any] = {
            "type": "message",
            "channel": channel_ref or f"C_{channel_key}",
            "user": author_id,
            "text": text,
            "ts": slack_ts,
            "thread_ts": thread_ref or slack_ts,
        }
        if attachments:
            event["files"] = _slack_smoke_files(attachments)
            if not text:
                event["subtype"] = "file_share"
        return (
            {
                "type": "event_callback",
                "team_id": "T_ADMIN_SMOKE",
                "event_id": event_id,
                "event": event,
            },
            "slack",
            event_id,
            message_id,
        )
    if channel_type == "teams":
        payload = {
            "type": "message",
            "id": message_id,
            "text": text,
            "conversation": {"id": thread_ref or channel_ref or f"conversation-{channel_key}"},
            "from": {"id": author_id, "name": author_name},
            "channelData": {
                "team": {"id": "team-admin-smoke"},
                "channel": {"id": channel_ref or f"channel-{channel_key}"},
            },
        }
        if attachments:
            payload["attachments"] = _teams_smoke_attachments(attachments)
        return (
            payload,
            "teams",
            event_id,
            message_id,
        )
    if channel_type == "discord":
        data = {
            "id": message_id,
            "channel_id": channel_ref or f"discord-channel-{channel_key}",
            "guild_id": "discord-guild-admin-smoke",
            "content": text,
            "author": {"id": author_id, "username": author_name, "email": author_email, "bot": False},
        }
        if attachments:
            data["attachments"] = _discord_smoke_attachments(attachments)
        return (
            {
                "t": "MESSAGE_CREATE",
                "s": 1,
                "op": 0,
                "d": data,
            },
            "discord",
            event_id,
            message_id,
        )
    if channel_type == "telegram":
        update_id = int(datetime.now(timezone.utc).timestamp() * 1000)
        try:
            message_int = int(message_id)
        except ValueError:
            message_int = update_id % 2_147_483_647
        payload = {
            "update_id": update_id,
            "message": {
                "message_id": message_int,
                "chat": {"id": channel_ref or "admin-smoke-chat", "type": "private", "title": "Admin smoke"},
                "from": {"id": author_id, "first_name": author_name},
                "text": text,
            },
        }
        if attachments:
            payload["message"]["attachments"] = attachments
            payload["message"]["document"] = _telegram_smoke_attachment(attachments)
        return (
            payload,
            "telegram",
            event_id,
            str(message_int),
        )
    if channel_type == "line":
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        destination = channel_ref or f"line-bot-{channel_key}"
        source_id = thread_ref or author_id or "line-customer"
        message: dict[str, Any] = {
            "id": message_id,
            "type": "text",
            "text": text,
        }
        if attachments:
            first_attachment = attachments[0]
            message = {
                "id": message_id,
                "type": "file",
                "fileName": str(first_attachment.get("filename") or first_attachment.get("name") or "line-file"),
                "fileSize": int(first_attachment.get("size") or first_attachment.get("fileSize") or 0),
            }
        return (
            {
                "destination": destination,
                "events": [
                    {
                        "type": "message",
                        "mode": "active",
                        "timestamp": timestamp_ms,
                        "webhookEventId": event_id,
                        "replyToken": f"reply-{event_id}",
                        "source": {
                            "type": "user",
                            "userId": source_id,
                        },
                        "message": message,
                        "attachments": attachments,
                    }
                ],
            },
            "line",
            event_id,
            message_id,
        )
    if channel_type == "viber":
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        receiver = channel_ref or f"viber-bot-{channel_key}"
        sender_id = thread_ref or author_id or "viber-customer"
        token_digits = "".join(char for char in message_id if char.isdigit())
        message_token = int(token_digits[-18:] or str(timestamp_ms))
        message: dict[str, Any] = {
            "type": "text",
            "text": text,
            "tracking_data": event_id,
        }
        if attachments:
            first_attachment = attachments[0]
            message = {
                "type": "file",
                "media": str(first_attachment.get("url") or f"https://files.example/{first_attachment.get('id') or 'viber-file'}"),
                "file_name": str(first_attachment.get("filename") or first_attachment.get("name") or "viber-file"),
                "size": int(first_attachment.get("size") or first_attachment.get("fileSize") or 0),
                "tracking_data": event_id,
            }
        return (
            {
                "event": "message",
                "timestamp": timestamp_ms,
                "message_token": message_token,
                "chat_hostname": receiver,
                "sender": {
                    "id": sender_id,
                    "name": author_name,
                    "avatar": "",
                    "country": "US",
                    "language": "en",
                    "api_version": 1,
                },
                "message": message,
            },
            "viber",
            event_id,
            str(message_token),
        )
    if channel_type == "whatsapp":
        phone_number_id = channel_ref or f"whatsapp-phone-{channel_key}"
        wa_id = thread_ref or author_id or "15550000001"
        message: dict[str, Any] = {
            "from": wa_id,
            "id": message_id,
            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
            "type": "text",
            "text": {"body": text},
        }
        if attachments:
            media_type, media = _whatsapp_smoke_media(attachments)
            if media_type and media:
                message["type"] = media_type
                message[media_type] = media
                if not text:
                    message.pop("text", None)
        return (
            {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "id": "WABA_ADMIN_SMOKE",
                        "changes": [
                            {
                                "field": "messages",
                                "value": {
                                    "metadata": {
                                        "display_phone_number": "+15550000000",
                                        "phone_number_id": phone_number_id,
                                    },
                                    "contacts": [
                                        {
                                            "wa_id": wa_id,
                                            "profile": {"name": author_name},
                                        }
                                    ],
                                    "messages": [message],
                                },
                            }
                        ],
                    }
                ],
            },
            "whatsapp",
            event_id,
            message_id,
        )
    if channel_type in {"messenger", "facebook_messenger"}:
        page_id = channel_ref or f"messenger-page-{channel_key}"
        psid = thread_ref or author_id or "messenger-customer"
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        message: dict[str, Any] = {"mid": message_id, "text": text}
        if attachments:
            message["attachments"] = [
                {
                    "type": "file",
                    "payload": {
                        "url": str(item.get("url") or f"https://files.example/{item.get('id') or index}")
                    },
                }
                for index, item in enumerate(attachments)
            ]
        return (
            {
                "object": "page",
                "entry": [
                    {
                        "id": page_id,
                        "time": timestamp_ms,
                        "messaging": [
                            {
                                "sender": {"id": psid},
                                "recipient": {"id": page_id},
                                "timestamp": timestamp_ms,
                                "message": message,
                            }
                        ],
                    }
                ],
            },
            "messenger",
            event_id,
            message_id,
        )
    if channel_type == "instagram":
        account_id = channel_ref or f"instagram-account-{channel_key}"
        scoped_user_id = thread_ref or author_id or "instagram-customer"
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        message: dict[str, Any] = {"mid": message_id, "text": text}
        if attachments:
            message["attachments"] = [
                {
                    "type": "file",
                    "payload": {
                        "url": str(item.get("url") or f"https://files.example/{item.get('id') or index}")
                    },
                }
                for index, item in enumerate(attachments)
            ]
        return (
            {
                "object": "instagram",
                "entry": [
                    {
                        "id": account_id,
                        "time": timestamp_ms,
                        "messaging": [
                            {
                                "sender": {"id": scoped_user_id},
                                "recipient": {"id": account_id},
                                "timestamp": timestamp_ms,
                                "message": message,
                            }
                        ],
                    }
                ],
            },
            "instagram",
            event_id,
            message_id,
        )
    if channel_type in {"twitter", "x"}:
        subscribed_user_id = channel_ref or "4337869213"
        sender_id = thread_ref or author_id or "3001969357"
        timestamp_ms = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        message_data: dict[str, Any] = {
            "text": text,
            "entities": {"hashtags": [], "symbols": [], "user_mentions": [], "urls": []},
        }
        if attachments:
            message_data["attachment"] = {
                "type": "media",
                "media": {
                    "id": str(attachments[0].get("id") or "twitter-media-admin-smoke"),
                    "media_url": str(attachments[0].get("url") or "https://files.example/twitter-media"),
                },
            }
        return (
            {
                "for_user_id": subscribed_user_id,
                "direct_message_events": [
                    {
                        "type": "message_create",
                        "id": message_id,
                        "created_timestamp": timestamp_ms,
                        "message_create": {
                            "target": {"recipient_id": subscribed_user_id},
                            "sender_id": sender_id,
                            "source_app_id": "admin-smoke",
                            "message_data": message_data,
                        },
                    }
                ],
                "users": {
                    sender_id: {"id": sender_id, "name": author_name, "screen_name": author_name.lower().replace(" ", "_")},
                    subscribed_user_id: {"id": subscribed_user_id, "name": "Support", "screen_name": "support"},
                },
            },
            "twitter",
            event_id,
            message_id,
        )
    if channel_type == "sms":
        from_number = thread_ref or author_id
        if not from_number.startswith("+"):
            from_number = "+15551234567"
        to_number = channel_ref or "+15550001111"
        payload: dict[str, Any] = {
            "MessageSid": message_id,
            "SmsSid": message_id,
            "AccountSid": "AC_ADMIN_SMOKE",
            "From": from_number,
            "To": to_number,
            "Body": text,
            "NumMedia": str(len(attachments)),
            "SmsStatus": "received",
        }
        for index, attachment in enumerate(attachments):
            payload[f"MediaUrl{index}"] = str(attachment.get("url") or f"https://files.example/{attachment.get('id') or index}")
            payload[f"MediaContentType{index}"] = str(
                attachment.get("contentType")
                or attachment.get("content_type")
                or attachment.get("mimeType")
                or "application/octet-stream"
            )
        return (
            payload,
            "sms",
            event_id,
            message_id,
        )
    payload, event_id, message_id = _generic_test_message_payload(channel_key, channel_type, body)
    payload["metadata"]["source"] = "admin_smoke"
    return payload, str(payload.get("provider") or channel_type or "webhook"), event_id, message_id


def _smoke_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    items = result.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    item = {
        "eventId": result.get("eventId") or result.get("event_id"),
        "status": result.get("status"),
        "kind": result.get("kind") or "inbound_message",
        "issueId": result.get("issueId") or result.get("issue_id"),
        "messageId": result.get("messageId") or result.get("message_id"),
        "error": result.get("error"),
    }
    return [item] if any(item.values()) else []


def _smoke_count(result: dict[str, Any], key: str, fallback: int = 0) -> int:
    value = result.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def _smoke_url(provider: str, setup: dict[str, Any]) -> str:
    if provider in {"email", "slack", "teams", "discord", "telegram", "line", "viber", "whatsapp", "messenger", "instagram", "twitter", "sms"}:
        return str(setup.get("providerWebhookUrl") or "").strip()
    return str(setup.get("inboundWebhookUrl") or "").strip()


def _smoke_token(setup: dict[str, Any], secrets: dict[str, str] | None) -> tuple[str, str]:
    token_env = str(setup.get("providerTokenEnv") or setup.get("tokenEnv") or "").strip()
    token = _secret_value(token_env, secrets)
    if token:
        return token_env, token
    fallback_env = str(setup.get("fallbackTokenEnv") or "SUPPORT_SYNC_TOKEN").strip()
    fallback = _secret_value(fallback_env, secrets)
    if fallback:
        return fallback_env, fallback
    return token_env or fallback_env, ""


def _smoke_hmac_headers(setup: dict[str, Any], secret: str, raw_body: bytes) -> dict[str, str]:
    header = str(setup.get("signatureHeader") or "X-Support-Signature").strip() or "X-Support-Signature"
    if setup.get("signatureTimestampRequired"):
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        timestamp_header = str(
            setup.get("signatureTimestampHeader") or "X-Support-Signature-Timestamp"
        ).strip() or "X-Support-Signature-Timestamp"
        signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
        signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return {header: f"sha256={signature}", timestamp_header: timestamp}
    signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return {header: f"sha256={signature}"}


def _smoke_twilio_signature(url: str, payload: dict[str, Any], auth_token: str) -> str:
    signed = url + "".join(
        f"{key}{value}"
        for key, value in sorted((str(key), str(value)) for key, value in payload.items())
    )
    return base64.b64encode(
        hmac.new(auth_token.encode("utf-8"), signed.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")


def _smoke_http_timeout(provider: str = "") -> float:
    normalized_provider = provider.strip().lower()
    default = 180.0 if normalized_provider == "email" else 60.0
    configured = (
        os.getenv("SUPPORT_EMAIL_SMOKE_TIMEOUT")
        if normalized_provider == "email"
        else None
    )
    if configured is None:
        configured = os.getenv("SUPPORT_SMOKE_TIMEOUT")
    try:
        timeout = float(configured) if configured is not None else default
    except (TypeError, ValueError):
        timeout = default
    if not math.isfinite(timeout):
        timeout = default
    return max(1.0, min(timeout, 300.0))


def _smoke_http_headers(provider: str, setup: dict[str, Any], secrets: dict[str, str] | None, raw_body: bytes) -> tuple[dict[str, str], dict[str, str]]:
    headers = {"Content-Type": "application/json"}
    if provider == "slack":
        signature_env = str(setup.get("signatureEnv") or "SUPPORT_SLACK_SIGNING_SECRET").strip()
        signature_secret = _secret_value(signature_env, secrets)
        if signature_secret:
            timestamp = str(int(datetime.now(timezone.utc).timestamp()))
            base = f"v0:{timestamp}:".encode("utf-8") + raw_body
            headers["X-Slack-Request-Timestamp"] = timestamp
            headers["X-Slack-Signature"] = "v0=" + hmac.new(signature_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
            return headers, {
                "mode": "slack_signature",
                "env": signature_env,
                "header": "X-Slack-Signature",
                "timestampHeader": "X-Slack-Request-Timestamp",
            }
        if setup.get("signatureRequired"):
            raise ValueError(f"Slack signing secret env missing: {signature_env}")
    if provider == "viber":
        signature_env = str(setup.get("signatureEnv") or "SUPPORT_VIBER_AUTH_TOKEN").strip()
        signature_secret = _secret_value(signature_env, secrets)
        if signature_secret:
            headers["X-Viber-Content-Signature"] = hmac.new(signature_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            return headers, {
                "mode": "viber_content_signature",
                "env": signature_env,
                "header": "X-Viber-Content-Signature",
            }
        if setup.get("signatureRequired"):
            raise ValueError(f"Viber auth token env missing: {signature_env}")
    if setup.get("signatureRequired"):
        signature_env = str(setup.get("signatureEnv") or "").strip()
        signature_secret = _secret_value(signature_env, secrets)
        if not signature_secret:
            raise ValueError(f"Channel signing secret env missing: {signature_env}")
        hmac_headers = _smoke_hmac_headers(setup, signature_secret, raw_body)
        headers.update(hmac_headers)
        return headers, {
            "mode": "hmac_signature",
            "env": signature_env,
            "header": str(setup.get("signatureHeader") or "X-Support-Signature").strip() or "X-Support-Signature",
            "timestampHeader": str(setup.get("signatureTimestampHeader") or ""),
        }
    if provider == "telegram":
        secret_env = str(setup.get("providerSecretEnv") or "").strip()
        secret = _secret_value(secret_env, secrets) if secret_env else ""
        if secret:
            header = str(setup.get("providerSecretHeader") or "X-Telegram-Bot-Api-Secret-Token").strip()
            headers[header] = secret
            return headers, {"mode": "telegram_secret_token", "env": secret_env, "header": header}
    token_env, token = _smoke_token(setup, secrets)
    if not token:
        raise ValueError(f"Inbound webhook token env missing: {token_env}")
    token_header = str(setup.get("tokenHeader") or "X-Support-Sync-Token").strip() or "X-Support-Sync-Token"
    headers[token_header] = token
    return headers, {"mode": "token", "env": token_env, "header": token_header}


def _post_smoke_http(provider: str, setup: dict[str, Any], payload: dict[str, Any], secrets: dict[str, str] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    url = _smoke_url(provider, setup)
    if not url:
        raise ValueError("Inbound webhook URL is not available")
    if provider == "sms":
        raw_body = urlencode({str(key): str(value) for key, value in payload.items()}).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        auth_token_env = str(
            setup.get("twilioSignatureAuthTokenEnv")
            or setup.get("authTokenEnv")
            or "SUPPORT_TWILIO_AUTH_TOKEN"
        ).strip() or "SUPPORT_TWILIO_AUTH_TOKEN"
        auth_token = _secret_value(auth_token_env, secrets)
        if auth_token:
            header = str(setup.get("twilioSignatureHeader") or "X-Twilio-Signature").strip() or "X-Twilio-Signature"
            headers[header] = _smoke_twilio_signature(url, payload, auth_token)
            auth = {
                "mode": "twilio_signature",
                "env": auth_token_env,
                "header": header,
            }
        else:
            token_env, token = _smoke_token(setup, secrets)
            if not token:
                raise ValueError(f"Twilio auth token env missing: {auth_token_env}")
            token_header = str(setup.get("tokenHeader") or "X-Support-Sync-Token").strip() or "X-Support-Sync-Token"
            headers[token_header] = token
            auth = {"mode": "token", "env": token_env, "header": token_header}
    else:
        raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers, auth = _smoke_http_headers(provider, setup, secrets, raw_body)
    timeout = _smoke_http_timeout(provider)
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, content=raw_body, headers=headers)
    except httpx.TimeoutException as exc:
        raise SmokeHttpTimeoutError(
            f"Smoke endpoint timed out after {timeout:g} seconds"
        ) from exc
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    if response.status_code >= 400:
        raise ValueError(_http_response_error(response))
    try:
        result = response.json()
    except ValueError as exc:
        raise ValueError("Smoke endpoint returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("Smoke endpoint returned invalid result")
    return result, {
        "url": url,
        "statusCode": response.status_code,
        "auth": auth,
    }


@router.get("/projects/{pid}/channels/presets")
async def get_channel_presets(_ctx: ProjectViewerDep) -> dict[str, Any]:
    return {
        "items": [
            _channel_preset(channel_type)
            for channel_type in (
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
                "sms",
                "chat",
                "webhook",
            )
        ]
    }


@router.post("/projects/{pid}/channels/slack/install-url")
async def create_slack_install_url(
    body: SlackInstallUrlInput,
    ctx: ProjectEditorDep,
    request: Request,
) -> dict[str, Any]:
    _require_ctx_capability(ctx, "canManageProjectSecrets")
    runtime_secrets = load_runtime_secrets(ctx.tenant_id, ctx.project_id) or {}
    client_id, _client_secret = _slack_oauth_client_config(runtime_secrets)
    state_secret = _slack_oauth_state_secret(runtime_secrets)
    if not client_id or not state_secret:
        raise HTTPException(status_code=400, detail="Slack OAuth client ID and client secret/state secret are required")
    channel_key = body.channel_key.strip() or "slack-main"
    redirect_uri = _slack_oauth_redirect_uri(request, ctx.project_id)
    scopes = body.scopes.strip() or _default_slack_oauth_scopes(runtime_secrets)
    state = _sign_slack_oauth_state(
        {
            "tenantId": ctx.tenant_id or "",
            "projectId": ctx.project_id,
            "channelKey": channel_key,
            "name": body.name.strip() or "Slack",
            "redirectUri": redirect_uri,
            "issuedAt": datetime.now(timezone.utc).isoformat(),
            "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "nonce": uuid4().hex,
        },
        state_secret,
    )
    install_url = "https://slack.com/oauth/v2/authorize?" + urlencode({
        "client_id": client_id,
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
    })
    return {
        "installUrl": install_url,
        "redirectUri": redirect_uri,
        "scopes": scopes,
        "channelKey": channel_key,
        "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    }


@router.get("/projects/{pid}/channels/slack/oauth/callback")
async def slack_oauth_callback(
    pid: str,
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
) -> HTMLResponse:
    if error:
        return _slack_oauth_error_page("Slack install canceled", error)
    if not code or not state:
        return _slack_oauth_error_page("Slack install failed", "Missing OAuth code or state")
    try:
        unsigned_state = _unsigned_slack_oauth_state(state)
        project_id = str(unsigned_state.get("projectId") or "")
        tenant_id = str(unsigned_state.get("tenantId") or "").strip() or None
        if not project_id or project_id != pid:
            raise ValueError("Slack OAuth state does not match this project")
        runtime_secrets = load_runtime_secrets(tenant_id, project_id) or {}
        payload = _verify_slack_oauth_state(state, _slack_oauth_state_secret(runtime_secrets))
        client_id, client_secret = _slack_oauth_client_config(runtime_secrets)
        if not client_id or not client_secret:
            raise ValueError("Slack OAuth client ID and secret are required")
        redirect_uri = str(payload.get("redirectUri") or _slack_oauth_redirect_uri(request, project_id))
        install = _exchange_slack_oauth_code(
            code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
        channel = _store_slack_install(
            tenant_id=tenant_id,
            project_id=project_id,
            channel_key=str(payload.get("channelKey") or "slack-main"),
            name=str(payload.get("name") or "Slack"),
            install=install,
        )
    except ValueError as exc:
        return _slack_oauth_error_page("Slack install failed", str(exc))
    return _slack_oauth_success_page(
        str(channel.get("config", {}).get("workspaceName") or channel.get("name") or "Slack"),
        str(channel.get("channelKey") or "slack-main"),
    )


@router.post("/projects/{pid}/channels/{channel_id}/telegram/webhook")
async def configure_telegram_webhook(
    channel_id: str,
    body: TelegramWebhookInput,
    ctx: ProjectEditorDep,
    request: Request,
) -> dict[str, Any]:
    _require_ctx_capability(ctx, "canManageProjectSecrets")
    channel = get_channel(
        channel_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if str(channel.get("type") or "").strip().lower() != "telegram":
        raise HTTPException(status_code=400, detail="Channel is not a Telegram channel")
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    runtime_secrets = load_runtime_secrets(ctx.tenant_id, ctx.project_id) or {}
    setup = _channel_setup(channel, ctx, request)
    webhook_url = str(setup.get("providerWebhookUrl") or "").strip()
    bot_token_env = _telegram_bot_token_env(config)
    secret_token_env = _telegram_secret_token_env(config)
    bot_token = _secret_value(bot_token_env, runtime_secrets)
    secret_token = _secret_value(secret_token_env, runtime_secrets)
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Telegram provider webhook URL is not available")
    if not bot_token:
        raise HTTPException(status_code=400, detail=f"Telegram bot token env missing: {bot_token_env}")
    if not secret_token:
        raise HTTPException(status_code=400, detail=f"Telegram secret token env missing: {secret_token_env}")
    _validate_telegram_secret_token(secret_token)
    allowed_updates = [str(item).strip() for item in body.allowed_updates if str(item).strip()]
    payload: dict[str, Any] = {
        "url": webhook_url,
        "secret_token": secret_token,
        "drop_pending_updates": bool(body.drop_pending_updates),
    }
    if allowed_updates:
        payload["allowed_updates"] = allowed_updates
    try:
        with httpx.Client(timeout=12) as client:
            response = client.post(
                f"https://api.telegram.org/bot{bot_token}/setWebhook",
                json=payload,
            )
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=400, detail=_http_response_error(response))
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Telegram returned invalid JSON") from exc
    if not isinstance(data, dict) or data.get("ok") is not True:
        detail = data.get("description") or data.get("error") if isinstance(data, dict) else "Telegram setWebhook failed"
        raise HTTPException(status_code=400, detail=str(detail))
    return {
        "status": "configured",
        "webhookUrl": webhook_url,
        "botTokenEnv": bot_token_env,
        "secretTokenEnv": secret_token_env,
        "allowedUpdates": allowed_updates,
        "telegram": _telegram_webhook_response(data),
    }


@router.get("/projects/{pid}/channels")
async def get_channels(ctx: ProjectViewerDep, request: Request, limit: int = 100) -> dict[str, Any]:
    channels = list_channels(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=max(1, min(limit, 200)),
    )
    sync_runs = _safe_channel_sync_runs(ctx, limit=200)
    webhook_events = _safe_channel_webhook_events(ctx, limit=200)
    launch_proof_items = _safe_support_launch_items(ctx)
    return {
        "items": [
            _with_channel_setup(
                channel,
                ctx,
                request,
                sync_runs=sync_runs,
                launch_proof_items=launch_proof_items,
                webhook_events=webhook_events,
            )
            for channel in channels
        ]
    }


@router.get("/projects/{pid}/channels/activation-backlog")
async def get_channel_activation_backlog(ctx: ProjectViewerDep, request: Request, limit: int = 200) -> dict[str, Any]:
    channels = list_channels(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=max(1, min(limit, 200)),
    )
    sync_runs = _safe_channel_sync_runs(ctx, limit=200)
    webhook_events = _safe_channel_webhook_events(ctx, limit=200)
    launch_proof_items = _safe_support_launch_items(ctx)
    hydrated = [
        _with_channel_setup(
            channel,
            ctx,
            request,
            sync_runs=sync_runs,
            launch_proof_items=launch_proof_items,
            webhook_events=webhook_events,
        )
        for channel in channels
    ]
    return _channel_activation_backlog(project_id=ctx.project_id, channels=hydrated)


@router.get("/projects/{pid}/channels/activation-plan")
async def get_channel_activation_plan(ctx: ProjectViewerDep, request: Request, limit: int = 200) -> dict[str, Any]:
    channels = list_channels(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=max(1, min(limit, 200)),
    )
    sync_runs = _safe_channel_sync_runs(ctx, limit=200)
    webhook_events = _safe_channel_webhook_events(ctx, limit=200)
    launch_proof_items = _safe_support_launch_items(ctx)
    hydrated = [
        _with_channel_setup(
            channel,
            ctx,
            request,
            sync_runs=sync_runs,
            launch_proof_items=launch_proof_items,
            webhook_events=webhook_events,
        )
        for channel in channels
    ]
    backlog = _channel_activation_backlog(project_id=ctx.project_id, channels=hydrated)
    return _channel_activation_plan(project_id=ctx.project_id, backlog=backlog)


@router.post("/projects/{pid}/channels/activation-backlog/bootstrap")
async def bootstrap_channel_activation_backlog(
    body: ChannelActivationBootstrapInput,
    ctx: ProjectEditorDep,
    request: Request,
    auth: AuthDep,
) -> dict[str, Any]:
    return _bootstrap_channel_surface_setups(
        ctx=ctx,
        request=request,
        actor_email=auth.email,
        surfaces=body.surfaces,
        status=body.status,
    )


@router.post("/projects/{pid}/channels/activation-backlog/activate-ready")
async def activate_ready_channel_activation_backlog(
    body: ChannelActivationReadyInput,
    ctx: ProjectEditorDep,
    request: Request,
) -> dict[str, Any]:
    return _activate_ready_channel_surface_setups(
        ctx=ctx,
        request=request,
        surfaces=body.surfaces,
    )


@router.post("/projects/{pid}/channels")
async def save_channel(body: ChannelInput, ctx: ProjectEditorDep, request: Request) -> dict[str, Any]:
    try:
        channel = upsert_channel(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            channel_key=body.channel_key,
            channel_type=body.type,
            name=body.name,
            status=body.status,
            config=body.config,
        )
        sync_runs = _safe_channel_sync_runs(ctx, channel_id=str(channel.get("id") or ""), limit=50)
        webhook_events = _safe_channel_webhook_events(ctx, channel_id=str(channel.get("id") or ""), limit=50)
        return _with_channel_setup(
            channel,
            ctx,
            request,
            sync_runs=sync_runs,
            launch_proof_items=_safe_support_launch_items(ctx),
            webhook_events=webhook_events,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{pid}/channels/{channel_id}/validate")
async def validate_channel_setup(channel_id: str, ctx: ProjectEditorDep, request: Request) -> dict[str, Any]:
    channel = get_channel(
        channel_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    started_at = datetime.now(timezone.utc).isoformat()
    validation = _channel_setup_validation(channel, ctx, request)
    run_id = _record_validation_run(channel, ctx=ctx, validation=validation, started_at=started_at)
    if run_id:
        validation["runId"] = run_id
    return validation


@router.post("/projects/{pid}/channels/{channel_id}/sync")
async def sync_channel(channel_id: str, ctx: ProjectEditorDep, auth: AuthDep, limit: int = 25) -> dict[str, Any]:
    try:
        return sync_support_channel(
            channel_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
            payload=auth,
            limit=max(1, min(limit, 100)),
            source="admin",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post(
    "/projects/{pid}/channels/{channel_id}/test-message",
    status_code=status.HTTP_202_ACCEPTED,
)
async def test_channel_message(channel_id: str, body: ChannelTestMessageInput, ctx: ProjectEditorDep) -> dict[str, Any]:
    channel = get_channel(
        channel_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    channel_key = str(channel.get("channelKey") or "").strip()
    if not channel_key:
        raise HTTPException(status_code=400, detail="Channel key is required")
    text = body.body.strip()
    attachments = _smoke_attachments(body.attachments)
    if not text and not attachments:
        raise HTTPException(status_code=400, detail="Message body is required")
    channel_type = str(channel.get("type") or "webhook").strip() or "webhook"
    payload, _event_id, _message_id = _generic_test_message_payload(channel_key, channel_type, body)
    try:
        return enqueue_channel_test_message(
            channel=channel,
            payload=payload,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{pid}/channels/test-message-jobs/{job_id}")
async def channel_test_message_job(job_id: str, ctx: ProjectViewerDep) -> dict[str, Any]:
    result = get_channel_test_job_status(
        job_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Channel test message job not found")
    return result


def _run_channel_smoke(
    channel: dict[str, Any],
    *,
    body: ChannelTestMessageInput,
    ctx: ProjectEditorDep,
    request: Request,
) -> dict[str, Any]:
    channel_key = str(channel.get("channelKey") or "").strip()
    if not channel_key:
        raise ValueError("Channel key is required")
    channel_type = str(channel.get("type") or "webhook").strip() or "webhook"
    channel_config = _channel_config(channel)
    body = _test_message_with_channel_defaults(body, channel_type=channel_type.lower(), config=channel_config)
    attachments = _smoke_attachments(body.attachments)
    if not body.body.strip() and not attachments:
        raise ValueError("Message body is required")
    validation = _channel_setup_validation(channel, ctx, request)
    payload, provider, event_id, message_id = _provider_smoke_payload(channel_key, channel_type, body)
    transport = body.transport.strip().lower() or "direct"
    if transport not in {"direct", "http"}:
        raise ValueError("Smoke transport must be direct or http")
    http_result: dict[str, Any] | None = None
    if transport == "http":
        result, http_result = _post_smoke_http(
            provider,
            validation.get("setup") if isinstance(validation.get("setup"), dict) else {},
            payload,
            load_runtime_secrets(ctx.tenant_id, ctx.project_id) or {},
        )
    elif provider == "slack":
        result = ingest_slack_event(
            channel_key,
            payload=payload,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            source="admin-smoke",
        )
    elif provider == "teams":
        result = ingest_teams_event(
            channel_key,
            payload=payload,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            source="admin-smoke",
        )
    elif provider == "email":
        result = ingest_email_webhook(
            channel_key,
            payload=payload,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            source="admin-smoke",
        )
    else:
        result = ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            source=f"{provider}-admin-smoke",
        )
    items = _smoke_items(result)
    first_item = items[0] if items else {}
    issue_id = str(first_item.get("issueId") or result.get("issueId") or "")
    result_message_id = str(first_item.get("messageId") or result.get("messageId") or message_id)
    processed = _smoke_count(result, "processed", 1 if issue_id else 0)
    failed = _smoke_count(result, "failed")
    skipped = _smoke_count(result, "skipped", _smoke_count(result, "ignored"))
    smoke_result = {
        "channelId": channel.get("id", ""),
        "channelKey": channel_key,
        "type": channel_type,
        "provider": provider,
        "transport": transport,
        "ready": bool(validation.get("ready")),
        "validation": validation,
        "payload": payload,
        "smokeTarget": _inbound_smoke_target_proof(channel_type.lower(), body),
        "ingestion": result,
        "http": http_result or {},
        "eventId": event_id,
        "messageId": result_message_id,
        "issueId": issue_id,
        "attachmentCount": len(attachments),
        "fileOnly": bool(attachments and not body.body.strip()),
        "status": str(result.get("status") or "success"),
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "unmatched": _smoke_count(result, "unmatched"),
        "items": items,
    }
    if issue_id and processed and failed == 0:
        smoke_result["cleanup"] = _complete_smoke_issue(
            issue_id,
            ctx=ctx,
            workflow_source="admin-channel-smoke-cleanup",
        )
    smoke_result["remediation"] = _smoke_remediation(smoke_result, phase="inbound")
    return smoke_result


def _channel_config(channel: dict[str, Any]) -> dict[str, Any]:
    config = channel.get("config")
    return config if isinstance(config, dict) else {}


def _smoke_channel_ref(config: dict[str, Any], channel_type: str, explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip()
    if channel_type == "telegram":
        value = _config_text(config, "smokeChatId", "smoke_chat_id", "chatId", "chat_id", "smokeToAddress", "smoke_to_address")
        if value:
            return value
    return _config_text(
        config,
        "smokeChannelId",
        "smoke_channel_id",
        "channelId",
        "channel_id",
        "defaultChannelId",
        "default_channel_id",
    )


def _smoke_thread_ref(config: dict[str, Any], explicit: str = "") -> str:
    return explicit.strip() or _config_text(
        config,
        "smokeThreadTs",
        "smoke_thread_ts",
        "smokeThreadId",
        "smoke_thread_id",
        "threadTs",
        "thread_ts",
        "threadId",
        "thread_id",
    )


def _smoke_recipient_ref(config: dict[str, Any], channel_type: str, explicit: str = "") -> str:
    clean_type = channel_type.strip().lower()
    if clean_type == "telegram":
        return _smoke_channel_ref(config, clean_type, explicit)
    if clean_type == "whatsapp":
        return explicit.strip() or _config_text(
            config,
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
            "waId",
            "wa_id",
            "senderId",
            "sender_id",
            "chatId",
            "chat_id",
        )
    if clean_type in {"messenger", "facebook_messenger"}:
        return explicit.strip() or _config_text(
            config,
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
            "senderId",
            "sender_id",
            "psid",
            "chatId",
            "chat_id",
        )
    if clean_type == "instagram":
        return explicit.strip() or _config_text(
            config,
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
            "senderId",
            "sender_id",
            "igid",
            "chatId",
            "chat_id",
        )
    if clean_type in {"twitter", "x"}:
        return explicit.strip() or _config_text(
            config,
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
            "senderId",
            "sender_id",
            "twitterUserId",
            "twitter_user_id",
            "xUserId",
            "x_user_id",
            "chatId",
            "chat_id",
        )
    if clean_type in {"sms", "twilio"}:
        return explicit.strip() or _config_text(
            config,
            "smokeToAddress",
            "smoke_to_address",
            "smokeConversationId",
            "smoke_conversation_id",
        )
    return _smoke_thread_ref(config, explicit)


def _smoke_message_ref(config: dict[str, Any], explicit: str = "") -> str:
    return explicit.strip() or _config_text(
        config,
        "smokeProviderMessageId",
        "smoke_provider_message_id",
        "smokeMessageId",
        "smoke_message_id",
        "providerMessageId",
        "provider_message_id",
    )


def _smoke_event_ref(config: dict[str, Any], explicit: str = "") -> str:
    return explicit.strip() or _config_text(config, "smokeEventId", "smoke_event_id")


def _test_message_with_channel_defaults(
    body: ChannelTestMessageInput,
    *,
    channel_type: str,
    config: dict[str, Any],
) -> ChannelTestMessageInput:
    return ChannelTestMessageInput(
        body=body.body,
        author_name=body.author_name,
        author_email=body.author_email,
        author_id=body.author_id,
        provider=body.provider or channel_type,
        channel_id=_smoke_channel_ref(config, channel_type, body.channel_id),
        thread_id=_smoke_recipient_ref(config, channel_type, body.thread_id),
        message_id=_smoke_message_ref(config, body.message_id),
        event_id=_smoke_event_ref(config, body.event_id),
        transport=body.transport,
        attachments=body.attachments,
    )


def _inbound_smoke_target_proof(channel_type: str, body: ChannelTestMessageInput) -> dict[str, str]:
    proof: dict[str, str] = {}
    channel_ref = body.channel_id.strip()
    thread_ref = body.thread_id.strip()
    if channel_ref:
        proof["channelId"] = channel_ref
    if thread_ref:
        proof["threadId"] = thread_ref
    if channel_type == "slack" and thread_ref:
        proof["threadTs"] = thread_ref
    if channel_type == "teams":
        conversation_ref = thread_ref or channel_ref
        if conversation_ref:
            proof["conversationId"] = conversation_ref
    if channel_type == "telegram" and channel_ref:
        proof["chatId"] = channel_ref
    if channel_type == "whatsapp":
        recipient_ref = thread_ref or body.author_id.strip()
        if recipient_ref:
            proof["waId"] = recipient_ref
            proof["senderId"] = recipient_ref
            proof["recipient"] = recipient_ref
    if channel_type in {"messenger", "facebook_messenger"}:
        recipient_ref = thread_ref or body.author_id.strip()
        if recipient_ref:
            proof["psid"] = recipient_ref
            proof["senderId"] = recipient_ref
            proof["recipient"] = recipient_ref
    if channel_type == "instagram":
        recipient_ref = thread_ref or body.author_id.strip()
        if recipient_ref:
            proof["igid"] = recipient_ref
            proof["senderId"] = recipient_ref
            proof["recipient"] = recipient_ref
    if channel_type in {"twitter", "x"}:
        recipient_ref = thread_ref or body.author_id.strip()
        if recipient_ref:
            proof["twitterUserId"] = recipient_ref
            proof["senderId"] = recipient_ref
            proof["recipient"] = recipient_ref
    if channel_type in {"sms", "twilio"}:
        from_number = thread_ref or body.author_id.strip()
        if from_number and not from_number.startswith("+"):
            from_number = "+15551234567"
        if from_number:
            proof["phone"] = from_number
            proof["senderId"] = from_number
        if channel_ref:
            proof["toAddress"] = channel_ref
            proof["recipient"] = channel_ref
    return proof


def _outbound_message_with_channel_defaults(
    body: ChannelOutboundSmokeInput,
    *,
    channel_type: str,
    config: dict[str, Any],
) -> ChannelOutboundSmokeInput:
    channel_id = _smoke_channel_ref(config, channel_type, body.channel_id)
    return ChannelOutboundSmokeInput(
        body=body.body,
        to_address=body.to_address.strip() or _config_text(config, "smokeToAddress", "smoke_to_address") or channel_id,
        from_address=body.from_address,
        subject=body.subject,
        channel_id=channel_id,
        thread_id=_smoke_thread_ref(config, body.thread_id),
        message_id=body.message_id.strip() or _config_text(config, "smokeOutboundMessageId", "smoke_outbound_message_id"),
        provider_message_id=_smoke_message_ref(config, body.provider_message_id),
        event_id=_smoke_event_ref(config, body.event_id),
        conversation_id=body.conversation_id.strip()
        or _config_text(config, "smokeConversationId", "smoke_conversation_id", "conversationId", "conversation_id"),
        reply_to_id=body.reply_to_id.strip()
        or _config_text(config, "smokeReplyToId", "smoke_reply_to_id", "replyToId", "reply_to_id"),
        service_url=body.service_url.strip()
        or _config_text(config, "smokeServiceUrl", "smoke_service_url", "serviceUrl", "service_url"),
    )


def _lifecycle_message_with_channel_defaults(
    body: ChannelLifecycleSmokeInput,
    *,
    channel_type: str,
    config: dict[str, Any],
) -> ChannelLifecycleSmokeInput:
    return ChannelLifecycleSmokeInput(
        body=body.body,
        reply_body=body.reply_body,
        author_name=body.author_name,
        author_email=body.author_email,
        author_id=body.author_id,
        from_address=body.from_address,
        channel_id=_smoke_channel_ref(config, channel_type, body.channel_id),
        thread_id=_smoke_thread_ref(config, body.thread_id),
        message_id=_smoke_message_ref(config, body.message_id),
        event_id=_smoke_event_ref(config, body.event_id),
        transport=body.transport,
        attachments=body.attachments,
        reply_attachments=body.reply_attachments,
    )


def _outbound_smoke_metadata(
    *,
    channel_key: str,
    channel_type: str,
    body: ChannelOutboundSmokeInput,
    message_id: str,
) -> dict[str, Any]:
    channel_ref = body.channel_id.strip() or f"admin-smoke-{channel_key}"
    thread_ref = body.thread_id.strip()
    provider_message_id = body.provider_message_id.strip() or body.message_id.strip() or message_id
    event_id = body.event_id.strip() or message_id
    metadata: dict[str, Any] = {
        "source": "admin_outbound_smoke",
        "issueSource": channel_key,
        "channel": channel_type,
        "channelId": channel_ref,
        "eventId": event_id,
        "sourceMessageId": message_id,
        "providerMessageId": provider_message_id,
    }
    if thread_ref:
        metadata["threadId"] = thread_ref
    if channel_type == "slack":
        metadata["threadTs"] = thread_ref or provider_message_id
    if body.conversation_id.strip():
        metadata["conversationId"] = body.conversation_id.strip()
    if body.reply_to_id.strip():
        metadata["replyToId"] = body.reply_to_id.strip()
    if body.service_url.strip():
        metadata["serviceUrl"] = body.service_url.strip()
    return metadata


def _run_channel_outbound_smoke(
    channel: dict[str, Any],
    *,
    body: ChannelOutboundSmokeInput,
    ctx: ProjectEditorDep,
    request: Request,
) -> dict[str, Any]:
    channel_key = str(channel.get("channelKey") or "").strip()
    if not channel_key:
        raise ValueError("Channel key is required")
    channel_type = str(channel.get("type") or "webhook").strip().lower() or "webhook"
    if channel_type in {"email", "chat", "web_chat"}:
        raise ValueError("Outbound smoke uses external channel adapters")
    text = body.body.strip()
    if not text:
        raise ValueError("Reply body is required")
    validation = _channel_setup_validation(channel, ctx, request)
    channel_config = _channel_config(channel)
    body = _outbound_message_with_channel_defaults(body, channel_type=channel_type, config=channel_config)
    message_id = body.message_id.strip() or f"admin-outbound-smoke-{uuid4().hex}"
    metadata = _outbound_smoke_metadata(
        channel_key=channel_key,
        channel_type=channel_type,
        body=body,
        message_id=message_id,
    )
    result = send_support_channel_reply(
        message_id=message_id,
        channel=channel_type,
        channel_config=channel_config,
        to_address=body.to_address.strip() or metadata.get("channelId", ""),
        from_address=body.from_address.strip() or "support-agent@example.com",
        subject=body.subject.strip() or "Support reply smoke",
        body=text,
        metadata=metadata,
        secrets=load_runtime_secrets(ctx.tenant_id, ctx.project_id) or {},
    )
    delivery_metadata = result.metadata if isinstance(result.metadata, dict) else {}
    smoke_result = {
        "channelId": channel.get("id", ""),
        "channelKey": channel_key,
        "type": channel_type,
        "ready": bool(validation.get("ready")),
        "validation": validation,
        "messageId": message_id,
        "provider": result.provider,
        "providerMessageId": result.provider_message_id,
        "status": result.status,
        "sent": result.status == "sent",
        "deferred": result.status == "queued",
        "failed": result.status not in {"sent", "queued"},
        "processed": 1,
        "skipped": 0,
        "error": result.error,
        "retryAfterSeconds": result.retry_after_seconds,
        "metadata": metadata,
        "deliveryRoute": delivery_metadata.get("deliveryRoute", {}),
        "providerResponse": delivery_metadata.get("providerResponse", {}),
    }
    smoke_result["remediation"] = _smoke_remediation(smoke_result, phase="outbound")
    return smoke_result


def _lifecycle_test_message_body(body: ChannelLifecycleSmokeInput) -> ChannelTestMessageInput:
    return ChannelTestMessageInput(
        body=body.body,
        author_name=body.author_name,
        author_email=body.author_email,
        author_id=body.author_id,
        channel_id=body.channel_id,
        thread_id=body.thread_id,
        message_id=body.message_id,
        event_id=body.event_id,
        transport=body.transport,
        attachments=body.attachments,
    )


def _email_lifecycle_delivery_run(
    *,
    ctx: ProjectEditorDep,
    result: dict[str, Any],
    started_at: str,
) -> dict[str, Any]:
    try:
        return record_delivery_run(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            source="admin-email-lifecycle-smoke",
            result=result,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        result["deliveryRunRecordingError"] = str(exc)
        return {}


def _complete_smoke_issue(
    issue_id: str,
    *,
    ctx: ProjectEditorDep,
    workflow_source: str,
) -> dict[str, Any]:
    clean_issue_id = issue_id.strip()
    if not clean_issue_id:
        return {}
    try:
        updated = update_issue(
            clean_issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            updates={
                "status": "done",
                "workflow_source": workflow_source,
            },
        )
    except Exception as exc:
        return {
            "issueId": clean_issue_id,
            "status": "failed",
            "error": str(exc),
        }
    return {
        "issueId": clean_issue_id,
        "status": str(updated.get("status") or "done") if isinstance(updated, dict) else "done",
        "workflowSource": workflow_source,
    }


def _email_lifecycle_result(
    *,
    channel: dict[str, Any],
    validation: dict[str, Any],
    inbound: dict[str, Any],
    issue_id: str,
    reply_id: str = "",
    message_id: str = "",
    status: str = "failed",
    sent: bool = False,
    deferred: bool = False,
    error: str = "",
    approval: dict[str, Any] | None = None,
    delivery: dict[str, Any] | None = None,
    delivery_run: dict[str, Any] | None = None,
    attachment_count: int = 0,
    reply_attachment_count: int = 0,
) -> dict[str, Any]:
    failed = not sent and not deferred
    delivery = delivery if isinstance(delivery, dict) else {}
    delivery_metadata = delivery.get("metadata") if isinstance(delivery.get("metadata"), dict) else {}
    result = {
        "channelId": channel.get("id", ""),
        "channelKey": str(channel.get("channelKey") or ""),
        "type": "email",
        "ready": bool(validation.get("ready")),
        "validation": validation,
        "inbound": inbound,
        "issueId": issue_id,
        "replyId": reply_id,
        "messageId": message_id,
        "attachmentCount": attachment_count,
        "replyAttachmentCount": reply_attachment_count,
        "fileOnly": False,
        "provider": str(delivery.get("provider") or ""),
        "providerMessageId": str(delivery.get("providerMessageId") or delivery.get("provider_message_id") or ""),
        "status": status,
        "sent": sent,
        "deferred": deferred,
        "failed": failed,
        "processed": 1 if sent or deferred else 0,
        "skipped": int(inbound.get("skipped") or 0),
        "error": error,
        "approval": approval or {},
        "delivery": delivery,
        "deliveryRun": delivery_run or {},
        "deliveryRoute": delivery_metadata.get("deliveryRoute", {}),
        "providerResponse": delivery_metadata.get("providerResponse", {}),
    }
    result["remediation"] = _smoke_remediation(result, phase="lifecycle")
    return result


def _run_email_channel_lifecycle_smoke(
    channel: dict[str, Any],
    *,
    body: ChannelLifecycleSmokeInput,
    ctx: ProjectEditorDep,
    request: Request,
    actor_email: str,
) -> dict[str, Any]:
    channel_key = str(channel.get("channelKey") or "").strip()
    if not channel_key:
        raise ValueError("Channel key is required")
    attachments = _smoke_attachments(body.attachments)
    reply_attachments = _smoke_attachments(body.reply_attachments)
    if not body.body.strip() and not attachments:
        raise ValueError("Message body is required")
    if not body.reply_body.strip():
        raise ValueError("Reply body is required")

    validation = _channel_setup_validation(channel, ctx, request)
    setup = validation.get("setup") if isinstance(validation.get("setup"), dict) else {}
    if not bool(setup.get("authConfigured")):
        raise ValueError("Configure email inbound webhook token, fallback sync token, or HMAC signature before lifecycle proof")
    message_id = body.message_id.strip() or f"admin-email-lifecycle-{uuid4().hex}"
    subject = "Email lifecycle smoke"
    inbound = ingest_email_webhook(
        channel_key,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        actor_email=body.author_email.strip() or "launch-proof@example.com",
        source="admin-email-lifecycle-smoke",
        payload={
            "email": {
                "messageId": message_id,
                "threadId": body.thread_id.strip() or message_id,
                "subject": subject,
                "fromAddress": body.author_email.strip() or "launch-proof@example.com",
                "fromName": body.author_name.strip() or "Launch Proof",
                "body": body.body,
                "attachments": attachments,
            },
            "metadata": {
                "source": "admin_lifecycle_smoke",
                "channelKey": channel_key,
                "eventId": body.event_id.strip(),
            },
        },
    )
    items = inbound.get("items") if isinstance(inbound.get("items"), list) else []
    issue_id = ""
    result_message_id = message_id
    for item in items:
        if not isinstance(item, dict):
            continue
        issue_id = issue_id or str(item.get("issueId") or "").strip()
        result_message_id = str(item.get("messageId") or result_message_id)
    if not issue_id:
        return _email_lifecycle_result(
            channel=channel,
            validation=validation,
            inbound=inbound,
            issue_id="",
            message_id=result_message_id,
            status=str(inbound.get("status") or "failed"),
            error=str(inbound.get("error") or "Inbound email smoke did not create a ticket"),
            attachment_count=len(attachments),
            reply_attachment_count=len(reply_attachments),
        )

    reviewer_email = actor_email or body.from_address.strip() or "support-agent@example.com"
    reply = create_issue_reply(
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        author_email=body.from_address.strip() or reviewer_email,
        body=body.reply_body,
        status="queued",
        source="admin_lifecycle_smoke",
        metadata={
            "approvalRequired": True,
            "approved": False,
            "reviewStatus": "pending",
            "smoke": "email_lifecycle",
            "channelKey": channel_key,
        },
        attachments=reply_attachments,
    )
    if not reply:
        return _email_lifecycle_result(
            channel=channel,
            validation=validation,
            inbound=inbound,
            issue_id=issue_id,
            message_id=result_message_id,
            error="Could not create email smoke reply",
            attachment_count=len(attachments),
            reply_attachment_count=len(reply_attachments),
        )
    reply_id = str(reply.get("id") or "").strip()
    approved = approve_issue_reply(
        issue_id,
        reply_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        approved_by=reviewer_email,
    )
    if not approved:
        return _email_lifecycle_result(
            channel=channel,
            validation=validation,
            inbound=inbound,
            issue_id=issue_id,
            reply_id=reply_id,
            message_id=result_message_id,
            error="Could not approve email smoke reply",
            attachment_count=len(attachments),
            reply_attachment_count=len(reply_attachments),
        )

    delivery_started_at = datetime.now(timezone.utc).isoformat()
    delivered: dict[str, Any] | None = None
    delivery_error = ""
    try:
        delivered = deliver_issue_reply(
            issue_id,
            reply_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        )
    except ValueError as exc:
        delivery_error = str(exc)
    delivered = delivered if isinstance(delivered, dict) else {}
    status = str(delivered.get("status") or "failed")
    sent = status == "sent"
    deferred = status == "queued"
    error = "" if sent or deferred else delivery_error or str(delivered.get("error") or "Could not deliver email smoke reply")
    delivery_result = {
        "status": "success" if sent else "deferred" if deferred else "failed",
        "processed": 1,
        "sent": 1 if sent else 0,
        "failed": 0 if sent or deferred else 1,
        "blocked": 0,
        "deferred": 1 if deferred else 0,
        "retryFailed": False,
        "items": [delivered] if delivered else [],
        "error": error,
    }
    delivery_run = _email_lifecycle_delivery_run(
        ctx=ctx,
        result=delivery_result,
        started_at=delivery_started_at,
    )
    cleanup = (
        _complete_smoke_issue(
            issue_id,
            ctx=ctx,
            workflow_source="admin-email-lifecycle-smoke-cleanup",
        )
        if sent
        else {}
    )
    result = _email_lifecycle_result(
        channel=channel,
        validation=validation,
        inbound=inbound,
        issue_id=issue_id,
        reply_id=reply_id,
        message_id=result_message_id,
        status=status,
        sent=sent,
        deferred=deferred,
        error=error,
        approval=approved,
        delivery=delivered,
        delivery_run=delivery_run,
        attachment_count=len(attachments),
        reply_attachment_count=len(reply_attachments),
    )
    if cleanup:
        result["cleanup"] = cleanup
    return result


def _run_channel_lifecycle_smoke(
    channel: dict[str, Any],
    *,
    body: ChannelLifecycleSmokeInput,
    ctx: ProjectEditorDep,
    request: Request,
    actor_email: str,
) -> dict[str, Any]:
    channel_key = str(channel.get("channelKey") or "").strip()
    channel_type = str(channel.get("type") or "webhook").strip().lower() or "webhook"
    if not channel_key:
        raise ValueError("Channel key is required")
    if channel_type == "email":
        return _run_email_channel_lifecycle_smoke(
            channel,
            body=body,
            ctx=ctx,
            request=request,
            actor_email=actor_email,
        )
    if channel_type in {"chat", "web_chat"}:
        raise ValueError("Lifecycle smoke uses external channel adapters")
    channel_config = _channel_config(channel)
    body = _lifecycle_message_with_channel_defaults(body, channel_type=channel_type, config=channel_config)
    attachments = _smoke_attachments(body.attachments)
    reply_attachments = _smoke_attachments(body.reply_attachments)
    if not body.body.strip() and not attachments:
        raise ValueError("Message body is required")
    if not body.reply_body.strip():
        raise ValueError("Reply body is required")

    inbound = _run_channel_smoke(
        channel,
        body=_lifecycle_test_message_body(body),
        ctx=ctx,
        request=request,
    )
    issue_id = str(inbound.get("issueId") or "").strip()
    if not issue_id:
        inbound_items = inbound.get("items") if isinstance(inbound.get("items"), list) else []
        for item in inbound_items:
            if isinstance(item, dict) and str(item.get("issueId") or "").strip():
                issue_id = str(item.get("issueId") or "").strip()
                break
    base_result: dict[str, Any] = {
        "channelId": channel.get("id", ""),
        "channelKey": channel_key,
        "type": channel_type,
        "ready": bool(inbound.get("ready")),
        "validation": inbound.get("validation") if isinstance(inbound.get("validation"), dict) else {},
        "inbound": inbound,
        "issueId": issue_id,
        "replyId": "",
        "messageId": str(inbound.get("messageId") or body.message_id or ""),
        "attachmentCount": int(inbound.get("attachmentCount") or len(attachments)),
        "replyAttachmentCount": len(reply_attachments),
        "fileOnly": bool(attachments and not body.body.strip()),
        "provider": "",
        "providerMessageId": "",
        "status": "failed",
        "sent": False,
        "deferred": False,
        "failed": True,
        "processed": 0,
        "skipped": int(inbound.get("skipped") or 0),
        "error": "",
        "approval": {},
        "delivery": {},
    }
    if not issue_id:
        result = {
            **base_result,
            "error": "Inbound smoke did not create a ticket",
            "failed": True,
            "processed": int(inbound.get("processed") or 0),
        }
        result["remediation"] = _smoke_remediation(result, phase="lifecycle")
        return result

    reviewer_email = actor_email or body.from_address.strip() or "admin"
    reply = create_issue_reply(
        issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        author_email=body.from_address.strip() or reviewer_email,
        body=body.reply_body,
        status="queued",
        source="admin_lifecycle_smoke",
        metadata={
            "approvalRequired": True,
            "approved": False,
            "reviewStatus": "pending",
            "smoke": "lifecycle",
        },
        attachments=reply_attachments,
    )
    if not reply:
        result = {**base_result, "error": "Could not create smoke reply", "processed": int(inbound.get("processed") or 0)}
        result["remediation"] = _smoke_remediation(result, phase="lifecycle")
        return result
    reply_id = str(reply.get("id") or "").strip()
    approved = approve_issue_reply(
        issue_id,
        reply_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        approved_by=reviewer_email,
    )
    if not approved:
        result = {
            **base_result,
            "replyId": reply_id,
            "error": "Could not approve smoke reply",
            "processed": int(inbound.get("processed") or 0),
        }
        result["remediation"] = _smoke_remediation(result, phase="lifecycle")
        return result
    delivered = deliver_issue_reply(
        issue_id,
        reply_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if not delivered:
        result = {
            **base_result,
            "replyId": reply_id,
            "approval": approved,
            "error": "Could not deliver smoke reply",
            "processed": int(inbound.get("processed") or 0),
        }
        result["remediation"] = _smoke_remediation(result, phase="lifecycle")
        return result

    status = str(delivered.get("status") or "failed")
    sent = status == "sent"
    deferred = status == "queued"
    failed = status not in {"sent", "queued"}
    error = str(delivered.get("error") or "")
    delivery_metadata = delivered.get("metadata") if isinstance(delivered.get("metadata"), dict) else {}
    result = {
        **base_result,
        "replyId": reply_id,
        "provider": str(delivered.get("provider") or ""),
        "providerMessageId": str(delivered.get("providerMessageId") or ""),
        "status": status,
        "sent": sent,
        "deferred": deferred,
        "failed": failed,
        "processed": 1 if not failed else int(inbound.get("processed") or 0),
        "error": error,
        "approval": approved,
        "delivery": delivered,
        "deliveryRoute": delivery_metadata.get("deliveryRoute", {}),
        "providerResponse": delivery_metadata.get("providerResponse", {}),
    }
    if sent:
        result["cleanup"] = _complete_smoke_issue(
            issue_id,
            ctx=ctx,
            workflow_source="admin-channel-lifecycle-smoke-cleanup",
        )
    result["remediation"] = _smoke_remediation(result, phase="lifecycle")
    return result


def _record_smoke_run(
    channel_id: str,
    *,
    ctx: ProjectEditorDep,
    result: dict[str, Any],
    started_at: str,
    completed_at: str,
    source: str = "admin-smoke-run",
) -> str:
    if not channel_id:
        return ""
    try:
        run = record_channel_sync_run(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            channel_id=channel_id,
            source=source,
            result=result,
            started_at=started_at,
            completed_at=completed_at,
        )
    except Exception as exc:
        result["recordingError"] = str(exc)
        return ""
    return str(run.get("id") or "")


@router.post("/projects/{pid}/channels/{channel_id}/smoke")
async def smoke_channel(channel_id: str, body: ChannelTestMessageInput, ctx: ProjectEditorDep, request: Request) -> dict[str, Any]:
    channel = get_channel(
        channel_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = await asyncio.to_thread(_run_channel_smoke, channel, body=body, ctx=ctx, request=request)
    except SmokeHttpTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run_id = _record_smoke_run(
        channel_id,
        ctx=ctx,
        result=result,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc).isoformat(),
        source="admin-smoke",
    )
    if run_id:
        result["runId"] = run_id
    return result


@router.post("/projects/{pid}/channels/{channel_id}/outbound-smoke")
async def smoke_channel_outbound(
    channel_id: str,
    body: ChannelOutboundSmokeInput,
    ctx: ProjectEditorDep,
    request: Request,
) -> dict[str, Any]:
    channel = get_channel(
        channel_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = await asyncio.to_thread(_run_channel_outbound_smoke, channel, body=body, ctx=ctx, request=request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run_id = _record_smoke_run(
        channel_id,
        ctx=ctx,
        result=result,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc).isoformat(),
        source="admin-outbound-smoke",
    )
    if run_id:
        result["runId"] = run_id
    return result


@router.post("/projects/{pid}/channels/{channel_id}/lifecycle-smoke")
async def smoke_channel_lifecycle(
    channel_id: str,
    body: ChannelLifecycleSmokeInput,
    ctx: ProjectEditorDep,
    request: Request,
    auth: AuthDep,
) -> dict[str, Any]:
    channel = get_channel(
        channel_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = await asyncio.to_thread(
            _run_channel_lifecycle_smoke,
            channel,
            body=body,
            ctx=ctx,
            request=request,
            actor_email=auth.email,
        )
    except SmokeHttpTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run_id = _record_smoke_run(
        channel_id,
        ctx=ctx,
        result=result,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc).isoformat(),
        source="admin-lifecycle-smoke",
    )
    if run_id:
        result["runId"] = run_id
    return result


@router.post("/projects/{pid}/channels/lifecycle-smoke/run")
async def smoke_channels_lifecycle(
    body: ChannelLifecycleSmokeInput,
    ctx: ProjectEditorDep,
    request: Request,
    auth: AuthDep,
    limit: int = 25,
) -> dict[str, Any]:
    channels = list_channels(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    active_channels = [
        channel for channel in channels
        if str(channel.get("status") or "active").strip().lower() == "active"
        and str(channel.get("type") or "").strip().lower() not in {"email", "chat", "web_chat"}
    ][:max(1, min(limit, 100))]
    items: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for channel in active_channels:
        channel_id = str(channel.get("id") or "")
        channel_key = str(channel.get("channelKey") or "")
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = await asyncio.to_thread(
                _run_channel_lifecycle_smoke,
                channel,
                body=body,
                ctx=ctx,
                request=request,
                actor_email=auth.email,
            )
            run_id = _record_smoke_run(
                channel_id,
                ctx=ctx,
                result=result,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                source="admin-lifecycle-smoke",
            )
            if run_id:
                result["runId"] = run_id
            items.append(result)
        except ValueError as exc:
            failure_result = {
                "channelId": channel_id,
                "channelKey": channel_key,
                "type": str(channel.get("type") or ""),
                "ready": False,
                "status": "failed",
                "sent": False,
                "deferred": False,
                "failed": True,
                "processed": 0,
                "skipped": 0,
                "error": str(exc),
            }
            run_id = _record_smoke_run(
                channel_id,
                ctx=ctx,
                result=failure_result,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                source="admin-lifecycle-smoke",
            )
            failure = {
                "channelId": channel_id,
                "channelKey": channel_key,
                "error": str(exc),
            }
            if run_id:
                failure["runId"] = run_id
            if failure_result.get("recordingError"):
                failure["recordingError"] = str(failure_result.get("recordingError") or "")
            failures.append(failure)
    sent = sum(1 for item in items if bool(item.get("sent")))
    deferred = sum(1 for item in items if bool(item.get("deferred")))
    failed = sum(1 for item in items if bool(item.get("failed"))) + len(failures)
    processed = sum(_smoke_count(item, "processed", 1) for item in items) + len(failures)
    ready = sum(
        1 for item in items
        if bool(item.get("ready")) and bool(item.get("sent")) and not bool(item.get("failed"))
    )
    status = "idle"
    if active_channels:
        status = "failed" if failed and not sent and not deferred else "partial" if failed or deferred else "success"
    return {
        "status": status,
        "channels": len(active_channels),
        "ready": ready,
        "processed": processed,
        "sent": sent,
        "deferred": deferred,
        "failed": failed,
        "skipped": 0,
        "items": items,
        "failures": failures,
    }


@router.post("/projects/{pid}/channels/outbound-smoke/run")
async def smoke_channels_outbound(
    body: ChannelOutboundSmokeInput,
    ctx: ProjectEditorDep,
    request: Request,
    limit: int = 25,
) -> dict[str, Any]:
    channels = list_channels(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    active_channels = [
        channel for channel in channels
        if str(channel.get("status") or "active").strip().lower() == "active"
        and str(channel.get("type") or "").strip().lower() not in {"email", "chat", "web_chat"}
    ][:max(1, min(limit, 100))]
    items: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for channel in active_channels:
        channel_id = str(channel.get("id") or "")
        channel_key = str(channel.get("channelKey") or "")
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = await asyncio.to_thread(_run_channel_outbound_smoke, channel, body=body, ctx=ctx, request=request)
            run_id = _record_smoke_run(
                channel_id,
                ctx=ctx,
                result=result,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                source="admin-outbound-smoke",
            )
            if run_id:
                result["runId"] = run_id
            items.append(result)
        except ValueError as exc:
            failure_result = {
                "channelId": channel_id,
                "channelKey": channel_key,
                "type": str(channel.get("type") or ""),
                "ready": False,
                "status": "failed",
                "sent": False,
                "deferred": False,
                "failed": True,
                "processed": 1,
                "skipped": 0,
                "error": str(exc),
            }
            run_id = _record_smoke_run(
                channel_id,
                ctx=ctx,
                result=failure_result,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                source="admin-outbound-smoke",
            )
            failure = {
                "channelId": channel_id,
                "channelKey": channel_key,
                "error": str(exc),
            }
            if run_id:
                failure["runId"] = run_id
            if failure_result.get("recordingError"):
                failure["recordingError"] = str(failure_result.get("recordingError") or "")
            failures.append(failure)
    sent = sum(1 for item in items if bool(item.get("sent")))
    deferred = sum(1 for item in items if bool(item.get("deferred")))
    failed = sum(1 for item in items if bool(item.get("failed"))) + len(failures)
    processed = sum(_smoke_count(item, "processed", 1) for item in items) + len(failures)
    ready = sum(
        1 for item in items
        if bool(item.get("ready")) and bool(item.get("sent")) and not bool(item.get("failed"))
    )
    status = "idle"
    if active_channels:
        status = "failed" if failed and not sent and not deferred else "partial" if failed or deferred else "success"
    return {
        "status": status,
        "channels": len(active_channels),
        "ready": ready,
        "processed": processed,
        "sent": sent,
        "deferred": deferred,
        "failed": failed,
        "skipped": 0,
        "items": items,
        "failures": failures,
    }


@router.post("/projects/{pid}/channels/smoke/run")
async def smoke_channels(body: ChannelTestMessageInput, ctx: ProjectEditorDep, request: Request, limit: int = 25) -> dict[str, Any]:
    channels = list_channels(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    active_channels = [
        channel for channel in channels
        if str(channel.get("status") or "active").strip().lower() == "active"
        and str(channel.get("type") or "").strip().lower() not in {"email", "chat", "web_chat"}
    ][:max(1, min(limit, 100))]
    items: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for channel in active_channels:
        channel_id = str(channel.get("id") or "")
        channel_key = str(channel.get("channelKey") or "")
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = await asyncio.to_thread(_run_channel_smoke, channel, body=body, ctx=ctx, request=request)
            run_id = _record_smoke_run(
                channel_id,
                ctx=ctx,
                result=result,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            if run_id:
                result["runId"] = run_id
            items.append(result)
        except ValueError as exc:
            failure_result = {
                "channelId": channel_id,
                "channelKey": channel_key,
                "type": str(channel.get("type") or ""),
                "provider": str(channel.get("type") or ""),
                "transport": body.transport.strip().lower() or "direct",
                "ready": False,
                "status": "failed",
                "processed": 0,
                "failed": 1,
                "skipped": 0,
                "error": str(exc),
                "items": [],
            }
            run_id = _record_smoke_run(
                channel_id,
                ctx=ctx,
                result=failure_result,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            failure = {
                "channelId": channel_id,
                "channelKey": channel_key,
                "error": str(exc),
            }
            if run_id:
                failure["runId"] = run_id
            if failure_result.get("recordingError"):
                failure["recordingError"] = str(failure_result.get("recordingError") or "")
            failures.append(failure)
    processed = sum(_smoke_count(item, "processed") for item in items)
    failed = sum(_smoke_count(item, "failed") for item in items) + len(failures)
    skipped = sum(_smoke_count(item, "skipped") for item in items)
    ready = sum(
        1 for item in items
        if bool(item.get("ready")) and _smoke_count(item, "failed") == 0 and _smoke_count(item, "processed") > 0
    )
    status = "idle"
    if active_channels:
        status = "failed" if failed and not processed else "partial" if failed else "success"
    return {
        "status": status,
        "transport": body.transport.strip().lower() or "direct",
        "channels": len(active_channels),
        "ready": ready,
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "items": items,
        "failures": failures,
    }


@router.post("/projects/{pid}/channels/sync/run")
async def sync_channels(ctx: ProjectEditorDep, auth: AuthDep, limit: int = 25) -> dict[str, Any]:
    return sync_support_channels(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        actor_email=auth.email,
        payload=auth,
        limit=max(1, min(limit, 100)),
        source="admin",
    )


@router.get("/projects/{pid}/channels/sync/runs")
async def get_channel_sync_runs(ctx: ProjectViewerDep, channel_id: str = "", limit: int = 50) -> dict[str, Any]:
    return {
        "items": list_channel_sync_runs(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            channel_id=channel_id,
            limit=max(1, min(limit, 200)),
        )
    }


@router.get("/projects/{pid}/channels/cursors")
async def get_channel_cursors(ctx: ProjectViewerDep, channel_id: str = "", limit: int = 100) -> dict[str, Any]:
    return {
        "items": list_channel_cursors(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            channel_id=channel_id,
            limit=max(1, min(limit, 200)),
        )
    }


@router.get("/projects/{pid}/channels/webhook-events")
async def get_channel_webhook_events(
    ctx: ProjectViewerDep,
    channel_id: str = "",
    status: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    return {
        "items": list_channel_webhook_events(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            channel_id=channel_id,
            status=status,
            limit=max(1, min(limit, 200)),
        )
    }


@router.post("/projects/{pid}/channels/webhook-events/{event_id}/rematch")
async def rematch_channel_webhook_event_endpoint(
    event_id: str,
    body: ChannelWebhookRematchInput,
    ctx: ProjectEditorDep,
) -> dict[str, Any]:
    event = rematch_channel_webhook_event(
        event_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        outbound_message_id=body.outbound_message_id.strip(),
    )
    if not event:
        raise HTTPException(status_code=404, detail="Channel webhook event not found")
    return event


@router.get("/projects/{pid}/channels/web-chat/sessions")
async def get_web_chat_sessions(
    ctx: ProjectViewerDep,
    channel_id: str = "",
    status: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    return {
        "items": list_web_chat_sessions(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            channel_id=channel_id,
            status=status,
            limit=max(1, min(limit, 200)),
        )
    }


@router.get("/projects/{pid}/crm/connectors")
async def get_crm_connectors(ctx: ProjectViewerDep, limit: int = 100) -> dict[str, Any]:
    return {
        "items": list_crm_connectors(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            limit=max(1, min(limit, 200)),
        )
    }


@router.post("/projects/{pid}/crm/connectors")
async def save_crm_connector(body: CrmConnectorInput, ctx: ProjectEditorDep) -> dict[str, Any]:
    try:
        return upsert_crm_connector(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            connector_key=body.connector_key,
            provider=body.provider,
            name=body.name,
            status=body.status,
            config=body.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{pid}/crm/connectors/{connector_id}/validate")
async def validate_crm_connector_setup(connector_id: str, ctx: ProjectEditorDep) -> dict[str, Any]:
    try:
        return validate_crm_connector(
            connector_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/projects/{pid}/crm/connectors/{connector_id}/sync")
async def sync_crm_connector(connector_id: str, ctx: ProjectEditorDep, limit: int = 25) -> dict[str, Any]:
    try:
        return sync_support_crm_connector(
            connector_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            limit=max(1, min(limit, 100)),
            source="admin",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/projects/{pid}/crm/connectors/sync/run")
async def sync_crm_connectors(ctx: ProjectEditorDep, limit: int = 25) -> dict[str, Any]:
    return sync_support_crm_connectors(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=max(1, min(limit, 100)),
        source="admin",
    )


@router.get("/projects/{pid}/crm/connectors/sync/runs")
async def get_crm_sync_runs(ctx: ProjectViewerDep, connector_id: str = "", limit: int = 50) -> dict[str, Any]:
    return {
        "items": list_crm_sync_runs(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            connector_id=connector_id,
            limit=max(1, min(limit, 200)),
        )
    }


@router.get("/projects/{pid}/crm/connectors/webhook-events")
async def get_crm_webhook_events(
    ctx: ProjectViewerDep,
    connector_id: str = "",
    status: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    return {
        "items": list_crm_webhook_events(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            connector_id=connector_id,
            status=status,
            limit=max(1, min(limit, 200)),
        )
    }
