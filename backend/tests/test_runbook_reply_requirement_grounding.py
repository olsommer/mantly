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
    articles: list[dict[str, Any]] | None = None,
    verdict: str = "grounded",
) -> issue_agent.AutomationGroundingAssessment:
    answer_units = issue_agent._grounding_answer_units(answer)
    evidence_by_unit: dict[str, list[str]] = {}
    for _obligation_id, _resolution, answer_unit_ids, evidence_ids in resolutions:
        for unit_id in answer_unit_ids:
            evidence_by_unit.setdefault(unit_id, []).extend(evidence_ids)
    output = AutomationGroundingOutput(
        verdict=verdict,  # type: ignore[arg-type]
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
        articles=articles or [],
        tenant_id="tenant-1",
        project_id="project-1",
    )


def _audit_reporting_tool_evidence(
    *,
    audit_api: str = "true",
    scheduled_audit_email: str = "false",
) -> dict[str, Any]:
    return {
        "name": "fixture_saas_entitlements_acme",
        "method": "GET",
        "status": "success",
        "responseFacts": [
            {
                "path": "fixture_evidence.result.0",
                "value": f"audit_api: {audit_api}",
            },
            {
                "path": "fixture_evidence.result.1",
                "value": f"scheduled_audit_email: {scheduled_audit_email}",
            },
        ],
    }


def _audit_reporting_issue(
    *,
    concern_id: str = "audit-reporting",
    tool_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _issue(
        {
            "concernId": concern_id,
            "matched": True,
            "intentName": "saas-audit-reporting",
            "requiredGuidance": [
                "State reviewed current audit workarounds and unavailable "
                "scheduled-email capability explicitly."
            ],
            "outcome": {
                "toolEvidence": tool_evidence or [_audit_reporting_tool_evidence()],
            },
        }
    )


def _audit_reporting_article() -> dict[str, Any]:
    return {
        "id": "saas-audit-reporting-policy",
        "title": "Audit reporting capabilities",
        "body": (
            "Audit events can be exported through the API or as CSV. Scheduled "
            "email delivery of audit reports is not currently available."
        ),
        "tags": ["audit", "reporting"],
        "status": "published",
        "reviewStatus": "reviewed",
        "freshnessStatus": "fresh",
        "needsReview": False,
        "automationAllowed": True,
        "public": True,
        "visibility": "public",
    }


def _audit_reporting_override_inputs(
    issue: dict[str, Any],
    answer: str,
) -> tuple[
    dict[str, Any],
    tuple[str, ...],
    dict[str, dict[str, Any]],
    dict[str, frozenset[str]],
]:
    ticket = issue_agent._automatic_ticket_context(issue)
    units = issue_agent._grounding_answer_units(answer)
    expected_units = {unit["id"]: unit for unit in units}
    tool_id = "tool:audit-reporting:fixture_saas_entitlements_acme"
    evidence = {
        unit_id: frozenset({tool_id, "saas-audit-reporting-policy"})
        for unit_id in expected_units
    }
    return ticket, tuple(expected_units), expected_units, evidence


def test_s09_supported_audit_capability_conjunction_overrides_semantic_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concern_id = "audit-reporting"
    issue = _audit_reporting_issue(concern_id=concern_id)
    answer = (
        "Scheduled daily email reporting for admin audit events is not currently "
        "available. As a workaround, you can export current audit events via API "
        "or CSV."
    )
    units = issue_agent._grounding_answer_units(answer)
    tool_id = f"tool:{concern_id}:fixture_saas_entitlements_acme"
    article_id = "saas-audit-reporting-policy"

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                f"{concern_id}:required-guidance-1",
                "not_covered",
                [unit["id"] for unit in units],
                [tool_id, article_id],
            )
        ],
        articles=[_audit_reporting_article()],
        verdict="not_grounded",
    )

    assert result.verified is True
    assert result.status == "passed"
    assert result.uncovered_obligations == ()
    assert result.obligation_assessments == (
        {
            "obligationId": f"{concern_id}:required-guidance-1",
            "resolution": "answered",
            "covered": True,
            "answerUnitIds": [unit["id"] for unit in units],
            "evidenceIds": [tool_id, article_id],
        },
    )


