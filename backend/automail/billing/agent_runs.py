"""Canonical, idempotent billing reservations for inbound agent runs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import httpx

from automail.billing.config import IS_SAAS


@dataclass(frozen=True, slots=True)
class AgentRunReservation:
    """Result of reserving one inbound message as one billable agent run."""

    record: dict | None
    created: bool
    metered: bool


def _agent_run_key(namespace: str, *parts: str) -> str:
    """Build a bounded, non-PII key for PocketBase's tenant-scoped index."""
    clean_namespace = namespace.strip().lower().replace(" ", "_") or "inbound"
    material = "\0".join(str(part).strip() for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{clean_namespace}:{digest}"


def email_agent_run_key(*, project_id: str | None, email_id: str) -> str:
    """Return one stable key regardless of which email adapter delivered it."""
    return _agent_run_key("email", project_id or "", email_id)


def direct_channel_agent_run_key(
    *,
    project_id: str,
    source: str,
    source_message_id: str,
) -> str:
    """Return one stable key for a direct-channel provider message."""
    return _agent_run_key("channel", project_id, source, source_message_id)


def _existing_agent_run(tenant_id: str, idempotency_key: str) -> dict | None:
    from automail.db.pocketbase.client import _escape_pb, _first

    return _first(
        "agent_runs",
        (
            f"tenant='{_escape_pb(tenant_id)}' && "
            f"idempotency_key='{_escape_pb(idempotency_key)}'"
        ),
    )


def reserve_agent_run(
    *,
    tenant_id: str | None,
    project_id: str | None,
    source: str,
    idempotency_key: str,
) -> AgentRunReservation:
    """Reserve one inbound message before AI work.

    Hosted deployments enforce the plan limit and persist one row protected by
    a unique ``(tenant, idempotency_key)`` index. A retry returns the existing
    reservation and therefore cannot consume a second run. Community/self-
    hosted deployments stay unlimited and do not require the billing ledger.
    """
    if not IS_SAAS or not tenant_id:
        return AgentRunReservation(record=None, created=False, metered=False)

    clean_source = source.strip() or "inbound"
    clean_key = idempotency_key.strip()
    if not clean_key:
        raise ValueError("Agent-run idempotency key is required")

    existing = _existing_agent_run(tenant_id, clean_key)
    if existing:
        return AgentRunReservation(record=existing, created=False, metered=True)

    # Check after the duplicate lookup so a retry can still read its existing
    # result when the tenant has since reached the limit.
    from automail.billing.usage import check_limit

    check_limit(tenant_id, "agent_runs_per_month")

    from automail.db.pocketbase.client import _post, generate_id

    data: dict = {
        "id": generate_id(),
        "tenant": tenant_id,
        "source": clean_source,
        "idempotency_key": clean_key,
    }
    if project_id:
        data["project"] = project_id

    try:
        record = _post("/api/collections/agent_runs/records", data)
    except httpx.HTTPStatusError:
        # A concurrent worker may have won the unique-index race after our
        # initial lookup. Only swallow the error when that row now exists.
        existing = _existing_agent_run(tenant_id, clean_key)
        if not existing:
            raise
        return AgentRunReservation(record=existing, created=False, metered=True)

    return AgentRunReservation(record={**data, **record}, created=True, metered=True)
