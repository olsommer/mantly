"""Admin tenant user and current-user endpoints."""

import httpx
from fastapi import APIRouter, HTTPException

from automail.api.admin.deps import AuthDep, RootAuthDep, _require_auth_capability
from automail.core.brand import get_brand
from automail.core.language import normalize_language, validate_language
from automail.db.pocketbase.client import (
    create_pb_user,
    delete_pb_user,
    get_user_projects,
    get_user_record,
    list_tenant_projects,
    list_tenant_users,
    patch_user_record,
    set_user_default_project,
)

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────
# Users (tenant-level — root only)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(auth: RootAuthDep) -> list[dict]:
    """List all users in the admin's tenant."""
    tenant_id = auth.tenant_id
    _require_auth_capability(auth, "canManageMembers")
    if not tenant_id:
        return []  # REQUIRE_AUTH=false dev mode
    return list_tenant_users(tenant_id)


@router.post("/users")
async def create_user_endpoint(body: dict, auth: RootAuthDep) -> dict:
    """Create a new user (admin-provisioned, must change password on first login).

    On-prem only.  SaaS tenants should use ``POST /users/add-by-email`` instead.
    """
    from automail.billing.config import IS_SAAS
    from automail.billing.usage import check_limit
    tenant_id = auth.tenant_id
    _require_auth_capability(auth, "canManageMembers")
    if IS_SAAS:
        raise HTTPException(400, "Use the invite-by-email flow to add team members in SaaS mode")
    email = body.get("email", "").strip()
    password = body.get("password", "").strip()
    is_root = body.get("isAdmin", False) or body.get("isRoot", False)
    if not email or not password:
        raise HTTPException(400, "email and password are required")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if not tenant_id:
        raise HTTPException(400, "Cannot create users when REQUIRE_AUTH is disabled")
    check_limit(tenant_id, "users")
    # Enforce license seat limit (on-prem only)
    from automail.billing.license import get_license_state, is_license_required
    if is_license_required():
        license_state = get_license_state()
        if license_state.max_users is not None:
            current_users = list_tenant_users(tenant_id)
            if len(current_users) >= license_state.max_users:
                raise HTTPException(
                    403,
                    f"License limit reached: maximum {license_state.max_users} users. "
                    f"Contact {get_brand().support_email} to upgrade your license.",
                )
    try:
        rec = create_pb_user(email, password, tenant_id, is_root)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500] if exc.response else str(exc)
        raise HTTPException(400, f"Failed to create user: {detail}")
    from automail.billing.addons import sync_stripe_addons_best_effort
    sync_stripe_addons_best_effort(tenant_id)
    return {"id": rec["id"], "email": rec.get("email", email)}


@router.post("/users/add-by-email")
async def add_user_by_email_endpoint(body: dict, auth: RootAuthDep) -> dict:
    """Add an existing user to this tenant by email (SaaS only).

    The target user must have already created their own account via the
    signup page.  This endpoint moves them from their current tenant into
    the caller's tenant.
    """
    from automail.billing.config import IS_SAAS
    from automail.billing.usage import check_limit
    tenant_id = auth.tenant_id
    _require_auth_capability(auth, "canManageMembers")
    if not IS_SAAS:
        raise HTTPException(404, "Not found")

    email = body.get("email", "").strip().lower()
    if not email:
        raise HTTPException(400, "Email is required")

    check_limit(tenant_id, "users")

    from automail.db.pocketbase.client import get_user_by_email, set_user_tenant
    user = get_user_by_email(email)
    if user is None:
        raise HTTPException(
            404,
            "No account found with this email. "
            "The user needs to sign up first at the login page.",
        )

    if user.get("tenant") == tenant_id:
        raise HTTPException(409, "This user is already in your organisation.")

    # Move user to the admin's tenant
    set_user_tenant(user["id"], tenant_id)
    from automail.billing.addons import sync_stripe_addons_best_effort
    sync_stripe_addons_best_effort(tenant_id)
    return {"id": user["id"], "email": user.get("email", email)}


@router.delete("/users/{user_id}")
async def delete_user_endpoint(user_id: str, auth: RootAuthDep) -> dict:
    """Delete a user from PocketBase."""
    tenant_id = auth.tenant_id
    _require_auth_capability(auth, "canManageMembers")
    if not tenant_id:
        raise HTTPException(400, "Cannot delete users when REQUIRE_AUTH is disabled")

    user_record = get_user_record(user_id)
    if not user_record or user_record.get("tenant") != tenant_id:
        raise HTTPException(404, "User not found")

    delete_pb_user(user_id)
    from automail.billing.addons import sync_stripe_addons_best_effort
    sync_stripe_addons_best_effort(tenant_id)
    return {"status": "deleted"}


