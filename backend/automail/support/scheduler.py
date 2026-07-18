"""Scheduled support channel sync runner."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from automail.db.pocketbase.client import (
    deliver_queued_issue_replies_for_scope,
    expire_stale_direct_channel_processing_runs_for_scope,
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
_processing_expiry_started = False
_lock = threading.Lock()
_delivery_lock = threading.Lock()
_crm_lock = threading.Lock()
_sla_lock = threading.Lock()
_processing_expiry_lock = threading.Lock()


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


def run_scheduled_support_sync(
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int = 25,
    source: str = "scheduler",
) -> dict[str, Any]:
    return sync_support_channels_for_scope(
        tenant_id=tenant_id,
        project_id=project_id,
        actor_email="support-sync",
        limit=max(1, min(limit, 100)),
        source=source,
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
    result = {
        **result,
        "status": status,
    }
    if error:
        result["error"] = error
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
    except Exception:
        logger.warning("Failed to record support delivery run", exc_info=True)
    return result


def run_scheduled_support_crm_sync(
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int = 25,
    source: str = "scheduler",
) -> dict[str, Any]:
    return sync_support_crm_connectors_for_scope(
        tenant_id=tenant_id,
        project_id=project_id,
        limit=max(1, min(limit, 100)),
        source=source,
    )


def run_scheduled_support_sla_escalations(
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
    source: str = "scheduler",
) -> dict[str, Any]:
    if not project_id:
        return {
            "processed": 0,
            "escalated": 0,
            "skipped": 0,
            "failed": 1,
            "items": [],
            "error": "projectId is required for SLA escalation scans",
        }
    return run_sla_breach_escalations_for_scope(
        tenant_id=tenant_id,
        project_id=project_id,
        limit=max(1, min(limit, 200)),
        actor_email="sla-monitor",
        source=source,
    )


def run_scheduled_support_processing_expiry(
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int = 200,
    source: str = "scheduler",
) -> dict[str, Any]:
    return expire_stale_direct_channel_processing_runs_for_scope(
        tenant_id=tenant_id,
        project_id=project_id,
        limit=max(1, min(limit, 500)),
        source=source,
    )


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
                "Support sync scheduler run: channels=%s processed=%s failed=%s",
                result.get("channels"),
                result.get("processed"),
                result.get("failed"),
            )
        except Exception:
            logger.warning("Support sync scheduler run failed", exc_info=True)
        elapsed = time.monotonic() - started
        time.sleep(max(1, interval_seconds - int(elapsed)))


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
                "Support delivery scheduler run: processed=%s sent=%s failed=%s",
                result.get("processed"),
                result.get("sent"),
                result.get("failed"),
            )
        except Exception:
            logger.warning("Support delivery scheduler run failed", exc_info=True)
        elapsed = time.monotonic() - started
        time.sleep(max(1, interval_seconds - int(elapsed)))


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
                "Support CRM sync scheduler run: connectors=%s processed=%s failed=%s",
                result.get("connectors"),
                result.get("processed"),
                result.get("failed"),
            )
        except Exception:
            logger.warning("Support CRM sync scheduler run failed", exc_info=True)
        elapsed = time.monotonic() - started
        time.sleep(max(1, interval_seconds - int(elapsed)))


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
                "Support SLA scheduler run: processed=%s escalated=%s failed=%s",
                result.get("processed"),
                result.get("escalated"),
                result.get("failed"),
            )
        except Exception:
            logger.warning("Support SLA scheduler run failed", exc_info=True)
        elapsed = time.monotonic() - started
        time.sleep(max(1, interval_seconds - int(elapsed)))


def _loop_processing_expiry(
    interval_seconds: int,
    tenant_id: str | None,
    project_id: str | None,
    limit: int,
) -> None:
    while True:
        started = time.monotonic()
        try:
            result = run_scheduled_support_processing_expiry(
                tenant_id=tenant_id,
                project_id=project_id,
                limit=limit,
                source="scheduler",
            )
            logger.info(
                "Support processing expiry run: inspected=%s expired=%s failed=%s",
                result.get("inspected"),
                result.get("expired"),
                result.get("failed"),
            )
        except Exception:
            logger.warning("Support processing expiry run failed", exc_info=True)
        elapsed = time.monotonic() - started
        time.sleep(max(1, interval_seconds - int(elapsed)))


def start_support_sync_scheduler() -> bool:
    """Start optional in-process sync loop.

    Disabled unless SUPPORT_SYNC_INTERVAL_SECONDS is set to a positive value.
    External cron can use /api/internal/support/sync instead.
    """
    global _started
    interval_seconds = _int_env("SUPPORT_SYNC_INTERVAL_SECONDS", 0)
    if interval_seconds <= 0:
        return False
    tenant_id = os.getenv("SUPPORT_SYNC_TENANT_ID", "").strip() or None
    project_id = os.getenv("SUPPORT_SYNC_PROJECT_ID", "").strip() or None
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
    logger.info("Support sync scheduler started interval=%ss project=%s", interval_seconds, project_id or "*")
    return True


def start_support_delivery_scheduler() -> bool:
    """Start optional outbound delivery loop.

    Disabled unless SUPPORT_DELIVERY_INTERVAL_SECONDS is set to a positive value.
    External cron can use /api/internal/support/delivery instead.
    """
    global _delivery_started
    interval_seconds = _int_env("SUPPORT_DELIVERY_INTERVAL_SECONDS", 0)
    if interval_seconds <= 0:
        return False
    tenant_id = os.getenv("SUPPORT_DELIVERY_TENANT_ID", "").strip() or None
    project_id = os.getenv("SUPPORT_DELIVERY_PROJECT_ID", "").strip() or None
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
    logger.info("Support delivery scheduler started interval=%ss project=%s", interval_seconds, project_id or "*")
    return True


def start_support_crm_sync_scheduler() -> bool:
    """Start optional CRM connector polling loop.

    Disabled unless SUPPORT_CRM_SYNC_INTERVAL_SECONDS is set to a positive value.
    External cron can use /api/internal/support/crm-sync instead.
    """
    global _crm_started
    interval_seconds = _int_env("SUPPORT_CRM_SYNC_INTERVAL_SECONDS", 0)
    if interval_seconds <= 0:
        return False
    tenant_id = os.getenv("SUPPORT_CRM_SYNC_TENANT_ID", "").strip() or None
    project_id = os.getenv("SUPPORT_CRM_SYNC_PROJECT_ID", "").strip() or None
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
    logger.info("Support CRM sync scheduler started interval=%ss project=%s", interval_seconds, project_id or "*")
    return True


def start_support_sla_scheduler() -> bool:
    """Start optional SLA breach escalation loop.

    Disabled unless SUPPORT_SLA_INTERVAL_SECONDS is set to a positive value.
    External cron can use /api/internal/support/sla instead.
    """
    global _sla_started
    interval_seconds = _int_env("SUPPORT_SLA_INTERVAL_SECONDS", 0)
    if interval_seconds <= 0:
        return False
    tenant_id = os.getenv("SUPPORT_SLA_TENANT_ID", "").strip() or None
    project_id = os.getenv("SUPPORT_SLA_PROJECT_ID", "").strip() or None
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
    logger.info("Support SLA scheduler started interval=%ss project=%s", interval_seconds, project_id or "*")
    return True


def start_support_processing_expiry_scheduler() -> bool:
    """Start the default-on abandoned-processing expiry sweep."""
    global _processing_expiry_started
    interval_seconds = _int_env("SUPPORT_PROCESSING_EXPIRY_INTERVAL_SECONDS", 60)
    if interval_seconds <= 0:
        return False
    tenant_id = os.getenv("SUPPORT_PROCESSING_EXPIRY_TENANT_ID", "").strip() or None
    project_id = os.getenv("SUPPORT_PROCESSING_EXPIRY_PROJECT_ID", "").strip() or None
    limit = _int_env("SUPPORT_PROCESSING_EXPIRY_LIMIT", 200)
    with _processing_expiry_lock:
        if _processing_expiry_started:
            return True
        thread = threading.Thread(
            target=_loop_processing_expiry,
            args=(interval_seconds, tenant_id, project_id, limit),
            daemon=True,
            name="support-processing-expiry-scheduler",
        )
        thread.start()
        _processing_expiry_started = True
    logger.info(
        "Support processing expiry scheduler started interval=%ss project=%s",
        interval_seconds,
        project_id or "*",
    )
    return True
