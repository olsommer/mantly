"""On-prem first-tenant bootstrap."""

import logging
import os

import httpx

from automail.db.pocketbase.bootstrap_common import (
    PB_ADMIN_EMAIL,
    PB_ADMIN_PASSWORD,
    PB_URL,
    _authenticate_superuser,
)

logger = logging.getLogger(__name__)


def bootstrap_onprem_tenant(
    *,
    pb_url: str | None = None,
    pb_admin_email: str | None = None,
    pb_admin_password: str | None = None,
) -> bool:
    """Create the initial tenant, root user and default project for on-prem.

    Only runs when ALL of the following are true:
    - ``IS_SAAS`` is false
    - ``REQUIRE_AUTH`` is true
    - The ``tenants`` collection has **zero** records
    - ``SETUP_ADMIN_EMAIL`` is set in the environment

    The root user's password comes from ``SETUP_ADMIN_PASSWORD`` (defaults to
    ``changeme``).  The user is created with ``must_change_password=True`` so
    they are forced to set a real password on first login.

    Returns True if a tenant was created; False otherwise (already exists or
    not applicable).
    """
    is_saas = os.getenv("IS_SAAS", "false").lower() == "true"
    require_auth = os.getenv("REQUIRE_AUTH", "false").lower() == "true"

    if is_saas or not require_auth:
        return False

    setup_email = os.getenv("SETUP_ADMIN_EMAIL", "").strip()
    if not setup_email:
        return False

    setup_password = os.getenv("SETUP_ADMIN_PASSWORD", "changeme")
    company_name = os.getenv("COMPANY_NAME", "My Organisation")

    resolved_pb_url = (pb_url or PB_URL).rstrip("/")
    resolved_email = (pb_admin_email if pb_admin_email is not None else PB_ADMIN_EMAIL).strip()
    resolved_password = pb_admin_password if pb_admin_password is not None else PB_ADMIN_PASSWORD

    if not resolved_email or not resolved_password:
        return False

    try:
        with httpx.Client(timeout=10.0) as client:
            token = _authenticate_superuser(client, resolved_pb_url, resolved_email, resolved_password)
            headers = {"Authorization": f"Bearer {token}"}

            # Check if any tenants already exist
            resp = client.get(
                f"{resolved_pb_url}/api/collections/tenants/records",
                headers=headers,
                params={"perPage": 1},
            )
            resp.raise_for_status()
            if resp.json().get("totalItems", 0) > 0:
                logger.info("On-prem bootstrap: tenants already exist — skipping")
                return False

            # ── Create tenant ─────────────────────────────────────────────
            from automail.db.pocketbase.client import generate_id

            tenant_id = generate_id()
            client.post(
                f"{resolved_pb_url}/api/collections/tenants/records",
                headers=headers,
                json={"id": tenant_id, "name": company_name, "account_type": "normal"},
            ).raise_for_status()
            logger.info("On-prem bootstrap: created tenant %s (%s)", tenant_id, company_name)

            # ── Create root user ──────────────────────────────────────────
            user_id = generate_id()
            client.post(
                f"{resolved_pb_url}/api/collections/users/records",
                headers=headers,
                json={
                    "id": user_id,
                    "email": setup_email,
                    "password": setup_password,
                    "passwordConfirm": setup_password,
                    "tenant": tenant_id,
                    "is_root": True,
                    "must_change_password": True,
                    "password_login_enabled": True,
                    "verified": True,
                },
            ).raise_for_status()
            logger.info("On-prem bootstrap: created root user %s", setup_email)

            # ── Create default project ────────────────────────────────────
            project_id = generate_id()
            client.post(
                f"{resolved_pb_url}/api/collections/projects/records",
                headers=headers,
                json={
                    "id": project_id,
                    "name": "Default",
                    "description": "",
                    "tenant": tenant_id,
                },
            ).raise_for_status()
            logger.info("On-prem bootstrap: created default project %s", project_id)

            # ── Create project membership ─────────────────────────────────
            client.post(
                f"{resolved_pb_url}/api/collections/project_members/records",
                headers=headers,
                json={
                    "id": generate_id(),
                    "user": user_id,
                    "project": project_id,
                    "role": "admin",
                },
            ).raise_for_status()

            logger.info(
                "On-prem bootstrap complete — log in with: %s (password must be changed on first login)",
                setup_email,
            )
            return True

    except Exception as exc:
        logger.error("On-prem bootstrap failed: %s", exc)
        return False
