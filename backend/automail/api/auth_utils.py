"""Shared auth endpoint helpers."""

import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone

import jwt as pyjwt

from automail.core.auth import JWT_ALGORITHM, JWT_SECRET

LOGIN_CODE_TTL_MINUTES = 10
LOGIN_CODE_MAX_ATTEMPTS = 5
VERIFICATION_TOKEN_HOURS = 24
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def saas_signup_enabled() -> bool:
    return os.getenv("SAAS_SIGNUP_ENABLED", "true").strip().lower() == "true"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hash_login_code(email: str, code: str) -> str:
    message = f"{email.strip().lower()}:{code.strip()}".encode()
    return hmac.new(JWT_SECRET.encode(), message, hashlib.sha256).hexdigest()


def _create_verification_token(user_id: str, email: str) -> str:
    """Create a short-lived JWT for email verification."""
    payload = {
        "sub": user_id,
        "email": email,
        "purpose": "email-verification",
        "exp": datetime.now(timezone.utc) + timedelta(hours=VERIFICATION_TOKEN_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
