from automail.models import (
    AnswerObligation,
    Email,
    IntentResult,
    ResponseDraft,
    RunbookActionOutcome,
    RunbookOutcome,
    RunbookToolEvidence,
    VerifiedFact,
)
from automail.pipeline.response.composer import (
    _draft_review_requirements,
    _pending_action_claim_check,
    _reply_requires_human,
)
from automail.pipeline.response.prompt_factory import create_response_user_prompt


def _email() -> Email:
    return Email(
        id="message-1",
        subject="Cancel and buy",
        from_address="customer@example.test",
        body="Cancel C-184 and quote three XYZ Pro units.",
        attachments=[],
    )


def _result() -> IntentResult:
    return IntentResult(
        matched=True,
        intent_name="contract-cancellation",
        concerns=[
            RunbookOutcome(
                concern_id="cancel-contract",
                concern_summary="Cancel contract C-184",
                source_text="Cancel C-184",
                confidence=0.99,
                matched=True,
                intent_name="contract-cancellation",
                status="requires_human",
                answer_obligations=[
                    AnswerObligation(
                        obligation_id="cancel-contract:obligation-1",
                        question="Can contract C-184 be cancelled?",
                    )
                ],
                reply_requirements=["Never claim cancellation completed before approval."],
                requires_human=True,
                requires_human_reason="Cancellation requires approval.",
            ),
            RunbookOutcome(
                concern_id="buy-product",
                concern_summary="Buy three XYZ Pro units",
                source_text="quote three XYZ Pro units",
                confidence=0.98,
                matched=True,
                intent_name="product-purchase",
                status="ready",
                answer_obligations=[
                    AnswerObligation(
                        obligation_id="buy-product:obligation-1",
                        question="What is the price for three XYZ Pro units?",
                    ),
                    AnswerObligation(
                        obligation_id="buy-product:obligation-2",
                        question="What delivery information is required?",
                    ),
                ],
                tool_evidence=[
                    RunbookToolEvidence(
                        tool_name="product_lookup",
                        status="success",
                        facts=[
                            VerifiedFact(
                                path="product",
                                value="XYZ Pro",
                                source="tool:product_lookup",
                            ),
                            VerifiedFact(
                                path="price",
                                value=500,
                                source="tool:product_lookup",
                            ),
                        ],
                    )
                ],
                missing_information=["Delivery address"],
            ),
        ],
    )


def test_multi_concern_prompt_contains_every_outcome_and_evidence():
    prompt = create_response_user_prompt(_email(), intent_result=_result())

    assert '<intent_context status="multi" concern_count="2">' in prompt
    assert '<concern id="cancel-contract" matched="True"' in prompt
    assert "contract-cancellation" in prompt
    assert "product-purchase" in prompt
    assert '<tool_result name="product_lookup" status="success">' in prompt
    assert '<fact path="price">500</fact>' in prompt
    assert "Delivery address" in prompt
    assert "Never claim cancellation completed before approval." in prompt
    assert '<answer_obligation id="cancel-contract:obligation-1">' in prompt
    assert "What is the price for three XYZ Pro units?" in prompt


def test_most_restrictive_concern_keeps_combined_reply_in_review():
    requires_human, reason = _reply_requires_human(_result())

    assert requires_human is True
    assert reason == "Cancellation requires approval."


def test_unmatched_secondary_concern_does_not_erase_matched_primary():
    result = _result()
    result.concerns[1] = RunbookOutcome(
        concern_id="sponsorship",
        concern_summary="Sponsor a football team",
        source_text="Will you sponsor our football team?",
        confidence=0.75,
        matched=False,
        status="unmatched",
        requires_human=True,
        requires_human_reason="No sponsorship runbook exists.",
    )

    prompt = create_response_user_prompt(_email(), intent_result=result)
    requires_human, reason = _reply_requires_human(result)

    assert "Sponsor a football team" in prompt
    assert "No sponsorship runbook exists." in prompt
    assert requires_human is True
    assert reason == "Cancellation requires approval. No sponsorship runbook exists."


def test_composer_forces_review_when_exact_concern_coverage_is_missing():
    result = _result()
    result.concerns[0].status = "ready"
    result.concerns[0].requires_human = False
    result.concerns[0].requires_human_reason = None

    requires_human, reason = _draft_review_requirements(
        result,
        ResponseDraft(
            response_text="Combined answer",
            covered_concern_ids=["cancel-contract"],
            covered_obligation_ids=[
                "cancel-contract:obligation-1",
                "buy-product:obligation-1",
                "buy-product:obligation-2",
            ],
        ),
    )

    assert requires_human is True
    assert "exact coverage" in reason


def test_composer_accepts_exact_coverage_and_surfaces_rule_conflicts():
    result = _result()
    result.concerns[0].status = "ready"
    result.concerns[0].requires_human = False
    result.concerns[0].requires_human_reason = None
    exact = ResponseDraft(
        response_text="Combined answer",
        covered_concern_ids=["buy-product", "cancel-contract"],
        covered_obligation_ids=[
            "buy-product:obligation-2",
            "cancel-contract:obligation-1",
            "buy-product:obligation-1",
        ],
    )

    assert _draft_review_requirements(result, exact) == (False, "")

    exact.conflicting_requirements = ["Cancellation policy conflicts with purchase rule"]
    requires_human, reason = _draft_review_requirements(result, exact)
    assert requires_human is True
    assert "Cancellation policy conflicts" in reason


def test_composer_forces_review_when_one_question_obligation_is_missing():
    result = _result()
    result.concerns[0].status = "ready"
    result.concerns[0].requires_human = False
    result.concerns[0].requires_human_reason = None

    requires_human, reason = _draft_review_requirements(
        result,
        ResponseDraft(
            response_text="Combined but incomplete answer",
            covered_concern_ids=["cancel-contract", "buy-product"],
            covered_obligation_ids=[
                "cancel-contract:obligation-1",
                "buy-product:obligation-1",
            ],
        ),
    )

    assert requires_human is True
    assert "every answer obligation" in reason


def test_pipeline_composer_deterministically_blocks_pending_action_claim():
    result = _result()
    result.concerns[0].action_outcomes = [
        RunbookActionOutcome(
            name="cancel_contract",
            label="Cancel contract",
            status="proposed",
        )
    ]

    unsafe = _pending_action_claim_check(
        result,
        "We are cancelling contract C-184 now.",
    )
    safe = _pending_action_claim_check(
        result,
        "We can cancel contract C-184 after approval.",
    )

    assert unsafe.blocked is True
    assert safe.blocked is False


def test_pipeline_composer_blocks_controlled_actor_future_action_claim():
    result = _result()
    result.concerns[0].action_outcomes = [
        RunbookActionOutcome(
            name="open_ticket",
            label="Open ticket",
            status="proposed",
        )
    ]

    unsafe = _pending_action_claim_check(
        result,
        "A human agent will follow up with you shortly to assist further with this case.",
    )
    conditional = _pending_action_claim_check(
        result,
        "A human agent will follow up once the ticket is approved.",
    )
    external = _pending_action_claim_check(
        result,
        "The carrier will update tracking tomorrow.",
    )

    assert unsafe.blocked is True
    assert conditional.blocked is False
    assert external.blocked is False
