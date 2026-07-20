from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import pytest

from automail import llm as llm_module
from automail.core import config as config_module
from automail.llm import usage as usage_module
from automail.support import issue_agent
from automail.support.issue_agent import (
    AutomationGroundingObligationAssessment,
    AutomationGroundingOutput,
    AutomationGroundingUnitAssessment,
)


def _issue(*concerns: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "issue-runbook-requirements",
        "subject": "Runbook response requirements",
        "aiRuns": [
            {
                "source": "channel:email-main",
                "intentResult": {"concerns": list(concerns)},
            }
        ],
    }


def _ground_with_output(
    monkeypatch: pytest.MonkeyPatch,
    *,
    issue: dict[str, Any],
    answer: str,
    resolutions: list[tuple[str, str, list[str], list[str]]],
) -> issue_agent.AutomationGroundingAssessment:
    answer_units = issue_agent._grounding_answer_units(answer)
    evidence_by_unit: dict[str, list[str]] = {}
    for _obligation_id, _resolution, answer_unit_ids, evidence_ids in resolutions:
        for unit_id in answer_unit_ids:
            evidence_by_unit.setdefault(unit_id, []).extend(evidence_ids)
    output = AutomationGroundingOutput(
        verdict="grounded",
        answer_sha256=issue_agent.grounding_text_sha256(answer),
        unit_assessments=[
            AutomationGroundingUnitAssessment(
                unit_id=unit["id"],
                unit_sha256=unit["sha256"],
                supported=True,
                evidence_ids=list(dict.fromkeys(evidence_by_unit.get(unit["id"], ["ticket"]))),
            )
            for unit in answer_units
        ],
        obligation_assessments=[
            AutomationGroundingObligationAssessment(
                obligation_id=obligation_id,
                resolution=resolution,  # type: ignore[arg-type]
                answer_unit_ids=answer_unit_ids,
                evidence_ids=evidence_ids,
            )
            for obligation_id, resolution, answer_unit_ids, evidence_ids in resolutions
        ],
    )
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(
        usage_module,
        "record_usage_from_result",
        lambda *_args, **_kwargs: None,
    )

    class FakeGroundingAgent:
        def invoke(
            self,
            _inputs: dict[str, Any],
            *,
            config: dict[str, Any],
        ) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            return {"structured_response": output}

    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: FakeGroundingAgent(),
    )
    return issue_agent.assess_issue_automation_grounding(
        issue=issue,
        messages=[{"direction": "customer", "body": "Please help with this request."}],
        answer=answer,
        articles=[],
        tenant_id="tenant-1",
        project_id="project-1",
    )


def test_s06_runbook_requirements_cannot_be_satisfied_by_generic_pending_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concern_id = "token-exposure"
    requirements = [
        "Tell the customer to remove the exposed token from public access immediately.",
        "Tell the customer to stop using the exposed token immediately.",
        "Preserve repository and access evidence without copying the secret.",
        "Require the approved secure channel for any replacement.",
    ]
    issue = _issue(
        {
            "concernId": concern_id,
            "matched": True,
            "intentName": "token-exposure",
            "answerObligations": [
                {
                    "obligationId": f"{concern_id}:obligation-1",
                    "question": "Confirm whether misuse occurred.",
                }
            ],
            "requiredGuidance": requirements,
        }
    )
    answer = (
        "Misuse is not determined. Revocation, replacement, and investigation "
        "remain pending human review."
    )
    units = issue_agent._grounding_answer_units(answer)
    concern_evidence = [f"concern:{concern_id}"]
    resolutions = [
        (f"{concern_id}:obligation-1", "pending_or_unavailable", [units[0]["id"]], concern_evidence),
        *[
            (
                f"{concern_id}:required-guidance-{index}",
                "pending_or_unavailable",
                [units[-1]["id"]],
                concern_evidence,
            )
            for index in range(1, len(requirements) + 1)
        ],
    ]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=resolutions,
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == tuple(requirements)
    requirement_assessments = [
        item
        for item in result.obligation_assessments
        if ":required-guidance-" in item["obligationId"]
    ]
    assert {item["resolution"] for item in requirement_assessments} == {"not_covered"}


