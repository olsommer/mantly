"""Billing-period usage counting and limit checks."""

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from automail.billing.config import (
    IS_SAAS,
    PLAN_LIMITS,
    STRIPE_EXTRA_EMAIL_BLOCK_PRICE_ID,
    STRIPE_EXTRA_PROJECT_PRICE_ID,
    STRIPE_EXTRA_USER_PRICE_ID,
    UNLIMITED,
)
from automail.billing.tenant import get_effective_tenant_plan, get_tenant_record


def _pb_date_filter_value(value: datetime) -> str:
    """Format a datetime for PocketBase date comparisons."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000Z")

def _current_period_start_iso(tenant_id: str) -> str:
    """Return the start of the current billing period as ISO string.

    If Stripe has synced a concrete period start, use that.  Older tenant
    records may only have ``current_period_end``; for those, fall back to the
    1st of the current month.
    """
    rec = get_tenant_record(tenant_id)

    period_start_str = rec.get("current_period_start")
    if period_start_str:
        try:
            period_start = datetime.fromisoformat(period_start_str.replace("Z", "+00:00"))
            return _pb_date_filter_value(period_start)
        except (ValueError, TypeError):
            pass

    # Fallback: 1st of current month
    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return _pb_date_filter_value(period_start)

def get_usage(tenant_id: str) -> dict[str, int]:
    """Return current usage counts for the tenant.

    Keys: ``emails_this_period``, ``projects``, ``users``, ``eval_runs_this_period``,
    ``eval_sets``.
    """
    from automail.db.pocketbase.client import _escape_pb, _list_all

    period_start = _current_period_start_iso(tenant_id)
    esc_tid = _escape_pb(tenant_id)

    # Emails this period
    emails = _list_all(
        "chats",
        f"tenant='{esc_tid}' && status='analyzed' && created>='{period_start}'",
    )

    # Total projects
    projects = _list_all("projects", f"tenant='{esc_tid}'")

    # Total users
    users = _list_all("users", f"tenant='{esc_tid}'")

    # Eval runs this period
    eval_runs = _list_all(
        "eval_runs",
        f"tenant='{esc_tid}' && created>='{period_start}'",
    )

    # Total eval sets
    eval_sets = _list_all("eval_sets", f"tenant='{esc_tid}'")

    return {
        "emails_this_period": len(emails),
        "projects": len(projects),
        "users": len(users),
        "eval_runs_this_period": len(eval_runs),
        "eval_sets": len(eval_sets),
    }

def get_llm_billing_usage(tenant_id: str) -> dict[str, Any]:
    """Return current-period LLM cost summary for billing visibility."""
    from automail.db.pocketbase.client import _escape_pb, _list_all

    period_start = _current_period_start_iso(tenant_id)
    esc_tid = _escape_pb(tenant_id)
    events = _list_all(
        "llm_usage_events",
        f"tenant='{esc_tid}' && created>='{period_start}'",
    )
    raw_micros = sum(int(event.get("raw_cost_usd_micros") or 0) for event in events)
    billed_micros = sum(int(event.get("billed_cost_usd_micros") or 0) for event in events)
    managed_events = [event for event in events if event.get("billing_mode") == "mantly_managed"]
    return {
        "event_count": len(events),
        "managed_event_count": len(managed_events),
        "reported_event_count": len([event for event in managed_events if event.get("stripe_reported")]),
        "raw_cost_usd_micros": raw_micros,
        "billed_cost_usd_micros": billed_micros,
        "raw_cost_usd": round(raw_micros / 1_000_000, 6),
        "billed_cost_usd": round(billed_micros / 1_000_000, 6),
    }

def _get_limit(plan: str, resource: str) -> int:
    """Return the limit for a given resource on a plan."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"]).get(resource, 0)

def get_tenant_limit(tenant_id: str | None, resource: str) -> int:
    if not IS_SAAS or not tenant_id:
        return UNLIMITED
    return _get_limit(get_effective_tenant_plan(tenant_id), resource)

def _is_unlimited(limit: int) -> bool:
    return limit < 0

def _addon_price_for_resource(resource: str) -> str:
    return {
        "emails_per_month": STRIPE_EXTRA_EMAIL_BLOCK_PRICE_ID,
        "projects": STRIPE_EXTRA_PROJECT_PRICE_ID,
        "users": STRIPE_EXTRA_USER_PRICE_ID,
    }.get(resource, "")

def check_limit(tenant_id: str, resource: str) -> None:
    """Raise ``HTTPException(402)`` if the tenant has exceeded the limit for *resource*.

    *resource* must be one of: ``emails_per_month``, ``projects``, ``users``,
    ``eval_runs_per_month``, ``eval_sets``.

    No-op when ``IS_SAAS`` is false (on-prem deployments are unlimited).
    """
    if not IS_SAAS:
        return

    plan = get_effective_tenant_plan(tenant_id)
    limit = _get_limit(plan, resource)
    if _is_unlimited(limit):
        return

    usage = get_usage(tenant_id)

    # Map resource name to usage key
    usage_key_map = {
        "emails_per_month": "emails_this_period",
        "projects": "projects",
        "users": "users",
        "eval_runs_per_month": "eval_runs_this_period",
        "eval_sets": "eval_sets",
    }
    usage_key = usage_key_map.get(resource, resource)
    current = usage.get(usage_key, 0)

    if current >= limit:
        if plan != "free" and _addon_price_for_resource(resource):
            return
        raise HTTPException(
            status_code=402,
            detail={
                "error": "plan_limit_exceeded",
                "resource": resource,
                "limit": limit,
                "current": current,
                "plan": plan,
                "message": (
                    f"You have reached the {resource.replace('_', ' ')} limit "
                    f"({limit}) on the {plan} plan. Upgrade to increase your limits."
                ),
            },
        )

def check_eval_cases_limit(tenant_id: str | None, set_id: str) -> None:
    """Enforce per-eval-set case limits."""
    if not IS_SAAS or not tenant_id:
        return

    limit = get_tenant_limit(tenant_id, "eval_cases_per_set")
    if _is_unlimited(limit):
        return

    from automail.db.pocketbase.client import _escape_pb, _list_all

    cases = _list_all("eval_cases", f"eval_set='{_escape_pb(set_id)}'")
    current = len(cases)
    if current >= limit:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "plan_limit_exceeded",
                "resource": "eval_cases_per_set",
                "limit": limit,
                "current": current,
                "plan": get_effective_tenant_plan(tenant_id),
                "message": (
                    f"You have reached the eval cases per set limit ({limit}) "
                    "on your plan. Upgrade to increase your limits."
                ),
            },
        )
