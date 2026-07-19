import pytest

from automail.support.pending_action_claims import (
    PENDING_ACTION_CLAIM_REASON_CODE,
    PENDING_ACTION_REPAIR_NOTICE,
    check_pending_action_claims,
    has_durable_action_success,
    has_meaningful_action_success_proof,
    has_success_backed_action_claim,
    repair_pending_action_claims,
)


def _actions(status: str = "pending_approval") -> list[dict[str, str]]:
    return [
        {
            "name": "open_ticket",
            "label": "Open fulfillment investigation",
            "status": status,
        }
    ]


def _tracking_evidence(
    *,
    method: str = "GET",
    status: str = "success",
    include_tracking_id: bool = True,
) -> list[dict[str, object]]:
    facts: list[dict[str, object]] = [
        {"path": "orderNumber", "value": "ZF-10482"},
        {"path": "status", "value": "in_transit"},
    ]
    if include_tracking_id:
        facts.append(
            {
                "path": "trackingNumber",
                "value": "UPS1Z999AA10123456784",
            }
        )
    return [
        {
            "name": "lookup-zf-e2e-shipment",
            "method": method,
            "status": status,
            "responseFacts": facts,
        }
    ]


def _durable_success_action(
    *,
    name: str = "cancel_order",
    label: str = "Cancel order",
    concern_id: str = "concern-order",
    proof: object = None,
) -> dict[str, object]:
    return {
        "name": name,
        "label": label,
        "status": "success",
        "concernId": concern_id,
        "applied": True,
        "webhookResult": {"status": "ok"},
        "evidenceId": f"action:{concern_id}:{name}",
        "proof": proof or {"confirmationNumber": "CAN-10482"},
    }


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
        "Conflict ESC-1 has been escalated for human review.",
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


@pytest.mark.parametrize(
    "answer",
    [
        "We paused substantive discussion for MAT-2026-221.",
        "We have stopped the substantive discussion for MAT-2026-221.",
        "We've paused substantive discussion for MAT-2026-221.",
        "We are pausing substantive discussion for MAT-2026-221.",
        "We're pausing substantive discussion for MAT-2026-221.",
        "We’ll pause substantive discussion for MAT-2026-221.",
        "We are going to pause substantive discussion for MAT-2026-221.",
        "We plan to stop substantive discussion for MAT-2026-221.",
        "We intend to pause substantive discussion for MAT-2026-221.",
        "We will need to pause substantive discussion for MAT-2026-221.",
        "We definitely will pause substantive discussion for MAT-2026-221.",
        "We will be pausing substantive discussion for MAT-2026-221.",
        "We promise to pause substantive discussion for MAT-2026-221.",
        "We commit to pausing substantive discussion for MAT-2026-221.",
        "We expect to pause substantive discussion for MAT-2026-221.",
        "We aim to stop substantive discussion for MAT-2026-221.",
        "We agree to pause substantive discussion for MAT-2026-221.",
        "We undertake to stop substantive discussion for MAT-2026-221.",
        "We are scheduled to pause substantive discussion for MAT-2026-221.",
        "Our legal team will pause substantive discussion for MAT-2026-221.",
        "Our legal team is scheduled to pause substantive discussion for MAT-2026-221.",
        "Our conflicts team is pausing substantive discussion for MAT-2026-221.",
        "We did pause substantive discussion for MAT-2026-221.",
        "Substantive discussion is paused while the conflict is reviewed.",
        "Substantive discussion remains paused while the conflict is reviewed.",
        "The substantive discussion has been stopped.",
        "We will pause substantive discussion for MAT-2026-221.",
        "We shall stop the substantive discussion for MAT-2026-221.",
        "Substantive discussion will be paused while the conflict is reviewed.",
        "Substantive discussions will be paused while the conflict is reviewed.",
        "The substantive discussion shall be stopped.",
    ],
)
def test_pending_action_guard_blocks_substantive_discussion_state_claims(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Substantive discussion will not be paused.",
        "Substantive discussion is not paused.",
        "We cannot confirm whether substantive discussion will be paused.",
        "Once human approval is granted, substantive discussion will be paused.",
        "We do not promise to pause substantive discussion.",
        "We are not scheduled to pause substantive discussion.",
        "We definitely will not pause substantive discussion.",
        "Our legal team is not scheduled to pause substantive discussion.",
        "We cannot commit to pausing substantive discussion.",
        "If human approval is granted, we will be pausing substantive discussion.",
        "Substantive discussion was paused by the client.",
    ],
)
def test_pending_action_guard_allows_safe_substantive_discussion_states(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False


def test_pending_action_repair_removes_live_substantive_discussion_promise() -> None:
    answer = (
        "We received the potential-conflict report. Substantive discussion for "
        "MAT-2026-221 will be paused while the potential conflict is under review."
    )

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=_actions(),
    )

    assert "will be paused" not in repaired
    assert "We received the potential-conflict report." in repaired
    assert PENDING_ACTION_REPAIR_NOTICE in repaired
    assert check_pending_action_claims(
        answer=repaired,
        runbook_actions=_actions(),
    ).blocked is False


def test_pending_action_guard_blocks_future_third_party_discussion_promise() -> None:
    answer = "Substantive discussion will be paused by the client."

    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Refund issued.",
        "Order cancelled.",
        "Conflict escalated.",
        "Ticket opened.",
        "Cancellation complete.",
        "Refund: issued.",
        "Refund RF-1 issued.",
        "Ticket T-1 opened.",
        "Conflict in matter MAT-1 recorded.",
        "Refund of CHF 100 issued.",
        "- Refund issued.",
        "> Refund issued.",
        "> > Refund issued.",
        "# Refund issued.",
        "+ Refund issued.",
        "- [x] Refund issued.",
        "1. [x] Refund issued.",
        "1 - [x] Refund issued.",
        "| Refund | issued |",
        "Refund | issued",
        "* Refund issued.",
        "• Refund issued.",
        "1) Refund issued.",
        "**Refund issued.**",
        "`Refund issued.`",
        "Refund — issued.",
        "Refund – issued.",
        "Status: Refund issued.",
        "Result: Refund issued.",
        "✅ Refund issued.",
        "Refund\nissued.",
        "We have **issued** your refund.",
        "We have _issued_ your refund.",
        "We have `issued` your refund.",
        "We have <strong>issued</strong> your refund.",
        "We will **issue** your refund.",
        "Your refund has been **issued**.",
        "Cancelled: order A.",
        "Cancelled order A.",
        "Issued: refund RF-1.",
        "Opened ticket T-1.",
        "Escalated: conflict MAT-1.",
        "Completed: cancellation.",
        "Done: cancellation.",
        "Underway: cancellation.",
        "Sorted: your request.",
        "Successfully cancelled: order A.",
        "Processing: refund RF-1.",
        "Cancellation underway.",
        "Cancellation in progress.",
        "Refund processing.",
        "Investigation ongoing.",
        "Escalation ongoing.",
        "Ticket opening.",
    ],
)
def test_pending_action_guard_blocks_terse_or_formatted_claims(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We hereby issue the refund.",
        "We intend to issue the refund.",
        "We plan to issue the refund.",
        "We are set to issue the refund.",
        "I've gone ahead and issued the refund.",
        "We went ahead and issued the refund.",
        "I went ahead and cancelled the order.",
        "Consider the refund issued.",
        "Refund will be issued.",
        "Order will be cancelled.",
        "Ticket will be opened.",
        "Conflict will be escalated.",
        "Order is being cancelled.",
        "Order has been cancelled.",
        "Cancellation successful.",
        "Your cancellation is successful.",
        "The cancellation has gone through.",
        "The cancellation went through.",
        "Consider it done.",
        "Your cancellation is all set.",
        "That has been handled.",
        "This request is sorted.",
        "Cancellation finalized.",
        "Your cancellation request is resolved.",
        "Your contract is no longer active.",
        "The agreement is terminated.",
        "The cancellation has been actioned.",
        "Cancellation was taken care of.",
        "Your cancellation is all done.",
    ],
)
def test_pending_action_guard_blocks_performative_or_bare_passive_claims(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Refund not issued.",
        "Order not cancelled.",
        "Conflict not escalated.",
        "Ticket not opened.",
        "Cancellation incomplete.",
        "Cancellation unsuccessful.",
        "The cancellation has not gone through.",
        "We do not intend to issue the refund.",
        "We plan to issue the refund after human approval.",
        "We are set to issue the refund once approved.",
        "Your order will be processed at the carrier depot tomorrow.",
        "Order has been processed at the carrier depot.",
        "Refund policy: issued refunds take five days.",
        "To issue a refund, approval is required.",
    ],
)
def test_pending_action_guard_allows_negative_conditional_or_policy_text(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        "We are confirming executive escalation.",
        "We confirmed executive escalation.",
        "We have confirmed executive escalation.",
        "Executive escalation is confirmed.",
        "Executive escalation has been confirmed.",
        "The escalation had been confirmed.",
        "Executive escalation will be confirmed.",
        "A human agent will confirm executive escalation.",
        "I confirm executive escalation.",
        "We confirm executive escalation.",
        "We will confirm executive escalation.",
        "We can confirm executive escalation.",
        "I can confirm executive escalation.",
        "We can now confirm executive escalation.",
        ("No escalation was requested, but executive escalation has been confirmed."),
        "No escalation was requested; executive escalation has been confirmed.",
    ],
)
def test_pending_action_guard_blocks_unsupported_confirmation_state(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We cannot confirm executive escalation.",
        "We can't confirm executive escalation.",
        "We can not confirm executive escalation.",
        "Executive escalation is not confirmed.",
        "Executive escalation has not been confirmed.",
        "The escalation had not been confirmed.",
        "Executive escalation will not be confirmed.",
        "After review, executive escalation will be confirmed.",
        "A human agent will not confirm executive escalation.",
        "After review, a human agent will confirm executive escalation.",
        "We do not confirm executive escalation.",
        ("No escalation, replacement, refund, collection, return, or other business action has been confirmed."),
        "Executive escalation is pending confirmation.",
        "After review we can confirm executive escalation.",
        "We confirmed tracking UPS1Z999AA10123456784.",
        "We confirmed your email address.",
        "We will confirm the tracking status.",
    ],
)
def test_pending_action_guard_allows_safe_confirmation_state(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


def test_pending_action_guard_blocks_exact_live_b2b_escalation_claim() -> None:
    answer = "This urgent B2B SLA incident has been escalated for human operations review."
    actions = [
        {"name": "agent_triage", "label": "Agent triage", "status": "pending_approval"},
        {"name": "open_ticket", "label": "Open ticket", "status": "pending_approval"},
    ]

    result = check_pending_action_claims(answer=answer, runbook_actions=actions)

    assert result.blocked is True
    assert result.pending_actions == ("Agent triage", "Open ticket")
    assert result.claims == (answer,)


def test_pending_action_guard_blocks_exact_active_internal_review_claim() -> None:
    answer = "This matter is now undergoing an internal review process."
    actions = [{"name": "agent_triage", "label": "Agent triage", "status": "pending_approval"}]

    result = check_pending_action_claims(answer=answer, runbook_actions=actions)

    assert result.blocked is True
    assert result.pending_actions == ("Agent triage",)
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "This matter is not undergoing an internal review process.",
        "This matter is pending internal review.",
        "This matter will undergo an internal review once approved.",
        "This legal opinion discusses the court's standard of review.",
    ],
)
def test_pending_action_guard_allows_safe_internal_review_nearby_language(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        "I've checked tracking for UPS1Z999AA10123456784, and it is in transit.",
        "We have checked the tracking status for UPS1Z999AA10123456784.",
        "I checked the shipment status for UPS1Z999AA10123456784.",
    ],
)
def test_pending_action_guard_allows_proven_readonly_tracking_check(
    answer: str,
) -> None:
    actions = [
        {"name": "agent_triage", "label": "Agent triage", "status": "pending_approval"},
        {"name": "open_ticket", "label": "Open ticket", "status": "pending_approval"},
    ]

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=actions,
        tool_evidence=_tracking_evidence(),
    )

    assert result.blocked is False
    assert result.pending_actions == ("Agent triage", "Open ticket")
    assert result.claims == ()


