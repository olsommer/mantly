"""JWT utilities and role-based access control for FastAPI.

Password hashing and user/tenant management have moved to PocketBase.
This module handles JWT creation, decoding, and FastAPI dependencies for
authentication and authorization.

Auth is opt-in: set REQUIRE_AUTH=true to enforce JWT on all endpoints.
When REQUIRE_AUTH is false (default), all endpoints are accessible without
a token for on-premise bootstrap and local development.

Role hierarchy (highest to lowest):
    root   — org-wide superadmin, manages all projects and users
    admin  — project-level admin, manages project settings and members
    editor — can edit intents, tools, config within a project
    viewer — read-only access to admin panel for a project
"""
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# --- Configuration ---
REQUIRE_AUTH: bool = os.getenv("REQUIRE_AUTH", "false").lower() == "true"
JWT_SECRET: str = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72  # 3 days

# Ordered from most privileged to least — used for min-role comparisons.
ROLE_HIERARCHY = ("root", "admin", "editor", "viewer")


@dataclass(slots=True)
class TokenPayload:
    """Decoded JWT claims."""
    user_id: str
    email: str
    tenant_id: str
    is_root: bool
    is_platform_admin: bool = False
    tenant_account_type: str = "normal"


@dataclass(slots=True)
class ProjectContext:
    """Resolved auth context for a project-scoped request."""
    tenant_id: str
    user_id: str
    project_id: str
    role: str  # 'root' | 'admin' | 'editor' | 'viewer'
    is_platform_admin: bool = False


# --- JWT ---

def create_token(
    user_id: str,
    email: str,
    tenant_id: str,
    is_root: bool,
    tenant_name: str = "",
    *,
    is_platform_admin: bool = False,
    tenant_account_type: str = "normal",
) -> str:
    """Create a signed FastAPI JWT for the given user."""
    payload = {
        "sub": user_id,
        "email": email,
        "tenant_id": tenant_id,
        "is_root": is_root,
        "is_platform_admin": is_platform_admin,
        "tenant_account_type": tenant_account_type,
        "tenant_name": tenant_name,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises jwt.InvalidTokenError on failure."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# --- Helpers ---

def _extract_payload(request: Request) -> TokenPayload:
    """Extract and validate the JWT from a request's Authorization header.

    Raises HTTPException 401 on missing/invalid/expired tokens.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    raw = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = decode_token(raw)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    return TokenPayload(
        user_id=payload.get("sub", ""),
        email=payload.get("email", ""),
        tenant_id=payload.get("tenant_id", ""),
        is_root=bool(payload.get("is_root", False)),
        is_platform_admin=bool(payload.get("is_platform_admin", False)),
        tenant_account_type=str(payload.get("tenant_account_type") or "normal"),
    )


def _role_level(role: str) -> int:
    """Return numeric level for a role (lower = more privileged)."""
    try:
        return ROLE_HIERARCHY.index(role)
    except ValueError:
        return len(ROLE_HIERARCHY)  # unknown role → least privileged


def _has_min_role(actual: str, minimum: str) -> bool:
    """Return True if ``actual`` role is at least as privileged as ``minimum``."""
    return _role_level(actual) <= _role_level(minimum)


# --- FastAPI dependencies ---

def get_current_tenant(request: Request) -> Optional[str]:
    """Extract tenant_id from JWT in Authorization header.

    - If REQUIRE_AUTH is False: always returns None (unauthenticated access OK).
    - If REQUIRE_AUTH is True: raises 401 if token is missing or invalid.
    """
    if not REQUIRE_AUTH:
        return None

    payload = _extract_payload(request)
    return payload.tenant_id


def get_token_payload(request: Request) -> Optional[TokenPayload]:
    """Extract the full token payload from a request.

    Returns None when REQUIRE_AUTH is False.
    """
    if not REQUIRE_AUTH:
        return None
    return _extract_payload(request)


def require_root(request: Request) -> str:
    """FastAPI dependency: require a valid JWT with is_root=True.

    Returns tenant_id.  When REQUIRE_AUTH is False this is a no-op.
    """
    if not REQUIRE_AUTH:
        return ""

    payload = _extract_payload(request)
    if not payload.is_root:
        raise HTTPException(status_code=403, detail="Root access required")
    return payload.tenant_id


def require_authenticated(request: Request) -> TokenPayload:
    """FastAPI dependency: require any valid JWT.

    Returns the full TokenPayload.  When REQUIRE_AUTH is False, returns a
    dummy payload with empty strings.
    """
    if not REQUIRE_AUTH:
        return TokenPayload(user_id="", email="", tenant_id="", is_root=False)
    return _extract_payload(request)


def resolve_project_context(
    request: Request,
    project_id: str,
    min_role: str = "viewer",
) -> ProjectContext:
    """Resolve the caller's role in a project and enforce minimum role.

    Root users implicitly have the ``root`` role in every project (bypasses
    membership lookup).  Non-root users must have a project_members record.

    Raises:
        HTTPException 401 — missing/invalid token
        HTTPException 403 — insufficient role
        HTTPException 404 — project not found or user not a member
    """
    if not REQUIRE_AUTH:
        return ProjectContext(
            tenant_id="",
            user_id="",
            project_id=project_id,
            role="root",
            is_platform_admin=False,
        )

    payload = _extract_payload(request)

    # Root/platform admins have implicit root role on all projects in their tenant
    if payload.is_root or payload.is_platform_admin:
        # Verify project belongs to the user's tenant
        from automail.db.pocketbase.client import get_project
        project = get_project(project_id)
        if project is None or project.get("tenant") != payload.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")
        return ProjectContext(
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            project_id=project_id,
            role="root",
            is_platform_admin=payload.is_platform_admin,
        )

    # Non-root: look up membership
    from automail.db.pocketbase.client import get_project, get_user_project_role
    project = get_project(project_id)
    if project is None or project.get("tenant") != payload.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    role = get_user_project_role(payload.user_id, project_id)
    if role is None:
        raise HTTPException(status_code=403, detail="You are not a member of this project")

    if not _has_min_role(role, min_role):
        raise HTTPException(
            status_code=403,
            detail=f"This action requires at least '{min_role}' role in this project",
        )

    return ProjectContext(
        tenant_id=payload.tenant_id,
        user_id=payload.user_id,
        project_id=project_id,
        role=role,
        is_platform_admin=payload.is_platform_admin,
    )
