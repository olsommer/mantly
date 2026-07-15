"""Low-level PocketBase HTTP client helpers."""

import base64
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, List, Optional

import httpx

logger = logging.getLogger(__name__)

PB_URL = os.getenv("PB_URL", "http://localhost:8090")
_PB_ADMIN_EMAIL = os.getenv("PB_ADMIN_EMAIL", "")
_PB_ADMIN_PASSWORD = os.getenv("PB_ADMIN_PASSWORD", "")

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
_ID_LENGTH = 15
_TRANSIENT_PB_STATUSES = {400, 403}
_PB_RETRY_ATTEMPTS = 3

def generate_id() -> str:
    """Return a 15-char lowercase alphanumeric nanoid for PocketBase records."""
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(_ID_LENGTH))


# ── Superuser token cache ──────────────────────────────────────────────────────

_token_lock = threading.Lock()
_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


def _jwt_exp(token: str) -> float:
    """Decode the `exp` claim from a JWT without an external library."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return 0.0
        # Add padding so base64 decodes cleanly
        padding = "=" * (-len(parts[1]) % 4)
        payload = base64.urlsafe_b64decode(parts[1] + padding)
        return float(json.loads(payload).get("exp", 0))
    except Exception:
        return 0.0


def _pb_token() -> str:
    """Return a valid superuser Bearer token, refreshing when near expiry."""
    with _token_lock:
        # Refresh 60 s before real expiry to avoid race conditions
        if _token_cache["expires_at"] - time.time() < 60:
            _refresh_superuser_token()
        return _token_cache["token"]


def _refresh_superuser_token() -> None:
    """Re-authenticate as PocketBase superuser and update the cache."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{PB_URL}/api/collections/_superusers/auth-with-password",
            json={"identity": _PB_ADMIN_EMAIL, "password": _PB_ADMIN_PASSWORD},
        )
    resp.raise_for_status()
    token = resp.json()["token"]
    exp = _jwt_exp(token)
    _token_cache["token"] = token
    # Fall back to 12-hour refresh window if exp is missing
    _token_cache["expires_at"] = exp if exp > 0 else time.time() + 12 * 3600
    logger.debug("PocketBase superuser token refreshed")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_pb_token()}"}


# ── Low-level HTTP helpers ─────────────────────────────────────────────────────

def _request_json(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_data: dict | None = None,
    data: dict | None = None,
    files: dict | None = None,
    timeout: float = 15.0,
) -> dict:
    """Request PocketBase with a short retry for transient local PB failures."""
    last_response: httpx.Response | None = None
    for attempt in range(_PB_RETRY_ATTEMPTS):
        with httpx.Client(timeout=timeout) as client:
            resp = client.request(
                method,
                f"{PB_URL}{path}",
                headers=_headers(),
                params=params,
                json=json_data,
                data=data,
                files=files,
            )
        last_response = resp
        if resp.status_code not in _TRANSIENT_PB_STATUSES or attempt == _PB_RETRY_ATTEMPTS - 1:
            resp.raise_for_status()
            return resp.json()
        time.sleep(0.05 * (attempt + 1))
    assert last_response is not None
    last_response.raise_for_status()
    return last_response.json()

def _get(path: str, params: dict | None = None) -> dict:
    return _request_json("GET", path, params=params)


def _post(path: str, data: dict) -> dict:
    return _request_json("POST", path, json_data=data)


def _post_multipart(path: str, data: dict, files: dict) -> dict:
    return _request_json("POST", path, data=data, files=files, timeout=30.0)


def _patch(path: str, data: dict) -> dict:
    return _request_json("PATCH", path, json_data=data)


def _patch_multipart(path: str, data: dict, files: dict) -> dict:
    return _request_json("PATCH", path, data=data, files=files, timeout=30.0)


def _delete(path: str) -> bool:
    for attempt in range(_PB_RETRY_ATTEMPTS):
        with httpx.Client(timeout=15.0) as client:
            resp = client.delete(f"{PB_URL}{path}", headers=_headers())
        if resp.status_code not in _TRANSIENT_PB_STATUSES or attempt == _PB_RETRY_ATTEMPTS - 1:
            return resp.status_code == 204
        time.sleep(0.05 * (attempt + 1))
    return False


def _get_binary(path: str) -> tuple[bytes, str]:
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(f"{PB_URL}{path}", headers=_headers())
    resp.raise_for_status()
    return resp.content, resp.headers.get("content-type", "application/octet-stream")


def _list_all(
    collection: str,
    filter_str: str = "",
    sort: str = "-created",
    per_page: int = 200,
) -> List[dict]:
    """Fetch all records from a collection, handling PocketBase pagination."""
    page = 1
    records: List[dict] = []
    while True:
        params: dict[str, Any] = {"page": page, "perPage": per_page, "sort": sort}
        if filter_str:
            params["filter"] = filter_str
        data = _get(f"/api/collections/{collection}/records", params)
        batch: List[dict] = data.get("items", [])
        records.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return records


def _first(collection: str, filter_str: str) -> Optional[dict]:
    """Return the first matching record or None."""
    params: dict[str, Any] = {"filter": filter_str, "perPage": 1, "sort": "-created"}
    try:
        data = _get(f"/api/collections/{collection}/records", params)
        items: List[dict] = data.get("items", [])
        return items[0] if items else None
    except httpx.HTTPStatusError:
        return None


def _escape_pb(value: str) -> str:
    """Escape single quotes for PocketBase filter strings."""
    return value.replace("'", "\\'")
