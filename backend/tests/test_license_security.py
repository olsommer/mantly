"""Focused security tests for SaaS license administration and storage."""

import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from automail.billing import license_store
from automail.core.auth import create_token

pytestmark = pytest.mark.no_gemini


def _auth_header(
    *,
    is_root: bool,
    is_platform_admin: bool = False,
) -> dict[str, str]:
    token = create_token(
        "platform-admin" if is_platform_admin else "root-user" if is_root else "regular-user",
        "platform@example.test" if is_platform_admin else "root@example.test" if is_root else "user@example.test",
        "tenant-1",
        is_root,
        is_platform_admin=is_platform_admin,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/admin/licenses", None),
        ("POST", "/api/admin/licenses", {"tenant_name": "Tenant A"}),
        ("DELETE", "/api/admin/licenses/license-1", None),
        ("POST", "/api/admin/licenses/license-1/reset-instance", None),
    ],
)
def test_license_admin_routes_require_platform_admin_auth(
    client,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", True)
    request_kwargs = {"json": payload} if payload is not None else {}

    with (
        patch("automail.api.admin.license.IS_SAAS", True),
        patch("automail.api.admin.license._list_all", return_value=[]) as list_all,
        patch(
            "automail.api.admin.license._post",
            return_value={"id": "license-1"},
        ) as create,
        patch("automail.api.admin.license._patch") as mutate,
    ):
        missing = client.request(method, path, **request_kwargs)
        non_root = client.request(
            method,
            path,
            headers=_auth_header(is_root=False),
            **request_kwargs,
        )
        tenant_root = client.request(
            method,
            path,
            headers=_auth_header(is_root=True),
            **request_kwargs,
        )
        platform_admin = client.request(
            method,
            path,
            headers=_auth_header(is_root=False, is_platform_admin=True),
            **request_kwargs,
        )

    assert missing.status_code == 401
    assert non_root.status_code == 403
    assert non_root.json()["detail"] == "Platform administrator access required"
    assert tenant_root.status_code == 403
    assert tenant_root.json()["detail"] == "Platform administrator access required"
    assert platform_admin.status_code == 200
    assert list_all.call_count == (1 if method == "GET" else 0)
    assert create.call_count == (1 if method == "POST" and path == "/api/admin/licenses" else 0)
    assert mutate.call_count == (1 if path != "/api/admin/licenses" else 0)


def test_license_admin_routes_fail_closed_when_auth_is_disabled(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", False)

    with (
        patch("automail.api.admin.license.IS_SAAS", True),
        patch("automail.api.admin.license._list_all", return_value=[]) as list_all,
    ):
        response = client.get("/api/admin/licenses")

    assert response.status_code == 403
    assert response.json()["detail"] == "Platform administrator access required"
    list_all.assert_not_called()


def test_license_admin_routes_reject_platform_token_without_subject(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", True)
    token = create_token(
        "",
        "platform@example.test",
        "tenant-1",
        False,
        is_platform_admin=True,
    )

    with (
        patch("automail.api.admin.license.IS_SAAS", True),
        patch("automail.api.admin.license._list_all", return_value=[]) as list_all,
    ):
        response = client.get(
            "/api/admin/licenses",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Platform administrator access required"
    list_all.assert_not_called()


def test_saas_startup_rejects_disabled_authentication() -> None:
    env = {
        **os.environ,
        "IS_SAAS": "true",
        "REQUIRE_AUTH": "false",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import automail.main"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "REQUIRE_AUTH=true is required when IS_SAAS=true" in (result.stdout + result.stderr)


def test_list_returns_only_masked_prefix_not_secret_or_digest(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", True)
    secret = "a" * 40
    digest = license_store.license_key_digest(secret)
    record = {
        "id": "license-1",
        "key": digest,
        "key_prefix": secret[:8],
        "tenant_name": "Tenant A",
        "is_active": True,
    }

    with (
        patch("automail.api.admin.license.IS_SAAS", True),
        patch("automail.api.admin.license._list_all", return_value=[record]),
    ):
        response = client.get(
            "/api/admin/licenses",
            headers=_auth_header(is_root=False, is_platform_admin=True),
        )

    assert response.status_code == 200
    assert response.json()[0]["key"] == "aaaaaaaa..."
    assert response.json()[0]["keyPrefix"] == "aaaaaaaa"
    assert secret not in response.text
    assert digest not in response.text


def test_create_reveals_plaintext_once_but_persists_only_digest(
    client,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", True)
    secret = "b" * 40
    caplog.set_level(logging.INFO, logger="automail.api.admin.license")

    with (
        patch("automail.api.admin.license.IS_SAAS", True),
        patch("automail.api.admin.license.generate_license_key", return_value=secret),
        patch("automail.api.admin.license._post", return_value={"id": "license-1"}) as post,
    ):
        response = client.post(
            "/api/admin/licenses",
            json={"tenant_name": "Tenant A", "max_users": 25},
            headers=_auth_header(is_root=False, is_platform_admin=True),
        )

    stored = post.call_args.args[1]
    assert response.status_code == 200
    assert response.json()["key"] == secret
    assert response.headers["cache-control"] == "no-store"
    assert stored["key"] == license_store.license_key_digest(secret)
    assert stored["key_prefix"] == secret[:8]
    assert secret not in caplog.text


def test_digest_value_cannot_authenticate_as_a_legacy_key() -> None:
    stolen_digest = license_store.license_key_digest("c" * 40)

    with patch("automail.billing.license_store._first", return_value=None) as first:
        record = license_store.find_license_by_key(stolen_digest)

    assert record is None
    assert first.call_count == 1
    assert stolen_digest not in first.call_args.args[1]


def test_legacy_key_lookup_rehashes_record_without_changing_validation_identity() -> None:
    legacy_key = "d" * 40
    legacy_record = {
        "id": "legacy-1",
        "key": legacy_key,
        "tenant_name": "Legacy Tenant",
        "is_active": True,
    }

    with (
        patch(
            "automail.billing.license_store._first",
            side_effect=[None, legacy_record],
        ) as first,
        patch("automail.billing.license_store._patch") as migrate,
    ):
        record = license_store.find_license_by_key(legacy_key)

    assert first.call_count == 2
    assert record is not None
    assert record["key"] == license_store.license_key_digest(legacy_key)
    assert record["key_prefix"] == legacy_key[:8]
    migrate.assert_called_once_with(
        "/api/collections/licenses/records/legacy-1",
        license_store.license_key_storage_fields(legacy_key),
    )


def test_legacy_key_remains_usable_when_best_effort_rehash_fails() -> None:
    legacy_key = "e" * 40
    legacy_record = {
        "id": "legacy-1",
        "key": legacy_key,
        "is_active": True,
    }
    request = httpx.Request("PATCH", "http://pb.test/licenses/legacy-1")
    response = httpx.Response(503, request=request)
    error = httpx.HTTPStatusError("unavailable", request=request, response=response)

    with (
        patch(
            "automail.billing.license_store._first",
            side_effect=[None, legacy_record],
        ),
        patch("automail.billing.license_store._patch", side_effect=error),
    ):
        record = license_store.find_license_by_key(legacy_key)

    assert record == legacy_record


def test_onprem_checkout_requires_manual_platform_admin_provisioning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from automail.billing import webhooks

    caplog.set_level(logging.WARNING, logger="automail.billing.webhooks")
    session = {
        "metadata": {"tenant_id": "tenant-1"},
        "subscription": "sub-1",
    }

    with (
        patch("automail.billing.webhooks.STRIPE_ONPREM_PRICE_ID", "price-onprem"),
        patch("automail.billing.webhooks._is_onprem_subscription", return_value=True),
        patch("automail.billing.webhooks._patch_tenant") as patch_tenant,
        patch("automail.db.pocketbase.client._post") as post,
        patch("secrets.token_hex") as generate_key,
    ):
        webhooks._handle_checkout_completed(session)

    patch_tenant.assert_not_called()
    post.assert_not_called()
    generate_key.assert_not_called()
    assert "no license was created automatically" in caplog.text
    assert "platform administrator must create and securely deliver it" in caplog.text
