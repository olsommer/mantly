"""Focused tests for tenant isolation and authz boundaries."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi import HTTPException

from automail.api.process import _email_thread_metadata, _resolve_process_project_id
from automail.core.auth import TokenPayload, create_token, decode_token
from automail.models import Email, ProcessEmailRequest


def auth_header(
    *,
    user_id: str = "user-1",
    email: str = "user@example.com",
    tenant_id: str = "tenant-a",
    is_root: bool = False,
) -> dict[str, str]:
    token = create_token(user_id, email, tenant_id, is_root)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_enabled(monkeypatch):
    monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", True)
    monkeypatch.setattr("automail.api.auth.REQUIRE_AUTH", True)


@pytest.mark.no_gemini
def test_create_token_roundtrip_preserves_tenant_and_admin_claims():
    token = create_token(
        "user-123",
        "owner@example.com",
        "tenant-123",
        True,
        is_platform_admin=True,
        tenant_account_type="demo",
    )
    payload = decode_token(token)

    assert payload["sub"] == "user-123"
    assert payload["email"] == "owner@example.com"
    assert payload["tenant_id"] == "tenant-123"
    assert payload["is_root"] is True
    assert payload["is_platform_admin"] is True
    assert payload["tenant_account_type"] == "demo"


@pytest.mark.no_gemini
def test_exchange_token_returns_jwt_with_expected_claims(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.auth.validate_pb_token",
        lambda token: {
            "record": {
                "id": "pb-user-1",
                "email": "admin@example.com",
                "tenant": "tenant-a",
                "is_root": True,
                "verified": True,
                "must_change_password": True,
            }
        },
    )
    monkeypatch.setattr("automail.api.auth.get_tenant_name", lambda tenant_id: "Tenant A")

    response = client.post("/api/auth/exchange", json={"pb_token": "pb.jwt"})

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "admin@example.com"
    assert data["tenantId"] == "tenant-a"
    assert data["isRoot"] is True
    assert data["mustChangePassword"] is True

    payload = decode_token(data["token"])
    assert payload["sub"] == "pb-user-1"
    assert payload["email"] == "admin@example.com"
    assert payload["tenant_id"] == "tenant-a"
    assert payload["is_root"] is True


@pytest.mark.no_gemini
def test_exchange_token_rejects_users_without_tenant(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.auth.validate_pb_token",
        lambda token: {
            "record": {
                "id": "pb-user-1",
                "email": "user@example.com",
                "tenant": "",
                "is_root": False,
                "must_change_password": False,
            }
        },
    )

    response = client.post("/api/auth/exchange", json={"pb_token": "pb.jwt"})

    assert response.status_code == 400
    assert "no associated tenant" in response.json()["detail"].lower()


@pytest.mark.no_gemini
def test_admin_users_requires_auth_header(client, auth_enabled):
    response = client.get("/api/admin/users")

    assert response.status_code == 401


@pytest.mark.no_gemini
def test_admin_users_rejects_non_admin(client, auth_enabled):
    response = client.get(
        "/api/admin/users",
        headers=auth_header(is_root=False, tenant_id="tenant-a"),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Root access required"


@pytest.mark.no_gemini
def test_admin_users_lists_only_requesting_tenant(client, auth_enabled, monkeypatch):
    seen: list[str] = []

    def fake_list_tenant_users(tenant_id: str):
        seen.append(tenant_id)
        return [{"id": "u-1", "email": "admin@tenant-a.test"}]

    monkeypatch.setattr("automail.api.admin.users.list_tenant_users", fake_list_tenant_users)

    response = client.get(
        "/api/admin/users",
        headers=auth_header(is_root=True, tenant_id="tenant-a"),
    )

    assert response.status_code == 200
    assert response.json() == [{"id": "u-1", "email": "admin@tenant-a.test"}]
    assert seen == ["tenant-a"]


@pytest.mark.no_gemini
def test_current_user_profile_includes_and_updates_name(client, auth_enabled, monkeypatch):
    patched: dict[str, object] = {}

    monkeypatch.setattr(
        "automail.api.admin.users.get_user_record",
        lambda user_id: {
            "id": user_id,
            "email": "admin@tenant-a.test",
            "tenant": "tenant-a",
            "name": "Old Name",
            "default_project": "",
        },
    )
    monkeypatch.setattr("automail.api.admin.users.get_user_projects", lambda user_id: [])
    monkeypatch.setattr(
        "automail.db.pocketbase.client.get_tenant_settings",
        lambda tenant_id: {"addinPrimaryColor": "#111111"},
    )
    monkeypatch.setattr(
        "automail.api.admin.users.patch_user_record",
        lambda user_id, data: patched.update({"user_id": user_id, "data": data}) or data,
    )

    headers = auth_header(
        user_id="user-1",
        email="admin@tenant-a.test",
        is_root=True,
        tenant_id="tenant-a",
    )

    profile = client.get("/api/admin/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["name"] == "Old Name"
    assert profile.json()["language"] == "en"

    update = client.put("/api/admin/me", headers=headers, json={"name": "New Name", "language": "de"})
    assert update.status_code == 200
    assert update.json()["name"] == "New Name"
    assert update.json()["language"] == "de"
    assert patched == {"user_id": "user-1", "data": {"name": "New Name", "language": "de"}}


@pytest.mark.no_gemini
def test_create_user_uses_tenant_from_admin_jwt(client, auth_enabled, monkeypatch):
    called: dict[str, object] = {}

    def fake_create_pb_user(email: str, password: str, tenant_id: str, is_root: bool = False):
        called.update(
            {
                "email": email,
                "password": password,
                "tenant_id": tenant_id,
                "is_root": is_root,
            }
        )
        return {"id": "user-2", "email": email}

    monkeypatch.setattr("automail.api.admin.users.create_pb_user", fake_create_pb_user)
    monkeypatch.setattr("automail.billing.config.IS_SAAS", False)

    response = client.post(
        "/api/admin/users",
        headers=auth_header(is_root=True, tenant_id="tenant-a"),
        json={
            "email": "new.user@example.com",
            "password": "InitialUser123!",
            "isAdmin": True,
            "tenant": "tenant-b",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"id": "user-2", "email": "new.user@example.com"}
    assert called == {
        "email": "new.user@example.com",
        "password": "InitialUser123!",
        "tenant_id": "tenant-a",
        "is_root": True,
    }


@pytest.mark.no_gemini
def test_delete_user_rejects_cross_tenant_target(client, auth_enabled, monkeypatch):
    deleted: list[str] = []

    monkeypatch.setattr(
        "automail.api.admin.users.get_user_record",
        lambda user_id: {"id": user_id, "tenant": "tenant-b"},
    )
    monkeypatch.setattr("automail.api.admin.users.delete_pb_user", lambda user_id: deleted.append(user_id))

    response = client.delete(
        "/api/admin/users/user-foreign",
        headers=auth_header(is_root=True, tenant_id="tenant-a"),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"
    assert deleted == []


@pytest.mark.no_gemini
def test_delete_user_allows_same_tenant_target(client, auth_enabled, monkeypatch):
    deleted: list[str] = []

    monkeypatch.setattr(
        "automail.api.admin.users.get_user_record",
        lambda user_id: {"id": user_id, "tenant": "tenant-a"},
    )
    monkeypatch.setattr("automail.api.admin.users.delete_pb_user", lambda user_id: deleted.append(user_id))

    response = client.delete(
        "/api/admin/users/user-local",
        headers=auth_header(is_root=True, tenant_id="tenant-a"),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}
    assert deleted == ["user-local"]


@pytest.mark.no_gemini
def test_pb_client_get_chat_adds_tenant_filter(monkeypatch):
    captured: dict[str, str] = {}

    def fake_first(collection: str, filter_str: str):
        captured["collection"] = collection
        captured["filter"] = filter_str
        return {
            "id": "rec-1",
            "email_id": "chat-1",
            "messages": [],
            "members": [],
            "tenant": "tenant-a",
        }

    monkeypatch.setattr("automail.db.pocketbase.chats._first", fake_first)

    from automail.db.pocketbase.client import get_chat

    chat = get_chat("chat-1", tenant_id="tenant-a")

    assert chat is not None
    assert chat["id"] == "chat-1"
    assert captured == {
        "collection": "chats",
        "filter": "email_id='chat-1' && tenant='tenant-a'",
    }


@pytest.mark.no_gemini
def test_pb_client_get_chat_adds_project_filter(monkeypatch):
    captured: dict[str, str] = {}

    def fake_first(collection: str, filter_str: str):
        captured["collection"] = collection
        captured["filter"] = filter_str
        return {
            "id": "rec-1",
            "email_id": "chat-1",
            "messages": [],
            "members": [],
            "tenant": "tenant-a",
            "project": "project-a",
        }

    monkeypatch.setattr("automail.db.pocketbase.chats._first", fake_first)

    from automail.db.pocketbase.client import get_chat

    chat = get_chat("chat-1", tenant_id="tenant-a", project_id="project-a")

    assert chat is not None
    assert chat["id"] == "chat-1"
    assert captured == {
        "collection": "chats",
        "filter": "email_id='chat-1' && tenant='tenant-a' && project='project-a'",
    }


@pytest.mark.no_gemini
def test_pb_client_get_chats_scopes_records_to_tenant(monkeypatch):
    captured: dict[str, str] = {}

    def fake_list_all(collection: str, filter_str: str = "", sort: str = "-created", per_page: int = 200):
        captured["collection"] = collection
        captured["filter"] = filter_str
        return [
            {
                "id": "rec-1",
                "email_id": "chat-1",
                "creator": "agent@example.com",
                "members": ["user@example.com"],
                "requires_human": True,
                "status": "analyzed",
                "subject": "Tenant A chat",
                "from_address": "client@example.com",
            },
            {
                "id": "rec-2",
                "email_id": "chat-2",
                "creator": "other@example.com",
                "members": ["someone-else@example.com"],
                "requires_human": False,
                "status": "analyzed",
                "subject": "Ignored chat",
                "from_address": "other@example.com",
            },
        ]

    monkeypatch.setattr("automail.db.pocketbase.chats._list_all", fake_list_all)

    from automail.db.pocketbase.client import get_chats

    chats = get_chats("user@example.com", tenant_id="tenant-a")

    assert captured == {"collection": "chats", "filter": "tenant='tenant-a'"}
    assert chats == [
        {
            "id": "chat-1",
            "subject": "Tenant A chat",
            "from": "client@example.com",
            "requiresHuman": True,
        }
    ]


@pytest.mark.no_gemini
def test_pb_client_get_analytics_scopes_by_tenant(monkeypatch):
    captured: dict[str, str] = {}

    def fake_list_all(collection: str, filter_str: str = "", sort: str = "-created", per_page: int = 200):
        captured["collection"] = collection
        captured["filter"] = filter_str
        return [
            {"requires_human": True, "activated_intent": "intent-a"},
            {"requires_human": False, "activated_intent": "intent-a"},
            {"requires_human": False, "activated_intent": None},
        ]

    monkeypatch.setattr("automail.db.pocketbase.chats._list_all", fake_list_all)

    from automail.db.pocketbase.client import get_analytics

    analytics = get_analytics(tenant_id="tenant-a")

    assert captured == {"collection": "chats", "filter": "tenant='tenant-a'"}
    assert analytics["totalEmails"] == 3
    assert analytics["intentMatched"] == 2
    assert analytics["requiresHuman"] == 1
    assert analytics["topIntents"] == [{"intent": "intent-a", "count": 2}]


@pytest.mark.no_gemini
def test_pb_client_list_tenant_users_scopes_by_tenant(monkeypatch):
    captured: dict[str, str] = {}

    def fake_list_all(collection: str, filter_str: str = "", sort: str = "-created", per_page: int = 200):
        captured["collection"] = collection
        captured["filter"] = filter_str
        captured["sort"] = sort
        return [
            {
                "id": "user-1",
                "email": "member@tenant-a.test",
                "is_root": True,
                "must_change_password": False,
                "created": "2026-03-13 10:00:00.000Z",
            }
        ]

    monkeypatch.setattr("automail.db.pocketbase.users._list_all", fake_list_all)

    from automail.db.pocketbase.client import list_tenant_users

    users = list_tenant_users("tenant-a")

    assert captured == {
        "collection": "users",
        "filter": "tenant='tenant-a'",
        "sort": "-created",
    }
    assert users == [
            {
                "id": "user-1",
                "email": "member@tenant-a.test",
                "name": "",
                "language": "en",
                "isAdmin": True,
                "isRoot": True,
            "mustChangePassword": False,
            "passwordLoginEnabled": False,
            "defaultProject": None,
            "created": "2026-03-13 10:00:00.000Z",
        }
    ]


@pytest.mark.no_gemini
def test_process_email_passes_tenant_to_pipeline(client, auth_enabled, monkeypatch):
    seen: dict[str, str | None] = {}

    class DummyPipelineResult:
        identity_result = None
        intent_result = None
        phishing_result = None
        prompt_injection_result = None
        token_usage = {}

        class AgentResponse:
            response_text = "Reply"
            activated_intent = None
            requires_human = True
            requires_human_reason = None
            response_attachments = []
            generated_attachments = []

        agent_response = AgentResponse()

    monkeypatch.setattr("automail.api.process.get_chat", lambda email_id, tenant_id=None, project_id=None: None)
    monkeypatch.setattr("automail.api.process.get_user_default_project", lambda user_id: None)
    monkeypatch.setattr("automail.api.process.get_user_projects", lambda user_id: [])
    monkeypatch.setattr("automail.api.process.parse_email_attachments", lambda email: {})
    monkeypatch.setattr("automail.api.process.load_attachment_files", lambda result, intents_dir=None: [])

    def fake_run_pipeline(
        email,
        parsed_attachments=None,
        creator=None,
        tenant_id=None,
        project_id=None,
        config_source=None,
    ):
        seen["tenant_id"] = tenant_id
        return DummyPipelineResult()

    monkeypatch.setattr("automail.api.process.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("automail.api.process.store_email_analysis", lambda *args, **kwargs: "rec-1")

    response = client.post(
        "/api/process",
        headers=auth_header(is_root=False, tenant_id="tenant-a"),
        json={
            "email": {
                "id": "email-1",
                "subject": "Subject",
                "fromAddress": "client@example.com",
                "body": "Hello",
                "attachments": [],
            },
            "action": "respond",
            "creator": "user@example.com",
        },
    )

    assert response.status_code == 200
    assert seen == {"tenant_id": "tenant-a"}


def test_email_thread_metadata_keeps_attachment_metadata():
    email = Email(
        id="email-1",
        subject="Subject",
        from_address="client@example.com",
        body="Hello",
        attachments=[
            {
                "filename": "contract.pdf",
                "base64": "Y29udHJhY3Q=",
            },
            {
                "filename": "screenshot.png",
                "base64": "data:image/png;base64,cG5n",
            },
        ],
    )

    metadata = _email_thread_metadata(email)

    assert metadata["attachments"] == [
        {"filename": "contract.pdf", "size": 8},
        {"filename": "screenshot.png", "contentType": "image/png", "size": 3},
    ]


@pytest.mark.no_gemini
def test_process_project_resolution_prefers_explicit_project(monkeypatch):
    monkeypatch.setattr(
        "automail.api.process.get_user_projects",
        lambda user_id: [
            {"id": "project-a", "name": "A"},
            {"id": "project-b", "name": "B"},
        ],
    )
    monkeypatch.setattr("automail.api.process.get_user_default_project", lambda user_id: "project-a")

    body = ProcessEmailRequest(
        email=Email(id="email-1", subject="Subject", from_address="client@example.com", body="Hello", attachments=[]),
        creator="user@example.com",
        project_id="project-b",
    )
    payload = TokenPayload("user-1", "user@example.com", "tenant-a", False)

    assert _resolve_process_project_id(body, payload) == "project-b"


@pytest.mark.no_gemini
def test_process_project_resolution_rejects_inaccessible_project(monkeypatch):
    monkeypatch.setattr(
        "automail.api.process.get_user_projects",
        lambda user_id: [{"id": "project-a", "name": "A"}],
    )

    body = ProcessEmailRequest(
        email=Email(id="email-1", subject="Subject", from_address="client@example.com", body="Hello", attachments=[]),
        creator="user@example.com",
        project_id="project-b",
    )
    payload = TokenPayload("user-1", "user@example.com", "tenant-a", False)

    with pytest.raises(HTTPException) as exc:
        _resolve_process_project_id(body, payload)

    assert exc.value.status_code == 403


@pytest.mark.no_gemini
def test_process_project_resolution_allows_root_explicit_project(monkeypatch):
    monkeypatch.setattr("automail.api.process.get_user_projects", lambda user_id: [])
    monkeypatch.setattr(
        "automail.api.process.get_project",
        lambda project_id: {"id": project_id, "tenant": "tenant-a"},
    )

    body = ProcessEmailRequest(
        email=Email(id="email-1", subject="Subject", from_address="client@example.com", body="Hello", attachments=[]),
        creator="root@example.com",
        project_id="project-b",
    )
    payload = TokenPayload("root-1", "root@example.com", "tenant-a", True)

    assert _resolve_process_project_id(body, payload) == "project-b"


@pytest.mark.no_gemini
def test_process_project_resolution_uses_default_as_fallback(monkeypatch):
    monkeypatch.setattr(
        "automail.api.process.get_user_projects",
        lambda user_id: [
            {"id": "project-a", "name": "A"},
            {"id": "project-b", "name": "B"},
        ],
    )
    monkeypatch.setattr("automail.api.process.get_user_default_project", lambda user_id: "project-a")

    body = ProcessEmailRequest(
        email=Email(id="email-1", subject="Subject", from_address="client@example.com", body="Hello", attachments=[]),
        creator="user@example.com",
    )
    payload = TokenPayload("user-1", "user@example.com", "tenant-a", False)

    assert _resolve_process_project_id(body, payload) == "project-a"
