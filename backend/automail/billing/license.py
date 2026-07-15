"""On-prem license client — phone-home validation against the SaaS server.

When LICENSE_KEY and LICENSE_SERVER_URL are set the backend validates its
license on startup and periodically re-validates in a background thread.
If validation fails (after the grace period), a middleware rejects all
API requests with 503 Service Unavailable.

Environment variables:
    LICENSE_KEY         — the license key issued by the SaaS provider
    LICENSE_SERVER_URL  — the SaaS server URL (e.g. https://api.mantly.io)
    LICENSE_GRACE_HOURS — hours to keep operating on a cached validation
                          after the server becomes unreachable (default: 48)
    INSTANCE_ID_PATH   — path to the persistent instance fingerprint file
                          (default: /app/data/.instance-id)
"""

import hashlib
import hmac
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from automail.core.brand import get_brand

logger = logging.getLogger(__name__)

LICENSE_KEY: str = os.getenv("LICENSE_KEY", "").strip()
LICENSE_SERVER_URL: str = os.getenv("LICENSE_SERVER_URL", "").strip().rstrip("/")
LICENSE_GRACE_HOURS: int = int(os.getenv("LICENSE_GRACE_HOURS", "48"))

# Paths that should always be accessible (health checks, static assets)
_EXEMPT_PREFIXES = ("/api/health", "/addin/", "/assets/", "/favicon")

# Path for the persistent instance fingerprint (survives container recreation)
_INSTANCE_ID_PATH = Path(os.getenv("INSTANCE_ID_PATH", "/app/data/.instance-id"))
_instance_id_fallback: str | None = None


# ── Instance fingerprint ──────────────────────────────────────────────────────

def _machine_fingerprint() -> str:
    """Return a stable instance fingerprint persisted to disk.

    On first boot a random UUID is generated and written to
    ``_INSTANCE_ID_PATH``.  On subsequent boots the stored value is read back.
    This survives Docker container recreation as long as the ``/app/data``
    volume is persistent.
    """
    try:
        if _INSTANCE_ID_PATH.exists():
            stored = _INSTANCE_ID_PATH.read_text().strip()
            if stored:
                return stored
    except OSError:
        pass

    global _instance_id_fallback
    if _instance_id_fallback:
        return _instance_id_fallback

    # Generate a new fingerprint and persist it
    fingerprint = uuid.uuid4().hex
    try:
        _INSTANCE_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        _INSTANCE_ID_PATH.write_text(fingerprint)
        logger.info("Generated new instance fingerprint: %s…", fingerprint[:8])
    except OSError as exc:
        logger.warning("Could not persist instance fingerprint: %s", exc)
    _instance_id_fallback = fingerprint
    return fingerprint


# ── HMAC helpers for cache integrity ──────────────────────────────────────────

def _hmac_key() -> bytes:
    """Derive a signing key from LICENSE_KEY alone.

    The license key is a 40-char hex secret with sufficient entropy for HMAC.
    This is intentionally decoupled from JWT_SECRET so that rotating
    JWT_SECRET does not invalidate the license cache.
    """
    return hashlib.sha256(LICENSE_KEY.encode()).digest()


def _sign_payload(payload_bytes: bytes) -> str:
    return hmac.new(_hmac_key(), payload_bytes, "sha256").hexdigest()


def _verify_signature(payload_bytes: bytes, signature: str) -> bool:
    expected = _sign_payload(payload_bytes)
    return hmac.compare_digest(expected, signature)


# ── License state ─────────────────────────────────────────────────────────────

@dataclass
class LicenseState:
    valid: bool = False
    message: str = "License not yet validated"
    expires_at: Optional[str] = None
    max_users: Optional[int] = None
    last_check: float = 0.0  # time.time() of last successful check
    last_attempt: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def is_within_grace_period(self) -> bool:
        if self.last_check == 0.0:
            return False
        elapsed_hours = (time.time() - self.last_check) / 3600
        return elapsed_hours < LICENSE_GRACE_HOURS

    def should_allow_requests(self) -> bool:
        with self._lock:
            return self.valid or self.is_within_grace_period()

    def update(self, valid: bool, message: str, expires_at: Optional[str] = None, max_users: Optional[int] = None):
        with self._lock:
            self.valid = valid
            self.message = message
            self.expires_at = expires_at
            self.max_users = max_users
            self.last_attempt = time.time()
            if valid:
                self.last_check = time.time()


