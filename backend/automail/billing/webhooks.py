"""Stripe webhook processing."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from automail.billing.config import (
    STRIPE_ONPREM_PRICE_ID,
    STRIPE_WEBHOOK_SECRET,
    _ensure_stripe,
)
from automail.billing.subscriptions import (
    _plan_from_subscription,
    _stripe_object_to_dict,
    _subscription_cancels_at_period_end,
    _subscription_period_timestamps,
)
from automail.billing.tenant import _patch_tenant

logger = logging.getLogger(__name__)

def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    """Verify and construct a Stripe webhook event.

    Raises ``HTTPException(400)`` on invalid signatures.
    Returns a plain dict (Stripe SDK v15 returns StripeObject, not dict).
    """
    stripe = _ensure_stripe()
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "STRIPE_WEBHOOK_SECRET is not configured")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        # Convert StripeObject → plain dict so .get() works everywhere
        return event.to_dict()
    except stripe.SignatureVerificationError:
        raise HTTPException(400, "Invalid Stripe webhook signature")
    except Exception as exc:
        logger.error("Webhook verification failed: %s", exc)
        raise HTTPException(400, "Webhook verification failed")

def handle_webhook_event(event: dict) -> None:
    """Process a verified Stripe webhook event."""
    event_type = event.get("type", "")
    data_object = event.get("data", {}).get("object", {})

    logger.info("Processing Stripe webhook: %s", event_type)

    if event_type.startswith("customer.subscription."):
        data_object = _hydrate_subscription_event(data_object)

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data_object)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(data_object)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data_object)
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(data_object)
    else:
        logger.debug("Ignoring Stripe event type: %s", event_type)

def _hydrate_subscription_event(subscription: dict) -> dict:
    """Fetch full subscription when Stripe sends a thin webhook payload."""
    if subscription.get("customer"):
        return subscription

    subscription_id = subscription.get("id")
    if not subscription_id:
        return subscription

    try:
        return _stripe_object_to_dict(_ensure_stripe().Subscription.retrieve(subscription_id))
    except Exception:
        logger.warning("Failed to hydrate Stripe subscription webhook %s", subscription_id, exc_info=True)
        return subscription

def _find_tenant_by_customer(customer_id: str) -> str | None:
    """Look up the tenant ID for a Stripe customer ID."""
    from automail.db.pocketbase.client import _first
    rec = _first("tenants", f"stripe_customer_id='{customer_id}'")
    return rec["id"] if rec else None

def _handle_checkout_completed(session: dict) -> None:
    """Upgrade a SaaS tenant or defer on-prem licensing to a platform admin."""
    # Try metadata first, then customer lookup
    tenant_id = (session.get("metadata") or {}).get("tenant_id")
    if not tenant_id:
        customer_id = session.get("customer")
        if customer_id:
            tenant_id = _find_tenant_by_customer(customer_id)

    subscription_id = session.get("subscription", "")

    # Check if this is an on-prem subscription by inspecting line items
    if STRIPE_ONPREM_PRICE_ID and subscription_id:
        try:
            is_onprem = _is_onprem_subscription(subscription_id)
        except Exception:
            is_onprem = False
        if is_onprem:
            logger.warning(
                "On-prem checkout completed for subscription %s (tenant=%s); "
                "no license was created automatically. A platform administrator "
                "must create and securely deliver it through POST /api/admin/licenses.",
                subscription_id,
                tenant_id or "unresolved",
            )
            return

    if not tenant_id:
        logger.warning("checkout.session.completed: could not resolve tenant")
        return

    requested_plan = (session.get("metadata") or {}).get("plan", "pro")
    plan = requested_plan if requested_plan in {"pro", "business"} else "pro"
    if subscription_id:
        try:
            subscription = _ensure_stripe().Subscription.retrieve(subscription_id)
            plan = _plan_from_subscription(_stripe_object_to_dict(subscription), plan)
        except Exception:
            logger.warning("checkout.session.completed: failed to inspect subscription %s", subscription_id, exc_info=True)

    _patch_tenant(tenant_id, {
        "plan": plan,
        "subscription_status": "active",
        "subscription_id": subscription_id,
        "cancel_at_period_end": False,
    })
    logger.info("Tenant %s upgraded to %s (sub=%s)", tenant_id, plan, subscription_id)

def _is_onprem_subscription(subscription_id: str) -> bool:
    """Check whether a Stripe subscription contains the on-prem price."""
    stripe = _ensure_stripe()
    sub = stripe.Subscription.retrieve(subscription_id)
    for item in sub.get("items", {}).get("data", []):
        price_id = item.get("price", {}).get("id", "")
        if price_id == STRIPE_ONPREM_PRICE_ID:
            return True
    return False

def _handle_subscription_updated(subscription: dict) -> None:
    """Handle customer.subscription.updated — sync status and period end."""
    customer_id = subscription.get("customer")
    if not customer_id:
        return

    tenant_id = _find_tenant_by_customer(customer_id)
    if not tenant_id:
        logger.warning("subscription.updated: unknown customer %s", customer_id)
        return

    status = subscription.get("status", "active")
    period_start, period_end = _subscription_period_timestamps(subscription)

    period_start_iso = ""
    period_end_iso = ""
    if period_start:
        period_start_iso = datetime.fromtimestamp(period_start, tz=timezone.utc).isoformat()
    if period_end:
        period_end_iso = datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat()

    update: dict[str, Any] = {
        "plan": _plan_from_subscription(subscription, "pro"),
        "subscription_status": status,
        "subscription_id": subscription.get("id", ""),
        "cancel_at_period_end": _subscription_cancels_at_period_end(subscription),
    }
    if period_start_iso:
        update["current_period_start"] = period_start_iso
    if period_end_iso:
        update["current_period_end"] = period_end_iso

    _patch_tenant(tenant_id, update)
    logger.info("Tenant %s subscription updated: status=%s", tenant_id, status)

def _handle_subscription_deleted(subscription: dict) -> None:
    """Handle customer.subscription.deleted — downgrade to free and/or revoke on-prem license."""
    subscription_id = subscription.get("id", "")

    # Check if this subscription is linked to an on-prem license
    if subscription_id:
        _revoke_onprem_license_by_subscription(subscription_id)

    customer_id = subscription.get("customer")
    if not customer_id:
        return

    tenant_id = _find_tenant_by_customer(customer_id)
    if not tenant_id:
        logger.warning("subscription.deleted: unknown customer %s", customer_id)
        return

    _patch_tenant(tenant_id, {
        "plan": "free",
        "subscription_status": "none",
        "subscription_id": "",
        "cancel_at_period_end": False,
        "current_period_start": "",
        "current_period_end": "",
    })
    logger.info("Tenant %s downgraded to free (subscription deleted)", tenant_id)

def _revoke_onprem_license_by_subscription(subscription_id: str) -> None:
    """Revoke any on-prem license linked to a Stripe subscription."""
    from automail.db.pocketbase.client import _first, _patch

    rec = _first("licenses", f"subscription_id='{subscription_id}'")
    if not rec:
        return

    if not rec.get("is_active", True):
        logger.info("License for subscription %s already revoked", subscription_id)
        return

    _patch(
        f"/api/collections/licenses/records/{rec['id']}",
        {"is_active": False},
    )
    logger.info(
        "Auto-revoked on-prem license record %s (subscription %s deleted)",
        rec.get("id", "unknown"),
        subscription_id,
    )

def _handle_payment_failed(invoice: dict) -> None:
    """Handle invoice.payment_failed — mark subscription as past_due."""
    customer_id = invoice.get("customer")
    if not customer_id:
        return

    tenant_id = _find_tenant_by_customer(customer_id)
    if not tenant_id:
        logger.warning("invoice.payment_failed: unknown customer %s", customer_id)
        return

    _patch_tenant(tenant_id, {"subscription_status": "past_due"})
    logger.info("Tenant %s marked as past_due (payment failed)", tenant_id)
