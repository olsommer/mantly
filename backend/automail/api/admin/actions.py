"""Admin action webhook proxy endpoint."""

import ipaddress
import os
import re
import socket
import time
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _PreparedActionRequest:
    method: str
    webhook: str
    headers: dict[str, str]
    query: dict[str, Any]
    json_payload: dict[str, Any] | None


def _trusted_demo_webhook(url: str) -> bool:
    candidate = urlparse(url)
    if not candidate.path.startswith("/demo/"):
        return False
    configured_origin = os.getenv("API_PUBLIC_URL", "").strip() or os.getenv("PUBLIC_URL", "").strip()
    if not configured_origin:
        return False
    trusted = urlparse(configured_origin)

    def origin(parsed) -> tuple[str, str, int | None]:
        default_port = 443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None
        return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port or default_port

    return bool(candidate.hostname and trusted.hostname and origin(candidate) == origin(trusted))


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


def _prepare_action_request(
    body: ActionTriggerRequest,
    *,
    tenant_id: str,
    project_id: str,
    authorization_header: str,
) -> _PreparedActionRequest:
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
    headers = dict(resolved_headers)
    if _trusted_demo_webhook(resolved_webhook) and authorization_header:
        headers.setdefault("Authorization", authorization_header)

    if method == "POST" and resolved_body:
        json_payload = resolved_body
    elif method == "POST" and not resolved_query:
        json_payload = resolved_payload
    else:
        json_payload = None

    return _PreparedActionRequest(
        method=method,
        webhook=resolved_webhook,
        headers=headers,
        query=resolved_query,
        json_payload=json_payload,
    )


def _request_kwargs(prepared: _PreparedActionRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "method": prepared.method,
        "url": prepared.webhook,
        "headers": prepared.headers,
        "params": prepared.query or None,
    }
    if prepared.json_payload is not None:
        kwargs["json"] = prepared.json_payload
    return kwargs


def _response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text[:1000]


def _record_action_success(
    body: ActionTriggerRequest,
    *,
    tenant_id: str,
    project_id: str,
    user_email: str,
    response_payload: Any,
    started: float,
) -> dict:
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


def _raise_action_failure(
    body: ActionTriggerRequest,
    exc: Exception,
    *,
    tenant_id: str,
    project_id: str,
    user_email: str,
    started: float,
) -> None:
    if isinstance(exc, httpx.HTTPStatusError):
        error = f"Webhook returned {exc.response.status_code}"
        detail = f"{error}: {exc.response.text[:500]}"
    else:
        error = str(exc)
        detail = f"Webhook call failed: {exc}"
    record_action_run(
        tenant_id=tenant_id,
        project_id=project_id,
        user_email=user_email,
        webhook=body.webhook,
        method=body.method,
        payload=body.payload,
        error=error,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    raise HTTPException(status_code=502, detail=detail)


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
    prepared = _prepare_action_request(
        body,
        tenant_id=tenant_id,
        project_id=project_id,
        authorization_header=authorization_header,
    )
    started = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(**_request_kwargs(prepared))
            response.raise_for_status()
            return _record_action_success(
                body,
                tenant_id=tenant_id,
                project_id=project_id,
                user_email=user_email,
                response_payload=_response_payload(response),
                started=started,
            )
    except Exception as exc:
        _raise_action_failure(
            body,
            exc,
            tenant_id=tenant_id,
            project_id=project_id,
            user_email=user_email,
            started=started,
        )
        raise AssertionError("unreachable")


def execute_action_webhook_sync(
    body: ActionTriggerRequest,
    *,
    tenant_id: str,
    project_id: str,
    user_email: str = "",
    authorization_header: str = "",
) -> dict:
    """Synchronously execute an action webhook with the admin proxy guardrails."""
    prepared = _prepare_action_request(
        body,
        tenant_id=tenant_id,
        project_id=project_id,
        authorization_header=authorization_header,
    )
    started = time.monotonic()

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.request(**_request_kwargs(prepared))
            response.raise_for_status()
            return _record_action_success(
                body,
                tenant_id=tenant_id,
                project_id=project_id,
                user_email=user_email,
                response_payload=_response_payload(response),
                started=started,
            )
    except Exception as exc:
        _raise_action_failure(
            body,
            exc,
            tenant_id=tenant_id,
            project_id=project_id,
            user_email=user_email,
            started=started,
        )
        raise AssertionError("unreachable")
