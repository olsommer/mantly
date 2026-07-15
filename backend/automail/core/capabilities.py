"""Tenant account-type capabilities.

Normal accounts keep today's behavior. SaaS demo accounts can use the product
with seeded data. Demo accounts can change safe configuration surfaces so the
product can be shown end-to-end, but billing, users, and project lifecycle stay
locked.
"""
from fastapi import HTTPException, Request

from automail.core.runtime_flags import demo_mode_enabled, is_saas_mode

NORMAL_ACCOUNT_TYPE = "normal"
DEMO_ACCOUNT_TYPE = "demo"

CapabilityMap = dict[str, bool]

NORMAL_CAPABILITIES: CapabilityMap = {
    "canManageOrgSettings": True,
    "canManageMembers": True,
    "canDownloadManifest": True,
    "canManageBilling": True,
    "canManageTenantSecrets": True,
    "canManageProjectSecrets": True,
    "canManageProjectSettings": True,
    "canEditProjectConfig": True,
    "canEditIntents": True,
    "canPublish": True,
    "canUsePlatformLlm": False,
    "canAccessDemoEndpoints": False,
}

DEMO_CAPABILITIES: CapabilityMap = {
    "canManageOrgSettings": True,
    "canManageMembers": False,
    "canDownloadManifest": True,
    "canManageBilling": False,
    "canManageTenantSecrets": True,
    "canManageProjectSecrets": True,
    "canManageProjectSettings": False,
    "canEditProjectConfig": True,
    "canEditIntents": True,
    "canPublish": True,
    "canUsePlatformLlm": True,
    "canAccessDemoEndpoints": True,
}


def normalize_account_type(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    return DEMO_ACCOUNT_TYPE if candidate == DEMO_ACCOUNT_TYPE else NORMAL_ACCOUNT_TYPE


def get_account_capabilities(
    tenant_id: str,
    *,
    is_platform_admin: bool = False,
) -> CapabilityMap:
    if is_platform_admin:
        caps = NORMAL_CAPABILITIES.copy()
        caps["canAccessDemoEndpoints"] = True
        return caps

    if not is_saas_mode():
        caps = NORMAL_CAPABILITIES.copy()
        caps["canAccessDemoEndpoints"] = demo_mode_enabled()
        return caps

    from automail.db.pocketbase.client import get_tenant_account_type

    if get_tenant_account_type(tenant_id) == DEMO_ACCOUNT_TYPE:
        return DEMO_CAPABILITIES.copy()
    return NORMAL_CAPABILITIES.copy()


def require_capability(
    tenant_id: str,
    capability: str,
    *,
    is_platform_admin: bool = False,
) -> None:
    if not get_account_capabilities(
        tenant_id,
        is_platform_admin=is_platform_admin,
    ).get(capability, False):
        raise HTTPException(status_code=403, detail="This action is not available for this account")


def require_demo_endpoint_access(request: Request):
    if not is_saas_mode():
        if demo_mode_enabled():
            return None
        raise HTTPException(status_code=404, detail="Demo endpoints are disabled")

    from automail.core.auth import require_authenticated
    from automail.db.pocketbase.client import get_tenant_account_type

    auth = require_authenticated(request)
    if auth.is_platform_admin or get_tenant_account_type(auth.tenant_id) == DEMO_ACCOUNT_TYPE:
        return auth
    raise HTTPException(status_code=404, detail="Demo endpoints are disabled")
