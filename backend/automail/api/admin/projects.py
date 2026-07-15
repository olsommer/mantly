"""Admin project, member, and publish endpoints."""

import httpx
from fastapi import APIRouter, HTTPException

from automail.api.admin.deps import (
    ProjectAdminDep,
    ProjectViewerDep,
    RootAuthDep,
    _require_auth_capability,
    _require_ctx_capability,
)
from automail.pipeline.drafts import ensure_draft_exists, has_unpublished_changes
from automail.pipeline.drafts import publish as do_publish

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────
# Project management (root + project admins)
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/projects")
async def create_project_endpoint(body: dict, auth: RootAuthDep) -> dict:
    """Create a new project (root only)."""
    from automail.billing.usage import check_limit
    from automail.db.pocketbase.client import create_project
    tenant_id = auth.tenant_id
    _require_auth_capability(auth, "canManageProjectSettings")
    name = body.get("name", "").strip()
    description = body.get("description", "").strip()
    if not name:
        raise HTTPException(400, "Project name is required")
    if not tenant_id:
        raise HTTPException(400, "Cannot create projects when REQUIRE_AUTH is disabled")
    check_limit(tenant_id, "projects")
    rec = create_project(name, description, tenant_id)
    # Bootstrap the draft for the new project
    ensure_draft_exists(rec["id"], tenant_id=tenant_id)
    from automail.billing.addons import sync_stripe_addons_best_effort
    sync_stripe_addons_best_effort(tenant_id)
    return {"id": rec["id"], "name": rec.get("name", name)}


@router.get("/projects/{pid}")
async def get_project_endpoint(ctx: ProjectViewerDep) -> dict:
    """Get project details."""
    from automail.db.pocketbase.client import get_project
    project = get_project(ctx.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return {
        "id": project["id"],
        "name": project.get("name", ""),
        "description": project.get("description", ""),
        "tenant": project.get("tenant", ""),
        "created": project.get("created", ""),
    }


@router.put("/projects/{pid}")
async def update_project_endpoint(body: dict, ctx: ProjectAdminDep) -> dict:
    """Update project name/description (admin+ required)."""
    from automail.db.pocketbase.client import update_project
    _require_ctx_capability(ctx, "canManageProjectSettings")
    name = body.get("name")
    description = body.get("description")
    update_project(ctx.project_id, name=name, description=description)
    return {"status": "ok"}


@router.delete("/projects/{pid}")
async def delete_project_endpoint(pid: str, auth: RootAuthDep) -> dict:
    """Delete a project (root only)."""

    from automail.db.pocketbase.client import delete_project, get_project
    tenant_id = auth.tenant_id
    _require_auth_capability(auth, "canManageProjectSettings")
    if not tenant_id:
        raise HTTPException(400, "Cannot delete projects when REQUIRE_AUTH is disabled")
    project = get_project(pid)
    if not project or project.get("tenant") != tenant_id:
        raise HTTPException(404, "Project not found")
    delete_project(pid)
    from automail.billing.addons import sync_stripe_addons_best_effort
    sync_stripe_addons_best_effort(tenant_id)
    return {"status": "deleted"}


# ──────────────────────────────────────────────────────────────────────────────
# Project Members (admin+ in project)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/members")
async def list_members(ctx: ProjectAdminDep) -> list[dict]:
    """List members of a project."""
    from automail.db.pocketbase.client import list_project_members
    _require_ctx_capability(ctx, "canManageMembers")
    return list_project_members(ctx.project_id)


@router.post("/projects/{pid}/members")
async def add_member(body: dict, ctx: ProjectAdminDep) -> dict:
    """Add a member to a project."""
    from automail.billing.usage import check_limit
    from automail.db.pocketbase.client import add_project_member

    _require_ctx_capability(ctx, "canManageMembers")
    check_limit(ctx.tenant_id, "users")

    user_id = body.get("userId", "").strip()
    role = body.get("role", "").strip()
    if not user_id or role not in ("admin", "editor", "viewer"):
        raise HTTPException(400, "userId and valid role (admin|editor|viewer) are required")
    try:
        rec = add_project_member(user_id, ctx.project_id, role)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500] if exc.response else str(exc)
        raise HTTPException(400, f"Failed to add member: {detail}")
    return {"id": rec["id"], "userId": user_id, "role": role}


@router.put("/projects/{pid}/members/{member_id}")
async def update_member_role(member_id: str, body: dict, ctx: ProjectAdminDep) -> dict:
    """Update a member's role."""
    from automail.db.pocketbase.client import update_project_member_role
    _require_ctx_capability(ctx, "canManageMembers")
    role = body.get("role", "").strip()
    if role not in ("admin", "editor", "viewer"):
        raise HTTPException(400, "Valid role (admin|editor|viewer) is required")
    update_project_member_role(member_id, role)
    return {"status": "ok"}


@router.delete("/projects/{pid}/members/{member_id}")
async def remove_member(member_id: str, ctx: ProjectAdminDep) -> dict:
    """Remove a member from a project."""
    from automail.db.pocketbase.client import remove_project_member
    _require_ctx_capability(ctx, "canManageMembers")
    remove_project_member(member_id)
    return {"status": "deleted"}


# ──────────────────────────────────────────────────────────────────────────────
# Publish (draft → live) — project-scoped
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/projects/{pid}/publish")
async def publish_project(ctx: ProjectAdminDep) -> dict:
    """Copy draft config + intents to live for a project."""
    _require_ctx_capability(ctx, "canPublish")
    do_publish(ctx.project_id, tenant_id=ctx.tenant_id)
    return {"status": "ok"}


@router.get("/projects/{pid}/publish/status")
async def publish_status(ctx: ProjectViewerDep) -> dict:
    """Return whether draft differs from live for a project."""
    return {"hasUnpublishedChanges": has_unpublished_changes(ctx.project_id, tenant_id=ctx.tenant_id)}
