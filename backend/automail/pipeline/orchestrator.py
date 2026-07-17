"""Email processing pipeline.

Phase 1 — Identity Analysis  (HTTP tools → CRM lookup)
Phase 2 — Intent Analysis    (classify → process → optionally generate response)
Sidecars — Phishing + Prompt Injection Monitoring (warning-only)

Phases run sequentially: Phase 2 receives the identity result from Phase 1
so that the intent-processing stage has full customer context. Security
monitoring starts alongside Phase 1 and never blocks or changes response
policy beyond returning informational warning results.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from automail.core.config import read_config
from automail.integrations.http_tool import (
    begin_generated_attachment_collection,
    begin_tool_call_collection,
    collect_generated_attachments,
    collect_tool_calls,
)
from automail.llm.usage import collect_llm_usage
from automail.models import (
    AgentResponse,
    Email,
    GeneratedAttachment,
    IdentityResult,
    IntentResult,
    PhishingResult,
    PromptInjectionResult,
)
from automail.pipeline.identity.agent import run_identity_agent
from automail.pipeline.intent.agent import run_intent_agent
from automail.pipeline.security.phishing import detect_phishing, disabled_phishing_result
from automail.pipeline.security.prompt_injection import detect_prompt_injection, disabled_prompt_injection_result

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    identity_result: IdentityResult
    intent_result: IntentResult
    agent_response: AgentResponse
    phishing_result: PhishingResult
    prompt_injection_result: PromptInjectionResult
    token_usage: dict[str, Any]
    tools_used: list[dict[str, Any]]


def run_pipeline(
    email: Email,
    parsed_attachments: dict[str, str] | None = None,
    creator: str | None = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
    config_source: Any = None,
    compose_response: bool = True,
) -> PipelineResult:
    """Run the two-phase pipeline for an incoming email.

    Phase 1 (Identity) runs first, then Phase 2 (Intent) receives the identity
    result so runbook processing has full customer context. When requested, one
    message-level composer drafts a reply after every concern has finished.

    A failure in Phase 1 does not abort the pipeline — Phase 2 receives an
    empty identity result and continues best-effort.

    Args:
        email: The incoming email to process.
        parsed_attachments: Optional dict mapping filename → extracted text.
        creator: Email address of the user who triggered the analysis.
        tenant_id: Optional tenant ID for secrets resolution.
        project_id: Optional project ID for secrets resolution.
        config_source: Optional config source for draft/live PB pipeline storage.
        compose_response: Draft one combined reply. Channel ingestion disables
            this because its persisted ticket-level Inbox composer owns the reply.

    Returns:
        PipelineResult containing both phase outputs plus the agent response.
    """
    logger.info(
        "Starting pipeline: subject='%s', from='%s'",
        email.subject, email.from_address,
    )

    cs = config_source  # shorthand

    try:
        config = read_config(cs) if cs else read_config()
        if tenant_id:
            from automail.llm import resolve_effective_config

            config = resolve_effective_config(config, tenant_id, project_id)
        phishing_enabled = config.phishing_monitoring_enabled
        prompt_injection_enabled = config.prompt_injection_monitoring_enabled
        if tenant_id:
            try:
                from automail.billing.plans import has_feature
                if not has_feature(tenant_id, "security_monitoring"):
                    phishing_enabled = False
                    prompt_injection_enabled = False
            except Exception:
                logger.warning("Failed to resolve security monitoring plan gate", exc_info=True)
    except Exception as exc:
        logger.warning("Failed to read security monitoring config: %s", exc)
        phishing_enabled = False
        prompt_injection_enabled = False

    with collect_llm_usage() as token_collector:
        executor = ThreadPoolExecutor(max_workers=3)
        phishing_result = disabled_phishing_result()
        prompt_injection_result = disabled_prompt_injection_result()
        phishing_future = None
        prompt_injection_future = None
        identity_result = IdentityResult()
        intent_result = IntentResult()
        agent_response = None
        generated_token = begin_generated_attachment_collection()
        tool_call_token = begin_tool_call_collection()
        try:
            from contextvars import copy_context

            identity_context = copy_context()
            phishing_context = copy_context()
            prompt_injection_context = copy_context()
            identity_future = executor.submit(
                identity_context.run,
                run_identity_agent,
                email.from_address,
                config_path=cs if cs else None,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            phishing_future = executor.submit(
                phishing_context.run,
                detect_phishing,
                email,
                enabled=phishing_enabled,
                parsed_attachments=parsed_attachments,
                config_source=cs if cs else None,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            prompt_injection_future = executor.submit(
                prompt_injection_context.run,
                detect_prompt_injection,
                email,
                enabled=prompt_injection_enabled,
                parsed_attachments=parsed_attachments,
                config_source=cs if cs else None,
                tenant_id=tenant_id,
                project_id=project_id,
            )

            # ------------------------------------------------------------------
            # Phase 1: Identity Analysis
            # ------------------------------------------------------------------
            try:
                identity_result = identity_future.result()
            except Exception as exc:
                logger.error("Phase 1 (Identity) failed: %s — continuing with empty result", exc, exc_info=True)
                identity_result = IdentityResult(error=str(exc))

            # ------------------------------------------------------------------
            # Phase 2: Concern analysis and runbook processing
            # ------------------------------------------------------------------
            try:
                intent_result, agent_response = run_intent_agent(
                    email=email,
                    identity_result=identity_result,
                    intents_dir=cs if cs else None,
                    config_path=cs if cs else None,
                    parsed_attachments=parsed_attachments,
                    creator=creator,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
            except Exception as exc:
                logger.error("Phase 2 (Intent) failed: %s — using empty fallback", exc, exc_info=True)
                intent_result = IntentResult(error=str(exc))
                agent_response = None
            if compose_response and intent_result.matched:
                try:
                    from automail.pipeline.response.composer import compose_pipeline_reply

                    agent_response = compose_pipeline_reply(
                        email=email,
                        identity_result=identity_result,
                        intent_result=intent_result,
                        intents_dir=cs if cs else None,
                        config_path=cs if cs else None,
                        creator=creator,
                        parsed_attachments=parsed_attachments,
                        tenant_id=tenant_id,
                        project_id=project_id,
                    )
                except Exception as exc:
                    logger.error("Reply composer failed: %s", exc, exc_info=True)
                    agent_response = AgentResponse(
                        response_text="",
                        activated_intent=intent_result.intent_name,
                        requires_human=True,
                        requires_human_reason=f"Reply composition failed: {exc}",
                    )
        finally:
            generated_attachments = collect_generated_attachments(generated_token)
            tools_used = collect_tool_calls(tool_call_token)
            executor.shutdown(wait=False)

        # If Phase 2 didn't produce an agent response (response drafting disabled
        # or intent not matched), build a minimal placeholder.
        if agent_response is None:
            agent_response = AgentResponse(
                response_text="",
                activated_intent=intent_result.intent_name if intent_result.matched else None,
                requires_human=not intent_result.matched,
            )

        if generated_attachments:
            deduped_generated = {}
            for attachment in generated_attachments:
                filename = str(attachment.get("filename") or "")
                if filename:
                    deduped_generated[filename] = attachment
            agent_response.generated_attachments = [
                GeneratedAttachment(**attachment)
                for attachment in deduped_generated.values()
            ]
            generated_filenames = [
                attachment.filename
                for attachment in agent_response.generated_attachments
                if attachment.attach_to_response
            ]
            if generated_filenames:
                merged = list(agent_response.response_attachments or [])
                existing = set(merged)
                for filename in generated_filenames:
                    if filename not in existing:
                        merged.append(filename)
                        existing.add(filename)
                agent_response.response_attachments = merged

        if phishing_future is not None:
            try:
                phishing_result = phishing_future.result()
            except Exception as exc:
                logger.error("Phishing monitoring failed: %s — continuing without warning", exc, exc_info=True)
                phishing_result = PhishingResult(
                    enabled=phishing_enabled,
                    risk_level="none",
                    score=0,
                    checked_at="",
                    error=str(exc),
                ) if phishing_enabled else disabled_phishing_result()

        if prompt_injection_future is not None:
            try:
                prompt_injection_result = prompt_injection_future.result()
            except Exception as exc:
                logger.error("Prompt injection monitoring failed: %s — continuing without warning", exc, exc_info=True)
                prompt_injection_result = PromptInjectionResult(
                    enabled=prompt_injection_enabled,
                    risk_level="none",
                    score=0,
                    checked_at="",
                    error=str(exc),
                ) if prompt_injection_enabled else disabled_prompt_injection_result()

        token_usage = token_collector.aggregate()

    logger.info(
        "Pipeline complete: intent=%s, requires_human=%s",
        intent_result.intent_name,
        agent_response.requires_human,
    )

    return PipelineResult(
        identity_result=identity_result,
        intent_result=intent_result,
        agent_response=agent_response,
        phishing_result=phishing_result,
        prompt_injection_result=prompt_injection_result,
        token_usage=token_usage,
        tools_used=tools_used,
    )
