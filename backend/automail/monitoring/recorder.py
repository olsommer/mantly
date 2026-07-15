"""Monitor run recording."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from automail.core.background import enqueue_io
from automail.db.pocketbase.client import _patch, _post, generate_id
from automail.monitoring.sanitize import ERROR_LIMIT, clip, safe_dict


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunRecorder:
    def __init__(
        self,
        *,
        tenant_id: str | None,
        project_id: str | None,
        source: str,
        user_email: str = "",
        input_data: dict[str, Any] | None = None,
    ) -> None:
        self.started = time.monotonic()
        self.record_id: str | None = None
        data: dict[str, Any] = {
            "id": generate_id(),
            "source": source,
            "status": "running",
            "started_at": now_iso(),
            "user_email": clip(user_email, 300),
            "input": safe_dict(input_data or {}),
            "output": {},
            "actions": [],
            "error": "",
        }
        if tenant_id:
            data["tenant"] = tenant_id
        if project_id:
            data["project"] = project_id
        self.record_id = data["id"]
        enqueue_io(
            "monitor_runs.create",
            _post,
            "/api/collections/monitor_runs/records",
            data,
        )

    def finish(
        self,
        *,
        status: str,
        output: dict[str, Any] | None = None,
        actions: list[dict[str, Any]] | None = None,
        error: str = "",
    ) -> None:
        if not self.record_id:
            return
        duration_ms = int((time.monotonic() - self.started) * 1000)
        data = {
            "status": status,
            "completed_at": now_iso(),
            "duration_ms": duration_ms,
            "output": safe_dict(output or {}),
            "actions": actions or [],
            "error": clip(error, ERROR_LIMIT),
        }
        enqueue_io(
            "monitor_runs.finish",
            _patch,
            f"/api/collections/monitor_runs/records/{self.record_id}",
            data,
        )


def record_action_run(
    *,
    tenant_id: str | None,
    project_id: str | None,
    user_email: str,
    webhook: str,
    method: str,
    payload: dict[str, Any],
    response: Any = None,
    error: str = "",
    duration_ms: int = 0,
) -> None:
    parsed = urlparse(webhook)
    status = "failed" if error else "success"
    data: dict[str, Any] = {
        "id": generate_id(),
        "source": "action",
        "status": status,
        "started_at": now_iso(),
        "completed_at": now_iso(),
        "duration_ms": duration_ms,
        "user_email": clip(user_email, 300),
        "input": {
            "method": method.upper(),
            "host": parsed.hostname or "",
            "path": parsed.path,
            "payload": safe_dict(payload),
        },
        "output": {"response": clip(response)},
        "actions": [{
            "type": "webhook",
            "label": clip(str(payload.get("actionLabel") or payload.get("actionName") or parsed.hostname or webhook), 300),
            "method": method.upper(),
            "status": status,
        }],
        "error": clip(error, ERROR_LIMIT),
    }
    if tenant_id:
        data["tenant"] = tenant_id
    if project_id:
        data["project"] = project_id
    enqueue_io(
        "monitor_runs.action",
        _post,
        "/api/collections/monitor_runs/records",
        data,
    )
