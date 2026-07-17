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
        "We escalated the safety incident.",
        "Your refund has been issued.",
        "The investigation is now in progress.",
        "The incident has been flagged for urgent human operations review.",
        "This request has been marked for escalation.",
    ],
)
def test_pending_action_guard_blocks_completed_or_active_state_claims(answer: str) -> None:
    result = check_pending_action_claims(answer=answer, runbook_actions=_actions())

    assert result.blocked is True
    assert result.claims == (answer,)


@pytest.mark.parametrize(
    "answer",
    [
        "We can initiate the investigation after review.",
        "We will check for separate parcels once the action is approved.",
        "We could escalate this after approval.",
        "The escalation is pending approval.",
        "We have not escalated this incident.",
        "We are waiting for approval before escalating.",
        "We are ready to check this after approval.",
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
