"""Durable asynchronous execution for admin channel test messages."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from automail.db.pocketbase.client import (
    _list_all,
    get_channel_webhook_event,
    ingest_channel_webhook,
    record_channel_webhook_event,
    update_channel_webhook_event,
)
from automail.db.pocketbase.issues import (
    _claim_existing_channel_webhook_event,
    _try_complete_channel_webhook_claim,
)

logger = logging.getLogger(__name__)

CHANNEL_TEST_JOB_KIND = "admin_channel_test_message"
CHANNEL_TEST_JOB_PROVIDER = "admin-test-job"
CHANNEL_TEST_JOB_TERMINAL_STATUSES = {
    "processed",
    "failed",
    "skipped",
    "ignored",
    "unmatched",
}
# Provider-event ownership lasts 15 minutes. Recovery must start after that lease,
# otherwise ingestion correctly reports the still-active owner as a replay.
CHANNEL_TEST_JOB_STALE_MINUTES = 16

_active_job_ids: set[str] = set()
_active_job_lock = threading.Lock()


def _string(value: Any) -> str:
    return str(value or "").strip()


def _record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _event_token(value: str) -> str:
    clean = [character if character.isalnum() else "_" for character in value.strip().lower()]
    return "_".join(part for part in "".join(clean).split("_") if part)


def _ticket_creation_mode(channel: dict[str, Any]) -> str:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    raw = _event_token(
        _string(
            config.get("ticketCreationMode")
            or config.get("ticket_creation_mode")
            or config.get("issueCreationMode")
            or config.get("issue_creation_mode")
        )
    )
    return "per_thread" if raw in {
        "per_thread",
        "perthread",
        "thread",
        "thread_updates",
        "conversation",
        "conversation_updates",
        "existing_ticket_per_thread",
        "one_ticket_per_thread",
    } else "per_message"


def channel_test_source_ids(
    channel: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, str]:
    """Mirror generic-ingestion resolver IDs for the normalized admin payload."""

    provider = _event_token(
        _string(payload.get("provider") or channel.get("type") or "channel")
    ) or "channel"
    channel_key = _string(channel.get("channelKey"))
    channel_id = _string(payload.get("channelId")) or channel_key
    message_id = _string(payload.get("messageId") or payload.get("eventId"))
    thread_id = _string(payload.get("threadId")) or message_id
    source_key = message_id if _ticket_creation_mode(channel) == "per_message" else thread_id
    source_issue_id = f"{provider}:{channel_key}:{channel_id}:{source_key}"
    return source_issue_id, f"{source_issue_id}:{message_id}"


def _job_metadata(
    *,
    channel: dict[str, Any],
    payload: dict[str, Any],
    tenant_id: str | None,
    project_id: str,
) -> dict[str, Any]:
    source_issue_id, source_message_id = channel_test_source_ids(channel, payload)
    return {
        "kind": CHANNEL_TEST_JOB_KIND,
        "tenantId": tenant_id or "",
        "projectId": project_id,
        "channelId": _string(channel.get("id")),
        "channelKey": _string(channel.get("channelKey")),
        "eventId": _string(payload.get("eventId")),
        "messageId": _string(payload.get("messageId")),
        "sourceIssueId": source_issue_id,
        "sourceMessageId": source_message_id,
        "queued": True,
    }


def _job_event_id(provider_event_id: str) -> str:
    """Keep the durable job receipt outside the provider event's claim key."""

    return f"admin-test-job:{provider_event_id}:{uuid4().hex}"


def _filter_token(value: str) -> str:
    return value.replace("'", "\\'")


