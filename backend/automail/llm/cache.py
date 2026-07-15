"""LLM singleton cache invalidation."""

import logging

logger = logging.getLogger(__name__)


def invalidate_all() -> None:
    """Clear every cached LLM singleton across agent modules."""
    logger.info("LLM cache invalidation requested; no module-level LLM singletons are active")
