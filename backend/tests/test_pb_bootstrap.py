import json

import httpx
import pytest

from automail.db.pocketbase.bootstrap_app_schema import AppCollectionsBootstrapResult, ensure_app_collections_schema
from automail.db.pocketbase.bootstrap_common import validate_pb_bootstrap_env
from automail.db.pocketbase.bootstrap_users import UsersSchemaBootstrapResult, ensure_users_collection_schema


def _collection_payload(*, create_rule, include_must_change_password: bool) -> dict:
    fields = [
        {"id": "email3885137012", "name": "email", "type": "email"},
        {"id": "text2222222222", "name": "name", "type": "text"},
        {"id": "text3333333333", "name": "language", "type": "text"},
        {"id": "relation1314505826", "name": "tenant", "type": "relation"},
    ]
    if include_must_change_password:
        fields.extend([
            {
                "id": "bool915273641",
                "name": "must_change_password",
                "type": "bool",
            },
            {"id": "bool1111111111", "name": "password_login_enabled", "type": "bool"},
            {"id": "text1111111111", "name": "login_code_hash", "type": "text"},
            {"id": "date1111111111", "name": "login_code_expires", "type": "date"},
            {"id": "number1111111111", "name": "login_code_attempts", "type": "number"},
        ])
    return {
        "id": "_pb_users_auth_",
        "name": "users",
        "createRule": create_rule,
        "fields": fields,
    }


class TestValidatePbBootstrapEnv:
    @pytest.mark.no_gemini
    def test_auth_disabled_allows_missing_pb_admin_credentials(self):
        validate_pb_bootstrap_env(False, pb_admin_email="", pb_admin_password="")

    @pytest.mark.no_gemini
    def test_auth_enabled_requires_pb_admin_credentials(self):
        with pytest.raises(RuntimeError, match="PB_ADMIN_EMAIL and PB_ADMIN_PASSWORD"):
            validate_pb_bootstrap_env(True, pb_admin_email="", pb_admin_password="")


