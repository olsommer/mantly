"""Admin action webhook proxy endpoint."""

import ipaddress
import os
import re
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from automail.api.admin.deps import ProjectEditorDep
from automail.core.auth import get_token_payload
from automail.core.rate_limit import limiter
from automail.monitoring import record_action_run

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────

# Private/reserved IP ranges that must never be reachable via the webhook proxy.
_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 ULA
]


def _validate_webhook_url(url: str) -> None:
    """Raise HTTPException if the URL targets a private/internal address."""
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Webhook URL must use http or https")

    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="Webhook URL has no hostname")

    allowed_hosts_raw = os.getenv("ALLOWED_WEBHOOK_HOSTS", "")
    if allowed_hosts_raw:
        allowed = {h.strip().lower() for h in allowed_hosts_raw.split(",") if h.strip()}
        if host.lower() not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Webhook host '{host}' is not in ALLOWED_WEBHOOK_HOSTS",
            )
        return

    try:
        resolved = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"Cannot resolve webhook host: {exc}")

    for _family, _type, _proto, _canonname, sockaddr in resolved:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        for private_range in _PRIVATE_RANGES:
            if ip in private_range:
                raise HTTPException(
                    status_code=400,
                    detail=f"Webhook URL resolves to a private/internal address ({ip_str}) — not allowed",
                )


class ActionTriggerRequest(BaseModel):
    webhook: str
    method: str = "POST"
    payload: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)


def _resolve_action_mapping(value: Any, runtime_values: dict[str, Any], secrets: dict[str, str] | None) -> Any:
    """Resolve action query/body placeholders from runtime payload first, then secrets."""
    if isinstance(value, str):
        exact = re.fullmatch(r"\{([^}]+)\}", value)
        if exact and exact.group(1) in runtime_values:
            return runtime_values[exact.group(1)]

        def replace(match: re.Match) -> str:
            key = match.group(1)
            if key in runtime_values:
                return str(runtime_values[key])
            if secrets and key in secrets:
                return str(secrets[key])
            return match.group(0)

        return re.sub(r"\{([^}]+)\}", replace, value)
    if isinstance(value, dict):
        return {key: _resolve_action_mapping(item, runtime_values, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_action_mapping(item, runtime_values, secrets) for item in value]
    return value


@router.post("/projects/{pid}/actions/trigger")
@limiter.limit("60/minute")
async def trigger_action(body: ActionTriggerRequest, request: Request, ctx: ProjectEditorDep) -> dict:
    """Proxy an intent action webhook call server-side."""
    payload = get_token_payload(request)
    return await execute_action_webhook(
        body,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        user_email=payload.email if payload else "",
        authorization_header=request.headers.get("Authorization", ""),
    )


async def execute_action_webhook(
    body: ActionTriggerRequest,
    *,
    tenant_id: str,
    project_id: str,
    user_email: str = "",
    authorization_header: str = "",
) -> dict:
    """Execute an intent action webhook with the same guardrails as the admin proxy."""
    from automail.core.runtime_secrets import load_runtime_secrets, resolve_secret_placeholders

    method = body.method.upper()
    if method not in {"GET", "POST"}:
        raise HTTPException(status_code=400, detail="Action webhooks only support GET and POST")

    secrets = load_runtime_secrets(tenant_id, project_id)
    resolved_webhook = str(resolve_secret_placeholders(body.webhook, secrets))
    resolved_headers = resolve_secret_placeholders(dict(body.headers), secrets)
    resolved_payload = resolve_secret_placeholders(dict(body.payload), secrets)
    if not isinstance(resolved_headers, dict):
        resolved_headers = {}
    if not isinstance(resolved_payload, dict):
        resolved_payload = {}
    runtime_values = dict(resolved_payload)
    resolved_webhook = str(_resolve_action_mapping(resolved_webhook, runtime_values, secrets))
    resolved_query = _resolve_action_mapping(dict(body.query), runtime_values, secrets)
    resolved_body = _resolve_action_mapping(dict(body.body), runtime_values, secrets)
    if not isinstance(resolved_query, dict):
        resolved_query = {}
    if not isinstance(resolved_body, dict):
        resolved_body = {}

    _validate_webhook_url(resolved_webhook)
    parsed = urlparse(resolved_webhook)
    headers = dict(resolved_headers)
    started = time.monotonic()
    if parsed.path.startswith("/demo/"):
        if authorization_header:
            headers.setdefault("Authorization", authorization_header)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if method == "POST" and resolved_body:
                json_payload = resolved_body
            elif method == "POST" and not resolved_query:
                json_payload = resolved_payload
            else:
                json_payload = None
            if json_payload is not None:
                response = await client.request(
                    method=method,
                    url=resolved_webhook,
                    headers=headers,
                    params=resolved_query if resolved_query else None,
                    json=json_payload,
                )
            else:
                response = await client.request(
                    method=method,
                    url=resolved_webhook,
                    headers=headers,
                    params=resolved_query if resolved_query else None,
                )
            response.raise_for_status()
            try:
                response_payload = response.json()
            except Exception:
                response_payload = response.text[:1000]
            record_action_run(
                tenant_id=tenant_id,
                project_id=project_id,
                user_email=user_email,
                webhook=body.webhook,
                method=body.method,
                payload=body.payload,
                response=response_payload,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return {"status": "ok", "response": response_payload}
    except httpx.HTTPStatusError as exc:
        record_action_run(
            tenant_id=tenant_id,
            project_id=project_id,
            user_email=user_email,
            webhook=body.webhook,
            method=body.method,
            payload=body.payload,
            error=f"Webhook returned {exc.response.status_code}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Webhook returned {exc.response.status_code}: {exc.response.text[:500]}",
        )
    except Exception as exc:
        record_action_run(
            tenant_id=tenant_id,
            project_id=project_id,
            user_email=user_email,
            webhook=body.webhook,
            method=body.method,
            payload=body.payload,
            error=str(exc),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        raise HTTPException(status_code=502, detail=f"Webhook call failed: {exc}")
