"""Internal support automation endpoints."""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from automail.core.runtime_secrets import load_runtime_secrets
from automail.db.pocketbase.client import (
    get_channel_by_key,
    ingest_channel_webhook,
    ingest_slack_event,
    ingest_teams_event,
)
from automail.models import CamelCaseModel
from automail.support.crm import ingest_crm_webhook
from automail.support.ingestion import ingest_email_webhook
from automail.support.scheduler import (
    run_scheduled_support_crm_sync,
    run_scheduled_support_delivery,
    run_scheduled_support_sla_escalations,
    run_scheduled_support_sync,
)

router = APIRouter()

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

PROVIDER_SIGNATURE_DEFAULT_HEADERS: dict[str, str] = {
    "whatsapp": "X-Hub-Signature-256",
    "messenger": "X-Hub-Signature-256",
    "facebook_messenger": "X-Hub-Signature-256",
    "instagram": "X-Hub-Signature-256",
    "twitter": "x-twitter-webhooks-signature",
    "x": "x-twitter-webhooks-signature",
    "line": "X-Line-Signature",
    "viber": "X-Viber-Content-Signature",
}


class SupportSyncRequest(CamelCaseModel):
    tenant_id: str | None = None
    project_id: str | None = None
    limit: int = 25
    retry_failed: bool = False


def _request_token(request: Request) -> str:
    header = request.headers.get("x-support-sync-token", "").strip()
    if header:
        return header
    auth = request.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _secret_value(secret_name: str, *, tenant_id: str | None = None, project_id: str | None = None) -> str:
    clean_name = secret_name.strip()
    if not clean_name:
        return ""
    secrets = load_runtime_secrets(tenant_id, project_id) or {}
    value = secrets.get(clean_name)
    if value:
        return str(value).strip()
    return os.getenv(clean_name, "").strip()


def _require_support_token(
    request: Request,
    env_name: str,
    fallback_env_name: str = "SUPPORT_SYNC_TOKEN",
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> None:
    expected = (
        _secret_value(env_name, tenant_id=tenant_id, project_id=project_id)
        or _secret_value(fallback_env_name, tenant_id=tenant_id, project_id=project_id)
    )
    if not expected:
        raise HTTPException(status_code=404, detail="Support automation endpoint is disabled")
    if not hmac.compare_digest(_request_token(request), expected):
        raise HTTPException(status_code=401, detail="Invalid support automation token")


def _slack_signature_secret(
    channel: dict[str, Any] | None,
    *,
    tenant_id: str | None,
    project_id: str | None,
) -> tuple[str, str]:
    config = channel.get("config") if isinstance(channel, dict) else None
    if isinstance(config, dict):
        env_name = str(
            config.get("slackSigningSecretEnv")
            or config.get("slack_signing_secret_env")
            or config.get("signatureSecretEnv")
            or config.get("webhookSignatureSecretEnv")
            or config.get("signature_secret_env")
            or ""
        ).strip()
        if env_name:
            return _secret_value(env_name, tenant_id=tenant_id, project_id=project_id), env_name
    return (
        _secret_value("SUPPORT_SLACK_SIGNING_SECRET", tenant_id=tenant_id, project_id=project_id),
        "SUPPORT_SLACK_SIGNING_SECRET",
    )


def _verify_slack_signature(request: Request, raw_body: bytes, secret: str) -> None:
    timestamp = request.headers.get("x-slack-request-timestamp", "").strip()
    signature = request.headers.get("x-slack-signature", "").strip()
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing Slack signature")
    try:
        request_time = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Slack timestamp") from exc
    if abs(time.time() - request_time) > 60 * 5:
        raise HTTPException(status_code=401, detail="Stale Slack request")
    base = f"v0:{timestamp}:".encode("utf-8") + raw_body
    expected = "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")


