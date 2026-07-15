"""Plan limits, features, and entitlement checks."""

from fastapi import HTTPException

from automail.billing.config import IS_SAAS, PLAN_FEATURES, PLAN_LIMITS
from automail.billing.tenant import get_effective_tenant_plan


def get_plan_limits(plan: str) -> dict[str, int]:
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"]).copy()

def get_plan_features(plan: str) -> dict[str, bool]:
    return PLAN_FEATURES.get(plan, PLAN_FEATURES["free"]).copy()

def get_tenant_limits(tenant_id: str) -> dict[str, int]:
    if not IS_SAAS:
        return PLAN_LIMITS["enterprise"].copy()
    return get_plan_limits(get_effective_tenant_plan(tenant_id))

def get_tenant_features(tenant_id: str) -> dict[str, bool]:
    if not IS_SAAS:
        return {key: True for key in PLAN_FEATURES["enterprise"]}
    return get_plan_features(get_effective_tenant_plan(tenant_id))

def has_feature(tenant_id: str | None, feature: str) -> bool:
    if not IS_SAAS or not tenant_id:
        return True
    return bool(get_tenant_features(tenant_id).get(feature, False))

def require_feature(tenant_id: str | None, feature: str) -> None:
    if has_feature(tenant_id, feature):
        return
    plan = get_effective_tenant_plan(tenant_id or "") if tenant_id else "free"
    raise HTTPException(
        status_code=402,
        detail={
            "error": "feature_not_in_plan",
            "feature": feature,
            "plan": plan,
            "message": f"This feature is not included in the {plan} plan.",
        },
    )
