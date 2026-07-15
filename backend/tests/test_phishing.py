from automail.models import Email
from automail.pipeline.security.agent import SecurityAssessmentOutput
from automail.pipeline.security.phishing import detect_phishing


def test_phishing_detector_returns_disabled_result_when_off():
    result = detect_phishing(
        Email(
            id="email-1",
            subject="Hello",
            fromAddress="person@example.com",
            body="Plain operational update.",
            attachments=[],
        ),
        enabled=False,
    )

    assert result.enabled is False
    assert result.risk_level == "none"
    assert result.indicators == []


def test_phishing_detector_maps_llm_assessment(monkeypatch):
    def fake_run_and_map_security_assessment(**kwargs):
        assert kwargs["parsed_attachments"] == {"invoice.pdf": "Wire funds to the new IBAN."}
        return kwargs["mapper"](
            SecurityAssessmentOutput(
                risk_level="high",
                score=88,
                indicators=["Requests payment redirection."],
                reason="Payment redirection risk detected.",
            ),
            None,
        )

    monkeypatch.setattr(
        "automail.pipeline.security.phishing.run_and_map_security_assessment",
        fake_run_and_map_security_assessment,
    )

    result = detect_phishing(
        Email(
            id="email-2",
            subject="Urgent account verification",
            fromAddress="security@example.com",
            body="Please pay the attached invoice.",
            attachments=[{"filename": "invoice.pdf", "base64": ""}],
        ),
        enabled=True,
        parsed_attachments={"invoice.pdf": "Wire funds to the new IBAN."},
    )

    assert result.enabled is True
    assert result.risk_level == "high"
    assert result.score == 88
    assert result.indicators == ["Requests payment redirection."]
    assert result.reason == "Payment redirection risk detected."