@pytest.mark.parametrize(
    "answer",
    [
        "Scheduled daily email reporting for audit events is not currently available.",
        "As a workaround, you can export current audit events via API or CSV.",
        (
            "Scheduled daily email reporting for audit events is not currently "
            "available. As a workaround, you can export current audit events via API."
        ),
        (
            'The customer says "scheduled daily email reporting for audit events is '
            'not currently available." As a workaround, you can export current audit '
            "events via API or CSV."
        ),
        (
            "It is not true that scheduled daily email reporting for audit events is "
            "unavailable. As a workaround, you can export current audit events via API or CSV."
        ),
        (
            "Scheduled daily email reporting for audit events is not currently "
            "available. API and CSV audit exports are not available as a workaround."
        ),
        (
            "'Scheduled daily email reporting for audit events is not currently "
            "available.' As a workaround, you can export current audit events via "
            "API or CSV."
        ),
        (
            "The policy states scheduled daily email reporting for audit events is "
            "not currently available. As a workaround, you can export current audit "
            "events via API or CSV."
        ),
        (
            "Scheduled daily email reporting for audit events is not currently "
            "available, but that statement is false. As a workaround, you can export "
            "current audit events via API or CSV."
        ),
        (
            "Scheduled daily email reporting for audit events is not currently "
            "available, although it is currently available. As a workaround, you can "
            "export current audit events via API or CSV."
        ),
        (
            "Scheduled daily email reporting for audit events is not currently "
            "available, though it remains available. As a workaround, you can export "
            "current audit events via API or CSV."
        ),
        (
            "Scheduled daily email reporting for audit events is not currently "
            "available, but currently available to admins. As a workaround, you can "
            "export current audit events via API or CSV."
        ),
        (
            "Scheduled daily email reporting for audit events is not currently "
            "available. As a workaround, you can export current audit events via API "
            "or CSV, but neither method works."
        ),
        (
            "Scheduled daily email reporting for audit events is not currently "
            "available. As a workaround, you can export current audit events via API "
            "or CSV, although this is false."
        ),
        (
            "Scheduled daily email reporting for audit events is not currently "
            "available. As a workaround, you can export current audit events via API "
            "or CSV, but both are disabled."
        ),
        (
            "Scheduled daily email reporting for audit events is not currently "
            "available. You can export current audit events via API or CSV."
        ),
    ],
)
def test_audit_capability_conjunction_override_rejects_missing_or_indirect_legs(
    answer: str,
) -> None:
    issue = _audit_reporting_issue()
    ticket, unit_ids, expected_units, evidence = _audit_reporting_override_inputs(
        issue,
        answer,
    )

    assert (
        issue_agent._tool_and_knowledge_backed_audit_reporting_guidance_answers_obligation(
            ticket=ticket,
            concern_id="audit-reporting",
            question=(
                "State reviewed current audit workarounds and unavailable "
                "scheduled-email capability explicitly."
            ),
            answer_unit_ids=unit_ids,
            expected_units=expected_units,
            supported_unit_evidence_ids=evidence,
            citation_ids=frozenset({"saas-audit-reporting-policy"}),
        )
        is False
    )


@pytest.mark.parametrize(
    "question",
    [
        (
            "Do not state reviewed current audit workarounds and unavailable "
            "scheduled-email capability explicitly."
        ),
        (
            "You might call current audit workarounds and scheduled-email capability "
            "unavailable."
        ),
        (
            "State reviewed current audit workaround and unavailable scheduled-email "
            "capability explicitly."
        ),
    ],
)
def test_audit_capability_conjunction_override_requires_exact_controlled_guidance(
    question: str,
) -> None:
    answer = (
        "Scheduled daily email reporting for admin audit events is not currently "
        "available. As a workaround, you can export current audit events via API or CSV."
    )
    issue = _audit_reporting_issue()
    ticket, unit_ids, expected_units, evidence = _audit_reporting_override_inputs(
        issue,
        answer,
    )

    assert not issue_agent._tool_and_knowledge_backed_audit_reporting_guidance_answers_obligation(
        ticket=ticket,
        concern_id="audit-reporting",
        question=question,
        answer_unit_ids=unit_ids,
        expected_units=expected_units,
        supported_unit_evidence_ids=evidence,
        citation_ids=frozenset({"saas-audit-reporting-policy"}),
    )


def test_audit_capability_conjunction_override_rejects_unsupported_or_foreign_scope() -> None:
    answer = (
        "Scheduled daily email reporting for admin audit events is not currently "
        "available. As a workaround, you can export current audit events via API or CSV."
    )
    issue = _audit_reporting_issue()
    ticket, unit_ids, expected_units, evidence = _audit_reporting_override_inputs(
        issue,
        answer,
    )
    unsupported_evidence = dict(evidence)
    unsupported_evidence.pop(unit_ids[-1])

    assert not issue_agent._tool_and_knowledge_backed_audit_reporting_guidance_answers_obligation(
        ticket=ticket,
        concern_id="audit-reporting",
        question=(
            "State reviewed current audit workarounds and unavailable "
            "scheduled-email capability explicitly."
        ),
        answer_unit_ids=unit_ids,
        expected_units=expected_units,
        supported_unit_evidence_ids=unsupported_evidence,
        citation_ids=frozenset({"saas-audit-reporting-policy"}),
    )

    foreign_ticket = issue_agent._automatic_ticket_context(
        _audit_reporting_issue(concern_id="other-concern")
    )
    assert not issue_agent._tool_and_knowledge_backed_audit_reporting_guidance_answers_obligation(
        ticket=foreign_ticket,
        concern_id="audit-reporting",
        question=(
            "State reviewed current audit workarounds and unavailable "
            "scheduled-email capability explicitly."
        ),
        answer_unit_ids=unit_ids,
        expected_units=expected_units,
        supported_unit_evidence_ids=evidence,
        citation_ids=frozenset({"saas-audit-reporting-policy"}),
    )