def _require_slack_request(
    channel_key: str,
    request: Request,
    raw_body: bytes,
    *,
    tenant_id: str | None,
    project_id: str | None,
) -> None:
    try:
        channel = get_channel_by_key(channel_key, tenant_id=tenant_id, project_id=project_id)
    except Exception:
        channel = None
    secret, env_name = _slack_signature_secret(channel, tenant_id=tenant_id, project_id=project_id)
    signature_required = bool(
        channel
        and isinstance(channel.get("config"), dict)
        and (
            channel["config"].get("slackSigningSecretEnv")
            or channel["config"].get("slack_signing_secret_env")
            or channel["config"].get("signatureSecretEnv")
            or channel["config"].get("webhookSignatureSecretEnv")
            or channel["config"].get("signature_secret_env")
        )
    )
    if secret:
        _verify_slack_signature(request, raw_body, secret)
        return
    if signature_required:
        raise HTTPException(status_code=404, detail=f"Slack signing secret env is not configured: {env_name}")
    token_env = _channel_token_env(channel, "SUPPORT_SLACK_WEBHOOK_TOKEN")
    _require_support_token(
        request,
        token_env,
        tenant_id=tenant_id,
        project_id=project_id,
    )


def _body_scope(body: Any, tenant_id: str | None, project_id: str | None) -> tuple[str | None, str | None, Any]:
    scoped_tenant_id = tenant_id
    scoped_project_id = project_id
    payload: Any = body
    if isinstance(body, dict):
        scoped_tenant_id = scoped_tenant_id or str(body.get("tenantId") or body.get("tenant_id") or "").strip() or None
        scoped_project_id = scoped_project_id or str(body.get("projectId") or body.get("project_id") or "").strip() or None
        if "payload" in body:
            payload = body["payload"]
    return scoped_tenant_id, scoped_project_id, payload


def _channel_signature_config(channel: dict[str, Any] | None, *, provider: str = "") -> tuple[str, str]:
    config = channel.get("config") if isinstance(channel, dict) else None
    if not isinstance(config, dict):
        return "", ""
    provider_key = provider.strip().lower()
    env_name = ""
    for key in (
        *PROVIDER_SIGNATURE_SECRET_CONFIG_KEYS.get(provider_key, ()),
        "signatureSecretEnv",
        "webhookSignatureSecretEnv",
        "signature_secret_env",
    ):
        env_name = str(config.get(key) or "").strip()
        if env_name:
            break
    default_header = PROVIDER_SIGNATURE_DEFAULT_HEADERS.get(provider_key, "X-Support-Signature")
    header_name = str(config.get("signatureHeader") or config.get("signature_header") or default_header).strip()
    return env_name, header_name or "X-Support-Signature"


def _whatsapp_verify_token_env(channel: dict[str, Any] | None) -> str:
    config = channel.get("config") if isinstance(channel, dict) and isinstance(channel.get("config"), dict) else {}
    return str(
        config.get("whatsappVerifyTokenEnv")
        or config.get("whatsapp_verify_token_env")
        or config.get("verifyTokenEnv")
        or config.get("verify_token_env")
        or "SUPPORT_WHATSAPP_VERIFY_TOKEN"
    ).strip() or "SUPPORT_WHATSAPP_VERIFY_TOKEN"


def _messenger_verify_token_env(channel: dict[str, Any] | None) -> str:
    config = channel.get("config") if isinstance(channel, dict) and isinstance(channel.get("config"), dict) else {}
    return str(
        config.get("messengerVerifyTokenEnv")
        or config.get("messenger_verify_token_env")
        or config.get("verifyTokenEnv")
        or config.get("verify_token_env")
        or "SUPPORT_MESSENGER_VERIFY_TOKEN"
    ).strip() or "SUPPORT_MESSENGER_VERIFY_TOKEN"


def _instagram_verify_token_env(channel: dict[str, Any] | None) -> str:
    config = channel.get("config") if isinstance(channel, dict) and isinstance(channel.get("config"), dict) else {}
    return str(
        config.get("instagramVerifyTokenEnv")
        or config.get("instagram_verify_token_env")
        or config.get("verifyTokenEnv")
        or config.get("verify_token_env")
        or "SUPPORT_INSTAGRAM_VERIFY_TOKEN"
    ).strip() or "SUPPORT_INSTAGRAM_VERIFY_TOKEN"


