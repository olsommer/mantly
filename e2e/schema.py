"""Strict schema for portable Mantly end-to-end personas."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml  # pyright: ignore[reportMissingModuleSource]
from pydantic import BaseModel, ConfigDict, Field, model_validator

REQUIRED_PROCESSING_STAGES = (
    "runbooks",
    "automation",
    "triage",
    "ticket_fields",
    "composer",
    "grounding",
    "saving",
    "finalizing",
    "completed",
)
SYNTHETIC_KNOWLEDGE_MARKER = "SYNTHETIC QA KNOWLEDGE ONLY"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OperatorPersona(StrictModel):
    role: str = Field(min_length=1)
    perspective: str = Field(min_length=1)
    goals: list[str] = Field(min_length=1)
    risk_boundaries: list[str] = Field(min_length=1)


class BusinessContext(StrictModel):
    name: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    locale: str = Field(min_length=2)
    timezone: str = Field(min_length=1)


class TestPolicy(StrictModel):
    channel: Literal["email"]
    require_human_approval: Literal[True]
    allow_external_send: Literal[False]
    allow_external_actions: Literal[False]
    require_grounding: Literal[True]
    require_progress_audit: Literal[True]
    require_idempotency_replay: Literal[True]
    processing_stages: list[str]

    @model_validator(mode="after")
    def validate_processing_stages(self) -> TestPolicy:
        if tuple(self.processing_stages) != REQUIRED_PROCESSING_STAGES:
            raise ValueError(
                "processing_stages must contain the canonical nine stages in order"
            )
        return self


class KnowledgeFixture(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    tags: list[str] = Field(min_length=1)
    visibility: Literal["public", "internal"]
    automation_allowed: bool
    reviewed: Literal[True]
    synthetic: Literal[True]

    @model_validator(mode="after")
    def validate_synthetic_marker(self) -> KnowledgeFixture:
        if not self.body.startswith(SYNTHETIC_KNOWLEDGE_MARKER):
            raise ValueError(
                f"knowledge body must begin with {SYNTHETIC_KNOWLEDGE_MARKER!r}"
            )
        return self


class ToolFixture(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    tool: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    input: dict[str, Any]
    result: dict[str, Any]


class SeedData(StrictModel):
    knowledge: list[KnowledgeFixture] = Field(min_length=1)
    tool_fixtures: list[ToolFixture] = Field(default_factory=list)


class RunbookExpectation(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    purpose: str = Field(min_length=1)
    proposed_actions: list[str] = Field(default_factory=list)
    response_rules: list[str] = Field(default_factory=list)
    required_guidance: list[str] = Field(default_factory=list)
    required_read_only_tools: list[str] = Field(default_factory=list)


class ConcernExpectation(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    runbook_key: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    answer_obligations: list[str] = Field(min_length=1)


class InboundAttachment(StrictModel):
    filename: str = Field(min_length=1)


class InboundMessage(StrictModel):
    from_name: str = Field(min_length=1)
    from_address: str = Field(pattern=r"^[^@\s]+@example\.test$")
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    attachments: list[InboundAttachment] = Field(default_factory=list)


class ReplayExpectation(StrictModel):
    processed_on_replay: Literal[0]
    skipped_on_replay: Literal[1]
    state_unchanged: Literal[True]


class CaseExpectation(StrictModel):
    minimum_concern_count: int = Field(ge=1)
    reply_disposition: Literal["draft", "withheld"]
    grounding_status: Literal["passed", "failed_closed"]
    approval_required: Literal[True]
    single_combined_reply: Literal[True]
    draft_count: int = Field(ge=0, le=1)
    queued_count: Literal[0]
    sent_count: Literal[0]
    must_cover: list[str] = Field(min_length=1)
    must_not_claim: list[str] = Field(min_length=1)
    knowledge_ids: list[str] = Field(default_factory=list)
    knowledge_any_of: list[str] = Field(default_factory=list, min_length=1)
    tool_fixture_ids: list[str] = Field(default_factory=list)
    pending_actions: list[str] = Field(default_factory=list)
    idempotency: ReplayExpectation

    @model_validator(mode="after")
    def validate_disposition(self) -> CaseExpectation:
        expected_drafts = 1 if self.reply_disposition == "draft" else 0
        if self.draft_count != expected_drafts:
            raise ValueError(
                "draft_count must be 1 for draft disposition and 0 for withheld disposition"
            )
        if self.reply_disposition == "draft" and self.grounding_status != "passed":
            raise ValueError("a persisted draft must have passed grounding")
        return self


class FollowUpExpectation(StrictModel):
    id: str = Field(pattern=r"^[A-Z][0-9]{2}-F[0-9]+$")
    body: str = Field(min_length=1)
    same_ticket: Literal[True]
    new_message_id: Literal[True]


class PersonaCase(StrictModel):
    id: str = Field(pattern=r"^[A-Z][0-9]{2}$")
    title: str = Field(min_length=1)
    inbound: InboundMessage
    concerns: list[ConcernExpectation] = Field(min_length=1)
    expected: CaseExpectation
    follow_ups: list[FollowUpExpectation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_case(self) -> PersonaCase:
        concern_keys = [concern.key for concern in self.concerns]
        if len(concern_keys) != len(set(concern_keys)):
            raise ValueError(f"case {self.id} contains duplicate concern keys")
        if self.expected.minimum_concern_count > len(self.concerns):
            raise ValueError(
                f"case {self.id} minimum_concern_count exceeds declared concerns"
            )
        return self


class KnowledgeCheck(StrictModel):
    id: str = Field(pattern=r"^K[0-9]{2}$")
    question: str = Field(min_length=1)
    expected_citation_ids: list[str] = Field(min_length=1)
    must_cover: list[str] = Field(min_length=1)
    must_mark_unverified: list[str] = Field(default_factory=list)
    create_draft: Literal[False]


class E2EPersona(StrictModel):
    schema_version: Literal[1]
    id: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    name: str = Field(min_length=1)
    case_id_prefix: str = Field(pattern=r"^[A-Z]$")
    description: str = Field(min_length=1)
    operator: OperatorPersona
    business: BusinessContext
    test_policy: TestPolicy
    seed: SeedData
    runbooks: list[RunbookExpectation] = Field(min_length=1)
    knowledge_checks: list[KnowledgeCheck] = Field(min_length=1)
    cases: list[PersonaCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references_and_ids(self) -> E2EPersona:
        runbook_keys = [runbook.key for runbook in self.runbooks]
        knowledge_ids = [article.id for article in self.seed.knowledge]
        tool_fixture_ids = [fixture.id for fixture in self.seed.tool_fixtures]
        case_ids = [case.id for case in self.cases]

        for label, values in (
            ("runbook keys", runbook_keys),
            ("knowledge ids", knowledge_ids),
            ("tool fixture ids", tool_fixture_ids),
            ("case ids", case_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"persona {self.id} contains duplicate {label}")

        expected_case_pattern = re.compile(rf"^{re.escape(self.case_id_prefix)}[0-9]{{2}}$")
        runbook_key_set = set(runbook_keys)
        runbook_actions = {
            runbook.key: set(runbook.proposed_actions) for runbook in self.runbooks
        }
        runbook_tools = {
            runbook.key: {
                f"fixture_{fixture_id.replace('-', '_')}"
                for case in self.cases
                if runbook.key
                in {concern.runbook_key for concern in case.concerns}
                for fixture_id in case.expected.tool_fixture_ids
            }
            for runbook in self.runbooks
        }
        knowledge_id_set = set(knowledge_ids)
        tool_fixture_id_set = set(tool_fixture_ids)

        for runbook in self.runbooks:
            unknown_required_tools = (
                set(runbook.required_read_only_tools) - runbook_tools[runbook.key]
            )
            if unknown_required_tools:
                raise ValueError(
                    f"runbook {runbook.key} requires undeclared read-only tools: "
                    f"{unknown_required_tools}"
                )

        for case in self.cases:
            if expected_case_pattern.fullmatch(case.id) is None:
                raise ValueError(
                    f"case {case.id} does not use persona prefix {self.case_id_prefix}"
                )
            unknown_runbooks = {
                concern.runbook_key for concern in case.concerns
            } - runbook_key_set
            unknown_knowledge = set(case.expected.knowledge_ids) - knowledge_id_set
            unknown_knowledge_any_of = (
                set(case.expected.knowledge_any_of) - knowledge_id_set
            )
            unknown_tools = set(case.expected.tool_fixture_ids) - tool_fixture_id_set
            if unknown_runbooks:
                raise ValueError(f"case {case.id} references unknown runbooks: {unknown_runbooks}")
            if unknown_knowledge:
                raise ValueError(f"case {case.id} references unknown knowledge: {unknown_knowledge}")
            if unknown_knowledge_any_of:
                raise ValueError(
                    f"case {case.id} references unknown knowledge_any_of: "
                    f"{unknown_knowledge_any_of}"
                )
            if unknown_tools:
                raise ValueError(f"case {case.id} references unknown tools: {unknown_tools}")
            allowed_pending_actions = set().union(
                *(runbook_actions[concern.runbook_key] for concern in case.concerns)
            )
            unknown_pending_actions = (
                set(case.expected.pending_actions) - allowed_pending_actions
            )
            if unknown_pending_actions:
                raise ValueError(
                    f"case {case.id} expects actions not declared by its runbooks: "
                    f"{unknown_pending_actions}"
                )

        for check in self.knowledge_checks:
            unknown_citations = set(check.expected_citation_ids) - knowledge_id_set
            if unknown_citations:
                raise ValueError(
                    f"knowledge check {check.id} references unknown knowledge: {unknown_citations}"
                )
        return self


def load_persona(path: Path) -> E2EPersona:
    """Load and strictly validate one persona YAML file."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return E2EPersona.model_validate(raw)


def load_personas(directory: Path) -> list[E2EPersona]:
    """Load all persona YAML files in deterministic order."""

    return [load_persona(path) for path in sorted(directory.glob("*.yaml"))]