@pytest.mark.parametrize(
    ("answer", "evidence", "actions"),
    [
        (
            "I've checked tracking for UPS1Z999AA10123456784.",
            [],
            _actions(),
        ),
        (
            "I've checked tracking for UPS1Z999AA10123456784.",
            _tracking_evidence(method="POST"),
            _actions(),
        ),
        (
            "I've checked tracking for UPS1Z999AA10123456784.",
            _tracking_evidence(status="http_500"),
            _actions(),
        ),
        (
            "I've checked tracking for UPS1Z999AA10123456784.",
            _tracking_evidence(include_tracking_id=False),
            _actions(),
        ),
        (
            "I've checked tracking for UPS1Z999AA10123456785.",
            _tracking_evidence(),
            _actions(),
        ),
        (
            "I've checked tracking for UPS1Z999AA10123456784-EXTRA.",
            _tracking_evidence(),
            _actions(),
        ),
        (
            "I've checked the tracking status.",
            _tracking_evidence(),
            _actions(),
        ),
        (
            "I've checked your refund request.",
            _tracking_evidence(),
            _actions(),
        ),
        (
            "I've checked your cancellation request.",
            _tracking_evidence(),
            _actions(),
        ),
        (
            "I've checked tracking for UPS1Z999AA10123456784.",
            _tracking_evidence(),
            [
                {
                    "name": "check_shipment_tracking",
                    "label": "Check shipment tracking",
                    "status": "pending_approval",
                }
            ],
        ),
        (
            ("I've checked tracking for UPS1Z999AA10123456784, and I've opened a ticket."),
            _tracking_evidence(),
            _actions(),
        ),
        (
            ("I've checked tracking for UPS1Z999AA10123456784 and escalated your case."),
            _tracking_evidence(),
            _actions(),
        ),
        (
            ("I've checked tracking for UPS1Z999AA10123456784 and opened a ticket."),
            _tracking_evidence(),
            _actions(),
        ),
        (
            ("I've checked tracking for UPS1Z999AA10123456784, then escalated your case."),
            _tracking_evidence(),
            _actions(),
        ),
    ],
)
def test_pending_action_guard_keeps_unproven_mutating_or_related_checks_blocked(
    answer: str,
    evidence: list[dict[str, object]],
    actions: list[dict[str, str]],
) -> None:
    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=actions,
        tool_evidence=evidence,
    )

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "This urgent B2B SLA incident has not been escalated.",
        "This urgent B2B SLA incident is pending escalation.",
        "This urgent B2B SLA incident can be escalated after approval.",
        "The B2B shipment has been processed at the UPS depot.",
        "The B2B order was updated by the carrier tracking feed.",
        "Your order has been dispatched by DHL.",
        "The deadline was updated by the court.",
        "The contract was terminated by the customer.",
        "The subscription was cancelled automatically at expiry.",
        "The delivery address was changed by the customer in checkout.",
        "The contract was terminated by opposing counsel.",
    ],
)
def test_pending_action_guard_allows_safe_b2b_nearby_language(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        "The order has been cancelled; the tracking record was updated by the carrier.",
        "The order was cancelled by our team after the status was updated by the carrier.",
        "The order was cancelled by our team and recorded by the customer.",
        "The order was cancelled by the customer service team.",
    ],
)
def test_external_attribution_cannot_exempt_a_first_party_action_claim(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        ("A specialist will review your request and follow up with you regarding the next steps for this."),
        "A human agent will follow up with you shortly to assist further with this case.",
        "An agent will be in touch shortly to assist you further.",
        "Our team will contact you with an update.",
        "Operations will investigate the delivery exception.",
        "The operations team will open a warehouse ticket.",
        "A support representative will arrange the replacement.",
        "Our legal team will terminate the contract.",
        "Our billing team will issue the refund.",
        "You can expect an update from us shortly.",
        "We will get back to you.",
        "We shall get back to you.",
        "We will respond with an update.",
        "We will let you know.",
        "Our team will email you.",
        "We will notify you.",
        "We will send you an email.",
        "We will circle back.",
        "We will keep you posted.",
        "You will hear from us shortly.",
        "We will reply shortly.",
        "Our case team will contact you.",
        "Expect to hear from us shortly.",
        "We will respond shortly.",
        "Our conflicts team will update you.",
        "We will drop you a note.",
        "We will be back in touch.",
    ],
)
def test_pending_action_guard_blocks_controlled_support_actor_future_promises(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We will provide an update as soon as more information is available.",
        ("Your request has been forwarded for warehouse verification and a potential carrier redirect."),
        "We will need to investigate further.",
        ("Once reviewed, a human agent will be able to provide further updates."),
    ],
)
def test_pending_action_guard_blocks_exact_final_live_residual_phrases(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We will be in touch once the review is complete.",
        "After the request has been reviewed, we will let you know the result.",
        "We'll contact you when the billing review is complete.",
        "Our billing team will follow up with you after human review.",
        "A human agent will reach out to you if the exception is approved.",
        "Our support team will contact you after review.",
        "You will be contacted by our team after review.",
        "Our team will respond after review.",
        "You will receive an update after review.",
        "Our team will follow-up with you after review.",
        "We will message you after review.",
        "We will reach back out after review.",
    ],
)
def test_pending_action_guard_blocks_future_customer_contact_despite_condition(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Wir werden Sie nach der Prüfung kontaktieren.",
        "Nach der Prüfung werden wir Sie kontaktieren.",
        "Wir werden Ihnen nach der Prüfung antworten.",
        "Wir werden Sie nach der Prüfung informieren.",
        "Wir werden Sie nach der Prüfung benachrichtigen.",
        "Wir werden Sie nach der Prüfung auf dem Laufenden halten.",
        "Wir werden Ihnen nach der Prüfung ein Update senden.",
        "Nous vous contacterons après examen.",
        "Nous vous répondrons après examen.",
        "Nous vous informerons après examen.",
        "Nous vous notifierons après examen.",
        "Nous vous tiendrons informé après examen.",
        "Nous vous enverrons une mise à jour après examen.",
        "Le contactaremos después de la revisión.",
        "Nos pondremos en contacto con usted después de la revisión.",
        "Le responderemos después de la revisión.",
        "Le informaremos después de la revisión.",
        "Le notificaremos después de la revisión.",
        "Le mantendremos informado después de la revisión.",
        "Le enviaremos una actualización después de la revisión.",
        "La contatteremo dopo la revisione.",
        "Ci metteremo in contatto con lei dopo la revisione.",
        "Le risponderemo dopo la revisione.",
        "La informeremo dopo la revisione.",
        "La notificheremo dopo la revisione.",
        "La terremo aggiornata dopo la revisione.",
        "Le invieremo un aggiornamento dopo la revisione.",
    ],
)
def test_pending_action_guard_blocks_multilingual_conditional_customer_contact(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We will provide the export link once it is available.",
        "Our team will send you the download link after export approval.",
        "We will share the export file after review.",
        "We will email you the report once it is generated.",
        "You will receive the data export after approval.",
        "The export link will be sent once it is ready.",
    ],
)
def test_pending_action_guard_blocks_conditional_action_artifact_delivery(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        (
            "Once we have these confirmations, we can confirm the deletion is complete "
            "and that no retained copies exist."
        ),
        "After review, we will confirm the data deletion is complete.",
        "Our team will confirm the export is complete once approved.",
        "Once approved, we will be able to confirm the deletion has been completed.",
    ],
)
def test_pending_action_guard_blocks_contingent_confirmation_of_completion(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We can confirm whether the deletion is complete after the audit.",
        "We can confirm if the deletion is complete after the audit.",
        "We cannot confirm that the deletion is complete.",
        "We can confirm the deletion is not complete.",
        "We can confirm the request is not complete.",
        "We can confirm the request remains unverified.",
        "We can confirm the request has not been completed.",
        "Our team will confirm the request remains unverified.",
        "The deletion remains unverified.",
        "The vendor will provide the export link after processing.",
        "The vendor can confirm the deletion is complete.",
        "You will receive the export link from the vendor after processing.",
        "We can provide the export link after approval.",
    ],
)
def test_pending_action_guard_allows_safe_artifact_and_completion_contrasts(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        "This request needs human review.",
        "The warehouse verification requires human review before any action.",
    ],
)
def test_pending_action_guard_allows_explicit_human_review_requirement(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


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
        ("While we cannot promise a same-day consultation, we are prioritizing your matter."),
    )


