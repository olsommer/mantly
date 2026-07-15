"""Stripe customer, checkout, and portal sessions."""

import logging

from fastapi import HTTPException

from automail.billing.config import (
    STRIPE_BUSINESS_PRICE_ID,
    STRIPE_LLM_USAGE_PRICE_ID,
    STRIPE_PRO_PRICE_ID,
    STRIPE_SECRET_KEY,
    _ensure_stripe,
)
from automail.billing.tenant import _patch_tenant, get_tenant_record

logger = logging.getLogger(__name__)

def create_stripe_customer(tenant_id: str, email: str, name: str) -> str | None:
    """Create a Stripe customer and link it to the tenant.

    Returns the Stripe customer ID, or None if Stripe is not configured.
    """
    if not STRIPE_SECRET_KEY:
        logger.info("Stripe not configured — skipping customer creation for tenant %s", tenant_id)
        return None

    stripe = _ensure_stripe()
    customer = stripe.Customer.create(
        email=email,
        name=name,
        metadata={"tenant_id": tenant_id},
    )
    customer_id: str = customer["id"]

    # Save to tenant record + set default plan
    _patch_tenant(tenant_id, {
        "stripe_customer_id": customer_id,
        "plan": "free",
        "subscription_status": "none",
    })

    logger.info("Created Stripe customer %s for tenant %s", customer_id, tenant_id)
    return customer_id

def _get_or_create_stripe_customer_id(tenant_id: str, email: str) -> str:
    """Return the Stripe customer ID, creating one if needed."""
    rec = get_tenant_record(tenant_id)
    existing = rec.get("stripe_customer_id")
    if existing:
        return existing
    cid = create_stripe_customer(tenant_id, email, rec.get("name", ""))
    if not cid:
        raise HTTPException(500, "Stripe is not configured")
    return cid

def create_checkout_session(
    tenant_id: str,
    email: str,
    success_url: str,
    cancel_url: str,
    plan: str = "pro",
) -> str:
    """Create a Stripe Checkout session for a paid SaaS plan.

    Returns the Checkout session URL.
    """
    stripe = _ensure_stripe()
    customer_id = _get_or_create_stripe_customer_id(tenant_id, email)

    price_by_plan = {
        "pro": STRIPE_PRO_PRICE_ID,
        "business": STRIPE_BUSINESS_PRICE_ID,
    }
    if plan not in price_by_plan:
        raise HTTPException(400, "Unsupported checkout plan")
    price_id = price_by_plan[plan]
    if not price_id:
        env_name = "STRIPE_BUSINESS_PRICE_ID" if plan == "business" else "STRIPE_PRO_PRICE_ID"
        raise HTTPException(500, f"{env_name} is not configured")

    line_items = [{"price": price_id, "quantity": 1}]
    if STRIPE_LLM_USAGE_PRICE_ID:
        line_items.append({"price": STRIPE_LLM_USAGE_PRICE_ID})

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=line_items,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"tenant_id": tenant_id, "plan": plan},
        subscription_data={"metadata": {"tenant_id": tenant_id, "plan": plan}},
    )
    return session.url

def create_portal_session(tenant_id: str, email: str, return_url: str) -> str:
    """Create a Stripe Customer Portal session.

    Returns the portal URL.
    """
    stripe = _ensure_stripe()
    customer_id = _get_or_create_stripe_customer_id(tenant_id, email)

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url
