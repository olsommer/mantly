"""Controlled intent-learning proposal persistence and evaluation overrides."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from automail.db.pocketbase.base import _escape_pb, _first, _list_all, _patch, _post, generate_id

LEARNING_PROPOSAL_STATES = {
    "proposed",
    "evaluating",
    "evaluated",
    "eval_failed",
    "published",
    "rejected",
}
LEARNING_PROPOSAL_OPERATIONS = {"create", "update", "delete"}
LEARNING_EVAL_SERVER_FLOOR = 80.0
LEARNING_EVAL_STAGE_DIMENSIONS = {
    "action": "actions",
    "action_fills": "actions",
    "actions": "actions",
    "answer": "response",
    "customer": "identity",
    "customer_identification": "identity",
    "email_response": "response",
    "identity": "identity",
    "intent": "intent",
    "intent_processing": "actions",
    "intent_recognition": "intent",
    "response": "response",
    "response_text": "response",
    "skill": "intent",
    "tool": "actions",
    "tool_usage": "actions",
    "tools": "actions",
    "workflow": "actions",
}
LEARNING_EVAL_PREFIX_DIMENSIONS = {
    "action:": "actions",
    "tool:": "actions",
}
LEARNING_EVAL_POLICY = {
    "prefix_dimensions": LEARNING_EVAL_PREFIX_DIMENSIONS,
    "server_floor": 80,
    "stage_dimensions": LEARNING_EVAL_STAGE_DIMENSIONS,
    "version": "intent-learning-eval-v1",
}
LEARNING_EVAL_POLICY_HASH = "eade510f204556964a0ac6f3938482c53e07dcf6598f6656ed647c99b2cdec8a"

_evaluation_override: ContextVar[dict[str, Any] | None] = ContextVar(
    "intent_learning_evaluation_override",
    default=None,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stage_values(value: Any) -> list[str]:
    if not value:
        return []
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _scope_filter(
    *,
    intent_name: str,
    tenant_id: str | None,
    project_id: str | None,
) -> str:
    filter_str = f"intent_name='{_escape_pb(intent_name)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    return filter_str


def _active_learning_snapshot(
    *,
    intent_name: str,
    tenant_id: str | None,
    project_id: str | None,
) -> list[dict[str, Any]]:
    records = _list_all(
        "intent_learnings",
        _scope_filter(
            intent_name=intent_name,
            tenant_id=tenant_id,
            project_id=project_id,
        ),
        sort="created",
    )
    snapshot = [
        {
            "id": str(item.get("id") or ""),
            "learning": str(item.get("learning") or ""),
            "source_feedback_id": str(item.get("source_feedback_id") or ""),
            "affected_stages": _stage_values(item.get("affected_stages")),
        }
        for item in records
    ]
    return sorted(snapshot, key=lambda item: item["id"])


def active_learning_set_hash(
    *,
    intent_name: str,
    tenant_id: str | None,
    project_id: str | None,
) -> str:
    """Hash every active rule that contributed to the evaluated prompt."""
    return _sha256(
        _active_learning_snapshot(
            intent_name=intent_name,
            tenant_id=tenant_id,
            project_id=project_id,
        ),
    )


def _proposal_hash_payload(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent_name": str(proposal.get("intent_name") or ""),
        "operation": str(proposal.get("operation") or ""),
        "target_learning_id": str(proposal.get("target_learning_id") or ""),
        "proposed_learning": str(proposal.get("proposed_learning") or ""),
        "before_learning": str(proposal.get("before_learning") or ""),
        "source_feedback_id": str(proposal.get("source_feedback_id") or ""),
        "affected_stages": _stage_values(proposal.get("affected_stages")),
        "base_learning_hash": str(proposal.get("base_learning_hash") or ""),
        "tenant": str(proposal.get("tenant") or ""),
        "project": str(proposal.get("project") or ""),
        "runbook_id": str(proposal.get("runbook_id") or ""),
        "runbook_updated": str(proposal.get("runbook_updated") or ""),
    }


def compute_learning_proposal_hash(proposal: dict[str, Any]) -> str:
    return _sha256(_proposal_hash_payload(proposal))


def learning_eval_dimension(affected_stages: Any) -> str:
    dimensions: set[str] = set()
    for raw_stage in _stage_values(affected_stages):
        stage = raw_stage.strip().lower().replace("-", "_")
        dimension = LEARNING_EVAL_STAGE_DIMENSIONS.get(stage)
        if not dimension:
            for prefix, prefix_dimension in LEARNING_EVAL_PREFIX_DIMENSIONS.items():
                if stage.startswith(prefix):
                    dimension = prefix_dimension
                    break
        if not dimension:
            raise ValueError(f"Affected stage '{raw_stage}' has no evaluation policy")
        dimensions.add(dimension)
    if not dimensions:
        raise ValueError("Proposal must identify an affected stage")
    if len(dimensions) != 1:
        raise ValueError("Affected stages must map to one evaluation dimension")
    return next(iter(dimensions))


def eval_case_selection_hash(cases: list[dict[str, Any]]) -> str:
    snapshot = sorted(
        [
            {
                "id": str(case.get("id") or ""),
                "updated": str(case.get("updated") or ""),
            }
            for case in cases
        ],
        key=lambda item: item["id"],
    )
    return _sha256(snapshot)


def _proposal_filter(
    proposal_id: str,
    *,
    intent_name: str,
    tenant_id: str | None,
    project_id: str | None,
) -> str:
    return (
        f"id='{_escape_pb(proposal_id)}' && "
        + _scope_filter(
            intent_name=intent_name,
            tenant_id=tenant_id,
            project_id=project_id,
        )
    )


def get_learning_proposal(
    proposal_id: str,
    *,
    intent_name: str,
    tenant_id: str | None,
    project_id: str | None,
) -> dict[str, Any] | None:
    return _first(
        "intent_learning_proposals",
        _proposal_filter(
            proposal_id,
            intent_name=intent_name,
            tenant_id=tenant_id,
            project_id=project_id,
        ),
    )


def list_learning_proposals(
    *,
    intent_name: str,
    tenant_id: str | None,
    project_id: str | None,
) -> list[dict[str, Any]]:
    return _list_all(
        "intent_learning_proposals",
        _scope_filter(
            intent_name=intent_name,
            tenant_id=tenant_id,
            project_id=project_id,
        ),
        sort="-created",
    )


def create_learning_proposal(
    *,
    intent_name: str,
    operation: str,
    tenant_id: str | None,
    project_id: str | None,
    proposed_learning: str = "",
    target_learning_id: str = "",
    source_feedback_id: str = "",
    affected_stages: list[str] | None = None,
    created_by: str = "",
    runbook_id: str = "",
    runbook_updated: str = "",
) -> dict[str, Any]:
    operation = operation.strip().lower()
    proposed_learning = proposed_learning.strip()
    target_learning_id = target_learning_id.strip()
    if operation not in LEARNING_PROPOSAL_OPERATIONS:
        raise ValueError("operation must be create, update, or delete")
    if operation in {"create", "update"} and not proposed_learning:
        raise ValueError("proposedLearning is required")
    if operation in {"update", "delete"} and not target_learning_id:
        raise ValueError("targetLearningId is required")

    target: dict[str, Any] | None = None
    if target_learning_id:
        target_filter = (
            f"id='{_escape_pb(target_learning_id)}' && "
            + _scope_filter(
                intent_name=intent_name,
                tenant_id=tenant_id,
                project_id=project_id,
            )
        )
        target = _first("intent_learnings", target_filter)
        if not target:
            raise LookupError("Target learning not found")

    clean_stages = _stage_values(affected_stages)
    if target is not None and affected_stages is None:
        clean_stages = _stage_values(target.get("affected_stages"))

    data: dict[str, Any] = {
        "id": generate_id(),
        "intent_name": intent_name,
        "operation": operation,
        "status": "proposed",
        "proposed_learning": proposed_learning,
        "before_learning": str((target or {}).get("learning") or ""),
        "target_learning_id": target_learning_id,
        "source_feedback_id": source_feedback_id.strip(),
        "affected_stages": clean_stages,
        "base_learning_hash": active_learning_set_hash(
            intent_name=intent_name,
            tenant_id=tenant_id,
            project_id=project_id,
        ),
        "created_by": created_by,
        "runbook_id": runbook_id,
        "runbook_updated": runbook_updated,
    }
    if tenant_id:
        data["tenant"] = tenant_id
    if project_id:
        data["project"] = project_id
    data["proposal_hash"] = compute_learning_proposal_hash(data)
    return _post("/api/collections/intent_learning_proposals/records", data)


def patch_learning_proposal(
    proposal_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    return _patch(f"/api/collections/intent_learning_proposals/records/{proposal_id}", updates)


def serialize_learning_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    summary = proposal.get("eval_summary")
    if not isinstance(summary, dict):
        summary = {}
    return {
        "id": str(proposal.get("id") or ""),
        "intent_name": str(proposal.get("intent_name") or ""),
        "status": str(proposal.get("status") or ""),
        "operation": str(proposal.get("operation") or ""),
        "proposed_learning": str(proposal.get("proposed_learning") or ""),
        "before_learning": str(proposal.get("before_learning") or ""),
        "target_learning_id": str(proposal.get("target_learning_id") or ""),
        "affected_stages": _stage_values(proposal.get("affected_stages")),
        "source_feedback_id": str(proposal.get("source_feedback_id") or ""),
        "eval_set_id": str(proposal.get("eval_set") or ""),
        "eval_run_id": str(proposal.get("eval_run") or ""),
        "eval_summary": summary,
        "eval_case_ids": _stage_values(proposal.get("eval_case_ids")),
        "eval_case_hash": str(proposal.get("eval_case_hash") or ""),
        "eval_policy_hash": str(proposal.get("eval_policy_hash") or ""),
        "eval_dimension": str(proposal.get("eval_dimension") or ""),
        "minimum_score": float(proposal.get("minimum_score") or 0),
        "error": str(proposal.get("error") or ""),
        "rejection_reason": str(proposal.get("rejection_reason") or ""),
        "active_learning_id": str(proposal.get("active_learning_id") or ""),
        "runbook_id": str(proposal.get("runbook_id") or ""),
        "runbook_updated": str(proposal.get("runbook_updated") or ""),
        "created_by": str(proposal.get("created_by") or ""),
        "evaluated_by": str(proposal.get("evaluated_by") or ""),
        "published_by": str(proposal.get("published_by") or ""),
        "rejected_by": str(proposal.get("rejected_by") or ""),
        "created": str(proposal.get("created") or ""),
        "updated": str(proposal.get("updated") or ""),
        "evaluated_at": str(proposal.get("evaluated_at") or ""),
        "published_at": str(proposal.get("published_at") or ""),
        "rejected_at": str(proposal.get("rejected_at") or ""),
    }


@contextmanager
def learning_proposal_evaluation_override(proposal: dict[str, Any]) -> Iterator[None]:
    """Apply one candidate only inside the current eval execution context."""
    token = _evaluation_override.set(dict(proposal))
    try:
        yield
    finally:
        _evaluation_override.reset(token)


def apply_learning_proposal_evaluation_override(
    records: list[dict[str, Any]],
    *,
    intent_name: str,
    tenant_id: str | None,
    project_id: str | None,
) -> list[dict[str, Any]]:
    proposal = _evaluation_override.get()
    if not proposal:
        return records
    if str(proposal.get("intent_name") or "") != intent_name:
        return records
    if str(proposal.get("tenant") or "") != str(tenant_id or ""):
        return records
    if str(proposal.get("project") or "") != str(project_id or ""):
        return records

    operation = str(proposal.get("operation") or "")
    target_id = str(proposal.get("target_learning_id") or "")
    result = [dict(record) for record in records]
    if operation == "delete":
        return [record for record in result if str(record.get("id") or "") != target_id]
    if operation == "update":
        for record in result:
            if str(record.get("id") or "") == target_id:
                record["learning"] = str(proposal.get("proposed_learning") or "")
                record["affected_stages"] = _stage_values(proposal.get("affected_stages"))
        return result
    if operation == "create":
        result.append({
            "id": f"proposal:{proposal.get('id', '')}",
            "learning": str(proposal.get("proposed_learning") or ""),
            "affected_stages": _stage_values(proposal.get("affected_stages")),
            "source_feedback_id": str(proposal.get("source_feedback_id") or ""),
        })
    return result


def publish_learning_proposal(
    proposal: dict[str, Any],
    *,
    published_by: str,
) -> dict[str, Any]:
    """Publish through PocketBase's transaction-fenced custom route."""
    if str(proposal.get("status") or "") != "evaluated":
        raise ValueError("Proposal must have a successful evaluation before publish")
    if compute_learning_proposal_hash(proposal) != str(proposal.get("proposal_hash") or ""):
        raise ValueError("Proposal changed after creation; create a new proposal")
    if str(proposal.get("evaluated_proposal_hash") or "") != str(proposal.get("proposal_hash") or ""):
        raise ValueError("Proposal does not match its evaluation evidence")

    intent_name = str(proposal.get("intent_name") or "")
    tenant_id = str(proposal.get("tenant") or "") or None
    project_id = str(proposal.get("project") or "") or None
    current_base_hash = active_learning_set_hash(
        intent_name=intent_name,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    expected_base_hash = str(proposal.get("base_learning_hash") or "")
    if current_base_hash != expected_base_hash:
        raise ValueError("Active learnings changed after proposal creation; evaluate a new proposal")
    if str(proposal.get("evaluated_base_hash") or "") != expected_base_hash:
        raise ValueError("Active-learning baseline does not match evaluation evidence")

    result = _post(
        f"/api/mantly/intent-learning-proposals/{proposal['id']}/publish",
        {
            "intent_name": intent_name,
            "tenant_id": tenant_id or "",
            "project_id": project_id or "",
            "expected_proposal_hash": str(proposal.get("proposal_hash") or ""),
            "expected_base_hash": expected_base_hash,
            "expected_eval_run_id": str(proposal.get("eval_run") or ""),
            "published_by": published_by,
        },
    )
    published = result.get("proposal")
    if not isinstance(published, dict):
        raise RuntimeError("PocketBase publish route returned no proposal")
    return published
