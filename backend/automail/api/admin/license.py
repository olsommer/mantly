"""License management and validation router.

SaaS-side endpoints:
    POST /api/license/validate     — unauthenticated; called by on-prem instances
    GET  /api/admin/licenses       — list all licenses (admin only)
    POST /api/admin/licenses       — create a new license (admin only)
    DELETE /api/admin/licenses/{id} — revoke/delete a license (admin only)

The on-prem instance sends its LICENSE_KEY + a machine fingerprint.
On first call the fingerprint is bound to the license record so the same
key cannot be reused on a different machine.
"""

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from automail.db.pocketbase.client import _escape_pb, _first, _list_all, _patch, _post, generate_id

logger = logging.getLogger(__name__)

IS_SAAS: bool = os.getenv("IS_SAAS", "false").lower() == "true"

# ── Public router (no auth — called by on-prem instances) ────────────────────

public_router = APIRouter(prefix="/api/license")


class ValidateRequest(BaseModel):
    license_key: str
    instance_id: str


class ValidateResponse(BaseModel):
    valid: bool
    expires_at: Optional[str] = None
    max_users: Optional[int] = None
    message: str = ""


@public_router.post("/validate", response_model=ValidateResponse)
async def validate_license(body: ValidateRequest):
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

    rec = _first("licenses", f"key='{_escape_pb(key)}'")
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
        logger.info("License %s bound to instance %s", key[:8], instance_id[:12])
    elif stored_instance != instance_id:
        logger.warning(
            "License %s instance mismatch: stored=%s got=%s",
            key[:8], stored_instance[:12], instance_id[:12],
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


# ── Admin router (requires admin JWT) ────────────────────────────────────────

admin_router = APIRouter()


class CreateLicenseRequest(BaseModel):
    tenant_name: str
    max_users: Optional[int] = None
    expires_at: Optional[str] = None


@admin_router.get("/licenses")
async def list_licenses() -> list[dict]:
    """List all licenses (SaaS admin only)."""
    if not IS_SAAS:
        raise HTTPException(status_code=404, detail="Not found")
    records = _list_all("licenses", sort="-created")
    return [
        {
            "id": r["id"],
            "key": r.get("key", ""),
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


@admin_router.post("/licenses")
async def create_license(body: CreateLicenseRequest) -> dict:
    """Create a new on-prem license (SaaS admin only)."""
    if not IS_SAAS:
        raise HTTPException(status_code=404, detail="Not found")

    key = secrets.token_hex(20)  # 40-char hex key
    data: dict[str, object] = {
        "id": generate_id(),
        "key": key,
        "tenant_name": body.tenant_name.strip(),
        "is_active": True,
    }
    if body.max_users is not None:
        data["max_users"] = body.max_users
    if body.expires_at:
        data["expires_at"] = body.expires_at

    try:
        rec = _post("/api/collections/licenses/records", data)
    except httpx.HTTPStatusError as exc:
        logger.error("Failed to create license: %s", exc.response.text)
        raise HTTPException(status_code=500, detail="Failed to create license")

    return {"id": rec["id"], "key": key, "tenantName": body.tenant_name}


@admin_router.delete("/licenses/{license_id}")
async def revoke_license(license_id: str) -> dict:
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
            raise HTTPException(status_code=404, detail="License not found")
        raise HTTPException(status_code=500, detail="Failed to revoke license")

    return {"status": "revoked"}


@admin_router.post("/licenses/{license_id}/reset-instance")
async def reset_license_instance(license_id: str) -> dict:
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
            raise HTTPException(status_code=404, detail="License not found")
        raise HTTPException(status_code=500, detail="Failed to reset instance")

    logger.info("License %s instance binding cleared", license_id)
    return {"status": "reset"}
