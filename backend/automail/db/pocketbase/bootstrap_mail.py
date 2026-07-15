"""PocketBase mail and public URL settings bootstrap."""

import logging
import os
import time
from typing import Any

import httpx

from automail.db.pocketbase.bootstrap_common import (
    PB_ADMIN_EMAIL,
    PB_ADMIN_PASSWORD,
    PB_URL,
    _authenticate_superuser,
)

logger = logging.getLogger(__name__)
_TRANSIENT_PB_STATUSES = {400, 403}


def _clean_env_url(value: str) -> str:
    return value.strip().strip("'\"").rstrip("/")


def _public_pb_url() -> str:
    explicit = _clean_env_url(os.getenv("PB_PUBLIC_URL", ""))
    if explicit:
        return explicit
    vite_pb = _clean_env_url(os.getenv("VITE_PB_URL", ""))
    if vite_pb:
        return vite_pb
    public_url = _clean_env_url(os.getenv("PUBLIC_URL", ""))
    if public_url:
        return public_url if public_url.endswith("/pb") else f"{public_url}/pb"
    return ""


def _request_settings_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, Any] | None = None,
) -> httpx.Response:
    last_response: httpx.Response | None = None
    for attempt in range(3):
        response = client.request(method, url, headers=headers, json=json)
        last_response = response
        if response.status_code not in _TRANSIENT_PB_STATUSES or attempt == 2:
            response.raise_for_status()
            return response
        time.sleep(0.05 * (attempt + 1))
    assert last_response is not None
    last_response.raise_for_status()
    return last_response


def sync_pocketbase_mail_settings(
    pb_url: str | None = None,
    pb_admin_email: str | None = None,
    pb_admin_password: str | None = None,
) -> bool:
    """Sync PocketBase app URL and SMTP settings from environment variables."""
    resolved_pb_url = (pb_url or PB_URL).rstrip("/")
    resolved_email = (pb_admin_email if pb_admin_email is not None else PB_ADMIN_EMAIL).strip()
    resolved_password = pb_admin_password if pb_admin_password is not None else PB_ADMIN_PASSWORD
    if not resolved_email or not resolved_password:
        logger.info("PocketBase mail settings sync skipped: missing superuser credentials")
        return False

    app_url = _public_pb_url()
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587") or "587")
    if not app_url and not smtp_host:
        return False

    with httpx.Client(timeout=15.0) as client:
        token = _authenticate_superuser(client, resolved_pb_url, resolved_email, resolved_password)
        settings_resp = _request_settings_with_retry(
            client,
            "GET",
            f"{resolved_pb_url}/api/settings",
            headers={"Authorization": f"Bearer {token}"},
        )
        current = settings_resp.json()

        payload: dict[str, Any] = {}
        if app_url:
            meta = dict(current.get("meta") or {})
            meta.update({
                "appName": os.getenv("APP_BRAND_NAME", "Mantly").strip() or "Mantly",
                "appURL": app_url,
                "senderName": os.getenv("APP_BRAND_NAME", "Mantly").strip() or "Mantly",
            })
            if smtp_from:
                meta["senderAddress"] = smtp_from
            payload["meta"] = meta

        if smtp_host:
            smtp = dict(current.get("smtp") or {})
            smtp.update({
                "enabled": True,
                "host": smtp_host,
                "port": smtp_port,
                "username": smtp_user,
                "authMethod": smtp.get("authMethod") or "PLAIN",
                "tls": smtp.get("tls") or False,
            })
            if smtp_password:
                smtp["password"] = smtp_password
            payload["smtp"] = smtp

        if not payload:
            return False

        try:
            _request_settings_with_retry(
                client,
                "PATCH",
                f"{resolved_pb_url}/api/settings",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "PocketBase mail settings sync failed — continuing: %s",
                exc.response.text,
            )
            return False
    logger.info("PocketBase mail settings synced: app_url=%s smtp=%s", app_url or "unchanged", "enabled" if smtp_host else "unchanged")
    return True
