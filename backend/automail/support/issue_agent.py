"""Ticket agent answer generation."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextvars import copy_context
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.tools import tool
from pydantic import BaseModel, Field, computed_field

from automail.support.knowledge_workspace import KnowledgeWorkspace
from automail.support.pending_action_claims import (
    PENDING_ACTION_CLAIM_REASON_CODE,
    action_obligation_parts,
    action_record_matches_expected_text,
    check_pending_action_claims,
    has_meaningful_action_success_proof,
    has_success_backed_action_claim,
    remaining_action_obligation_text,
    repair_pending_action_claims,
)
from automail.support.reply_signoff import clean_reply_signoff
from automail.support.safety_guidance import (
    SAFETY_GUIDANCE_MISSING_REASON_CODE,
    SafetyGuidanceAssessment,
    assess_lithium_battery_safety,
    lithium_battery_safety_system_prompt,
    missing_lithium_battery_safety_guidance,
)

logger = logging.getLogger(__name__)
_KNOWLEDGE_AGENT_SLOTS = threading.BoundedSemaphore(4)
_KNOWLEDGE_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="knowledge-agent")
KNOWLEDGE_AGENT_DEADLINE_SECONDS = 75
KNOWLEDGE_AGENT_MODEL_CALL_LIMIT = 9
KNOWLEDGE_AGENT_TOOL_CALL_LIMIT = 8
_KNOWLEDGE_REQUEST_ITEM_LIMIT = 20
_AUTOMATION_AGENT_SLOTS = threading.BoundedSemaphore(8)
_AUTOMATION_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="automation-agent")
AUTOMATION_AGENT_DEADLINE_SECONDS = 55
AUTOMATION_AGENT_SLOT_WAIT_SECONDS = 40
_GROUNDING_AGENT_SLOTS = threading.BoundedSemaphore(8)
_GROUNDING_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="grounding-agent")
GROUNDING_MODEL_CALL_LIMIT = 2
GROUNDING_MODEL_CALL_TIMEOUT_SECONDS = 30
# Keep deterministic adjudication bounded; live Gemini reasoning otherwise
# exceeded the fail-closed parent deadline on a fully covered safety reply.
GROUNDING_MODEL_THINKING_BUDGET = 1024
# A protocol-complete second pass is intentionally allowed. Provider clients can
# return after their nominal transport timeout; live evidence observed an 86.8s
# first adjudication followed by a 20.8s reassessment. Keep enough parent-future
# headroom for both calls while retaining the same bounded, fail-closed deadline.
GROUNDING_AGENT_DEADLINE_SECONDS = 120
GROUNDING_AGENT_SLOT_WAIT_SECONDS = 40
GROUNDING_GATE_VERSION = "automation-grounding-v8"
GROUNDING_GATE_MAX_AGE_SECONDS = 10 * 60
GROUNDING_MAX_ARTICLE_CHARS = 30_000
GROUNDING_MAX_TOTAL_ARTICLE_CHARS = 60_000
_AUTOMATIC_RUNBOOK_ACTION_ERROR_MAX_CHARS = 500
_GROUNDING_TICKET_SCOPED_KEYS = frozenset(
    {
        "concerns",
        "toolEvidence",
        "runbookActions",
    }
)
LANGUAGE_MISMATCH_REASON_CODE = "language_mismatch"
BUSINESS_IDENTIFIER_MISMATCH_REASON_CODE = "identifier_mismatch"
_ADDRESSED_OBLIGATION_RESOLUTIONS = frozenset(
    {
        "answered",
        "fulfilled_action",
        "pending_or_unavailable",
    }
)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_SYSTEM_SAFETY_PROMPT = lithium_battery_safety_system_prompt()
_SYSTEM_PROMPT = (
    (_PROMPTS_DIR / "issue_agent_system_prompt.md").read_text(encoding="utf-8").strip() + "\n\n" + _SYSTEM_SAFETY_PROMPT
)
_USER_TEMPLATE = (_PROMPTS_DIR / "issue_agent_user_prompt.md").read_text(encoding="utf-8").strip()
_AUTOMATION_SYSTEM_PROMPT = (
    (_PROMPTS_DIR / "issue_automation_system_prompt.md").read_text(encoding="utf-8").strip()
    + "\n\n"
    + _SYSTEM_SAFETY_PROMPT
)
_AUTOMATION_USER_TEMPLATE = (_PROMPTS_DIR / "issue_automation_user_prompt.md").read_text(encoding="utf-8").strip()
_AUTOMATION_OBLIGATION_REPAIR_TEMPLATE = (
    (_PROMPTS_DIR / "issue_automation_obligation_repair.md").read_text(encoding="utf-8").strip()
)
_AUTOMATION_GROUNDING_REPAIR_TEMPLATE = (
    (_PROMPTS_DIR / "issue_automation_grounding_repair.md").read_text(encoding="utf-8").strip()
)
_GROUNDING_SYSTEM_PROMPT = (_PROMPTS_DIR / "issue_grounding_eval_system_prompt.md").read_text(encoding="utf-8").strip()
_GROUNDING_USER_TEMPLATE = (_PROMPTS_DIR / "issue_grounding_eval_user_prompt.md").read_text(encoding="utf-8").strip()
_GROUNDING_PROTOCOL_REPAIR_TEMPLATE = (
    (_PROMPTS_DIR / "issue_grounding_protocol_repair.md").read_text(encoding="utf-8").strip()
)
_GROUNDING_OBLIGATION_REASSESSMENT_INSTRUCTION = """

## Required Second-Pass Obligation Adjudication
The previous result linked one or more evidence-supported answer units to an
obligation but still marked that obligation `not_covered`. Reassess every answer
obligation from scratch using the unchanged evidence and immutable answer units.

Keep these two decisions separate:
1. whether every assertion in an answer unit is supported by allowed evidence;
2. whether supported units directly answer an obligation or explicitly state a
   pending/unavailable result and concrete next step.

Directly supplied status, last-event, ETA, limitation, or eligibility information
is `answered` for the matching question. For a requested action, a supported reply
that says the action cannot be done directly, is not confirmed or is pending human
review, and gives the concrete next step is `pending_or_unavailable`. It must never
be upgraded to `fulfilled_action` without successful exact same-concern action
evidence. Generic acknowledgement, intake-only language, repetition of the request,
or a promise to look into it remains `not_covered`.

A supported answer that explicitly says a requested guarantee cannot be made and
explains the evidence-backed controlling party or limitation directly addresses the
guarantee request; use `pending_or_unavailable`, not `not_covered`. For every
obligation, return only evidence IDs already attached to its linked answer units.

