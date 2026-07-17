"""Intent pipeline: classify concerns and execute matched runbooks."""

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain.agents.structured_output import ToolStrategy
from langgraph.errors import GraphRecursionError

from automail.integrations.http_tool import current_generated_attachments, current_tool_calls
from automail.llm.usage import llm_stage
from automail.models import (
    AgentResponse,
    AnswerObligation,
    ConcernRoute,
    Email,
    IdentityResult,
    IntentAction,
    IntentProcessingOutput,
    IntentResponseConfig,
    IntentResult,
    IntentReviewOutput,
    RunbookActionOutcome,
    RunbookAttachment,
    RunbookOutcome,
    RunbookToolEvidence,
    VerifiedFact,
)
from automail.pipeline.intent.activate_intent import (
    activate_intent,
    no_match,
    route_concerns,
    use_intents_dir,
)
from automail.pipeline.intent.classification import _CLASSIFY_SYSTEM_PROMPT
from automail.pipeline.intent.helpers import (
    _append_feedback_learnings,
    _build_intent_http_tools,
    _build_intents_list,
    _build_process_user_message,
    _find_activated_intent,
    _find_no_match_reason,
    _find_routed_concerns,
    _format_attachment_context,
    _invoke_agent,
    _is_open_ticket_button,
    _load_intent_feedback_learnings,
)
from automail.pipeline.intent.intents_factory import (
    get_intent_actions,
    get_intent_body,
    get_intent_require_review,
    get_intent_response_attachments,
    get_intent_response_config,
    get_intent_tools,
    get_known_intent_names,
)

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_PROCESSING_SECURITY_BOUNDARY = (
    _PROMPTS_DIR / "processing_security_boundary.md"
).read_text(encoding="utf-8").strip()


def _action_is_enabled(raw: dict[str, Any]) -> bool:
    value = raw.get("enabled")
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"false", "0", "no", "off"}


def _load_intent_actions(intent_name: str, intents_dir: Any = None) -> list[IntentAction]:
    actions: list[IntentAction] = []
    for raw in get_intent_actions(intent_name, intents_dir=intents_dir):
        try:
            if not _action_is_enabled(raw):
                continue
            actions.append(IntentAction(**raw))
        except Exception as exc:
            logger.warning("Invalid action in intent '%s': %s", intent_name, exc)
    return actions


def _load_response_config(intent_name: str, intents_dir: Any = None) -> IntentResponseConfig:
    raw = get_intent_response_config(intent_name, intents_dir=intents_dir)
    try:
        return IntentResponseConfig(**raw)
    except Exception as exc:
        logger.warning("Invalid response config in intent '%s': %s", intent_name, exc)
        return IntentResponseConfig()


def _build_intent_result(intent_name: str, intents_dir: Any = None) -> IntentResult:
    return IntentResult(
        matched=True,
        intent_name=intent_name,
        actions=_load_intent_actions(intent_name, intents_dir=intents_dir),
        response=_load_response_config(intent_name, intents_dir=intents_dir),
    )


def _intent_needs_processing(
    intent_name: str,
    actions: list[IntentAction],
    intents_dir: Any = None,
    *,
    response_enabled: bool,
) -> bool:
    # ``response_enabled`` remains in the signature for single-concern callers.
    # Runbooks now own all tool/action work; ticket-level reply composition is a
    # separate phase and never owns runbook tools.
    del response_enabled
    return bool(actions or get_intent_tools(intent_name, intents_dir=intents_dir))


def _merge_action_fills(actions: list[IntentAction], output: IntentProcessingOutput) -> int:
    fills_by_name = {f.name: f.initial_value for f in output.action_fills if f.initial_value}
    for action in actions:
        if action.name in fills_by_name:
            action.initial_value = fills_by_name[action.name]
        alt_name = action.name.replace("-", "_")
        if alt_name in fills_by_name:
            action.initial_value = fills_by_name[alt_name]
    return len(fills_by_name)


