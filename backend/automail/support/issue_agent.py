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
from pydantic import BaseModel, Field

from automail.support.knowledge_workspace import KnowledgeWorkspace
from automail.support.pending_action_claims import (
    PENDING_ACTION_CLAIM_REASON_CODE,
    check_pending_action_claims,
)

logger = logging.getLogger(__name__)
_KNOWLEDGE_AGENT_SLOTS = threading.BoundedSemaphore(4)
_KNOWLEDGE_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="knowledge-agent")
KNOWLEDGE_AGENT_DEADLINE_SECONDS = 75
KNOWLEDGE_AGENT_MODEL_CALL_LIMIT = 9
KNOWLEDGE_AGENT_TOOL_CALL_LIMIT = 8
_AUTOMATION_AGENT_SLOTS = threading.BoundedSemaphore(8)
_AUTOMATION_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="automation-agent")
AUTOMATION_AGENT_DEADLINE_SECONDS = 55
AUTOMATION_AGENT_SLOT_WAIT_SECONDS = 40
_GROUNDING_AGENT_SLOTS = threading.BoundedSemaphore(8)
_GROUNDING_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="grounding-agent")
GROUNDING_AGENT_DEADLINE_SECONDS = 40
GROUNDING_AGENT_SLOT_WAIT_SECONDS = 40
GROUNDING_GATE_VERSION = "automation-grounding-v4"
GROUNDING_GATE_MAX_AGE_SECONDS = 10 * 60
GROUNDING_MAX_ARTICLE_CHARS = 30_000
GROUNDING_MAX_TOTAL_ARTICLE_CHARS = 60_000
_AUTOMATIC_RUNBOOK_ACTION_ERROR_MAX_CHARS = 500
LANGUAGE_MISMATCH_REASON_CODE = "language_mismatch"
BUSINESS_IDENTIFIER_MISMATCH_REASON_CODE = "identifier_mismatch"

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_SYSTEM_PROMPT = (_PROMPTS_DIR / "issue_agent_system_prompt.md").read_text(encoding="utf-8").strip()
_USER_TEMPLATE = (_PROMPTS_DIR / "issue_agent_user_prompt.md").read_text(encoding="utf-8").strip()
_AUTOMATION_SYSTEM_PROMPT = (_PROMPTS_DIR / "issue_automation_system_prompt.md").read_text(encoding="utf-8").strip()
_AUTOMATION_USER_TEMPLATE = (_PROMPTS_DIR / "issue_automation_user_prompt.md").read_text(encoding="utf-8").strip()
_GROUNDING_SYSTEM_PROMPT = (_PROMPTS_DIR / "issue_grounding_eval_system_prompt.md").read_text(encoding="utf-8").strip()
_GROUNDING_USER_TEMPLATE = (_PROMPTS_DIR / "issue_grounding_eval_user_prompt.md").read_text(encoding="utf-8").strip()


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
            "modelCallLimit": 1,
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


class KnowledgeAgentOutput(BaseModel):
    """Structured result produced after searching the isolated workspace."""

    answer: str = Field(description="Approval-ready customer support answer")
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
    covered: bool
    answer_unit_ids: list[str] = Field(default_factory=list)


class AutomationGroundingOutput(BaseModel):
    """Independent exhaustive answer-unit support decision."""

    verdict: Literal["grounded", "not_grounded"]
    answer_sha256: str
    checked_citation_ids: list[str] = Field(default_factory=list)
    unit_assessments: list[AutomationGroundingUnitAssessment] = Field(default_factory=list)
    obligation_assessments: list[AutomationGroundingObligationAssessment] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


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
        extracted_text = _string_from(
            attachment.get("extractedText") or attachment.get("extracted_text")
        )
        if not extracted_text or remaining <= 0:
            continue
        filename = _string_from(
            attachment.get("filename") or attachment.get("name")
        ) or f"attachment-{index}"
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


def _detected_supported_language(*values: str) -> str:
    clean = "\n".join(value for value in values if value).casefold()
    words = re.findall(r"[^\W\d_]+", clean, flags=re.UNICODE)
    word_counts: dict[str, int] = {}
    for word in words:
        word_counts[word] = word_counts.get(word, 0) + 1
    normalized_text = " ".join(words)
    scores: dict[str, int] = {}
    for language, word_weights in _LANGUAGE_WORD_WEIGHTS.items():
        score = sum(
            weight * min(word_counts.get(word, 0), 2)
            for word, weight in word_weights.items()
        )
        score += sum(
            weight
            for phrase, weight in _LANGUAGE_PHRASE_WEIGHTS.get(language, {}).items()
            if phrase in normalized_text
        )
        score += sum(
            weight
            for character, weight in _LANGUAGE_CHARACTER_WEIGHTS.get(language, {}).items()
            if character in clean
        )
        scores[language] = score
    return max(scores, key=scores.get) if max(scores.values(), default=0) > 0 else "en"


