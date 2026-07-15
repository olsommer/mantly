import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException


def test_feedback_stage_selection_rejects_multiple():
    from automail.api.feedback import _selected_feedback_stage

    assert _selected_feedback_stage(["response_text"]) == "response_text"
    assert _selected_feedback_stage(["response_text", "response_text"]) == "response_text"

    with pytest.raises(HTTPException) as exc:
        _selected_feedback_stage(["response_text", "intent_identification"])

    assert exc.value.status_code == 422


def test_intent_feedback_filters_same_stage(monkeypatch):
    from automail.db.pocketbase import feedback as feedback_store

    def fake_get(path, params):
        assert path == "/api/collections/feedback/records"
        assert params["perPage"] == 30
        return {
            "items": [
                {
                    "id": "f1",
                    "chat_id": "c1",
                    "rating": "dislike",
                    "affected_stages": ["response_text"],
                    "feedback_text": "response wrong",
                    "user_email": "user@example.com",
                    "created": "2026-01-01 00:00:00.000Z",
                },
                {
                    "id": "f2",
                    "chat_id": "c2",
                    "rating": "dislike",
                    "affected_stages": '["intent_identification"]',
                    "feedback_text": "intent wrong",
                    "user_email": "user@example.com",
                    "created": "2026-01-01 00:00:01.000Z",
                },
            ],
        }

    monkeypatch.setattr(feedback_store, "_get", fake_get)

    results = feedback_store.get_intent_feedback(
        "demo-intent",
        tenant_id="tenant",
        project_id="project",
        stage_filter=["response_text"],
        limit=10,
    )

    assert [item["id"] for item in results] == ["f1"]


def test_delete_intent_learnings_filters_same_stage(monkeypatch):
    from automail.db.pocketbase import feedback as feedback_store

    deleted: list[str] = []

    monkeypatch.setattr(
        feedback_store,
        "_list_all",
        lambda _collection, _filter: [
            {"id": "l1", "affected_stages": ["response_text"]},
            {"id": "l2", "affected_stages": ["intent_identification"]},
            {"id": "l3", "affected_stages": '["response_text"]'},
        ],
    )
    monkeypatch.setattr(feedback_store, "_delete", lambda path: deleted.append(path) or True)

    feedback_store.delete_intent_learnings_for_intent(
        "demo-intent",
        tenant_id="tenant",
        project_id="project",
        stage_filter=["response_text"],
    )

    assert deleted == [
        "/api/collections/intent_learnings/records/l1",
        "/api/collections/intent_learnings/records/l3",
    ]


def test_action_stage_learnings_apply_to_processing_only():
    from automail.db.pocketbase.feedback import _learning_applies_to_target

    assert _learning_applies_to_target(["action:create_claim"], "processing")
    assert not _learning_applies_to_target(["action:create_claim"], "response")


def test_get_intent_learnings_filters_project_and_stage(monkeypatch):
    from automail.db.pocketbase import feedback as feedback_store

    captured: dict[str, Any] = {}

    def fake_get(path, params):
        captured["path"] = path
        captured["params"] = params
        return {
            "items": [
                {"learning": "Use concise replies", "affected_stages": ["response_text"]},
                {"learning": "Pick the right intent", "affected_stages": ["intent_identification"]},
            ],
        }

    monkeypatch.setattr(feedback_store, "_get", fake_get)

    learnings = feedback_store.get_intent_learnings(
        "demo-intent",
        tenant_id="tenant",
        project_id="project",
        stage_filter=["response_text"],
    )

    assert learnings == ["Use concise replies"]
    assert captured["path"] == "/api/collections/intent_learnings/records"
    assert "project='project'" in captured["params"]["filter"]


