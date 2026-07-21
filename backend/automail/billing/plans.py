"""Plan limits, features, and entitlement checks."""

from fastapi import HTTPException

from automail.billing.config import (
    DEPLOYMENT_MODE,
    EDITION_FEATURES,
    EDITION_LIMITS,
    INSTANCE_EDITION,
    IS_SAAS,
    PLAN_FEATURES,
    PLAN_LIMITS,
)
from automail.billing.tenant import get_effective_tenant_plan


def get_plan_limits(plan: str) -> dict[str, int]:
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"]).copy()


def get_plan_features(plan: str) -> dict[str, bool]:
    return PLAN_FEATURES.get(plan, PLAN_FEATURES["free"]).copy()


def get_edition_limits(edition: str) -> dict[str, int]:
    return EDITION_LIMITS.get(edition, EDITION_LIMITS["community"]).copy()


def get_edition_features(edition: str) -> dict[str, bool]:
    return EDITION_FEATURES.get(edition, EDITION_FEATURES["community"]).copy()


def get_tenant_edition(tenant_id: str | None) -> str:
    """Resolve commercial edition independently from deployment location."""
    if not IS_SAAS:
        return INSTANCE_EDITION
    plan = get_effective_tenant_plan(tenant_id or "") if tenant_id else "free"
    if plan in {"business", "enterprise"}:
        return plan
    return "community"


def get_tenant_limits(tenant_id: str) -> dict[str, int]:
    if not IS_SAAS:
        return get_edition_limits(get_tenant_edition(tenant_id))
    return get_plan_limits(get_effective_tenant_plan(tenant_id))


def get_tenant_features(tenant_id: str) -> dict[str, bool]:
    if not IS_SAAS:
        return get_edition_features(get_tenant_edition(tenant_id))
    return get_plan_features(get_effective_tenant_plan(tenant_id))


def has_feature(tenant_id: str | None, feature: str) -> bool:
    if not tenant_id:
        return feature in EDITION_FEATURES["community"]
    return bool(get_tenant_features(tenant_id).get(feature, False))


def entitlement_context(tenant_id: str | None) -> dict[str, str]:
    return {
        "deployment": DEPLOYMENT_MODE,
        "edition": get_tenant_edition(tenant_id),
    }


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
