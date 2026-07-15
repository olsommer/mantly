"""Runtime secret resolution for tool and provider placeholders."""
from __future__ import annotations

import logging
from typing import Any

from automail.integrations.http_tool import _resolve_env_vars

logger = logging.getLogger(__name__)


def load_runtime_secrets(
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, str] | None:
    """Fetch merged tenant/project secrets.

    Project secrets override tenant secrets. Returning ``None`` lets
    ``_resolve_env_vars`` fall back to process env vars.
    """
    if not tenant_id and not project_id:
        return None
    try:
        if tenant_id and project_id:
            from automail.db.pocketbase.client import get_merged_secrets
            return get_merged_secrets(tenant_id, project_id)
        if tenant_id:
            from automail.db.pocketbase.client import get_tenant_secrets
            return get_tenant_secrets(tenant_id)
        if project_id:
            from automail.db.pocketbase.client import get_project_secrets
            return get_project_secrets(project_id)
    except Exception:
        logger.warning("Failed to load runtime secrets", exc_info=True)
    return {}


def resolve_secret_placeholders(value: Any, secrets: dict[str, str] | None) -> Any:
    """Resolve ``{SECRET_NAME}`` placeholders inside strings, dicts, and lists."""
    if isinstance(value, str):
        return _resolve_env_vars(value, secrets)
    if isinstance(value, dict):
        return {key: resolve_secret_placeholders(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_secret_placeholders(item, secrets) for item in value]
    return value
