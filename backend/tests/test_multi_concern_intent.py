"""Focused tests for multi-concern runbook execution."""

import json
from types import SimpleNamespace

import pytest

from automail.api.attachments import load_attachment_files
from automail.integrations.http_tool import (
    ToolDefinition,
    _capture_generated_file,
    _record_tool_call,
    begin_generated_attachment_collection,
    begin_tool_call_collection,
    collect_generated_attachments,
    collect_tool_calls,
    current_generated_attachments,
    current_tool_calls,
)
from automail.models import (
    AgentResponse,
    ConcernRoute,
    Email,
    IdentityResult,
    IntentAction,
    IntentProcessingOutput,
    IntentReviewOutput,
    PhishingResult,
    PromptInjectionResult,
    VerifiedFact,
)
from automail.pipeline import orchestrator
from automail.pipeline.intent.agent import (
    _apply_deterministic_action_eligibility,
    _build_process_user_message,
    _concern_id,
    _concern_processing_email,
    _execute_routed_concern,
    _route_concerns_call_is_invalid,
    run_intent_agent,
)
from automail.pipeline.response.composer import _available_attachments
from automail.pipeline.response.prompt_factory import create_response_user_prompt


def _email() -> Email:
    return Email(
        id="message-42",
        subject="Cancel and buy",
        from_address="customer@example.test",
        body="Cancel contract C-1. I also want to buy three XYZ units.",
        attachments=[],
    )


def _base_stubs(monkeypatch) -> None:
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_known_intent_names",
        lambda intents_dir=None: {"cancel-contract", "buy-product"},
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_require_review", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_tools", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_attachments", lambda *_args, **_kwargs: [])


def test_processing_prompt_requires_exact_materially_applicable_action_selection() -> None:
    prompt = _build_process_user_message(
        _email(),
        None,
        [
            IntentAction(
                name="delete_workspace",
                label="Delete workspace",
                description="Delete a workspace after authority verification",
            ),
        ],
    )

    assert "selected_action_names" in prompt
    assert "exact configured action names" in prompt
    assert "prerequisites fail" in prompt
    assert "lacks sufficient authority" in prompt
    assert "does not block an internal defensive or review action" in prompt
    assert "security or safety incident" in prompt
    assert "remains pending human approval" in prompt
    assert "Return an empty array" in prompt


@pytest.mark.parametrize(
    ("allowed", "expected_names"),
    [
        pytest.param(False, ["request_carrier_redirect"], id="ineligible-direct-change"),
        pytest.param(
            True,
            ["request_address_change", "request_carrier_redirect"],
            id="eligible-direct-change",
        ),
    ],
)
def test_verified_address_change_eligibility_filters_only_direct_change(
    allowed: bool,
    expected_names: list[str],
) -> None:
    actions = [
        IntentAction(name="request_address_change", label="Request address change"),
        IntentAction(name="request_carrier_redirect", label="Request carrier redirect"),
    ]
    facts = [
        VerifiedFact(
            path="address_change_allowed",
            value=allowed,
            source="tool:shipment_lookup",
        ),
        VerifiedFact(path="status", value="in_transit", source="tool:shipment_lookup"),
    ]

    filtered = _apply_deterministic_action_eligibility(actions, facts)

    assert [action.name for action in filtered] == expected_names


def test_verified_address_change_ineligibility_preserves_unrelated_actions() -> None:
    actions = [
        IntentAction(name="request_address_change", label="Request address change"),
        IntentAction(name="request_refund", label="Request refund"),
    ]
    facts = [
        VerifiedFact(
            path="fixture_evidence.result.0",
            value="address_change_allowed: false",
            source="tool:shipment_lookup",
        )
    ]

    filtered = _apply_deterministic_action_eligibility(actions, facts)

    assert [action.name for action in filtered] == ["request_refund"]


def test_e05_verified_in_transit_state_suppresses_direct_address_change(monkeypatch) -> None:
    _base_stubs(monkeypatch)
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_actions",
        lambda *_args, **_kwargs: [
            {
                "name": "request_address_change",
                "label": "Request address change",
                "type": "button",
            },
            {
                "name": "request_carrier_redirect",
                "label": "Request carrier redirect",
                "type": "button",
            },
        ],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "shipment_lookup", "method": "GET"}],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )

    def process(*_args, **_kwargs):
        _record_tool_call(
            ToolDefinition(
                name="shipment_lookup",
                description="Lookup shipment",
                method="GET",
                url_template="https://example.test/shipments",
            ),
            status="success",
            response_text=json.dumps(
                {
                    "found": True,
                    "status": "in_transit",
                    "address_change_allowed": False,
                }
            ),
        )
        return IntentProcessingOutput(
            summary="Direct change unavailable; redirect prepared.",
            selected_action_names=[
                "request_address_change",
                "request_carrier_redirect",
            ],
        )

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)
    route = ConcernRoute(
        summary="Address change",
        source_text="Change the address and request a redirect if already shipped.",
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "e05-address-change",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [action.name for action in outcome.actions] == ["request_carrier_redirect"]
    assert [action.name for action in outcome.action_outcomes] == [
        "request_carrier_redirect"
    ]
    assert any(
        fact.path == "address_change_allowed" and fact.value is False
        for fact in outcome.verified_facts
    )


@pytest.mark.parametrize(
    ("selection_mode", "selected_action_names", "expected_action_names", "expect_review"),
    [
        pytest.param("legacy", None, [], True, id="missing-selection-fails-closed"),
        pytest.param("explicit", [], [], False, id="explicit-empty-suppresses-all"),
        pytest.param(
            "explicit",
            ["upgrade_plan", "unknown_action", "upgrade_plan"],
            [],
            True,
            id="unknown-selection-fails-closed",
        ),
        pytest.param(
            "explicit",
            ["upgrade_plan", "upgrade_plan"],
            ["upgrade_plan"],
            False,
            id="duplicate-known-selection-is-collapsed",
        ),
    ],
)
def test_runbook_action_selection_reaches_grounding_and_approval_proposals(
    monkeypatch: pytest.MonkeyPatch,
    selection_mode: str,
    selected_action_names: list[str] | None,
    expected_action_names: list[str],
    expect_review: bool,
) -> None:
    from automail.db.pocketbase import issues

    _base_stubs(monkeypatch)
    route = ConcernRoute(
        summary="Workspace request",
        source_text="Please handle my workspace request.",
        intent_name="cancel-contract",
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: ([route], None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_actions",
        lambda *_args, **_kwargs: [
            {
                "name": "delete_workspace",
                "label": "Delete workspace",
                "type": "button",
                "webhook": "https://example.test/delete",
            },
            {
                "name": "upgrade_plan",
                "label": "Upgrade plan",
                "type": "button",
                "webhook": "https://example.test/upgrade",
            },
        ],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.intents_factory.get_intent_response_rules",
        lambda *_args, **_kwargs: [],
    )

    def process(*_args, **_kwargs):
        if selection_mode == "legacy":
            return IntentProcessingOutput(summary="Processed legacy output")
        return IntentProcessingOutput(
            summary="Processed explicit selection",
            selected_action_names=selected_action_names,
        )

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)

    result, response = run_intent_agent(_email())

    assert (response is not None and response.requires_human) is expect_review
    assert [action.name for action in result.actions] == expected_action_names
    assert [action.name for action in result.concerns[0].actions] == expected_action_names
    assert [action.name for action in result.concerns[0].action_outcomes] == expected_action_names
    if expect_review:
        assert result.concerns[0].requires_human is True
        assert "selection" in (result.concerns[0].requires_human_reason or "").lower()

    proposals = issues._runbook_action_proposals(
        result.model_dump(mode="json", by_alias=True),
    )
    assert [proposal["name"] for proposal in proposals] == expected_action_names

    grounding_prompt = create_response_user_prompt(_email(), intent_result=result)
    for action_name in ("delete_workspace", "upgrade_plan"):
        assert (f'<action name="{action_name}"' in grounding_prompt) == (
            action_name in expected_action_names
        )


def test_router_rejects_known_intent_without_any_concern_or_obligation_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._find_router_tool_call",
        lambda *_args, **_kwargs: {
            "concerns": [
                {
                    "intent_name": "refund",
                    "summary": "",
                    "source_text": "",
                    "answer_obligations": [],
                    "confidence": 1,
                }
            ]
        },
    )

    assert _route_concerns_call_is_invalid([object()]) is True


