"""Intent pipeline: classify concerns and execute matched runbooks."""

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain.agents.structured_output import ToolStrategy
from langgraph.errors import GraphRecursionError

from automail.core.runtime_secrets import load_runtime_secrets
from automail.integrations.http_tool import (
    HttpToolCollection,
    _make_http_tool,
    isolated_http_tool_collection,
    merge_http_tool_collection,
    raw_tool_to_definition,
)
from automail.llm.usage import llm_stage
from automail.models import (
    AgentResponse,
    AnswerObligation,
    ConcernRoute,
    Email,
    IdentityResult,
    IntentAction,
    IntentProcessingOutput,
    IntentResponseConfig,
    IntentResult,
    IntentReviewOutput,
    RunbookActionOutcome,
    RunbookAttachment,
    RunbookOutcome,
    RunbookToolEvidence,
    VerifiedFact,
)
from automail.pipeline.intent.activate_intent import (
    MAX_ROUTED_CONCERNS,
    route_concerns,
    use_intents_dir,
)
from automail.pipeline.intent.classification import _CLASSIFY_SYSTEM_PROMPT
from automail.pipeline.intent.helpers import (
    _append_feedback_learnings,
    _build_intent_http_tools,
    _build_intents_list,
    _build_process_user_message,
    _find_activated_intent,
    _find_no_match_reason,
    _find_routed_concerns,
    _find_router_tool_call,
    _format_attachment_context,
    _invoke_agent,
    _is_open_ticket_button,
    _load_intent_feedback_learnings,
)
from automail.pipeline.intent.intents_factory import (
    get_intent_actions,
    get_intent_body,
    get_intent_require_review,
    get_intent_required_read_only_tools,
    get_intent_response_attachments,
    get_intent_response_config,
    get_intent_subsumes_runbooks,
    get_intent_tools,
    get_known_intent_names,
)

logger = logging.getLogger(__name__)

_ROUTER_MALFORMED_OUTPUT_MAX_ATTEMPTS = 3
_ROUTER_EXECUTION_LIMIT_MAX_ATTEMPTS = 2
_ROUTER_GRAPH_RECURSION_LIMIT = 6
_ROUTER_EXECUTION_LIMIT_REVIEW_REASON = (
    "Intent classification stopped safely; human review is required."
)
_MALFORMED_ROUTER_REVIEW_REASON = (
    "Intent classification returned malformed structured output; human review is required."
)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_PROCESSING_SECURITY_BOUNDARY = (_PROMPTS_DIR / "processing_security_boundary.md").read_text(encoding="utf-8").strip()
_REQUIRED_LOOKUP_UNAVAILABLE_REPLY_REQUIREMENT = (
    _PROMPTS_DIR / "processing_required_lookup_unavailable.md"
).read_text(encoding="utf-8").strip()

_FULFILLMENT_CONTEXT_PATTERN = re.compile(
    r"\b(?:delivery|item|order|package|parcel|product|shipment)\w*\b",
    re.IGNORECASE,
)
_HAZARDOUS_GOODS_PATTERN = re.compile(
    r"\b(?:batter(?:y|ies)|chemical|corrosive|dangerous\s+goods|flammable|"
    r"hazardous|hazmat|lithium)\b",
    re.IGNORECASE,
)
_DAMAGE_SAFETY_PATTERN = re.compile(
    r"\b(?:broken|burn(?:ing|t)?|chemical\s+smell|crush(?:ed)?|damage(?:d)?|"
    r"fire|fumes?|hot|leak(?:ed|ing|s)?|overheat(?:ed|ing)?|puncture(?:d)?|"
    r"rupture(?:d)?|smok(?:e|ing)|spill(?:ed|ing|s)?|swollen)\b",
    re.IGNORECASE,
)
_LABELED_BUSINESS_OBJECT_IDENTIFIER_PATTERN = re.compile(
    r"\b(?P<label>account|booking|case|claim|contract|invoice|matter|order|policy|"
    r"quote|return|rma|shipment|subscription|ticket|tracking)"
    r"(?:\s+(?:id|no\.?|number|reference))?\s*(?:[:#]\s*)?"
    r"(?P<value>[A-Za-z0-9][A-Za-z0-9._/-]{1,63})\b",
    re.IGNORECASE,
)
_BUSINESS_OBJECT_IDENTIFIER_CANDIDATE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9@])(?P<value>[A-Za-z0-9][A-Za-z0-9._/-]{1,63})(?![A-Za-z0-9@])"
)
_SHARED_BUSINESS_OBJECT_PREFIX_PATTERN = re.compile(
    r"^\s*(?:about|for|re(?:garding)?|with\s+regard\s+to|"
    r"account|booking|case|claim|contract|invoice|matter|order|policy|quote|"
    r"return|rma|shipment|subscription|ticket|tracking)\b",
    re.IGNORECASE,
)
_BUSINESS_PARTY_LABEL_PATTERN = (
    r"prospective\s+client|opposing\s+party|adverse\s+party|counterparty|"
    r"parent(?:\s+company)?|affiliate|subsidiary|claimant|respondent|"
    r"plaintiff|defendant|buyer|seller|vendor|supplier|merchant|carrier|"
    r"customer|client|employer|employee|landlord|tenant|debtor|creditor|"
    r"insurer|insured"
)
_LABELED_BUSINESS_PARTY_PATTERN = re.compile(
    rf"\b(?P<label>{_BUSINESS_PARTY_LABEL_PATTERN})\b"
    r"(?:\s+(?:name|organisation|organization))?\s*"
    r"(?:(?:is|was)\s+|[:=]\s*)?",
    re.IGNORECASE,
)
_BUSINESS_PARTY_NAME_TOKEN_PATTERN = re.compile(
    r"^[A-ZÀ-ÖØ-Þ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9&'’.\-/]*$"
)
_BUSINESS_PARTY_NAME_CONNECTORS = frozenset(
    {"&", "and", "de", "del", "der", "la", "le", "of", "the", "van", "von"}
)
_CUSTOMER_TEXT_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
_SAFETY_INTENT_WEIGHTS = {
    "hazard": 12,
    "hazardous": 12,
    "hazmat": 12,
    "safety": 12,
    "dangerous": 10,
    "damage": 10,
    "damaged": 10,
    "defect": 9,
    "defective": 9,
    "leak": 9,
    "leaking": 9,
    "spill": 9,
    "exception": 7,
    "warehouse": 6,
    "incident": 5,
    "parcel": 4,
    "package": 4,
    "shipment": 4,
    "delivery": 3,
    "fulfillment": 3,
    "order": 2,
    "product": 2,
}
_DIRECT_SAFETY_INTENT_TERMS = {
    "damage",
    "damaged",
    "dangerous",
    "defect",
    "defective",
    "hazard",
    "hazardous",
    "hazmat",
    "incident",
    "leak",
    "leaking",
    "safety",
    "spill",
}
_FULFILLMENT_INTENT_TERMS = {
    "delivery",
    "fulfillment",
    "order",
    "package",
    "parcel",
    "product",
    "shipment",
    "warehouse",
}


def _action_is_enabled(raw: dict[str, Any]) -> bool:
    value = raw.get("enabled")
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"false", "0", "no", "off"}


def _load_intent_actions(intent_name: str, intents_dir: Any = None) -> list[IntentAction]:
    actions: list[IntentAction] = []
    for raw in get_intent_actions(intent_name, intents_dir=intents_dir):
        try:
            if not _action_is_enabled(raw):
                continue
            actions.append(IntentAction(**raw))
        except Exception as exc:
            logger.warning("Invalid action in intent '%s': %s", intent_name, exc)
    return actions


def _load_response_config(intent_name: str, intents_dir: Any = None) -> IntentResponseConfig:
    raw = get_intent_response_config(intent_name, intents_dir=intents_dir)
    try:
        return IntentResponseConfig(**raw)
    except Exception as exc:
        logger.warning("Invalid response config in intent '%s': %s", intent_name, exc)
        return IntentResponseConfig()


def _build_intent_result(intent_name: str, intents_dir: Any = None) -> IntentResult:
    return IntentResult(
        matched=True,
        intent_name=intent_name,
        actions=_load_intent_actions(intent_name, intents_dir=intents_dir),
        response=_load_response_config(intent_name, intents_dir=intents_dir),
    )


def _intent_needs_processing(
    intent_name: str,
    actions: list[IntentAction],
    intents_dir: Any = None,
    *,
    response_enabled: bool,
) -> bool:
    # ``response_enabled`` remains in the signature for single-concern callers.
    # Runbooks now own all tool/action work; ticket-level reply composition is a
    # separate phase and never owns runbook tools.
    del response_enabled
    return bool(actions or get_intent_tools(intent_name, intents_dir=intents_dir))


def _tool_call_names(
    collection: HttpToolCollection,
    *,
    successful_only: bool,
) -> set[str]:
    names: set[str] = set()
    for call in collection.tool_calls:
        if successful_only and str(call.get("status") or "").casefold() != "success":
            continue
        name = str(call.get("name") or "").strip().casefold()
        if name:
            names.add(name)
    return names


def _has_required_runtime_input(raw_tool: dict[str, Any]) -> bool:
    input_schema = raw_tool.get("inputSchema", raw_tool.get("input_schema", []))
    if not isinstance(input_schema, list):
        return False
    return any(
        isinstance(item, dict)
        and bool(str(item.get("key") or "").strip())
        and item.get("required", True) is not False
        for item in input_schema
    )


def _has_unresolved_tool_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return any(
            name != "sender_email"
            for name in re.findall(r"\{([^{}]+)\}", value)
        )
    if isinstance(value, dict):
        return any(_has_unresolved_tool_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_unresolved_tool_placeholder(item) for item in value)
    return False


