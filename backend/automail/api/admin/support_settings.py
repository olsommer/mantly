"""Admin support settings endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import Field

from automail.api.admin.deps import ProjectEditorDep, ProjectViewerDep
from automail.db.pocketbase.client import get_sla_policy, support_schema_health, upsert_sla_policy
from automail.models import CamelCaseModel
from automail.support.scheduler import run_scheduled_support_sla_escalations

router = APIRouter()


class SlaPolicyInput(CamelCaseModel):
    name: str = "Default"
    active: bool = True
    first_response_minutes: int = 240
    resolution_minutes: int = 2880
    business_hours: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/projects/{pid}/support/sla-policy")
async def get_support_sla_policy(ctx: ProjectViewerDep) -> dict[str, Any]:
    return get_sla_policy(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )


@router.get("/projects/{pid}/support/schema-health")
async def get_support_schema_health(ctx: ProjectViewerDep) -> dict[str, Any]:
    _ = ctx
    return support_schema_health()


@router.patch("/projects/{pid}/support/sla-policy")
async def save_support_sla_policy(body: SlaPolicyInput, ctx: ProjectEditorDep) -> dict[str, Any]:
    try:
        return upsert_sla_policy(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            name=body.name,
            active=body.active,
            first_response_minutes=body.first_response_minutes,
            resolution_minutes=body.resolution_minutes,
            business_hours=body.business_hours,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{pid}/support/sla/run")
async def run_support_sla_escalations(ctx: ProjectEditorDep, limit: int = 100) -> dict[str, Any]:
    return run_scheduled_support_sla_escalations(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        limit=max(1, min(limit, 200)),
        source="admin",
    )