def test_intent_learning_admin_records_filter_project(monkeypatch):
    from automail.db.pocketbase import feedback as feedback_store

    captured: dict[str, Any] = {}

    def fake_get(path, params):
        captured["path"] = path
        captured["filter"] = params["filter"]
        return {"items": []}

    monkeypatch.setattr(feedback_store, "_get", fake_get)

    assert feedback_store.get_intent_learnings_records(
        "demo-intent",
        tenant_id="tenant-a",
        project_id="project-a",
    ) == []
    assert captured["path"] == "/api/collections/intent_learnings/records"
    assert "intent_name='demo-intent'" in captured["filter"]
    assert "tenant='tenant-a'" in captured["filter"]
    assert "project='project-a'" in captured["filter"]


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_intent_learning_mutation_rejects_cross_project_record(monkeypatch, operation):
    from automail.db.pocketbase import feedback as feedback_store

    inspected: list[str] = []
    mutations: list[str] = []

    def fake_first(_collection, filter_str):
        inspected.append(filter_str)
        return None

    monkeypatch.setattr(feedback_store, "_first", fake_first)
    monkeypatch.setattr(feedback_store, "_patch", lambda path, _body: mutations.append(path))
    monkeypatch.setattr(feedback_store, "_delete", lambda path: mutations.append(path))

    if operation == "update":
        changed = feedback_store.update_intent_learning(
            "learning-other-project",
            "Changed",
            intent_name="demo-intent",
            tenant_id="tenant-a",
            project_id="project-a",
        )
    else:
        changed = feedback_store.delete_intent_learning(
            "learning-other-project",
            intent_name="demo-intent",
            tenant_id="tenant-a",
            project_id="project-a",
        )

    assert changed is False
    assert mutations == []
    assert "id='learning-other-project'" in inspected[0]
    assert "intent_name='demo-intent'" in inspected[0]
    assert "tenant='tenant-a'" in inspected[0]
    assert "project='project-a'" in inspected[0]


def test_delete_intent_learnings_for_feedback_is_project_scoped(monkeypatch):
    from automail.db.pocketbase import feedback as feedback_store

    captured: dict[str, str] = {}
    deleted: list[str] = []

    def fake_list_all(collection, filter_str):
        captured["collection"] = collection
        captured["filter"] = filter_str
        return [{"id": "learning-1"}]

    monkeypatch.setattr(feedback_store, "_list_all", fake_list_all)
    monkeypatch.setattr(feedback_store, "_delete", lambda path: deleted.append(path) or True)

    count = feedback_store.delete_intent_learnings_for_feedback(
        "feedback-1",
        intent_name="demo-intent",
        tenant_id="tenant-a",
        project_id="project-a",
    )

    assert count == 1
    assert captured["collection"] == "intent_learnings"
    assert "source_feedback_id='feedback-1'" in captured["filter"]
    assert "intent_name='demo-intent'" in captured["filter"]
    assert "tenant='tenant-a'" in captured["filter"]
    assert "project='project-a'" in captured["filter"]
    assert deleted == ["/api/collections/intent_learnings/records/learning-1"]


def test_delete_intent_learnings_for_feedback_fails_closed(monkeypatch):
    from automail.db.pocketbase import feedback as feedback_store

    monkeypatch.setattr(
        feedback_store,
        "_list_all",
        lambda *_args, **_kwargs: [{"id": "learning-1"}],
    )
    monkeypatch.setattr(feedback_store, "_delete", lambda *_args, **_kwargs: False)

    with pytest.raises(RuntimeError, match="Failed to remove legacy intent learning"):
        feedback_store.delete_intent_learnings_for_feedback(
            "feedback-1",
            intent_name="demo-intent",
            tenant_id="tenant-a",
            project_id="project-a",
        )


def test_feedback_message_context_sanitizes_pipeline_result():
    from automail.feedback.context import feedback_message_context

    original_email, pipeline_result = feedback_message_context({
        "messages": [
            {"role": "email", "content": "Subject: Test\n\nHello"},
            {
                "role": "response",
                "content": {
                    "email_body": "Wrong answer",
                    "tokenUsage": {"input": 10, "output": 5},
                    "rawUsage": {"debug": True},
                    "emailAttachments": [
                        {
                            "filename": "template.pdf",
                            "content_base64": "SECRET",
                        },
                    ],
                },
            },
        ],
    })

    assert original_email == "Subject: Test\n\nHello"
    assert "Wrong answer" in pipeline_result
    assert "template.pdf" in pipeline_result
    assert "tokenUsage" not in pipeline_result
    assert "rawUsage" not in pipeline_result
    assert "content_base64" not in pipeline_result
    assert "SECRET" not in pipeline_result


