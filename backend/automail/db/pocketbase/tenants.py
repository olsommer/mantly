"""PocketBase tenant persistence."""

from typing import Any

import httpx

from automail.db.pocketbase.base import _get, _list_all, _patch, _post, generate_id


def get_tenant_name(tenant_id: str) -> str:
    """Return the display name for a tenant, or empty string if not found."""
    try:
        rec = _get(f"/api/collections/tenants/records/{tenant_id}")
        return rec.get("name", "")
    except httpx.HTTPStatusError:
        return ""


def get_tenant_account_type(tenant_id: str) -> str:
    """Return tenant account type: normal or demo."""
    from automail.core.capabilities import normalize_account_type

    try:
        rec = _get(f"/api/collections/tenants/records/{tenant_id}")
    except Exception:
        return "normal"
    return normalize_account_type(rec.get("account_type"))


def get_single_tenant() -> dict[str, Any] | None:
    """Return the first (and only) tenant record, or None.

    Used by on-prem deployments where exactly one tenant exists.
    """
    tenants = _list_all("tenants", sort="")
    return tenants[0] if tenants else None


def _default_llm_provider() -> str:
    try:
        from automail.billing import config as billing_config

        return "managed" if billing_config.IS_SAAS else "gemini"
    except Exception:
        return "gemini"


def _tenant_llm_provider(rec: dict[str, Any]) -> str:
    default_provider = _default_llm_provider()
    provider = rec.get("llm_provider", "") or default_provider
    if (
        provider == "gemini"
        and default_provider == "managed"
        and not rec.get("llm_api_key")
        and not rec.get("llm_custom_base_url")
        and not rec.get("llm_custom_model")
    ):
        return "managed"
    return provider


def get_tenant_settings(tenant_id: str) -> dict[str, Any]:
    """Return tenant-level settings (support/feedback emails + org identity + LLM)."""
    from automail.core.capabilities import normalize_account_type

    rec = _get(f"/api/collections/tenants/records/{tenant_id}")
    return {
        "supportEmail": rec.get("support_email", ""),
        "feedbackEmail": rec.get("feedback_email", ""),
        "orgName": rec.get("org_name", ""),
        "orgDescription": rec.get("org_description", ""),
        "addinPrimaryColor": rec.get("addin_primary_color", ""),
        "llmProvider": _tenant_llm_provider(rec),
        "llmModel": rec.get("llm_model", ""),
        "llmApiKey": rec.get("llm_api_key", ""),
        "llmCustomBaseUrl": rec.get("llm_custom_base_url", ""),
        "llmCustomModel": rec.get("llm_custom_model", ""),
        "phishingMonitoringEnabled": bool(rec.get("phishing_monitoring_enabled", False)),
        "promptInjectionMonitoringEnabled": bool(rec.get("prompt_injection_monitoring_enabled", False)),
        "allowSignups": bool(rec.get("allow_signups", False)),
        "accountType": normalize_account_type(rec.get("account_type")),
    }


def update_tenant_settings(
    tenant_id: str,
    support_email: str | None = None,
    feedback_email: str | None = None,
    org_name: str | None = None,
    org_description: str | None = None,
    addin_primary_color: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_api_key: str | None = None,
    llm_custom_base_url: str | None = None,
    llm_custom_model: str | None = None,
    phishing_monitoring_enabled: bool | None = None,
    prompt_injection_monitoring_enabled: bool | None = None,
    allow_signups: bool | None = None,
) -> dict[str, Any]:
    """Update tenant-level settings. Returns the updated settings."""
    data: dict[str, Any] = {}
    if support_email is not None:
        data["support_email"] = support_email
    if feedback_email is not None:
        data["feedback_email"] = feedback_email
    if org_name is not None:
        data["org_name"] = org_name
    if org_description is not None:
        data["org_description"] = org_description
    if addin_primary_color is not None:
        data["addin_primary_color"] = addin_primary_color
    if llm_provider is not None:
        data["llm_provider"] = llm_provider
    if llm_model is not None:
        data["llm_model"] = llm_model
    if llm_api_key is not None:
        data["llm_api_key"] = llm_api_key
    if llm_custom_base_url is not None:
        data["llm_custom_base_url"] = llm_custom_base_url
    if llm_custom_model is not None:
        data["llm_custom_model"] = llm_custom_model
    if phishing_monitoring_enabled is not None:
        data["phishing_monitoring_enabled"] = phishing_monitoring_enabled
    if prompt_injection_monitoring_enabled is not None:
        data["prompt_injection_monitoring_enabled"] = prompt_injection_monitoring_enabled
    if allow_signups is not None:
        data["allow_signups"] = allow_signups
    if data:
        _patch(f"/api/collections/tenants/records/{tenant_id}", data)
    return get_tenant_settings(tenant_id)


def create_tenant(name: str, account_type: str = "normal") -> str:
    """Create a new tenant in PocketBase and return its record ID."""
    from automail.core.capabilities import normalize_account_type

    rec = _post(
        "/api/collections/tenants/records",
        {
            "id": generate_id(),
            "name": name,
            "org_name": name,
            "account_type": normalize_account_type(account_type),
        },
    )
    return rec["id"]