def test_audit_capability_conjunction_override_rejects_conflicting_tool_state() -> None:
    answer = (
        "Scheduled daily email reporting for admin audit events is not currently "
        "available. As a workaround, you can export current audit events via API or CSV."
    )
    issue = _audit_reporting_issue(
        tool_evidence=[
            _audit_reporting_tool_evidence(),
            _audit_reporting_tool_evidence(scheduled_audit_email="true"),
        ]
    )
    ticket, unit_ids, expected_units, evidence = _audit_reporting_override_inputs(
        issue,
        answer,
    )

    assert not issue_agent._tool_and_knowledge_backed_audit_reporting_guidance_answers_obligation(
        ticket=ticket,
        concern_id="audit-reporting",
        question=(
            "State reviewed current audit workarounds and unavailable "
            "scheduled-email capability explicitly."
        ),
        answer_unit_ids=unit_ids,
        expected_units=expected_units,
        supported_unit_evidence_ids=evidence,
        citation_ids=frozenset({"saas-audit-reporting-policy"}),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "draft"),
        ("reviewStatus", "pending"),
        ("freshnessStatus", "stale"),
        ("needsReview", True),
        ("automationAllowed", False),
        ("public", False),
    ],
)
def test_audit_capability_conjunction_override_rejects_ineligible_knowledge(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    concern_id = "audit-reporting"
    issue = _audit_reporting_issue(concern_id=concern_id)
    answer = (
        "Scheduled daily email reporting for admin audit events is not currently "
        "available. As a workaround, you can export current audit events via API or CSV."
    )
    units = issue_agent._grounding_answer_units(answer)
    tool_id = f"tool:{concern_id}:fixture_saas_entitlements_acme"
    article = _audit_reporting_article()
    article[field] = value
    if field == "public":
        article["visibility"] = "private"

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                f"{concern_id}:required-guidance-1",
                "not_covered",
                [unit["id"] for unit in units],
                [tool_id, article["id"]],
            )
        ],
        articles=[article],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == (
        "State reviewed current audit workarounds and unavailable "
        "scheduled-email capability explicitly.",
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


_REPEATED_INVOICE_GUIDANCE = (
    "State the current invoice status and due date from the billing lookup.",
    "State the billed amount and subscription amount from the billing lookup.",
    "State that credit eligibility and amount remain unverified pending review.",
)


def _invoice_tool_evidence(
    *,
    method: str = "GET",
    status: str = "success",
    billed_amount: str = "120",
) -> dict[str, Any]:
    return {
        "name": "fixture_saas_invoice_inv_9012",
        "method": method,
        "status": status,
        "responseFacts": [
            {"path": "fixture_evidence.result.0", "value": "invoice_status: open"},
            {"path": "fixture_evidence.result.1", "value": "due_date: 2026-08-15"},
            {
                "path": "fixture_evidence.result.2",
                "value": f"billed_amount: {billed_amount}",
            },
            {"path": "fixture_evidence.result.3", "value": "subscription_amount: 100"},
        ],
    }


def _conflicting_invoice_tool_evidence() -> dict[str, Any]:
    evidence = _invoice_tool_evidence()
    evidence["responseFacts"].append(
        {
            "path": "fixture_evidence.result.4",
            "value": "invoice_status: paid",
        }
    )
    return evidence


def _whitespace_conflicting_invoice_tool_evidence() -> dict[str, Any]:
    return {
        "name": "fixture_saas_invoice_inv_9012",
        "method": "GET",
        "status": "success",
        "responseFacts": [
            {
                "path": "fixture_evidence.result.0",
                "value": "status: open",
            },
            {
                "path": "fixture_evidence.result.1",
                "value": "status : paid",
            },
        ],
    }


def _unflagged_nonaffirmative_invoice_tool_evidence(
    *,
    wrapped: bool,
) -> dict[str, Any]:
    return {
        "name": "fixture_saas_invoice_inv_9012",
        "method": "GET",
        "status": "success",
        "responseFacts": (
            [
                {
                    "path": "fixture_evidence.result.0",
                    "value": "found: false",
                },
                {
                    "path": "fixture_evidence.result.1",
                    "value": "status: not_found",
                },
            ]
            if wrapped
            else [
                {"path": "found", "value": False},
                {"path": "status", "value": "not_found"},
            ]
        ),
    }


def _subscription_tool_evidence(
    *,
    subscription_amount: str = "100",
) -> dict[str, Any]:
    return {
        "name": "fixture_saas_subscription_northwind",
        "method": "GET",
        "status": "success",
        "responseFacts": [
            {
                "path": "fixture_evidence.result.0",
                "value": "subscription_status: active",
            },
            {
                "path": "fixture_evidence.result.1",
                "value": f"subscription_amount: {subscription_amount}",
            },
        ],
    }


def _extra_tool_evidence(
    *,
    method: str = "GET",
    status: str = "success",
    truncated: bool = False,
    nonaffirmative: bool = False,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "name": "fixture_saas_risk_check",
        "method": method,
        "status": status,
        "responseFacts": [
            {
                "path": "fixture_evidence.result.0",
                "value": "risk_status: clear",
            }
        ],
    }
    if truncated:
        evidence["responseFactsTruncated"] = True
    if nonaffirmative:
        evidence["hasNonaffirmativeLookupResult"] = True
    return evidence


def _invoice_concern(
    concern_id: str,
    *,
    runbook: str = "saas-invoice-dispute",
    guidance: tuple[str, ...] = _REPEATED_INVOICE_GUIDANCE,
    tool_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "requiredGuidance": list(guidance),
    }
    if tool_evidence is not None:
        outcome["toolEvidence"] = tool_evidence
    return {
        "concernId": concern_id,
        "matched": True,
        "intentName": runbook,
        "outcome": outcome,
    }


def _pending_runbook_action(concern_id: str) -> dict[str, Any]:
    return {
        "id": f"pending-{concern_id}",
        "type": "runbook_webhook",
        "status": "pending",
        "metadata": {
            "source": "runbook",
            "approvalRequired": True,
            "concernId": concern_id,
        },
        "result": {
            "proposedAction": {
                "name": "set_status",
                "label": "Set status",
            }
        },
    }


def _successful_runbook_action(concern_id: str) -> dict[str, Any]:
    return {
        "id": f"success-{concern_id}",
        "type": "runbook_webhook",
        "status": "success",
        "completedAt": "2026-07-21T10:00:00Z",
        "metadata": {
            "source": "runbook",
            "concernId": concern_id,
        },
        "result": {
            "proposedAction": {
                "name": "set_status",
                "label": "Set status",
            },
            "application": {
                "applied": True,
                "webhookResult": {
                    "status": "ok",
                    "response": {"status": "active"},
                },
            },
        },
    }


def _repeated_policy_issue_with_actions(
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    guidance = _REPEATED_INVOICE_GUIDANCE[2]
    issue = _issue(
        *(
            _invoice_concern(
                concern_id,
                guidance=(guidance,),
                tool_evidence=[
                    _invoice_tool_evidence(),
                    _subscription_tool_evidence(),
                ],
            )
            for concern_id in ("invoice-source", "invoice-target")
        )
    )
    issue["actionExecutions"] = actions
    return issue


def _repeated_invoice_resolutions(
    answer: str,
    *,
    source_concern_id: str,
    target_concern_ids: tuple[str, ...],
) -> list[tuple[str, str, list[str], list[str]]]:
    units = issue_agent._grounding_answer_units(answer)
    source_tool_id = (
        f"tool:{source_concern_id}:fixture_saas_invoice_inv_9012"
    )
    resolutions: list[tuple[str, str, list[str], list[str]]] = []
    for guidance_index in range(1, len(_REPEATED_INVOICE_GUIDANCE) + 1):
        unit_id = units[0]["id"] if guidance_index < 3 else units[1]["id"]
        source_evidence_id = (
            source_tool_id
            if guidance_index < 3
            else f"concern:{source_concern_id}"
        )
        resolutions.append(
            (
                f"{source_concern_id}:required-guidance-{guidance_index}",
                "answered",
                [unit_id],
                [source_evidence_id],
            )
        )
        resolutions.extend(
            (
                f"{target_concern_id}:required-guidance-{guidance_index}",
                "not_covered",
                [unit_id],
                [source_evidence_id],
            )
            for target_concern_id in target_concern_ids
        )
    return resolutions


def test_repeated_runbook_requirements_rebind_to_exact_target_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concern_ids = ("invoice-source", "invoice-target-a", "invoice-target-b")
    issue = _issue(
        *(
            _invoice_concern(
                concern_id,
                tool_evidence=(
                    [_invoice_tool_evidence(), _subscription_tool_evidence()]
                    if index % 2 == 0
                    else [_subscription_tool_evidence(), _invoice_tool_evidence()]
                ),
            )
            for index, concern_id in enumerate(concern_ids)
        )
    )
    # Approval-pending mutations are state, not reusable proof, and do not make
    # otherwise identical read-only concern evidence unsafe to rebind.
    issue["actionExecutions"] = [_pending_runbook_action("invoice-target-b")]
    ticket = issue_agent._automatic_ticket_context(issue)
    assert ticket["runbookActions"][0]["status"] == "pending_approval"
    assert issue_agent._durable_successful_runbook_action_concern_ids(ticket) == frozenset()
    answer = (
        "The invoice is open, due 2026-08-15, and was billed 120 instead "
        "of the subscription amount of 100. Credit eligibility and amount "
        "remain unverified pending review."
    )
    units = issue_agent._grounding_answer_units(answer)

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=_repeated_invoice_resolutions(
            answer,
            source_concern_id=concern_ids[0],
            target_concern_ids=concern_ids[1:],
        ),
        verdict="not_grounded",
    )

    assert result.verified is True
    assert result.status == "passed"
    assert result.uncovered_obligations == ()
    assert len(result.obligation_assessments) == 9
    assert all(
        assessment["resolution"] == "answered"
        and assessment["covered"] is True
        for assessment in result.obligation_assessments
    )
    assessment_by_id = {
        assessment["obligationId"]: assessment
        for assessment in result.obligation_assessments
    }
    for target_concern_id in concern_ids[1:]:
        target_tool_id = (
            f"tool:{target_concern_id}:fixture_saas_invoice_inv_9012"
        )
        assert assessment_by_id[
            f"{target_concern_id}:required-guidance-1"
        ]["evidenceIds"] == [target_tool_id]
        assert assessment_by_id[
            f"{target_concern_id}:required-guidance-2"
        ]["evidenceIds"] == [target_tool_id]
        assert assessment_by_id[
            f"{target_concern_id}:required-guidance-3"
        ]["evidenceIds"] == [f"concern:{target_concern_id}"]

    unit_assessments = {
        assessment["unitId"]: assessment
        for assessment in result.unit_assessments
    }
    assert set(unit_assessments[units[0]["id"]]["evidenceIds"]) == {
        f"tool:{concern_id}:fixture_saas_invoice_inv_9012"
        for concern_id in concern_ids
    }
    assert set(unit_assessments[units[1]["id"]]["evidenceIds"]) == {
        f"concern:{concern_id}" for concern_id in concern_ids
    }


@pytest.mark.parametrize("action_concern_id", ["invoice-source", "invoice-target"])
def test_repeated_runbook_requirement_rebinding_fails_closed_for_durable_action(
    monkeypatch: pytest.MonkeyPatch,
    action_concern_id: str,
) -> None:
    issue = _issue(
        _invoice_concern(
            "invoice-source",
            guidance=(_REPEATED_INVOICE_GUIDANCE[2],),
            tool_evidence=[_invoice_tool_evidence()],
        ),
        _invoice_concern(
            "invoice-target",
            guidance=(_REPEATED_INVOICE_GUIDANCE[2],),
            tool_evidence=[_invoice_tool_evidence()],
        ),
    )
    issue["actionExecutions"] = [_successful_runbook_action(action_concern_id)]
    ticket = issue_agent._automatic_ticket_context(issue)
    assert issue_agent._durable_successful_runbook_action_concern_ids(ticket) == frozenset(
        {action_concern_id}
    )
    answer = "Credit eligibility and amount remain unverified pending review."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                ["concern:invoice-source"],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                ["concern:invoice-source"],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    target_assessment = next(
        assessment
        for assessment in result.obligation_assessments
        if assessment["obligationId"] == "invoice-target:required-guidance-1"
    )
    assert target_assessment["resolution"] == "not_covered"
    assert target_assessment.get("evidenceIds", []) == []


@pytest.mark.parametrize("hidden_position", [10, 25], ids=("after-ten", "after-twenty-five"))
def test_rebinding_raw_action_guard_finds_success_beyond_context_bounds(
    monkeypatch: pytest.MonkeyPatch,
    hidden_position: int,
) -> None:
    if hidden_position == 10:
        prefix_actions = []
        for index in range(10):
            pending = _pending_runbook_action("invoice-source")
            pending["id"] = f"pending-source-{index}"
            prefix_actions.append(pending)
    else:
        prefix_actions = [
            {"id": f"noise-{index}", "type": "noop", "status": "pending"}
            for index in range(25)
        ]
    issue = _repeated_policy_issue_with_actions(
        [*prefix_actions, _successful_runbook_action("invoice-target")]
    )
    ticket = issue_agent._automatic_ticket_context(issue)
    assert issue_agent._durable_successful_runbook_action_concern_ids(ticket) == frozenset()
    assert issue_agent._raw_issue_durable_runbook_action_concern_ids(issue) == frozenset(
        {"invoice-target"}
    )
    answer = "Credit eligibility and amount remain unverified pending review."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                ["concern:invoice-source"],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                ["concern:invoice-source"],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"


@pytest.mark.parametrize(
    "guard_case",
    (
        "oversized-actions",
        "missing-scope",
        "oversized-scope",
        "malformed-scope",
    ),
)
def test_rebinding_raw_action_guard_disables_rebinding_when_scan_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
    guard_case: str,
) -> None:
    if guard_case == "oversized-actions":
        actions = [
            {"id": f"noise-{index}", "type": "noop", "status": "pending"}
            for index in range(
                issue_agent._RUNBOOK_REBINDING_MAX_RAW_ACTION_EXECUTIONS + 1
            )
        ]
    else:
        successful_action = _successful_runbook_action("invoice-target")
        if guard_case == "missing-scope":
            successful_action["metadata"].pop("concernId")
        elif guard_case == "malformed-scope":
            successful_action["metadata"]["concernIds"] = {
                "unexpected": "shape"
            }
        else:
            successful_action["metadata"]["concernIds"] = [
                f"concern-{index}" for index in range(21)
            ]
        actions = [successful_action]
    issue = _repeated_policy_issue_with_actions(actions)
    assert issue_agent._raw_issue_durable_runbook_action_concern_ids(issue) is None
    answer = "Credit eligibility and amount remain unverified pending review."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                ["concern:invoice-source"],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                ["concern:invoice-source"],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"


