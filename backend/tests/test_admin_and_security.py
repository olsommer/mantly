"""Current admin routes, security headers, webhook validation, and auth boundaries."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import pytest

from automail.core.auth import create_token, decode_token
from automail.core.config import AdminConfig
from automail.pipeline.store import parse_intent_content

PROJECT_ID = "test-project"

VALID_INTENT_MD = """\
---
name: test-intent
description: A test intent
active: true
response:
  enabled: true
  response_rules:
    - Write a concise reply.
actions: []
---
Write a concise reply.
"""


@pytest.fixture
def isolated_project_data(monkeypatch):
    configs: dict[tuple[str, str], AdminConfig] = {}
    intents: dict[tuple[str, str], dict[str, dict]] = {}

    def source_key(source):
        return (source.project_id, source.mode)

    def fake_read_config(config_path=None):
        return configs.get(source_key(config_path), AdminConfig())

    def fake_write_config(config: AdminConfig, config_path=None):
        configs[source_key(config_path)] = config

    def fake_list_intents(source):
        return list(intents.get(source_key(source), {}).values())

    def fake_get_intent(source, name):
        return intents.get(source_key(source), {}).get(name)

    def fake_upsert_intent(source, name, content):
        fm, body = parse_intent_content(content)
        rec = {
            "name": name,
            "description": fm.get("description", ""),
            "active": fm.get("active", True),
            "require_review": fm.get("require_review", False),
            "actions": fm.get("actions") or [],
            "tools": fm.get("tools") or [],
            "response": fm.get("response") or {},
            "metadata": {},
            "content": body,
        }
        intents.setdefault(source_key(source), {})[name] = rec
        return rec

    def fake_delete_intent(source, name):
        return intents.get(source_key(source), {}).pop(name, None) is not None

    monkeypatch.setattr("automail.api.admin.config.ensure_draft_exists", lambda *args, **kwargs: None)
    monkeypatch.setattr("automail.api.admin.intents.ensure_draft_exists", lambda *args, **kwargs: None)
    monkeypatch.setattr("automail.api.admin.config.read_config", fake_read_config)
    monkeypatch.setattr("automail.api.admin.config.write_config", fake_write_config)
    monkeypatch.setattr("automail.api.admin.intents.list_project_intents", fake_list_intents)
    monkeypatch.setattr("automail.api.admin.intents.get_project_intent", fake_get_intent)
    monkeypatch.setattr("automail.api.admin.intents.upsert_project_intent", fake_upsert_intent)
    monkeypatch.setattr("automail.api.admin.intents.delete_project_intent", fake_delete_intent)
    monkeypatch.setattr("automail.api.admin.intents._list_all", lambda *args, **kwargs: [])
    monkeypatch.setattr("automail.api.admin.intents._delete", lambda *args, **kwargs: True)
    return {"configs": configs, "intents": intents}


def root_header(tenant_id: str = "tenant-a") -> dict[str, str]:
    token = create_token("root-1", "root@example.com", tenant_id, True)
    return {"Authorization": f"Bearer {token}"}


class TestProjectAdminConfig:
    @pytest.mark.no_gemini
    def test_get_project_config_returns_current_shape(self, client, isolated_project_data):
        resp = client.get(f"/api/admin/projects/{PROJECT_ID}/config")
        assert resp.status_code == 200
        data = resp.json()
        for key in (
            "orgName",
            "orgDescription",
            "llmModel",
            "llmProvider",
            "tool",
            "useCustomSecurity",
            "phishingMonitoringEnabled",
            "promptInjectionMonitoringEnabled",
        ):
            assert key in data

    @pytest.mark.no_gemini
    def test_update_project_config_roundtrip(self, client, isolated_project_data):
        resp = client.put(f"/api/admin/projects/{PROJECT_ID}/config", json={
            "orgName": "Mantly Test",
            "orgDescription": "Test organisation",
            "identityNotes": "Keep CRM payload fields in identity data.",
            "useCustomSecurity": True,
            "phishingMonitoringEnabled": True,
        })
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        data = client.get(f"/api/admin/projects/{PROJECT_ID}/config").json()
        assert data["orgName"] == "Mantly Test"
        assert data["orgDescription"] == "Test organisation"
        assert data["identityNotes"] == "Keep CRM payload fields in identity data."
        assert data["useCustomSecurity"] is True
        assert data["phishingMonitoringEnabled"] is True


class TestProjectIntents:
    @pytest.mark.no_gemini
    def test_project_intent_crud(self, client, isolated_project_data):
        base = f"/api/admin/projects/{PROJECT_ID}/intents"

        assert client.get(base).json() == []

        create = client.put(f"{base}/test-intent", json={"content": VALID_INTENT_MD})
        assert create.status_code == 200
        assert create.json() == {"status": "ok", "name": "test-intent"}

        listed = client.get(base).json()
        assert listed == [{
            "name": "test-intent",
            "description": "A test intent",
            "actions": [],
            "response": {
                "enabled": True,
                "response_rules": ["Write a concise reply."],
            },
            "active": True,
            "require_review": False,
        }]

        fetched = client.get(f"{base}/test-intent")
        assert fetched.status_code == 200
        assert "Write a concise reply" in fetched.json()["content"]

        invalid = client.put(f"{base}/bad", json={"content": "missing frontmatter"})
        assert invalid.status_code == 400

        malformed = client.put(
            f"{base}/bad-yaml",
            json={"content": '---\nname: bad-yaml\ndescription: "bad " quote"\n---\n\nBody'},
        )
        assert malformed.status_code == 400
        assert "Invalid intent YAML" in malformed.json()["detail"]

        deleted = client.delete(f"{base}/test-intent")
        assert deleted.status_code == 200
        assert deleted.json() == {"status": "deleted", "name": "test-intent"}
        assert client.get(f"{base}/test-intent").status_code == 404


class TestWebhookProxy:
    def _trigger(self, client, url: str, method: str = "POST"):
        return client.post(f"/api/admin/projects/{PROJECT_ID}/actions/trigger", json={
            "webhook": url,
            "method": method,
            "payload": {},
        })

    @pytest.mark.no_gemini
    @pytest.mark.parametrize("url", [
        "http://localhost/api",
        "http://127.0.0.1/api",
        "http://10.0.0.1/hook",
        "http://192.168.1.100/hook",
        "http://172.16.0.1/hook",
        "http://169.254.169.254/latest/meta-data/",
    ])
    def test_rejects_private_or_internal_urls(self, client, isolated_project_data, url):
        assert self._trigger(client, url).status_code == 400

    @pytest.mark.no_gemini
    def test_rejects_non_http_scheme(self, client, isolated_project_data):
        resp = self._trigger(client, "ftp://example.com/file", method="GET")
        assert resp.status_code == 400
        assert "http or https" in resp.json()["detail"].lower()

    @pytest.mark.no_gemini
    def test_rejects_host_not_in_allowlist(self, client, isolated_project_data, monkeypatch):
        monkeypatch.setenv("ALLOWED_WEBHOOK_HOSTS", "trusted.example.com")
        resp = self._trigger(client, "https://untrusted.example.com/hook")
        assert resp.status_code == 400
        assert "ALLOWED_WEBHOOK_HOSTS" in resp.json()["detail"]

    @pytest.mark.no_gemini
    def test_resolves_project_secrets_before_proxying(self, client, isolated_project_data, monkeypatch):
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def request(self, **kwargs):
                captured["request"] = kwargs
                return FakeResponse()

        monkeypatch.setattr("automail.api.admin.actions.httpx.AsyncClient", FakeAsyncClient)
        monkeypatch.setattr("automail.api.admin.actions._validate_webhook_url", lambda url: captured.setdefault("validated", url))
        monkeypatch.setattr("automail.api.admin.actions.record_action_run", lambda **kwargs: captured.setdefault("recorded", kwargs))
        monkeypatch.setattr(
            "automail.core.runtime_secrets.load_runtime_secrets",
            lambda tenant_id=None, project_id=None: {
                "ACTION_HOST": "api.example.com",
                "ACTION_TOKEN": "secret-token",
            },
        )

        resp = client.post(f"/api/admin/projects/{PROJECT_ID}/actions/trigger", json={
            "webhook": "https://{ACTION_HOST}/hook",
            "method": "POST",
            "payload": {"token": "{ACTION_TOKEN}"},
            "headers": {"Authorization": "Bearer {ACTION_TOKEN}"},
        })

        assert resp.status_code == 200
        assert captured["validated"] == "https://api.example.com/hook"
        assert captured["request"]["url"] == "https://api.example.com/hook"
        assert captured["request"]["headers"]["Authorization"] == "Bearer secret-token"
        assert captured["request"]["json"] == {"token": "secret-token"}
        assert captured["recorded"]["webhook"] == "https://{ACTION_HOST}/hook"
        assert captured["recorded"]["payload"] == {"token": "{ACTION_TOKEN}"}

    @pytest.mark.no_gemini
    def test_action_trigger_maps_query_and_body_templates(self, client, isolated_project_data, monkeypatch):
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def request(self, **kwargs):
                captured.setdefault("requests", []).append(kwargs)
                return FakeResponse()

        monkeypatch.setattr("automail.api.admin.actions.httpx.AsyncClient", FakeAsyncClient)
        monkeypatch.setattr("automail.api.admin.actions._validate_webhook_url", lambda url: None)
        monkeypatch.setattr("automail.api.admin.actions.record_action_run", lambda **kwargs: None)
        monkeypatch.setattr(
            "automail.core.runtime_secrets.load_runtime_secrets",
            lambda tenant_id=None, project_id=None: {"ACTION_TOKEN": "secret-token"},
        )

        get_resp = client.post(f"/api/admin/projects/{PROJECT_ID}/actions/trigger", json={
            "webhook": "https://api.example.com/claims/{claim_number}",
            "method": "GET",
            "payload": {"claim_number": "CLM-42", "actionLabel": "Open Claim"},
            "query": {"claim": "{claim_number}", "token": "{ACTION_TOKEN}"},
            "body": {"ignored": "{claim_number}"},
        })
        post_resp = client.post(f"/api/admin/projects/{PROJECT_ID}/actions/trigger", json={
            "webhook": "https://api.example.com/claims",
            "method": "POST",
            "payload": {"claim_number": "CLM-42", "title": "Claim CLM-42"},
            "body": {"claim": "{claim_number}", "title": "{title}", "token": "{ACTION_TOKEN}"},
        })

        assert get_resp.status_code == 200
        assert post_resp.status_code == 200
        assert captured["requests"][0]["url"] == "https://api.example.com/claims/CLM-42"
        assert captured["requests"][0]["params"] == {"claim": "CLM-42", "token": "secret-token"}
        assert "json" not in captured["requests"][0]
        assert captured["requests"][1]["json"] == {
            "claim": "CLM-42",
            "title": "Claim CLM-42",
            "token": "secret-token",
        }

    @pytest.mark.no_gemini
    def test_action_trigger_rejects_unsupported_methods(self, client, isolated_project_data, monkeypatch):
        monkeypatch.setattr("automail.api.admin.actions._validate_webhook_url", lambda url: None)

        resp = client.post(f"/api/admin/projects/{PROJECT_ID}/actions/trigger", json={
            "webhook": "https://api.example.com/claims",
            "method": "PUT",
            "payload": {"claim_number": "CLM-42"},
        })

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Action webhooks only support GET and POST"


class TestSecurityHeaders:
    @pytest.mark.no_gemini
    def test_headers_present_on_success(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "SAMEORIGIN"
        assert "strict-origin" in resp.headers.get("referrer-policy", "").lower()

    @pytest.mark.no_gemini
    def test_headers_present_on_404(self, client):
        resp = client.get("/demo/scenarios")
        assert resp.status_code == 404
        assert resp.headers.get("x-content-type-options") == "nosniff"


class TestAuthBoundaries:
    @pytest.fixture(autouse=True)
    def require_auth(self, monkeypatch):
        monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", True)
        monkeypatch.setattr("automail.api.auth.REQUIRE_AUTH", True)

    @pytest.fixture
    def project_for_root(self, monkeypatch):
        monkeypatch.setattr(
            "automail.db.pocketbase.client.get_project",
            lambda pid: {"id": pid, "tenant": "tenant-a", "name": "Test"},
        )

    @pytest.mark.no_gemini
    def test_email_endpoint_requires_bearer_token(self, client):
        resp = client.get("/api/chat/some-id")
        assert resp.status_code == 401

    @pytest.mark.no_gemini
    def test_project_admin_requires_bearer_token(self, client, isolated_project_data):
        resp = client.get(f"/api/admin/projects/{PROJECT_ID}/config")
        assert resp.status_code == 401

    @pytest.mark.no_gemini
    def test_project_admin_rejects_wrong_tenant_root(self, client, project_for_root):
        token = create_token("root-2", "other@example.com", "tenant-b", True)
        resp = client.get(
            f"/api/admin/projects/{PROJECT_ID}/config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.no_gemini
    def test_project_admin_accepts_root_jwt(self, client, isolated_project_data, project_for_root):
        resp = client.get(f"/api/admin/projects/{PROJECT_ID}/config", headers=root_header())
        assert resp.status_code == 200

    @pytest.mark.no_gemini
    def test_manifest_uses_split_saas_urls(self, client, project_for_root, monkeypatch):
        manifest_template = Path(__file__).resolve().parents[2] / "addin" / "manifest.xml"
        monkeypatch.setattr("automail.api.admin.manifest._MANIFEST_TEMPLATE_PATH", manifest_template)
        monkeypatch.setenv("PUBLIC_URL", "https://api.mantly.io")
        monkeypatch.setenv("MANIFEST_BASE_URL", "https://api.mantly.io")
        monkeypatch.setenv("ADDIN_BASE_URL", "https://addin.mantly.io")
        monkeypatch.setenv("ASSET_BASE_URL", "https://api.mantly.io")

        resp = client.get(f"/api/admin/projects/{PROJECT_ID}/manifest", headers=root_header())

        assert resp.status_code == 200
        xml = resp.text
        assert '<AppDomain>https://addin.mantly.io</AppDomain>' in xml
        assert 'SourceLocation DefaultValue="https://addin.mantly.io/"' in xml
        assert 'bt:Url id="Taskpane.Url" DefaultValue="https://addin.mantly.io/"' in xml
        assert 'IconUrl DefaultValue="https://api.mantly.io/assets/icon-64.png"' in xml
        assert "https://app.mantly.io" not in xml
        assert "ADDIN_BASE_URL" not in xml

    @pytest.mark.no_gemini
    def test_demo_tenant_root_can_download_manifest(self, client, project_for_root, monkeypatch):
        manifest_template = Path(__file__).resolve().parents[2] / "addin" / "manifest.xml"
        monkeypatch.setattr("automail.api.admin.manifest._MANIFEST_TEMPLATE_PATH", manifest_template)
        monkeypatch.setenv("IS_SAAS", "true")
        monkeypatch.setattr("automail.db.pocketbase.client.get_tenant_account_type", lambda tenant_id: "demo")

        resp = client.get(f"/api/admin/projects/{PROJECT_ID}/manifest", headers=root_header())

        assert resp.status_code == 200
        assert "ADDIN_BASE_URL" not in resp.text

    @pytest.mark.no_gemini
    def test_demo_tenant_root_cannot_manage_users(self, client, monkeypatch):
        monkeypatch.setenv("IS_SAAS", "true")
        monkeypatch.setattr("automail.db.pocketbase.client.get_tenant_account_type", lambda tenant_id: "demo")

        resp = client.get("/api/admin/users", headers=root_header())

        assert resp.status_code == 403

    @pytest.mark.no_gemini
    def test_demo_tenant_root_can_edit_intents(self, client, project_for_root, monkeypatch):
        monkeypatch.setenv("IS_SAAS", "true")
        monkeypatch.setattr("automail.db.pocketbase.client.get_tenant_account_type", lambda tenant_id: "demo")
        monkeypatch.setattr("automail.api.admin.intents.ensure_draft_exists", lambda *args, **kwargs: None)
        seen: dict[str, str] = {}

        def fake_upsert(_source, name, content):
            seen["name"] = name
            seen["content"] = content
            return {"name": name}

        monkeypatch.setattr("automail.api.admin.intents.upsert_project_intent", fake_upsert)

        resp = client.put(
            f"/api/admin/projects/{PROJECT_ID}/intents/test-intent",
            json={"content": VALID_INTENT_MD},
            headers=root_header(),
        )

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "name": "test-intent"}
        assert seen["name"] == "test-intent"

    @pytest.mark.no_gemini
    def test_demo_tenant_root_can_update_tenant_settings(self, client, monkeypatch):
        monkeypatch.setenv("IS_SAAS", "true")
        monkeypatch.setattr("automail.db.pocketbase.client.get_tenant_account_type", lambda tenant_id: "demo")
        monkeypatch.setattr("automail.db.pocketbase.client.update_tenant_settings", lambda *args, **kwargs: {
            "orgName": "Changed",
            "orgDescription": "",
            "llmProvider": "gemini",
            "llmModel": "",
            "llmApiKey": "",
            "llmCustomBaseUrl": "",
            "llmCustomModel": "",
            "phishingMonitoringEnabled": True,
            "promptInjectionMonitoringEnabled": False,
            "allowSignups": False,
        })
        monkeypatch.setattr("automail.llm.invalidate_all", lambda: None)

        resp = client.patch(
            "/api/admin/tenant/settings",
            json={"orgName": "Changed", "phishingMonitoringEnabled": True},
            headers=root_header(),
        )

        assert resp.status_code == 200
        assert resp.json()["orgName"] == "Changed"
        assert resp.json()["phishingMonitoringEnabled"] is True

    @pytest.mark.no_gemini
    def test_managed_tenant_settings_clear_llm_credentials(self, client, monkeypatch):
        seen: dict = {}
        required_features: list[str] = []

        def fake_update_tenant_settings(*args, **kwargs):
            seen.update(kwargs)
            return {
                "orgName": "",
                "orgDescription": "",
                "llmProvider": kwargs["llm_provider"],
                "llmModel": kwargs["llm_model"],
                "llmApiKey": kwargs["llm_api_key"],
                "llmCustomBaseUrl": kwargs["llm_custom_base_url"],
                "llmCustomModel": kwargs["llm_custom_model"],
                "phishingMonitoringEnabled": False,
                "promptInjectionMonitoringEnabled": False,
                "allowSignups": False,
            }

        monkeypatch.setattr(
            "automail.billing.plans.require_feature",
            lambda tenant_id, feature: required_features.append(feature),
        )
        monkeypatch.setattr("automail.db.pocketbase.client.update_tenant_settings", fake_update_tenant_settings)
        monkeypatch.setattr("automail.llm.invalidate_all", lambda: None)

        resp = client.patch(
            "/api/admin/tenant/settings",
            json={
                "llmProvider": "managed",
                "llmModel": "gemini-customer",
                "llmApiKey": "customer-key",
                "llmCustomBaseUrl": "https://llm.example.test",
                "llmCustomModel": "custom-model",
            },
            headers=root_header(),
        )

        assert resp.status_code == 200
        assert seen["llm_provider"] == "managed"
        assert seen["llm_model"] == ""
        assert seen["llm_api_key"] == ""
        assert seen["llm_custom_base_url"] == ""
        assert seen["llm_custom_model"] == ""
        assert required_features == []

    @pytest.mark.no_gemini
    def test_invalid_bearer_token_returns_401(self, client):
        resp = client.get("/api/chat/some-id", headers={"Authorization": "Bearer not.a.jwt"})
        assert resp.status_code == 401


class TestAuthExchange:
    @pytest.fixture(autouse=True)
    def require_auth(self, monkeypatch):
        monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", True)
        monkeypatch.setattr("automail.api.auth.REQUIRE_AUTH", True)

    @pytest.mark.no_gemini
    def test_login_method_returns_password_for_enabled_account(self, client, monkeypatch):
        monkeypatch.setattr("automail.api.auth.get_user_by_email", lambda email: {
            "id": "user-abc",
            "email": email,
            "password_login_enabled": True,
        })

        resp = client.post("/api/auth/login-method", json={"email": "admin@firm.com"})

        assert resp.status_code == 200
        assert resp.json() == {"method": "password"}

    @pytest.mark.no_gemini
    def test_login_method_defaults_to_code_for_unknown_or_normal_account(self, client, monkeypatch):
        monkeypatch.setattr("automail.api.auth.get_user_by_email", lambda email: None)
        unknown = client.post("/api/auth/login-method", json={"email": "missing@firm.com"})
        assert unknown.status_code == 200
        assert unknown.json() == {"method": "code"}

        monkeypatch.setattr("automail.api.auth.get_user_by_email", lambda email: {
            "id": "user-abc",
            "email": email,
            "password_login_enabled": False,
        })
        normal = client.post("/api/auth/login-method", json={"email": "user@firm.com"})
        assert normal.status_code == 200
        assert normal.json() == {"method": "code"}

    @pytest.mark.no_gemini
    def test_exchange_invalid_pb_token_returns_401(self, client, monkeypatch):
        def fail(token):
            raise httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=MagicMock(status_code=401))

        monkeypatch.setattr("automail.api.auth.validate_pb_token", fail)
        resp = client.post("/api/auth/exchange", json={"pb_token": "bad-token"})
        assert resp.status_code == 401

    @pytest.mark.no_gemini
    def test_exchange_valid_verified_user_returns_fastapi_token(self, client, monkeypatch):
        monkeypatch.setattr("automail.api.auth.IS_SAAS", True)
        monkeypatch.setattr("automail.api.auth.validate_pb_token", lambda token: {
            "record": {
                "id": "user-abc",
                "email": "admin@firm.com",
                "tenant": "tenant-xyz",
                "is_root": True,
                "verified": True,
                "must_change_password": False,
            }
        })
        monkeypatch.setattr("automail.api.auth.get_tenant_name", lambda tenant_id: "Firm")

        resp = client.post("/api/auth/exchange", json={"pb_token": "valid-pb-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "admin@firm.com"
        assert data["tenantId"] == "tenant-xyz"
        assert data["isRoot"] is True
        payload = decode_token(data["token"])
        assert payload["tenant_id"] == "tenant-xyz"

    @pytest.mark.no_gemini
    def test_exchange_unverified_saas_user_returns_403(self, client, monkeypatch):
        monkeypatch.setattr("automail.api.auth.IS_SAAS", True)
        monkeypatch.setattr("automail.api.auth.validate_pb_token", lambda token: {
            "record": {
                "id": "user-abc",
                "email": "user@firm.com",
                "tenant": "tenant-xyz",
                "is_root": False,
                "verified": False,
            }
        })

        resp = client.post("/api/auth/exchange", json={"pb_token": "valid-pb-token"})
        assert resp.status_code == 403
        assert "verify" in resp.json()["detail"].lower()
