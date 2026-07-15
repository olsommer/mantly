"""Warning-only LLM phishing monitoring."""
from __future__ import annotations

from pathlib import Path

from automail.core.config import ConfigSource
from automail.models import Email, PhishingResult
from automail.pipeline.security.agent import (
    SecurityAssessmentOutput,
    now_iso,
    run_and_map_security_assessment,
)

_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "phishing_system_prompt.md"


def disabled_phishing_result() -> PhishingResult:
    return PhishingResult(enabled=False, checked_at=now_iso())


def detect_phishing(
    email: Email,
    *,
    enabled: bool,
    parsed_attachments: dict[str, str] | None = None,
    config_source: ConfigSource = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> PhishingResult:
    """Return a warning-only phishing monitoring result for *email*."""
    if not enabled:
        return disabled_phishing_result()

    return run_and_map_security_assessment(
        mapper=_map_output,
        email=email,
        parsed_attachments=parsed_attachments,
        config_source=config_source,
        tenant_id=tenant_id,
        project_id=project_id,
        system_prompt_path=_SYSTEM_PROMPT_PATH,
        stage="security_phishing",
        run_name="security_phishing_agent",
        tags=["mantly", "security", "phishing", "agent"],
    )


def _map_output(output: SecurityAssessmentOutput, error: str | None) -> PhishingResult:
    return PhishingResult(
        enabled=True,
        risk_level=output.risk_level,
        score=output.score,
        indicators=output.indicators,
        reason=output.reason,
        checked_at=now_iso(),
        error=error,
    )
