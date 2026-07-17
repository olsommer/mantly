"""Compatibility helpers for consumers of multi-concern intent results."""

from __future__ import annotations

from typing import Any


def _field(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def scoped_intent_actions(intent_result: Any) -> list[tuple[str, str, Any]]:
    """Return each concern action with its stable concern and runbook scope.

    New multi-concern results source actions from ``concerns``. Legacy results
    without concern actions fall back to top-level ``actions``.
    """
    if intent_result is None:
        return []

    scoped: list[tuple[str, str, Any]] = []
    for concern in _field(intent_result, "concerns", default=[]) or []:
        outcome = _field(concern, "outcome", "runbookOutcome", "runbook_outcome", default=None) or concern
        concern_id = str(_field(concern, "concern_id", "concernId", default="") or "")
        intent_name = str(
            _field(concern, "intent_name", "intentName", "runbook", default=None)
            or _field(outcome, "intent_name", "intentName", "runbook", default="")
            or ""
        )
        actions = _field(outcome, "actions", default=None) or _field(concern, "actions", default=[])
        for action in actions or []:
            scoped.append((concern_id, intent_name, action))

    if scoped:
        return scoped

    intent_name = str(_field(intent_result, "intent_name", "intentName", default="") or "")
    return [
        ("", intent_name, action)
        for action in _field(intent_result, "actions", default=[]) or []
    ]


def resolve_intent_action_payloads(intent_result: Any, identity_data: dict[str, Any]) -> None:
    """Merge identity data into legacy and concern-scoped action instances."""
    if intent_result is None or not identity_data:
        return

    action_instances = list(_field(intent_result, "actions", default=[]) or [])
    for concern in _field(intent_result, "concerns", default=[]) or []:
        outcome = _field(concern, "outcome", "runbookOutcome", "runbook_outcome", default=None) or concern
        actions = _field(outcome, "actions", default=None) or _field(concern, "actions", default=[])
        action_instances.extend(actions or [])

    seen: set[int] = set()
    for action in action_instances:
        marker = id(action)
        if marker in seen:
            continue
        seen.add(marker)
        current = _field(action, "payload", default={})
        current_payload = current if isinstance(current, dict) else {}
        resolved = {**identity_data, **current_payload}
        if isinstance(action, dict):
            action["payload"] = resolved
        else:
            action.payload = resolved


def attachment_intent_names(
    intent_result: Any,
    filename: str,
    *,
    owners_only: bool = False,
) -> list[str]:
    """Return matched runbooks, prioritizing those that own ``filename``."""
    if intent_result is None:
        return []

    owners: list[str] = []
    remaining: list[str] = []
    for concern in _field(intent_result, "concerns", default=[]) or []:
        outcome = _field(concern, "outcome", "runbookOutcome", "runbook_outcome", default=None) or concern
        intent_name = str(
            _field(concern, "intent_name", "intentName", "runbook", default=None)
            or _field(outcome, "intent_name", "intentName", "runbook", default="")
            or ""
        ).strip()
        if not intent_name:
            continue
        attachment_names = {
            str(_field(item, "filename", default="") or "").strip()
            for item in (
                _field(outcome, "attachments", default=None)
                or _field(concern, "attachments", default=[])
                or []
            )
        }
        target = owners if filename in attachment_names else remaining
        if intent_name not in target:
            target.append(intent_name)

    if owners_only:
        return owners

    primary = str(_field(intent_result, "intent_name", "intentName", default="") or "").strip()
    if primary and primary not in owners and primary not in remaining:
        remaining.insert(0, primary)

    return [*owners, *remaining]