Do not assume the previous result was wrong and do not assume the reply is complete.
Return the full required structured result, reassessing every unit and obligation
exactly once.
""".strip()


class _AgentInvocationUsage:
    """Isolate one worker's usage from caller work that continues after timeout."""

    def __init__(self) -> None:
        self._calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def run(self, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        from automail.llm.usage import collect_llm_usage

        with collect_llm_usage() as collector:
            try:
                return callback()
            finally:
                with self._lock:
                    self._calls = [dict(event) for event in collector.events if isinstance(event, dict)]

    def calls(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(call) for call in self._calls]

    def merge_into(self, collector: Any) -> None:
        if collector is None:
            return
        for call in self.calls():
            collector.add(call)


def _finish_timed_out_agent(
    *,
    slot_semaphore: threading.BoundedSemaphore,
    invocation_usage: _AgentInvocationUsage,
    on_late_usage: Callable[[list[dict[str, Any]]], None] | None,
) -> None:
    """Release timed-out capacity and hand late provider usage to durable persistence."""
    slot_semaphore.release()
    if on_late_usage is None:
        return
    calls = invocation_usage.calls()
    if not calls:
        return
    try:
        on_late_usage(calls)
    except Exception:
        logger.exception("Failed to persist late support-agent usage")


@dataclass(frozen=True)
class IssueAgentDraft:
    answer: str
    confidence: str
    generation_mode: str
    error: str = ""
    citation_ids: tuple[str, ...] = field(default_factory=tuple)
    citation_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    missing_information: tuple[str, ...] = field(default_factory=tuple)
    response_attachments: tuple[str, ...] = field(default_factory=tuple)
    covered_concern_ids: tuple[str, ...] = field(default_factory=tuple)
    covered_obligation_ids: tuple[str, ...] = field(default_factory=tuple)
    requires_human: bool = False
    requires_human_reason: str = ""
    tool_calls: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AutomationGroundingAssessment:
    """Code-validated audit result for an automatic answer."""

    verified: bool
    status: str
    reason_code: str
    checked_at: str
    citation_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_snapshots: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    context_snapshots: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    answer_sha256: str = ""
    answer_units: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    unit_assessments: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    answer_obligations: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    obligation_assessments: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    uncovered_obligations: tuple[str, ...] = field(default_factory=tuple)
    pending_action_claims: tuple[str, ...] = field(default_factory=tuple)
    pending_actions: tuple[str, ...] = field(default_factory=tuple)
    claim_count: int = 0
    unsupported_claims: tuple[str, ...] = field(default_factory=tuple)
    contradictions: tuple[str, ...] = field(default_factory=tuple)
    provider: str = ""
    model: str = ""
    error: str = ""

    def as_metadata(self) -> dict[str, Any]:
        return {
            "version": GROUNDING_GATE_VERSION,
            "verified": self.verified,
            "status": self.status,
            "reasonCode": self.reason_code,
            "checkedAt": self.checked_at,
            "provider": self.provider,
            "model": self.model,
            "modelCallLimit": GROUNDING_MODEL_CALL_LIMIT,
            "answerSha256": self.answer_sha256,
            "answerUnits": [dict(unit) for unit in self.answer_units],
            "unitAssessments": [dict(assessment) for assessment in self.unit_assessments],
            "answerObligations": [dict(obligation) for obligation in self.answer_obligations],
            "obligationAssessments": [dict(assessment) for assessment in self.obligation_assessments],
            "uncoveredObligations": list(self.uncovered_obligations),
            "pendingActionClaims": list(self.pending_action_claims),
            "pendingActions": list(self.pending_actions),
            "citationIds": list(self.citation_ids),
            "evidenceSnapshots": [dict(snapshot) for snapshot in self.evidence_snapshots],
            "contextSnapshots": [dict(snapshot) for snapshot in self.context_snapshots],
            "claimCount": self.claim_count,
            "unsupportedClaims": list(self.unsupported_claims),
            "contradictions": list(self.contradictions),
            "error": self.error[:1_000],
        }


class KnowledgeRequestItemAssessment(BaseModel):
    """Answer-span proof for one runtime-extracted agent question item."""

    request_item_id: str = Field(description="Exact request item ID from the runtime checklist")
    resolution: Literal["answered", "unknown_or_unavailable"]
    answer_excerpt: str = Field(
        max_length=1_000,
        description=(
            "Exact non-empty contiguous excerpt from the customer answer that resolves "
            "this item or states its item-specific unknown/unavailable result"
        ),
    )


class KnowledgeAgentOutput(BaseModel):
    """Structured result produced after searching the isolated workspace."""

    answer: str = Field(
        description=(
            "Approval-ready customer support answer that explicitly resolves every "
            "independent item in the agent request, including an item-specific "
            "unknown, unverified, pending, unavailable, or unquantified result when "
            "the evidence does not establish it"
        )
    )
    confidence: Literal["low", "medium", "high"]
    citation_ids: list[str] = Field(default_factory=list)
    citation_paths: list[str] = Field(
        default_factory=list,
        description="Exact article chunk paths read with standalone cat calls and used as evidence",
    )
    missing_information: list[str] = Field(default_factory=list)
    response_attachments: list[str] = Field(default_factory=list)
    covered_concern_ids: list[str] = Field(default_factory=list)
    covered_obligation_ids: list[str] = Field(default_factory=list)
    request_item_assessments: list[KnowledgeRequestItemAssessment] = Field(
        max_length=_KNOWLEDGE_REQUEST_ITEM_LIMIT * 2,
        description=(
            "Exactly one answer-span assessment for every runtime request item ID, "
            "with no missing, duplicate, or invented IDs"
        )
    )
    requires_human: bool = False
    requires_human_reason: str = ""


class AutomationAnswerOutput(BaseModel):
    """Structured result from the bounded automatic response generator."""

    answer: str = Field(description="Customer-facing support answer")
    confidence: Literal["low", "medium", "high"]
    citation_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    response_attachments: list[str] = Field(default_factory=list)
    covered_concern_ids: list[str] = Field(default_factory=list)
    covered_obligation_ids: list[str] = Field(default_factory=list)
    requires_human: bool = False
    requires_human_reason: str = ""


class AutomationGroundingUnitAssessment(BaseModel):
    """Evidence assessment for one immutable answer unit."""

    unit_id: str
    unit_sha256: str
    supported: bool
    evidence_ids: list[str] = Field(default_factory=list)


class AutomationGroundingObligationAssessment(BaseModel):
    """Coverage assessment for one explicit customer answer obligation."""

    obligation_id: str
    resolution: Literal[
        "answered",
        "fulfilled_action",
        "pending_or_unavailable",
        "not_covered",
    ]
    answer_unit_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    @computed_field(return_type=bool)
    @property
    def covered(self) -> bool:
        """Compatibility projection; code still validates the resolution evidence."""
        return self.resolution in _ADDRESSED_OBLIGATION_RESOLUTIONS


class AutomationGroundingOutput(BaseModel):
    """Independent exhaustive answer-unit support decision."""

    verdict: Literal["grounded", "not_grounded"]
    answer_sha256: str
    checked_citation_ids: list[str] = Field(default_factory=list)
    unit_assessments: list[AutomationGroundingUnitAssessment] = Field(default_factory=list)
    obligation_assessments: list[AutomationGroundingObligationAssessment] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


def _grounding_retryable_protocol_errors(
    structured: Any,
    *,
    expected_unit_ids: frozenset[str],
    expected_obligation_ids: frozenset[str],
    allowed_evidence_ids: frozenset[str],
) -> tuple[str, ...]:
    """Return evaluator-shape errors that justify one identical retry.

    This intentionally excludes semantic grounding failures. Unknown evidence
    IDs are malformed protocol references and receive the same bounded retry as
    unknown unit or obligation IDs. The normal validation path remains
    authoritative after the final attempt.
    """

    if not isinstance(structured, AutomationGroundingOutput):
        return ("Evaluator returned no structured response",)

    errors: list[str] = []
    if not structured.unit_assessments:
        errors.append("Evaluator returned no answer-unit assessments")
    if len(structured.unit_assessments) > _GROUNDING_MAX_UNITS:
        errors.append("Evaluator returned too many answer-unit assessments")
    unit_ids = [_string_from(assessment.unit_id) for assessment in structured.unit_assessments[:_GROUNDING_MAX_UNITS]]
    if any(not unit_id for unit_id in unit_ids) or len(unit_ids) != len(set(unit_ids)):
        errors.append("Evaluator returned a missing or duplicate answer-unit ID")
    if set(unit_ids) != expected_unit_ids:
        errors.append("Evaluator did not assess every answer unit exactly once")
    for assessment in structured.unit_assessments[:_GROUNDING_MAX_UNITS]:
        unit_id = _string_from(assessment.unit_id)
        evidence_ids = {
            evidence_id
            for value in assessment.evidence_ids
            if (evidence_id := _string_from(value))
        }
        if assessment.supported and not evidence_ids:
            errors.append(f"Supported answer unit has no evidence IDs: {unit_id or '<missing>'}")
        unknown_evidence_ids = sorted(evidence_ids - allowed_evidence_ids)
        if unknown_evidence_ids:
            errors.append(
                "Answer unit uses unknown evidence IDs: "
                + ", ".join(unknown_evidence_ids[:5])
            )

    if len(structured.obligation_assessments) > 100:
        errors.append("Evaluator returned too many obligation assessments")
    obligation_ids = [_string_from(assessment.obligation_id) for assessment in structured.obligation_assessments[:100]]
    if any(not obligation_id for obligation_id in obligation_ids) or len(obligation_ids) != len(set(obligation_ids)):
        errors.append("Evaluator returned a missing or duplicate answer-obligation ID")
    if set(obligation_ids) != expected_obligation_ids:
        errors.append("Evaluator did not assess every answer obligation exactly once")
    for assessment in structured.obligation_assessments[:100]:
        answer_unit_ids = {unit_id for value in assessment.answer_unit_ids if (unit_id := _string_from(value))}
        if not answer_unit_ids.issubset(expected_unit_ids):
            errors.append("Answer obligation uses unknown answer-unit IDs")
        if assessment.resolution in _ADDRESSED_OBLIGATION_RESOLUTIONS and not answer_unit_ids:
            errors.append("Addressed obligation has no answer-unit IDs")
        evidence_ids = {
            evidence_id
            for value in assessment.evidence_ids
            if (evidence_id := _string_from(value))
        }
        unknown_evidence_ids = sorted(evidence_ids - allowed_evidence_ids)
        if unknown_evidence_ids:
            errors.append(
                "Answer obligation uses unknown evidence IDs: "
                + ", ".join(unknown_evidence_ids[:5])
            )
    all_units_supported = bool(structured.unit_assessments) and all(
        assessment.supported
        and bool(
            {
                evidence_id
                for value in assessment.evidence_ids
                if (evidence_id := _string_from(value))
            }
        )
        for assessment in structured.unit_assessments[:_GROUNDING_MAX_UNITS]
    )
    all_obligations_addressed = all(
        assessment.resolution in _ADDRESSED_OBLIGATION_RESOLUTIONS
        and bool(
            {
                unit_id
                for value in assessment.answer_unit_ids
                if (unit_id := _string_from(value))
            }
        )
        for assessment in structured.obligation_assessments[:100]
    )
    if (
        not errors
        and structured.verdict == "not_grounded"
        and all_units_supported
        and all_obligations_addressed
        and not any(_string_from(value) for value in structured.contradictions)
    ):
        errors.append("Evaluator verdict contradicts exhaustive grounded assessments")
    return tuple(dict.fromkeys(errors))


def _grounding_unknown_evidence_ids(
    structured: Any,
    *,
    allowed_evidence_ids: frozenset[str],
) -> tuple[str, ...]:
    """List malformed evidence references for one bounded corrective retry."""
    if not isinstance(structured, AutomationGroundingOutput):
        return ()
    supplied_ids = {
        evidence_id
        for assessment in structured.unit_assessments[:_GROUNDING_MAX_UNITS]
        for value in assessment.evidence_ids
        if (evidence_id := _string_from(value))
    }
    supplied_ids.update(
        evidence_id
        for assessment in structured.obligation_assessments[:100]
        for value in assessment.evidence_ids
        if (evidence_id := _string_from(value))
    )
    return tuple(sorted(supplied_ids - allowed_evidence_ids)[:100])


def _grounding_needs_obligation_reassessment(
    structured: Any,
    *,
    expected_unit_ids: frozenset[str],
    expected_obligation_ids: frozenset[str],
    allowed_evidence_ids: frozenset[str],
    expected_units: dict[str, dict[str, Any]] | None = None,
    expected_obligations: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Detect a narrow semantic result worth one independent second pass.

    The retry never converts a failure by itself. It is allowed only when the
    first result is protocol-complete, every immutable answer unit is supported
    by known evidence, and an uncovered obligation was nevertheless linked to
    one or more real answer units. The final full validation remains authoritative.
    """

    if not expected_obligation_ids or not isinstance(structured, AutomationGroundingOutput):
        return False
    if _grounding_retryable_protocol_errors(
        structured,
        expected_unit_ids=expected_unit_ids,
        expected_obligation_ids=expected_obligation_ids,
        allowed_evidence_ids=allowed_evidence_ids,
    ):
        return False
    if any(_string_from(value) for value in structured.contradictions):
        return False
    for assessment in structured.unit_assessments:
        evidence_ids = {evidence_id for value in assessment.evidence_ids if (evidence_id := _string_from(value))}
        if not assessment.supported or not evidence_ids or not evidence_ids.issubset(allowed_evidence_ids):
            return False
    obligation_questions_by_unit: dict[str, list[str]] = {}
    for assessment in structured.obligation_assessments:
        evidence_ids = {evidence_id for value in assessment.evidence_ids if (evidence_id := _string_from(value))}
        if not evidence_ids.issubset(allowed_evidence_ids):
            return False
        obligation_id = _string_from(assessment.obligation_id)
        question = _string_from((expected_obligations or {}).get(obligation_id, {}).get("question"))
        if not question:
            continue
        for value in assessment.answer_unit_ids:
            unit_id = _string_from(value)
            if unit_id in expected_unit_ids:
                obligation_questions_by_unit.setdefault(unit_id, []).append(question)
    all_obligation_questions = tuple(
        question
        for obligation in (expected_obligations or {}).values()
        if (question := _string_from(obligation.get("question")))
    )
    for assessment in structured.obligation_assessments:
        if assessment.resolution != "not_covered":
            continue
        linked_unit_ids = tuple(
            unit_id for value in assessment.answer_unit_ids if (unit_id := _string_from(value)) in expected_unit_ids
        )
        if not linked_unit_ids:
            continue
        if expected_units and all(
            _grounding_unit_only_acknowledges_or_defers(
                _string_from(expected_units.get(unit_id, {}).get("text")),
                linked_obligation_questions=tuple(obligation_questions_by_unit.get(unit_id, ())),
                all_obligation_questions=all_obligation_questions,
            )
            for unit_id in linked_unit_ids
        ):
            continue
        return True
    return False


_GROUNDING_ACKNOWLEDGEMENT_PATTERNS = (
    re.compile(
        r"^\s*you\s+(?:are|were)\s+(?:seeking|asking|requesting)\b"
        r"(?P<body>[^.!?\n]*)[.!?]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:thank\s+you|thanks)\b"
        r"(?=[^.!?\n]{0,180}\b(?:messages?|enquir(?:y|ies)|"
        r"inquir(?:y|ies)|requests?|contacting)\b)"
        r"(?P<body>[^.!?\n]{0,240})[.!?]?\s*$",
        re.IGNORECASE,
    ),
)
_GROUNDING_UNMISTAKABLE_DEFERRAL_PATTERN = re.compile(
    r"^\s*(?:we|our\s+team)\s+(?:will|would)\s+look\s+into\s+"
    r"(?:it|this|the\s+(?:matter|issue|request|enquiry|inquiry))"
    r"(?:\s+and\s+get\s+back\s+to\s+you)?[.!]?\s*$",
    re.IGNORECASE,
)
_GROUNDING_SUBSTANTIVE_DETAIL_PATTERN = re.compile(
    r"[:;]|(?:CHF|EUR|USD|GBP|\$|€|£)\s*\d|\b\d+(?:[.,]\d+)?\b|"
    r"\b(?:for\s+example|including|such\s+as|namely|first|second|third|next|then|"
    r"minimum|maximum|must|may|might|needs?|requires?|consists?|amounts?\s+to|"
    r"within|electronically|online|falls?|due|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday|articles?\s+of\s+association|public\s+deed|is|are)\b",
    re.IGNORECASE,
)
_GROUNDING_RESTATEMENT_TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_GROUNDING_RESTATEMENT_META_TOKENS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "asking",
        "back",
        "contacting",
        "enquiry",
        "for",
        "from",
        "get",
        "give",
        "has",
        "have",
        "how",
        "information",
        "into",
        "inquiry",
        "it",
        "look",
        "message",
        "of",
        "on",
        "outline",
        "please",
        "regarding",
        "request",
        "requested",
        "seeking",
        "tell",
        "that",
        "the",
        "to",
        "us",
        "what",
        "when",
        "which",
        "will",
        "you",
        "your",
    }
)


def _grounding_restatement_tokens(text: str) -> frozenset[str]:
    aliases = {
        "consultations": "consultation",
        "documents": "document",
        "enquiries": "enquiry",
        "inquiries": "inquiry",
        "messages": "message",
        "requests": "request",
        "requirements": "requirement",
        "steps": "step",
    }
    return frozenset(
        normalized
        for token in _GROUNDING_RESTATEMENT_TOKEN_PATTERN.findall(text.casefold())
        if (normalized := aliases.get(token, token)) not in _GROUNDING_RESTATEMENT_META_TOKENS
    )


def _grounding_has_appositive_punctuation(text: str) -> bool:
    """Treat answer-like punctuation as substantive, except a genuine long list."""
    if re.search(r"[()–—=]|\s[-/]\s", text):
        return True
    if "," not in text:
        return False
    segments = [segment.strip() for segment in text.split(",")]
    is_long_conjoined_list = (
        len(segments) >= 3 and all(segments) and re.match(r"^(?:and|or)\b", segments[-1], re.IGNORECASE) is not None
    )
    return not is_long_conjoined_list


def _grounding_unit_only_acknowledges_or_defers(
    text: str,
    *,
    linked_obligation_questions: tuple[str, ...] = (),
    all_obligation_questions: tuple[str, ...] = (),
) -> bool:
    """Identify request restatements that cannot justify a semantic retry."""
    if not text:
        return False
    if _GROUNDING_UNMISTAKABLE_DEFERRAL_PATTERN.fullmatch(text):
        return True
    for pattern in _GROUNDING_ACKNOWLEDGEMENT_PATTERNS:
        match = pattern.fullmatch(text)
        if match is None:
            continue
        body = match.groupdict().get("body") or ""
        if _grounding_has_appositive_punctuation(body):
            return False
        if _GROUNDING_SUBSTANTIVE_DETAIL_PATTERN.search(body) is not None:
            return False
        body_tokens = _grounding_restatement_tokens(body)
        if not body_tokens:
            return True
        linked_tokens = _grounding_restatement_tokens(" ".join(linked_obligation_questions))
        if not linked_tokens or not body_tokens.intersection(linked_tokens):
            return False
        if body_tokens.issubset(linked_tokens):
            return True
        # A single restatement unit can repeat several customer questions even
        # when the evaluator links it to only a subset of them. Permit those
        # extra words only when they also come verbatim from another immutable
        # obligation; newly asserted details still force an independent pass.
        all_obligation_tokens = _grounding_restatement_tokens(" ".join(all_obligation_questions))
        return body_tokens.issubset(all_obligation_tokens)
    return False


_GUARANTEE_REQUEST_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
    r"guarantee\s+(?:that\s+)?(?P<subject>.+?)\s*[.?!]*$",
    re.IGNORECASE,
)


def _knowledge_backed_negative_guarantee_answers_obligation(
    *,
    question: str,
    answer_unit_ids: tuple[str, ...],
    expected_units: dict[str, dict[str, Any]],
    supported_unit_evidence_ids: dict[str, frozenset[str]],
    citation_ids: frozenset[str],
) -> bool:
    """Recognize an explicit, knowledge-backed refusal of a requested guarantee."""
    request_match = _GUARANTEE_REQUEST_PATTERN.search(question)
    if request_match is None:
        return False
    subject = request_match.group("subject").strip(" \t\r\n.,;:!?\"'“”‘’")
    subject = re.sub(
        r"\s+\b(?:by|before|on)\b\s+.+$",
        "",
        subject,
        flags=re.IGNORECASE,
    ).strip()
    subject = re.sub(r"^(?:a|an|the)\s+", "", subject, flags=re.IGNORECASE)
    if not subject:
        return False
    subject_pattern = re.escape(subject).replace(r"\ ", r"\s+")
    subject_object_boundary = r"(?=\s*(?:[.,;:!?]|$|\bby\b))"
    negative_patterns = (
        rf"^\s*(?:(?:unfortunately|currently)\s*,?\s+)?"
        rf"(?:we|i|zenfulfillment)\s+"
        rf"(?:cannot|can['’]t|can\s+not|am\s+unable\s+to|are\s+unable\s+to|"
        rf"am\s+not\s+able\s+to|are\s+not\s+able\s+to)\s+"
        rf"guarantee\s+(?:a|an|the)?\s*{subject_pattern}\b"
        rf"{subject_object_boundary}",
        rf"^\s*(?:a|an|the)?\s*{subject_pattern}(?:\s+timing)?\s+"
        rf"(?:(?:cannot|can['’]t|can\s+not)\s+be\s+guaranteed|"
        rf"(?:is|are)\s+not\s+guaranteed)\b",
        rf"^\s*(?:regarding|about)\s+(?:a|an|the)?\s*{subject_pattern}\s*,\s*"
        rf"(?:its|the)\s+(?:timing|outcome)\b"
        rf"(?:(?!\b(?:guaranteed|while|but|however|though|although|yet)\b)"
        rf"[^,;.!?\n]){{0,100}}?\b"
        rf"(?:cannot|can['’]t|can\s+not)\s+be\s+guaranteed\b",
        rf"^\s*(?:there\s+is|there['’]s)\s+no\s+guarantee\s+"
        rf"(?:for|of|that)?\s*(?:a|an|the)?\s*{subject_pattern}\b"
        rf"{subject_object_boundary}",
    )
    negated_attribution_pattern = re.compile(
        r"(?:\b(?:does|do|did|is|was)\s+(?:not|never)\s+"
        r"(?:say|state|mean|show|claim)\b|"
        r"\b(?:false\s+that|not\s+true\s+that)\b|"
        r"\bno\s+one\s+(?:said|says|states|claimed|claims)\b)",
        re.IGNORECASE,
    )
    guarantee_reversal_pattern = re.compile(
        r"\b(?:but|however|though|although|yet|while)\b"
        r"[^.!?\n]{0,120}\b(?:false|guaranteed|untrue)\b",
        re.IGNORECASE,
    )
    negated_conclusion_pattern = re.compile(
        r"[^.!?\n]{0,80}\b(?:is|was)\s+(?:false|untrue)\b",
        re.IGNORECASE,
    )
    for unit_id in answer_unit_ids:
        evidence_ids = supported_unit_evidence_ids.get(unit_id, frozenset())
        if not evidence_ids.intersection(citation_ids):
            continue
        unit_text = _string_from(expected_units.get(unit_id, {}).get("text"))
        for pattern in negative_patterns:
            for negative_match in re.finditer(pattern, unit_text, re.IGNORECASE):
                if negated_attribution_pattern.search(
                    unit_text[max(0, negative_match.start() - 160) : negative_match.start()]
                ):
                    continue
                if guarantee_reversal_pattern.search(unit_text[negative_match.end() :]):
                    continue
                if negated_conclusion_pattern.fullmatch(unit_text[negative_match.end() :].strip()):
                    continue
                return True
    return False


_SECRET_DELIVERY_OBJECT_PATTERN = re.compile(
    r"\b(?:replacement\s+)?(?:(?:api|access|authentication)\s+)?(?:"
    r"tokens?|secrets?|credentials?|passwords?|api[-\s]?keys?|recovery\s+codes?"
    r")\b",
    re.IGNORECASE,
)
_SECRET_DELIVERY_ACTION_PATTERN = (
    r"(?:deliver(?:y|ed|ing)?|provid(?:e|ed|ing)|send|sent|share|shared|"
    r"transmit(?:ted|ting)?|use|using)"
)
_SECURE_DELIVERY_ROUTE_PATTERN = (
    r"(?:(?:(?:approved|trusted)\s+)?secure\s+|(?:approved|trusted)\s+)"
    r"(?:(?:recovery|credential|token)\s+)?(?:channel|portal|vault|method|route)"
)
_SECRET_SECURE_DELIVERY_PATTERNS = (
    re.compile(
        rf"{_SECRET_DELIVERY_OBJECT_PATTERN.pattern}[^.!?\n]{{0,140}}"
        rf"\b{_SECRET_DELIVERY_ACTION_PATTERN}\b[^.!?\n]{{0,100}}"
        rf"\b{_SECURE_DELIVERY_ROUTE_PATTERN}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_SECRET_DELIVERY_ACTION_PATTERN}\b[^.!?\n]{{0,100}}"
        rf"\b{_SECURE_DELIVERY_ROUTE_PATTERN}\b[^.!?\n]{{0,120}}"
        rf"{_SECRET_DELIVERY_OBJECT_PATTERN.pattern}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_SECURE_DELIVERY_ROUTE_PATTERN}\b[^.!?\n]{{0,100}}"
        rf"\b(?:for|to)\b[^.!?\n]{{0,100}}{_SECRET_DELIVERY_OBJECT_PATTERN.pattern}",
        re.IGNORECASE,
    ),
)
_SECRET_EMAIL_PROHIBITION_PATTERNS = (
    re.compile(
        rf"\b(?:do\s+not|don['’]t|never|must\s+not|should\s+not)\s+"
        rf"(?:send|provide|deliver|share|transmit|email)\s+"
        rf"(?:(?:a|an|the|any|new|your)\s+){{0,3}}{_SECRET_DELIVERY_OBJECT_PATTERN.pattern}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{_SECRET_DELIVERY_OBJECT_PATTERN.pattern}[^.!?\n]{{0,120}}"
        r"\b(?:do\s+not|don['’]t|never|must\s+not|should\s+not|will\s+not|not)\b"
        r"[^.!?\n]{0,50}\b(?:e-?mail(?:ed|ing)?|electronic\s+mail)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:do\s+not|don['’]t|never|must\s+not|should\s+not)\s+"
        r"(?:send|provide|deliver|share|transmit)\s+(?:it|them|one)\s+"
        r"(?:via|by|through|over|using)\s+(?:e-?mail|electronic\s+mail)\b",
        re.IGNORECASE,
    ),
)
_SECRET_EMAIL_ALLOWANCE_PATTERNS = (
    re.compile(
        r"\b(?:can|may|should|must|will)\s+(?:be\s+)?emailed\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:can|may|should|must|will)\s+(?:send|email|share|deliver|provide)\b"
        rf"[^.!?\n]{{0,100}}{_SECRET_DELIVERY_OBJECT_PATTERN.pattern}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{_SECRET_DELIVERY_OBJECT_PATTERN.pattern}[^.!?\n]{{0,100}}"
        r"\b(?:can|may|should|must|will)\s+(?:be\s+)?"
        r"(?:emailed|sent|delivered|provided|shared)\b"
        r"(?:(?!\b(?:not|never)\b)[^.!?\n]){0,60}"
        r"\b(?:via|by|through|over|using)\s+(?:secure\s+)?e-?mail\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bsecure\s+e-?mail\b", re.IGNORECASE),
)
_SECRET_EMAIL_PROHIBITION_REVERSAL_PATTERN = re.compile(
    r"(?:"
    r"\b(?:false|untrue|incorrect)\s+that\b[^.!?\n]{0,120}"
    r"\b(?:not|never)\b[^.!?\n]{0,60}\be-?mail(?:ed|ing)?\b|"
    r"\b(?:not|never)\b[^.!?\n]{0,80}\be-?mail(?:ed|ing)?\b[^.!?\n]{0,60}"
    r"\b(?:is|was)\s+(?:false|untrue|incorrect)\b|"
    r"\b(?:not|never)\b[^.!?\n]{0,80}\be-?mail(?:ed|ing)?\b[^.!?\n]{0,40}"
    r"\b(?:unless|except)\b"
    r")",
    re.IGNORECASE,
)
_SECRET_REPETITION_PROHIBITION_PATTERN = re.compile(
    rf"\b(?:do\s+not|don['’]t|never|must\s+not|should\s+not)\s+"
    rf"(?:repeat|copy|display|reveal)\s+"
    rf"(?:(?:a|an|the|any|new|your)\s+){{0,3}}{_SECRET_DELIVERY_OBJECT_PATTERN.pattern}",
    re.IGNORECASE,
)
_SECURE_SECRET_DELIVERY_NOTICE = (
    "For security, never repeat the secret or credential. "
    "Never email the secret or credential, or any replacement. "
    "Use only the approved secure channel for any replacement credential."
)


def _knowledge_backed_secure_secret_delivery_answers_obligation(
    *,
    question: str,
    answer_unit_ids: tuple[str, ...],
    expected_units: dict[str, dict[str, Any]],
    supported_unit_evidence_ids: dict[str, frozenset[str]],
    citation_ids: frozenset[str],
) -> bool:
    """Recognize explicit knowledge-backed secure secret-delivery guidance.

    This is deliberately narrower than general semantic coverage. It handles a
    repeated evaluator false negative only when both the obligation and cited
    reply require a secure delivery route and expressly prohibit email.
    """

    if (
        _SECRET_DELIVERY_OBJECT_PATTERN.search(question) is None
        or re.search(r"\b(?:deliver(?:y)?|provide|send|share|transmit)\b", question, re.IGNORECASE) is None
        or re.search(r"\b(?:secure|approved|trusted)\b", question, re.IGNORECASE) is None
        or not any(pattern.search(question) for pattern in _SECRET_EMAIL_PROHIBITION_PATTERNS)
    ):
        return False

    cited_text_units = [
        _string_from(expected_units.get(unit_id, {}).get("text"))
        for unit_id in answer_unit_ids
        if supported_unit_evidence_ids.get(unit_id, frozenset()).intersection(citation_ids)
    ]
    answer_text = " ".join(text for text in cited_text_units if text)
    if not answer_text:
        return False
    if _SECRET_EMAIL_PROHIBITION_REVERSAL_PATTERN.search(answer_text):
        return False
    if any(pattern.search(answer_text) for pattern in _SECRET_EMAIL_ALLOWANCE_PATTERNS):
        return False
    return bool(
        _SECRET_DELIVERY_OBJECT_PATTERN.search(answer_text)
        and any(pattern.search(answer_text) for pattern in _SECRET_SECURE_DELIVERY_PATTERNS)
        and any(pattern.search(answer_text) for pattern in _SECRET_EMAIL_PROHIBITION_PATTERNS)
    )


def _string_from(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _record_from(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _positive_int_from(value: Any) -> int:
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _attachment_text_context(message: dict[str, Any], *, limit: int = 4_000) -> str:
    raw_attachments = message.get("attachments")
    if not isinstance(raw_attachments, list):
        content = _record_from(message.get("content"))
        raw_attachments = content.get("emailAttachments") or content.get("email_attachments")
    if not isinstance(raw_attachments, list):
        return ""

    sections: list[str] = []
    remaining = limit
    for index, raw_attachment in enumerate(raw_attachments[:10], start=1):
        attachment = _record_from(raw_attachment)
        extracted_text = _string_from(attachment.get("extractedText") or attachment.get("extracted_text"))
        if not extracted_text or remaining <= 0:
            continue
        filename = _string_from(attachment.get("filename") or attachment.get("name")) or f"attachment-{index}"
        header = f"### {filename[:240]}\n"
        available = max(0, remaining - len(header))
        if available <= 0:
            break
        excerpt = extracted_text[: min(2_000, available)]
        section = f"{header}{excerpt}"
        sections.append(section)
        remaining -= len(section)
    if not sections:
        return ""
    return "Attachments (extracted text, untrusted):\n" + "\n\n".join(sections)


def _message_context(messages: list[dict[str, Any]], limit: int = 8) -> list[dict[str, str]]:
    context: list[dict[str, str]] = []
    for message in messages[-limit:]:
        body = _string_from(message.get("body"))
        if not body:
            content = message.get("content")
            if isinstance(content, str):
                body = content.strip()
            elif isinstance(content, dict):
                body = _string_from(
                    content.get("emailBody") or content.get("email_body") or content.get("responseText")
                )
        attachment_context = _attachment_text_context(message)
        if not body and not attachment_context:
            continue
        context_body = body[:2_000]
        if attachment_context:
            context_body = f"{context_body}\n\n{attachment_context}".strip()
        context.append(
            {
                "direction": _string_from(message.get("direction") or message.get("user") or message.get("role")),
                "sender": _string_from(message.get("sender") or message.get("from") or message.get("authorEmail")),
                "body": context_body,
                "occurredAt": _string_from(message.get("occurredAt") or message.get("created")),
            }
        )
    return context


def _automatic_message_context(messages: list[dict[str, Any]], limit: int = 8) -> list[dict[str, str]]:
    customer_messages = [
        message
        for message in messages
        if isinstance(message, dict)
        and _string_from(message.get("direction") or message.get("user") or message.get("role")).lower()
        in {"customer", "email", "visitor", "user"}
    ]
    return _message_context(customer_messages, limit=limit)


_LANGUAGE_WORD_WEIGHTS: dict[str, dict[str, int]] = {
    "en": {
        "hello": 4,
        "please": 3,
        "thanks": 3,
        "thank": 3,
        "where": 2,
        "when": 2,
        "what": 2,
        "tell": 2,
        "help": 2,
        "current": 2,
        "estimated": 2,
        "order": 2,
        "delivery": 2,
        "shipment": 2,
        "refund": 2,
        "cancel": 2,
        "request": 2,
        "pending": 2,
        "review": 2,
        "received": 2,
        "we": 1,
        "have": 1,
        "the": 1,
        "and": 1,
        "your": 1,
        "my": 1,
        "is": 1,
        "are": 1,
        "with": 1,
    },
    "fr": {
        "bonjour": 4,
        "merci": 4,
        "colis": 3,
        "commande": 3,
        "livraison": 3,
        "remboursement": 3,
        "annuler": 3,
        "retard": 3,
        "suivi": 3,
        "pouvez": 2,
        "pourriez": 2,
        "souhaite": 2,
        "aide": 2,
        "réponse": 2,
        "question": 2,
        "quel": 2,
        "quelle": 2,
        "où": 2,
        "quand": 2,
        "vous": 1,
        "votre": 1,
        "mon": 1,
        "ma": 1,
        "mes": 1,
        "est": 1,
        "pour": 1,
        "avec": 1,
        "nous": 2,
        "demande": 3,
        "examinons": 3,
        "reçu": 2,
        "reçue": 2,
        "cours": 2,
        "sera": 1,
        "veuillez": 4,
        "rembourser": 4,
        "escaladez": 4,
        "remboursez": 4,
    },
    "de": {
        "hallo": 4,
        "danke": 4,
        "bitte": 3,
        "bestellung": 3,
        "lieferung": 3,
        "paket": 3,
        "verspätet": 3,
        "stornieren": 3,
        "kündigen": 3,
        "rückerstattung": 3,
        "sendungsverfolgung": 3,
        "wissen": 2,
        "sagen": 2,
        "helfen": 2,
        "wann": 2,
        "warum": 2,
        "wo": 2,
        "wie": 2,
        "mein": 1,
        "meine": 1,
        "meiner": 1,
        "ihre": 1,
        "ist": 1,
        "sind": 1,
        "und": 1,
        "nicht": 1,
        "mir": 1,
        "wir": 2,
        "haben": 2,
        "anfrage": 3,
        "erhalten": 2,
        "prüfen": 3,
        "erstatten": 4,
        "rückerstatten": 4,
        "zurückerstatten": 4,
    },
    "es": {
        "hola": 4,
        "gracias": 4,
        "necesito": 4,
        "pedido": 3,
        "envío": 3,
        "entrega": 3,
        "reembolso": 3,
        "cancelar": 3,
        "seguimiento": 3,
        "ayuda": 3,
        "quisiera": 2,
        "saber": 2,
        "dónde": 2,
        "cuando": 2,
        "cuándo": 2,
        "qué": 2,
        "respuesta": 2,
        "pregunta": 2,
        "favor": 1,
        "con": 1,
        "mi": 1,
        "está": 1,
        "por": 1,
        "su": 1,
        "solicitud": 3,
        "estamos": 2,
        "revisando": 3,
        "pendiente": 2,
        "hemos": 2,
        "recibido": 2,
        "será": 1,
        "escale": 4,
        "reembolse": 4,
    },
    "it": {
        "ciao": 4,
        "grazie": 4,
        "vorrei": 4,
        "ordine": 3,
        "consegna": 3,
        "spedizione": 3,
        "rimborso": 3,
        "annullare": 3,
        "pacco": 3,
        "ritardo": 3,
        "sapere": 2,
        "aiuto": 2,
        "bisogno": 2,
        "dove": 2,
        "quando": 2,
        "risposta": 2,
        "domanda": 2,
        "stato": 2,
        "favore": 1,
        "mio": 1,
        "mia": 1,
        "del": 1,
        "della": 1,
        "con": 1,
        "per": 1,
        "richiesta": 3,
        "sospeso": 2,
        "sospesa": 2,
        "stiamo": 2,
        "esaminando": 3,
        "abbiamo": 2,
        "ricevuto": 2,
        "ricevuta": 2,
        "sarà": 1,
        "rimborsi": 4,
    },
}
_LANGUAGE_PHRASE_WEIGHTS: dict[str, dict[str, int]] = {
    "en": {"thank you": 4},
    "fr": {"s il vous plaît": 5},
    "de": {"vielen dank": 5},
    "es": {"por favor": 4},
    "it": {"per favore": 4},
}
_LANGUAGE_CHARACTER_WEIGHTS: dict[str, dict[str, int]] = {
    "fr": {"ç": 3, "œ": 3, "ê": 2, "î": 2, "û": 2},
    "de": {"ß": 4, "ä": 3, "ö": 3, "ü": 3},
    "es": {"¿": 4, "¡": 4, "ñ": 4, "á": 1, "í": 1, "ó": 1, "ú": 1},
    "it": {"ì": 3, "ò": 3},
}
_LANGUAGE_NAMES = {
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
}
_PENDING_ACTION_REPAIR_NOTICES = {
    "de": (
        "Jede angefragte Aktion, die eine menschliche Prüfung erfordert, ist "
        "ausstehend und weder als begonnen noch als abgeschlossen bestätigt."
    ),
    "en": ("Any requested action that requires human review is pending and is not confirmed as started or completed."),
    "es": (
        "Toda acción solicitada que requiera revisión humana está pendiente y no "
        "se confirma como iniciada ni completada."
    ),
    "fr": (
        "Toute action demandée nécessitant un contrôle humain est en attente et "
        "n’est confirmée ni comme commencée ni comme terminée."
    ),
    "it": (
        "Qualsiasi azione richiesta che necessiti di revisione umana è in sospeso "
        "e non è confermata né come avviata né come completata."
    ),
}
_ACTION_STATE_OBLIGATION_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "de": (
        re.compile(
            r"^\s*(?:bitte\s+)?(?:eskalieren|stornieren|kündigen|erstatten|rückerstatten|zurückerstatten|öffnen)"
            r"(?:\s+sie)?\s+(?P<subject>.+?)\s*[.?!]*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:bitte\s+)?(?:bestätigen|garantieren|versichern)"
            r"(?:\s+sie)?\s+(?P<subject>.+?)\s*[.?!]*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:können|könnten)\s+sie\s+(?:bitte\s+)?"
            r"(?P<subject>.+?)\s+(?:bestätigen|garantieren|versichern)\s*[.?!]*$",
            re.IGNORECASE,
        ),
    ),
    "en": (
        re.compile(
            r"^\s*(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
            r"(?:confirm|guarantee|ensure)\s+(?:that\s+)?"
            r"(?P<subject>.+?)\s*[.?!]*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:please\s+)?(?P<action>record|log|escalate|cancel|terminate|"
            r"rescind|refund|issue|notify|open|submit|investigate|update|change|replace|"
            r"reship|dispatch)\s+"
            r"(?P<subject>.+?)\s*[.?!]*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:please\s+)?identify\s+and\s+"
            r"(?P<action>escalate)\s+(?P<subject>.+?)\s*[.?!]*$",
            re.IGNORECASE,
        ),
    ),
    "es": (
        re.compile(
            r"^\s*(?:por\s+favor[,]?\s+)?"
            r"(?:escale|escalar|cancele|cancelar|anule|anular|"
            r"reembolse|reembolsar|abra|abrir)\s+"
            r"(?P<subject>.+?)\s*[.?!]*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:por\s+favor[,]?\s+)?"
            r"(?:confirme|confirmar|garantice|garantizar|asegure|asegurar)\s+"
            r"(?:que\s+)?(?P<subject>.+?)\s*[.?!]*$",
            re.IGNORECASE,
        ),
    ),
    "fr": (
        re.compile(
            r"^\s*(?:veuillez\s+)?"
            r"(?:escaladez|escalader|annulez|annuler|résiliez|résilier|"
            r"remboursez|rembourser|ouvrez|ouvrir)\s+"
            r"(?P<subject>.+?)\s*[.?!]*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:veuillez\s+)?"
            r"(?:confirmer|confirmez|garantir|garantissez|assurer|assurez)\s+"
            r"(?:que\s+)?(?P<subject>.+?)\s*[.?!]*$",
            re.IGNORECASE,
        ),
    ),
    "it": (
        re.compile(
            r"^\s*(?:per\s+favore[,]?\s+)?"
            r"(?:escalate|escalare|annulli|annullare|cancelli|cancellare|"
            r"rimborsi|rimborsare|apra|aprire)\s+"
            r"(?P<subject>.+?)\s*[.?!]*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:per\s+favore[,]?\s+)?"
            r"(?:confermare|confermi|garantire|garantisca|assicurare|assicuri)\s+"
            r"(?:che\s+)?(?P<subject>.+?)\s*[.?!]*$",
            re.IGNORECASE,
        ),
    ),
}
_ACTION_STATE_PENDING_NOTICES = {
    "de": (
        "Für {subject} liegt keine Bestätigung vor. Ein damit verbundener nächster "
        "Schritt für Ihre Anfrage wartet weiterhin auf menschliche Prüfung."
    ),
    "en": ("{subject} is not confirmed. A related next step for your request remains pending human review."),
    "es": (
        "No hay confirmación para {subject}. Un siguiente paso relacionado con su "
        "solicitud sigue pendiente de revisión humana."
    ),
    "fr": (
        "Aucune confirmation n’est disponible pour {subject}. Une prochaine étape "
        "connexe de votre demande reste en attente d’un contrôle humain."
    ),
    "it": (
        "Non c’è una conferma per {subject}. Un passaggio successivo collegato alla "
        "richiesta resta in attesa di revisione umana."
    ),
}
_SEPARATE_PENDING_ACTION_NOTICES = {
    "de": (
        "Die ausstehende Aktion ({label}) wartet auf menschliche Prüfung und ist "
        "weder als begonnen noch als abgeschlossen bestätigt."
    ),
    "en": (
        "The pending action ({label}) remains under human review and is not "
        "confirmed as started or completed."
    ),
    "es": (
        "La acción pendiente ({label}) sigue a la espera de revisión humana y no "
        "está confirmada como iniciada ni completada."
    ),
    "fr": (
        "L’action en attente ({label}) reste soumise à un contrôle humain et "
        "n’est confirmée ni comme commencée ni comme terminée."
    ),
    "it": (
        "L’azione in sospeso ({label}) resta soggetta a revisione umana e non è "
        "confermata né come avviata né come completata."
    ),
}
_SEPARATE_PENDING_ACTION_STATE_RE = re.compile(
    r"\b(?:pending|awaiting|unconfirmed|ausstehend|bestätigt|attente|confirmée|"
    r"pendiente|confirmada|sospeso|confermata|human\s+review|menschliche\s+prüfung|"
    r"contrôle\s+humain|revisión\s+humana|revisione\s+umana)\b",
    re.IGNORECASE,
)
_SEPARATE_PENDING_ACTION_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SEPARATE_PENDING_ACTION_TOKEN_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "action",
        "for",
        "human",
        "pending",
        "request",
        "requested",
        "the",
        "to",
    }
)
_ACTION_STATE_SUBJECT_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "be",
        "been",
        "can",
        "could",
        "das",
        "dass",
        "de",
        "der",
        "die",
        "el",
        "en",
        "et",
        "for",
        "für",
        "have",
        "has",
        "i",
        "il",
        "in",
        "is",
        "it",
        "la",
        "le",
        "les",
        "lo",
        "of",
        "or",
        "our",
        "que",
        "that",
        "the",
        "to",
        "und",
        "we",
        "whether",
        "will",
        "would",
        "you",
        "your",
    }
)
_ACTION_STATE_SUBJECT_TOKEN_ALIASES = {
    # Read-only facts are commonly phrased as either "the recorded due date"
    # or "our records show the due date". Keep those forms on one topic token
    # so an answered fact is not mistaken for an omitted pending action.
    "recorded": "record",
    "recording": "record",
    "records": "record",
}
_ACTION_STATE_SUBJECT_LEAD_REJECT_PATTERN = re.compile(
    r"^(?:i|me|you|he|him|she|her|it|we|us|they|them|this|that|these|those|"
    r"there|whether|if|who|what|which)\b",
    re.IGNORECASE,
)
_ACTION_STATE_SUBJECT_CLAUSE_REJECT_PATTERN = re.compile(
    r"(?:\b(?:is|are|was|were|has|have|had|will|would|can|could|should|must|"
    r"do|does|did)\b|"
    r"\b(?:changed|escalated|cancelled|canceled|refunded|shipped|dispatched|"
    r"started|completed|confirmed|approved|opened|created|updated|processed|"
    r"sent|received|arrived|failed|succeeded|happened|occurred|went)\b\s*$)",
    re.IGNORECASE,
)
_ENGLISH_ACTION_RESULT_CONFIRMATION_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
    r"(?:confirm|guarantee|ensure)\s+(?:that\s+)?"
    r"(?P<topic>.+?)\s+(?:is|was|has\s+been)\s+"
    r"(?P<state>fixed|resolved|restored|recovered|complete|completed|successful|working)"
    r"\s*[.?!]*$",
    re.IGNORECASE,
)


def _detected_supported_language(*values: str) -> str:
    clean = "\n".join(value for value in values if value).casefold()
    words = re.findall(r"[^\W\d_]+", clean, flags=re.UNICODE)
    word_counts: dict[str, int] = {}
    for word in words:
        word_counts[word] = word_counts.get(word, 0) + 1
    normalized_text = " ".join(words)
    scores: dict[str, int] = {}
    for language, word_weights in _LANGUAGE_WORD_WEIGHTS.items():
        score = sum(weight * min(word_counts.get(word, 0), 2) for word, weight in word_weights.items())
        score += sum(
            weight for phrase, weight in _LANGUAGE_PHRASE_WEIGHTS.get(language, {}).items() if phrase in normalized_text
        )
        score += sum(
            weight for character, weight in _LANGUAGE_CHARACTER_WEIGHTS.get(language, {}).items() if character in clean
        )
        scores[language] = score
    return max(scores, key=scores.get) if max(scores.values(), default=0) > 0 else "en"


def _latest_customer_language(messages: list[dict[str, Any]]) -> str:
    context = _automatic_message_context(messages, limit=1)
    return _detected_supported_language(context[-1]["body"] if context else "")


_KNOWLEDGE_QUESTION_START_PATTERN = re.compile(
    r"^(?:what|when|where|which|who|whom|whose|why|how|"
    r"is|are|was|were|has|have|had|can|could|may|might|"
    r"will|would|do|does|did|should|must)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_RESTARTED_QUESTION_PATTERN = re.compile(
    r"\s*,?\s+(?:and|or)\s+(?="
    r"(?:is|are|was|were|has|have|had|can|could|may|might|"
    r"will|would|do|does|did|should|must)\b)",
    re.IGNORECASE,
)
_KNOWLEDGE_IMPERATIVE_REQUEST_PATTERN = re.compile(
    r"(?:^|[,:;?]\s+(?:(?:and|or)\s+)?|[.]\s+)"
    r"(?P<request>(?:please\s+)?(?:explain|describe|provide|give|"
    r"tell|state|identify|list|summarize|confirm|compare|clarify)\b)",
    re.IGNORECASE,
)
_KNOWLEDGE_RESTARTED_IMPERATIVE_ITEM_PATTERN = re.compile(
    r"\s*,\s*(?:and\s+|or\s+)?(?="
    r"(?:whether|what|when|where|which|who|whom|whose|why|how)\b)|"
    r"\s+(?:and|or)\s+(?="
    r"(?:whether|what|when|where|which|who|whom|whose|why|how)\b)",
    re.IGNORECASE,
)
_KNOWLEDGE_RESTARTED_REQUEST_SENTENCE_PATTERN = re.compile(
    r"(?:[!?;]\s+(?:(?:and|or)\s+)?|[.]\s+)"
    r"(?=(?:please\s+)?"
    r"(?:explain|describe|provide|give|tell|state|"
    r"identify|list|summarize|confirm|compare|clarify|what|when|where|which|who|"
    r"whom|whose|why|how|is|are|was|were|has|have|had|can|could|may|might|will|"
    r"would|do|does|did|should|must)\b)",
    re.IGNORECASE,
)
_KNOWLEDGE_REQUEST_TOPIC_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "answer",
        "any",
        "are",
        "as",
        "at",
        "based",
        "be",
        "been",
        "being",
        "by",
        "can",
        "could",
        "clarify",
        "compare",
        "confirm",
        "describe",
        "did",
        "do",
        "does",
        "explain",
        "exact",
        "for",
        "from",
        "give",
        "had",
        "has",
        "have",
        "how",
        "i",
        "identify",
        "in",
        "is",
        "it",
        "known",
        "list",
        "may",
        "me",
        "might",
        "must",
        "of",
        "on",
        "only",
        "or",
        "our",
        "please",
        "provide",
        "request",
        "requested",
        "should",
        "state",
        "summarize",
        "tell",
        "that",
        "the",
        "their",
        "they",
        "this",
        "to",
        "using",
        "us",
        "verified",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "whether",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)
_KNOWLEDGE_REQUEST_TOKEN_ALIASES = {
    "affected": "affect",
    "affecting": "affect",
    "approval": "approv",
    "approved": "approv",
    "approves": "approv",
    "approving": "approv",
    "quantification": "quantifi",
    "quantified": "quantifi",
    "quantify": "quantifi",
    "services": "service",
}
_KNOWLEDGE_REQUEST_GENERIC_STATE_TOKENS = frozenset(
    {
        "approv",
        "known",
        "quantifi",
    }
)
_KNOWLEDGE_FRAMING_MANNER_ADVERB = r"[a-z]+(?:-[a-z]+)*ly"
_KNOWLEDGE_FRAMING_MANNER_PATTERN = re.compile(
    rf"{_KNOWLEDGE_FRAMING_MANNER_ADVERB}"
    rf"(?:(?:\s*,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+)"
    rf"{_KNOWLEDGE_FRAMING_MANNER_ADVERB})*",
    re.IGNORECASE,
)
_KNOWLEDGE_FRAMING_FORMAT_PATTERN = re.compile(
    r"(?:in|using|with|as)\s+(?:(?:a|an|the)\s+)?"
    r"(?:[a-z0-9][a-z0-9'-]*\s+){0,5}"
    r"(?:bullet\s+points?|examples?|formats?|json|language|markdown|"
    r"paragraphs?|prose|sentences?|styles?|tables?|terms|words)",
    re.IGNORECASE,
)
_KNOWLEDGE_FRAMING_NOUN_PHRASE_PATTERN = re.compile(
    r"(?:(?:a|an|the|this|that|these|those|some|any)\s+"
    r"(?:[a-z][a-z'-]*\s+){0,5})?"
    r"(?:answers?|details?|following|overviews?|responses?|summar(?:y|ies))",
    re.IGNORECASE,
)


def _knowledge_imperative_prefix_is_framing_only(value: str) -> bool:
    """Recognize a topic-free command that only frames introduced questions."""

    match = _KNOWLEDGE_IMPERATIVE_REQUEST_PATTERN.match(value.strip())
    if match is None or match.start("request") != 0:
        return False
    remainder = value.strip()[match.end("request") :].strip(" ,:\t\r\n")
    recipient = re.match(r"(?:me|us)\b[\s,]*", remainder, flags=re.IGNORECASE)
    if recipient is not None:
        remainder = remainder[recipient.end() :].strip()
    if not remainder:
        return True
    return bool(
        _KNOWLEDGE_FRAMING_MANNER_PATTERN.fullmatch(remainder)
        or _KNOWLEDGE_FRAMING_FORMAT_PATTERN.fullmatch(remainder)
        or _KNOWLEDGE_FRAMING_NOUN_PHRASE_PATTERN.fullmatch(remainder)
    )


def _knowledge_request_items(question: str) -> tuple[dict[str, str], ...]:
    """Extract bounded question or imperative clauses without splitting noun conjunctions."""
    normalized = re.sub(r"\s+", " ", str(question or "")).strip()
    if not normalized:
        return ()
    raw_questions = list(re.finditer(r"[^?]*\?", normalized))
    if len(raw_questions) > _KNOWLEDGE_REQUEST_ITEM_LIMIT:
        raise ValueError("Knowledge agent request contains too many direct questions")

    positioned_items: list[tuple[int, str]] = []
    direct_question_starts: list[int] = []

    def trim_leading_conjunction(value: str) -> tuple[str, int]:
        match = re.match(r"\s*(?:(?:and|or)\s+)?", value, flags=re.IGNORECASE)
        offset = match.end() if match is not None else 0
        return value[offset:].strip(), offset

    def collect_clauses(
        value: str,
        *,
        start: int,
        separator: re.Pattern[str],
    ) -> None:
        cursor = 0
        for clause in separator.split(value):
            item = clause.strip(" ,:.;?\t\r\n")
            if not item:
                continue
            relative_start = value.find(item, cursor)
            if relative_start < 0:
                relative_start = cursor
            positioned_items.append((start + relative_start, item))
            cursor = relative_start + len(item)

    for raw_match in raw_questions:
        raw_question = raw_match.group(0)
        candidate = raw_question.strip(" .;\t\r\n")
        candidate_start = raw_match.start() + len(raw_question) - len(
            raw_question.lstrip(" .;\t\r\n")
        )
        candidate, conjunction_offset = trim_leading_conjunction(candidate)
        candidate_start += conjunction_offset
        for separator in (":", ".", ";"):
            separator_index = candidate.rfind(separator)
            if separator_index < 0:
                continue
            raw_tail = candidate[separator_index + 1 :]
            tail, tail_offset = trim_leading_conjunction(raw_tail)
            if _KNOWLEDGE_QUESTION_START_PATTERN.match(tail):
                candidate_start += separator_index + 1 + tail_offset
                candidate = tail
        candidate = candidate.rstrip("?").strip()
        if not _KNOWLEDGE_QUESTION_START_PATTERN.match(candidate):
            continue
        direct_question_starts.append(candidate_start)
        collect_clauses(
            candidate,
            start=candidate_start,
            separator=_KNOWLEDGE_RESTARTED_QUESTION_PATTERN,
        )

    for imperative_match in _KNOWLEDGE_IMPERATIVE_REQUEST_PATTERN.finditer(normalized):
        imperative_start = imperative_match.start("request")
        boundary = _KNOWLEDGE_RESTARTED_REQUEST_SENTENCE_PATTERN.search(
            normalized[imperative_start:]
        )
        imperative_end = (
            imperative_start + boundary.start()
            if boundary is not None
            else len(normalized)
        )
        introduced_question_starts = [
            start
            for start in direct_question_starts
            if start > imperative_start
            and normalized[imperative_start:start].rstrip().endswith(":")
            and re.search(
                r"[.!?;]",
                normalized[imperative_start:start],
            )
            is None
        ]
        if introduced_question_starts:
            imperative_end = min(imperative_end, min(introduced_question_starts))
        imperative = normalized[imperative_start:imperative_end].strip()
        introduced_question_prefix = bool(introduced_question_starts)
        if imperative and (
            not introduced_question_prefix
            or not _knowledge_imperative_prefix_is_framing_only(imperative)
        ):
            collect_clauses(
                imperative,
                start=imperative_start,
                separator=_KNOWLEDGE_RESTARTED_IMPERATIVE_ITEM_PATTERN,
            )

    if not positioned_items:
        fallback = normalized.strip(" .?;\t\r\n")
        if not fallback:
            return ()
        positioned_items.append((0, fallback))

    items: list[str] = []
    seen: set[str] = set()
    for _position, raw_item in sorted(positioned_items, key=lambda item: item[0]):
        item = raw_item[0].upper() + raw_item[1:] + "?"
        normalized_item = " ".join(item.casefold().split())
        if normalized_item in seen:
            continue
        seen.add(normalized_item)
        items.append(item[:1_000])
        if len(items) > _KNOWLEDGE_REQUEST_ITEM_LIMIT:
            raise ValueError("Knowledge agent request contains too many direct request items")
    return tuple(
        {"id": f"request:item-{index}", "question": item}
        for index, item in enumerate(items, start=1)
    )


def _knowledge_request_tokens(value: str) -> set[str]:
    normalized = re.sub(
        r"\bestimated\s+time\s+of\s+arrival\b",
        " eta ",
        value.casefold(),
    )
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", normalized):
        if raw in _KNOWLEDGE_REQUEST_TOPIC_STOP_WORDS or (len(raw) == 1 and not raw.isdigit()):
            continue
        token = _KNOWLEDGE_REQUEST_TOKEN_ALIASES.get(raw, raw)
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("ing") and len(token) > 5:
            token = token[:-3]
        elif token.endswith("ed") and len(token) > 4:
            token = token[:-2]
        elif token.endswith("s") and len(token) > 4:
            token = token[:-1]
        tokens.add(token)
    return tokens


def _knowledge_request_excerpt_matches(item: dict[str, str], excerpt: str) -> bool:
    topic_tokens = _knowledge_request_tokens(item["question"])
    if not topic_tokens:
        return bool(excerpt.strip())
    excerpt_tokens = _knowledge_request_tokens(excerpt)
    specific_tokens = topic_tokens - _KNOWLEDGE_REQUEST_GENERIC_STATE_TOKENS
    compared_tokens = specific_tokens or topic_tokens
    matched = len(compared_tokens & excerpt_tokens)
    required = max(1, (len(compared_tokens) * 2 + 4) // 5)
    return matched >= required


def _uncovered_knowledge_request_items(
    *,
    items: tuple[dict[str, str], ...],
    answer: str,
    assessments: list[KnowledgeRequestItemAssessment],
    internal_citation_ids: tuple[str, ...] | list[str] = (),
) -> tuple[dict[str, str], ...]:
    """Accept only unique exact answer spans with enough item-specific topic proof."""
    assessments_by_id: dict[str, list[KnowledgeRequestItemAssessment]] = {}
    for assessment in assessments[:_KNOWLEDGE_REQUEST_ITEM_LIMIT * 2]:
        assessments_by_id.setdefault(assessment.request_item_id.strip(), []).append(assessment)

    uncovered: list[dict[str, str]] = []
    for item in items:
        candidates = assessments_by_id.get(item["id"], [])
        if len(candidates) != 1:
            uncovered.append(item)
            continue
        excerpt = _strip_internal_citation_markers(
            candidates[0].answer_excerpt,
            internal_citation_ids=internal_citation_ids,
        ).strip()
        if not excerpt or excerpt not in answer or not _knowledge_request_excerpt_matches(item, excerpt):
            uncovered.append(item)
    return tuple(uncovered)


def _knowledge_unknown_item_answer(item: str, *, language: str) -> str:
    templates = {
        "de": 'Die verfügbaren Belege klären diesen angefragten Punkt nicht: "{item}"',
        "fr": 'Les éléments disponibles ne permettent pas d’établir ce point demandé : « {item} »',
        "es": 'La información disponible no permite establecer este punto solicitado: «{item}»',
        "it": 'Le informazioni disponibili non consentono di stabilire questo punto richiesto: «{item}»',
        "en": 'Available evidence does not establish this requested item: "{item}"',
    }
    return templates.get(language, templates["en"]).format(item=item)


def _repair_knowledge_request_item_coverage(
    *,
    answer: str,
    question: str,
    items: tuple[dict[str, str], ...],
    assessments: list[KnowledgeRequestItemAssessment],
    internal_citation_ids: tuple[str, ...] | list[str] = (),
) -> tuple[str, tuple[dict[str, str], ...]]:
    """Fail closed per omitted item by appending one explicit evidence-unknown result."""
    uncovered = _uncovered_knowledge_request_items(
        items=items,
        answer=answer,
        assessments=assessments,
        internal_citation_ids=internal_citation_ids,
    )
    if not uncovered:
        return answer, ()
    language = _detected_supported_language(question)
    repair = " ".join(
        _knowledge_unknown_item_answer(item["question"], language=language)
        for item in uncovered
    )
    return f"{answer.rstrip()}\n\n{repair}".strip(), uncovered


def _knowledge_failure_answer(
    question: str,
    messages: list[dict[str, Any]] | None = None,
) -> str:
    language_parts = [question]
    for message in reversed(messages or []):
        message_body = _string_from(message.get("body") or message.get("content"))
        if message_body:
            language_parts.append(message_body[:1_000])
            break
    language = _detected_supported_language(*language_parts)
    return {
        "de": (
            "Die Wissensrecherche konnte nicht abgeschlossen werden. Es wurde keine belegte Antwort erstellt. "
            "Bitte prüfen Sie dieses Ticket manuell, bevor Sie antworten."
        ),
        "fr": (
            "La recherche dans les connaissances n’a pas pu être terminée. Aucune réponse étayée n’a été "
            "produite. Veuillez faire vérifier ce ticket avant de répondre."
        ),
        "es": (
            "No se pudo completar la búsqueda en la base de conocimiento. No se generó una respuesta "
            "fundamentada. Revise este ticket manualmente antes de responder."
        ),
        "it": (
            "La ricerca nella knowledge base non è stata completata. Non è stata generata una risposta "
            "supportata da fonti. Verifica manualmente il ticket prima di rispondere."
        ),
        "en": (
            "Knowledge research could not be completed. No grounded answer was produced. "
            "Please review this ticket manually before replying."
        ),
    }[language]


def _battery_safety_failure_answer(
    messages: list[dict[str, Any]] | None = None,
    *,
    language: str | None = None,
) -> str:
    """Return complete policy guidance when model generation cannot do so safely."""
    language = language if language in _LANGUAGE_NAMES else _latest_customer_language(messages or [])
    return {
        "de": (
            "Nicht berühren. Nicht benutzen. Nicht laden. Isolieren Sie den Artikel nur, "
            "wenn dies sicher möglich ist, und halten Sie ihn nur wenn sicher von Hitze "
            "und brennbaren Materialien fern. Nicht versenden, zurücksenden oder anderweitig "
            "transportieren, bevor Sie bestätigte Gefahrgut-Anweisungen von einem Menschen "
            "erhalten. Wenn Rauch, Feuer oder ungewöhnliche Hitze auftritt, entfernen Sie "
            "sich und kontaktieren Sie den örtlichen Notdienst oder die Feuerwehr. Eine "
            "menschliche Sicherheitsprüfung ist erforderlich, bevor eine Eskalation, ein "
            "Ersatz, eine Rückerstattung, eine Abholung oder Rücksendung bestätigt werden "
            "kann; dieser Entwurf bestätigt keine solche Aktion. Bewahren Sie vorhandene "
            "Bestelldaten und bereits aufgenommene Fotos auf, aber bewegen oder berühren Sie "
            "den Artikel nicht, um weitere Beweise zu sammeln."
        ),
        "fr": (
            "Ne manipulez pas, n'utilisez pas et ne rechargez pas l'article. Isolez-le "
            "uniquement si cela peut être fait en toute sécurité, et gardez-le à l'écart de "
            "la chaleur et des matières inflammables uniquement si c'est sûr. Ne l'expédiez "
            "pas, ne le retournez pas et ne le transportez pas avant d'avoir reçu d'une "
            "personne des consignes confirmées pour les marchandises dangereuses. En cas de "
            "fumée, d'incendie ou de chaleur inhabituelle, éloignez-vous et contactez les "
            "services d'urgence locaux ou les pompiers. Un contrôle humain de sécurité est "
            "requis avant de confirmer une escalade, un remplacement, un remboursement, un "
            "enlèvement ou un retour ; ce brouillon ne confirme aucune de ces actions. "
            "Conservez les informations de commande et les photos déjà prises, mais ne "
            "manipulez ni ne déplacez l'article pour recueillir d'autres preuves."
        ),
        "es": (
            "No manipule, use ni cargue el artículo. Aíslelo solo si puede hacerse de forma "
            "segura y manténgalo alejado del calor y de materiales inflamables, solo si es "
            "seguro. No lo envíe, devuelva ni transporte antes de recibir de una persona "
            "instrucciones confirmadas de seguridad para mercancías peligrosas. Si hay humo, "
            "fuego o calor inusual, aléjese y contacte los servicios de emergencia locales o "
            "los bomberos. Se requiere una revisión humana de seguridad antes de confirmar "
            "una escalada, sustitución, reembolso, recogida o devolución; este borrador no "
            "confirma ninguna de esas acciones. Conserve los datos del pedido y las fotos ya "
            "tomadas, pero no manipule ni mueva el artículo para reunir más pruebas."
        ),
        "it": (
            "Non manipoli, non utilizzi e non ricarichi l'articolo. Lo isoli solo se può "
            "farlo in sicurezza e lo tenga lontano dal calore e dai materiali infiammabili, "
            "solo se è sicuro. Non lo spedisca, restituisca o trasporti prima di ricevere da "
            "una persona istruzioni confermate di sicurezza per merci pericolose. In caso di "
            "fumo, fuoco o calore insolito, si allontani e contatti i servizi di emergenza "
            "locali o i vigili del fuoco. È necessaria una revisione umana della sicurezza "
            "prima di confermare un'escalation, una sostituzione, un rimborso, un ritiro o un "
            "reso; questa bozza non conferma nessuna di tali azioni. Conservi i dati "
            "dell'ordine e le foto già scattate, ma non manipoli né sposti l'articolo per "
            "raccogliere ulteriori prove."
        ),
        "en": (
            "Stop handling, using, and charging the item immediately. Isolate it only if this "
            "can be done safely, and keep it away from heat and flammable materials only if "
            "safe. Do not ship, return, or otherwise transport it until a human provides "
            "confirmed hazardous-goods instructions. If smoke, fire, or unusual heat is "
            "present or develops, move away and contact local emergency services or the local "
            "fire authority. No escalation, replacement, refund, collection, return, or other "
            "business action has been confirmed. Human safety review is required before any "
            "business next step. Keep existing order details and any photos already taken "
            "available, but do not handle or move the item to collect more evidence."
        ),
    }[language]


def _safety_aware_failure_answer(
    *,
    assessment: SafetyGuidanceAssessment,
    ordinary_answer: str,
    messages: list[dict[str, Any]] | None = None,
) -> str:
    if assessment.active:
        return _battery_safety_failure_answer(messages)
    return ordinary_answer


def _article_context(articles: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    for article in articles[:limit]:
        metadata = _record_from(article.get("metadata"))
        context.append(
            {
                "id": _string_from(article.get("id")),
                "title": _string_from(article.get("title")),
                "body": _string_from(article.get("body"))[:2_400],
                "tags": article.get("tags") if isinstance(article.get("tags"), list) else [],
                "status": _string_from(article.get("status")),
                "reviewStatus": _string_from(article.get("reviewStatus")),
                "freshnessStatus": _string_from(article.get("freshnessStatus")),
                "source": _string_from(article.get("sourceUrl") or metadata.get("source") or metadata.get("url")),
                "match": _record_from(metadata.get("knowledgeMatch")),
            }
        )
    return context


def _agent_chat_context(runs: list[dict[str, Any]], limit: int = 6) -> list[dict[str, str]]:
    context: list[dict[str, str]] = []
    for run in runs[-limit:]:
        metadata = _record_from(run.get("metadata"))
        answer = _string_from(metadata.get("answer") or run.get("summary"))
        if not answer:
            continue
        context.append(
            {
                "id": _string_from(run.get("id")),
                "question": _string_from(metadata.get("question")),
                "answer": answer[:2400],
                "confidence": _string_from(metadata.get("confidence")),
                "completedAt": _string_from(run.get("completedAt") or run.get("completed_at") or run.get("created")),
            }
        )
    return context


def _conversation_context(conversation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(conversation, dict) or not _string_from(conversation.get("key")):
        return {}
    tickets = conversation.get("tickets") if isinstance(conversation.get("tickets"), list) else []
    messages = conversation.get("messages") if isinstance(conversation.get("messages"), list) else []
    return {
        "key": _string_from(conversation.get("key")),
        "source": _string_from(conversation.get("source")),
        "label": _string_from(conversation.get("label")),
        "channel": _string_from(conversation.get("channel")),
        "currentIssueId": _string_from(conversation.get("currentIssueId")),
        "issueCount": _positive_int_from(conversation.get("issueCount")),
        "messageCount": _positive_int_from(conversation.get("messageCount")),
        "openCount": _positive_int_from(conversation.get("openCount")),
        "ongoingCount": _positive_int_from(conversation.get("ongoingCount")),
        "doneCount": _positive_int_from(conversation.get("doneCount")),
        "latestMessageAt": _string_from(conversation.get("latestMessageAt")),
        "tickets": [
            {
                "id": _string_from(ticket.get("id")),
                "subject": _string_from(ticket.get("subject")),
                "status": _string_from(ticket.get("status")),
                "priority": _string_from(ticket.get("priority")),
                "latestMessageAt": _string_from(ticket.get("latestMessageAt")),
                "needsResponse": bool(ticket.get("needsResponse")),
            }
            for ticket in tickets[:6]
            if isinstance(ticket, dict)
        ],
        "messages": [
            {
                "issueId": _string_from(message.get("issueId")),
                "ticketSubject": _string_from(message.get("ticketSubject")),
                "direction": _string_from(message.get("direction")),
                "sender": _string_from(message.get("sender")),
                "body": _string_from(message.get("body"))[:1200],
                "occurredAt": _string_from(message.get("occurredAt")),
            }
            for message in messages[-12:]
            if isinstance(message, dict) and _string_from(message.get("body"))
        ],
    }


def _ticket_context(issue: dict[str, Any]) -> dict[str, Any]:
    ticket = {
        "id": _string_from(issue.get("id")),
        "subject": _string_from(issue.get("subject")),
        "status": _string_from(issue.get("status") or issue.get("workflowStatus")),
        "priority": _string_from(issue.get("priority")),
        "channel": _string_from(issue.get("channel")),
        "queue": _string_from(issue.get("queueName") or issue.get("queueKey")),
        "account": _string_from(issue.get("accountName") or issue.get("accountDomain")),
        "contact": _string_from(issue.get("contactEmail") or issue.get("fromAddress")),
        "summary": _string_from(issue.get("aiSummary")),
        "runbook": _string_from(issue.get("activatedIntent") or issue.get("activated_intent")),
    }
    concern_context, tool_evidence, run_scope = _automatic_runbook_concern_context(issue)
    if concern_context:
        ticket["concerns"] = concern_context
    if tool_evidence:
        ticket["toolEvidence"] = tool_evidence
    runbook_actions = _automatic_runbook_action_context(
        issue,
        concern_ids={
            _string_from(concern.get("id"))
            for concern in concern_context
            if isinstance(concern, dict) and _string_from(concern.get("id"))
        },
        source_message_id=_string_from(run_scope.get("sourceMessageId")),
    )
    if runbook_actions:
        ticket["runbookActions"] = runbook_actions
    return ticket


def _validated_response_attachments(
    issue: dict[str, Any],
    requested_filenames: list[str],
) -> tuple[str, ...]:
    """Allow only latest-run attachment names; always-mode files cannot be omitted."""
    ticket = _ticket_context(issue)
    available: dict[str, str] = {}
    for concern in ticket.get("concerns", []):
        if not isinstance(concern, dict):
            continue
        for item in concern.get("attachments", []):
            if not isinstance(item, dict):
                continue
            filename = _string_from(item.get("filename"))
            if filename:
                available.setdefault(filename, _string_from(item.get("mode")).lower())

    selected: list[str] = []
    for raw_filename in requested_filenames[:20]:
        filename = _string_from(raw_filename)
        if filename in available and filename not in selected:
            selected.append(filename)
    for filename, mode in available.items():
        if mode in {"always", "generated"} and filename not in selected:
            selected.append(filename)
    return tuple(selected[:20])


def _validated_concern_coverage(
    issue: dict[str, Any],
    covered_concern_ids: list[str],
    *,
    model_requires_human: bool,
    model_reason: str,
) -> tuple[tuple[str, ...], bool, str]:
    expected_ids = [
        _string_from(concern.get("id"))
        for concern in _ticket_context(issue).get("concerns", [])
        if isinstance(concern, dict) and _string_from(concern.get("id"))
    ]
    covered_ids = tuple(_string_from(item) for item in covered_concern_ids[:20] if _string_from(item))
    reasons: list[str] = []
    requires_human = bool(model_requires_human)
    if expected_ids and (len(covered_ids) != len(expected_ids) or set(covered_ids) != set(expected_ids)):
        requires_human = True
        reasons.append("Reply composer did not confirm exact coverage of every concern.")
    if model_requires_human:
        reasons.append(model_reason.strip() or "Reply composer requested human review.")
    return covered_ids, requires_human, " ".join(dict.fromkeys(reasons))[:1_000]


def _answer_obligations_from_issue(issue: dict[str, Any]) -> tuple[dict[str, str], ...]:
    obligations: list[dict[str, str]] = []
    seen: set[str] = set()
    for concern in _ticket_context(issue).get("concerns", []):
        if not isinstance(concern, dict):
            continue
        concern_id = _string_from(concern.get("id"))
        for field_name, default_kind in (
            ("answerObligations", "customer_question"),
            ("requiredGuidanceObligations", "runbook_requirement"),
        ):
            raw_obligations = concern.get(field_name)
            if not isinstance(raw_obligations, list):
                continue
            for raw in raw_obligations[:20]:
                obligation = _record_from(raw)
                obligation_id = _string_from(obligation.get("id"))
                question = _string_from(obligation.get("question"))
                if not obligation_id or not question or obligation_id in seen:
                    continue
                seen.add(obligation_id)
                kind = _string_from(obligation.get("kind")) or default_kind
                normalized = {
                    "id": obligation_id,
                    "concernId": concern_id,
                    "question": question,
                }
                if kind != "customer_question":
                    normalized["kind"] = kind
                obligations.append(normalized)
    return tuple(obligations)


def _validated_obligation_coverage(
    issue: dict[str, Any],
    covered_obligation_ids: list[str],
) -> tuple[tuple[str, ...], bool, str]:
    expected_ids = [item["id"] for item in _answer_obligations_from_issue(issue)]
    covered_ids = tuple(
        dict.fromkeys(_string_from(item) for item in covered_obligation_ids[:100] if _string_from(item))
    )
    if expected_ids and (len(covered_ids) != len(expected_ids) or set(covered_ids) != set(expected_ids)):
        return (
            covered_ids,
            True,
            "Reply composer did not confirm exact coverage of every answer obligation.",
        )
    return covered_ids, False, ""


def _validated_draft_coverage(
    issue: dict[str, Any],
    covered_concern_ids: list[str],
    covered_obligation_ids: list[str],
    *,
    model_requires_human: bool,
    model_reason: str,
) -> tuple[tuple[str, ...], tuple[str, ...], bool, str]:
    concern_ids, requires_human, concern_reason = _validated_concern_coverage(
        issue,
        covered_concern_ids,
        model_requires_human=model_requires_human,
        model_reason=model_reason,
    )
    obligation_ids, obligation_requires_human, obligation_reason = _validated_obligation_coverage(
        issue, covered_obligation_ids
    )
    reasons = [reason for reason in (concern_reason, obligation_reason) if reason]
    return (
        concern_ids,
        obligation_ids,
        requires_human or obligation_requires_human,
        " ".join(dict.fromkeys(reasons))[:1_000],
    )


def _issue_safety_assessment(
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
) -> SafetyGuidanceAssessment:
    return assess_lithium_battery_safety(
        subject=_string_from(issue.get("subject")),
        messages=messages,
    )


def _with_safety_prompt_context(
    ticket: dict[str, Any],
    assessment: SafetyGuidanceAssessment,
) -> dict[str, Any]:
    """Expose activated policy and its obligation without mutating runbook outcomes."""
    if not assessment.active:
        return ticket
    return {
        **ticket,
        "systemSafety": assessment.prompt_context(),
    }


def _safety_review_state(
    assessment: SafetyGuidanceAssessment,
    *,
    model_requires_human: bool,
    model_reason: str,
) -> tuple[bool, str]:
    reasons = [model_reason.strip()] if model_requires_human and model_reason.strip() else []
    if assessment.active:
        reasons.append(assessment.requires_human_reason)
    return (
        bool(model_requires_human or assessment.active),
        " ".join(dict.fromkeys(reasons))[:1_000],
    )


def _bounded_string_list(value: Any, *, limit: int = 10, item_limit: int = 500) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []
    return [clean[:item_limit] for item in values[:limit] if (clean := _string_from(item))]


def _tool_evidence_id(name: str, *, concern_id: str = "") -> str:
    """Build the exact evidence identity for legacy or concern-scoped tools."""
    return f"tool:{concern_id}:{name}" if concern_id else f"tool:{name}"


def _automatic_tool_evidence_context(
    value: Any,
    *,
    concern_id: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Expose only the bounded, allowlisted facts recorded by HTTP tools."""
    if not isinstance(value, list):
        return []
    evidence: list[dict[str, Any]] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        status = _string_from(item.get("status"))
        record: dict[str, Any] = {
            "name": _string_from(item.get("name") or item.get("toolName") or item.get("tool_name"))[:160],
            "method": _string_from(item.get("method"))[:16],
            "status": status[:80],
        }
        facts = item.get("responseFacts") or item.get("response_facts") or item.get("facts")
        if status == "success" and isinstance(facts, (dict, list)) and facts:
            # http_tool owns the allowlist and size bounds. Round-trip through JSON
            # to detach the prompt context from mutable persisted metadata.
            try:
                record["responseFacts"] = json.loads(json.dumps(facts, ensure_ascii=False))
                record["evidenceId"] = _tool_evidence_id(
                    record["name"],
                    concern_id=concern_id,
                )
            except (TypeError, ValueError):
                pass
        if record["name"]:
            evidence.append(record)
    return evidence


def _is_runbook_ai_run(
    run: dict[str, Any],
    intent_result: dict[str, Any],
) -> bool:
    """Identify modern and legacy runbook runs without claiming unrelated AI work."""
    metadata = _record_from(run.get("metadata"))
    if _string_from(metadata.get("kind")) == "direct_channel_runbooks":
        return True
    if _string_from(run.get("source")).startswith("channel:"):
        return True
    if isinstance(intent_result.get("concerns"), list):
        return True
    return any(key in intent_result for key in ("matched", "intentName", "intent_name"))


def _automatic_runbook_concern_context(
    issue: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Return latest per-message concern outcomes plus safe tool evidence."""
    runs = issue.get("aiRuns")
    if not isinstance(runs, list):
        return [], [], {}

    for run in runs:
        if not isinstance(run, dict):
            continue
        source = _string_from(run.get("source"))
        if source in {"agent_answer", "triage", "custom_fields"}:
            continue
        metadata = _record_from(run.get("metadata"))
        source_message_id = _string_from(
            metadata.get("emailId") or metadata.get("messageId") or metadata.get("sourceMessageId")
        )
        intent_result = _record_from(run.get("intentResult") or run.get("intent_result"))
        if not _is_runbook_ai_run(run, intent_result):
            continue
        raw_concerns = intent_result.get("concerns")
        if not isinstance(raw_concerns, list) or not raw_concerns:
            # Runs are newest-first. Once the newest runbook run is found,
            # never revive concerns or evidence from an older customer message.
            return [], [], {"sourceMessageId": source_message_id}

        concerns: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_concerns[:10]):
            if not isinstance(raw, dict):
                continue
            outcome = _record_from(raw.get("outcome") or raw.get("runbookOutcome") or raw.get("runbook_outcome"))
            intent_name = _string_from(
                raw.get("intentName")
                or raw.get("intent_name")
                or raw.get("runbook")
                or outcome.get("intentName")
                or outcome.get("intent_name")
                or outcome.get("runbook")
            )
            matched_value = raw.get("matched")
            matched = bool(intent_name) if matched_value is None else bool(matched_value)
            concern: dict[str, Any] = {
                "id": _string_from(raw.get("concernId") or raw.get("concern_id") or raw.get("id"))
                or f"concern-{index + 1}",
                "text": _string_from(
                    raw.get("text") or raw.get("sourceText") or raw.get("source_text") or raw.get("summary")
                )[:1_000],
                "matched": matched,
                "runbook": intent_name[:240],
                "confidence": _string_from(raw.get("confidence") or outcome.get("confidence"))[:40],
                "status": _string_from(outcome.get("status") or raw.get("status"))[:80],
                "requiresHuman": bool(
                    outcome.get("requiresHuman")
                    or outcome.get("requires_human")
                    or raw.get("requiresHuman")
                    or raw.get("requires_human")
                ),
            }
            concern_summary = _string_from(
                raw.get("concernSummary")
                or raw.get("concern_summary")
                or outcome.get("concernSummary")
                or outcome.get("concern_summary")
            )
            if concern_summary:
                concern["concernSummary"] = concern_summary[:1_000]
            runbook_outcome_summary = _string_from(
                outcome.get("summary") or raw.get("summary")
            )
            if runbook_outcome_summary:
                concern["runbookOutcomeSummary"] = runbook_outcome_summary[:1_000]
            reason = _string_from(
                raw.get("reason")
                or raw.get("unmatchedReason")
                or raw.get("unmatched_reason")
                or raw.get("requiresHumanReason")
                or raw.get("requires_human_reason")
                or outcome.get("reason")
                or outcome.get("requiresHumanReason")
                or outcome.get("requires_human_reason")
                or outcome.get("error")
                or raw.get("error")
            )
            if reason:
                concern["reason"] = reason[:500]
            raw_obligations = (
                outcome.get("answerObligations")
                or outcome.get("answer_obligations")
                or raw.get("answerObligations")
                or raw.get("answer_obligations")
                or []
            )
            obligations: list[dict[str, str]] = []
            if isinstance(raw_obligations, list):
                for obligation_index, raw_obligation in enumerate(raw_obligations[:10], start=1):
                    obligation = _record_from(raw_obligation)
                    question = _string_from(
                        obligation.get("question")
                        or obligation.get("text")
                        or (raw_obligation if isinstance(raw_obligation, str) else "")
                    )
                    obligation_id = (
                        _string_from(
                            obligation.get("obligationId") or obligation.get("obligation_id") or obligation.get("id")
                        )
                        or f"{concern['id']}:obligation-{obligation_index}"
                    )
                    if not question:
                        continue
                    obligations.append(
                        {
                            "id": obligation_id[:240],
                            "question": question[:500],
                            "sourceText": _string_from(obligation.get("sourceText") or obligation.get("source_text"))[
                                :1_000
                            ],
                        }
                    )
            if obligations:
                concern["answerObligations"] = obligations
            missing = _bounded_string_list(
                outcome.get("missingInformation")
                or outcome.get("missing_information")
                or raw.get("missingInformation")
                or raw.get("missing_information")
            )
            if missing:
                concern["missingInformation"] = missing
            requirements = _bounded_string_list(
                outcome.get("replyRequirements")
                or outcome.get("reply_requirements")
                or outcome.get("responseRules")
                or outcome.get("response_rules")
                or raw.get("replyRequirements")
                or raw.get("reply_requirements")
            )
            if requirements:
                concern["replyRequirements"] = requirements
            required_guidance = _bounded_string_list(
                outcome.get("requiredGuidance")
                or outcome.get("required_guidance")
                or raw.get("requiredGuidance")
                or raw.get("required_guidance")
            )
            if required_guidance:
                concern["requiredGuidance"] = required_guidance
                concern["requiredGuidanceObligations"] = [
                    {
                        "id": f"{concern['id']}:required-guidance-{guidance_index}",
                        "question": guidance,
                        "kind": "runbook_requirement",
                    }
                    for guidance_index, guidance in enumerate(required_guidance, start=1)
                ]
            forbidden = _bounded_string_list(
                outcome.get("forbiddenClaims")
                or outcome.get("forbidden_claims")
                or raw.get("forbiddenClaims")
                or raw.get("forbidden_claims")
            )
            if forbidden:
                concern["forbiddenClaims"] = forbidden
            raw_attachments = outcome.get("attachments") or raw.get("attachments") or []
            attachments: list[dict[str, str]] = []
            if isinstance(raw_attachments, list):
                for raw_attachment in raw_attachments[:20]:
                    attachment = _record_from(raw_attachment)
                    filename = _string_from(attachment.get("filename"))
                    if not filename:
                        continue
                    attachments.append(
                        {
                            "filename": filename[:240],
                            "description": _string_from(attachment.get("description"))[:500],
                            "mode": _string_from(attachment.get("mode") or "dynamic")[:40],
                            "source": _string_from(attachment.get("source") or "runbook")[:40],
                        }
                    )
            if attachments:
                concern["attachments"] = attachments
            concern_tools = _automatic_tool_evidence_context(
                outcome.get("toolEvidence")
                or outcome.get("tool_evidence")
                or outcome.get("toolCalls")
                or outcome.get("tool_calls")
                or raw.get("toolEvidence")
                or raw.get("tool_evidence")
                or raw.get("toolCalls")
                or raw.get("tool_calls"),
                concern_id=concern["id"],
            )
            if concern_tools:
                concern["toolEvidence"] = concern_tools
            concerns.append(concern)

        # Modern runs bind evidence to each concern. Flat run-level calls can
        # include identity or another concern and are not customer-claim proof.
        return concerns, [], {"sourceMessageId": source_message_id}
    return [], [], {}


def _automatic_runbook_action_context(
    issue: dict[str, Any],
    *,
    concern_ids: set[str] | None = None,
    source_message_id: str = "",
) -> list[dict[str, Any]]:
    actions = issue.get("actionExecutions")
    if not isinstance(actions, list):
        return []
    context: list[dict[str, Any]] = []
    for execution in actions[:25]:
        if not isinstance(execution, dict):
            continue
        metadata = _record_from(execution.get("metadata"))
        status = _string_from(execution.get("status")).lower()
        execution_type = _string_from(execution.get("type")).lower()
        execution_source = _string_from(metadata.get("source")).lower()
        is_runbook_action = execution_type == "runbook_webhook" or execution_source == "runbook"
        # Channel triage is a real pending mutation even though it is not a
        # runbook webhook. Expose only the approval-gated pending form.
        is_pending_agent_triage = (
            (execution_type == "agent_triage" or execution_source == "agent_triage")
            and status == "pending"
            and metadata.get("approvalRequired") is True
        )
        if not is_runbook_action and not is_pending_agent_triage:
            continue
        automation_context = _record_from(metadata.get("automationContext") or metadata.get("automation_context"))
        # Channel-created actions keep their message scope in automationContext.
        execution_source_message_ids = {
            value
            for value in (
                _string_from(metadata.get("sourceMessageId") or metadata.get("source_message_id")),
                _string_from(metadata.get("emailId") or metadata.get("email_id")),
                _string_from(metadata.get("messageId") or metadata.get("message_id")),
                _string_from(automation_context.get("sourceMessageId") or automation_context.get("source_message_id")),
                _string_from(automation_context.get("emailId") or automation_context.get("email_id")),
                _string_from(automation_context.get("messageId") or automation_context.get("message_id")),
            )
            if value
        }
        result = _record_from(execution.get("result"))
        proposed = _record_from(result.get("proposedAction") or metadata.get("proposedAction"))
        execution_concern_id = _string_from(
            metadata.get("concernId")
            or metadata.get("concern_id")
            or proposed.get("concernId")
            or proposed.get("concern_id")
        )
        if source_message_id and source_message_id not in execution_source_message_ids:
            continue
        if concern_ids and is_runbook_action and execution_concern_id not in concern_ids:
            continue
        name = _string_from(proposed.get("name") or execution.get("actionKey"))
        label = _string_from(proposed.get("label") or execution.get("label") or name)
        concern_id = execution_concern_id
        runbook = _string_from(metadata.get("runbook") or proposed.get("runbook"))
        if status == "pending" and metadata.get("approvalRequired") is True:
            action_context = {
                "name": name,
                "label": label,
                "status": "pending_approval",
            }
            if concern_id:
                action_context["concernId"] = concern_id
            if runbook:
                action_context["runbook"] = runbook
            context.append(action_context)
            if len(context) >= 10:
                break
            continue
        if status in {"failed", "skipped"}:
            application = _record_from(result.get("application"))
            approval = _record_from(result.get("approval"))
            error = _string_from(execution.get("error") or application.get("error") or approval.get("note"))[
                :_AUTOMATIC_RUNBOOK_ACTION_ERROR_MAX_CHARS
            ]
            action_context = {
                "name": name,
                "label": label,
                "status": status,
                "completedAt": _string_from(execution.get("completedAt")),
            }
            if concern_id:
                action_context["concernId"] = concern_id
            if runbook:
                action_context["runbook"] = runbook
            if error:
                action_context["error"] = error
            context.append(action_context)
            if len(context) >= 10:
                break
            continue
        application = _record_from(result.get("application"))
        webhook_result = _record_from(application.get("webhookResult"))
        if status != "success" or application.get("applied") is not True or webhook_result.get("status") != "ok":
            continue
        response = webhook_result.get("response")
        proof: dict[str, Any] = {}
        if isinstance(response, dict):
            # Validate the complete response before minimizing it. Otherwise a
            # negative sibling such as ``error`` or ``failed`` could be dropped
            # while its reference number was incorrectly retained as success.
            if not has_meaningful_action_success_proof(
                response,
                action={"name": name, "label": label},
            ):
                continue
            for key in (
                "action",
                "status",
                "ok",
                "id",
                "reference",
                "ticketReference",
                "confirmationNumber",
            ):
                value = response.get(key)
                if isinstance(value, str):
                    cleaned = value.strip()
                    if cleaned and len(cleaned) <= 240:
                        proof[key] = cleaned
                elif isinstance(value, bool):
                    proof[key] = value
                elif isinstance(value, int):
                    proof[key] = value
        if not has_meaningful_action_success_proof(
            proof,
            action={"name": name, "label": label},
        ):
            continue
        action_context = {
            "name": name,
            "label": label,
            "status": "success",
            "completedAt": _string_from(execution.get("completedAt")),
            # Preserve the minimal durable execution proof needed by the
            # deterministic action-state guard. The full webhook payload stays
            # out of customer-facing context.
            "applied": True,
            "webhookResult": {"status": "ok"},
            "proof": proof,
        }
        if concern_id:
            action_context["concernId"] = concern_id
        if runbook:
            action_context["runbook"] = runbook
        if concern_id and name:
            execution_id = _string_from(execution.get("id"))
            evidence_scope = execution_id or f"{concern_id}:{name}"
            action_context["evidenceId"] = f"action:{evidence_scope}"
        context.append(action_context)
        if len(context) >= 10:
            break
    return context


def _automatic_ticket_context(issue: dict[str, Any]) -> dict[str, Any]:
    """Exclude generated and queue-mutated state from customer-facing evidence."""
    ticket = _ticket_context(issue)
    ticket.pop("status", None)
    ticket.pop("summary", None)
    return ticket


def _global_grounding_ticket_evidence(ticket: dict[str, Any]) -> dict[str, Any]:
    """Keep concern-scoped runbook facts outside the global ``ticket`` evidence ID."""
    return {key: value for key, value in ticket.items() if key not in _GROUNDING_TICKET_SCOPED_KEYS}


def _concern_grounding_evidence_id(concern_id: str) -> str:
    return f"concern:{concern_id}"


def _scoped_grounding_ticket_evidence(
    ticket: dict[str, Any],
) -> dict[str, Any]:
    """Expose runbook facts only through exact concern or legacy evidence IDs."""
    raw_actions = ticket.get("runbookActions")
    actions = raw_actions if isinstance(raw_actions, list) else []
    concern_evidence: list[dict[str, Any]] = []
    raw_concerns = ticket.get("concerns")
    if isinstance(raw_concerns, list):
        for raw_concern in raw_concerns:
            concern = _record_from(raw_concern)
            concern_id = _string_from(concern.get("id") or concern.get("concernId") or concern.get("concern_id"))
            if not concern_id:
                continue
            scoped_actions = [
                action
                for raw_action in actions
                if (
                    (action := _record_from(raw_action))
                    and _string_from(action.get("concernId") or action.get("concern_id")) == concern_id
                )
            ]
            grounding_context = {
                key: value
                for key, value in concern.items()
                if key not in {"concernSummary", "runbookOutcomeSummary"}
            }
            evidence = {
                "evidenceId": _concern_grounding_evidence_id(concern_id),
                "concernId": concern_id,
                "context": grounding_context,
            }
            if scoped_actions:
                evidence["runbookActions"] = scoped_actions
            concern_evidence.append(evidence)

    scoped: dict[str, Any] = {}
    if concern_evidence:
        scoped["concerns"] = concern_evidence
    raw_legacy_tools = ticket.get("toolEvidence")
    if isinstance(raw_legacy_tools, list) and raw_legacy_tools:
        scoped["legacyToolEvidence"] = raw_legacy_tools
    return scoped


def _automatic_conversation_context(
    conversation_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep true-thread context without treating account history as a thread."""
    conversation = _conversation_context(conversation_context)
    if not conversation:
        return {}
    current_issue_id = _string_from(conversation.get("currentIssueId"))
    broad_history_fallback = _string_from(conversation.get("source")).lower() in {
        "account",
        "contact",
    }
    tickets = [
        item
        for item in conversation.get("tickets", [])
        if isinstance(item, dict)
        and (not broad_history_fallback or (current_issue_id and _string_from(item.get("id")) == current_issue_id))
    ]
    messages = [
        message
        for message in conversation.get("messages", [])
        if isinstance(message, dict)
        and _string_from(message.get("direction")).lower() in {"customer", "email", "visitor", "user"}
        and (
            not broad_history_fallback
            or (current_issue_id and _string_from(message.get("issueId")) == current_issue_id)
        )
    ]
    return {
        "key": conversation.get("key", ""),
        "source": conversation.get("source", ""),
        "label": conversation.get("label", ""),
        "channel": conversation.get("channel", ""),
        "currentIssueId": current_issue_id,
        "latestMessageAt": conversation.get("latestMessageAt", ""),
        "tickets": [
            {
                "id": item.get("id", ""),
                "subject": item.get("subject", ""),
                "priority": item.get("priority", ""),
                "latestMessageAt": item.get("latestMessageAt", ""),
                **(
                    {}
                    if _string_from(item.get("id")) == current_issue_id
                    else {
                        "status": item.get("status", ""),
                        "needsResponse": bool(item.get("needsResponse")),
                    }
                ),
            }
            for item in tickets
        ],
        "messages": messages,
    }


def _automatic_account_context(
    account_context: dict[str, Any] | None,
    *,
    issue_id: str = "",
    conversation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Expose bounded account facts without leaking unrelated ticket prose.

    Account rollups can contain free-text signals copied from every ticket in an
    account. Those signals are useful for internal prioritization, but feeding an
    unrelated ``bodyPreview`` to the customer composer can merge one customer's
    incident into another reply. Keep scalar rollups and CRM freshness, and keep
    signal prose only when its source is the current ticket. Conversation
    summaries can be grouped by account or contact and are not an authority to
    expose another ticket's free text.
    """

    account = _record_from(account_context)
    if not account:
        return {}

    del conversation_context
    allowed_issue_ids = {clean_id for value in (issue_id,) if (clean_id := _string_from(value))}

    safe: dict[str, Any] = {}
    for key in ("accountId", "id", "name", "domain"):
        if value := _string_from(account.get(key)):
            safe[key] = value[:500]

    health = _record_from(account.get("health"))
    safe_health: dict[str, Any] = {}
    for key in (
        "status",
        "failedExternalSyncRuns",
        "highPriorityIssues",
        "lastSignalAt",
        "openFeatureRequests",
        "openIssues",
        "openRisks",
        "unresolvedSignals",
        "urgentIssues",
    ):
        value = health.get(key)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            safe_health[key] = value
    if safe_health:
        safe["health"] = safe_health

    insight_summary = _record_from(account.get("insightSummary"))
    safe_summary: dict[str, Any] = {}
    for key in ("lastInsightAt", "openFeatureRequests", "openRisks", "total", "unresolved"):
        value = insight_summary.get(key)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            safe_summary[key] = value
    if safe_summary:
        safe["insightSummary"] = safe_summary

    crm = _record_from(account.get("crm"))
    safe_crm: dict[str, Any] = {}
    for key in ("externalRecordCount", "latestSyncAt", "latestSyncStatus"):
        value = crm.get(key)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            safe_crm[key] = value
    providers = (
        [provider[:120] for value in crm.get("providers", [])[:20] if (provider := _string_from(value))]
        if isinstance(crm.get("providers"), list)
        else []
    )
    if providers:
        safe_crm["providers"] = providers
    if safe_crm:
        safe["crm"] = safe_crm

    related_signals: list[dict[str, Any]] = []
    raw_signals = account.get("openSignals")
    if isinstance(raw_signals, list) and allowed_issue_ids:
        for raw_signal in raw_signals[:100]:
            signal = _record_from(raw_signal)
            source_issue_id = _string_from(signal.get("sourceIssueId"))
            if not source_issue_id or source_issue_id not in allowed_issue_ids:
                continue
            clean_signal: dict[str, Any] = {"sourceIssueId": source_issue_id}
            for key in ("id", "title", "type", "severity", "status", "lastSeenAt", "bodyPreview"):
                if value := _string_from(signal.get(key)):
                    clean_signal[key] = value[:1_000]
            related_signals.append(clean_signal)
            if len(related_signals) >= 20:
                break
    if related_signals:
        safe["openSignals"] = related_signals
    return safe


_LABELED_INTERNAL_CITATION_MARKER_RE = re.compile(
    r"""
    (?P<leading>[ \t]*)
    (?:
        \(\s*(?P<paren_label>
            cited\s+as|citation(?:\s+(?:id|reference))?|source\s+id|evidence\s+id
        )\s*(?::|\#)?\s*(?P<paren_value>[^()\r\n]{1,160}?)\s*\)
        |
        \[\s*(?P<bracket_label>
            cited\s+as|citation(?:\s+(?:id|reference))?|source\s+id|evidence\s+id
        )\s*(?::|\#)?\s*(?P<bracket_value>[^\[\]\r\n]{1,160}?)\s*\]
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_BARE_INTERNAL_CITATION_MARKER_RE = re.compile(
    r"(?P<leading>[ \t]*)(?:\(\s*(?P<paren>[^()\s]{1,160})\s*\)|\[\s*(?P<bracket>[^\[\]\s]{1,160})\s*\])"
)
_INTERNAL_REFERENCE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{1,159}")
_INTERNAL_REFERENCE_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_INTERNAL_REFERENCE_HASH_RE = re.compile(r"[0-9a-f]{32,128}", re.IGNORECASE)
_INTERNAL_REFERENCE_NAMESPACE_RE = re.compile(
    r"(?:article|citation|context|evidence|knowledge|source|tool):[A-Za-z0-9._:/-]{1,150}",
    re.IGNORECASE,
)
_READABLE_BUSINESS_REFERENCE_RE = re.compile(r"[A-Z][A-Z0-9]{1,31}-[0-9]{1,32}")


def _unquote_internal_reference(value: str) -> str:
    clean = value.strip()
    if len(clean) >= 2 and clean[0] == clean[-1] and clean[0] in {'"', "'", "`"}:
        return clean[1:-1].strip()
    return clean


def _looks_like_opaque_internal_reference(value: str) -> bool:
    """Recognize opaque runtime IDs without treating readable citations as internal."""
    if _INTERNAL_REFERENCE_UUID_RE.fullmatch(value):
        return True
    if _INTERNAL_REFERENCE_HASH_RE.fullmatch(value):
        return True
    if _INTERNAL_REFERENCE_NAMESPACE_RE.fullmatch(value):
        return True
    return bool(
        len(value) == 15
        and value.isascii()
        and value.isalnum()
        and value.lower() == value
        and any(char.isalpha() for char in value)
        and any(char.isdigit() for char in value)
    )


def _looks_like_readable_business_reference(value: str) -> bool:
    """Keep incident, order, ticket, and standards references visible to readers."""
    return bool(_READABLE_BUSINESS_REFERENCE_RE.fullmatch(value))


def _strip_internal_citation_markers(
    value: str,
    *,
    internal_citation_ids: tuple[str, ...] | list[str] = (),
) -> str:
    """Remove machine citation markers while preserving readable source prose."""
    known_ids = {
        clean.casefold()
        for raw_id in internal_citation_ids
        if (clean := _unquote_internal_reference(_string_from(raw_id)))
    }

    def is_internal(raw_value: str) -> bool:
        candidate = _unquote_internal_reference(raw_value)
        if not candidate or not _INTERNAL_REFERENCE_TOKEN_RE.fullmatch(candidate):
            return False
        if _looks_like_readable_business_reference(candidate):
            return False
        return candidate.casefold() in known_ids or _looks_like_opaque_internal_reference(candidate)

    def strip_labeled(match: re.Match[str]) -> str:
        marker_value = match.group("paren_value") or match.group("bracket_value") or ""
        return "" if is_internal(marker_value) else match.group(0)

    def strip_bare(match: re.Match[str]) -> str:
        marker_value = match.group("paren") or match.group("bracket") or ""
        candidate = _unquote_internal_reference(marker_value)
        return (
            ""
            if candidate.casefold() in known_ids
            and not _looks_like_readable_business_reference(candidate)
            else match.group(0)
        )

    clean = _LABELED_INTERNAL_CITATION_MARKER_RE.sub(strip_labeled, value)
    return _BARE_INTERNAL_CITATION_MARKER_RE.sub(strip_bare, clean)


def _clean_answer(
    value: str,
    *,
    messages: list[dict[str, Any]] | None = None,
    signer_name: str = "",
    internal_citation_ids: tuple[str, ...] | list[str] = (),
) -> str:
    clean = value.strip()
    if clean.startswith("```"):
        clean = clean.strip("`").strip()
        if clean.lower().startswith("text"):
            clean = clean[4:].strip()
    clean = _strip_internal_citation_markers(
        clean,
        internal_citation_ids=internal_citation_ids,
    )
    return clean_reply_signoff(
        clean[:6000],
        messages=messages,
        signer_name=signer_name,
    )


def grounding_text_sha256(value: str) -> str:
    """Hash the exact normalized text used by grounding and delivery."""
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


_BUSINESS_IDENTIFIER_RE = re.compile(r"(?<![A-Za-z0-9@])[A-Za-z0-9][A-Za-z0-9_-]{6,62}[A-Za-z0-9](?![A-Za-z0-9@])")
_BUSINESS_IDENTIFIER_DURATION_WORDS = {
    "day",
    "days",
    "hour",
    "hours",
    "minute",
    "minutes",
    "month",
    "months",
    "week",
    "weeks",
    "year",
    "years",
}


def _business_identifiers(value: Any) -> tuple[str, ...]:
    """Extract bounded business-like IDs without treating dates or prose as IDs."""
    found: list[str] = []

    def collect(item: Any) -> None:
        if isinstance(item, dict):
            for child in item.values():
                collect(child)
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                collect(child)
            return
        if not isinstance(item, str):
            return
        for match in _BUSINESS_IDENTIFIER_RE.finditer(item):
            candidate = match.group(0)
            if sum(char.isdigit() for char in candidate) < 2:
                continue
            if sum(char.isalpha() for char in candidate) < 2:
                continue
            parts = [part.casefold() for part in re.split(r"[-_]", candidate) if part]
            if (
                len(parts) == 2
                and any(part.isdigit() for part in parts)
                and any(part in _BUSINESS_IDENTIFIER_DURATION_WORDS for part in parts)
            ):
                continue
            found.append(candidate)

    collect(value)
    return tuple(dict.fromkeys(found))


def _allowed_business_identifiers(
    *,
    messages: list[dict[str, Any]],
    ticket: dict[str, Any],
    articles: list[dict[str, Any]],
) -> tuple[str, ...]:
    """Return exact IDs present in bounded customer or trusted support evidence."""
    identifiers: list[str] = []
    for source in (
        _automatic_message_context(messages),
        ticket,
        _article_context(articles),
    ):
        identifiers.extend(_business_identifiers(source))
    return tuple(dict.fromkeys(identifiers))


def _unsupported_business_identifiers(
    answer: str,
    *,
    allowed_identifiers: tuple[str, ...],
) -> tuple[str, ...]:
    allowed = {identifier.casefold() for identifier in allowed_identifiers}
    return tuple(identifier for identifier in _business_identifiers(answer) if identifier.casefold() not in allowed)


def _automatic_tool_evidence_records_with_scope(
    ticket: dict[str, Any],
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Return tool evidence paired with its trusted enclosing concern scope."""
    records: list[tuple[str, dict[str, Any]]] = []
    raw_ticket_evidence = ticket.get("toolEvidence")
    if isinstance(raw_ticket_evidence, list):
        records.extend(("", record) for raw_record in raw_ticket_evidence if (record := _record_from(raw_record)))
    concerns = ticket.get("concerns")
    if isinstance(concerns, list):
        for raw_concern in concerns:
            concern = _record_from(raw_concern)
            concern_id = _string_from(concern.get("id") or concern.get("concernId") or concern.get("concern_id"))
            raw_concern_evidence = concern.get("toolEvidence")
            if concern_id and isinstance(raw_concern_evidence, list):
                records.extend(
                    (concern_id, record) for raw_record in raw_concern_evidence if (record := _record_from(raw_record))
                )
    return tuple(records)


def _automatic_tool_evidence_records(ticket: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Flatten the exact ticket and per-concern tool evidence visible to agents."""
    return tuple(record for _concern_id, record in _automatic_tool_evidence_records_with_scope(ticket))


_TEMPORAL_FACT_TOKEN_ALIASES = {
    "began": "start",
    "begin": "start",
    "beginning": "start",
    "datetime": "time",
    "started": "start",
    "starting": "start",
    "timestamp": "time",
}
_TEMPORAL_FACT_STOP_WORDS = frozenset(
    {
        "at",
        "confirm",
        "confirmed",
        "exact",
        "from",
        "invoice",
        "of",
        "on",
        "recorded",
        "state",
        "the",
    }
)
_TEMPORAL_FACT_TOKENS = frozenset({"date", "due", "eta", "start", "time"})
_READ_ONLY_TEMPORAL_QUESTION_LEAD_RE = re.compile(
    r"^(?:state|report|provide|what(?:['’]s|\s+is|\s+was)|when\b|"
    r"confirm\s+(?:(?:the|a|an)\s+)?(?:recorded|current|tool[-\s]?recorded|verified)\b)",
    re.IGNORECASE,
)
_TEMPORAL_APPROVAL_OR_MUTATION_RE = re.compile(
    r"\b(?:approv(?:e|ed|al)|authori[sz](?:e|ed|ation)|waiv(?:e|ed|er)|"
    r"reschedul(?:e|ed|ing)|postpon(?:e|ed|ing)|extend(?:ed|ing)?|"
    r"chang(?:e|ed|ing)|updat(?:e|ed|ing)|modify|modified|modifying|adjust(?:ed|ing)?|"
    r"set|setting|move|moving|eligib(?:le|ility)|completed?|executed?)\b",
    re.IGNORECASE,
)
_RECORDED_CHANGED_DUE_DATE_CONTRAST_RE = re.compile(
    r"\bdistinguish\b[^.;!?]{0,120}\bfrom\s+(?:(?:a|the)\s+)?changed\s+(?:due\s+)?date\b",
    re.IGNORECASE,
)
_ISO_DATE_OR_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2}))?$"
)
_FIXTURE_EVIDENCE_RESULT_PATH_RE = re.compile(
    r"^fixture_evidence\.result\.\d{1,2}$"
)
_FIXTURE_EVIDENCE_SCALAR_RE = re.compile(
    r"^(?P<path>[A-Za-z][^:\r\n]{0,119}): (?P<value>[^\r\n]{1,500})$"
)
_FIXTURE_TEMPORAL_SCALAR_PATHS = frozenset({"started_at"})
_SERVICE_STATUS_LOOKUP_RE = re.compile(r"\bservice[-_\s]?status\s+lookup\b", re.IGNORECASE)
_SERVICE_INCIDENT_RUNBOOK_RE = re.compile(
    r"(?:^|[-_\s])(?:service[-_\s]+)?incident(?:$|[-_\s])|"
    r"(?:^|[-_\s])outage(?:$|[-_\s])",
    re.IGNORECASE,
)
_SERVICE_INCIDENT_FACT_PATHS = frozenset(
    {"affected_region", "affected_service", "started_at", "status"}
)
_EXPLICIT_INCIDENT_START_TIMESTAMP_RE = re.compile(
    r"\b(?:started|began)\s+(?:at|on|since)\s+"
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})\b",
    re.IGNORECASE,
)


def _tool_fact_scalar_entries(
    value: Any,
    *,
    path: str = "",
    allow_fixture_result_scalars: bool = False,
) -> tuple[tuple[str, str], ...]:
    """Flatten bounded scalar tool facts while retaining their semantic path."""

    entries: list[tuple[str, str]] = []
    if isinstance(value, dict):
        explicit_path = _string_from(value.get("path"))
        if explicit_path and "value" in value and not isinstance(value.get("value"), (dict, list)):
            scalar = _string_from(value.get("value"))
            if scalar:
                fixture_scalar = (
                    _FIXTURE_EVIDENCE_SCALAR_RE.fullmatch(scalar)
                    if allow_fixture_result_scalars
                    and _FIXTURE_EVIDENCE_RESULT_PATH_RE.fullmatch(explicit_path)
                    else None
                )
                if (
                    fixture_scalar
                    and fixture_scalar.group("path") in _FIXTURE_TEMPORAL_SCALAR_PATHS
                ):
                    entries.append(
                        (
                            fixture_scalar.group("path")[:240],
                            fixture_scalar.group("value")[:500],
                        )
                    )
                else:
                    entries.append((explicit_path[:240], scalar[:500]))
            return tuple(entries)
        for raw_key, child in list(value.items())[:100]:
            key = _string_from(raw_key)
            if not key:
                continue
            child_path = f"{path}.{key}" if path else key
            entries.extend(
                _tool_fact_scalar_entries(
                    child,
                    path=child_path,
                    allow_fixture_result_scalars=allow_fixture_result_scalars,
                )
            )
    elif isinstance(value, list):
        for child in value[:100]:
            entries.extend(
                _tool_fact_scalar_entries(
                    child,
                    path=path,
                    allow_fixture_result_scalars=allow_fixture_result_scalars,
                )
            )
    elif path:
        scalar = _string_from(value)
        if scalar:
            entries.append((path[:240], scalar[:500]))
    return tuple(entries)


def _temporal_fact_tokens(value: str) -> frozenset[str]:
    normalized: set[str] = set()
    for token in re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE):
        if token in _TEMPORAL_FACT_STOP_WORDS:
            continue
        alias = _TEMPORAL_FACT_TOKEN_ALIASES.get(token)
        normalized.add(alias if alias is not None else token)
    return frozenset(normalized)


def _temporal_scalar_answer_variants(value: str) -> tuple[str, ...]:
    """Return conservative renderings of one exact ISO tool-backed scalar."""

    if _ISO_DATE_OR_TIMESTAMP_RE.fullmatch(value) is None:
        return ()
    variants = [value]
    if "T" in value:
        date_part, time_part = value.split("T", 1)
        variants.extend((f"{date_part} at {time_part}", f"{date_part} {time_part}"))
    else:
        try:
            parsed_date = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            pass
        else:
            variants.extend(
                (
                    parsed_date.strftime("%B %d, %Y").replace(" 0", " "),
                    parsed_date.strftime("%b %d, %Y").replace(" 0", " "),
                )
            )
    return tuple(dict.fromkeys(variants))


def _answer_contains_temporal_scalar(answer: str, value: str) -> bool:
    folded_answer = answer.casefold()
    return any(variant.casefold() in folded_answer for variant in _temporal_scalar_answer_variants(value))


def _is_atomic_read_only_temporal_question(question: str) -> bool:
    """Reject mutations and multi-fact clauses before deterministic resolution."""

    clean_question = question.strip()
    mutation_scan = _RECORDED_CHANGED_DUE_DATE_CONTRAST_RE.sub("", clean_question)
    if (
        _READ_ONLY_TEMPORAL_QUESTION_LEAD_RE.search(clean_question) is None
        or _TEMPORAL_APPROVAL_OR_MUTATION_RE.search(mutation_scan)
    ):
        return False
    clauses = [
        clause
        for clause in re.split(
            r"\s*(?:;|\b(?:and|or|plus|also)\b)\s*",
            clean_question,
            flags=re.IGNORECASE,
        )
        if clause.strip()
    ]
    if len(clauses) > 1 and _RECORDED_CHANGED_DUE_DATE_CONTRAST_RE.search(clean_question) is None:
        return False
    clause_topics: list[frozenset[str]] = []
    for clause in clauses:
        temporal_tokens = _temporal_fact_tokens(clause).intersection(_TEMPORAL_FACT_TOKENS)
        specific_tokens = temporal_tokens.intersection({"due", "eta", "start"})
        topics = specific_tokens or temporal_tokens.intersection({"date", "time"})
        if not topics:
            return False
        clause_topics.append(frozenset(topics))
    return bool(clause_topics and len(set(clause_topics)) == 1)


def _same_concern_tool_temporal_fact_matches(
    *,
    ticket: dict[str, Any],
    concern_id: str,
    question: str,
    answer: str,
    allowed_evidence_ids: frozenset[str] | None = None,
) -> bool:
    """Recognize only same-concern, successful, exact temporal tool facts."""

    if not _is_atomic_read_only_temporal_question(question):
        return False
    question_tokens = _temporal_fact_tokens(question)
    specific_question_tokens = question_tokens.intersection({"due", "eta", "start"})
    for evidence_concern_id, record in _automatic_tool_evidence_records_with_scope(ticket):
        if evidence_concern_id != concern_id:
            continue
        evidence_id = _valid_tool_evidence_id(record, concern_id=concern_id)
        if not evidence_id or (allowed_evidence_ids is not None and evidence_id not in allowed_evidence_ids):
            continue
        for path, scalar in _tool_fact_scalar_entries(
            record.get("responseFacts"),
            allow_fixture_result_scalars=_string_from(record.get("name")).startswith("fixture_"),
        ):
            path_tokens = _temporal_fact_tokens(path).intersection(_TEMPORAL_FACT_TOKENS)
            if (
                path_tokens
                and path_tokens.intersection(question_tokens)
                and (
                    not specific_question_tokens
                    or path_tokens.intersection(specific_question_tokens)
                )
                and _answer_contains_temporal_scalar(answer, scalar)
            ):
                return True
    return False


def _canonicalize_tool_backed_timestamps(ticket: dict[str, Any], answer: str) -> str:
    """Restore exact trusted ISO timestamp separators before grounding."""

    canonical = answer
    for concern_id, record in _automatic_tool_evidence_records_with_scope(ticket):
        if not _valid_tool_evidence_id(record, concern_id=concern_id):
            continue
        for _path, scalar in _tool_fact_scalar_entries(
            record.get("responseFacts"),
            allow_fixture_result_scalars=_string_from(record.get("name")).startswith("fixture_"),
        ):
            if "T" not in scalar or _ISO_DATE_OR_TIMESTAMP_RE.fullmatch(scalar) is None:
                continue
            for variant in _temporal_scalar_answer_variants(scalar)[1:]:
                canonical = re.sub(re.escape(variant), scalar, canonical, flags=re.IGNORECASE)
    return canonical


def _tool_backed_temporal_scalar_answers_obligation(
    *,
    ticket: dict[str, Any],
    concern_id: str,
    question: str,
    answer_unit_ids: tuple[str, ...],
    expected_units: dict[str, dict[str, Any]],
    supported_unit_evidence_ids: dict[str, frozenset[str]],
) -> bool:
    """Resolve a semantic miss only from a linked exact same-concern tool fact."""

    if not concern_id or not answer_unit_ids:
        return False
    linked_text = " ".join(
        text
        for unit_id in answer_unit_ids
        if (text := _string_from(expected_units.get(unit_id, {}).get("text")))
    )
    linked_evidence_ids = frozenset(
        evidence_id
        for unit_id in answer_unit_ids
        for evidence_id in supported_unit_evidence_ids.get(unit_id, frozenset())
    )
    return bool(
        linked_text
        and linked_evidence_ids
        and _same_concern_tool_temporal_fact_matches(
            ticket=ticket,
            concern_id=concern_id,
            question=question,
            answer=linked_text,
            allowed_evidence_ids=linked_evidence_ids,
        )
    )


def _is_service_incident_temporal_requirement(
    *,
    ticket: dict[str, Any],
    concern_id: str,
    question: str,
) -> bool:
    """Recognize a trusted service-incident timestamp requirement."""

    if (
        _SERVICE_STATUS_LOOKUP_RE.search(question) is None
        or not _is_atomic_read_only_temporal_question(question)
        or "start" not in _temporal_fact_tokens(question)
    ):
        return False
    raw_concerns = ticket.get("concerns")
    concerns = raw_concerns if isinstance(raw_concerns, list) else []
    concern = next(
        (
            record
            for raw_concern in concerns
            if (record := _record_from(raw_concern))
            and _string_from(record.get("id")) == concern_id
        ),
        {},
    )
    if concern.get("matched") is not True or _SERVICE_INCIDENT_RUNBOOK_RE.search(
        _string_from(concern.get("runbook"))
    ) is None:
        return False
    return True


def _service_incident_record_fact_values(
    record: dict[str, Any],
) -> dict[str, frozenset[str]]:
    """Retain every incident field value so conflicting lookup rows stay ambiguous."""

    facts: dict[str, set[str]] = {}
    is_fixture = _string_from(record.get("name")).startswith("fixture_")
    for raw_path, raw_scalar in _tool_fact_scalar_entries(record.get("responseFacts")):
        path = raw_path.rsplit(".", 1)[-1]
        scalar = raw_scalar
        fixture_scalar = (
            _FIXTURE_EVIDENCE_SCALAR_RE.fullmatch(raw_scalar)
            if is_fixture and _FIXTURE_EVIDENCE_RESULT_PATH_RE.fullmatch(raw_path)
            else None
        )
        if fixture_scalar is not None:
            path = fixture_scalar.group("path")
            scalar = fixture_scalar.group("value")
        if path in _SERVICE_INCIDENT_FACT_PATHS and scalar:
            facts.setdefault(path, set()).add(scalar)
    return {path: frozenset(values) for path, values in facts.items()}


def _service_incident_record_facts(record: dict[str, Any]) -> dict[str, str]:
    """Extract only unambiguous status fields used by the incident sentence grammar."""

    return {
        path: next(iter(values))
        for path, values in _service_incident_record_fact_values(record).items()
        if len(values) == 1
    }


def _is_isolated_service_incident_temporal_answer(
    *,
    ticket: dict[str, Any],
    concern_id: str,
    answer_unit_ids: tuple[str, ...],
    expected_units: dict[str, dict[str, Any]],
    supported_unit_evidence_ids: dict[str, frozenset[str]],
) -> bool:
    """Prove one linked unit contains only an exact incident-status timestamp claim."""

    if len(answer_unit_ids) != 1:
        return False
    unit_id = answer_unit_ids[0]
    linked_text = _string_from(expected_units.get(unit_id, {}).get("text"))
    linked_evidence_ids = supported_unit_evidence_ids.get(unit_id, frozenset())
    if not linked_text or not linked_evidence_ids:
        return False
    for evidence_concern_id, record in _automatic_tool_evidence_records_with_scope(ticket):
        if evidence_concern_id != concern_id:
            continue
        evidence_id = _valid_tool_evidence_id(record, concern_id=concern_id)
        if not evidence_id or evidence_id not in linked_evidence_ids:
            continue
        facts = _service_incident_record_facts(record)
        started_at = facts.get("started_at", "")
        if not started_at or _ISO_DATE_OR_TIMESTAMP_RE.fullmatch(started_at) is None:
            continue
        timestamp = re.escape(started_at)
        start_clause = rf"(?:started|began)\s+(?:at|on|since)\s+{timestamp}"
        patterns = [
            rf"(?:The\s+)?(?:service\s+)?(?:incident|outage|issue)\s+{start_clause}\.?",
        ]
        status = facts.get("status", "")
        region = facts.get("affected_region", "")
        service = facts.get("affected_service", "")
        if status and region and service:
            escaped_status = re.escape(status)
            escaped_region = re.escape(region)
            escaped_service = re.escape(service)
            patterns.extend(
                (
                    rf"The\s+{escaped_service}\s+service\s+in\s+(?:the\s+)?{escaped_region}"
                    rf"(?:\s+region)?\s+is\s+currently\s+{escaped_status}\s+an?\s+"
                    rf"(?:incident|outage|issue)\s+(?:that|which)\s+{start_clause}\.?",
                    rf"The\s+(?:service\s+)?(?:incident|outage|issue)\s+is\s+currently\s+"
                    rf"{escaped_status},\s+affecting\s+the\s+{escaped_service}\s+service\s+in\s+"
                    rf"(?:the\s+)?{escaped_region}(?:\s+region)?,\s+and\s+{start_clause}\.?",
                )
            )
            if status.casefold() == "investigating":
                patterns.extend(
                    (
                        rf"(?:This|The)\s+incident\s+is\s+currently\s+under\s+investigation,\s+"
                        rf"affecting\s+the\s+{escaped_region}\s+{escaped_service}\s+service,\s+"
                        rf"and\s+started\s+at\s+{timestamp}\.?",
                        rf"(?:This|The)\s+incident\s+is\s+currently\s+under\s+investigation,\s+"
                        rf"affecting\s+the\s+{escaped_service}\s+service\s+in\s+(?:the\s+)?"
                        rf"{escaped_region}(?:\s+region)?,\s+and\s+started\s+at\s+{timestamp}\.?",
                        rf"This\s+incident,\s+which\s+affects\s+the\s+{escaped_region}\s+"
                        rf"{escaped_service}\s+service,\s+is\s+currently\s+under\s+"
                        rf"investigation\s+and\s+began\s+at\s+{timestamp}\.?",
                    )
                )
        if any(re.fullmatch(pattern, linked_text, flags=re.IGNORECASE) for pattern in patterns):
            return True
    return False


def repair_issue_automation_answer_service_incident_start_time(
    *,
    issue: dict[str, Any],
    answer: str,
    uncovered_obligation_ids: tuple[str, ...],
) -> str:
    """Fill one omitted incident start time from exact same-concern tool proof."""

    clean_answer = answer.strip()
    uncovered_ids = {
        _string_from(obligation_id)
        for obligation_id in uncovered_obligation_ids
        if _string_from(obligation_id)
    }
    if not clean_answer or not uncovered_ids:
        return answer

    ticket = _automatic_ticket_context(issue)
    qualifying_concern_ids = {
        concern_id
        for obligation in _answer_obligations_from_issue(issue)
        if _string_from(obligation.get("id")) in uncovered_ids
        and (
            concern_id := _string_from(obligation.get("concernId"))
        )
        and _is_service_incident_temporal_requirement(
            ticket=ticket,
            concern_id=concern_id,
            question=_string_from(obligation.get("question")),
        )
    }
    if len(qualifying_concern_ids) != 1:
        return answer
    concern_id = next(iter(qualifying_concern_ids))

    started_at_values: set[str] = set()
    for evidence_concern_id, record in _automatic_tool_evidence_records_with_scope(ticket):
        if evidence_concern_id != concern_id:
            continue
        if not _valid_tool_evidence_id(record, concern_id=concern_id):
            continue
        if _string_from(record.get("method")).upper() not in {"GET", "HEAD"}:
            continue
        started_at_values.update(
            _service_incident_record_fact_values(record).get(
                "started_at",
                frozenset(),
            )
        )
    if len(started_at_values) != 1:
        return answer

    started_at = next(iter(started_at_values))
    if "T" not in started_at or _ISO_DATE_OR_TIMESTAMP_RE.fullmatch(started_at) is None:
        return answer
    if started_at.casefold() in clean_answer.casefold():
        return answer
    if _EXPLICIT_INCIDENT_START_TIMESTAMP_RE.search(clean_answer):
        # Do not supplement a conflicting start-time claim. Grounding must keep
        # the draft blocked instead of masking the contradiction.
        return answer
    return f"{clean_answer}\n\nThe incident began at {started_at}."


def _required_secret_delivery_guidance(ticket: dict[str, Any]) -> bool:
    """Require all secret-delivery constraints from one matched concern only."""

    raw_concerns = ticket.get("concerns")
    concerns = raw_concerns if isinstance(raw_concerns, list) else []
    for raw_concern in concerns:
        concern = _record_from(raw_concern)
        if concern.get("matched") is not True:
            continue
        raw_guidance = concern.get("requiredGuidance")
        if not isinstance(raw_guidance, list):
            continue
        guidance = " ".join(_string_from(item) for item in raw_guidance if _string_from(item))
        if (
            _SECRET_DELIVERY_OBJECT_PATTERN.search(guidance)
            and re.search(r"\b(?:never|do\s+not|don['’]t|must\s+not|should\s+not)\b", guidance, re.IGNORECASE)
            and re.search(r"\be-?mail(?:ed|ing)?\b", guidance, re.IGNORECASE)
            and re.search(r"\b(?:approved|trusted)\s+secure\s+channel\b", guidance, re.IGNORECASE)
        ):
            return True
    return False


def _answer_has_complete_secret_delivery_guidance(answer: str) -> bool:
    if _SECRET_EMAIL_PROHIBITION_REVERSAL_PATTERN.search(answer):
        return False
    if any(pattern.search(answer) for pattern in _SECRET_EMAIL_ALLOWANCE_PATTERNS):
        return False
    return bool(
        _SECRET_REPETITION_PROHIBITION_PATTERN.search(answer)
        and any(pattern.search(answer) for pattern in _SECRET_EMAIL_PROHIBITION_PATTERNS)
        and any(pattern.search(answer) for pattern in _SECRET_SECURE_DELIVERY_PATTERNS)
    )


def _append_required_secret_delivery_guidance(
    *,
    ticket: dict[str, Any],
    answer: str,
    language: str,
) -> str:
    """Deterministically preserve mandatory English secret-delivery safety."""

    if (
        language != "en"
        or not _required_secret_delivery_guidance(ticket)
        or _answer_has_complete_secret_delivery_guidance(answer)
    ):
        return answer
    return "\n\n".join((answer.rstrip(), _SECURE_SECRET_DELIVERY_NOTICE)).strip()


def _action_state_obligation_subject(
    question: str,
    *,
    language: str,
) -> str:
    """Extract the customer-visible topic from an explicit state request."""
    for pattern in _ACTION_STATE_OBLIGATION_PATTERNS.get(language, ()):
        match = pattern.fullmatch(question)
        if match is None:
            continue
        raw_subject = match.group("subject").strip()
        action = _string_from(match.groupdict().get("action")).casefold()
        pronoun_subject = bool(_ACTION_STATE_SUBJECT_LEAD_REJECT_PATTERN.search(raw_subject))
        if _ACTION_STATE_SUBJECT_CLAUSE_REJECT_PATTERN.search(raw_subject):
            return ""
        if pronoun_subject:
            if action != "escalate":
                return ""
            return "escalation"
        subject = raw_subject.strip(" \t\r\n.,;:!?\"'“”‘’")
        if language == "es" and subject.casefold().startswith("al "):
            subject = "el " + subject[3:]
        if language == "de" and subject.casefold().startswith("dem "):
            subject = "den " + subject[4:]
        if action in {"record", "log"}:
            subject = f"recording {subject}"
        elif action == "escalate":
            subject = f"escalating {subject}"
        elif action in {"cancel", "terminate", "rescind"}:
            subject = f"cancelling {subject}"
        elif action in {
            "dispatch",
            "investigate",
            "issue",
            "notify",
            "open",
            "refund",
            "replace",
            "reship",
            "submit",
            "update",
            "change",
        }:
            gerund = {
                "change": "changing",
                "dispatch": "dispatching",
                "investigate": "investigating",
                "issue": "issuing",
                "notify": "notifying",
                "open": "opening",
                "refund": "refunding",
                "replace": "replacing",
                "reship": "reshipping",
                "submit": "submitting",
                "update": "updating",
            }[action]
            subject = f"{gerund} {subject}"
        if _action_state_subject_tokens(subject):
            return subject[:240]
    return ""


def _english_action_result_pending_notice(question: str) -> tuple[str, str] | None:
    """Render a direct negative answer for a narrowly bounded result claim."""
    match = _ENGLISH_ACTION_RESULT_CONFIRMATION_PATTERN.fullmatch(question)
    if match is None:
        return None
    topic = match.group("topic").strip(" \t\r\n.,;:!?\"'“”‘’")
    state = match.group("state").casefold()
    if (
        not topic
        or _ACTION_STATE_SUBJECT_LEAD_REJECT_PATTERN.search(topic)
        or _ACTION_STATE_SUBJECT_CLAUSE_REJECT_PATTERN.search(topic)
    ):
        return None
    rendered_topic = topic[:1].upper() + topic[1:]
    subject_key = f"{topic} {state}"
    return (
        subject_key,
        f"{rendered_topic} is not confirmed as {state}. "
        "A related next step for your request remains pending human review.",
    )


def _action_state_subject_tokens(value: str) -> frozenset[str]:
    """Return stable topic tokens for conservative answer-presence checks."""
    return frozenset(
        _ACTION_STATE_SUBJECT_TOKEN_ALIASES.get(word, word)
        for word in re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE)
        if word not in _ACTION_STATE_SUBJECT_STOP_WORDS
    )


def _answer_has_explicit_negative_confirmation(answer: str, subject: str) -> bool:
    """Recognize a direct negative answer so a later policy aside cannot duplicate it."""
    subject_pattern = re.escape(subject).replace(r"\ ", r"\s+")
    patterns = (
        rf"\b(?:cannot|can['’]t|unable\s+to|not\s+able\s+to)\s+confirm\b"
        rf"[^.!?\n]{{0,100}}\b{subject_pattern}\b",
        rf"\b{subject_pattern}\b[^.!?\n]{{0,80}}\b"
        rf"(?:is|are|was|were|has|have|had|cannot|can['’]t)\s+"
        rf"(?:(?:not|never)\s+|not\s+been\s+|be\s+)?confirmed\b",
        rf"\bno\s+confirmation\b[^.!?\n]{{0,100}}\b{subject_pattern}\b",
    )
    return any(re.search(pattern, answer, re.IGNORECASE) for pattern in patterns)


def _answer_uses_pending_confirmation_gerund(answer: str, subject: str) -> bool:
    """Detect bounded, safe `confirming X ... pending` wording for canonicalization."""
    if _answer_has_explicit_negative_confirmation(answer, subject):
        return False
    subject_pattern = re.escape(subject).replace(r"\ ", r"\s+")
    for match in re.finditer(
        rf"\bconfirming\s+(?:the\s+|an?\s+)?{subject_pattern}\b"
        rf"(?P<tail>[^.!?\n]{{0,240}})",
        answer,
        re.IGNORECASE,
    ):
        tail = match.group("tail")
        pending_match = re.match(
            r"^\s+(?:is|are|remain|remains)\s+"
            r"(?:(?:all|both|still)\s+)*(?:pending|awaiting)\b",
            tail,
            re.IGNORECASE,
        )
        if pending_match is not None:
            remainder = tail[pending_match.end() :]
            if (
                re.search(
                    r"\b(?:complete|completed|done|successful|confirmed)\b",
                    remainder,
                    re.IGNORECASE,
                )
                is None
            ):
                return True
        pending_match = re.match(
            r"^(?:\s*,\s*(?:confirming|guaranteeing)\s+[^,;.!?\n]+)+"
            r"\s*,?\s+and\s+(?:confirming|guaranteeing)\s+[^,;.!?\n]+"
            r"\s+(?:are|remain)\s+(?:(?:all|both|still)\s+)*"
            r"(?:pending|awaiting)\b",
            tail,
            re.IGNORECASE,
        )
        if pending_match is not None:
            remainder = tail[pending_match.end() :]
            if (
                re.search(
                    r"\b(?:complete|completed|done|successful|confirmed)\b",
                    remainder,
                    re.IGNORECASE,
                )
                is None
            ):
                return True
    return False


def _answer_mentions_subject_without_positive_action_claim(
    answer: str,
    subject_tokens: frozenset[str],
) -> bool:
    """Count only a safe same-topic explanation, not another concern's action."""
    if not subject_tokens:
        return False
    synthetic_guard = (
        {
            "name": "human_review",
            "label": "Human review",
            "status": "pending_approval",
        },
    )
    for match in re.finditer(r"[^.!?\n]+(?:[.!?]+|(?=\n)|$)", answer):
        unit = match.group(0).strip()
        if not unit or not subject_tokens.issubset(_action_state_subject_tokens(unit)):
            continue
        if not check_pending_action_claims(
            answer=unit,
            runbook_actions=synthetic_guard,
        ).blocked:
            return True
    return False


_HUMAN_REVIEW_CONCERN_STATUSES = frozenset(
    {
        "human_review",
        "needs_human",
        "pending_human_review",
        "requires_human",
    }
)


def _concern_requires_human_review(concern: dict[str, Any]) -> bool:
    """Use only an explicitly matched concern's durable review state."""
    return concern.get("matched") is True and (
        concern.get("requiresHuman") is True
        or _string_from(concern.get("status")).lower().replace("-", "_") in _HUMAN_REVIEW_CONCERN_STATUSES
    )


def _is_durable_successful_runbook_action(action: dict[str, Any]) -> bool:
    """Require the complete, minimized proof emitted for an applied mutation."""
    proof = action.get("proof")
    webhook_result = _record_from(action.get("webhookResult"))
    return bool(
        _string_from(action.get("status")).lower() == "success"
        and action.get("applied") is True
        and _string_from(webhook_result.get("status")).lower() == "ok"
        and _string_from(action.get("evidenceId")).startswith("action:")
        and has_meaningful_action_success_proof(proof, action=action)
    )


def _pending_action_obligation_notices(
    *,
    ticket: dict[str, Any],
    answer: str,
    language: str,
) -> tuple[str, ...]:
    """Build safe notices only for omitted topics with same-scope pending work."""
    raw_actions = ticket.get("runbookActions")
    actions = raw_actions if isinstance(raw_actions, list) else []
    pending_actions = [
        action
        for raw_action in actions
        if (
            (action := _record_from(raw_action))
            and _string_from(action.get("status")).lower().replace("-", "_") == "pending_approval"
        )
    ]
    pending_concern_ids = {
        concern_id
        for action in pending_actions
        if (concern_id := _string_from(action.get("concernId") or action.get("concern_id")))
    }
    notices: list[str] = []
    seen_subjects: set[frozenset[str]] = set()
    raw_concerns = ticket.get("concerns")
    concerns = raw_concerns if isinstance(raw_concerns, list) else []
    human_review_concern_ids = {
        concern_id
        for raw_concern in concerns
        if (
            (concern := _record_from(raw_concern))
            and _concern_requires_human_review(concern)
            and (concern_id := _string_from(concern.get("id") or concern.get("concernId") or concern.get("concern_id")))
        )
    }
    review_concern_ids = pending_concern_ids | human_review_concern_ids
    if not review_concern_ids:
        return ()

    def append_notice_for_question(
        question: str,
        concern_actions: list[dict[str, Any]],
        concern_id: str,
    ) -> None:
        remaining_question = remaining_action_obligation_text(
            runbook_actions=concern_actions,
            expected_action_text=question,
        )
        if not remaining_question:
            return
        if has_success_backed_action_claim(
            answer=answer,
            runbook_actions=concern_actions,
            expected_action_text=remaining_question,
        ):
            return
        if _same_concern_tool_temporal_fact_matches(
            ticket=ticket,
            concern_id=concern_id,
            question=remaining_question,
            answer=answer,
        ):
            return
        result_notice = (
            _english_action_result_pending_notice(remaining_question)
            if language == "en"
            else None
        )
        if result_notice is not None:
            subject, notice = result_notice
        else:
            subject = _action_state_obligation_subject(
                remaining_question,
                language=language,
            )
            rendered_subject = (
                subject[:1].upper() + subject[1:]
                if language == "en"
                else subject
            )
            notice = _ACTION_STATE_PENDING_NOTICES[language].format(
                subject=rendered_subject,
            )
        subject_tokens = _action_state_subject_tokens(subject)
        if (
            not subject_tokens
            or subject_tokens in seen_subjects
            or notice.casefold() in answer.casefold()
            or (
                _answer_mentions_subject_without_positive_action_claim(
                    answer,
                    subject_tokens,
                )
                and not (language == "en" and _answer_uses_pending_confirmation_gerund(answer, subject))
            )
        ):
            return
        seen_subjects.add(subject_tokens)
        notices.append(notice)

    for raw_concern in concerns:
        concern = _record_from(raw_concern)
        concern_id = _string_from(concern.get("id") or concern.get("concernId") or concern.get("concern_id"))
        if concern.get("matched") is not True or concern_id not in review_concern_ids:
            continue
        raw_obligations = concern.get("answerObligations")
        if not isinstance(raw_obligations, list):
            continue
        for raw_obligation in raw_obligations[:10]:
            obligation = _record_from(raw_obligation)
            question = _string_from(
                obligation.get("question")
                or obligation.get("text")
                or (raw_obligation if isinstance(raw_obligation, str) else "")
            )
            concern_actions = [
                action
                for action in actions
                if _string_from(action.get("concernId") or action.get("concern_id")) == concern_id
            ]
            for action_question in action_obligation_parts(question):
                append_notice_for_question(action_question, concern_actions, concern_id)
    return tuple(notices)


def _separate_pending_action_token_forms(token: str) -> frozenset[str]:
    """Return bounded English inflections for action-label matching."""

    forms = {token}
    if len(token) < 3:
        return frozenset(forms)
    if token.endswith("e"):
        forms.update({f"{token}d", f"{token[:-1]}ing"})
    elif token.endswith("y") and token[-2:-1] not in "aeiou":
        forms.update({f"{token[:-1]}ied", f"{token}ing"})
    else:
        forms.update({f"{token}ed", f"{token}ing"})
        if token.endswith(("g", "l", "m", "p", "t")):
            forms.update({f"{token}{token[-1]}ed", f"{token}{token[-1]}ing"})
    return frozenset(forms)


def _separate_pending_action_tokens(value: str) -> tuple[str, ...]:
    normalized = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|[_-]+",
        " ",
        value,
    )
    return tuple(
        token
        for raw_token in _SEPARATE_PENDING_ACTION_TOKEN_RE.findall(normalized.casefold())
        if (token := _ACTION_STATE_SUBJECT_TOKEN_ALIASES.get(raw_token, raw_token))
        not in _SEPARATE_PENDING_ACTION_TOKEN_STOP_WORDS
    )


def _answer_unit_mentions_pending_action(unit: str, action: dict[str, Any]) -> bool:
    """Require same-sentence action identity plus an explicit pending state."""

    if _SEPARATE_PENDING_ACTION_STATE_RE.search(unit) is None:
        return False
    unit_tokens = frozenset(_separate_pending_action_tokens(unit))
    for value in (
        _string_from(action.get("label")),
        _string_from(action.get("name")),
    ):
        expected_tokens = _separate_pending_action_tokens(value)
        if expected_tokens and all(
            unit_tokens.intersection(_separate_pending_action_token_forms(token))
            for token in expected_tokens
        ):
            return True
    return False


def _separate_pending_action_notices(
    *,
    ticket: dict[str, Any],
    answer: str,
    language: str,
    customer_request: str,
) -> tuple[str, ...]:
    """Name each action when one concern has several approval-gated actions."""

    if len(action_obligation_parts(customer_request)) < 2:
        return ()

    raw_actions = ticket.get("runbookActions")
    actions = raw_actions if isinstance(raw_actions, list) else []
    by_concern: dict[str, list[dict[str, Any]]] = {}
    for raw_action in actions:
        action = _record_from(raw_action)
        concern_id = _string_from(action.get("concernId") or action.get("concern_id"))
        if (
            not concern_id
            or _string_from(action.get("status")).lower().replace("-", "_") != "pending_approval"
        ):
            continue
        by_concern.setdefault(concern_id, []).append(action)

    answer_units = tuple(
        match.group(0).strip()
        for match in re.finditer(r"[^.!?\n]+(?:[.!?]+|(?=\n)|$)", answer)
        if match.group(0).strip()
    )
    notices: list[str] = []
    for concern_actions in by_concern.values():
        if len(concern_actions) < 2:
            continue
        individually_acknowledged: set[int] = set()
        for unit in answer_units:
            matching_indexes = {
                index
                for index, action in enumerate(concern_actions)
                if _answer_unit_mentions_pending_action(unit, action)
            }
            if len(matching_indexes) == 1:
                individually_acknowledged.update(matching_indexes)
        for index, action in enumerate(concern_actions):
            if index in individually_acknowledged:
                continue
            label = re.sub(
                r"\s+",
                " ",
                _string_from(action.get("label") or action.get("name") or "pending action"),
            ).strip(" \t\r\n.,;:!?\"'“”‘’")[:160]
            if not label:
                continue
            notice = _SEPARATE_PENDING_ACTION_NOTICES[language].format(label=label)
            if notice.casefold() not in answer.casefold() and notice not in notices:
                notices.append(notice)
    return tuple(notices)


_ENGLISH_DEPENDENT_ACTION_FRAGMENT_RE = re.compile(
    r"^to\s+(?:assess|confirm|verify|check|review|process|update|escalate|investigate|"
    r"open|submit|arrange|schedule)\b[^,;:!?]{0,180}[.!?]*$",
    re.IGNORECASE,
)
_ENGLISH_DEPENDENT_ACTION_FRAGMENT_START_RE = re.compile(
    r"To\s+(?:assess|confirm|verify|check|review|process|update|escalate|investigate|"
    r"open|submit|arrange|schedule)\b",
)
_ACTION_REPAIR_NONTERMINAL_ABBREVIATIONS = frozenset(
    {
        "a.g",
        "co",
        "corp",
        "dr",
        "e.k",
        "e.v",
        "inc",
        "jr",
        "ltd",
        "mr",
        "mrs",
        "ms",
        "prof",
        "sr",
        "u.s",
        "u.s.a",
    }
)


_ENGLISH_FINITE_PREDICATE_RE = re.compile(
    r"\b(?:am|are|is|was|were|can|cannot|can't|could|do|does|did|have|has|had|"
    r"applies|continues|covers|ends|happens|includes|may|might|must|need|needs|"
    r"occurs|remain|remains|require|requires|serves|shall|should|starts|will|"
    r"would)\b",
    re.IGNORECASE,
)
_ENGLISH_LIKELY_SENTENCE_OPENER_RE = re.compile(r"(?:A|An|I|It|Our|That|The|These|They|This|Those|We|You|Your)\b")
_ENGLISH_PROCESS_FRAGMENT_SUFFIX_RE = re.compile(
    r"(?:^|(?<=[.!?])[ \t]+)"
    r"(?P<fragment>[A-Za-z][^.!?\n]{0,180}\bas part of (?:this|the) process\b[.!?]*)",
    re.IGNORECASE,
)
_ENGLISH_SINGULAR_ACTION_GERUND_PLURAL_PENDING_RE = re.compile(
    r"(?P<prefix>^|(?<=[.!?])\s+)"
    r"(?P<subject>(?:assessing|confirming|verifying|checking|reviewing|processing|"
    r"updating|escalating|investigating|opening|submitting|arranging|scheduling|"
    r"pausing|stopping|recording|logging|cancelling|canceling|terminating|refunding|"
    r"issuing|notifying|replacing|reshipping|dispatching|creating|revoking)\b"
    r"[^,;.!?\n]{0,180}?)\s+are\s+(?:all|both)\s+"
    r"(?P<state>(?:still\s+)?(?:pending|awaiting)\b)",
    re.IGNORECASE,
)


def _dependent_action_fragment_end(text: str, start: int) -> int | None:
    """Find one fragment end without treating initials as sentence breaks."""

    limit = min(len(text), start + 240)
    index = start
    while index < limit:
        character = text[index]
        if character == "\n":
            return index
        if character not in ".!?":
            index += 1
            continue
        end = index + 1
        while end < len(text) and text[end] in ".!?":
            end += 1
        if end >= len(text) or text[end] == "\n":
            return end
        next_index = end
        while next_index < len(text) and text[next_index] in " \t":
            next_index += 1
        has_space = next_index > end
        if next_index >= len(text) or text[next_index] == "\n":
            return end
        if character in "!?":
            return end
        if not has_space:
            continues_initialism = (
                text[next_index].isupper() and next_index + 1 < len(text) and text[next_index + 1] == "."
            )
            if text[next_index].isupper() and not continues_initialism:
                return end
            index = end
            continue
        if not text[next_index].isupper():
            index = end
            continue

        token_match = re.search(r"([A-Za-z]+(?:\.[A-Za-z]+)*)$", text[:index])
        token = token_match.group(1).casefold() if token_match else ""
        token_is_abbreviation = token in _ACTION_REPAIR_NONTERMINAL_ABBREVIATIONS or "." in token
        if token_is_abbreviation:
            following = text[next_index : min(len(text), next_index + 180)]
            if _ENGLISH_LIKELY_SENTENCE_OPENER_RE.match(following) and _ENGLISH_FINITE_PREDICATE_RE.search(following):
                return end
            index = end
            continue
        return end
    return None


def _dependent_action_fragment_spans(text: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    for match in _ENGLISH_DEPENDENT_ACTION_FRAGMENT_START_RE.finditer(text):
        start = match.start()
        if start:
            if not text[start - 1].isspace():
                continue
            prefix = text[:start].rstrip(" \t")
            if prefix and prefix[-1] not in ".!?\n":
                continue
        end = _dependent_action_fragment_end(text, start)
        if end is None:
            continue
        fragment = text[start:end].strip()
        if _ENGLISH_DEPENDENT_ACTION_FRAGMENT_RE.fullmatch(fragment):
            spans.append((start, end))
    return tuple(spans)


def _clean_action_repair_artifacts(answer: str, *, language: str) -> str:
    """Remove bounded dependent fragments and restore sentence separators.

    Action repair can retain a safe local clause after deleting an unsafe claim.
    A retained infinitive or noun fragment is not independently customer-ready,
    even though it is harmless to the action-state guard. Keep this cleanup
    intentionally narrow and English-only; grounding remains authoritative.
    """

    cleaned = answer.strip()
    if language == "en" and cleaned:
        cursor = 0
        parts: list[str] = []
        for start, end in _dependent_action_fragment_spans(cleaned):
            parts.append(cleaned[cursor:start])
            cursor = end
        if parts:
            parts.append(cleaned[cursor:])
            cleaned = "".join(parts).strip()
        cleaned = _ENGLISH_SINGULAR_ACTION_GERUND_PLURAL_PENDING_RE.sub(
            lambda match: (
                match.group(0)
                if re.search(r"\b(?:and|or)\b", match.group("subject"), re.IGNORECASE)
                else f'{match.group("prefix")}{match.group("subject")} is {match.group("state")}'
            ),
            cleaned,
        )
        cursor = 0
        parts = []
        for process_fragment in _ENGLISH_PROCESS_FRAGMENT_SUFFIX_RE.finditer(cleaned):
            if _ENGLISH_FINITE_PREDICATE_RE.search(process_fragment.group("fragment")):
                continue
            parts.append(cleaned[cursor : process_fragment.start()])
            cursor = process_fragment.end()
        if parts:
            parts.append(cleaned[cursor:])
            cleaned = "".join(parts).strip()

    cleaned = re.sub(
        r"(\b[a-z]{2,}|\d+)([.!?])(?=[A-ZÀ-ÖØ-Þ])",
        r"\1\2 ",
        cleaned,
    )
    cleaned = re.sub(
        r"\b([A-Z][A-Za-zÀ-ÖØ-öø-ÿ&'-]{1,50}\s+"
        r"(?:SA|AG|GmbH|Inc|Ltd|LLC|PLC|Corp|Sarl|SARL|SAS|BV|NV))([.!?])"
        r"(?=(?:A|An|I|It|Our|That|The|These|They|This|Those|We|You|Your)\b)",
        r"\1\2 ",
        cleaned,
    )
    cleaned = re.sub(
        r"((?:\b[A-Za-z]\.){2,})(?=[A-Z][a-z])",
        r"\1 ",
        cleaned,
    )
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n[ \t]+\n", "\n\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def repair_issue_automation_answer_action_state(
    *,
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
    answer: str,
) -> str:
    """Repair action claims and omitted action-state answers from durable state."""
    ticket = _automatic_ticket_context(issue)
    language = _latest_customer_language(messages)
    answer = _canonicalize_tool_backed_timestamps(ticket, answer)
    message_context = _automatic_message_context(messages, limit=1)
    customer_request = message_context[-1]["body"] if message_context else ""
    raw_actions = ticket.get("runbookActions")
    guard_actions = list(raw_actions) if isinstance(raw_actions, list) else []
    if not any(
        _string_from(_record_from(action).get("status")).lower().replace("-", "_") == "pending_approval"
        for action in guard_actions
    ):
        raw_concerns = ticket.get("concerns")
        concerns = raw_concerns if isinstance(raw_concerns, list) else []
        if any(
            _concern_requires_human_review(concern)
            for raw_concern in concerns
            if (concern := _record_from(raw_concern))
        ):
            # The concern state proves that human review is required even when
            # a generic triage action is not yet present in this issue snapshot.
            # This synthetic guard input is not surfaced as action evidence.
            guard_actions.append(
                {
                    "name": "human_review",
                    "label": "Human review",
                    "status": "pending_approval",
                }
            )
    repaired = repair_pending_action_claims(
        answer=answer,
        runbook_actions=guard_actions,
        tool_evidence=_automatic_tool_evidence_records(ticket),
        repair_notice=(
            "\n\n".join(
                _separate_pending_action_notices(
                    ticket=ticket,
                    answer="",
                    language=language,
                    customer_request=customer_request,
                )
            )
            or _PENDING_ACTION_REPAIR_NOTICES[language]
        ),
    )
    repaired = _clean_action_repair_artifacts(repaired, language=language)
    repaired = _append_required_secret_delivery_guidance(
        ticket=ticket,
        answer=repaired,
        language=language,
    )
    notices = (*_pending_action_obligation_notices(
        ticket=ticket,
        answer=repaired,
        language=language,
    ), *_separate_pending_action_notices(
        ticket=ticket,
        answer=repaired,
        language=language,
        customer_request=customer_request,
    ))
    clean_answer = repaired.rstrip()
    candidate = (
        "\n\n".join((clean_answer, *notices))
        if notices and clean_answer
        else "\n\n".join(notices)
        if notices
        else clean_answer
    )
    candidate = _clean_action_repair_artifacts(candidate, language=language)
    # Notices are derived after the first repair pass, so make the exact final
    # customer text pass the same deterministic guard before grounding sees it.
    final_check = check_pending_action_claims(
        answer=candidate,
        runbook_actions=guard_actions,
        tool_evidence=_automatic_tool_evidence_records(ticket),
    )
    if not final_check.blocked:
        return candidate
    final_repair = repair_pending_action_claims(
        answer=candidate,
        runbook_actions=guard_actions,
        tool_evidence=_automatic_tool_evidence_records(ticket),
        repair_notice=_PENDING_ACTION_REPAIR_NOTICES[language],
    )
    return _clean_action_repair_artifacts(final_repair, language=language)


def _valid_tool_evidence_id(record: dict[str, Any], *, concern_id: str = "") -> str:
    """Validate a successful tool record against its exact enclosing scope."""
    name = _string_from(record.get("name"))
    evidence_id = _string_from(record.get("evidenceId"))
    if (
        name
        and evidence_id == _tool_evidence_id(name, concern_id=concern_id)
        and _string_from(record.get("status")).lower() == "success"
        and isinstance(record.get("responseFacts"), (dict, list))
        and record.get("responseFacts")
    ):
        return evidence_id
    return ""


def _automatic_tool_evidence_ids(ticket: dict[str, Any]) -> tuple[str, ...]:
    """Return only exact, successful tool evidence IDs surfaced in ticket context."""

    evidence_ids: list[str] = []
    for concern_id, record in _automatic_tool_evidence_records_with_scope(ticket):
        if evidence_id := _valid_tool_evidence_id(record, concern_id=concern_id):
            evidence_ids.append(evidence_id)
    return tuple(dict.fromkeys(evidence_ids))


def _scoped_tool_evidence_concerns(ticket: dict[str, Any]) -> dict[str, str]:
    """Map each exact modern tool evidence ID to its enclosing concern."""
    scoped: dict[str, str] = {}
    for concern_id, record in _automatic_tool_evidence_records_with_scope(ticket):
        if not concern_id:
            continue
        if evidence_id := _valid_tool_evidence_id(record, concern_id=concern_id):
            scoped[evidence_id] = concern_id
    return scoped


def _successful_action_evidence_ids_by_concern(
    ticket: dict[str, Any],
) -> dict[str, frozenset[str]]:
    """Index exact successful tool/action evidence under its originating concern."""
    evidence_by_concern: dict[str, set[str]] = {}
    for evidence_id, (concern_id, _record) in _successful_action_evidence_records_by_id(ticket).items():
        evidence_by_concern.setdefault(concern_id, set()).add(evidence_id)
    return {concern_id: frozenset(evidence_ids) for concern_id, evidence_ids in evidence_by_concern.items()}


def _successful_action_evidence_records_by_id(
    ticket: dict[str, Any],
) -> dict[str, tuple[str, dict[str, Any]]]:
    """Index every durable action/tool record by its exact scoped evidence ID."""
    evidence_records: dict[str, tuple[str, dict[str, Any]]] = {}
    concerns = ticket.get("concerns")
    if isinstance(concerns, list):
        for raw_concern in concerns:
            concern = _record_from(raw_concern)
            concern_id = _string_from(concern.get("id") or concern.get("concernId") or concern.get("concern_id"))
            raw_evidence = concern.get("toolEvidence")
            if not concern_id or not isinstance(raw_evidence, list):
                continue
            for raw_record in raw_evidence:
                record = _record_from(raw_record)
                if evidence_id := _valid_tool_evidence_id(
                    record,
                    concern_id=concern_id,
                ):
                    evidence_records[evidence_id] = (concern_id, record)

    raw_actions = ticket.get("runbookActions")
    if isinstance(raw_actions, list):
        for raw_action in raw_actions:
            action = _record_from(raw_action)
            concern_id = _string_from(action.get("concernId") or action.get("concern_id"))
            evidence_id = _string_from(action.get("evidenceId"))
            if concern_id and _is_durable_successful_runbook_action(action):
                evidence_records[evidence_id] = (concern_id, action)

    return evidence_records


def _matching_successful_action_evidence_ids(
    evidence_records: dict[str, tuple[str, dict[str, Any]]],
    *,
    concern_id: str,
    expected_action_text: str,
) -> frozenset[str]:
    """Return same-concern evidence whose action and target match one obligation."""
    return frozenset(
        evidence_id
        for evidence_id, (record_concern_id, record) in evidence_records.items()
        if record_concern_id == concern_id and action_record_matches_expected_text(record, expected_action_text)
    )


def _scoped_grounding_evidence_concerns(
    ticket: dict[str, Any],
    *,
    successful_evidence_by_concern: dict[str, frozenset[str]] | None = None,
) -> dict[str, frozenset[str]]:
    """Index every concern container and exact successful tool/action ID by scope."""
    scoped: dict[str, set[str]] = {}
    raw_concerns = ticket.get("concerns")
    if isinstance(raw_concerns, list):
        for raw_concern in raw_concerns:
            concern = _record_from(raw_concern)
            concern_id = _string_from(concern.get("id") or concern.get("concernId") or concern.get("concern_id"))
            if concern_id:
                scoped.setdefault(
                    _concern_grounding_evidence_id(concern_id),
                    set(),
                ).add(concern_id)

    evidence_by_concern = (
        successful_evidence_by_concern
        if successful_evidence_by_concern is not None
        else _successful_action_evidence_ids_by_concern(ticket)
    )
    for concern_id, evidence_ids in evidence_by_concern.items():
        for evidence_id in evidence_ids:
            scoped.setdefault(evidence_id, set()).add(concern_id)
    return {evidence_id: frozenset(concern_ids) for evidence_id, concern_ids in scoped.items()}


def grounding_context_snapshots(
    *,
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
    account_context: dict[str, Any] | None = None,
    conversation_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Bind automatic answers to the non-knowledge context seen by the evaluator."""
    ticket = _automatic_ticket_context(issue)
    global_ticket_evidence = _global_grounding_ticket_evidence(ticket)
    scoped_ticket_evidence = _scoped_grounding_ticket_evidence(ticket)
    conversation = _automatic_conversation_context(conversation_context)
    account = _automatic_account_context(
        account_context,
        issue_id=_string_from(issue.get("id")),
        conversation_context=conversation_context,
    )

    payloads: list[tuple[str, Any]] = [
        ("ticket", global_ticket_evidence),
        ("ticket:scoped", scoped_ticket_evidence),
        ("messages", _automatic_message_context(messages)),
        ("account", account),
        ("conversation", conversation),
    ]
    snapshots: list[dict[str, Any]] = []
    for context_id, payload in payloads:
        if context_id != "ticket" and not payload:
            continue
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        snapshots.append(
            {
                "id": context_id,
                "contextSha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            }
        )
    safety_assessment = _issue_safety_assessment(issue, messages)
    if safety_assessment.active:
        snapshots.append(safety_assessment.snapshot())
    return tuple(snapshots)


_GROUNDING_SENTENCE_RE = re.compile(r".+?(?:[.!?]+[\"')\]]*(?=\s|$)|$)")
_GROUNDING_MAX_UNIT_CHARS = 500
_GROUNDING_MAX_UNITS = 50


def _grounding_answer_units(answer: str) -> tuple[dict[str, Any], ...]:
    """Create exhaustive immutable spans; every non-whitespace answer byte is covered."""
    units: list[dict[str, Any]] = []
    line_offset = 0
    for raw_line in answer.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        content_start = len(line) - len(line.lstrip())
        content_end = len(line.rstrip())
        if content_start < content_end:
            content = line[content_start:content_end]
            for match in _GROUNDING_SENTENCE_RE.finditer(content):
                raw_segment = match.group(0)
                left_trim = len(raw_segment) - len(raw_segment.lstrip())
                right_trim = len(raw_segment.rstrip())
                segment_start = line_offset + content_start + match.start() + left_trim
                segment_end = line_offset + content_start + match.start() + right_trim
                cursor = segment_start
                while cursor < segment_end:
                    while cursor < segment_end and answer[cursor].isspace():
                        cursor += 1
                    if cursor >= segment_end:
                        break
                    chunk_end = min(cursor + _GROUNDING_MAX_UNIT_CHARS, segment_end)
                    if chunk_end < segment_end:
                        whitespace_break = max(
                            answer.rfind(" ", cursor, chunk_end + 1),
                            answer.rfind("\t", cursor, chunk_end + 1),
                        )
                        if whitespace_break >= cursor + (_GROUNDING_MAX_UNIT_CHARS // 2):
                            chunk_end = whitespace_break
                    while chunk_end > cursor and answer[chunk_end - 1].isspace():
                        chunk_end -= 1
                    if chunk_end <= cursor:
                        chunk_end = min(cursor + _GROUNDING_MAX_UNIT_CHARS, segment_end)
                    text = answer[cursor:chunk_end]
                    units.append(
                        {
                            "id": f"u{len(units) + 1:03d}",
                            "start": cursor,
                            "end": chunk_end,
                            "text": text,
                            "sha256": grounding_text_sha256(text),
                        }
                    )
                    cursor = chunk_end
        line_offset += len(raw_line)

    covered = [False] * len(answer)
    for unit in units:
        for index in range(int(unit["start"]), int(unit["end"])):
            covered[index] = True
    if any(not char.isspace() and not covered[index] for index, char in enumerate(answer)):
        return ()
    return tuple(units)


def _citation_supports_high_confidence(article: dict[str, Any]) -> bool:
    return (
        _string_from(article.get("status")).lower() == "published"
        and _string_from(article.get("reviewStatus")).lower() == "reviewed"
        and _string_from(article.get("freshnessStatus")).lower() == "fresh"
        and not bool(article.get("needsReview"))
    )


def draft_issue_agent_answer(
    *,
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
    question: str,
    articles: list[dict[str, Any]],
    prior_agent_runs: list[dict[str, Any]],
    tenant_id: str | None,
    project_id: str,
    fallback_answer: str,
    fallback_confidence: str,
    account_context: dict[str, Any] | None = None,
    conversation_context: dict[str, Any] | None = None,
    on_late_usage: Callable[[list[dict[str, Any]]], None] | None = None,
) -> IssueAgentDraft:
    """Run the isolated knowledge agent, falling back offline on any failure."""
    safety_assessment = _issue_safety_assessment(issue, messages)
    slot_semaphore = _KNOWLEDGE_AGENT_SLOTS
    if not slot_semaphore.acquire(blocking=False):
        _, review_reason = _safety_review_state(
            safety_assessment,
            model_requires_human=True,
            model_reason="Knowledge agent capacity is temporarily exhausted.",
        )
        return IssueAgentDraft(
            answer=_safety_aware_failure_answer(
                assessment=safety_assessment,
                ordinary_answer=_knowledge_failure_answer(question, messages),
                messages=messages,
            ),
            confidence="low",
            generation_mode="deterministic_fallback",
            error="Knowledge agent capacity is temporarily exhausted",
            requires_human=True,
            requires_human_reason=review_reason,
        )
    workspace: KnowledgeWorkspace | None = None
    deferred_slot_release = False
    parent_usage_collector: Any = None
    invocation_usage = _AgentInvocationUsage()
    try:
        from automail.core.config import read_config
        from automail.llm import create_llm, resolve_effective_config
        from automail.llm.usage import current_collector, llm_stage, record_usage_from_result

        config = resolve_effective_config(read_config(), tenant_id, project_id)
        llm = create_llm(config, timeout=30, max_retries=0, temperature=0.2)
        usage_context = getattr(llm, "_mantly_usage_context", None)
        clean_question = (question.strip() or "Prepare the best support answer and next step.")[:4_000]
        request_items = _knowledge_request_items(clean_question)
        workspace = KnowledgeWorkspace(
            ticket=_with_safety_prompt_context(
                _ticket_context(issue),
                safety_assessment,
            ),
            messages=_message_context(messages),
            account=_automatic_account_context(
                account_context,
                issue_id=_string_from(issue.get("id")),
                conversation_context=conversation_context,
            ),
            conversation=_automatic_conversation_context(conversation_context),
            prior_agent_answers=_agent_chat_context(prior_agent_runs),
            question=clean_question,
            articles=articles,
        )

        @tool
        def knowledge_bash(command: str) -> str:
            """Search and read the isolated support workspace with safe Bash commands."""
            return workspace.run(command)

        agent = create_agent(
            model=llm,
            tools=[knowledge_bash],
            system_prompt=_SYSTEM_PROMPT,
            response_format=ToolStrategy(KnowledgeAgentOutput),
            middleware=[
                ModelCallLimitMiddleware(
                    run_limit=KNOWLEDGE_AGENT_MODEL_CALL_LIMIT,
                    exit_behavior="error",
                ),
                ToolCallLimitMiddleware(
                    tool_name="knowledge_bash",
                    run_limit=KNOWLEDGE_AGENT_TOOL_CALL_LIMIT,
                    exit_behavior="error",
                ),
            ],
            name="ticket_knowledge_agent",
        )
        user_prompt = _USER_TEMPLATE.format(
            question=clean_question,
            request_items=_json(request_items),
        )
        invoke_config = {
            "recursion_limit": 48,
            "run_name": "ticket_knowledge_agent",
            "tags": ["mantly", "support", "knowledge-agent"],
            "metadata": {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "issue_id": _string_from(issue.get("id")),
                "source": "support.issue_agent",
            },
        }

        def invoke_agent() -> dict[str, Any]:
            with llm_stage("issue_agent_answer"):
                response = agent.invoke(
                    {"messages": [{"role": "user", "content": user_prompt}]},
                    config=invoke_config,
                )
                record_usage_from_result(response, usage_context)
            return response

        parent_usage_collector = current_collector()
        future = _KNOWLEDGE_AGENT_EXECUTOR.submit(
            copy_context().run,
            invocation_usage.run,
            invoke_agent,
        )
        try:
            response = future.result(timeout=KNOWLEDGE_AGENT_DEADLINE_SECONDS)
        except FutureTimeoutError as exc:
            deferred_slot_release = True
            future.add_done_callback(
                lambda _future: _finish_timed_out_agent(
                    slot_semaphore=slot_semaphore,
                    invocation_usage=invocation_usage,
                    on_late_usage=on_late_usage,
                )
            )
            raise TimeoutError("Knowledge agent deadline exceeded") from exc
        structured = response.get("structured_response") if isinstance(response, dict) else None
        if not isinstance(structured, KnowledgeAgentOutput):
            raise ValueError("Knowledge agent returned no structured response")
        if not workspace.read_paths:
            raise ValueError("Knowledge agent did not inspect the workspace")
        citation_ids = workspace.validated_citation_ids(
            structured.citation_ids,
            structured.citation_paths,
        )
        citation_evidence = workspace.validated_citation_evidence(
            structured.citation_ids,
            structured.citation_paths,
        )
        answer = _clean_answer(
            structured.answer,
            messages=messages,
            internal_citation_ids=citation_ids,
        )
        if not answer:
            raise ValueError("Issue agent returned an empty answer")
        answer, uncovered_request_items = _repair_knowledge_request_item_coverage(
            answer=answer,
            question=clean_question,
            items=request_items,
            assessments=structured.request_item_assessments,
            internal_citation_ids=citation_ids,
        )
        missing_safety = missing_lithium_battery_safety_guidance(answer) if safety_assessment.active else ()
        if missing_safety:
            raise ValueError(SAFETY_GUIDANCE_MISSING_REASON_CODE + ": " + ", ".join(missing_safety))
        truncated_citation_ids = workspace.truncated_citation_ids(citation_ids)
        confidence = structured.confidence
        articles_by_id = {
            _string_from(article.get("id")): article for article in articles if _string_from(article.get("id"))
        }
        if confidence == "high" and (
            not citation_ids
            or truncated_citation_ids
            or any(
                not _citation_supports_high_confidence(articles_by_id.get(article_id, {}))
                for article_id in citation_ids
            )
        ):
            confidence = "medium"
        missing_information = [item.strip()[:500] for item in structured.missing_information[:10] if item.strip()]
        missing_information.extend(
            f"Unresolved request item: {item['question']}"[:500]
            for item in uncovered_request_items
        )
        if truncated_citation_ids:
            missing_information.append(
                "Full source content requires human review: " + ", ".join(truncated_citation_ids)
            )
        model_requires_human, model_reason = _safety_review_state(
            safety_assessment,
            model_requires_human=bool(structured.requires_human or uncovered_request_items),
            model_reason=" ".join(
                part
                for part in (
                    structured.requires_human_reason.strip(),
                    (
                        "One or more direct agent questions lacked item-specific answer proof; "
                        "the runtime marked each omitted item unknown."
                        if uncovered_request_items
                        else ""
                    ),
                )
                if part
            ),
        )
        (
            covered_concern_ids,
            covered_obligation_ids,
            requires_human,
            requires_human_reason,
        ) = _validated_draft_coverage(
            issue,
            structured.covered_concern_ids,
            structured.covered_obligation_ids,
            model_requires_human=model_requires_human,
            model_reason=model_reason,
        )
        return IssueAgentDraft(
            answer=answer,
            confidence=confidence,
            generation_mode="knowledge_agent",
            citation_ids=citation_ids,
            citation_evidence=citation_evidence,
            missing_information=tuple(dict.fromkeys(missing_information))[:10],
            response_attachments=_validated_response_attachments(
                issue,
                structured.response_attachments,
            ),
            covered_concern_ids=covered_concern_ids,
            covered_obligation_ids=covered_obligation_ids,
            requires_human=requires_human,
            requires_human_reason=requires_human_reason,
            tool_calls=workspace.tool_calls,
        )
    except Exception as exc:
        logger.info("Falling back to deterministic issue agent answer: %s", exc)
        _, review_reason = _safety_review_state(
            safety_assessment,
            model_requires_human=True,
            model_reason="Knowledge answer generation failed.",
        )
        (
            covered_concern_ids,
            covered_obligation_ids,
            requires_human,
            requires_human_reason,
        ) = _validated_draft_coverage(
            issue,
            [],
            [],
            model_requires_human=True,
            model_reason=review_reason,
        )
        return IssueAgentDraft(
            answer=_safety_aware_failure_answer(
                assessment=safety_assessment,
                ordinary_answer=_knowledge_failure_answer(question, messages),
                messages=messages,
            ),
            confidence="low",
            generation_mode="deterministic_fallback",
            error=str(exc)[:1_000],
            covered_concern_ids=covered_concern_ids,
            covered_obligation_ids=covered_obligation_ids,
            requires_human=requires_human,
            requires_human_reason=requires_human_reason,
            tool_calls=workspace.tool_calls if workspace else (),
        )
    finally:
        if not deferred_slot_release:
            invocation_usage.merge_into(parent_usage_collector)
            slot_semaphore.release()


def draft_issue_automation_answer(
    *,
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
    question: str,
    articles: list[dict[str, Any]],
    prior_agent_runs: list[dict[str, Any]],
    tenant_id: str | None,
    project_id: str,
    fallback_answer: str,
    fallback_confidence: str,
    account_context: dict[str, Any] | None = None,
    conversation_context: dict[str, Any] | None = None,
    coverage_repair_answer: str = "",
    coverage_repair_obligations: tuple[str, ...] = (),
    grounding_repair_unsupported_claims: tuple[str, ...] = (),
    grounding_repair_contradictions: tuple[str, ...] = (),
    on_late_usage: Callable[[list[dict[str, Any]]], None] | None = None,
) -> IssueAgentDraft:
    """Preserve the bounded one-shot generator for automatic/shared retrieval paths."""
    safety_assessment = _issue_safety_assessment(issue, messages)
    slot_semaphore = _AUTOMATION_AGENT_SLOTS
    if not slot_semaphore.acquire(
        blocking=True,
        timeout=AUTOMATION_AGENT_SLOT_WAIT_SECONDS,
    ):
        _, review_reason = _safety_review_state(
            safety_assessment,
            model_requires_human=True,
            model_reason="Automatic answer capacity is temporarily exhausted.",
        )
        return IssueAgentDraft(
            answer=_safety_aware_failure_answer(
                assessment=safety_assessment,
                ordinary_answer=fallback_answer,
                messages=messages,
            ),
            confidence=fallback_confidence,
            generation_mode="deterministic_fallback",
            error="Automatic answer capacity is temporarily exhausted",
            requires_human=True,
            requires_human_reason=review_reason,
        )
    deferred_slot_release = False
    parent_usage_collector: Any = None
    invocation_usage = _AgentInvocationUsage()
    try:
        from automail.core.config import read_config
        from automail.llm import create_llm, resolve_effective_config
        from automail.llm.usage import current_collector, llm_stage, record_usage_from_result

        config = resolve_effective_config(read_config(), tenant_id, project_id)
        llm = create_llm(config, timeout=45, max_retries=0, temperature=0.2)
        usage_context = getattr(llm, "_mantly_usage_context", None)
        reply_language = _latest_customer_language(messages)
        reply_language_name = _LANGUAGE_NAMES[reply_language]
        ticket_context = _with_safety_prompt_context(
            _automatic_ticket_context(issue),
            safety_assessment,
        )
        allowed_business_identifiers = _allowed_business_identifiers(
            messages=messages,
            ticket=ticket_context,
            articles=articles,
        )
        user_prompt = _AUTOMATION_USER_TEMPLATE.format(
            ticket=_json(ticket_context),
            account_intelligence=_json(
                _automatic_account_context(
                    account_context,
                    issue_id=_string_from(issue.get("id")),
                    conversation_context=conversation_context,
                )
            ),
            conversation_context=_json(_automatic_conversation_context(conversation_context)),
            messages=_json(_automatic_message_context(messages)),
            reply_language=reply_language_name,
            knowledge_articles=_json(_article_context(articles)),
            prior_agent_answers=_json(_agent_chat_context(prior_agent_runs)),
            question=(question.strip() or "Prepare the best support answer and next step.")[:4_000],
        )
        clean_repair_obligations = tuple(
            dict.fromkeys(
                obligation.strip()[:500]
                for obligation in coverage_repair_obligations[:20]
                if obligation.strip()
            )
        )
        clean_unsupported_claims = tuple(
            dict.fromkeys(
                claim.strip()[:500]
                for claim in grounding_repair_unsupported_claims[:20]
                if claim.strip()
            )
        )
        clean_contradictions = tuple(
            dict.fromkeys(
                contradiction.strip()[:500]
                for contradiction in grounding_repair_contradictions[:20]
                if contradiction.strip()
            )
        )
        if clean_unsupported_claims or clean_contradictions:
            user_prompt += "\n\n" + _AUTOMATION_GROUNDING_REPAIR_TEMPLATE.format(
                previous_answer=_json(coverage_repair_answer.strip()[:12_000]),
                unsupported_claims=_json(clean_unsupported_claims),
                contradictions=_json(clean_contradictions),
                uncovered_obligations=_json(clean_repair_obligations),
            )
        elif clean_repair_obligations:
            user_prompt += "\n\n" + _AUTOMATION_OBLIGATION_REPAIR_TEMPLATE.format(
                previous_answer=_json(coverage_repair_answer.strip()[:12_000]),
                uncovered_obligations=_json(clean_repair_obligations),
            )
        agent = create_agent(
            model=llm,
            tools=[],
            system_prompt=_AUTOMATION_SYSTEM_PROMPT,
            response_format=ToolStrategy(AutomationAnswerOutput),
            middleware=[ModelCallLimitMiddleware(run_limit=2, exit_behavior="error")],
            name="issue_automation_answer",
        )
        invoke_config = {
            "recursion_limit": 6,
            "run_name": "issue_automation_answer",
            "tags": ["mantly", "support", "automation-answer"],
            "metadata": {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "issue_id": _string_from(issue.get("id")),
                "source": "support.issue_automation",
            },
        }

        def invoke_agent() -> dict[str, Any]:
            with llm_stage("issue_automation_answer"):
                response = agent.invoke(
                    {"messages": [{"role": "user", "content": user_prompt}]},
                    config=invoke_config,
                )
                record_usage_from_result(response, usage_context)
                structured = response.get("structured_response") if isinstance(response, dict) else None
                first_answer = _string_from(getattr(structured, "answer", ""))
                correction_reasons: list[str] = []
                if first_answer and _detected_supported_language(first_answer) != reply_language:
                    correction_reasons.append(f"Rewrite the entire answer in {reply_language_name}.")
                pending_action_check = check_pending_action_claims(
                    answer=first_answer,
                    runbook_actions=ticket_context.get("runbookActions", []),
                    tool_evidence=_automatic_tool_evidence_records(ticket_context),
                )
                if pending_action_check.blocked:
                    correction_reasons.append(
                        "Remove every statement that says or promises a pending business action "
                        "has started, completed, or will definitely occur. Describe it only as "
                        "pending approval or conditional on review."
                    )
                unsupported_identifiers = _unsupported_business_identifiers(
                    first_answer,
                    allowed_identifiers=allowed_business_identifiers,
                )
                if unsupported_identifiers:
                    allowed_summary = ", ".join(allowed_business_identifiers[:20]) or "none"
                    correction_reasons.append(
                        "Remove or correct unsupported business identifiers: "
                        + ", ".join(unsupported_identifiers[:20])
                        + ". Use only exact identifiers present in trusted evidence: "
                        + allowed_summary
                        + "."
                    )
                missing_safety = (
                    missing_lithium_battery_safety_guidance(first_answer)
                    if first_answer and safety_assessment.active
                    else ()
                )
                if missing_safety:
                    correction_reasons.append(
                        "Add every required immediate damaged-lithium-battery safety instruction. "
                        "Missing policy elements: " + ", ".join(missing_safety) + "."
                    )
                if (
                    first_answer
                    and _required_secret_delivery_guidance(ticket_context)
                    and not _answer_has_complete_secret_delivery_guidance(first_answer)
                ):
                    correction_reasons.append(
                        "State all mandatory secret-delivery constraints explicitly: never repeat the secret, "
                        "never email the secret or its replacement, and use only the approved secure channel "
                        "for any replacement."
                    )
                if correction_reasons:
                    correction_prompt = (
                        f"{user_prompt}\n\n"
                        "## Correction Required\n"
                        + " ".join(correction_reasons)
                        + " Preserve the same evidence and coverage boundaries."
                    )
                    response = agent.invoke(
                        {"messages": [{"role": "user", "content": correction_prompt}]},
                        config=invoke_config,
                    )
                    record_usage_from_result(response, usage_context)
            return response

        parent_usage_collector = current_collector()
        future = _AUTOMATION_AGENT_EXECUTOR.submit(
            copy_context().run,
            invocation_usage.run,
            invoke_agent,
        )
        try:
            response = future.result(timeout=AUTOMATION_AGENT_DEADLINE_SECONDS)
        except FutureTimeoutError as exc:
            deferred_slot_release = True
            future.add_done_callback(
                lambda _future: _finish_timed_out_agent(
                    slot_semaphore=slot_semaphore,
                    invocation_usage=invocation_usage,
                    on_late_usage=on_late_usage,
                )
            )
            raise TimeoutError("Automatic answer deadline exceeded") from exc
        structured = response.get("structured_response") if isinstance(response, dict) else None
        if not isinstance(structured, AutomationAnswerOutput):
            raise ValueError("Issue automation returned no structured response")
        available_ids = {_string_from(article.get("id")) for article in articles if _string_from(article.get("id"))}
        citation_ids = tuple(
            dict.fromkeys(
                article_id
                for article_id in (_string_from(value) for value in structured.citation_ids)
                if article_id in available_ids
            )
        )
        answer = _clean_answer(
            structured.answer,
            messages=messages,
            internal_citation_ids=citation_ids,
        )
        if not answer:
            raise ValueError("Issue automation returned an empty answer")
        missing_safety = missing_lithium_battery_safety_guidance(answer) if safety_assessment.active else ()
        if missing_safety:
            raise ValueError(SAFETY_GUIDANCE_MISSING_REASON_CODE + ": " + ", ".join(missing_safety))
        if _detected_supported_language(answer) != reply_language:
            raise ValueError(f"Automatic answer language mismatch: expected {reply_language_name}")
        confidence = structured.confidence
        if confidence == "high" and not citation_ids:
            confidence = "medium"
        missing_information = tuple(
            dict.fromkeys(item.strip()[:500] for item in structured.missing_information[:10] if item.strip())
        )
        model_requires_human, model_reason = _safety_review_state(
            safety_assessment,
            model_requires_human=structured.requires_human,
            model_reason=structured.requires_human_reason,
        )
        (
            covered_concern_ids,
            covered_obligation_ids,
            requires_human,
            requires_human_reason,
        ) = _validated_draft_coverage(
            issue,
            structured.covered_concern_ids,
            structured.covered_obligation_ids,
            model_requires_human=model_requires_human,
            model_reason=model_reason,
        )
        return IssueAgentDraft(
            answer=answer,
            confidence=confidence,
            generation_mode="llm",
            citation_ids=citation_ids,
            missing_information=missing_information,
            response_attachments=_validated_response_attachments(
                issue,
                structured.response_attachments,
            ),
            covered_concern_ids=covered_concern_ids,
            covered_obligation_ids=covered_obligation_ids,
            requires_human=requires_human,
            requires_human_reason=requires_human_reason,
        )
    except Exception as exc:
        logger.info("Falling back to deterministic issue automation answer: %s", exc)
        _, review_reason = _safety_review_state(
            safety_assessment,
            model_requires_human=True,
            model_reason="Automatic answer generation failed.",
        )
        (
            covered_concern_ids,
            covered_obligation_ids,
            requires_human,
            requires_human_reason,
        ) = _validated_draft_coverage(
            issue,
            [],
            [],
            model_requires_human=True,
            model_reason=review_reason,
        )
        return IssueAgentDraft(
            answer=_safety_aware_failure_answer(
                assessment=safety_assessment,
                ordinary_answer=fallback_answer,
                messages=messages,
            ),
            confidence=fallback_confidence,
            generation_mode="deterministic_fallback",
            error=str(exc)[:1_000],
            covered_concern_ids=covered_concern_ids,
            covered_obligation_ids=covered_obligation_ids,
            requires_human=requires_human,
            requires_human_reason=requires_human_reason,
        )
    finally:
        if not deferred_slot_release:
            invocation_usage.merge_into(parent_usage_collector)
            slot_semaphore.release()


def grounding_evidence_snapshot(article: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return evaluator-visible evidence and its canonical delivery binding."""
    metadata = _record_from(article.get("metadata"))
    body = _string_from(article.get("body"))
    evidence = {
        "evidenceId": _string_from(article.get("id")),
        "id": _string_from(article.get("id")),
        "title": _string_from(article.get("title")),
        "body": body,
        "tags": article.get("tags") if isinstance(article.get("tags"), list) else [],
        "status": _string_from(article.get("status")),
        "reviewStatus": _string_from(article.get("reviewStatus")),
        "freshnessStatus": _string_from(article.get("freshnessStatus")),
        "needsReview": bool(article.get("needsReview")),
        "visibility": _string_from(article.get("visibility") or metadata.get("visibility")),
        "public": bool(article.get("public") or metadata.get("public")),
        "automationAllowed": bool(
            article.get("automationAllowed") if "automationAllowed" in article else metadata.get("automationAllowed")
        ),
        "updated": _string_from(article.get("updated")),
        "revision": _string_from(
            article.get("revision")
            or article.get("version")
            or metadata.get("revision")
            or metadata.get("version")
            or metadata.get("sourceRevision")
        ),
    }
    evidence_hash_payload = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    snapshot = {
        "id": evidence["id"],
        "updated": evidence["updated"],
        "revision": evidence["revision"],
        "bodySha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "evidenceSha256": hashlib.sha256(evidence_hash_payload.encode("utf-8")).hexdigest(),
        "bodyChars": len(body),
        "status": evidence["status"],
        "reviewStatus": evidence["reviewStatus"],
        "freshnessStatus": evidence["freshnessStatus"],
        "needsReview": evidence["needsReview"],
        "visibility": evidence["visibility"],
        "public": evidence["public"],
        "automationAllowed": evidence["automationAllowed"],
    }
    return evidence, snapshot


def _grounding_evidence(
    articles: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], tuple[dict[str, Any], ...], tuple[str, ...]]:
    evidence: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    incomplete_ids: list[str] = []
    total_body_chars = 0
    for article in articles:
        article_id = _string_from(article.get("id"))
        if not article_id:
            continue
        article_evidence, snapshot = grounding_evidence_snapshot(article)
        body = _string_from(article_evidence.get("body"))
        body_chars = len(body)
        snapshots.append(snapshot)
        if (
            not body
            or body_chars > GROUNDING_MAX_ARTICLE_CHARS
            or total_body_chars + body_chars > GROUNDING_MAX_TOTAL_ARTICLE_CHARS
        ):
            incomplete_ids.append(article_id)
            continue
        total_body_chars += body_chars
        evidence.append(article_evidence)
    return evidence, tuple(snapshots), tuple(incomplete_ids)


def assess_issue_automation_grounding(
    *,
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
    answer: str,
    articles: list[dict[str, Any]],
    tenant_id: str | None,
    project_id: str,
    account_context: dict[str, Any] | None = None,
    conversation_context: dict[str, Any] | None = None,
    on_late_usage: Callable[[list[dict[str, Any]]], None] | None = None,
) -> AutomationGroundingAssessment:
    """Fail-closed semantic gate for a statically eligible automatic reply."""
    checked_at = datetime.now(timezone.utc).isoformat()
    answer = answer.strip()
    answer_sha256 = grounding_text_sha256(answer)
    safety_assessment = _issue_safety_assessment(issue, messages)
    context_snapshots = grounding_context_snapshots(
        issue=issue,
        messages=messages,
        account_context=account_context,
        conversation_context=conversation_context,
    )
    answer_units = _grounding_answer_units(answer)
    audit_answer_units = tuple(
        {
            "id": _string_from(unit.get("id")),
            "start": int(unit.get("start", 0)),
            "end": int(unit.get("end", 0)),
            "sha256": _string_from(unit.get("sha256")),
        }
        for unit in answer_units
    )
    answer_obligations = list(_answer_obligations_from_issue(issue))
    if safety_assessment.active:
        answer_obligations.append(safety_assessment.answer_obligation())
    answer_obligations = tuple(answer_obligations)
    citation_ids = tuple(
        dict.fromkeys(
            article_id for article_id in (_string_from(article.get("id")) for article in articles) if article_id
        )
    )
    ticket_evidence = _automatic_ticket_context(issue)
    global_ticket_evidence = _global_grounding_ticket_evidence(ticket_evidence)
    scoped_ticket_evidence = _scoped_grounding_ticket_evidence(ticket_evidence)
    successful_action_evidence_records = _successful_action_evidence_records_by_id(ticket_evidence)
    successful_action_evidence_by_concern = _successful_action_evidence_ids_by_concern(ticket_evidence)
    scoped_grounding_evidence_concerns = _scoped_grounding_evidence_concerns(
        ticket_evidence,
        successful_evidence_by_concern=successful_action_evidence_by_concern,
    )
    expected_language = _latest_customer_language(messages)
    detected_answer_language = _detected_supported_language(answer)
    if expected_language != detected_answer_language:
        return AutomationGroundingAssessment(
            verified=False,
            status="failed",
            reason_code=LANGUAGE_MISMATCH_REASON_CODE,
            checked_at=checked_at,
            citation_ids=citation_ids,
            context_snapshots=context_snapshots,
            answer_sha256=answer_sha256,
            answer_units=audit_answer_units,
            answer_obligations=answer_obligations,
            error=(
                f"Answer language {_LANGUAGE_NAMES[detected_answer_language]} does not match "
                f"latest customer language {_LANGUAGE_NAMES[expected_language]}"
            ),
        )
    missing_safety = missing_lithium_battery_safety_guidance(answer) if safety_assessment.active else ()
    if missing_safety:
        return AutomationGroundingAssessment(
            verified=False,
            status="failed",
            reason_code=SAFETY_GUIDANCE_MISSING_REASON_CODE,
            checked_at=checked_at,
            citation_ids=citation_ids,
            context_snapshots=context_snapshots,
            answer_sha256=answer_sha256,
            answer_units=audit_answer_units,
            answer_obligations=answer_obligations,
            uncovered_obligations=(safety_assessment.answer_obligation()["question"],),
            unsupported_claims=missing_safety,
            error=("Missing mandatory damaged-lithium-battery safety guidance: " + ", ".join(missing_safety))[:1_000],
        )
    pending_action_check = check_pending_action_claims(
        answer=answer,
        runbook_actions=ticket_evidence.get("runbookActions", []),
        tool_evidence=_automatic_tool_evidence_records(ticket_evidence),
    )
    if pending_action_check.blocked:
        return AutomationGroundingAssessment(
            verified=False,
            status="failed",
            reason_code=PENDING_ACTION_CLAIM_REASON_CODE,
            checked_at=checked_at,
            citation_ids=citation_ids,
            context_snapshots=context_snapshots,
            answer_sha256=answer_sha256,
            answer_units=audit_answer_units,
            answer_obligations=answer_obligations,
            pending_action_claims=pending_action_check.claims,
            pending_actions=pending_action_check.pending_actions,
        )
    allowed_business_identifiers = _allowed_business_identifiers(
        messages=messages,
        ticket=ticket_evidence,
        articles=articles,
    )
    unsupported_identifiers = _unsupported_business_identifiers(
        answer,
        allowed_identifiers=allowed_business_identifiers,
    )
    if unsupported_identifiers:
        return AutomationGroundingAssessment(
            verified=False,
            status="failed",
            reason_code=BUSINESS_IDENTIFIER_MISMATCH_REASON_CODE,
            checked_at=checked_at,
            citation_ids=citation_ids,
            context_snapshots=context_snapshots,
            answer_sha256=answer_sha256,
            answer_units=audit_answer_units,
            answer_obligations=answer_obligations,
            unsupported_claims=unsupported_identifiers,
            error=(
                "Candidate answer contains unsupported business identifiers: " + ", ".join(unsupported_identifiers[:20])
            )[:1_000],
        )
    if not answer_units or len(answer_units) > _GROUNDING_MAX_UNITS:
        return AutomationGroundingAssessment(
            verified=False,
            status="error",
            reason_code="grounding_check_failed",
            checked_at=checked_at,
            citation_ids=citation_ids,
            context_snapshots=context_snapshots,
            answer_sha256=answer_sha256,
            answer_units=audit_answer_units,
            answer_obligations=answer_obligations,
            error="Candidate answer could not be exhaustively segmented for grounding",
        )
    evidence, snapshots, incomplete_ids = _grounding_evidence(articles)
    if incomplete_ids or len(evidence) != len(citation_ids):
        return AutomationGroundingAssessment(
            verified=False,
            status="blocked",
            reason_code="grounding_evidence_incomplete",
            checked_at=checked_at,
            citation_ids=citation_ids,
            evidence_snapshots=snapshots,
            context_snapshots=context_snapshots,
            answer_sha256=answer_sha256,
            answer_units=audit_answer_units,
            answer_obligations=answer_obligations,
            error=("Incomplete cited evidence: " + ", ".join(incomplete_ids or citation_ids))[:1_000],
        )
    slot_semaphore = _GROUNDING_AGENT_SLOTS
    if not slot_semaphore.acquire(
        blocking=True,
        timeout=GROUNDING_AGENT_SLOT_WAIT_SECONDS,
    ):
        return AutomationGroundingAssessment(
            verified=False,
            status="error",
            reason_code="grounding_check_failed",
            checked_at=checked_at,
            citation_ids=citation_ids,
            evidence_snapshots=snapshots,
            context_snapshots=context_snapshots,
            answer_sha256=answer_sha256,
            answer_units=audit_answer_units,
            answer_obligations=answer_obligations,
            error="Grounding evaluator capacity is temporarily exhausted",
        )

    deferred_slot_release = False
    parent_usage_collector: Any = None
    invocation_usage = _AgentInvocationUsage()
    provider = ""
    model = ""
    try:
        from automail.core.config import read_config
        from automail.llm import create_llm, resolve_effective_config
        from automail.llm.usage import current_collector, llm_stage, record_usage_from_result

        config = resolve_effective_config(read_config(), tenant_id, project_id)
        provider = _string_from(getattr(config, "llm_provider", ""))
        model = _string_from(
            getattr(config, "llm_custom_model", "") if provider == "custom" else getattr(config, "llm_model", "")
        )
        llm = create_llm(
            config,
            timeout=GROUNDING_MODEL_CALL_TIMEOUT_SECONDS,
            max_retries=0,
            temperature=0,
            thinking_budget=GROUNDING_MODEL_THINKING_BUDGET,
        )
        usage_context = getattr(llm, "_mantly_usage_context", None)
        if isinstance(usage_context, dict):
            provider = _string_from(usage_context.get("provider")) or provider
            model = _string_from(usage_context.get("model")) or model
        message_evidence = _automatic_message_context(messages)
        account_evidence = _automatic_account_context(
            account_context,
            issue_id=_string_from(issue.get("id")),
            conversation_context=conversation_context,
        )
        conversation_evidence = _automatic_conversation_context(conversation_context)
        allowed_evidence_ids = ["ticket"]
        if safety_assessment.active:
            allowed_evidence_ids.append(safety_assessment.policy_id)
        allowed_evidence_ids.extend(_automatic_tool_evidence_ids(ticket_evidence))
        for evidence_ids in successful_action_evidence_by_concern.values():
            allowed_evidence_ids.extend(evidence_ids)
        allowed_evidence_ids.extend(
            evidence_id for evidence_id in scoped_grounding_evidence_concerns if evidence_id.startswith("concern:")
        )
        if message_evidence:
            allowed_evidence_ids.append("messages")
        if account_evidence:
            allowed_evidence_ids.append("account")
        if conversation_evidence:
            allowed_evidence_ids.append("conversation")
        allowed_evidence_ids.extend(citation_ids)
        allowed_evidence_ids = list(dict.fromkeys(allowed_evidence_ids))
        prompt = _GROUNDING_USER_TEMPLATE.format(
            answer_sha256=answer_sha256,
            answer_units=_json(answer_units),
            answer_obligations=_json(answer_obligations),
            allowed_evidence_ids=_json(allowed_evidence_ids),
            ticket=_json(global_ticket_evidence),
            scoped_ticket_evidence=_json(scoped_ticket_evidence),
            account_intelligence=_json(account_evidence),
            conversation_context=_json(conversation_evidence),
            messages=_json(message_evidence),
            knowledge_articles=_json(evidence),
            system_safety_policy=_json(safety_assessment.evidence()),
            answer=answer,
        )
        agent = create_agent(
            model=llm,
            tools=[],
            system_prompt=_GROUNDING_SYSTEM_PROMPT,
            response_format=ToolStrategy(AutomationGroundingOutput),
            middleware=[ModelCallLimitMiddleware(run_limit=1, exit_behavior="error")],
            name="issue_automation_grounding",
        )
        invoke_config = {
            "recursion_limit": 4,
            "run_name": "issue_automation_grounding",
            "tags": ["mantly", "support", "automation-grounding"],
            "metadata": {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "issue_id": _string_from(issue.get("id")),
                "source": "support.issue_automation_grounding",
                "gate_version": GROUNDING_GATE_VERSION,
            },
        }

        expected_unit_ids_for_retry = frozenset(
            _string_from(unit.get("id")) for unit in answer_units if _string_from(unit.get("id"))
        )
        expected_units_for_retry = {
            _string_from(unit.get("id")): unit for unit in answer_units if _string_from(unit.get("id"))
        }
        expected_obligation_ids_for_retry = frozenset(
            _string_from(obligation.get("id"))
            for obligation in answer_obligations
            if _string_from(obligation.get("id"))
        )
        expected_obligations_for_retry = {
            _string_from(obligation.get("id")): obligation
            for obligation in answer_obligations
            if _string_from(obligation.get("id"))
        }

        def invoke_once(active_prompt: str) -> dict[str, Any]:
            with llm_stage("issue_automation_grounding"):
                response = agent.invoke(
                    {"messages": [{"role": "user", "content": active_prompt}]},
                    config=invoke_config,
                )
                record_usage_from_result(response, usage_context)
            return response

        def invoke_agent() -> dict[str, Any]:
            response: dict[str, Any] = {}
            active_prompt = prompt
            for attempt in range(GROUNDING_MODEL_CALL_LIMIT):
                response = invoke_once(active_prompt)
                structured = response.get("structured_response") if isinstance(response, dict) else None
                retryable_errors = _grounding_retryable_protocol_errors(
                    structured,
                    expected_unit_ids=expected_unit_ids_for_retry,
                    expected_obligation_ids=expected_obligation_ids_for_retry,
                    allowed_evidence_ids=frozenset(allowed_evidence_ids),
                )
                if retryable_errors and attempt + 1 < GROUNDING_MODEL_CALL_LIMIT:
                    logger.warning(
                        "Grounding evaluator returned malformed protocol output; retrying once: %s",
                        "; ".join(retryable_errors),
                    )
                    active_prompt = prompt + "\n\n" + _GROUNDING_PROTOCOL_REPAIR_TEMPLATE.format(
                        protocol_errors=_json(list(retryable_errors)),
                        invalid_evidence_ids=_json(
                            list(
                                _grounding_unknown_evidence_ids(
                                    structured,
                                    allowed_evidence_ids=frozenset(allowed_evidence_ids),
                                )
                            )
                        ),
                        allowed_evidence_ids=_json(sorted(allowed_evidence_ids)),
                        answer_unit_ids=_json(sorted(expected_unit_ids_for_retry)),
                        answer_obligation_ids=_json(sorted(expected_obligation_ids_for_retry)),
                    )
                    continue
                if attempt + 1 < GROUNDING_MODEL_CALL_LIMIT and _grounding_needs_obligation_reassessment(
                    structured,
                    expected_unit_ids=expected_unit_ids_for_retry,
                    expected_obligation_ids=expected_obligation_ids_for_retry,
                    allowed_evidence_ids=frozenset(allowed_evidence_ids),
                    expected_units=expected_units_for_retry,
                    expected_obligations=expected_obligations_for_retry,
                ):
                    logger.warning(
                        "Grounding evaluator linked supported units to an uncovered obligation; "
                        "running one focused obligation reassessment"
                    )
                    active_prompt = prompt + "\n\n" + _GROUNDING_OBLIGATION_REASSESSMENT_INSTRUCTION
                    continue
                if not retryable_errors or attempt + 1 >= GROUNDING_MODEL_CALL_LIMIT:
                    break
            return response

        parent_usage_collector = current_collector()
        future = _GROUNDING_AGENT_EXECUTOR.submit(
            copy_context().run,
            invocation_usage.run,
            invoke_agent,
        )
        try:
            response = future.result(timeout=GROUNDING_AGENT_DEADLINE_SECONDS)
        except FutureTimeoutError as exc:
            deferred_slot_release = True
            future.add_done_callback(
                lambda _future: _finish_timed_out_agent(
                    slot_semaphore=slot_semaphore,
                    invocation_usage=invocation_usage,
                    on_late_usage=on_late_usage,
                )
            )
            raise TimeoutError("Grounding evaluator deadline exceeded") from exc
        structured = response.get("structured_response") if isinstance(response, dict) else None
        if not isinstance(structured, AutomationGroundingOutput):
            raise ValueError("Grounding evaluator returned no structured response")

        protocol_errors: list[str] = []
        if not structured.unit_assessments:
            protocol_errors.append("Evaluator returned no answer-unit assessments")
        if len(structured.unit_assessments) > _GROUNDING_MAX_UNITS:
            protocol_errors.append("Evaluator returned too many answer-unit assessments")

        allowed_ids = set(allowed_evidence_ids)
        unsupported_claims: list[str] = []
        expected_units = {_string_from(unit.get("id")): unit for unit in answer_units if _string_from(unit.get("id"))}
        seen_unit_ids: set[str] = set()
        used_supported_evidence_ids: set[str] = set()
        clean_unit_assessments: list[dict[str, Any]] = []
        for assessment in structured.unit_assessments[:_GROUNDING_MAX_UNITS]:
            unit_id = _string_from(assessment.unit_id)
            expected_unit = expected_units.get(unit_id)
            evidence_ids = tuple(
                dict.fromkeys(
                    evidence_id
                    for evidence_id in (_string_from(value) for value in assessment.evidence_ids)
                    if evidence_id
                )
            )
            if not unit_id or unit_id in seen_unit_ids:
                protocol_errors.append("Evaluator returned a missing or duplicate answer-unit ID")
                continue
            seen_unit_ids.add(unit_id)
            if expected_unit is None:
                protocol_errors.append(f"Evaluator returned unknown answer-unit ID: {unit_id}")
                continue
            expected_unit_sha256 = _string_from(expected_unit.get("sha256"))
            unknown_ids = [evidence_id for evidence_id in evidence_ids if evidence_id not in allowed_ids]
            if unknown_ids:
                protocol_errors.append(f"Answer unit uses unknown evidence IDs: {', '.join(unknown_ids[:5])}")
            if assessment.supported and not evidence_ids:
                protocol_errors.append(f"Supported answer unit has no evidence IDs: {unit_id}")
            if not assessment.supported or not evidence_ids:
                unsupported_claims.append(_string_from(expected_unit.get("text"))[:500])
            else:
                used_supported_evidence_ids.update(evidence_ids)
            clean_unit_assessments.append(
                {
                    "unitId": unit_id,
                    "unitSha256": expected_unit_sha256,
                    "supported": bool(assessment.supported),
                    "evidenceIds": list(evidence_ids),
                }
            )
        if seen_unit_ids != set(expected_units):
            protocol_errors.append("Evaluator did not assess every answer unit exactly once")
        supported_unit_evidence_ids = {
            _string_from(item.get("unitId")): frozenset(
                _string_from(evidence_id) for evidence_id in item.get("evidenceIds", []) if _string_from(evidence_id)
            )
            for item in clean_unit_assessments
            if (
                item.get("supported")
                and item.get("evidenceIds")
                and set(item.get("evidenceIds", [])).issubset(allowed_ids)
            )
        }
        supported_units = set(supported_unit_evidence_ids)

        expected_obligations = {
            _string_from(obligation.get("id")): obligation
            for obligation in answer_obligations
            if _string_from(obligation.get("id"))
        }
        seen_obligation_ids: set[str] = set()
        deterministically_resolved_obligation_ids: set[str] = set()
        clean_obligation_assessments: list[dict[str, Any]] = []
        uncovered_obligations: list[str] = []
        if len(structured.obligation_assessments) > 100:
            protocol_errors.append("Evaluator returned too many obligation assessments")
        for assessment in structured.obligation_assessments[:100]:
            obligation_id = _string_from(assessment.obligation_id)
            obligation = expected_obligations.get(obligation_id)
            answer_unit_ids = tuple(
                dict.fromkeys(
                    unit_id for unit_id in (_string_from(value) for value in assessment.answer_unit_ids) if unit_id
                )
            )
            if not obligation_id or obligation_id in seen_obligation_ids:
                protocol_errors.append("Evaluator returned a missing or duplicate answer-obligation ID")
                continue
            seen_obligation_ids.add(obligation_id)
            if obligation is None:
                protocol_errors.append(f"Evaluator returned unknown answer-obligation ID: {obligation_id}")
                continue
            unknown_unit_ids = [unit_id for unit_id in answer_unit_ids if unit_id not in expected_units]
            if unknown_unit_ids:
                protocol_errors.append(
                    "Answer obligation uses unknown answer-unit IDs: " + ", ".join(unknown_unit_ids[:5])
                )
            requested_resolution = _string_from(assessment.resolution)
            resolution = requested_resolution
            obligation_kind = _string_from(obligation.get("kind")) or "customer_question"
            linked_units_are_supported = bool(
                answer_unit_ids and not unknown_unit_ids and set(answer_unit_ids).issubset(supported_units)
            )
            obligation_concern_id = _string_from(obligation.get("concernId"))
            linked_evidence_ids = {
                evidence_id
                for unit_id in answer_unit_ids
                for evidence_id in supported_unit_evidence_ids.get(unit_id, frozenset())
            }
            requested_obligation_evidence_ids = tuple(
                dict.fromkeys(evidence_id for value in assessment.evidence_ids if (evidence_id := _string_from(value)))
            )
            unknown_obligation_evidence_ids = [
                evidence_id for evidence_id in requested_obligation_evidence_ids if evidence_id not in allowed_ids
            ]
            if unknown_obligation_evidence_ids:
                protocol_errors.append(
                    "Answer obligation uses unknown evidence IDs: " + ", ".join(unknown_obligation_evidence_ids[:5])
                )
            requested_linked_evidence_ids = {
                evidence_id for evidence_id in requested_obligation_evidence_ids if evidence_id in linked_evidence_ids
            }
            obligation_evidence_ids = set(requested_linked_evidence_ids or linked_evidence_ids)
            usable_obligation_evidence_ids = {
                evidence_id
                for evidence_id in obligation_evidence_ids
                if (
                    not (scoped_concern_ids := scoped_grounding_evidence_concerns.get(evidence_id))
                    or scoped_concern_ids == frozenset({obligation_concern_id})
                )
            }
            # A unit may make separately supported statements for several
            # concerns. Filter foreign IDs from this obligation instead of
            # rejecting the whole unit; at least one same-concern or global
            # evidence source must remain.
            obligation_has_usable_evidence = bool(usable_obligation_evidence_ids) and not (
                unknown_obligation_evidence_ids
            )
            if requested_resolution in _ADDRESSED_OBLIGATION_RESOLUTIONS and not answer_unit_ids:
                protocol_errors.append(f"Addressed obligation has no answer-unit IDs: {obligation_id}")
            if requested_resolution in _ADDRESSED_OBLIGATION_RESOLUTIONS and not linked_units_are_supported:
                resolution = "not_covered"
            if requested_resolution in _ADDRESSED_OBLIGATION_RESOLUTIONS and not obligation_has_usable_evidence:
                resolution = "not_covered"
            if (
                requested_resolution == "not_covered"
                and linked_units_are_supported
                and obligation_has_usable_evidence
                and _knowledge_backed_negative_guarantee_answers_obligation(
                    question=_string_from(obligation.get("question")),
                    answer_unit_ids=answer_unit_ids,
                    expected_units=expected_units,
                    supported_unit_evidence_ids=supported_unit_evidence_ids,
                    citation_ids=frozenset(citation_ids),
                )
            ):
                resolution = "pending_or_unavailable"
                deterministically_resolved_obligation_ids.add(obligation_id)
            if (
                requested_resolution == "not_covered"
                and linked_units_are_supported
                and obligation_has_usable_evidence
                and _knowledge_backed_secure_secret_delivery_answers_obligation(
                    question=_string_from(obligation.get("question")),
                    answer_unit_ids=answer_unit_ids,
                    expected_units=expected_units,
                    supported_unit_evidence_ids=supported_unit_evidence_ids,
                    citation_ids=frozenset(citation_ids),
                )
            ):
                resolution = "answered"
                deterministically_resolved_obligation_ids.add(obligation_id)
            obligation_question = _string_from(obligation.get("question"))
            is_service_incident_temporal_requirement = bool(
                obligation_kind == "runbook_requirement"
                and _is_service_incident_temporal_requirement(
                    ticket=ticket_evidence,
                    concern_id=obligation_concern_id,
                    question=obligation_question,
                )
            )
            isolated_service_incident_temporal_answer = bool(
                is_service_incident_temporal_requirement
                and linked_units_are_supported
                and obligation_has_usable_evidence
                and _is_isolated_service_incident_temporal_answer(
                    ticket=ticket_evidence,
                    concern_id=obligation_concern_id,
                    answer_unit_ids=answer_unit_ids,
                    expected_units=expected_units,
                    supported_unit_evidence_ids=supported_unit_evidence_ids,
                )
            )
            if (
                requested_resolution == "answered"
                and is_service_incident_temporal_requirement
                and not isolated_service_incident_temporal_answer
            ):
                resolution = "not_covered"
            linked_answer_asserts_action_state = any(
                check_pending_action_claims(
                    answer=_string_from(expected_units.get(unit_id, {}).get("text")),
                    runbook_actions=(
                        {
                            "name": obligation_question or "pending_action",
                            "label": obligation_question or "Pending action",
                            "status": "pending_approval",
                        },
                    ),
                ).blocked
                for unit_id in answer_unit_ids
            )
            must_bind_action_evidence = requested_resolution == "fulfilled_action" or (
                requested_resolution == "answered" and linked_answer_asserts_action_state
            )
            if must_bind_action_evidence and linked_units_are_supported:
                same_concern_action_evidence_ids = successful_action_evidence_by_concern.get(
                    obligation_concern_id,
                    frozenset(),
                )
                matching_action_evidence_ids = _matching_successful_action_evidence_ids(
                    successful_action_evidence_records,
                    concern_id=obligation_concern_id,
                    expected_action_text=_string_from(obligation.get("question")),
                )
                cited_same_concern_action_evidence_ids = obligation_evidence_ids.intersection(
                    same_concern_action_evidence_ids
                )
                if (
                    not matching_action_evidence_ids
                    or not cited_same_concern_action_evidence_ids
                    or not cited_same_concern_action_evidence_ids.issubset(matching_action_evidence_ids)
                    or any(
                        not supported_unit_evidence_ids.get(unit_id, frozenset()).intersection(
                            matching_action_evidence_ids
                        )
                        for unit_id in answer_unit_ids
                    )
                ):
                    resolution = "not_covered"
            # Run this exact-fact exception after action-state validation. A
            # read-only sentence such as "the incident started at <ISO>" can
            # look like a completed mutation to the generic action guard. Only
            # restore coverage when the obligation and linked unit pass the
            # stricter same-concern, successful-tool, exact-scalar checks.
            if (
                resolution == "not_covered"
                and requested_resolution == "answered"
                and obligation_kind == "runbook_requirement"
                and linked_units_are_supported
                and obligation_has_usable_evidence
                and isolated_service_incident_temporal_answer
                and _tool_backed_temporal_scalar_answers_obligation(
                    ticket=ticket_evidence,
                    concern_id=obligation_concern_id,
                    question=obligation_question,
                    answer_unit_ids=answer_unit_ids,
                    expected_units=expected_units,
                    supported_unit_evidence_ids=supported_unit_evidence_ids,
                )
            ):
                resolution = "answered"
                deterministically_resolved_obligation_ids.add(obligation_id)
            # A runbook response requirement is trusted operational guidance,
            # not a customer-requested business action. Enforce this after all
            # deterministic resolution overrides: only a substantive `answered`
            # result can cover it; generic pending/unavailable prose cannot.
            if obligation_kind == "runbook_requirement" and resolution != "answered":
                resolution = "not_covered"
            covered = resolution in _ADDRESSED_OBLIGATION_RESOLUTIONS
            if not covered:
                uncovered_obligations.append(_string_from(obligation.get("question"))[:500])
            clean_assessment = {
                "obligationId": obligation_id,
                "resolution": resolution,
                "covered": covered,
                "answerUnitIds": list(answer_unit_ids),
            }
            if requested_obligation_evidence_ids:
                clean_evidence_candidates = (
                    requested_obligation_evidence_ids
                    if requested_linked_evidence_ids
                    else tuple(sorted(linked_evidence_ids))
                )
                clean_assessment["evidenceIds"] = [
                    evidence_id
                    for evidence_id in clean_evidence_candidates
                    if (evidence_id in obligation_evidence_ids and evidence_id in usable_obligation_evidence_ids)
                ]
            clean_obligation_assessments.append(clean_assessment)
        if seen_obligation_ids != set(expected_obligations):
            protocol_errors.append("Evaluator did not assess every answer obligation exactly once")
            uncovered_obligations.extend(
                _string_from(obligation.get("question"))[:500]
                for obligation_id, obligation in expected_obligations.items()
                if obligation_id not in seen_obligation_ids
            )
        used_citation_ids = tuple(
            citation_id for citation_id in citation_ids if citation_id in used_supported_evidence_ids
        )
        used_citation_id_set = set(used_citation_ids)
        used_evidence_snapshots = tuple(
            snapshot for snapshot in snapshots if _string_from(snapshot.get("id")) in used_citation_id_set
        )

        contradictions = tuple(
            dict.fromkeys(
                contradiction
                for contradiction in (_string_from(value)[:500] for value in structured.contradictions[:20])
                if contradiction
            )
        )
        clean_unsupported = tuple(dict.fromkeys(unsupported_claims))
        clean_uncovered_obligations = tuple(dict.fromkeys(uncovered_obligations))
        if protocol_errors:
            return AutomationGroundingAssessment(
                verified=False,
                status="error",
                reason_code="grounding_check_failed",
                checked_at=checked_at,
                citation_ids=citation_ids,
                evidence_snapshots=snapshots,
                context_snapshots=context_snapshots,
                answer_sha256=answer_sha256,
                answer_units=audit_answer_units,
                unit_assessments=tuple(clean_unit_assessments),
                answer_obligations=answer_obligations,
                obligation_assessments=tuple(clean_obligation_assessments),
                uncovered_obligations=clean_uncovered_obligations,
                claim_count=min(len(structured.unit_assessments), _GROUNDING_MAX_UNITS),
                unsupported_claims=clean_unsupported,
                contradictions=contradictions,
                provider=provider,
                model=model,
                error="; ".join(dict.fromkeys(protocol_errors))[:1_000],
            )
        deterministic_obligation_override = bool(
            deterministically_resolved_obligation_ids
            and not clean_unsupported
            and not contradictions
            and not clean_uncovered_obligations
        )
        if (
            (structured.verdict != "grounded" and not deterministic_obligation_override)
            or clean_unsupported
            or contradictions
            or clean_uncovered_obligations
        ):
            return AutomationGroundingAssessment(
                verified=False,
                status="failed",
                reason_code=("incomplete_answer" if clean_uncovered_obligations else "ungrounded_answer"),
                checked_at=checked_at,
                citation_ids=citation_ids,
                evidence_snapshots=snapshots,
                context_snapshots=context_snapshots,
                answer_sha256=answer_sha256,
                answer_units=audit_answer_units,
                unit_assessments=tuple(clean_unit_assessments),
                answer_obligations=answer_obligations,
                obligation_assessments=tuple(clean_obligation_assessments),
                uncovered_obligations=clean_uncovered_obligations,
                claim_count=len(structured.unit_assessments),
                unsupported_claims=clean_unsupported,
                contradictions=contradictions,
                provider=provider,
                model=model,
            )
        return AutomationGroundingAssessment(
            verified=True,
            status="passed",
            reason_code="",
            checked_at=checked_at,
            citation_ids=used_citation_ids,
            evidence_snapshots=used_evidence_snapshots,
            context_snapshots=context_snapshots,
            answer_sha256=answer_sha256,
            answer_units=audit_answer_units,
            unit_assessments=tuple(clean_unit_assessments),
            answer_obligations=answer_obligations,
            obligation_assessments=tuple(clean_obligation_assessments),
            claim_count=len(structured.unit_assessments),
            provider=provider,
            model=model,
        )
    except Exception as exc:
        logger.info("Automatic answer grounding check failed: %s", exc)
        return AutomationGroundingAssessment(
            verified=False,
            status="error",
            reason_code="grounding_check_failed",
            checked_at=checked_at,
            citation_ids=citation_ids,
            evidence_snapshots=snapshots,
            context_snapshots=context_snapshots,
            answer_sha256=answer_sha256,
            answer_units=audit_answer_units,
            answer_obligations=answer_obligations,
            provider=provider,
            model=model,
            error=str(exc)[:1_000],
        )
    finally:
        if not deferred_slot_release:
            invocation_usage.merge_into(parent_usage_collector)
            slot_semaphore.release()