def _twitter_consumer_secret_env(channel: dict[str, Any] | None) -> str:
    config = channel.get("config") if isinstance(channel, dict) and isinstance(channel.get("config"), dict) else {}
    return str(
        config.get("twitterConsumerSecretEnv")
        or config.get("twitter_consumer_secret_env")
        or config.get("xConsumerSecretEnv")
        or config.get("x_consumer_secret_env")
        or config.get("consumerSecretEnv")
        or config.get("consumer_secret_env")
        or "SUPPORT_X_CONSUMER_SECRET"
    ).strip() or "SUPPORT_X_CONSUMER_SECRET"


def _config_bool(config: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = config.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _config_int(config: dict[str, Any], *keys: str, default: int) -> int:
    for key in keys:
        value = config.get(key)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return default


def _channel_signature_replay_config(channel: dict[str, Any] | None) -> tuple[bool, str, int]:
    config = channel.get("config") if isinstance(channel, dict) else None
    if not isinstance(config, dict):
        return False, "X-Support-Signature-Timestamp", 300
    required = _config_bool(
        config,
        "signatureTimestampRequired",
        "signature_timestamp_required",
        "signatureReplayProtection",
        "signature_replay_protection",
    )
    header_name = str(
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
    return required, header_name, tolerance


def _channel_token_env(channel: dict[str, Any] | None, default_env: str) -> str:
    config = channel.get("config") if isinstance(channel, dict) else None
    if isinstance(config, dict):
        env_name = str(
            config.get("webhookTokenEnv")
            or config.get("webhook_token_env")
            or config.get("emailWebhookTokenEnv")
            or config.get("email_webhook_token_env")
            or config.get("providerTokenEnv")
            or config.get("provider_token_env")
            or ""
        ).strip()
        if env_name:
            return env_name
    return default_env


def _channel_outbound_token_env(channel: dict[str, Any] | None) -> str:
    config = channel.get("config") if isinstance(channel, dict) else None
    if isinstance(config, dict):
        env_name = str(
            config.get("outboundWebhookTokenEnv")
            or config.get("outbound_webhook_token_env")
            or ""
        ).strip()
        if env_name:
            return env_name
    return "SUPPORT_WEBHOOK_OUTBOUND_TOKEN"


def _twilio_auth_token_env(channel: dict[str, Any] | None) -> str:
    config = channel.get("config") if isinstance(channel, dict) else None
    if isinstance(config, dict):
        env_name = str(
            config.get("twilioAuthTokenEnv")
            or config.get("twilio_auth_token_env")
            or config.get("authTokenEnv")
            or config.get("auth_token_env")
            or ""
        ).strip()
        if env_name:
            return env_name
    return "SUPPORT_TWILIO_AUTH_TOKEN"


def _twilio_signature_url(request: Request, channel: dict[str, Any] | None) -> str:
    config = channel.get("config") if isinstance(channel, dict) else None
    if isinstance(config, dict):
        override = str(
            config.get("twilioSignatureUrl")
            or config.get("twilio_signature_url")
            or config.get("twilioWebhookUrl")
            or config.get("twilio_webhook_url")
            or ""
        ).strip()
        if override:
            return override
    return str(request.url)


def _signature_hex(value: str) -> str:
    clean = value.strip()
    if "," in clean:
        clean = clean.split(",", 1)[0].strip()
    for prefix in ("sha256=", "v1=", "hmac-sha256="):
        if clean.lower().startswith(prefix):
            return clean[len(prefix):].strip()
    return clean


def _verify_channel_hmac_signature(
    request: Request,
    raw_body: bytes,
    *,
    secret: str,
    signature_header: str,
    channel: dict[str, Any] | None,
) -> None:
    signature = request.headers.get(signature_header, "").strip()
    if not signature:
        raise HTTPException(status_code=401, detail="Missing channel webhook signature")
    timestamp_required, timestamp_header, tolerance_seconds = _channel_signature_replay_config(channel)
    timestamp = request.headers.get(timestamp_header, "").strip()
    if timestamp_required and not timestamp:
        raise HTTPException(status_code=401, detail="Missing channel webhook signature timestamp")
    if timestamp:
        try:
            request_time = int(timestamp)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid channel webhook signature timestamp") from exc
        if abs(time.time() - request_time) > tolerance_seconds:
            raise HTTPException(status_code=401, detail="Stale channel webhook signature timestamp")
        signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
    else:
        signed_payload = raw_body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).digest()
    expected_hex = digest.hex()
    expected_base64 = base64.b64encode(digest).decode("ascii")
    provided = _signature_hex(signature)
    if hmac.compare_digest(expected_hex, provided) or hmac.compare_digest(expected_base64, provided):
        return
    raise HTTPException(status_code=401, detail="Invalid channel webhook signature")


def _require_channel_webhook_request(
    channel_key: str,
    request: Request,
    raw_body: bytes,
    *,
    tenant_id: str | None,
    project_id: str | None,
) -> None:
    try:
        channel = get_channel_by_key(channel_key, tenant_id=tenant_id, project_id=project_id)
    except Exception:
        channel = None
    env_name, header_name = _channel_signature_config(channel)
    if not env_name:
        token_env = _channel_token_env(channel, "SUPPORT_CHANNEL_WEBHOOK_TOKEN")
        _require_support_token(
            request,
            token_env,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        return
    secret = _secret_value(env_name, tenant_id=tenant_id, project_id=project_id)
    if not secret:
        raise HTTPException(status_code=404, detail="Channel webhook signature secret is not configured")
    _verify_channel_hmac_signature(
        request,
        raw_body,
        secret=secret,
        signature_header=header_name,
        channel=channel,
    )


def _verify_twilio_signature(
    request: Request,
    *,
    channel: dict[str, Any] | None,
    form_params: dict[str, str],
    tenant_id: str | None,
    project_id: str | None,
) -> bool:
    signature = request.headers.get("x-twilio-signature", "").strip()
    if not signature:
        return False
    auth_token_env = _twilio_auth_token_env(channel)
    auth_token = _secret_value(auth_token_env, tenant_id=tenant_id, project_id=project_id)
    if not auth_token:
        raise HTTPException(status_code=404, detail=f"Twilio auth token env is not configured: {auth_token_env}")
    signature_url = _twilio_signature_url(request, channel)
    signed = signature_url + "".join(
        f"{key}{value}"
        for key, value in sorted(form_params.items())
    )
    expected = base64.b64encode(
        hmac.new(auth_token.encode("utf-8"), signed.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid Twilio signature")
    return True


def _require_provider_channel_request(
    channel_key: str,
    request: Request,
    raw_body: bytes,
    *,
    tenant_id: str | None,
    project_id: str | None,
    provider_token_env: str,
    provider: str = "",
) -> None:
    try:
        channel = get_channel_by_key(channel_key, tenant_id=tenant_id, project_id=project_id)
    except Exception:
        channel = None
    form_params = getattr(request.state, "support_form_params", None)
    if provider.strip().lower() in {"sms", "twilio"} and isinstance(form_params, dict):
        if _verify_twilio_signature(
            request,
            channel=channel,
            form_params=form_params,
            tenant_id=tenant_id,
            project_id=project_id,
        ):
            return
    env_name, header_name = _channel_signature_config(channel, provider=provider)
    if not env_name:
        token_env = _channel_token_env(channel, provider_token_env)
        _require_support_token(
            request,
            token_env,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        return
    secret = _secret_value(env_name, tenant_id=tenant_id, project_id=project_id)
    if not secret:
        raise HTTPException(status_code=404, detail="Channel webhook signature secret is not configured")
    _verify_channel_hmac_signature(
        request,
        raw_body,
        secret=secret,
        signature_header=header_name,
        channel=channel,
    )


def _load_channel_for_provider(
    channel_key: str,
    *,
    tenant_id: str | None,
    project_id: str | None,
) -> dict[str, Any] | None:
    try:
        return get_channel_by_key(channel_key, tenant_id=tenant_id, project_id=project_id)
    except Exception:
        return None


def _require_telegram_request(
    channel_key: str,
    request: Request,
    raw_body: bytes,
    *,
    tenant_id: str | None,
    project_id: str | None,
) -> None:
    try:
        channel = get_channel_by_key(channel_key, tenant_id=tenant_id, project_id=project_id)
    except Exception:
        channel = None
    config = channel.get("config") if isinstance(channel, dict) and isinstance(channel.get("config"), dict) else {}
    env_name, header_name = _channel_signature_config(channel, provider="telegram")
    if env_name:
        secret = _secret_value(env_name, tenant_id=tenant_id, project_id=project_id)
        if not secret:
            raise HTTPException(status_code=404, detail="Channel webhook signature secret is not configured")
        _verify_channel_hmac_signature(
            request,
            raw_body,
            secret=secret,
            signature_header=header_name,
            channel=channel,
        )
        return
    secret_env = str(
        config.get("telegramSecretTokenEnv")
        or config.get("telegram_secret_token_env")
        or config.get("secretTokenEnv")
        or config.get("secret_token_env")
        or "SUPPORT_TELEGRAM_SECRET_TOKEN"
    ).strip() or "SUPPORT_TELEGRAM_SECRET_TOKEN"
    expected = _secret_value(secret_env, tenant_id=tenant_id, project_id=project_id)
    if expected:
        actual = request.headers.get("x-telegram-bot-api-secret-token", "").strip()
        if not hmac.compare_digest(actual, expected):
            raise HTTPException(status_code=401, detail="Invalid Telegram secret token")
        return
    _require_provider_channel_request(
        channel_key,
        request,
        raw_body,
        tenant_id=tenant_id,
        project_id=project_id,
        provider_token_env="SUPPORT_TELEGRAM_WEBHOOK_TOKEN",
        provider="telegram",
    )


@router.post("/support/sync")
async def run_support_sync(body: SupportSyncRequest, request: Request) -> dict[str, Any]:
    _require_support_token(request, "SUPPORT_SYNC_TOKEN")
    return run_scheduled_support_sync(
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        limit=max(1, min(body.limit, 100)),
        source="cron",
    )


@router.post("/support/delivery")
async def run_support_delivery(body: SupportSyncRequest, request: Request) -> dict[str, Any]:
    _require_support_token(request, "SUPPORT_DELIVERY_TOKEN")
    return run_scheduled_support_delivery(
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        limit=max(1, min(body.limit, 100)),
        source="cron",
        retry_failed=body.retry_failed,
    )


@router.post("/support/crm-sync")
async def run_support_crm_sync(body: SupportSyncRequest, request: Request) -> dict[str, Any]:
    _require_support_token(request, "SUPPORT_CRM_SYNC_TOKEN")
    return run_scheduled_support_crm_sync(
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        limit=max(1, min(body.limit, 100)),
        source="cron",
    )


@router.post("/support/sla")
async def run_support_sla_escalations(body: SupportSyncRequest, request: Request) -> dict[str, Any]:
    _require_support_token(request, "SUPPORT_SLA_TOKEN")
    if not body.project_id:
        raise HTTPException(status_code=400, detail="projectId is required")
    return run_scheduled_support_sla_escalations(
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        limit=max(1, min(body.limit, 200)),
        source="cron",
    )


@router.post("/support/crm-webhooks/{connector_key}")
async def receive_support_crm_webhook(
    connector_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    _require_support_token(request, "SUPPORT_CRM_WEBHOOK_TOKEN")
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id = tenant_id
    scoped_project_id = project_id
    payload: Any = body
    if isinstance(body, dict):
        scoped_tenant_id = scoped_tenant_id or str(body.get("tenantId") or body.get("tenant_id") or "").strip() or None
        scoped_project_id = scoped_project_id or str(body.get("projectId") or body.get("project_id") or "").strip() or None
        if "payload" in body:
            payload = body["payload"]
    try:
        return ingest_crm_webhook(
            connector_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/support/email/{channel_key}")
async def receive_support_email_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    if not scoped_project_id:
        raise HTTPException(status_code=400, detail="projectId is required")
    # Channel lookup and the full email pipeline use synchronous HTTP/LLM clients.
    # Keep both outside the ASGI event loop so unrelated requests remain responsive.
    await run_in_threadpool(
        _require_provider_channel_request,
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
        provider_token_env="SUPPORT_EMAIL_WEBHOOK_TOKEN",
        provider="email",
    )
    actor_email = "email-webhook"
    if isinstance(body, dict):
        actor_email = str(body.get("actorEmail") or body.get("actor_email") or body.get("creator") or actor_email).strip()
    try:
        return await run_in_threadpool(
            ingest_email_webhook,
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            actor_email=actor_email,
            source="email-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/support/slack/{channel_key}")
async def receive_support_slack_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_slack_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
    )
    if isinstance(body, dict) and body.get("type") == "url_verification" and body.get("challenge"):
        return {"challenge": str(body["challenge"])}
    try:
        return ingest_slack_event(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="slack-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.get("/support/teams/{channel_key}")
async def verify_support_teams_event(
    channel_key: str,
    validation_token: str | None = Query(default=None, alias="validationToken"),
) -> PlainTextResponse:
    del channel_key
    if not validation_token:
        raise HTTPException(status_code=404, detail="Teams validation token is required")
    return PlainTextResponse(validation_token)


@router.post("/support/teams/{channel_key}")
async def receive_support_teams_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_provider_channel_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
        provider_token_env="SUPPORT_TEAMS_WEBHOOK_TOKEN",
        provider="teams",
    )
    if isinstance(body, dict) and body.get("challenge"):
        return {"challenge": str(body["challenge"])}
    try:
        return ingest_teams_event(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="teams-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/support/discord/{channel_key}")
async def receive_support_discord_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_provider_channel_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
        provider_token_env="SUPPORT_DISCORD_WEBHOOK_TOKEN",
        provider="discord",
    )
    try:
        return ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="discord-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/support/telegram/{channel_key}")
async def receive_support_telegram_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_telegram_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
    )
    try:
        return ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="telegram-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/support/line/{channel_key}")
async def receive_support_line_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_provider_channel_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
        provider_token_env="SUPPORT_LINE_WEBHOOK_TOKEN",
        provider="line",
    )
    try:
        return ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="line-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/support/viber/{channel_key}")
