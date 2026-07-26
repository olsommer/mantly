"""Run multi-concern runbooks for one direct-channel customer message."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from automail.integrations.http_tool import (
    begin_generated_attachment_collection,
    begin_tool_call_collection,
    collect_generated_attachments,
    collect_tool_calls,
)
from automail.llm.usage import collect_llm_usage
from automail.models import Email, IdentityResult
from automail.pipeline.intent.agent import run_intent_agent
from automail.pipeline.intent.consumers import resolve_intent_action_payloads


@dataclass(frozen=True)
class DirectChannelRunbookResult:
    """Persistable output from runbook processing without reply composition."""

    identity_result: dict[str, Any]
    intent_result: dict[str, Any]
    token_usage: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    generated_attachments: list[dict[str, Any]]
    activated_intent: str
    summary: str
    requires_human: bool


def run_direct_channel_runbooks(
    *,
    source_message_id: str,
    subject: str,
    body: str,
    from_address: str,
    identity: dict[str, str],
    identity_data: dict[str, Any],
    config_source: Any,
    tenant_id: str | None,
    project_id: str,
) -> DirectChannelRunbookResult:
    """Route one channel message, execute every concern, and compose no reply."""
    email = Email(
        id=source_message_id,
        subject=subject,
        from_address=from_address,
        body=body,
        attachments=[],
    )
    resolved_identity = IdentityResult(
        customer_found=bool(identity.get("contact_email")),
        data={
            "accountName": identity.get("account_name", ""),
            "accountDomain": identity.get("account_domain", ""),
            "contactEmail": identity.get("contact_email", ""),
            "contactName": identity.get("contact_name", ""),
            **identity_data,
        },
    )
    generated_token = begin_generated_attachment_collection()
    tool_token = begin_tool_call_collection()
    with collect_llm_usage() as usage:
        try:
            intent_result, review = run_intent_agent(
                email=email,
                identity_result=resolved_identity,
                intents_dir=config_source,
                config_path=config_source,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            resolve_intent_action_payloads(intent_result, resolved_identity.data)
        finally:
            generated_attachments = collect_generated_attachments(generated_token)
            tool_calls = collect_tool_calls(tool_token)

    concerns = intent_result.concerns
    requires_human = (
        not intent_result.matched
        or any(concern.requires_human or not concern.matched for concern in concerns)
        or bool(review and review.requires_human)
    )
    summaries = [concern.summary.strip() for concern in concerns if concern.summary.strip()]
    return DirectChannelRunbookResult(
        identity_result=resolved_identity.model_dump(by_alias=True),
        intent_result=intent_result.model_dump(by_alias=True),
        token_usage=usage.aggregate(),
        tool_calls=tool_calls,
        generated_attachments=generated_attachments,
        activated_intent=intent_result.intent_name or "",
        summary="; ".join(dict.fromkeys(summaries)),
        requires_human=requires_human,
    )
