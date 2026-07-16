"""Intent pipeline: classify, optionally process, then optionally draft."""

import logging
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain.agents.structured_output import ToolStrategy
from langgraph.errors import GraphRecursionError

from automail.integrations.http_tool import current_generated_attachments
from automail.llm.usage import llm_stage
from automail.models import (
    AgentResponse,
    Email,
    IdentityResult,
    IntentAction,
    IntentProcessingOutput,
    IntentResponseConfig,
    IntentResult,
    IntentReviewOutput,
    ResponseDraft,
)
from automail.pipeline.intent.activate_intent import activate_intent, no_match, use_intents_dir
from automail.pipeline.intent.classification import _CLASSIFY_SYSTEM_PROMPT
from automail.pipeline.intent.helpers import (
    _append_feedback_learnings,
    _build_intent_http_tools,
    _build_intents_list,
    _build_process_user_message,
    _find_activated_intent,
    _find_no_match_reason,
    _format_attachment_context,
    _generated_attachment_prompt_items,
    _invoke_agent,
    _load_intent_feedback_learnings,
)
from automail.pipeline.intent.intents_factory import (
    get_intent_actions,
    get_intent_body,
    get_intent_require_review,
    get_intent_response_config,
    get_intent_tools,
    get_known_intent_names,
)

logger = logging.getLogger(__name__)


def _load_intent_actions(intent_name: str, intents_dir: Any = None) -> list[IntentAction]:
    actions: list[IntentAction] = []
    for raw in get_intent_actions(intent_name, intents_dir=intents_dir):
        try:
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
    if actions:
        return True
    tools = get_intent_tools(intent_name, intents_dir=intents_dir)
    if not tools:
        return False
    response_owns_tools = response_enabled and all(
        isinstance(item, dict) and str(item.get("method") or "").upper() == "GET"
        for item in tools
    )
    return not response_owns_tools


def _merge_action_fills(actions: list[IntentAction], output: IntentProcessingOutput) -> int:
    fills_by_name = {f.name: f.initial_value for f in output.action_fills if f.initial_value}
    for action in actions:
        if action.name in fills_by_name:
            action.initial_value = fills_by_name[action.name]
        alt_name = action.name.replace("-", "_")
        if alt_name in fills_by_name:
            action.initial_value = fills_by_name[alt_name]
    return len(fills_by_name)


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


