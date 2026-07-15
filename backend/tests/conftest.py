"""Shared fixtures for e2e tests."""

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AUTOMAIL_BACKGROUND_IO", "disabled")

import pytest
from starlette.testclient import TestClient

from automail.main import app
from automail.models import Email


@pytest.fixture
def client():
    """Provide a TestClient for the FastAPI app."""
    return TestClient(app)


def unique_email_id() -> str:
    """Generate a unique email ID to bypass DB cache."""
    return f"e2e-{uuid.uuid4().hex[:12]}"


# Reusable demo emails for e2e tests
DEMO_EMAILS = {
    "gmbh-inquiry": Email(
        id="demo-email-6",
        subject="Anfrage GmbH-Gründung in der Schweiz",
        from_address="info@wysslaw.ch",
        body=(
            "Sehr geehrte Damen und Herren\n\n"
            "Ich plane die Gründung einer GmbH mit Sitz im Kanton Zug und möchte Sie um "
            "Unterstützung bitten.\n\n"
            "Es handelt sich um eine Gesellschaft im Bereich IT-Dienstleistungen. Das Stammkapital "
            "soll CHF 20'000.00 betragen. Ich wäre alleiniger Gesellschafter und Geschäftsführer.\n\n"
            "Konkret hätte ich folgende Fragen:\n"
            "- Welche Unterlagen werden für die Gründung benötigt?\n"
            "- Wie hoch sind die Gründungskosten (Notariatskosten, Handelsregistereintrag etc.)?\n\n"
            "Ich wäre Ihnen dankbar, wenn Sie mir ein unverbindliches Angebot für die vollständige "
            "Begleitung der Gründung zukommen lassen könnten.\n\n"
            "Freundliche Grüsse"
        ),
        attachments=[],
    ),
    "ag-formation": Email(
        id="demo-email-7",
        subject="Anfrage Gründung einer AG in der Schweiz",
        from_address="info@wysslaw.ch",
        body=(
            "Sehr geehrte Damen und Herren\n\n"
            "Zusammen mit zwei Geschäftspartnern beabsichtige ich, eine Aktiengesellschaft in der "
            "Schweiz zu gründen. Der Sitz soll im Kanton Zug sein.\n\n"
            "Die Gesellschaft wird im Bereich Handel und Import von Medizinprodukten tätig sein. "
            "Das Aktienkapital soll CHF 100'000.00 betragen, aufgeteilt auf drei Aktionäre.\n\n"
            "Über ein unverbindliches Angebot für die vollständige Begleitung der AG-Gründung wären "
            "wir sehr dankbar.\n\n"
            "Mit freundlichen Grüssen"
        ),
        attachments=[],
    ),
    "marriage-contract": Email(
        id="demo-email-3",
        subject="Anfrage Kosten Beglaubigung Ehevertrag",
        from_address="info@wysslaw.ch",
        body=(
            "Sehr geehrte Damen und Herren\n\n"
            "Gerne möchte ich mich erkundigen wie viel die Beglaubigung eines Ehevertrages "
            "(zwecks Nachlassregelung) bei Ihnen kosten würde.\n\n"
            "Vielen Dank für Ihre Rückmeldung.\n\n"
            "Freundliche Grüsse"
        ),
        attachments=[],
    ),
}