def test_submit_feedback_stores_evidence_without_learning_mutation(monkeypatch):
    from automail.api import feedback as feedback_api
    from automail.db.pocketbase import client as pb_client
    from automail.feedback import reflect_agent
    from automail.models import FeedbackRequest

    stored: list[dict] = []
    chat_reads: list[dict] = []
    monkeypatch.setattr(
        feedback_api,
        "get_chat",
        lambda *_args, **kwargs: chat_reads.append(kwargs) or {"id": "chat-1"},
    )
    monkeypatch.setattr(
        feedback_api,
        "store_feedback",
        lambda **kwargs: stored.append(kwargs) or "feedback-1",
    )
    monkeypatch.setattr(
        pb_client,
        "store_intent_learning",
        lambda **_kwargs: pytest.fail("ordinary feedback published a learning"),
    )
    monkeypatch.setattr(
        reflect_agent,
        "run_reflect_agent",
        lambda **_kwargs: pytest.fail("ordinary feedback invoked reflection"),
    )

    result = feedback_api.submit_feedback_for_context(
        FeedbackRequest(
            chat_id="chat-1",
            project_id="project-a",
            user="agent@example.com",
            rating="dislike",
            affected_stages=["response_text"],
            feedback_text="Response should be shorter",
        ),
        tenant_id="tenant-a",
        project_id="project-a",
        user_email="authenticated@example.com",
    )

    assert result.status == "ok"
    assert result.id == "feedback-1"
    assert stored == [{
        "chat_id": "chat-1",
        "user_email": "authenticated@example.com",
        "rating": "dislike",
        "affected_stages": ["response_text"],
        "feedback_text": "Response should be shorter",
        "tenant_id": "tenant-a",
        "project_id": "project-a",
    }]
    assert chat_reads == [{"tenant_id": "tenant-a", "project_id": "project-a"}]


def test_feedback_http_route_binds_project_membership_and_authenticated_email(monkeypatch):
    from automail.api import feedback as feedback_api
    from automail.models import FeedbackRequest, FeedbackResponse

    captured: list[dict] = []
    monkeypatch.setattr(
        feedback_api,
        "require_authenticated",
        lambda _request: SimpleNamespace(
            email="authenticated@example.com",
            tenant_id="tenant-a",
        ),
    )
    monkeypatch.setattr(
        feedback_api,
        "resolve_project_context",
        lambda _request, project_id, min_role: SimpleNamespace(
            tenant_id="tenant-a",
            project_id=project_id,
            role=min_role,
        ),
    )
    monkeypatch.setattr(
        feedback_api,
        "submit_feedback_for_context",
        lambda request, **kwargs: captured.append({"request": request, **kwargs})
        or FeedbackResponse(status="ok", id="feedback-1"),
    )

    result = asyncio.run(
        feedback_api.submit_feedback(
            FeedbackRequest(
                chat_id="chat-1",
                project_id="project-a",
                user="spoofed@example.com",
                rating="dislike",
                affected_stages=["response_text"],
                feedback_text="Wrong answer",
            ),
            SimpleNamespace(),
        )
    )

    assert result.id == "feedback-1"
    assert captured[0]["tenant_id"] == "tenant-a"
    assert captured[0]["project_id"] == "project-a"
    assert captured[0]["user_email"] == "authenticated@example.com"


def test_feedback_http_route_requires_explicit_project():
    from automail.api import feedback as feedback_api
    from automail.models import FeedbackRequest

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            feedback_api.submit_feedback(
                FeedbackRequest(
                    chat_id="chat-1",
                    user="agent@example.com",
                    rating="like",
                ),
                SimpleNamespace(),
            )
        )

    assert exc.value.status_code == 422