def test_pending_action_guard_blocks_coordinated_future_escalation() -> None:
    answer = "We have noted the potential conflict for MAT-2026-221 and will escalate it for review."

    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We are recording the potential conflict for MAT-2026-221.",
        "We have recorded the potential conflict for MAT-2026-221.",
        "We recorded the potential conflict for MAT-2026-221.",
        "Conflict has been recorded.",
        "The potential conflict has been logged.",
        "We have logged the potential conflict for MAT-2026-221.",
        "We have noted the potential conflict for MAT-2026-221.",
        "We have noted: the potential conflict for MAT-2026-221.",
        "We noted MAT-2026-221 as a potential conflict.",
        "The potential conflict has been noted.",
    ],
)
def test_pending_action_guard_blocks_record_log_or_note_conflict_claims(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We've noted the conflict and will escalate it for review.",
        "We're aware of the conflict and will escalate it for review.",
        "We have noted the conflict and will not only escalate it for review.",
        "We have noted the conflict and therefore will escalate it for review.",
        "We have noted the conflict and definitely will escalate it for review.",
        "We have noted the conflict and will escalate it before human approval.",
        "We have noted the conflict and will escalate it until approval.",
        "We have noted the conflict and will escalate it if review is rejected.",
        "We understand the conflict and will escalate it for review.",
        "We acknowledge the conflict and will escalate it for review.",
        "We noted the conflict and will escalate it for review.",
        "We received the request and will escalate it for review.",
        "We will definitely escalate it for review.",
        "We'll certainly escalate it for review.",
        "We definitely will escalate it for review.",
        "I certainly will escalate it for review.",
    ],
)
def test_pending_action_guard_blocks_adversarial_coordinated_future_escalation(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


def test_pending_action_guard_allows_policy_gerund_after_unrelated_conjunction() -> None:
    answer = "We understand the policy, and reviewing applications is required."

    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        ("We understand the potential conflict and will not escalate it before review."),
        ("We have noted your request and will escalate it once human review is approved."),
    ],
)
def test_pending_action_guard_allows_safe_coordinated_escalation_state(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        "We do not promise that we will escalate the case.",
        "We don't promise that we will escalate the case.",
        "We cannot definitely promise that we will escalate the case.",
        "We cannot confirm that your order has been cancelled.",
        "We cannot confirm whether your order has been cancelled.",
        "We cannot confirm whether we are escalating.",
        "We can't confirm that your order has been cancelled.",
        "We are unable to confirm that your order has been cancelled.",
        "We cannot guarantee that your refund has been issued.",
        "We can't promise the escalation is completed.",
        "It is unclear whether we are escalating the case.",
        "There is no evidence that the refund has been issued.",
        "We deny that we have escalated the case.",
        "We cannot definitely promise that we are escalating the case.",
        "We cannot promise that we will provide an update.",
        "We cannot promise that you will be contacted after review.",
        "Our support team will not contact you after review.",
        "You will not receive an update after review.",
        "Nach der Prüfung werden wir Sie nicht kontaktieren.",
        "Nous ne vous répondrons pas après examen.",
        "No nos pondremos en contacto con usted después de la revisión.",
        "No le responderemos después de la revisión.",
        "Non ci metteremo in contatto con lei dopo la revisione.",
        "Non le risponderemo dopo la revisione.",
        "Wir können nicht versprechen, dass wir Sie nach der Prüfung kontaktieren werden.",
        "Nous ne pouvons pas promettre que nous vous contacterons après examen.",
        "Nous ne pouvons pas promettre que nous vous répondrons après examen.",
        "No podemos prometer que le contactaremos después de la revisión.",
        "No podemos prometer que nos pondremos en contacto con usted después de la revisión.",
        "Non possiamo promettere che la contatteremo dopo la revisione.",
        "Non possiamo promettere che ci metteremo in contatto con lei dopo la revisione.",
        "We have noted that there is no conflict.",
        "No conflict has been noted.",
    ],
)
def test_pending_action_guard_allows_scoped_negative_or_epistemic_claims(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        ("We cannot confirm that your order has been cancelled, but we will escalate the case."),
        ("There is no evidence that the refund has been issued; however, we are escalating the case."),
        ("It is unclear whether the conflict has been recorded, but we have logged the conflict."),
        ("We deny that we have escalated the case, but have recorded the conflict."),
        ("We cannot confirm that we have escalated the case; however, have logged the conflict."),
    ],
)
def test_negative_scope_does_not_hide_later_positive_action_claim(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "After approval expires, we will escalate the case.",
        "If approval is withdrawn, we will escalate the case.",
        "If confirmation is refused, we will escalate the case.",
        "Once approval has lapsed, we will escalate the case.",
        "When approval is revoked, we will escalate the case.",
        "If review is rejected, we will escalate the case.",
        "If approval is denied, we will escalate the case.",
        "If authorization is declined, we will escalate the case.",
        "If verification fails, we will escalate the case.",
    ],
)
def test_negative_or_failed_condition_does_not_make_action_promise_safe(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


def test_subject_to_human_approval_is_a_safe_scoped_condition() -> None:
    answer = "Subject to human approval, we will escalate the case."

    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


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
        "Once approved, the warehouse ticket will be opened.",
        ("This parcel is currently in transit and was processed at the DHL Paketzentrum Ruedersdorf today at 08:42."),
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


@pytest.mark.parametrize(
    "answer",
    [
        "A specialist is expected to follow up after review.",
        "The carrier will update tracking tomorrow.",
        "The customer will contact support after review.",
        "A carrier representative will follow up tomorrow.",
        "Carrier operations will update the tracking scan tomorrow.",
        "Our team will follow up with the carrier after review.",
        "You will be contacted by the carrier after review.",
        "Our team will follow up on the carrier trace after review.",
        "Our team will follow up after review with the carrier.",
        "Our team will respond to the vendor after review.",
        "We will reply to the court after review.",
        "We will reach out regarding the carrier trace after review.",
    ],
)
def test_pending_action_guard_allows_contingent_or_external_actor_future_facts(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.pending_actions == ("Open fulfillment investigation",)
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        "We will follow up with you after the carrier review.",
        "We will follow up after the carrier review with you.",
        "We will respond to you about the carrier trace.",
        "We will reply to the customer after the vendor review.",
        "We will reach out to you regarding the carrier trace.",
    ],
)
def test_external_reference_does_not_hide_explicit_customer_contact_promise(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


def test_pending_action_guard_does_not_apply_without_pending_approval() -> None:
    answer = "We are escalating this incident now."

    success = check_pending_action_claims(answer=answer, runbook_actions=_actions("success"))
    no_actions = check_pending_action_claims(answer=answer, runbook_actions=[])

    assert success == no_actions
    assert success.blocked is False


def test_durable_success_preserves_only_its_matching_cross_concern_claim() -> None:
    successful_unit = "Your order has been cancelled."
    pending_unit = "We will escalate the potential conflict for review."
    actions = [
        {
            "name": "escalate_conflict",
            "label": "Escalate conflict",
            "status": "pending_approval",
            "concernId": "concern-conflict",
        },
        _durable_success_action(concern_id="concern-order"),
    ]
    answer = f"{successful_unit} {pending_unit}"

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=actions,
    )
    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=actions,
    )

    assert result.blocked is True
    assert result.claims == (pending_unit,)
    assert repaired == f"{successful_unit}\n\n{PENDING_ACTION_REPAIR_NOTICE}"
    assert pending_unit not in repaired


def test_durable_success_can_be_read_from_nested_application_record() -> None:
    success = _durable_success_action()
    success["application"] = {
        "applied": success.pop("applied"),
        "webhookResult": success.pop("webhookResult"),
    }
    answer = "Your order has been cancelled."

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[*_actions(), success],
    )

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        "We will cancel the order.",
        "We are going to cancel the order.",
        "We promise to cancel the order.",
        "We are cancelling the order.",
    ],
)
def test_completed_success_never_backs_nonterminal_wording(answer: str) -> None:
    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[*_actions(), _durable_success_action()],
    )

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Wir haben den Konflikt unter ESC-1 eskaliert.",
        "Hemos escalado el conflicto ESC-1.",
        "Abbiamo escalato il conflitto ESC-1.",
    ],
)
def test_exact_success_proof_preserves_localized_terminal_claims(
    answer: str,
) -> None:
    success = _durable_success_action(
        name="escalate_conflict",
        label="Escalate conflict",
        concern_id="concern-conflict",
        proof={"reference": "ESC-1"},
    )

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[*_actions(), success],
    )

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        "Order CAN-10482 and subscription have been cancelled.",
        "The conflict ESC-1 and deadline have been escalated.",
    ],
)
def test_success_proof_cannot_cover_an_additional_action_object(
    answer: str,
) -> None:
    cancel_success = _durable_success_action()
    escalation_success = _durable_success_action(
        name="escalate_conflict",
        label="Escalate conflict",
        concern_id="concern-conflict",
        proof={"reference": "ESC-1"},
    )

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[*_actions(), cancel_success, escalation_success],
    )

    assert result.blocked is True
    assert result.claims == (answer,)


def test_completed_success_does_not_hide_terse_second_action() -> None:
    answer = "We cancelled the order; refund issued."

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=[*_actions(), _durable_success_action()],
    )

    assert repaired == ("We cancelled the order.\n\n" + PENDING_ACTION_REPAIR_NOTICE)


def test_exact_success_proof_can_replace_missing_object_overlap() -> None:
    answer = "Your cancellation CAN-10482 is complete."

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[*_actions(), _durable_success_action()],
    )

    assert result.blocked is False
    assert result.claims == ()


def test_success_proof_does_not_exempt_a_different_action() -> None:
    answer = "Your refund CAN-10482 has been issued."

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[*_actions(), _durable_success_action()],
    )

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"status": "failed"},
        {"applied": False},
        {"webhookResult": {"status": "failed"}},
        {"evidenceId": ""},
        {"proof": {}},
    ],
)
def test_incomplete_success_record_never_exempts_action_claim(
    invalid_fields: dict[str, object],
) -> None:
    success = _durable_success_action()
    success.update(invalid_fields)
    answer = "Your order has been cancelled."

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[*_actions(), success],
    )

    assert result.blocked is True
    assert result.claims == (answer,)


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
        "We will reply after approval.",
    )


def test_future_condition_does_not_hide_separate_completed_claim() -> None:
    answer = "We have opened a ticket and will reply once the request has been reviewed."

    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


def test_negative_refusal_does_not_hide_separate_completed_action() -> None:
    answer = "We are unable to promise a replacement, but we have immediately escalated your case."

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


@pytest.mark.parametrize(
    "answer",
    [
        "Changing the address for ZF-20991 is not confirmed.",
        "Confirming the carrier redirect remains pending approval.",
        "Opening the warehouse ticket is still unconfirmed.",
        "Opening the warehouse ticket remains pending review.",
        "Opening the warehouse ticket is pending confirmation.",
        "Changing the address is currently pending human approval.",
    ],
)
def test_pending_action_guard_allows_action_subject_with_explicit_negative_state(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        "Changing the address is not confirmed, but we will change it tomorrow.",
        "Opening the ticket remains pending approval; we have opened the escalation.",
    ],
)
def test_explicit_negative_state_does_not_hide_later_positive_action_claim(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True


@pytest.mark.parametrize(
    "answer",
    [
        "Opening the warehouse ticket remains pending, then we will do it tomorrow.",
        "Opening the warehouse ticket remains pending and will happen tomorrow.",
        "Opening the warehouse ticket remains pending with completion tomorrow.",
        "Opening the warehouse ticket is not confirmed and we are doing so now.",
    ],
)
def test_explicit_negative_action_state_requires_a_safe_terminal_tail(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We changed the address and the ticket is not confirmed.",
        "We have changed the address and the request is not approved.",
        "We opened the escalation and the address change remains pending.",
        "The address was changed and the refund is not confirmed.",
        "Address changed and the ticket remains pending.",
        "We are changing the address and the ticket remains pending.",
    ],
)
def test_unrelated_negative_state_does_not_exempt_a_completed_action(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True


@pytest.mark.parametrize(
    "answer",
    [
        "We will provide you with updates once the investigation is underway.",
        "We are initiating a warehouse verification.",
        ("Your request for a refund will be reviewed once the warehouse verification is complete."),
        "We are escalating this immediately to our warehouse team.",
        "A human agent will follow up to confirm authorization.",
        "An agent will be in touch shortly to assist you further.",
    ],
)
def test_pending_action_repair_replaces_live_residual_claims_with_neutral_state(
    answer: str,
) -> None:
    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=_actions(),
    )

    assert repaired == PENDING_ACTION_REPAIR_NOTICE
    assert answer not in repaired
    assert (
        check_pending_action_claims(
            answer=repaired,
            runbook_actions=_actions(),
        ).blocked
        is False
    )


