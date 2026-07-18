"""Focused tests for multi-concern runbook execution."""

from automail.models import ConcernRoute, Email, IntentProcessingOutput, IntentReviewOutput
from automail.pipeline.intent.agent import _concern_id, _execute_routed_concern, run_intent_agent


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
    monkeypatch.setattr("automail.pipeline.intent.agent.current_generated_attachments", lambda: [])
    monkeypatch.setattr("automail.pipeline.intent.agent.current_tool_calls", lambda: [])


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
    monkeypatch.setattr("automail.pipeline.intent.agent._run_intent_router_agent", lambda *_args, **_kwargs: (routes, None))
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_actions",
        lambda intent_name, **_kwargs: [{
            "name": f"prepare-{intent_name}",
            "label": f"Prepare {intent_name}",
            "type": "button",
        }],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda intent_name, **_kwargs: {
            "enabled": True,
            "response_rules": [f"Explain {intent_name} state."],
        },
    )
    calls: list[tuple[str, str, str]] = []

    def process(intent_name, _actions, email, *_args, **_kwargs):
        calls.append((intent_name, email.subject, email.body))
        return IntentProcessingOutput(
            summary=f"Prepared {intent_name}",
            reply_requirements=[f"Cover {intent_name}."],
        )

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)

    result, response = run_intent_agent(_email())

    assert calls == [
        (
            "cancel-contract",
            "Cancel contract C-1",
            "## Routed concern to process\nCancel contract C-1.\n\n"
            "## Full original customer message context\nSubject: Cancel and buy\n\n"
            "Cancel contract C-1. I also want to buy three XYZ units.",
        ),
        (
            "buy-product",
            "Buy three XYZ units",
            "## Routed concern to process\nI also want to buy three XYZ units.\n\n"
            "## Full original customer message context\nSubject: Cancel and buy\n\n"
            "Cancel contract C-1. I also want to buy three XYZ units.",
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
    assert [
        obligation.question for obligation in result.concerns[0].answer_obligations
    ] == [
        "Confirm whether contract C-1 can be cancelled.",
        "Explain when cancellation becomes effective.",
    ]
    assert [
        obligation.obligation_id for obligation in result.concerns[0].answer_obligations
    ] == [
        f"{result.concerns[0].concern_id}:obligation-1",
        f"{result.concerns[0].concern_id}:obligation-2",
    ]
    assert result.concerns[0].concern_id != result.concerns[1].concern_id


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
            "What is the consultation fee? Is a retainer required? "
            "When is the invoice due? Can the retainer be waived?"
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
        "## Full original customer message context\nSubject: Cancel and buy\n\n"
        "Cancel contract C-1. I also want to buy three XYZ units.",
        "## Routed concern to process\nCancel contract C-2.\n\n"
        "## Full original customer message context\nSubject: Cancel and buy\n\n"
        "Cancel contract C-1. I also want to buy three XYZ units.",
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
    assert processing_bodies[0].startswith(
        "## Routed concern to process\nTell me the current shipment status and ETA."
    )
    assert processing_bodies[1].startswith(
        "## Routed concern to process\nChange the delivery address to 24 New Street."
    )


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
    monkeypatch.setattr("automail.pipeline.intent.agent._run_intent_router_agent", lambda *_args, **_kwargs: (routes, None))
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
    monkeypatch.setattr("automail.pipeline.intent.agent._run_intent_router_agent", lambda *_args, **_kwargs: (routes, None))
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
        return IntentProcessingOutput(summary="Purchase prepared")

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
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_processing_agent",
        lambda *_args, **_kwargs: IntentReviewOutput.model_validate({
            "summary": "Lookup complete",
            "verified_facts": [{"fact": "Invented cancellation date"}],
            "tool_evidence": [{"tool_name": "fake", "facts": [{"fact": "Invented"}]}],
        }),
    )
    snapshots = iter([
        [],
        [{
            "name": "contract_lookup",
            "method": "GET",
            "status": "success",
            "responseFacts": [{"path": "contract.status", "value": "active"}],
        }],
    ])
    monkeypatch.setattr("automail.pipeline.intent.agent.current_tool_calls", lambda: next(snapshots))
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