async def receive_support_viber_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_provider_channel_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
        provider_token_env="SUPPORT_VIBER_WEBHOOK_TOKEN",
        provider="viber",
    )
    try:
        return ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="viber-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.get("/support/whatsapp/{channel_key}")
async def verify_support_whatsapp_event(
    channel_key: str,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> PlainTextResponse:
    channel = _load_channel_for_provider(channel_key, tenant_id=tenant_id, project_id=project_id)
    verify_token_env = _whatsapp_verify_token_env(channel)
    expected = _secret_value(verify_token_env, tenant_id=tenant_id, project_id=project_id)
    if not expected:
        raise HTTPException(status_code=404, detail=f"WhatsApp verify token env is not configured: {verify_token_env}")
    if hub_mode != "subscribe" or not hmac.compare_digest(hub_verify_token or "", expected):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp verify token")
    if not hub_challenge:
        raise HTTPException(status_code=400, detail="WhatsApp challenge is required")
    return PlainTextResponse(hub_challenge)


@router.post("/support/whatsapp/{channel_key}")
async def receive_support_whatsapp_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_provider_channel_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
        provider_token_env="SUPPORT_WHATSAPP_WEBHOOK_TOKEN",
        provider="whatsapp",
    )
    try:
        return ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="whatsapp-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.get("/support/messenger/{channel_key}")