def test_pending_action_repair_removes_unsupported_e09_confirmation() -> None:
    safe_status = "We cannot confirm SLA compensation."
    answer = f"Executive escalation is confirmed. {safe_status}"

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=_actions(),
    )

    assert repaired == f"{safe_status}\n\n{PENDING_ACTION_REPAIR_NOTICE}"
    assert "Executive escalation is confirmed" not in repaired
    assert (
        check_pending_action_claims(
            answer=repaired,
            runbook_actions=_actions(),
        ).blocked
        is False
    )


def test_pending_action_repair_does_not_preserve_orphan_iso_time_fragments() -> None:
    answer = (
        "The P1 escalation has been opened for incident INC-204 affecting EU "
        "authentication since 2026-07-19T07:40:00Z."
    )
    actions = [
        {
            "name": "open_p1_escalation",
            "label": "Open P1 Escalation",
            "status": "pending_approval",
        }
    ]

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=actions,
    )

    assert repaired == PENDING_ACTION_REPAIR_NOTICE
    assert "40 00Z" not in repaired


def test_pending_action_repair_preserves_an_intact_iso_fact_in_its_own_unit() -> None:
    safe_fact = (
        "Incident INC-204 affects EU authentication and began at "
        "2026-07-19T07:40:00Z."
    )
    answer = f"{safe_fact} The P1 escalation has been opened."
    actions = [
        {
            "name": "open_p1_escalation",
            "label": "Open P1 Escalation",
            "status": "pending_approval",
        }
    ]

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=actions,
    )

    assert repaired == f"{safe_fact}\n\n{PENDING_ACTION_REPAIR_NOTICE}"


@pytest.mark.parametrize("separator", [": ", " — ", " – "])
def test_pending_action_repair_preserves_real_local_clause_boundaries(
    separator: str,
) -> None:
    safe_fact = "Incident INC-204 remains under investigation."
    answer = f"We opened the P1 escalation{separator}{safe_fact}"
    actions = [
        {
            "name": "open_p1_escalation",
            "label": "Open P1 Escalation",
            "status": "pending_approval",
        }
    ]

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=actions,
    )

    assert repaired == f"{safe_fact}\n\n{PENDING_ACTION_REPAIR_NOTICE}"


def test_pending_action_repair_preserves_safe_units_and_removes_only_unsafe_units() -> None:
    safe_status = "Order ZF-10482 remains in transit with an estimated delivery on the next business day."
    unsafe_action = "We are initiating a warehouse verification."
    safe_evidence_request = "Please retain the outer packaging and take clear photos."
    answer = f"{safe_status}\n\n{unsafe_action}\n\n{safe_evidence_request}"

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=_actions(),
    )

    assert repaired == (f"{safe_status}\n\n{safe_evidence_request}\n\n{PENDING_ACTION_REPAIR_NOTICE}")
    assert unsafe_action not in repaired
    assert (
        check_pending_action_claims(
            answer=repaired,
            runbook_actions=_actions(),
        ).blocked
        is False
    )


def test_pending_action_repair_removes_final_live_residuals_and_preserves_facts() -> None:
    safe_status = "Order ZF-10482 remains in transit after its latest carrier scan."
    unsafe_units = (
        "We will provide an update as soon as more information is available.",
        ("Your request has been forwarded for warehouse verification and a potential carrier redirect."),
        "We will need to investigate further.",
        ("Once reviewed, a human agent will be able to provide further updates."),
    )
    safe_review_state = "The requested warehouse action requires human review before it can be confirmed."
    answer = "\n\n".join((safe_status, *unsafe_units, safe_review_state))

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=_actions(),
    )

    assert repaired == (f"{safe_status}\n\n{safe_review_state}\n\n{PENDING_ACTION_REPAIR_NOTICE}")
    assert all(unit not in repaired for unit in unsafe_units)
    assert (
        check_pending_action_claims(
            answer=repaired,
            runbook_actions=_actions(),
        ).blocked
        is False
    )


def test_pending_action_repair_removes_conditional_contact_promise_and_preserves_facts() -> None:
    safe_facts = "The standard consultation fee is CHF 250, and the recorded due date is 25 July 2026."
    unsafe_promise = "We will be in touch once the review is complete."
    answer = f"{safe_facts}\n\n{unsafe_promise}"

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=_actions(),
    )

    assert repaired == f"{safe_facts}\n\n{PENDING_ACTION_REPAIR_NOTICE}"
    assert unsafe_promise not in repaired
    assert (
        check_pending_action_claims(
            answer=repaired,
            runbook_actions=_actions(),
        ).blocked
        is False
    )


@pytest.mark.parametrize(
    "unsafe_claim",
    [
        "We will provide the export link once it is available.",
        (
            "Once we have these confirmations, we can confirm the deletion is complete "
            "and that no retained copies exist."
        ),
    ],
)
def test_pending_action_repair_removes_artifact_or_completion_promise_and_preserves_facts(
    unsafe_claim: str,
) -> None:
    safe_fact = "The workspace identifier is WS-104."
    answer = f"{safe_fact}\n\n{unsafe_claim}"

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=_actions(),
    )

    assert repaired == f"{safe_fact}\n\n{PENDING_ACTION_REPAIR_NOTICE}"
    assert unsafe_claim not in repaired
    assert check_pending_action_claims(
        answer=repaired,
        runbook_actions=_actions(),
    ).blocked is False


def test_pending_action_repair_preserves_normal_answer_byte_for_byte() -> None:
    answer = "  The request is pending human review.\n\nWe can open the investigation after approval.  "

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=_actions(),
    )

    assert repaired == answer


def test_pending_action_repair_accepts_a_localized_safe_notice() -> None:
    notice = (
        "Jede angefragte Aktion, die eine menschliche Prüfung erfordert, ist "
        "ausstehend und weder als begonnen noch als abgeschlossen bestätigt."
    )

    repaired = repair_pending_action_claims(
        answer="Wir haben den Fall eskaliert.",
        runbook_actions=_actions(),
        repair_notice=notice,
    )

    assert repaired == notice
    assert (
        check_pending_action_claims(
            answer=repaired,
            runbook_actions=_actions(),
        ).blocked
        is False
    )


def _pending_action(*, name: str, label: str, concern_id: str) -> dict[str, object]:
    return {
        "name": name,
        "label": label,
        "status": "pending_approval",
        "concernId": concern_id,
    }


@pytest.mark.parametrize(
    "answer",
    [
        "Order B has been cancelled.",
        "Your second order has been cancelled.",
        "We have cancelled order B.",
    ],
)
def test_same_signature_pending_action_requires_exact_success_identifier(
    answer: str,
) -> None:
    success = _durable_success_action(
        name="cancel_order_a",
        label="Cancel order A",
        concern_id="concern-order-a",
        proof={"confirmationNumber": "CAN-ORDER-A"},
    )
    pending = _pending_action(
        name="cancel_order_b",
        label="Cancel order B",
        concern_id="concern-order-b",
    )

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[success, pending],
    )

    assert result.blocked is True
    assert result.claims == (answer,)


def test_same_signature_success_allows_only_its_exact_proof_identifier() -> None:
    success = _durable_success_action(
        name="cancel_order_a",
        label="Cancel order A",
        concern_id="concern-order-a",
        proof={"confirmationNumber": "CAN-ORDER-A"},
    )
    pending = _pending_action(
        name="cancel_order_b",
        label="Cancel order B",
        concern_id="concern-order-b",
    )

    proven = check_pending_action_claims(
        answer="Order CAN-ORDER-A has been cancelled.",
        runbook_actions=[success, pending],
    )
    wrong = check_pending_action_claims(
        answer="Order CAN-ORDER-B has been cancelled.",
        runbook_actions=[success, pending],
    )

    assert proven.blocked is False
    assert wrong.blocked is True


@pytest.mark.parametrize(
    "separator",
    [
        ", and ",
        " and ",
        ", however, ",
        ", yet ",
        ": ",
        " — ",
        ", while ",
    ],
)
def test_success_binding_is_local_to_its_coordinated_clause(
    separator: str,
) -> None:
    success = _durable_success_action(
        name="escalate_conflict",
        label="Escalate conflict",
        concern_id="concern-conflict",
        proof={"reference": "ESC-CONFLICT-1"},
    )
    pending = _pending_action(
        name="escalate_refund",
        label="Escalate refund",
        concern_id="concern-refund",
    )
    successful_clause = "Your conflict has been escalated"
    pending_clause = "we will escalate the refund."
    answer = f"{successful_clause}{separator}{pending_clause}"

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[success, pending],
    )
    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=[success, pending],
    )

    assert result.blocked is True
    assert result.claims == (answer,)
    assert repaired == (f"{successful_clause}.\n\n{PENDING_ACTION_REPAIR_NOTICE}")
    assert pending_clause not in repaired


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"concernId": ""},
        {"evidenceId": "tool:not-an-action"},
        {"evidenceId": "action:"},
        {"proof": {"arbitrary": "value"}},
        {"proof": {"invalid": "ABCD-1234"}},
        {"proof": {"confirmationNumber": "x"}},
        {"proof": {"status": "x" * 241}},
        {"proof": {"ok": False}},
        {"proof": {"status": "failed"}},
        {"proof": {"error": "could not cancel", "reference": "ERR-1"}},
        {"proof": {"failed": True, "id": "ERR1"}},
        {"proof": {"failure": "warehouse rejected", "confirmationNumber": "ERR-2"}},
        {"proof": {"status": "not_found"}},
        {"proof": {"status": "not found"}},
        {"proof": {"status": "missing"}},
        {"proof": {"status": "pending_approval", "reference": "REF-1"}},
        {"proof": {"status": "unconfirmed_action", "reference": "REF-1"}},
        {"proof": {"status": "not_completed_yet", "reference": "REF-1"}},
        {"proof": {"status": "blocked_by_review", "reference": "REF-1"}},
        {"proof": {"status": "failed_action", "reference": "REF-1"}},
        {"proof": {"status": "rejected_by_human", "reference": "REF-1"}},
        {"proof": {"status": "http_500_error", "reference": "REF-1"}},
        {
            "proof": {
                "status": "rejected",
                "reference": "REF-CONTRADICTED-1",
            }
        },
    ],
)
def test_success_exemption_rejects_unbound_or_arbitrary_proof(
    invalid_fields: dict[str, object],
) -> None:
    success = _durable_success_action()
    success.update(invalid_fields)
    answer = "Your order has been cancelled."

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[*_actions(), success],
    )

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "proof",
    [
        {"status": "complete", "reference": "X-123", "data": "refund failed"},
        {"payload": "rejected", "reference": "X-123"},
        {"meta": {"note": "refund failed"}, "reference": "X-123"},
        {"warnings": ["refund rejected"], "reference": "X-123"},
        {"details": ["refund rejected"], "reference": "X-123"},
        {"status": "queued", "reference": "X-123"},
        {"status": "incomplete", "reference": "X-123"},
        {"status": "not_complete", "reference": "X-123"},
        {"status": "awaiting_review", "reference": "X-123"},
        {"status": "requires_approval", "reference": "X-123"},
        {"status": "processing", "reference": "X-123"},
        {"status": "partial", "reference": "X-123"},
        {"status": "unknown", "reference": "X-123"},
        {"status": "timeout", "reference": "X-123"},
        {"status": "not_started", "reference": "X-123"},
        {"status": "no_action", "reference": "X-123"},
        {"status": "noop", "reference": "X-123"},
        {"status": 500, "reference": "X-123"},
        {"httpStatus": False, "reference": "X-123"},
        {"httpStatus": None, "reference": "X-123"},
        {"httpStatus": "Bad Gateway", "reference": "X-123"},
        {"responseCode": 500, "reference": "X-123"},
        {"http_response_code": 500, "reference": "X-123"},
        {"httpStatus": 202, "reference": "X-123"},
        {"httpStatus": 206, "reference": "X-123"},
        {"httpStatus": 207, "reference": "X-123"},
        {"status": {}, "reference": "X-123"},
        {"status": {"phase": "waiting"}, "reference": "X-123"},
        {"message": "deferred; retry later", "reference": "X-123"},
        {"message": "accepted", "reference": "X-123"},
        {"message": "enqueued", "reference": "X-123"},
        {"message": "will run later", "reference": "X-123"},
        {"message": "not yet complete", "reference": "X-123"},
        {"action": "refund"},
        {"action": "attempted", "reference": "X-123"},
        {"success": "false", "reference": "X-123"},
        {"success": 0, "reference": "X-123"},
        {"completed": "false", "reference": "X-123"},
        {"applied": "false", "reference": "X-123"},
        {"confirmed": "no", "reference": "X-123"},
    ],
)
def test_success_proof_rejects_negative_or_nonterminal_payloads(
    proof: dict[str, object],
) -> None:
    assert has_meaningful_action_success_proof(proof) is False


