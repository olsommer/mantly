"""Centralized privacy-safe logging configuration for the Mantly backend."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, cast

from automail.core.observability import correlation_id, redact, redact_text, request_id

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


class JsonLogFormatter(logging.Formatter):
    """Render one redacted JSON object per log event."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        current_request_id = request_id()
        current_correlation_id = correlation_id()
        if current_request_id:
            payload["requestId"] = current_request_id
        if current_correlation_id:
            payload["correlationId"] = current_correlation_id

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
        }
        if extras:
            payload["fields"] = redact(extras)
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        if record.stack_info:
            payload["stack"] = redact_text(self.formatStack(record.stack_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


class RedactingTextFormatter(logging.Formatter):
    """Human-readable local format that still redacts common secrets/content."""

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = request_id() or "-"
        record.correlation_id = correlation_id() or "-"
        return redact_text(super().format(record))


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

    handler: logging.StreamHandler[Any] | None = None
    for existing in root.handlers:
        if getattr(existing, "_mantly_handler", False):
            handler = cast(logging.StreamHandler[Any], existing)
            break
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        setattr(handler, "_mantly_handler", True)
        root.addHandler(handler)

    handler.setLevel(resolved_level)
    handler.setFormatter(formatter)

    # Third-party debug logs can contain payloads or create excessive volume.
    for logger_name in ("httpx", "httpcore", "urllib3", "multipart", "asyncio"):
        logging.getLogger(logger_name).setLevel(max(resolved_level, logging.WARNING))