async def verify_support_messenger_event(
    channel_key: str,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> PlainTextResponse:
    channel = _load_channel_for_provider(channel_key, tenant_id=tenant_id, project_id=project_id)
    verify_token_env = _messenger_verify_token_env(channel)
    expected = _secret_value(verify_token_env, tenant_id=tenant_id, project_id=project_id)
    if not expected:
        raise HTTPException(status_code=404, detail=f"Messenger verify token env is not configured: {verify_token_env}")
    if hub_mode != "subscribe" or not hmac.compare_digest(hub_verify_token or "", expected):
        raise HTTPException(status_code=401, detail="Invalid Messenger verify token")
    if not hub_challenge:
        raise HTTPException(status_code=400, detail="Messenger challenge is required")
    return PlainTextResponse(hub_challenge)


@router.post("/support/messenger/{channel_key}")
async def receive_support_messenger_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_provider_channel_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
        provider_token_env="SUPPORT_MESSENGER_WEBHOOK_TOKEN",
        provider="messenger",
    )
    try:
        return ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="messenger-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.get("/support/instagram/{channel_key}")
async def verify_support_instagram_event(
    channel_key: str,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> PlainTextResponse:
    channel = _load_channel_for_provider(channel_key, tenant_id=tenant_id, project_id=project_id)
    verify_token_env = _instagram_verify_token_env(channel)
    expected = _secret_value(verify_token_env, tenant_id=tenant_id, project_id=project_id)
    if not expected:
        raise HTTPException(status_code=404, detail=f"Instagram verify token env is not configured: {verify_token_env}")
    if hub_mode != "subscribe" or not hmac.compare_digest(hub_verify_token or "", expected):
        raise HTTPException(status_code=401, detail="Invalid Instagram verify token")
    if not hub_challenge:
        raise HTTPException(status_code=400, detail="Instagram challenge is required")
    return PlainTextResponse(hub_challenge)


@router.post("/support/instagram/{channel_key}")
async def receive_support_instagram_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_provider_channel_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
        provider_token_env="SUPPORT_INSTAGRAM_WEBHOOK_TOKEN",
        provider="instagram",
    )
    try:
        return ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="instagram-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.get("/support/twitter/{channel_key}")
