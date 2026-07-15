"""Shared forwarding helpers for deployable support channel bridges."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

DEFAULT_TOKEN_ENVS = {
    "slack": "SUPPORT_SLACK_WEBHOOK_TOKEN",
    "teams": "SUPPORT_TEAMS_WEBHOOK_TOKEN",
    "discord": "SUPPORT_DISCORD_WEBHOOK_TOKEN",
    "telegram": "SUPPORT_TELEGRAM_WEBHOOK_TOKEN",
    "line": "SUPPORT_LINE_WEBHOOK_TOKEN",
    "line-messaging": "SUPPORT_LINE_WEBHOOK_TOKEN",
    "line-messaging-api": "SUPPORT_LINE_WEBHOOK_TOKEN",
    "viber": "SUPPORT_VIBER_WEBHOOK_TOKEN",
    "viber-bot": "SUPPORT_VIBER_WEBHOOK_TOKEN",
    "whatsapp": "SUPPORT_WHATSAPP_WEBHOOK_TOKEN",
    "messenger": "SUPPORT_MESSENGER_WEBHOOK_TOKEN",
    "facebook-messenger": "SUPPORT_MESSENGER_WEBHOOK_TOKEN",
    "instagram": "SUPPORT_INSTAGRAM_WEBHOOK_TOKEN",
    "twitter": "SUPPORT_X_WEBHOOK_TOKEN",
    "x": "SUPPORT_X_WEBHOOK_TOKEN",
    "sms": "SUPPORT_TWILIO_WEBHOOK_TOKEN",
    "twilio": "SUPPORT_TWILIO_WEBHOOK_TOKEN",
    "channel-webhooks": "SUPPORT_CHANNEL_WEBHOOK_TOKEN",
    "webhook": "SUPPORT_CHANNEL_WEBHOOK_TOKEN",
    "generic": "SUPPORT_CHANNEL_WEBHOOK_TOKEN",
}

CORE_PROVIDER_ALIASES = {
    "facebook-messenger": "messenger",
    "instagram-dm": "instagram",
    "line-messaging": "line",
    "line-messaging-api": "line",
    "viber-bot": "viber",
    "x": "twitter",
    "x-dm": "twitter",
    "webhook": "channel-webhooks",
    "generic": "channel-webhooks",
}


@dataclass(frozen=True)
class BridgeForwardSettings:
    core_url: str
    project_id: str = ""
    tenant_id: str = ""
    token: str = ""
    token_header: str = "X-Support-Sync-Token"
    signature_secret: str = ""
    signature_header: str = "X-Support-Signature"
    signature_timestamp_header: str = "X-Support-Signature-Timestamp"
    timeout_seconds: float = 15


class BridgeForwardError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def _env_value(name: str) -> str:
    return os.getenv(name, "").strip()


def _env_secret(name: str) -> str:
    clean = name.strip()
    return _env_value(clean) if clean else ""


def _provider_key(provider: str) -> str:
    return provider.strip().lower().replace("_", "-")


def _core_provider_key(provider: str) -> str:
    clean = _provider_key(provider)
    return CORE_PROVIDER_ALIASES.get(clean, clean)


def _token_env(provider: str) -> str:
    override = _env_value("SUPPORT_BRIDGE_TOKEN_ENV")
    if override:
        return override
    return DEFAULT_TOKEN_ENVS.get(_provider_key(provider), "SUPPORT_CHANNEL_WEBHOOK_TOKEN")


def _signature_secret() -> str:
    secret = _env_value("SUPPORT_BRIDGE_SIGNATURE_SECRET")
    if secret:
        return secret
    return _env_secret(_env_value("SUPPORT_BRIDGE_SIGNATURE_SECRET_ENV"))


def bridge_settings_from_env(provider: str) -> BridgeForwardSettings:
    token = _env_value("SUPPORT_BRIDGE_TOKEN") or _env_secret(_token_env(provider))
    return BridgeForwardSettings(
        core_url=_env_value("SUPPORT_BRIDGE_CORE_URL") or "http://localhost:8080",
        project_id=_env_value("SUPPORT_BRIDGE_PROJECT_ID"),
        tenant_id=_env_value("SUPPORT_BRIDGE_TENANT_ID"),
        token=token,
        token_header=_env_value("SUPPORT_BRIDGE_TOKEN_HEADER") or "X-Support-Sync-Token",
        signature_secret=_signature_secret(),
        signature_header=_env_value("SUPPORT_BRIDGE_SIGNATURE_HEADER") or "X-Support-Signature",
        signature_timestamp_header=_env_value("SUPPORT_BRIDGE_SIGNATURE_TIMESTAMP_HEADER")
        or "X-Support-Signature-Timestamp",
        timeout_seconds=float(_env_value("SUPPORT_BRIDGE_TIMEOUT_SECONDS") or "15"),
    )


def _core_event_url(
    settings: BridgeForwardSettings,
    provider: str,
    channel_key: str,
    *,
    extra_query: Mapping[str, Any] | None = None,
) -> str:
    base = settings.core_url.rstrip("/")
    clean_provider = _core_provider_key(provider)
    clean_channel_key = channel_key.strip().strip("/")
    if not clean_channel_key:
        raise BridgeForwardError("channel_key is required", status_code=400)
    query: dict[str, str] = {}
    for key, value in (extra_query or {}).items():
        clean_key = str(key).strip()
        clean_value = str(value).strip() if value is not None else ""
        if clean_key and clean_value:
            query[clean_key] = clean_value
    if settings.project_id:
        query["project_id"] = settings.project_id
    if settings.tenant_id:
        query["tenant_id"] = settings.tenant_id
    query_string = urlencode(query)
    url = f"{base}/api/internal/support/{clean_provider}/{clean_channel_key}"
    return f"{url}?{query_string}" if query_string else url


def _bridge_body(settings: BridgeForwardSettings, payload: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {"payload": payload}
    if settings.project_id:
        body["projectId"] = settings.project_id
    if settings.tenant_id:
        body["tenantId"] = settings.tenant_id
    return body


def _json_bytes(body: dict[str, Any]) -> bytes:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _headers(settings: BridgeForwardSettings, raw_body: bytes) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.token:
        headers[settings.token_header] = settings.token
    if settings.signature_secret:
        timestamp = str(int(time.time()))
        signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
        digest = hmac.new(settings.signature_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        headers[settings.signature_header] = f"sha256={digest}"
        headers[settings.signature_timestamp_header] = timestamp
    return headers


def _http_error(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        data = response.text
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("message") or data.get("error")
        if detail:
            return f"Core support endpoint returned HTTP {response.status_code}: {detail}"
    if isinstance(data, str) and data.strip():
        return f"Core support endpoint returned HTTP {response.status_code}: {data.strip()[:240]}"
    return f"Core support endpoint returned HTTP {response.status_code}"


def forward_bridge_event(
    *,
    provider: str,
    channel_key: str,
    payload: dict[str, Any],
    settings: BridgeForwardSettings | None = None,
) -> dict[str, Any]:
    config = settings or bridge_settings_from_env(provider)
    body = _bridge_body(config, payload)
    raw_body = _json_bytes(body)
    url = _core_event_url(config, provider, channel_key)
    headers = _headers(config, raw_body)

    try:
        with httpx.Client(timeout=config.timeout_seconds) as client:
            response = client.post(url, content=raw_body, headers=headers)
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        raise BridgeForwardError(str(exc)) from exc

    if response.status_code >= 400:
        raise BridgeForwardError(_http_error(response), status_code=502)
    try:
        core_result: Any = response.json()
    except ValueError:
        core_result = {"text": response.text}
    return {
        "status": "forwarded",
        "provider": _core_provider_key(provider),
        "channelKey": channel_key,
        "core": core_result,
    }


def forward_bridge_validation(
    *,
    provider: str,
    channel_key: str,
    query_params: Mapping[str, Any],
    settings: BridgeForwardSettings | None = None,
) -> dict[str, Any]:
    config = settings or bridge_settings_from_env(provider)
    url = _core_event_url(config, provider, channel_key, extra_query=query_params)

    try:
        with httpx.Client(timeout=config.timeout_seconds) as client:
            response = client.get(url, headers={"Accept": "text/plain, application/json"})
    except Exception as exc:  # pragma: no cover - network path is monkeypatched in tests
        raise BridgeForwardError(str(exc)) from exc

    if response.status_code >= 400:
        raise BridgeForwardError(_http_error(response), status_code=response.status_code)
    result: dict[str, Any] = {
        "status": "validated",
        "provider": _core_provider_key(provider),
        "channelKey": channel_key,
        "text": response.text,
    }
    try:
        json_body = response.json()
        if json_body:
            result["json"] = json_body
    except ValueError:
        pass
    return result
