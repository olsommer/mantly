"""LLM-backed email security assessment helpers."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from automail.core.config import ConfigSource, read_config
from automail.llm.usage import llm_stage, record_usage_from_result
from automail.models import Email

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_USER_TEMPLATE = (_PROMPTS_DIR / "security_user_prompt.md").read_text(encoding="utf-8").strip()


RiskLevel = Literal["none", "low", "medium", "high"]
T = TypeVar("T")


class SecurityAssessmentOutput(BaseModel):
    """Structured LLM output for warning-only security monitoring."""

    risk_level: RiskLevel = "none"
    score: int = Field(default=0, ge=0, le=100)
    indicators: list[str] = Field(default_factory=list)
    reason: str = ""


def _retry_exception(retry_state: RetryCallState) -> BaseException | str:
    outcome = retry_state.outcome
    if outcome is None:
        return ""
    exc = outcome.exception()
    return exc if exc is not None else ""


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type(Exception),
    reraise=True,
    before_sleep=lambda rs: logger.warning(
        "Security agent invoke failed (attempt %d), retrying: %s",
        rs.attempt_number, _retry_exception(rs),
    ),
)
def _invoke_agent(
    agent: Any,
    user_prompt: str,
    *,
    run_name: str,
    tags: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return agent.invoke(
        {"messages": [{"role": "user", "content": user_prompt}]},
        config={
            "run_name": run_name,
            "tags": tags,
            "metadata": metadata,
        },
    )


def run_security_assessment(
    *,
    email: Email,
    parsed_attachments: dict[str, str] | None,
    config_source: ConfigSource,
    tenant_id: str | None,
    project_id: str | None,
    system_prompt_path: Path,
    stage: str,
    run_name: str,
    tags: list[str],
) -> SecurityAssessmentOutput:
    """Run one warning-only security assessment agent."""
    from automail.llm import create_llm, resolve_effective_config

    config = read_config(config_source)
    config = resolve_effective_config(config, tenant_id, project_id)
    llm = create_llm(config, timeout=45, max_retries=1, temperature=0)
    usage_context = getattr(llm, "_mantly_usage_context", None)

    agent = create_agent(
        model=llm,
        tools=[],
        system_prompt=system_prompt_path.read_text(encoding="utf-8").strip(),
        response_format=ToolStrategy(SecurityAssessmentOutput),
    )

    with llm_stage(stage):
        result = _invoke_agent(
            agent,
            _build_user_prompt(email, parsed_attachments),
            run_name=run_name,
            tags=tags,
            metadata={
                "tenant_id": tenant_id,
                "project_id": project_id,
                "attachment_count": len(parsed_attachments or {}),
                "source": "pipeline.security.agent",
            },
        )
    record_usage_from_result(result, usage_context)

    structured = result.get("structured_response")
    if not isinstance(structured, SecurityAssessmentOutput):
        raise ValueError("Security agent returned no structured response.")
    return _normalize_output(structured)


def _build_user_prompt(email: Email, parsed_attachments: dict[str, str] | None) -> str:
    body_html = email.body_html or "None"
    attachments_text = _format_attachments(email, parsed_attachments)
    return _USER_TEMPLATE.format(
        from_address=_xml_text(email.from_address),
        subject=_xml_text(email.subject),
        body=_xml_text(email.body),
        body_html=_xml_text(body_html),
        attachments=attachments_text,
    )


def _format_attachments(email: Email, parsed_attachments: dict[str, str] | None, max_chars: int = 6000) -> str:
    attachment_names = [att.filename for att in email.attachments or []]
    if not attachment_names and not parsed_attachments:
        return "  <none />"

    sections: list[str] = []
    seen: set[str] = set()
    for filename in attachment_names:
        seen.add(filename)
        text = (parsed_attachments or {}).get(filename, "")
        sections.append(_format_attachment(filename, text, max_chars=max_chars))

    for filename, text in (parsed_attachments or {}).items():
        if filename in seen:
            continue
        sections.append(_format_attachment(filename, text, max_chars=max_chars))

    return "\n".join(sections)


def _format_attachment(filename: str, text: str, *, max_chars: int) -> str:
    content = str(text or "[No extracted text available]")
    if len(content) > max_chars:
        content = f"{content[:max_chars]}\n[... truncated, {len(content) - max_chars} characters omitted ...]"
    return (
        f"  <attachment filename={_xml_attr(filename)}>\n"
        f"    <content>{_xml_text(content)}</content>\n"
        "  </attachment>"
    )


def _normalize_output(output: SecurityAssessmentOutput) -> SecurityAssessmentOutput:
    score = max(0, min(100, int(output.score)))
    indicators = [indicator.strip() for indicator in output.indicators if indicator.strip()]
    reason = output.reason.strip() or _default_reason(output.risk_level)
    return SecurityAssessmentOutput(
        risk_level=output.risk_level,
        score=score,
        indicators=indicators,
        reason=reason,
    )


def _default_reason(risk_level: RiskLevel) -> str:
    if risk_level == "none":
        return "No security risk detected."
    return "Security risk detected."


def failed_security_output() -> SecurityAssessmentOutput:
    return SecurityAssessmentOutput(
        risk_level="none",
        score=0,
        indicators=[],
        reason="Security assessment failed.",
    )


def _xml_attr(value: Any) -> str:
    return '"' + _xml_text(str(value)).replace('"', "&quot;") + '"'


def _xml_text(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def result_error_message(error: Exception) -> str:
    return str(error) or error.__class__.__name__


def run_and_map_security_assessment(
    *,
    mapper: Callable[[SecurityAssessmentOutput, str | None], T],
    email: Email,
    parsed_attachments: dict[str, str] | None,
    config_source: ConfigSource,
    tenant_id: str | None,
    project_id: str | None,
    system_prompt_path: Path,
    stage: str,
    run_name: str,
    tags: list[str],
) -> T:
    try:
        output = run_security_assessment(
            email=email,
            parsed_attachments=parsed_attachments,
            config_source=config_source,
            tenant_id=tenant_id,
            project_id=project_id,
            system_prompt_path=system_prompt_path,
            stage=stage,
            run_name=run_name,
            tags=tags,
        )
        return mapper(output, None)
    except Exception as exc:
        logger.error("Security assessment failed: %s", exc, exc_info=True)
        return mapper(failed_security_output(), result_error_message(exc))
