"""Effective LLM configuration resolution."""

import logging
import os

from automail.core.config import AdminConfig

logger = logging.getLogger(__name__)


def resolve_effective_config(config: AdminConfig, tenant_id: str | None = None, project_id: str | None = None) -> AdminConfig:
    """Return an AdminConfig with tenant defaults merged where applicable."""
    if not tenant_id:
        return _resolve_llm_secret_placeholders(config, tenant_id, project_id)

    demo_llm_managed = False
    try:
        from automail.core.capabilities import DEMO_ACCOUNT_TYPE
        from automail.db.pocketbase.client import get_tenant_account_type

        if get_tenant_account_type(tenant_id) == DEMO_ACCOUNT_TYPE:
            demo_overrides = {
                "llm_provider": os.getenv("DEMO_LLM_PROVIDER", "gemini").strip() or "gemini",
                "llm_model": os.getenv("DEMO_LLM_MODEL", "").strip(),
                "llm_api_key": os.getenv("DEMO_LLM_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip(),
                "llm_custom_base_url": os.getenv("DEMO_LLM_CUSTOM_BASE_URL", "").strip(),
                "llm_custom_model": os.getenv("DEMO_LLM_CUSTOM_MODEL", "").strip(),
                "use_custom_llm": False,
            }
            config = config.model_copy(update=demo_overrides)
            demo_llm_managed = True
    except Exception as exc:
        logger.warning("Failed to resolve demo LLM config for %s: %s — using project config", tenant_id, exc)

    needs_tenant = ((not config.use_custom_llm) and not demo_llm_managed) or (
        not config.use_custom_org
    ) or (
        not config.use_custom_security
    )
    if not needs_tenant:
        return _resolve_llm_secret_placeholders(_apply_llm_billing_policy(config, tenant_id), tenant_id, project_id)

    try:
        from automail.db.pocketbase.client import get_tenant_settings

        ts = get_tenant_settings(tenant_id)
    except Exception as exc:
        logger.warning("Failed to fetch tenant settings for %s: %s — using project config", tenant_id, exc)
        return _resolve_llm_secret_placeholders(_apply_llm_billing_policy(config, tenant_id), tenant_id, project_id)

    overrides: dict = {}

    if not config.use_custom_org:
        if ts.get("orgName"):
            overrides["org_name"] = ts["orgName"]
        if ts.get("orgDescription"):
            overrides["org_description"] = ts["orgDescription"]

    if (not config.use_custom_llm) and not demo_llm_managed:
        if ts.get("llmProvider"):
            overrides["llm_provider"] = ts["llmProvider"]
        if ts.get("llmModel"):
            overrides["llm_model"] = ts["llmModel"]
        if ts.get("llmApiKey"):
            overrides["llm_api_key"] = ts["llmApiKey"]
        if ts.get("llmCustomBaseUrl"):
            overrides["llm_custom_base_url"] = ts["llmCustomBaseUrl"]
        if ts.get("llmCustomModel"):
            overrides["llm_custom_model"] = ts["llmCustomModel"]

    if not config.use_custom_security:
        overrides["phishing_monitoring_enabled"] = bool(ts.get("phishingMonitoringEnabled", False))
        overrides["prompt_injection_monitoring_enabled"] = bool(ts.get("promptInjectionMonitoringEnabled", False))

    effective = config.model_copy(update=overrides) if overrides else config
    return _resolve_llm_secret_placeholders(_apply_llm_billing_policy(effective, tenant_id), tenant_id, project_id)


def _resolve_llm_secret_placeholders(config: AdminConfig, tenant_id: str | None = None, project_id: str | None = None) -> AdminConfig:
    """Resolve secret placeholders in LLM provider fields."""
    try:
        from automail.core.runtime_secrets import load_runtime_secrets, resolve_secret_placeholders

        secrets = load_runtime_secrets(tenant_id, project_id)
        updates = {}
        for field in ("llm_api_key", "llm_custom_base_url"):
            value = getattr(config, field, "")
            resolved = resolve_secret_placeholders(value, secrets)
            if isinstance(resolved, str) and resolved != value:
                updates[field] = resolved
        return config.model_copy(update=updates) if updates else config
    except Exception:
        logger.warning("Failed to resolve LLM secret placeholders", exc_info=True)
        return config


def _apply_llm_billing_policy(config: AdminConfig, tenant_id: str | None = None) -> AdminConfig:
    """Apply SaaS BYOK vs Mantly-managed LLM policy to the effective config."""
    try:
        from automail.billing.config import IS_SAAS
        from automail.billing.plans import has_feature
        from automail.billing.tenant import get_tenant_plan
        from automail.llm.billing import (
            LLM_BILLING_BYOK,
            LLM_BILLING_INCLUDED,
            LLM_BILLING_MANTLY_MANAGED,
            managed_llm_env,
        )
    except Exception:
        return config

    if not IS_SAAS or not tenant_id:
        return config.model_copy(update={"llm_billing_mode": LLM_BILLING_BYOK})

    plan = "free"
    try:
        plan = get_tenant_plan(tenant_id)
    except Exception:
        pass
    managed = managed_llm_env()
    uses_managed_provider = config.llm_provider == "managed"

    if not uses_managed_provider and has_feature(tenant_id, "byok_llm") and config.llm_api_key:
        return config.model_copy(update={"llm_billing_mode": LLM_BILLING_BYOK})

    if not managed.get("llm_api_key"):
        return config

    billing_mode = LLM_BILLING_INCLUDED if plan == "free" else LLM_BILLING_MANTLY_MANAGED
    return config.model_copy(update={
        **{key: value for key, value in managed.items() if value},
        "llm_billing_mode": billing_mode,
    })
