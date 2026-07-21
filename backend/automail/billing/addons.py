"""Stripe add-on quantity synchronization."""

import logging

from automail.billing.config import (
    IS_SAAS,
    PLAN_LIMITS,
    STRIPE_EXTRA_EMAIL_BLOCK_PRICE_ID,
    STRIPE_EXTRA_EMAIL_BLOCK_SIZE,
    STRIPE_EXTRA_PROJECT_PRICE_ID,
    STRIPE_EXTRA_USER_PRICE_ID,
    STRIPE_SECRET_KEY,
    _ensure_stripe,
)
from automail.billing.subscriptions import _retrieve_stripe_subscription, _subscription_items_by_price
from automail.billing.tenant import get_tenant_record
from automail.billing.usage import get_usage

logger = logging.getLogger(__name__)


def _billable_overage(current: int, included: int) -> int:
    if included < 0:
        return 0
    return max(current - included, 0)


def sync_stripe_addons_best_effort(tenant_id: str) -> dict[str, int]:
    """Sync licensed add-on subscription item quantities from current usage."""
    try:
        return sync_stripe_addons(tenant_id)
    except Exception:
        logger.warning("Failed to sync Stripe add-ons for tenant %s", tenant_id, exc_info=True)
        return {}


def sync_stripe_addons(tenant_id: str) -> dict[str, int]:
    """Update extra user/project/email subscription quantities in Stripe."""
    if not IS_SAAS or not STRIPE_SECRET_KEY:
        return {}
    stripe = _ensure_stripe()
    rec = get_tenant_record(tenant_id)
    plan = rec.get("plan") or "free"
    if plan == "free":
        return {}
    subscription = _retrieve_stripe_subscription(
        stripe,
        rec.get("subscription_id"),
        rec.get("stripe_customer_id"),
    )
    if not subscription or subscription.get("status") not in {"active", "trialing", "past_due", "unpaid"}:
        return {}

    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    usage = get_usage(tenant_id)
    agent_run_overage = _billable_overage(
        usage["agent_runs_this_period"],
        limits["emails_per_month"],
    )
    desired = {
        STRIPE_EXTRA_USER_PRICE_ID: _billable_overage(usage["users"], limits["users"]),
        STRIPE_EXTRA_PROJECT_PRICE_ID: _billable_overage(
            usage["projects"],
            limits["projects"],
        ),
        STRIPE_EXTRA_EMAIL_BLOCK_PRICE_ID: (
            (agent_run_overage + STRIPE_EXTRA_EMAIL_BLOCK_SIZE - 1) // STRIPE_EXTRA_EMAIL_BLOCK_SIZE
            if STRIPE_EXTRA_EMAIL_BLOCK_PRICE_ID and STRIPE_EXTRA_EMAIL_BLOCK_SIZE > 0
            else 0
        ),
    }
    desired = {price_id: quantity for price_id, quantity in desired.items() if price_id}
    if not desired:
        return {}

    items_by_price = _subscription_items_by_price(subscription)
    synced: dict[str, int] = {}
    for price_id, quantity in desired.items():
        item = items_by_price.get(price_id)
        if item:
            current_quantity = int(item.get("quantity") or 0)
            if current_quantity != quantity:
                stripe.SubscriptionItem.modify(
                    item["id"],
                    quantity=quantity,
                    proration_behavior="none",
                )
            synced[price_id] = quantity
        elif quantity > 0:
            stripe.SubscriptionItem.create(
                subscription=subscription["id"],
                price=price_id,
                quantity=quantity,
                proration_behavior="none",
            )
            synced[price_id] = quantity
    return synced
