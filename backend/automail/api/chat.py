"""Email chat, analytics, users, and health endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from automail.api.users_env import parse_users
from automail.core.auth import get_current_tenant
from automail.db.pocketbase.client import (
    add_user,
    get_analytics,
    get_chat,
    get_chats,
    mark_chat_reviewed,
    update_chat,
)
from automail.models import AddUserRequest, ChatRequest, ChatResponse, Message

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/chat", response_model=Message | None)
async def chat_email(request: ChatRequest, req: Request) -> Message | None:
    """Chat endpoint to interact with the AI or mention a reviewer"""
    tenant_id: Optional[str] = get_current_tenant(req)

    # Extract chat_id
    chat_id = request.chat_id

    # Convert messages to dict for JSON serialization
    messages_dict = [
        msg.model_dump()
        for msg in request.messages
    ]

    # Store in database
    try:
        record_id = update_chat(
            chat_id=chat_id,
            messages_dict=messages_dict,
            tenant_id=tenant_id,
        )
        logger.info("Stored chat with ID: %s for chat: %s", record_id, chat_id)
    except Exception:
        logger.exception("Error storing chat")
        raise HTTPException(status_code=500, detail="Internal error")

@router.get("/chat/{chat_id:path}", response_model=ChatResponse | None)
async def get_chat_endpoint(
    chat_id: str,
    req: Request,
    project_id: str | None = Query(default=None, alias="projectId"),
) -> dict | None:
    """Get chat details by chat-id"""
    tenant_id: Optional[str] = get_current_tenant(req)
    chat = get_chat(chat_id=chat_id, tenant_id=tenant_id, project_id=project_id)
    if chat:
        return chat
    return None

@router.get("/chats", response_model=list[dict] | None)
async def get_user_chats(user: str, req: Request) -> list[dict] | None:
    """Get all chat IDs where the user is a member"""
    tenant_id: Optional[str] = get_current_tenant(req)
    return get_chats(user=user, tenant_id=tenant_id)

@router.post("/user")
async def add_user_to_chat(request: AddUserRequest, req: Request):
    """Add a user to a chat (mark with supervisors)."""
    tenant_id: Optional[str] = get_current_tenant(req)
    chat_id = request.chat_id
    user_email = request.email

    try:
        add_user(
            chat_id=chat_id,
            user_email=user_email,
            tenant_id=tenant_id,
        )
        logger.info("Added user %s to chat for chat: %s", user_email, chat_id)
    except Exception:
        logger.exception("Error updating email")
        raise HTTPException(status_code=500, detail="Internal error")

    return {"status": "success"}

@router.get("/users")
async def get_users(req: Request):
    """Get the list of users from environment variable."""
    _tenant_id: Optional[str] = get_current_tenant(req)
    return {"users": parse_users()}

@router.get("/analytics")
async def analytics_endpoint(req: Request) -> dict:
    """Return aggregate usage stats for the current tenant."""
    tenant_id: Optional[str] = get_current_tenant(req)
    return get_analytics(tenant_id=tenant_id)


@router.get("/health")
async def health_check():
    """Health check endpoint. Returns status of service dependencies."""
    import httpx as _httpx

    from automail.db.pocketbase.client import PB_URL

    pb_ok = False
    pb_error = None
    try:
        with _httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{PB_URL}/api/health")
            resp.raise_for_status()
            pb_ok = True
    except Exception as exc:
        pb_error = str(exc)

    overall = "healthy" if pb_ok else "degraded"
    result: dict = {
        "status": overall,
        "service": "mantly",
        "dependencies": {
            "pocketbase": {"status": "ok" if pb_ok else "error", "error": pb_error},
        },
    }

    # Include license status when running in on-prem licensed mode
    from automail.billing.license import get_license_status, is_license_required
    if is_license_required():
        lic = get_license_status()
        result["license"] = lic
        if not lic["valid"] and not lic["withinGracePeriod"]:
            result["status"] = "degraded"

    return result

@router.patch("/chat/{chat_id:path}/reviewed")
async def mark_chat_reviewed_endpoint(chat_id: str, req: Request):
    """Mark a chat as reviewed, removing it from the human-attention queue."""
    tenant_id: Optional[str] = get_current_tenant(req)
    found = mark_chat_reviewed(chat_id, tenant_id=tenant_id)
    if not found:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"status": "reviewed"}