class TestEnsureUsersCollectionSchema:
    @pytest.mark.no_gemini
    def test_noop_when_users_collection_is_already_current(self):
        calls: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path))
            if request.method == "POST" and request.url.path.endswith("/auth-with-password"):
                return httpx.Response(200, json={"token": "superuser-token"}, request=request)
            if request.method == "GET" and request.url.path.endswith("/_pb_users_auth_"):
                return httpx.Response(
                    200,
                    json=_collection_payload(create_rule=None, include_must_change_password=True),
                    request=request,
                )
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = ensure_users_collection_schema(
            client=client,
            pb_url="http://pb.test",
            pb_admin_email="admin@example.com",
            pb_admin_password="secret",
        )

        assert result == UsersSchemaBootstrapResult(
            updated=False,
            changed_create_rule=False,
            added_must_change_password_field=False,
        )
        assert calls == [
            ("POST", "/api/collections/_superusers/auth-with-password"),
            ("GET", "/api/collections/_pb_users_auth_"),
        ]

    @pytest.mark.no_gemini
    def test_patches_users_collection_when_rule_or_field_is_missing(self):
        patch_bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.endswith("/auth-with-password"):
                return httpx.Response(200, json={"token": "superuser-token"}, request=request)
            if request.method == "GET" and request.url.path.endswith("/_pb_users_auth_"):
                return httpx.Response(
                    200,
                    json=_collection_payload(create_rule="", include_must_change_password=False),
                    request=request,
                )
            if request.method == "PATCH" and request.url.path.endswith("/_pb_users_auth_"):
                patch_bodies.append(json.loads(request.content.decode("utf-8")))
                return httpx.Response(200, json={"status": "ok"}, request=request)
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = ensure_users_collection_schema(
            client=client,
            pb_url="http://pb.test",
            pb_admin_email="admin@example.com",
            pb_admin_password="secret",
        )

        assert result == UsersSchemaBootstrapResult(
            updated=True,
            changed_create_rule=True,
            added_must_change_password_field=True,
        )
        assert len(patch_bodies) == 1
        assert patch_bodies[0]["createRule"] is None
        assert [field["name"] for field in patch_bodies[0]["fields"]] == [
            "email",
            "name",
            "language",
            "tenant",
            "must_change_password",
            "password_login_enabled",
            "login_code_hash",
            "login_code_expires",
            "login_code_attempts",
        ]

    @pytest.mark.no_gemini
    def test_raises_when_must_change_password_has_unexpected_type(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.endswith("/auth-with-password"):
                return httpx.Response(200, json={"token": "superuser-token"}, request=request)
            if request.method == "GET" and request.url.path.endswith("/_pb_users_auth_"):
                payload = _collection_payload(create_rule=None, include_must_change_password=True)
                for field in payload["fields"]:
                    if field["name"] == "must_change_password":
                        field["type"] = "text"
                return httpx.Response(200, json=payload, request=request)
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(RuntimeError, match="unexpected type"):
            ensure_users_collection_schema(
                client=client,
                pb_url="http://pb.test",
                pb_admin_email="admin@example.com",
                pb_admin_password="secret",
            )


class TestEnsureAppCollectionsSchema:
    @pytest.mark.no_gemini
    def test_skips_when_admin_credentials_are_missing(self):
        result = ensure_app_collections_schema(
            client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500, request=request))),
            pb_url="http://pb.test",
            pb_admin_email="",
            pb_admin_password="",
        )

        assert result == AppCollectionsBootstrapResult(created_collections=[])

    @pytest.mark.no_gemini
    def test_creates_missing_app_collections(self):
        users_collection = {"id": "_pb_users_auth_", "name": "users", "fields": []}
        collections: dict[str, dict] = {
            "tenants": {"id": "tenants-id", "name": "tenants", "fields": []},
            "users": users_collection,
            "_pb_users_auth_": users_collection,
        }
        posted_payloads: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.endswith("/auth-with-password"):
                return httpx.Response(200, json={"token": "superuser-token"}, request=request)

            if request.method == "GET" and request.url.path.startswith("/api/collections/"):
                name = request.url.path.rsplit("/", 1)[-1]
                collection = collections.get(name)
                if collection is None:
                    return httpx.Response(404, json={"message": "missing"}, request=request)
                return httpx.Response(200, json=collection, request=request)

            if request.method == "POST" and request.url.path == "/api/collections":
                payload = json.loads(request.content.decode("utf-8"))
                posted_payloads.append(payload)
                collection = {"id": f"{payload['name']}-id", "name": payload["name"], "fields": payload["fields"]}
                collections[payload["name"]] = collection
                return httpx.Response(200, json=collection, request=request)

            if request.method == "PATCH" and request.url.path.startswith("/api/collections/"):
                name = request.url.path.rsplit("/", 1)[-1]
                collection = collections.get(name)
                if collection is None:
                    return httpx.Response(404, json={"message": "missing"}, request=request)
                payload = json.loads(request.content.decode("utf-8"))
                collection.update(payload)
                return httpx.Response(200, json=collection, request=request)

            raise AssertionError(f"Unexpected request: {request.method} {request.url}")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = ensure_app_collections_schema(
            client=client,
            pb_url="http://pb.test",
            pb_admin_email="admin@example.com",
            pb_admin_password="secret",
        )

        assert result == AppCollectionsBootstrapResult(
            created_collections=[
                "licenses",
                "eval_sets",
                "eval_cases",
                "eval_runs",
                "eval_results",
                "projects",
                "project_configs",
                "intent_attachments",
                "project_intents",
                "intent_actions",
                "intent_tools",
                "project_members",
                "monitor_runs",
                "email_processing_claims",
                "support_accounts",
                "support_contacts",
                "support_issues",
                "support_queues",
                "support_inbox_views",
                "support_reply_macros",
                "support_crm_connectors",
                "support_crm_cursors",
                "support_crm_sync_runs",
                "support_crm_webhook_events",
                "support_external_objects",
                "support_external_sync_runs",
                "support_messages",
                "support_outbound_messages",
                "support_delivery_runs",
                "support_launch_proof_runs",
                "support_ai_runs",
                "support_agent_messages",
                "support_action_executions",
                "support_automation_rules",
                "support_automation_runs",
                "support_issue_events",
                "support_internal_notes",
                "support_issue_assignments",
                "support_notifications",
                "support_issue_watchers",
                "support_sla_policies",
                "support_sla_events",
                "support_customer_portal_sessions",
                "support_csat_feedback",
                "support_channels",
                "support_channel_cursors",
                "support_channel_sync_runs",
                "support_channel_webhook_events",
                "support_web_chat_sessions",
                "knowledge_articles",
                "support_knowledge_gaps",
                "support_account_insights",
                "llm_usage_events",
                "feedback",
                "intent_learnings",
                "intent_learning_proposals",
            ]
        )
        assert [payload["name"] for payload in posted_payloads] == [
            "licenses",
            "eval_sets",
            "eval_cases",
            "eval_runs",
            "eval_results",
            "projects",
            "project_configs",
            "intent_attachments",
            "project_intents",
            "intent_actions",
            "intent_tools",
            "project_members",
            "monitor_runs",
            "email_processing_claims",
            "support_accounts",
            "support_contacts",
            "support_issues",
            "support_queues",
            "support_inbox_views",
            "support_reply_macros",
            "support_crm_connectors",
            "support_crm_cursors",
            "support_crm_sync_runs",
            "support_crm_webhook_events",
            "support_external_objects",
            "support_external_sync_runs",
            "support_messages",
            "support_outbound_messages",
            "support_delivery_runs",
            "support_launch_proof_runs",
            "support_ai_runs",
            "support_agent_messages",
            "support_action_executions",
            "support_automation_rules",
            "support_automation_runs",
            "support_issue_events",
            "support_internal_notes",
            "support_issue_assignments",
            "support_notifications",
            "support_issue_watchers",
            "support_sla_policies",
            "support_sla_events",
            "support_customer_portal_sessions",
            "support_csat_feedback",
            "support_channels",
            "support_channel_cursors",
            "support_channel_sync_runs",
            "support_channel_webhook_events",
            "support_web_chat_sessions",
            "knowledge_articles",
            "support_knowledge_gaps",
            "support_account_insights",
            "llm_usage_events",
            "feedback",
            "intent_learnings",
            "intent_learning_proposals",
        ]
        assert posted_payloads[0]["indexes"] == ["CREATE UNIQUE INDEX idx_licenses_key ON licenses (key)"]
        assert posted_payloads[2]["fields"][0]["collectionId"] == "eval_sets-id"
        assert posted_payloads[4]["fields"][0]["collectionId"] == "eval_runs-id"
        intent_attachments = next(payload for payload in posted_payloads if payload["name"] == "intent_attachments")
        assert any(field["name"] == "file" and field["type"] == "file" for field in intent_attachments["fields"])
        support_accounts = next(payload for payload in posted_payloads if payload["name"] == "support_accounts")
        assert any(field["name"] == "account_key" and field["required"] for field in support_accounts["fields"])
        support_contacts = next(payload for payload in posted_payloads if payload["name"] == "support_contacts")
        assert any(field["name"] == "contact_key" and field["required"] for field in support_contacts["fields"])
        email_claims = next(
            payload for payload in posted_payloads
            if payload["name"] == "email_processing_claims"
        )
        assert any(
            field["name"] == "owner_token" and field["hidden"] is True
            for field in email_claims["fields"]
        )
        assert (
            "CREATE UNIQUE INDEX idx_email_processing_claim_attempt ON "
            "email_processing_claims (project, claim_key, attempt)"
        ) in email_claims["indexes"]
        support_issues = next(payload for payload in posted_payloads if payload["name"] == "support_issues")
        assert any(field["name"] == "source_email_id" and field["required"] for field in support_issues["fields"])
        assert any(field["name"] == "project" and field["collectionId"] == "projects-id" for field in support_issues["fields"])
        assert any(field["name"] == "queue_key" and field["type"] == "text" for field in support_issues["fields"])
        assert any(field["name"] == "queue_name" and field["type"] == "text" for field in support_issues["fields"])
        llm_usage = next(payload for payload in posted_payloads if payload["name"] == "llm_usage_events")
        assert any(
            field["name"] == "duration_ms" and field["type"] == "number"
            for field in llm_usage["fields"]
        )
        assert any(
            field["name"] == "stage_execution_id" and field["type"] == "text"
            for field in llm_usage["fields"]
        )
        assert any(
            field["name"] == "usage_record_id" and field["type"] == "text"
            for field in llm_usage["fields"]
        )
        assert any(
            field["name"] == "duration_scope" and field["type"] == "text"
            for field in llm_usage["fields"]
        )
        assert any(
            field["name"] == "usage_payload_count" and field["type"] == "number"
            for field in llm_usage["fields"]
        )
        assert any(field["name"] == "metadata" and field["type"] == "json" for field in support_issues["fields"])
        support_issues_final = collections["support_issues"]
        assert any(field["name"] == "merged_into_issue" and field["collectionId"] == "support_issues-id" for field in support_issues_final["fields"])
        assert any(field["name"] == "merged_at" and field["type"] == "date" for field in support_issues_final["fields"])
        assert any(field["name"] == "metadata" and field["type"] == "json" for field in support_issues_final["fields"])
        support_queues = next(payload for payload in posted_payloads if payload["name"] == "support_queues")
        assert any(field["name"] == "queue_key" and field["required"] for field in support_queues["fields"])
        assert any(field["name"] == "name" and field["required"] for field in support_queues["fields"])
        reply_macros = next(payload for payload in posted_payloads if payload["name"] == "support_reply_macros")
        assert any(field["name"] == "title" and field["required"] for field in reply_macros["fields"])
        assert any(field["name"] == "body" and field["type"] == "editor" for field in reply_macros["fields"])
        crm_connectors = next(payload for payload in posted_payloads if payload["name"] == "support_crm_connectors")
        assert any(field["name"] == "connector_key" and field["required"] for field in crm_connectors["fields"])
        crm_cursors = next(payload for payload in posted_payloads if payload["name"] == "support_crm_cursors")
        assert any(field["name"] == "connector" and field["collectionId"] == "support_crm_connectors-id" for field in crm_cursors["fields"])
        crm_sync_runs = next(payload for payload in posted_payloads if payload["name"] == "support_crm_sync_runs")
        assert any(field["name"] == "objects_seen" and field["type"] == "number" for field in crm_sync_runs["fields"])
        crm_webhook_events = next(payload for payload in posted_payloads if payload["name"] == "support_crm_webhook_events")
        assert any(field["name"] == "event_id" and field["required"] for field in crm_webhook_events["fields"])
        assert any(field["name"] == "connector" and field["collectionId"] == "support_crm_connectors-id" for field in crm_webhook_events["fields"])
        support_messages = next(payload for payload in posted_payloads if payload["name"] == "support_messages")
        assert any(field["name"] == "issue" and field["collectionId"] == "support_issues-id" for field in support_messages["fields"])
        external_objects = next(payload for payload in posted_payloads if payload["name"] == "support_external_objects")
        assert any(field["name"] == "external_id" and field["required"] for field in external_objects["fields"])
        assert any(field["name"] == "account" and field["collectionId"] == "support_accounts-id" for field in external_objects["fields"])
        external_sync_runs = next(payload for payload in posted_payloads if payload["name"] == "support_external_sync_runs")
        assert any(field["name"] == "objects_seen" and field["type"] == "number" for field in external_sync_runs["fields"])
        assert any(field["name"] == "source_issue" and field["collectionId"] == "support_issues-id" for field in external_sync_runs["fields"])
        support_outbound = next(payload for payload in posted_payloads if payload["name"] == "support_outbound_messages")
        assert any(field["name"] == "to_address" and field["required"] for field in support_outbound["fields"])
        assert any(field["name"] == "body" and field["required"] for field in support_outbound["fields"])
        assert any(
            field["name"] == "delivery_claim_token" and field["hidden"] is True
            for field in support_outbound["fields"]
        )
        assert {field["name"] for field in support_outbound["fields"]} >= {
            "idempotency_key",
            "delivery_attempt_key",
            "delivery_claimed_at",
            "delivery_claim_expires_at",
        }
        assert (
            "CREATE UNIQUE INDEX idx_support_outbound_issue_idempotency ON "
            "support_outbound_messages (issue, idempotency_key) WHERE idempotency_key <> ''"
        ) in support_outbound["indexes"]
        delivery_runs = next(payload for payload in posted_payloads if payload["name"] == "support_delivery_runs")
        assert any(field["name"] == "sent" and field["type"] == "number" for field in delivery_runs["fields"])
        assert any(field["name"] == "result" and field["type"] == "json" for field in delivery_runs["fields"])
        launch_proof_runs = next(payload for payload in posted_payloads if payload["name"] == "support_launch_proof_runs")
        assert any(field["name"] == "actions" and field["type"] == "json" for field in launch_proof_runs["fields"])
        assert any(field["name"] == "launch_proof" and field["type"] == "json" for field in launch_proof_runs["fields"])
        support_ai_runs = next(payload for payload in posted_payloads if payload["name"] == "support_ai_runs")
        assert any(field["name"] == "run_key" and field["required"] for field in support_ai_runs["fields"])
        assert any(field["name"] == "issue" and field["collectionId"] == "support_issues-id" for field in support_ai_runs["fields"])
        support_agent_messages = next(payload for payload in posted_payloads if payload["name"] == "support_agent_messages")
        assert any(field["name"] == "role" and field["required"] for field in support_agent_messages["fields"])
        assert any(field["name"] == "run" and field["collectionId"] == "support_ai_runs-id" for field in support_agent_messages["fields"])
        assert any(field["name"] == "reply" and field["collectionId"] == "support_outbound_messages-id" for field in support_agent_messages["fields"])
        support_actions = next(payload for payload in posted_payloads if payload["name"] == "support_action_executions")
        assert any(field["name"] == "action_key" and field["required"] for field in support_actions["fields"])
        assert any(field["name"] == "label" and field["required"] for field in support_actions["fields"])
        automation_rules = next(payload for payload in posted_payloads if payload["name"] == "support_automation_rules")
        assert any(field["name"] == "trigger" and field["required"] for field in automation_rules["fields"])
        assert any(field["name"] == "actions" and field["type"] == "json" for field in automation_rules["fields"])
        automation_runs = next(payload for payload in posted_payloads if payload["name"] == "support_automation_runs")
        assert any(field["name"] == "rule" and field["collectionId"] == "support_automation_rules-id" for field in automation_runs["fields"])
        assert any(field["name"] == "issue" and field["collectionId"] == "support_issues-id" for field in automation_runs["fields"])
        support_events = next(payload for payload in posted_payloads if payload["name"] == "support_issue_events")
        assert any(field["name"] == "event_type" and field["required"] for field in support_events["fields"])
        assert any(field["name"] == "issue" and field["collectionId"] == "support_issues-id" for field in support_events["fields"])
        support_notes = next(payload for payload in posted_payloads if payload["name"] == "support_internal_notes")
        assert any(field["name"] == "body" and field["required"] for field in support_notes["fields"])
        sla_policies = next(payload for payload in posted_payloads if payload["name"] == "support_sla_policies")
        assert any(field["name"] == "first_response_minutes" and field["type"] == "number" for field in sla_policies["fields"])
        assert any(field["name"] == "resolution_minutes" and field["type"] == "number" for field in sla_policies["fields"])
        portal_sessions = next(payload for payload in posted_payloads if payload["name"] == "support_customer_portal_sessions")
        assert any(field["name"] == "token_hash" and field["required"] for field in portal_sessions["fields"])
        assert any(field["name"] == "issue" and field["collectionId"] == "support_issues-id" for field in portal_sessions["fields"])
        csat_feedback = next(payload for payload in posted_payloads if payload["name"] == "support_csat_feedback")
        assert any(field["name"] == "rating" and field["type"] == "number" for field in csat_feedback["fields"])
        assert any(field["name"] == "portal_session" and field["collectionId"] == "support_customer_portal_sessions-id" for field in csat_feedback["fields"])
        support_channels = next(payload for payload in posted_payloads if payload["name"] == "support_channels")
        assert any(field["name"] == "channel_key" and field["required"] for field in support_channels["fields"])
        channel_cursors = next(payload for payload in posted_payloads if payload["name"] == "support_channel_cursors")
        assert any(field["name"] == "cursor_key" and field["required"] for field in channel_cursors["fields"])
        assert any(field["name"] == "channel" and field["collectionId"] == "support_channels-id" for field in channel_cursors["fields"])
        sync_runs = next(payload for payload in posted_payloads if payload["name"] == "support_channel_sync_runs")
        assert any(field["name"] == "channel" and field["collectionId"] == "support_channels-id" for field in sync_runs["fields"])
        assert any(field["name"] == "result" and field["type"] == "json" for field in sync_runs["fields"])
        channel_webhook_events = next(payload for payload in posted_payloads if payload["name"] == "support_channel_webhook_events")
        assert any(field["name"] == "event_id" and field["required"] for field in channel_webhook_events["fields"])
        assert any(field["name"] == "outbound_message" and field["collectionId"] == "support_outbound_messages-id" for field in channel_webhook_events["fields"])
        web_chat_sessions = next(payload for payload in posted_payloads if payload["name"] == "support_web_chat_sessions")
        assert any(field["name"] == "session_key" and field["required"] for field in web_chat_sessions["fields"])
        assert any(field["name"] == "issue" and field["collectionId"] == "support_issues-id" for field in web_chat_sessions["fields"])
        knowledge_articles = next(payload for payload in posted_payloads if payload["name"] == "knowledge_articles")
        assert any(field["name"] == "title" and field["required"] for field in knowledge_articles["fields"])
        knowledge_gaps = next(payload for payload in posted_payloads if payload["name"] == "support_knowledge_gaps")
        assert any(field["name"] == "gap_key" and field["required"] for field in knowledge_gaps["fields"])
        assert any(field["name"] == "issue" and field["collectionId"] == "support_issues-id" for field in knowledge_gaps["fields"])
        account_insights = next(payload for payload in posted_payloads if payload["name"] == "support_account_insights")
        assert any(field["name"] == "account" and field["collectionId"] == "support_accounts-id" for field in account_insights["fields"])
        assert any(field["name"] == "insight_key" and field["required"] for field in account_insights["fields"])
        intent_learnings = next(payload for payload in posted_payloads if payload["name"] == "intent_learnings")
        assert any(field["name"] == "affected_stages" and field["type"] == "json" for field in intent_learnings["fields"])
        learning_proposals = next(
            payload for payload in posted_payloads
            if payload["name"] == "intent_learning_proposals"
        )
        assert any(
            field["name"] == "eval_case_hash" and field["type"] == "text"
            for field in learning_proposals["fields"]
        )
        assert any(
            field["name"] == "eval_run" and field["type"] == "text"
            for field in learning_proposals["fields"]
        )