def _default_open_ticket_task(email: Email) -> str:
    subject = " ".join(email.subject.split())
    body = " ".join(email.body.split())
    if subject and body and not body.casefold().startswith(subject.casefold()):
        task = f"{subject}: {body}"
    else:
        task = body or subject
    return task[:1000].rstrip()


def _ensure_open_ticket_action_task(actions: list[IntentAction], email: Email) -> int:
    task = _default_open_ticket_task(email)
    if not task:
        return 0

    filled = 0
    for action in actions:
        if _is_open_ticket_button(action) and not str(action.initial_value or "").strip():
            action.initial_value = task
            filled += 1
    return filled


def _classification_user_prompt(
    email: Email,
    parsed_attachments: dict[str, str] | None = None,
) -> str:
    prompt = (
        f"Subject: {email.subject}\n"
        f"From: {email.from_address}\n\n"
        f"{email.body}"
    )
    attachment_context = _format_attachment_context(parsed_attachments)
    if attachment_context:
        prompt += f"\n\n## Attachments\n{attachment_context}"
    return prompt


def _concern_processing_email(
    email: Email,
    route: ConcernRoute,
) -> tuple[Email, Email]:
    """Return focused fallback input plus processing input with shared context.

    Routers intentionally extract only the text that belongs to each concern.
    Shared identifiers such as order, contract, or tracking numbers can sit
    elsewhere in the original message, though. Runbook processing therefore
    receives both the routed concern and the full original message while
    deterministic action fallbacks stay scoped to the concern alone.
    """
    focused = email.model_copy(
        update={
            "subject": route.summary or email.subject,
            "body": route.source_text or email.body,
        }
    )
    if focused.subject == email.subject and focused.body == email.body:
        return focused, focused

    processing = focused.model_copy(
        update={
            "body": (
                "## Routed concern to process\n"
                f"{focused.body}\n\n"
                "## Full original customer message context\n"
                f"Subject: {email.subject}\n\n"
                f"{email.body}"
            )
        }
    )
    return focused, processing


