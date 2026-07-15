from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

from automail.addon.gmail.events import GmailAddonEvent
from automail.core import auth as app_auth
from automail.core.auth import TokenPayload
from automail.core.capabilities import normalize_account_type
from automail.db.pocketbase.client import get_is_root, get_tenant_account_type, get_user_by_email

logger = logging.getLogger(__name__)

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


@dataclass(slots=True)
class GmailAddonIdentity:
    email: str
    tenant_id: str | None
    payload: TokenPayload | None


class GmailAddonAuthError(Exception):
    def __init__(self, code: str, message: str, *, email: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.email = email


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _verify_google_jwt(token: str, *, audience: str) -> dict[str, Any]:
    jwks = PyJWKClient(GOOGLE_CERTS_URL)
    signing_key = jwks.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        issuer=GOOGLE_ISSUERS,
    )


def _decode_user_token(token: str) -> dict[str, Any]:
    if not token:
        return {}

    audience = os.getenv("GOOGLE_ADDON_OAUTH_CLIENT_ID", "").strip()
    if audience and _env_bool("GOOGLE_ADDON_VERIFY_USER_TOKEN", True):
        try:
            return _verify_google_jwt(token, audience=audience)
        except Exception:
            logger.warning("Failed to verify Gmail add-on user token", exc_info=True)
            return {}

    if app_auth.REQUIRE_AUTH:
        logger.error("GOOGLE_ADDON_OAUTH_CLIENT_ID is required when authentication is enabled")
        return {}

    # Local development fallback only.
    try:
        return jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
    except Exception:
        return {}


def user_email_from_event(event: GmailAddonEvent) -> str:
    claims = _decode_user_token(event.user_id_token)
    email = str(claims.get("email") or "").strip().lower()
    return email if email and claims.get("email_verified", True) else ""


def resolve_addon_identity(event: GmailAddonEvent) -> GmailAddonIdentity:
    email = user_email_from_event(event)
    if not app_auth.REQUIRE_AUTH:
        return GmailAddonIdentity(email=email or "gmail-user", tenant_id=None, payload=None)

    if not email:
        raise GmailAddonAuthError("google_identity_missing", "Google user identity missing")

    user = get_user_by_email(email)
    if not user:
        raise GmailAddonAuthError(
            "mantly_user_missing",
            "No Mantly user exists for this Google account",
            email=email,
        )

    tenant_id = str(user.get("tenant") or "")
    if not tenant_id:
        raise GmailAddonAuthError("mantly_tenant_missing", "Mantly user has no tenant", email=email)

    tenant_account_type = normalize_account_type(get_tenant_account_type(tenant_id))
    payload = TokenPayload(
        user_id=str(user.get("id") or ""),
        email=email,
        tenant_id=tenant_id,
        is_root=get_is_root(user),
        is_platform_admin=bool(user.get("is_platform_admin", False)),
        tenant_account_type=tenant_account_type,
    )
    return GmailAddonIdentity(email=email, tenant_id=tenant_id, payload=payload)


def verify_google_request(request: Request, *, audience: str) -> None:
    if not _env_bool("GOOGLE_ADDON_VERIFY_REQUESTS", app_auth.REQUIRE_AUTH):
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Google system token")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        claims = _verify_google_jwt(token, audience=audience)
    except Exception:
        logger.warning("Failed to verify Gmail add-on system token", exc_info=True)
        raise HTTPException(status_code=401, detail="Invalid Google system token")

    expected_email = os.getenv("GOOGLE_ADDON_SERVICE_ACCOUNT_EMAIL", "").strip()
    if expected_email and claims.get("email") != expected_email:
        raise HTTPException(status_code=403, detail="Unexpected Google service account")
