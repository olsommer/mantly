"""Small fire-and-forget worker for non-critical persistence."""
from __future__ import annotations

import logging
import os
import queue
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_jobs: queue.Queue[tuple[str, Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = queue.Queue()
_started = False
_lock = threading.Lock()


def _worker() -> None:
    while True:
        name, fn, args, kwargs = _jobs.get()
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.warning("Background job failed: %s", name, exc_info=True)
        finally:
            _jobs.task_done()


def enqueue_io(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Queue non-critical IO without blocking the request path."""
    global _started
    mode = os.getenv("AUTOMAIL_BACKGROUND_IO", "async").strip().lower()
    if mode in {"off", "disabled", "false", "0"}:
        logger.debug("Background job skipped: %s", name)
        return
    if mode in {"sync", "inline"}:
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.warning("Background job failed: %s", name, exc_info=True)
        return

    with _lock:
        if not _started:
            threading.Thread(target=_worker, name="automail-bg-io", daemon=True).start()
            _started = True
    _jobs.put((name, fn, args, kwargs))