@router.get("/support/x/{channel_key}")
async def verify_support_twitter_event(
    channel_key: str,
    crc_token: str | None = Query(default=None),
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> JSONResponse:
    if not crc_token:
        raise HTTPException(status_code=400, detail="X crc_token is required")
    channel = _load_channel_for_provider(channel_key, tenant_id=tenant_id, project_id=project_id)
    secret_env = _twitter_consumer_secret_env(channel)
    secret = _secret_value(secret_env, tenant_id=tenant_id, project_id=project_id)
    if not secret:
        raise HTTPException(status_code=404, detail=f"X consumer secret env is not configured: {secret_env}")
    digest = hmac.new(secret.encode("utf-8"), crc_token.encode("utf-8"), hashlib.sha256).digest()
    return JSONResponse({"response_token": "sha256=" + base64.b64encode(digest).decode("ascii")})


@router.post("/support/twitter/{channel_key}")
@router.post("/support/x/{channel_key}")
async def receive_support_twitter_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_provider_channel_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
        provider_token_env="SUPPORT_X_WEBHOOK_TOKEN",
        provider="twitter",
    )
    try:
        return ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="twitter-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/support/sms/{channel_key}")
@router.post("/support/twilio/{channel_key}")
async def receive_support_twilio_event(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            body = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    else:
        try:
            form = await request.form()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid form body") from exc
        body = {str(key): str(value) for key, value in form.items()}
        request.state.support_form_params = body
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_provider_channel_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
        provider_token_env="SUPPORT_TWILIO_WEBHOOK_TOKEN",
        provider="sms",
    )
    try:
        return ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="twilio-webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/support/channel-webhooks/{channel_key}/outbound-echo")
