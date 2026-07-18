import pytest

from automail.support.pending_action_claims import (
    PENDING_ACTION_CLAIM_REASON_CODE,
    PENDING_ACTION_REPAIR_NOTICE,
    check_pending_action_claims,
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


def test_pending_action_guard_blocks_exact_live_b2b_escalation_claim() -> None:
    answer = (
        "This urgent B2B SLA incident has been escalated for human operations review."
    )
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
    actions = [
        {"name": "agent_triage", "label": "Agent triage", "status": "pending_approval"}
    ]

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
            (
                "I've checked tracking for UPS1Z999AA10123456784, and I've "
                "opened a ticket."
            ),
            _tracking_evidence(),
            _actions(),
        ),
        (
            (
                "I've checked tracking for UPS1Z999AA10123456784 and escalated "
                "your case."
            ),
            _tracking_evidence(),
            _actions(),
        ),
        (
            (
                "I've checked tracking for UPS1Z999AA10123456784 and opened "
                "a ticket."
            ),
            _tracking_evidence(),
            _actions(),
        ),
        (
            (
                "I've checked tracking for UPS1Z999AA10123456784, then escalated "
                "your case."
            ),
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
    ],
)
def test_pending_action_guard_allows_safe_b2b_nearby_language(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is False
    assert result.claims == ()


@pytest.mark.parametrize(
    "answer",
    [
        (
            "A specialist will review your request and follow up with you "
            "regarding the next steps for this."
        ),
        "A human agent will follow up with you shortly to assist further with this case.",
        "Our team will contact you with an update.",
        "Operations will investigate the delivery exception.",
        "The operations team will open a warehouse ticket.",
        "A support representative will arrange the replacement.",
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
        (
            "Your request has been forwarded for warehouse verification and a "
            "potential carrier redirect."
        ),
        "We will need to investigate further.",
        (
            "Once reviewed, a human agent will be able to provide further "
            "updates."
        ),
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


@pytest.mark.parametrize(
    "answer",
    [
        "A specialist will follow up once the action is approved.",
        "A human agent will contact you if available.",
        "A specialist is expected to follow up after review.",
        "The carrier will update tracking tomorrow.",
        "The customer will contact support after review.",
        "A carrier representative will follow up tomorrow.",
        "Carrier operations will update the tracking scan tomorrow.",
    ],
)
def test_pending_action_guard_allows_contingent_or_external_actor_future_facts(
    answer: str,
) -> None:
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


@pytest.mark.parametrize(
    "answer",
    [
        "We will provide you with updates once the investigation is underway.",
        "We are initiating a warehouse verification.",
        (
            "Your request for a refund will be reviewed once the warehouse "
            "verification is complete."
        ),
        "We are escalating this immediately to our warehouse team.",
        "A human agent will follow up to confirm authorization.",
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
    assert check_pending_action_claims(
        answer=repaired,
        runbook_actions=_actions(),
    ).blocked is False


def test_pending_action_repair_preserves_safe_units_and_removes_only_unsafe_units() -> None:
    safe_status = (
        "Order ZF-10482 remains in transit with an estimated delivery on the next "
        "business day."
    )
    unsafe_action = "We are initiating a warehouse verification."
    safe_evidence_request = "Please retain the outer packaging and take clear photos."
    answer = (
        f"{safe_status}\n\n"
        f"{unsafe_action}\n\n"
        f"{safe_evidence_request}"
    )

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=_actions(),
    )

    assert repaired == (
        f"{safe_status}\n\n"
        f"{safe_evidence_request}\n\n"
        f"{PENDING_ACTION_REPAIR_NOTICE}"
    )
    assert unsafe_action not in repaired
    assert check_pending_action_claims(
        answer=repaired,
        runbook_actions=_actions(),
    ).blocked is False


def test_pending_action_repair_removes_final_live_residuals_and_preserves_facts() -> None:
    safe_status = (
        "Order ZF-10482 remains in transit after its latest carrier scan."
    )
    unsafe_units = (
        "We will provide an update as soon as more information is available.",
        (
            "Your request has been forwarded for warehouse verification and a "
            "potential carrier redirect."
        ),
        "We will need to investigate further.",
        (
            "Once reviewed, a human agent will be able to provide further "
            "updates."
        ),
    )
    safe_review_state = (
        "The requested warehouse action requires human review before it can be "
        "confirmed."
    )
    answer = "\n\n".join((safe_status, *unsafe_units, safe_review_state))

    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=_actions(),
    )

    assert repaired == (
        f"{safe_status}\n\n"
        f"{safe_review_state}\n\n"
        f"{PENDING_ACTION_REPAIR_NOTICE}"
    )
    assert all(unit not in repaired for unit in unsafe_units)
    assert check_pending_action_claims(
        answer=repaired,
        runbook_actions=_actions(),
    ).blocked is False


def test_pending_action_repair_preserves_normal_answer_byte_for_byte() -> None:
    answer = (
        "  The request is pending human review.\n\n"
        "We can open the investigation after approval.  "
    )

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
    assert check_pending_action_claims(
        answer=repaired,
        runbook_actions=_actions(),
    ).blocked is False
