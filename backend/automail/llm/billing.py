"""LLM billing metadata and cost estimation helpers."""
from __future__ import annotations

import json
import os
from typing import Any

LLM_BILLING_INCLUDED = "included"
LLM_BILLING_BYOK = "byok"
LLM_BILLING_MANTLY_MANAGED = "mantly_managed"

LLM_COST_MARKUP: float = float(os.getenv("LLM_COST_MARKUP", "1.2"))

# USD per 1M tokens. Override/extend with LLM_PRICE_TABLE_JSON:
# {"model-prefix":{"input":0.4,"output":1.6,"cached_input":0.1}}
DEFAULT_PRICE_TABLE: dict[str, dict[str, float]] = {
    "gemini-3-flash-preview": {"input": 0.5, "output": 3.0, "cached_input": 0.5},
    "gpt-4.1-mini": {"input": 0.4, "output": 1.6, "cached_input": 0.1},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6, "cached_input": 0.075},
    "gpt-5-mini": {"input": 0.25, "output": 2.0, "cached_input": 0.025},
}


def price_table() -> dict[str, dict[str, float]]:
    raw = os.getenv("LLM_PRICE_TABLE_JSON", "").strip()
    if not raw:
        return DEFAULT_PRICE_TABLE
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return DEFAULT_PRICE_TABLE
    if not isinstance(parsed, dict):
        return DEFAULT_PRICE_TABLE
    table = DEFAULT_PRICE_TABLE.copy()
    for key, value in parsed.items():
        if isinstance(key, str) and isinstance(value, dict):
            table[key] = {
                "input": float(value.get("input", 0) or 0),
                "output": float(value.get("output", 0) or 0),
                "cached_input": float(value.get("cached_input", value.get("input", 0)) or 0),
            }
    return table


def managed_llm_env() -> dict[str, str]:
    provider = os.getenv("MANTLY_MANAGED_LLM_PROVIDER", "gemini").strip() or "gemini"
    return {
        "llm_provider": provider,
        "llm_model": os.getenv("MANTLY_MANAGED_LLM_MODEL", "").strip(),
        "llm_api_key": (
            os.getenv("MANTLY_MANAGED_LLM_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
        ),
        "llm_custom_base_url": os.getenv("MANTLY_MANAGED_LLM_CUSTOM_BASE_URL", "").strip(),
        "llm_custom_model": os.getenv("MANTLY_MANAGED_LLM_CUSTOM_MODEL", "").strip(),
    }


def estimate_cost_usd_micros(
    *,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_input_tokens: int | None = None,
) -> int:
    rates = _rates_for_model(model)
    if not rates:
        return 0
    input_count = max(int(input_tokens or 0) - int(cached_input_tokens or 0), 0)
    cached_count = int(cached_input_tokens or 0)
    output_count = int(output_tokens or 0)
    cost_usd = (
        input_count * rates["input"] / 1_000_000
        + cached_count * rates.get("cached_input", rates["input"]) / 1_000_000
        + output_count * rates["output"] / 1_000_000
    )
    return int(round(cost_usd * 1_000_000))


def annotate_usage_event(event: dict[str, Any], *, billing_mode: str) -> dict[str, Any]:
    raw_micros = estimate_cost_usd_micros(
        model=str(event.get("model") or ""),
        input_tokens=event.get("inputTokens"),
        output_tokens=event.get("outputTokens"),
        cached_input_tokens=event.get("cachedInputTokens"),
    )
    billed_micros = 0
    if billing_mode == LLM_BILLING_MANTLY_MANAGED:
        billed_micros = int(round(raw_micros * LLM_COST_MARKUP))
    return {
        **event,
        "billingMode": billing_mode,
        "rawCostUsdMicros": raw_micros,
        "billedCostUsdMicros": billed_micros,
        "costMarkup": LLM_COST_MARKUP if billing_mode == LLM_BILLING_MANTLY_MANAGED else 0,
    }


def _rates_for_model(model: str) -> dict[str, float] | None:
    normalized = model.lower()
    for prefix, rates in price_table().items():
        if normalized.startswith(prefix.lower()):
            return rates
    return None