def _latest_customer_language(messages: list[dict[str, Any]]) -> str:
    context = _automatic_message_context(messages, limit=1)
    return _detected_supported_language(context[-1]["body"] if context else "")


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
    covered_ids = tuple(
        _string_from(item)
        for item in covered_concern_ids[:20]
        if _string_from(item)
    )
    reasons: list[str] = []
    requires_human = bool(model_requires_human)
    if expected_ids and (
        len(covered_ids) != len(expected_ids)
        or set(covered_ids) != set(expected_ids)
    ):
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
        raw_obligations = concern.get("answerObligations")
        if not isinstance(raw_obligations, list):
            continue
        for raw in raw_obligations[:10]:
            obligation = _record_from(raw)
            obligation_id = _string_from(obligation.get("id"))
            question = _string_from(obligation.get("question"))
            if not obligation_id or not question or obligation_id in seen:
                continue
            seen.add(obligation_id)
            obligations.append(
                {
                    "id": obligation_id,
                    "concernId": concern_id,
                    "question": question,
                }
            )
    return tuple(obligations)


def _validated_obligation_coverage(
    issue: dict[str, Any],
    covered_obligation_ids: list[str],
) -> tuple[tuple[str, ...], bool, str]:
    expected_ids = [item["id"] for item in _answer_obligations_from_issue(issue)]
    covered_ids = tuple(
        dict.fromkeys(
            _string_from(item)
            for item in covered_obligation_ids[:100]
            if _string_from(item)
        )
    )
    if expected_ids and (
        len(covered_ids) != len(expected_ids)
        or set(covered_ids) != set(expected_ids)
    ):
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
    obligation_ids, obligation_requires_human, obligation_reason = (
        _validated_obligation_coverage(issue, covered_obligation_ids)
    )
    reasons = [reason for reason in (concern_reason, obligation_reason) if reason]
    return (
        concern_ids,
        obligation_ids,
        requires_human or obligation_requires_human,
        " ".join(dict.fromkeys(reasons))[:1_000],
    )


def _bounded_string_list(value: Any, *, limit: int = 10, item_limit: int = 500) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []
    return [
        clean[:item_limit]
        for item in values[:limit]
        if (clean := _string_from(item))
    ]


def _automatic_tool_evidence_context(value: Any, *, limit: int = 20) -> list[dict[str, Any]]:
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
                record["evidenceId"] = f"tool:{record['name']}"
            except (TypeError, ValueError):
                pass
        if record["name"]:
            evidence.append(record)
    return evidence


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
        intent_result = _record_from(run.get("intentResult") or run.get("intent_result"))
        raw_concerns = intent_result.get("concerns")
        if not isinstance(raw_concerns, list) or not raw_concerns:
            continue

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
                    raw.get("text")
                    or raw.get("sourceText")
                    or raw.get("source_text")
                    or raw.get("summary")
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
                    obligation_id = _string_from(
                        obligation.get("obligationId")
                        or obligation.get("obligation_id")
                        or obligation.get("id")
                    ) or f"{concern['id']}:obligation-{obligation_index}"
                    if not question:
                        continue
                    obligations.append(
                        {
                            "id": obligation_id[:240],
                            "question": question[:500],
                            "sourceText": _string_from(
                                obligation.get("sourceText")
                                or obligation.get("source_text")
                            )[:1_000],
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
            forbidden = _bounded_string_list(
                outcome.get("forbiddenClaims")
                or outcome.get("forbidden_claims")
                or raw.get("forbiddenClaims")
                or raw.get("forbidden_claims")
            )
            if forbidden:
                concern["forbiddenClaims"] = forbidden
            raw_attachments = (
                outcome.get("attachments")
                or raw.get("attachments")
                or []
            )
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
                or raw.get("tool_calls")
            )
            if concern_tools:
                concern["toolEvidence"] = concern_tools
            concerns.append(concern)

        metadata = _record_from(run.get("metadata"))
        source_message_id = _string_from(
            metadata.get("emailId")
            or metadata.get("messageId")
            or metadata.get("sourceMessageId")
        )
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
        if (
            _string_from(execution.get("type")) != "runbook_webhook"
            and _string_from(metadata.get("source")) != "runbook"
        ):
            continue
        execution_source_message_id = _string_from(
            metadata.get("sourceMessageId") or metadata.get("source_message_id")
        )
        execution_concern_id = _string_from(
            metadata.get("concernId") or metadata.get("concern_id")
        )
        if source_message_id and execution_source_message_id != source_message_id:
            continue
        if concern_ids and execution_concern_id not in concern_ids:
            continue
        result = _record_from(execution.get("result"))
        proposed = _record_from(result.get("proposedAction") or metadata.get("proposedAction"))
        name = _string_from(proposed.get("name") or execution.get("actionKey"))
        label = _string_from(proposed.get("label") or execution.get("label") or name)
        concern_id = _string_from(
            execution_concern_id
            or proposed.get("concernId")
            or proposed.get("concern_id")
        )
        runbook = _string_from(metadata.get("runbook") or proposed.get("runbook"))
        status = _string_from(execution.get("status"))
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
            error = _string_from(
                execution.get("error")
                or application.get("error")
                or approval.get("note")
            )[:_AUTOMATIC_RUNBOOK_ACTION_ERROR_MAX_CHARS]
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
                if isinstance(value, (str, int, float, bool)):
                    proof[key] = value
        action_context = {
            "name": name,
            "label": label,
            "status": "success",
            "completedAt": _string_from(execution.get("completedAt")),
            "proof": proof,
        }
        if concern_id:
            action_context["concernId"] = concern_id
        if runbook:
            action_context["runbook"] = runbook
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


def _automatic_conversation_context(
    conversation_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep related-ticket state while excluding the current ticket's queue transition."""
    conversation = _conversation_context(conversation_context)
    if not conversation:
        return {}
    current_issue_id = _string_from(conversation.get("currentIssueId"))
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
            for item in conversation.get("tickets", [])
            if isinstance(item, dict)
        ],
        "messages": [
            message
            for message in conversation.get("messages", [])
            if isinstance(message, dict)
            and _string_from(message.get("direction")).lower()
            in {"customer", "email", "visitor", "user"}
        ],
    }


