"""Tenant billing record helpers."""

import logging

from automail.billing.config import DEMO_EFFECTIVE_PLAN

logger = logging.getLogger(__name__)

def get_tenant_record(tenant_id: str) -> dict:
    """Fetch the full tenant record from PocketBase."""
    from automail.db.pocketbase.client import _get
    return _get(f"/api/collections/tenants/records/{tenant_id}")

def _patch_tenant(tenant_id: str, data: dict) -> dict:
    from automail.db.pocketbase.client import _patch
    return _patch(f"/api/collections/tenants/records/{tenant_id}", data)

def get_tenant_plan(tenant_id: str) -> str:
    """Return the tenant's current plan."""
    rec = get_tenant_record(tenant_id)
    return rec.get("plan") or "free"

def is_demo_tenant(tenant_id: str | None) -> bool:
    if not tenant_id:
        return False
    try:
        from automail.core.capabilities import DEMO_ACCOUNT_TYPE
        from automail.db.pocketbase.client import get_tenant_account_type
        return get_tenant_account_type(tenant_id) == DEMO_ACCOUNT_TYPE
    except Exception:
        logger.warning("Failed to resolve tenant account type for billing", exc_info=True)
        return False

def get_effective_tenant_plan(tenant_id: str) -> str:
    """Return the plan used for product limits/features.

    Demo tenants keep their stored Stripe plan, but receive a business-level
    product surface so demos can show paid features without creating billing
    state.
    """
    if is_demo_tenant(tenant_id):
        return DEMO_EFFECTIVE_PLAN
    return get_tenant_plan(tenant_id)