@router.patch("/users/{user_id}/password-login")
async def update_user_password_login_endpoint(user_id: str, body: dict, auth: RootAuthDep) -> dict:
    """Enable or disable password login for a user."""
    tenant_id = auth.tenant_id
    _require_auth_capability(auth, "canManageMembers")
    if not tenant_id:
        raise HTTPException(400, "Cannot update users when REQUIRE_AUTH is disabled")

    user_record = get_user_record(user_id)
    if not user_record or user_record.get("tenant") != tenant_id:
        raise HTTPException(404, "User not found")

    enabled = bool(body.get("enabled", False))
    patch_user_record(user_id, {"password_login_enabled": enabled})
    return {"id": user_id, "passwordLoginEnabled": enabled}


@router.get("/users/{user_id}/default-project")
async def get_default_project(user_id: str, auth: RootAuthDep) -> dict:
    """Get a user's default project."""
    tenant_id = auth.tenant_id
    _require_auth_capability(auth, "canManageMembers")
    if not tenant_id:
        return {"defaultProject": None}
    user_record = get_user_record(user_id)
    if not user_record or user_record.get("tenant") != tenant_id:
        raise HTTPException(404, "User not found")
    project_id = user_record.get("default_project") or None
    return {"defaultProject": project_id}


@router.put("/users/{user_id}/default-project")
async def update_default_project(user_id: str, body: dict, auth: RootAuthDep) -> dict:
    """Set (or clear) a user's default project."""
    tenant_id = auth.tenant_id
    _require_auth_capability(auth, "canManageMembers")
    if not tenant_id:
        raise HTTPException(400, "Cannot update users when REQUIRE_AUTH is disabled")
    user_record = get_user_record(user_id)
    if not user_record or user_record.get("tenant") != tenant_id:
        raise HTTPException(404, "User not found")
    project_id = body.get("projectId") or None
    # Validate project belongs to tenant
    if project_id:
        projects = list_tenant_projects(tenant_id)
        if not any(p["id"] == project_id for p in projects):
            raise HTTPException(400, "Project not found in tenant")
    set_user_default_project(user_id, project_id)
    return {"defaultProject": project_id}


@router.get("/me")
async def get_current_user_profile(auth: AuthDep) -> dict:
    """Return the authenticated user's profile including default project."""
    if not auth.user_id:
        return {
            "id": "",
            "email": "",
            "name": "",
            "language": "en",
            "defaultProject": None,
            "projects": [],
            "branding": {"primaryColor": ""},
        }
    user_record = get_user_record(auth.user_id)
    if not user_record:
        raise HTTPException(404, "User not found")
    projects = get_user_projects(auth.user_id)
    from automail.db.pocketbase.client import get_tenant_settings
    tenant_settings = get_tenant_settings(auth.tenant_id)
    return {
        "id": auth.user_id,
        "email": auth.email,
        "name": user_record.get("name") or "",
        "language": normalize_language(user_record.get("language")),
        "defaultProject": user_record.get("default_project") or None,
        "projects": projects,
        "branding": {
            "primaryColor": tenant_settings.get("addinPrimaryColor", ""),
        },
    }


@router.put("/me")
async def update_current_user_profile(body: dict, auth: AuthDep) -> dict:
    """Let the current user update their own profile."""
    if not auth.user_id:
        raise HTTPException(400, "Cannot update profile when REQUIRE_AUTH is disabled")

    user_record = get_user_record(auth.user_id)
    if not user_record:
        raise HTTPException(404, "User not found")

    updates: dict[str, str] = {}

    if "name" in body:
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name is required")
        if len(name) > 120:
            raise HTTPException(status_code=400, detail="Name must be at most 120 characters")
        updates["name"] = name

    if "language" in body:
        language = validate_language(body.get("language"))
        if language is None:
            raise HTTPException(status_code=400, detail="Language must be en or de")
        updates["language"] = language

    if updates:
        patch_user_record(auth.user_id, updates)

    return {
        "id": auth.user_id,
        "email": auth.email,
        "name": updates.get("name") or user_record.get("name") or "",
        "language": updates.get("language") or normalize_language(user_record.get("language")),
    }


@router.put("/me/default-project")
async def update_own_default_project(body: dict, auth: AuthDep) -> dict:
    """Let the current user set their own default project."""
    if not auth.user_id:
        raise HTTPException(400, "Cannot update profile when REQUIRE_AUTH is disabled")
    project_id = body.get("projectId") or None
    # Validate user is a member of the project
    if project_id:
        projects = get_user_projects(auth.user_id)
        if not any(p["id"] == project_id for p in projects):
            raise HTTPException(400, "You are not a member of that project")
    set_user_default_project(auth.user_id, project_id)
    return {"defaultProject": project_id}
