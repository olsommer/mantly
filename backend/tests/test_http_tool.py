import json

import httpx
import pytest

from automail.integrations.http_tool import (
    ToolDefinition,
    _make_http_tool,
    begin_tool_call_collection,
    collect_tool_calls,
    current_tool_calls,
)


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
