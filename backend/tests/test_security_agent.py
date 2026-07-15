from pathlib import Path

from automail.models import Email
from automail.pipeline.security import agent as security_agent
from automail.pipeline.security.agent import SecurityAssessmentOutput


def test_security_user_prompt_includes_extracted_attachments():
    prompt = security_agent._build_user_prompt(
        Email(
            id="email-1",
            subject="Please review",
            from_address="person@example.com",
            body="See attached.",
            body_html="<p>See attached.</p>",
            attachments=[{"filename": "invoice.pdf", "base64": ""}],
        ),
        {"invoice.pdf": "Please wire money to the new account."},
    )

    assert "<incoming_email>" in prompt
    assert 'filename="invoice.pdf"' in prompt
    assert "Please wire money to the new account." in prompt
    assert "&lt;p&gt;See attached.&lt;/p&gt;" in prompt


def test_security_output_normalization_clamps_and_cleans_values():
    output = security_agent._normalize_output(
        SecurityAssessmentOutput.model_construct(
            risk_level="low",
            score=150,
            indicators=[" suspicious ", ""],
            reason="",
        )
    )

    assert output.score == 100
    assert output.indicators == ["suspicious"]
    assert output.reason == "Security risk detected."


def test_security_mapper_receives_nonblocking_error(monkeypatch):
    def fail_assessment(**_kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(security_agent, "run_security_assessment", fail_assessment)

    result = security_agent.run_and_map_security_assessment(
        mapper=lambda output, error: {"output": output, "error": error},
        email=Email(
            id="email-1",
            subject="Hello",
            from_address="person@example.com",
            body="Body",
            attachments=[],
        ),
        parsed_attachments=None,
        config_source=None,
        tenant_id=None,
        project_id=None,
        system_prompt_path=Path("unused.md"),
        stage="security_test",
        run_name="security_test_agent",
        tags=["test"],
    )

    assert result["output"].risk_level == "none"
    assert result["output"].score == 0
    assert result["error"] == "model down"
