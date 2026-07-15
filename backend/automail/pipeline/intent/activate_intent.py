"""Router tools for selecting an intent."""

import logging
from typing import Any

from langchain.tools import tool

from automail.pipeline.intent.intents_factory import get_intent_body

logger = logging.getLogger(__name__)

_intents_dir_override: Any | None = None


def set_intents_dir(intents_dir: Any | None) -> None:
    """Set the intent source used by router tools during one invocation."""
    global _intents_dir_override
    _intents_dir_override = intents_dir


@tool
def activate_intent(intent_name: str) -> str:
    """Activate one configured intent by exact name when it matches the email."""
    body = get_intent_body(intent_name, intents_dir=_intents_dir_override)
    if body is not None:
        logger.info("Activated intent: %s", intent_name)
        return body

    logger.warning("Intent not found: '%s'", intent_name)
    return f"Error: Intent '{intent_name}' not found."


@tool
def no_match(reason: str = "") -> str:
    """Signal that no configured intent matches the incoming email."""
    return reason or "No configured intent matches this email."
