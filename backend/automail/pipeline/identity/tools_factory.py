"""Factory for loading the identity tool definition from project config.

The tool config is a single dict stored under the "tool" key in project config.
If no tool is configured (tool is None or missing required fields) an empty list
is returned and the identity phase is skipped.

URL templates, header values, and body values may reference:
  - {sender_email}  — substituted per-call with the email sender address
  - {SECRET_NAME}   — resolved from tenant/project secrets at load time
"""
import logging
from typing import Any

from automail.core.runtime_secrets import load_runtime_secrets
from automail.integrations.http_tool import (  # noqa: F401 – re-exported
    ToolDefinition,
    _resolve_env_vars,
)

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = {"name", "description", "method", "urlTemplate"}


def load_tool_definitions(
    config_path: Any = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> list[ToolDefinition]:
    """Load the identity tool definition from project config.

    Returns a single-element list if a tool is configured, or an empty list
    if no tool is set (identity phase will be skipped).
    """
    from automail.core.config import read_config
    config = read_config(config_path=config_path)

    raw: dict[str, Any] | None = config.tool
    if not raw:
        logger.info("No identity tool configured — skipping identity phase")
        return []

    url_template = raw.get("urlTemplate", "")
    missing = (_REQUIRED_FIELDS - raw.keys()) | ({"urlTemplate"} if not url_template else set())
    if missing:
        logger.warning("Tool config missing required fields: %s — skipping", sorted(missing))
        return []

    secrets = load_runtime_secrets(tenant_id, project_id)

    headers_value = raw.get("headers")
    body_value = raw.get("body")
    env_vars_value = raw.get("envVars")
    input_schema_value = raw.get("inputSchema")

    raw_headers: dict[str, Any] = headers_value if isinstance(headers_value, dict) else {}
    raw_body: dict[str, Any] = body_value if isinstance(body_value, dict) else {}
    raw_env_vars: list[Any] = env_vars_value if isinstance(env_vars_value, list) else []
    raw_input_schema: list[Any] = input_schema_value if isinstance(input_schema_value, list) else []

    resolved_headers = {
        k: _resolve_env_vars(v, secrets) if isinstance(v, str) else v
        for k, v in raw_headers.items()
    }
    resolved_body = {
        k: _resolve_env_vars(v, secrets) if isinstance(v, str) else v
        for k, v in raw_body.items()
    }
    resolved_url = _resolve_env_vars(str(url_template), secrets)

    tool = ToolDefinition(
        name=str(raw["name"]),
        description=str(raw["description"]),
        method=str(raw["method"]).upper(),
        url_template=resolved_url,
        headers=resolved_headers,
        body=resolved_body,
        env_vars=[str(item) for item in raw_env_vars],
        input_schema=[item for item in raw_input_schema if isinstance(item, dict)],
    )
    logger.info("Loaded identity tool: %s", tool.name)
    return [tool]
