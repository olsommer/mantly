"""Controlled proposal, evaluation, and publish flow for intent learnings."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from automail.api.admin.deps import (
    ProjectAdminDep,
    ProjectEditorDep,
    ProjectViewerDep,
    _require_ctx_capability,
)
from automail.api.admin.eval_helpers import _escape, _get_eval_set_for_ctx
from automail.api.admin.eval_runner import _execute_eval_run
from automail.db.pocketbase.client import (
    _first,
    _list_all,
    _patch,
    _post,
    generate_id,
    get_chat,
    get_feedback_record,
    get_intent_learnings,
)
from automail.db.pocketbase.learning_proposals import (
    LEARNING_EVAL_POLICY_HASH,
    LEARNING_EVAL_SERVER_FLOOR,
    active_learning_set_hash,
    compute_learning_proposal_hash,
    create_learning_proposal,
    eval_case_selection_hash,
    get_learning_proposal,
    learning_eval_dimension,
    learning_proposal_evaluation_override,
    list_learning_proposals,
    patch_learning_proposal,
    publish_learning_proposal,
    serialize_learning_proposal,
)

logger = logging.getLogger(__name__)
router = APIRouter()

LEARNING_EVAL_TERMINAL_GRACE_SECONDS = 60
LEARNING_EVAL_STALE_SECONDS = 60 * 60


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _string_list(value: Any) -> list[str]:
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item)]


def _feedback_learnings_enabled(value: Any) -> bool:
    response = _json_object(value)
    configured = response.get("use_feedback_learnings", True)
    if isinstance(configured, bool):
        return configured
    return str(configured).strip().lower() not in {"false", "0", "no", "off"}


def _draft_runbook_for_proposal(name: str, ctx: Any) -> dict[str, Any]:
    filter_str = (
        f"project='{_escape(ctx.project_id)}' && mode='draft' "
        f"&& name='{_escape(name)}'"
    )
    if ctx.tenant_id:
        filter_str += f" && tenant='{_escape(ctx.tenant_id)}'"
    runbook = _first("project_intents", filter_str)
    if not runbook:
        raise HTTPException(status_code=404, detail="Draft runbook not found")
    if not _feedback_learnings_enabled(runbook.get("response")):
        raise HTTPException(
            status_code=409,
            detail="Feedback learnings are disabled for this runbook",
        )
    return runbook


def _assert_runbook_unchanged(proposal: dict[str, Any], name: str, ctx: Any) -> dict[str, Any]:
    runbook = _draft_runbook_for_proposal(name, ctx)
    if (
        str(runbook.get("id") or "") != str(proposal.get("runbook_id") or "")
        or str(runbook.get("updated") or "") != str(proposal.get("runbook_updated") or "")
    ):
        raise HTTPException(
            status_code=409,
            detail="Runbook changed after proposal creation; create a new proposal",
        )
    return runbook


def _target_eval_cases(cases: list[dict[str, Any]], intent_name: str) -> list[dict[str, Any]]:
    target = intent_name.strip().lower()
    return [
        case
        for case in cases
        if str(case.get("expected_intent_name") or "").strip().lower() == target
        and bool(case.get("expected_intent_matched"))
    ]


def _require_learning_feature(ctx: Any) -> None:
    from automail.billing.plans import require_feature

    require_feature(ctx.tenant_id, "feedback_learnings")


def _utc_timestamp(value: Any) -> datetime | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _reconcile_interrupted_proposal_eval(proposal: dict[str, Any]) -> dict[str, Any]:
    """Release evaluations orphaned by process restarts so admins can retry."""
    if str(proposal.get("status") or "") != "evaluating":
        return proposal
    now = datetime.now(timezone.utc)
    run_id = str(proposal.get("eval_run") or "")
    run = _first("eval_runs", f"id='{_escape(run_id)}'") if run_id else None
    run_status = str((run or {}).get("status") or "")
    proposal_updated = _utc_timestamp(proposal.get("updated"))
    terminal_at = _utc_timestamp((run or {}).get("completed_at"))
    terminal_orphaned = run_status in {"completed", "failed"} and bool(
        terminal_at
        and (now - terminal_at).total_seconds() >= LEARNING_EVAL_TERMINAL_GRACE_SECONDS
    )
    stale = bool(
        proposal_updated
        and (now - proposal_updated).total_seconds() >= LEARNING_EVAL_STALE_SECONDS
    )
    if not terminal_orphaned and not stale:
        return proposal

    reason = (
        "Evaluation worker stopped before proposal finalization; run the evaluation again"
        if terminal_orphaned
        else "Evaluation worker timed out or restarted; run the evaluation again"
    )
    if run_id and run_status not in {"completed", "failed"}:
        try:
            _patch(
                f"/api/collections/eval_runs/records/{run_id}",
                {
                    "status": "failed",
                    "completed_at": now.isoformat(),
                    "summary": {
                        "totalCases": 0,
                        "completedCases": 0,
                        "failedCases": 0,
                        "recoveredInterruptedRun": True,
                    },
                },
            )
        except Exception:
            logger.exception("Failed to close interrupted proposal eval run: %s", run_id)
    return patch_learning_proposal(
        str(proposal.get("id") or ""),
        {
            "status": "eval_failed",
            "error": reason,
            "evaluated_at": now.isoformat(),
        },
    )


def _proposal_for_ctx(proposal_id: str, name: str, ctx: Any) -> dict[str, Any]:
    proposal = get_learning_proposal(
        proposal_id,
        intent_name=name,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Learning proposal not found")
    return _reconcile_interrupted_proposal_eval(proposal)


def _proposal_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _eval_summary(
    run: dict[str, Any] | None,
    *,
    minimum_score: float,
    results: list[dict[str, Any]],
    selected_case_ids: list[str],
    dimension: str,
    case_hash: str,
) -> dict[str, Any]:
    raw = run.get("summary") if run else None
    summary = raw if isinstance(raw, dict) else {}
    total = int(summary.get("totalCases") or 0)
    completed = int(summary.get("completedCases") or 0)
    failed = int(summary.get("failedCases") or max(0, total - completed))
    overall_raw = summary.get("overallScore")
    overall = float(overall_raw) if isinstance(overall_raw, (int, float)) else None
    selected_set = set(selected_case_ids)
    selected_results = [
        result
        for result in results
        if str(result.get("eval_case") or "") in selected_set
    ]
    score_field = f"{dimension}_score"
    affected_scores = [
        float(result[score_field])
        for result in selected_results
        if isinstance(result.get(score_field), (int, float))
    ]
    coverage_passed = bool(
        selected_case_ids
        and len(selected_results) == len(selected_case_ids)
        and all(result.get("status") == "completed" for result in selected_results)
        and len(affected_scores) == len(selected_case_ids)
        and min(affected_scores, default=-1) >= minimum_score
    )
    passed = bool(
        run
        and run.get("status") == "completed"
        and total > 0
        and completed == total
        and failed == 0
        and overall is not None
        and overall >= minimum_score
        and coverage_passed
    )
    return {
        **summary,
        "passed": passed,
        "failed": failed,
        "total": total,
        "completed": completed,
        "overallScore": overall,
        "minimumScore": minimum_score,
        "affectedDimension": dimension,
        "affectedScore": min(affected_scores) if affected_scores else None,
        "affectedCoveragePassed": coverage_passed,
        "selectedCaseIds": selected_case_ids,
        "selectedCaseHash": case_hash,
        "policyHash": LEARNING_EVAL_POLICY_HASH,
    }


def _execute_proposal_eval(
    *,
    proposal: dict[str, Any],
    run_id: str,
    cases: list[dict[str, Any]],
    tenant_id: str,
    project_id: str,
    minimum_score: float,
    evaluated_by: str,
) -> None:
    proposal_id = str(proposal.get("id") or "")
    try:
        with learning_proposal_evaluation_override(proposal):
            _execute_eval_run(run_id, cases, tenant_id, project_id)

        run = _first("eval_runs", f"id='{_escape(run_id)}'")
        results = _list_all("eval_results", f"eval_run='{_escape(run_id)}'", sort="created")
        selected_case_ids = _string_list(proposal.get("eval_case_ids"))
        selected_id_set = set(selected_case_ids)
        current_cases = [
            case
            for case in _list_all(
                "eval_cases",
                f"eval_set='{_escape(str(proposal.get('eval_set') or ''))}'",
                sort="created",
            )
            if str(case.get("id") or "") in selected_id_set
        ]
        case_hash = eval_case_selection_hash(current_cases)
        dimension = str(proposal.get("eval_dimension") or "")
        summary = _eval_summary(
            run,
            minimum_score=minimum_score,
            results=results,
            selected_case_ids=selected_case_ids,
            dimension=dimension,
            case_hash=case_hash,
        )
        current = get_learning_proposal(
            proposal_id,
            intent_name=str(proposal.get("intent_name") or ""),
            tenant_id=tenant_id or None,
            project_id=project_id or None,
        )
        if not current or current.get("status") != "evaluating":
            return
        if str(current.get("eval_run") or "") != run_id:
            return

        expected_hash = str(proposal.get("proposal_hash") or "")
        integrity_ok = (
            compute_learning_proposal_hash(current) == expected_hash
            and str(current.get("proposal_hash") or "") == expected_hash
        )
        current_base_hash = active_learning_set_hash(
            intent_name=str(proposal.get("intent_name") or ""),
            tenant_id=tenant_id or None,
            project_id=project_id or None,
        )
        baseline_ok = current_base_hash == str(proposal.get("base_learning_hash") or "")
        case_evidence_ok = bool(
            str(proposal.get("eval_policy_hash") or "") == LEARNING_EVAL_POLICY_HASH
            and str(proposal.get("eval_case_hash") or "") == case_hash
            and len(current_cases) == len(selected_case_ids)
        )
        runbook = _first(
            "project_intents",
            f"id='{_escape(str(proposal.get('runbook_id') or ''))}'",
        )
        runbook_ok = bool(
            runbook
            and str(runbook.get("updated") or "") == str(proposal.get("runbook_updated") or "")
            and _feedback_learnings_enabled(runbook.get("response"))
        )
        passed = bool(
            summary["passed"]
            and integrity_ok
            and baseline_ok
            and case_evidence_ok
            and runbook_ok
        )
        if not integrity_ok:
            error = "Proposal changed while evaluation was running"
        elif not baseline_ok:
            error = "Active learnings changed while evaluation was running"
        elif not case_evidence_ok:
            error = "Selected eval cases or evaluation policy changed"
        elif not runbook_ok:
            error = "Runbook changed or feedback learnings were disabled"
        elif not summary["passed"]:
            error = "Evaluation failed, was incomplete, or scored below the minimum"
        else:
            error = ""
        patch_learning_proposal(
            proposal_id,
            {
                "status": "evaluated" if passed else "eval_failed",
                "eval_summary": summary,
                "evaluated_proposal_hash": expected_hash,
                "evaluated_base_hash": str(proposal.get("base_learning_hash") or ""),
                "evaluated_by": evaluated_by,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
                "error": error,
            },
        )
    except Exception as exc:
        logger.exception("Intent-learning proposal eval failed: %s", proposal_id)
        try:
            _patch(
                f"/api/collections/eval_runs/records/{run_id}",
                {
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "summary": {
                        "totalCases": len(cases),
                        "completedCases": 0,
                        "failedCases": len(cases),
                    },
                },
            )
        except Exception:
            logger.exception("Failed to mark proposal eval run failed: %s", run_id)
        try:
            current = get_learning_proposal(
                proposal_id,
                intent_name=str(proposal.get("intent_name") or ""),
                tenant_id=tenant_id or None,
                project_id=project_id or None,
            )
            if current and current.get("status") == "evaluating":
                patch_learning_proposal(
                    proposal_id,
                    {
                        "status": "eval_failed",
                        "error": str(exc)[:500],
                        "evaluated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
        except Exception:
            logger.exception("Failed to mark learning proposal eval failed: %s", proposal_id)


@router.get("/projects/{pid}/intents/{name}/learning-proposals")
async def list_proposals(name: str, ctx: ProjectViewerDep) -> list[dict[str, Any]]:
    _require_learning_feature(ctx)
    return [
        serialize_learning_proposal(_reconcile_interrupted_proposal_eval(proposal))
        for proposal in list_learning_proposals(
            intent_name=name,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        )
    ]


@router.get("/projects/{pid}/intents/{name}/learning-proposals/{proposal_id}")
async def get_proposal(
    name: str,
    proposal_id: str,
    ctx: ProjectViewerDep,
) -> dict[str, Any]:
    _require_learning_feature(ctx)
    return serialize_learning_proposal(_proposal_for_ctx(proposal_id, name, ctx))


@router.post("/projects/{pid}/intents/{name}/learning-proposals")
async def propose_learning_change(
    name: str,
    body: dict[str, Any],
    ctx: ProjectEditorDep,
) -> dict[str, Any]:
    _require_ctx_capability(ctx, "canEditIntents")
    _require_learning_feature(ctx)
    runbook = _draft_runbook_for_proposal(name, ctx)
    source_feedback_id = str(body.get("sourceFeedbackId") or body.get("source_feedback_id") or "").strip()
    if source_feedback_id and not get_feedback_record(
        source_feedback_id,
        intent_name=name,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    ):
        raise HTTPException(status_code=404, detail="Feedback not found")
    affected_stages = body.get("affectedStages", body.get("affected_stages"))
    if affected_stages is not None and not isinstance(affected_stages, list):
        raise HTTPException(status_code=422, detail="affectedStages must be an array")
    try:
        proposal = create_learning_proposal(
            intent_name=name,
            operation=str(body.get("operation") or ""),
            proposed_learning=str(body.get("proposedLearning") or body.get("proposed_learning") or ""),
            target_learning_id=str(body.get("targetLearningId") or body.get("target_learning_id") or ""),
            source_feedback_id=source_feedback_id,
            affected_stages=affected_stages,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            created_by=ctx.user_id,
            runbook_id=str(runbook.get("id") or ""),
            runbook_updated=str(runbook.get("updated") or ""),
        )
    except (LookupError, ValueError) as exc:
        raise _proposal_error(exc) from exc
    return serialize_learning_proposal(proposal)


@router.post("/projects/{pid}/intents/{name}/feedback/{feedback_id}/learning-proposals")
async def propose_learning_from_feedback(
    name: str,
    feedback_id: str,
    body: dict[str, Any],
    ctx: ProjectEditorDep,
) -> dict[str, Any]:
    """Explicit Learn this action. Reflection creates inert proposals only."""
    _require_ctx_capability(ctx, "canEditIntents")
    _require_learning_feature(ctx)
    runbook = _draft_runbook_for_proposal(name, ctx)
    feedback = get_feedback_record(
        feedback_id,
        intent_name=name,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    existing = [
        proposal
        for proposal in list_learning_proposals(
            intent_name=name,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        )
        if str(proposal.get("source_feedback_id") or "") == feedback_id
        and str(proposal.get("status") or "") not in {"published", "rejected"}
    ]
    if existing:
        return {"proposals": [serialize_learning_proposal(item) for item in existing]}

    feedback_text = str(feedback.get("feedback_text") or "").strip()
    if feedback.get("rating") != "dislike" or not feedback_text:
        raise HTTPException(
            status_code=422,
            detail="Learn this requires dislike feedback with written evidence",
        )
    affected_stages = feedback.get("affected_stages") or []
    affected_stage = str(affected_stages[0]).strip() if affected_stages else ""
    explicit_learning = str(body.get("learning") or "").strip()
    learnings = [explicit_learning] if explicit_learning else []
    if not learnings:
        chat_id = str(feedback.get("chat_id") or "")
        chat = get_chat(
            chat_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        )
        if not chat:
            raise HTTPException(status_code=422, detail="Feedback chat evidence is unavailable")
        from automail.feedback.context import feedback_message_context
        from automail.feedback.reflect_agent import run_reflect_agent

        original_email, pipeline_result = feedback_message_context(chat)
        if not original_email and not pipeline_result:
            raise HTTPException(status_code=422, detail="Feedback context is unavailable")
        current_learnings = get_intent_learnings(
            name,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            stage_filter=[affected_stage] if affected_stage else None,
        )
        try:
            learnings = await asyncio.wait_for(
                asyncio.to_thread(
                    run_reflect_agent,
                    feedback_text=feedback_text,
                    original_email=original_email,
                    pipeline_result=pipeline_result,
                    current_learnings=list(current_learnings),
                    tenant_id=ctx.tenant_id,
                    affected_stage=affected_stage,
                ),
                timeout=90,
            )
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="Learning reflection timed out") from exc
    if not learnings:
        raise HTTPException(status_code=422, detail="Feedback produced no actionable learning")

    proposals = [
        create_learning_proposal(
            intent_name=name,
            operation="create",
            proposed_learning=learning,
            source_feedback_id=feedback_id,
            affected_stages=affected_stages,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            created_by=ctx.user_id,
            runbook_id=str(runbook.get("id") or ""),
            runbook_updated=str(runbook.get("updated") or ""),
        )
        for learning in learnings
    ]
    return {"proposals": [serialize_learning_proposal(item) for item in proposals]}


@router.post("/projects/{pid}/intents/{name}/learning-proposals/{proposal_id}/evaluate")
async def evaluate_proposal(
    name: str,
    proposal_id: str,
    body: dict[str, Any],
    ctx: ProjectEditorDep,
) -> dict[str, Any]:
    _require_ctx_capability(ctx, "canEditIntents")
    _require_learning_feature(ctx)
    proposal = _proposal_for_ctx(proposal_id, name, ctx)
    _assert_runbook_unchanged(proposal, name, ctx)
    if proposal.get("status") in {"evaluating", "published", "rejected"}:
        raise HTTPException(status_code=409, detail="Proposal cannot be evaluated in its current state")
    proposal_hash = compute_learning_proposal_hash(proposal)
    if proposal_hash != str(proposal.get("proposal_hash") or ""):
        raise HTTPException(status_code=409, detail="Proposal integrity check failed")
    current_base_hash = active_learning_set_hash(
        intent_name=name,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if current_base_hash != str(proposal.get("base_learning_hash") or ""):
        raise HTTPException(
            status_code=409,
            detail="Active learnings changed; create a new proposal",
        )
    try:
        eval_dimension = learning_eval_dimension(proposal.get("affected_stages"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    eval_set_id = str(body.get("evalSetId") or body.get("eval_set_id") or "").strip()
    if not eval_set_id:
        raise HTTPException(status_code=422, detail="evalSetId is required")
    raw_minimum = body.get(
        "minimumScore",
        body.get("minimum_score", LEARNING_EVAL_SERVER_FLOOR),
    )
    try:
        minimum_score = float(raw_minimum)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="minimumScore must be numeric") from exc
    if minimum_score < 0 or minimum_score > 100:
        raise HTTPException(status_code=422, detail="minimumScore must be between 0 and 100")
    if minimum_score < LEARNING_EVAL_SERVER_FLOOR:
        raise HTTPException(
            status_code=422,
            detail=f"minimumScore cannot be below {int(LEARNING_EVAL_SERVER_FLOOR)}",
        )

    from automail.billing.usage import check_limit

    if ctx.tenant_id:
        check_limit(ctx.tenant_id, "eval_runs_per_month")
    _get_eval_set_for_ctx(eval_set_id, ctx)
    cases = _list_all("eval_cases", f"eval_set='{_escape(eval_set_id)}'", sort="created")
    if not cases:
        raise HTTPException(status_code=400, detail="Eval set has no cases")
    target_cases = _target_eval_cases(cases, name)
    if not target_cases:
        raise HTTPException(
            status_code=422,
            detail="Eval set has no cases targeting this runbook",
        )
    if eval_dimension == "response" and not all(
        str(case.get("expected_response") or "").strip()
        for case in target_cases
    ):
        raise HTTPException(
            status_code=422,
            detail="Every target runbook case needs an expected response",
        )
    selected_case_ids = sorted(str(case["id"]) for case in target_cases)
    selected_case_hash = eval_case_selection_hash(target_cases)

    run_data: dict[str, Any] = {
        "id": generate_id(),
        "eval_set": eval_set_id,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "project": ctx.project_id,
    }
    if ctx.tenant_id:
        run_data["tenant"] = ctx.tenant_id
    run = _post("/api/collections/eval_runs/records", run_data)
    run_id = str(run["id"])
    for case in cases:
        _post(
            "/api/collections/eval_results/records",
            {
                "id": generate_id(),
                "eval_run": run_id,
                "eval_case": case["id"],
                "status": "pending",
            },
        )

    evaluating = patch_learning_proposal(
        proposal_id,
        {
            "status": "evaluating",
            "eval_set": eval_set_id,
            "eval_run": run_id,
            "eval_summary": {},
            "eval_case_ids": selected_case_ids,
            "eval_case_hash": selected_case_hash,
            "eval_policy_hash": LEARNING_EVAL_POLICY_HASH,
            "eval_dimension": eval_dimension,
            "minimum_score": minimum_score,
            "evaluated_by": ctx.user_id,
            "evaluated_at": "",
            "evaluated_proposal_hash": "",
            "evaluated_base_hash": "",
            "error": "",
        },
    )
    thread = threading.Thread(
        target=_execute_proposal_eval,
        kwargs={
            "proposal": {**proposal, **evaluating},
            "run_id": run_id,
            "cases": cases,
            "tenant_id": ctx.tenant_id,
            "project_id": ctx.project_id,
            "minimum_score": minimum_score,
            "evaluated_by": ctx.user_id,
        },
        daemon=True,
    )
    thread.start()
    return serialize_learning_proposal(evaluating)


@router.post("/projects/{pid}/intents/{name}/learning-proposals/{proposal_id}/publish")
async def publish_proposal(
    name: str,
    proposal_id: str,
    ctx: ProjectAdminDep,
) -> dict[str, Any]:
    _require_ctx_capability(ctx, "canEditIntents")
    _require_learning_feature(ctx)
    proposal = _proposal_for_ctx(proposal_id, name, ctx)
    _assert_runbook_unchanged(proposal, name, ctx)
    run_id = str(proposal.get("eval_run") or "")
    run = _first(
        "eval_runs",
        f"id='{_escape(run_id)}' && project='{_escape(ctx.project_id)}'",
    ) if run_id else None
    minimum_score = float(proposal.get("minimum_score") or 0)
    if minimum_score < LEARNING_EVAL_SERVER_FLOOR:
        raise HTTPException(status_code=409, detail="Evaluation threshold is below server policy")
    if str(proposal.get("eval_policy_hash") or "") != LEARNING_EVAL_POLICY_HASH:
        raise HTTPException(status_code=409, detail="Evaluation policy changed")
    selected_case_ids = _string_list(proposal.get("eval_case_ids"))
    selected_set = set(selected_case_ids)
    current_cases = [
        case
        for case in _list_all(
            "eval_cases",
            f"eval_set='{_escape(str(proposal.get('eval_set') or ''))}'",
            sort="created",
        )
        if str(case.get("id") or "") in selected_set
    ]
    if (
        len(current_cases) != len(selected_case_ids)
        or eval_case_selection_hash(current_cases) != str(proposal.get("eval_case_hash") or "")
        or sorted(str(case["id"]) for case in _target_eval_cases(current_cases, name))
        != selected_case_ids
    ):
        raise HTTPException(status_code=409, detail="Selected eval cases changed")
    results = _list_all("eval_results", f"eval_run='{_escape(run_id)}'", sort="created")
    authoritative_summary = _eval_summary(
        run,
        minimum_score=minimum_score,
        results=results,
        selected_case_ids=selected_case_ids,
        dimension=str(proposal.get("eval_dimension") or ""),
        case_hash=str(proposal.get("eval_case_hash") or ""),
    )
    if authoritative_summary != proposal.get("eval_summary"):
        raise HTTPException(status_code=409, detail="Evaluation evidence changed or is unavailable")
    try:
        published = publish_learning_proposal(proposal, published_by=ctx.user_id)
    except httpx.HTTPStatusError as exc:
        detail = "Learning publish transaction rejected"
        try:
            payload = exc.response.json()
            detail = str(payload.get("message") or payload.get("detail") or detail)
        except Exception:
            pass
        raise HTTPException(status_code=409, detail=detail) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_learning_proposal(published)


@router.post("/projects/{pid}/intents/{name}/learning-proposals/{proposal_id}/reject")
async def reject_proposal(
    name: str,
    proposal_id: str,
    body: dict[str, Any],
    ctx: ProjectAdminDep,
) -> dict[str, Any]:
    _require_ctx_capability(ctx, "canEditIntents")
    _require_learning_feature(ctx)
    proposal = _proposal_for_ctx(proposal_id, name, ctx)
    if proposal.get("status") in {"published", "rejected"}:
        raise HTTPException(status_code=409, detail="Proposal is already terminal")
    rejected = patch_learning_proposal(
        proposal_id,
        {
            "status": "rejected",
            "rejection_reason": str(body.get("reason") or "").strip(),
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "rejected_by": ctx.user_id,
        },
    )
    return serialize_learning_proposal(rejected)
