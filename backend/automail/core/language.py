"""User language preference helpers."""

from typing import Any

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = {"en", "de"}


def normalize_language(value: Any) -> str:
    """Return a supported language code, falling back to the product default."""
    language = str(value or "").strip().lower()
    if language in SUPPORTED_LANGUAGES:
        return language
    return DEFAULT_LANGUAGE


def validate_language(value: Any) -> str | None:
    """Return a supported language code, or None when the input is invalid."""
    language = str(value or "").strip().lower()
    return language if language in SUPPORTED_LANGUAGES else None
