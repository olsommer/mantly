"""Stripe Billing Meter integration for managed LLM usage."""

import logging
from datetime import datetime, timezone

from automail.billing.config import (
    IS_SAAS,
    STRIPE_LLM_METER_EVENT_NAME,
    STRIPE_LLM_USAGE_PRICE_ID,
    STRIPE_SECRET_KEY,
    _ensure_stripe,
)
from automail.billing.subscriptions import _retrieve_stripe_subscription, _subscription_items_by_price
from automail.billing.tenant import get_tenant_record

logger = logging.getLogger(__name__)

def ensure_subscription_metered_item(tenant_id: str) -> bool:
    """Ensure the LLM metered price is attached to this tenant's subscription."""
    if not IS_SAAS or not STRIPE_SECRET_KEY or not STRIPE_LLM_USAGE_PRICE_ID:
        return False
    stripe = _ensure_stripe()
    rec = get_tenant_record(tenant_id)
    if (rec.get("plan") or "free") == "free":
        return False
    subscription = _retrieve_stripe_subscription(
        stripe,
        rec.get("subscription_id"),
        rec.get("stripe_customer_id"),
    )
    if not subscription:
        return False
    if STRIPE_LLM_USAGE_PRICE_ID in _subscription_items_by_price(subscription):
        return True
    stripe.SubscriptionItem.create(
        subscription=subscription["id"],
        price=STRIPE_LLM_USAGE_PRICE_ID,
        proration_behavior="none",
    )
    return True

def report_llm_usage_event_to_stripe(tenant_id: str | None, event_record: dict) -> None:
    """Report one Mantly-managed LLM usage event to Stripe Billing Meters."""
    if not tenant_id or not IS_SAAS or not STRIPE_SECRET_KEY or not STRIPE_LLM_USAGE_PRICE_ID:
        return
    if event_record.get("billing_mode") != "mantly_managed" or event_record.get("stripe_reported"):
        return
    value = int(event_record.get("billed_cost_usd_micros") or 0)
    if value <= 0:
        return

    from automail.db.pocketbase.client import _patch

    try:
        rec = get_tenant_record(tenant_id)
        customer_id = rec.get("stripe_customer_id")
        if not customer_id:
            return
        ensure_subscription_metered_item(tenant_id)
        identifier = f"llm_{event_record['id']}"
        stripe = _ensure_stripe()
        stripe.billing.MeterEvent.create(
            event_name=STRIPE_LLM_METER_EVENT_NAME,
            payload={
                "stripe_customer_id": customer_id,
                "value": str(value),
            },
            identifier=identifier,
        )
        _patch(
            f"/api/collections/llm_usage_events/records/{event_record['id']}",
            {
                "stripe_reported": True,
                "stripe_reported_at": datetime.now(timezone.utc).isoformat(),
                "stripe_meter_event_id": identifier,
                "stripe_report_error": "",
            },
        )
    except Exception as exc:
        logger.warning("Failed to report LLM usage event %s to Stripe", event_record.get("id"), exc_info=True)
        try:
            _patch(
                f"/api/collections/llm_usage_events/records/{event_record['id']}",
                {"stripe_report_error": str(exc)[:500]},
            )
        except Exception:
            logger.warning("Failed to persist Stripe usage reporting error", exc_info=True)
