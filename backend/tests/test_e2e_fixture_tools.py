"""Tests for read-only hosted E2E persona tool fixtures."""

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from automail.demo.e2e_fixtures import (
    E2EFixtureManifestError,
    E2EFixtureNotFound,
    _fixture_evidence,
    lookup_e2e_tool_fixture,
    merge_e2e_tool_input,
)
from automail.integrations.http_tool import (
    ToolDefinition,
    _make_http_tool,
    begin_tool_call_collection,
    collect_tool_calls,
)
from automail.main import create_app


@pytest.mark.no_gemini
def test_exact_fixture_lookup_returns_detached_static_result():
    first = lookup_e2e_tool_fixture(
        "fulfillment",
        "shipment_lookup",
        {"order_number": "ZF-10482"},
    )
    first["status"] = "mutated"

    second = lookup_e2e_tool_fixture(
        "fulfillment",
        "shipment_lookup",
        {"order_number": "ZF-10482"},
    )

    assert second["found"] is True
    assert second["status"] == "in_transit"
    assert second["tracking_number"] == "DHL00340434161234567890"


@pytest.mark.no_gemini
def test_fixture_lookup_requires_exact_typed_input():
    with pytest.raises(E2EFixtureNotFound, match="No exact E2E fixture input match"):
        lookup_e2e_tool_fixture(
            "fulfillment",
            "shipment_lookup",
            {"order_number": "ZF-10482", "unexpected": True},
        )

    with pytest.raises(E2EFixtureNotFound, match="Invalid E2E persona id"):
        lookup_e2e_tool_fixture(
            "../fulfillment",
            "shipment_lookup",
            {"order_number": "ZF-10482"},
        )


@pytest.mark.no_gemini
def test_repeated_query_parameters_remain_a_list():
    assert merge_e2e_tool_input(
        [
            ("parties", "Helvetia Systems AG"),
            ("parties", "Helvetia Holdings SA"),
        ]
    ) == {"parties": ["Helvetia Systems AG", "Helvetia Holdings SA"]}


@pytest.mark.no_gemini
def test_fixture_evidence_filters_credentials_hidden_under_safe_keys():
    evidence = _fixture_evidence(
        {
            "status": "active",
            "reference": "ghp_QATESTCREDENTIAL1234567890",
            "result": "recent_change: client_secret=qa-secret-value",
            "case_id": "AKIAABCDEFGHIJKLMNOP",
        }
    )

    assert evidence == ["status: active"]


@pytest.mark.no_gemini
def test_manifest_reader_uses_safe_yaml_loader(tmp_path: Path):
    manifest = tmp_path / "unsafe.yaml"
    manifest.write_text(
        "!!python/object/apply:builtins.eval ['1 + 1']\n",
        encoding="utf-8",
    )

    with pytest.raises(E2EFixtureManifestError, match="Unable to safely read"):
        lookup_e2e_tool_fixture(
            "fulfillment",
            "shipment_lookup",
            {"order_number": "ZF-10482"},
            personas_dir=tmp_path,
        )


@pytest.mark.no_gemini
def test_hosted_fixture_tool_runs_in_process_without_public_http(monkeypatch):
    monkeypatch.setenv("ENABLE_E2E_FIXTURES", "true")
    def unexpected_http(**_kwargs):
        raise AssertionError("hosted E2E fixture must not use public HTTP")

    monkeypatch.setattr("automail.integrations.http_tool.httpx.request", unexpected_http)
    tool = _make_http_tool(
        ToolDefinition(
            name="lookup-matter",
            description="Look up a deterministic legal matter fixture.",
            method="GET",
            url_template="https://api.mantly.io/demo/e2e/tool/lawyer/matter_lookup",
            input_schema=[
                {
                    "key": "matter_id",
                    "type": "string",
                    "required": True,
                    "description": "Synthetic matter identifier.",
                }
            ],
        ),
        sender_email="synthetic@example.test",
    )

    result = json.loads(tool.invoke({"matter_id": "MAT-2026-104"}))

    evidence = result.pop("fixture_evidence")
    assert result == {
        "status": "Awaiting counterparty response",
        "next_deadline": "2026-08-05",
        "responsible_lawyer": "Dr Nora Keller",
    }
    assert "responsible_lawyer: Dr Nora Keller" in evidence["result"]


