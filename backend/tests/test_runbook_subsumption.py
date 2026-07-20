from __future__ import annotations

from typing import Any

from automail.models import ConcernRoute, Email
from automail.pipeline.intent import agent, intents_factory


def _enable_fulfillment_subsumption(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        agent,
        "get_intent_subsumes_runbooks",
        lambda intent_name, intents_dir=None: (
            ["fulfillment-shipment-status"]
            if intent_name == "fulfillment-delivery-exception"
            else []
        ),
    )


def test_e04_delivery_exception_subsumes_generic_status_for_same_order(
    monkeypatch: Any,
) -> None:
    _enable_fulfillment_subsumption(monkeypatch)
    body = (
        "Order ZF-88310 has not moved for 3 days. Give the last scan, location, "
        "and delivery window, and open a delivery-exception investigation now. "
        "Has it already opened, and when will it be resolved?"
    )
    email = Email(
        id="message-e04",
        subject="Stalled shipment exception for ZF-88310",
        from_address="elena.rossi@example.test",
        body=body,
        attachments=[],
    )
    routes = [
        ConcernRoute(
            summary="Stalled shipment requiring an exception investigation",
            source_text=body,
            answer_obligations=[
                "Has it already opened, and when will it be resolved?",
                (
                    "Give the last scan, location, and delivery window, and open "
                    "a delivery-exception investigation now."
                ),
            ],
            intent_name="fulfillment-delivery-exception",
            confidence=0.98,
        ),
        ConcernRoute(
            summary="Shipment status request",
            source_text="Give the last scan, location, and delivery window",
            answer_obligations=[
                "Give the last scan",
                "location",
                "delivery window",
            ],
            intent_name="fulfillment-shipment-status",
            confidence=1.0,
        ),
    ]

    merged = agent._apply_runbook_subsumption(email, routes, intents_dir=object())

    assert len(merged) == 1
    assert merged[0].intent_name == "fulfillment-delivery-exception"
    assert merged[0].source_text == body
    assert merged[0].answer_obligations == [
        "Has it already opened, and when will it be resolved?",
        (
            "Give the last scan, location, and delivery window, and open "
            "a delivery-exception investigation now."
        ),
        "Give the last scan",
        "location",
        "delivery window",
    ]
    assert merged[0].confidence == 1.0


def test_runbook_subsumption_merges_distinct_source_spans_for_same_order(
    monkeypatch: Any,
) -> None:
    _enable_fulfillment_subsumption(monkeypatch)
    email = Email(
        id="message-same-order",
        subject="Order ZF-88310",
        from_address="elena.rossi@example.test",
        body=(
            "Open a delivery exception for ZF-88310. "
            "Give shipment status for ZF-88310."
        ),
        attachments=[],
    )
    routes = [
        ConcernRoute(
            source_text="Open a delivery exception for ZF-88310.",
            answer_obligations=["Open a delivery exception."],
            intent_name="fulfillment-delivery-exception",
        ),
        ConcernRoute(
            source_text="Give shipment status for ZF-88310.",
            answer_obligations=["Give shipment status."],
            intent_name="fulfillment-shipment-status",
        ),
    ]

    merged = agent._apply_runbook_subsumption(email, routes, intents_dir=object())

    assert len(merged) == 1
    assert merged[0].source_text == (
        "Open a delivery exception for ZF-88310.\n"
        "Give shipment status for ZF-88310."
    )
    assert merged[0].answer_obligations == [
        "Open a delivery exception.",
        "Give shipment status.",
    ]


def test_runbook_subsumption_never_collapses_distinct_order_identifiers(
    monkeypatch: Any,
) -> None:
    _enable_fulfillment_subsumption(monkeypatch)
    email = Email(
        id="message-two-orders",
        subject="Two separate orders",
        from_address="elena.rossi@example.test",
        body=(
            "Open a delivery exception for ZF-88310. "
            "Give shipment status for ZF-20991."
        ),
        attachments=[],
    )
    routes = [
        ConcernRoute(
            source_text="Open a delivery exception for ZF-88310.",
            answer_obligations=["Open the exception."],
            intent_name="fulfillment-delivery-exception",
        ),
        ConcernRoute(
            source_text="Give shipment status for ZF-20991.",
            answer_obligations=["Give shipment status."],
            intent_name="fulfillment-shipment-status",
        ),
    ]

    assert agent._apply_runbook_subsumption(
        email,
        routes,
        intents_dir=object(),
    ) == routes


def test_runbook_subsumption_does_not_guess_for_unlabeled_route_with_two_orders(
    monkeypatch: Any,
) -> None:
    _enable_fulfillment_subsumption(monkeypatch)
    email = Email(
        id="message-ambiguous-order",
        subject="Exception for ZF-88310",
        from_address="elena.rossi@example.test",
        body=(
            "Open a delivery exception for ZF-88310. "
            "For separate order ZF-20991, give the latest shipment status."
        ),
        attachments=[],
    )
    routes = [
        ConcernRoute(
            source_text="Open a delivery exception for ZF-88310.",
            intent_name="fulfillment-delivery-exception",
        ),
        ConcernRoute(
            source_text="Give the latest shipment status.",
            intent_name="fulfillment-shipment-status",
        ),
    ]

    assert agent._apply_runbook_subsumption(
        email,
        routes,
        intents_dir=object(),
    ) == routes


def test_runbook_subsumption_fails_safe_for_cyclic_runtime_contract(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        agent,
        "get_intent_subsumes_runbooks",
        lambda intent_name, intents_dir=None: {
            "specialized": ["generic"],
            "generic": ["specialized"],
        }.get(intent_name, []),
    )
    email = Email(
        id="message-cycle",
        subject="Order ZF-88310",
        from_address="elena.rossi@example.test",
        body="Process order ZF-88310.",
        attachments=[],
    )
    routes = [
        ConcernRoute(source_text=email.body, intent_name="specialized"),
        ConcernRoute(source_text=email.body, intent_name="generic"),
    ]

    assert agent._apply_runbook_subsumption(
        email,
        routes,
        intents_dir=object(),
    ) == routes


def test_subsumption_frontmatter_contract_is_explicit_and_deduplicated(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        intents_factory,
        "get_intent_frontmatters",
        lambda intents_dir=None: [
            {
                "name": "fulfillment-delivery-exception",
                "subsumes_runbooks": [
                    "fulfillment-shipment-status",
                    "fulfillment-shipment-status",
                    "fulfillment-delivery-exception",
                    "",
                ],
            }
        ],
    )

    assert intents_factory.get_intent_subsumes_runbooks(
        "FULFILLMENT-DELIVERY-EXCEPTION"
    ) == ["fulfillment-shipment-status"]
