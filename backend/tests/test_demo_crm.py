"""Tests for the seeded demo CRM endpoint used by customer-identification."""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from automail.core.auth import create_token
from automail.integrations.http_tool import ToolDefinition as IntentToolDefinition
from automail.integrations.http_tool import _make_http_tool as make_intent_http_tool
from automail.main import create_app
from automail.models import AgentResponse, GeneratedAttachment
from automail.pipeline.identity.agent import _make_http_tool
from automail.pipeline.identity.tools_factory import ToolDefinition


@pytest.fixture
def demo_client(monkeypatch):
    monkeypatch.setenv("ENABLE_DEMO_MODE", "true")
    return TestClient(create_app())


@pytest.fixture
def saas_demo_client(monkeypatch):
    monkeypatch.setenv("IS_SAAS", "true")
    monkeypatch.setenv("ENABLE_DEMO_MODE", "false")
    monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", True)
    return TestClient(create_app())


@pytest.mark.no_gemini
def test_demo_routes_are_disabled_by_default(client):
    response = client.get(
        "/demo/crm",
        params={"sender_email": "sarah.keller@alpina-claims.ch"},
    )

    assert response.status_code == 404


@pytest.mark.no_gemini
def test_demo_crm_returns_seeded_customer_record(demo_client):
    response = demo_client.get(
        "/demo/crm",
        params={"sender_email": "sarah.keller@alpina-claims.ch"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "customerFound": True,
        "lookupEmail": "sarah.keller@alpina-claims.ch",
        "customerId": "crm_1001",
        "fullName": "Sarah Keller",
        "organization": "Alpina Claims AG",
        "status": "active",
        "segment": "enterprise",
        "preferredLanguage": "de",
        "openMatters": [
            "MOTOR-2026-0142",
            "MOTOR-2026-0188",
        ],
        "notes": [
            "Key fleet customer with dedicated claims contact.",
            "Prefers updates by email in German.",
        ],
    }


@pytest.mark.no_gemini
def test_demo_crm_returns_fasser_lead_record(demo_client):
    response = demo_client.get(
        "/demo/crm",
        params={"sender_email": "martin.fasser@fasser-treuhand.ch"},
    )

    assert response.status_code == 200
    assert response.json()["customerFound"] is True
    assert response.json()["customerId"] == "crm_sro_2001"
    assert response.json()["fullName"] == "Martin Fasser"
    assert response.json()["segment"] == "fiduciary-sro"
    assert response.json()["openMatters"] == ["KYC-SRO-2026-014"]


@pytest.mark.no_gemini
def test_demo_crm_returns_zenfulfillment_merchant_record(demo_client):
    response = demo_client.get(
        "/demo/crm",
        params={"sender_email": "operations@shop-demo.de"},
    )

    assert response.status_code == 200
    assert response.json()["customerFound"] is True
    assert response.json()["customerId"] == "crm_zen_3001"
    assert response.json()["organization"] == "Shop Demo GmbH"
    assert response.json()["segment"] == "merchant"
    assert response.json()["openMatters"] == ["OPS-2026-4412"]


@pytest.mark.no_gemini
def test_demo_crm_returns_not_found_payload_for_unknown_email(demo_client):
    response = demo_client.get(
        "/demo/crm",
        params={"sender_email": "unknown@example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "customerFound": False,
        "lookupEmail": "unknown@example.com",
        "customerId": None,
        "fullName": None,
        "organization": None,
        "status": None,
        "segment": None,
        "preferredLanguage": None,
        "openMatters": [],
        "notes": [],
    }


@pytest.mark.no_gemini
def test_demo_crm_requires_sender_email_query_param(demo_client):
    response = demo_client.get("/demo/crm")

    assert response.status_code == 422


@pytest.mark.no_gemini
def test_demo_shipment_status_returns_seeded_record(demo_client):
    response = demo_client.get(
        "/demo/logistics/shipment-status",
        params={
            "sender_email": "lena.schmidt@example-shop.de",
            "order_number": "ZF-10482",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["shipmentFound"] is True
    assert payload["lookup"]["matchedBy"] == "order_number"
    assert payload["orderNumber"] == "ZF-10482"
    assert payload["carrier"] == "DHL"
    assert payload["status"] == "in_transit"
    assert payload["lastEvent"]["label"] == "Sendung im Ziel-Paketzentrum bearbeitet"


@pytest.mark.no_gemini
def test_demo_shipment_status_returns_missing_identifier_payload(demo_client):
    response = demo_client.get(
        "/demo/logistics/shipment-status",
        params={"sender_email": "kunde@example-shop.de"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "shipmentFound": False,
        "lookup": {
            "senderEmail": "kunde@example-shop.de",
            "orderNumber": "",
            "trackingNumber": "",
            "matchedBy": None,
        },
        "status": "missing_identifier",
    }


@pytest.mark.no_gemini
def test_intent_http_tool_resolves_demo_shipment_status_in_process():
    tool = make_intent_http_tool(
        IntentToolDefinition(
            name="lookup-shipment-status",
            description="Look up shipment status in the logistics demo system.",
            method="GET",
            url_template="https://api.mantly.io/demo/logistics/shipment-status?sender_email={sender_email}",
            input_schema=[
                {
                    "key": "order_number",
                    "type": "string",
                    "required": False,
                    "description": "Zenfulfillment order number.",
                }
            ],
        ),
        sender_email="lena.schmidt@example-shop.de",
    )

    result = json.loads(tool.invoke({"order_number": "ZF-10482"}))

    assert result["shipmentFound"] is True
    assert result["lookup"]["senderEmail"] == "lena.schmidt@example-shop.de"
    assert result["orderNumber"] == "ZF-10482"
    assert result["status"] == "in_transit"


@pytest.mark.no_gemini
def test_saas_demo_tenant_can_access_demo_crm(saas_demo_client, monkeypatch):
    monkeypatch.setattr("automail.db.pocketbase.client.get_tenant_account_type", lambda tenant_id: "demo")
    token = create_token(
        "demo-user",
        "demo@example.com",
        "tenant-demo",
        True,
        tenant_account_type="demo",
    )

    response = saas_demo_client.get(
        "/demo/crm",
        params={"sender_email": "sarah.keller@alpina-claims.ch"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["customerFound"] is True


@pytest.mark.no_gemini
def test_saas_normal_tenant_cannot_access_demo_crm(saas_demo_client, monkeypatch):
    monkeypatch.setattr("automail.db.pocketbase.client.get_tenant_account_type", lambda tenant_id: "normal")
    token = create_token("user", "user@example.com", "tenant-normal", True)

    response = saas_demo_client.get(
        "/demo/crm",
        params={"sender_email": "sarah.keller@alpina-claims.ch"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


@pytest.mark.no_gemini
def test_identity_http_tool_can_call_demo_crm_endpoint(demo_client, monkeypatch):
    def fake_request(method: str, url: str, **kwargs) -> httpx.Response:
        split = urlsplit(url)
        query_params = dict(parse_qsl(split.query))
        extra_params = kwargs.get("params") or {}
        query_params.update({key: str(value) for key, value in extra_params.items()})

        response = demo_client.request(
            method,
            split.path,
            params=query_params,
            json=kwargs.get("json"),
            headers=kwargs.get("headers"),
        )
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers=dict(response.headers),
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr("automail.pipeline.identity.agent.httpx.request", fake_request)

    tool = _make_http_tool(
        ToolDefinition(
            name="customer-lookup",
            description="Look up customer records in the demo CRM.",
            method="GET",
            url_template="https://example.test/demo/crm?sender_email={sender_email}",
        )
    )

    result = tool.invoke({"sender_email": "martina.hug@wysslaw.ch"})

    assert json.loads(result) == {
        "customerFound": True,
        "lookupEmail": "martina.hug@wysslaw.ch",
        "customerId": "crm_1003",
        "fullName": "Martina Hug",
        "organization": "Wyss Law Partners",
        "status": "active",
        "segment": "referral",
        "preferredLanguage": "de",
        "openMatters": [],
        "notes": [
            "Referral partner account used for collaboration tests.",
        ],
    }


@pytest.mark.no_gemini
def test_demo_process_start_returns_mock_started_payload(demo_client):
    response = demo_client.post(
        "/demo/process-start",
        json={
            "chatId": "chat_123",
            "process": "Open onboarding process",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "action": "process-start",
        "status": "started",
        "chatId": "chat_123",
        "process": "Open onboarding process",
        "processId": "process_chat_123",
        "received": {
            "chatId": "chat_123",
            "process": "Open onboarding process",
        },
    }


@pytest.mark.no_gemini
def test_demo_process_start_uses_action_label_when_process_missing(demo_client):
    response = demo_client.post(
        "/demo/process-start",
        json={
            "chatId": "chat_123",
            "actionName": "process-start",
            "actionLabel": "Start Claim Intake",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "action": "process-start",
        "status": "started",
        "chatId": "chat_123",
        "process": "Start Claim Intake",
        "processId": "process_chat_123",
        "received": {
            "chatId": "chat_123",
            "actionName": "process-start",
            "actionLabel": "Start Claim Intake",
        },
    }


@pytest.mark.no_gemini
def test_demo_update_title_returns_mock_updated_payload(demo_client):
    response = demo_client.post(
        "/demo/update-title",
        json={
            "chatId": "chat_123",
            "title": "Claims intake for Alpina Claims AG",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "action": "update-title",
        "status": "updated",
        "chatId": "chat_123",
        "title": "Claims intake for Alpina Claims AG",
        "received": {
            "chatId": "chat_123",
            "title": "Claims intake for Alpina Claims AG",
        },
    }


@pytest.mark.no_gemini
def test_demo_update_title_accepts_claim_title_payload(demo_client):
    response = demo_client.post(
        "/demo/update-title",
        json={
            "chatId": "chat_123",
            "claim_title": "Parkschaden am hinteren Stossfaenger",
        },
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Parkschaden am hinteren Stossfaenger"
    assert response.json()["received"] == {
        "chatId": "chat_123",
        "title": "Parkschaden am hinteren Stossfaenger",
    }


@pytest.mark.no_gemini
def test_demo_process_start_requires_process_field(demo_client):
    response = demo_client.post(
        "/demo/process-start",
        json={"chatId": "chat_123"},
    )

    assert response.status_code == 422


@pytest.mark.no_gemini
def test_demo_update_title_requires_title_field(demo_client):
    response = demo_client.post(
        "/demo/update-title",
        json={"chatId": "chat_123"},
    )

    assert response.status_code == 422


@pytest.mark.no_gemini
def test_load_attachment_files_reads_generated_tool_attachment():
    from automail.api.attachments import load_attachment_files

    response = AgentResponse(
        response_text="Attached.",
        activated_intent="gruene-karte-beauftragen",
        response_attachments=["gruene-karte-max-keller.pdf"],
        generated_attachments=[
            GeneratedAttachment(
                filename="gruene-karte-max-keller.pdf",
                content_base64="ZGVtbw==",
                content_type="application/pdf",
                size=4,
                source_tool="request_green_card",
            )
        ],
    )

    attachments = load_attachment_files(response)

    assert attachments == [
        {
            "filename": "gruene-karte-max-keller.pdf",
            "content_base64": "ZGVtbw==",
            "content_type": "application/pdf",
            "size": 4,
            "source_tool": "request_green_card",
        }
    ]


@pytest.mark.no_gemini
def test_load_attachment_files_dedupes_generated_tool_attachment():
    from automail.api.attachments import load_attachment_files

    response = AgentResponse(
        response_text="Attached.",
        activated_intent="gruene-karte-beauftragen",
        response_attachments=[
            "gruene-karte-max-keller.pdf",
            "gruene-karte-max-keller.pdf",
        ],
        generated_attachments=[
            GeneratedAttachment(
                filename="gruene-karte-max-keller.pdf",
                content_base64="ZGVtbw==",
                content_type="application/pdf",
                size=4,
                source_tool="request_green_card",
            )
        ],
    )

    attachments = load_attachment_files(response)

    assert len(attachments or []) == 1
    assert attachments[0]["filename"] == "gruene-karte-max-keller.pdf"
