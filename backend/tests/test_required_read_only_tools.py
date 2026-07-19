"""Deterministic postconditions for explicitly required runbook lookups."""

from __future__ import annotations

from typing import Any

from automail.models import ConcernRoute, Email, IntentProcessingOutput
from automail.pipeline.intent.agent import _execute_routed_concern
from automail.pipeline.intent.intents_factory import (
    get_intent_required_read_only_tools,
)


def _email() -> Email:
    return Email(
        id="s03-message",
        subject="Cancel Analytics, reduce seats, buy SSO Advanced, and refund",
        from_address="priya.nair@example.test",
        body=(
            "For ACME-4421: Can you cancel the Analytics add-on? Can you reduce "
            "us from 120 to 100 seats? Can you purchase SSO Advanced today? "
            "Can you refund the unused Analytics term?"
        ),
        attachments=[],
    )


def _configure_runbook(
    monkeypatch: Any,
    *,
    tools: list[dict[str, Any]],
    required_tools: list[str],
    actions: list[dict[str, Any]] | None = None,
) -> None:
    configured_actions = actions or []
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: tools,
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_required_read_only_tools",
        lambda *_args, **_kwargs: required_tools,
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_actions",
        lambda *_args, **_kwargs: configured_actions,
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_require_review",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_attachments",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.load_runtime_secrets",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_processing_agent",
        lambda *_args, **_kwargs: IntentProcessingOutput(
            summary="Prepared subscription changes without calling the lookup.",
            selected_action_names=[
                str(action.get("name") or "") for action in configured_actions
            ],
        ),
    )


def test_required_read_only_tool_contract_is_explicit_and_ordered(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "automail.pipeline.intent.intents_factory.get_intent_frontmatters",
        lambda intents_dir=None: [
            {
                "name": "saas-subscription-change",
                "required_read_only_tools": [
                    "fixture_saas_subscription_acme",
                    "fixture_saas_subscription_acme",
                    "second_lookup",
                ],
            }
        ],
    )

    assert get_intent_required_read_only_tools("SAAS-SUBSCRIPTION-CHANGE") == [
        "fixture_saas_subscription_acme",
        "second_lookup",
    ]


def test_s03_required_subscription_lookup_runs_when_model_skips_it(monkeypatch: Any) -> None:
    required_name = "fixture_saas_subscription_acme"
    monkeypatch.setenv("ENABLE_E2E_FIXTURES", "true")
    actions = [
        {"name": name, "label": name.replace("_", " ").title(), "type": "button"}
        for name in (
            "cancel_add_on",
            "reduce_seats",
            "purchase_add_on",
            "request_refund",
        )
    ]
    _configure_runbook(
        monkeypatch,
        tools=[
            {
                "name": required_name,
                "description": "Read the current ACME subscription.",
                "method": "GET",
                "urlTemplate": (
                    "https://api.mantly.io/demo/e2e/tool/"
                    "saas-support/subscription_lookup"
                ),
                "body": {"account_id": "ACME-4421"},
                "inputSchema": [],
            }
        ],
        required_tools=[required_name],
        actions=actions,
    )
    outcome = _execute_routed_concern(
        "s03-subscription-change",
        ConcernRoute(
            summary="Cancel, reduce, purchase, and refund",
            source_text=_email().body,
            intent_name="saas-subscription-change",
        ),
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.tool_name for item in outcome.tool_evidence] == [required_name]
    evidence_values = {str(fact.value) for fact in outcome.verified_facts}
    assert {
        "plan: Enterprise",
        "seats: 120",
        "add_ons.Analytics: active",
        "add_ons.SSO Advanced: inactive",
    } <= evidence_values
    assert [action.name for action in outcome.actions] == [
        "cancel_add_on",
        "reduce_seats",
        "purchase_add_on",
        "request_refund",
    ]


def test_optional_read_only_tool_is_not_auto_executed(monkeypatch: Any) -> None:
    _configure_runbook(
        monkeypatch,
        tools=[
            {
                "name": "optional_lookup",
                "description": "Use only when this concern needs it.",
                "method": "GET",
                "urlTemplate": "https://tools.example.test/optional",
                "body": {},
                "inputSchema": [],
            }
        ],
        required_tools=[],
    )
    requests: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "automail.integrations.http_tool.httpx.request",
        lambda **kwargs: requests.append(kwargs),
    )

    outcome = _execute_routed_concern(
        "optional-lookup",
        ConcernRoute(
            summary="Explain policy",
            source_text="Explain the policy without a live lookup.",
            intent_name="policy-question",
        ),
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert requests == []
    assert outcome.tool_evidence == []


def test_required_contract_never_auto_executes_post_tool(monkeypatch: Any) -> None:
    tool_name = "mutating_tool"
    _configure_runbook(
        monkeypatch,
        tools=[
            {
                "name": tool_name,
                "description": "Mutates external state.",
                "method": "POST",
                "urlTemplate": "https://tools.example.test/mutate",
                "body": {},
                "inputSchema": [],
            }
        ],
        required_tools=[tool_name],
    )
    requests: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "automail.integrations.http_tool.httpx.request",
        lambda **kwargs: requests.append(kwargs),
    )

    outcome = _execute_routed_concern(
        "mutating-tool",
        ConcernRoute(
            summary="Do not mutate",
            source_text="Prepare this request for review.",
            intent_name="mutation-review",
        ),
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert requests == []
    assert outcome.tool_evidence == []
    assert outcome.requires_human is True
    assert any(tool_name in item for item in outcome.missing_information)
    assert any("Do not state current external state" in item for item in outcome.reply_requirements)
