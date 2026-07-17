"""Deterministic guard for customer-facing claims about pending actions."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

PENDING_ACTION_CLAIM_REASON_CODE = "pending_action_claim"

_PROGRESSIVE_ACTIONS = (
    r"initiating",
    r"checking",
    r"escalating",
    r"investigating",
    r"opening",
    r"submitting",
    r"processing",
    r"reviewing",
    r"contacting",
    r"arranging",
    r"scheduling",
    r"issuing",
    r"refunding",
    r"cancell?ing",
    r"changing",
    r"updating",
    r"dispatching",
    r"reshipping",
    r"replacing",
    r"creating",
    r"starting",
    r"beginning",
    r"activating",
    r"authorizing",
    r"working\s+on",
    r"looking\s+into",
    r"following\s+up",
    r"reaching\s+out",
    r"taking\s+action",
)
_COMPLETED_ACTIONS = (
    r"initiated",
    r"checked",
    r"escalated",
    r"investigated",
    r"opened",
    r"submitted",
    r"processed",
    r"reviewed",
    r"contacted",
    r"arranged",
    r"scheduled",
    r"issued",
    r"refunded",
    r"cancelled",
    r"canceled",
    r"changed",
    r"updated",
    r"dispatched",
    r"reshipped",
    r"replaced",
    r"created",
    r"flagged",
    r"marked",
    r"started",
    r"begun",
    r"activated",
    r"authorized",
    r"completed",
    r"finished",
)

_PROGRESSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:we\s+are|we['’]re|i\s+am|i['’]m)\s+"
    rf"(?:(?:already|currently|now|actively)\s+)*(?:{'|'.join(_PROGRESSIVE_ACTIONS)})\b",
    re.IGNORECASE,
)
_PERFECT_ACTION_PATTERN = re.compile(
    rf"\b(?:we\s+have|we['’]ve|i\s+have|i['’]ve)\s+"
    rf"(?:(?:already|successfully|now)\s+)*(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_PAST_ACTION_PATTERN = re.compile(
    rf"\b(?:we|i)\s+(?:(?:already|successfully)\s+)*(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_PASSIVE_ACTION_PATTERN = re.compile(
    rf"\b(?:the|this|your|our)\s+[^.!?\n]{{0,100}}?\b"
    rf"(?:has|have|is|are|was|were)\s+(?:(?:already|successfully|now|currently)\s+)*"
    rf"(?:been\s+|being\s+)?(?:{'|'.join(_COMPLETED_ACTIONS)})\b",
    re.IGNORECASE,
)
_ACTIVE_STATE_PATTERN = re.compile(
    r"\b(?:investigation|escalation|claim|refund|cancellation|cancelation|replacement|return|request|case|ticket|review)"
    r"\s+(?:is|are)\s+(?:(?:already|now|currently)\s+)*(?:underway|in\s+progress|ongoing)\b",
    re.IGNORECASE,
)
_ANSWER_UNIT_PATTERN = re.compile(r"[^.!?\n]+(?:[.!?]+|(?=\n)|$)")
_CLAIM_PATTERNS = (
    _PROGRESSIVE_ACTION_PATTERN,
    _PERFECT_ACTION_PATTERN,
    _PAST_ACTION_PATTERN,
    _PASSIVE_ACTION_PATTERN,
    _ACTIVE_STATE_PATTERN,
)


@dataclass(frozen=True)
class PendingActionClaimCheck:
    """Result consumed before a generated customer draft is accepted."""

    pending_actions: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.pending_actions and self.claims)


def _pending_action_names(runbook_actions: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    names: list[str] = []
    for action in runbook_actions:
        status = str(action.get("status") or "").strip().lower().replace("-", "_")
        if status != "pending_approval":
            continue
        name = str(action.get("label") or action.get("name") or "pending action").strip()
        if name and name not in names:
            names.append(name[:160])
    return tuple(names[:20])


def _answer_units(answer: str) -> tuple[str, ...]:
    units = [match.group(0).strip() for match in _ANSWER_UNIT_PATTERN.finditer(answer) if match.group(0).strip()]
    return tuple(units or ([answer.strip()] if answer.strip() else []))


def check_pending_action_claims(
    *,
    answer: str,
    runbook_actions: Iterable[Mapping[str, Any]],
) -> PendingActionClaimCheck:
    """Block active/completed wording when any supplied runbook action awaits approval.

    Conditional, future, negative, and explicit pending wording do not match the
    prohibited first-person, passive-completed, or active-state forms.
    """

    pending_actions = _pending_action_names(runbook_actions)
    if not pending_actions:
        return PendingActionClaimCheck()

    claims: list[str] = []
    for unit in _answer_units(answer):
        if any(pattern.search(unit) for pattern in _CLAIM_PATTERNS) and unit not in claims:
            claims.append(unit[:500])
    return PendingActionClaimCheck(
        pending_actions=pending_actions,
        claims=tuple(claims[:20]),
    )
