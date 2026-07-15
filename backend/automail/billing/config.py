"""Billing environment and plan definitions."""

import os
from typing import Any

IS_SAAS: bool = os.getenv("IS_SAAS", "false").lower() == "true"
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
        "users": 1,
        "eval_runs_per_month": 50,
        "eval_sets": 5,
        "eval_cases_per_set": 100,
        "retention_days": 90,
    },
    "business": {
        "emails_per_month": 1000,
        "projects": 1,
        "users": 5,
        "eval_runs_per_month": UNLIMITED,
        "eval_sets": UNLIMITED,
        "eval_cases_per_set": UNLIMITED,
        "retention_days": 365,
    },
    "enterprise": {
        "emails_per_month": 50_000,
        "projects": 100,
        "users": 500,
        "eval_runs_per_month": UNLIMITED,
        "eval_sets": UNLIMITED,
        "eval_cases_per_set": UNLIMITED,
        "retention_days": 3650,
    },
}

PLAN_FEATURES: dict[str, dict[str, bool]] = {
    "free": {
        "feedback_learnings": False,
        "security_monitoring": False,
        "byok_llm": False,
        "custom_llm_gateway": False,
    },
    "pro": {
        "feedback_learnings": True,
        "security_monitoring": False,
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

DEMO_EFFECTIVE_PLAN = "business"
