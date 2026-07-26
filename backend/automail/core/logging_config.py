"""Centralized privacy-safe logging configuration for the Mantly backend."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Mapping

from automail.core.observability import correlation_id, request_id, sanitize_identifier

_STANDARD_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/*-]{0,127}")
_SAFE_ROUTE = re.compile(r"/[A-Za-z0-9_./{}:*-]{0,255}")
_SAFE_NUMERIC_FIELDS = frozenset(
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
_SAFE_BOOLEAN_FIELDS = frozenset(
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
_SAFE_IDENTIFIER_FIELDS = frozenset(
    {
        "actionId",
        "channelId",
        "issueId",
        "projectId",
        "providerRequestId",
        "runId",
        "tenantId",
        "ticketId",
    }
)
_SAFE_ENUM_FIELDS = frozenset(
    {
        "component",
        "errorType",
        "method",
        "model",
        "provider",
        "reason",
        "source",
        "stage",
        "status",
    }
)


def _safe_token(value: Any, *, fallback: str = "") -> str:
    clean = str(value or "").strip()
    return clean if _SAFE_TOKEN.fullmatch(clean) else fallback


def _safe_fields(values: Mapping[str, Any]) -> dict[str, Any]:
    """Drop unregistered or content-bearing fields."""

    fields: dict[str, Any] = {}
    for key, value in values.items():
        if key == "event":
            continue
        if key == "schedulers" and isinstance(value, Mapping):
            schedulers = {
                safe_key: nested
                for nested_key, nested in value.items()
                if (safe_key := _safe_token(nested_key)) and isinstance(nested, bool)
            }
            if schedulers:
                fields[key] = schedulers
            continue
        if key in _SAFE_BOOLEAN_FIELDS and isinstance(value, bool):
            fields[key] = value
            continue
        if (
            key in _SAFE_NUMERIC_FIELDS
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        ):
            fields[key] = value
            continue
        if key in _SAFE_IDENTIFIER_FIELDS:
            clean_identifier = "*" if value == "*" else sanitize_identifier(str(value or ""), max_length=128)
            if clean_identifier:
                fields[key] = clean_identifier
            continue
        if key == "route":
            clean_route = str(value or "")
            if _SAFE_ROUTE.fullmatch(clean_route):
                fields[key] = clean_route
            continue
        if key in _SAFE_ENUM_FIELDS:
            clean_token = _safe_token(value)
            if clean_token:
                fields[key] = clean_token
    return fields


def _log_payload(record: logging.LogRecord) -> dict[str, Any]:
    event = _safe_token(record.__dict__.get("event"), fallback="unstructured_log")
    payload: dict[str, Any] = {
        "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
        "level": record.levelname,
        "logger": _safe_token(record.name, fallback="unknown"),
        "event": event,
        "message": event,
        "source": {
            "module": _safe_token(record.module, fallback="unknown"),
            "function": _safe_token(record.funcName, fallback="unknown"),
            "line": record.lineno,
        },
    }
    current_request_id = sanitize_identifier(request_id(), max_length=128)
    current_correlation_id = sanitize_identifier(correlation_id(), max_length=128)
    if current_request_id:
        payload["requestId"] = current_request_id
    if current_correlation_id:
        payload["correlationId"] = current_correlation_id

    extras = {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
    }
    fields = _safe_fields(extras)
    if fields:
        payload["fields"] = fields
    if record.exc_info and record.exc_info[0]:
        payload["exceptionType"] = _safe_token(record.exc_info[0].__name__, fallback="Exception")
    return payload


class JsonLogFormatter(logging.Formatter):
    """Render one deny-by-default JSON object per log event."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(_log_payload(record), ensure_ascii=False, separators=(",", ":"))


class RedactingTextFormatter(logging.Formatter):
    """Human-readable local format built from the same safe field allowlist."""

    def format(self, record: logging.LogRecord) -> str:
        payload = _log_payload(record)
        parts = [
            str(payload["timestamp"]),
            f"[{payload['level']}]",
            str(payload["logger"]),
            f"request={payload.get('requestId', '-')}",
            f"correlation={payload.get('correlationId', '-')}",
            f"event={payload['event']}",
        ]
        if "fields" in payload:
            parts.append(f"fields={json.dumps(payload['fields'], ensure_ascii=False, separators=(',', ':'))}")
        if "exceptionType" in payload:
            parts.append(f"exceptionType={payload['exceptionType']}")
        return " ".join(parts)


def _resolve_level(level: int | None) -> int:
    if level is not None:
        return level
    env_level = os.getenv("LOG_LEVEL", "INFO").upper()
    resolved = getattr(logging, env_level, logging.INFO)
    return resolved if isinstance(resolved, int) else logging.INFO


def setup_logging(level: int | None = None) -> None:
    """Configure one application handler with redaction and request correlation.

    ``LOG_FORMAT=json`` is the production default. Set ``LOG_FORMAT=text`` for
    local interactive use. Repeated calls update the existing Mantly handler
    rather than producing duplicate records.
    """

    resolved_level = _resolve_level(level)
    log_format = os.getenv("LOG_FORMAT", "json").strip().lower()
    formatter: logging.Formatter
    if log_format == "text":
        formatter = RedactingTextFormatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s request=%(request_id)s correlation=%(correlation_id)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    else:
        formatter = JsonLogFormatter()

    root = logging.getLogger()
    root.setLevel(resolved_level)
    for existing in list(root.handlers):
        root.removeHandler(existing)

    handler: logging.StreamHandler[Any] = logging.StreamHandler(sys.stdout)
    setattr(handler, "_mantly_handler", True)
    handler.setLevel(resolved_level)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Named handlers can bypass root formatting and leak original LogRecords.
    managed_loggers = ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore", "urllib3", "multipart", "asyncio")
    for logger_name in managed_loggers:
        named_logger = logging.getLogger(logger_name)
        named_logger.handlers.clear()
        named_logger.propagate = True
        named_logger.disabled = logger_name == "uvicorn.access"
        if logger_name not in {"uvicorn", "uvicorn.error", "uvicorn.access"}:
            named_logger.setLevel(max(resolved_level, logging.WARNING))
