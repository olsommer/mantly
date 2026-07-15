"""Draft/live manager for PocketBase-backed pipeline configuration."""

from automail.pipeline.store import (
    PipelineSource,
    ensure_project_pipeline,
    has_unpublished_project_changes,
    replace_live_from_draft,
)


def get_live_source(project_id: str | None = None, tenant_id: str | None = None) -> PipelineSource:
    if project_id is None:
        raise ValueError("project_id is required for PocketBase pipeline storage")
    return PipelineSource(project_id=project_id, mode="live", tenant_id=tenant_id)


def get_draft_source(project_id: str | None = None, tenant_id: str | None = None) -> PipelineSource:
    if project_id is None:
        raise ValueError("project_id is required for PocketBase pipeline storage")
    return PipelineSource(project_id=project_id, mode="draft", tenant_id=tenant_id)


def ensure_draft_exists(project_id: str | None = None, tenant_id: str | None = None) -> None:
    if project_id is None:
        return
    ensure_project_pipeline(project_id, tenant_id=tenant_id)


def publish(project_id: str | None = None, tenant_id: str | None = None) -> None:
    if project_id is None:
        raise ValueError("project_id is required")
    replace_live_from_draft(project_id, tenant_id=tenant_id)


def has_unpublished_changes(project_id: str | None = None, tenant_id: str | None = None) -> bool:
    if project_id is None:
        return False
    return has_unpublished_project_changes(project_id, tenant_id=tenant_id)
