"""Billing environment and plan definitions."""

import os
from typing import Any

IS_SAAS: bool = os.getenv("IS_SAAS", "false").lower() == "true"

# Deployment location and product entitlement are separate concerns.  Keep
# IS_SAAS as a backwards-compatible switch for Stripe/signup behavior while
# exposing explicit values for Community, managed Cloud, and dedicated installs.
DEPLOYMENT_MODES = frozenset({"cloud", "self_hosted", "dedicated"})
PRODUCT_EDITIONS = frozenset({"community", "business", "enterprise"})

DEPLOYMENT_MODE: str = (
    os.getenv(
        "MANTLY_DEPLOYMENT_MODE",
        "cloud" if IS_SAAS else "self_hosted",
    )
    .strip()
    .lower()
)
if DEPLOYMENT_MODE not in DEPLOYMENT_MODES:
    raise RuntimeError("MANTLY_DEPLOYMENT_MODE must be one of: cloud, self_hosted, dedicated")

INSTANCE_EDITION: str = (
    os.getenv(
        "MANTLY_EDITION",
        "enterprise" if DEPLOYMENT_MODE == "dedicated" else "community",
    )
    .strip()
    .lower()
)
if INSTANCE_EDITION not in PRODUCT_EDITIONS:
    raise RuntimeError("MANTLY_EDITION must be one of: community, business, enterprise")
STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRO_PRICE_ID: str = os.getenv("STRIPE_PRO_PRICE_ID", "")
STRIPE_BUSINESS_PRICE_ID: str = os.getenv("STRIPE_BUSINESS_PRICE_ID", "")
STRIPE_EXTRA_USER_PRICE_ID: str = os.getenv("STRIPE_EXTRA_USER_PRICE_ID", "")
STRIPE_EXTRA_PROJECT_PRICE_ID: str = os.getenv("STRIPE_EXTRA_PROJECT_PRICE_ID", "")
STRIPE_EXTRA_EMAIL_BLOCK_PRICE_ID: str = os.getenv("STRIPE_EXTRA_EMAIL_BLOCK_PRICE_ID", "")
STRIPE_EXTRA_EMAIL_BLOCK_SIZE: int = int(os.getenv("STRIPE_EXTRA_EMAIL_BLOCK_SIZE", "100"))
STRIPE_LLM_USAGE_PRICE_ID: str = os.getenv("STRIPE_LLM_USAGE_PRICE_ID", "")
STRIPE_LLM_METER_EVENT_NAME: str = os.getenv("STRIPE_LLM_METER_EVENT_NAME", "mantly_llm_usage")
STRIPE_ONPREM_PRICE_ID: str = os.getenv("STRIPE_ONPREM_PRICE_ID", "")
STRIPE_ONPREM_MAX_USERS: int = int(os.getenv("STRIPE_ONPREM_MAX_USERS", "20"))

_stripe_configured = False


def _ensure_stripe() -> Any:
    """Import and configure the Stripe SDK on first use.  Returns the module."""
    global _stripe_configured
    import stripe

    if not _stripe_configured:
        if not STRIPE_SECRET_KEY:
            raise RuntimeError("STRIPE_SECRET_KEY is not set")
        stripe.api_key = STRIPE_SECRET_KEY
        _stripe_configured = True
    return stripe


UNLIMITED = -1

PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free": {
        "emails_per_month": 20,
        "projects": 1,
        "users": 1,
        "eval_runs_per_month": 5,
        "eval_sets": 1,
        "eval_cases_per_set": 10,
        "retention_days": 30,
    },
    "pro": {
        "emails_per_month": 150,
        "projects": 1,
        "users": UNLIMITED,
        "eval_runs_per_month": 50,
        "eval_sets": 5,
        "eval_cases_per_set": 100,
        "retention_days": 90,
    },
    "business": {
        "emails_per_month": 1000,
        "projects": 10,
        "users": UNLIMITED,
        "eval_runs_per_month": UNLIMITED,
        "eval_sets": UNLIMITED,
        "eval_cases_per_set": UNLIMITED,
        "retention_days": 365,
    },
    "enterprise": {
        "emails_per_month": 50_000,
        "projects": UNLIMITED,
        "users": UNLIMITED,
        "eval_runs_per_month": UNLIMITED,
        "eval_sets": UNLIMITED,
        "eval_cases_per_set": UNLIMITED,
        "retention_days": 3650,
    },
}

# Self-hosted Community usage is limited by the operator's own infrastructure,
# not by Mantly's hosted billing system.  Paid self-hosted editions can add
# proprietary governance modules without pretending Community is Enterprise.
EDITION_LIMITS: dict[str, dict[str, int]] = {
    edition: {
        "emails_per_month": UNLIMITED,
        "projects": UNLIMITED,
        "users": UNLIMITED,
        "eval_runs_per_month": UNLIMITED,
        "eval_sets": UNLIMITED,
        "eval_cases_per_set": UNLIMITED,
        "retention_days": UNLIMITED,
    }
    for edition in PRODUCT_EDITIONS
}

PLAN_FEATURES: dict[str, dict[str, bool]] = {
    "free": {
        "feedback_learnings": False,
        "security_monitoring": True,
        "byok_llm": False,
        "custom_llm_gateway": False,
    },
    "pro": {
        "feedback_learnings": True,
        "security_monitoring": True,
        "byok_llm": True,
        "custom_llm_gateway": True,
    },
    "business": {
        "feedback_learnings": True,
        "security_monitoring": True,
        "byok_llm": True,
        "custom_llm_gateway": True,
    },
    "enterprise": {
        "feedback_learnings": True,
        "security_monitoring": True,
        "byok_llm": True,
        "custom_llm_gateway": True,
    },
}

# Every self-hosted edition contains the complete safe Community core.  Paid
# governance/scale modules should introduce their own explicit entitlements.
EDITION_FEATURES: dict[str, dict[str, bool]] = {
    edition: {feature: True for feature in PLAN_FEATURES["enterprise"]} for edition in PRODUCT_EDITIONS
}

DEMO_EFFECTIVE_PLAN = "business"