@pytest.mark.parametrize(
    "proof",
    [
        {"reference": "X-123"},
        {"ok": True},
        {"status": "complete"},
        {"status": "opened", "ticketReference": "T-123"},
        {"action": "cancelled", "confirmationNumber": "CAN-123"},
        {"status": "clear", "reference": "CHK-123"},
    ],
)
def test_success_proof_accepts_only_explicit_terminal_payloads(
    proof: dict[str, object],
) -> None:
    assert has_meaningful_action_success_proof(proof) is True


@pytest.mark.parametrize(
    "answer",
    [
        "We have noted your marketing opt-out.",
        "We noted the do-not-contact request.",
        "We have noted your request not to be contacted.",
        "Your marketing opt-out has been noted.",
        "The do-not-contact request has been noted.",
    ],
)
def test_pending_action_guard_blocks_noted_contact_preference_state(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "It remains unclear whether we have recorded the conflict.",
        "We cannot confirm if we have recorded the conflict.",
        "We cannot confirm if your marketing opt-out has been noted.",
        "We have not noted your marketing opt-out.",
        "No marketing opt-out has been noted.",
    ],
)
def test_pending_action_guard_allows_additional_scoped_negative_variants(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        "After approval is rescinded, we will escalate the case.",
        "If approval is unsuccessful, we will escalate the case.",
        "Once approval runs out, we will escalate the case.",
        "If review cannot be completed, we will escalate the case.",
    ],
)
def test_additional_failed_conditions_do_not_make_action_promise_safe(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We will be escalating the case.",
        "We are going to escalate the case.",
        "We definitely are escalating the case.",
        "We absolutely have escalated the case.",
        "We are definitely going to escalate the case.",
        "We promise to escalate the case.",
        "We commit to escalating the case.",
        "We understand the conflict and will be escalating it.",
        "We shall escalate the case.",
        "We understand the conflict and shall escalate it.",
        "We understand the conflict and shall be escalating it.",
    ],
)
def test_pending_action_guard_blocks_definite_future_and_commitment_grammar(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We will not be escalating the case.",
        "We are not going to escalate the case.",
        "We definitely are not escalating the case.",
        "We absolutely have not escalated the case.",
        "We do not promise to escalate the case.",
        "We cannot promise to escalate the case.",
        "We do not commit to escalating the case.",
        "Once approved, we will be escalating the case.",
        "Subject to human approval, we are going to escalate the case.",
        "Once approved, we promise to escalate the case.",
        "We shall not escalate the case.",
        "Once approved, we shall escalate the case.",
        "We understand the conflict and will not be escalating it.",
        "We understand the conflict and shall not escalate it.",
        ("We understand the conflict and will be escalating it once human review is approved."),
        ("We understand the conflict and shall escalate it once human review is approved."),
        "Wir eskalieren den Konflikt nach der Freigabe.",
        "Nous annulerons le contrat après approbation.",
    ],
)
def test_pending_action_guard_allows_negative_or_conditional_new_grammar(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    ("answer", "preserved"),
    [
        (
            "We have cancelled the order and issued the refund.",
            "We have cancelled the order.",
        ),
        (
            "We cancelled the order and issued the refund.",
            "We cancelled the order.",
        ),
        (
            "We will cancel the order and issue the refund.",
            "",
        ),
        (
            "We are going to cancel the order and issue the refund.",
            "",
        ),
        (
            "We promise to cancel the order and issue the refund.",
            "",
        ),
        (
            "We have cancelled the order, issuing the refund.",
            "We have cancelled the order.",
        ),
        (
            "We cancelled the order, then issued the refund.",
            "We cancelled the order.",
        ),
        (
            "We cancelled the order before issuing the refund.",
            "We cancelled the order.",
        ),
    ],
)
def test_successful_first_action_does_not_hide_unbacked_second_action(
    answer: str,
    preserved: str,
) -> None:
    success = _durable_success_action(
        name="cancel_order",
        label="Cancel order",
        concern_id="concern-order",
        proof={"reference": "CANCEL-ORDER-1"},
    )
    pending = _pending_action(
        name="issue_refund",
        label="Issue refund",
        concern_id="concern-refund",
    )

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[success, pending],
    )
    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=[success, pending],
    )

    assert result.blocked is True
    assert result.claims == (answer,)
    assert repaired == (f"{preserved}\n\n{PENDING_ACTION_REPAIR_NOTICE}" if preserved else PENDING_ACTION_REPAIR_NOTICE)
    assert "refund" not in repaired.lower()


