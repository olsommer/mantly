"""Evaluation API router.

Provides CRUD for eval sets, cases, runs, and results — all scoped per-project.
Also exposes a run-trigger endpoint that executes the pipeline + LLM judge
in a background thread.
"""
import asyncio
import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from automail.api.admin.deps import ProjectEditorDep, ProjectViewerDep
from automail.api.admin.eval_helpers import (
    _demo_root,
    _escape,
    _get_eval_case_for_ctx,
    _get_eval_run_for_ctx,
    _get_eval_set_for_ctx,
    mark_orphaned_eval_runs_failed,
)
from automail.api.admin.eval_models import EvalCaseCreate, EvalCaseUpdate, EvalSetCreate, EvalSetUpdate
from automail.api.admin.eval_runner import _execute_eval_run
from automail.db.pocketbase.client import (
    _delete,
    _first,
    _list_all,
    _patch,
    _post,
    generate_id,
)
from automail.demo.e2e_fixtures import e2e_fixture_runtime_enabled
from automail.evals.judge import run_judge
from automail.pipeline.drafts import get_draft_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/projects/{pid}/eval")

__all__ = ["_demo_root", "mark_orphaned_eval_runs_failed", "router"]

_E2E_RESPONSE_JUDGE_TIMEOUT_SECONDS = 60
# ``langchain-google-genai`` forwards this value as total attempts and the
# underlying Google client treats ``0`` as its default of five attempts.
# One therefore means one bounded request with no provider retry for the live
# fixture judge. (The normal eval runner keeps its existing defaults.)
_E2E_RESPONSE_JUDGE_MAX_RETRIES = 1


class E2EResponseJudgeInput(BaseModel):
    response_text: str = Field(min_length=1, max_length=50_000)
    must_cover: list[str] = Field(min_length=1, max_length=30)
    must_not_claim: list[str] = Field(default_factory=list, max_length=30)
    must_mark_unverified: list[str] = Field(default_factory=list, max_length=30)


@router.post("/e2e-response-judge")
async def judge_e2e_response(
    body: E2EResponseJudgeInput,
    ctx: ProjectEditorDep,
) -> dict:
    """Semantically grade one synthetic response while the E2E runtime is enabled."""
    if not e2e_fixture_runtime_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    expected_response = "\n".join(
        [
            "The text below is a grading rubric, not content that the customer "
            "response must repeat. Apply each item as a semantic constraint to "
            "the actual response. A MUST NOT CLAIM item is violated only when the "
            "response asserts the prohibited proposition as true. Mentioning it "
            "to explicitly deny it, say it is unconfirmed, ask about it, or "
            "attribute it to the customer does not violate the constraint.",
            "The response must satisfy every MUST COVER item, must not make any "
            "MUST NOT CLAIM statement, and must explicitly describe every MUST MARK "
            "UNVERIFIED item as unknown, pending, unavailable, or requiring approval. "
            "A prohibited claim or omitted required item is a material error and must "
            "score below 90.",
            "MUST COVER:",
            *(f"- {item}" for item in body.must_cover),
            "MUST NOT CLAIM:",
            *(f"- {item}" for item in body.must_not_claim),
            "MUST EXPLICITLY MARK UNVERIFIED OR PENDING:",
            *(f"- {item}" for item in body.must_mark_unverified),
        ]
    )
    expected = {
        # Keep the generic pipeline judge's identity and routing dimensions
        # neutral. This endpoint grades response text only; marking the intent
        # unmatched can make the judge reject a correct, grounded answer for
        # having answered at all.
        "expected_customer_found": True,
        "expected_customer_data": {},
        "expected_intent_matched": True,
        "expected_intent_name": "e2e-response-rubric",
        "expected_actions": [],
        "expected_requires_human": True,
        "expected_response": expected_response,
    }
    actual = {
        "identityResult": {"found": True},
        "intentResult": {
            "matched": True,
            "intentName": "e2e-response-rubric",
            "actions": [],
        },
        "agentResponse": {
            "responseText": body.response_text,
            "requiresHuman": True,
        },
    }
    config_source = get_draft_source(ctx.project_id, tenant_id=ctx.tenant_id)
    result = await asyncio.to_thread(
        run_judge,
        expected,
        actual,
        True,
        config_path=config_source,
        tenant_id=ctx.tenant_id or None,
        timeout=_E2E_RESPONSE_JUDGE_TIMEOUT_SECONDS,
        max_retries=_E2E_RESPONSE_JUDGE_MAX_RETRIES,
    )
    if result.response is None:
        raise HTTPException(status_code=502, detail="Response judge returned no response score")
    return {
        "passed": result.response.score >= 90,
        "score": result.response.score,
        "reasoning": result.response.reasoning,
        "threshold": 90,
        "tokenUsage": result.token_usage or {},
    }