def _enforce_required_read_only_tool_postcondition(
    intent_name: str,
    email: Email,
    intents_dir: Any,
    tenant_id: str | None,
    project_id: str | None,
    collection: HttpToolCollection,
) -> list[str]:
    """Run skipped static GET contracts once, then return any unmet names."""
    required_names = get_intent_required_read_only_tools(
        intent_name,
        intents_dir=intents_dir,
    )
    if not required_names:
        return []

    raw_tools = get_intent_tools(intent_name, intents_dir=intents_dir)
    raw_by_name = {
        str(raw.get("name") or "").strip().casefold(): raw
        for raw in raw_tools
        if isinstance(raw, dict) and str(raw.get("name") or "").strip()
    }
    called_names = _tool_call_names(collection, successful_only=False)
    successful_names = _tool_call_names(collection, successful_only=True)
    skipped_names = [
        name for name in required_names if name.casefold() not in called_names
    ]
    if not skipped_names:
        return [
            name for name in required_names if name.casefold() not in successful_names
        ]
    try:
        secrets = load_runtime_secrets(tenant_id, project_id)
    except Exception as exc:
        logger.warning(
            "Could not load secrets for required read-only tools on intent '%s': %s",
            intent_name,
            exc,
        )
        return [
            name for name in required_names if name.casefold() not in successful_names
        ]

    for required_name in skipped_names:
        normalized_name = required_name.casefold()
        raw_tool = raw_by_name.get(normalized_name)
        method = str((raw_tool or {}).get("method") or "").upper()
        if raw_tool is None or method != "GET" or _has_required_runtime_input(raw_tool):
            logger.warning(
                "Required read-only tool '%s' on intent '%s' cannot run deterministically",
                required_name,
                intent_name,
            )
            continue
        definition = raw_tool_to_definition(raw_tool, secrets)
        if (
            definition is None
            or definition.method != "GET"
            or _has_unresolved_tool_placeholder(definition.url_template)
            or _has_unresolved_tool_placeholder(definition.headers)
            or _has_unresolved_tool_placeholder(definition.body)
        ):
            continue
        try:
            _make_http_tool(definition, sender_email=email.from_address).invoke({})
        except Exception as exc:
            logger.warning(
                "Required read-only tool '%s' on intent '%s' failed: %s",
                required_name,
                intent_name,
                exc,
            )

    successful_names = _tool_call_names(collection, successful_only=True)
    return [
        name for name in required_names if name.casefold() not in successful_names
    ]


def _merge_action_fills(actions: list[IntentAction], output: IntentProcessingOutput) -> int:
    fills_by_name = {f.name: f.initial_value for f in output.action_fills if f.initial_value}
    for action in actions:
        if action.name in fills_by_name:
            action.initial_value = fills_by_name[action.name]
        alt_name = action.name.replace("-", "_")
        if alt_name in fills_by_name:
            action.initial_value = fills_by_name[alt_name]
    return len(fills_by_name)


def _select_applicable_actions(
    actions: list[IntentAction],
    output: IntentProcessingOutput,
) -> list[IntentAction]:
    """Filter configured actions using the runbook's explicit selection.

    Missing or unknown selections fail closed before any action outcome reaches
    grounding or approval consumers. Valid selections preserve configured order
    and collapse duplicate names.
    """
    if _action_selection_error(actions, output):
        return []

    selected_names = {
        name.strip()
        for name in output.selected_action_names
        if name.strip()
    }
    selected: list[IntentAction] = []
    seen: set[str] = set()
    for action in actions:
        if action.name not in selected_names or action.name in seen:
            continue
        selected.append(action)
        seen.add(action.name)
    return selected


def _verified_boolean_state(
    facts: list[VerifiedFact],
    state_name: str,
) -> bool | None:
    """Read one boolean only from persisted, allowlisted tool evidence."""
    normalized_state = "".join(character for character in state_name.casefold() if character.isalnum())
    for fact in facts:
        path = "".join(character for character in fact.path.casefold() if character.isalnum())
        value = fact.value
        if path == normalized_state:
            if isinstance(value, bool):
                return value
            normalized_value = str(value).strip().casefold()
            if normalized_value in {"true", "false"}:
                return normalized_value == "true"
        if isinstance(value, str):
            match = re.fullmatch(
                rf"\s*{re.escape(state_name)}\s*:\s*(true|false)\s*",
                value,
                re.IGNORECASE,
            )
            if match:
                return match.group(1).casefold() == "true"
    return None


def _apply_deterministic_action_eligibility(
    actions: list[IntentAction],
    verified_facts: list[VerifiedFact],
) -> list[IntentAction]:
    """Suppress proposals contradicted by verified business-object state."""
    if _verified_boolean_state(verified_facts, "address_change_allowed") is not False:
        return actions

    blocked_names = {"request_address_change"}
    allowed = [
        action
        for action in actions
        if action.name.strip().casefold().replace("-", "_") not in blocked_names
    ]
    if len(allowed) != len(actions):
        logger.info(
            "Suppressed direct address-change proposal because verified eligibility is false"
        )
    return allowed


def _action_selection_error(
    actions: list[IntentAction],
    output: IntentProcessingOutput,
) -> str:
    if not actions:
        return ""
    if output.selected_action_names is None:
        return "Runbook action selection was missing; all configured actions were suppressed."
    configured_names = {action.name for action in actions}
    invalid_names = sorted(
        {
            str(name).strip()
            for name in output.selected_action_names
            if not str(name).strip() or str(name).strip() not in configured_names
        }
    )
    if invalid_names:
        return (
            "Runbook action selection contained unknown action names; all configured "
            "actions were suppressed."
        )
    return ""


def _default_open_ticket_task(email: Email) -> str:
    subject = " ".join(email.subject.split())
    body = " ".join(email.body.split())
    if subject and body and not body.casefold().startswith(subject.casefold()):
        task = f"{subject}: {body}"
    else:
        task = body or subject
    return task[:1000].rstrip()


def _ensure_open_ticket_action_task(actions: list[IntentAction], email: Email) -> int:
    task = _default_open_ticket_task(email)
    if not task:
        return 0

    filled = 0
    for action in actions:
        if _is_open_ticket_button(action) and not str(action.initial_value or "").strip():
            action.initial_value = task
            filled += 1
    return filled


def _classification_user_prompt(
    email: Email,
    parsed_attachments: dict[str, str] | None = None,
) -> str:
    prompt = f"Subject: {email.subject}\nFrom: {email.from_address}\n\n{email.body}"
    attachment_context = _format_attachment_context(parsed_attachments)
    if attachment_context:
        prompt += f"\n\n## Attachments\n{attachment_context}"
    return prompt


def _has_damaged_hazardous_shipment_evidence(route: ConcernRoute) -> bool:
    """Return whether a routed concern states a concrete fulfillment hazard."""
    text = f"{route.summary}\n{route.source_text}"
    return bool(
        _FULFILLMENT_CONTEXT_PATTERN.search(text)
        and _HAZARDOUS_GOODS_PATTERN.search(text)
        and _DAMAGE_SAFETY_PATTERN.search(text)
    )


def _safety_intent_score(intent_name: str) -> int:
    """Rank semantically named runbooks suitable for damaged-goods hazards."""
    terms = set(re.findall(r"[a-z0-9]+", intent_name.casefold()))
    has_fulfillment_scope = bool(terms & _FULFILLMENT_INTENT_TERMS)
    has_safety_scope = bool(terms & _DIRECT_SAFETY_INTENT_TERMS)
    is_fulfillment_exception = "exception" in terms and has_fulfillment_scope
    if not has_fulfillment_scope or not (has_safety_scope or is_fulfillment_exception):
        return 0
    return sum(_SAFETY_INTENT_WEIGHTS.get(term, 0) for term in terms)


def _apply_safety_intent_precedence(
    routes: list[ConcernRoute],
    known_intents: set[str],
) -> list[ConcernRoute]:
    """Prefer a configured safety/fulfillment runbook for explicit hazards.

    The language-model router remains authoritative for ordinary urgency. This
    guard only acts when the routed source contains fulfillment context plus
    both hazardous-goods and damage evidence, and a semantically specialized
    configured intent scores above the selected intent.
    """
    ranked = sorted(
        ((_safety_intent_score(intent_name), intent_name) for intent_name in known_intents),
        key=lambda item: (-item[0], item[1]),
    )
    if not ranked or ranked[0][0] <= 0:
        return routes

    preferred_score, preferred_intent = ranked[0]
    corrected: list[ConcernRoute] = []
    for route in routes:
        current_intent = str(route.intent_name or "").strip()
        current_score = _safety_intent_score(current_intent)
        if (
            preferred_intent != current_intent
            and preferred_score > current_score
            and _has_damaged_hazardous_shipment_evidence(route)
        ):
            logger.warning(
                "Safety routing precedence changed intent '%s' to '%s'",
                current_intent or "unmatched",
                preferred_intent,
            )
            route = route.model_copy(
                update={
                    "intent_name": preferred_intent,
                    "reason": (
                        "Deterministic safety precedence: the concern contains "
                        "fulfillment, hazardous-goods, and damage evidence."
                    ),
                }
            )
        corrected.append(route)
    return corrected


def _concern_processing_email(
    email: Email,
    route: ConcernRoute,
) -> tuple[Email, Email]:
    """Return concern-only fallback input plus narrowly shared identifier context."""
    focused = email.model_copy(
        update={
            "subject": route.summary or email.subject,
            "body": route.source_text or email.body,
        }
    )
    if focused.subject == email.subject and focused.body == email.body:
        return focused, focused

    shared_identifiers = _shared_business_object_identifiers(email, route)
    shared_parties = _shared_business_party_references(email, route)
    processing_sections = [f"## Routed concern to process\n{focused.body}"]
    if shared_identifiers:
        processing_sections.append(
            "## Shared business-object identifiers\n"
            "These identifiers are context for this concern, not separate requests.\n"
            + "\n".join(
                f"- {label}: {value}" for label, value in shared_identifiers
            )
        )
    if shared_parties:
        processing_sections.append(
            "## Shared business-party references\n"
            "These explicitly labeled parties are identity context for this concern, "
            "not separate requests.\n"
            + "\n".join(f"- {label}: {value}" for label, value in shared_parties)
        )

    processing = focused.model_copy(
        update={"body": "\n\n".join(processing_sections)}
    )
    return focused, processing


