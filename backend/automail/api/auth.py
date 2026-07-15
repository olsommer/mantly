"""Authentication endpoints for the PocketBase-backed auth flow.

Endpoints:

    POST /api/auth/exchange        — validate a PocketBase user JWT and issue a
                                     FastAPI JWT in return (called after PB login)

    POST /api/auth/signup          — self-service tenant signup (SaaS only);
                                     creates a tenant + first admin user

    POST /api/auth/verify-email    — confirm email verification (SaaS only)

    POST /api/auth/change-password — change password (requires valid JWT);
                                     clears must_change_password flag

PocketBase handles the following directly in the browser:
  - Login                 POST PB_URL/api/collections/users/auth-with-password
  - Password reset        POST PB_URL/api/collections/users/request-password-reset
"""
import hmac
import logging
import os
import re
import secrets
from datetime import datetime, timedelta

import httpx
import jwt as pyjwt
from fastapi import APIRouter, Body, HTTPException, Request

from automail.api.auth_models import (
    AuthResponse,
    LoginCodeRequest,
    LoginMethodResponse,
    PasswordLoginRequest,
    SignupRequest,
    SignupResponse,
    VerifyLoginCodeRequest,
)
from automail.api.auth_utils import (
    EMAIL_RE as _EMAIL_RE,
)
from automail.api.auth_utils import (
    LOGIN_CODE_MAX_ATTEMPTS,
    LOGIN_CODE_TTL_MINUTES,
    _create_verification_token,
    _hash_login_code,
    _now_utc,
    saas_signup_enabled,
)
from automail.core.auth import (
    JWT_ALGORITHM,
    JWT_SECRET,
    REQUIRE_AUTH,
    create_token,
    decode_token,
)
from automail.core.capabilities import get_account_capabilities, normalize_account_type
from automail.core.language import normalize_language
from automail.db.pocketbase.client import (
    PB_URL,
    add_project_member,
    check_email_exists,
    create_onprem_signup_user,
    create_project,
    create_signup_user,
    create_tenant,
    get_is_root,
    get_single_tenant,
    get_tenant_account_type,
    get_tenant_name,
    get_tenant_settings,
    get_user_by_email,
    list_tenant_projects,
    patch_user_record,
    set_user_default_project,
    set_user_verified,
    update_user_password,
    validate_pb_token,
)

logger = logging.getLogger(__name__)

IS_SAAS: bool = os.getenv("IS_SAAS", "false").lower() == "true"

router = APIRouter()




# ── GET /api/auth/config (public — no auth required) ─────────────────────────

@router.get("/config")
async def auth_config():
    """Return public auth configuration for the login page.

    No authentication required.  The frontend fetches this before the user
    logs in so it knows whether to show a "Create account" link.
    """
    allow_signups = False
    if not IS_SAAS:
        # On-prem: check the single tenant's allow_signups setting
        try:
            tenant = get_single_tenant()
            if tenant:
                allow_signups = bool(get_tenant_settings(tenant["id"]).get("allowSignups", False))
        except Exception:
            logger.debug("Could not read on-prem tenant settings for auth config", exc_info=True)

    return {
        "isSaas": IS_SAAS,
        "allowSignups": (saas_signup_enabled() if IS_SAAS else allow_signups),
    }
















def _issue_auth_response(record: dict) -> AuthResponse:
    user_id: str = record.get("id", "")
    email: str = record.get("email", "")
    tenant_id: str = record.get("tenant", "") or ""
    is_root: bool = get_is_root(record)
    is_platform_admin: bool = bool(record.get("is_platform_admin", False))
    must_change_password: bool = bool(record.get("must_change_password", False))

    if not email:
        raise HTTPException(status_code=400, detail="User record has no email")
    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="User has no associated tenant — contact your administrator",
        )
    if IS_SAAS and not record.get("verified", False):
        raise HTTPException(
            status_code=403,
            detail="Please verify your email address before signing in. Check your inbox for the verification link.",
        )

    tenant_account_type = normalize_account_type(get_tenant_account_type(tenant_id))
    tenant_name = get_tenant_name(tenant_id)
    token = create_token(
        user_id,
        email,
        tenant_id,
        is_root,
        tenant_name=tenant_name,
        is_platform_admin=is_platform_admin,
        tenant_account_type=tenant_account_type,
    )

    return AuthResponse(
        token=token,
        email=email,
        language=normalize_language(record.get("language")),
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        is_root=is_root,
        is_platform_admin=is_platform_admin,
        tenant_account_type=tenant_account_type,
        capabilities=get_account_capabilities(
            tenant_id,
            is_platform_admin=is_platform_admin,
        ),
        must_change_password=must_change_password,
    )


