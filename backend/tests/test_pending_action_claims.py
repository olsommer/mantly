import pytest

from automail.support.pending_action_claims import (
    PENDING_ACTION_CLAIM_REASON_CODE,
    check_pending_action_claims,
)


def _actions(status: str = "pending_approval") -> list[dict[str, str]]:
    return [
        {
            "name": "open_ticket",
            "label": "Open fulfillment investigation",
            "status": status,
        }
    ]


@pytest.mark.parametrize(
    "answer",
    [
        "We are initiating the steps to open this investigation.",
        "We are checking if there are any separate parcels associated with this order.",
        "We are escalating this incident for immediate human operations review.",
        "We're currently investigating the delivery exception.",
        "I am looking into the missing parcel.",
    ],
)
def test_pending_action_guard_blocks_live_progressive_claims(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert PENDING_ACTION_CLAIM_REASON_CODE == "pending_action_claim"
    assert result.blocked is True
    assert result.pending_actions == ("Open fulfillment investigation",)
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We have opened a delivery investigation.",
        "We have immediately escalated this case to our operations team.",
        "We immediately opened a warehouse ticket.",
        "A delivery-exception investigation is being initiated.",
        "This urgent safety incident is being escalated for human review.",
        "We escalated the safety incident.",
        "Your refund has been issued.",
        "The investigation is now in progress.",
        "The incident has been flagged for urgent human operations review.",
        "This request has been marked for escalation.",
        "We have also internally escalated your request for urgent triage.",
        "We are prioritizing your matter.",
        "Your matter has been prioritized for urgent review.",
        "We will prioritize your matter immediately.",
        "A warehouse ticket for this order is pending approval and will be opened shortly.",
        "We will escalate this to our team.",
        "Your order has been cancelled.",
        "The contract was terminated.",
        "Our subscription has been canceled.",
        "The shipping address has been changed.",
        "This order cancellation is complete.",
        "Your subscription will be cancelled.",
    ],
)
def test_pending_action_guard_blocks_completed_or_active_state_claims(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


def test_pending_action_guard_blocks_exact_live_coordinated_triage_claims() -> None:
    answer = (
        "We have noted the critical deadline of 20 July 2026 and have escalated "
        "your request for immediate human triage due to its urgency. While we "
        "cannot promise a same-day consultation, we are prioritizing your matter."
    )

    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (
        (
            "We have noted the critical deadline of 20 July 2026 and have escalated "
            "your request for immediate human triage due to its urgency."
        ),
        (
            "While we cannot promise a same-day consultation, we are prioritizing "
            "your matter."
        ),
    )


@pytest.mark.parametrize(
    "answer",
    [
        "We can initiate the investigation after review.",
        "We will check for separate parcels once the action is approved.",
        "We could escalate this after approval.",
        "The escalation is pending approval.",
        "This urgent safety incident is pending human review.",
        "We have not escalated this incident.",
        "We have not immediately escalated this case.",
        "We have noted the deadline and have not escalated your request.",
        "We are not prioritizing your matter before approval.",
        "We cannot prioritize your matter until a human approves triage.",
        "We will prioritize your matter once triage is approved.",
        "We cannot promise that your matter will be prioritized before approval.",
        "We are unable to promise a replacement or refund before this verification is complete.",
        "We are waiting for approval before escalating.",
        "We are ready to check this after approval.",
        "We will follow up once our team has reviewed your address change request.",
        "After the request has been reviewed, we will let you know the result.",
        "Once approved, the warehouse ticket will be opened.",
        (
            "This parcel is currently in transit and was processed at the DHL "
            "Paketzentrum Ruedersdorf today at 08:42."
        ),
        "The parcel will be processed at the depot tomorrow.",
        "Your order will be processed at the carrier depot tomorrow.",
        "We will cancel your order once the cancellation is approved.",
    ],
)
def test_pending_action_guard_allows_conditional_future_negative_and_pending_language(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.pending_actions == ("Open fulfillment investigation",)
    assert result.claims == ()


def test_pending_action_guard_does_not_apply_without_pending_approval() -> None:
    answer = "We are escalating this incident now."

    success = check_pending_action_claims(answer=answer, runbook_actions=_actions("success"))
    no_actions = check_pending_action_claims(answer=answer, runbook_actions=[])

    assert success == no_actions
    assert success.blocked is False


def test_pending_action_guard_reports_each_unsafe_answer_unit_once() -> None:
    answer = "We are checking the parcel. We have escalated the incident. We will reply after approval."

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[*_actions(), *_actions()],
    )

    assert result.pending_actions == ("Open fulfillment investigation",)
    assert result.claims == (
        "We are checking the parcel.",
        "We have escalated the incident.",
    )


def test_future_condition_does_not_hide_separate_completed_claim() -> None:
    answer = "We have opened a ticket and will reply once the request has been reviewed."

    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


def test_negative_refusal_does_not_hide_separate_completed_action() -> None:
    answer = (
        "We are unable to promise a replacement, but we have immediately "
        "escalated your case."
    )

    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


def test_future_condition_does_not_hide_separate_future_claim() -> None:
    answer = "We will escalate this now, and once approved we will contact you."

    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We will cancel your order and contact you once the address change is approved.",
        "We will change your address, but we will contact you once the request is approved.",
        "Once approved, we will contact you, but we will cancel your subscription now.",
    ],
)
def test_unrelated_future_condition_does_not_hide_action_promise(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Wir haben das Ticket eröffnet.",
        "Wir haben den Fall eskaliert.",
        "Ihre Bestellung wurde storniert.",
        "Ihr Vertrag wurde gekündigt.",
        "Ihre Adresse wurde geändert.",
        "Wir haben Ihnen den Betrag zurückerstattet.",
        "Wir werden das Ticket eröffnen.",
        "Ihre Bestellung wird storniert.",
        "Nous avons ouvert le ticket.",
        "La commande a été annulée.",
        "Nous allons rembourser le client.",
        "Hemos escalado el caso.",
        "El pedido ha sido cancelado.",
        "Vamos a reembolsar al cliente.",
        "Abbiamo aperto il ticket.",
        "L'ordine è stato annullato.",
        "Stiamo per rimborsare il cliente.",
    ],
)
def test_pending_action_guard_blocks_multilingual_action_claims(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Wir haben das Ticket nicht eröffnet.",
        "Wir werden das Ticket eröffnen, sobald die Freigabe bestätigt wurde.",
        "Nous n'avons pas annulé la commande.",
        "No hemos cancelado el pedido.",
        "Non abbiamo annullato l'ordine.",
    ],
)
def test_pending_action_guard_allows_multilingual_negative_or_conditional_claims(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()
