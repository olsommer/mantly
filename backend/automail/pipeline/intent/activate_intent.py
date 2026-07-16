"""Router tools for selecting an intent."""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langchain.tools import tool

from automail.pipeline.intent.intents_factory import get_intent_body

logger = logging.getLogger(__name__)

_intents_dir_override: ContextVar[Any | None] = ContextVar(
    "intent_router_intents_dir",
    default=None,
)


@contextmanager
def use_intents_dir(intents_dir: Any | None) -> Generator[None]:
    """Scope the router's intent source to the current invocation context."""
    token = _intents_dir_override.set(intents_dir)
    try:
        yield
    finally:
        _intents_dir_override.reset(token)


@tool(return_direct=True)
def activate_intent(intent_name: str) -> str:
    """Activate one configured intent by exact name when it matches the email."""
    body = get_intent_body(intent_name, intents_dir=_intents_dir_override.get())
    if body is not None:
        logger.info("Activated intent: %s", intent_name)
        return body

    logger.warning("Intent not found: '%s'", intent_name)
    return f"Error: Intent '{intent_name}' not found."


@tool(return_direct=True)
def no_match(reason: str = "") -> str:
    """Signal that no configured intent matches the incoming email."""
    return reason or "No configured intent matches this email."