# ── Helpers ────────────────────────────────────────────────────────────────────


def _eval_set_response(eval_set: dict) -> dict:
    set_id = eval_set["id"]
    cases = _list_all("eval_cases", f"eval_set='{_escape(set_id)}'")
    last_run = _first("eval_runs", f"eval_set='{_escape(set_id)}' && status='completed'")
    return {
        "id": set_id,
        "name": eval_set.get("name", ""),
        "description": eval_set.get("description", ""),
        "caseCount": len(cases),
        "lastRunScore": last_run.get("summary", {}).get("overallScore") if last_run else None,
        "lastRunAt": last_run.get("completed_at") if last_run else None,
        "created": eval_set.get("created", ""),
    }


# ── Eval Sets CRUD ─────────────────────────────────────────────────────────────

@router.get("/sets")
async def list_eval_sets(ctx: ProjectViewerDep) -> list[dict]:
    """List all eval sets for the project, with case counts and last run info."""
    filter_str = f"project='{_escape(ctx.project_id)}'"
    if ctx.tenant_id:
        filter_str += f" && tenant='{_escape(ctx.tenant_id)}'"
    sets = _list_all("eval_sets", filter_str, sort="-created")

    result = []
    for s in sets:
        result.append(_eval_set_response(s))
    return result


@router.get("/sets/{set_id}")
async def get_eval_set(set_id: str, ctx: ProjectViewerDep) -> dict:
    """Get one eval set for direct-linked pages."""
    return _eval_set_response(_get_eval_set_for_ctx(set_id, ctx))


@router.post("/sets")
async def create_eval_set(body: EvalSetCreate, ctx: ProjectEditorDep) -> dict:
    """Create a new eval set."""
    if ctx.tenant_id:
        from automail.billing.usage import check_limit
        check_limit(ctx.tenant_id, "eval_sets")

    data: dict = {"id": generate_id(), "name": body.name, "description": body.description}
    if ctx.tenant_id:
        data["tenant"] = ctx.tenant_id
    data["project"] = ctx.project_id
    rec = _post("/api/collections/eval_sets/records", data)
    return {"id": rec["id"], "name": rec.get("name", "")}


@router.put("/sets/{set_id}")
async def update_eval_set(set_id: str, body: EvalSetUpdate, ctx: ProjectEditorDep) -> dict:
    """Update an eval set's name or description."""
    _get_eval_set_for_ctx(set_id, ctx)
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if not updates:
        raise HTTPException(400, "No fields to update")
    _patch(f"/api/collections/eval_sets/records/{set_id}", updates)
    return {"status": "ok"}


@router.delete("/sets/{set_id}")
async def delete_eval_set(set_id: str, ctx: ProjectEditorDep) -> dict:
    """Delete an eval set and all its cases, runs, and results."""
    _get_eval_set_for_ctx(set_id, ctx)
    # Delete results for all runs of this set
    runs = _list_all("eval_runs", f"eval_set='{_escape(set_id)}'")
    for run in runs:
        results = _list_all("eval_results", f"eval_run='{_escape(run['id'])}'")
        for r in results:
            _delete(f"/api/collections/eval_results/records/{r['id']}")
        _delete(f"/api/collections/eval_runs/records/{run['id']}")

    # Delete cases
    cases = _list_all("eval_cases", f"eval_set='{_escape(set_id)}'")
    for c in cases:
        _delete(f"/api/collections/eval_cases/records/{c['id']}")

    # Delete the set itself
    _delete(f"/api/collections/eval_sets/records/{set_id}")
    return {"status": "deleted"}