@pytest.mark.no_gemini
def test_hosted_fixture_runtime_is_opt_in_and_never_falls_through(monkeypatch):
    monkeypatch.setenv("ENABLE_E2E_FIXTURES", "false")
    monkeypatch.setattr(
        "automail.integrations.http_tool.httpx.request",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("disabled E2E fixtures must not fall through to HTTP")
        ),
    )
    tool = _make_fixture_tool(
        "lawyer",
        "matter_lookup",
        [{"key": "matter_id", "type": "string", "required": True}],
    )
    token = begin_tool_call_collection()
    try:
        result = tool.invoke({"matter_id": "MAT-2026-104"})
        calls = collect_tool_calls(token)
    except Exception:
        collect_tool_calls(token)
        raise

    assert result == "E2E fixture lookup failed: E2E fixture runtime is disabled"
    assert calls[0]["status"] == "fixture_error"


def _make_fixture_tool(
    persona_id: str,
    tool_name: str,
    input_schema: list[dict[str, object]],
):
    return _make_http_tool(
        ToolDefinition(
            name=f"fixture-{persona_id}-{tool_name}",
            description="Look up deterministic synthetic E2E fixture data.",
            method="GET",
            url_template=(
                f"https://api.mantly.io/demo/e2e/tool/{persona_id}/{tool_name}"
            ),
            input_schema=input_schema,
        ),
        sender_email="synthetic@example.test",
    )


def _evidence_values(call: dict[str, object]) -> list[str]:
    facts = call.get("responseFacts", [])
    assert isinstance(facts, list)
    return [
        fact["value"]
        for fact in facts
        if isinstance(fact, dict)
        and str(fact.get("path", "")).startswith("fixture_evidence.result.")
        and isinstance(fact.get("value"), str)
    ]


@pytest.mark.no_gemini
def test_saas_role_and_incident_evidence_survives_response_fact_filtering(monkeypatch):
    monkeypatch.setenv("ENABLE_E2E_FIXTURES", "true")
    account_tool = _make_fixture_tool(
        "saas-support",
        "account_lookup",
        [{"key": "account_id", "type": "string", "required": True}],
    )
    incident_tool = _make_fixture_tool(
        "saas-support",
        "service_status_lookup",
        [{"key": "incident_id", "type": "string", "required": True}],
    )
    token_tool = _make_fixture_tool(
        "saas-support",
        "api_token_lookup",
        [
            {"key": "account_id", "type": "string", "required": True},
            {"key": "fingerprint", "type": "string", "required": True},
        ],
    )

    collection_token = begin_tool_call_collection()
    try:
        account = json.loads(account_tool.invoke({"account_id": "ACME-4421"}))
        incident = json.loads(incident_tool.invoke({"incident_id": "INC-204"}))
        token_result = json.loads(
            token_tool.invoke(
                {
                    "account_id": "ACME-4421",
                    "fingerprint": "sha256:qa-7f2a91cd",
                }
            )
        )
        calls = collect_tool_calls(collection_token)
    except Exception:
        collect_tool_calls(collection_token)
        raise

    assert account["requester_roles"]["priya.nair@example.test"] == "Billing Admin"
    assert incident["affected_region"] == "EU"
    assert incident["affected_service"] == "authentication"
    assert token_result["last_four"] == "9QAX"
    assert "requester_roles.priya.nair@example.test: Billing Admin" in _evidence_values(
        calls[0]
    )
    assert "affected_region: EU" in _evidence_values(calls[1])
    assert "affected_service: authentication" in _evidence_values(calls[1])
    persisted = json.dumps(calls)
    assert "sha256:qa-7f2a91cd" not in persisted
    assert "9QAX" not in persisted
    assert "last_four" not in persisted


