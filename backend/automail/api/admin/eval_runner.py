"""Background evaluation run execution."""

import logging
import uuid
from datetime import datetime, timezone

from automail.api.admin.eval_helpers import _escape
from automail.db.pocketbase.client import _first, _patch, store_llm_usage_events
from automail.evals.judge import run_judge
from automail.llm.usage import aggregate_usage_calls
from automail.models import Email
from automail.monitoring import RunRecorder
from automail.pipeline.drafts import ensure_draft_exists, get_draft_source

logger = logging.getLogger(__name__)


def _execute_eval_run(run_id: str, cases: list[dict], tenant_id: str, project_id: str) -> None:
    """Execute all eval cases in sequence (runs in background thread)."""
    from automail.api.attachments import parse_email_attachments
    from automail.pipeline import run_pipeline

    draft = get_draft_source(project_id, tenant_id=tenant_id)
    ensure_draft_exists(project_id, tenant_id=tenant_id)
    recorder = RunRecorder(
        tenant_id=tenant_id,
        project_id=project_id,
        source="eval",
        user_email="eval@mantly.io",
        input_data={"evalRunId": run_id, "caseCount": len(cases)},
    )
    scores: list[int] = []
    identity_scores: list[int] = []
    intent_scores: list[int] = []
    actions_scores: list[int] = []
    response_scores: list[int] = []
    token_usage_calls: list[dict] = []
    had_failure = False

    for case in cases:
        # Find the result record for this case
        result_rec = _first(
            "eval_results",
            f"eval_run='{_escape(run_id)}' && eval_case='{_escape(case['id'])}'",
        )
        if not result_rec:
            continue

        result_id = result_rec["id"]

        try:
            # Mark as running
            _patch(f"/api/collections/eval_results/records/{result_id}", {
                "status": "running",
            })

            # Build Email object
            email = Email(
                id=f"eval-{uuid.uuid4().hex[:12]}",
                subject=case.get("email_subject", ""),
                from_address=case.get("email_from", ""),
                body=case.get("email_body", ""),
                attachments=case.get("email_attachments") or [],
            )
            parsed_attachments = parse_email_attachments(email)

            # Run the pipeline against draft config
            pipeline_result = run_pipeline(
                email=email,
                parsed_attachments=parsed_attachments,
                creator="eval@mantly.io",
                tenant_id=tenant_id or None,
                project_id=project_id or None,
                config_source=draft,
            )

            # Serialize pipeline output
            pipeline_output = {
                "identityResult": pipeline_result.identity_result.model_dump(by_alias=True),
                "intentResult": pipeline_result.intent_result.model_dump(by_alias=True),
                "agentResponse": pipeline_result.agent_response.model_dump(by_alias=True),
                "phishingResult": pipeline_result.phishing_result.model_dump(by_alias=True),
                "promptInjectionResult": pipeline_result.prompt_injection_result.model_dump(by_alias=True),
                "tokenUsage": pipeline_result.token_usage,
            }

            # Build expected dict for the judge
            expected = {
                "expected_customer_found": case.get("expected_customer_found", False),
                "expected_customer_data": case.get("expected_customer_data", {}),
                "expected_intent_matched": case.get("expected_intent_matched", False),
                "expected_intent_name": case.get("expected_intent_name", ""),
                "expected_actions": case.get("expected_actions", []),
                "expected_requires_human": case.get("expected_requires_human", False),
                "expected_response": case.get("expected_response", ""),
            }

            # Determine if response scoring applies
            has_response = bool(
                case.get("expected_response")
                and pipeline_result.agent_response.response_text
            )

            # Run the LLM judge
            judge_result = run_judge(expected, pipeline_output, has_response,
                                      config_path=draft, tenant_id=tenant_id)
            case_token_calls = []
            if isinstance(pipeline_result.token_usage, dict):
                case_token_calls.extend(pipeline_result.token_usage.get("calls", []))
            if isinstance(judge_result.token_usage, dict):
                case_token_calls.extend(judge_result.token_usage.get("calls", []))
            token_usage_calls.extend(case_token_calls)
            try:
                store_llm_usage_events(
                    case_token_calls,
                    tenant_id=tenant_id or None,
                    project_id=project_id or None,
                    eval_run_id=run_id,
                    run_id=f"{run_id}:{case['id']}",
                )
            except Exception:
                logger.warning("Failed to store eval LLM usage events", exc_info=True)

            # Update result record with scores
            update_data: dict = {
                "status": "completed",
                "pipeline_output": pipeline_output,
                "identity_score": judge_result.identity.score,
                "identity_reasoning": judge_result.identity.reasoning,
                "intent_score": judge_result.intent.score,
                "intent_reasoning": judge_result.intent.reasoning,
                "actions_score": judge_result.actions.score,
                "actions_reasoning": judge_result.actions.reasoning,
                "overall_score": judge_result.overall,
            }
            if judge_result.response is not None:
                update_data["response_score"] = judge_result.response.score
                update_data["response_reasoning"] = judge_result.response.reasoning
                response_scores.append(judge_result.response.score)

            _patch(f"/api/collections/eval_results/records/{result_id}", update_data)

            scores.append(judge_result.overall)
            identity_scores.append(judge_result.identity.score)
            intent_scores.append(judge_result.intent.score)
            actions_scores.append(judge_result.actions.score)

            logger.info(
                "Eval case '%s' scored: overall=%d, identity=%d, intent=%d, actions=%d",
                case.get("name", case["id"]),
                judge_result.overall,
                judge_result.identity.score,
                judge_result.intent.score,
                judge_result.actions.score,
            )

        except Exception as exc:
            logger.error("Eval case '%s' failed: %s", case.get("name", ""), exc, exc_info=True)
            _patch(f"/api/collections/eval_results/records/{result_id}", {
                "status": "failed",
                "error": str(exc)[:500],
            })
            had_failure = True

    # Update run summary
    def _avg(lst: list[int]) -> float | None:
        return round(sum(lst) / len(lst), 1) if lst else None

    summary = {
        "overallScore": _avg(scores),
        "identityScore": _avg(identity_scores),
        "intentScore": _avg(intent_scores),
        "actionsScore": _avg(actions_scores),
        "responseScore": _avg(response_scores),
        "tokenUsage": aggregate_usage_calls(token_usage_calls),
        "totalCases": len(cases),
        "completedCases": len(scores),
        "failedCases": len(cases) - len(scores),
    }

    _patch(f"/api/collections/eval_runs/records/{run_id}", {
        "status": "failed" if had_failure and not scores else "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "token_usage": summary["tokenUsage"],
    })

    recorder.finish(
        status="failed" if had_failure and not scores else "success",
        output={"evalRunId": run_id, "summary": summary},
        error="One or more eval cases failed" if had_failure and not scores else "",
    )

    logger.info("Eval run %s complete: %s", run_id, summary)
