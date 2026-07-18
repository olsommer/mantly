from __future__ import annotations

import json
import logging
from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

import automail.core.observability as observability_module
from automail.core.logging_config import JsonLogFormatter, RedactingTextFormatter
from automail.core.observability import (
    bind_request_context,
    install_observability,
    redact,
    redact_text,
    reset_request_context,
    runtime_observability,
    sanitize_identifier,
)


def _app() -> FastAPI:
    app = FastAPI()
    install_observability(app)

    @app.get("/example/{item_id}")
    async def example(item_id: str) -> dict[str, str]:
        return {"itemId": item_id}

    @app.get("/failure")
    async def failure() -> None:
        raise RuntimeError("test failure")

    return app


def setup_function() -> None:
    runtime_observability.reset_for_tests()


def test_redaction_removes_nested_secrets_and_email_local_parts(monkeypatch) -> None:
    monkeypatch.setenv("LOG_REDACT_EMAILS", "true")
    payload = {
        "password": "super-secret-password",
        "nested": {
            "api_key": "provider-key",
            "message": "Authorization: Bearer abcdefghijklmnop from user@example.com",
        },
        "safe": "visible",
    }

    result = redact(payload)

    assert result["password"] == "[REDACTED]"
    assert result["nested"]["api_key"] == "[REDACTED]"
    assert "abcdefghijklmnop" not in result["nested"]["message"]
    assert "user@example.com" not in result["nested"]["message"]
    assert result["safe"] == "visible"
    assert redact_text("token=abcdefghijk") == "token=[REDACTED]"


def test_request_ids_are_sanitized() -> None:
    assert sanitize_identifier(" request/id with spaces ") == "requestidwithspaces"
    assert sanitize_identifier("a" * 200, max_length=32) == "a" * 32


def test_health_and_readiness_follow_component_state(monkeypatch) -> None:
    runtime_observability.mark_success("application.startup")
    runtime_observability.mark_started("support.delivery", stale_after_seconds=60)
    runtime_observability.mark_success("support.delivery", details={"sent": 2})

    assert runtime_observability.health()["ready"] is True

    runtime_observability.mark_failure("support.delivery", "password=do-not-expose")
    degraded = runtime_observability.health()
    assert degraded["ready"] is False
    assert degraded["failures"] == ["support.delivery"]
    assert "do-not-expose" not in runtime_observability.snapshot()["components"]["support.delivery"]["last_error"]

    runtime_observability.mark_success("support.delivery", details={"sent": 3})
    assert runtime_observability.health()["ready"] is True

    snapshot = runtime_observability.snapshot()["components"]["support.delivery"]
    assert snapshot["stale_after_seconds"] == 60
    assert snapshot["details"]["sent"] == 3

    original_now = observability_module.utc_now
    success_time = observability_module.datetime.fromisoformat(snapshot["last_success_at"])
    monkeypatch.setattr(observability_module, "utc_now", lambda: success_time + timedelta(seconds=61))
    try:
        stale = runtime_observability.health()
    finally:
        monkeypatch.setattr(observability_module, "utc_now", original_now)
    assert stale["ready"] is False
    assert stale["stale"] == ["support.delivery"]


def test_http_middleware_propagates_correlation_and_records_low_cardinality_paths(monkeypatch) -> None:
    monkeypatch.setenv("OBSERVABILITY_SLOW_REQUEST_MS", "1")
    runtime_observability.mark_success("application.startup")
    client = TestClient(_app(), raise_server_exceptions=False)

    response = client.get(
        "/example/1234567890123456",
        headers={"X-Request-ID": "request-123", "X-Correlation-ID": "correlation-456"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-123"
    assert response.headers["X-Correlation-ID"] == "correlation-456"

    snapshot = runtime_observability.snapshot()
    assert snapshot["requests"]["total"] >= 1
    assert snapshot["requests"]["pathCounts"]["GET /example/:id"] == 1

    failed = client.get("/failure")
    assert failed.status_code == 500
    assert runtime_observability.snapshot()["requests"]["serverErrors"] == 1


def test_health_endpoints_and_protected_detail(monkeypatch) -> None:
    runtime_observability.mark_success("application.startup")
    client = TestClient(_app())

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "live": True, "ready": True}

    ready = client.get("/api/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    monkeypatch.delenv("OBSERVABILITY_TOKEN", raising=False)
    assert client.get("/api/internal/observability").status_code == 404

    monkeypatch.setenv("OBSERVABILITY_TOKEN", "observability-test-token")
    assert client.get("/api/internal/observability", headers={"X-Observability-Token": "wrong"}).status_code == 401
    detail = client.get(
        "/api/internal/observability",
        headers={"X-Observability-Token": "observability-test-token"},
    )
    assert detail.status_code == 200
    assert detail.json()["health"]["ready"] is True
    assert "components" in detail.json()


def test_logging_formatters_include_context_and_redact() -> None:
    tokens = bind_request_context("request-log", "correlation-log")
    try:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="password=super-secret for user@example.com",
            args=(),
            exc_info=None,
        )
        record.api_key = "another-secret"

        rendered_json = json.loads(JsonLogFormatter().format(record))
        assert rendered_json["requestId"] == "request-log"
        assert rendered_json["correlationId"] == "correlation-log"
        assert "super-secret" not in rendered_json["message"]
        assert "user@example.com" not in rendered_json["message"]
        assert rendered_json["fields"]["api_key"] == "[REDACTED]"

        text = RedactingTextFormatter(
            "%(levelname)s request=%(request_id)s correlation=%(correlation_id)s %(message)s"
        ).format(record)
        assert "request=request-log" in text
        assert "correlation=correlation-log" in text
        assert "super-secret" not in text
    finally:
        reset_request_context(tokens)
