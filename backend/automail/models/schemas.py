from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def to_camel(string: str) -> str:
    """Convert snake_case to camelCase."""
    components = string.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])


class CamelCaseModel(BaseModel):
    """Base model that converts between camelCase and snake_case."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,  # Allow both camelCase and snake_case
    )


# ---------------------------------------------------------------------------
# v3 Pipeline Models
# ---------------------------------------------------------------------------

class IdentityResult(CamelCaseModel):
    """Result of Phase 1: customer identity analysis."""
    customer_found: bool = False
    data: dict = {}
    tool_calls_made: list[str] = []
    error: Optional[str] = None


class ResponseAttachment(CamelCaseModel):
    """Metadata for a file available to response drafting.

    ``mode`` controls whether the file is always included in the response
    or left to the response agent to decide dynamically.
    """
    filename: str
    description: str = ""
    mode: Literal["always", "dynamic"] = "always"


class GeneratedAttachment(CamelCaseModel):
    """Attachment returned by a tool during a pipeline run."""
    filename: str
    content_base64: str
    content_type: str = "application/octet-stream"
    size: Optional[int] = None
    source_tool: str = ""
    attach_to_response: bool = True


class IntentResponseConfig(CamelCaseModel):
    """Response drafting settings for a matched intent."""
    enabled: bool = False
    auto: bool = True
    response_rules: list[str] = Field(default_factory=list)
    required_guidance: list[str] = Field(default_factory=list)
    attachments: list[ResponseAttachment] = Field(default_factory=list)
    use_feedback_learnings: bool = True

    @field_validator("response_rules", "required_guidance", mode="before")
    @classmethod
    def _coerce_response_rules(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if not isinstance(v, list):
            return [str(v)]
        out: list[str] = []
        for item in v:
            if isinstance(item, dict):
                for k, val in item.items():
                    out.append(f"{k}: {val}")
            else:
                out.append(str(item))
        return out


class IntentAction(CamelCaseModel):
    """A business action element associated with a matched intent."""
    name: str
    label: str
    type: Literal['dropdown', 'calendar', 'input', 'button'] = 'button'
    description: Optional[str] = None  # human-readable description of the action
    options: list[str] = Field(default_factory=list)  # static choices for dropdown
    separate_call: bool = True      # True = fires its own webhook on change; False = collected by a button
    webhook: str = ""               # required for type=button or separate_call=True
    method: str = "POST"
    payload: dict = Field(default_factory=dict)  # Pre-resolved identity data, injected before the response is sent
    query: dict = Field(default_factory=dict)    # Optional query params mapped from action payload values
    body: dict = Field(default_factory=dict)     # Optional JSON body mapped from action payload values
    headers: dict[str, str] = Field(default_factory=dict)  # Custom HTTP headers forwarded to the webhook
    initial_value: Optional[str] = None  # LLM-extracted pre-fill value


class ConcernRoute(BaseModel):
    """One independently actionable concern selected by the intent router."""

    summary: str = ""
    source_text: str = ""
    answer_obligations: list[str] = Field(default_factory=list, max_length=10)
    intent_name: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class AnswerObligation(CamelCaseModel):
    """One explicit customer question the final reply must address."""

    obligation_id: str
    question: str
    source_text: str = ""


class VerifiedFact(CamelCaseModel):
    """Allowlisted fact prepared for ticket-level reply composition."""

    fact: str = ""
    path: str = ""
    value: str | bool | int | float | None = None
    source: str = "runbook"


class RunbookToolEvidence(CamelCaseModel):
    """Safe, structured facts derived from one runbook tool call."""

    tool_name: str
    method: str = ""
    facts: list[VerifiedFact] = Field(default_factory=list)
    status: str = "success"
    response_facts_truncated: bool = False
    has_nonaffirmative_lookup_result: bool = False


class RunbookActionOutcome(CamelCaseModel):
    """Execution/proposal state for one runbook action."""

    name: str
    label: str = ""
    status: Literal["proposed", "pending_input", "succeeded", "failed", "skipped"] = "proposed"
    initial_value: Optional[str] = None
    detail: str = ""
    reference: str = ""


class RunbookAttachment(CamelCaseModel):
    """Attachment made available by a runbook or one of its tools."""

    filename: str
    description: str = ""
    source: Literal["runbook", "tool"] = "runbook"
    mode: str = "dynamic"
    source_filename: str = ""
    source_intent: str = ""


class RunbookOutcome(CamelCaseModel):
    """Structured output of one concern's independently executed runbook."""

    concern_id: str
    concern_summary: str = ""
    source_text: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    matched: bool = False
    intent_name: Optional[str] = None
    status: Literal["ready", "requires_human", "unmatched", "failed"] = "unmatched"
    summary: str = ""
    answer_obligations: list[AnswerObligation] = Field(default_factory=list)
    actions: list[IntentAction] = Field(default_factory=list)
    action_outcomes: list[RunbookActionOutcome] = Field(default_factory=list)
    verified_facts: list[VerifiedFact] = Field(default_factory=list)
    tool_evidence: list[RunbookToolEvidence] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    reply_requirements: list[str] = Field(default_factory=list)
    required_guidance: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    attachments: list[RunbookAttachment] = Field(default_factory=list)
    requires_human: bool = False
    requires_human_reason: Optional[str] = None
    error: Optional[str] = None