def test_rebinding_raw_action_guard_unions_conflicting_scope_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successful_action = _successful_runbook_action("invoice-source")
    proposed_action = successful_action["result"]["proposedAction"]
    proposed_action["concernId"] = "invoice-target"
    proposed_action["payload"] = {"concernId": "payload-target"}
    successful_action["metadata"]["proposedAction"] = {
        "concernId": "metadata-proposed-target"
    }
    issue = _repeated_policy_issue_with_actions([successful_action])

    assert issue_agent._raw_issue_durable_runbook_action_concern_ids(
        issue
    ) == frozenset(
        {
            "invoice-source",
            "invoice-target",
            "payload-target",
            "metadata-proposed-target",
        }
    )
    answer = "Credit eligibility and amount remain unverified pending review."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                ["concern:invoice-source"],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                ["concern:invoice-source"],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"


@pytest.mark.parametrize(
    "target_tool_evidence",
    [
        [_invoice_tool_evidence()],
        [
            _invoice_tool_evidence(),
            _subscription_tool_evidence(),
            _extra_tool_evidence(status="failed"),
        ],
        [
            _invoice_tool_evidence(),
            _subscription_tool_evidence(),
            _extra_tool_evidence(method="POST"),
        ],
        [
            _invoice_tool_evidence(),
            _subscription_tool_evidence(),
            _extra_tool_evidence(truncated=True),
        ],
        [
            _invoice_tool_evidence(),
            _subscription_tool_evidence(),
            _extra_tool_evidence(nonaffirmative=True),
        ],
        [
            _invoice_tool_evidence(),
            _subscription_tool_evidence(subscription_amount="101"),
        ],
    ],
    ids=(
        "missing-tool",
        "failed-extra",
        "post-extra",
        "truncated-extra",
        "nonaffirmative-extra",
        "conflicting-tool-facts",
    ),
)
def test_concern_container_rebinding_requires_identical_complete_read_only_sets(
    monkeypatch: pytest.MonkeyPatch,
    target_tool_evidence: list[dict[str, Any]],
) -> None:
    guidance = _REPEATED_INVOICE_GUIDANCE[2]
    issue = _issue(
        _invoice_concern(
            "invoice-source",
            guidance=(guidance,),
            tool_evidence=[
                _invoice_tool_evidence(),
                _subscription_tool_evidence(),
            ],
        ),
        _invoice_concern(
            "invoice-target",
            guidance=(guidance,),
            tool_evidence=target_tool_evidence,
        ),
    )
    answer = "Credit eligibility and amount remain unverified pending review."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                ["concern:invoice-source"],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                ["concern:invoice-source"],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    target_assessment = next(
        assessment
        for assessment in result.obligation_assessments
        if assessment["obligationId"] == "invoice-target:required-guidance-1"
    )
    assert target_assessment["resolution"] == "not_covered"
    assert target_assessment.get("evidenceIds", []) == []


