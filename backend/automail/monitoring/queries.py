"""Monitor run queries and aggregate stats."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from automail.db.pocketbase.client import _escape_pb, _list_all


def list_monitor_runs(
    *,
    tenant_id: str | None,
    project_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filter_str = f"project='{_escape_pb(project_id)}'"
    if tenant_id:
        filter_str += f" && tenant='{_escape_pb(tenant_id)}'"
    return _list_all("monitor_runs", filter_str, sort="-created", per_page=max(1, min(limit, 100)))


def monitor_summary(*, tenant_id: str | None, project_id: str) -> dict[str, Any]:
    records = list_monitor_runs(tenant_id=tenant_id, project_id=project_id, limit=200)
    now = datetime.now(timezone.utc)
    today = now.date()
    today_records = []
    durations = []
    failures = 0
    needs_human = 0
    actions_triggered = 0
    for rec in records:
        status = rec.get("status", "")
        if status == "failed":
            failures += 1
        if rec.get("duration_ms") is not None:
            durations.append(int(rec.get("duration_ms") or 0))
        output = rec.get("output") or {}
        if isinstance(output, dict) and output.get("requiresHuman"):
            needs_human += 1
        actions = rec.get("actions") or []
        if rec.get("source") == "action":
            actions_triggered += 1
        elif isinstance(actions, list):
            actions_triggered += sum(1 for a in actions if isinstance(a, dict) and a.get("status") == "success")
        try:
            started = datetime.fromisoformat((rec.get("started_at") or rec.get("created") or "").replace("Z", "+00:00"))
            if started.date() == today:
                today_records.append(rec)
        except Exception:
            pass

    durations_sorted = sorted(durations)
    avg_ms = round(sum(durations_sorted) / len(durations_sorted)) if durations_sorted else 0
    p95_ms = 0
    if durations_sorted:
        idx = max(0, min(len(durations_sorted) - 1, int(len(durations_sorted) * 0.95) - 1))
        p95_ms = durations_sorted[idx]

    return {
        "hasRuns": len(records) > 0,
        "totalRuns": len(records),
        "requestsToday": len(today_records),
        "failures": failures,
        "avgDurationMs": avg_ms,
        "p95DurationMs": p95_ms,
        "needsHuman": needs_human,
        "actionsTriggered": actions_triggered,
    }