@pytest.mark.no_gemini
def test_fulfillment_event_and_location_survive_response_fact_filtering(monkeypatch):
    monkeypatch.setenv("ENABLE_E2E_FIXTURES", "true")
    tool = _make_fixture_tool(
        "fulfillment",
        "shipment_lookup",
        [{"key": "order_number", "type": "string", "required": True}],
    )

    collection_token = begin_tool_call_collection()
    try:
        response = json.loads(tool.invoke({"order_number": "ZF-10482"}))
        calls = collect_tool_calls(collection_token)
    except Exception:
        collect_tool_calls(collection_token)
        raise

    assert response["last_event"] == "Sendung im Ziel-Paketzentrum bearbeitet"
    assert response["last_location"] == "DHL Paketzentrum Ruedersdorf"
    evidence = _evidence_values(calls[0])
    assert "last_event: Sendung im Ziel-Paketzentrum bearbeitet" in evidence
    assert "last_location: DHL Paketzentrum Ruedersdorf" in evidence


@pytest.mark.no_gemini
def test_string_array_input_invokes_exact_conflict_fixture(monkeypatch):
    monkeypatch.setenv("ENABLE_E2E_FIXTURES", "true")
    tool = _make_fixture_tool(
        "lawyer",
        "conflict_check_lookup",
        [{"key": "parties", "type": "array", "required": True}],
    )

    response = json.loads(
        tool.invoke(
            {"parties": ["Helvetia Systems AG", "Helvetia Holdings SA"]}
        )
    )

    assert response["status"] == "requires_human_review"
    assert response["cleared"] is False
    assert response["reference"] == "CONFLICT-QA-101"


@pytest.mark.no_gemini
def test_hosted_fixture_tool_fails_closed_on_unknown_input(monkeypatch):
    monkeypatch.setenv("ENABLE_E2E_FIXTURES", "true")
    def unexpected_http(**_kwargs):
        raise AssertionError("unknown fixture input must not fall through to public HTTP")

    monkeypatch.setattr("automail.integrations.http_tool.httpx.request", unexpected_http)
    tool = _make_http_tool(
        ToolDefinition(
            name="lookup-order",
            description="Look up a deterministic order fixture.",
            method="GET",
            url_template="https://api.mantly.io/demo/e2e/tool/fulfillment/order_lookup",
            input_schema=[
                {
                    "key": "order_number",
                    "type": "string",
                    "required": True,
                    "description": "Synthetic order identifier.",
                }
            ],
        ),
        sender_email="synthetic@example.test",
    )

    token = begin_tool_call_collection()
    try:
        result = tool.invoke({"order_number": "UNKNOWN"})
        calls = collect_tool_calls(token)
    except Exception:
        collect_tool_calls(token)
        raise

    assert result == (
        "E2E fixture lookup failed: No exact E2E fixture input match for "
        "fulfillment/order_lookup"
    )
    assert calls == [
        {
            "name": "lookup-order",
            "method": "GET",
            "status": "fixture_not_found",
        }
    ]


@pytest.mark.no_gemini
def test_demo_fixture_route_is_protected_and_reports_not_found(monkeypatch):
    monkeypatch.setenv("ENABLE_DEMO_MODE", "true")
    monkeypatch.setenv("ENABLE_E2E_FIXTURES", "true")
    demo_client = TestClient(create_app())

    found = demo_client.get(
        "/demo/e2e/tool/saas-support/invoice_lookup",
        params={"invoice_id": "INV-9012"},
    )
    missing = demo_client.get(
        "/demo/e2e/tool/saas-support/invoice_lookup",
        params={"invoice_id": "UNKNOWN"},
    )

    assert found.status_code == 200
    assert found.json()["amount"] == 12480
    assert missing.status_code == 404
    assert missing.json() == {
        "detail": "No exact E2E fixture input match for saas-support/invoice_lookup"
    }

    monkeypatch.setenv("ENABLE_DEMO_MODE", "false")
    disabled_client = TestClient(create_app())
    disabled = disabled_client.get(
        "/demo/e2e/tool/saas-support/invoice_lookup",
        params={"invoice_id": "INV-9012"},
    )
    assert disabled.status_code == 404