def _clean_answer(value: str) -> str:
    clean = value.strip()
    if clean.startswith("```"):
        clean = clean.strip("`").strip()
        if clean.lower().startswith("text"):
            clean = clean[4:].strip()
    return clean[:6000]


def grounding_text_sha256(value: str) -> str:
    """Hash the exact normalized text used by grounding and delivery."""
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


_BUSINESS_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9@])[A-Za-z0-9][A-Za-z0-9_-]{6,62}[A-Za-z0-9](?![A-Za-z0-9@])"
)
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
    return tuple(
        identifier
        for identifier in _business_identifiers(answer)
        if identifier.casefold() not in allowed
    )


def _automatic_tool_evidence_ids(ticket: dict[str, Any]) -> tuple[str, ...]:
    """Return only exact, successful tool evidence IDs surfaced in ticket context."""
    records: list[Any] = []
    raw_ticket_evidence = ticket.get("toolEvidence")
    if isinstance(raw_ticket_evidence, list):
        records.extend(raw_ticket_evidence)
    concerns = ticket.get("concerns")
    if isinstance(concerns, list):
        for raw_concern in concerns:
            concern = _record_from(raw_concern)
            raw_concern_evidence = concern.get("toolEvidence")
            if isinstance(raw_concern_evidence, list):
                records.extend(raw_concern_evidence)

    evidence_ids: list[str] = []
    for raw_record in records:
        record = _record_from(raw_record)
        name = _string_from(record.get("name"))
        evidence_id = _string_from(record.get("evidenceId"))
        if (
            name
            and evidence_id == f"tool:{name}"
            and _string_from(record.get("status")) == "success"
            and isinstance(record.get("responseFacts"), (dict, list))
            and record.get("responseFacts")
        ):
            evidence_ids.append(evidence_id)
    return tuple(dict.fromkeys(evidence_ids))


