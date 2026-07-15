"""Admin account intelligence endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException

from automail.api.admin.deps import AuthDep, ProjectEditorDep, ProjectViewerDep
from automail.db.pocketbase.client import (
    create_account_insight,
    generate_account_summary_insight,
    get_account,
    list_accounts,
    prepare_account_action_package,
    update_account_insight,
)
from automail.models import CamelCaseModel

router = APIRouter()


class AccountInsightUpdate(CamelCaseModel):
    status: str | None = None
    severity: str | None = None
    title: str | None = None
    body: str | None = None


class AccountInsightCreate(CamelCaseModel):
    type: str = "summary"
    title: str
    body: str = ""
    severity: str = "info"
    status: str = "open"
    source_issue_id: str = ""
    insight_key: str = ""
    metadata: dict[str, Any] | None = None


@router.get("/projects/{pid}/accounts")
async def get_accounts(ctx: ProjectViewerDep, limit: int = 100) -> dict[str, Any]:
    return {
        "items": list_accounts(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            limit=max(1, min(limit, 200)),
        )
    }


@router.get("/projects/{pid}/accounts/{account_id}")
async def get_account_detail(account_id: str, ctx: ProjectViewerDep) -> dict[str, Any]:
    account = get_account(
        account_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.post("/projects/{pid}/accounts/{account_id}/insights")
async def create_account_insight_record(
    account_id: str,
    body: AccountInsightCreate,
    ctx: ProjectEditorDep,
) -> dict[str, Any]:
    try:
        insight = create_account_insight(
            account_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            insight_type=body.type,
            title=body.title,
            body=body.body,
            severity=body.severity,
            status=body.status,
            source_issue_id=body.source_issue_id,
            insight_key=body.insight_key,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not insight:
        raise HTTPException(status_code=404, detail="Account not found")
    return insight


@router.post("/projects/{pid}/accounts/{account_id}/summary")
async def generate_account_summary(
    account_id: str,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    insight = generate_account_summary_insight(
        account_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        author_email=auth.email,
    )
    if not insight:
        raise HTTPException(status_code=404, detail="Account not found")
    return insight


@router.post("/projects/{pid}/accounts/{account_id}/action-package")
async def prepare_account_action(
    account_id: str,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    package = prepare_account_action_package(
        account_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        author_email=auth.email,
    )
    if not package:
        raise HTTPException(status_code=404, detail="Account not found")
    return package


@router.patch("/projects/{pid}/accounts/insights/{insight_id}")
async def patch_account_insight(
    insight_id: str,
    body: AccountInsightUpdate,
    ctx: ProjectEditorDep,
) -> dict[str, Any]:
    insight = update_account_insight(
        insight_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        updates=body.model_dump(exclude_unset=True),
    )
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")
    return insight
