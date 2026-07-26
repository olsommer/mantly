from __future__ import annotations

import io
import json
import logging
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import automail.core.observability as observability_module
from automail.core.logging_config import JsonLogFormatter, RedactingTextFormatter, setup_logging
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
    assert runtime_observability.snapshot()["components"]["support.delivery"]["last_error"] == "reported_failure"

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


def test_never_successful_component_becomes_stale(monkeypatch) -> None:
    runtime_observability.mark_success("application.startup")
    runtime_observability.mark_started("support.sync", stale_after_seconds=30)
    started_at = observability_module.datetime.fromisoformat(
        runtime_observability.snapshot()["components"]["support.sync"]["started_at"]
    )
    monkeypatch.setattr(observability_module, "utc_now", lambda: started_at + timedelta(seconds=31))

    degraded = runtime_observability.health()

    assert degraded["ready"] is False
    assert degraded["stale"] == ["support.sync"]


def test_http_middleware_uses_route_templates_and_never_raw_paths(monkeypatch) -> None:
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

    content_like_path = "private-customer-filename.txt"
    assert client.get(f"/example/{content_like_path}").status_code == 200
    unmatched_path = "private-unmatched-customer-content"
    assert client.get(f"/{unmatched_path}").status_code == 404

    snapshot = runtime_observability.snapshot()
    assert snapshot["requests"]["total"] >= 3
    assert snapshot["requests"]["pathCounts"]["GET /example/{item_id}"] == 2
    assert snapshot["requests"]["pathCounts"]["GET /__unmatched__"] == 1
    serialized = json.dumps(snapshot)
    assert "1234567890123456" not in serialized
    assert content_like_path not in serialized
    assert unmatched_path not in serialized

    failed = client.get("/failure")
    assert failed.status_code == 500
    assert runtime_observability.snapshot()["requests"]["serverErrors"] == 1


@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer", "3600001"])
def test_slow_request_threshold_is_validated_at_startup(monkeypatch, value: str) -> None:
    monkeypatch.setenv("OBSERVABILITY_SLOW_REQUEST_MS", value)

    with pytest.raises(RuntimeError, match="OBSERVABILITY_SLOW_REQUEST_MS"):
        _app()


def test_slow_request_threshold_is_parsed_once(monkeypatch) -> None:
    monkeypatch.setenv("OBSERVABILITY_SLOW_REQUEST_MS", "2000")
    client = TestClient(_app())
    monkeypatch.setenv("OBSERVABILITY_SLOW_REQUEST_MS", "invalid-after-startup")

    assert client.get("/example/one").status_code == 200


def test_request_and_operation_cardinality_are_bounded() -> None:
    for index in range(300):
        runtime_observability.record_request(
            "GET",
            f"/route/{index}",
            200,
            1,
            f"request-{index}",
            slow_threshold_ms=2_000,
        )
    for index in range(40):
        runtime_observability.record_operation(
            f"operation.{index}",
            succeeded=False,
            status="failed",
            error=RuntimeError(f"private-error-{index}"),
            details={
                "failed": 1,
                "projectId": "project-1",
                "body": f"private-body-{index}",
            },
        )

    snapshot = runtime_observability.snapshot()
    assert len(snapshot["requests"]["pathCounts"]) == 50
    assert snapshot["requests"]["pathCounts"]["OTHER /__overflow__"] == 45
    assert len(snapshot["operations"]) == 32
    assert snapshot["operations"]["__overflow__"]["total"] == 9
    assert snapshot["operations"]["operation.0"]["last_error"] == "RuntimeError"
    assert snapshot["operations"]["operation.0"]["details"] == {
        "failed": 1,
        "projectId": "project-1",
    }
    assert "private-" not in json.dumps(snapshot)