def grounding_context_snapshots(
    *,
    issue: dict[str, Any],
    messages: list[dict[str, Any]],
    account_context: dict[str, Any] | None = None,
    conversation_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Bind automatic answers to the non-knowledge context seen by the evaluator."""
    ticket = _automatic_ticket_context(issue)
    conversation = _automatic_conversation_context(conversation_context)

    payloads: list[tuple[str, Any]] = [
        ("ticket", ticket),
        ("messages", _automatic_message_context(messages)),
        ("account", _record_from(account_context)),
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
    slot_semaphore = _KNOWLEDGE_AGENT_SLOTS
    if not slot_semaphore.acquire(blocking=False):
        return IssueAgentDraft(
            answer=_knowledge_failure_answer(question, messages),
            confidence="low",
            generation_mode="deterministic_fallback",
            error="Knowledge agent capacity is temporarily exhausted",
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
        workspace = KnowledgeWorkspace(
            ticket=_ticket_context(issue),
            messages=_message_context(messages),
            account=_record_from(account_context),
            conversation=_conversation_context(conversation_context),
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
        user_prompt = _USER_TEMPLATE.format(question=clean_question)
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
        answer = _clean_answer(structured.answer)
        if not answer:
            raise ValueError("Issue agent returned an empty answer")
        citation_ids = workspace.validated_citation_ids(
            structured.citation_ids,
            structured.citation_paths,
        )
        citation_evidence = workspace.validated_citation_evidence(
            structured.citation_ids,
            structured.citation_paths,
        )
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
        if truncated_citation_ids:
            missing_information.append(
                "Full source content requires human review: " + ", ".join(truncated_citation_ids)
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
            model_requires_human=structured.requires_human,
            model_reason=structured.requires_human_reason,
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
            model_reason="Knowledge answer generation failed.",
        )
        return IssueAgentDraft(
            answer=_knowledge_failure_answer(question, messages),
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
    on_late_usage: Callable[[list[dict[str, Any]]], None] | None = None,
) -> IssueAgentDraft:
    """Preserve the bounded one-shot generator for automatic/shared retrieval paths."""
    slot_semaphore = _AUTOMATION_AGENT_SLOTS
    if not slot_semaphore.acquire(
        blocking=True,
        timeout=AUTOMATION_AGENT_SLOT_WAIT_SECONDS,
    ):
        return IssueAgentDraft(
            answer=fallback_answer,
            confidence=fallback_confidence,
            generation_mode="deterministic_fallback",
            error="Automatic answer capacity is temporarily exhausted",
            requires_human=True,
            requires_human_reason="Automatic answer capacity is temporarily exhausted.",
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
        ticket_context = _automatic_ticket_context(issue)
        allowed_business_identifiers = _allowed_business_identifiers(
            messages=messages,
            ticket=ticket_context,
            articles=articles,
        )
        user_prompt = _AUTOMATION_USER_TEMPLATE.format(
            ticket=_json(ticket_context),
            account_intelligence=_json(_record_from(account_context)),
            conversation_context=_json(_automatic_conversation_context(conversation_context)),
            messages=_json(_automatic_message_context(messages)),
            reply_language=reply_language_name,
            knowledge_articles=_json(_article_context(articles)),
            prior_agent_answers=_json(_agent_chat_context(prior_agent_runs)),
            question=(question.strip() or "Prepare the best support answer and next step.")[:4_000],
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
                    correction_reasons.append(
                        f"Rewrite the entire answer in {reply_language_name}."
                    )
                pending_action_check = check_pending_action_claims(
                    answer=first_answer,
                    runbook_actions=ticket_context.get("runbookActions", []),
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
        answer = _clean_answer(structured.answer)
        if not answer:
            raise ValueError("Issue automation returned an empty answer")
        if _detected_supported_language(answer) != reply_language:
            raise ValueError(
                f"Automatic answer language mismatch: expected {reply_language_name}"
            )
        available_ids = {_string_from(article.get("id")) for article in articles if _string_from(article.get("id"))}
        citation_ids = tuple(
            dict.fromkeys(
                article_id
                for article_id in (_string_from(value) for value in structured.citation_ids)
                if article_id in available_ids
            )
        )
        confidence = structured.confidence
        if confidence == "high" and not citation_ids:
            confidence = "medium"
        missing_information = tuple(
            dict.fromkeys(item.strip()[:500] for item in structured.missing_information[:10] if item.strip())
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
            model_requires_human=structured.requires_human,
            model_reason=structured.requires_human_reason,
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
            model_reason="Automatic answer generation failed.",
        )
        return IssueAgentDraft(
            answer=fallback_answer,
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
    answer_obligations = _answer_obligations_from_issue(issue)
    citation_ids = tuple(
        dict.fromkeys(
            article_id for article_id in (_string_from(article.get("id")) for article in articles) if article_id
        )
    )
    ticket_evidence = _automatic_ticket_context(issue)
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
    pending_action_check = check_pending_action_claims(
        answer=answer,
        runbook_actions=ticket_evidence.get("runbookActions", []),
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
                "Candidate answer contains unsupported business identifiers: "
                + ", ".join(unsupported_identifiers[:20])
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
        llm = create_llm(config, timeout=30, max_retries=0, temperature=0)
        usage_context = getattr(llm, "_mantly_usage_context", None)
        if isinstance(usage_context, dict):
            provider = _string_from(usage_context.get("provider")) or provider
            model = _string_from(usage_context.get("model")) or model
        message_evidence = _automatic_message_context(messages)
        account_evidence = _record_from(account_context)
        conversation_evidence = _automatic_conversation_context(conversation_context)
        allowed_evidence_ids = ["ticket"]
        allowed_evidence_ids.extend(_automatic_tool_evidence_ids(ticket_evidence))
        if message_evidence:
            allowed_evidence_ids.append("messages")
        if account_evidence:
            allowed_evidence_ids.append("account")
        if conversation_evidence:
            allowed_evidence_ids.append("conversation")
        allowed_evidence_ids.extend(citation_ids)
        prompt = _GROUNDING_USER_TEMPLATE.format(
            answer_sha256=answer_sha256,
            answer_units=_json(answer_units),
            answer_obligations=_json(answer_obligations),
            allowed_evidence_ids=_json(allowed_evidence_ids),
            ticket=_json(ticket_evidence),
            account_intelligence=_json(account_evidence),
            conversation_context=_json(conversation_evidence),
            messages=_json(message_evidence),
            knowledge_articles=_json(evidence),
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

        def invoke_agent() -> dict[str, Any]:
            with llm_stage("issue_automation_grounding"):
                response = agent.invoke(
                    {"messages": [{"role": "user", "content": prompt}]},
                    config=invoke_config,
                )
                record_usage_from_result(response, usage_context)
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

        expected_obligations = {
            _string_from(obligation.get("id")): obligation
            for obligation in answer_obligations
            if _string_from(obligation.get("id"))
        }
        seen_obligation_ids: set[str] = set()
        clean_obligation_assessments: list[dict[str, Any]] = []
        uncovered_obligations: list[str] = []
        if len(structured.obligation_assessments) > 100:
            protocol_errors.append("Evaluator returned too many obligation assessments")
        for assessment in structured.obligation_assessments[:100]:
            obligation_id = _string_from(assessment.obligation_id)
            obligation = expected_obligations.get(obligation_id)
            answer_unit_ids = tuple(
                dict.fromkeys(
                    unit_id
                    for unit_id in (
                        _string_from(value) for value in assessment.answer_unit_ids
                    )
                    if unit_id
                )
            )
            if not obligation_id or obligation_id in seen_obligation_ids:
                protocol_errors.append(
                    "Evaluator returned a missing or duplicate answer-obligation ID"
                )
                continue
            seen_obligation_ids.add(obligation_id)
            if obligation is None:
                protocol_errors.append(
                    f"Evaluator returned unknown answer-obligation ID: {obligation_id}"
                )
                continue
            unknown_unit_ids = [
                unit_id for unit_id in answer_unit_ids if unit_id not in expected_units
            ]
            if unknown_unit_ids:
                protocol_errors.append(
                    "Answer obligation uses unknown answer-unit IDs: "
                    + ", ".join(unknown_unit_ids[:5])
                )
            supported_units = {
                _string_from(item.get("unitId"))
                for item in clean_unit_assessments
                if item.get("supported") and item.get("evidenceIds")
            }
            covered = bool(
                assessment.covered
                and answer_unit_ids
                and not unknown_unit_ids
                and set(answer_unit_ids).issubset(supported_units)
            )
            if assessment.covered and not answer_unit_ids:
                protocol_errors.append(
                    f"Covered obligation has no answer-unit IDs: {obligation_id}"
                )
            if not covered:
                uncovered_obligations.append(
                    _string_from(obligation.get("question"))[:500]
                )
            clean_obligation_assessments.append(
                {
                    "obligationId": obligation_id,
                    "covered": covered,
                    "answerUnitIds": list(answer_unit_ids),
                }
            )
        if seen_obligation_ids != set(expected_obligations):
            protocol_errors.append(
                "Evaluator did not assess every answer obligation exactly once"
            )
        used_citation_ids = tuple(
            citation_id for citation_id in citation_ids if citation_id in used_supported_evidence_ids
        )
        used_citation_id_set = set(used_citation_ids)
        used_evidence_snapshots = tuple(
            snapshot
            for snapshot in snapshots
            if _string_from(snapshot.get("id")) in used_citation_id_set
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
        if (
            structured.verdict != "grounded"
            or clean_unsupported
            or contradictions
            or clean_uncovered_obligations
        ):
            return AutomationGroundingAssessment(
                verified=False,
                status="failed",
                reason_code=(
                    "incomplete_answer"
                    if clean_uncovered_obligations
                    else "ungrounded_answer"
                ),
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