def _run_intent_router_agent(
    email: Email,
    known_intents: set[str],
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    tenant_id: str | None,
    project_id: str | None,
) -> tuple[list[ConcernRoute], str | None]:
    from automail.core.config import read_config
    from automail.llm import create_llm, resolve_effective_config

    config = read_config(config_path=config_path)
    config = resolve_effective_config(config, tenant_id, project_id)
    llm = create_llm(config, timeout=180, max_retries=2)
    usage_context = getattr(llm, "_mantly_usage_context", None)

    try:
        # One tool call carries every concern. Tool and graph limits keep router
        # behavior bounded even when a model ignores the prompt.
        agent = create_agent(
            model=llm,
            tools=[route_concerns, activate_intent, no_match],
            system_prompt=_CLASSIFY_SYSTEM_PROMPT.format(
                intents_list=_build_intents_list(intents_dir=intents_dir),
            ),
            response_format=None,
            middleware=[
                ToolCallLimitMiddleware(
                    run_limit=1,
                    exit_behavior="error",
                )
            ],
        )

        with use_intents_dir(intents_dir), llm_stage("intent"):
            raw_result = _invoke_agent(
                agent,
                _classification_user_prompt(email, parsed_attachments),
                parsed_attachments=parsed_attachments,
                usage_context=usage_context,
                run_name="intent_router_agent",
                tags=["mantly", "intent", "router"],
                metadata={
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "source": "pipeline.intent.agent",
                },
                recursion_limit=4,
            )
    except (GraphRecursionError, ToolCallLimitExceededError) as exc:
        logger.error("Intent router stopped at its execution limit: %s", exc)
        return [], "Intent classification stopped safely; human review is required."

    messages = raw_result.get("messages")
    if not isinstance(messages, list):
        logger.info("Intent router returned no messages")
        return [], "No concerns were routed."

    routed = _find_routed_concerns(messages)
    if routed:
        canonical_names = {name.casefold(): name for name in known_intents}
        normalized: list[ConcernRoute] = []
        for concern in routed[:3]:
            intent_name = str(concern.intent_name or "").strip()
            canonical_name = canonical_names.get(intent_name.casefold()) if intent_name else None
            reason = concern.reason.strip()
            if intent_name and not canonical_name:
                logger.warning("Intent router selected unknown intent '%s'", intent_name)
                reason = f"Router selected unknown intent: {intent_name}"
            normalized.append(ConcernRoute(
                summary=concern.summary.strip(),
                source_text=concern.source_text.strip(),
                answer_obligations=_dedupe_strings(concern.answer_obligations)[:10],
                intent_name=canonical_name,
                confidence=concern.confidence,
                reason=reason or ("" if canonical_name else "No configured intent matches this concern."),
            ))
        return normalized, None

    if routed == []:
        return [], "Intent router returned no usable concerns."

    # Backward-compatible single-concern route for older model/tool-call caches.
    legacy_intent = _find_activated_intent(messages)
    if legacy_intent:
        canonical_names = {name.casefold(): name for name in known_intents}
        canonical_name = canonical_names.get(legacy_intent.casefold())
        if canonical_name:
            return [ConcernRoute(
                summary=email.subject,
                source_text=email.body,
                intent_name=canonical_name,
                confidence=1.0,
            )], None
        return [ConcernRoute(
            summary=email.subject,
            source_text=email.body,
            confidence=0.0,
            reason=f"Router selected unknown intent: {legacy_intent}",
        )], None

    legacy_no_match = _find_no_match_reason(messages)
    if legacy_no_match is not None:
        return [ConcernRoute(
            summary=email.subject,
            source_text=email.body,
            reason=legacy_no_match or "No configured intent matches this email.",
        )], None

    logger.info("Intent router returned no tool call")
    return [], "No concerns were routed."


