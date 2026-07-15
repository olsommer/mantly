"""Create Mantly Stripe billing products, prices, and meter.

Usage:
    STRIPE_SECRET_KEY=sk_live_... uv run python tools/setup_stripe_billing.py

The script prints the env vars that must be configured on the API service.
It is idempotent for prices via Stripe lookup keys.
"""
from __future__ import annotations

import os
from pathlib import Path

import stripe

CURRENCY = os.getenv("STRIPE_BILLING_CURRENCY", "eur").lower()
LLM_EVENT_NAME = os.getenv("STRIPE_LLM_METER_EVENT_NAME", "mantly_llm_usage")


def _require_key() -> None:
    key = os.getenv("STRIPE_SECRET_KEY", "").strip() or _stripe_cli_key()
    if not key:
        raise SystemExit("STRIPE_SECRET_KEY is required or Stripe CLI must be authenticated")
    stripe.api_key = key


def _stripe_cli_key() -> str:
    config_path = Path.home() / ".config" / "stripe" / "config.toml"
    if not config_path.exists():
        return ""
    for line in config_path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("live_mode_api_key") or stripped.startswith("test_mode_api_key"):
            _, _, value = stripped.partition("=")
            return value.strip().strip('"')
    return ""


def _existing_price(lookup_key: str):
    prices = stripe.Price.list(lookup_keys=[lookup_key], active=True, limit=1)
    data = getattr(prices, "data", None) or []
    return data[0] if data else None


def _product(name: str, key: str):
    return stripe.Product.create(
        name=name,
        metadata={"mantly_key": key},
    )


def _licensed_price(*, lookup_key: str, name: str, amount_cents: int):
    existing = _existing_price(lookup_key)
    if existing:
        return existing
    product = _product(name, lookup_key)
    return stripe.Price.create(
        product=product.id,
        lookup_key=lookup_key,
        currency=CURRENCY,
        unit_amount=amount_cents,
        recurring={"interval": "month", "usage_type": "licensed"},
    )


def _meter():
    meters = stripe.billing.Meter.list(limit=100)
    data = getattr(meters, "data", None) or []
    for meter in data:
        if getattr(meter, "event_name", None) == LLM_EVENT_NAME:
            return meter
    return stripe.billing.Meter.create(
        display_name="Mantly-managed LLM usage",
        event_name=LLM_EVENT_NAME,
        default_aggregation={"formula": "sum"},
        customer_mapping={
            "type": "by_id",
            "event_payload_key": "stripe_customer_id",
        },
        value_settings={"event_payload_key": "value"},
    )


def _metered_price(*, lookup_key: str, meter_id: str):
    existing = _existing_price(lookup_key)
    if existing:
        return existing
    product = _product("Mantly-managed LLM usage", lookup_key)
    return stripe.Price.create(
        product=product.id,
        lookup_key=lookup_key,
        currency=CURRENCY,
        unit_amount_decimal="0.0001",
        recurring={
            "interval": "month",
            "usage_type": "metered",
            "meter": meter_id,
        },
    )


def main() -> None:
    _require_key()
    pro = _licensed_price(lookup_key="mantly_pro_monthly", name="Mantly Pro", amount_cents=1900)
    business = _licensed_price(lookup_key="mantly_business_monthly", name="Mantly Business", amount_cents=19900)
    extra_user = _licensed_price(lookup_key="mantly_extra_user_monthly", name="Mantly extra user", amount_cents=900)
    extra_project = _licensed_price(lookup_key="mantly_extra_project_monthly", name="Mantly extra project", amount_cents=4900)
    extra_email_block = _licensed_price(
        lookup_key="mantly_extra_100_emails_monthly",
        name="Mantly extra 100 emails",
        amount_cents=900,
    )
    meter = _meter()
    llm_usage = _metered_price(lookup_key="mantly_llm_usage_micro_monthly", meter_id=meter.id)

    print("STRIPE_PRO_PRICE_ID=" + pro.id)
    print("STRIPE_BUSINESS_PRICE_ID=" + business.id)
    print("STRIPE_EXTRA_USER_PRICE_ID=" + extra_user.id)
    print("STRIPE_EXTRA_PROJECT_PRICE_ID=" + extra_project.id)
    print("STRIPE_EXTRA_EMAIL_BLOCK_PRICE_ID=" + extra_email_block.id)
    print("STRIPE_EXTRA_EMAIL_BLOCK_SIZE=100")
    print("STRIPE_LLM_USAGE_PRICE_ID=" + llm_usage.id)
    print("STRIPE_LLM_METER_EVENT_NAME=" + LLM_EVENT_NAME)


if __name__ == "__main__":
    main()