async def receive_support_channel_webhook_outbound_echo(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be an object")
    channel = _load_channel_for_provider(
        channel_key,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    _require_support_token(
        request,
        _channel_outbound_token_env(channel),
        fallback_env_name="SUPPORT_CHANNEL_WEBHOOK_TOKEN",
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
    )
    message_id = str(
        payload.get("messageId")
        or payload.get("message_id")
        or payload.get("outboundMessageId")
        or payload.get("outbound_message_id")
        or ""
    ).strip()
    if not message_id:
        raise HTTPException(status_code=400, detail="messageId is required")
    channel_type = str(channel.get("type") or "webhook").strip().lower() or "webhook"
    return {
        "status": "accepted",
        "provider": f"{channel_type}_echo",
        "channelKey": str(channel.get("channelKey") or channel_key),
        "messageId": message_id,
        "outboundMessageId": message_id,
        "providerMessageId": f"{channel_type}:{message_id}",
    }


@router.post("/support/channel-webhooks/{channel_key}")
async def receive_support_channel_webhook(
    channel_key: str,
    request: Request,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    scoped_tenant_id, scoped_project_id, payload = _body_scope(body, tenant_id, project_id)
    _require_channel_webhook_request(
        channel_key,
        request,
        raw_body,
        tenant_id=scoped_tenant_id,
        project_id=scoped_project_id,
    )
    try:
        return ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=scoped_tenant_id,
            project_id=scoped_project_id,
            source="webhook",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc
