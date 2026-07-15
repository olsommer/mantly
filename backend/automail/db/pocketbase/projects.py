"""PocketBase project and project-member persistence."""

from typing import Any, Optional

import httpx

from automail.db.pocketbase.base import _delete, _escape_pb, _first, _get, _list_all, _patch, _post, generate_id
from automail.db.pocketbase.users import get_user_record


def create_project(name: str, description: str, tenant_id: str) -> dict:
    """Create a new project and return its full PocketBase record."""
    return _post("/api/collections/projects/records", {
        "id": generate_id(),
        "name": name,
        "description": description,
        "tenant": tenant_id,
    })


def get_project(project_id: str) -> Optional[dict]:
    """Return a project record by ID, or None if not found."""
    try:
        return _get(f"/api/collections/projects/records/{project_id}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise


def list_tenant_projects(tenant_id: str) -> list[dict]:
    """List all projects belonging to a tenant."""
    records = _list_all("projects", f"tenant='{_escape_pb(tenant_id)}'", sort="created")
    return [
        {
            "id": r["id"],
            "name": r.get("name", ""),
            "description": r.get("description", ""),
            "tenant": r.get("tenant", ""),
            "created": r.get("created", ""),
        }
        for r in records
    ]


def update_project(project_id: str, name: str | None = None, description: str | None = None) -> dict:
    """Update a project's name and/or description."""
    data: dict[str, Any] = {}
    if name is not None:
        data["name"] = name
    if description is not None:
        data["description"] = description
    return _patch(f"/api/collections/projects/records/{project_id}", data)


def delete_project(project_id: str) -> bool:
    """Delete a project. Returns True if found and deleted."""
    return _delete(f"/api/collections/projects/records/{project_id}")


# ── Project Members ───────────────────────────────────────────────────────────

def list_project_members(project_id: str) -> list[dict]:
    """List all members of a project with their roles."""
    records = _list_all(
        "project_members",
        f"project='{_escape_pb(project_id)}'",
        sort="created",
    )
    # Enrich with user email — fetch each user record
    result = []
    for r in records:
        user_id = r.get("user", "")
        user_rec = get_user_record(user_id) if user_id else None
        result.append({
            "id": r["id"],
            "userId": user_id,
            "email": user_rec.get("email", "") if user_rec else "",
            "isRoot": bool(user_rec.get("is_root", False)) if user_rec else False,
            "role": r.get("role", ""),
            "projectId": r.get("project", ""),
            "created": r.get("created", ""),
        })
    return result


def add_project_member(user_id: str, project_id: str, role: str) -> dict:
    """Add a user to a project with the given role (admin|editor|viewer).

    Raises httpx.HTTPStatusError if the membership already exists (unique index).
    """
    return _post("/api/collections/project_members/records", {
        "id": generate_id(),
        "user": user_id,
        "project": project_id,
        "role": role,
    })


def update_project_member_role(member_id: str, role: str) -> dict:
    """Update a project member's role."""
    return _patch(f"/api/collections/project_members/records/{member_id}", {"role": role})


def remove_project_member(member_id: str) -> bool:
    """Remove a project member. Returns True if found and deleted."""
    return _delete(f"/api/collections/project_members/records/{member_id}")


def get_user_project_role(user_id: str, project_id: str) -> Optional[str]:
    """Return the user's role in a project, or None if not a member."""
    rec = _first(
        "project_members",
        f"user='{_escape_pb(user_id)}' && project='{_escape_pb(project_id)}'",
    )
    return rec.get("role") if rec else None


def get_user_projects(user_id: str) -> list[dict]:
    """Return all projects the user is a member of (with roles).

    Each entry includes the project details and the user's role.
    """
    memberships = _list_all(
        "project_members",
        f"user='{_escape_pb(user_id)}'",
        sort="created",
    )
    result = []
    for m in memberships:
        project_id = m.get("project", "")
        project = get_project(project_id) if project_id else None
        if project:
            result.append({
                "id": project["id"],
                "name": project.get("name", ""),
                "description": project.get("description", ""),
                "tenant": project.get("tenant", ""),
                "role": m.get("role", ""),
                "membershipId": m["id"],
                "created": project.get("created", ""),
            })
    return result