# ── Eval Cases CRUD ────────────────────────────────────────────────────────────

@router.get("/sets/{set_id}/cases")
async def list_eval_cases(set_id: str, ctx: ProjectViewerDep) -> list[dict]:
    """List all cases in an eval set."""
    _get_eval_set_for_ctx(set_id, ctx)
    cases = _list_all("eval_cases", f"eval_set='{_escape(set_id)}'", sort="created")
    return [
        {
            "id": c["id"],
            "name": c.get("name", ""),
            "emailSubject": c.get("email_subject", ""),
            "emailFrom": c.get("email_from", ""),
            "emailBody": c.get("email_body", ""),
            "emailAttachments": c.get("email_attachments"),
            "expectedCustomerFound": c.get("expected_customer_found", False),
            "expectedCustomerData": c.get("expected_customer_data"),
            "expectedIntentMatched": c.get("expected_intent_matched", False),
            "expectedIntentName": c.get("expected_intent_name", ""),
            "expectedActions": c.get("expected_actions"),
            "expectedRequiresHuman": c.get("expected_requires_human", False),
            "expectedResponse": c.get("expected_response", ""),
            "created": c.get("created", ""),
        }
        for c in cases
    ]


@router.post("/sets/{set_id}/cases")
async def create_eval_case(set_id: str, body: EvalCaseCreate, ctx: ProjectEditorDep) -> dict:
    """Create a new eval case in a set."""
    _get_eval_set_for_ctx(set_id, ctx)
    if ctx.tenant_id:
        from automail.billing.usage import check_eval_cases_limit
        check_eval_cases_limit(ctx.tenant_id, set_id)

    data: dict = {
        "id": generate_id(),
        "eval_set": set_id,
        "name": body.name,
        "email_subject": body.email_subject,
        "email_from": body.email_from,
        "email_body": body.email_body,
        "email_attachments": body.email_attachments or [],
        "expected_customer_found": body.expected_customer_found,
        "expected_customer_data": body.expected_customer_data or {},
        "expected_intent_matched": body.expected_intent_matched,
        "expected_intent_name": body.expected_intent_name,
        "expected_actions": body.expected_actions or [],
        "expected_requires_human": body.expected_requires_human,
        "expected_response": body.expected_response,
    }
    rec = _post("/api/collections/eval_cases/records", data)
    return {"id": rec["id"], "name": rec.get("name", "")}


@router.put("/cases/{case_id}")
async def update_eval_case(case_id: str, body: EvalCaseUpdate, ctx: ProjectEditorDep) -> dict:
    """Update an eval case."""
    _get_eval_case_for_ctx(case_id, ctx)
    updates: dict = {}
    for field in [
        "name", "email_subject", "email_from", "email_body",
        "email_attachments", "expected_customer_found", "expected_customer_data",
        "expected_intent_matched", "expected_intent_name", "expected_actions",
        "expected_requires_human", "expected_response",
    ]:
        value = getattr(body, field)
        if value is not None:
            updates[field] = value
    if not updates:
        raise HTTPException(400, "No fields to update")
    _patch(f"/api/collections/eval_cases/records/{case_id}", updates)
    return {"status": "ok"}


@router.delete("/cases/{case_id}")
async def delete_eval_case(case_id: str, ctx: ProjectEditorDep) -> dict:
    """Delete an eval case."""
    _get_eval_case_for_ctx(case_id, ctx)
    _delete(f"/api/collections/eval_cases/records/{case_id}")
    return {"status": "deleted"}


# ── Eval Runs ──────────────────────────────────────────────────────────────────

