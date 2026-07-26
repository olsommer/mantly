"""Shared FastAPI dependencies for admin routers."""

import re
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from automail.core.auth import (
    ProjectContext,
    TokenPayload,
    require_authenticated,
    require_root,
    resolve_project_context,
)
from automail.core.capabilities import require_capability

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _normalize_hex_color(value: object) -> str | None:
    if value is None:
        return None
    color = str(value).strip()
    if not color:
        return ""
    if not _HEX_COLOR_RE.match(color):
        raise HTTPException(status_code=400, detail="Primary color must use #RRGGBB format")
    return color.upper()


def require_admin(request: Request) -> str:
    """FastAPI dependency: require a valid JWT with is_root=True."""
    return require_root(request)


AdminDep = Annotated[str, Depends(require_admin)]


def _project_viewer(request: Request, pid: str) -> ProjectContext:
    return resolve_project_context(request, pid, min_role="viewer")


def _project_editor(request: Request, pid: str) -> ProjectContext:
    return resolve_project_context(request, pid, min_role="editor")


def _project_admin(request: Request, pid: str) -> ProjectContext:
    return resolve_project_context(request, pid, min_role="admin")


def _root_auth(request: Request) -> TokenPayload:
    payload = require_authenticated(request)
    if payload.user_id and not (payload.is_root or payload.is_platform_admin):
        raise HTTPException(status_code=403, detail="Root access required")
    return payload


def _platform_admin_auth(request: Request) -> TokenPayload:
    """Require a platform administrator for global, cross-tenant operations."""
    payload = require_authenticated(request)
    if not payload.user_id or not payload.is_platform_admin:
        raise HTTPException(
            status_code=403,
            detail="Platform administrator access required",
        )
    return payload


def _require_ctx_capability(ctx: ProjectContext, capability: str) -> None:
    if not ctx.tenant_id:
        return
    require_capability(
        ctx.tenant_id,
        capability,
        is_platform_admin=ctx.is_platform_admin,
    )


def _require_auth_capability(auth: TokenPayload, capability: str) -> None:
    if not auth.tenant_id:
        return
    require_capability(
        auth.tenant_id,
        capability,
        is_platform_admin=auth.is_platform_admin,
    )


ProjectViewerDep = Annotated[ProjectContext, Depends(_project_viewer)]
ProjectEditorDep = Annotated[ProjectContext, Depends(_project_editor)]
ProjectAdminDep = Annotated[ProjectContext, Depends(_project_admin)]
RootDep = Annotated[str, Depends(require_root)]
RootAuthDep = Annotated[TokenPayload, Depends(_root_auth)]
PlatformAdminDep = Annotated[TokenPayload, Depends(_platform_admin_auth)]
AuthDep = Annotated[TokenPayload, Depends(require_authenticated)]
