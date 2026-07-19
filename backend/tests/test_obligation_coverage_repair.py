from contextlib import nullcontext
from typing import Any

from automail import llm as llm_module
from automail.core import config as config_module
from automail.llm import usage as usage_module
from automail.support import issue_agent
from automail.support.issue_agent import AutomationAnswerOutput


def test_automation_composer_receives_focused_obligation_repair_context(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeAutomationAgent:
        def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            captured.update(inputs=inputs, config=config)
            return {
                "structured_response": AutomationAnswerOutput(
                    answer=(
                        "Current evidence does not establish the exact cause. "
                        "Credit approval remains pending review."
                    ),
                    confidence="medium",
                )
            }

    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: FakeAutomationAgent(),
    )

    result = issue_agent.draft_issue_automation_answer(
        issue={"id": "issue-1", "subject": "Billing mismatch"},
        messages=[
            {
                "direction": "customer",
                "body": "Explain the mismatch and credit the difference.",
            }
        ],
        question="Prepare the customer answer.",
        articles=[],
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="Human review required.",
        fallback_confidence="low",
        coverage_repair_answer="The invoice and subscription counts differ.",
        coverage_repair_obligations=(
            "Explain the exact mismatch cause.",
            "Credit the difference.",
        ),
    )

    prompt = captured["inputs"]["messages"][0]["content"]
    assert "Required answer-obligation repair" in prompt
    assert "The invoice and subscription counts differ." in prompt
    assert "Explain the exact mismatch cause." in prompt
    assert "Credit the difference." in prompt
    assert "not established by current" in prompt
    assert "pending approval or review" in prompt
    assert result.generation_mode == "llm"
    assert "exact cause" in result.answer


def test_automation_composer_receives_exact_factual_grounding_repair_context(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeAutomationAgent:
        def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            captured.update(inputs=inputs, config=config)
            return {
                "structured_response": AutomationAnswerOutput(
                    answer=(
                        "Authentication is affected in the EU region. "
                        "The incident began at 2026-07-19T07:40:00Z."
                    ),
                    confidence="high",
                )
            }

    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: FakeAutomationAgent(),
    )

    previous_answer = "The affected service is authentication in the EU region 40 00Z."
    unsupported = (previous_answer,)
    contradictions = (
        "The answer merges region EU with started_at 2026-07-19T07:40:00Z.",
    )
    result = issue_agent.draft_issue_automation_answer(
        issue={"id": "issue-1", "subject": "Authentication incident"},
        messages=[
            {
                "direction": "customer",
                "body": "Which service and region are affected, and when did it start?",
            }
        ],
        question="Prepare the customer answer.",
        articles=[],
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="Human review required.",
        fallback_confidence="low",
        coverage_repair_answer=previous_answer,
        grounding_repair_unsupported_claims=unsupported,
        grounding_repair_contradictions=contradictions,
    )

    prompt = captured["inputs"]["messages"][0]["content"]
    assert "Required factual-grounding repair" in prompt
    assert previous_answer in prompt
    assert unsupported[0] in prompt
    assert contradictions[0] in prompt
    assert "only trusted evidence" in prompt
    assert "Keep separate evidence fields separate" in prompt
    assert "Grounding feedback identifies" in prompt
    assert "it is not new evidence" in prompt
    assert result.generation_mode == "llm"
    assert result.answer.endswith("2026-07-19T07:40:00Z.")
