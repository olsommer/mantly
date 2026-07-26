"""Secure storage helpers for SaaS-issued on-prem license keys."""

import hashlib
import logging
import re
import secrets
from typing import Any

import httpx

from automail.db.pocketbase.client import _escape_pb, _first, _patch

logger = logging.getLogger(__name__)

LICENSE_KEY_BYTES = 20
LICENSE_KEY_PREFIX_LENGTH = 8
_LEGACY_LICENSE_KEY_RE = re.compile(r"^[0-9a-f]{40}$")


def generate_license_key() -> str:
    """Return a high-entropy key that is revealed only to its creator."""
    return secrets.token_hex(LICENSE_KEY_BYTES)


def license_key_digest(key: str) -> str:
    """Return the deterministic digest stored and indexed by PocketBase."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def license_key_prefix(key: str) -> str:
    """Return the short non-secret identifier shown in admin inventories."""
    return key[:LICENSE_KEY_PREFIX_LENGTH]


def license_key_storage_fields(key: str) -> dict[str, str]:
    """Build fields that persist no recoverable license secret."""
    return {
        "key": license_key_digest(key),
        "key_prefix": license_key_prefix(key),
    }


def license_key_prefix_from_record(record: dict[str, Any]) -> str:
    """Return a safe display prefix for hashed and legacy records."""
    stored_prefix = str(record.get("key_prefix") or "").strip()
    if stored_prefix:
        return stored_prefix[:LICENSE_KEY_PREFIX_LENGTH]

    legacy_key = str(record.get("key") or "").strip().lower()
    if _LEGACY_LICENSE_KEY_RE.fullmatch(legacy_key):
        return license_key_prefix(legacy_key)
    return ""


def masked_license_key(record: dict[str, Any]) -> str:
    """Return a stable preview without exposing a full key or stored digest."""
    prefix = license_key_prefix_from_record(record)
    return f"{prefix}..." if prefix else "********"


def _legacy_lookup_allowed(key: str) -> bool:
    """Recognize only the exact format generated before digest storage.

    In particular, a 64-character stored SHA-256 digest must never be accepted
    as a presented key through the compatibility lookup.
    """
    return _LEGACY_LICENSE_KEY_RE.fullmatch(key.lower()) is not None


def find_license_by_key(key: str) -> dict[str, Any] | None:
    """Find a hashed license record, with bounded legacy migration support."""
    digest = license_key_digest(key)
    record = _first("licenses", f"key='{_escape_pb(digest)}'")
    if record or not _legacy_lookup_allowed(key):
        return record

    legacy_record = _first("licenses", f"key='{_escape_pb(key)}'")
    if not legacy_record:
        return None

    record_id = str(legacy_record.get("id") or "").strip()
    if record_id:
        try:
            _patch(
                f"/api/collections/licenses/records/{record_id}",
                license_key_storage_fields(key),
            )
            legacy_record = {
                **legacy_record,
                **license_key_storage_fields(key),
            }
            logger.info("Migrated legacy license record %s to digest storage", record_id)
        except httpx.HTTPError as exc:
            # A failed best-effort migration must not invalidate an otherwise
            # valid legacy deployment. The next validation retries migration.
            status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
            logger.warning(
                "Could not migrate legacy license record %s (status=%s)",
                record_id,
                status_code,
            )
    return legacy_record