def _run_processing_agent(
    intent_name: str,
    actions: list[IntentAction],
    email: Email,
    identity_result: IdentityResult | None,
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    tenant_id: str | None,
    project_id: str | None,
) -> IntentProcessingOutput | IntentReviewOutput:
    from automail.core.config import read_config
    from automail.llm import create_llm, resolve_effective_config

    intent_body = get_intent_body(intent_name, intents_dir=intents_dir)
    if not intent_body:
        intent_body = f"Process the matched intent: {intent_name}"
    intent_body = _append_feedback_learnings(
        intent_body,
        _load_intent_feedback_learnings(
            intent_name,
            tenant_id,
            project_id=project_id,
            intents_dir=intents_dir,
            target="processing",
        ),
    )
    intent_body = (
        f"{_PROCESSING_SECURITY_BOUNDARY}\n\n"
        "When the user message contains a routed concern and full original "
        "message context, process only the routed concern. Use identifiers and "
        "shared facts from the original context when they apply, but do not "
        "perform work for unrelated concerns.\n\n"
        "## Configured runbook\n\n"
        f"{intent_body}"
    )

    http_tools = _build_intent_http_tools(
        intent_name,
        email.from_address,
        intents_dir=intents_dir,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    user_prompt = _build_process_user_message(
        email,
        identity_result,
        actions,
        parsed_attachments,
    )

    logger.info(
        "Running intent processing: intent='%s', tools=%d, actions=%d",
        intent_name,
        len(http_tools),
        len(actions),
    )

    config = read_config(config_path=config_path)
    config = resolve_effective_config(config, tenant_id, project_id)
    llm = create_llm(config, timeout=180, max_retries=2)
    usage_context = getattr(llm, "_mantly_usage_context", None)

    response_model = IntentProcessingOutput if actions else IntentReviewOutput

    agent = create_agent(
        model=llm,
        tools=http_tools,
        system_prompt=intent_body,
        response_format=ToolStrategy(response_model),
    )

    with llm_stage("intent"):
        raw_result = _invoke_agent(
            agent,
            user_prompt,
            parsed_attachments=parsed_attachments,
            usage_context=usage_context,
            run_name="intent_processing_agent",
            tags=["mantly", "intent", "processing"],
            metadata={
                "tenant_id": tenant_id,
                "project_id": project_id,
                "intent_name": intent_name,
                "tool_count": len(http_tools),
                "action_count": len(actions),
                "source": "pipeline.intent.agent",
            },
        )

    structured = raw_result.get("structured_response")
    if not isinstance(structured, response_model):
        logger.warning(
            "Intent processing returned unexpected structured output: %s",
            type(structured).__name__,
        )
        return response_model(
            requires_human=True,
            requires_human_reason="Intent processing returned no usable structured output.",
        )

    return structured


def _dedupe_strings(*groups: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            item = str(raw or "").strip()
            key = item.casefold()
            if item and key not in seen:
                result.append(item)
                seen.add(key)
    return result


_OBLIGATION_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "can",
    "could",
    "do",
    "does",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "or",
    "please",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "would",
    "you",
}


def _obligation_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", value.casefold()):
        if raw in _OBLIGATION_STOP_WORDS:
            continue
        token = raw
        if len(token) > 5 and token.endswith("ing"):
            token = token[:-3]
        elif len(token) > 4 and token.endswith("ed"):
            token = token[:-2]
        elif len(token) > 4 and token.endswith("s"):
            token = token[:-1]
        tokens.add(token)
    return tokens


def _obligation_covers_question(obligation: str, question: str) -> bool:
    question_tokens = _obligation_tokens(question)
    if not question_tokens:
        return " ".join(question.casefold().split()) in " ".join(obligation.casefold().split())
    obligation_tokens = _obligation_tokens(obligation)
    return len(question_tokens & obligation_tokens) / len(question_tokens) >= 0.6


def _answer_obligations(
    concern_id: str,
    route: ConcernRoute,
) -> list[AnswerObligation]:
    """Bind router-extracted questions to stable runtime IDs."""
    routed_questions = _dedupe_strings(route.answer_obligations)
    explicit_questions = _dedupe_strings([
        match.group(0).strip()
        for match in re.finditer(r"[^.!?\n]*\?", route.source_text)
        if match.group(0).strip()
    ])
    questions = list(explicit_questions)
    for routed_question in routed_questions:
        if any(_obligation_covers_question(routed_question, question) for question in explicit_questions):
            continue
        questions.append(routed_question)
    if not questions:
        fallback = route.summary.strip() or route.source_text.strip()
        questions = [fallback] if fallback else []
    return [
        AnswerObligation(
            obligation_id=f"{concern_id}:obligation-{index}",
            question=question[:500],
            source_text=route.source_text[:1_000],
        )
        for index, question in enumerate(questions[:10], start=1)
    ]


def _new_tool_evidence(start_index: int) -> list[RunbookToolEvidence]:
    """Convert this concern's safe HTTP audit facts into composer evidence."""
    evidence: list[RunbookToolEvidence] = []
    for call in current_tool_calls()[start_index:]:
        tool_name = str(call.get("name") or "").strip()
        if not tool_name:
            continue
        facts: list[VerifiedFact] = []
        for raw_fact in call.get("responseFacts") or []:
            if not isinstance(raw_fact, dict):
                continue
            path = str(raw_fact.get("path") or "").strip()
            value = raw_fact.get("value")
            if not path or not isinstance(value, (str, bool, int, float)):
                continue
            facts.append(VerifiedFact(
                path=path,
                value=value,
                source=f"tool:{tool_name}",
            ))
        evidence.append(RunbookToolEvidence(
            tool_name=tool_name,
            facts=facts,
            status=str(call.get("status") or "unknown"),
        ))
    return evidence


def _outcome_attachments(
    intent_name: str,
    intents_dir: Any,
    generated_start_index: int,
) -> list[RunbookAttachment]:
    attachments: list[RunbookAttachment] = []
    try:
        configured = get_intent_response_attachments(intent_name, intents_dir=intents_dir)
    except Exception as exc:
        logger.warning("Could not load attachments for intent '%s': %s", intent_name, exc)
        configured = []
    for item in configured:
        filename = str(item.get("filename") or "").strip()
        if filename:
            attachments.append(RunbookAttachment(
                filename=filename,
                description=str(item.get("description") or "").strip(),
                source="runbook",
                mode=str(item.get("mode") or "dynamic"),
            ))
    for item in current_generated_attachments()[generated_start_index:]:
        filename = str(item.get("filename") or "").strip()
        if filename and item.get("attach_to_response", True):
            attachments.append(RunbookAttachment(
                filename=filename,
                description=f"Generated by {str(item.get('source_tool') or 'runbook tool')}",
                source="tool",
                mode="generated",
            ))
    deduped: dict[str, RunbookAttachment] = {}
    for attachment in attachments:
        deduped.setdefault(attachment.filename, attachment)
    return list(deduped.values())


def _action_outcomes(actions: list[IntentAction]) -> list[RunbookActionOutcome]:
    outcomes: list[RunbookActionOutcome] = []
    for action in actions:
        needs_value = action.type in {"dropdown", "calendar", "input"} or _is_open_ticket_button(action)
        status = "pending_input" if needs_value and not str(action.initial_value or "").strip() else "proposed"
        outcomes.append(RunbookActionOutcome(
            name=action.name,
            label=action.label,
            status=status,
            initial_value=action.initial_value,
        ))
    return outcomes


def _verified_facts(evidence: list[RunbookToolEvidence]) -> list[VerifiedFact]:
    facts: list[VerifiedFact] = []
    seen: set[tuple[str, str, str, str]] = set()
    for fact in (fact for item in evidence for fact in item.facts):
        key = (fact.fact, fact.path, repr(fact.value), fact.source)
        if key not in seen:
            facts.append(fact)
            seen.add(key)
    return facts


def _execute_routed_concern(
    concern_id: str,
    route: ConcernRoute,
    email: Email,
    identity_result: IdentityResult | None,
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    tenant_id: str | None,
    project_id: str | None,
) -> RunbookOutcome:
    intent_name = str(route.intent_name or "").strip()
    if not intent_name:
        reason = route.reason or "No configured intent matches this concern."
        return RunbookOutcome(
            concern_id=concern_id,
            concern_summary=route.summary,
            source_text=route.source_text,
            answer_obligations=_answer_obligations(concern_id, route),
            confidence=route.confidence,
            matched=False,
            status="unmatched",
            summary=reason,
            missing_information=[reason],
            requires_human=True,
            requires_human_reason=reason,
        )

    intent_result = _build_intent_result(intent_name, intents_dir=intents_dir)
    requires_review = get_intent_require_review(intent_name, intents_dir=intents_dir)
    focused_email, processing_email = _concern_processing_email(email, route)
    generated_start_index = len(current_generated_attachments())
    tool_start_index = len(current_tool_calls())
    output: IntentProcessingOutput | IntentReviewOutput = IntentReviewOutput()
    fills_count = 0

    if _intent_needs_processing(
        intent_name,
        intent_result.actions,
        intents_dir=intents_dir,
        response_enabled=False,
    ):
        output = _run_processing_agent(
            intent_name,
            intent_result.actions,
            processing_email,
            identity_result,
            intents_dir,
            config_path,
            parsed_attachments,
            tenant_id,
            project_id,
        )
        if intent_result.actions and isinstance(output, IntentProcessingOutput):
            fills_count = _merge_action_fills(intent_result.actions, output)
            fills_count += _ensure_open_ticket_action_task(intent_result.actions, focused_email)
    else:
        logger.info("Intent '%s' requires no tool or action processing", intent_name)

    audited_evidence = _new_tool_evidence(tool_start_index)
    tool_evidence = audited_evidence
    review_reasons = []
    if requires_review:
        review_reasons.append("Intent is configured to require human review.")
    if output.requires_human:
        review_reasons.append(output.requires_human_reason or "Intent processing requires human review.")
    requires_human_reason = "; ".join(_dedupe_strings(review_reasons)) or None

    logger.info(
        "Runbook outcome: concern=%s, intent=%s, actions=%d, fills=%d, evidence=%d",
        concern_id,
        intent_name,
        len(intent_result.actions),
        fills_count,
        len(tool_evidence),
    )
    return RunbookOutcome(
        concern_id=concern_id,
        concern_summary=route.summary,
        source_text=route.source_text,
        answer_obligations=_answer_obligations(concern_id, route),
        confidence=route.confidence,
        matched=True,
        intent_name=intent_name,
        status="requires_human" if requires_human_reason else "ready",
        summary=output.summary or route.summary,
        actions=intent_result.actions,
        action_outcomes=_action_outcomes(intent_result.actions),
        verified_facts=_verified_facts(tool_evidence),
        tool_evidence=tool_evidence,
        missing_information=output.missing_information,
        reply_requirements=_dedupe_strings(
            intent_result.response.response_rules,
            output.reply_requirements,
        ),
        forbidden_claims=output.forbidden_claims,
        attachments=_outcome_attachments(intent_name, intents_dir, generated_start_index),
        requires_human=bool(requires_human_reason),
        requires_human_reason=requires_human_reason,
    )


def _failed_outcome(
    concern_id: str,
    route: ConcernRoute,
    exc: Exception,
) -> RunbookOutcome:
    reason = f"Runbook processing failed: {exc}"
    return RunbookOutcome(
        concern_id=concern_id,
        concern_summary=route.summary,
        source_text=route.source_text,
        answer_obligations=_answer_obligations(concern_id, route),
        confidence=route.confidence,
        matched=bool(route.intent_name),
        intent_name=route.intent_name,
        status="failed",
        summary=reason,
        requires_human=True,
        requires_human_reason=reason,
        error=str(exc),
    )


def _concern_route_identity(route: ConcernRoute) -> tuple[str, str]:
    """Return execution identity for a routed concern."""
    return (
        str(route.intent_name or "unmatched").strip().casefold(),
        " ".join(route.source_text.split()).casefold(),
    )


def _dedupe_concern_routes(routes: list[ConcernRoute]) -> list[ConcernRoute]:
    """Keep the first copy of each routed concern before runbook execution."""
    deduplicated: list[ConcernRoute] = []
    seen: set[tuple[str, str]] = set()
    for route in routes:
        identity = _concern_route_identity(route)
        if identity in seen:
            logger.warning(
                "Suppressing duplicate routed concern for intent '%s'",
                route.intent_name or "unmatched",
            )
            continue
        seen.add(identity)
        deduplicated.append(route)
    return deduplicated


def _concern_id(
    email: Email,
    route: ConcernRoute,
    occurrences: dict[str, int],
) -> str:
    """Build stable concern identity from immutable message and routed source."""
    normalized_intent, normalized_source = _concern_route_identity(route)
    identity = "\x00".join((
        email.id,
        normalized_intent,
        normalized_source,
    ))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    base = f"concern-{digest}"
    occurrences[base] = occurrences.get(base, 0) + 1
    occurrence = occurrences[base]
    return base if occurrence == 1 else f"{base}-{occurrence}"


def _intent_result_from_outcomes(outcomes: list[RunbookOutcome], intents_dir: Any) -> IntentResult:
    primary = next((outcome for outcome in outcomes if outcome.matched and outcome.intent_name), None)
    if primary is not None:
        return IntentResult(
            matched=True,
            intent_name=primary.intent_name,
            actions=primary.actions,
            response=_load_response_config(primary.intent_name, intents_dir=intents_dir),
            concerns=outcomes,
            error=primary.error,
        )
    reasons = _dedupe_strings([
        outcome.requires_human_reason or outcome.error or outcome.summary
        for outcome in outcomes
    ])
    return IntentResult(
        concerns=outcomes,
        error="; ".join(reasons) or "No configured intent matches this email.",
    )


def _review_response_from_outcomes(outcomes: list[RunbookOutcome]) -> AgentResponse | None:
    needs_review = [outcome for outcome in outcomes if outcome.requires_human]
    if not needs_review:
        return None
    reasons = _dedupe_strings([
        outcome.requires_human_reason or outcome.error or "Concern requires human review."
        for outcome in needs_review
    ])
    primary = next((outcome for outcome in outcomes if outcome.matched and outcome.intent_name), None)
    return AgentResponse(
        response_text="",
        activated_intent=primary.intent_name if primary else None,
        requires_human=True,
        requires_human_reason="; ".join(reasons),
    )


def _handle_matched_intent(
    intent_name: str,
    email: Email,
    identity_result: IdentityResult | None,
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    creator: str | None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> tuple[IntentResult, AgentResponse | None]:
    del creator
    route = ConcernRoute(
        summary=email.subject,
        source_text=email.body,
        intent_name=intent_name,
        confidence=1.0,
    )
    occurrences: dict[str, int] = {}
    concern_id = _concern_id(email, route, occurrences)
    try:
        outcome = _execute_routed_concern(
            concern_id,
            route,
            email,
            identity_result,
            intents_dir,
            config_path,
            parsed_attachments,
            tenant_id,
            project_id,
        )
    except Exception as exc:
        logger.error("Runbook '%s' failed: %s", intent_name, exc, exc_info=True)
        outcome = _failed_outcome(concern_id, route, exc)
    outcomes = [outcome]
    return (
        _intent_result_from_outcomes(outcomes, intents_dir),
        _review_response_from_outcomes(outcomes),
    )


def run_intent_agent(
    email: Email,
    identity_result: IdentityResult | None = None,
    intents_dir: Any = None,
    config_path: Any = None,
    parsed_attachments: dict[str, str] | None = None,
    creator: str | None = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> tuple[IntentResult, AgentResponse | None]:
    """Classify up to three concerns and execute each matched runbook."""
    known_intents = get_known_intent_names(intents_dir=intents_dir)
    if not known_intents:
        logger.info("No intents configured; skipping intent phase")
        return IntentResult(), None

    logger.info("Running intent agent for email: subject='%s'", email.subject)

    routes, router_error = _run_intent_router_agent(
        email,
        known_intents,
        intents_dir,
        config_path,
        parsed_attachments,
        tenant_id,
        project_id,
    )
    del creator
    routes = _dedupe_concern_routes(routes)
    if not routes:
        reason = router_error or "No configured intent matches this email."
        routes = [ConcernRoute(
            summary=email.subject,
            source_text=email.body,
            reason=reason,
        )]

    outcomes: list[RunbookOutcome] = []
    occurrences: dict[str, int] = {}
    for route in routes[:3]:
        concern_id = _concern_id(email, route, occurrences)
        try:
            outcome = _execute_routed_concern(
                concern_id,
                route,
                email,
                identity_result,
                intents_dir,
                config_path,
                parsed_attachments,
                tenant_id,
                project_id,
            )
        except Exception as exc:
            logger.error(
                "Runbook concern %s (%s) failed: %s",
                concern_id,
                route.intent_name,
                exc,
                exc_info=True,
            )
            outcome = _failed_outcome(concern_id, route, exc)
        outcomes.append(outcome)

    return (
        _intent_result_from_outcomes(outcomes, intents_dir),
        _review_response_from_outcomes(outcomes),
    )