@pytest.mark.parametrize(
    "duplicate_record",
    [
        _invoice_tool_evidence(method="POST"),
        _invoice_tool_evidence(status="failed"),
        {**_invoice_tool_evidence(), "responseFactsTruncated": True},
        {**_invoice_tool_evidence(), "hasNonaffirmativeLookupResult": True},
        _invoice_tool_evidence(),
    ],
    ids=(
        "post",
        "failed",
        "truncated",
        "nonaffirmative",
        "identical-safe",
    ),
)
def test_tool_rebinding_rejects_any_duplicate_raw_evidence_id(
    monkeypatch: pytest.MonkeyPatch,
    duplicate_record: dict[str, Any],
) -> None:
    guidance = _REPEATED_INVOICE_GUIDANCE[0]
    issue = _issue(
        _invoice_concern(
            "invoice-source",
            guidance=(guidance,),
            tool_evidence=[_invoice_tool_evidence()],
        ),
        _invoice_concern(
            "invoice-target",
            guidance=(guidance,),
            tool_evidence=[_invoice_tool_evidence(), duplicate_record],
        ),
    )
    answer = "The invoice is open and due 2026-08-15."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]
    source_evidence_id = "tool:invoice-source:fixture_saas_invoice_inv_9012"

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                [source_evidence_id],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                [source_evidence_id],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    target_assessment = next(
        assessment
        for assessment in result.obligation_assessments
        if assessment["obligationId"] == "invoice-target:required-guidance-1"
    )
    assert target_assessment["resolution"] == "not_covered"
    assert target_assessment.get("evidenceIds", []) == []