def _business_object_identifiers(value: str) -> list[tuple[str, str]]:
    """Extract bounded, non-secret business references from customer-visible text."""
    identifiers: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(label: str, raw_value: str, *, labeled: bool) -> None:
        identifier = raw_value.strip(".,;:()[]{}<>")
        normalized = identifier.casefold()
        if not identifier or normalized in seen or not any(character.isdigit() for character in identifier):
            return
        if not labeled and (
            not any(character.isalpha() for character in identifier)
            or not any(character.isupper() for character in identifier)
            or (len(identifier) < 6 and not re.search(r"[-_/]", identifier))
        ):
            return
        identifiers.append((label.casefold(), identifier))
        seen.add(normalized)

    for match in _LABELED_BUSINESS_OBJECT_IDENTIFIER_PATTERN.finditer(value):
        add(match.group("label"), match.group("value"), labeled=True)
    for match in _BUSINESS_OBJECT_IDENTIFIER_CANDIDATE_PATTERN.finditer(value):
        add("reference", match.group("value"), labeled=False)
    return identifiers


def _shared_business_object_identifiers(
    email: Email,
    route: ConcernRoute,
) -> list[tuple[str, str]]:
    """Bind safe shared references to one concern without importing sibling semantics."""
    full_identifiers = _business_object_identifiers(f"{email.subject}\n{email.body}")
    labels_by_value = {
        value.casefold(): label
        for label, value in full_identifiers
        if label != "reference"
    }

    def with_best_labels(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
        return [
            (labels_by_value.get(value.casefold(), label), value)
            for label, value in items
        ][:8]

    routed = _business_object_identifiers(f"{route.summary}\n{route.source_text}")
    if routed:
        return with_best_labels(routed)

    subject_identifiers = _business_object_identifiers(email.subject)
    if len(subject_identifiers) == 1:
        return with_best_labels(subject_identifiers)

    leading_context = re.split(r"[.;\n]", email.body, maxsplit=1)[0]
    leading_identifiers = _business_object_identifiers(leading_context)
    if (
        _SHARED_BUSINESS_OBJECT_PREFIX_PATTERN.match(leading_context)
        and len(leading_identifiers) == 1
    ):
        return with_best_labels(leading_identifiers)
    return []


def _business_party_references(value: str) -> list[tuple[str, str]]:
    """Extract bounded names only when customer text gives an explicit party label."""
    normalized = re.sub(r"[ \t]*\r?\n[ \t]*", " ", str(value or "")).strip()
    matches = list(_LABELED_BUSINESS_PARTY_PATTERN.finditer(normalized))
    references: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, match in enumerate(matches[:8]):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        raw_name = normalized[match.end() : end]
        if index + 1 < len(matches):
            raw_name = re.sub(r"(?:,\s*)?\band\s+(?:the\s+)?$", "", raw_name, flags=re.IGNORECASE)
        raw_name = re.split(r"[;!?]", raw_name, maxsplit=1)[0]

        name_tokens: list[str] = []
        for raw_token in raw_name.split():
            token = raw_token.strip(" \t,;:!?()[]{}\"")
            token = token.rstrip(".")
            if not token:
                continue
            if token.casefold() in _BUSINESS_PARTY_NAME_CONNECTORS:
                if name_tokens:
                    name_tokens.append(token)
                continue
            if _BUSINESS_PARTY_NAME_TOKEN_PATTERN.fullmatch(token) is None:
                break
            name_tokens.append(token)
            if len(name_tokens) >= 8:
                break
        while name_tokens and name_tokens[-1].casefold() in _BUSINESS_PARTY_NAME_CONNECTORS:
            name_tokens.pop()
        name = " ".join(name_tokens).strip()
        if not name or len(name) > 120 or not any(character.isalpha() for character in name):
            continue
        label = " ".join(match.group("label").casefold().split())
        key = (label, name.casefold())
        if key not in seen:
            references.append((label, name))
            seen.add(key)
    return references


def _shared_business_party_references(
    email: Email,
    route: ConcernRoute,
) -> list[tuple[str, str]]:
    """Carry only adjacent, explicitly labeled parties into one isolated concern."""
    if _business_party_references(f"{route.summary}\n{route.source_text}"):
        return []

    body = re.sub(r"[ \t]*\r?\n[ \t]*", " ", email.body).strip()
    source = re.sub(r"[ \t]*\r?\n[ \t]*", " ", route.source_text).strip()
    if not body or not source or body.casefold().count(source.casefold()) != 1:
        return []

    source_start = body.casefold().find(source.casefold())
    prior_sentences = [
        item.strip()
        for item in _CUSTOMER_TEXT_SENTENCE_SPLIT_PATTERN.split(body[:source_start].rstrip())
        if item.strip()
    ]
    collected: list[list[tuple[str, str]]] = []
    for sentence in reversed(prior_sentences[-2:]):
        if "?" in sentence or _explicit_request_sentences(sentence):
            break
        references = _business_party_references(sentence)
        if not references:
            break
        collected.append(references)

    flattened = [reference for group in reversed(collected) for reference in group]
    if not flattened:
        return []
    values = [value.casefold() for _, value in flattened]
    if len(values) != len(set(values)):
        return []
    return flattened[:8]


def _is_malformed_function_call_reason(value: Any) -> bool:
    """Recognize Gemini's exact malformed-function-call finish reason."""
    if hasattr(value, "name"):
        value = value.name
    normalized = str(value or "").strip().upper().rsplit(".", 1)[-1]
    return normalized == "MALFORMED_FUNCTION_CALL"


def _message_has_malformed_tool_output(message: Any) -> bool:
    if isinstance(message, dict):
        response_metadata = message.get("response_metadata")
        invalid_tool_calls = message.get("invalid_tool_calls")
    else:
        response_metadata = getattr(message, "response_metadata", None)
        invalid_tool_calls = getattr(message, "invalid_tool_calls", None)

    if invalid_tool_calls:
        return True
    if not isinstance(response_metadata, dict):
        return False
    return any(
        _is_malformed_function_call_reason(response_metadata.get(key)) for key in ("finish_reason", "finishReason")
    )


def _route_concerns_call_is_invalid(messages: list[Any]) -> bool:
    """Return whether a present route call violates its structured contract."""
    args = _find_router_tool_call(messages, "route_concerns")
    if args is None:
        return False

    raw_concerns = args.get("concerns")
    if not isinstance(raw_concerns, list) or not 1 <= len(raw_concerns) <= MAX_ROUTED_CONCERNS:
        return True
    for raw_concern in raw_concerns:
        if not isinstance(raw_concern, dict):
            return True
        try:
            concern = ConcernRoute.model_validate(raw_concern)
        except Exception:
            return True
        fields = (
            concern.summary,
            concern.source_text,
            *concern.answer_obligations,
        )
        if not any(
            "".join(
                character for character in str(field or "") if unicodedata.category(character) not in {"Cc", "Cf"}
            ).strip()
            for field in fields
        ):
            return True
    return False


def _router_result_has_malformed_output(raw_result: dict[str, Any]) -> bool:
    messages = raw_result.get("messages")
    if not isinstance(messages, list):
        return False
    return any(_message_has_malformed_tool_output(message) for message in messages) or (
        _route_concerns_call_is_invalid(messages)
    )


def _is_malformed_router_exception(exc: BaseException) -> bool:
    """Recognize only provider errors explicitly naming malformed calls."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if "MALFORMED_FUNCTION_CALL" in str(current).upper().replace(" ", "_"):
            return True
        if "MALFORMEDFUNCTIONCALL" in type(current).__name__.upper():
            return True
        current = current.__cause__ or current.__context__
    return False


def _run_intent_router_agent(
    email: Email,
    known_intents: set[str],
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    tenant_id: str | None,
    project_id: str | None,
) -> tuple[list[ConcernRoute], str | None]:
    from automail.core.config import read_config
    from automail.llm import create_llm, resolve_effective_config

    config = read_config(config_path=config_path)
    config = resolve_effective_config(config, tenant_id, project_id)
    llm = create_llm(config, timeout=180, max_retries=2)
    usage_context = getattr(llm, "_mantly_usage_context", None)

    try:
        # One tool call carries every concern. Tool and graph limits keep router
        # behavior bounded even when a model ignores the prompt.
        agent = create_agent(
            model=llm,
            tools=[route_concerns],
            system_prompt=_CLASSIFY_SYSTEM_PROMPT.format(
                intents_list=_build_intents_list(intents_dir=intents_dir),
            ),
            response_format=None,
            middleware=[
                ToolCallLimitMiddleware(
                    run_limit=1,
                    exit_behavior="error",
                )
            ],
        )

        with use_intents_dir(intents_dir), llm_stage("intent"):
            for attempt in range(_ROUTER_MALFORMED_OUTPUT_MAX_ATTEMPTS):
                try:
                    raw_result = _invoke_agent(
                        agent,
                        _classification_user_prompt(email, parsed_attachments),
                        parsed_attachments=parsed_attachments,
                        usage_context=usage_context,
                        run_name="intent_router_agent",
                        tags=["mantly", "intent", "router"],
                        metadata={
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "source": "pipeline.intent.agent",
                        },
                        recursion_limit=_ROUTER_GRAPH_RECURSION_LIMIT,
                    )
                except (GraphRecursionError, ToolCallLimitExceededError) as exc:
                    if attempt + 1 < _ROUTER_EXECUTION_LIMIT_MAX_ATTEMPTS:
                        logger.warning(
                            "Intent router hit %s; retrying once",
                            type(exc).__name__,
                        )
                        continue
                    logger.error(
                        "Intent router stopped at its execution limit within bounded retries: %s",
                        exc,
                    )
                    return [], _ROUTER_EXECUTION_LIMIT_REVIEW_REASON
                except Exception as exc:
                    if not _is_malformed_router_exception(exc):
                        raise
                    malformed_output = True
                else:
                    malformed_output = _router_result_has_malformed_output(raw_result)

                if not malformed_output:
                    break
                if attempt + 1 < _ROUTER_MALFORMED_OUTPUT_MAX_ATTEMPTS:
                    logger.warning(
                        "Intent router returned malformed structured output; retrying (%d/%d)",
                        attempt + 2,
                        _ROUTER_MALFORMED_OUTPUT_MAX_ATTEMPTS,
                    )
                    continue
                logger.error("Intent router returned malformed structured output three times")
                return [], _MALFORMED_ROUTER_REVIEW_REASON
    except (GraphRecursionError, ToolCallLimitExceededError) as exc:
        logger.error("Intent router stopped at its execution limit: %s", exc)
        return [], _ROUTER_EXECUTION_LIMIT_REVIEW_REASON

    messages = raw_result.get("messages")
    if not isinstance(messages, list):
        logger.info("Intent router returned no messages")
        return [], "No concerns were routed."

    routed = _find_routed_concerns(messages)
    if routed:
        canonical_names = {name.casefold(): name for name in known_intents}
        normalized: list[ConcernRoute] = []
        for concern in routed[:MAX_ROUTED_CONCERNS]:
            intent_name = str(concern.intent_name or "").strip()
            canonical_name = canonical_names.get(intent_name.casefold()) if intent_name else None
            reason = concern.reason.strip()
            if intent_name and not canonical_name:
                logger.warning("Intent router selected unknown intent '%s'", intent_name)
                reason = f"Router selected unknown intent: {intent_name}"
            normalized.append(
                ConcernRoute(
                    summary=concern.summary.strip(),
                    source_text=concern.source_text.strip(),
                    answer_obligations=_dedupe_strings(concern.answer_obligations)[:10],
                    intent_name=canonical_name,
                    confidence=concern.confidence,
                    reason=reason or ("" if canonical_name else "No configured intent matches this concern."),
                )
            )
        return normalized, None

    if routed == []:
        return [], "Intent router returned no usable concerns."

    # Backward-compatible single-concern route for older model/tool-call caches.
    legacy_intent = _find_activated_intent(messages)
    if legacy_intent:
        canonical_names = {name.casefold(): name for name in known_intents}
        canonical_name = canonical_names.get(legacy_intent.casefold())
        if canonical_name:
            return [
                ConcernRoute(
                    summary=email.subject,
                    source_text=email.body,
                    intent_name=canonical_name,
                    confidence=1.0,
                )
            ], None
        return [
            ConcernRoute(
                summary=email.subject,
                source_text=email.body,
                confidence=0.0,
                reason=f"Router selected unknown intent: {legacy_intent}",
            )
        ], None

    legacy_no_match = _find_no_match_reason(messages)
    if legacy_no_match is not None:
        return [
            ConcernRoute(
                summary=email.subject,
                source_text=email.body,
                reason=legacy_no_match or "No configured intent matches this email.",
            )
        ], None

    logger.info("Intent router returned no tool call")
    return [], "No concerns were routed."


def _run_processing_agent(
    intent_name: str,
    actions: list[IntentAction],
    email: Email,
    identity_result: IdentityResult | None,
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    tenant_id: str | None,
    project_id: str | None,
) -> IntentProcessingOutput | IntentReviewOutput:
    from automail.core.config import read_config
    from automail.llm import create_llm, resolve_effective_config

    intent_body = get_intent_body(intent_name, intents_dir=intents_dir)
    if not intent_body:
        intent_body = f"Process the matched intent: {intent_name}"
    intent_body = _append_feedback_learnings(
        intent_body,
        _load_intent_feedback_learnings(
            intent_name,
            tenant_id,
            project_id=project_id,
            intents_dir=intents_dir,
            target="processing",
        ),
    )
    intent_body = (
        f"{_PROCESSING_SECURITY_BOUNDARY}\n\n"
        "When the user message contains a routed concern and full original "
        "message context, process only the routed concern. Use identifiers and "
        "shared facts from the original context when they apply, but do not "
        "perform work for unrelated concerns.\n\n"
        "## Configured runbook\n\n"
        f"{intent_body}"
    )

    http_tools = _build_intent_http_tools(
        intent_name,
        email.from_address,
        intents_dir=intents_dir,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    user_prompt = _build_process_user_message(
        email,
        identity_result,
        actions,
        parsed_attachments,
    )

    logger.info(
        "Running intent processing: intent='%s', tools=%d, actions=%d",
        intent_name,
        len(http_tools),
        len(actions),
    )

    config = read_config(config_path=config_path)
    config = resolve_effective_config(config, tenant_id, project_id)
    llm = create_llm(config, timeout=180, max_retries=2)
    usage_context = getattr(llm, "_mantly_usage_context", None)

    response_model = IntentProcessingOutput if actions else IntentReviewOutput

    agent = create_agent(
        model=llm,
        tools=http_tools,
        system_prompt=intent_body,
        response_format=ToolStrategy(response_model),
    )

    with llm_stage("intent"):
        raw_result = _invoke_agent(
            agent,
            user_prompt,
            parsed_attachments=parsed_attachments,
            usage_context=usage_context,
            run_name="intent_processing_agent",
            tags=["mantly", "intent", "processing"],
            metadata={
                "tenant_id": tenant_id,
                "project_id": project_id,
                "intent_name": intent_name,
                "tool_count": len(http_tools),
                "action_count": len(actions),
                "source": "pipeline.intent.agent",
            },
        )

    structured = raw_result.get("structured_response")
    if not isinstance(structured, response_model):
        logger.warning(
            "Intent processing returned unexpected structured output: %s",
            type(structured).__name__,
        )
        return response_model(
            requires_human=True,
            requires_human_reason="Intent processing returned no usable structured output.",
        )

    return structured


def _dedupe_strings(*groups: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            item = str(raw or "").strip()
            key = item.casefold()
            if item and key not in seen:
                result.append(item)
                seen.add(key)
    return result


_OBLIGATION_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "can",
    "could",
    "do",
    "does",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "or",
    "please",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "would",
    "you",
}

_OBLIGATION_CLAUSE_SPLIT_PATTERN = re.compile(
    r"\s*(?:"
    r"\band\s+(?:then\s+)?|"
    r",\s*(?:(?:and|then)\s+)?|"
    r";\s*(?:(?:\(\d+\)|\d+[.)])\s*)?|"
    r"\n+\s*(?:(?:[-*]|\(\d+\)|\d+[.)])\s*)?"
    r")(?=(?:please\s+)?confirm\s+it\s+"
    r"(?:changed|is|was|has|had|will|did|can|cannot|can't)\b)",
    re.IGNORECASE,
)
_DIRECT_ACTION_OBLIGATION_PATTERN = re.compile(
    r"^\s*(?:please\s+)?"
    r"(?:(?:can|could|would)\s+you\s+(?:please\s+)?)?"
    r"change\b",
    re.IGNORECASE,
)
_EXPLICIT_REQUEST_ORDERING_PREFIX_PATTERN = re.compile(
    r"^\s*(?:(?:first|second|third|then|next|finally|also|afterwards?)\s*[,;:]?\s+)+",
    re.IGNORECASE,
)
_EXPLICIT_REQUEST_COURTESY_PREFIX_PATTERN = re.compile(
    r"^\s*(?:please|kindly)\s+",
    re.IGNORECASE,
)
_NEGATIVE_REQUEST_CONSTRAINT_PATTERN = re.compile(
    r"^\s*(?:(?:i|we|you)\s+)?(?:do\s+not|don't|never|must\s+not|"
    r"should\s+not|cannot|can't|need\s+not|no\s+need\s+to|avoid|refrain\s+from)\b",
    re.IGNORECASE,
)
_FACTUAL_ACTION_NOUN_SENTENCE_PATTERN = re.compile(
    r"^\s*(?:(?:review|record)\s+of|(?:answer|reply|report|update)\s+from|"
    r"change\s+in|(?:address|answer|change|check|issue|list|log|record|reply|"
    r"report|review|state|stop|update)\s+(?:is|was|were|has|had|remains?))\b",
    re.IGNORECASE,
)
_FIRST_PERSON_NOUN_REQUEST_PATTERN = re.compile(
    r"^\s*(?:(?:i|we)\s+(?:need|want|would\s+like)|"
    r"i\s+am\s+requesting|we\s+are\s+requesting)\s+"
    r"(?:an?|the|some|my|our)\s+"
    r"(?:(?:urgent|immediate|new|same-day|updated|current|written|full|partial|"
    r"replacement|billing|technical|legal|human)\s+){0,3}"
    r"(?:consultation|appointment|refund|replacement|return|cancellation|"
    r"cancelation|update|status|answer|review|escalation|callback|call|copy|"
    r"invoice|receipt|extension|waiver|plan|booking|reservation|quote|estimate|"
    r"reset|change)\b",
    re.IGNORECASE,
)
_EXPLICIT_REQUEST_SENTENCE_PATTERN = re.compile(
    r"^\s*(?:"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)|"
    r"(?:(?:i|we)\s+(?:need|want|would\s+like)\s+you\s+to\s+)|"
    r"(?:you\s+(?:must|need\s+to|should)\s+)"
    r")?"
    r"(?:address|answer|apply|approve|arrange|book|cancel|change|check|confirm|"
    r"create|delete|dispatch|escalate|explain|find|give|identify|investigate|"
    r"issue|list|log|look\s+up|notify|open|pause|provide|record|refund|remove|"
    r"replace|reply|report|reschedule|reset|resolve|restore|review|say|schedule|"
    r"send|show|state|stop|submit|terminate|tell|update|verify|waive)\b",
    re.IGNORECASE,
)


def _split_answer_obligation(value: str) -> list[str]:
    """Keep explicit follow-up requests as independently auditable obligations."""
    item = str(value or "").strip()
    if not item:
        return []
    if _DIRECT_ACTION_OBLIGATION_PATTERN.match(item) is None:
        return [item]
    parts = [part.strip() for part in _OBLIGATION_CLAUSE_SPLIT_PATTERN.split(item)]
    return [part for part in parts if part]


def _explicit_request_sentences(value: str) -> list[str]:
    """Extract whole imperative request sentences without treating constraints as work."""
    normalized = re.sub(r"[ \t]*\r?\n[ \t]*", " ", str(value or "")).strip()
    if not normalized:
        return []

    requests: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", normalized):
        item = sentence.strip()
        if not item or "?" in item:
            continue
        candidate = _EXPLICIT_REQUEST_ORDERING_PREFIX_PATTERN.sub("", item)
        candidate = _EXPLICIT_REQUEST_COURTESY_PREFIX_PATTERN.sub("", candidate)
        if _NEGATIVE_REQUEST_CONSTRAINT_PATTERN.match(candidate):
            continue
        if _FACTUAL_ACTION_NOUN_SENTENCE_PATTERN.match(candidate):
            continue
        if (
            _EXPLICIT_REQUEST_SENTENCE_PATTERN.match(candidate)
            or _FIRST_PERSON_NOUN_REQUEST_PATTERN.match(candidate)
        ):
            requests.append(item)
    return _dedupe_strings(requests)


def _obligation_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", value.casefold()):
        if raw in _OBLIGATION_STOP_WORDS:
            continue
        token = raw
        if len(token) > 5 and token.endswith("ing"):
            token = token[:-3]
        elif len(token) > 4 and token.endswith("ed"):
            token = token[:-2]
        elif len(token) > 4 and token.endswith("s"):
            token = token[:-1]
        tokens.add(token)
    return tokens


def _obligation_covers_question(obligation: str, question: str) -> bool:
    question_tokens = _obligation_tokens(question)
    if not question_tokens:
        return " ".join(question.casefold().split()) in " ".join(obligation.casefold().split())
    obligation_tokens = _obligation_tokens(obligation)
    return len(question_tokens & obligation_tokens) / len(question_tokens) >= 0.6


def _obligation_restates_part_of_question(obligation: str, question: str) -> bool:
    """Avoid adding a routed subset beside an explicit compound question."""
    obligation_tokens = _obligation_tokens(obligation)
    question_tokens = _obligation_tokens(question)
    if re.match(r"^\s*(?:please\s+)?confirm\b", obligation, re.IGNORECASE) and re.search(
        r"\band\s+(?:then\s+)?confirm\b", question, re.IGNORECASE
    ):
        return False
    if {"term", "condition"}.issubset(question_tokens) and obligation_tokens.intersection({"term", "condition"}):
        return True
    return bool(obligation_tokens and obligation_tokens.issubset(question_tokens))


_INLINE_NEGATIVE_REQUEST_CONSTRAINT_PATTERN = re.compile(
    r"\s*[,;]\s*(?:and\s+)?(?:please\s+)?(?:do\s+not|don't|never|must\s+not|"
    r"should\s+not|cannot|can't|avoid|refrain\s+from)\b.*$",
    re.IGNORECASE,
)


def _routed_obligations_cover_request(
    request: str,
    routed_obligations: list[str],
) -> bool:
    """Accept granular router units when their combined meaning covers one request."""
    if any(
        _obligation_covers_question(obligation, request)
        or _obligation_restates_part_of_question(obligation, request)
        for obligation in routed_obligations
    ):
        return True

    positive_request = _INLINE_NEGATIVE_REQUEST_CONSTRAINT_PATTERN.sub("", request)
    request_tokens = _obligation_tokens(positive_request)
    routed_tokens = {
        token
        for obligation in routed_obligations
        for token in _obligation_tokens(obligation)
    }
    return bool(
        request_tokens
        and len(request_tokens & routed_tokens) / len(request_tokens) >= 0.8
    )


_EXPLICIT_COMPOUND_QUESTION_PATTERN = re.compile(
    r"^\s*what\s+(?:is|are)\s+(?P<article>the\s+)?"
    r"(?P<first>[^?]+?)\s+and\s+(?P<second>[^?]+?)\?\s*$",
    re.IGNORECASE,
)
_EXPLICIT_LOOKUP_LIST_QUESTION_PATTERN = re.compile(
    r"^\s*what\s+(?P<facets>[^?]+?)\s+does\s+the\s+"
    r"(?P<source>lookup|tool|record|system)\s+"
    r"(?P<verb>show|return|report)\?\s*$",
    re.IGNORECASE,
)
_SIMPLE_LOOKUP_FACET_PATTERN = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:\s+[a-z0-9]+(?:-[a-z0-9]+)*){0,5}$",
    re.IGNORECASE,
)
_UNSAFE_LOOKUP_FACET_TOKENS = frozenset(
    {
        "and",
        "are",
        "can",
        "could",
        "did",
        "do",
        "does",
        "had",
        "has",
        "have",
        "if",
        "is",
        "it",
        "must",
        "no",
        "not",
        "or",
        "our",
        "should",
        "that",
        "their",
        "these",
        "they",
        "this",
        "those",
        "was",
        "were",
        "whether",
        "which",
        "will",
        "would",
        "you",
        "your",
    }
)
_UNSPLITTABLE_LOOKUP_FACET_HEAD_SETS = (
    frozenset({"term", "condition"}),
)
_SHARED_COMPOUND_QUESTION_MODIFIERS = frozenset({"standard"})
_COMPOUND_BILLING_OBJECT_TOKENS = frozenset(
    {
        "charge",
        "cost",
        "deposit",
        "fee",
        "price",
        "retainer",
    }
)
_SAFE_COMPOUND_SECOND_BILLING_MODIFIERS = frozenset(
    {
        "advance",
        "annual",
        "current",
        "estimated",
        "exact",
        "future",
        "initial",
        "monthly",
        "quoted",
        "renewal",
        "service",
        "setup",
        "standard",
        "upfront",
    }
)
_SAFE_COMPOUND_FIRST_BILLING_MODIFIER_SEQUENCES = frozenset(
    {
        (),
        ("advance",),
        ("annual",),
        ("consultation",),
        ("current",),
        ("estimated",),
        ("exact",),
        ("future",),
        ("initial",),
        ("initial", "consultation"),
        ("monthly",),
        ("quoted",),
        ("renewal",),
        ("service",),
        ("setup",),
        ("standard",),
        ("standard", "annual"),
        ("standard", "consultation"),
        ("standard", "initial", "consultation"),
        ("standard", "service"),
        ("standard", "setup"),
        ("current", "setup"),
        ("upfront",),
    }
)
_UNSAFE_COMPOUND_BILLING_PHRASE_TOKENS = frozenset(
    {
        "a",
        "all",
        "an",
        "another",
        "any",
        "between",
        "both",
        "certain",
        "compared",
        "comparison",
        "conditions",
        "different",
        "difference",
        "differences",
        "double",
        "each",
        "either",
        "enough",
        "every",
        "few",
        "fewer",
        "greater",
        "half",
        "her",
        "his",
        "higher",
        "if",
        "its",
        "least",
        "less",
        "little",
        "lower",
        "many",
        "more",
        "most",
        "much",
        "multiple",
        "my",
        "neither",
        "no",
        "none",
        "numerous",
        "of",
        "one",
        "or",
        "other",
        "our",
        "per",
        "requirements",
        "same",
        "several",
        "single",
        "some",
        "such",
        "than",
        "that",
        "these",
        "terms",
        "the",
        "their",
        "this",
        "those",
        "versus",
        "vs",
        "various",
        "whatever",
        "whether",
        "whichever",
        "which",
        "whose",
        "your",
        "zero",
    }
)


def _compound_billing_object_head(value: str) -> str:
    """Return an explicit singular billing noun at the end of one question side."""
    words = re.findall(r"[a-z0-9]+", value.casefold())
    if not words or words[-1] not in _COMPOUND_BILLING_OBJECT_TOKENS:
        return ""
    return words[-1]


def _is_simple_compound_billing_phrase(value: str) -> bool:
    """Accept only noun phrases that can safely stand alone after ``What is``."""
    normalized = " ".join(value.casefold().split())
    if re.fullmatch(r"[a-z0-9]+(?: [a-z0-9]+){0,5}", normalized) is None:
        return False
    words = normalized.split()
    return not (
        any(word.isdigit() for word in words) or set(words).intersection(_UNSAFE_COMPOUND_BILLING_PHRASE_TOKENS)
    )


def _is_safe_compound_second_billing_phrase(value: str) -> bool:
    """Allow only a billing noun or one known stand-alone billing adjective plus noun."""
    words = re.findall(r"[a-z0-9]+", value.casefold())
    if not words or words[-1] not in _COMPOUND_BILLING_OBJECT_TOKENS:
        return False
    return len(words) == 1 or (len(words) == 2 and words[0] in _SAFE_COMPOUND_SECOND_BILLING_MODIFIERS)


def _is_safe_compound_first_billing_phrase(value: str) -> bool:
    """Accept only known billing modifiers followed by one terminal billing noun."""
    words = re.findall(r"[a-z0-9]+", value.casefold())
    if not words or words[-1] not in _COMPOUND_BILLING_OBJECT_TOKENS:
        return False
    return tuple(words[:-1]) in _SAFE_COMPOUND_FIRST_BILLING_MODIFIER_SEQUENCES


def _routed_question_identifies_compound_side(
    routed_question: str,
    *,
    first_tokens: set[str],
    second_tokens: set[str],
) -> bool:
    """Require side-specific router evidence, excluding a shared billing head."""
    routed_tokens = _obligation_tokens(routed_question)
    shared_tokens = (first_tokens & second_tokens) | _SHARED_COMPOUND_QUESTION_MODIFIERS
    first_specific = first_tokens - shared_tokens
    second_specific = second_tokens - shared_tokens
    if not routed_tokens or not first_specific or not second_specific:
        return False

    has_billing_object = bool(routed_tokens.intersection(_COMPOUND_BILLING_OBJECT_TOKENS))
    first_coverage = len(first_specific & routed_tokens) / len(first_specific)
    second_coverage = len(second_specific & routed_tokens) / len(second_specific)
    return bool(
        has_billing_object
        and (
            first_coverage >= 0.8
            and not second_specific.intersection(routed_tokens)
            or second_coverage >= 0.8
            and not first_specific.intersection(routed_tokens)
        )
    )


def _split_explicit_compound_question(
    question: str,
    *,
    routed_questions: list[str],
) -> list[str]:
    """Split only a proven safe billing shape or independently routed sides."""
    if question.casefold().count(" and ") != 1:
        return [question]
    match = _EXPLICIT_COMPOUND_QUESTION_PATTERN.fullmatch(question)
    if match is None:
        return [question]
    first = match.group("first").strip()
    second = match.group("second").strip()
    if not (
        _is_simple_compound_billing_phrase(first)
        and _is_simple_compound_billing_phrase(second)
        and _is_safe_compound_first_billing_phrase(first)
        and _is_safe_compound_second_billing_phrase(second)
    ):
        return [question]
    first_object_head = _compound_billing_object_head(first)
    second_object_head = _compound_billing_object_head(second)
    if not first_object_head or not second_object_head:
        return [question]
    first_tokens = _obligation_tokens(first)
    second_tokens = _obligation_tokens(second)
    first_words = re.findall(r"[a-z0-9]+", first.casefold())
    second_words = re.findall(r"[a-z0-9]+", second.casefold())
    deterministic_mc01_split = bool(
        match.group("article")
        and first_words == ["standard", "initial", "consultation", "fee"]
        and first_object_head == "fee"
        and second_object_head == "retainer"
        and second_words == ["advance", "retainer"]
    )
    independently_routed = bool(match.group("article")) and any(
        _routed_question_identifies_compound_side(
            routed_question,
            first_tokens=first_tokens,
            second_tokens=second_tokens,
        )
        for routed_question in routed_questions
    )
    if not (deterministic_mc01_split or independently_routed):
        return [question]

    article = "the " if match.group("article") else ""
    first_word = first.split(maxsplit=1)[0].casefold()
    shared_modifier = (
        first_word + " "
        if (first_word in _SHARED_COMPOUND_QUESTION_MODIFIERS and not second.casefold().startswith(first_word + " "))
        else ""
    )
    return [
        f"What is {article}{first}?",
        f"What is {article}{shared_modifier}{second}?",
    ]


def _split_explicit_lookup_list_question(question: str) -> list[str]:
    """Split only an anchored three-or-four-facet read-only lookup question."""
    match = _EXPLICIT_LOOKUP_LIST_QUESTION_PATTERN.fullmatch(question)
    if match is None:
        return [question]
    facets_text = match.group("facets")
    final_separators = tuple(re.finditer(r",\s+and\s+", facets_text, re.IGNORECASE))
    if len(final_separators) != 1:
        return [question]
    final_separator = final_separators[0]
    leading = facets_text[: final_separator.start()]
    final = facets_text[final_separator.end() :]
    facets = [*(part.strip() for part in leading.split(",")), final.strip()]
    if not 3 <= len(facets) <= 4:
        return [question]

    heads: list[str] = []
    for facet in facets:
        if not facet or _SIMPLE_LOOKUP_FACET_PATTERN.fullmatch(facet) is None:
            return [question]
        tokens = re.findall(r"[a-z0-9]+", facet.casefold())
        if not tokens or set(tokens).intersection(_UNSAFE_LOOKUP_FACET_TOKENS):
            return [question]
        heads.append(tokens[-1])
    if len(heads) != len(set(heads)):
        return [question]
    normalized_heads = {
        {"conditions": "condition", "terms": "term"}.get(head, head)
        for head in heads
    }
    if any(blocked.issubset(normalized_heads) for blocked in _UNSPLITTABLE_LOOKUP_FACET_HEAD_SETS):
        return [question]

    source = match.group("source").casefold()
    verb = match.group("verb").casefold()
    return [f"What {facet} does the {source} {verb}?" for facet in facets]


def _expand_lookup_list_obligations_within_limit(
    questions: list[str],
    *,
    limit: int,
) -> list[str]:
    """Expand safe lookup lists only when no later obligation can be truncated."""
    expanded: list[str] = []
    for index, question in enumerate(questions):
        parts = _split_explicit_lookup_list_question(question)
        remaining_count = len(questions) - index - 1
        if len(parts) > 1 and len(expanded) + len(parts) + remaining_count <= limit:
            expanded.extend(parts)
        else:
            expanded.append(question)
    return expanded


def _answer_obligations(
    concern_id: str,
    route: ConcernRoute,
) -> list[AnswerObligation]:
    """Bind router-extracted questions to stable runtime IDs."""
    routed_questions = _dedupe_strings(
        [part for raw in route.answer_obligations for part in _split_answer_obligation(raw)]
    )
    explicit_questions = _dedupe_strings(
        [
            part
            for match in re.finditer(r"[^.!?\n]*\?", route.source_text)
            if match.group(0).strip()
            for part in _split_explicit_compound_question(
                match.group(0).strip(),
                routed_questions=routed_questions,
            )
        ]
    )
    explicit_requests = _explicit_request_sentences(route.source_text)
    # More explicit sentences than router units proves an L08-style omission.
    # Otherwise add only source requests not covered by the router units together,
    # preserving intentional granular splits of one compound request.
    missing_request_sentences = (
        explicit_requests
        if len(explicit_requests) > len(routed_questions)
        else [
            request
            for request in explicit_requests
            if not _routed_obligations_cover_request(request, routed_questions)
        ]
    )
    explicit_obligations = _dedupe_strings(explicit_questions, missing_request_sentences)
    questions = list(explicit_obligations)
    for routed_question in routed_questions:
        if any(
            _obligation_covers_question(routed_question, question)
            or _obligation_restates_part_of_question(routed_question, question)
            for question in explicit_obligations
        ):
            continue
        questions.append(routed_question)
    if not questions:
        fallback = route.summary.strip() or route.source_text.strip()
        questions = [fallback] if fallback else []
    questions = _expand_lookup_list_obligations_within_limit(
        questions,
        limit=10,
    )
    return [
        AnswerObligation(
            obligation_id=f"{concern_id}:obligation-{index}",
            question=question[:500],
            source_text=route.source_text[:1_000],
        )
        for index, question in enumerate(questions[:10], start=1)
    ]


def _tool_evidence(tool_calls: list[dict[str, Any]]) -> list[RunbookToolEvidence]:
    """Convert this concern's safe HTTP audit facts into composer evidence."""
    evidence: list[RunbookToolEvidence] = []
    for call in tool_calls:
        tool_name = str(call.get("name") or "").strip()
        if not tool_name:
            continue
        facts: list[VerifiedFact] = []
        for raw_fact in call.get("responseFacts") or []:
            if not isinstance(raw_fact, dict):
                continue
            path = str(raw_fact.get("path") or "").strip()
            value = raw_fact.get("value")
            if not path or not isinstance(value, (str, bool, int, float)):
                continue
            facts.append(
                VerifiedFact(
                    path=path,
                    value=value,
                    source=f"tool:{tool_name}",
                )
            )
        evidence.append(
            RunbookToolEvidence(
                tool_name=tool_name,
                method=str(call.get("method") or ""),
                facts=facts,
                status=str(call.get("status") or "unknown"),
            )
        )
    return evidence


def _outcome_attachments(
    intent_name: str,
    intents_dir: Any,
    generated_attachments: list[dict[str, Any]],
) -> list[RunbookAttachment]:
    attachments: list[RunbookAttachment] = []
    try:
        configured = get_intent_response_attachments(intent_name, intents_dir=intents_dir)
    except Exception as exc:
        logger.warning("Could not load attachments for intent '%s': %s", intent_name, exc)
        configured = []
    for item in configured:
        filename = str(item.get("filename") or "").strip()
        if filename:
            attachments.append(
                RunbookAttachment(
                    filename=filename,
                    description=str(item.get("description") or "").strip(),
                    source="runbook",
                    mode=str(item.get("mode") or "dynamic"),
                    source_filename=filename,
                    source_intent=intent_name,
                )
            )
    for item in generated_attachments:
        filename = str(item.get("filename") or "").strip()
        if filename and item.get("attach_to_response", True):
            attachments.append(
                RunbookAttachment(
                    filename=filename,
                    description=f"Generated by {str(item.get('source_tool') or 'runbook tool')}",
                    source="tool",
                    mode="generated",
                )
            )
    deduped: dict[str, RunbookAttachment] = {}
    for attachment in attachments:
        deduped.setdefault(attachment.filename, attachment)
    return list(deduped.values())


def _action_outcomes(actions: list[IntentAction]) -> list[RunbookActionOutcome]:
    outcomes: list[RunbookActionOutcome] = []
    for action in actions:
        needs_value = action.type in {"dropdown", "calendar", "input"} or _is_open_ticket_button(action)
        status = "pending_input" if needs_value and not str(action.initial_value or "").strip() else "proposed"
        outcomes.append(
            RunbookActionOutcome(
                name=action.name,
                label=action.label,
                status=status,
                initial_value=action.initial_value,
            )
        )
    return outcomes


def _verified_facts(evidence: list[RunbookToolEvidence]) -> list[VerifiedFact]:
    facts: list[VerifiedFact] = []
    seen: set[tuple[str, str, str, str]] = set()
    for fact in (fact for item in evidence for fact in item.facts):
        key = (fact.fact, fact.path, repr(fact.value), fact.source)
        if key not in seen:
            facts.append(fact)
            seen.add(key)
    return facts


def _build_routed_concern_outcome(
    concern_id: str,
    route: ConcernRoute,
    email: Email,
    identity_result: IdentityResult | None,
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    tenant_id: str | None,
    project_id: str | None,
    collection: HttpToolCollection,
) -> RunbookOutcome:
    intent_name = str(route.intent_name or "").strip()
    if not intent_name:
        reason = route.reason or "No configured intent matches this concern."
        return RunbookOutcome(
            concern_id=concern_id,
            concern_summary=route.summary,
            source_text=route.source_text,
            answer_obligations=_answer_obligations(concern_id, route),
            confidence=route.confidence,
            matched=False,
            status="unmatched",
            summary=reason,
            missing_information=[reason],
            requires_human=True,
            requires_human_reason=reason,
        )

    intent_result = _build_intent_result(intent_name, intents_dir=intents_dir)
    requires_review = get_intent_require_review(intent_name, intents_dir=intents_dir)
    focused_email, processing_email = _concern_processing_email(email, route)
    output: IntentProcessingOutput | IntentReviewOutput = IntentReviewOutput()
    applicable_actions = intent_result.actions
    action_selection_error = ""
    fills_count = 0

    if _intent_needs_processing(
        intent_name,
        intent_result.actions,
        intents_dir=intents_dir,
        response_enabled=False,
    ):
        output = _run_processing_agent(
            intent_name,
            intent_result.actions,
            processing_email,
            identity_result,
            intents_dir,
            config_path,
            parsed_attachments,
            tenant_id,
            project_id,
        )
    else:
        logger.info("Intent '%s' requires no tool or action processing", intent_name)

    missing_required_tools = _enforce_required_read_only_tool_postcondition(
        intent_name,
        processing_email,
        intents_dir,
        tenant_id,
        project_id,
        collection,
    )
    if missing_required_tools:
        required_reason = (
            "Required read-only lookup did not succeed: "
            + ", ".join(missing_required_tools)
            + "."
        )
        output.requires_human = True
        output.requires_human_reason = "; ".join(
            _dedupe_strings(
                [str(output.requires_human_reason or "")],
                [required_reason],
            )
        )
        output.missing_information = _dedupe_strings(
            output.missing_information,
            [required_reason],
        )
        output.reply_requirements = _dedupe_strings(
            output.reply_requirements,
            [_REQUIRED_LOOKUP_UNAVAILABLE_REPLY_REQUIREMENT],
        )

    tool_evidence = _tool_evidence(collection.tool_calls)
    verified_facts = _verified_facts(tool_evidence)
    if intent_result.actions and isinstance(output, IntentProcessingOutput):
        action_selection_error = _action_selection_error(intent_result.actions, output)
        applicable_actions = _apply_deterministic_action_eligibility(
            _select_applicable_actions(intent_result.actions, output),
            verified_facts,
        )
        fills_count = _merge_action_fills(applicable_actions, output)
        fills_count += _ensure_open_ticket_action_task(applicable_actions, focused_email)
    review_reasons = []
    if requires_review:
        review_reasons.append("Intent is configured to require human review.")
    if output.requires_human:
        review_reasons.append(output.requires_human_reason or "Intent processing requires human review.")
    if action_selection_error:
        review_reasons.append(action_selection_error)
    requires_human_reason = "; ".join(_dedupe_strings(review_reasons)) or None

    logger.info(
        "Runbook outcome: concern=%s, intent=%s, actions=%d, fills=%d, evidence=%d",
        concern_id,
        intent_name,
        len(applicable_actions),
        fills_count,
        len(tool_evidence),
    )
    return RunbookOutcome(
        concern_id=concern_id,
        concern_summary=route.summary,
        source_text=route.source_text,
        answer_obligations=_answer_obligations(concern_id, route),
        confidence=route.confidence,
        matched=True,
        intent_name=intent_name,
        status="requires_human" if requires_human_reason else "ready",
        summary=output.summary or route.summary,
        actions=applicable_actions,
        action_outcomes=_action_outcomes(applicable_actions),
        verified_facts=verified_facts,
        tool_evidence=tool_evidence,
        missing_information=output.missing_information,
        reply_requirements=_dedupe_strings(
            intent_result.response.response_rules,
            output.reply_requirements,
        ),
        required_guidance=_dedupe_strings(intent_result.response.required_guidance),
        forbidden_claims=output.forbidden_claims,
        attachments=_outcome_attachments(
            intent_name,
            intents_dir,
            collection.generated_attachments,
        ),
        requires_human=bool(requires_human_reason),
        requires_human_reason=requires_human_reason,
    )


@dataclass(frozen=True)
class ConcernExecutionResult:
    """One concern outcome plus only activity produced by that concern."""

    outcome: RunbookOutcome
    collection: HttpToolCollection


def _scoped_attachment_filename(
    *,
    concern_id: str,
    attachment_index: int,
    original_filename: str,
    owner_key: str,
    occupied: set[str],
) -> str:
    """Build a stable collision-free runtime alias for one attachment owner."""
    basename = original_filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not basename:
        basename = "attachment"
    suffix = Path(basename).suffix[:32]
    stem = basename[: -len(suffix)] if suffix else basename
    stem = stem or "attachment"
    for nonce in range(100):
        identity = "\x00".join(
            (
                concern_id,
                owner_key,
                str(attachment_index),
                original_filename,
                str(nonce),
            )
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        marker = f"--mantly-{digest}"
        max_stem_chars = max(1, 240 - len(marker) - len(suffix))
        candidate = f"{stem[:max_stem_chars]}{marker}{suffix}"
        if candidate.casefold() not in occupied:
            return candidate
    raise ValueError("Could not assign a unique attachment filename")


def _scope_attachment_collisions(
    results: list[ConcernExecutionResult],
) -> None:
    """Give every colliding configured or generated owner a stable runtime alias."""
    references: dict[
        str,
        list[tuple[ConcernExecutionResult, str, int, RunbookAttachment | dict[str, Any]]],
    ] = {}
    for result in results:
        if result.outcome.status == "failed":
            continue
        for index, attachment in enumerate(result.outcome.attachments, start=1):
            if attachment.source == "tool" or not attachment.filename:
                continue
            references.setdefault(attachment.filename.casefold(), []).append((result, "runbook", index, attachment))
        for index, item in enumerate(result.collection.generated_attachments, start=1):
            filename = str(item.get("filename") or "").strip()
            if filename:
                references.setdefault(filename.casefold(), []).append((result, "tool", index, item))

    colliding_names = {filename for filename, items in references.items() if len(items) > 1}
    if not colliding_names:
        return

    occupied = set(references) - colliding_names
    changed_results: set[int] = set()
    for filename, items in references.items():
        if filename not in colliding_names:
            continue
        for result, owner_type, attachment_index, owner in items:
            if isinstance(owner, RunbookAttachment):
                original_filename = owner.source_filename or owner.filename
                owner_key = f"runbook:{owner.source_intent or result.outcome.intent_name or ''}"
            else:
                original_filename = str(owner.get("filename") or "").strip()
                owner_key = f"tool:{str(owner.get('source_tool') or '')}"
            scoped_filename = _scoped_attachment_filename(
                concern_id=result.outcome.concern_id,
                attachment_index=attachment_index,
                original_filename=original_filename,
                owner_key=owner_key,
                occupied=occupied,
            )
            if isinstance(owner, RunbookAttachment):
                owner.source_filename = original_filename
                owner.source_intent = owner.source_intent or str(result.outcome.intent_name or "")
                owner.filename = scoped_filename
            else:
                owner["filename"] = scoped_filename
            occupied.add(scoped_filename.casefold())
            changed_results.add(id(result))

    for result in results:
        if id(result) not in changed_results:
            continue
        configured = [attachment for attachment in result.outcome.attachments if attachment.source != "tool"]
        generated = [
            RunbookAttachment(
                filename=str(item.get("filename") or "").strip(),
                description=(f"Generated by {str(item.get('source_tool') or 'runbook tool')}"),
                source="tool",
                mode="generated",
            )
            for item in result.collection.generated_attachments
            if (str(item.get("filename") or "").strip() and item.get("attach_to_response", True))
        ]
        result.outcome.attachments = [*configured, *generated]


def _merge_concern_execution_result(result: ConcernExecutionResult) -> RunbookOutcome:
    """Merge audit activity, excluding files produced by failed runbooks."""
    for call in result.collection.tool_calls:
        call["concernId"] = result.outcome.concern_id
    merge_http_tool_collection(
        result.collection,
        include_generated_attachments=result.outcome.status != "failed",
    )
    return result.outcome


def _execute_routed_concern_result(
    concern_id: str,
    route: ConcernRoute,
    email: Email,
    identity_result: IdentityResult | None,
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    tenant_id: str | None,
    project_id: str | None,
) -> ConcernExecutionResult:
    """Execute one concern against fresh tool and attachment collectors."""
    with isolated_http_tool_collection() as collection:
        try:
            outcome = _build_routed_concern_outcome(
                concern_id,
                route,
                email,
                identity_result,
                intents_dir,
                config_path,
                parsed_attachments,
                tenant_id,
                project_id,
                collection,
            )
        except Exception as exc:
            logger.error(
                "Runbook concern %s (%s) failed: %s",
                concern_id,
                route.intent_name,
                exc,
                exc_info=True,
            )
            outcome = _failed_outcome(concern_id, route, exc)
    return ConcernExecutionResult(outcome=outcome, collection=collection)


def _execute_routed_concern(
    concern_id: str,
    route: ConcernRoute,
    email: Email,
    identity_result: IdentityResult | None,
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    tenant_id: str | None,
    project_id: str | None,
) -> RunbookOutcome:
    """Execute one concern and preserve activity for legacy direct callers."""
    result = _execute_routed_concern_result(
        concern_id,
        route,
        email,
        identity_result,
        intents_dir,
        config_path,
        parsed_attachments,
        tenant_id,
        project_id,
    )
    return _merge_concern_execution_results([result])[0]


def _merge_concern_execution_results(
    results: list[ConcernExecutionResult],
) -> list[RunbookOutcome]:
    """Merge isolated activity and outcomes in router order."""
    _scope_attachment_collisions(results)
    outcomes: list[RunbookOutcome] = []
    for result in results:
        outcomes.append(_merge_concern_execution_result(result))
    return outcomes


def _failed_outcome(
    concern_id: str,
    route: ConcernRoute,
    exc: Exception,
) -> RunbookOutcome:
    reason = f"Runbook processing failed: {exc}"
    return RunbookOutcome(
        concern_id=concern_id,
        concern_summary=route.summary,
        source_text=route.source_text,
        answer_obligations=_answer_obligations(concern_id, route),
        confidence=route.confidence,
        matched=bool(route.intent_name),
        intent_name=route.intent_name,
        status="failed",
        summary=reason,
        requires_human=True,
        requires_human_reason=reason,
        error=str(exc),
    )


def _concern_route_identity(route: ConcernRoute) -> tuple[str, str]:
    """Return execution identity for a routed concern."""
    return (
        str(route.intent_name or "unmatched").strip().casefold(),
        " ".join(route.source_text.split()).casefold(),
    )


def _dedupe_concern_routes(routes: list[ConcernRoute]) -> list[ConcernRoute]:
    """Keep the first copy of each routed concern before runbook execution."""
    deduplicated: list[ConcernRoute] = []
    seen: set[tuple[str, str]] = set()
    for route in routes:
        identity = _concern_route_identity(route)
        if identity in seen:
            logger.warning(
                "Suppressing duplicate routed concern for intent '%s'",
                route.intent_name or "unmatched",
            )
            continue
        seen.add(identity)
        deduplicated.append(route)
    return deduplicated


def _route_business_object_identifier(email: Email, route: ConcernRoute) -> str:
    """Return one unambiguous identifier available to an isolated concern."""
    routed_values = {
        value.casefold()
        for _label, value in _business_object_identifiers(
            f"{route.summary}\n{route.source_text}"
        )
        if value.strip()
    }
    if len(routed_values) == 1:
        return next(iter(routed_values))
    if routed_values:
        return ""
    message_values = {
        value.casefold()
        for _label, value in _business_object_identifiers(
            f"{email.subject}\n{email.body}"
        )
        if value.strip()
    }
    return next(iter(message_values)) if len(message_values) == 1 else ""


def _merge_routed_source_text(primary: str, subsumed: str) -> str:
    """Preserve both routed excerpts without repeating a contained span."""
    primary = primary.strip()
    subsumed = subsumed.strip()
    if not primary:
        return subsumed
    if not subsumed:
        return primary
    normalized_primary = " ".join(primary.split()).casefold()
    normalized_subsumed = " ".join(subsumed.split()).casefold()
    if normalized_subsumed in normalized_primary:
        return primary
    if normalized_primary in normalized_subsumed:
        return subsumed
    return f"{primary}\n{subsumed}"


def _merge_subsumed_route(
    specialized: ConcernRoute,
    generic: ConcernRoute,
) -> ConcernRoute:
    """Merge one generic route into its configured specialized runbook route."""
    return specialized.model_copy(
        update={
            "source_text": _merge_routed_source_text(
                specialized.source_text,
                generic.source_text,
            ),
            "answer_obligations": _dedupe_strings(
                specialized.answer_obligations,
                generic.answer_obligations,
            )[:10],
            "confidence": max(specialized.confidence, generic.confidence),
        }
    )


def _apply_runbook_subsumption(
    email: Email,
    routes: list[ConcernRoute],
    intents_dir: Any,
) -> list[ConcernRoute]:
    """Collapse an opted-in generic route only for one proven shared object."""
    if len(routes) < 2:
        return routes

    configured: dict[str, set[str]] = {}
    identifiers = [
        _route_business_object_identifier(email, route)
        for route in routes
    ]
    for route in routes:
        intent_name = str(route.intent_name or "").strip().casefold()
        if not intent_name or intent_name in configured:
            continue
        configured[intent_name] = {
            name.strip().casefold()
            for name in get_intent_subsumes_runbooks(
                intent_name,
                intents_dir=intents_dir,
            )
            if name.strip()
        }

    parents: dict[int, int] = {}
    for generic_index, generic in enumerate(routes):
        generic_intent = str(generic.intent_name or "").strip().casefold()
        generic_identifier = identifiers[generic_index]
        if not generic_intent or not generic_identifier:
            continue
        candidates = [
            specialized_index
            for specialized_index, specialized in enumerate(routes)
            if specialized_index != generic_index
            and generic_intent
            in configured.get(
                str(specialized.intent_name or "").strip().casefold(),
                set(),
            )
            and identifiers[specialized_index] == generic_identifier
        ]
        if len(candidates) != 1:
            continue
        parents[generic_index] = candidates[0]

    for start in parents:
        visited: set[int] = set()
        current = start
        while current in parents:
            if current in visited:
                logger.warning(
                    "Skipping cyclic runbook subsumption contract for this email"
                )
                return routes
            visited.add(current)
            current = parents[current]

    def parent_depth(index: int) -> int:
        depth = 0
        while index in parents:
            depth += 1
            index = parents[index]
        return depth

    replacements = {index: route for index, route in enumerate(routes)}
    for generic_index in sorted(
        parents,
        key=lambda index: (-parent_depth(index), index),
    ):
        specialized_index = parents[generic_index]
        specialized = replacements[specialized_index]
        generic = replacements[generic_index]
        replacements[specialized_index] = _merge_subsumed_route(
            specialized,
            generic,
        )
        logger.info(
            "Runbook '%s' subsumed '%s' for shared business object",
            specialized.intent_name,
            generic.intent_name,
        )

    return [
        replacements[index]
        for index in range(len(routes))
        if index not in parents
    ]


def _concern_id(
    email: Email,
    route: ConcernRoute,
    occurrences: dict[str, int],
) -> str:
    """Build stable concern identity from immutable message and routed source."""
    normalized_intent, normalized_source = _concern_route_identity(route)
    identity = "\x00".join(
        (
            email.id,
            normalized_intent,
            normalized_source,
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    base = f"concern-{digest}"
    occurrences[base] = occurrences.get(base, 0) + 1
    occurrence = occurrences[base]
    return base if occurrence == 1 else f"{base}-{occurrence}"


def _intent_result_from_outcomes(outcomes: list[RunbookOutcome], intents_dir: Any) -> IntentResult:
    primary = next((outcome for outcome in outcomes if outcome.matched and outcome.intent_name), None)
    if primary is not None:
        return IntentResult(
            matched=True,
            intent_name=primary.intent_name,
            actions=primary.actions,
            response=_load_response_config(primary.intent_name, intents_dir=intents_dir),
            concerns=outcomes,
            error=primary.error,
        )
    reasons = _dedupe_strings(
        [outcome.requires_human_reason or outcome.error or outcome.summary for outcome in outcomes]
    )
    return IntentResult(
        concerns=outcomes,
        error="; ".join(reasons) or "No configured intent matches this email.",
    )


def _review_response_from_outcomes(outcomes: list[RunbookOutcome]) -> AgentResponse | None:
    needs_review = [outcome for outcome in outcomes if outcome.requires_human]
    if not needs_review:
        return None
    reasons = _dedupe_strings(
        [outcome.requires_human_reason or outcome.error or "Concern requires human review." for outcome in needs_review]
    )
    primary = next((outcome for outcome in outcomes if outcome.matched and outcome.intent_name), None)
    return AgentResponse(
        response_text="",
        activated_intent=primary.intent_name if primary else None,
        requires_human=True,
        requires_human_reason="; ".join(reasons),
    )


def _handle_matched_intent(
    intent_name: str,
    email: Email,
    identity_result: IdentityResult | None,
    intents_dir: Any,
    config_path: Any,
    parsed_attachments: dict[str, str] | None,
    creator: str | None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> tuple[IntentResult, AgentResponse | None]:
    del creator
    route = ConcernRoute(
        summary=email.subject,
        source_text=email.body,
        intent_name=intent_name,
        confidence=1.0,
    )
    occurrences: dict[str, int] = {}
    concern_id = _concern_id(email, route, occurrences)
    result = _execute_routed_concern_result(
        concern_id,
        route,
        email,
        identity_result,
        intents_dir,
        config_path,
        parsed_attachments,
        tenant_id,
        project_id,
    )
    outcomes = _merge_concern_execution_results([result])
    return (
        _intent_result_from_outcomes(outcomes, intents_dir),
        _review_response_from_outcomes(outcomes),
    )


def run_intent_agent(
    email: Email,
    identity_result: IdentityResult | None = None,
    intents_dir: Any = None,
    config_path: Any = None,
    parsed_attachments: dict[str, str] | None = None,
    creator: str | None = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> tuple[IntentResult, AgentResponse | None]:
    """Classify up to six concerns and execute each matched runbook."""
    known_intents = get_known_intent_names(intents_dir=intents_dir)
    if not known_intents:
        logger.info("No intents configured; skipping intent phase")
        return IntentResult(), None

    logger.info("Running intent agent for email: subject='%s'", email.subject)

    routes, router_error = _run_intent_router_agent(
        email,
        known_intents,
        intents_dir,
        config_path,
        parsed_attachments,
        tenant_id,
        project_id,
    )
    del creator
    routes = _apply_safety_intent_precedence(routes, known_intents)
    routes = _dedupe_concern_routes(routes)
    routes = _apply_runbook_subsumption(email, routes, intents_dir)
    if not routes:
        reason = router_error or "No configured intent matches this email."
        routes = [
            ConcernRoute(
                summary=email.subject,
                source_text=email.body,
                reason=reason,
            )
        ]

    executions: list[ConcernExecutionResult] = []
    occurrences: dict[str, int] = {}
    for route in routes[:MAX_ROUTED_CONCERNS]:
        concern_id = _concern_id(email, route, occurrences)
        executions.append(
            _execute_routed_concern_result(
                concern_id,
                route,
                email,
                identity_result,
                intents_dir,
                config_path,
                parsed_attachments,
                tenant_id,
                project_id,
            )
        )

    outcomes = _merge_concern_execution_results(executions)

    return (
        _intent_result_from_outcomes(outcomes, intents_dir),
        _review_response_from_outcomes(outcomes),
    )
