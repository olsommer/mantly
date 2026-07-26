"""Production observability primitives with privacy-safe defaults."""

from __future__ import annotations

import contextvars
import copy
import hmac
import math
import os
import re
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, TypeVar

from fastapi import FastAPI, Header, HTTPException, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

T = TypeVar("T")

_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("mantly_request_id", default="")
_CORRELATION_ID: contextvars.ContextVar[str] = contextvars.ContextVar("mantly_correlation_id", default="")

_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|token|authorization|cookie|api[_-]?key|private[_-]?key|client[_-]?secret|jwt|smtp[_-]?password|webhook[_-]?secret)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_KEY_VALUE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|client[_-]?secret|jwt)\b\s*[:=]\s*([^\s,;]+)"
)
_EMAIL = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/*-]{0,127}")
_SAFE_ROUTE_TEMPLATE = re.compile(r"/[A-Za-z0-9_./{}:*-]{0,255}")
_SAFE_METHODS = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"})
_MAX_REQUEST_ROUTE_KEYS = 256
_ROUTE_OVERFLOW_KEY = "OTHER /__overflow__"
_MAX_OPERATION_KEYS = 32
_OPERATION_OVERFLOW_KEY = "__overflow__"

_SAFE_OPERATION_NUMERIC_FIELDS = frozenset(
    {
        "blocked",
        "cachedInputTokens",
        "channels",
        "claimed",
        "connectors",
        "costUsdMicros",
        "created",
        "deferred",
        "durationMs",
        "escalated",
        "expired",
        "failed",
        "inputTokens",
        "inspected",
        "intervalSeconds",
        "outputTokens",
        "processed",
        "recorded",
        "retried",
        "sent",
        "skipped",
        "started",
        "statusCode",
        "totalTokens",
        "uncertain",
        "unmatched",
        "updated",
    }
)
_SAFE_OPERATION_BOOLEAN_FIELDS = frozenset(
    {
        "configEnvLoaded",
        "demoRoutes",
        "enabled",
        "live",
        "ready",
        "recorded",
        "requireAuth",
    }
)
_SAFE_OPERATION_IDENTIFIER_FIELDS = frozenset(
    {
        "actionId",
        "channelId",
        "correlationId",
        "issueId",
        "projectId",
        "providerRequestId",
        "requestId",
        "runId",
        "tenantId",
        "ticketId",
    }
)
_SAFE_OPERATION_ENUM_FIELDS = frozenset(
    {
        "component",
        "errorType",
        "method",
        "model",
        "provider",
        "reason",
        "route",
        "source",
        "stage",
        "status",
    }
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def request_id() -> str:
    return _REQUEST_ID.get()


def correlation_id() -> str:
    return _CORRELATION_ID.get()


def bind_request_context(request_value: str, correlation_value: str) -> tuple[contextvars.Token[str], contextvars.Token[str]]:
    return _REQUEST_ID.set(request_value), _CORRELATION_ID.set(correlation_value)


def reset_request_context(tokens: tuple[contextvars.Token[str], contextvars.Token[str]]) -> None:
    request_token, correlation_token = tokens
    _REQUEST_ID.reset(request_token)
    _CORRELATION_ID.reset(correlation_token)


def sanitize_identifier(value: str | None, *, max_length: int = 128) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Za-z0-9._:-]", "", value.strip())[:max_length]


def redact_text(value: str, *, redact_emails: bool | None = None) -> str:
    """Remove common secret shapes and optionally email local parts from text."""

    redacted = _BEARER.sub("Bearer [REDACTED]", value)
    redacted = _KEY_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    should_redact_emails = (
        os.getenv("LOG_REDACT_EMAILS", "true").lower() == "true" if redact_emails is None else redact_emails
    )
    if should_redact_emails:
        redacted = _EMAIL.sub(lambda match: f"[REDACTED]@{match.group(2)}", redacted)
    return redacted


def redact(value: Any, *, depth: int = 0) -> Any:
    """Recursively redact secrets while preserving operational structure."""

    if depth > 8:
        return "[MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes):
        return f"[BYTES:{len(value)}]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            result[key] = "[REDACTED]" if _SENSITIVE_KEY.search(key) else redact(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item, depth=depth + 1) for item in value]
    return redact_text(str(value))


def _safe_token(value: Any) -> str:
    clean = str(value or "").strip()
    return clean if _SAFE_TOKEN.fullmatch(clean) else ""


def _safe_operational_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Allow only typed, content-free operational fields."""

    if value is None:
        return {}
    result: dict[str, Any] = {}
    for raw_key, item in value.items():
        key = str(raw_key)
        if key == "schedulers" and isinstance(item, Mapping):
            schedulers = {
                safe_key: nested
                for nested_key, nested in item.items()
                if (safe_key := _safe_token(nested_key)) and isinstance(nested, bool)
            }
            if schedulers:
                result[key] = schedulers
            continue
        if key in _SAFE_OPERATION_BOOLEAN_FIELDS and isinstance(item, bool):
            result[key] = item
            continue
        if (
            key in _SAFE_OPERATION_NUMERIC_FIELDS
            and isinstance(item, (int, float))
            and not isinstance(item, bool)
            and (not isinstance(item, float) or math.isfinite(item))
        ):
            result[key] = item
            continue
        if key in _SAFE_OPERATION_IDENTIFIER_FIELDS:
            clean_identifier = "*" if item == "*" else sanitize_identifier(str(item or ""), max_length=128)
            if clean_identifier:
                result[key] = clean_identifier
            continue
        if key in _SAFE_OPERATION_ENUM_FIELDS:
            clean_token = _safe_token(item)
            if clean_token:
                result[key] = clean_token
    return result


def _safe_error_code(error: BaseException | str | None) -> str:
    if isinstance(error, BaseException):
        return type(error).__name__
    clean = _safe_token(error)
    return clean or "reported_failure"


@dataclass
class ComponentState:
    name: str
    enabled: bool = True
    status: str = "unknown"
    started_at: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_duration_ms: int | None = None
    consecutive_failures: int = 0
    total_runs: int = 0
    total_failures: int = 0
    last_error: str | None = None
    stale_after_seconds: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class OperationState:
    name: str
    status: str = "unknown"
    total: int = 0
    total_failures: int = 0
    last_observed_at: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_duration_ms: int | None = None
    last_error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class RuntimeObservability:
    """Thread-safe in-process state for health, request metrics and heartbeats."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._components: dict[str, ComponentState] = {}
        self._operations: dict[str, OperationState] = {}
        self._process_started_at = iso_now()
        self._request_total = 0
        self._request_errors = 0
        self._request_duration_ms_total = 0
        self._status_counts: Counter[str] = Counter()
        self._path_counts: Counter[str] = Counter()
        self._recent_slow_requests: deque[dict[str, Any]] = deque(maxlen=25)

    def reset_for_tests(self) -> None:
        with self._lock:
            self._components.clear()
            self._operations.clear()
            self._process_started_at = iso_now()
            self._request_total = 0
            self._request_errors = 0
            self._request_duration_ms_total = 0
            self._status_counts.clear()
            self._path_counts.clear()
            self._recent_slow_requests.clear()

    def mark_started(
        self,
        name: str,
        *,
        enabled: bool = True,
        stale_after_seconds: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> float:
        with self._lock:
            state = self._components.setdefault(name, ComponentState(name=name))
            state.enabled = enabled
            state.status = "running" if enabled else "disabled"
            state.started_at = iso_now()
            if stale_after_seconds is not None:
                state.stale_after_seconds = stale_after_seconds
            if details is not None:
                state.details.update(_safe_operational_mapping(details))
            if not enabled:
                state.last_error = None
                state.consecutive_failures = 0
        return time.monotonic()

    def mark_disabled(self, name: str, *, reason: str, details: Mapping[str, Any] | None = None) -> None:
        merged = dict(details or {})
        merged["reason"] = reason
        self.mark_started(name, enabled=False, details=merged)

    def mark_success(
        self,
        name: str,
        *,
        started_monotonic: float | None = None,
        status: str = "ok",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            state = self._components.setdefault(name, ComponentState(name=name))
            state.enabled = True
            state.status = status
            state.last_success_at = iso_now()
            state.last_duration_ms = (
                int((time.monotonic() - started_monotonic) * 1000) if started_monotonic is not None else None
            )
            state.consecutive_failures = 0
            state.total_runs += 1
            state.last_error = None
            if details is not None:
                state.details.update(_safe_operational_mapping(details))

    def mark_failure(
        self,
        name: str,
        error: BaseException | str,
        *,
        started_monotonic: float | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            state = self._components.setdefault(name, ComponentState(name=name))
            state.enabled = True
            state.status = "failed"
            state.last_failure_at = iso_now()
            state.last_duration_ms = (
                int((time.monotonic() - started_monotonic) * 1000) if started_monotonic is not None else None
            )
            state.consecutive_failures += 1
            state.total_runs += 1
            state.total_failures += 1
            state.last_error = _safe_error_code(error)
            if details is not None:
                state.details.update(_safe_operational_mapping(details))

    def record_operation(
        self,
        name: str,
        *,
        succeeded: bool,
        status: str | None = None,
        started_monotonic: float | None = None,
        error: BaseException | str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Record bounded customer-impact evidence without changing readiness."""

        clean_name = _safe_token(name) or "invalid"
        with self._lock:
            if clean_name not in self._operations and len(self._operations) >= _MAX_OPERATION_KEYS - 1:
                clean_name = _OPERATION_OVERFLOW_KEY
            state = self._operations.setdefault(clean_name, OperationState(name=clean_name))
            now = iso_now()
            state.total += 1
            state.last_observed_at = now
            state.last_duration_ms = (
                int((time.monotonic() - started_monotonic) * 1000) if started_monotonic is not None else None
            )
            state.status = _safe_token(status) or ("ok" if succeeded else "failed")
            if succeeded:
                state.last_success_at = now
                state.last_error = None
            else:
                state.total_failures += 1
                state.last_failure_at = now
                state.last_error = _safe_error_code(error)
            if details is not None:
                state.details.update(_safe_operational_mapping(details))

    def record_request(
        self,
        method: str,
        route_template: str,
        status_code: int,
        duration_ms: int,
        request_value: str,
        *,
        slow_threshold_ms: int,
    ) -> None:
        normalized_method = method.upper() if method.upper() in _SAFE_METHODS else "OTHER"
        normalized_route = route_template if _SAFE_ROUTE_TEMPLATE.fullmatch(route_template) else "/__unmatched__"
        route_key = f"{normalized_method} {normalized_route}"
        with self._lock:
            self._request_total += 1
            self._request_duration_ms_total += max(0, duration_ms)
            if status_code >= 500:
                self._request_errors += 1
            self._status_counts[str(status_code)] += 1
            if route_key not in self._path_counts and len(self._path_counts) >= _MAX_REQUEST_ROUTE_KEYS - 1:
                route_key = _ROUTE_OVERFLOW_KEY
            self._path_counts[route_key] += 1
            if duration_ms >= slow_threshold_ms:
                self._recent_slow_requests.append(
                    {
                        "at": iso_now(),
                        "requestId": sanitize_identifier(request_value, max_length=128),
                        "method": normalized_method,
                        "route": normalized_route,
                        "status": status_code,
                        "durationMs": duration_ms,
                    }
                )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            components = {name: asdict(copy.deepcopy(state)) for name, state in sorted(self._components.items())}
            operations = {name: asdict(copy.deepcopy(state)) for name, state in sorted(self._operations.items())}
            request_total = self._request_total
            return {
                "schemaVersion": "1.0",
                "processStartedAt": self._process_started_at,
                "generatedAt": iso_now(),
                "components": components,
                "operations": operations,
                "requests": {
                    "total": request_total,
                    "serverErrors": self._request_errors,
                    "serverErrorRate": self._request_errors / request_total if request_total else 0.0,
                    "averageDurationMs": self._request_duration_ms_total / request_total if request_total else 0.0,
                    "statusCounts": dict(sorted(self._status_counts.items())),
                    "pathCounts": dict(self._path_counts.most_common(50)),
                    "recentSlow": list(self._recent_slow_requests),
                },
            }

    def health(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        now = utc_now()
        failures: list[str] = []
        stale: list[str] = []
        for name, state in snapshot["components"].items():
            if not state["enabled"]:
                continue
            if state["status"] == "failed":
                failures.append(name)
            stale_after = state.get("stale_after_seconds")
            last_success = state.get("last_success_at")
            started_at = state.get("started_at")
            freshness_reference = last_success if isinstance(last_success, str) else started_at
            if isinstance(stale_after, int) and stale_after > 0 and isinstance(freshness_reference, str):
                parsed = datetime.fromisoformat(freshness_reference)
                if (now - parsed).total_seconds() > stale_after:
                    stale.append(name)
        startup = snapshot["components"].get("application.startup", {})
        ready = startup.get("status") == "ok" and not failures and not stale
        return {
            "schemaVersion": "1.0",
            "status": "ready" if ready else "degraded",
            "live": True,
            "ready": ready,
            "generatedAt": snapshot["generatedAt"],
            "failures": failures,
            "stale": stale,
        }


runtime_observability = RuntimeObservability()


def request_route_template(request: Request) -> str:
    """Return the matched static route template, never caller-controlled path text."""

    route = request.scope.get("route")
    candidate = getattr(route, "path_format", None) or getattr(route, "path", None)
    if isinstance(candidate, str) and _SAFE_ROUTE_TEMPLATE.fullmatch(candidate):
        return candidate
    return "/__unmatched__"


def _positive_int_env(name: str, default: int, *, maximum: int) -> int:
    raw = os.getenv(name, str(default)) or str(default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer from 1 to {maximum}") from exc
    if value < 1 or value > maximum:
        raise RuntimeError(f"{name} must be an integer from 1 to {maximum}")
    return value


def observe_call(
    component: str,
    callback: Callable[[], T],
    *,
    stale_after_seconds: int | None = None,
    detail_builder: Callable[[T], Mapping[str, Any]] | None = None,
) -> T:
    started = runtime_observability.mark_started(component, stale_after_seconds=stale_after_seconds)
    try:
        result = callback()
    except Exception as exc:
        runtime_observability.mark_failure(component, exc, started_monotonic=started)
        raise
    details = detail_builder(result) if detail_builder else None
    runtime_observability.mark_success(component, started_monotonic=started, details=details)
    return result


def install_observability(app: FastAPI) -> None:
    """Install request correlation, privacy-safe metrics, and health endpoints."""

    slow_request_ms = _positive_int_env("OBSERVABILITY_SLOW_REQUEST_MS", 2_000, maximum=3_600_000)

    @app.middleware("http")
    async def observability_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming_request_id = sanitize_identifier(request.headers.get("X-Request-ID"))
        incoming_correlation_id = sanitize_identifier(request.headers.get("X-Correlation-ID"))
        request_value = incoming_request_id or uuid.uuid4().hex
        correlation_value = incoming_correlation_id or request_value
        tokens = bind_request_context(request_value, correlation_value)
        started = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_value
            response.headers["X-Correlation-ID"] = correlation_value
            return response
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            runtime_observability.record_request(
                request.method,
                request_route_template(request),
                status_code,
                duration_ms,
                request_value,
                slow_threshold_ms=slow_request_ms,
            )
            reset_request_context(tokens)

    @app.get("/api/health", include_in_schema=False)
    async def health() -> dict[str, Any]:
        state = runtime_observability.health()
        return {"status": "ok" if state["live"] else "failed", "live": state["live"], "ready": state["ready"]}

    @app.get("/api/ready", include_in_schema=False)
    async def readiness(response: Response) -> dict[str, Any]:
        state = runtime_observability.health()
        if not state["ready"]:
            response.status_code = 503
        return state

    @app.get("/api/internal/observability", include_in_schema=False)
    async def detailed_observability(
        x_observability_token: str | None = Header(default=None, alias="X-Observability-Token"),
    ) -> dict[str, Any]:
        expected = os.getenv("OBSERVABILITY_TOKEN", "")
        if not expected:
            raise HTTPException(status_code=404, detail="Observability detail endpoint is disabled")
        if not x_observability_token or not hmac.compare_digest(x_observability_token, expected):
            raise HTTPException(status_code=401, detail="Invalid observability token")
        return {"health": runtime_observability.health(), **runtime_observability.snapshot()}
