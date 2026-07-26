import json

import httpx
import pytest

from automail.integrations.http_tool import (
    ToolDefinition,
    _make_http_tool,
    _record_tool_call,
    _response_facts,
    begin_tool_call_collection,
    collect_tool_calls,
    current_tool_calls,
)


def test_response_facts_preserve_bounded_matter_lookup_contract() -> None:
    facts, truncated = _response_facts(
        json.dumps(
            {
                "found": None,
                "matter_id": "MAT-2026-104",
                "status": "Awaiting counterparty response",
                "next_deadline": "2026-08-05",
                "responsible_lawyer": "Dr Nora Keller",
                "customer_name": "Must not be persisted",
            }
        )
    )

    assert truncated is False
    assert facts == [
        {"path": "found", "value": None},
        {"path": "matter_id", "value": "MAT-2026-104"},
        {"path": "status", "value": "Awaiting counterparty response"},
        {"path": "next_deadline", "value": "2026-08-05"},
        {"path": "responsible_lawyer", "value": "Dr Nora Keller"},
    ]


@pytest.mark.parametrize("signal", [False, None, {}, []], ids=("false", "null", "object", "array"))
def test_matter_tool_audit_preserves_nonaffirmative_raw_lookup_signal(signal) -> None:
    token = begin_tool_call_collection()
    try:
        _record_tool_call(
            ToolDefinition(
                name="matter_lookup",
                description="Look up a matter",
                method="GET",
                url_template="https://example.test/matters",
            ),
            status="success",
            response_text=json.dumps(
                {
                    "found": signal,
                    "matter_id": "MAT-2026-104",
                    "status": "Awaiting counterparty response",
                    "next_deadline": "2026-08-05",
                    "responsible_lawyer": "Dr Nora Keller",
                }
            ),
        )
        calls = collect_tool_calls(token)
    except Exception:
        collect_tool_calls(token)
        raise

    assert calls[0]["hasNonaffirmativeLookupResult"] is True


def test_matter_tool_audit_marks_truncated_response_before_late_false_signal() -> None:
    response = {
        "matter_id": "MAT-2026-104",
        "status": "Awaiting counterparty response",
        "next_deadline": "2026-08-05",
        "responsible_lawyer": "Dr Nora Keller",
    }
    response.update({f"noise_{index}": {"status": "ok"} for index in range(24)})
    response["found"] = False
    token = begin_tool_call_collection()
    try:
        _record_tool_call(
            ToolDefinition(
                name="matter_lookup",
                description="Look up a matter",
                method="GET",
                url_template="https://example.test/matters",
            ),
            status="success",
            response_text=json.dumps(response),
        )
        calls = collect_tool_calls(token)
    except Exception:
        collect_tool_calls(token)
        raise

    assert calls[0]["responseFactsTruncated"] is True
    assert calls[0]["hasNonaffirmativeLookupResult"] is True
    assert not any(fact["path"] == "found" for fact in calls[0]["responseFacts"])


def test_matter_tool_audit_vetoes_incomplete_raw_scan_before_hidden_signal() -> None:
    response = {
        "matter_id": "MAT-2026-104",
        "status": "Awaiting counterparty response",
        "next_deadline": "2026-08-05",
        "responsible_lawyer": "Dr Nora Keller",
        "debug": {f"ignored_{index}": "value" for index in range(300)},
        "result": {"found": {}},
    }
    token = begin_tool_call_collection()
    try:
        _record_tool_call(
            ToolDefinition(
                name="matter_lookup",
                description="Look up a matter",
                method="GET",
                url_template="https://example.test/matters",
            ),
            status="success",
            response_text=json.dumps(response),
        )
        calls = collect_tool_calls(token)
    except Exception:
        collect_tool_calls(token)
        raise

    assert calls[0].get("responseFactsTruncated") is not True
    assert calls[0]["hasNonaffirmativeLookupResult"] is True


