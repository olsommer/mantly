"""PocketBase tenant and project secrets persistence."""

from automail.db.pocketbase.base import _get, _patch


def get_tenant_secrets(tenant_id: str) -> dict[str, str]:
    """Return the tenant-level secrets map (key → value)."""
    rec = _get(f"/api/collections/tenants/records/{tenant_id}")
    return rec.get("secrets") or {}


def update_tenant_secrets(tenant_id: str, secrets: dict[str, str]) -> dict[str, str]:
    """Replace the tenant-level secrets map and return the new value."""
    _patch(f"/api/collections/tenants/records/{tenant_id}", {"secrets": secrets})
    return get_tenant_secrets(tenant_id)


def get_project_secrets(project_id: str) -> dict[str, str]:
    """Return the project-level secrets map (key → value)."""
    rec = _get(f"/api/collections/projects/records/{project_id}")
    return rec.get("secrets") or {}


def update_project_secrets(project_id: str, secrets: dict[str, str]) -> dict[str, str]:
    """Replace the project-level secrets map and return the new value."""
    _patch(f"/api/collections/projects/records/{project_id}", {"secrets": secrets})
    return get_project_secrets(project_id)


def get_merged_secrets(tenant_id: str, project_id: str) -> dict[str, str]:
    """Return secrets merged from tenant + project (project overrides tenant)."""
    tenant_secrets = get_tenant_secrets(tenant_id)
    project_secrets = get_project_secrets(project_id)
    return {**tenant_secrets, **project_secrets}
