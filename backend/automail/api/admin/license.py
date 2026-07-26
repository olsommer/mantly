"""License management and validation router.

SaaS-side endpoints:
    POST /api/license/validate     — unauthenticated; called by on-prem instances
    GET  /api/admin/licenses       — list all licenses (platform admin only)
    POST /api/admin/licenses       — create a new license (platform admin only)
    DELETE /api/admin/licenses/{id} — revoke/delete a license (platform admin only)

The on-prem instance sends its LICENSE_KEY + a machine fingerprint.
On first call the fingerprint is bound to the license record so the same
key cannot be reused on a different machine.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from automail.api.admin.deps import PlatformAdminDep
from automail.billing.license_store import (
    find_license_by_key,
    generate_license_key,
    license_key_prefix,
    license_key_prefix_from_record,
    license_key_storage_fields,
    masked_license_key,
)
from automail.core.auth import TokenPayload
from automail.core.rate_limit import limiter
from automail.db.pocketbase.client import _list_all, _patch, _post, generate_id

logger = logging.getLogger(__name__)

IS_SAAS: bool = os.getenv("IS_SAAS", "false").lower() == "true"

# ── Public router (no auth — called by on-prem instances) ────────────────────

public_router = APIRouter(prefix="/api/license")


class ValidateRequest(BaseModel):
    license_key: str = Field(max_length=256)
    instance_id: str = Field(max_length=256)


class ValidateResponse(BaseModel):
    valid: bool
    expires_at: Optional[str] = None
    max_users: Optional[int] = None
    message: str = ""


@public_router.post("/validate", response_model=ValidateResponse)
@limiter.limit("60/minute")
async def validate_license(body: ValidateRequest, request: Request):
    """Validate an on-prem license key.

    Called periodically by on-prem instances.  On first call the
    instance_id is bound to the license; subsequent calls must match.
    """
    if not IS_SAAS:
        raise HTTPException(status_code=404, detail="Not found")

    key = body.license_key.strip()
    instance_id = body.instance_id.strip()

    if not key or not instance_id:
        return ValidateResponse(valid=False, message="Missing license key or instance ID")

    rec = find_license_by_key(key)
    if not rec:
        logger.warning("License validation failed: unknown key")
        return ValidateResponse(valid=False, message="Invalid license key")

    # Check if license is active
    if not rec.get("is_active", True):
        return ValidateResponse(valid=False, message="License has been revoked")

    # Check expiry
    expires_at_str = rec.get("expires_at") or ""
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if expires_at < datetime.now(timezone.utc):
                return ValidateResponse(
                    valid=False,
                    expires_at=expires_at_str,
                    message="License has expired",
                )
        except ValueError:
            pass

    # Bind instance on first validation
    stored_instance = (rec.get("instance_id") or "").strip()
    if not stored_instance:
        _patch(
            f"/api/collections/licenses/records/{rec['id']}",
            {"instance_id": instance_id},
        )
        logger.info("License record %s bound to instance %s", rec["id"], instance_id[:12])
    elif stored_instance != instance_id:
        logger.warning(
            "License record %s instance mismatch: stored=%s got=%s",
            rec["id"],
            stored_instance[:12],
            instance_id[:12],
        )
        return ValidateResponse(
            valid=False,
            message="License is bound to a different instance",
        )

    max_users = rec.get("max_users")
    return ValidateResponse(
        valid=True,
        expires_at=expires_at_str or None,
        max_users=int(max_users) if max_users else None,
        message="License is valid",
    )


# ── Admin router (requires platform-admin JWT) ───────────────────────────────

admin_router = APIRouter()


class CreateLicenseRequest(BaseModel):
    tenant_name: str
    max_users: Optional[int] = None
    expires_at: Optional[str] = None


def _audit_actor(auth: TokenPayload) -> str:
    return auth.user_id or "local-no-auth"


@admin_router.get("/licenses")
async def list_licenses(auth: PlatformAdminDep) -> list[dict]:
    """List all licenses (SaaS platform administrators only)."""
    if not IS_SAAS:
        raise HTTPException(status_code=404, detail="Not found")
    records = _list_all("licenses", sort="-created")
    response = [
        {
            "id": r["id"],
            "key": masked_license_key(r),
            "keyPrefix": license_key_prefix_from_record(r),
            "tenantName": r.get("tenant_name", ""),
            "maxUsers": r.get("max_users"),
            "expiresAt": r.get("expires_at"),
            "isActive": r.get("is_active", True),
            "instanceId": r.get("instance_id", ""),
            "subscriptionId": r.get("subscription_id", ""),
            "created": r.get("created", ""),
        }
        for r in records
    ]
    logger.info(
        "License inventory listed by platform admin %s (records=%d)",
        _audit_actor(auth),
        len(response),
    )
    return response


@admin_router.post("/licenses")
async def create_license(
    body: CreateLicenseRequest,
    response: Response,
    auth: PlatformAdminDep,
) -> dict:
    """Create a new on-prem license (SaaS platform administrators only)."""
    if not IS_SAAS:
        raise HTTPException(status_code=404, detail="Not found")

    key = generate_license_key()
    tenant_name = body.tenant_name.strip()
    data: dict[str, object] = {
        "id": generate_id(),
        **license_key_storage_fields(key),
        "tenant_name": tenant_name,
        "is_active": True,
    }
    if body.max_users is not None:
        data["max_users"] = body.max_users
    if body.expires_at:
        data["expires_at"] = body.expires_at

    try:
        rec = _post("/api/collections/licenses/records", data)
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Failed to create license record (status=%s)",
            exc.response.status_code,
        )
        raise HTTPException(status_code=500, detail="Failed to create license") from exc

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    logger.info(
        "License record %s created by platform admin %s",
        rec["id"],
        _audit_actor(auth),
    )
    return {
        "id": rec["id"],
        "key": key,
        "keyPrefix": license_key_prefix(key),
        "tenantName": tenant_name,
    }


@admin_router.delete("/licenses/{license_id}")
async def revoke_license(license_id: str, auth: PlatformAdminDep) -> dict:
    """Revoke (deactivate) a license."""
    if not IS_SAAS:
        raise HTTPException(status_code=404, detail="Not found")

    try:
        _patch(
            f"/api/collections/licenses/records/{license_id}",
            {"is_active": False},
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="License not found") from exc
        raise HTTPException(status_code=500, detail="Failed to revoke license") from exc

    logger.info(
        "License record %s revoked by platform admin %s",
        license_id,
        _audit_actor(auth),
    )
    return {"status": "revoked"}


@admin_router.post("/licenses/{license_id}/reset-instance")
async def reset_license_instance(license_id: str, auth: PlatformAdminDep) -> dict:
    """Clear the instance binding so the license can be used on a new machine."""
    if not IS_SAAS:
        raise HTTPException(status_code=404, detail="Not found")

    try:
        _patch(
            f"/api/collections/licenses/records/{license_id}",
            {"instance_id": ""},
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="License not found") from exc
        raise HTTPException(status_code=500, detail="Failed to reset instance") from exc

    logger.info(
        "License record %s instance binding cleared by platform admin %s",
        license_id,
        _audit_actor(auth),
    )
    return {"status": "reset"}
