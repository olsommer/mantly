"""Durable ownership claims for connected-channel email processing."""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from automail.db.pocketbase.base import _escape_pb, _list_all, _patch, _post
from automail.db.pocketbase.chats import get_chat

_COLLECTION = "email_processing_claims"
_DEFAULT_LEASE_SECONDS = 15 * 60
_DEFAULT_WAIT_SECONDS = 3 * 60
_DEFAULT_POLL_SECONDS = 0.25


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def _claim_key(*, project_id: str, email_id: str) -> str:
    raw = f"{project_id}\0{email_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _claim_record_id(*, claim_key: str, attempt: int) -> str:
    raw = f"{claim_key}:{attempt}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:15]


def _attempt(record: dict[str, Any] | None) -> int:
    try:
        return max(0, int((record or {}).get("attempt") or 0))
    except (TypeError, ValueError):
        return 0


def _latest_claim(*, project_id: str, email_id: str) -> dict[str, Any] | None:
    claim_key = _claim_key(project_id=project_id, email_id=email_id)
    records = _list_all(
        _COLLECTION,
        (
            f"project='{_escape_pb(project_id)}' && "
            f"claim_key='{_escape_pb(claim_key)}'"
        ),
        sort="-attempt",
        per_page=20,
    )
    if not records:
        return None
    return max(records, key=_attempt)


def _parse_datetime(value: Any) -> datetime | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_expired(record: dict[str, Any] | None) -> bool:
    lease_until = _parse_datetime((record or {}).get("lease_until"))
    return lease_until is None or lease_until <= datetime.now(timezone.utc)


def _claim_view(record: dict[str, Any], *, owner_token: str = "", owned: bool = False) -> dict[str, Any]:
    return {
        "id": str(record.get("id") or ""),
        "claimKey": str(record.get("claim_key") or ""),
        "emailId": str(record.get("email_id") or ""),
        "attempt": _attempt(record),
        "ownerToken": owner_token,
        "status": str(record.get("status") or "processing"),
        "owned": owned,
        "leaseUntil": str(record.get("lease_until") or ""),
    }


def acquire_email_processing_claim(
    *,
    email_id: str,
    tenant_id: str | None,
    project_id: str,
    lease_seconds: float | None = None,
) -> dict[str, Any]:
    """Atomically elect one worker for a project/email pair.

    Attempts are immutable rows with deterministic record IDs. A failed or
    expired attempt advances to the next deterministic ID, so two workers
    racing to recover cannot both acquire ownership.
    """
    latest = _latest_claim(project_id=project_id, email_id=email_id)
    status = str((latest or {}).get("status") or "").strip().lower()
    if latest and status == "completed":
        return _claim_view(latest)
    if latest and status not in {"failed"} and not _is_expired(latest):
        return _claim_view(latest)

    attempt = _attempt(latest) + 1
    claim_key = _claim_key(project_id=project_id, email_id=email_id)
    owner_token = secrets.token_urlsafe(24)
    lease_for = lease_seconds or _positive_float_env(
        "EMAIL_PROCESSING_CLAIM_LEASE_SECONDS",
        _DEFAULT_LEASE_SECONDS,
    )
    now = datetime.now(timezone.utc)
    data: dict[str, Any] = {
        "id": _claim_record_id(claim_key=claim_key, attempt=attempt),
        "project": project_id,
        "claim_key": claim_key,
        "email_id": email_id,
        "attempt": attempt,
        "owner_token": owner_token,
        "status": "processing",
        "lease_until": (now + timedelta(seconds=lease_for)).isoformat(),
        "error": "",
    }
    if tenant_id:
        data["tenant"] = tenant_id
    try:
        created = _post(f"/api/collections/{_COLLECTION}/records", data)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in {400, 409}:
            raise
        winner = _latest_claim(project_id=project_id, email_id=email_id)
        if not winner:
            raise
        return _claim_view(winner)
    return _claim_view({**data, **created}, owner_token=owner_token, owned=True)


def owns_email_processing_claim(
    claim: dict[str, Any],
    *,
    email_id: str,
    project_id: str,
) -> bool:
    if not claim.get("owned"):
        return False
    latest = _latest_claim(project_id=project_id, email_id=email_id)
    return bool(
        latest
        and str(latest.get("id") or "") == str(claim.get("id") or "")
        and str(latest.get("owner_token") or "") == str(claim.get("ownerToken") or "")
        and str(latest.get("status") or "").strip().lower() == "processing"
        and not _is_expired(latest)
    )


def complete_email_processing_claim(
    claim: dict[str, Any],
    *,
    email_id: str,
    project_id: str,
) -> bool:
    if not owns_email_processing_claim(claim, email_id=email_id, project_id=project_id):
        return False
    _patch(
        f"/api/collections/{_COLLECTION}/records/{claim['id']}",
        {
            "status": "completed",
            "lease_until": datetime.now(timezone.utc).isoformat(),
            "error": "",
        },
    )
    return True


def fail_email_processing_claim(
    claim: dict[str, Any] | None,
    *,
    email_id: str,
    project_id: str,
    error: str,
) -> bool:
    if not claim or not claim.get("owned"):
        return False
    latest = _latest_claim(project_id=project_id, email_id=email_id)
    if not latest:
        return False
    if (
        str(latest.get("id") or "") != str(claim.get("id") or "")
        or str(latest.get("owner_token") or "") != str(claim.get("ownerToken") or "")
    ):
        return False
    _patch(
        f"/api/collections/{_COLLECTION}/records/{claim['id']}",
        {
            "status": "failed",
            "lease_until": datetime.now(timezone.utc).isoformat(),
            "error": str(error or "Email processing failed")[:500],
        },
    )
    return True


def wait_for_email_processing_claim(
    *,
    email_id: str,
    tenant_id: str | None,
    project_id: str,
    wait_seconds: float | None = None,
    poll_seconds: float | None = None,
) -> dict[str, Any] | None:
    """Wait for winner to finish issue sync, then return cached chat."""
    wait_for = wait_seconds or _positive_float_env(
        "EMAIL_PROCESSING_WAIT_SECONDS",
        _DEFAULT_WAIT_SECONDS,
    )
    poll_for = poll_seconds or _DEFAULT_POLL_SECONDS
    deadline = time.monotonic() + wait_for
    while time.monotonic() < deadline:
        latest = _latest_claim(project_id=project_id, email_id=email_id)
        if not latest:
            return None
        status = str(latest.get("status") or "").strip().lower()
        if status == "completed":
            chat = get_chat(email_id, tenant_id=tenant_id, project_id=project_id)
            if chat:
                return chat
        elif status == "failed" or _is_expired(latest):
            return None
        time.sleep(poll_for)
    return None