def test_store_feedback_derives_intent_from_same_project_chat(monkeypatch):
    from automail.db.pocketbase import feedback as feedback_store

    captured: dict[str, str] = {}
    monkeypatch.setattr(
        feedback_store,
        "_first",
        lambda collection, filter_str: captured.update(
            collection=collection,
            filter=filter_str,
        )
        or {"activated_intent": "demo-intent"},
    )
    monkeypatch.setattr(
        feedback_store,
        "_post",
        lambda _path, data: {**data, "id": "feedback-1"},
    )
    monkeypatch.setattr(feedback_store, "generate_id", lambda: "feedback-1")

    feedback_store.store_feedback(
        chat_id="chat-1",
        user_email="agent@example.com",
        rating="like",
        tenant_id="tenant-a",
        project_id="project-a",
    )

    assert captured["collection"] == "chats"
    assert "email_id='chat-1'" in captured["filter"]
    assert "tenant='tenant-a'" in captured["filter"]
    assert "project='project-a'" in captured["filter"]


def test_delete_feedback_returns_storage_failure(monkeypatch):
    from automail.db.pocketbase import feedback as feedback_store

    monkeypatch.setattr(feedback_store, "_first", lambda *_args, **_kwargs: {"id": "feedback-1"})
    monkeypatch.setattr(feedback_store, "_delete", lambda *_args, **_kwargs: False)

    assert feedback_store.delete_feedback(
        "feedback-1",
        intent_name="demo-intent",
        tenant_id="tenant-a",
        project_id="project-a",
    ) is False


def test_reflect_agent_sets_langsmith_run_name(monkeypatch):
    from automail.feedback import reflect_agent

    captured: dict[str, Any] = {}

    class FakeAgent:
        def invoke(self, payload, config=None):
            captured["payload"] = payload
            captured["config"] = config
            return {"structured_response": reflect_agent.ReflectOutput(learnings=["Use shorter replies"])}

    monkeypatch.setattr(reflect_agent, "create_agent", lambda *args, **kwargs: FakeAgent())
    monkeypatch.setattr("automail.core.config.read_config", lambda: SimpleNamespace())
    monkeypatch.setattr("automail.llm.resolve_effective_config", lambda config, tenant_id=None: config)
    monkeypatch.setattr(
        "automail.llm.create_llm",
        lambda config, timeout=60, max_retries=2: SimpleNamespace(_mantly_usage_context=None),
    )
    monkeypatch.setattr("automail.llm.usage.record_usage_from_result", lambda *args, **kwargs: None)

    learnings = reflect_agent.run_reflect_agent(
        feedback_text="Response should be shorter",
        original_email="Subject: Test\n\nHello",
        pipeline_result='{"email_body":"Wrong answer"}',
        tenant_id="tenant",
        affected_stage="response_text",
    )

    assert learnings == ["Use shorter replies"]
    assert captured["config"]["run_name"] == "feedback_reflect_agent"
    assert captured["config"]["tags"] == ["mantly", "feedback", "agent"]
    assert captured["config"]["metadata"]["tenant_id"] == "tenant"
    assert captured["config"]["metadata"]["affected_stage"] == "response_text"


def test_admin_learning_endpoints_enforce_project_scope(monkeypatch):
    from automail.api.admin import intents as intent_api
    from automail.core.auth import ProjectContext
    from automail.db.pocketbase import client as pb_client

    calls: list[tuple[str, dict]] = []
    ctx = ProjectContext(
        tenant_id="tenant-a",
        user_id="user-a",
        project_id="project-a",
        role="editor",
    )

    monkeypatch.setattr(
        "automail.billing.plans.require_feature",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pb_client,
        "get_intent_learnings_records",
        lambda name, **kwargs: calls.append((f"list:{name}", kwargs)) or [],
    )

    assert asyncio.run(intent_api.list_intent_learnings("demo-intent", ctx)) == []
    with pytest.raises(HTTPException) as update_exc:
        asyncio.run(intent_api.update_learning("demo-intent", "learning-1", {"learning": "Changed"}, ctx))
    with pytest.raises(HTTPException) as delete_exc:
        asyncio.run(intent_api.delete_learning("demo-intent", "learning-1", ctx))

    assert update_exc.value.status_code == 409
    assert delete_exc.value.status_code == 409
    assert calls == [
        ("list:demo-intent", {"tenant_id": "tenant-a", "project_id": "project-a"}),
    ]


