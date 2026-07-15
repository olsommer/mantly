"""Admin API router aggregator."""

from fastapi import APIRouter

from automail.api.admin import (
    accounts,
    actions,
    automations,
    channels,
    config,
    intents,
    issues,
    knowledge,
    learning_proposals,
    manifest,
    monitor,
    preview,
    projects,
    settings,
    support_analytics,
    support_delivery,
    support_settings,
    users,
)

router = APIRouter(prefix="/api/admin")

for child_router in (
    config.router,
    intents.router,
    users.router,
    settings.router,
    projects.router,
    issues.router,
    accounts.router,
    automations.router,
    channels.router,
    knowledge.router,
    learning_proposals.router,
    support_analytics.router,
    support_delivery.router,
    support_settings.router,
    monitor.router,
    preview.router,
    actions.router,
    manifest.router,
):
    router.include_router(child_router)
