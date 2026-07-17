"""Focused tests for deterministic generated-reply sign-off cleanup."""

from automail.support.issue_agent import _clean_answer


def _customer_message(signature: str = "Returns Team") -> list[dict[str, str]]:
    return [{
        "direction": "customer",
        "body": f"Please confirm the return instructions.\n\n{signature}",
    }]


def test_copied_customer_team_signature_is_replaced_by_configured_signer() -> None:
    answer = "We can review the return after receiving the photos.\n\nBest regards,\nReturns Team"

    assert _clean_answer(
        answer,
        messages=_customer_message(),
        signer_name="Mantly Support Team",
    ) == (
        "We can review the return after receiving the photos.\n\n"
        "Best regards,\nMantly Support Team"
    )


def test_agent_name_placeholder_is_replaced_by_configured_signer() -> None:
    answer = "We need the parcel photos before review.\n\nKind regards,\n[Agent Name]"

    assert _clean_answer(
        answer,
        messages=_customer_message(),
        signer_name="Mantly Support Team",
    ).endswith("Kind regards,\nMantly Support Team")


def test_agent_name_placeholder_and_closing_are_removed_without_project_signer() -> None:
    answer = "We need the parcel photos before review.\n\nKind regards,\n[Agent Name]"

    assert _clean_answer(answer, messages=_customer_message()) == (
        "We need the parcel photos before review."
    )


def test_dangling_closing_is_completed_or_removed() -> None:
    answer = "Please keep the damaged parcel isolated.\n\nBest regards,"

    assert _clean_answer(answer, signer_name="Mantly Support Team").endswith(
        "Best regards,\nMantly Support Team"
    )
    assert _clean_answer(answer) == "Please keep the damaged parcel isolated."


def test_unconfigured_generated_support_signature_is_removed_before_grounding() -> None:
    answer = (
        "Shipment UPS1Z999AA10123456784 is in transit.\n\n"
        "Best regards,\nZenFulfillment Support"
    )

    assert _clean_answer(answer) == (
        "Shipment UPS1Z999AA10123456784 is in transit."
    )


def test_substantive_final_line_and_legitimate_support_signature_are_preserved() -> None:
    substantive = "Please keep the parcel isolated until the safety review is complete."
    signed = f"{substantive}\n\nBest regards,\nMantly Support Team"

    assert _clean_answer(substantive, messages=_customer_message()) == substantive
    assert _clean_answer(
        signed,
        messages=_customer_message(),
        signer_name="Mantly",
    ) == signed


def test_detached_substantive_customer_paragraph_is_not_treated_as_signature() -> None:
    final_line = "Please keep the parcel isolated until the safety review is complete."
    messages = [{
        "direction": "customer",
        "body": f"The battery pack is leaking.\n\n{final_line}",
    }]

    assert _clean_answer(final_line, messages=messages) == final_line
