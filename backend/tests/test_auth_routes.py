"""Focused coverage for public authentication routes and shared auth dependencies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, call

import httpx
import jwt as pyjwt
import pytest
from fastapi import HTTPException

from automail.api import auth, auth_utils
from automail.api.admin import deps
from automail.core.auth import JWT_ALGORITHM, JWT_SECRET, ProjectContext, TokenPayload


def _user_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": "user-1",
        "email": "user@example.test",
        "tenant": "tenant-1",
        "is_root": False,
        "is_platform_admin": False,
        "verified": True,
        "language": "de",
        "must_change_password": False,
    }
    record.update(overrides)
    return record


def _verification_token(**overrides: Any) -> str:
    payload: dict[str, Any] = {
        "sub": "user-1",
        "email": "user@example.test",
        "purpose": "email-verification",
        "exp": datetime(2099, 1, 1, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _http_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "http://pocketbase.test/auth")
    return httpx.Response(status_code, request=request)


class _PocketBaseClient:
    def __init__(
        self,
        response: httpx.Response | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or _http_response(200)
        self.error = error
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __enter__(self) -> _PocketBaseClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, json: dict[str, str]) -> httpx.Response:
        self.requests.append((url, json))
        if self.error:
            raise self.error
        return self.response


@pytest.fixture(autouse=True)
def _enable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "REQUIRE_AUTH", True)


@pytest.fixture
def _auth_response_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, MagicMock]:
    account_type = MagicMock(return_value="demo")
    tenant_name = MagicMock(return_value="Test Tenant")
    capabilities = MagicMock(return_value={"canPublish": True})
    create_token = MagicMock(return_value="issued-token")
    monkeypatch.setattr(auth, "get_is_root", lambda record: bool(record.get("is_root")))
    monkeypatch.setattr(auth, "get_tenant_account_type", account_type)
    monkeypatch.setattr(auth, "get_tenant_name", tenant_name)
    monkeypatch.setattr(auth, "get_account_capabilities", capabilities)
    monkeypatch.setattr(auth, "create_token", create_token)
    return {
        "account_type": account_type,
        "tenant_name": tenant_name,
        "capabilities": capabilities,
        "create_token": create_token,
    }


@pytest.mark.no_gemini
def test_auth_config_reads_onprem_signup_setting(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "IS_SAAS", False)
    monkeypatch.setattr(auth, "get_single_tenant", lambda: {"id": "tenant-1"})
    monkeypatch.setattr(
        auth,
        "get_tenant_settings",
        lambda _tenant_id: {"allowSignups": True},
    )

    response = client.get("/api/auth/config")

    assert response.status_code == 200
    assert response.json() == {"isSaas": False, "allowSignups": True}


@pytest.mark.no_gemini
def test_auth_config_fails_closed_when_tenant_lookup_fails(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth, "IS_SAAS", False)
    monkeypatch.setattr(
        auth,
        "get_single_tenant",
        MagicMock(side_effect=RuntimeError("PocketBase unavailable")),
    )

    response = client.get("/api/auth/config")

    assert response.status_code == 200
    assert response.json()["allowSignups"] is False


@pytest.mark.no_gemini
@pytest.mark.parametrize(
    ("record", "detail"),
    [
        ({"id": "user-1", "tenant": "tenant-1"}, "no email"),
        ({"id": "user-1", "email": "user@example.test"}, "no associated tenant"),
    ],
)
def test_issue_auth_response_rejects_incomplete_records(
    record: dict[str, str],
    detail: str,
) -> None:
    with pytest.raises(HTTPException, match=detail):
        auth._issue_auth_response(record)


@pytest.mark.no_gemini
def test_issue_auth_response_rejects_unverified_saas_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth, "IS_SAAS", True)

    with pytest.raises(HTTPException, match="verify your email"):
        auth._issue_auth_response(_user_record(verified=False))


@pytest.mark.no_gemini
def test_request_login_code_hides_invalid_and_unknown_accounts(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = MagicMock(return_value=None)
    patch_record = MagicMock()
    monkeypatch.setattr(auth, "get_user_by_email", lookup)
    monkeypatch.setattr(auth, "patch_user_record", patch_record)

    invalid = client.post("/api/auth/request-login-code", json={"email": "not-an-email"})
    unknown = client.post(
        "/api/auth/request-login-code",
        json={"email": "missing@example.test"},
    )

    assert invalid.status_code == 200
    assert unknown.status_code == 200
    assert invalid.json() == unknown.json() == {"status": "ok"}
    lookup.assert_called_once_with("missing@example.test")
    patch_record.assert_not_called()


@pytest.mark.no_gemini
def test_request_login_code_hides_unverified_saas_account(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth, "IS_SAAS", True)
    monkeypatch.setattr(
        auth,
        "get_user_by_email",
        lambda _email: _user_record(verified=False),
    )
    patch_record = MagicMock()
    monkeypatch.setattr(auth, "patch_user_record", patch_record)

    response = client.post(
        "/api/auth/request-login-code",
        json={"email": "user@example.test"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    patch_record.assert_not_called()


@pytest.mark.no_gemini
def test_request_login_code_persists_hash_and_sends_code(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    patched: list[tuple[str, dict[str, Any]]] = []
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(auth, "IS_SAAS", False)
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: _user_record())
    monkeypatch.setattr(auth, "_now_utc", lambda: fixed_now)
    monkeypatch.setattr(auth.secrets, "choice", lambda _digits: "7")
    monkeypatch.setattr(
        auth,
        "patch_user_record",
        lambda user_id, values: patched.append((user_id, values)),
    )
    monkeypatch.setattr(
        "automail.integrations.email_sender.send_login_code_email",
        lambda email, code: sent.append((email, code)),
    )

    response = client.post(
        "/api/auth/request-login-code",
        json={"email": "  USER@example.test  "},
    )

    assert response.status_code == 200
    assert sent == [("user@example.test", "777777")]
    assert patched == [
        (
            "user-1",
            {
                "login_code_hash": auth_utils._hash_login_code(
                    "user@example.test",
                    "777777",
                ),
                "login_code_expires": (
                    fixed_now + timedelta(minutes=auth.LOGIN_CODE_TTL_MINUTES)
                ).isoformat(),
                "login_code_attempts": 0,
            },
        ),
    ]


@pytest.mark.no_gemini
def test_request_login_code_reports_delivery_failure(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: _user_record())
    monkeypatch.setattr(auth, "patch_user_record", lambda *_args: None)
    monkeypatch.setattr(
        "automail.integrations.email_sender.send_login_code_email",
        MagicMock(side_effect=RuntimeError("SMTP unavailable")),
    )

    response = client.post(
        "/api/auth/request-login-code",
        json={"email": "user@example.test"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to send login code"


@pytest.mark.no_gemini
def test_verify_login_code_rejects_missing_user(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: None)

    response = client.post(
        "/api/auth/verify-login-code",
        json={"email": "missing@example.test", "code": "123456"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired login code"


@pytest.mark.no_gemini
def test_verify_login_code_counts_malformed_expiry_as_failed_attempt(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user_record(
        login_code_hash="not-the-hash",
        login_code_expires="not-a-date",
        login_code_attempts=2,
    )
    patch_record = MagicMock()
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: user)
    monkeypatch.setattr(auth, "patch_user_record", patch_record)

    response = client.post(
        "/api/auth/verify-login-code",
        json={"email": "user@example.test", "code": "123456"},
    )

    assert response.status_code == 400
    patch_record.assert_called_once_with("user-1", {"login_code_attempts": 3})


@pytest.mark.no_gemini
def test_verify_login_code_enforces_maximum_attempts_before_issuing_session(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = "user@example.test"
    code = "123456"
    user = _user_record(
        login_code_hash=auth_utils._hash_login_code(email, code),
        login_code_expires=datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat(),
        login_code_attempts=auth.LOGIN_CODE_MAX_ATTEMPTS,
    )
    patch_record = MagicMock()
    issue_response = MagicMock()
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: user)
    monkeypatch.setattr(auth, "patch_user_record", patch_record)
    monkeypatch.setattr(auth, "_issue_auth_response", issue_response)

    response = client.post(
        "/api/auth/verify-login-code",
        json={"email": email, "code": code},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired login code"
    patch_record.assert_called_once_with(
        "user-1",
        {"login_code_attempts": auth.LOGIN_CODE_MAX_ATTEMPTS + 1},
    )
    issue_response.assert_not_called()


@pytest.mark.no_gemini
def test_verify_login_code_clears_secret_and_returns_session(
    client,
    monkeypatch: pytest.MonkeyPatch,
    _auth_response_dependencies: dict[str, MagicMock],
) -> None:
    email = "user@example.test"
    code = "123456"
    user = _user_record(
        login_code_hash=auth_utils._hash_login_code(email, code),
        login_code_expires=(
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat(),
        login_code_attempts=0,
        is_root=True,
        is_platform_admin=True,
    )
    patch_record = MagicMock()
    monkeypatch.setattr(auth, "IS_SAAS", False)
    monkeypatch.setattr(auth, "get_user_by_email", lambda _email: user)
    monkeypatch.setattr(auth, "patch_user_record", patch_record)

    response = client.post(
        "/api/auth/verify-login-code",
        json={"email": email, "code": "12-34 56"},
    )

    assert response.status_code == 200
    assert response.json()["token"] == "issued-token"
    assert response.json()["language"] == "de"
    assert response.json()["tenantAccountType"] == "demo"
    assert response.json()["capabilities"] == {"canPublish": True}
    patch_record.assert_called_once_with(
        "user-1",
        {
            "login_code_hash": "",
            "login_code_expires": "",
            "login_code_attempts": 0,
        },
    )
    _auth_response_dependencies["account_type"].assert_called_once_with("tenant-1")
    _auth_response_dependencies["tenant_name"].assert_called_once_with("tenant-1")
    _auth_response_dependencies["create_token"].assert_called_once_with(
        "user-1",
        "user@example.test",
        "tenant-1",
        True,
        tenant_name="Test Tenant",
        is_platform_admin=True,
        tenant_account_type="demo",
    )
    _auth_response_dependencies["capabilities"].assert_called_once_with(
        "tenant-1",
        is_platform_admin=True,
    )


@pytest.mark.no_gemini
def test_password_login_requires_explicit_account_opt_in(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth,
        "get_user_by_email",
        lambda _email: _user_record(password_login_enabled=False),
    )

    response = client.post(
        "/api/auth/password-login",
        json={"email": "user@example.test", "password": "old-password"},
    )

    assert response.status_code == 403
    assert "not enabled" in response.json()["detail"]


@pytest.mark.no_gemini
@pytest.mark.parametrize(
    ("pocketbase_client", "expected_status", "expected_detail"),
    [
        (_PocketBaseClient(_http_response(401)), 401, "Invalid email or password"),
        (_PocketBaseClient(error=RuntimeError("connection lost")), 500, "Login failed"),
    ],
)
def test_password_login_maps_pocketbase_failures(
    client,
    monkeypatch: pytest.MonkeyPatch,
    pocketbase_client: _PocketBaseClient,
    expected_status: int,
    expected_detail: str,
) -> None:
    monkeypatch.setattr(
        auth,
        "get_user_by_email",
        lambda _email: _user_record(password_login_enabled=True),
    )
    monkeypatch.setattr(auth.httpx, "Client", lambda **_kwargs: pocketbase_client)

    response = client.post(
        "/api/auth/password-login",
        json={"email": "user@example.test", "password": "old-password"},
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail


@pytest.mark.no_gemini
def test_password_login_returns_session_after_pocketbase_auth(
    client,
    monkeypatch: pytest.MonkeyPatch,
    _auth_response_dependencies: dict[str, MagicMock],
) -> None:
    pocketbase_client = _PocketBaseClient()
    monkeypatch.setattr(
        auth,
        "get_user_by_email",
        lambda _email: _user_record(
            password_login_enabled=True,
            is_root=True,
            is_platform_admin=True,
        ),
    )
    monkeypatch.setattr(auth.httpx, "Client", lambda **_kwargs: pocketbase_client)

    response = client.post(
        "/api/auth/password-login",
        json={"email": "  USER@example.test ", "password": "old-password"},
    )

    assert response.status_code == 200
    assert response.json()["token"] == "issued-token"
    assert response.json()["isRoot"] is True
    assert response.json()["isPlatformAdmin"] is True
    assert response.json()["tenantAccountType"] == "demo"
    assert response.json()["capabilities"] == {"canPublish": True}
    assert pocketbase_client.requests == [
        (
            f"{auth.PB_URL}/api/collections/users/auth-with-password",
            {"identity": "user@example.test", "password": "old-password"},
        ),
    ]
    _auth_response_dependencies["account_type"].assert_called_once_with("tenant-1")
    _auth_response_dependencies["tenant_name"].assert_called_once_with("tenant-1")
    _auth_response_dependencies["create_token"].assert_called_once_with(
        "user-1",
        "user@example.test",
        "tenant-1",
        True,
        tenant_name="Test Tenant",
        is_platform_admin=True,
        tenant_account_type="demo",
    )
    _auth_response_dependencies["capabilities"].assert_called_once_with(
        "tenant-1",
        is_platform_admin=True,
    )


@pytest.mark.no_gemini
@pytest.mark.parametrize(
    ("token", "detail"),
    [
        (
            _verification_token(
                exp=datetime.now(timezone.utc) - timedelta(minutes=1),
            ),
            "Verification link has expired",
        ),
        ("not-a-jwt", "Invalid verification token"),
        (_verification_token(purpose="password-reset"), "Invalid token type"),
        (_verification_token(sub=""), "Invalid token payload"),
    ],
)
def test_verify_email_rejects_invalid_tokens(client, token: str, detail: str) -> None:
    response = client.post("/api/auth/verify-email", json={"token": token})

    assert response.status_code == 400
    assert detail in response.json()["detail"]


@pytest.mark.no_gemini
def test_verify_email_maps_pocketbase_failure(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = httpx.HTTPStatusError(
        "PocketBase failure",
        request=httpx.Request("PATCH", "http://pocketbase.test/users/user-1"),
        response=_http_response(500),
    )
    monkeypatch.setattr(auth, "set_user_verified", MagicMock(side_effect=error))

    response = client.post(
        "/api/auth/verify-email",
        json={"token": _verification_token()},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Verification failed. Please try again."


@pytest.mark.no_gemini
def test_verify_email_marks_user_verified(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_verified = MagicMock()
    monkeypatch.setattr(auth, "set_user_verified", set_verified)

    response = client.post(
        "/api/auth/verify-email",
        json={"token": _verification_token()},
    )

    assert response.status_code == 200
    assert response.json()["message"].startswith("Email verified successfully")
    set_verified.assert_called_once_with("user-1")


def _change_password(
    client,
    *,
    token: str = "session-token",
    old_password: str = "old-password",
    new_password: str = "new-password",
):
    return client.post(
        "/api/auth/change-password",
        json={
            "old_password": old_password,
            "new_password": new_password,
        },
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.no_gemini
def test_change_password_requires_bearer_token(client) -> None:
    response = client.post(
        "/api/auth/change-password",
        json={"old_password": "old-password", "new_password": "new-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Authorization header"


@pytest.mark.no_gemini
@pytest.mark.parametrize(
    ("error", "detail"),
    [
        (pyjwt.ExpiredSignatureError(), "Token expired"),
        (ValueError("invalid"), "Invalid token"),
    ],
)
def test_change_password_rejects_invalid_session_token(
    client,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    detail: str,
) -> None:
    monkeypatch.setattr(auth, "decode_token", MagicMock(side_effect=error))

    response = _change_password(client)

    assert response.status_code == 401
    assert response.json()["detail"] == detail


@pytest.mark.no_gemini
def test_change_password_rejects_incomplete_token_payload(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth, "decode_token", lambda _token: {"email": ""})

    response = _change_password(client)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid token payload"


@pytest.mark.no_gemini
def test_change_password_rejects_short_new_password(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda _token: {"sub": "user-1", "email": "user@example.test"},
    )

    response = _change_password(client, new_password="short")

    assert response.status_code == 400
    assert "8 characters" in response.json()["detail"]


@pytest.mark.no_gemini
@pytest.mark.parametrize(
    ("pocketbase_client", "expected_status", "expected_detail"),
    [
        (_PocketBaseClient(_http_response(401)), 400, "Current password is incorrect"),
        (
            _PocketBaseClient(error=RuntimeError("connection lost")),
            500,
            "Failed to verify current password",
        ),
    ],
)
def test_change_password_maps_old_password_check_failures(
    client,
    monkeypatch: pytest.MonkeyPatch,
    pocketbase_client: _PocketBaseClient,
    expected_status: int,
    expected_detail: str,
) -> None:
    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda _token: {
            "sub": "user-1",
            "email": "user@example.test",
            "tenant_id": "tenant-1",
        },
    )
    monkeypatch.setattr(auth.httpx, "Client", lambda **_kwargs: pocketbase_client)

    response = _change_password(client)

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail


@pytest.mark.no_gemini
def test_change_password_maps_update_failure(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = httpx.HTTPStatusError(
        "PocketBase failure",
        request=httpx.Request("PATCH", "http://pocketbase.test/users/user-1"),
        response=_http_response(500),
    )
    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda _token: {
            "sub": "user-1",
            "email": "user@example.test",
            "tenant_id": "tenant-1",
        },
    )
    monkeypatch.setattr(auth.httpx, "Client", lambda **_kwargs: _PocketBaseClient())
    monkeypatch.setattr(auth, "update_user_password", MagicMock(side_effect=error))

    response = _change_password(client)

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to update password"


@pytest.mark.no_gemini
def test_change_password_updates_password_and_returns_fresh_session(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pocketbase_client = _PocketBaseClient()
    update_password = MagicMock()
    token_payload = {
        "sub": "user-1",
        "email": "user@example.test",
        "tenant_id": "tenant-1",
        "is_root": True,
        "is_platform_admin": True,
        "tenant_account_type": "demo",
    }
    create_token = MagicMock(return_value="fresh-token")
    monkeypatch.setattr(auth, "decode_token", lambda _token: token_payload)
    monkeypatch.setattr(auth.httpx, "Client", lambda **_kwargs: pocketbase_client)
    monkeypatch.setattr(auth, "update_user_password", update_password)
    monkeypatch.setattr(auth, "get_tenant_name", lambda _tenant_id: "Test Tenant")
    monkeypatch.setattr(auth, "create_token", create_token)

    response = _change_password(client)

    assert response.status_code == 200
    assert response.json() == {
        "token": "fresh-token",
        "email": "user@example.test",
    }
    update_password.assert_called_once_with("user-1", "new-password")
    create_token.assert_called_once_with(
        "user-1",
        "user@example.test",
        "tenant-1",
        True,
        tenant_name="Test Tenant",
        is_platform_admin=True,
        tenant_account_type="demo",
    )
    assert pocketbase_client.requests[0][1] == {
        "identity": "user@example.test",
        "password": "old-password",
    }


@pytest.mark.no_gemini
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("  ", ""),
        ("#a1b2c3", "#A1B2C3"),
    ],
)
def test_normalize_hex_color(raw: object, expected: str | None) -> None:
    assert deps._normalize_hex_color(raw) == expected


@pytest.mark.no_gemini
def test_normalize_hex_color_rejects_invalid_value() -> None:
    with pytest.raises(HTTPException, match="#RRGGBB"):
        deps._normalize_hex_color("blue")


@pytest.mark.no_gemini
@pytest.mark.parametrize(
    ("dependency", "minimum_role"),
    [
        (deps._project_viewer, "viewer"),
        (deps._project_editor, "editor"),
        (deps._project_admin, "admin"),
    ],
)
def test_project_dependencies_apply_expected_minimum_role(
    monkeypatch: pytest.MonkeyPatch,
    dependency,
    minimum_role: str,
) -> None:
    request = MagicMock()
    context = ProjectContext("tenant-1", "user-1", "project-1", minimum_role)
    resolver = MagicMock(return_value=context)
    monkeypatch.setattr(deps, "resolve_project_context", resolver)

    assert dependency(request, "project-1") is context
    resolver.assert_called_once_with(request, "project-1", min_role=minimum_role)


@pytest.mark.no_gemini
def test_root_auth_rejects_authenticated_non_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = TokenPayload("user-1", "user@example.test", "tenant-1", False)
    monkeypatch.setattr(deps, "require_authenticated", lambda _request: payload)

    with pytest.raises(HTTPException, match="Root access required"):
        deps._root_auth(MagicMock())


@pytest.mark.no_gemini
@pytest.mark.parametrize(
    "payload",
    [
        TokenPayload("", "", "", False),
        TokenPayload("user-1", "user@example.test", "tenant-1", True),
        TokenPayload(
            "user-1",
            "user@example.test",
            "tenant-1",
            False,
            is_platform_admin=True,
        ),
    ],
)
def test_root_auth_accepts_bootstrap_root_or_platform_admin(
    monkeypatch: pytest.MonkeyPatch,
    payload: TokenPayload,
) -> None:
    monkeypatch.setattr(deps, "require_authenticated", lambda _request: payload)

    assert deps._root_auth(MagicMock()) is payload


@pytest.mark.no_gemini
@pytest.mark.parametrize(
    "payload",
    [
        TokenPayload("", "", "", False),
        TokenPayload("user-1", "user@example.test", "tenant-1", False),
    ],
)
def test_platform_admin_auth_rejects_other_callers(
    monkeypatch: pytest.MonkeyPatch,
    payload: TokenPayload,
) -> None:
    monkeypatch.setattr(deps, "require_authenticated", lambda _request: payload)

    with pytest.raises(HTTPException, match="Platform administrator access required"):
        deps._platform_admin_auth(MagicMock())


@pytest.mark.no_gemini
def test_platform_admin_auth_returns_platform_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = TokenPayload(
        "user-1",
        "user@example.test",
        "tenant-1",
        False,
        is_platform_admin=True,
    )
    monkeypatch.setattr(deps, "require_authenticated", lambda _request: payload)

    assert deps._platform_admin_auth(MagicMock()) is payload


@pytest.mark.no_gemini
def test_capability_dependencies_skip_bootstrap_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_capability = MagicMock()
    monkeypatch.setattr(deps, "require_capability", require_capability)

    deps._require_ctx_capability(
        ProjectContext("", "", "project-1", "root"),
        "canPublish",
    )
    deps._require_auth_capability(
        TokenPayload("", "", "", False),
        "canManageBilling",
    )

    require_capability.assert_not_called()


@pytest.mark.no_gemini
def test_capability_dependencies_forward_tenant_and_platform_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_capability = MagicMock()
    monkeypatch.setattr(deps, "require_capability", require_capability)

    deps._require_ctx_capability(
        ProjectContext(
            "tenant-1",
            "user-1",
            "project-1",
            "root",
            is_platform_admin=True,
        ),
        "canPublish",
    )
    deps._require_auth_capability(
        TokenPayload(
            "user-1",
            "user@example.test",
            "tenant-1",
            True,
            is_platform_admin=False,
        ),
        "canManageBilling",
    )

    assert require_capability.call_args_list == [
        call(
            "tenant-1",
            "canPublish",
            is_platform_admin=True,
        ),
        call(
            "tenant-1",
            "canManageBilling",
            is_platform_admin=False,
        ),
    ]


@pytest.mark.no_gemini
def test_auth_utils_normalize_and_sign_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAAS_SIGNUP_ENABLED", " TRUE ")
    assert auth_utils.saas_signup_enabled() is True
    monkeypatch.setenv("SAAS_SIGNUP_ENABLED", "false")
    assert auth_utils.saas_signup_enabled() is False

    now = auth_utils._now_utc()
    assert now.tzinfo is timezone.utc
    assert auth_utils._hash_login_code(" User@Example.test ", " 123456 ") == (
        auth_utils._hash_login_code("user@example.test", "123456")
    )
    assert auth_utils._hash_login_code("user@example.test", "123456") != (
        auth_utils._hash_login_code("user@example.test", "654321")
    )

    fixed_now = datetime(2030, 5, 17, 12, 34, 56, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(auth_utils, "datetime", _FixedDatetime)
    token = auth_utils._create_verification_token("user-1", "user@example.test")
    payload = pyjwt.decode(
        token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITHM],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert payload["sub"] == "user-1"
    assert payload["email"] == "user@example.test"
    assert payload["purpose"] == "email-verification"
    assert payload["iat"] == int(fixed_now.timestamp())
    assert payload["exp"] - payload["iat"] == (
        auth_utils.VERIFICATION_TOKEN_HOURS * 60 * 60
    )