@router.get("/runs")
async def list_eval_runs(set_id: str, ctx: ProjectViewerDep) -> list[dict]:
    """List all runs for a specific eval set."""
    _get_eval_set_for_ctx(set_id, ctx)
    runs = _list_all("eval_runs", f"eval_set='{_escape(set_id)}'", sort="-created")
    return [
        {
            "id": r["id"],
            "status": r.get("status", ""),
            "startedAt": r.get("started_at"),
            "completedAt": r.get("completed_at"),
            "summary": r.get("summary"),
            "created": r.get("created", ""),
        }
        for r in runs
    ]


@router.get("/runs/{run_id}")
async def get_eval_run(run_id: str, ctx: ProjectViewerDep) -> dict:
    """Get a run with all its results."""
    run = _get_eval_run_for_ctx(run_id, ctx)
    results = _list_all("eval_results", f"eval_run='{_escape(run_id)}'", sort="created")
    return {
        "id": run["id"],
        "evalSet": run.get("eval_set", ""),
        "status": run.get("status", ""),
        "startedAt": run.get("started_at"),
        "completedAt": run.get("completed_at"),
        "summary": run.get("summary"),
        "results": [
            {
                "id": r["id"],
                "evalCase": r.get("eval_case", ""),
                "status": r.get("status", ""),
                "pipelineOutput": r.get("pipeline_output"),
                "identityScore": r.get("identity_score"),
                "identityReasoning": r.get("identity_reasoning", ""),
                "intentScore": r.get("intent_score"),
                "intentReasoning": r.get("intent_reasoning", ""),
                "actionsScore": r.get("actions_score"),
                "actionsReasoning": r.get("actions_reasoning", ""),
                "responseScore": r.get("response_score"),
                "responseReasoning": r.get("response_reasoning", ""),
                "overallScore": r.get("overall_score"),
                "error": r.get("error", ""),
            }
            for r in results
        ],
    }


@router.delete("/runs/{run_id}")
async def delete_eval_run(run_id: str, ctx: ProjectEditorDep) -> dict:
    """Delete a run and all its results."""
    _get_eval_run_for_ctx(run_id, ctx)
    results = _list_all("eval_results", f"eval_run='{_escape(run_id)}'")
    for r in results:
        _delete(f"/api/collections/eval_results/records/{r['id']}")
    _delete(f"/api/collections/eval_runs/records/{run_id}")
    return {"status": "deleted"}


# ── Run Trigger ────────────────────────────────────────────────────────────────

@router.post("/sets/{set_id}/run")
async def trigger_eval_run(set_id: str, ctx: ProjectEditorDep) -> dict:
    """Trigger a new evaluation run in the background.

    Returns immediately with the run ID. Poll GET /runs/{run_id} for status.
    """
    # Enforce plan limits (SaaS only)
    from automail.billing.usage import check_limit
    if ctx.tenant_id:
        check_limit(ctx.tenant_id, "eval_runs_per_month")

    # Verify the set exists and has cases
    _get_eval_set_for_ctx(set_id, ctx)
    cases = _list_all("eval_cases", f"eval_set='{_escape(set_id)}'", sort="created")
    if not cases:
        raise HTTPException(400, "Eval set has no cases")

    # Create the run record
    run_data: dict = {
        "id": generate_id(),
        "eval_set": set_id,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    if ctx.tenant_id:
        run_data["tenant"] = ctx.tenant_id
    run_data["project"] = ctx.project_id
    run_rec = _post("/api/collections/eval_runs/records", run_data)
    run_id = run_rec["id"]

    # Create pending result records for each case
    for case in cases:
        _post("/api/collections/eval_results/records", {
            "id": generate_id(),
            "eval_run": run_id,
            "eval_case": case["id"],
            "status": "pending",
        })

    # Launch background thread
    thread = threading.Thread(
        target=_execute_eval_run,
        args=(run_id, cases, ctx.tenant_id, ctx.project_id),
        daemon=True,
    )
    thread.start()

    return {"runId": run_id, "status": "running"}