@pytest.mark.parametrize("whitespace_variant", [False, True])
def test_concern_container_rebinding_rejects_identical_internal_fact_conflicts(
    monkeypatch: pytest.MonkeyPatch,
    whitespace_variant: bool,
) -> None:
    guidance = _REPEATED_INVOICE_GUIDANCE[2]
    issue = _issue(
        *(
            _invoice_concern(
                concern_id,
                guidance=(guidance,),
                tool_evidence=[
                    _whitespace_conflicting_invoice_tool_evidence()
                    if whitespace_variant
                    else _conflicting_invoice_tool_evidence()
                ],
            )
            for concern_id in ("invoice-source", "invoice-target")
        )
    )
    answer = "Credit eligibility and amount remain unverified pending review."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                ["concern:invoice-source"],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                ["concern:invoice-source"],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    target_assessment = next(
        assessment
        for assessment in result.obligation_assessments
        if assessment["obligationId"] == "invoice-target:required-guidance-1"
    )
    assert target_assessment["resolution"] == "not_covered"
    assert target_assessment.get("evidenceIds", []) == []


@pytest.mark.parametrize("wrapped", [False, True], ids=("direct", "fixture-wrapped"))
def test_concern_container_rebinding_rejects_unflagged_nonaffirmative_lookup(
    monkeypatch: pytest.MonkeyPatch,
    wrapped: bool,
) -> None:
    guidance = _REPEATED_INVOICE_GUIDANCE[2]
    issue = _issue(
        *(
            _invoice_concern(
                concern_id,
                guidance=(guidance,),
                tool_evidence=[
                    _unflagged_nonaffirmative_invoice_tool_evidence(
                        wrapped=wrapped
                    )
                ],
            )
            for concern_id in ("invoice-source", "invoice-target")
        )
    )
    answer = "Credit eligibility and amount remain unverified pending review."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                ["concern:invoice-source"],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                ["concern:invoice-source"],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    target_assessment = next(
        assessment
        for assessment in result.obligation_assessments
        if assessment["obligationId"] == "invoice-target:required-guidance-1"
    )
    assert target_assessment["resolution"] == "not_covered"
    assert target_assessment.get("evidenceIds", []) == []


