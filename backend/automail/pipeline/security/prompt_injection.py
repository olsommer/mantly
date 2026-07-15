"""Warning-only LLM prompt-injection monitoring."""
from __future__ import annotations

from pathlib import Path

from automail.core.config import ConfigSource
from automail.models import Email, PromptInjectionResult
from automail.pipeline.security.agent import (
    SecurityAssessmentOutput,
    now_iso,
    run_and_map_security_assessment,
)

_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "prompt_injection_system_prompt.md"


def disabled_prompt_injection_result() -> PromptInjectionResult:
    return PromptInjectionResult(enabled=False, checked_at=now_iso())


def detect_prompt_injection(
    email: Email,
    *,
    enabled: bool,
    parsed_attachments: dict[str, str] | None = None,
    config_source: ConfigSource = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> PromptInjectionResult:
    """Return a warning-only prompt-injection monitoring result for *email*."""
    if not enabled:
        return disabled_prompt_injection_result()

    return run_and_map_security_assessment(
        mapper=_map_output,
        email=email,
        parsed_attachments=parsed_attachments,
        config_source=config_source,
        tenant_id=tenant_id,
        project_id=project_id,
        system_prompt_path=_SYSTEM_PROMPT_PATH,
        stage="security_prompt_injection",
        run_name="security_prompt_injection_agent",
        tags=["mantly", "security", "prompt-injection", "agent"],
    )


def _map_output(output: SecurityAssessmentOutput, error: str | None) -> PromptInjectionResult:
    return PromptInjectionResult(
        enabled=True,
        risk_level=output.risk_level,
        score=output.score,
        indicators=output.indicators,
        reason=output.reason,
        checked_at=now_iso(),
        error=error,
    )
