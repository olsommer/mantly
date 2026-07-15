"""Demo action adapter backed by repo-root demo data."""

import base64
import json
import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, model_validator


def _demo_root() -> Path:
    return Path(os.getenv("DEMO_DATA_DIR", Path(__file__).resolve().parents[3] / "demo"))


@lru_cache(maxsize=1)
def _responses() -> dict:
    return json.loads((_demo_root() / "actions" / "responses.json").read_text(encoding="utf-8"))


class DemoProcessStartRequest(BaseModel):
    process: str | None = None
    actionName: str | None = None
    actionLabel: str | None = None
    chatId: str | None = None

    @model_validator(mode="after")
    def require_process_reference(self) -> Self:
        if not (self.process or self.actionLabel or self.actionName):
            raise ValueError("process, actionLabel, or actionName is required")
        return self


class DemoUpdateTitleRequest(BaseModel):
    title: str | None = None
    chatId: str | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_claim_title_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("title"):
            claim_title = data.get("claim_title") or data.get("claimTitle")
            if claim_title:
                return {**data, "title": claim_title}
        return data

    @model_validator(mode="after")
    def require_title(self) -> Self:
        if not self.title:
            raise ValueError("title is required")
        return self


class DemoGreenCardRequest(BaseModel):
    policyNumber: str | None = None
    licensePlate: str | None = None
    customerName: str | None = None


def mock_demo_process_start(payload: DemoProcessStartRequest) -> dict:
    config = _responses()["processStart"]
    chat_id = payload.chatId or config["defaultChatId"]
    process = payload.process or payload.actionLabel or payload.actionName or config["defaultProcess"]
    process_id = f"{config['processIdPrefix']}{chat_id.replace(' ', '-').lower()}"
    body = payload.model_dump(exclude_none=True)

    return {
        "ok": True,
        "action": config["action"],
        "status": config["status"],
        "chatId": chat_id,
        "process": process,
        "processId": process_id,
        "received": deepcopy(body),
    }


def mock_demo_update_title(payload: DemoUpdateTitleRequest) -> dict:
    config = _responses()["updateTitle"]
    body = payload.model_dump(exclude_none=True)

    return {
        "ok": True,
        "action": config["action"],
        "status": config["status"],
        "chatId": payload.chatId,
        "title": payload.title,
        "received": deepcopy(body),
    }


def mock_demo_motor_policy(sender_email: str | None = None, policy_number: str | None = None) -> dict:
    """Return deterministic motor-insurance data for demo intent tools."""
    sender = (sender_email or "").strip().lower()
    policy = policy_number or "AXA-M-104928"
    return {
        "ok": True,
        "customer": {
            "name": "Max Keller",
            "email": sender or "max.keller@example.com",
            "customerNumber": "C-AXA-77821",
        },
        "policy": {
            "policyNumber": policy,
            "product": "Motorfahrzeugversicherung",
            "status": "active",
            "validFrom": "2026-01-01",
            "validTo": "2026-12-31",
        },
        "vehicle": {
            "licensePlate": "ZH-48291",
            "vin": "WVWZZZ1KZ6W000001",
            "make": "VW",
            "model": "Golf",
            "firstRegistration": "2021-04-16",
        },
        "greenCardEligible": True,
    }


def mock_demo_green_card_request(payload: DemoGreenCardRequest) -> dict:
    """Return a generated-document reference used by the demo response."""
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Count 0 >> endobj\n"
        b"trailer << /Root 1 0 R >>\n%%EOF\n"
    )
    return {
        "ok": True,
        "action": "green-card-request",
        "status": "generated",
        "document": {
            "filename": "gruene-karte-max-keller.pdf",
            "contentType": "application/pdf",
            "contentBase64": base64.b64encode(pdf_bytes).decode("ascii"),
            "description": "Internationale Versicherungskarte fuer das Fahrzeug ZH-48291.",
        },
        "policyNumber": payload.policyNumber or "AXA-M-104928",
        "licensePlate": payload.licensePlate or "ZH-48291",
        "customerName": payload.customerName or "Max Keller",
    }
