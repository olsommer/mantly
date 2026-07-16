"""Scheduled support channel sync runner with observable heartbeats."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from automail.core.observability import runtime_observability
from automail.db.pocketbase.client import (
    deliver_queued_issue_replies_for_scope,
    record_delivery_run,
    run_sla_breach_escalations_for_scope,
)
from automail.support.crm import sync_support_crm_connectors_for_scope
from automail.support.ingestion import sync_support_channels_for_scope

logger = logging.getLogger(__name__)

_started = False
_delivery_started = False
_crm_started = False
_sla_started = False
_lock = threading.Lock()
_delivery_lock = threading.Lock()
_crm_lock = threading.Lock()
_sla_lock = threading.Lock()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or str(default))
    except ValueError:
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _delivery_run_error_summary(result: dict[str, Any]) -> str:
    failed = int(result.get("failed") or 0)
    blocked = int(result.get("blocked") or 0)
    if failed <= 0 and blocked <= 0:
        return ""

    labels: list[str] = []
    if failed > 0:
        labels.append(f"{failed} failed")
    if blocked > 0:
        labels.append(f"{blocked} blocked")

    errors: list[str] = []
    seen: set[str] = set()
    for item in result.get("items") if isinstance(result.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        error = str(item.get("error") or "").strip()
        if not error or error in seen:
            continue
        seen.add(error)
        errors.append(error)
        if len(errors) >= 3:
            break

    prefix = ", ".join(labels)
    if not errors:
        return prefix
    return f"{prefix}: {'; '.join(errors)}"


def _numeric_details(result: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "status",
        "channels",
        "connectors",
        "processed",
        "created",
        "updated",
        "sent",
        "failed",
        "blocked",
        "deferred",
        "skipped",
        "escalated",
        "claimed",
        "retried",
    }
    details: dict[str, Any] = {}
    for key in allowed:
        value = result.get(key)
        if isinstance(value, (str, bool, int, float)) or value is None:
            details[key] = value
    return details


def _run_observed(
    component: str,
    callback: Callable[[], dict[str, Any]],
    *,
    failure_keys: tuple[str, ...] = ("failed",),
) -> dict[str, Any]:
    started = runtime_observability.mark_started(component)
    try:
        result = callback()
    except Exception as exc:
        runtime_observability.mark_failure(component, exc, started_monotonic=started)
        raise

    failures = sum(int(result.get(key) or 0) for key in failure_keys)
    details = _numeric_details(result)
    if failures > 0:
        runtime_observability.mark_failure(
            component,
            f"run reported {failures} failed or blocked item(s)",
            started_monotonic=started,
            details=details,
        )
    else:
        status = str(result.get("status") or "ok")
        runtime_observability.mark_success(
            component,
            started_monotonic=started,
            status=status,
            details=details,
        )
    return result


def run_scheduled_support_sync(
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int = 25,
    source: str = "scheduler",
) -> dict[str, Any]:
    return _run_observed(
        "support.sync",
        lambda: sync_support_channels_for_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_email="support-sync",
            limit=max(1, min(limit, 100)),
            source=source,
        ),
    )


def run_scheduled_support_delivery(
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int = 25,
    source: str = "scheduler",
    retry_failed: bool = False,
) -> dict[str, Any]:
    started_at = _now_iso()

    def deliver() -> dict[str, Any]:
        result = deliver_queued_issue_replies_for_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            limit=max(1, min(limit, 100)),
            include_failed=retry_failed,
        )
        failed = int(result.get("failed") or 0)
        blocked = int(result.get("blocked") or 0)
        sent = int(result.get("sent") or 0)
        status = "idle"
        if result.get("processed"):
            if failed or blocked:
                status = "partial" if sent else "blocked" if blocked and not failed else "failed"
            else:
                status = "success"
        elif result.get("deferred"):
            status = "deferred"
        error = _delivery_run_error_summary(result)
        normalized = {**result, "status": status}
        if error:
            normalized["error"] = error
        return normalized

    result = _run_observed("support.delivery", deliver, failure_keys=("failed", "blocked"))
    completed_at = _now_iso()
    try:
        record_delivery_run(
            tenant_id=tenant_id,
            project_id=project_id,
            source=source,
            result=result,
            started_at=started_at,
            completed_at=completed_at,
        )
    except Exception as exc:
        runtime_observability.mark_failure("support.delivery.record", exc)
        logger.warning(
            "support_delivery_run_record_failed",
            exc_info=True,
            extra={"event": "support_delivery_run_record_failed"},
        )
    else:
        runtime_observability.mark_success("support.delivery.record", details={"recorded": True})
    return result


def run_scheduled_support_crm_sync(
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int = 25,
    source: str = "scheduler",
) -> dict[str, Any]:
    return _run_observed(
        "support.crm_sync",
        lambda: sync_support_crm_connectors_for_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            limit=max(1, min(limit, 100)),
            source=source,
        ),
    )


def run_scheduled_support_sla_escalations(
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
    source: str = "scheduler",
) -> dict[str, Any]:
    if not project_id:
        result = {
            "processed": 0,
            "escalated": 0,
            "skipped": 0,
            "failed": 1,
            "items": [],
            "error": "projectId is required for SLA escalation scans",
        }
        runtime_observability.mark_failure("support.sla", result["error"], details=_numeric_details(result))
        return result
    return _run_observed(
        "support.sla",
        lambda: run_sla_breach_escalations_for_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            limit=max(1, min(limit, 200)),
            actor_email="sla-monitor",
            source=source,
        ),
    )


def _sleep_after(started: float, interval_seconds: int) -> None:
    elapsed = time.monotonic() - started
    time.sleep(max(1, interval_seconds - int(elapsed)))


def _loop_sync(interval_seconds: int, tenant_id: str | None, project_id: str | None, limit: int) -> None:
    while True:
        started = time.monotonic()
        try:
            result = run_scheduled_support_sync(
                tenant_id=tenant_id,
                project_id=project_id,
                limit=limit,
                source="scheduler",
            )
            logger.info(
                "support_sync_scheduler_run",
                extra={"event": "support_sync_scheduler_run", **_numeric_details(result)},
            )
        except Exception:
            logger.warning("support_sync_scheduler_failed", exc_info=True, extra={"event": "support_sync_scheduler_failed"})
        _sleep_after(started, interval_seconds)


def _loop_delivery(interval_seconds: int, tenant_id: str | None, project_id: str | None, limit: int) -> None:
    while True:
        started = time.monotonic()
        try:
            result = run_scheduled_support_delivery(
                tenant_id=tenant_id,
                project_id=project_id,
                limit=limit,
                source="scheduler",
            )
            logger.info(
                "support_delivery_scheduler_run",
                extra={"event": "support_delivery_scheduler_run", **_numeric_details(result)},
            )
        except Exception:
            logger.warning(
                "support_delivery_scheduler_failed",
                exc_info=True,
                extra={"event": "support_delivery_scheduler_failed"},
            )
        _sleep_after(started, interval_seconds)


def _loop_crm_sync(interval_seconds: int, tenant_id: str | None, project_id: str | None, limit: int) -> None:
    while True:
        started = time.monotonic()
        try:
            result = run_scheduled_support_crm_sync(
                tenant_id=tenant_id,
                project_id=project_id,
                limit=limit,
                source="scheduler",
            )
            logger.info(
                "support_crm_sync_scheduler_run",
                extra={"event": "support_crm_sync_scheduler_run", **_numeric_details(result)},
            )
        except Exception:
            logger.warning(
                "support_crm_sync_scheduler_failed",
                exc_info=True,
                extra={"event": "support_crm_sync_scheduler_failed"},
            )
        _sleep_after(started, interval_seconds)


def _loop_sla(interval_seconds: int, tenant_id: str | None, project_id: str | None, limit: int) -> None:
    while True:
        started = time.monotonic()
        try:
            result = run_scheduled_support_sla_escalations(
                tenant_id=tenant_id,
                project_id=project_id,
                limit=limit,
                source="scheduler",
            )
            logger.info(
                "support_sla_scheduler_run",
                extra={"event": "support_sla_scheduler_run", **_numeric_details(result)},
            )
        except Exception:
            logger.warning("support_sla_scheduler_failed", exc_info=True, extra={"event": "support_sla_scheduler_failed"})
        _sleep_after(started, interval_seconds)


def _configure_component(name: str, interval_seconds: int, project_id: str | None) -> None:
    if interval_seconds <= 0:
        runtime_observability.mark_disabled(name, reason="interval not configured")
        return
    runtime_observability.mark_started(
        name,
        stale_after_seconds=max(interval_seconds * 3, interval_seconds + 60),
        details={"intervalSeconds": interval_seconds, "projectId": project_id or "*"},
    )


def start_support_sync_scheduler() -> bool:
    """Start optional in-process sync loop."""

    global _started
    interval_seconds = _int_env("SUPPORT_SYNC_INTERVAL_SECONDS", 0)
    tenant_id = os.getenv("SUPPORT_SYNC_TENANT_ID", "").strip() or None
    project_id = os.getenv("SUPPORT_SYNC_PROJECT_ID", "").strip() or None
    _configure_component("support.sync", interval_seconds, project_id)
    if interval_seconds <= 0:
        return False
    limit = _int_env("SUPPORT_SYNC_LIMIT", 25)
    with _lock:
        if _started:
            return True
        thread = threading.Thread(
            target=_loop_sync,
            args=(interval_seconds, tenant_id, project_id, limit),
            daemon=True,
            name="support-sync-scheduler",
        )
        thread.start()
        _started = True
    logger.info(
        "support_sync_scheduler_started",
        extra={"event": "support_sync_scheduler_started", "intervalSeconds": interval_seconds, "projectId": project_id or "*"},
    )
    return True


def start_support_delivery_scheduler() -> bool:
    """Start optional outbound delivery loop."""

    global _delivery_started
    interval_seconds = _int_env("SUPPORT_DELIVERY_INTERVAL_SECONDS", 0)
    tenant_id = os.getenv("SUPPORT_DELIVERY_TENANT_ID", "").strip() or None
    project_id = os.getenv("SUPPORT_DELIVERY_PROJECT_ID", "").strip() or None
    _configure_component("support.delivery", interval_seconds, project_id)
    if interval_seconds <= 0:
        return False
    limit = _int_env("SUPPORT_DELIVERY_LIMIT", 25)
    with _delivery_lock:
        if _delivery_started:
            return True
        thread = threading.Thread(
            target=_loop_delivery,
            args=(interval_seconds, tenant_id, project_id, limit),
            daemon=True,
            name="support-delivery-scheduler",
        )
        thread.start()
        _delivery_started = True
    logger.info(
        "support_delivery_scheduler_started",
        extra={"event": "support_delivery_scheduler_started", "intervalSeconds": interval_seconds, "projectId": project_id or "*"},
    )
    return True


def start_support_crm_sync_scheduler() -> bool:
    """Start optional CRM connector polling loop."""

    global _crm_started
    interval_seconds = _int_env("SUPPORT_CRM_SYNC_INTERVAL_SECONDS", 0)
    tenant_id = os.getenv("SUPPORT_CRM_SYNC_TENANT_ID", "").strip() or None
    project_id = os.getenv("SUPPORT_CRM_SYNC_PROJECT_ID", "").strip() or None
    _configure_component("support.crm_sync", interval_seconds, project_id)
    if interval_seconds <= 0:
        return False
    limit = _int_env("SUPPORT_CRM_SYNC_LIMIT", 25)
    with _crm_lock:
        if _crm_started:
            return True
        thread = threading.Thread(
            target=_loop_crm_sync,
            args=(interval_seconds, tenant_id, project_id, limit),
            daemon=True,
            name="support-crm-sync-scheduler",
        )
        thread.start()
        _crm_started = True
    logger.info(
        "support_crm_sync_scheduler_started",
        extra={"event": "support_crm_sync_scheduler_started", "intervalSeconds": interval_seconds, "projectId": project_id or "*"},
    )
    return True


def start_support_sla_scheduler() -> bool:
    """Start optional SLA breach escalation loop."""

    global _sla_started
    interval_seconds = _int_env("SUPPORT_SLA_INTERVAL_SECONDS", 0)
    tenant_id = os.getenv("SUPPORT_SLA_TENANT_ID", "").strip() or None
    project_id = os.getenv("SUPPORT_SLA_PROJECT_ID", "").strip() or None
    _configure_component("support.sla", interval_seconds, project_id)
    if interval_seconds <= 0:
        return False
    limit = _int_env("SUPPORT_SLA_LIMIT", 100)
    with _sla_lock:
        if _sla_started:
            return True
        thread = threading.Thread(
            target=_loop_sla,
            args=(interval_seconds, tenant_id, project_id, limit),
            daemon=True,
            name="support-sla-scheduler",
        )
        thread.start()
        _sla_started = True
    logger.info(
        "support_sla_scheduler_started",
        extra={"event": "support_sla_scheduler_started", "intervalSeconds": interval_seconds, "projectId": project_id or "*"},
    )
    return True