class IntentResult(CamelCaseModel):
    """Result of Phase 2 with legacy primary-intent compatibility fields."""
    matched: bool = False
    intent_name: Optional[str] = None
    actions: list[IntentAction] = Field(default_factory=list)
    response: IntentResponseConfig = Field(default_factory=IntentResponseConfig)
    concerns: list[RunbookOutcome] = Field(default_factory=list)
    error: Optional[str] = None


class PhishingResult(CamelCaseModel):
    """Best-effort phishing monitoring result.

    Informational only: callers must not treat this as a pipeline blocker.
    """
    enabled: bool = False
    risk_level: Literal["none", "low", "medium", "high"] = "none"
    score: int = 0
    indicators: list[str] = []
    reason: str = ""
    checked_at: str = ""
    error: Optional[str] = None


class PromptInjectionResult(CamelCaseModel):
    """Best-effort prompt injection monitoring result.

    Informational only: callers must not treat this as a pipeline blocker.
    """
    enabled: bool = False
    risk_level: Literal["none", "low", "medium", "high"] = "none"
    score: int = 0
    indicators: list[str] = []
    reason: str = ""
    checked_at: str = ""
    error: Optional[str] = None


class TokenUsageCall(CamelCaseModel):
    stage: str = "unknown"
    provider: str = ""
    model: str = ""
    duration_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    metadata_available: bool = False
    raw_usage: dict = {}


class TokenUsage(CamelCaseModel):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    metadata_available: bool = False
    calls: list[TokenUsageCall] = []


# ---------------------------------------------------------------------------
# Internal structured outputs for the intent agent middleware stages
# (not exposed to the API — used to communicate between middleware stages)
# ---------------------------------------------------------------------------

class ActionFill(BaseModel):
    """LLM-produced prefill value for a single action field."""
    name: str
    initial_value: Optional[str] = None


class RunbookProcessingDetails(BaseModel):
    """Shared structured handoff from a runbook to the ticket composer."""

    summary: str = ""
    missing_information: list[str] = Field(default_factory=list)
    reply_requirements: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    requires_human: bool = False
    requires_human_reason: Optional[str] = None


class IntentProcessingOutput(RunbookProcessingDetails):
    """Structured output for the intent-processing stage (Stage B).

    The LLM selects applicable actions, fills action values, and decides whether
    human review is needed.
    Action *definitions* (type, webhook, etc.) still come from INTENT.md
    frontmatter — the LLM only selects definitions and provides initial_value
    fills. A null selection is invalid and fails closed; an explicit empty list
    suppresses every configured action.
    """
    selected_action_names: Optional[list[str]] = None
    action_fills: list[ActionFill] = Field(default_factory=list)


