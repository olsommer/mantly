"""Shared PocketBase bootstrap configuration and admin helpers."""

import os
from typing import Any

import httpx

PB_URL = os.getenv("PB_URL", "http://localhost:8090")
PB_ADMIN_EMAIL = os.getenv("PB_ADMIN_EMAIL", "")
PB_ADMIN_PASSWORD = os.getenv("PB_ADMIN_PASSWORD", "")

_USERS_COLLECTION_ID = "_pb_users_auth_"


def validate_pb_bootstrap_env(
    require_auth: bool,
    pb_admin_email: str | None = None,
    pb_admin_password: str | None = None,
) -> None:
    """Ensure auth-enabled deployments have the PB admin credentials required."""
    if not require_auth:
        return

    email = (pb_admin_email if pb_admin_email is not None else PB_ADMIN_EMAIL).strip()
    password = pb_admin_password if pb_admin_password is not None else PB_ADMIN_PASSWORD
    if email and password:
        return

    raise RuntimeError(
        "PB_ADMIN_EMAIL and PB_ADMIN_PASSWORD must be set when REQUIRE_AUTH=true. "
        "The backend needs PocketBase superuser access for auth-enabled user management."
    )


def _authenticate_superuser(
    client: httpx.Client,
    pb_url: str,
    pb_admin_email: str,
    pb_admin_password: str,
) -> str:
    response = client.post(
        f"{pb_url}/api/collections/_superusers/auth-with-password",
        json={"identity": pb_admin_email, "password": pb_admin_password},
    )
    response.raise_for_status()
    return response.json()["token"]


def _get_collection(
    client: httpx.Client,
    pb_url: str,
    token: str,
    name_or_id: str,
) -> dict[str, Any] | None:
    response = client.get(
        f"{pb_url}/api/collections/{name_or_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()