@pytest.mark.parametrize(
    "answer",
    [
        "We definitely shall escalate the case.",
        "We certainly shall escalate the case.",
        "I absolutely shall cancel the order.",
        "We shall provide you with an update.",
        "We shall keep you updated.",
        "We shall be in touch.",
        "I shall provide further updates.",
    ],
)
def test_pending_action_guard_blocks_formal_shall_commitments(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We definitely shall not escalate the case.",
        "I absolutely shall not cancel the order.",
        "Once approved, we definitely shall escalate the case.",
        "We shall not provide you with an update.",
        "We shall not keep you updated.",
        "We shall not be in touch.",
    ],
)
def test_pending_action_guard_allows_negative_or_conditional_shall_grammar(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize("subject", ["booking", "reservation", "appointment", "account"])
@pytest.mark.parametrize(
    "template",
    [
        "{subject} has been cancelled.",
        "{subject} will be cancelled.",
        "{subject} is being cancelled.",
    ],
)
def test_pending_action_guard_derives_custom_runbook_subjects(
    subject: str,
    template: str,
) -> None:
    action = {
        "name": f"cancel_{subject}",
        "label": f"Cancel {subject}",
        "status": "pending_approval",
    }
    answer = template.format(subject=subject.title())

    result = check_pending_action_claims(answer=answer, runbook_actions=[action])

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Membership has been cancelled.",
        "Membership will be cancelled.",
        "Membership is being cancelled.",
        "We are rescinding the contract.",
        "We rescinded the contract.",
        "We will rescind the contract.",
        "Wir stornieren den Vertrag.",
        "Nous annulons le contrat.",
        "Cancelamos el pedido.",
        "Annulliamo l'ordine.",
        "Nous annulerons le contrat.",
        "Cancelaremos el pedido.",
        "Annulleremo il contratto.",
        "J’annule le contrat.",
        "Cancelo el pedido.",
        "Annullo il contratto.",
    ],
)
def test_pending_action_guard_blocks_lifecycle_and_localized_action_variants(
    answer: str,
) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "status",
    [
        "initiated",
        "opened",
        "submitted",
        "scheduled",
        "issued",
        "refunded",
        "active",
        "inactive",
        "clear",
        "escalated",
    ],
)
def test_success_proof_terminal_semantics_must_match_the_action(status: str) -> None:
    success = _durable_success_action(
        name="cancel_order",
        label="Cancel order",
        proof={"status": status, "reference": "WRONG-ACTION-1"},
    )
    answer = "Your order has been cancelled."

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[*_actions(), success],
    )

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Order B (reference CAN-ORDER-A) has been cancelled.",
        "Order B under confirmation CAN-ORDER-A has been cancelled.",
        "Order B has been cancelled under confirmation CAN-ORDER-A.",
        "The second order, CAN-ORDER-A, has been cancelled.",
        "The next order, CAN-ORDER-A, has been cancelled.",
    ],
)
def test_success_identifier_cannot_be_transplanted_to_another_entity(
    answer: str,
) -> None:
    success = _durable_success_action(
        name="cancel_order_a",
        label="Cancel order A",
        concern_id="concern-order-a",
        proof={"confirmationNumber": "CAN-ORDER-A"},
    )
    pending = _pending_action(
        name="cancel_order_b",
        label="Cancel order B",
        concern_id="concern-order-b",
    )

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[success, pending],
    )

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    ("name", "label", "answer"),
    [
        ("cancel_bookings", "Cancel bookings", "Booking has been cancelled."),
        ("approve_booking", "Approve booking", "Booking has been approved."),
        ("archive_account", "Archive account", "Account has been archived."),
        ("delete_profile", "Delete profile", "Profile has been deleted."),
        ("close_workspace", "Close workspace", "Workspace has been closed."),
        ("cancel_booking", "Cancel booking", "Bookings have been cancelled."),
        ("cancel_booking", "Cancel booking", "CANCELLED — booking BK-1."),
    ],
)
def test_dynamic_pending_subjects_cover_plural_nouns_and_custom_verbs(
    name: str,
    label: str,
    answer: str,
) -> None:
    action = {"name": name, "label": label, "status": "pending_approval"}

    result = check_pending_action_claims(answer=answer, runbook_actions=[action])

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Account has been disabled.",
        "We disabled the account.",
        "We will disable the account.",
        "We are disabling the account.",
        "DISABLED — account AC-1.",
    ],
)
def test_dynamic_pending_subjects_cover_arbitrary_verb_forms(answer: str) -> None:
    action = {
        "name": "disable_account",
        "label": "Disable account",
        "status": "pending_approval",
    }

    result = check_pending_action_claims(answer=answer, runbook_actions=[action])

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "> * [x] Refund issued.",
        "> - [x] Refund issued.",
        "> + [x] Refund issued.",
        "| Action | Status |\n| --- | --- |\n| Refund | issued |",
    ],
)
def test_pending_action_guard_blocks_nested_markdown_action_claims(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Je rembourserai le client.",
        "Je résilierai le contrat.",
    ],
)
def test_pending_action_guard_blocks_french_singular_future_claims(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "Cancelaremos el pedido después de la aprobación.",
        "Annulleremo l’ordine dopo l’approvazione.",
    ],
)
def test_pending_action_guard_allows_localized_approval_conditions(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize("field", ["message", "detail", "reason"])
def test_success_proof_narrative_action_must_match_the_record(field: str) -> None:
    proof = {"reference": "X-123", field: "opened"}

    assert (
        has_meaningful_action_success_proof(
            proof,
            action={"name": "cancel_order", "label": "Cancel order"},
        )
        is False
    )


@pytest.mark.parametrize(
    ("name", "label", "message"),
    [
        ("open_ticket", "Open ticket", "ticket not opened"),
        ("cancel_order", "Cancel order", "order not cancelled"),
        ("issue_refund", "Issue refund", "refund not issued"),
        ("escalate_conflict", "Escalate conflict", "could not escalate conflict"),
        ("cancel_order", "Cancel order", "unable to cancel order"),
        ("open_ticket", "Open ticket", "ticket was never opened"),
        ("open_ticket", "Open ticket", "we didn't open the ticket"),
        ("open_ticket", "Open ticket", "we don’t open the ticket"),
        ("open_ticket", "Open ticket", "we won't open the ticket"),
        ("open_ticket", "Open ticket", "we haven't opened the ticket"),
        ("open_ticket", "Open ticket", "ticket hasn't been opened"),
        ("open_ticket", "Open ticket", "no ticket was opened"),
        ("open_ticket", "Open ticket", "without opening the ticket"),
        ("cancel_order", "Cancel order", "order hasn't been cancelled"),
        ("cancel_order", "Cancel order", "order isn't being cancelled"),
        ("cancel_order", "Cancel order", "no order was cancelled"),
        ("cancel_order", "Cancel order", "without cancelling the order"),
        ("issue_refund", "Issue refund", "no refund was issued"),
        ("issue_refund", "Issue refund", "refund without being issued"),
        ("open_ticket", "Open ticket", "we didn't actually open the ticket"),
        ("open_ticket", "Open ticket", "we haven't really opened the ticket"),
        ("open_ticket", "Open ticket", "ticket hasn't actually been opened"),
        ("open_ticket", "Open ticket", "we haven't been able to open the ticket"),
        ("open_ticket", "Open ticket", "we couldn't manage to open the ticket"),
        ("open_ticket", "Open ticket", "we cannot currently open the ticket"),
        ("open_ticket", "Open ticket", "we are not presently opening the ticket"),
        ("open_ticket", "Open ticket", "no ticket has actually been opened"),
        ("open_ticket", "Open ticket", "the ticket was never actually opened"),
        ("cancel_order", "Cancel order", "we could not safely cancel the order"),
        ("cancel_order", "Cancel order", "without actually cancelling the order"),
        ("issue_refund", "Issue refund", "we haven't yet actually issued the refund"),
        ("open_ticket", "Open ticket", "Opening did not occur."),
        ("open_ticket", "Open ticket", "No one opened the ticket."),
        ("open_ticket", "Open ticket", "Nobody opened the ticket."),
        ("open_ticket", "Open ticket", "We opened no ticket."),
        ("open_ticket", "Open ticket", "The ticket remains unopened."),
        ("open_ticket", "Open ticket", "Completed without actually opening the ticket."),
        ("open_ticket", "Open ticket", "Completed without the ticket being opened."),
        ("open_ticket", "Open ticket", "We cannot confirm the ticket was opened."),
        ("open_ticket", "Open ticket", "The ticket may not have been opened."),
        ("open_ticket", "Open ticket", "After retry."),
        ("open_ticket", "Open ticket", "After a failed first attempt."),
        ("open_ticket", "Open ticket", "Ticket will open after retry."),
        ("open_ticket", "Open ticket", "Not pending; ticket will open shortly."),
        ("open_ticket", "Open ticket", "Please open the ticket."),
        ("open_ticket", "Open ticket", "We will open the ticket."),
        ("open_ticket", "Open ticket", "We are opening the ticket."),
        ("open_ticket", "Open ticket", "the ticket will be opened"),
        ("open_ticket", "Open ticket", "the ticket is going to be opened"),
        ("open_ticket", "Open ticket", "the ticket shall be opened"),
        ("open_ticket", "Open ticket", "the ticket is scheduled to be opened"),
        ("open_ticket", "Open ticket", "the ticket is about to be opened"),
        ("open_ticket", "Open ticket", "the ticket is being opened"),
        ("open_ticket", "Open ticket", "the ticket may have been opened"),
        ("open_ticket", "Open ticket", "the ticket should now be opened"),
        ("open_ticket", "Open ticket", "the ticket would be opened"),
        ("open_ticket", "Open ticket", "the ticket can be opened"),
        ("open_ticket", "Open ticket", "the ticket must be opened"),
        ("open_ticket", "Open ticket", "the ticket ought to be opened"),
        ("open_ticket", "Open ticket", "the ticket is expected to be opened"),
        ("open_ticket", "Open ticket", "the ticket is intended to be opened"),
        ("open_ticket", "Open ticket", "the ticket is planned to be opened"),
        ("open_ticket", "Open ticket", "the ticket is due to be opened"),
        ("open_ticket", "Open ticket", "the ticket is set to be opened"),
        ("open_ticket", "Open ticket", "the ticket is ready to be opened"),
        ("open_ticket", "Open ticket", "the ticket is queued to be opened"),
        ("open_ticket", "Open ticket", "the ticket needs to be opened"),
        ("open_ticket", "Open ticket", "the ticket remains to be opened"),
        ("open_ticket", "Open ticket", "the ticket has yet to be opened"),
        ("open_ticket", "Open ticket", "the ticket is awaiting being opened"),
        ("open_ticket", "Open ticket", "the ticket is in process of being opened"),
        ("open_ticket", "Open ticket", "the ticket was supposed to be opened"),
        ("issue_refund", "Issue refund", "the refund is queued to be issued"),
        ("issue_refund", "Issue refund", "the refund is expected to be issued"),
        ("cancel_order", "Cancel order", "the order will be cancelled"),
        ("issue_refund", "Issue refund", "the refund is being issued"),
        ("open_ticket", "Open ticket", "The ticket was not, in fact, opened."),
        ("open_ticket", "Open ticket", "The ticket was not\nopened."),
        ("open_ticket", "Open ticket", "The customer opened the ticket."),
        ("open_ticket", "Open ticket", "The ticket was opened by the vendor."),
        ("cancel_order", "Cancel order", "The subscription was cancelled."),
        ("open_ticket", "Open ticket", "The bank account was opened."),
        ("issue_refund", "Issue refund", "The replacement invoice was issued."),
        ("update_address", "Update address", "The contact email was updated."),
        ("close_account", "Close account", "The support ticket was closed."),
        ("cancel_order", "Cancel order", "Subscription was cancelled for order REF-1234."),
        ("open_ticket", "Open ticket", "Bank account was opened for the ticket request."),
        ("cancel_order", "Cancel order", "Subscription operation completed successfully."),
        ("open_ticket", "Open ticket", "Account operation completed successfully."),
        ("issue_refund", "Issue refund", "The refund was issued, but then revoked."),
        ("cancel_order", "Cancel order", "The order was cancelled, but then reinstated."),
        ("issue_refund", "Issue refund", "The refund was issued, then recalled."),
        ("issue_refund", "Issue refund", "The refund was issued, then cancelled."),
        ("cancel_order", "Cancel order", "The order cancellation was undone."),
        ("open_ticket", "Open ticket", "The ticket was opened, then deleted."),
        ("open_ticket", "Open ticket", "The ticket was opened, then archived."),
        ("cancel_order", "Cancel order", "The buyer cancelled the order."),
        ("open_ticket", "Open ticket", "The client's agent opened the ticket."),
        ("open_ticket", "Open ticket", "Nothing was done."),
        ("open_ticket", "Open ticket", "opened: false"),
        ("open_ticket", "Open ticket", "open_ticket=false"),
        ("open_ticket", "Open ticket", "ticket opened: 0"),
        ("cancel_order", "Cancel order", "cancelled = false"),
        ("issue_refund", "Issue refund", "refund issued: no"),
    ],
)
def test_success_proof_rejects_negated_narrative_actions(
    name: str,
    label: str,
    message: str,
) -> None:
    assert (
        has_meaningful_action_success_proof(
            {"reference": "X-123", "message": message},
            action={"name": name, "label": label},
        )
        is False
    )


@pytest.mark.parametrize(
    ("name", "label", "message"),
    [
        ("open_ticket", "Open ticket", "ticket was not only opened but assigned"),
        ("open_ticket", "Open ticket", "ticket opened successfully after retry"),
        ("issue_refund", "Issue refund", "refund issued successfully, not pending"),
        ("issue_refund", "Issue refund", "refund issued after a failed first attempt"),
        ("issue_refund", "Issue refund", "refund completed without failure"),
        ("open_ticket", "Open ticket", "No error occurred; the ticket was opened."),
        ("open_ticket", "Open ticket", "Without delay, the ticket was opened."),
        ("open_ticket", "Open ticket", "We did not only open the ticket; we assigned it."),
        ("open_ticket", "Open ticket", "We didn't just open the ticket; we assigned it."),
        (
            "open_ticket",
            "Open ticket",
            "The first attempt did not open the ticket; after retry, the ticket was opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            "we did not cancel the order, but we opened the ticket",
        ),
        (
            "open_ticket",
            "Open ticket",
            "the old ticket wasn't reopened; the new ticket was opened",
        ),
        (
            "cancel_order",
            "Cancel order",
            "we could not open a ticket, but the order was cancelled",
        ),
        (
            "issue_refund",
            "Issue refund",
            "we did not cancel the order; the refund was issued",
        ),
        ("open_ticket", "Open ticket", "Customer's ticket was opened."),
        ("issue_refund", "Issue refund", "Customer's refund was issued."),
        ("cancel_order", "Cancel order", "Customer's order was cancelled."),
        ("open_ticket", "Open ticket", "User-requested ticket was opened."),
        (
            "open_ticket",
            "Open ticket",
            "After cancelling the order the ticket was opened.",
        ),
        ("open_ticket", "Open ticket", "Operation completed after retry."),
        ("open_ticket", "Open ticket", "Operation completed after a failed first attempt."),
        ("open_ticket", "Open ticket", "Operation completed without failure."),
        ("open_ticket", "Open ticket", "Complete and not pending."),
    ],
)
def test_success_proof_accepts_nonnegative_narrative_qualifiers(
    name: str,
    label: str,
    message: str,
) -> None:
    assert (
        has_meaningful_action_success_proof(
            {"reference": "X-123", "message": message},
            action={"name": name, "label": label},
        )
        is True
    )


@pytest.mark.parametrize(
    ("name", "label", "proof"),
    [
        ("open_ticket", "Open ticket", {"reference": "X-123", "opened": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "didOpenTicket": False}),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "ok": True, "opened": False},
        ),
        ("cancel_order", "Cancel order", {"reference": "X-123", "cancelled": False}),
        ("issue_refund", "Issue refund", {"reference": "X-123", "refundIssued": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "opened": "N"}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "opened": "not_opened"}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "opened": None}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "opened": 0.0}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "notOpened": True}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "openingAttempted": True}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "willOpen": True}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "openResult": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "open": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "ticketOpen": False}),
        ("cancel_order", "Cancel order", {"reference": "X-123", "ticketOpenSuccess": True}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "notOpened": None}),
        ("issue_refund", "Issue refund", {"reference": "X-123", "refundRevoked": True}),
        ("issue_refund", "Issue refund", {"reference": "X-123", "refundReversed": True}),
        ("cancel_order", "Cancel order", {"reference": "X-123", "orderReinstated": True}),
        ("cancel_order", "Cancel order", {"reference": "X-123", "subscriptionCancelled": True}),
        ("cancel_order", "Cancel order", {"reference": "X-123", "ticketOpened": True}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "accountOpened": True}),
        ("issue_refund", "Issue refund", {"reference": "X-123", "invoiceIssued": True}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "isSuccess": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "succeeded": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "operationSucceeded": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "isOk": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "wasSuccessful": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "actionSucceeded": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "done": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "complete": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "resolved": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "verified": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "didSucceed": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "successFlag": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "okFlag": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "response.done": False}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "response.status": 500}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "responseStatusCode": 500}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "resultCode": 500}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "response.code": 500}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "http.code": 500}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "response": {"code": 500}}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "status": 202}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "state": 202}),
        ("open_ticket", "Open ticket", {"reference": "X-123", "action": 202}),
    ],
)
def test_success_proof_rejects_action_specific_false_fields(
    name: str,
    label: str,
    proof: dict[str, object],
) -> None:
    assert has_meaningful_action_success_proof(proof, action={"name": name, "label": label}) is False


