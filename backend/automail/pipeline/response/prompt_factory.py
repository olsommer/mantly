import logging
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr as xml_quoteattr

from automail.core.config import read_config
from automail.models import Email, IdentityResult, IntentResult

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _safe_format(template: str, **kwargs: Any) -> str:
    """Format a template, escaping braces in values to prevent injection.

    User-supplied content (email bodies, attachments, etc.) may contain literal
    { or } characters.  Python's str.format() would interpret those as field
    references and raise KeyError.  This helper escapes braces in every value
    before calling .format(), so literal braces survive round-tripping.
    """
    escaped = {k: str(v).replace("{", "{{").replace("}", "}}") for k, v in kwargs.items()}
    return template.format(**escaped)


def _xml_text(value: Any) -> str:
    return xml_escape(str(value))


def _xml_attr(value: Any) -> str:
    return xml_quoteattr(str(value))


def create_response_system_prompt(
    intent_name: str | None = None,
    tenant_id: str | None = None,
    config_path: Any = None,
    intents_dir: Any = None,
) -> str:
    """Create the response-generation system prompt.

    Args:
        intent_name: Kept for API symmetry with the response user prompt.
        tenant_id: Optional tenant ID for scoping DB-stored intents.
        config_path: Optional path to admin config file.
        intents_dir: Kept for API symmetry with the response user prompt.
    """
    system_prompt = (_PROMPTS_DIR / "response_system_prompt.md").read_text(encoding="utf-8").strip()
    config = read_config(config_path=config_path)
    project_id = getattr(config_path, "project_id", None)
    if tenant_id or project_id:
        from automail.llm import resolve_effective_config
        config = resolve_effective_config(config, tenant_id, project_id)

    return _safe_format(
        system_prompt,
        company_name=config.org_name,
    )


