"""Reflect agent — derives actionable learning rules from user feedback.

When a user gives negative feedback on a pipeline result, this agent analyses
the gap between the expected and actual output and produces concise learning
rules that prevent the same mistake in future runs.

Uses LangChain ``create_agent`` with ``ToolStrategy`` structured output,
following the same pattern as the intent and identity agents.
"""
import logging
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parent / "prompts"


# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------

class ReflectOutput(BaseModel):
    """Output of the reflect agent — derived learnings from user feedback."""
    learnings: list[str] = []


_SYSTEM_PROMPT = (_PROMPTS_DIR / "reflect_system_prompt.md").read_text(encoding="utf-8").strip()
_USER_TEMPLATE = (_PROMPTS_DIR / "reflect_user_prompt.md").read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

def _retry_exception(retry_state: RetryCallState) -> BaseException | str:
    outcome = retry_state.outcome
    if outcome is None:
        return ""
    exc = outcome.exception()
    return exc if exc is not None else ""


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
    before_sleep=lambda rs: logger.warning(
        "Reflect agent invoke failed (attempt %d), retrying: %s",
        rs.attempt_number, _retry_exception(rs),
    ),
)
def _invoke_agent(
    agent: Any,
    user_prompt: str,
    *,
    run_name: str,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {"run_name": run_name}
    if tags:
        config["tags"] = tags
    if metadata:
        config["metadata"] = metadata
    return agent.invoke(
        {"messages": [{"role": "user", "content": user_prompt}]},
        config=config,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_reflect_agent(
    feedback_text: str,
    original_email: str = "",
    pipeline_result: str = "",
    current_learnings: list[str] | None = None,
    tenant_id: str | None = None,
    affected_stage: str = "",
) -> list[str]:
    """Analyse user feedback and return derived learning rules.

    Args:
        feedback_text: The user's written feedback on the pipeline result.
        original_email: The original incoming email (subject + body).
        pipeline_result: Sanitized structured pipeline result, including the generated response.
        current_learnings: Existing learning rules for the intent (to avoid
            duplicating them).
        tenant_id: Optional tenant for config resolution.
        affected_stage: UI-selected stage the feedback refers to.

    Returns:
        A list of new learning rule strings.  May be empty if the feedback
        does not contain actionable information.
    """
    from automail.core.config import read_config
    from automail.llm import create_llm, resolve_effective_config

    config = read_config()
    config = resolve_effective_config(config, tenant_id)
    llm = create_llm(config, timeout=60, max_retries=2)

    agent = create_agent(
        model=llm,
        tools=[],
        system_prompt=_SYSTEM_PROMPT,
        response_format=ToolStrategy(ReflectOutput),
    )

    learnings_text = "None yet."
    if current_learnings:
        learnings_text = "\n".join(f"{i}. {rule}" for i, rule in enumerate(current_learnings, 1))

    user_prompt = _USER_TEMPLATE.format(
        affected_stage=affected_stage or "Not specified.",
        original_email=original_email or "Not available.",
        pipeline_result=pipeline_result or "No pipeline result available.",
        feedback_text=feedback_text,
        current_learnings=learnings_text,
    )

    logger.info("Running reflect agent for feedback (len=%d)", len(feedback_text))

    from automail.llm.usage import llm_stage
    with llm_stage("feedback_reflect"):
        result = _invoke_agent(
            agent,
            user_prompt,
            run_name="feedback_reflect_agent",
            tags=["mantly", "feedback", "agent"],
            metadata={
                "tenant_id": tenant_id,
                "affected_stage": affected_stage,
                "source": "feedback.reflect_agent",
            },
        )
    from automail.llm.usage import record_usage_from_result

    record_usage_from_result(result, getattr(llm, "_mantly_usage_context", None))
    structured: ReflectOutput | None = result.get("structured_response")

    if not structured:
        logger.warning("Reflect agent returned no structured response")
        return []

    logger.info("Reflect agent produced %d learnings", len(structured.learnings))
    return [rule.strip() for rule in structured.learnings if rule.strip()]
