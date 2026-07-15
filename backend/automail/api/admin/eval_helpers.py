"""Shared helpers for evaluation admin endpoints."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from automail.core.auth import ProjectContext
from automail.db.pocketbase.client import _first, _list_all, _patch, _post, generate_id

logger = logging.getLogger(__name__)


def _escape(value: str) -> str:
    return value.replace("'", "\\'")


def _tenant_filter(tenant_id: str) -> str:
    if not tenant_id:
        return ""
    return f"tenant='{_escape(tenant_id)}'"


def _demo_root() -> Path:
    import os

    return Path(os.getenv("DEMO_DATA_DIR", Path(__file__).resolve().parents[4] / "demo"))


def _load_demo_emails() -> list[dict]:
    try:
        return json.loads((_demo_root() / "emails" / "emails.json").read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to load demo email fixtures", exc_info=True)
        return []


def _demo_expected_outcomes(email: dict) -> dict:
    email_id = str(email.get("id") or "")
    if email_id == "zen-shipment-status":
        return {
            "expected_customer_found": False,
            "expected_customer_data": {},
            "expected_intent_matched": True,
            "expected_intent_name": "shipment-status-request",
            "expected_actions": [],
            "expected_requires_human": False,
            "expected_response": (
                "The response should answer in German, use the shipment lookup for ZF-10482, "
                "include the DHL status and delivery window, and avoid inventing carrier events."
            ),
        }
    if email_id == "zen-delivery-exception":
        return {
            "expected_customer_found": False,
            "expected_customer_data": {},
            "expected_intent_matched": True,
            "expected_intent_name": "delivery-exception",
            "expected_actions": [{"name": "open_ticket", "label": "Open ticket"}],
            "expected_requires_human": False,
            "expected_response": (
                "The response should acknowledge the stale tracking issue in German, "
                "use shipment lookup context when available, expose the Open ticket action, "
                "and confirm that Customer Operations can review the case."
            ),
        }
    return {
        "expected_customer_found": False,
        "expected_customer_data": {},
        "expected_intent_matched": True,
        "expected_intent_name": "shipment-status-request",
        "expected_actions": [],
        "expected_requires_human": False,
        "expected_response": "The response should handle the demo logistics email without human review.",
    }


def _ensure_demo_eval_cases(ctx: ProjectContext) -> None:
    if not ctx.tenant_id:
        return

    try:
        from automail.db.pocketbase.client import get_tenant_account_type

        if get_tenant_account_type(ctx.tenant_id) != "demo":
            return

        demo_set = _first(
            "eval_sets",
            f"project='{_escape(ctx.project_id)}' && tenant='{_escape(ctx.tenant_id)}' && name='Demo test emails'",
        )
        if not demo_set:
            demo_set = _post(
                "/api/collections/eval_sets/records",
                {
                    "id": generate_id(),
                    "tenant": ctx.tenant_id,
                    "project": ctx.project_id,
                    "name": "Demo test emails",
                    "description": "",
                },
            )
        elif demo_set.get("description"):
            _patch(f"/api/collections/eval_sets/records/{demo_set['id']}", {"description": ""})
            demo_set["description"] = ""

        existing_cases = _list_all("eval_cases", f"eval_set='{_escape(demo_set['id'])}'")
        existing_subjects = {case.get("email_subject", ""): case for case in existing_cases}

        for email in _load_demo_emails():
            subject = str(email.get("subject") or "").strip()
            if not subject:
                continue
            expected = _demo_expected_outcomes(email)
            if subject in existing_subjects:
                _patch(
                    f"/api/collections/eval_cases/records/{existing_subjects[subject]['id']}",
                    expected,
                )
                continue

            _post(
                "/api/collections/eval_cases/records",
                {
                    "id": generate_id(),
                    "eval_set": demo_set["id"],
                    "name": subject,
                    "email_subject": subject,
                    "email_from": str(email.get("fromAddress") or "unknown@example.com"),
                    "email_body": str(email.get("body") or ""),
                    "email_attachments": email.get("attachments") or [],
                    **expected,
                },
            )
    except Exception:
        logger.warning("Failed to seed demo evaluation cases", exc_info=True)


def _get_eval_set_for_ctx(set_id: str, ctx: ProjectContext) -> dict:
    filters = [f"id='{_escape(set_id)}'", f"project='{_escape(ctx.project_id)}'"]
    if ctx.tenant_id:
        filters.append(f"tenant='{_escape(ctx.tenant_id)}'")
    eval_set = _first("eval_sets", " && ".join(filters))
    if not eval_set:
        raise HTTPException(status_code=404, detail="Eval set not found")
    return eval_set


def _get_eval_case_for_ctx(case_id: str, ctx: ProjectContext) -> dict:
    case = _first("eval_cases", f"id='{_escape(case_id)}'")
    if not case:
        raise HTTPException(status_code=404, detail="Eval case not found")
    _get_eval_set_for_ctx(str(case.get("eval_set") or ""), ctx)
    return case


def _get_eval_run_for_ctx(run_id: str, ctx: ProjectContext) -> dict:
    filters = [f"id='{_escape(run_id)}'", f"project='{_escape(ctx.project_id)}'"]
    if ctx.tenant_id:
        filters.append(f"tenant='{_escape(ctx.tenant_id)}'")
    run = _first("eval_runs", " && ".join(filters))
    if not run:
        raise HTTPException(status_code=404, detail="Eval run not found")
    return run


def mark_orphaned_eval_runs_failed() -> int:
    """Mark in-progress eval runs as failed after a backend restart.

    Eval execution currently happens in an in-process background thread. If the
    backend exits while a run is active, no worker remains to complete it and
    the admin UI would poll forever. Startup calls this after schema bootstrap.
    """
    failed_count = 0
    now = datetime.now(timezone.utc).isoformat()
    runs = _list_all("eval_runs", sort="-created")

    for run in runs:
        if run.get("status") not in {"pending", "running"}:
            continue

        run_id = run["id"]
        results = _list_all("eval_results", f"eval_run='{_escape(run_id)}'")
        for result in results:
            if result.get("status") in {"pending", "running"}:
                _patch(
                    f"/api/collections/eval_results/records/{result['id']}",
                    {
                        "status": "failed",
                        "error": "Evaluation was interrupted by a backend restart.",
                    },
                )

        _patch(
            f"/api/collections/eval_runs/records/{run_id}",
            {
                "status": "failed",
                "completed_at": now,
                "summary": {
                    "overallScore": None,
                    "identityScore": None,
                    "intentScore": None,
                    "actionsScore": None,
                    "responseScore": None,
                    "totalCases": len(results),
                    "completedCases": 0,
                    "failedCases": len(results),
                },
            },
        )
        failed_count += 1

    if failed_count:
        logger.warning("Marked %d orphaned eval run(s) as failed", failed_count)

    return failed_count