@router.post("/login-method", response_model=LoginMethodResponse)
async def login_method(body: LoginCodeRequest):
    """Return the login method for an email address.

    Unknown users fall back to code login so this endpoint does not expose a
    generic account lookup surface. Password is returned only for accounts where
    admins explicitly enabled password login.
    """
    if not REQUIRE_AUTH:
        raise HTTPException(status_code=400, detail="Auth is not enabled")

    email = body.email.strip().lower()
    user = get_user_by_email(email) if _EMAIL_RE.match(email) else None
    if user and user.get("password_login_enabled", False):
        return LoginMethodResponse(method="password")
    return LoginMethodResponse(method="code")


@router.post("/request-login-code")
async def request_login_code(body: LoginCodeRequest):
    """Send a short login code to the user's email address."""
    if not REQUIRE_AUTH:
        raise HTTPException(status_code=400, detail="Auth is not enabled")

    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        return {"status": "ok"}

    user = get_user_by_email(email)
    if not user:
        logger.info("Login code requested for unknown email: %s", email)
        return {"status": "ok"}
    if IS_SAAS and not user.get("verified", False):
        logger.info("Login code requested for unverified email: %s", email)
        return {"status": "ok"}

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    expires = _now_utc() + timedelta(minutes=LOGIN_CODE_TTL_MINUTES)
    patch_user_record(user["id"], {
        "login_code_hash": _hash_login_code(email, code),
        "login_code_expires": expires.isoformat(),
        "login_code_attempts": 0,
    })

    try:
        from automail.integrations.email_sender import send_login_code_email
        send_login_code_email(email, code)
    except Exception:
        logger.warning("Failed to send login code to %s", email, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send login code")

    return {"status": "ok"}


@router.post("/verify-login-code", response_model=AuthResponse)
async def verify_login_code(body: VerifyLoginCodeRequest):
    """Verify an email login code and issue a FastAPI JWT."""
    if not REQUIRE_AUTH:
        raise HTTPException(status_code=400, detail="Auth is not enabled")

    email = body.email.strip().lower()
    code = re.sub(r"\D", "", body.code)
    user = get_user_by_email(email) if _EMAIL_RE.match(email) else None
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired login code")

    attempts = int(user.get("login_code_attempts") or 0)
    expires_raw = user.get("login_code_expires") or ""
    expected_hash = user.get("login_code_hash") or ""
    try:
        expires = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
    except ValueError:
        expires = _now_utc() - timedelta(seconds=1)

    valid = (
        expected_hash
        and attempts < LOGIN_CODE_MAX_ATTEMPTS
        and expires >= _now_utc()
        and hmac.compare_digest(expected_hash, _hash_login_code(email, code))
    )
    if not valid:
        patch_user_record(user["id"], {"login_code_attempts": attempts + 1})
        raise HTTPException(status_code=400, detail="Invalid or expired login code")

    patch_user_record(user["id"], {
        "login_code_hash": "",
        "login_code_expires": "",
        "login_code_attempts": 0,
    })
    logger.info("Login code verified: user=%s tenant=%s", email, user.get("tenant", ""))
    return _issue_auth_response(user)


@router.post("/password-login", response_model=AuthResponse)
async def password_login(body: PasswordLoginRequest):
    """Password login for explicitly enabled accounts only."""
    if not REQUIRE_AUTH:
        raise HTTPException(status_code=400, detail="Auth is not enabled")

    email = body.email.strip().lower()
    user = get_user_by_email(email) if _EMAIL_RE.match(email) else None
    if not user or not user.get("password_login_enabled", False):
        raise HTTPException(status_code=403, detail="Password login is not enabled for this account")

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{PB_URL}/api/collections/users/auth-with-password",
                json={"identity": email, "password": body.password},
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    except Exception:
        raise HTTPException(status_code=500, detail="Login failed")

    logger.info("Password login completed: user=%s tenant=%s", email, user.get("tenant", ""))
    return _issue_auth_response(user)


# ── POST /api/auth/exchange ───────────────────────────────────────────────────

@router.post("/exchange", response_model=AuthResponse)
async def exchange_token(pb_token: str = Body(..., embed=True)):
    """Exchange a PocketBase user JWT for a FastAPI JWT.

    The SPA authenticates against PocketBase (login / OAuth2 callback) and
    then calls this endpoint to get a FastAPI token it can use for all AI /
    data operations.

    Steps:
      1. Call PocketBase auth-refresh to validate the PB token and read user record
      2. Issue a FastAPI JWT with {user_id, email, tenant_id, is_root}
      3. Include must_change_password flag so the SPA can enforce a password change
    """
    try:
        pb_response = validate_pb_token(pb_token)
    except httpx.HTTPStatusError as exc:
        logger.warning("PocketBase token validation failed: %s", exc.response.status_code)
        raise HTTPException(status_code=401, detail="Invalid or expired PocketBase token")
    except Exception:
        logger.exception("Unexpected error validating PocketBase token")
        raise HTTPException(status_code=500, detail="Token validation failed")

    record = pb_response.get("record", {})
    logger.info("PB auth-refresh record keys: %s", list(record.keys()))
    logger.info("PB tenant field: %r  is_root: %r", record.get("tenant"), record.get("is_root"))

    user_id: str = record.get("id", "")
    email: str = record.get("email", "")
    tenant_id: str = record.get("tenant", "") or ""
    is_root: bool = get_is_root(record)
    is_platform_admin: bool = bool(record.get("is_platform_admin", False))
    must_change_password: bool = bool(record.get("must_change_password", False))

    if not email:
        raise HTTPException(status_code=400, detail="User record has no email")

    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="User has no associated tenant — contact your administrator",
        )

    # In SaaS mode, require email verification before issuing a token
    if IS_SAAS and not record.get("verified", False):
        raise HTTPException(
            status_code=403,
            detail="Please verify your email address before signing in. Check your inbox for the verification link.",
        )

    tenant_account_type = normalize_account_type(get_tenant_account_type(tenant_id))
    tenant_name = get_tenant_name(tenant_id)
    token = create_token(
        user_id,
        email,
        tenant_id,
        is_root,
        tenant_name=tenant_name,
        is_platform_admin=is_platform_admin,
        tenant_account_type=tenant_account_type,
    )
    logger.info("Token exchanged: user=%s tenant=%s root=%s", email, tenant_id, is_root)

    return AuthResponse(
        token=token,
        email=email,
        language=normalize_language(record.get("language")),
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        is_root=is_root,
        is_platform_admin=is_platform_admin,
        tenant_account_type=tenant_account_type,
        capabilities=get_account_capabilities(
            tenant_id,
            is_platform_admin=is_platform_admin,
        ),
        must_change_password=must_change_password,
    )


