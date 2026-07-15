"""One-time PocketBase bootstrap migrations."""

import logging
from typing import Any

import httpx

from automail.db.pocketbase.bootstrap_common import (
    PB_ADMIN_EMAIL,
    PB_ADMIN_PASSWORD,
    PB_URL,
    _authenticate_superuser,
)

logger = logging.getLogger(__name__)


def migrate_project_config_to_tenant(
    *,
    pb_url: str | None = None,
    pb_admin_email: str | None = None,
    pb_admin_password: str | None = None,
) -> None:
    """One-time migration: copy org identity + LLM settings from the first
    project's live config to the tenant record in PocketBase.

    Only runs if the tenant's org_name is still empty (i.e. the migration
    hasn't happened yet).  Safe to call on every startup.
    """
    resolved_pb_url = (pb_url or PB_URL).rstrip("/")
    resolved_email = (pb_admin_email if pb_admin_email is not None else PB_ADMIN_EMAIL).strip()
    resolved_password = pb_admin_password if pb_admin_password is not None else PB_ADMIN_PASSWORD

    if not resolved_email or not resolved_password:
        return

    try:
        from automail.core.config import read_config
        from automail.pipeline.drafts import ensure_draft_exists, get_live_source

        with httpx.Client(timeout=10.0) as client:
            token = _authenticate_superuser(client, resolved_pb_url, resolved_email, resolved_password)

            # List all tenants
            resp = client.get(
                f"{resolved_pb_url}/api/collections/tenants/records",
                headers={"Authorization": f"Bearer {token}"},
                params={"perPage": 100},
            )
            resp.raise_for_status()
            tenants = resp.json().get("items", [])

            for tenant in tenants:
                # Skip tenants that already have org settings populated
                if tenant.get("org_name"):
                    continue

                tenant_id = tenant["id"]

                # Find the first project belonging to this tenant
                resp = client.get(
                    f"{resolved_pb_url}/api/collections/projects/records",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"filter": f"tenant='{tenant_id}'", "perPage": 1, "sort": "created"},
                )
                resp.raise_for_status()
                projects = resp.json().get("items", [])
                if not projects:
                    continue

                project_id = projects[0]["id"]

                # Try to read the project's config
                try:
                    ensure_draft_exists(project_id, tenant_id=tenant_id)
                    live_source = get_live_source(project_id, tenant_id=tenant_id)
                    config = read_config(config_path=live_source)
                except Exception:
                    continue

                # Migrate org identity + LLM settings to tenant
                patch_data: dict[str, Any] = {}
                if config.org_name:
                    patch_data["org_name"] = config.org_name
                if config.org_description:
                    patch_data["org_description"] = config.org_description
                if config.llm_provider:
                    patch_data["llm_provider"] = config.llm_provider
                if config.llm_model:
                    patch_data["llm_model"] = config.llm_model
                if config.llm_api_key:
                    patch_data["llm_api_key"] = config.llm_api_key
                if config.llm_custom_base_url:
                    patch_data["llm_custom_base_url"] = config.llm_custom_base_url
                if config.llm_custom_model:
                    patch_data["llm_custom_model"] = config.llm_custom_model

                if patch_data:
                    client.patch(
                        f"{resolved_pb_url}/api/collections/tenants/records/{tenant_id}",
                        headers={"Authorization": f"Bearer {token}"},
                        json=patch_data,
                    )
                    logger.info(
                        "Migrated org/LLM settings from project %s to tenant %s",
                        project_id, tenant_id,
                    )
    except Exception as exc:
        logger.warning("Project→tenant config migration failed (non-fatal): %s", exc)