def test_rescinded_is_a_valid_terminal_cancellation_status() -> None:
    assert (
        has_meaningful_action_success_proof(
            {"reference": "X-123", "status": "rescinded"},
            action={"name": "cancel_contract", "label": "Cancel contract"},
        )
        is True
    )


@pytest.mark.parametrize(
    ("label", "message"),
    [
        ("Cancel first order", "The second order was cancelled."),
        ("Cancel order A", "Order B was cancelled."),
        ("Cancel order 1001", "Order 1002 was cancelled."),
    ],
)
def test_success_proof_rejects_wrong_entity_qualifier(
    label: str,
    message: str,
) -> None:
    assert (
        has_meaningful_action_success_proof(
            {"reference": "X-123", "message": message},
            action={"name": label.lower().replace(" ", "_"), "label": label},
        )
        is False
    )


@pytest.mark.parametrize(
    "proof",
    [
        {"reference": "X-123", "status": "complete", "message": ["ticket was not opened"]},
        {"reference": "X-123", "status": "complete", "result": ["failed"]},
        {"reference": "X-123", "status": "complete", "result": ["ticket not opened"]},
        {"reference": "X-123", "status": "complete", "details": {"note": "ticket not opened"}},
        {"reference": "X-123", "status": "complete", "warnings": ["ticket not opened"]},
        {"reference": "X-123", "message": '{"opened": false}'},
        {"reference": "X-123", "message": '{"opened": null}'},
        {"reference": "X-123", "didNotOpenTicket": True},
        {"reference": "X-123", "result": {"value": False}},
        {"reference": "X-123", "status": "complete", "result": [0]},
        {"reference": "X-123", "status": "complete", "result": [500]},
        {"reference": "X-123", "status": "complete", "result": [None]},
        {"reference": "X-123", "status": "complete", "result": [True]},
        {"reference": "X-123", "status": "complete", "result": ["false"]},
        {"reference": "X-123", "status": "complete", "result": []},
        {"reference": "X-123", "status": "complete", "result": {}},
        {"reference": "X-123", "status": "complete", "result": {"value": 500}},
    ],
)
def test_success_proof_rejects_nested_or_serialized_negative_state(
    proof: dict[str, object],
) -> None:
    assert (
        has_meaningful_action_success_proof(
            proof,
            action={"name": "open_ticket", "label": "Open ticket"},
        )
        is False
    )


@pytest.mark.parametrize(
    "field",
    ["error", "warning", "retryRequired", "cached", "dryRun"],
)
def test_success_proof_allows_benign_false_metadata(field: str) -> None:
    proof = {"reference": "X-123", "opened": True, field: False}

    assert (
        has_meaningful_action_success_proof(
            proof,
            action={"name": "open_ticket", "label": "Open ticket"},
        )
        is True
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"note": "no error"},
        {"note": "not pending"},
        {"note": "after retry"},
        {"note": "without failure"},
        {"url": "https://example.test/tickets/open"},
        {"confirmation.code": "CAN-123"},
        {"error": "none"},
        {"error": {"present": False}},
        {"result": {"count": 0, "status": "opened"}},
    ],
)
def test_success_proof_allows_neutral_metadata_with_terminal_state(
    metadata: dict[str, object],
) -> None:
    proof = {"reference": "X-123", "status": "opened", **metadata}

    assert (
        has_meaningful_action_success_proof(
            proof,
            action={"name": "open_ticket", "label": "Open ticket"},
        )
        is True
    )


@pytest.mark.parametrize(
    ("name", "label", "message", "expected_action", "answer"),
    [
        (
            "open_ticket",
            "Open ticket",
            "we didn't open the ticket",
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "cancel_order",
            "Cancel order",
            "no order was cancelled",
            "Cancel the order.",
            "Order X-123 has been cancelled.",
        ),
        (
            "issue_refund",
            "Issue refund",
            "refund without being issued",
            "Issue the refund.",
            "Refund X-123 has been issued.",
        ),
    ],
)
def test_negated_narrative_cannot_become_durable_action_success(
    name: str,
    label: str,
    message: str,
    expected_action: str,
    answer: str,
) -> None:
    action = _durable_success_action(
        name=name,
        label=label,
        proof={"reference": "X-123", "message": message},
    )

    assert (
        has_durable_action_success(
            runbook_actions=[action],
            expected_action_text=expected_action,
        )
        is False
    )
    assert (
        has_success_backed_action_claim(
            answer=answer,
            runbook_actions=[action],
            expected_action_text=expected_action,
        )
        is False
    )


@pytest.mark.parametrize(
    ("name", "label", "proof_status"),
    [
        ("cancel_order", "Cancel order", "terminated"),
        ("issue_refund", "Issue refund", "refunded"),
    ],
)
def test_success_proof_accepts_action_synonyms(
    name: str,
    label: str,
    proof_status: str,
) -> None:
    assert (
        has_meaningful_action_success_proof(
            {"status": proof_status, "reference": "X-123"},
            action={"name": name, "label": label},
        )
        is True
    )


def test_multiple_successes_support_one_truthful_bundled_claim() -> None:
    conflict = _durable_success_action(
        name="escalate_conflict",
        label="Escalate conflict",
        concern_id="concern-conflict",
        proof={"reference": "proof-conf"},
    )
    deadline = _durable_success_action(
        name="escalate_deadline",
        label="Escalate deadline",
        concern_id="concern-deadline",
        proof={"reference": "proof-dead"},
    )
    pending = _pending_action(
        name="issue_refund",
        label="Issue refund",
        concern_id="concern-refund",
    )
    answer = "Conflict proof-conf and deadline proof-dead have been escalated."

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[conflict, deadline, pending],
    )

    assert result.blocked is False
    assert result.claims == ()


