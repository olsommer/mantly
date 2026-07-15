"""Admin monitor endpoints."""

from fastapi import APIRouter

from automail.api.admin.deps import ProjectViewerDep
from automail.db.pocketbase.client import _escape_pb, _list_all
from automail.monitoring import list_monitor_runs, monitor_summary

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────
# Monitor — customer-facing run history
# ──────────────────────────────────────────────────────────────────────────────

def _monitor_feedback_summary(chat_id: str, tenant_id: str | None, project_id: str) -> dict:
    if not chat_id:
        return {"count": 0, "latestRating": "", "latestAt": "", "hasFeedback": False}
    filter_str = f"chat_id='{_escape_pb(chat_id)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    if project_id:
        filter_str += f" && project='{_escape_pb(project_id)}'"
    records = _list_all("feedback", filter_str, sort="-created", per_page=5)
    latest = records[0] if records else {}
    return {
        "count": len(records),
        "latestRating": latest.get("rating", ""),
        "latestAt": latest.get("created", ""),
        "hasFeedback": bool(records),
    }


def _monitor_chat_id(rec: dict) -> str:
    input_data = rec.get("input") or {}
    if not isinstance(input_data, dict):
        return ""
    if input_data.get("emailId"):
        return str(input_data.get("emailId") or "")
    payload = input_data.get("payload") or {}
    if isinstance(payload, dict) and payload.get("chatId"):
        return str(payload.get("chatId") or "")
    return ""


def _monitor_run_to_api(rec: dict, tenant_id: str | None, project_id: str) -> dict:
    chat_id = _monitor_chat_id(rec)
    return {
        "id": rec.get("id", ""),
        "source": rec.get("source", ""),
        "status": rec.get("status", ""),
        "startedAt": rec.get("started_at") or rec.get("created") or "",
        "completedAt": rec.get("completed_at") or "",
        "durationMs": int(rec.get("duration_ms") or 0),
        "userEmail": rec.get("user_email") or "",
        "input": rec.get("input") or {},
        "output": rec.get("output") or {},
        "actions": rec.get("actions") or [],
        "feedback": _monitor_feedback_summary(chat_id, tenant_id, project_id),
        "error": rec.get("error") or "",
        "created": rec.get("created") or "",
    }


@router.get("/projects/{pid}/monitor/summary")
async def get_monitor_summary(ctx: ProjectViewerDep) -> dict:
    return monitor_summary(tenant_id=ctx.tenant_id, project_id=ctx.project_id)


@router.get("/projects/{pid}/monitor/runs")
async def get_monitor_runs(ctx: ProjectViewerDep, limit: int = 50) -> dict:
    runs = list_monitor_runs(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=max(1, min(limit, 100)),
    )
    return {"items": [_monitor_run_to_api(rec, ctx.tenant_id, ctx.project_id) for rec in runs]}
