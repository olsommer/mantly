"""Aggregate public email/add-in API router."""

from fastapi import APIRouter

from automail.api import chat, feedback, process

router = APIRouter()

for child_router in (
    process.router,
    chat.router,
    feedback.router,
):
    router.include_router(child_router)
