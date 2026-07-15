"""Admin knowledge base endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import Field

from automail.api.admin.deps import AuthDep, ProjectEditorDep, ProjectViewerDep
from automail.db.pocketbase.client import (
    create_knowledge_article,
    create_knowledge_article_from_gap,
    get_knowledge_article,
    list_knowledge_articles,
    list_knowledge_gaps,
    update_knowledge_article,
    update_knowledge_gap,
)
from automail.models import CamelCaseModel

router = APIRouter()


class KnowledgeArticleInput(CamelCaseModel):
    title: str
    body: str
    status: str = "draft"
    source_issue_id: str = ""
    source_gap_id: str = ""
    source_url: str = ""
    visibility: str = "public"
    automation_allowed: bool | None = None
    tags: list[str] = Field(default_factory=list)


class KnowledgeArticleUpdate(CamelCaseModel):
    title: str | None = None
    body: str | None = None
    status: str | None = None
    source_issue_id: str | None = None
    source_url: str | None = None
    visibility: str | None = None
    public: bool | None = None
    automation_allowed: bool | None = None
    review_status: str | None = None
    last_reviewed_at: str | None = None
    review_due_at: str | None = None
    tags: list[str] | None = None


class KnowledgeGapUpdate(CamelCaseModel):
    status: str | None = None
    severity: str | None = None
    title: str | None = None
    evidence: str | None = None
    suggested_article_title: str | None = None


class KnowledgeGapArticleInput(CamelCaseModel):
    status: str = "draft"


@router.get("/projects/{pid}/knowledge")
async def get_knowledge(
    ctx: ProjectViewerDep,
    auth: AuthDep,
    status: str = "all",
    limit: int = 100,
) -> dict[str, Any]:
    return {
        "items": list_knowledge_articles(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            status=status,
            limit=max(1, min(limit, 200)),
            actor_email=auth.email,
            actor_role=ctx.role,
        )
    }


@router.get("/projects/{pid}/knowledge/gaps")
async def get_knowledge_gaps(
    ctx: ProjectViewerDep,
    auth: AuthDep,
    status: str = "open",
    limit: int = 100,
) -> dict[str, Any]:
    return {
        "items": list_knowledge_gaps(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            status=status,
            limit=max(1, min(limit, 200)),
            actor_email=auth.email,
            actor_role=ctx.role,
        )
    }


@router.patch("/projects/{pid}/knowledge/gaps/{gap_id}")
async def patch_knowledge_gap(gap_id: str, body: KnowledgeGapUpdate, ctx: ProjectEditorDep) -> dict[str, Any]:
    try:
        gap = update_knowledge_gap(
            gap_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            updates=body.model_dump(exclude_unset=True),
            actor_role=ctx.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not gap:
        raise HTTPException(status_code=404, detail="Knowledge gap not found")
    return gap


@router.post("/projects/{pid}/knowledge/gaps/{gap_id}/article")
async def create_article_from_gap(gap_id: str, body: KnowledgeGapArticleInput, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    try:
        article = create_knowledge_article_from_gap(
            gap_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            status=body.status,
            actor_email=auth.email,
            actor_role=ctx.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not article:
        raise HTTPException(status_code=404, detail="Knowledge gap not found")
    return article


@router.get("/projects/{pid}/knowledge/{article_id}")
async def get_article(
    article_id: str,
    ctx: ProjectViewerDep,
    auth: AuthDep,
) -> dict[str, Any]:
    article = get_knowledge_article(
        article_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        actor_email=auth.email,
        actor_role=ctx.role,
    )
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.post("/projects/{pid}/knowledge")
async def create_article(body: KnowledgeArticleInput, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    if body.visibility.strip().lower() == "private" and ctx.role not in {"root", "admin"}:
        raise HTTPException(status_code=403, detail="Private knowledge requires project admin access")
    try:
        return create_knowledge_article(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            title=body.title,
            body=body.body,
            status=body.status,
            source_issue_id=body.source_issue_id,
            source_gap_id=body.source_gap_id,
            source_url=body.source_url,
            visibility=body.visibility,
            automation_allowed=body.automation_allowed,
            tags=body.tags,
            actor_email=auth.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/projects/{pid}/knowledge/{article_id}")
async def patch_article(article_id: str, body: KnowledgeArticleUpdate, ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    if (
        body.visibility is not None
        and body.visibility.strip().lower() == "private"
        and ctx.role not in {"root", "admin"}
    ):
        raise HTTPException(status_code=403, detail="Private knowledge requires project admin access")
    try:
        article = update_knowledge_article(
            article_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            updates=body.model_dump(exclude_unset=True),
            actor_email=auth.email,
            actor_role=ctx.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
