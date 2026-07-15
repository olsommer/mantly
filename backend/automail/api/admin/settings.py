"""Admin tenant settings, secrets, and license status endpoints."""

from fastapi import APIRouter

from automail.api.admin.config import _nonempty, _requested_byok_llm
from automail.api.admin.deps import (
    AuthDep,
    ProjectEditorDep,
    ProjectViewerDep,
    RootAuthDep,
    _normalize_hex_color,
    _require_auth_capability,
    _require_ctx_capability,
)
from automail.core.config import is_masked, mask_api_key

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────
# Tenant / organisation settings (root only)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/tenant/settings")
async def get_tenant_settings_endpoint(auth: AuthDep) -> dict:
    """Return tenant-level settings. Any authenticated user."""
    from automail.db.pocketbase.client import get_tenant_settings

    data = get_tenant_settings(auth.tenant_id)
    # Mask the LLM API key before sending to frontend
    data["llmApiKey"] = mask_api_key(data.get("llmApiKey", ""))
    return data


@router.patch("/tenant/settings")
async def update_tenant_settings_endpoint(body: dict, auth: RootAuthDep) -> dict:
    """Update tenant-level settings (root only)."""
    from automail.db.pocketbase.client import get_tenant_settings, update_tenant_settings

    tenant_id = auth.tenant_id
    _require_auth_capability(auth, "canManageOrgSettings")

    # Preserve existing API key if the frontend sends back a masked value.
    incoming_key = body.get("llmApiKey")
    if incoming_key is not None and is_masked(incoming_key):
        current = get_tenant_settings(tenant_id)
        incoming_key = current.get("llmApiKey", "")

    llm_provider = body.get("llmProvider")
    llm_model = body.get("llmModel")
    llm_custom_base_url = body.get("llmCustomBaseUrl")
    llm_custom_model = body.get("llmCustomModel")
    if llm_provider == "managed":
        incoming_key = ""
        llm_model = ""
        llm_custom_base_url = ""
        llm_custom_model = ""

    from automail.billing.plans import require_feature
    llm_body = {
        **body,
        "llmApiKey": incoming_key,
        "llmModel": llm_model,
        "llmCustomBaseUrl": llm_custom_base_url,
        "llmCustomModel": llm_custom_model,
    }
    if _requested_byok_llm(llm_body, incoming_key=incoming_key):
        require_feature(tenant_id, "byok_llm")
    if llm_provider == "custom" or _nonempty(llm_custom_base_url):
        require_feature(tenant_id, "custom_llm_gateway")
    if body.get("phishingMonitoringEnabled") is True or body.get("promptInjectionMonitoringEnabled") is True:
        require_feature(tenant_id, "security_monitoring")

    result = update_tenant_settings(
        tenant_id,
        support_email=body.get("supportEmail"),
        feedback_email=body.get("feedbackEmail"),
        org_name=body.get("orgName"),
        org_description=body.get("orgDescription"),
        addin_primary_color=_normalize_hex_color(body.get("addinPrimaryColor")),
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_api_key=incoming_key,
        llm_custom_base_url=llm_custom_base_url,
        llm_custom_model=llm_custom_model,
        phishing_monitoring_enabled=body.get("phishingMonitoringEnabled"),
        prompt_injection_monitoring_enabled=body.get("promptInjectionMonitoringEnabled"),
        allow_signups=body.get("allowSignups"),
    )

    # Invalidate cached LLM singletons so changes take effect immediately.
    from automail.llm import invalidate_all
    invalidate_all()

    result["llmApiKey"] = mask_api_key(result.get("llmApiKey", ""))
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Tenant secrets
# ──────────────────────────────────────────────────────────────────────────────

def _mask_secrets(secrets: dict[str, str]) -> dict[str, str]:
    """Return a copy with every value masked."""
    return {k: mask_api_key(v) for k, v in secrets.items()}


def _merge_secrets_preserving_masked(
    incoming: dict[str, str], current: dict[str, str],
) -> dict[str, str]:
    """Merge incoming secrets, keeping current values when the incoming value is masked."""
    merged: dict[str, str] = {}
    for key, val in incoming.items():
        if is_masked(val):
            # Preserve existing value for this key
            merged[key] = current.get(key, "")
        else:
            merged[key] = val
    return merged


@router.get("/tenant/secrets")
async def get_tenant_secrets_endpoint(auth: RootAuthDep) -> dict:
    """Return tenant-level secrets with masked values (root only)."""
    from automail.db.pocketbase.client import get_tenant_secrets

    _require_auth_capability(auth, "canManageTenantSecrets")
    return _mask_secrets(get_tenant_secrets(auth.tenant_id))


@router.patch("/tenant/secrets")
async def update_tenant_secrets_endpoint(body: dict, auth: RootAuthDep) -> dict:
    """Update tenant-level secrets (root only).

    Keys sent with a masked value (``••••...``) are preserved unchanged.
    Keys omitted from the payload are removed.
    """
    from automail.db.pocketbase.client import get_tenant_secrets, update_tenant_secrets

    tenant_id = auth.tenant_id
    _require_auth_capability(auth, "canManageTenantSecrets")
    current = get_tenant_secrets(tenant_id)
    merged = _merge_secrets_preserving_masked(body, current)
    update_tenant_secrets(tenant_id, merged)
    return _mask_secrets(merged)


# ──────────────────────────────────────────────────────────────────────────────
# Project secrets
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/secrets")
async def get_project_secrets_endpoint(ctx: ProjectViewerDep) -> dict:
    """Return project-level secrets with masked values."""
    from automail.db.pocketbase.client import get_project_secrets

    return _mask_secrets(get_project_secrets(ctx.project_id))


@router.patch("/projects/{pid}/secrets")
async def update_project_secrets_endpoint(body: dict, ctx: ProjectEditorDep) -> dict:
    """Update project-level secrets (editor+ required).

    Keys sent with a masked value are preserved.  Keys omitted are removed.
    """
    from automail.db.pocketbase.client import get_project_secrets, update_project_secrets

    _require_ctx_capability(ctx, "canManageProjectSecrets")
    current = get_project_secrets(ctx.project_id)
    merged = _merge_secrets_preserving_masked(body, current)
    update_project_secrets(ctx.project_id, merged)
    return _mask_secrets(merged)


@router.get("/license/status")
async def get_license_status_endpoint(auth: AuthDep) -> dict:
    """Return on-prem license status (any authenticated user)."""
    from automail.billing.license import get_license_status, is_license_required
    from automail.db.pocketbase.client import list_tenant_users

    if not is_license_required():
        return {"required": False}

    status = get_license_status()
    # Add current seat usage
    if auth.tenant_id:
        users = list_tenant_users(auth.tenant_id)
        status["currentUsers"] = len(users)
    return status
