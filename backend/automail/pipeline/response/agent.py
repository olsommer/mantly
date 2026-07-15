import logging
from typing import Any

from automail.models import AgentResponse
from automail.pipeline.intent.intents_factory import get_known_intent_names

logger = logging.getLogger(__name__)


def _get_valid_attachment_filenames(intents_dir: Any = None) -> set[str]:
    """Return filenames available from PocketBase intent attachments."""
    valid: set[str] = set()
    project_id = getattr(intents_dir, "project_id", None)
    if project_id:
        from automail.db.pocketbase.client import _list_all
        try:
            for rec in _list_all("intent_attachments", f"project='{project_id}'", per_page=200):
                if rec.get("filename"):
                    valid.add(str(rec["filename"]))
        except Exception:
            logger.warning("Failed to load PocketBase intent attachment filenames", exc_info=True)
    return valid


def _validate_response(
    response: AgentResponse,
    known_intents: set[str] | None = None,
    intents_dir: Any = None,
    extra_valid_attachment_filenames: set[str] | None = None,
) -> AgentResponse:
    """Validate and fix agent output before returning to the caller.

    Rules:
    1. response_text must be non-empty
    2. requires_human=False without runtime intent → override to requires_human=True
    3. activated_intent not in known intents → clear it, set requires_human=True
    4. response_attachments with invalid filenames → remove them
    5. activated_intent set AND requires_human=True → override to requires_human=False
    """
    if known_intents is None:
        known_intents = get_known_intent_names(intents_dir=intents_dir)

    # Rule 1: non-empty response
    if not response.response_text or not response.response_text.strip():
        raise ValueError("Agent returned empty response_text")

    # Rule 2: no intent but claims handled
    if not response.requires_human and not response.activated_intent:
        logger.warning("Runtime response has requires_human=False without activated_intent — overriding to requires_human=True")
        response.requires_human = True
        response.requires_human_reason = "No matching intent was activated."

    # Rule 3: unknown intent name
    if response.activated_intent:
        if response.activated_intent.lower() not in known_intents:
            logger.warning(
                "Runtime response has unknown intent '%s' (known: %s) — clearing, setting requires_human=True",
                response.activated_intent, known_intents,
            )
            unknown_name = response.activated_intent
            response.activated_intent = None
            response.requires_human = True
            response.requires_human_reason = f"Unknown intent: '{unknown_name}'."

    # Rule 5: intent activated but still flagged for human review — override to False.
    if response.activated_intent and response.requires_human:
        if response.activated_intent.lower() in known_intents:
            logger.warning(
                "Runtime response has intent '%s' but requires_human=True — overriding to False",
                response.activated_intent,
            )
            response.requires_human = False
            response.requires_human_reason = None

    # Rule 4: validate attachment filenames
    if response.response_attachments:
        valid_files = _get_valid_attachment_filenames(intents_dir=intents_dir) | (extra_valid_attachment_filenames or set())
        cleaned = []
        for fname in response.response_attachments:
            if fname in valid_files:
                cleaned.append(fname)
            else:
                logger.warning("Removing hallucinated attachment filename: '%s'", fname)
        response.response_attachments = cleaned if cleaned else None

    return response
