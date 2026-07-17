"""Admin draft preview endpoint."""

from fastapi import APIRouter, Request

from automail.api.admin.deps import ProjectEditorDep
from automail.core.auth import get_token_payload
from automail.core.rate_limit import limiter
from automail.monitoring import (
    RunRecorder,
    actions_from_intent,
    email_input_summary,
    pipeline_output_summary,
)
from automail.pipeline.drafts import ensure_draft_exists, get_draft_source
from automail.pipeline.intent.consumers import resolve_intent_action_payloads

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────
# Preview (process email against draft) — project-scoped
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/projects/{pid}/preview")
@limiter.limit("30/minute")
async def preview_email(request: Request, ctx: ProjectEditorDep) -> list:
    """Process an email against DRAFT config/intents for a project.  No DB storage."""
    from automail.api.attachments import load_attachment_files, parse_email_attachments
    from automail.models import EmailResponse, Message, ProcessEmailRequest, TokenUsage
    from automail.pipeline import run_pipeline

    draft = get_draft_source(ctx.project_id, tenant_id=ctx.tenant_id)
    ensure_draft_exists(ctx.project_id, tenant_id=ctx.tenant_id)

    body_raw = await request.json()
    body = ProcessEmailRequest(**body_raw)
    email = body.email
    payload = get_token_payload(request)
    creator = payload.email if payload and payload.email else body.creator
    preview_chat_id = f"preview:{ctx.project_id}:{email.id}"
    input_summary = email_input_summary(email)
    input_summary["emailId"] = preview_chat_id
    input_summary["originalEmailId"] = email.id
    recorder = RunRecorder(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        source="preview",
        user_email=creator,
        input_data=input_summary,
    )

    try:
        parsed_attachments = parse_email_attachments(email)
        pipeline_result = run_pipeline(
            email,
            parsed_attachments,
            creator=creator,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            config_source=draft,
        )
    except Exception as exc:
        recorder.finish(status="failed", error=str(exc))
        raise

    result = pipeline_result.agent_response
    identity_result = pipeline_result.identity_result
    intent_result = pipeline_result.intent_result
    phishing_result = pipeline_result.phishing_result
    prompt_injection_result = pipeline_result.prompt_injection_result
    token_usage = pipeline_result.token_usage

    # Resolve action payloads with identity data
    if intent_result and identity_result and identity_result.data:
        resolve_intent_action_payloads(intent_result, identity_result.data)

    attachments = load_attachment_files(
        result,
        intents_dir=draft,
        intent_result=intent_result,
        strict_intent_ownership=True,
    )
    attachment_list = attachments if attachments else []

    email_message = Message(
        user="email",
        role="email",
        content=f"Subject: {email.subject}\nFrom: {email.from_address}\n\n{email.body}",
    )

    ai_message = Message(
        user="response",
        role="response",
        content=EmailResponse(
            email_body=result.response_text,
            email_attachments=attachment_list,
            requires_human=result.requires_human,
            requires_human_reason=result.requires_human_reason,
            identity_result=identity_result,
            intent_result=intent_result,
            phishing_result=phishing_result,
            prompt_injection_result=prompt_injection_result,
            token_usage=TokenUsage.model_validate(token_usage) if token_usage else None,
            activated_intent=result.activated_intent,
        ),
    )
    messages_to_store = [
        email_message.model_dump(),
        ai_message.model_dump(),
    ]
    from automail.db.pocketbase.client import upsert_email_analysis
    upsert_email_analysis(
        preview_chat_id,
        creator,
        messages_to_store,
        subject=email.subject,
        from_address=email.from_address,
        activated_intent=result.activated_intent,
        requires_human=result.requires_human,
        tenant_id=ctx.tenant_id,
        identity_result=identity_result.model_dump() if identity_result else None,
        intent_result=intent_result.model_dump() if intent_result else None,
        phishing_result=phishing_result.model_dump() if phishing_result else None,
        prompt_injection_result=prompt_injection_result.model_dump() if prompt_injection_result else None,
        token_usage=token_usage,
        project_id=ctx.project_id,
        status="preview",
    )

    recorder.finish(
        status="needs_human" if result.requires_human else "success",
        output=pipeline_output_summary(pipeline_result),
        actions=actions_from_intent(intent_result),
    )

    return [
        email_message.model_dump(by_alias=True),
        ai_message.model_dump(by_alias=True),
    ]