# ── POST /api/auth/signup ────────────────────────────────────────────────────









@router.post("/signup", response_model=SignupResponse, status_code=201)
async def signup(body: SignupRequest):
    """Self-service signup.

    SaaS mode: creates a new tenant, its first admin user, and a default
    project.  Sends a verification email — user must confirm before login.

    On-prem mode: creates a regular (non-root) user under the single
    existing tenant.  Auto-adds the user to all existing projects as a
    viewer.  No email verification required.
    """
    if IS_SAAS:
        if not saas_signup_enabled():
            raise HTTPException(status_code=404, detail="Not found")
    else:
        # On-prem: check that self-registration is enabled
        tenant = get_single_tenant()
        if not tenant:
            raise HTTPException(status_code=500, detail="No tenant configured")
        tenant_settings = get_tenant_settings(tenant["id"])
        if not tenant_settings.get("allowSignups"):
            raise HTTPException(status_code=404, detail="Not found")

    if not REQUIRE_AUTH:
        raise HTTPException(status_code=400, detail="Auth is not enabled")

    # ── Validation ────────────────────────────────────────────────────────────
    email = body.email.strip().lower()
    password = body.password
    company = ""

    if IS_SAAS:
        company = body.company_name.strip()
        if not company:
            raise HTTPException(status_code=400, detail="Company name is required")
        if len(company) > 200:
            raise HTTPException(status_code=400, detail="Company name is too long")

    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email address")

    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # ── Uniqueness check ──────────────────────────────────────────────────────
    if check_email_exists(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    if IS_SAAS:
        # ── SaaS: create tenant + root user ───────────────────────────────────
        try:
            tenant_id = create_tenant(company)
        except httpx.HTTPStatusError as exc:
            logger.error("Failed to create tenant: %s", exc.response.text)
            raise HTTPException(status_code=500, detail="Failed to create organisation")

        # Create Stripe customer for the new tenant (SaaS billing)
        try:
            from automail.billing.checkout import create_stripe_customer
            create_stripe_customer(tenant_id, email, company)
        except Exception:
            logger.warning("Failed to create Stripe customer for tenant %s — continuing", tenant_id, exc_info=True)

        try:
            user_record = create_signup_user(email, password, tenant_id)
        except httpx.HTTPStatusError as exc:
            logger.error("Failed to create signup user: %s", exc.response.text)
            raise HTTPException(status_code=500, detail="Failed to create user account")

        user_id = user_record["id"]

        # Auto-create default project
        try:
            from automail.pipeline.drafts import ensure_draft_exists
            project_rec = create_project("Default", "", tenant_id)
            ensure_draft_exists(project_rec["id"], tenant_id=tenant_id)
            set_user_default_project(user_id, project_rec["id"])
            logger.info("Default project %s created for tenant %s", project_rec["id"], tenant_id)
        except Exception:
            logger.warning("Failed to create default project for tenant %s — continuing", tenant_id, exc_info=True)

        # Send verification email
        verification_token = _create_verification_token(user_id, email)
        try:
            from automail.integrations.email_sender import send_verification_email
            send_verification_email(email, verification_token)
        except Exception:
            logger.warning("Failed to send verification email to %s — continuing", email, exc_info=True)

        logger.info("Signup completed: email=%s tenant=%s (verification pending)", email, tenant_id)
        return SignupResponse(
            verification_required=True,
            email=email,
            message="Account created. Please check your inbox to verify your email address.",
        )

    else:
        # ── On-prem: join existing tenant ─────────────────────────────────────
        # tenant was already fetched above when checking allowSignups
        tenant_id = tenant["id"]  # type: ignore[union-attr]

        try:
            user_record = create_onprem_signup_user(email, password, tenant_id)
        except httpx.HTTPStatusError as exc:
            logger.error("Failed to create on-prem signup user: %s", exc.response.text)
            raise HTTPException(status_code=500, detail="Failed to create user account")

        user_id = user_record["id"]

        # Auto-add to all existing projects as viewer
        try:
            projects = list_tenant_projects(tenant_id)
            for proj in projects:
                add_project_member(proj["id"], user_id, "viewer")
            if projects:
                set_user_default_project(user_id, projects[0]["id"])
            logger.info("On-prem signup: added user %s to %d project(s)", user_id, len(projects))
        except Exception:
            logger.warning("Failed to add on-prem user %s to projects — continuing", user_id, exc_info=True)

        logger.info("On-prem signup completed: email=%s tenant=%s (auto-verified)", email, tenant_id)
        return SignupResponse(
            verification_required=False,
            email=email,
            message="Account created. You can now sign in.",
        )


# ── POST /api/auth/verify-email ─────────────────────────────────────────────

@router.post("/verify-email")
async def verify_email(token: str = Body(..., embed=True)):
    """Confirm email verification using the token from the verification email.

    Validates the JWT, marks the user as verified in PocketBase, and returns
    a success message.  The user can then log in normally.
    """
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Verification link has expired. Please sign up again.")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid verification token.")

    if payload.get("purpose") != "email-verification":
        raise HTTPException(status_code=400, detail="Invalid token type.")

    user_id = payload.get("sub", "")
    email = payload.get("email", "")

    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid token payload.")

    try:
        set_user_verified(user_id)
    except httpx.HTTPStatusError as exc:
        logger.error("Failed to verify user %s: %s", user_id, exc.response.text)
        raise HTTPException(status_code=500, detail="Verification failed. Please try again.")

    logger.info("Email verified: user=%s email=%s", user_id, email)
    return {"message": "Email verified successfully. You can now sign in."}