@pytest.mark.parametrize(
    ("target_runbook", "target_guidance", "target_tool"),
    [
        ("saas-other-runbook", _REPEATED_INVOICE_GUIDANCE, _invoice_tool_evidence()),
        (
            "saas-invoice-dispute",
            (
                "State a different invoice requirement.",
                *_REPEATED_INVOICE_GUIDANCE[1:],
            ),
            _invoice_tool_evidence(),
        ),
        (
            "saas-invoice-dispute",
            _REPEATED_INVOICE_GUIDANCE,
            _invoice_tool_evidence(billed_amount="121"),
        ),
        (
            "saas-invoice-dispute",
            _REPEATED_INVOICE_GUIDANCE,
            _invoice_tool_evidence(method="POST"),
        ),
        (
            "saas-invoice-dispute",
            _REPEATED_INVOICE_GUIDANCE,
            _invoice_tool_evidence(status="failed"),
        ),
        ("saas-invoice-dispute", _REPEATED_INVOICE_GUIDANCE, None),
    ],
    ids=(
        "other-runbook",
        "other-guidance",
        "different-facts",
        "post",
        "failed",
        "missing",
    ),
)
def test_repeated_runbook_requirement_rebinding_rejects_nonidentical_proof(
    monkeypatch: pytest.MonkeyPatch,
    target_runbook: str,
    target_guidance: tuple[str, ...],
    target_tool: dict[str, Any] | None,
) -> None:
    issue = _issue(
        _invoice_concern(
            "invoice-source",
            tool_evidence=[_invoice_tool_evidence()],
        ),
        _invoice_concern(
            "invoice-target",
            runbook=target_runbook,
            guidance=target_guidance,
            tool_evidence=[] if target_tool is None else [target_tool],
        ),
    )
    answer = (
        "The invoice is open, due 2026-08-15, and was billed 120 instead "
        "of the subscription amount of 100. Credit eligibility and amount "
        "remain unverified pending review."
    )

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=_repeated_invoice_resolutions(
            answer,
            source_concern_id="invoice-source",
            target_concern_ids=("invoice-target",),
        ),
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert any(
        assessment["obligationId"].startswith("invoice-target:")
        and assessment["resolution"] == "not_covered"
        for assessment in result.obligation_assessments
    )


def test_lookup_bound_requirement_cannot_rebind_concern_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guidance = "State the result of the invoice lookup."
    issue = _issue(
        _invoice_concern("invoice-source", guidance=(guidance,)),
        _invoice_concern("invoice-target", guidance=(guidance,)),
    )
    answer = "The invoice lookup result is open."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                ["concern:invoice-source"],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                ["concern:invoice-source"],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.uncovered_obligations == (guidance,)


def test_rebinding_rejects_source_specific_identifier_for_different_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guidance = _REPEATED_INVOICE_GUIDANCE[0]
    generic_tool = {
        "name": "invoice_lookup",
        "method": "GET",
        "status": "success",
        "responseFacts": [
            {"path": "invoice_status", "value": "open"},
            {"path": "due_date", "value": "2026-08-15"},
        ],
    }
    issue = _issue(
        {
            **_invoice_concern(
                "invoice-source",
                guidance=(guidance,),
                tool_evidence=[generic_tool],
            ),
            "sourceText": "Please check invoice INV-11111.",
        },
        {
            **_invoice_concern(
                "invoice-target",
                guidance=(guidance,),
                tool_evidence=[generic_tool],
            ),
            "sourceText": "Please check invoice INV-22222.",
        },
    )
    answer = "Invoice INV-11111 is open and due 2026-08-15."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]
    source_evidence_id = "tool:invoice-source:invoice_lookup"

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                [source_evidence_id],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                [source_evidence_id],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == (guidance,)


@pytest.mark.parametrize(
    ("source_text", "target_text", "answer_identifier"),
    [
        (
            "Compare invoices INV-11111 and INV-22222.",
            "Compare invoices INV-11111 and INV-22222.",
            "INV-11111",
        ),
        ("Check invoice INV-11.", "Check invoice INV-22.", "INV-11"),
    ],
    ids=("ambiguous-broad-scope", "short-identifiers"),
)
def test_rebinding_identifier_requires_independent_tool_binding(
    monkeypatch: pytest.MonkeyPatch,
    source_text: str,
    target_text: str,
    answer_identifier: str,
) -> None:
    guidance = _REPEATED_INVOICE_GUIDANCE[0]
    generic_tool = {
        "name": "invoice_lookup",
        "method": "GET",
        "status": "success",
        "responseFacts": [
            {"path": "invoice_status", "value": "open"},
            {"path": "due_date", "value": "2026-08-15"},
        ],
    }
    issue = _issue(
        {
            **_invoice_concern(
                "invoice-source",
                guidance=(guidance,),
                tool_evidence=[generic_tool],
            ),
            "sourceText": source_text,
        },
        {
            **_invoice_concern(
                "invoice-target",
                guidance=(guidance,),
                tool_evidence=[generic_tool],
            ),
            "sourceText": target_text,
        },
    )
    answer = f"Invoice {answer_identifier} is open and due 2026-08-15."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]
    source_evidence_id = "tool:invoice-source:invoice_lookup"

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                [source_evidence_id],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                [source_evidence_id],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == (guidance,)


