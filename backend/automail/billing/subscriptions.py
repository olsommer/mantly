"""Stripe subscription state helpers."""

import logging
from datetime import datetime, timezone
from typing import Any

from automail.billing.config import (
    PLAN_LIMITS,
    STRIPE_BUSINESS_PRICE_ID,
    STRIPE_ONPREM_PRICE_ID,
    STRIPE_PRO_PRICE_ID,
    STRIPE_SECRET_KEY,
    _ensure_stripe,
)
from automail.billing.tenant import _patch_tenant, get_tenant_record

logger = logging.getLogger(__name__)

def get_subscription_status(tenant_id: str) -> str:
    """Return the tenant's subscription status."""
    rec = get_tenant_record(tenant_id)
    return rec.get("subscription_status") or "none"

def get_subscription_details(tenant_id: str) -> dict[str, Any]:
    """Return subscription fields needed by the billing UI."""
    rec = get_tenant_record(tenant_id)
    rec = _sync_subscription_details_from_stripe(tenant_id, rec)
    return {
        "status": rec.get("subscription_status") or "none",
        "cancel_at_period_end": bool(rec.get("cancel_at_period_end")),
        "current_period_start": rec.get("current_period_start") or "",
        "current_period_end": rec.get("current_period_end") or "",
    }

def _subscription_period_timestamps(subscription: dict) -> tuple[int | None, int | None]:
    period_start = subscription.get("current_period_start")
    period_end = subscription.get("current_period_end")
    if period_start and period_end:
        return period_start, period_end

    items = (subscription.get("items") or {}).get("data") or []
    if items:
        first_item = items[0]
        period_start = period_start or first_item.get("current_period_start")
        period_end = period_end or first_item.get("current_period_end")
    return period_start, period_end

def _subscription_cancels_at_period_end(subscription: dict) -> bool:
    if bool(subscription.get("cancel_at_period_end")):
        return True

    cancel_at = subscription.get("cancel_at")
    status = subscription.get("status")
    return bool(cancel_at and status in {"active", "trialing", "past_due", "unpaid"})

def _plan_from_subscription(subscription: dict, fallback: str = "pro") -> str:
    metadata_plan = (subscription.get("metadata") or {}).get("plan", "")
    if metadata_plan in PLAN_LIMITS:
        return metadata_plan

    items = (subscription.get("items") or {}).get("data") or []
    for item in items:
        price_id = ((item.get("price") or {}).get("id")) or item.get("price")
        if STRIPE_BUSINESS_PRICE_ID and price_id == STRIPE_BUSINESS_PRICE_ID:
            return "business"
        if STRIPE_PRO_PRICE_ID and price_id == STRIPE_PRO_PRICE_ID:
            return "pro"
        if STRIPE_ONPREM_PRICE_ID and price_id == STRIPE_ONPREM_PRICE_ID:
            return "enterprise"

    return fallback if fallback in PLAN_LIMITS else "pro"

def _subscription_items_by_price(subscription: dict) -> dict[str, dict]:
    items = (subscription.get("items") or {}).get("data") or []
    by_price: dict[str, dict] = {}
    for item in items:
        price_id = ((item.get("price") or {}).get("id")) or item.get("price")
        if price_id:
            by_price[price_id] = item
    return by_price

def _sync_subscription_details_from_stripe(tenant_id: str, rec: dict) -> dict:
    """Best-effort Stripe reconciliation for portal changes missed by webhooks."""
    subscription_id = rec.get("subscription_id")
    customer_id = rec.get("stripe_customer_id")
    if not STRIPE_SECRET_KEY or (not subscription_id and not customer_id):
        return rec

    try:
        stripe = _ensure_stripe()
        subscription = _retrieve_stripe_subscription(stripe, subscription_id, customer_id)
        if not subscription:
            return rec
    except Exception:
        logger.warning("Failed to refresh Stripe subscription for tenant %s", tenant_id, exc_info=True)
        return rec

    period_start, period_end = _subscription_period_timestamps(subscription)
    update: dict[str, Any] = {
        "plan": _plan_from_subscription(subscription, rec.get("plan") or "pro"),
        "subscription_status": subscription.get("status", rec.get("subscription_status") or "active"),
        "subscription_id": subscription.get("id", subscription_id),
        "cancel_at_period_end": _subscription_cancels_at_period_end(subscription),
    }
    if period_start:
        update["current_period_start"] = datetime.fromtimestamp(period_start, tz=timezone.utc).isoformat()
    if period_end:
        update["current_period_end"] = datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat()

    if any(rec.get(key) != value for key, value in update.items()):
        try:
            _patch_tenant(tenant_id, update)
            rec = {**rec, **update}
        except Exception:
            logger.warning("Failed to persist Stripe subscription refresh for tenant %s", tenant_id, exc_info=True)

    return rec

def _stripe_object_to_dict(obj: Any) -> dict:
    if hasattr(obj, "to_dict_recursive"):
        return obj.to_dict_recursive()
    if hasattr(obj, "_to_dict_recursive"):
        return obj._to_dict_recursive()
    return dict(obj)

def _retrieve_stripe_subscription(stripe: Any, subscription_id: str | None, customer_id: str | None) -> dict | None:
    if customer_id:
        subscriptions_obj = stripe.Subscription.list(customer=customer_id, status="all", limit=10)
        subscriptions = _stripe_object_to_dict(subscriptions_obj).get("data") or []

        for subscription in subscriptions:
            if subscription.get("status") in {"active", "trialing", "past_due", "unpaid"} and subscription.get("cancel_at_period_end"):
                return subscription

        if subscription_id:
            for subscription in subscriptions:
                if subscription.get("id") == subscription_id:
                    return subscription

        for subscription in subscriptions:
            if subscription.get("status") in {"active", "trialing", "past_due", "unpaid"}:
                return subscription

        if subscriptions:
            return subscriptions[0]

    if subscription_id:
        return _stripe_object_to_dict(stripe.Subscription.retrieve(subscription_id))

    return None
