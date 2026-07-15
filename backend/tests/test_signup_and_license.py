"""Unit tests for the signup endpoint and license validation logic.

These tests run WITHOUT calling PocketBase or any external service — all
external dependencies are mocked.

Run with:
    uv run pytest tests/test_signup_and_license.py -v
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from starlette.testclient import TestClient

# ============================================================
# Signup endpoint tests
# ============================================================

class TestSignupEndpoint:
    """Tests for POST /api/auth/signup."""

    def _get_client(self):
        """Return a fresh TestClient (imports app after env patches)."""
        from automail.main import app
        return TestClient(app)

    # ── SaaS gate ─────────────────────────────────────────────

    @patch("automail.api.auth.IS_SAAS", False)
    @patch("automail.api.auth.REQUIRE_AUTH", True)
    @patch("automail.api.auth.get_tenant_settings", return_value={"allowSignups": False})
    @patch("automail.api.auth.get_single_tenant", return_value={"id": "tenant_abc"})
    def test_signup_returns_404_when_onprem_signups_disabled(self, _tenant, _settings):
        """On-prem signup is hidden unless the tenant explicitly allows signups."""
        client = self._get_client()
        resp = client.post("/api/auth/signup", json={
            "companyName": "ACME",
            "email": "new@example.com",
            "password": "securepassword123",
        })
        assert resp.status_code == 404

    @patch("automail.api.auth.IS_SAAS", True)
    @patch("automail.api.auth.REQUIRE_AUTH", False)
    def test_signup_requires_auth_enabled(self):
        """Signup returns 400 when REQUIRE_AUTH is False."""
        client = self._get_client()
        resp = client.post("/api/auth/signup", json={
            "companyName": "ACME",
            "email": "new@example.com",
            "password": "securepassword123",
        })
        assert resp.status_code == 400
        assert "Auth is not enabled" in resp.json()["detail"]

    @patch("automail.api.auth.IS_SAAS", True)
    def test_auth_config_hides_saas_signup_when_disabled(self):
        client = self._get_client()
        with patch.dict(os.environ, {"SAAS_SIGNUP_ENABLED": "false"}):
            resp = client.get("/api/auth/config")

        assert resp.status_code == 200
        assert resp.json()["allowSignups"] is False

    @patch("automail.api.auth.IS_SAAS", True)
    @patch("automail.api.auth.REQUIRE_AUTH", True)
    def test_signup_returns_404_when_saas_signups_disabled(self):
        client = self._get_client()
        with patch.dict(os.environ, {"SAAS_SIGNUP_ENABLED": "false"}):
            resp = client.post("/api/auth/signup", json={
                "companyName": "ACME",
                "email": "new@example.com",
                "password": "securepassword123",
            })

        assert resp.status_code == 404

    # ── Validation ────────────────────────────────────────────

    @patch("automail.api.auth.IS_SAAS", True)
    @patch("automail.api.auth.REQUIRE_AUTH", True)
    def test_signup_rejects_empty_company_name(self):
        client = self._get_client()
        resp = client.post("/api/auth/signup", json={
            "companyName": "   ",
            "email": "new@example.com",
            "password": "securepassword123",
        })
        assert resp.status_code == 400
        assert "Company name" in resp.json()["detail"]

    @patch("automail.api.auth.IS_SAAS", True)
    @patch("automail.api.auth.REQUIRE_AUTH", True)
    def test_signup_rejects_long_company_name(self):
        client = self._get_client()
        resp = client.post("/api/auth/signup", json={
            "companyName": "A" * 201,
            "email": "new@example.com",
            "password": "securepassword123",
        })
        assert resp.status_code == 400
        assert "too long" in resp.json()["detail"]

    @patch("automail.api.auth.IS_SAAS", True)
    @patch("automail.api.auth.REQUIRE_AUTH", True)
    def test_signup_rejects_invalid_email(self):
        client = self._get_client()
        resp = client.post("/api/auth/signup", json={
            "companyName": "ACME",
            "email": "not-an-email",
            "password": "securepassword123",
        })
        assert resp.status_code == 400
        assert "Invalid email" in resp.json()["detail"]

    @patch("automail.api.auth.IS_SAAS", True)
    @patch("automail.api.auth.REQUIRE_AUTH", True)
    def test_signup_rejects_short_password(self):
        client = self._get_client()
        resp = client.post("/api/auth/signup", json={
            "companyName": "ACME",
            "email": "new@example.com",
            "password": "short",
        })
        assert resp.status_code == 400
        assert "8 characters" in resp.json()["detail"]

    # ── Duplicate email ───────────────────────────────────────

    @patch("automail.api.auth.IS_SAAS", True)
    @patch("automail.api.auth.REQUIRE_AUTH", True)
    @patch("automail.api.auth.check_email_exists", return_value=True)
    def test_signup_rejects_duplicate_email(self, _mock_check):
        client = self._get_client()
        resp = client.post("/api/auth/signup", json={
            "companyName": "ACME",
            "email": "taken@example.com",
            "password": "securepassword123",
        })
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    # ── Happy path ────────────────────────────────────────────

    @patch("automail.api.auth.IS_SAAS", True)
    @patch("automail.api.auth.REQUIRE_AUTH", True)
    @patch("automail.api.auth.check_email_exists", return_value=False)
    @patch("automail.api.auth.create_project", return_value={"id": "project_abc"})
    @patch("automail.api.auth.create_stripe_customer", create=True)
    @patch("automail.api.auth.create_tenant", return_value="tenant_abc")
    @patch("automail.api.auth.create_signup_user", return_value={"id": "user_123"})
    @patch("automail.api.auth.set_user_default_project")
    def test_signup_happy_path(self, _mock_default_project, _mock_user, _mock_tenant, _mock_stripe, _mock_project, _mock_check):
        client = self._get_client()
        resp = client.post("/api/auth/signup", json={
            "companyName": "ACME GmbH",
            "email": "admin@acme.de",
            "password": "securepassword123",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == "admin@acme.de"
        assert body["verificationRequired"] is True
        assert "verify your email" in body["message"].lower()

    @patch("automail.api.auth.IS_SAAS", True)
    @patch("automail.api.auth.REQUIRE_AUTH", True)
    @patch("automail.api.auth.check_email_exists", return_value=False)
    @patch("automail.api.auth.create_project", return_value={"id": "project_abc"})
    @patch("automail.api.auth.create_stripe_customer", create=True)
    @patch("automail.api.auth.create_tenant", return_value="tenant_abc")
    @patch("automail.api.auth.create_signup_user", return_value={"id": "user_123"})
    @patch("automail.api.auth.set_user_default_project")
    def test_signup_normalises_email(self, _mock_default_project, _mock_user, _mock_tenant, _mock_stripe, _mock_project, _mock_check):
        """Signup should lowercase and strip the email."""
        client = self._get_client()
        resp = client.post("/api/auth/signup", json={
            "companyName": "ACME",
            "email": "  Admin@ACME.de  ",
            "password": "securepassword123",
        })
        assert resp.status_code == 201
        assert resp.json()["email"] == "admin@acme.de"

    # ── PocketBase failures ───────────────────────────────────

    @patch("automail.api.auth.IS_SAAS", True)
    @patch("automail.api.auth.REQUIRE_AUTH", True)
    @patch("automail.api.auth.check_email_exists", return_value=False)
    @patch("automail.api.auth.create_tenant", side_effect=httpx.HTTPStatusError(
        "PB error", request=MagicMock(), response=MagicMock(text="err", status_code=500),
    ))
    def test_signup_handles_tenant_creation_failure(self, _mock_tenant, _mock_check):
        client = self._get_client()
        resp = client.post("/api/auth/signup", json={
            "companyName": "ACME",
            "email": "new@example.com",
            "password": "securepassword123",
        })
        assert resp.status_code == 500
        assert "organisation" in resp.json()["detail"].lower()

    @patch("automail.api.auth.IS_SAAS", True)
    @patch("automail.api.auth.REQUIRE_AUTH", True)
    @patch("automail.api.auth.check_email_exists", return_value=False)
    @patch("automail.api.auth.create_tenant", return_value="tenant_abc")
    @patch("automail.api.auth.create_signup_user", side_effect=httpx.HTTPStatusError(
        "PB error", request=MagicMock(), response=MagicMock(text="err", status_code=500),
    ))
    def test_signup_handles_user_creation_failure(self, _mock_user, _mock_tenant, _mock_check):
        client = self._get_client()
        resp = client.post("/api/auth/signup", json={
            "companyName": "ACME",
            "email": "new@example.com",
            "password": "securepassword123",
        })
        assert resp.status_code == 500
        assert "user account" in resp.json()["detail"].lower()


# ============================================================
# License validation (on-prem client) tests
# ============================================================

class TestLicenseState:
    """Tests for LicenseState dataclass logic."""

    def test_fresh_state_is_invalid(self):
        from automail.billing.license import LicenseState
        state = LicenseState()
        assert state.valid is False
        assert state.should_allow_requests() is False

    def test_valid_state_allows_requests(self):
        from automail.billing.license import LicenseState
        state = LicenseState()
        state.update(valid=True, message="OK")
        assert state.valid is True
        assert state.should_allow_requests() is True

    def test_invalid_state_within_grace_allows_requests(self):
        from automail.billing.license import LicenseState
        state = LicenseState()
        # Simulate a successful check 1 hour ago, now invalid
        state.last_check = time.time() - 3600
        state.valid = False
        assert state.is_within_grace_period() is True
        assert state.should_allow_requests() is True

    def test_invalid_state_past_grace_blocks_requests(self):
        from automail.billing.license import LicenseState
        state = LicenseState()
        # Simulate a successful check 49 hours ago (beyond 48h grace)
        state.last_check = time.time() - (49 * 3600)
        state.valid = False
        assert state.is_within_grace_period() is False
        assert state.should_allow_requests() is False

    def test_no_prior_check_means_no_grace(self):
        from automail.billing.license import LicenseState
        state = LicenseState()
        state.last_check = 0.0
        state.valid = False
        assert state.is_within_grace_period() is False

    def test_update_sets_last_check_on_success(self):
        from automail.billing.license import LicenseState
        state = LicenseState()
        before = time.time()
        state.update(valid=True, message="OK", expires_at="2030-01-01", max_users=10)
        after = time.time()
        assert state.valid is True
        assert state.message == "OK"
        assert state.expires_at == "2030-01-01"
        assert state.max_users == 10
        assert before <= state.last_check <= after

    def test_update_does_not_set_last_check_on_failure(self):
        from automail.billing.license import LicenseState
        state = LicenseState()
        state.last_check = 0.0
        state.update(valid=False, message="Expired")
        # last_check should remain 0 because valid=False
        assert state.last_check == 0.0
        assert state.last_attempt > 0


class TestMachineFingerprint:
    """Tests for _machine_fingerprint()."""

    def test_fingerprint_is_deterministic(self):
        from automail.billing.license import _machine_fingerprint
        fp1 = _machine_fingerprint()
        fp2 = _machine_fingerprint()
        assert fp1 == fp2

    def test_fingerprint_is_hex_string(self):
        from automail.billing.license import _machine_fingerprint
        fp = _machine_fingerprint()
        assert len(fp) == 32
        int(fp, 16)  # Should not raise


class TestIsLicenseRequired:
    """Tests for is_license_required()."""

    @patch("automail.billing.license.LICENSE_KEY", "")
    @patch("automail.billing.license.LICENSE_SERVER_URL", "")
    def test_not_required_when_both_empty(self):
        from automail.billing.license import is_license_required
        assert is_license_required() is False

    @patch("automail.billing.license.LICENSE_KEY", "some-key")
    @patch("automail.billing.license.LICENSE_SERVER_URL", "")
    def test_not_required_when_url_empty(self):
        from automail.billing.license import is_license_required
        assert is_license_required() is False

    @patch("automail.billing.license.LICENSE_KEY", "")
    @patch("automail.billing.license.LICENSE_SERVER_URL", "https://addin.mantly.io")
    def test_not_required_when_key_empty(self):
        from automail.billing.license import is_license_required
        assert is_license_required() is False

    @patch("automail.billing.license.LICENSE_KEY", "some-key")
    @patch("automail.billing.license.LICENSE_SERVER_URL", "https://addin.mantly.io")
    def test_required_when_both_set(self):
        from automail.billing.license import is_license_required
        assert is_license_required() is True


class TestGetLicenseStatus:
    """Tests for get_license_status()."""

    @patch("automail.billing.license.is_license_required", return_value=False)
    def test_status_when_not_required(self, _mock):
        from automail.billing.license import get_license_status
        status = get_license_status()
        assert status["required"] is False

    @patch("automail.billing.license.is_license_required", return_value=True)
    def test_status_includes_expected_keys(self, _mock):
        from automail.billing.license import get_license_status
        status = get_license_status()
        expected_keys = {"required", "valid", "message", "expiresAt", "maxUsers", "lastCheck", "withinGracePeriod"}
        assert expected_keys == set(status.keys())


class TestLicenseCache:
    """Tests for license cache persistence."""

    def test_save_and_load_cache(self, tmp_path):
        """Cache should survive save/load roundtrip."""
        import automail.billing.license as lic

        cache_path = tmp_path / "license_cache.json"
        original_path = lic._CACHE_PATH
        original_state_valid = lic._state.valid
        original_state_message = lic._state.message

        try:
            lic._CACHE_PATH = cache_path

            # Populate state and save
            lic._state.update(valid=True, message="Cached OK", expires_at="2030-06-01", max_users=5)
            lic._save_cache()

            assert cache_path.exists()
            cached = json.loads(cache_path.read_text())
            assert "data" in cached
            assert "sig" in cached
            data = cached["data"]
            assert data["valid"] is True
            assert data["message"] == "Cached OK"

            # Reset state and reload from cache
            lic._state.valid = False
            lic._state.message = ""
            lic._load_cache()

            assert lic._state.valid is True
            assert lic._state.message == "Cached OK"
            assert lic._state.expires_at == "2030-06-01"
            assert lic._state.max_users == 5
        finally:
            lic._CACHE_PATH = original_path
            lic._state.valid = original_state_valid
            lic._state.message = original_state_message

    def test_load_cache_handles_missing_file(self, tmp_path):
        """Loading from a non-existent file should not raise."""
        import automail.billing.license as lic

        original_path = lic._CACHE_PATH
        try:
            lic._CACHE_PATH = tmp_path / "nonexistent.json"
            lic._load_cache()  # Should not raise
        finally:
            lic._CACHE_PATH = original_path

    def test_load_cache_handles_corrupt_json(self, tmp_path):
        """Loading corrupt JSON should not raise."""
        import automail.billing.license as lic

        cache_path = tmp_path / "bad.json"
        cache_path.write_text("{{not json}}")

        original_path = lic._CACHE_PATH
        try:
            lic._CACHE_PATH = cache_path
            lic._load_cache()  # Should not raise
        finally:
            lic._CACHE_PATH = original_path


# ============================================================
# License validation server (SaaS side) tests
# ============================================================

class TestLicenseValidationEndpoint:
    """Tests for POST /api/license/validate (SaaS-side)."""

    def _get_client(self):
        from automail.main import app
        return TestClient(app)

    @patch("automail.api.admin.license.IS_SAAS", False)
    def test_validate_returns_404_when_not_saas(self):
        client = self._get_client()
        resp = client.post("/api/license/validate", json={
            "license_key": "abc",
            "instance_id": "xyz",
        })
        assert resp.status_code == 404

    @patch("automail.api.admin.license.IS_SAAS", True)
    def test_validate_rejects_empty_key(self):
        client = self._get_client()
        resp = client.post("/api/license/validate", json={
            "license_key": "",
            "instance_id": "xyz",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert "Missing" in body["message"]

    @patch("automail.api.admin.license.IS_SAAS", True)
    @patch("automail.api.admin.license._first", return_value=None)
    def test_validate_rejects_unknown_key(self, _mock_first):
        client = self._get_client()
        resp = client.post("/api/license/validate", json={
            "license_key": "unknown-key",
            "instance_id": "xyz",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert "Invalid" in body["message"]

    @patch("automail.api.admin.license.IS_SAAS", True)
    @patch("automail.api.admin.license._first", return_value={
        "id": "rec1", "key": "valid-key", "is_active": False,
        "expires_at": "", "instance_id": "", "max_users": None,
    })
    def test_validate_rejects_revoked_license(self, _mock_first):
        client = self._get_client()
        resp = client.post("/api/license/validate", json={
            "license_key": "valid-key",
            "instance_id": "xyz",
        })
        body = resp.json()
        assert body["valid"] is False
        assert "revoked" in body["message"].lower()

    @patch("automail.api.admin.license.IS_SAAS", True)
    @patch("automail.api.admin.license._first", return_value={
        "id": "rec1", "key": "valid-key", "is_active": True,
        "expires_at": "2020-01-01T00:00:00Z", "instance_id": "", "max_users": None,
    })
    def test_validate_rejects_expired_license(self, _mock_first):
        client = self._get_client()
        resp = client.post("/api/license/validate", json={
            "license_key": "valid-key",
            "instance_id": "xyz",
        })
        body = resp.json()
        assert body["valid"] is False
        assert "expired" in body["message"].lower()

    @patch("automail.api.admin.license.IS_SAAS", True)
    @patch("automail.api.admin.license._first", return_value={
        "id": "rec1", "key": "valid-key", "is_active": True,
        "expires_at": "", "instance_id": "machine-A", "max_users": None,
    })
    def test_validate_rejects_instance_mismatch(self, _mock_first):
        client = self._get_client()
        resp = client.post("/api/license/validate", json={
            "license_key": "valid-key",
            "instance_id": "machine-B",
        })
        body = resp.json()
        assert body["valid"] is False
        assert "different instance" in body["message"].lower()

    @patch("automail.api.admin.license.IS_SAAS", True)
    @patch("automail.api.admin.license._patch")
    @patch("automail.api.admin.license._first", return_value={
        "id": "rec1", "key": "valid-key", "is_active": True,
        "expires_at": "", "instance_id": "", "max_users": 50,
    })
    def test_validate_binds_instance_on_first_call(self, _mock_first, mock_patch):
        client = self._get_client()
        resp = client.post("/api/license/validate", json={
            "license_key": "valid-key",
            "instance_id": "new-machine",
        })
        body = resp.json()
        assert body["valid"] is True
        assert body["max_users"] == 50
        # Should have called _patch to bind the instance
        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        assert "new-machine" in str(call_args)

    @patch("automail.api.admin.license.IS_SAAS", True)
    @patch("automail.api.admin.license._first", return_value={
        "id": "rec1", "key": "valid-key", "is_active": True,
        "expires_at": "2030-12-31T00:00:00Z", "instance_id": "machine-A", "max_users": 10,
    })
    def test_validate_happy_path_bound_instance(self, _mock_first):
        client = self._get_client()
        resp = client.post("/api/license/validate", json={
            "license_key": "valid-key",
            "instance_id": "machine-A",
        })
        body = resp.json()
        assert body["valid"] is True
        assert body["expires_at"] == "2030-12-31T00:00:00Z"
        assert body["max_users"] == 10
        assert "valid" in body["message"].lower()


# ============================================================
# License admin CRUD endpoint tests
# ============================================================

class TestLicenseAdminEndpoints:
    """Tests for GET/POST/DELETE /api/admin/licenses."""

    def _get_client(self):
        from automail.main import app
        return TestClient(app)

    @patch("automail.api.admin.license.IS_SAAS", False)
    def test_list_licenses_404_when_not_saas(self):
        client = self._get_client()
        resp = client.get("/api/admin/licenses")
        assert resp.status_code == 404

    @patch("automail.api.admin.license.IS_SAAS", True)
    @patch("automail.api.admin.license._list_all", return_value=[
        {"id": "r1", "key": "key1", "tenant_name": "Tenant A", "max_users": 5,
         "expires_at": "", "is_active": True, "instance_id": "", "created": "2025-01-01"},
    ])
    def test_list_licenses_returns_records(self, _mock_list):
        client = self._get_client()
        resp = client.get("/api/admin/licenses")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["tenantName"] == "Tenant A"
        assert body[0]["key"] == "key1"

    @patch("automail.api.admin.license.IS_SAAS", True)
    @patch("automail.api.admin.license._post", return_value={"id": "new_rec"})
    def test_create_license(self, _mock_post):
        client = self._get_client()
        resp = client.post("/api/admin/licenses", json={
            "tenant_name": "New Tenant",
            "max_users": 25,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "new_rec"
        assert body["tenantName"] == "New Tenant"
        assert len(body["key"]) == 40  # secrets.token_hex(20) → 40 chars

    @patch("automail.api.admin.license.IS_SAAS", True)
    @patch("automail.api.admin.license._patch")
    def test_revoke_license(self, mock_patch):
        client = self._get_client()
        resp = client.delete("/api/admin/licenses/rec123")
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"
        mock_patch.assert_called_once()

    @patch("automail.api.admin.license.IS_SAAS", True)
    @patch("automail.api.admin.license._patch", side_effect=httpx.HTTPStatusError(
        "not found", request=MagicMock(),
        response=MagicMock(status_code=404, text="not found"),
    ))
    def test_revoke_nonexistent_license(self, _mock_patch):
        client = self._get_client()
        resp = client.delete("/api/admin/licenses/nonexistent")
        assert resp.status_code == 404


# ============================================================
# License middleware tests
# ============================================================

class TestLicenseMiddleware:
    """Tests for LicenseMiddleware request blocking."""

    def test_exempt_paths_always_pass(self):
        """Health checks and static assets are never blocked."""
        from automail.billing.license import _EXEMPT_PREFIXES
        assert "/api/health" in _EXEMPT_PREFIXES[0]
        assert any(p.startswith("/addin/") for p in _EXEMPT_PREFIXES)
        assert any(p.startswith("/assets/") for p in _EXEMPT_PREFIXES)