def test_rebinding_identifier_rejects_ambiguous_same_family_tool_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guidance = _REPEATED_INVOICE_GUIDANCE[0]
    ambiguous_tool = {
        "name": "invoice_lookup",
        "method": "GET",
        "status": "success",
        "responseFacts": [
            {
                "path": "invoice_ids",
                "value": "INV-11111 and INV-22222",
            },
            {"path": "invoice_status", "value": "open"},
            {"path": "due_date", "value": "2026-08-15"},
        ],
    }
    issue = _issue(
        *(
            _invoice_concern(
                concern_id,
                guidance=(guidance,),
                tool_evidence=[ambiguous_tool],
            )
            for concern_id in ("invoice-source", "invoice-target")
        )
    )
    answer = "Invoice INV-11111 is open and due 2026-08-15."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]
    source_evidence_id = "tool:invoice-source:invoice_lookup"

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                [source_evidence_id],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                [source_evidence_id],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == (guidance,)


def test_rebinding_identifier_accepts_exact_fixture_bound_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guidance = _REPEATED_INVOICE_GUIDANCE[0]
    issue = _issue(
        {
            **_invoice_concern(
                "invoice-source",
                guidance=(guidance,),
                tool_evidence=[_invoice_tool_evidence()],
            ),
            "sourceText": "Please check invoice INV-9012.",
            "replyRequirements": [
                "Never claim a selected action completed before exact success evidence exists.",
                "State the open invoice and due date.",
            ],
            "forbiddenClaims": ["That a credit has been issued."],
        },
        {
            **_invoice_concern(
                "invoice-target",
                guidance=(guidance,),
                tool_evidence=[_invoice_tool_evidence()],
            ),
            "replyRequirements": [
                "Never claim a selected action completed before exact success evidence exists.",
                "Keep profile update pending.",
            ],
        },
    )
    answer = "Invoice INV-9012 is open and due 2026-08-15."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]
    source_evidence_id = "tool:invoice-source:fixture_saas_invoice_inv_9012"

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                [source_evidence_id],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                [source_evidence_id],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is True
    assert result.status == "passed"
    assert result.uncovered_obligations == ()


def test_rebinding_policy_identity_preserves_currency_and_percent_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_guidance = "State that the discount is 10%."
    target_guidance = "State that the discount is $10."
    issue = _issue(
        _invoice_concern(
            "invoice-source",
            guidance=(source_guidance,),
            tool_evidence=[_invoice_tool_evidence()],
        ),
        _invoice_concern(
            "invoice-target",
            guidance=(target_guidance,),
            tool_evidence=[_invoice_tool_evidence()],
        ),
    )
    answer = "The discount is 10%."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                ["concern:invoice-source"],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                ["concern:invoice-source"],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == (target_guidance,)


def test_rebinding_requires_identical_complete_runbook_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guidance = _REPEATED_INVOICE_GUIDANCE[0]
    issue = _issue(
        _invoice_concern(
            "invoice-source",
            guidance=(guidance,),
            tool_evidence=[_invoice_tool_evidence()],
        ),
        {
            **_invoice_concern(
                "invoice-target",
                guidance=(guidance,),
                tool_evidence=[_invoice_tool_evidence()],
            ),
            "forbiddenClaims": ["Do not state that the invoice is open."],
        },
    )
    answer = "The invoice is open and due 2026-08-15."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]
    source_evidence_id = "tool:invoice-source:fixture_saas_invoice_inv_9012"

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:required-guidance-1",
                "answered",
                [unit_id],
                [source_evidence_id],
            ),
            (
                "invoice-target:required-guidance-1",
                "not_covered",
                [unit_id],
                [source_evidence_id],
            ),
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == (guidance,)


def test_duplicate_customer_question_is_never_rebound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question = "What is the current invoice status?"
    issue = _issue(
        {
            **_invoice_concern("invoice-source"),
            "answerObligations": [
                {"obligationId": "invoice-source:question", "question": question}
            ],
        },
        {
            **_invoice_concern("invoice-target"),
            "answerObligations": [
                {"obligationId": "invoice-target:question", "question": question}
            ],
        },
    )
    answer = "The invoice is open."
    unit_id = issue_agent._grounding_answer_units(answer)[0]["id"]

    result = _ground_with_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (
                "invoice-source:question",
                "answered",
                [unit_id],
                ["concern:invoice-source"],
            ),
            (
                "invoice-target:question",
                "not_covered",
                [unit_id],
                ["concern:invoice-source"],
            ),
            *[
                (
                    f"{concern_id}:required-guidance-{index}",
                    "answered",
                    [unit_id],
                    [f"concern:{concern_id}"],
                )
                for concern_id in ("invoice-source", "invoice-target")
                for index in range(1, len(_REPEATED_INVOICE_GUIDANCE) + 1)
            ],
        ],
        verdict="not_grounded",
    )

    assert result.verified is False
    assert result.uncovered_obligations == (question,)
