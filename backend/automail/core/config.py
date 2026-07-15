"""Admin configuration manager.

Reads and writes pipeline config from PocketBase project sources.
Explicit file paths are still accepted for tests and local tools.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

from pydantic import BaseModel

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from automail.pipeline.store import PipelineSource
else:
    PipelineSource = Any

ConfigSource: TypeAlias = Path | PipelineSource | None

# Mask prefix used for API keys returned to the frontend.
_KEY_MASK = "\u2022" * 6  # "••••••"


class AdminConfig(BaseModel):
    org_name: str = ""
    org_description: str = ""
    use_custom_org: bool = False       # True = use project-level org identity
    llm_model: str = ""
    llm_provider: str = "gemini"       # "managed" | "gemini" | "custom"
    llm_api_key: str = ""              # Provider API key (Gemini or custom)
    llm_custom_base_url: str = ""      # OpenAI-compatible base URL
    llm_custom_model: str = ""         # Model name for custom provider
    llm_billing_mode: str = "byok"     # "included" | "byok" | "mantly_managed"
    use_custom_llm: bool = False       # True = use project-level LLM settings
    identity_notes: str = ""
    tool: dict | None = None  # Single HTTP tool for the identity phase; None = skip lookup
    use_custom_security: bool = False  # True = use project-level security monitoring settings
    phishing_monitoring_enabled: bool = False
    prompt_injection_monitoring_enabled: bool = False

    model_config = {"populate_by_name": True}


def mask_api_key(key: str) -> str:
    """Return a masked version of an API key for safe display.

    Shows ``••••••<last4>`` if the key is long enough, or ``••••••`` for short
    keys.  Returns empty string for empty keys.
    """
    if not key:
        return ""
    if len(key) > 4:
        return _KEY_MASK + key[-4:]
    return _KEY_MASK


def is_masked(value: str) -> bool:
    """Return True if *value* looks like a masked API key (starts with dots)."""
    return value.startswith(_KEY_MASK)


def read_config(config_path: ConfigSource = None) -> AdminConfig:
    """Load project config from PocketBase or an explicit file path."""
    if config_path is None:
        return AdminConfig()

    if isinstance(config_path, Path):
        path = config_path
    else:
        from automail.pipeline.store import read_project_config

        return read_project_config(config_path)

    if not path.exists():
        logger.info("Config file not found at %s — using defaults", path)
        return AdminConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Support both camelCase (JSON) and snake_case keys
        normalized: dict[str, Any] = {
            "org_name": raw.get("orgName") or raw.get("org_name") or AdminConfig().org_name,
            "org_description": raw.get("orgDescription") or raw.get("org_description") or AdminConfig().org_description,
            "use_custom_org": raw.get("useCustomOrg", raw.get("use_custom_org", False)),
            "llm_model": raw.get("llmModel") or raw.get("llm_model") or AdminConfig().llm_model,
            "llm_provider": raw.get("llmProvider", raw.get("llm_provider", "gemini")),
            "llm_api_key": raw.get("llmApiKey", raw.get("llm_api_key", "")),
            "llm_custom_base_url": raw.get("llmCustomBaseUrl", raw.get("llm_custom_base_url", "")),
            "llm_custom_model": raw.get("llmCustomModel", raw.get("llm_custom_model", "")),
            "llm_billing_mode": raw.get("llmBillingMode", raw.get("llm_billing_mode", "byok")),
            "use_custom_llm": raw.get("useCustomLlm", raw.get("use_custom_llm", False)),
            "identity_notes": raw.get("identityNotes", raw.get("identity_notes", "")),
            "tool": raw.get("tool"),
            "use_custom_security": raw.get(
                "useCustomSecurity",
                raw.get(
                    "use_custom_security",
                    bool(
                        raw.get("phishingMonitoringEnabled", raw.get("phishing_monitoring_enabled", False))
                        or raw.get(
                            "promptInjectionMonitoringEnabled",
                            raw.get("prompt_injection_monitoring_enabled", False),
                        )
                    ),
                ),
            ),
            "phishing_monitoring_enabled": raw.get(
                "phishingMonitoringEnabled",
                raw.get("phishing_monitoring_enabled", False),
            ),
            "prompt_injection_monitoring_enabled": raw.get(
                "promptInjectionMonitoringEnabled",
                raw.get("prompt_injection_monitoring_enabled", False),
            ),
        }
        return AdminConfig(**normalized)
    except Exception as exc:
        logger.warning("Failed to parse config file (%s) — using defaults", exc)
        return AdminConfig()


def write_config(config: AdminConfig, config_path: ConfigSource = None) -> None:
    """Persist project config to PocketBase or an explicit file path."""
    if config_path is None:
        raise ValueError("config_path is required for file config writes")

    if isinstance(config_path, Path):
        path = config_path
    else:
        from automail.pipeline.store import write_project_config

        write_project_config(config_path, config)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "orgName": config.org_name,
        "orgDescription": config.org_description,
        "useCustomOrg": config.use_custom_org,
        "llmModel": config.llm_model,
        "llmProvider": config.llm_provider,
        "llmApiKey": config.llm_api_key,
        "llmCustomBaseUrl": config.llm_custom_base_url,
        "llmCustomModel": config.llm_custom_model,
        "llmBillingMode": config.llm_billing_mode,
        "useCustomLlm": config.use_custom_llm,
        "identityNotes": config.identity_notes,
        "tool": config.tool,
        "useCustomSecurity": config.use_custom_security,
        "phishingMonitoringEnabled": config.phishing_monitoring_enabled,
        "promptInjectionMonitoringEnabled": config.prompt_injection_monitoring_enabled,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Admin config written to %s", path)