def test_first_order_wording_matches_proven_order_a() -> None:
    success = _durable_success_action(
        name="cancel_order_a",
        label="Cancel order A",
        concern_id="concern-order-a",
        proof={"confirmationNumber": "CAN-ORDER-A"},
    )
    pending = _pending_action(
        name="cancel_order_b",
        label="Cancel order B",
        concern_id="concern-order-b",
    )
    answer = "The first order, CAN-ORDER-A, has been cancelled."

    result = check_pending_action_claims(
        answer=answer,
        runbook_actions=[success, pending],
    )

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    ("name", "label", "proof", "expected_action", "answer"),
    [
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result": {"response": False}},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {
                "reference": "X-123",
                "status": "opened",
                "result": {"payload": {"description": "false"}},
            },
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result": {"code": 500}},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result": {"exitCode": 1}},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result.code": 500},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "dryRun": True},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "simulated": True},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "wouldOpenTicket": True},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "rolledBack": True},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result": {"returnCode": 1}},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {
                "reference": "X-123",
                "status": "opened",
                "result": {"execution": {"exitStatus": 1}},
            },
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result": {"simulationMode": True}},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result": {"previewOnly": True}},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "cancel_first_order",
            "Cancel first order",
            {"reference": "X-123", "secondOrderCancelled": True},
            "Cancel the first order.",
            "The first order X-123 has been cancelled.",
        ),
        (
            "cancel_first_order",
            "Cancel first order",
            {"reference": "X-123", "second_order_cancelled": True},
            "Cancel the first order.",
            "The first order X-123 has been cancelled.",
        ),
        (
            "cancel_first_order",
            "Cancel first order",
            {"reference": "X-123", "cancelledSecondOrder": True},
            "Cancel the first order.",
            "The first order X-123 has been cancelled.",
        ),
        (
            "cancel_order_a",
            "Cancel order A",
            {"reference": "X-123", "orderBCancelled": True},
            "Cancel order A.",
            "Order A X-123 has been cancelled.",
        ),
        (
            "cancel_order_a",
            "Cancel order A",
            {"reference": "X-123", "result": {"orderBCancelled": True}},
            "Cancel order A.",
            "Order A X-123 has been cancelled.",
        ),
        *[
            (
                "cancel_order_a",
                "Cancel order A",
                {"reference": "X-123", "status": "cancelled", **qualifier_proof},
                "Cancel order A.",
                "Order A X-123 has been cancelled.",
            )
            for qualifier_proof in (
                {"orderId": "B"},
                {"order": "B"},
                {"target": {"orderId": "B"}},
                {"entity": "order B"},
                {"target": "order B"},
            )
        ],
        (
            "cancel_order_1001",
            "Cancel order 1001",
            {"reference": "X-123", "order1002Cancelled": True},
            "Cancel order 1001.",
            "Order 1001 X-123 has been cancelled.",
        ),
        (
            "cancel_order_1001",
            "Cancel order 1001",
            {"reference": "X-123", "message": "Order number 1002 was cancelled."},
            "Cancel order 1001.",
            "Order 1001 X-123 has been cancelled.",
        ),
        (
            "cancel_first_order",
            "Cancel first order",
            {"reference": "X-123", "message": "Order number 2 was cancelled."},
            "Cancel the first order.",
            "The first order X-123 has been cancelled.",
        ),
        (
            "cancel_order_1001",
            "Cancel order 1001",
            {"reference": "X-123", "data": {"order1002Cancelled": True}},
            "Cancel order 1001.",
            "Order 1001 X-123 has been cancelled.",
        ),
        *[
            (
                "open_ticket",
                "Open ticket",
                {"reference": "X-123", "message": message},
                "Open the ticket.",
                "Ticket X-123 has been opened.",
            )
            for message in (
                "Ticket to be opened.",
                "Please have the ticket opened.",
                "The ticket is currently getting opened.",
                "The ticket appears opened.",
                "The ticket seems opened.",
                "The ticket is believed to be opened.",
                "Perhaps the ticket was opened.",
                "The ticket was allegedly opened.",
                "The ticket was almost opened.",
                "The ticket was nearly opened.",
                "The ticket was prevented from being opened.",
                "Le ticket sera ouvert.",
                "Le ticket devrait être ouvert.",
                "Le ticket va être ouvert.",
                "El ticket será abierto.",
                "El ticket podría ser abierto.",
                "El ticket va a ser abierto.",
                "Il ticket sarà aperto.",
                "Il ticket dovrebbe essere aperto.",
                "Il ticket verrà aperto.",
                "Le ticket doit être ouvert.",
                "Le ticket est en train d’être ouvert.",
                "El ticket debe ser abierto.",
                "El ticket está siendo abierto.",
                "Il ticket deve essere aperto.",
                "Il ticket sta per essere aperto.",
                "Das Ticket wird eröffnet.",
                "Das Ticket wird morgen eröffnet.",
                "Das Ticket wird gerade eröffnet.",
                "Das Ticket soll eröffnet werden.",
                "Das Ticket soll morgen eröffnet werden.",
                "Das Ticket könnte eröffnet werden.",
                "Das Ticket muss eröffnet werden.",
                "Ticket opened? No.",
                "The ticket was opened, or maybe not.",
                "The ticket was opened — not really.",
                "The ticket appears to have been opened.",
                "The ticket was opened, but I cannot confirm that.",
                "The ticket was opened in dry-run mode only.",
                "The ticket was opened, but the transaction was rolled back.",
                "If the webhook succeeded, the ticket was opened.",
                "When the webhook succeeds, the ticket is opened.",
                "The ticket was purportedly opened.",
                "The ticket was presumably opened.",
                "The logs suggest the ticket was opened.",
                "The ticket was opened in preview mode only.",
                "The ticket was opened in the sandbox only.",
                "The ticket was opened locally but was not persisted.",
                "A customer opened the ticket.",
                "The ticket was opened by a customer.",
                "A third party opened the ticket.",
                "The end user opened the ticket.",
                "The warehouse opened the ticket.",
                "The recipient opened the ticket.",
                "The supplier opened the ticket.",
                "Our supplier opened the ticket.",
                "Opposing counsel opened the ticket.",
                "External counsel opened the ticket.",
                "The vendor's bot opened the ticket.",
                "The ticket was opened by Zendesk.",
                "The door was opened.",
                "The browser window was opened.",
                "The bank account linked to ticket X was opened.",
            )
        ],
        (
            "cancel_order",
            "Cancel order",
            {"reference": "X-123", "message": "The order was cancelled, then the cancellation was reversed."},
            "Cancel the order.",
            "Order X-123 has been cancelled.",
        ),
        (
            "cancel_order",
            "Cancel order",
            {"reference": "X-123", "message": "The warehouse cancelled the order."},
            "Cancel the order.",
            "Order X-123 has been cancelled.",
        ),
        *[
            (
                "cancel_order",
                "Cancel order",
                {"reference": "X-123", "message": f"The {actor} cancelled the order."},
                "Cancel the order.",
                "Order X-123 has been cancelled.",
            )
            for actor in ("consumer", "purchaser", "recipient")
        ],
        (
            "cancel_order",
            "Cancel order",
            {"reference": "X-123", "message": "The courier cancelled the order."},
            "Cancel the order.",
            "Order X-123 has been cancelled.",
        ),
        (
            "cancel_contract",
            "Cancel contract",
            {"reference": "X-123", "message": "Outside counsel cancelled the contract."},
            "Cancel the contract.",
            "Contract X-123 has been cancelled.",
        ),
        (
            "cancel_order",
            "Cancel order",
            {"reference": "X-123", "message": "The meeting was cancelled."},
            "Cancel the order.",
            "Order X-123 has been cancelled.",
        ),
        (
            "cancel_contract",
            "Cancel contract",
            {"reference": "X-123", "message": "The court hearing was cancelled."},
            "Cancel the contract.",
            "Contract X-123 has been cancelled.",
        ),
        (
            "cancel_order",
            "Cancel order",
            {"reference": "X-123", "message": "The subscription for order X was cancelled."},
            "Cancel the order.",
            "Order X-123 has been cancelled.",
        ),
        (
            "issue_refund",
            "Issue refund",
            {"reference": "X-123", "message": "The coupon was issued."},
            "Issue the refund.",
            "Refund X-123 has been issued.",
        ),
        (
            "issue_refund",
            "Issue refund",
            {"reference": "X-123", "message": "A voucher was issued."},
            "Issue the refund.",
            "Refund X-123 has been issued.",
        ),
        (
            "issue_refund",
            "Issue refund",
            {"reference": "X-123", "message": "The bank issued the refund."},
            "Issue the refund.",
            "Refund X-123 has been issued.",
        ),
        (
            "issue_refund",
            "Issue refund",
            {"reference": "X-123", "message": "The replacement invoice for refund X was issued."},
            "Issue the refund.",
            "Refund X-123 has been issued.",
        ),
        (
            "close_account",
            "Close account",
            {"reference": "X-123", "message": "The support ticket for account X was closed."},
            "Close the account.",
            "Account X-123 has been closed.",
        ),
        (
            "activate_account",
            "Activate account",
            {"reference": "X-123", "message": "The account was activated, then deactivated."},
            "Activate the account.",
            "Account X-123 has been activated.",
        ),
        (
            "delete_profile",
            "Delete profile",
            {"reference": "X-123", "message": "The profile was deleted, then restored."},
            "Delete the profile.",
            "Profile X-123 has been deleted.",
        ),
        *[
            (
                "issue_refund",
                "Issue refund",
                {"reference": "X-123", "message": f"The refund was issued, then {reversal}."},
                "Issue the refund.",
                "Refund X-123 has been issued.",
            )
            for reversal in ("a chargeback followed", "clawed back", "rolled back", "taken back")
        ],
        *[
            (
                "open_ticket",
                "Open ticket",
                {"reference": "X-123", "message": f"The ticket was opened, then {reversal}."},
                "Open the ticket.",
                "Ticket X-123 has been opened.",
            )
            for reversal in ("purged", "removed")
        ],
        (
            "update_address",
            "Update address",
            {"reference": "X-123", "message": "The address was updated, then reset."},
            "Update the address.",
            "Address X-123 has been updated.",
        ),
        *[
            (
                "activate_account",
                "Activate account",
                {"reference": "X-123", "message": f"The account was activated, then {reversal}."},
                "Activate the account.",
                "Account X-123 has been activated.",
            )
            for reversal in ("frozen", "suspended")
        ],
        (
            "cancel_order",
            "Cancel order",
            {"reference": "X-123", "message": "The order was cancelled; later the cancellation was rolled back."},
            "Cancel the order.",
            "Order X-123 has been cancelled.",
        ),
        (
            "update_address",
            "Update address",
            {"reference": "X-123", "message": "The address was updated and then changed back."},
            "Update the address.",
            "Address X-123 has been updated.",
        ),
        (
            "update_address",
            "Update address",
            {"reference": "X-123", "message": "The software package was updated."},
            "Update the address.",
            "Address X-123 has been updated.",
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "message": "The ticket was opened and its creation was reverted."},
            "Open the ticket.",
            "Ticket X-123 has been opened.",
        ),
        (
            "close_account",
            "Close account",
            {"reference": "X-123", "message": "The account was closed; later the closure was undone."},
            "Close the account.",
            "Account X-123 has been closed.",
        ),
        (
            "delete_ticket",
            "Delete ticket",
            {"reference": "X-123", "message": "The ticket was deleted and then undeleted."},
            "Delete the ticket.",
            "Ticket X-123 has been deleted.",
        ),
        (
            "schedule_meeting",
            "Schedule meeting",
            {"reference": "X-123", "message": "The meeting was scheduled and then cancelled."},
            "Schedule the meeting.",
            "Meeting X-123 has been scheduled.",
        ),
        (
            "create_account",
            "Create account",
            {"reference": "X-123", "message": "The account was created and then deleted."},
            "Create the account.",
            "Account X-123 has been created.",
        ),
    ],
)
def test_adversarial_action_proof_is_rejected_at_every_acceptance_layer(
    name: str,
    label: str,
    proof: dict[str, object],
    expected_action: str,
    answer: str,
) -> None:
    action = _durable_success_action(name=name, label=label, proof=proof)

    assert has_meaningful_action_success_proof(proof, action=action) is False
    assert (
        has_durable_action_success(
            runbook_actions=[action],
            expected_action_text=expected_action,
        )
        is False
    )
    assert (
        has_success_backed_action_claim(
            answer=answer,
            runbook_actions=[action],
            expected_action_text=expected_action,
        )
        is False
    )


@pytest.mark.parametrize(
    ("name", "label", "proof"),
    [
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result": {"response": True}},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result": {"code": 200}},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result": {"exitCode": 0}},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result": {"returnCode": 0}},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "result": {"execution": {"exitStatus": 0}}},
        ),
        (
            "open_ticket",
            "Open ticket",
            {
                "reference": "X-123",
                "status": "opened",
                "result": {"simulationMode": False, "previewOnly": False},
            },
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "FAIL-1234", "status": "opened"},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "PENDING-1234", "status": "opened"},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "HTTP-500-REF", "status": "opened"},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "error": "no error"},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "error": "No error occurred"},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "error": "No failures detected"},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "failureReason": "not applicable"},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "note": "The operation is not pending anymore."},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "note": "Retry count: 1."},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "note": "Retry attempts: 1."},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "trackingCode": "CANCEL-123"},
        ),
        (
            "cancel_order",
            "Cancel order",
            {"reference": "X-123", "status": "cancelled", "contactEmail": "opened@example.test"},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "contact": "cancelled@example.test"},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "receiptFile": "refund-issued.pdf"},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "status": "opened", "featureFlag": False, "debugFlag": False},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "message": "Customer support opened the ticket."},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "message": "Das Ticket wurde eröffnet."},
        ),
        (
            "open_ticket",
            "Open ticket",
            {"reference": "X-123", "message": "Das Ticket ist eröffnet worden."},
        ),
        (
            "cancel_order",
            "Cancel order",
            {"reference": "X-123", "message": "The order was cancelled by our automation."},
        ),
        *[
            (
                "cancel_order_a",
                "Cancel order A",
                {"reference": "X-123", "status": "cancelled", **qualifier_proof},
            )
            for qualifier_proof in (
                {"orderId": "A"},
                {"order": "A"},
                {"target": {"orderId": "A"}},
                {"entity": "order A"},
                {"target": "order A"},
            )
        ],
        (
            "issue_refund",
            "Issue refund",
            {"reference": "X-123", "message": "The refund was issued and not revoked or reversed."},
        ),
        (
            "cancel_order",
            "Cancel order",
            {"reference": "X-123", "message": "The order was cancelled and not reinstated."},
        ),
        (
            "update_address",
            "Update address",
            {"reference": "X-123", "message": "The address was updated and not reverted."},
        ),
    ],
)
def test_terminal_action_proof_allows_safe_controls_and_neutral_metadata(
    name: str,
    label: str,
    proof: dict[str, object],
) -> None:
    assert has_meaningful_action_success_proof(proof, action={"name": name, "label": label}) is True


def test_action_proof_rejects_oversized_narrative_before_regex_validation() -> None:
    proof = {"reference": "X-123", "status": "opened", "note": "x" * 8_193}

    assert (
        has_meaningful_action_success_proof(
            proof,
            action={"name": "open_ticket", "label": "Open ticket"},
        )
        is False
    )