# ── POST /api/auth/change-password ───────────────────────────────────────────

@router.post("/change-password")
async def change_password(
    request: Request,
    old_password: str = Body(..., embed=True),
    new_password: str = Body(..., embed=True),
):
    """Change the current user's password.

    Verifies the old password against PocketBase, then updates via superuser.
    Clears must_change_password and returns a fresh FastAPI JWT.
    """
    if not REQUIRE_AUTH:
        raise HTTPException(status_code=400, detail="Auth is not enabled")

    # Extract user info from current JWT
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = decode_token(token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    email = payload.get("email", "")
    user_id = payload.get("sub", "")
    tenant_id = payload.get("tenant_id", "")
    is_root = bool(payload.get("is_root", False))

    if not email or not user_id:
        raise HTTPException(status_code=400, detail="Invalid token payload")

    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Verify old password by attempting a PocketBase login
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{PB_URL}/api/collections/users/auth-with-password",
                json={"identity": email, "password": old_password},
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to verify current password")

    # Update password via superuser (also clears must_change_password)
    try:
        update_user_password(user_id, new_password)
    except httpx.HTTPStatusError as exc:
        logger.error("Failed to update password: %s", exc.response.text)
        raise HTTPException(status_code=500, detail="Failed to update password")

    # Issue a fresh token so the session continues
    is_platform_admin = bool(payload.get("is_platform_admin", False))
    tenant_account_type = str(payload.get("tenant_account_type") or get_tenant_account_type(tenant_id))
    new_token = create_token(
        user_id,
        email,
        tenant_id,
        is_root,
        tenant_name=get_tenant_name(tenant_id),
        is_platform_admin=is_platform_admin,
        tenant_account_type=tenant_account_type,
    )
    logger.info("Password changed for user=%s", email)

    return {"token": new_token, "email": email}
