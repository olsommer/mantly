"""Provider-metadata-only LLM token usage collection."""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_collector_var: ContextVar["LLMUsageCollector | None"] = ContextVar("llm_usage_collector", default=None)
_stage_var: ContextVar[str] = ContextVar("llm_usage_stage", default="unknown")
_stage_started_var: ContextVar[float | None] = ContextVar("llm_usage_stage_started", default=None)


class LLMUsageCollector:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def aggregate(self) -> dict[str, Any]:
        return aggregate_usage_calls(self.events)


@contextmanager
def collect_llm_usage() -> Any:
    collector = LLMUsageCollector()
    token = _collector_var.set(collector)
    try:
        yield collector
    finally:
        _collector_var.reset(token)


@contextmanager
def llm_stage(stage: str) -> Any:
    stage_token = _stage_var.set(stage)
    started_token = _stage_started_var.set(time.perf_counter())
    try:
        yield
    finally:
        _stage_started_var.reset(started_token)
        _stage_var.reset(stage_token)


def current_collector() -> LLMUsageCollector | None:
    return _collector_var.get()


def aggregate_usage_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_calls = list(calls)
    return {
        "inputTokens": _sum_known(normalized_calls, "inputTokens"),
        "outputTokens": _sum_known(normalized_calls, "outputTokens"),
        "cachedInputTokens": _sum_known(normalized_calls, "cachedInputTokens"),
        "totalTokens": _sum_known(normalized_calls, "totalTokens"),
        "calls": normalized_calls,
        "metadataAvailable": any(call.get("metadataAvailable") for call in normalized_calls),
    }


def record_usage_from_result(result: Any, usage_context: dict[str, Any] | None = None) -> None:
    """Record provider token metadata from a LangChain response or agent result."""
    collector = current_collector()
    if collector is None:
        return

    context = usage_context or {}
    raw_payloads = _extract_usage_payloads(result)
    stage_started = _stage_started_var.get()
    duration_ms = (
        max(0, round((time.perf_counter() - stage_started) * 1_000))
        if stage_started is not None and raw_payloads
        else None
    )
    for raw_usage in raw_payloads:
        normalized = normalize_usage(raw_usage)
        event = {
            "stage": _stage_var.get(),
            "provider": context.get("provider") or _infer_provider(_extract_model(raw_usage) or context.get("model")),
            "model": _extract_model(raw_usage) or context.get("model") or "",
            **normalized,
            "rawUsage": raw_usage,
        }
        if duration_ms is not None:
            event["durationMs"] = duration_ms
        try:
            from automail.llm.billing import annotate_usage_event
            event = annotate_usage_event(event, billing_mode=str(context.get("billing_mode") or "byok"))
        except Exception:
            event["billingMode"] = context.get("billing_mode") or "byok"
        collector.add(event)


def normalize_usage(raw_usage: dict[str, Any]) -> dict[str, Any]:
    input_tokens = _find_first_number(raw_usage, {
        "input_tokens",
        "prompt_tokens",
        "promptTokenCount",
        "prompt_token_count",
    })
    output_tokens = _find_first_number(raw_usage, {
        "output_tokens",
        "completion_tokens",
        "candidatesTokenCount",
        "candidates_token_count",
    })
    cached_input_tokens = _find_first_number(raw_usage, {
        "cached_tokens",
        "cached_input_tokens",
        "cachedInputTokens",
        "cachedContentTokenCount",
        "cached_content_token_count",
        "cache_read_input_tokens",
        "cache_read",
    })
    total_tokens = _find_first_number(raw_usage, {
        "total_tokens",
        "totalTokenCount",
        "total_token_count",
    })
    metadata_available = any(v is not None for v in (
        input_tokens,
        output_tokens,
        cached_input_tokens,
        total_tokens,
    ))
    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cachedInputTokens": cached_input_tokens,
        "totalTokens": total_tokens,
        "metadataAvailable": metadata_available,
    }


def _extract_raw_usage(response: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {}

    llm_output = getattr(response, "llm_output", None)
    if isinstance(llm_output, dict):
        raw["llm_output"] = llm_output

    for generation_group in getattr(response, "generations", []) or []:
        for generation in generation_group or []:
            message = getattr(generation, "message", None)
            if message is None:
                continue
            usage_metadata = getattr(message, "usage_metadata", None)
            response_metadata = getattr(message, "response_metadata", None)
            if usage_metadata:
                raw.setdefault("message_usage_metadata", []).append(_to_plain(usage_metadata))
            if response_metadata:
                raw.setdefault("message_response_metadata", []).append(_to_plain(response_metadata))

    return raw


def _extract_usage_payloads(result: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    if isinstance(result, dict):
        for message in result.get("messages", []) or []:
            raw = _extract_message_usage(message)
            if raw:
                payloads.append(raw)
        return payloads

    raw = _extract_message_usage(result)
    if raw:
        return [raw]

    raw = _extract_raw_usage(result)
    return [raw] if raw else []


def _extract_message_usage(message: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    usage_metadata = getattr(message, "usage_metadata", None)
    response_metadata = getattr(message, "response_metadata", None)
    if usage_metadata:
        raw["message_usage_metadata"] = _to_plain(usage_metadata)
    if response_metadata:
        raw["message_response_metadata"] = _to_plain(response_metadata)
    return raw


def _extract_model(value: Any) -> str | None:
    raw = value if isinstance(value, dict) else _extract_raw_usage(value)
    return _find_first_string(raw, {"model_name", "model", "modelVersion", "model_version"})


def _infer_provider(model: Any) -> str:
    normalized = str(model or "").lower()
    if normalized.startswith("gemini"):
        return "gemini"
    if normalized.startswith("gpt") or normalized.startswith("o"):
        return "custom"
    return ""


def _find_first_number(value: Any, names: set[str]) -> int | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in names and isinstance(item, (int, float)):
                return int(item)
        for item in value.values():
            found = _find_first_number(item, names)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_first_number(item, names)
            if found is not None:
                return found
    return None


def _find_first_string(value: Any, names: set[str]) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in names and isinstance(item, str) and item:
                return item
        for item in value.values():
            found = _find_first_string(item, names)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_first_string(item, names)
            if found:
                return found
    return None


def _sum_known(calls: list[dict[str, Any]], key: str) -> int | None:
    values = [int(value) for call in calls if isinstance((value := call.get(key)), (int, float))]
    if not values:
        return None
    return int(sum(values))


def _to_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    return value
