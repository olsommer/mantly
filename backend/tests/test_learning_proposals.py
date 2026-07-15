import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from automail.core.auth import ProjectContext


def _proposal(**overrides):
    from automail.db.pocketbase.learning_proposals import compute_learning_proposal_hash

    proposal = {
        "id": "proposal-1",
        "intent_name": "returns",
        "operation": "create",
        "status": "evaluated",
        "proposed_learning": "Ask for the order number first.",
        "before_learning": "",
        "target_learning_id": "",
        "source_feedback_id": "feedback-1",
        "affected_stages": ["response_text"],
        "base_learning_hash": "base-hash",
        "tenant": "tenant-a",
        "project": "project-a",
        "runbook_id": "runbook-1",
        "runbook_updated": "2030-01-01 00:00:00.000Z",
        "eval_run": "run-1",
        "evaluated_base_hash": "base-hash",
    }
    proposal.update(overrides)
    proposal["proposal_hash"] = compute_learning_proposal_hash(proposal)
    proposal["evaluated_proposal_hash"] = proposal["proposal_hash"]
    return proposal


def test_eval_policy_hash_is_bound_to_canonical_policy():
    from automail.db.pocketbase.learning_proposals import (
        LEARNING_EVAL_POLICY,
        LEARNING_EVAL_POLICY_HASH,
    )

    encoded = json.dumps(
        LEARNING_EVAL_POLICY,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert hashlib.sha256(encoded).hexdigest() == LEARNING_EVAL_POLICY_HASH


def test_candidate_override_is_context_and_scope_local():
    from automail.db.pocketbase.learning_proposals import (
        apply_learning_proposal_evaluation_override,
        learning_proposal_evaluation_override,
    )

    records = [{"id": "active-1", "learning": "Old", "affected_stages": ["response_text"]}]
    proposal = _proposal(status="evaluating")
    with learning_proposal_evaluation_override(proposal):
        selected = apply_learning_proposal_evaluation_override(
            records,
            intent_name="returns",
            tenant_id="tenant-a",
            project_id="project-a",
        )
        other_project = apply_learning_proposal_evaluation_override(
            records,
            intent_name="returns",
            tenant_id="tenant-a",
            project_id="project-b",
        )

    assert [item["learning"] for item in selected] == ["Old", "Ask for the order number first."]
    assert other_project == records
    assert records == [{"id": "active-1", "learning": "Old", "affected_stages": ["response_text"]}]


def test_active_learning_loader_paginates_and_fails_closed_above_cap(monkeypatch):
    from automail.db.pocketbase import feedback

    pages: list[int] = []

    def fake_get(_path, params):
        page = int(params["page"])
        pages.append(page)
        count = 50 if page == 1 else 1
        return {
            "items": [
                {"id": f"learning-{page}-{index}", "learning": "Rule"}
                for index in range(count)
            ],
            "totalPages": 2,
        }

    monkeypatch.setattr(feedback, "_get", fake_get)
    with pytest.raises(RuntimeError, match="safe active-learning limit"):
        feedback.get_intent_learnings("returns", project_id="project-a")
    assert pages == [1, 2]


def test_publish_calls_transaction_route_only(monkeypatch):
    from automail.db.pocketbase import learning_proposals as store

    proposal = _proposal()
    calls = []
    monkeypatch.setattr(store, "active_learning_set_hash", lambda **_kwargs: "base-hash")

    def fake_post(path, body):
        calls.append((path, body))
        return {"proposal": {**proposal, "status": "published"}}

    monkeypatch.setattr(store, "_post", fake_post)
    published = store.publish_learning_proposal(proposal, published_by="admin-1")

    assert published["status"] == "published"
    assert calls == [
        (
            "/api/mantly/intent-learning-proposals/proposal-1/publish",
            {
                "intent_name": "returns",
                "tenant_id": "tenant-a",
                "project_id": "project-a",
                "expected_proposal_hash": proposal["proposal_hash"],
                "expected_base_hash": "base-hash",
                "expected_eval_run_id": "run-1",
                "published_by": "admin-1",
            },
        ),
    ]


def test_eval_summary_requires_affected_dimension_floor():
    from automail.api.admin.learning_proposals import _eval_summary

    run = {
        "status": "completed",
        "summary": {
            "overallScore": 90,
            "totalCases": 2,
            "completedCases": 2,
            "failedCases": 0,
        },
    }
    results = [
        {"eval_case": "case-1", "status": "completed", "response_score": 90},
        {"eval_case": "case-2", "status": "completed", "response_score": 79},
    ]
    failed = _eval_summary(
        run,
        minimum_score=80,
        results=results,
        selected_case_ids=["case-1", "case-2"],
        dimension="response",
        case_hash="case-hash",
    )
    results[1]["response_score"] = 80
    passed = _eval_summary(
        run,
        minimum_score=80,
        results=results,
        selected_case_ids=["case-1", "case-2"],
        dimension="response",
        case_hash="case-hash",
    )

    assert failed["passed"] is False
    assert failed["affectedScore"] == 79
    assert passed["passed"] is True


def test_stale_evaluating_proposal_recovers_to_retryable_failure(monkeypatch):
    from automail.api.admin import learning_proposals as api

    proposal = _proposal(
        status="evaluating",
        eval_run="run-stale",
        updated="2000-01-01 00:00:00.000Z",
    )
    run_patches = []
    proposal_patches = []
    monkeypatch.setattr(
        api,
        "_first",
        lambda *_args, **_kwargs: {"id": "run-stale", "status": "running"},
    )
    monkeypatch.setattr(
        api,
        "_patch",
        lambda path, updates: run_patches.append((path, updates)) or updates,
    )

    def fake_patch(proposal_id, updates):
        proposal_patches.append((proposal_id, updates))
        return {**proposal, **updates}

    monkeypatch.setattr(api, "patch_learning_proposal", fake_patch)

    recovered = api._reconcile_interrupted_proposal_eval(proposal)

    assert recovered["status"] == "eval_failed"
    assert "run the evaluation again" in recovered["error"]
    assert run_patches[0][0].endswith("/run-stale")
    assert run_patches[0][1]["status"] == "failed"
    assert proposal_patches[0][0] == "proposal-1"


def test_evaluate_rejects_client_threshold_below_server_floor(monkeypatch):
    from automail.api.admin import learning_proposals as api

    ctx = ProjectContext(
        tenant_id="tenant-a",
        user_id="editor-1",
        project_id="project-a",
        role="editor",
    )
    proposal = _proposal(status="proposed")
    monkeypatch.setattr(api, "_require_learning_feature", lambda _ctx: None)
    monkeypatch.setattr(api, "_require_ctx_capability", lambda *_args: None)
    monkeypatch.setattr(api, "_proposal_for_ctx", lambda *_args: proposal)
    monkeypatch.setattr(api, "_assert_runbook_unchanged", lambda *_args: {})
    monkeypatch.setattr(api, "active_learning_set_hash", lambda **_kwargs: "base-hash")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api.evaluate_proposal(
                "returns",
                "proposal-1",
                {"evalSetId": "set-1", "minimumScore": 79},
                ctx,
            ),
        )

    assert exc_info.value.status_code == 422
    assert "below 80" in str(exc_info.value.detail)


def test_disabled_runbook_rejects_proposal_path(monkeypatch):
    from automail.api.admin import learning_proposals as api

    ctx = ProjectContext(
        tenant_id="tenant-a",
        user_id="editor-1",
        project_id="project-a",
        role="editor",
    )
    monkeypatch.setattr(
        api,
        "_first",
        lambda *_args: {
            "id": "runbook-1",
            "response": {"use_feedback_learnings": False},
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        api._draft_runbook_for_proposal("returns", ctx)
    assert exc_info.value.status_code == 409


def test_publish_hook_contains_transaction_case_and_policy_fences():
    hook = Path("../pocketbase/pb_hooks/intent_learning_proposals.pb.js").read_text()
    assert "runInTransaction" in hook
    assert "status = 'publishing'" in hook
    assert "evalCaseHash(selectedCases)" in hook
    assert "LEARNING_EVAL_POLICY_HASH" in hook
    assert "score < minimum" in hook
    assert "$apis.requireSuperuserAuth()" in hook
