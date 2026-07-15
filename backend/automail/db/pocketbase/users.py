"""PocketBase user persistence."""

from typing import Any, Optional

import httpx

from automail.core.language import normalize_language
from automail.db.pocketbase.base import PB_URL, _delete, _escape_pb, _first, _get, _list_all, _patch, _post, generate_id


def check_email_exists(email: str) -> bool:
    """Check whether a user with the given email already exists."""
    rec = _first("users", f"email='{_escape_pb(email)}'")
    return rec is not None


def get_user_by_email(email: str) -> Optional[dict]:
    """Return the full user record for *email*, or None if not found."""
    return _first("users", f"email='{_escape_pb(email)}'")


def get_user_display_name(email: str, tenant_id: str | None = None) -> str | None:
    """Return a user's configured display name for prompt personalization."""
    record = get_user_by_email(email.strip().lower())
    if not record:
        return None
    if tenant_id and record.get("tenant") != tenant_id:
        return None
    name = str(record.get("name") or "").strip()
    return name or None


def patch_user_record(user_id: str, data: dict[str, Any]) -> dict:
    """Patch a PocketBase user record."""
    return _patch(f"/api/collections/users/records/{user_id}", data)


def set_user_tenant(user_id: str, tenant_id: str) -> dict:
    """Move a user to a different tenant."""
    return _patch(f"/api/collections/users/records/{user_id}", {"tenant": tenant_id})

def create_signup_user(
    email: str, password: str, tenant_id: str
) -> dict:
    """Create the first admin user for a self-service signup.

    Unlike create_pb_user (admin-provisioned), this user chose their own
    password so must_change_password is False.  Signup users are always root.

    The user is created with verified=False — they must confirm their email
    via the verification link before they can log in.
    """
    return _post("/api/collections/users/records", {
        "id": generate_id(),
        "email": email,
        "password": password,
        "passwordConfirm": password,
        "tenant": tenant_id,
        "is_root": True,
        "language": "en",
        "must_change_password": False,
        "verified": False,
    })


def create_onprem_signup_user(
    email: str, password: str, tenant_id: str
) -> dict:
    """Create a regular user for on-prem self-registration.

    Unlike SaaS signup, the user is NOT root (they join an existing org)
    and is automatically verified (no email confirmation on on-prem).
    """
    return _post("/api/collections/users/records", {
        "id": generate_id(),
        "email": email,
        "password": password,
        "passwordConfirm": password,
        "tenant": tenant_id,
        "is_root": False,
        "language": "en",
        "must_change_password": False,
        "verified": True,
    })


def list_tenant_users(tenant_id: str) -> list[dict]:
    """List all users belonging to a tenant."""
    records = _list_all("users", f"tenant='{_escape_pb(tenant_id)}'", sort="-created")
    return [
        {
            "id": r["id"],
            "email": r.get("email", ""),
            "name": r.get("name", ""),
            "language": normalize_language(r.get("language")),
            "isAdmin": bool(r.get("is_root", False)),
            "isRoot": bool(r.get("is_root", False)),
            "mustChangePassword": r.get("must_change_password", False),
            "passwordLoginEnabled": bool(r.get("password_login_enabled", False)),
            "defaultProject": r.get("default_project") or None,
            "created": r.get("created", ""),
        }
        for r in records
    ]


def get_user_record(user_id: str) -> Optional[dict]:
    """Return a PocketBase user record by ID, or None when it doesn't exist."""
    try:
        return _get(f"/api/collections/users/records/{user_id}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise


def create_pb_user(
    email: str, password: str, tenant_id: str, is_root: bool = False
) -> dict:
    """Create a user in PocketBase (admin-provisioned, must_change_password=true)."""
    return _post("/api/collections/users/records", {
        "id": generate_id(),
        "email": email,
        "password": password,
        "passwordConfirm": password,
        "tenant": tenant_id,
        "is_root": is_root,
        "language": "en",
        "must_change_password": True,
        "password_login_enabled": True,
        "verified": True,
    })


def delete_pb_user(user_id: str) -> bool:
    """Delete a user from PocketBase."""
    return _delete(f"/api/collections/users/records/{user_id}")


def update_user_password(user_id: str, new_password: str) -> dict:
    """Update a user's password and clear must_change_password flag."""
    return _patch(f"/api/collections/users/records/{user_id}", {
        "password": new_password,
        "passwordConfirm": new_password,
        "must_change_password": False,
    })


def set_user_verified(user_id: str) -> dict:
    """Mark a user as email-verified in PocketBase."""
    return _patch(f"/api/collections/users/records/{user_id}", {
        "verified": True,
    })


def validate_pb_token(pb_token: str) -> dict:
    """Validate a PocketBase user token and return the user record.

    Calls PocketBase's auth-refresh endpoint with the provided token.
    Raises httpx.HTTPStatusError on invalid / expired tokens.
    """
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{PB_URL}/api/collections/users/auth-refresh",
            headers={"Authorization": f"Bearer {pb_token}"},
        )
    resp.raise_for_status()
    return resp.json()

def get_is_root(user_record: dict) -> bool:
    """Read the root flag from a user record."""
    return bool(user_record.get("is_root", False))

def get_user_default_project(user_id: str) -> Optional[str]:
    """Return the user's default project ID, or None if not set."""
    record = get_user_record(user_id)
    if record is None:
        return None
    return record.get("default_project") or None


def set_user_default_project(user_id: str, project_id: str | None) -> dict:
    """Set (or clear) the user's default project."""
    return _patch(f"/api/collections/users/records/{user_id}", {
        "default_project": project_id or "",
    })
