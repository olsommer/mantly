"""Request models for evaluation admin endpoints."""

from pydantic import BaseModel


class EvalSetCreate(BaseModel):
    name: str
    description: str = ""


class EvalSetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class EvalCaseCreate(BaseModel):
    name: str
    email_subject: str
    email_from: str
    email_body: str
    email_attachments: list | None = None
    expected_customer_found: bool = False
    expected_customer_data: dict | None = None
    expected_intent_matched: bool = False
    expected_intent_name: str = ""
    expected_actions: list | None = None
    expected_requires_human: bool = False
    expected_response: str = ""


class EvalCaseUpdate(BaseModel):
    name: str | None = None
    email_subject: str | None = None
    email_from: str | None = None
    email_body: str | None = None
    email_attachments: list | None = None
    expected_customer_found: bool | None = None
    expected_customer_data: dict | None = None
    expected_intent_matched: bool | None = None
    expected_intent_name: str | None = None
    expected_actions: list | None = None
    expected_requires_human: bool | None = None
    expected_response: str | None = None
