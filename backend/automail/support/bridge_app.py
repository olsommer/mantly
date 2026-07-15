"""Small deployable support bridge sidecar.

Run with:
    uvicorn automail.support.bridge_app:app --host 0.0.0.0 --port 8095
"""

from __future__ import annotations

import hmac
import os
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from automail.support.bridge import BridgeForwardError, forward_bridge_event, forward_bridge_validation

BRIDGE_PROVIDER_ALIASES = {
    "facebook-messenger": "messenger",
    "instagram-dm": "instagram",
    "line-messaging": "line",
    "line-messaging-api": "line",
    "viber-bot": "viber",
    "x": "twitter",
    "x-dm": "twitter",
    "generic": "channel-webhooks",
    "webhook": "channel-webhooks",
}

SUPPORTED_BRIDGE_PROVIDERS = {
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
    "twilio",
    "channel-webhooks",
}

META_VALIDATION_PROVIDERS = {"whatsapp", "messenger", "instagram"}
JSON_VALIDATION_PROVIDERS = {"twitter"}


def _request_token(request: Request) -> str:
    header = request.headers.get("x-support-bridge-token", "").strip()
    if header:
        return header
    auth = request.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _require_inbound_token(request: Request) -> None:
    expected = os.getenv("SUPPORT_BRIDGE_INBOUND_TOKEN", "").strip()
    if expected and not hmac.compare_digest(_request_token(request), expected):
        raise HTTPException(status_code=401, detail="Invalid support bridge token")


def _bridge_provider(provider: str) -> str:
    clean = provider.strip().lower().replace("_", "-")
    canonical = BRIDGE_PROVIDER_ALIASES.get(clean, clean)
    if canonical not in SUPPORTED_BRIDGE_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unsupported support bridge provider")
    return canonical


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    return body


def _forward(provider: str, channel_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return forward_bridge_event(provider=provider, channel_key=channel_key, payload=payload)
    except BridgeForwardError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _forward_validation(provider: str, channel_key: str, query_params: dict[str, str]) -> str:
    try:
        result = forward_bridge_validation(
            provider=provider,
            channel_key=channel_key,
            query_params=query_params,
        )
    except BridgeForwardError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return str(result.get("text") or "")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Mantly Support Bridge",
        description="Forward external channel events into the support inbox.",
        version="1.0.0",
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/bridge/teams/{channel_key}")
    async def validate_teams(channel_key: str, validation_token: str | None = Query(default=None, alias="validationToken")) -> PlainTextResponse:
        del channel_key
        if not validation_token:
            raise HTTPException(status_code=404, detail="Teams validation token is required")
        return PlainTextResponse(validation_token)

    @app.get("/bridge/{provider}/{channel_key}")
    async def validate_provider(provider: str, channel_key: str, request: Request):
        canonical_provider = _bridge_provider(provider)
        if canonical_provider not in META_VALIDATION_PROVIDERS and canonical_provider not in JSON_VALIDATION_PROVIDERS:
            raise HTTPException(status_code=404, detail="Provider does not support bridge validation")
        if canonical_provider in JSON_VALIDATION_PROVIDERS:
            try:
                result = forward_bridge_validation(
                    provider=canonical_provider,
                    channel_key=channel_key,
                    query_params=dict(request.query_params),
                )
            except BridgeForwardError as exc:
                raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
            payload = result.get("json")
            if isinstance(payload, dict):
                return JSONResponse(payload)
            return JSONResponse({"response_token": str(result.get("text") or "")})
        return PlainTextResponse(_forward_validation(canonical_provider, channel_key, dict(request.query_params)))

    @app.post("/bridge/teams/{channel_key}")
    async def receive_teams(channel_key: str, request: Request) -> dict[str, Any]:
        _require_inbound_token(request)
        return _forward("teams", channel_key, await _json_body(request))

    @app.post("/bridge/discord/{channel_key}")
    async def receive_discord(channel_key: str, request: Request) -> dict[str, Any]:
        _require_inbound_token(request)
        return _forward("discord", channel_key, await _json_body(request))

    @app.post("/bridge/{provider}/{channel_key}")
    async def receive_provider(provider: str, channel_key: str, request: Request) -> dict[str, Any]:
        _require_inbound_token(request)
        return _forward(_bridge_provider(provider), channel_key, await _json_body(request))

    return app


app = create_app()


def main() -> None:
    host = os.getenv("SUPPORT_BRIDGE_HOST", "0.0.0.0")
    port = int(os.getenv("SUPPORT_BRIDGE_PORT", "8095"))
    uvicorn.run("automail.support.bridge_app:app", host=host, port=port)


if __name__ == "__main__":
    main()