@pytest.mark.no_gemini
def test_get_tool_collects_only_bounded_allowlisted_response_facts(monkeypatch):
    response_body = {
        "shipmentFound": True,
        "orderNumber": "ZF-10482",
        "trackingNumber": "DHL00340434161234567890",
        "carrier": "DHL",
        "status": "in_transit",
        "lastEvent": {
            "label": "Processed at destination facility",
            "location": "DHL Zurich Hub",
            "timestamp": "2026-07-17T08:42:00Z",
        },
        "estimatedDeliveryWindow": "next business day",
        "customer": {
            "name": "Private Customer",
            "email": "private@example.test",
            "status": "vip",
        },
        "authorizationToken": "never-persist-this",
        "headers": {"Authorization": "Bearer never-persist-this"},
        "reference": "ghp_QATESTCREDENTIAL1234567890",
        "result": "postgresql://qa-user:qa-password@example.test/db",
        "caseId": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJxYSJ9.signature123",
        "raw": "untrusted response content",
    }
    response = httpx.Response(
        200,
        json=response_body,
        request=httpx.Request("GET", "https://carrier.example.test/status"),
    )
    monkeypatch.setattr("automail.integrations.http_tool.httpx.request", lambda **_kwargs: response)
    tool = _make_http_tool(
        ToolDefinition(
            name="shipment-status",
            description="Look up shipment status",
            method="GET",
            url_template="https://carrier.example.test/status",
        ),
        sender_email="customer@example.test",
    )

    token = begin_tool_call_collection()
    try:
        result = tool.invoke({})
        current_calls = current_tool_calls()
        calls = collect_tool_calls(token)
    except Exception:
        collect_tool_calls(token)
        raise

    assert json.loads(result) == response_body
    assert current_calls == calls == [{
        "name": "shipment-status",
        "method": "GET",
        "status": "success",
        "responseFacts": [
            {"path": "shipmentFound", "value": True},
            {"path": "orderNumber", "value": "ZF-10482"},
            {"path": "trackingNumber", "value": "DHL00340434161234567890"},
            {"path": "carrier", "value": "DHL"},
            {"path": "status", "value": "in_transit"},
            {"path": "lastEvent.label", "value": "Processed at destination facility"},
            {"path": "lastEvent.location", "value": "DHL Zurich Hub"},
            {"path": "lastEvent.timestamp", "value": "2026-07-17T08:42:00Z"},
            {"path": "estimatedDeliveryWindow", "value": "next business day"},
        ],
    }]
    serialized = json.dumps(calls)
    assert "private@example.test" not in serialized
    assert "never-persist-this" not in serialized
    assert "ghp_QATESTCREDENTIAL" not in serialized
    assert "qa-password" not in serialized
    assert "eyJhbGci" not in serialized
    assert "untrusted response content" not in serialized


@pytest.mark.no_gemini
def test_get_tool_error_keeps_status_audit_without_response_evidence(monkeypatch):
    response = httpx.Response(
        401,
        json={
            "status": "unauthorized",
            "authorizationToken": "never-persist-this",
        },
        request=httpx.Request("GET", "https://carrier.example.test/status"),
    )
    monkeypatch.setattr("automail.integrations.http_tool.httpx.request", lambda **_kwargs: response)
    tool = _make_http_tool(
        ToolDefinition(
            name="shipment-status",
            description="Look up shipment status",
            method="GET",
            url_template="https://carrier.example.test/status",
        ),
        sender_email="customer@example.test",
    )

    token = begin_tool_call_collection()
    try:
        result = tool.invoke({})
        calls = collect_tool_calls(token)
    except Exception:
        collect_tool_calls(token)
        raise

    assert result.startswith("HTTP 401:")
    assert calls == [{"name": "shipment-status", "method": "GET", "status": "http_401"}]
    assert "never-persist-this" not in json.dumps(calls)


@pytest.mark.no_gemini
def test_tool_response_fact_collection_is_bounded(monkeypatch):
    response = httpx.Response(
        200,
        json={
            "status": "x" * 241,
            "shipments": [
                {"orderNumber": f"ZF-{index:05d}", "status": "in_transit"}
                for index in range(100)
            ],
        },
        request=httpx.Request("GET", "https://carrier.example.test/status"),
    )
    monkeypatch.setattr("automail.integrations.http_tool.httpx.request", lambda **_kwargs: response)
    tool = _make_http_tool(
        ToolDefinition(
            name="shipment-status",
            description="Look up shipment status",
            method="GET",
            url_template="https://carrier.example.test/status",
        ),
        sender_email="customer@example.test",
    )

    token = begin_tool_call_collection()
    try:
        tool.invoke({})
        call = collect_tool_calls(token)[0]
    except Exception:
        collect_tool_calls(token)
        raise

    assert len(call["responseFacts"]) == 24
    assert call["responseFactsTruncated"] is True
    assert all(len(str(fact["value"])) <= 240 for fact in call["responseFacts"])
    assert len(json.dumps(call["responseFacts"]).encode("utf-8")) <= 4_096