@pytest.mark.parametrize("invisible", ["\u200b", "\u200c", "\ufeff", "\u2060", "\x00"])
def test_router_rejects_control_or_format_only_concern_text(
    monkeypatch: pytest.MonkeyPatch,
    invisible: str,
) -> None:
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._find_router_tool_call",
        lambda *_args, **_kwargs: {
            "concerns": [
                {
                    "intent_name": "refund",
                    "summary": invisible,
                    "source_text": invisible,
                    "answer_obligations": [invisible],
                    "confidence": 1,
                }
            ]
        },
    )

    assert _route_concerns_call_is_invalid([object()]) is True


def _record_test_tool(intent_name: str) -> None:
    _record_tool_call(
        ToolDefinition(
            name=f"lookup-{intent_name}",
            description="Lookup",
            method="GET",
            url_template="https://example.test/lookup",
        ),
        status="success",
        response_text=json.dumps({"status": f"status-{intent_name}"}),
    )


def _record_test_attachment(intent_name: str) -> None:
    _record_named_test_attachment(f"{intent_name}.pdf", "cGRm", intent_name)


def _record_named_test_attachment(
    filename: str,
    content_base64: str,
    source: str,
) -> None:
    _capture_generated_file(
        ToolDefinition(
            name=f"file-{source}",
            description="Generate file",
            method="POST",
            url_template="https://example.test/file",
            expects_file=True,
            file_name_path="filename",
            file_content_type_path="contentType",
            file_content_base64_path="contentBase64",
        ),
        json.dumps(
            {
                "filename": filename,
                "contentType": "application/pdf",
                "contentBase64": content_base64,
            }
        ),
    )


def test_multi_concern_routes_execute_independently_and_keep_primary_fields(monkeypatch):
    _base_stubs(monkeypatch)
    routes = [
        ConcernRoute(
            summary="Cancel contract C-1",
            source_text="Cancel contract C-1.",
            answer_obligations=[
                "Confirm whether contract C-1 can be cancelled.",
                "Explain when cancellation becomes effective.",
            ],
            intent_name="cancel-contract",
            confidence=0.98,
        ),
        ConcernRoute(
            summary="Buy three XYZ units",
            source_text="I also want to buy three XYZ units.",
            intent_name="buy-product",
            confidence=0.94,
        ),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent", lambda *_args, **_kwargs: (routes, None)
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_actions",
        lambda intent_name, **_kwargs: [
            {
                "name": f"prepare-{intent_name}",
                "label": f"Prepare {intent_name}",
                "type": "button",
            }
        ],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda intent_name, **_kwargs: {
            "enabled": True,
            "response_rules": [f"Explain {intent_name} state."],
            "required_guidance": [f"Give required guidance for {intent_name}."],
        },
    )
    calls: list[tuple[str, str, str]] = []

    def process(intent_name, _actions, email, *_args, **_kwargs):
        calls.append((intent_name, email.subject, email.body))
        return IntentProcessingOutput(
            summary=f"Prepared {intent_name}",
            selected_action_names=[action.name for action in _actions],
            reply_requirements=[f"Cover {intent_name}."],
        )

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)

    result, response = run_intent_agent(_email())

    assert calls == [
        (
            "cancel-contract",
            "Cancel contract C-1",
            "## Routed concern to process\nCancel contract C-1.\n\n"
            "## Shared business-object identifiers\n"
            "These identifiers are context for this concern, not separate requests.\n"
            "- contract: C-1",
        ),
        (
            "buy-product",
            "Buy three XYZ units",
            "## Routed concern to process\nI also want to buy three XYZ units.",
        ),
    ]
    assert response is None
    assert result.matched is True
    assert result.intent_name == "cancel-contract"
    assert [item.intent_name for item in result.concerns] == ["cancel-contract", "buy-product"]
    assert all(item.status == "ready" for item in result.concerns)
    assert result.concerns[0].reply_requirements == [
        "Explain cancel-contract state.",
        "Cover cancel-contract.",
    ]
    assert result.concerns[0].required_guidance == [
        "Give required guidance for cancel-contract."
    ]
    assert [obligation.question for obligation in result.concerns[0].answer_obligations] == [
        "Confirm whether contract C-1 can be cancelled.",
        "Explain when cancellation becomes effective.",
    ]
    assert [obligation.obligation_id for obligation in result.concerns[0].answer_obligations] == [
        f"{result.concerns[0].concern_id}:obligation-1",
        f"{result.concerns[0].concern_id}:obligation-2",
    ]
    assert result.concerns[0].concern_id != result.concerns[1].concern_id


def test_four_independent_concerns_are_all_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_stubs(monkeypatch)
    intent_names = [
        "cancel-contract",
        "buy-product",
        "refund-order",
        "update-address",
    ]
    routes = [
        ConcernRoute(
            summary=f"Concern {index}",
            source_text=f"Request {index}.",
            answer_obligations=[f"Answer request {index}."],
            intent_name=intent_name,
            confidence=0.95,
        )
        for index, intent_name in enumerate(intent_names, 1)
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_known_intent_names",
        lambda intents_dir=None: set(intent_names),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_actions",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {"enabled": True},
    )
    result, response = run_intent_agent(_email())

    assert response is None
    assert [concern.intent_name for concern in result.concerns] == intent_names


def test_damaged_hazardous_parcel_prefers_fulfillment_exception_runbook(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_known_intent_names",
        lambda intents_dir=None: {
            "zf-e2e-b2b-sla-urgent",
            "zf-e2e-warehouse-order-exception",
        },
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_actions",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    email = Email(
        id="v10-c06",
        subject="V10 URGENT leaking battery parcel ZF-10482",
        from_address="safety@example.test",
        body=(
            "URGENT safety incident. The recipient reports that parcel for order "
            "ZF-10482 arrived with a leaking lithium battery pack and a strong "
            "chemical smell. What evidence must we collect, what should the "
            "recipient keep, and have you escalated this incident? Send a "
            "replacement and refund immediately.\n\nSafety Desk"
        ),
        attachments=[],
    )
    route = ConcernRoute(
        summary=email.subject,
        source_text=email.body,
        intent_name="zf-e2e-b2b-sla-urgent",
        confidence=0.91,
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: ([route], None),
    )

    result, response = run_intent_agent(email)

    assert response is None
    assert result.intent_name == "zf-e2e-warehouse-order-exception"
    assert [item.intent_name for item in result.concerns] == [
        "zf-e2e-warehouse-order-exception",
    ]


def test_urgent_b2b_sla_incident_stays_on_b2b_runbook(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_known_intent_names",
        lambda intents_dir=None: {
            "zf-e2e-b2b-sla-urgent",
            "zf-e2e-warehouse-order-exception",
        },
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_actions",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    email = Email(
        id="v10-c09",
        subject="V10 P1 B2B SLA incident - 87 orders blocked",
        from_address="operations@example.test",
        body=(
            "P1 escalation: 87 launch orders are blocked and our campaign starts "
            "tomorrow at 08:00 CET. We need executive escalation now. Confirm you "
            "have escalated it, guarantee inventory and dispatch before the "
            "deadline, and confirm our SLA compensation. Tell me what exact data "
            "you still need from us.\n\nOperations Director"
        ),
        attachments=[],
    )
    route = ConcernRoute(
        summary=email.subject,
        source_text=email.body,
        intent_name="zf-e2e-b2b-sla-urgent",
        confidence=0.96,
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: ([route], None),
    )

    result, response = run_intent_agent(email)

    assert response is None
    assert result.intent_name == "zf-e2e-b2b-sla-urgent"
    assert [item.intent_name for item in result.concerns] == [
        "zf-e2e-b2b-sla-urgent",
    ]