def _run_intent_router_agent(
    email: Email,
    known_intents: set[str],
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    tenant_id: str | None,
    project_id: str | None,
) -> tuple[str | None, str | None]:
    from automail.core.config import read_config
    from automail.llm import create_llm, resolve_effective_config

    config = read_config(config_path=config_path)
    config = resolve_effective_config(config, tenant_id, project_id)
    llm = create_llm(config, timeout=180, max_retries=2)
    usage_context = getattr(llm, "_mantly_usage_context", None)

    try:
        # The router makes one classification decision. Returning directly from
        # either tool is the primary stop condition; the middleware and graph
        # limit are independent guards against future tool or prompt changes.
        agent = create_agent(
            model=llm,
            tools=[activate_intent, no_match],
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
        return None, "Intent classification stopped safely; human review is required."

    messages = raw_result.get("messages")
    if not isinstance(messages, list):
        logger.info("Intent router returned no messages")
        return None, "No matching intent was activated."

    intent_name = _find_activated_intent(messages)
    if intent_name:
        if intent_name.lower() in known_intents:
            return intent_name, None
        logger.warning("Intent router activated unknown intent '%s'", intent_name)
        return None, f"Router activated unknown intent: {intent_name}"

    reason = _find_no_match_reason(messages)
    if reason is not None:
        return None, reason or "No configured intent matches this email."

    logger.info("Intent router returned no tool call")
    return None, "No matching intent was activated."


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


def _run_response_agent(
    email: Email,
    identity_result: IdentityResult | None,
    intent_name: str,
    intents_dir: Any = None,
    config_path: Any = None,
    creator: str | None = None,
    parsed_attachments: dict[str, str] | None = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> AgentResponse:
    """Run the response agent to draft an email reply."""
    from automail.core.config import read_config
    from automail.llm import create_llm, resolve_effective_config
    from automail.pipeline.intent.intents_factory import get_intent_response_attachments
    from automail.pipeline.response.prompt_factory import (
        create_response_system_prompt,
        create_response_user_prompt,
    )

    config = read_config(config_path=config_path)
    config = resolve_effective_config(config, tenant_id, project_id)

    system_prompt = create_response_system_prompt(
        intent_name=intent_name,
        tenant_id=tenant_id,
        config_path=config_path,
        intents_dir=intents_dir,
    )

    response_attachments_meta = get_intent_response_attachments(
        intent_name,
        intents_dir=intents_dir,
    )
    available_response_attachments = [
        *response_attachments_meta,
        *_generated_attachment_prompt_items(),
    ]
    always_filenames = [
        a["filename"] for a in response_attachments_meta if a.get("mode") == "always"
    ]

    intent_result_for_prompt = IntentResult(
        matched=True,
        intent_name=intent_name,
        response=_load_response_config(intent_name, intents_dir=intents_dir),
    )

    intent_learnings = _load_intent_feedback_learnings(
        intent_name,
        tenant_id,
        project_id=project_id,
        intents_dir=intents_dir,
        target="response",
    ) or None

    user_prompt = create_response_user_prompt(
        email,
        parsed_attachments,
        creator=creator,
        identity_result=identity_result,
        intent_result=intent_result_for_prompt,
        tenant_id=tenant_id,
        intents_dir=intents_dir,
        intent_learnings=intent_learnings,
        available_response_attachments=available_response_attachments,
        company_name=config.org_name,
        company_description=config.org_description,
    )
    response_tools = _build_intent_http_tools(
        intent_name,
        email.from_address,
        intents_dir=intents_dir,
        tenant_id=tenant_id,
        project_id=project_id,
        read_only_only=True,
    )
    response_llm = create_llm(config, timeout=120, max_retries=3)
    usage_context = getattr(response_llm, "_mantly_usage_context", None)

    agent = create_agent(
        model=response_llm,
        tools=response_tools,
        system_prompt=system_prompt,
        response_format=ToolStrategy(ResponseDraft),
    )

    with llm_stage("response"):
        result = _invoke_agent(
            agent,
            user_prompt,
            usage_context=usage_context,
            run_name="response_agent",
            tags=["mantly", "response", "agent"],
            metadata={
                "tenant_id": tenant_id,
                "project_id": project_id,
                "intent_name": intent_name,
                "tool_count": len(response_tools),
                "attachment_count": len(parsed_attachments or {}),
                "available_response_attachment_count": len(available_response_attachments),
                "generated_attachment_count": len(_generated_attachment_prompt_items()),
                "source": "pipeline.intent.agent",
            },
        )

    draft: ResponseDraft | None = result.get("structured_response")
    if not draft:
        raise ValueError("Response agent returned no structured response.")

    structured = AgentResponse(
        response_text=draft.response_text,
        response_attachments=draft.response_attachments,
        response_cc=draft.response_cc,
        response_bcc=draft.response_bcc,
        activated_intent=intent_name,
    )

    if always_filenames:
        existing = set(structured.response_attachments or [])
        merged = list(structured.response_attachments or [])
        for fname in always_filenames:
            if fname not in existing:
                merged.append(fname)
        structured.response_attachments = merged

    from automail.pipeline.response.agent import _validate_response

    known_intents = get_known_intent_names(intents_dir=intents_dir)
    generated_filenames = {
        str(attachment.get("filename") or "").strip()
        for attachment in current_generated_attachments()
        if attachment.get("attach_to_response", True)
    }
    generated_filenames.discard("")
    return _validate_response(
        structured,
        known_intents,
        intents_dir=intents_dir,
        extra_valid_attachment_filenames=generated_filenames,
    )


def _maybe_draft_response(
    intent_result: IntentResult,
    email: Email,
    identity_result: IdentityResult | None,
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    creator: str | None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> AgentResponse | None:
    """Run the response agent when intent response drafting is enabled."""
    if not intent_result.matched or not intent_result.intent_name:
        return None

    if get_intent_require_review(intent_result.intent_name, intents_dir=intents_dir):
        logger.info(
            "Intent '%s' requires human review; skipping response agent",
            intent_result.intent_name,
        )
        return AgentResponse(
            response_text="",
            activated_intent=intent_result.intent_name,
            requires_human=True,
            requires_human_reason="Intent is configured to require human review.",
        )

    if not intent_result.response.enabled:
        logger.info(
            "Intent '%s' has response drafting disabled",
            intent_result.intent_name,
        )
        return None

    logger.info("Running response agent for intent '%s'", intent_result.intent_name)
    try:
        return _run_response_agent(
            email=email,
            identity_result=identity_result,
            intent_name=intent_result.intent_name,
            intents_dir=intents_dir,
            config_path=config_path,
            creator=creator,
            parsed_attachments=parsed_attachments,
            tenant_id=tenant_id,
            project_id=project_id,
        )
    except Exception as exc:
        logger.error("Response agent failed: %s", exc, exc_info=True)
        return AgentResponse(
            response_text="",
            activated_intent=intent_result.intent_name,
            requires_human=True,
            requires_human_reason=f"Response generation failed: {exc}",
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
    intent_result = _build_intent_result(intent_name, intents_dir=intents_dir)

    if get_intent_require_review(intent_name, intents_dir=intents_dir):
        return intent_result, _maybe_draft_response(
            intent_result,
            email,
            identity_result,
            intents_dir,
            config_path,
            parsed_attachments,
            creator,
            tenant_id=tenant_id,
            project_id=project_id,
        )

    if _intent_needs_processing(
        intent_name,
        intent_result.actions,
        intents_dir=intents_dir,
        response_enabled=intent_result.response.enabled,
    ):
        output = _run_processing_agent(
            intent_name,
            intent_result.actions,
            email,
            identity_result,
            intents_dir,
            config_path,
            parsed_attachments,
            tenant_id,
            project_id,
        )
        fills_count = (
            _merge_action_fills(intent_result.actions, output)
            if intent_result.actions and isinstance(output, IntentProcessingOutput)
            else 0
        )
        if output.requires_human:
            intent_result.error = output.requires_human_reason
            return intent_result, AgentResponse(
                response_text="",
                activated_intent=intent_name,
                requires_human=True,
                requires_human_reason=output.requires_human_reason or "Intent processing requires human review.",
            )
        logger.info(
            "Intent result: matched=true, intent=%s, actions=%d, fills=%d",
            intent_name,
            len(intent_result.actions),
            fills_count,
        )
    else:
        logger.info("Intent '%s' requires no separate processing stage", intent_name)

    agent_response = _maybe_draft_response(
        intent_result,
        email,
        identity_result,
        intents_dir,
        config_path,
        parsed_attachments,
        creator,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    return intent_result, agent_response


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
    """Classify the email, process concrete work, and optionally draft a response."""
    known_intents = get_known_intent_names(intents_dir=intents_dir)
    if not known_intents:
        logger.info("No intents configured; skipping intent phase")
        return IntentResult(), None

    logger.info("Running intent agent for email: subject='%s'", email.subject)

    intent_name, no_match_reason = _run_intent_router_agent(
        email,
        known_intents,
        intents_dir,
        config_path,
        parsed_attachments,
        tenant_id,
        project_id,
    )
    if intent_name:
        return _handle_matched_intent(
            intent_name,
            email,
            identity_result,
            intents_dir,
            config_path,
            parsed_attachments,
            creator,
            tenant_id=tenant_id,
            project_id=project_id,
        )

    reason = no_match_reason or "No configured intent matches this email."
    return (
        IntentResult(error=reason),
        AgentResponse(
            response_text="",
            requires_human=True,
            requires_human_reason=reason,
        ),
    )
