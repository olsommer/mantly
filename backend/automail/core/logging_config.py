"""Centralized logging configuration for the Mantly backend."""

import logging
import os
import sys


def setup_logging(level: int | None = None) -> None:
    """Configure structured logging with timestamps for the entire application.

    The effective log level is resolved in this order:
    1. The ``level`` argument (if given)
    2. The ``LOG_LEVEL`` environment variable (DEBUG/INFO/WARNING/ERROR)
    3. INFO (default)

    Call once at startup (after dotenv is loaded) so every module that uses
    ``logging.getLogger(__name__)`` inherits this format automatically.
    """
    if level is None:
        env_level = os.getenv("LOG_LEVEL", "INFO").upper()
        resolved_level = getattr(logging, env_level, logging.INFO)
        level = resolved_level if isinstance(resolved_level, int) else logging.INFO

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers on repeated calls (e.g. tests, reload)
    if not root.handlers:
        root.addHandler(handler)
