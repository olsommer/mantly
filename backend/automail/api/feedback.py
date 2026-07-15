"""Email feedback endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from automail.core.auth import require_authenticated, resolve_project_context
from automail.db.pocketbase.client import (
    get_chat,
    store_feedback,
)
from automail.models import FeedbackRequest, FeedbackResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _selected_feedback_stage(affected_stages: list[str] | None) -> str:
    stages: list[str] = []
    for stage in affected_stages or []:
        value = str(stage).strip()
        if value and value not in stages:
            stages.append(value)

    if len(stages) > 1:
        raise HTTPException(status_code=422, detail="Feedback must refer to exactly one affected stage")
    return stages[0] if stages else ""


def submit_feedback_for_context(
    request: FeedbackRequest,
    *,
    tenant_id: Optional[str],
    project_id: str,
    user_email: str = "",
) -> FeedbackResponse:
    """Submit structured like/dislike feedback on a pipeline result."""
    if request.rating not in ("like", "dislike"):
        raise HTTPException(status_code=422, detail="rating must be 'like' or 'dislike'")

    # Verify the chat exists
    chat = get_chat(
        request.chat_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    affected_stage = _selected_feedback_stage(request.affected_stages)
    if request.rating == "dislike" and not affected_stage:
        raise HTTPException(status_code=422, detail="Feedback must include one affected stage")
    affected_stages = [affected_stage] if affected_stage else []

    record_id = store_feedback(
        chat_id=request.chat_id,
        user_email=user_email.strip() or request.user,
        rating=request.rating,
        affected_stages=affected_stages,
        feedback_text=request.feedback_text,
        tenant_id=tenant_id,
        project_id=project_id,
    )

    logger.info("Stored feedback: id=%s rating=%s chat=%s", record_id, request.rating, request.chat_id)

    # Feedback is evidence only. An explicit proposal -> eval -> publish flow must
    # own reflection before any new rule can affect live runbook prompts.

    return FeedbackResponse(status="ok", id=record_id)


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest, req: Request) -> FeedbackResponse:
    project_id = request.project_id.strip()
    if not project_id:
        raise HTTPException(status_code=422, detail="projectId is required")
    auth = require_authenticated(req)
    context = resolve_project_context(req, project_id, min_role="editor")
    return submit_feedback_for_context(
        request,
        tenant_id=context.tenant_id or auth.tenant_id or None,
        project_id=context.project_id,
        user_email=auth.email,
    )