class IntentReviewOutput(RunbookProcessingDetails):
    """Structured output for intent processing when no actions are configured."""


class Attachment(CamelCaseModel):
    filename: str
    base64: str
    content_type: str = ""

class Email(CamelCaseModel):
    id: str
    subject: str
    from_address: str
    body: str
    attachments: list[Attachment]
    body_html: Optional[str] = None
    thread_id: Optional[str] = None
    message_id: Optional[str] = None
    internet_message_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: list[str] = []

class ProcessEmailRequest(CamelCaseModel):
    """Request model for processing an email."""
    email: Email
    action: Literal['respond'] = 'respond'
    creator: str
    project_id: Optional[str] = None


class ResponseDraft(BaseModel):
    """LLM-facing response schema.

    Review state, activated intent, and generated tool attachments are runtime
    metadata. The response LLM should only draft the outgoing email payload.
    """

    response_text: str = ""
    response_attachments: Optional[List[str]] = None  # Just filenames
    response_cc: Optional[List[str]] = None
    response_bcc: Optional[List[str]] = None
    covered_concern_ids: list[str] = Field(default_factory=list)
    covered_obligation_ids: list[str] = Field(default_factory=list)
    requires_human: bool = False
    requires_human_reason: Optional[str] = None
    conflicting_requirements: list[str] = Field(default_factory=list)


class AgentResponse(CamelCaseModel):
    """Runtime response object persisted and returned by the API."""

    response_text: str = ""
    response_attachments: Optional[List[str]] = None  # Just filenames
    response_cc: Optional[List[str]] = None
    response_bcc: Optional[List[str]] = None
    activated_intent: Optional[str] = None
    requires_human: bool = False  # Indicates if email cannot be handled by agent
    requires_human_reason: Optional[str] = None  # Brief explanation why human attention is needed
    generated_attachments: list[GeneratedAttachment] = []


class FileAttachment(CamelCaseModel):
    """File attachment with actual content."""
    filename: str
    content: bytes
    content_type: str


class EmailAnalysisResponse(CamelCaseModel):
    """Full response including agent response and file attachments."""
    response_text: str
    activated_intent: Optional[str] = None
    response_cc: Optional[List[str]] = None
    response_bcc: Optional[List[str]] = None
    attachments: Optional[List[dict]] = None  # Will contain filename, content_base64, content_type


class EmailResponse(CamelCaseModel):
    email_body: str
    email_attachments: List[dict]  # Changed from List[FileAttachment] to support dict format
    requires_human: bool = False  # Pass through from AgentResponse
    requires_human_reason: Optional[str] = None  # Brief explanation why human attention is needed
    # v3 pipeline results
    identity_result: Optional[IdentityResult] = None
    intent_result: Optional[IntentResult] = None
    phishing_result: Optional[PhishingResult] = None
    prompt_injection_result: Optional[PromptInjectionResult] = None
    token_usage: Optional[TokenUsage] = None
    activated_intent: Optional[str] = None


class Message(CamelCaseModel):
    role: str  # 'ai' | 'supervisor' | 'user' | 'request' | 'email'
    user: str
    content: str | EmailResponse  # or EmailAnalysisResponse for 'email' role


class ChatRequest(CamelCaseModel):
    """Request model for chat endpoint."""
    messages: List[Message]
    chat_id: str


class AddUserRequest(CamelCaseModel):
    chat_id: str
    email: str


class ChatResponse(CamelCaseModel):
    id: str
    email_id: str
    creator: str
    messages: list[Message]
    created_at: str
    status: str
    members: list[str]
    activated_intent: Optional[str] = None
    requires_human: bool = False


class FeedbackRequest(CamelCaseModel):
    chat_id: str
    project_id: str = ""
    user: str
    rating: str  # "like" | "dislike"
    affected_stages: list[str] = []
    feedback_text: str = ""


class FeedbackResponse(CamelCaseModel):
    status: str
    id: str