def test_admin_delete_inert_feedback_preserves_active_learning_store(monkeypatch):
    from automail.api.admin import intents as intent_api
    from automail.core.auth import ProjectContext
    from automail.db.pocketbase import client as pb_client

    calls: list[tuple[str, dict]] = []
    ctx = ProjectContext(
        tenant_id="tenant-a",
        user_id="user-a",
        project_id="project-a",
        role="editor",
    )
    monkeypatch.setattr("automail.billing.plans.require_feature", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pb_client,
        "get_feedback_record",
        lambda fid, **kwargs: calls.append((f"get:{fid}", kwargs)) or {"id": fid},
    )
    monkeypatch.setattr(
        pb_client,
        "delete_feedback",
        lambda fid, **kwargs: calls.append((f"feedback:{fid}", kwargs)) or True,
    )
    monkeypatch.setattr(
        pb_client,
        "get_intent_learnings_records",
        lambda name, **kwargs: calls.append((f"active:{name}", kwargs)) or [],
    )
    monkeypatch.setattr(
        "automail.db.pocketbase.learning_proposals.list_learning_proposals",
        lambda **_kwargs: [],
    )

    result = asyncio.run(intent_api.delete_feedback("demo-intent", "feedback-1", ctx))

    assert result == {
        "status": "deleted",
        "id": "feedback-1",
        "learningCount": 0,
        "removedLearningCount": 0,
    }
    expected_scope = {
        "intent_name": "demo-intent",
        "tenant_id": "tenant-a",
        "project_id": "project-a",
    }
    assert calls == [
        ("get:feedback-1", expected_scope),
        (
            "active:demo-intent",
            {"tenant_id": "tenant-a", "project_id": "project-a"},
        ),
        ("feedback:feedback-1", expected_scope),
    ]


def test_admin_delete_feedback_does_not_mutate_outside_scope(monkeypatch):
    from automail.api.admin import intents as intent_api
    from automail.core.auth import ProjectContext
    from automail.db.pocketbase import client as pb_client

    ctx = ProjectContext(
        tenant_id="tenant-a",
        user_id="user-a",
        project_id="project-a",
        role="editor",
    )
    monkeypatch.setattr("automail.billing.plans.require_feature", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pb_client, "get_feedback_record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pb_client,
        "delete_intent_learnings_for_feedback",
        lambda *_args, **_kwargs: pytest.fail("must not delete learnings outside feedback scope"),
    )
    monkeypatch.setattr(
        pb_client,
        "delete_feedback",
        lambda *_args, **_kwargs: pytest.fail("must not delete feedback outside scope"),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(intent_api.delete_feedback("demo-intent", "feedback-other", ctx))

    assert exc_info.value.status_code == 404


def test_admin_delete_feedback_rejects_nonterminal_proposal_evidence(monkeypatch):
    from automail.api.admin import intents as intent_api
    from automail.core.auth import ProjectContext
    from automail.db.pocketbase import client as pb_client

    ctx = ProjectContext(
        tenant_id="tenant-a",
        user_id="user-a",
        project_id="project-a",
        role="editor",
    )
    monkeypatch.setattr("automail.billing.plans.require_feature", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pb_client, "get_feedback_record", lambda *_args, **_kwargs: {"id": "feedback-1"})
    monkeypatch.setattr(pb_client, "get_intent_learnings_records", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "automail.db.pocketbase.learning_proposals.list_learning_proposals",
        lambda **_kwargs: [
            {
                "id": "proposal-1",
                "source_feedback_id": "feedback-1",
                "status": "evaluated",
            },
        ],
    )
    monkeypatch.setattr(
        pb_client,
        "delete_feedback",
        lambda *_args, **_kwargs: pytest.fail("must preserve proposal evidence"),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(intent_api.delete_feedback("demo-intent", "feedback-1", ctx))

    assert exc_info.value.status_code == 409