def create_response_user_prompt(
    email: Email,
    parsed_attachments: dict[str, str] | None = None,
    creator: str | None = None,
    identity_result: IdentityResult | None = None,
    intent_result: IntentResult | None = None,
    tenant_id: str | None = None,
    intents_dir: Any = None,
    intent_learnings: list[str] | None = None,
    available_response_attachments: list[dict[str, Any]] | None = None,
    company_name: str = "",
    company_description: str = "",
) -> str:
    """
    Create a formatted user prompt from an email.

    Args:
        email: Email model containing email information
        parsed_attachments: Optional dict mapping filename to extracted text content
        creator: Optional email address of the responder (used for personalized sign-off)
        identity_result: Optional IdentityResult from Phase 1 (customer lookup)
        intent_result: Optional IntentResult from Phase 2 (intent classification)
        intent_learnings: Optional list of AI-generated learning rules derived from
            user feedback.
        available_response_attachments: Files available for response_attachments.

    Returns:
        Formatted prompt string for the agent
    """
    # Format attachments
    attachments_text = ""
    if parsed_attachments:
        for filename, content in parsed_attachments.items():
            attachments_text += f"### {filename}\n\n"
            max_chars = 10000
            if len(content) > max_chars:
                attachments_text += content[:max_chars] + f"\n\n[... truncated, {len(content) - max_chars} characters omitted ...]"
            else:
                attachments_text += content
            attachments_text += "\n\n"
    else:
        attachments_text = "None"

    # Format email using template
    email_template = (_PROMPTS_DIR / "email_template.md").read_text(encoding="utf-8").strip()
    formatted_email = _safe_format(
        email_template,
        from_addr=email.from_address,
        to_addr=getattr(email, 'to_address', ''),
        date=getattr(email, 'date', ''),
        subject=email.subject,
        email_body=email.body,
        attachments=attachments_text,
    )

    # Resolve creator name
    creator_name = ""
    creator_email = ""
    if creator:
        from automail.api.users_env import resolve_creator_name
        creator_name = resolve_creator_name(creator, tenant_id=tenant_id)
        creator_email = creator

    learnings_text = "<learnings>\n  <none />\n</learnings>"
    if intent_learnings:
        logger.info(
            "Injecting %d AI-generated learnings into user prompt",
            len(intent_learnings),
        )
        learnings_text = "<learnings>\n"
        for learning in intent_learnings:
            learnings_text += f"  <learning>{_xml_text(learning)}</learning>\n"
        learnings_text += "</learnings>"

    # Build responder/company section
    on_behalf_of_text = "<on_behalf_of>\n"
    if creator_name:
        on_behalf_of_text += f"  <responder_name>{_xml_text(creator_name)}</responder_name>\n"
    if creator_email:
        on_behalf_of_text += f"  <responder_email>{_xml_text(creator_email)}</responder_email>\n"
    if company_name:
        on_behalf_of_text += f"  <company_name>{_xml_text(company_name)}</company_name>\n"
    if company_description:
        on_behalf_of_text += f"  <company_description>{_xml_text(company_description)}</company_description>\n"
    if not creator_name and not creator_email and not company_name and not company_description:
        on_behalf_of_text += "  <none />\n"
    on_behalf_of_text += "</on_behalf_of>"

    # Build identity context section
    identity_text = ""
    if identity_result and identity_result.customer_found:
        identity_text = '<customer_identity status="found">\n'
        for key, value in identity_result.data.items():
            identity_text += f"  <field name={_xml_attr(key)}>{_xml_text(value)}</field>\n"
        identity_text += "</customer_identity>"
    elif identity_result:
        identity_text = '<customer_identity status="not_found" />'

    # Build concern/runbook context. New runs carry one structured outcome per
    # concern; the singular branch remains for cached and legacy callers.
    intent_text = ""
    concerns = list(getattr(intent_result, "concerns", None) or []) if intent_result else []
    if concerns:
        intent_text = f'<intent_context status="multi" concern_count="{len(concerns)}">\n'
        for index, concern in enumerate(concerns[:10], start=1):
            concern_id = str(getattr(concern, "concern_id", "") or f"concern-{index}")
            intent_name = str(getattr(concern, "intent_name", "") or "")
            intent_text += (
                f"  <concern id={_xml_attr(concern_id)} matched={_xml_attr(bool(getattr(concern, 'matched', False)))}"
                f" status={_xml_attr(getattr(concern, 'status', ''))}"
                f" requires_human={_xml_attr(bool(getattr(concern, 'requires_human', False)))}>\n"
            )
            intent_text += f"    <summary>{_xml_text(getattr(concern, 'concern_summary', ''))}</summary>\n"
            intent_text += f"    <source_text>{_xml_text(getattr(concern, 'source_text', ''))}</source_text>\n"
            intent_text += f"    <runbook>{_xml_text(intent_name)}</runbook>\n"
            intent_text += f"    <confidence>{_xml_text(getattr(concern, 'confidence', 0))}</confidence>\n"
            reason = getattr(concern, "requires_human_reason", None) or getattr(concern, "error", None)
            if reason:
                intent_text += f"    <reason>{_xml_text(reason)}</reason>\n"
            for fact in list(getattr(concern, "verified_facts", None) or [])[:24]:
                intent_text += (
                    f"    <verified_fact path={_xml_attr(getattr(fact, 'path', ''))}"
                    f" source={_xml_attr(getattr(fact, 'source', 'runbook'))}>"
                    f"{_xml_text(getattr(fact, 'value', ''))}</verified_fact>\n"
                )
            for tool_result in list(getattr(concern, "tool_evidence", None) or [])[:10]:
                tool_name = getattr(tool_result, "tool_name", "")
                tool_status = getattr(tool_result, "status", "")
                intent_text += (
                    f"    <tool_result name={_xml_attr(tool_name)} status={_xml_attr(tool_status)}>\n"
                )
                for fact in list(getattr(tool_result, "facts", None) or [])[:24]:
                    intent_text += (
                        f"      <fact path={_xml_attr(getattr(fact, 'path', ''))}>"
                        f"{_xml_text(getattr(fact, 'value', ''))}</fact>\n"
                    )
                intent_text += "    </tool_result>\n"
            for action in list(getattr(concern, "action_outcomes", None) or [])[:20]:
                intent_text += (
                    f"    <action name={_xml_attr(getattr(action, 'name', ''))}"
                    f" status={_xml_attr(getattr(action, 'status', ''))}>"
                    f"{_xml_text(getattr(action, 'detail', ''))}</action>\n"
                )
            for missing in list(getattr(concern, "missing_information", None) or [])[:10]:
                intent_text += f"    <missing_information>{_xml_text(missing)}</missing_information>\n"
            intent_text += "  </concern>\n"
        intent_text += "</intent_context>"
    elif intent_result and intent_result.matched:
        description = ""
        if intent_result.intent_name:
            from automail.pipeline.intent.intents_factory import get_intent_description
            description = get_intent_description(intent_result.intent_name, intents_dir=intents_dir)
        intent_text = '<intent_context status="matched">\n'
        intent_text += f"  <title>{_xml_text(intent_result.intent_name or '')}</title>\n"
        intent_text += f"  <description>{_xml_text(description)}</description>\n"
        intent_text += "</intent_context>"

    rules_text = "<rules>\n"
    if concerns:
        intent_rules = []
        seen_rules: set[str] = set()
        for concern in concerns:
            intent_name = str(getattr(concern, "intent_name", "") or "")
            configured_rules = []
            if intent_name:
                from automail.pipeline.intent.intents_factory import get_intent_response_rules
                configured_rules = get_intent_response_rules(intent_name, intents_dir=intents_dir)
            contributed_rules = [
                *configured_rules,
                *list(getattr(concern, "reply_requirements", None) or []),
                *[
                    f"Forbidden claim: {claim}"
                    for claim in list(getattr(concern, "forbidden_claims", None) or [])
                ],
            ]
            for rule in contributed_rules:
                clean_rule = str(rule).strip()
                if clean_rule and clean_rule not in seen_rules:
                    seen_rules.add(clean_rule)
                    intent_rules.append(clean_rule)
    elif intent_result and intent_result.matched and intent_result.intent_name:
        from automail.pipeline.intent.intents_factory import get_intent_response_rules
        intent_rules = get_intent_response_rules(intent_result.intent_name, intents_dir=intents_dir)
    else:
        intent_rules = []
    if intent_rules:
        for rule in intent_rules:
            rules_text += f"  <rule>{_xml_text(rule)}</rule>\n"

    # Build available response attachment section
    if available_response_attachments is None and intent_result:
        from automail.pipeline.intent.intents_factory import get_intent_response_attachments
        available_response_attachments = []
        seen_filenames: set[str] = set()
        attachment_intents = [
            str(getattr(concern, "intent_name", "") or "")
            for concern in concerns
            if getattr(concern, "matched", False)
        ] or ([intent_result.intent_name] if intent_result.matched and intent_result.intent_name else [])
        for intent_name in attachment_intents:
            for attachment in get_intent_response_attachments(intent_name, intents_dir=intents_dir):
                filename = str(attachment.get("filename") or "").strip()
                if filename and filename not in seen_filenames:
                    seen_filenames.add(filename)
                    available_response_attachments.append(attachment)
        for concern in concerns:
            for attachment in list(getattr(concern, "attachments", None) or []):
                filename = str(getattr(attachment, "filename", "") or "").strip()
                if not filename or filename in seen_filenames:
                    continue
                seen_filenames.add(filename)
                available_response_attachments.append(
                    {
                        "filename": filename,
                        "description": str(getattr(attachment, "description", "") or ""),
                        "mode": str(getattr(attachment, "mode", "dynamic") or "dynamic"),
                    }
                )

    available_attachments_text = "<available_attachments>\n"
    if available_response_attachments:
        for attachment in available_response_attachments:
            filename = str(attachment.get("filename") or "").strip()
            if not filename:
                continue
            mode = str(attachment.get("mode") or "").strip()
            description = str(attachment.get("description") or "").strip()
            available_attachments_text += f"  <attachment filename={_xml_attr(filename)}"
            if mode:
                available_attachments_text += f" mode={_xml_attr(mode)}"
            if description:
                available_attachments_text += f">{_xml_text(description)}</attachment>\n"
            else:
                available_attachments_text += " />\n"
    else:
        available_attachments_text += "  <none />\n"
    available_attachments_text += "</available_attachments>"

    rules_text += (
        "  <rule>Only use exact filenames listed in <available_attachments> when setting response_attachments.</rule>\n"
        "  <rule>If no available attachment matches the email, leave response_attachments empty unless a tool returned a generated file.</rule>\n"
        "</rules>"
    )

    # Format user prompt (single call — all placeholders at once)
    user_prompt = (_PROMPTS_DIR / "response_user_prompt.md").read_text(encoding="utf-8").strip()
    return _safe_format(
        user_prompt,
        email=formatted_email,
        on_behalf_of=on_behalf_of_text,
        identity_context=identity_text,
        intent_context=intent_text,
        available_attachments=available_attachments_text,
        rules=rules_text,
        learnings=learnings_text,
    )
