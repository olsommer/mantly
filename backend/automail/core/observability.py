"""Production observability primitives with privacy-safe defaults."""

from __future__ import annotations

import contextvars
import copy
import hmac
import os
import re
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, MutableMapping, TypeVar

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
    cleaned = re.sub(r"[^A-Za-z0-9._:-]", "", value.strip())[:max_length]
    return cleaned


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


class RuntimeObservability:
    """Thread-safe in-process state for health, request metrics and heartbeats."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._components: dict[str, ComponentState] = {}
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
            state.stale_after_seconds = stale_after_seconds
            state.details = dict(redact(details or {}))
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
            state.last_failure_at = state.last_failure_at
            state.last_duration_ms = (
                int((time.monotonic() - started_monotonic) * 1000) if started_monotonic is not None else None
            )
            state.consecutive_failures = 0
            state.total_runs += 1
            state.last_error = None
            if details is not None:
                state.details = dict(redact(details))

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
            state.last_error = redact_text(str(error))[:500]
            if details is not None:
                state.details = dict(redact(details))

    def record_request(self, method: str, path: str, status_code: int, duration_ms: int, request_value: str) -> None:
        normalized_path = normalize_path(path)
        with self._lock:
            self._request_total += 1
            self._request_duration_ms_total += max(0, duration_ms)
            if status_code >= 500:
                self._request_errors += 1
            self._status_counts[str(status_code)] += 1
            self._path_counts[f"{method.upper()} {normalized_path}"] += 1
            slow_threshold = max(1, int(os.getenv("OBSERVABILITY_SLOW_REQUEST_MS", "2000") or "2000"))
            if duration_ms >= slow_threshold:
                self._recent_slow_requests.append(
                    {
                        "at": iso_now(),
                        "requestId": request_value,
                        "method": method.upper(),
                        "path": normalized_path,
                        "status": status_code,
                        "durationMs": duration_ms,
                    }
                )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            components = {name: asdict(copy.deepcopy(state)) for name, state in sorted(self._components.items())}
            request_total = self._request_total
            return {
                "schemaVersion": "1.0",
                "processStartedAt": self._process_started_at,
                "generatedAt": iso_now(),
                "components": components,
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
            if stale_after and last_success:
                parsed = datetime.fromisoformat(last_success)
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


def normalize_path(path: str) -> str:
    """Reduce high-cardinality identifiers while preserving route usefulness."""

    segments = []
    for segment in path.split("/"):
        if not segment:
            continue
        if re.fullmatch(r"[0-9a-fA-F-]{16,}", segment) or re.fullmatch(r"\d{4,}", segment):
            segments.append(":id")
        else:
            segments.append(segment[:80])
    return "/" + "/".join(segments)


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
                request.url.path,
                status_code,
                duration_ms,
                request_value,
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