def test_missing_router_obligations_get_stable_concern_fallback(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    route = ConcernRoute(
        summary="Explain legal fees",
        source_text="What is the fee?",
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "concern-stable",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.model_dump(by_alias=True) for item in outcome.answer_obligations] == [
        {
            "obligationId": "concern-stable:obligation-1",
            "question": "What is the fee?",
            "sourceText": "What is the fee?",
        }
    ]


def test_explicit_questions_fill_router_obligation_omissions(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    route = ConcernRoute(
        summary="Billing questions",
        source_text=(
            "What is the consultation fee? Is a retainer required? When is the invoice due? Can the retainer be waived?"
        ),
        answer_obligations=["Explain the consultation fee."],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "billing",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [
        "What is the consultation fee?",
        "Is a retainer required?",
        "When is the invoice due?",
        "Can the retainer be waived?",
    ]


def test_explicit_request_sentences_fill_router_obligation_omissions(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    source_text = (
        "For MAT-2026-221, Westbridge SA may have been advised by the firm on a related transaction. "
        "First look up the current matter and say whether substantive discussion is already paused. "
        "Then stop substantive discussion, record the potential conflict, and escalate it for review. "
        "Do not conclude there is a conflict or that representation continues."
    )
    route = ConcernRoute(
        summary="Review a potential conflict",
        source_text=source_text,
        answer_obligations=[
            (
                "Look up the current matter and say whether substantive discussion is already paused; "
                "then stop discussion, record the potential conflict, and escalate it for review."
            )
        ],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "potential-conflict",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [
        "First look up the current matter and say whether substantive discussion is already paused.",
        "Then stop substantive discussion, record the potential conflict, and escalate it for review.",
    ]
    assert [item.obligation_id for item in outcome.answer_obligations] == [
        "potential-conflict:obligation-1",
        "potential-conflict:obligation-2",
    ]


def test_explicit_request_sentence_fills_equal_count_router_omission(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    source_text = (
        "For MAT-2026-221, Westbridge SA may have been advised by the firm on a related transaction. "
        "First look up the current matter and say whether substantive discussion is already paused. "
        "Then stop substantive discussion, record the potential conflict, and escalate it for review."
    )
    route = ConcernRoute(
        summary="Review a potential conflict",
        source_text=source_text,
        answer_obligations=[
            "Confirm if substantive discussion on MAT-2026-221 is already paused.",
            (
                "Confirm that substantive discussion on MAT-2026-221 will be stopped, "
                "the potential conflict recorded, and escalated for review."
            ),
        ],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "potential-conflict",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    questions = [item.question.casefold() for item in outcome.answer_obligations]
    assert any(
        "look up the current matter" in question
        and "substantive discussion" in question
        and "paus" in question
        for question in questions
    )
    assert any(
        "mat-2026-221" in question
        and "substantive discussion" in question
        and "paus" in question
        for question in questions
    )
    assert any(
        all(
            term in question
            for term in (
                "substantive discussion",
                "stop",
                "potential conflict",
                "record",
                "escalat",
                "review",
            )
        )
        for question in questions
    )
    assert [item.obligation_id for item in outcome.answer_obligations] == [
        f"potential-conflict:obligation-{index}"
        for index in range(1, len(outcome.answer_obligations) + 1)
    ]


def test_first_person_noun_request_fills_equal_count_router_omission(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    source_text = (
        "Zurich Commercial Court response due 20 July 2026 at 12:00. "
        "I need an urgent consultation today. "
        "Identify and escalate the deadline, explain the triage information needed, "
        "and do not promise an extension, representation, or outcome."
    )
    route = ConcernRoute(
        summary="Urgent court deadline and consultation request",
        source_text=source_text,
        answer_obligations=[
            "Identify and escalate the deadline.",
            "Explain the triage information needed.",
        ],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "urgent-deadline",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [
        "I need an urgent consultation today.",
        "Identify and escalate the deadline.",
        "Explain the triage information needed.",
    ]
    assert [item.obligation_id for item in outcome.answer_obligations] == [
        "urgent-deadline:obligation-1",
        "urgent-deadline:obligation-2",
        "urgent-deadline:obligation-3",
    ]


@pytest.mark.parametrize(
    "source_text",
    [
        "Westbridge SA may have been advised by the firm on a related transaction.",
        "The client asked the firm to stop substantive discussion.",
        "Stopping substantive discussion would preserve the current position.",
        "Review of the matter remains pending. Update from the client arrived yesterday.",
        "I needed an urgent consultation yesterday.",
        "The client said I need an urgent consultation today.",
        "I do not need an urgent consultation today.",
        "I need to explain the background before asking for advice.",
        "Do not conclude there is a conflict or that representation continues.",
        "Then do not stop substantive discussion or record a confirmed conflict.",
        "Please never escalate this as a confirmed conflict.",
        "No action is required while the review remains open.",
    ],
)
def test_narrative_and_negative_sentences_are_not_supplementary_obligations(
    monkeypatch,
    source_text: str,
):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    route = ConcernRoute(
        summary="Review reported background",
        source_text=source_text,
        answer_obligations=["Review reported background."],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "reported-background",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [
        "Review reported background.",
    ]


def test_compound_action_and_confirmation_are_separate_obligations(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    source_text = (
        "change the address to 24 New Street, Zurich 8001 today and confirm it changed. "
        "If already shipped, request a carrier redirect."
    )
    route = ConcernRoute(
        summary="Change the delivery address",
        source_text=source_text,
        answer_obligations=[
            "change the address to 24 New Street, Zurich 8001 today and confirm it changed",
            "request a carrier redirect if already shipped",
        ],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "address-change",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [
        "change the address to 24 New Street, Zurich 8001 today",
        "confirm it changed",
        "request a carrier redirect if already shipped",
    ]
    assert [item.obligation_id for item in outcome.answer_obligations] == [
        "address-change:obligation-1",
        "address-change:obligation-2",
        "address-change:obligation-3",
    ]


def test_live_e05_two_concerns_keep_all_six_obligations(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    routes = [
        ConcernRoute(
            summary="Give shipment status",
            source_text="give current status, last carrier event, and ETA",
            answer_obligations=[
                "give current status",
                "give last carrier event",
                "give ETA",
            ],
            intent_name="cancel-contract",
        ),
        ConcernRoute(
            summary="Change the delivery address",
            source_text=(
                "change the address to 24 New Street, Zurich 8001 today and "
                "confirm it changed. If already shipped, request a carrier redirect."
            ),
            answer_obligations=[
                "change the address to 24 New Street, Zurich 8001 today and confirm it changed",
                "request a carrier redirect if already shipped",
            ],
            intent_name="cancel-contract",
        ),
    ]

    outcomes = [
        _execute_routed_concern(
            f"e05-concern-{index}",
            route,
            _email(),
            None,
            None,
            None,
            None,
            None,
            None,
        )
        for index, route in enumerate(routes, start=1)
    ]

    assert [len(outcome.answer_obligations) for outcome in outcomes] == [3, 3]
    assert [obligation.question for outcome in outcomes for obligation in outcome.answer_obligations] == [
        "give current status",
        "give last carrier event",
        "give ETA",
        "change the address to 24 New Street, Zurich 8001 today",
        "confirm it changed",
        "request a carrier redirect if already shipped",
    ]
    assert [obligation.obligation_id for outcome in outcomes for obligation in outcome.answer_obligations] == [
        "e05-concern-1:obligation-1",
        "e05-concern-1:obligation-2",
        "e05-concern-1:obligation-3",
        "e05-concern-2:obligation-1",
        "e05-concern-2:obligation-2",
        "e05-concern-2:obligation-3",
    ]


@pytest.mark.parametrize(
    "question",
    [
        "Can you confirm that we can cancel and replace the order?",
        "Tell me which items you can refund and replace under warranty.",
        "Please explain how to check and update the shipment status.",
        "Provide the check and update history.",
        "Can you explain how to change and confirm the delivery address?",
        "Tell me whether I should change the address and confirm it by email.",
        "Change the company name to Update and Confirm LLC.",
        "Change notification addresses to billing@example.test, confirm@example.test.",
        "Can you provide steps to change the address and confirm it is valid?",
        "Send instructions on how to change the address and confirm it was saved.",
        "Change the workflow so agents update and confirm the address before saving.",
        "Update the company name to Update and Confirm It Ltd.",
    ],
)
def test_nested_or_noun_coordination_is_not_split(
    monkeypatch,
    question: str,
):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    route = ConcernRoute(
        summary="Keep shared context",
        source_text=question,
        answer_obligations=[question],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "shared-context",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [question]


@pytest.mark.parametrize(
    "question",
    [
        "Change the address and then confirm it changed.",
        "Change the address, then confirm it changed.",
        "Change the address; (2) confirm it changed.",
        "Change the address\n- confirm it changed.",
    ],
)
def test_confirmation_followup_separators_are_split(
    monkeypatch,
    question: str,
):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    route = ConcernRoute(
        summary="Change and confirm",
        source_text=question,
        answer_obligations=[question],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "confirmation-separator",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert len(outcome.answer_obligations) == 2
    assert outcome.answer_obligations[1].question.lower().startswith("confirm it changed")


def test_question_form_compound_request_is_split_without_splitting_noun_lists(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    route = ConcernRoute(
        summary="Status and address request",
        source_text=(
            "Can you give current status, last carrier event, and ETA? "
            "Can you change the address today and confirm it changed?"
        ),
        answer_obligations=[
            "Give current status, last carrier event, and ETA.",
            "Change the address today and confirm it changed.",
        ],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "status-address",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [
        "Can you give current status, last carrier event, and ETA?",
        "Can you change the address today and confirm it changed?",
        "confirm it changed.",
    ]


def test_explicit_question_is_kept_when_router_returned_more_other_obligations(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    route = ConcernRoute(
        summary="Partial shipment",
        source_text=(
            "Only one of three units arrived. Are the other two units in separate parcels "
            "with separate tracking numbers, "
            "or are they missing? Please provide every confirmed tracking number and "
            "refund missing units if there is no second parcel."
        ),
        answer_obligations=[
            "Provide every confirmed tracking number.",
            "Refund the missing units if there is no second parcel.",
        ],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "partial-shipment",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [
        "Are the other two units in separate parcels with separate tracking numbers, or are they missing?",
        "Provide every confirmed tracking number.",
        "Refund the missing units if there is no second parcel.",
    ]


def test_independently_routed_billing_side_splits_compound_question_without_duplicate(
    monkeypatch,
):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    source_text = "What are the standard setup fee and renewal fee?"
    route = ConcernRoute(
        summary="Explain standard fees",
        source_text=source_text,
        answer_obligations=["What is the renewal fee?"],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "legal-billing",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [
        "What is the standard setup fee?",
        "What is the standard renewal fee?",
    ]
    assert [item.obligation_id for item in outcome.answer_obligations] == [
        "legal-billing:obligation-1",
        "legal-billing:obligation-2",
    ]


def test_mc01_billing_shape_splits_without_router_variance(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    source_text = "what are the standard initial consultation fee and advance retainer?"
    route = ConcernRoute(
        summary="Explain standard fees",
        source_text=source_text,
        answer_obligations=[source_text],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "legal-billing",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [
        "What is the standard initial consultation fee?",
        "What is the standard advance retainer?",
    ]


def test_s05_explicit_lookup_list_becomes_independent_obligations(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    lookup_question = (
        "What exact status, first-failure time, affected events, and relevant "
        "recent change does the lookup show?"
    )
    source_text = (
        f"{lookup_question} Which redacted request ID do you need for diagnosis? "
        "Rotate the signing secret. Replay every failed event. Confirm delivery "
        "is fixed. Acknowledge the offer to send the current secret."
    )
    route = ConcernRoute(
        summary="Recover the production webhook",
        source_text=source_text,
        answer_obligations=[
            lookup_question,
            "Which redacted request ID do you need for diagnosis?",
            "Rotate the signing secret.",
            "Replay every failed event.",
            "Confirm delivery is fixed.",
            "Acknowledge the offer to send the current secret.",
        ],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "saas-webhook-recovery",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [
        "What exact status does the lookup show?",
        "What first-failure time does the lookup show?",
        "What affected events does the lookup show?",
        "What relevant recent change does the lookup show?",
        "Which redacted request ID do you need for diagnosis?",
        "Rotate the signing secret.",
        "Replay every failed event.",
        "Confirm delivery is fixed.",
        "Acknowledge the offer to send the current secret.",
    ]
    assert [item.obligation_id for item in outcome.answer_obligations] == [
        f"saas-webhook-recovery:obligation-{index}" for index in range(1, 10)
    ]


def test_lookup_list_does_not_split_coordinated_idiom(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    question = "What terms, conditions, and exceptions does the lookup show?"
    route = ConcernRoute(
        summary="Explain the policy",
        source_text=question,
        answer_obligations=[question],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "policy-lookup",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [question]


def test_lookup_list_does_not_split_clause_facet(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    question = (
        "What exact status, whether delivery is fixed, and affected events does "
        "the lookup show?"
    )
    route = ConcernRoute(
        summary="Inspect delivery recovery",
        source_text=question,
        answer_obligations=[question],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "delivery-recovery",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [question]


def test_lookup_list_does_not_split_two_item_question(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    question = "What exact status and first-failure time does the lookup show?"
    route = ConcernRoute(
        summary="Inspect webhook status",
        source_text=question,
        answer_obligations=[question],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "webhook-status",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [question]


def test_lookup_list_split_is_rejected_before_obligation_cap_overflow(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    lookup_question = (
        "What exact status, first-failure time, affected events, and relevant "
        "recent change does the lookup show?"
    )
    other_obligations = [f"Explain independent request {index}." for index in range(1, 9)]
    route = ConcernRoute(
        summary="Keep every bounded obligation",
        source_text=lookup_question,
        answer_obligations=[lookup_question, *other_obligations],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "bounded-lookup",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [
        lookup_question,
        *other_obligations,
    ]


@pytest.mark.parametrize(
    ("question", "routed_question"),
    [
        (
            "What are the terms and conditions?",
            "What are the terms and conditions?",
        ),
        (
            "What are the terms and conditions?",
            "What are the conditions?",
        ),
        (
            "What are the standard terms and conditions?",
            "Explain the applicable conditions.",
        ),
        (
            "What are the standard setup fee and renewal fee?",
            "Explain the standard setup fee and renewal fee.",
        ),
        (
            "What are standard initial consultation fee and advance retainer?",
            "What are standard initial consultation fee and advance retainer?",
        ),
        (
            "What are the consultation fee and the advance retainer?",
            "What are the consultation fee and the advance retainer?",
        ),
        (
            "What are the consultation fee and terms of retainer?",
            "What are the consultation fee and terms of retainer?",
        ),
        (
            "What are the consultation fee and any retainer?",
            "What are the consultation fee and any retainer?",
        ),
        (
            "What are the consultation fee and no retainer?",
            "What are the consultation fee and no retainer?",
        ),
        (
            "What are the consultation fee and either retainer?",
            "What are the consultation fee and either retainer?",
        ),
        (
            "What are the consultation fee and your retainer?",
            "What are the consultation fee and your retainer?",
        ),
        (
            "What are the standard consultation fee and another retainer?",
            "What are the standard consultation fee and another retainer?",
        ),
        (
            "What are the standard consultation fee and each retainer?",
            "What are the standard consultation fee and each retainer?",
        ),
        (
            "What are the standard consultation fee and one retainer?",
            "What are the standard consultation fee and one retainer?",
        ),
        (
            "What are the standard consultation fee and some retainer?",
            "What are the standard consultation fee and some retainer?",
        ),
        (
            "What are the standard consultation fee and both retainer?",
            "What are the standard consultation fee and both retainer?",
        ),
        (
            "What are the standard consultation fee and every retainer?",
            "What are the standard consultation fee and every retainer?",
        ),
        (
            "What are the standard consultation fee and neither retainer?",
            "What are the standard consultation fee and neither retainer?",
        ),
        (
            "What are the standard consultation fee and several retainer?",
            "What are the standard consultation fee and several retainer?",
        ),
        (
            "What are the standard consultation fee and half retainer?",
            "What are the standard consultation fee and half retainer?",
        ),
        (
            "What are the standard consultation fee and multiple retainer?",
            "What are the standard consultation fee and multiple retainer?",
        ),
        (
            "What are the standard consultation fee and various retainer?",
            "What are the standard consultation fee and various retainer?",
        ),
        (
            "What are the standard consultation fee and these retainer?",
            "What are the standard consultation fee and these retainer?",
        ),
        (
            "What are the standard consultation fee and his retainer?",
            "What are the standard consultation fee and his retainer?",
        ),
        (
            "What are the standard consultation fee and said retainer?",
            "What are the standard consultation fee and said retainer?",
        ),
        (
            "What are the standard consultation fee and aforementioned retainer?",
            "What are the standard consultation fee and aforementioned retainer?",
        ),
        (
            "What are the standard consultation fee and latter retainer?",
            "What are the standard consultation fee and latter retainer?",
        ),
        (
            "What are the standard consultation fee and former retainer?",
            "What are the standard consultation fee and former retainer?",
        ),
        (
            "What are the standard consultation fee and respective retainer?",
            "What are the standard consultation fee and respective retainer?",
        ),
        (
            "What are the standard consultation fee and 2 retainer?",
            "What are the standard consultation fee and 2 retainer?",
        ),
        (
            "What are the initial consultation fee and annual retainer?",
            "What are the initial consultation fee and annual retainer?",
        ),
        (
            "What are the current setup fee and future retainer?",
            "What are the current setup fee and future retainer?",
        ),
        (
            "What are the standard consultation fee and annual retainer?",
            "What are the standard consultation fee and annual retainer?",
        ),
        (
            "What are the standard fee and advance retainer?",
            "What are the standard fee and advance retainer?",
        ),
        (
            "What are the standard service fee and advance retainer?",
            "What are the standard service fee and advance retainer?",
        ),
        (
            "What are the standard annual fee and advance retainer?",
            "What are the standard annual fee and advance retainer?",
        ),
        (
            "What are the standard service fee and quoted price?",
            "What are the standard service fee and quoted price?",
        ),
    ],
)
def test_compound_question_is_not_split_without_independent_routing_evidence(
    monkeypatch,
    question: str,
    routed_question: str,
):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    route = ConcernRoute(
        summary="Keep compound question",
        source_text=question,
        answer_obligations=[routed_question],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "compound-question",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [question]


def test_unsafe_second_billing_phrase_stays_combined_even_when_side_is_routed(
    monkeypatch,
):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    source_text = "What are the standard consultation fee and said retainer?"
    route = ConcernRoute(
        summary="Keep referential billing phrase intact",
        source_text=source_text,
        answer_obligations=["What is the said retainer?"],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "compound-question",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [source_text]


@pytest.mark.parametrize(
    "source_text",
    [
        "What are standard setup fee and renewal fee?",
        "What are the standard customers pay setup fee and renewal fee?",
        "What are the standard cancel contract fee and renewal fee?",
        "What are the standard non refundable fee and renewal fee?",
    ],
)
def test_independent_routing_does_not_split_ungrammatical_billing_question(
    monkeypatch,
    source_text: str,
):
    _base_stubs(monkeypatch)
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    route = ConcernRoute(
        summary="Keep unsafe billing grammar intact",
        source_text=source_text,
        answer_obligations=["What is the renewal fee?"],
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "compound-question",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [item.question for item in outcome.answer_obligations] == [source_text]


def test_duplicate_routes_execute_runbook_only_once(monkeypatch):
    _base_stubs(monkeypatch)
    routes = [
        ConcernRoute(
            summary="Cancel contract C-1",
            source_text="Cancel contract C-1.",
            intent_name="cancel-contract",
            confidence=0.98,
        ),
        ConcernRoute(
            summary="Cancellation request",
            source_text="  CANCEL   contract C-1.  ",
            intent_name="CANCEL-CONTRACT",
            confidence=0.91,
        ),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    calls: list[str] = []

    def process(intent_name, *_args, **_kwargs):
        calls.append(intent_name)
        return IntentProcessingOutput(summary="Cancellation prepared")

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "contract_lookup", "method": "GET"}],
    )

    result, response = run_intent_agent(_email())

    assert calls == ["cancel-contract"]
    assert response is None
    assert [item.intent_name for item in result.concerns] == ["cancel-contract"]


def test_same_runbook_executes_distinct_source_excerpts_independently(monkeypatch):
    _base_stubs(monkeypatch)
    routes = [
        ConcernRoute(
            summary="Cancel contract C-1",
            source_text="Cancel contract C-1.",
            intent_name="cancel-contract",
        ),
        ConcernRoute(
            summary="Cancel contract C-2",
            source_text="Cancel contract C-2.",
            intent_name="cancel-contract",
        ),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    calls: list[str] = []

    def process(_intent_name, _actions, email, *_args, **_kwargs):
        calls.append(email.body)
        return IntentProcessingOutput(summary="Cancellation prepared")

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "contract_lookup", "method": "GET"}],
    )

    result, response = run_intent_agent(_email())

    assert calls == [
        "## Routed concern to process\nCancel contract C-1.\n\n"
        "## Shared business-object identifiers\n"
        "These identifiers are context for this concern, not separate requests.\n"
        "- contract: C-1",
        "## Routed concern to process\nCancel contract C-2.\n\n"
        "## Shared business-object identifiers\n"
        "These identifiers are context for this concern, not separate requests.\n"
        "- contract: C-2",
    ]
    assert response is None
    assert len(result.concerns) == 2
    assert result.concerns[0].concern_id != result.concerns[1].concern_id


def test_each_concern_processing_input_keeps_shared_identifier_from_original_message(monkeypatch):
    _base_stubs(monkeypatch)
    email = Email(
        id="message-shared-order",
        subject="Status and address change for ZF-20991",
        from_address="merchant@example.test",
        body=(
            "For order ZF-20991, tell me the current shipment status and ETA. "
            "Also change the delivery address to 24 New Street."
        ),
        attachments=[],
    )
    routes = [
        ConcernRoute(
            summary="Shipment status and ETA",
            source_text="Tell me the current shipment status and ETA.",
            intent_name="cancel-contract",
        ),
        ConcernRoute(
            summary="Address change",
            source_text="Change the delivery address to 24 New Street.",
            intent_name="buy-product",
        ),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "lookup", "method": "GET"}],
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    processing_bodies: list[str] = []

    def process(_intent_name, _actions, concern_email, *_args, **_kwargs):
        processing_bodies.append(concern_email.body)
        return IntentReviewOutput(summary="Processed")

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)

    result, response = run_intent_agent(email)

    assert response is None
    assert len(result.concerns) == 2
    assert all("ZF-20991" in body for body in processing_bodies)
    assert all("## Full original customer message context" not in body for body in processing_bodies)
    assert processing_bodies[0].startswith("## Routed concern to process\nTell me the current shipment status and ETA.")
    assert processing_bodies[1].startswith(
        "## Routed concern to process\nChange the delivery address to 24 New Street."
    )
    assert "Change the delivery address" not in processing_bodies[0]
    assert "current shipment status" not in processing_bodies[1]


def test_l01_narrow_router_span_keeps_adjacent_labeled_conflict_parties() -> None:
    email = Email(
        id="message-l01",
        subject="New client intake and conflict check",
        from_address="sophie.mueller@example.test",
        body=(
            "I may need advice about a failed software implementation. "
            "Opposing party Helvetia Systems AG and parent Helvetia Holdings SA. "
            "Before confidential facts or documents, explain the intake and conflict-check process. "
            "Do not imply mandate acceptance or give substantive advice."
        ),
        attachments=[],
    )
    route = ConcernRoute(
        summary="Explain the intake and conflict-check process for a potential new matter.",
        source_text="Before confidential facts or documents, explain the intake and conflict-check process.",
        intent_name="law-conflict-intake",
    )

    _, processing = _concern_processing_email(email, route)

    assert processing.body == (
        "## Routed concern to process\n"
        "Before confidential facts or documents, explain the intake and conflict-check process.\n\n"
        "## Shared business-party references\n"
        "These explicitly labeled parties are identity context for this concern, not separate requests.\n"
        "- opposing party: Helvetia Systems AG\n"
        "- parent: Helvetia Holdings SA"
    )
    assert "failed software implementation" not in processing.body
    assert "mandate acceptance" not in processing.body


def test_labeled_parties_stay_with_their_adjacent_concerns() -> None:
    email = Email(
        id="message-two-party-groups",
        subject="Two separate requests",
        from_address="operator@example.test",
        body=(
            "Opposing party Northlake AG and parent Northlake Holdings SA. "
            "Explain the conflict-check process. "
            "Supplier Bluebird GmbH and carrier Rapid Parcel AG. "
            "Find the delayed shipment."
        ),
        attachments=[],
    )
    conflict_route = ConcernRoute(
        summary="Conflict check",
        source_text="Explain the conflict-check process.",
        intent_name="law-conflict-intake",
    )
    shipment_route = ConcernRoute(
        summary="Shipment lookup",
        source_text="Find the delayed shipment.",
        intent_name="fulfillment-shipment-status",
    )

    _, conflict_processing = _concern_processing_email(email, conflict_route)
    _, shipment_processing = _concern_processing_email(email, shipment_route)

    assert "Northlake AG" in conflict_processing.body
    assert "Northlake Holdings SA" in conflict_processing.body
    assert "Bluebird GmbH" not in conflict_processing.body
    assert "Rapid Parcel AG" not in conflict_processing.body
    assert "Bluebird GmbH" in shipment_processing.body
    assert "Rapid Parcel AG" in shipment_processing.body
    assert "Northlake AG" not in shipment_processing.body


def test_business_party_context_requires_unique_span_and_explicit_labels() -> None:
    unlabeled = Email(
        id="message-unlabeled-party",
        subject="Conflict request",
        from_address="operator@example.test",
        body="Northlake AG and Marco Steiner. Explain the conflict-check process.",
        attachments=[],
    )
    repeated = Email(
        id="message-repeated-request",
        subject="Two conflict requests",
        from_address="operator@example.test",
        body=(
            "Opposing party Northlake AG. Explain the conflict-check process. "
            "Opposing party Bluebird GmbH. Explain the conflict-check process."
        ),
        attachments=[],
    )
    route = ConcernRoute(
        summary="Conflict check",
        source_text="Explain the conflict-check process.",
        intent_name="law-conflict-intake",
    )

    _, unlabeled_processing = _concern_processing_email(unlabeled, route)
    _, repeated_processing = _concern_processing_email(repeated, route)

    assert "Shared business-party references" not in unlabeled_processing.body
    assert "Northlake AG" not in unlabeled_processing.body
    assert "Shared business-party references" not in repeated_processing.body
    assert "Northlake AG" not in repeated_processing.body
    assert "Bluebird GmbH" not in repeated_processing.body


def test_e04_split_concerns_each_keep_the_shared_order_identifier(monkeypatch):
    _base_stubs(monkeypatch)
    email = Email(
        id="message-e04",
        subject="Stalled shipment exception for ZF-88310",
        from_address="merchant@example.test",
        body=(
            "Order ZF-88310 has not moved for 3 days. Give the last scan, location, "
            "and delivery window, and open a delivery-exception investigation now."
        ),
        attachments=[],
    )
    routes = [
        ConcernRoute(
            summary="Shipment status facts",
            source_text="Give the last scan, location, and delivery window.",
            intent_name="cancel-contract",
        ),
        ConcernRoute(
            summary="Delivery exception",
            source_text="Open a delivery-exception investigation now.",
            intent_name="buy-product",
        ),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "shipment_lookup", "method": "GET"}],
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    processing_bodies: list[str] = []

    def process(_intent_name, _actions, concern_email, *_args, **_kwargs):
        processing_bodies.append(concern_email.body)
        return IntentReviewOutput(summary="Processed")

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)

    result, response = run_intent_agent(email)

    assert response is None
    assert len(result.concerns) == 2
    assert all("- order: ZF-88310" in body for body in processing_bodies)
    assert "Open a delivery-exception" not in processing_bodies[0]
    assert "last scan" not in processing_bodies[1]


def test_leading_labeled_object_is_shared_when_generic_subject_drops_identifier(monkeypatch):
    _base_stubs(monkeypatch)
    email = Email(
        id="message-leading-order",
        subject="Shipment needs attention",
        from_address="merchant@example.test",
        body=(
            "Order ZF-12345 has not moved for three days. "
            "Give the last scan and open an investigation."
        ),
        attachments=[],
    )
    routes = [
        ConcernRoute(
            summary="Shipment status",
            source_text="Give the last scan.",
            intent_name="cancel-contract",
        ),
        ConcernRoute(
            summary="Investigation",
            source_text="Open an investigation.",
            intent_name="buy-product",
        ),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "shipment_lookup", "method": "GET"}],
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    processing_bodies: list[str] = []

    def process(_intent_name, _actions, concern_email, *_args, **_kwargs):
        processing_bodies.append(concern_email.body)
        return IntentReviewOutput(summary="Processed")

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)

    result, response = run_intent_agent(email)

    assert response is None
    assert len(result.concerns) == 2
    assert all("- order: ZF-12345" in body for body in processing_bodies)


def test_distinct_business_objects_do_not_cross_concern_processing(monkeypatch):
    _base_stubs(monkeypatch)
    email = Email(
        id="message-two-orders",
        subject="Two separate order requests",
        from_address="merchant@example.test",
        body=(
            "Give shipment status for order ZF-11111. "
            "Cancel order ZF-22222."
        ),
        attachments=[],
    )
    routes = [
        ConcernRoute(
            summary="Status for ZF-11111",
            source_text="Give shipment status for order ZF-11111.",
            intent_name="cancel-contract",
        ),
        ConcernRoute(
            summary="Cancellation for ZF-22222",
            source_text="Cancel order ZF-22222.",
            intent_name="buy-product",
        ),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "order_lookup", "method": "GET"}],
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    processing_bodies: list[str] = []

    def process(_intent_name, _actions, concern_email, *_args, **_kwargs):
        processing_bodies.append(concern_email.body)
        return IntentReviewOutput(summary="Processed")

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)

    result, response = run_intent_agent(email)

    assert response is None
    assert len(result.concerns) == 2
    assert "ZF-11111" in processing_bodies[0]
    assert "ZF-22222" not in processing_bodies[0]
    assert "ZF-22222" in processing_bodies[1]
    assert "ZF-11111" not in processing_bodies[1]


def test_unmatched_concern_preserves_matched_work_and_requires_human(monkeypatch):
    _base_stubs(monkeypatch)
    routes = [
        ConcernRoute(
            summary="Cancel contract",
            source_text="Cancel contract C-1.",
            intent_name="cancel-contract",
            confidence=0.97,
        ),
        ConcernRoute(
            summary="Unconfigured loyalty request",
            source_text="Transfer my loyalty points.",
            confidence=0.75,
            reason="No loyalty runbook exists.",
        ),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent", lambda *_args, **_kwargs: (routes, None)
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})

    result, response = run_intent_agent(_email())

    assert result.matched is True
    assert [item.status for item in result.concerns] == ["ready", "unmatched"]
    assert response is not None
    assert response.requires_human is True
    assert response.activated_intent == "cancel-contract"
    assert "No loyalty runbook exists." in str(response.requires_human_reason)


def test_failed_runbook_does_not_stop_other_concerns(monkeypatch):
    _base_stubs(monkeypatch)
    routes = [
        ConcernRoute(summary="Cancel", source_text="Cancel C-1.", intent_name="cancel-contract"),
        ConcernRoute(summary="Buy", source_text="Buy XYZ.", intent_name="buy-product"),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent", lambda *_args, **_kwargs: (routes, None)
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_actions",
        lambda intent_name, **_kwargs: [{"name": intent_name, "label": intent_name, "type": "button"}],
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})
    calls: list[str] = []

    def process(intent_name, *_args, **_kwargs):
        calls.append(intent_name)
        if intent_name == "cancel-contract":
            raise RuntimeError("cancellation API unavailable")
        return IntentProcessingOutput(
            summary="Purchase prepared",
            selected_action_names=["buy-product"],
        )

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)

    result, response = run_intent_agent(_email())

    assert calls == ["cancel-contract", "buy-product"]
    assert [item.status for item in result.concerns] == ["failed", "ready"]
    assert response is not None and response.requires_human is True


def test_concern_ids_are_stable_across_router_order_and_suffix_collisions():
    email = _email()
    cancellation = ConcernRoute(
        summary="Cancellation",
        source_text="Cancel contract C-1.",
        intent_name="cancel-contract",
    )
    purchase = ConcernRoute(
        summary="Purchase",
        source_text="Buy three XYZ units.",
        intent_name="buy-product",
    )

    first_order: dict[str, int] = {}
    cancellation_id = _concern_id(email, cancellation, first_order)
    purchase_id = _concern_id(email, purchase, first_order)
    second_order: dict[str, int] = {}

    assert _concern_id(email, purchase, second_order) == purchase_id
    assert _concern_id(email, cancellation, second_order) == cancellation_id
    assert _concern_id(email, cancellation, first_order) == f"{cancellation_id}-2"

    formatting_variant = ConcernRoute(
        summary="Cancellation",
        source_text="  CANCEL   contract C-1.  ",
        intent_name="CANCEL-CONTRACT",
    )
    assert _concern_id(email, formatting_variant, {}) == cancellation_id


def test_only_audited_http_facts_become_verified_evidence(monkeypatch):
    _base_stubs(monkeypatch)
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "lookup", "method": "GET"}],
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_response_config", lambda *_args, **_kwargs: {})

    def process(*_args, **_kwargs):
        _record_tool_call(
            ToolDefinition(
                name="contract_lookup",
                description="Lookup contract",
                method="GET",
                url_template="https://example.test/contracts",
            ),
            status="success",
            response_text='{"contract": {"status": "active"}}',
        )
        return IntentReviewOutput.model_validate(
            {
                "summary": "Lookup complete",
                "verified_facts": [{"fact": "Invented cancellation date"}],
                "tool_evidence": [{"tool_name": "fake", "facts": [{"fact": "Invented"}]}],
            }
        )

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)
    route = ConcernRoute(
        summary="Cancel contract",
        source_text="Cancel C-1.",
        intent_name="cancel-contract",
    )

    outcome = _execute_routed_concern(
        "concern-stable",
        route,
        _email(),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    assert [(fact.path, fact.value) for fact in outcome.verified_facts] == [
        ("contract.status", "active"),
    ]
    assert [item.tool_name for item in outcome.tool_evidence] == ["contract_lookup"]
    assert [item.method for item in outcome.tool_evidence] == ["GET"]
    assert "Invented" not in outcome.model_dump_json()


def test_concern_collectors_isolate_tools_actions_knowledge_and_composer_order(monkeypatch):
    _base_stubs(monkeypatch)
    routes = [
        ConcernRoute(
            summary="Cancel contract",
            source_text="Cancel C-1.",
            intent_name="cancel-contract",
        ),
        ConcernRoute(
            summary="Buy product",
            source_text="Buy XYZ.",
            intent_name="buy-product",
        ),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda intent_name, **_kwargs: [{"name": f"lookup-{intent_name}", "method": "GET"}],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_actions",
        lambda intent_name, **_kwargs: [
            {
                "name": f"action-{intent_name}",
                "label": f"Action {intent_name}",
                "type": "button",
            }
        ],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda intent_name, **_kwargs: {
            "response_rules": [f"Knowledge rule for {intent_name}"],
        },
    )

    def process(intent_name, *_args, **_kwargs):
        assert current_tool_calls() == []
        assert current_generated_attachments() == []
        _record_test_tool(intent_name)
        _record_test_attachment(intent_name)
        return IntentProcessingOutput(
            summary=f"Processed {intent_name}",
            selected_action_names=[f"action-{intent_name}"],
            reply_requirements=[f"Runtime knowledge for {intent_name}"],
        )

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)
    generated_token = begin_generated_attachment_collection()
    tool_token = begin_tool_call_collection()
    try:
        result, response = run_intent_agent(_email())
    finally:
        generated = collect_generated_attachments(generated_token)
        tool_calls = collect_tool_calls(tool_token)

    assert response is None
    assert [concern.intent_name for concern in result.concerns] == [
        "cancel-contract",
        "buy-product",
    ]
    assert [[tool.tool_name for tool in concern.tool_evidence] for concern in result.concerns] == [
        ["lookup-cancel-contract"],
        ["lookup-buy-product"],
    ]
    assert [[action.name for action in concern.actions] for concern in result.concerns] == [
        ["action-cancel-contract"],
        ["action-buy-product"],
    ]
    assert [concern.reply_requirements for concern in result.concerns] == [
        [
            "Knowledge rule for cancel-contract",
            "Runtime knowledge for cancel-contract",
        ],
        [
            "Knowledge rule for buy-product",
            "Runtime knowledge for buy-product",
        ],
    ]
    assert [[item.filename for item in concern.attachments] for concern in result.concerns] == [
        ["cancel-contract.pdf"],
        ["buy-product.pdf"],
    ]
    assert [call["name"] for call in tool_calls] == [
        "lookup-cancel-contract",
        "lookup-buy-product",
    ]
    assert [item["filename"] for item in generated] == [
        "cancel-contract.pdf",
        "buy-product.pdf",
    ]
    prompt = create_response_user_prompt(_email(), intent_result=result)
    assert prompt.index("runbook>cancel-contract</runbook>") < prompt.index("runbook>buy-product</runbook>")


def test_failed_concern_activity_cannot_leak_into_next_concern(monkeypatch):
    _base_stubs(monkeypatch)
    routes = [
        ConcernRoute(summary="Cancel", source_text="Cancel C-1.", intent_name="cancel-contract"),
        ConcernRoute(summary="Buy", source_text="Buy XYZ.", intent_name="buy-product"),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "lookup", "method": "GET"}],
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )

    def process(intent_name, *_args, **_kwargs):
        assert current_tool_calls() == []
        assert current_generated_attachments() == []
        _record_test_tool(intent_name)
        if intent_name == "cancel-contract":
            _record_test_attachment("partial-cancel")
            raise RuntimeError("cancel service unavailable")
        _record_test_attachment(intent_name)
        return IntentReviewOutput(summary="Purchase processed")

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)
    generated_token = begin_generated_attachment_collection()
    tool_token = begin_tool_call_collection()
    try:
        result, response = run_intent_agent(_email())
    finally:
        generated = collect_generated_attachments(generated_token)
        tool_calls = collect_tool_calls(tool_token)

    assert [concern.status for concern in result.concerns] == ["failed", "ready"]
    assert result.concerns[0].tool_evidence == []
    assert result.concerns[0].attachments == []
    assert [tool.tool_name for tool in result.concerns[1].tool_evidence] == [
        "lookup-buy-product",
    ]
    assert [item.filename for item in result.concerns[1].attachments] == [
        "buy-product.pdf",
    ]
    assert response is not None and response.requires_human is True
    assert [call["name"] for call in tool_calls] == [
        "lookup-cancel-contract",
        "lookup-buy-product",
    ]
    assert [call["concernId"] for call in tool_calls] == [
        result.concerns[0].concern_id,
        result.concerns[1].concern_id,
    ]
    assert "status-cancel-contract" not in result.model_dump_json()
    assert [item["filename"] for item in generated] == ["buy-product.pdf"]


def test_configured_filename_collision_aliases_every_owner_and_loads_exact_sources(
    monkeypatch,
):
    _base_stubs(monkeypatch)
    routes = [
        ConcernRoute(summary="Cancel", source_text="Cancel.", intent_name="cancel-contract"),
        ConcernRoute(summary="Buy", source_text="Buy.", intent_name="buy-product"),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_attachments",
        lambda intent_name, **_kwargs: [
            {
                "filename": "terms.pdf",
                "description": f"Terms for {intent_name}",
                "mode": "dynamic",
            }
        ],
    )

    result, _response = run_intent_agent(_email())

    attachments = [concern.attachments[0] for concern in result.concerns]
    aliases = [attachment.filename for attachment in attachments]
    assert len(set(aliases)) == 2
    assert all(alias != "terms.pdf" for alias in aliases)
    assert [attachment.source_filename for attachment in attachments] == [
        "terms.pdf",
        "terms.pdf",
    ]
    assert [attachment.source_intent for attachment in attachments] == [
        "cancel-contract",
        "buy-product",
    ]
    available, _always = _available_attachments(result, intents_dir=None)
    assert [item["filename"] for item in available] == aliases
    prompt = create_response_user_prompt(_email(), intent_result=result)
    assert "terms.pdf" not in prompt
    assert all(alias in prompt for alias in aliases)

    filters: list[str] = []

    def fake_list_all(_collection, filter_str="", **_kwargs):
        filters.append(filter_str)
        if "intent='cancel-contract'" in filter_str:
            return [{"id": "cancel-file", "file": "cancel.pdf"}]
        if "intent='buy-product'" in filter_str:
            return [{"id": "buy-file", "file": "buy.pdf"}]
        return []

    monkeypatch.setattr("automail.api.attachments._list_all", fake_list_all)
    monkeypatch.setattr(
        "automail.api.attachments._get_binary",
        lambda path: (
            b"cancel terms" if "cancel-file" in path else b"buy terms",
            "application/pdf",
        ),
    )
    response = AgentResponse(
        response_text="Attached.",
        response_attachments=aliases,
    )

    loaded = load_attachment_files(
        response,
        intents_dir=SimpleNamespace(project_id="project-1"),
        intent_result=result,
        strict_intent_ownership=True,
    )

    assert loaded is not None
    assert [item["filename"] for item in loaded] == aliases
    assert [item["content_base64"] for item in loaded] == [
        "Y2FuY2VsIHRlcm1z",
        "YnV5IHRlcm1z",
    ]
    assert filters == [
        "project='project-1' && filename='terms.pdf' && intent='cancel-contract'",
        "project='project-1' && filename='terms.pdf' && intent='buy-product'",
    ]


def test_configured_and_generated_same_name_both_receive_selectable_aliases(
    monkeypatch,
):
    _base_stubs(monkeypatch)
    route = ConcernRoute(
        summary="Create label",
        source_text="Create a label.",
        intent_name="cancel-contract",
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: ([route], None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "make-label", "method": "POST"}],
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_attachments",
        lambda *_args, **_kwargs: [{"filename": "label.pdf", "mode": "dynamic"}],
    )

    def process(*_args, **_kwargs):
        _record_named_test_attachment("label.pdf", "Z2VuZXJhdGVk", "label-tool")
        return IntentReviewOutput(summary="Created label")

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)
    generated_token = begin_generated_attachment_collection()
    try:
        result, _response = run_intent_agent(_email())
    finally:
        generated = collect_generated_attachments(generated_token)

    configured, tool_file = result.concerns[0].attachments
    assert configured.source == "runbook"
    assert configured.source_filename == "label.pdf"
    assert tool_file.source == "tool"
    assert configured.filename != tool_file.filename
    assert "label.pdf" not in {configured.filename, tool_file.filename}
    assert generated[0]["filename"] == tool_file.filename

    monkeypatch.setattr(
        "automail.api.attachments._list_all",
        lambda _collection, filter_str="", **_kwargs: (
            [{"id": "static-label", "file": "stored-label.pdf"}]
            if "filename='label.pdf'" in filter_str and "intent='cancel-contract'" in filter_str
            else []
        ),
    )
    monkeypatch.setattr(
        "automail.api.attachments._get_binary",
        lambda _path: (b"configured", "application/pdf"),
    )
    response = AgentResponse(
        response_text="Attached.",
        response_attachments=[configured.filename, tool_file.filename],
        generated_attachments=generated,
    )

    loaded = load_attachment_files(
        response,
        intents_dir=SimpleNamespace(project_id="project-1"),
        intent_result=result,
        strict_intent_ownership=True,
    )

    assert loaded is not None
    assert [item["filename"] for item in loaded] == [
        configured.filename,
        tool_file.filename,
    ]
    assert [item["content_base64"] for item in loaded] == [
        "Y29uZmlndXJlZA==",
        "Z2VuZXJhdGVk",
    ]


def test_cross_concern_generated_filename_collision_reaches_loader_with_both_payloads(
    monkeypatch,
):
    _base_stubs(monkeypatch)
    routes = [
        ConcernRoute(summary="First", source_text="First.", intent_name="cancel-contract"),
        ConcernRoute(summary="Second", source_text="Second.", intent_name="buy-product"),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "make-label", "method": "POST"}],
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )

    def process(intent_name, *_args, **_kwargs):
        content = "Zmlyc3Q=" if intent_name == "cancel-contract" else "c2Vjb25k"
        _record_named_test_attachment("label.pdf", content, intent_name)
        return IntentReviewOutput(summary=f"Processed {intent_name}")

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)
    monkeypatch.setattr(
        orchestrator,
        "read_config",
        lambda *_args, **_kwargs: SimpleNamespace(
            phishing_monitoring_enabled=False,
            prompt_injection_monitoring_enabled=False,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "run_identity_agent",
        lambda *_args, **_kwargs: IdentityResult(),
    )
    monkeypatch.setattr(
        orchestrator,
        "detect_phishing",
        lambda *_args, **_kwargs: PhishingResult(),
    )
    monkeypatch.setattr(
        orchestrator,
        "detect_prompt_injection",
        lambda *_args, **_kwargs: PromptInjectionResult(),
    )

    pipeline_result = orchestrator.run_pipeline(_email(), compose_response=False)

    outcome_filenames = [
        attachment.filename
        for concern in pipeline_result.intent_result.concerns
        for attachment in concern.attachments
        if attachment.source == "tool"
    ]
    generated_filenames = [attachment.filename for attachment in pipeline_result.agent_response.generated_attachments]
    assert len(outcome_filenames) == 2
    assert len(set(outcome_filenames)) == 2
    assert all(filename != "label.pdf" for filename in outcome_filenames)
    assert generated_filenames == outcome_filenames
    assert pipeline_result.agent_response.response_attachments == outcome_filenames

    loaded = load_attachment_files(pipeline_result.agent_response)

    assert loaded is not None
    assert [item["filename"] for item in loaded] == outcome_filenames
    assert [item["content_base64"] for item in loaded] == ["Zmlyc3Q=", "c2Vjb25k"]

    repeated_result = orchestrator.run_pipeline(_email(), compose_response=False)
    assert [
        attachment.filename for attachment in repeated_result.agent_response.generated_attachments
    ] == generated_filenames


def test_same_concern_duplicate_generated_filenames_are_both_advertised(monkeypatch):
    _base_stubs(monkeypatch)
    route = ConcernRoute(
        summary="Two labels",
        source_text="Create two labels.",
        intent_name="cancel-contract",
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: ([route], None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda *_args, **_kwargs: [{"name": "make-label", "method": "POST"}],
    )
    monkeypatch.setattr("automail.pipeline.intent.agent.get_intent_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )

    def process(*_args, **_kwargs):
        _record_named_test_attachment("label.pdf", "b25l", "one")
        _record_named_test_attachment("label.pdf", "dHdv", "two")
        return IntentReviewOutput(summary="Created two labels")

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)
    generated_token = begin_generated_attachment_collection()
    try:
        result, _response = run_intent_agent(_email())
    finally:
        generated = collect_generated_attachments(generated_token)

    outcome_filenames = [item.filename for item in result.concerns[0].attachments]
    generated_filenames = [str(item.get("filename") or "") for item in generated]
    assert len(outcome_filenames) == 2
    assert len(set(outcome_filenames)) == 2
    assert generated_filenames == outcome_filenames
    assert [item["content_base64"] for item in generated] == ["b25l", "dHdv"]