def _response_from_event(
    event: dict[str, Any],
    *,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    raw_status = _string(event.get("status")) or "received"
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    status = (
        "processing"
        if raw_status == "received" and bool(result.get("processing"))
        else "queued"
        if raw_status == "received"
        else raw_status
    )
    aggregate = result.get("aggregate") if isinstance(result.get("aggregate"), dict) else {}
    issue_id = _string(result.get("issueId") or metadata.get("issueId"))
    terminal = status in CHANNEL_TEST_JOB_TERMINAL_STATUSES
    failed = int(aggregate.get("failed") or (1 if status == "failed" else 0))
    skipped = int(
        aggregate.get("skipped") or (1 if status in {"skipped", "ignored"} else 0)
    )
    processed = int(aggregate.get("processed") or (1 if status == "processed" else 0))
    unmatched = int(aggregate.get("unmatched") or (1 if status == "unmatched" else 0))
    item = {
        "eventId": metadata["eventId"],
        "status": status,
        "kind": CHANNEL_TEST_JOB_KIND,
        "issueId": issue_id,
        "messageId": _string(result.get("messageId") or metadata.get("messageId")),
        "error": _string(event.get("error") or result.get("error")),
    }
    return {
        "accepted": not terminal,
        "status": status,
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "unmatched": unmatched,
        "payload": payload,
        "items": aggregate.get("items") if isinstance(aggregate.get("items"), list) else [item],
        "error": _string(aggregate.get("error") or item["error"]),
        "runId": _string(event.get("id")),
        "jobEventId": _string(event.get("eventId") or event.get("event_id")),
        "eventId": metadata["eventId"],
        "messageId": metadata["messageId"],
        "issueId": issue_id,
        "sourceIssueId": metadata["sourceIssueId"],
        "sourceMessageId": metadata["sourceMessageId"],
    }


def _aggregate_waits_for_provider_claim(aggregate: dict[str, Any]) -> bool:
    items = aggregate.get("items") if isinstance(aggregate.get("items"), list) else []
    return any(
        _string(item.get("winnerStatus")).lower() in {"received", "processing", "claimed"}
        for item in items
        if isinstance(item, dict)
    )


def enqueue_channel_test_message(
    *,
    channel: dict[str, Any],
    payload: dict[str, Any],
    tenant_id: str | None,
    project_id: str,
) -> dict[str, Any]:
    """Persist before launching so process loss cannot silently drop work."""

    channel_id = _string(channel.get("id"))
    event_id = _string(payload.get("eventId"))
    if not channel_id or not event_id:
        raise ValueError("Channel and event identifiers are required")
    metadata = _job_metadata(
        channel=channel,
        payload=payload,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    job_event_id = _job_event_id(event_id)
    event = record_channel_webhook_event(
        tenant_id=tenant_id,
        project_id=project_id,
        channel_id=channel_id,
        provider=CHANNEL_TEST_JOB_PROVIDER,
        event_id=job_event_id,
        event_type=CHANNEL_TEST_JOB_KIND,
        provider_message_id=_string(payload.get("messageId")),
        status="received",
        payload=payload,
        result=metadata,
    )
    start_channel_test_job(
        job_id=_string(event.get("id")),
        channel_id=channel_id,
        event_id=job_event_id,
        channel_key=metadata["channelKey"],
        payload=payload,
        tenant_id=tenant_id,
        project_id=project_id,
        metadata=metadata,
    )
    return _response_from_event(event, payload=payload, metadata=metadata)


def get_channel_test_job_status(
    job_id: str,
    *,
    tenant_id: str | None,
    project_id: str,
) -> dict[str, Any] | None:
    """Read one durable job exactly, scoped to the requesting project."""

    parts = [
        f"id='{_filter_token(_string(job_id))}'",
        f"project='{_filter_token(_string(project_id))}'",
        f"provider='{CHANNEL_TEST_JOB_PROVIDER}'",
    ]
    if tenant_id:
        parts.append(f"tenant='{_filter_token(_string(tenant_id))}'")
    records = _list_all(
        "support_channel_webhook_events",
        " && ".join(parts),
        per_page=1,
    )
    if not records:
        return None
    event = records[0]
    metadata = _record(event.get("result"))
    if metadata.get("kind") != CHANNEL_TEST_JOB_KIND:
        return None
    payload = _record(event.get("payload"))
    return _response_from_event(
        {**event, "payload": payload, "result": metadata},
        payload=payload,
        metadata=metadata,
    )


def process_channel_test_job(
    *,
    job_id: str,
    channel_id: str,
    event_id: str,
    channel_key: str,
    payload: dict[str, Any],
    tenant_id: str | None,
    project_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Run one durable job and persist terminal result or failure."""

    current = get_channel_webhook_event(
        channel_id,
        event_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    if not current:
        return {"status": "missing", "processed": 0, "failed": 1}
    if _string(current.get("status")) in CHANNEL_TEST_JOB_TERMINAL_STATUSES:
        stored = _record(current.get("result"))
        aggregate = stored.get("aggregate")
        return aggregate if isinstance(aggregate, dict) else {"status": current["status"]}
    claimed, claim_token = _claim_existing_channel_webhook_event(
        current,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    if not claim_token:
        return {"status": "claimed", "processed": 0, "failed": 0, "skipped": 0}
    claim_result = _record(claimed.get("result"))
    try:
        update_channel_webhook_event(
            job_id,
            tenant_id=tenant_id,
            project_id=project_id,
            status="received",
            result={**claim_result, **metadata, "queued": False, "processing": True},
        )
        aggregate = ingest_channel_webhook(
            channel_key,
            payload=payload,
            tenant_id=tenant_id,
            project_id=project_id,
            source="admin-test-async",
        )
        if _aggregate_waits_for_provider_claim(aggregate):
            logger.info(
                "Admin channel test job is waiting for provider claim expiry job=%s",
                job_id,
            )
            return aggregate
        items = aggregate.get("items") if isinstance(aggregate.get("items"), list) else []
        item = next((value for value in items if isinstance(value, dict)), {})
        winner_status = _string(item.get("winnerStatus")).lower()
        recovered_after_provider_completion = (
            int(claimed.get("processingAttempt") or 0) > 1
            and winner_status in CHANNEL_TEST_JOB_TERMINAL_STATUSES
        )
        if recovered_after_provider_completion:
            aggregate = {
                **aggregate,
                "processed": 1 if winner_status == "processed" else 0,
                "failed": 1 if winner_status == "failed" else 0,
                "skipped": 1 if winner_status in {"skipped", "ignored"} else 0,
                "unmatched": 1 if winner_status == "unmatched" else 0,
            }
        if int(aggregate.get("failed") or 0):
            status = "failed"
        elif int(aggregate.get("processed") or 0):
            status = "processed"
        elif int(aggregate.get("skipped") or 0):
            status = "skipped"
        elif int(aggregate.get("unmatched") or 0):
            status = "unmatched"
        else:
            status = "ignored"
        final_result = {
            **item,
            **metadata,
            "queued": False,
            "processing": False,
            "aggregate": aggregate,
        }
        completed = _try_complete_channel_webhook_claim(
            job_id,
            tenant_id=tenant_id,
            project_id=project_id,
            claim_token=claim_token,
            status=status,
            result=final_result,
            error=_string(aggregate.get("error")),
        )
        if not completed:
            logger.info("Admin channel test job ownership changed before completion job=%s", job_id)
        return aggregate
    except Exception as exc:
        error = str(exc)[:1_000]
        try:
            _try_complete_channel_webhook_claim(
                job_id,
                tenant_id=tenant_id,
                project_id=project_id,
                claim_token=claim_token,
                status="failed",
                result={
                    **metadata,
                    "queued": False,
                    "processing": False,
                    "error": error,
                },
                error=error,
            )
        except Exception:
            logger.exception("Could not persist admin channel test job failure job=%s", job_id)
        logger.exception("Admin channel test job failed job=%s", job_id)
        return {"status": "failed", "processed": 0, "failed": 1, "error": error}


def _run_and_release(**kwargs: Any) -> None:
    job_id = _string(kwargs.get("job_id"))
    try:
        process_channel_test_job(**kwargs)
    finally:
        with _active_job_lock:
            _active_job_ids.discard(job_id)


def start_channel_test_job(**kwargs: Any) -> bool:
    """Kick a daemon worker; durable scheduler remains recovery authority."""

    job_id = _string(kwargs.get("job_id"))
    if not job_id:
        return False
    with _active_job_lock:
        if job_id in _active_job_ids:
            return False
        _active_job_ids.add(job_id)
    thread = threading.Thread(
        target=_run_and_release,
        kwargs=kwargs,
        daemon=True,
        name=f"channel-test-{job_id[:12]}",
    )
    thread.start()
    return True


def _parse_datetime(value: Any) -> datetime | None:
    clean = _string(value)
    if not clean:
        return None
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _raw_jobs(status: str, limit: int) -> list[dict[str, Any]]:
    records = [
        record
        for record in _list_all(
            "support_channel_webhook_events",
            f"status='{status}' && provider='{CHANNEL_TEST_JOB_PROVIDER}'",
            sort="received_at",
            per_page=max(1, min(limit, 200)),
        )
        if _record(record.get("result")).get("kind") == CHANNEL_TEST_JOB_KIND
    ]
    return records[: max(1, min(limit, 200))]


def run_queued_channel_test_jobs(
    *,
    limit: int = 25,
    stale_minutes: int = CHANNEL_TEST_JOB_STALE_MINUTES,
) -> dict[str, Any]:
    """Recover unclaimed jobs and jobs whose durable ownership expired."""

    queued = _raw_jobs("queued", limit)
    now = datetime.now(timezone.utc)
    stale_before = datetime.now(timezone.utc) - timedelta(
        minutes=max(CHANNEL_TEST_JOB_STALE_MINUTES, stale_minutes),
    )
    received = [
        record
        for record in _raw_jobs("received", limit)
        if not _string(record.get("processing_claim_token"))
        or (
            (_parse_datetime(record.get("processing_claim_expires_at")) or stale_before) <= now
            and (_parse_datetime(record.get("updated")) or stale_before) <= stale_before
        )
    ]
    processing = [
        record
        for record in _raw_jobs("processing", limit)
        if (_parse_datetime(record.get("updated") or record.get("processed_at")) or stale_before)
        <= stale_before
    ]
    candidates = [*queued, *received, *processing][: max(1, min(limit, 200))]
    started = 0
    skipped = 0
    items: list[dict[str, Any]] = []
    for record in candidates:
        metadata = _record(record.get("result"))
        payload = _record(record.get("payload"))
        kwargs = {
            "job_id": _string(record.get("id")),
            "channel_id": _string(record.get("channel")),
            "event_id": _string(record.get("event_id")),
            "channel_key": _string(metadata.get("channelKey")),
            "payload": payload,
            "tenant_id": _string(record.get("tenant")) or None,
            "project_id": _string(record.get("project") or metadata.get("projectId")),
            "metadata": metadata,
        }
        if not all((kwargs["job_id"], kwargs["channel_id"], kwargs["event_id"], kwargs["channel_key"], kwargs["project_id"])):
            skipped += 1
            items.append({"id": kwargs["job_id"], "status": "invalid"})
            continue
        was_started = start_channel_test_job(**kwargs)
        started += int(was_started)
        skipped += int(not was_started)
        items.append({"id": kwargs["job_id"], "status": "started" if was_started else "active"})
    return {
        "inspected": len(candidates),
        "started": started,
        "skipped": skipped,
        "items": items,
    }
