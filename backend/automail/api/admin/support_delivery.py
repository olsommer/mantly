"""Admin support delivery endpoints."""

from typing import Any

from fastapi import APIRouter

from automail.api.admin.deps import ProjectEditorDep, ProjectViewerDep
from automail.db.pocketbase.client import list_delivery_runs
from automail.support.scheduler import run_scheduled_support_delivery

router = APIRouter()


@router.post("/projects/{pid}/support/delivery/run")
async def run_support_delivery(ctx: ProjectEditorDep, limit: int = 25, retry_failed: bool = False) -> dict[str, Any]:
    return run_scheduled_support_delivery(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=max(1, min(limit, 100)),
        source="admin",
        retry_failed=retry_failed,
    )


@router.get("/projects/{pid}/support/delivery/runs")
async def get_support_delivery_runs(ctx: ProjectViewerDep, limit: int = 50) -> dict[str, Any]:
    return {
        "items": list_delivery_runs(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            limit=max(1, min(limit, 200)),
        )
    }
