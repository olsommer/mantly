"""Provider-metadata-only LLM token usage collection."""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

_collector_var: ContextVar["LLMUsageCollector | None"] = ContextVar("llm_usage_collector", default=None)
_stage_var: ContextVar[str] = ContextVar("llm_usage_stage", default="unknown")
_stage_started_var: ContextVar[float | None] = ContextVar("llm_usage_stage_started", default=None)
_stage_execution_id_var: ContextVar[str] = ContextVar("llm_usage_stage_execution_id", default="")


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
    execution_id_token = _stage_execution_id_var.set(uuid4().hex)
    try:
        yield
    finally:
        _stage_execution_id_var.reset(execution_id_token)
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
        "stageExecutions": _aggregate_stage_executions(normalized_calls),
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
    stage_execution_id = _stage_execution_id_var.get()
    usage_record_id = uuid4().hex
    duration_ms = (
        max(0, round((time.perf_counter() - stage_started) * 1_000))
        if stage_started is not None and raw_payloads
        else None
    )
    payload_count = len(raw_payloads)
    for payload_index, raw_usage in enumerate(raw_payloads, start=1):
        normalized = normalize_usage(raw_usage)
        event = {
            "stage": _stage_var.get(),
            "provider": context.get("provider") or _infer_provider(_extract_model(raw_usage) or context.get("model")),
            "model": _extract_model(raw_usage) or context.get("model") or "",
            **normalized,
            "rawUsage": raw_usage,
            "usageRecordId": usage_record_id,
            "usagePayloadIndex": payload_index,
            "usagePayloadCount": payload_count,
        }
        if stage_execution_id:
            event["stageExecutionId"] = stage_execution_id
        if duration_ms is not None:
            event["durationMs"] = duration_ms
            # This is the wall time from entering llm_stage() until the
            # enclosing result is recorded. It is intentionally shared by all
            # provider-usage payloads extracted from that result and must not
            # be summed as if it were a per-provider-call duration.
            event["durationScope"] = "stage_wall_time"
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


def _aggregate_stage_executions(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize stage wall time once per execution instead of per usage row."""
    groups: dict[str, dict[str, Any]] = {}
    record_ids: dict[str, set[str]] = {}
    for call in calls:
        execution_id = str(call.get("stageExecutionId") or "")
        if not execution_id:
            continue
        group = groups.setdefault(execution_id, {
            "id": execution_id,
            "stage": call.get("stage") or "unknown",
            "durationMs": None,
            "durationScope": call.get("durationScope") or "stage_wall_time",
            "usageRecordCount": 0,
            "usageEventCount": 0,
        })
        group["usageEventCount"] += 1
        duration = call.get("durationMs")
        if isinstance(duration, (int, float)):
            current = group.get("durationMs")
            group["durationMs"] = int(duration) if current is None else max(int(current), int(duration))
        usage_record_id = str(call.get("usageRecordId") or "")
        if usage_record_id:
            ids = record_ids.setdefault(execution_id, set())
            ids.add(usage_record_id)
            group["usageRecordCount"] = len(ids)
    return list(groups.values())


def _to_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    return value
