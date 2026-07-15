"""LLM-as-a-judge for evaluation scoring.

Uses the shared LangChain LLM factory to score pipeline outputs against
expected outcomes across four dimensions: identity, intent, actions, and
response.  Each dimension gets a score (0–100) and a brief reasoning
explanation.

The judge uses the tenant's configured LLM (same provider, model, and
API key as the pipeline agents).  Retry / back-off for 429 and other
transient errors is handled automatically by LangChain's built-in
``max_retries`` logic.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.messages import HumanMessage, SystemMessage

from automail.core.config import ConfigSource, read_config

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class DimensionScore:
    """Score for a single evaluation dimension."""
    score: int  # 0–100
    reasoning: str


@dataclass
class JudgeResult:
    """Aggregated judge scores for a single eval case."""
    identity: DimensionScore
    intent: DimensionScore
    actions: DimensionScore
    response: DimensionScore | None  # None if response drafting was disabled
    overall: int  # weighted average
    token_usage: dict[str, Any] | None = None


_JUDGE_SYSTEM_PROMPT = (_PROMPTS_DIR / "judge_system_prompt.md").read_text(encoding="utf-8").strip()
_JUDGE_USER_PROMPT = (_PROMPTS_DIR / "judge_user_prompt.md").read_text(encoding="utf-8").strip()
_JUDGE_RESPONSE_DIMENSION = (_PROMPTS_DIR / "judge_response_dimension.md").read_text(encoding="utf-8").strip()


def _build_judge_prompt(
    expected: dict[str, Any],
    actual: dict[str, Any],
    has_response: bool,
) -> str:
    """Build the judge prompt comparing expected vs actual."""
    dimensions = [
        "identity",
        "intent",
        "actions",
    ]
    if has_response:
        dimensions.append("response")

    response_dimension = _JUDGE_RESPONSE_DIMENSION if has_response else ""
    response_schema = ", ".join(
        f'  "{dim}": {{"score": <0-100>, "reasoning": "<explanation>"}}'
        for dim in dimensions
    )
    return _JUDGE_USER_PROMPT.format(
        expected_json=json.dumps(expected, indent=2, ensure_ascii=False),
        actual_json=json.dumps(actual, indent=2, ensure_ascii=False),
        response_dimension=response_dimension,
        response_schema=response_schema,
    )


def _parse_judge_response(text: str, has_response: bool) -> JudgeResult:
    """Parse the LLM judge's JSON response into a JudgeResult."""
    # Strip markdown fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first and last fence lines
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines)

    data = json.loads(cleaned)

    identity = DimensionScore(
        score=int(data.get("identity", {}).get("score", 0)),
        reasoning=data.get("identity", {}).get("reasoning", ""),
    )
    intent = DimensionScore(
        score=int(data.get("intent", {}).get("score", 0)),
        reasoning=data.get("intent", {}).get("reasoning", ""),
    )
    actions = DimensionScore(
        score=int(data.get("actions", {}).get("score", 0)),
        reasoning=data.get("actions", {}).get("reasoning", ""),
    )

    response = None
    if has_response and "response" in data:
        response = DimensionScore(
            score=int(data["response"].get("score", 0)),
            reasoning=data["response"].get("reasoning", ""),
        )

    # Weighted average: identity 25%, intent 30%, actions 25%, response 20%
    if response is not None:
        overall = int(
            identity.score * 0.25
            + intent.score * 0.30
            + actions.score * 0.25
            + response.score * 0.20
        )
    else:
        # Without response: identity 30%, intent 40%, actions 30%
        overall = int(
            identity.score * 0.30
            + intent.score * 0.40
            + actions.score * 0.30
        )

    return JudgeResult(
        identity=identity,
        intent=intent,
        actions=actions,
        response=response,
        overall=overall,
    )


def _get_judge_llm(config_path: ConfigSource = None, tenant_id: str | None = None) -> Any:
    """Create a LangChain LLM for the eval judge.

    Uses the shared ``create_llm`` factory so that provider selection,
    API-key lookup, and retry / 429-backoff are handled consistently.
    The model and API key come from the tenant/project config — same as
    the pipeline agents.
    """
    from automail.llm import create_llm, resolve_effective_config

    config = read_config(config_path=config_path)
    config = resolve_effective_config(config, tenant_id, getattr(config_path, "project_id", None))

    return create_llm(
        config,
        timeout=300,
        max_retries=5,
        temperature=0.1,
    )


def run_judge(
    expected: dict[str, Any],
    actual: dict[str, Any],
    has_response: bool,
    config_path: ConfigSource = None,
    tenant_id: str | None = None,
) -> JudgeResult:
    """Run the LLM judge on a single eval case.

    Args:
        expected: Dict with expected_customer_found, expected_intent_name, etc.
        actual: Dict with identity_result, intent_result, agent_response from pipeline.
        has_response: Whether to also judge the response text dimension.

    Returns:
        JudgeResult with scores for each dimension.
    """
    llm = _get_judge_llm(config_path=config_path, tenant_id=tenant_id)
    prompt = _build_judge_prompt(expected, actual, has_response)

    logger.info(
        "Running LLM judge (has_response=%s)",
        has_response,
    )

    from automail.llm.usage import collect_llm_usage, llm_stage
    with collect_llm_usage() as token_collector:
        with llm_stage("eval_judge"):
            response = llm.invoke([
                SystemMessage(content=_JUDGE_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
        from automail.llm.usage import record_usage_from_result

        record_usage_from_result(response, getattr(llm, "_mantly_usage_context", None))
        token_usage = token_collector.aggregate()

    from automail.llm import message_content_text

    response_text = message_content_text(response.content)
    logger.debug("Judge raw response: %s", response_text[:500])

    result = _parse_judge_response(response_text, has_response)
    result.token_usage = token_usage
    return result
