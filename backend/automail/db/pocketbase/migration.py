"""One-time data migration: pre-projects → projects architecture.

On startup, this module checks whether each tenant already has at least one
project.  For tenants with no projects it:

    1. Creates a "Default" project in PocketBase.
    2. Creates project_members records for all tenant users (root → admin role,
       others → viewer).
    3. Patches existing PB records (chats, eval_sets, eval_runs) to reference
       the new project.

The migration is **idempotent** — running it multiple times is safe.
"""
import logging
from typing import Any

from automail.db.pocketbase.client import (
    _escape_pb,
    _list_all,
    _patch,
    add_project_member,
    create_project,
    get_is_root,
    list_tenant_projects,
)

logger = logging.getLogger(__name__)


def migrate_to_projects() -> dict[str, Any]:
    """Run the full pre-projects → projects migration.

    Returns a summary dict with counts of what was done.
    """
    summary: dict[str, Any] = {
        "tenants_migrated": 0,
        "projects_created": 0,
        "memberships_created": 0,
        "records_patched": 0,
    }

    # Find all tenants
    tenants = _list_all("tenants", sort="")
    if not tenants:
        logger.info("No tenants found — skipping projects migration")
        return summary

    for tenant in tenants:
        tenant_id = tenant["id"]
        tenant_name = tenant.get("name", tenant_id)

        # Check if tenant already has projects
        existing_projects = list_tenant_projects(tenant_id)
        if existing_projects:
            logger.debug("Tenant '%s' already has %d project(s) — skipping", tenant_name, len(existing_projects))
            continue

        logger.info("Migrating tenant '%s' (%s) to projects architecture", tenant_name, tenant_id)

        # 1. Create Default project
        project_rec = create_project("Default", f"Default project for {tenant_name}", tenant_id)
        project_id = project_rec["id"]
        summary["projects_created"] += 1
        logger.info("Created Default project '%s' for tenant '%s'", project_id, tenant_name)

        # 2. Create project memberships for all users
        users = _list_all("users", f"tenant='{_escape_pb(tenant_id)}'")
        for user in users:
            user_id = user["id"]

            # Create project membership
            is_root = get_is_root(user)
            role = "admin" if is_root else "viewer"
            try:
                add_project_member(user_id, project_id, role)
                summary["memberships_created"] += 1
            except Exception as exc:
                # Might fail if membership already exists (unique constraint)
                logger.debug("Skipped membership for user %s: %s", user_id, exc)

        # 3. Patch existing records to reference the new project
        for collection in ("chats", "eval_sets", "eval_runs"):
            try:
                records = _list_all(
                    collection,
                    f"tenant='{_escape_pb(tenant_id)}' && project=''",
                )
                for rec in records:
                    try:
                        _patch(
                            f"/api/collections/{collection}/records/{rec['id']}",
                            {"project": project_id},
                        )
                        summary["records_patched"] += 1
                    except Exception as exc:
                        logger.warning(
                            "Failed to patch %s record %s: %s", collection, rec["id"], exc
                        )
            except Exception as exc:
                # Collection might not exist or filter might fail for empty project field
                logger.debug("Skipped patching %s for tenant %s: %s", collection, tenant_id, exc)

        summary["tenants_migrated"] += 1

    if summary["tenants_migrated"]:
        logger.info("Projects migration complete: %s", summary)
    else:
        logger.info("Projects migration: nothing to do — all tenants already have projects")

    return summary