def test_operation_details_drop_non_finite_values_and_slow_request_ids_are_sanitized() -> None:
    runtime_observability.record_operation(
        "support.test",
        succeeded=True,
        details={"durationMs": float("nan"), "processed": 1},
    )
    runtime_observability.record_request(
        "GET",
        "/example/{item_id}",
        200,
        2_001,
        "request id with private content",
        slow_threshold_ms=2_000,
    )

    snapshot = runtime_observability.snapshot()
    assert snapshot["operations"]["support.test"]["details"] == {"processed": 1}
    assert snapshot["requests"]["recentSlow"][0]["requestId"] == "requestidwithprivatecontent"


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


def test_logging_formatters_emit_only_allowlisted_operational_fields() -> None:
    tokens = bind_request_context("request-log", "correlation-log")
    try:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="customer body %s",
            args=("private-message user@example.com token=super-secret",),
            exc_info=(RuntimeError, RuntimeError("private-exception-content"), None),
        )
        record.event = "provider_request_completed"
        record.route = "/example/{item_id}"
        record.statusCode = 200
        record.totalTokens = 42
        record.api_key = "another-secret"
        record.body = "private-body-content"
        record.prompt = "private-prompt-content"
        record.attachmentFilename = "private-file.txt"

        rendered_json = json.loads(JsonLogFormatter().format(record))
        assert rendered_json["requestId"] == "request-log"
        assert rendered_json["correlationId"] == "correlation-log"
        assert rendered_json["event"] == "provider_request_completed"
        assert rendered_json["message"] == "provider_request_completed"
        assert rendered_json["exceptionType"] == "RuntimeError"
        assert rendered_json["fields"] == {
            "route": "/example/{item_id}",
            "statusCode": 200,
            "totalTokens": 42,
        }

        text = RedactingTextFormatter().format(record)
        assert "request=request-log" in text
        assert "correlation=correlation-log" in text
        assert "event=provider_request_completed" in text
        assert "exceptionType=RuntimeError" in text

        rendered = json.dumps(rendered_json) + text
        for private_value in (
            "private-message",
            "user@example.com",
            "super-secret",
            "another-secret",
            "private-body-content",
            "private-prompt-content",
            "private-file.txt",
            "private-exception-content",
        ):
            assert private_value not in rendered
    finally:
        reset_request_context(tokens)


def test_setup_logging_owns_one_safe_handler(monkeypatch) -> None:
    managed_names = (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "httpx",
        "httpcore",
        "urllib3",
        "multipart",
        "asyncio",
    )
    root = logging.getLogger()
    original_root_handlers = list(root.handlers)
    original_root_level = root.level
    original_named_state = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).propagate,
            logging.getLogger(name).disabled,
            logging.getLogger(name).level,
        )
        for name in managed_names
    }
    sentinel_one = logging.StreamHandler(io.StringIO())
    sentinel_two = logging.StreamHandler(io.StringIO())
    root.handlers[:] = [sentinel_one, sentinel_two]
    logging.getLogger("uvicorn.access").handlers[:] = [logging.StreamHandler(io.StringIO())]
    stream = io.StringIO()
    try:
        monkeypatch.setenv("LOG_FORMAT", "json")
        setup_logging(logging.INFO)
        setup_logging(logging.INFO)
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert getattr(handler, "_mantly_handler", False) is True
        handler.setStream(stream)
        assert logging.getLogger("uvicorn.access").handlers == []
        assert logging.getLogger("uvicorn.access").disabled is True

        logging.getLogger("test.owned").info(
            "private ignored body",
            extra={"event": "owned_handler_test", "processed": 1},
        )
    finally:
        root.handlers[:] = original_root_handlers
        root.setLevel(original_root_level)
        for name, (handlers, propagate, disabled, level) in original_named_state.items():
            named_logger = logging.getLogger(name)
            named_logger.handlers[:] = handlers
            named_logger.propagate = propagate
            named_logger.disabled = disabled
            named_logger.setLevel(level)

    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "owned_handler_test"
    assert "private ignored body" not in lines[0]