def test_l03_source_bound_deadline_repeat_rejects_generic_pending_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concern_id = "urgent-deadline"
    repeat_requirement = (
        "Repeat the deadline: Zurich Commercial Court response due "
        "20 July 2026 at 12:00."
    )
    issue = _issue(
        {
            "concernId": concern_id,
            "matched": True,
            "intentName": "law-urgent-deadline",
            "answerObligations": [
                {
                    "obligationId": f"{concern_id}:obligation-1",
                    "question": "Identify and escalate the deadline.",
                }
            ],
            "requiredGuidance": [repeat_requirement],
        }
    )
    answer = (
        "Escalating the deadline is not confirmed. A related next step remains "
        "pending human review."
    )
    units = issue_agent._grounding_answer_units(answer)
    concern_evidence = [f"concern:{concern_id}"]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                f"{concern_id}:obligation-1",
                "pending_or_unavailable",
                [units[0]["id"]],
                concern_evidence,
            ),
            (
                f"{concern_id}:required-guidance-1",
                "pending_or_unavailable",
                [units[0]["id"]],
                concern_evidence,
            ),
        ],
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == (repeat_requirement,)
    repeat_assessment = next(
        item
        for item in result.obligation_assessments
        if item["obligationId"] == f"{concern_id}:required-guidance-1"
    )
    assert repeat_assessment["resolution"] == "not_covered"


def test_customer_questions_and_multi_concern_runbook_requirements_are_both_grounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = _issue(
        {
            "concernId": "order-intake",
            "matched": True,
            "intentName": "order-intake",
            "answerObligations": [
                {
                    "obligationId": "order-intake:obligation-1",
                    "question": "What detail is needed?",
                }
            ],
            "requiredGuidance": ["Ask the customer for the order number."],
        },
        {
            "concernId": "cancellation",
            "matched": True,
            "intentName": "cancellation",
            "answerObligations": [
                {
                    "obligationId": "cancellation:obligation-1",
                    "question": "Is cancellation complete?",
                }
            ],
            "requiredGuidance": ["State that cancellation remains pending human review."],
        },
    )
    ticket = issue_agent._automatic_ticket_context(issue)
    obligations = issue_agent._answer_obligations_from_issue(issue)
    answer = "Please send the order number. Cancellation remains pending human review."
    units = issue_agent._grounding_answer_units(answer)
    resolutions = [
        ("order-intake:obligation-1", "answered", [units[0]["id"]], ["concern:order-intake"]),
        (
            "order-intake:required-guidance-1",
            "answered",
            [units[0]["id"]],
            ["concern:order-intake"],
        ),
        (
            "cancellation:obligation-1",
            "pending_or_unavailable",
            [units[1]["id"]],
            ["concern:cancellation"],
        ),
        (
            "cancellation:required-guidance-1",
            "answered",
            [units[1]["id"]],
            ["concern:cancellation"],
        ),
    ]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=resolutions,
    )

    assert [item.get("kind", "customer_question") for item in obligations] == [
        "customer_question",
        "runbook_requirement",
        "customer_question",
        "runbook_requirement",
    ]
    assert ticket["concerns"][0]["requiredGuidanceObligations"] == [
        {
            "id": "order-intake:required-guidance-1",
            "question": "Ask the customer for the order number.",
            "kind": "runbook_requirement",
        }
    ]
    assert issue_agent._validated_obligation_coverage(
        issue,
        [item["id"] for item in obligations],
    )[1:] == (False, "")
    assert result.verified is True
    assert {item["resolution"] for item in result.obligation_assessments} == {
        "answered",
        "pending_or_unavailable",
    }
