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

logger = logging.getLogger(__name__)
_KNOWLEDGE_AGENT_SLOTS = threading.BoundedSemaphore(4)
_KNOWLEDGE_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="knowledge-agent")
KNOWLEDGE_AGENT_DEADLINE_SECONDS = 75
KNOWLEDGE_AGENT_MODEL_CALL_LIMIT = 9
KNOWLEDGE_AGENT_TOOL_CALL_LIMIT = 8
_AUTOMATION_AGENT_SLOTS = threading.BoundedSemaphore(8)
_AUTOMATION_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="automation-agent")
AUTOMATION_AGENT_DEADLINE_SECONDS = 55
_GROUNDING_AGENT_SLOTS = threading.BoundedSemaphore(4)
_GROUNDING_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="grounding-agent")
GROUNDING_AGENT_DEADLINE_SECONDS = 40
GROUNDING_GATE_VERSION = "automation-grounding-v3"
GROUNDING_GATE_MAX_AGE_SECONDS = 10 * 60
GROUNDING_MAX_ARTICLE_CHARS = 30_000
GROUNDING_MAX_TOTAL_ARTICLE_CHARS = 60_000

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


class AutomationAnswerOutput(BaseModel):
    """Structured result from the bounded automatic response generator."""

    answer: str = Field(description="Customer-facing support answer")
    confidence: Literal["low", "medium", "high"]
    citation_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class AutomationGroundingUnitAssessment(BaseModel):
    """Evidence assessment for one immutable answer unit."""

    unit_id: str
    unit_sha256: str
    supported: bool
    evidence_ids: list[str] = Field(default_factory=list)


