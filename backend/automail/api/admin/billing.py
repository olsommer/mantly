"""Billing API router for SaaS deployments.

Endpoints:
    POST /api/admin/billing/checkout  — create Stripe Checkout session (upgrade)
    POST /api/admin/billing/portal    — create Stripe Customer Portal session
    GET  /api/admin/billing/status    — current plan, usage, and limits
    POST /api/webhooks/stripe         — Stripe webhook receiver (no auth)
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from automail.billing.addons import sync_stripe_addons_best_effort
from automail.billing.checkout import create_checkout_session, create_portal_session
from automail.billing.config import IS_SAAS
from automail.billing.plans import entitlement_context, get_tenant_features, get_tenant_limits
from automail.billing.retention import enforce_retention_best_effort
from automail.billing.subscriptions import get_subscription_details
from automail.billing.tenant import get_effective_tenant_plan
from automail.billing.usage import get_llm_billing_usage, get_usage
from automail.billing.webhooks import handle_webhook_event, verify_webhook_signature
from automail.core.auth import require_authenticated, require_root

logger = logging.getLogger(__name__)


# ── Admin-facing endpoints (require root) ─────────────────────────────────────

admin_router = APIRouter(prefix="/api/admin/billing")


class CheckoutRequest(BaseModel):
    success_url: str
    cancel_url: str
    plan: str = "pro"


class PortalRequest(BaseModel):
    return_url: str


def _require_saas() -> None:
    if not IS_SAAS:
        raise HTTPException(404, "Not found")


@admin_router.post("/checkout")
async def billing_checkout(body: CheckoutRequest, request: Request) -> dict:
    """Create a Stripe Checkout session and return the redirect URL."""
    _require_saas()
    tenant_id = require_root(request)
    payload = require_authenticated(request)

    url = create_checkout_session(tenant_id, payload.email, body.success_url, body.cancel_url, body.plan)
    return {"url": url}


@admin_router.post("/portal")
async def billing_portal(body: PortalRequest, request: Request) -> dict:
    """Create a Stripe Customer Portal session and return the redirect URL."""
    _require_saas()
    tenant_id = require_root(request)
    payload = require_authenticated(request)

    url = create_portal_session(tenant_id, payload.email, body.return_url)
    return {"url": url}


@admin_router.get("/status")
async def billing_status(request: Request) -> dict:
    """Return current plan, subscription status, usage counts, and limits."""
    _require_saas()
    tenant_id = require_root(request)

    plan = get_effective_tenant_plan(tenant_id)
    subscription = get_subscription_details(tenant_id)
    retention = enforce_retention_best_effort(tenant_id)
    usage = get_usage(tenant_id)
    synced_addons = sync_stripe_addons_best_effort(tenant_id)
    llm_usage = get_llm_billing_usage(tenant_id)
    limits = get_tenant_limits(tenant_id)
    features = get_tenant_features(tenant_id)
    entitlements = entitlement_context(tenant_id)

    return {
        "plan": plan,
        "deploymentMode": entitlements["deployment"],
        "edition": entitlements["edition"],
        "subscriptionStatus": subscription["status"],
        "cancelAtPeriodEnd": subscription["cancel_at_period_end"],
        "currentPeriodStart": subscription["current_period_start"],
        "currentPeriodEnd": subscription["current_period_end"],
        "usage": {
            "agentRunsThisPeriod": usage["agent_runs_this_period"],
            # Transitional alias for older admin clients.
            "emailsThisPeriod": usage["agent_runs_this_period"],
            "projects": usage["projects"],
            "users": usage["users"],
            "evalRunsThisPeriod": usage["eval_runs_this_period"],
            "evalSets": usage["eval_sets"],
        },
        "llmUsage": {
            "eventCount": llm_usage["event_count"],
            "managedEventCount": llm_usage["managed_event_count"],
            "reportedEventCount": llm_usage["reported_event_count"],
            "rawCostUsdMicros": llm_usage["raw_cost_usd_micros"],
            "billedCostUsdMicros": llm_usage["billed_cost_usd_micros"],
            "rawCostUsd": llm_usage["raw_cost_usd"],
            "billedCostUsd": llm_usage["billed_cost_usd"],
        },
        "syncedAddons": synced_addons,
        "retention": retention,
        "limits": {
            "agentRunsPerMonth": limits["emails_per_month"],
            # Transitional alias for older admin clients.
            "emailsPerMonth": limits["emails_per_month"],
            "projects": limits["projects"],
            "users": limits["users"],
            "evalRunsPerMonth": limits["eval_runs_per_month"],
            "evalSets": limits["eval_sets"],
            "evalCasesPerSet": limits["eval_cases_per_set"],
            "retentionDays": limits["retention_days"],
        },
        "metering": {
            "unit": "agent_run",
            "definition": (
                "One inbound customer message processed, regardless of concerns, "
                "runbooks, knowledge searches, tool calls, or response steps."
            ),
        },
        "features": features,
    }


# ── Webhook endpoint (no auth — uses Stripe signature verification) ───────────

webhook_router = APIRouter()


@webhook_router.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict:
    """Receive and process Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not sig_header:
        raise HTTPException(400, "Missing stripe-signature header")

    event = verify_webhook_signature(payload, sig_header)
    handle_webhook_event(event)

    return {"status": "ok"}