_state = LicenseState()

# Path to the cached license response (survives container restarts)
_CACHE_PATH = Path(os.getenv("LICENSE_CACHE_PATH", "/app/data/license_cache.json"))


def _save_cache():
    """Persist the last successful validation to disk with HMAC integrity."""
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "valid": _state.valid,
            "message": _state.message,
            "expires_at": _state.expires_at,
            "max_users": _state.max_users,
            "last_check": _state.last_check,
        }, sort_keys=True)
        sig = _sign_payload(payload.encode())
        _CACHE_PATH.write_text(json.dumps({"data": json.loads(payload), "sig": sig}))
    except OSError:
        pass


def _load_cache():
    """Restore cached validation from disk, verifying HMAC integrity."""
    try:
        if not _CACHE_PATH.exists():
            return

        raw = json.loads(_CACHE_PATH.read_text())

        data = raw["data"]
        sig = raw["sig"]
        payload_bytes = json.dumps(data, sort_keys=True).encode()
        if not _verify_signature(payload_bytes, sig):
            logger.warning("License cache HMAC mismatch — ignoring cached state")
            return

        _state.valid = data.get("valid", False)
        _state.message = data.get("message", "")
        _state.expires_at = data.get("expires_at")
        _state.max_users = data.get("max_users")
        _state.last_check = data.get("last_check", 0.0)
        logger.info("Loaded cached license state: valid=%s last_check=%.0f", _state.valid, _state.last_check)
    except (OSError, json.JSONDecodeError, KeyError):
        logger.warning("Failed to load license cache — will re-validate")


# ── Validation logic ─────────────────────────────────────────────────────────

def _validate_once() -> bool:
    """Call the SaaS license server and update local state. Returns True on success."""
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{LICENSE_SERVER_URL}/api/license/validate",
                json={
                    "license_key": LICENSE_KEY,
                    "instance_id": _machine_fingerprint(),
                },
            )
        resp.raise_for_status()
        body = resp.json()

        valid = body.get("valid", False)
        message = body.get("message", "")
        _state.update(valid, message, body.get("expires_at"), body.get("max_users"))

        if valid:
            _save_cache()
            logger.info("License validation succeeded: %s", message)
        else:
            logger.warning("License validation failed: %s", message)

        return valid

    except Exception as exc:
        _state.last_attempt = time.time()
        logger.warning("License server unreachable: %s", exc)
        return False


def _background_loop():
    """Re-validate the license every 12 hours."""
    while True:
        time.sleep(12 * 3600)
        try:
            _validate_once()
        except Exception:
            logger.exception("License re-validation error")


# ── Public API ────────────────────────────────────────────────────────────────

def is_license_required() -> bool:
    """Return True when the app is running in on-prem licensed mode."""
    return bool(LICENSE_KEY and LICENSE_SERVER_URL)


def get_license_state() -> LicenseState:
    """Return the global license state (for max_users enforcement etc.)."""
    return _state


def validate_license_on_startup():
    """Called during app startup.  Validates and starts the background thread.

    If the license server is unreachable on first boot and no cache exists,
    the app will still start but all API requests will return 503.
    """
    if not is_license_required():
        return

    logger.info("License mode enabled — validating against %s", LICENSE_SERVER_URL)
    _load_cache()
    _validate_once()

    # Start background re-validation thread
    thread = threading.Thread(target=_background_loop, daemon=True, name="license-check")
    thread.start()
    logger.info("License background check thread started")


class LicenseMiddleware(BaseHTTPMiddleware):
    """Reject API requests when the license is invalid and the grace period has expired."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not is_license_required():
            return await call_next(request)

        path = request.url.path

        # Always allow health checks and static assets
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)

        if _state.should_allow_requests():
            return await call_next(request)

        brand = get_brand()
        logger.error("License invalid and grace period expired — blocking request to %s", path)
        return JSONResponse(
            status_code=503,
            content={
                "detail": f"License validation failed: {_state.message}. "
                          f"Contact {brand.support_email} to renew your license.",
            },
        )


def get_license_status() -> dict:
    """Return current license status (for health/debug endpoints)."""
    return {
        "required": is_license_required(),
        "valid": _state.valid,
        "message": _state.message,
        "expiresAt": _state.expires_at,
        "maxUsers": _state.max_users,
        "lastCheck": _state.last_check,
        "withinGracePeriod": _state.is_within_grace_period(),
    }