class AutomationGroundingOutput(BaseModel):
    """Independent exhaustive answer-unit support decision."""

    verdict: Literal["grounded", "not_grounded"]
    answer_sha256: str
    checked_citation_ids: list[str] = Field(default_factory=list)
    unit_assessments: list[AutomationGroundingUnitAssessment] = Field(default_factory=list)
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
    clean = "\n".join(language_parts).casefold()
    language_markers = {
        "fr": ("é", "è", "ê", "à", "ç", " vous ", " pour ", " réponse", " question", " indiquez", " dites"),
        "de": ("ä", "ö", "ü", "ß", " bitte ", " antwort", " frage", " nicht ", " wissen", " sagen"),
        "es": ("¿", "¡", "ñ", " respuesta", " pregunta", " por favor", " indique", " dígame"),
        "it": (" risposta", " domanda", " per favore", " dica", " conoscenza"),
    }
    padded = f" {clean} "
    scores = {
        language: sum(marker in padded for marker in markers)
        for language, markers in language_markers.items()
    }
    language = max(scores, key=scores.get) if max(scores.values(), default=0) > 0 else "en"
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
    return {
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


def _automatic_ticket_context(issue: dict[str, Any]) -> dict[str, Any]:
    """Exclude workflow state changed by queueing from customer-facing evidence."""
    ticket = _ticket_context(issue)
    ticket.pop("status", None)
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
        "messages": conversation.get("messages", []),
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
        ("messages", _message_context(messages)),
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
        return IssueAgentDraft(
            answer=answer,
            confidence=confidence,
            generation_mode="knowledge_agent",
            citation_ids=citation_ids,
            citation_evidence=citation_evidence,
            missing_information=tuple(dict.fromkeys(missing_information))[:10],
            tool_calls=workspace.tool_calls,
        )
    except Exception as exc:
        logger.info("Falling back to deterministic issue agent answer: %s", exc)
        return IssueAgentDraft(
            answer=_knowledge_failure_answer(question, messages),
            confidence="low",
            generation_mode="deterministic_fallback",
            error=str(exc)[:1_000],
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
    if not slot_semaphore.acquire(blocking=False):
        return IssueAgentDraft(
            answer=fallback_answer,
            confidence=fallback_confidence,
            generation_mode="deterministic_fallback",
            error="Automatic answer capacity is temporarily exhausted",
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
        user_prompt = _AUTOMATION_USER_TEMPLATE.format(
            ticket=_json(_automatic_ticket_context(issue)),
            account_intelligence=_json(_record_from(account_context)),
            conversation_context=_json(_automatic_conversation_context(conversation_context)),
            messages=_json(_message_context(messages)),
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
        return IssueAgentDraft(
            answer=answer,
            confidence=confidence,
            generation_mode="llm",
            citation_ids=citation_ids,
            missing_information=missing_information,
        )
    except Exception as exc:
        logger.info("Falling back to deterministic issue automation answer: %s", exc)
        return IssueAgentDraft(
            answer=fallback_answer,
            confidence=fallback_confidence,
            generation_mode="deterministic_fallback",
            error=str(exc)[:1_000],
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
    citation_ids = tuple(
        dict.fromkeys(
            article_id for article_id in (_string_from(article.get("id")) for article in articles) if article_id
        )
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
            error=("Incomplete cited evidence: " + ", ".join(incomplete_ids or citation_ids))[:1_000],
        )
    slot_semaphore = _GROUNDING_AGENT_SLOTS
    if not slot_semaphore.acquire(blocking=False):
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
        ticket_evidence = _automatic_ticket_context(issue)
        message_evidence = _message_context(messages)
        account_evidence = _record_from(account_context)
        conversation_evidence = _automatic_conversation_context(conversation_context)
        allowed_evidence_ids = ["ticket"]
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
        if _string_from(structured.answer_sha256) != answer_sha256:
            protocol_errors.append("Evaluator answer hash does not match candidate answer")
        raw_checked_citation_ids = [
            citation_id
            for citation_id in (_string_from(value) for value in structured.checked_citation_ids)
            if citation_id
        ]
        checked_citation_ids = tuple(dict.fromkeys(raw_checked_citation_ids))
        if len(raw_checked_citation_ids) != len(checked_citation_ids) or set(checked_citation_ids) != set(citation_ids):
            protocol_errors.append("Evaluator citation set does not match supplied citations")
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
            unit_sha256 = _string_from(assessment.unit_sha256)
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
            if unit_sha256 != _string_from(expected_unit.get("sha256")):
                protocol_errors.append(f"Evaluator answer-unit hash does not match: {unit_id}")
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
                    "unitSha256": unit_sha256,
                    "supported": bool(assessment.supported),
                    "evidenceIds": list(evidence_ids),
                }
            )
        if seen_unit_ids != set(expected_units):
            protocol_errors.append("Evaluator did not assess every answer unit exactly once")
        unused_citation_ids = [
            citation_id for citation_id in citation_ids if citation_id not in used_supported_evidence_ids
        ]
        if unused_citation_ids and structured.verdict == "grounded" and not unsupported_claims:
            protocol_errors.append(
                f"Cited knowledge was not used by any supported answer unit: {', '.join(unused_citation_ids)}"
            )

        contradictions = tuple(
            dict.fromkeys(
                contradiction
                for contradiction in (_string_from(value)[:500] for value in structured.contradictions[:20])
                if contradiction
            )
        )
        clean_unsupported = tuple(dict.fromkeys(unsupported_claims))
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
                claim_count=min(len(structured.unit_assessments), _GROUNDING_MAX_UNITS),
                unsupported_claims=clean_unsupported,
                contradictions=contradictions,
                provider=provider,
                model=model,
                error="; ".join(dict.fromkeys(protocol_errors))[:1_000],
            )
        if structured.verdict != "grounded" or clean_unsupported or contradictions:
            return AutomationGroundingAssessment(
                verified=False,
                status="failed",
                reason_code="ungrounded_answer",
                checked_at=checked_at,
                citation_ids=citation_ids,
                evidence_snapshots=snapshots,
                context_snapshots=context_snapshots,
                answer_sha256=answer_sha256,
                answer_units=audit_answer_units,
                unit_assessments=tuple(clean_unit_assessments),
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
            citation_ids=citation_ids,
            evidence_snapshots=snapshots,
            context_snapshots=context_snapshots,
            answer_sha256=answer_sha256,
            answer_units=audit_answer_units,
            unit_assessments=tuple(clean_unit_assessments),
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
            provider=provider,
            model=model,
            error=str(exc)[:1_000],
        )
    finally:
        if not deferred_slot_release:
            invocation_usage.merge_into(parent_usage_collector)
            slot_semaphore.release()
