"""PocketBase application collection schema bootstrap."""

import logging
from dataclasses import dataclass

import httpx

from automail.db.pocketbase.bootstrap_common import (
    _USERS_COLLECTION_ID,
    PB_ADMIN_EMAIL,
    PB_ADMIN_PASSWORD,
    PB_URL,
    _authenticate_superuser,
    _get_collection,
)
from automail.db.pocketbase.bootstrap_schema_fields import (
    _base_collection_payload,
    _bool_field,
    _created_field,
    _date_field,
    _editor_field,
    _ensure_collection,
    _ensure_field_on_collection,
    _ensure_field_options_on_collection,
    _file_field,
    _json_field,
    _number_field,
    _relation_field,
    _relation_field_cascade,
    _text_field,
    _updated_field,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppCollectionsBootstrapResult:
    created_collections: list[str]


def ensure_app_collections_schema(
    *,
    client: httpx.Client | None = None,
    pb_url: str | None = None,
    pb_admin_email: str | None = None,
    pb_admin_password: str | None = None,
) -> AppCollectionsBootstrapResult:
    """Ensure optional admin features have the PB collections they require.

    PB migrations are applied when PocketBase starts. In long-running local or
    on-prem instances, new migration files may exist while the current data dir
    is still missing the corresponding collections. Creating missing collections
    here keeps the backend usable without requiring a manual PB restart first.
    """
    resolved_pb_url = (pb_url or PB_URL).rstrip("/")
    resolved_email = (pb_admin_email if pb_admin_email is not None else PB_ADMIN_EMAIL).strip()
    resolved_password = pb_admin_password if pb_admin_password is not None else PB_ADMIN_PASSWORD

    if not resolved_email or not resolved_password:
        logger.info("Skipping PocketBase app collection bootstrap: admin credentials not configured")
        return AppCollectionsBootstrapResult(created_collections=[])

    created: list[str] = []

    with httpx.Client(timeout=10.0) if client is None else client as http_client:
        token = _authenticate_superuser(
            http_client,
            resolved_pb_url,
            resolved_email,
            resolved_password,
        )

        tenants = _get_collection(http_client, resolved_pb_url, token, "tenants")
        if tenants is None:
            raise RuntimeError("PocketBase tenants collection is required before app collection bootstrap.")
        tenants_id = tenants["id"]

        licenses_payload = _base_collection_payload(
            "licenses",
            [
                _text_field("key", required=True),
                _text_field("tenant_name", required=True),
                _number_field("max_users"),
                _date_field("expires_at"),
                _bool_field("is_active"),
                _text_field("instance_id"),
                _text_field("subscription_id"),
                _created_field(),
                _updated_field(),
            ],
            indexes=["CREATE UNIQUE INDEX idx_licenses_key ON licenses (key)"],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, licenses_payload)
        if was_created:
            created.append("licenses")

        eval_sets_payload = _base_collection_payload(
            "eval_sets",
            [
                _relation_field("tenant", tenants_id),
                _text_field("name", required=True),
                _text_field("description"),
                _created_field(),
                _updated_field(),
            ],
        )
        eval_sets, was_created = _ensure_collection(http_client, resolved_pb_url, token, eval_sets_payload)
        if was_created:
            created.append("eval_sets")
        eval_sets_id = eval_sets["id"]

        eval_cases_payload = _base_collection_payload(
            "eval_cases",
            [
                _relation_field("eval_set", eval_sets_id, required=True),
                _text_field("name", required=True),
                _text_field("email_subject", required=True),
                _text_field("email_from", required=True),
                _editor_field("email_body", required=True),
                _json_field("email_attachments"),
                _bool_field("expected_customer_found"),
                _json_field("expected_customer_data"),
                _bool_field("expected_intent_matched"),
                _text_field("expected_intent_name"),
                _json_field("expected_actions"),
                _bool_field("expected_requires_human"),
                _editor_field("expected_response"),
                _created_field(),
                _updated_field(),
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, eval_cases_payload)
        if was_created:
            created.append("eval_cases")

        eval_runs_payload = _base_collection_payload(
            "eval_runs",
            [
                _relation_field("eval_set", eval_sets_id, required=True),
                _relation_field("tenant", tenants_id),
                _text_field("status", required=True),
                _date_field("started_at"),
                _date_field("completed_at"),
                _json_field("summary"),
                _created_field(),
                _updated_field(),
            ],
        )
        eval_runs, was_created = _ensure_collection(http_client, resolved_pb_url, token, eval_runs_payload)
        if was_created:
            created.append("eval_runs")
        eval_runs_id = eval_runs["id"]

        eval_cases = _get_collection(http_client, resolved_pb_url, token, "eval_cases")
        if eval_cases is None:
            raise RuntimeError("PocketBase eval_cases collection was not created.")
        eval_cases_id = eval_cases["id"]

        eval_results_payload = _base_collection_payload(
            "eval_results",
            [
                _relation_field("eval_run", eval_runs_id, required=True),
                _relation_field("eval_case", eval_cases_id, required=True),
                _text_field("status", required=True),
                _json_field("pipeline_output"),
                _number_field("identity_score"),
                _editor_field("identity_reasoning"),
                _number_field("intent_score"),
                _editor_field("intent_reasoning"),
                _number_field("actions_score"),
                _editor_field("actions_reasoning"),
                _number_field("response_score"),
                _editor_field("response_reasoning"),
                _number_field("overall_score"),
                _text_field("error"),
                _created_field(),
                _updated_field(),
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, eval_results_payload)
        if was_created:
            created.append("eval_results")

        # ── Projects & RBAC ────────────────────────────────────────────────

        # projects collection
        projects_payload = _base_collection_payload(
            "projects",
            [
                _text_field("name", required=True),
                _text_field("description"),
                _relation_field_cascade("tenant", tenants_id, required=True),
                _created_field(),
                _updated_field(),
            ],
        )
        projects, was_created = _ensure_collection(http_client, resolved_pb_url, token, projects_payload)
        if was_created:
            created.append("projects")
        projects_id = projects["id"]

        project_configs_payload = _base_collection_payload(
            "project_configs",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("mode", required=True),
                _json_field("config"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_project_configs_project_mode ON project_configs (project, mode)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, project_configs_payload)
        if was_created:
            created.append("project_configs")

        intent_attachments_payload = _base_collection_payload(
            "intent_attachments",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("intent", required=True),
                _text_field("filename", required=True),
                _text_field("content_type"),
                _number_field("size"),
                _file_field("file", required=True),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_intent_attachments_project_intent_filename ON intent_attachments (project, intent, filename)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, intent_attachments_payload)
        if was_created:
            created.append("intent_attachments")
        _ensure_field_options_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "intent_attachments",
            _file_field("file", required=True),
            {"protected", "maxSelect", "maxSize"},
        )

        project_intents_payload = _base_collection_payload(
            "project_intents",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("mode", required=True),
                _text_field("name", required=True),
                _text_field("description"),
                _bool_field("active"),
                _bool_field("require_review"),
                _json_field("response"),
                _json_field("metadata"),
                _editor_field("content"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_project_intents_project_mode_name ON project_intents (project, mode, name)",
            ],
        )
        project_intents, was_created = _ensure_collection(http_client, resolved_pb_url, token, project_intents_payload)
        if was_created:
            created.append("project_intents")
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "project_intents",
            _json_field("metadata"),
        )
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "project_intents",
            _json_field("response"),
        )

        intent_actions_payload = _base_collection_payload(
            "intent_actions",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("intent", project_intents["id"], required=True),
                _text_field("type", required=True),
                _text_field("label"),
                _json_field("config"),
                _bool_field("enabled"),
                _number_field("sort_order"),
                _created_field(),
                _updated_field(),
            ],
            indexes=["CREATE INDEX idx_intent_actions_intent_order ON intent_actions (intent, sort_order)"],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, intent_actions_payload)
        if was_created:
            created.append("intent_actions")

        intent_tools_payload = _base_collection_payload(
            "intent_tools",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("intent", project_intents["id"], required=True),
                _text_field("name", required=True),
                _text_field("description"),
                _text_field("method"),
                _text_field("url_template"),
                _json_field("headers"),
                _json_field("body"),
                _json_field("input_schema"),
                _json_field("file_config"),
                _bool_field("enabled"),
                _number_field("sort_order"),
                _created_field(),
                _updated_field(),
            ],
            indexes=["CREATE INDEX idx_intent_tools_intent_order ON intent_tools (intent, sort_order)"],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, intent_tools_payload)
        if was_created:
            created.append("intent_tools")
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "intent_tools",
            _json_field("file_config"),
        )

        # project_members collection
        users = _get_collection(http_client, resolved_pb_url, token, "users")
        if users is None:
            raise RuntimeError("PocketBase users collection is required before projects bootstrap.")
        users_id = users["id"]

        project_members_payload = _base_collection_payload(
            "project_members",
            [
                _relation_field_cascade("user", users_id, required=True),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("role", required=True),
                _created_field(),
                _updated_field(),
            ],
            indexes=["CREATE UNIQUE INDEX idx_project_members_unique ON project_members (user, project)"],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, project_members_payload)
        if was_created:
            created.append("project_members")

        # Ensure role fields on users collection
        for field_def in (
            _bool_field("is_root"),
            _bool_field("is_platform_admin"),
        ):
            _ensure_field_on_collection(
                http_client, resolved_pb_url, token,
                _USERS_COLLECTION_ID,
                field_def,
            )

        # Ensure default_project field on users collection
        _ensure_field_on_collection(
            http_client, resolved_pb_url, token,
            _USERS_COLLECTION_ID,
            _relation_field("default_project", projects_id),
        )

        # Ensure project relation on existing collections
        project_relation = _relation_field("project", projects_id)
        for col_name in ("chats", "eval_sets", "eval_runs"):
            _ensure_field_on_collection(
                http_client, resolved_pb_url, token,
                col_name,
                project_relation,
            )

        monitor_runs_payload = _base_collection_payload(
            "monitor_runs",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("source", required=True),
                _text_field("status", required=True),
                _date_field("started_at"),
                _date_field("completed_at"),
                _number_field("duration_ms"),
                _text_field("user_email"),
                _json_field("input"),
                _json_field("output"),
                _json_field("actions"),
                _text_field("error"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_monitor_runs_project_created ON monitor_runs (project, created)",
                "CREATE INDEX idx_monitor_runs_tenant_created ON monitor_runs (tenant, created)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, monitor_runs_payload)
        if was_created:
            created.append("monitor_runs")

        _ensure_field_on_collection(
            http_client, resolved_pb_url, token,
            "chats",
            _text_field("activated_intent"),
        )
        _ensure_field_on_collection(
            http_client, resolved_pb_url, token,
            "chats",
            _json_field("phishing_result"),
        )
        _ensure_field_on_collection(
            http_client, resolved_pb_url, token,
            "chats",
            _json_field("prompt_injection_result"),
        )
        _ensure_field_on_collection(
            http_client, resolved_pb_url, token,
            "chats",
            _json_field("token_usage"),
        )
        _ensure_field_on_collection(
            http_client, resolved_pb_url, token,
            "chats",
            _text_field("thread_id"),
        )
        _ensure_field_on_collection(
            http_client, resolved_pb_url, token,
            "chats",
            _text_field("message_id"),
        )
        _ensure_field_on_collection(
            http_client, resolved_pb_url, token,
            "chats",
            _json_field("metadata"),
        )
        _ensure_field_on_collection(
            http_client, resolved_pb_url, token,
            "eval_runs",
            _json_field("token_usage"),
        )

        chats = _get_collection(http_client, resolved_pb_url, token, "chats")

        email_processing_claims_payload = _base_collection_payload(
            "email_processing_claims",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("claim_key", required=True),
                _text_field("email_id", required=True),
                {"name": "attempt", "type": "number", "required": True},
                {
                    "name": "owner_token",
                    "type": "text",
                    "required": True,
                    "hidden": True,
                },
                _text_field("status", required=True),
                {"name": "lease_until", "type": "date", "required": True},
                _text_field("error"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                (
                    "CREATE UNIQUE INDEX idx_email_processing_claim_attempt ON "
                    "email_processing_claims (project, claim_key, attempt)"
                ),
                (
                    "CREATE INDEX idx_email_processing_claim_status ON "
                    "email_processing_claims (project, status, lease_until)"
                ),
            ],
        )
        _, was_created = _ensure_collection(
            http_client,
            resolved_pb_url,
            token,
            email_processing_claims_payload,
        )
        if was_created:
            created.append("email_processing_claims")

        support_accounts_payload = _base_collection_payload(
            "support_accounts",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("account_key", required=True),
                _text_field("name"),
                _text_field("domain"),
                _text_field("external_id"),
                _text_field("health_status"),
                _json_field("metadata"),
                _number_field("issue_count"),
                _date_field("latest_issue_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_accounts_project_key ON support_accounts (project, account_key)",
                "CREATE INDEX idx_support_accounts_project_updated ON support_accounts (project, updated)",
            ],
        )
        support_accounts, was_created = _ensure_collection(
            http_client,
            resolved_pb_url,
            token,
            support_accounts_payload,
        )
        if was_created:
            created.append("support_accounts")

        support_contacts_payload = _base_collection_payload(
            "support_contacts",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field("account", support_accounts["id"]),
                _text_field("contact_key", required=True),
                _text_field("email"),
                _text_field("name"),
                _text_field("external_id"),
                _json_field("metadata"),
                _number_field("issue_count"),
                _date_field("latest_issue_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_contacts_project_key ON support_contacts (project, contact_key)",
                "CREATE INDEX idx_support_contacts_account_updated ON support_contacts (account, updated)",
            ],
        )
        support_contacts, was_created = _ensure_collection(
            http_client,
            resolved_pb_url,
            token,
            support_contacts_payload,
        )
        if was_created:
            created.append("support_contacts")

        support_issue_fields = [
            _relation_field("tenant", tenants_id),
            _relation_field_cascade("project", projects_id, required=True),
            _relation_field("account", support_accounts["id"]),
            _relation_field("contact", support_contacts["id"]),
            _text_field("source_email_id", required=True),
            _text_field("channel", required=True),
            _text_field("source"),
            _text_field("status", required=True),
            _text_field("priority", required=True),
            _text_field("assignee_email"),
            _text_field("queue_key"),
            _text_field("queue_name"),
            _json_field("tags"),
            _text_field("account_name"),
            _text_field("account_domain"),
            _text_field("contact_email"),
            _text_field("contact_name"),
            _text_field("subject"),
            _text_field("from_address"),
            _editor_field("ai_summary"),
            _text_field("activated_intent"),
            _bool_field("requires_human"),
            _number_field("message_count"),
            _json_field("action_log"),
            _json_field("metadata"),
            _date_field("latest_message_at"),
            _created_field(),
            _updated_field(),
        ]
        if chats is not None:
            support_issue_fields.insert(2, _relation_field("chat", chats["id"]))
        support_issues_payload = _base_collection_payload(
            "support_issues",
            support_issue_fields,
            indexes=[
                "CREATE UNIQUE INDEX idx_support_issues_project_source_email ON support_issues (project, source_email_id)",
                "CREATE INDEX idx_support_issues_project_status_updated ON support_issues (project, status, updated)",
                "CREATE INDEX idx_support_issues_tenant_updated ON support_issues (tenant, updated)",
            ],
        )
        support_issues, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_issues_payload)
        if was_created:
            created.append("support_issues")
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "support_issues",
            _relation_field("account", support_accounts["id"]),
        )
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "support_issues",
            _relation_field("contact", support_contacts["id"]),
        )
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "support_issues",
            _relation_field("merged_into_issue", support_issues["id"]),
        )
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "support_issues",
            _date_field("merged_at"),
        )
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "support_issues",
            _text_field("merged_by"),
        )
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "support_issues",
            _editor_field("merge_note"),
        )
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "support_issues",
            _text_field("queue_key"),
        )
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "support_issues",
            _text_field("queue_name"),
        )
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "support_issues",
            _json_field("tags"),
        )
        _ensure_field_on_collection(
            http_client,
            resolved_pb_url,
            token,
            "support_issues",
            _json_field("metadata"),
        )
        if chats is not None:
            _ensure_field_on_collection(
                http_client,
                resolved_pb_url,
                token,
                "support_issues",
                _relation_field("chat", chats["id"]),
            )

        support_issues = _get_collection(http_client, resolved_pb_url, token, "support_issues")
        if support_issues is None:
            raise RuntimeError("PocketBase support_issues collection was not created.")

        support_queues_payload = _base_collection_payload(
            "support_queues",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("queue_key", required=True),
                _text_field("name", required=True),
                _editor_field("description"),
                _text_field("default_assignee_email"),
                _text_field("status", required=True),
                _json_field("metadata"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_queues_project_key ON support_queues (project, queue_key)",
                "CREATE INDEX idx_support_queues_project_status_name ON support_queues (project, status, name)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_queues_payload)
        if was_created:
            created.append("support_queues")

        support_inbox_views_payload = _base_collection_payload(
            "support_inbox_views",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("name", required=True),
                _text_field("visibility", required=True),
                _text_field("owner_email"),
                _json_field("filters"),
                _number_field("sort_order"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_inbox_views_project_owner ON support_inbox_views (project, owner_email)",
                "CREATE INDEX idx_support_inbox_views_project_visibility_order ON support_inbox_views (project, visibility, sort_order)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_inbox_views_payload)
        if was_created:
            created.append("support_inbox_views")

        support_reply_macros_payload = _base_collection_payload(
            "support_reply_macros",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("title", required=True),
                _editor_field("body"),
                _text_field("visibility", required=True),
                _text_field("owner_email"),
                _text_field("status", required=True),
                _json_field("tags"),
                _json_field("metadata"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_reply_macros_project_status_title ON support_reply_macros (project, status, title)",
                "CREATE INDEX idx_support_reply_macros_project_owner ON support_reply_macros (project, owner_email)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_reply_macros_payload)
        if was_created:
            created.append("support_reply_macros")

        support_crm_connectors_payload = _base_collection_payload(
            "support_crm_connectors",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("connector_key", required=True),
                _text_field("provider", required=True),
                _text_field("name", required=True),
                _text_field("status"),
                _json_field("config"),
                _date_field("last_sync_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_crm_connectors_project_key ON support_crm_connectors (project, connector_key)",
                "CREATE INDEX idx_support_crm_connectors_project_provider ON support_crm_connectors (project, provider)",
            ],
        )
        support_crm_connectors, was_created = _ensure_collection(
            http_client,
            resolved_pb_url,
            token,
            support_crm_connectors_payload,
        )
        if was_created:
            created.append("support_crm_connectors")

        support_crm_cursors_payload = _base_collection_payload(
            "support_crm_cursors",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("connector", support_crm_connectors["id"], required=True),
                _text_field("cursor_key", required=True),
                _text_field("cursor_value"),
                _text_field("status"),
                _editor_field("last_error"),
                _json_field("metadata"),
                _date_field("last_synced_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_crm_cursors_connector_key ON support_crm_cursors (connector, cursor_key)",
                "CREATE INDEX idx_support_crm_cursors_project_status ON support_crm_cursors (project, status, updated)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_crm_cursors_payload)
        if was_created:
            created.append("support_crm_cursors")

        support_crm_sync_runs_payload = _base_collection_payload(
            "support_crm_sync_runs",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("connector", support_crm_connectors["id"], required=True),
                _text_field("source"),
                _text_field("status"),
                _number_field("processed"),
                _number_field("failed"),
                _number_field("skipped"),
                _number_field("objects_seen"),
                _editor_field("error"),
                _json_field("result"),
                _date_field("started_at"),
                _date_field("completed_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_crm_sync_runs_connector_started ON support_crm_sync_runs (connector, started_at)",
                "CREATE INDEX idx_support_crm_sync_runs_project_status ON support_crm_sync_runs (project, status, started_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_crm_sync_runs_payload)
        if was_created:
            created.append("support_crm_sync_runs")

        support_crm_webhook_events_payload = _base_collection_payload(
            "support_crm_webhook_events",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("connector", support_crm_connectors["id"], required=True),
                _text_field("provider", required=True),
                _text_field("event_id", required=True),
                _text_field("event_type"),
                _text_field("object_type"),
                _text_field("external_id"),
                _text_field("status", required=True),
                _editor_field("error"),
                _json_field("payload"),
                _json_field("result"),
                _date_field("received_at"),
                _date_field("processed_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_crm_webhook_events_connector_event ON support_crm_webhook_events (connector, event_id)",
                "CREATE INDEX idx_support_crm_webhook_events_project_status ON support_crm_webhook_events (project, status, received_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_crm_webhook_events_payload)
        if was_created:
            created.append("support_crm_webhook_events")

        support_external_objects_payload = _base_collection_payload(
            "support_external_objects",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field("account", support_accounts["id"]),
                _relation_field("contact", support_contacts["id"]),
                _text_field("provider", required=True),
                _text_field("object_type", required=True),
                _text_field("external_id", required=True),
                _text_field("external_url"),
                _text_field("display_name"),
                _json_field("raw"),
                _date_field("last_seen_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_external_objects_project_key ON support_external_objects (project, provider, object_type, external_id)",
                "CREATE INDEX idx_support_external_objects_account_seen ON support_external_objects (account, last_seen_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_external_objects_payload)
        if was_created:
            created.append("support_external_objects")

        support_external_sync_runs_payload = _base_collection_payload(
            "support_external_sync_runs",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field("account", support_accounts["id"]),
                _relation_field("source_issue", support_issues["id"]),
                _text_field("provider", required=True),
                _text_field("status", required=True),
                _number_field("objects_seen"),
                _editor_field("error"),
                _json_field("result"),
                _date_field("started_at"),
                _date_field("completed_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_external_sync_runs_account_started ON support_external_sync_runs (account, started_at)",
                "CREATE INDEX idx_support_external_sync_runs_project_status ON support_external_sync_runs (project, status, started_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_external_sync_runs_payload)
        if was_created:
            created.append("support_external_sync_runs")

        support_messages_payload = _base_collection_payload(
            "support_messages",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("source_message_id", required=True),
                _text_field("direction", required=True),
                _text_field("sender"),
                _editor_field("body"),
                _text_field("message_kind"),
                _json_field("attachments"),
                _json_field("metadata"),
                _date_field("occurred_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_messages_issue_source ON support_messages (issue, source_message_id)",
                "CREATE INDEX idx_support_messages_issue_occurred ON support_messages (issue, occurred_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_messages_payload)
        if was_created:
            created.append("support_messages")

        support_outbound_payload = _base_collection_payload(
            "support_outbound_messages",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("channel", required=True),
                _text_field("to_address", required=True),
                _text_field("from_address"),
                _text_field("subject", required=True),
                _editor_field("body", required=True),
                _text_field("status", required=True),
                _text_field("provider"),
                _text_field("provider_message_id"),
                _editor_field("error"),
                _text_field("created_by"),
                _text_field("idempotency_key"),
                _date_field("sent_at"),
                {**_text_field("delivery_claim_token"), "hidden": True},
                _text_field("delivery_attempt_key"),
                _date_field("delivery_claimed_at"),
                _date_field("delivery_claim_expires_at"),
                _json_field("metadata"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_outbound_issue_created ON support_outbound_messages (issue, created)",
                "CREATE INDEX idx_support_outbound_project_status ON support_outbound_messages (project, status, updated)",
                "CREATE INDEX idx_support_outbound_delivery_claim ON support_outbound_messages (status, delivery_claim_expires_at)",
                "CREATE UNIQUE INDEX idx_support_outbound_issue_idempotency ON support_outbound_messages (issue, idempotency_key) WHERE idempotency_key <> ''",
            ],
        )
        support_outbound, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_outbound_payload)
        if was_created:
            created.append("support_outbound_messages")
        for field_def in (
            _text_field("idempotency_key"),
            {**_text_field("delivery_claim_token"), "hidden": True},
            _text_field("delivery_attempt_key"),
            _date_field("delivery_claimed_at"),
            _date_field("delivery_claim_expires_at"),
        ):
            _ensure_field_on_collection(
                http_client,
                resolved_pb_url,
                token,
                "support_outbound_messages",
                field_def,
            )

        support_delivery_runs_payload = _base_collection_payload(
            "support_delivery_runs",
            [
                _relation_field("tenant", tenants_id),
                _relation_field("project", projects_id),
                _text_field("source"),
                _text_field("status"),
                _number_field("processed"),
                _number_field("sent"),
                _number_field("failed"),
                _editor_field("error"),
                _json_field("result"),
                _date_field("started_at"),
                _date_field("completed_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_delivery_runs_project_started ON support_delivery_runs (project, started_at)",
                "CREATE INDEX idx_support_delivery_runs_status_started ON support_delivery_runs (status, started_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_delivery_runs_payload)
        if was_created:
            created.append("support_delivery_runs")

        support_launch_proof_runs_payload = _base_collection_payload(
            "support_launch_proof_runs",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("status"),
                _number_field("ran"),
                _number_field("failed"),
                _number_field("skipped"),
                _editor_field("error"),
                _json_field("actions"),
                _json_field("launch_readiness"),
                _json_field("launch_proof"),
                _json_field("result"),
                _date_field("started_at"),
                _date_field("completed_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                (
                    "CREATE INDEX idx_support_launch_proof_runs_project_started "
                    "ON support_launch_proof_runs (project, started_at)"
                ),
                (
                    "CREATE INDEX idx_support_launch_proof_runs_status_started "
                    "ON support_launch_proof_runs (status, started_at)"
                ),
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_launch_proof_runs_payload)
        if was_created:
            created.append("support_launch_proof_runs")

        support_ai_runs_payload = _base_collection_payload(
            "support_ai_runs",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("run_key", required=True),
                _text_field("source"),
                _text_field("status", required=True),
                _text_field("activated_intent"),
                _bool_field("requires_human"),
                _editor_field("summary"),
                _json_field("identity_result"),
                _json_field("intent_result"),
                _json_field("security_result"),
                _json_field("token_usage"),
                _json_field("tool_calls"),
                _json_field("metadata"),
                _date_field("started_at"),
                _date_field("completed_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_ai_runs_issue_key ON support_ai_runs (issue, run_key)",
                "CREATE INDEX idx_support_ai_runs_project_updated ON support_ai_runs (project, updated)",
            ],
        )
        support_ai_runs, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_ai_runs_payload)
        if was_created:
            created.append("support_ai_runs")

        support_agent_messages_payload = _base_collection_payload(
            "support_agent_messages",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _relation_field("run", support_ai_runs["id"]),
                _relation_field("reply", support_outbound["id"]),
                _text_field("role", required=True),
                _text_field("author_email"),
                _editor_field("body", required=True),
                _json_field("metadata"),
                _date_field("occurred_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_agent_messages_issue_created ON support_agent_messages (issue, created)",
                "CREATE INDEX idx_support_agent_messages_project_created ON support_agent_messages (project, created)",
                "CREATE INDEX idx_support_agent_messages_issue_role ON support_agent_messages (issue, role, created)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_agent_messages_payload)
        if was_created:
            created.append("support_agent_messages")

        support_action_executions_payload = _base_collection_payload(
            "support_action_executions",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("action_key", required=True),
                _text_field("label", required=True),
                _text_field("type"),
                _text_field("status", required=True),
                _text_field("requested_by"),
                _json_field("result"),
                _editor_field("error"),
                _json_field("metadata"),
                _date_field("started_at"),
                _date_field("completed_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_action_exec_issue_created ON support_action_executions (issue, created)",
                "CREATE INDEX idx_support_action_exec_project_status ON support_action_executions (project, status, updated)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_action_executions_payload)
        if was_created:
            created.append("support_action_executions")

        support_automation_rules_payload = _base_collection_payload(
            "support_automation_rules",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("name", required=True),
                _bool_field("active"),
                _text_field("trigger", required=True),
                _json_field("conditions"),
                _json_field("actions"),
                _date_field("last_run_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_automation_rules_project_trigger ON support_automation_rules (project, trigger, active)",
                "CREATE INDEX idx_support_automation_rules_project_name ON support_automation_rules (project, name)",
            ],
        )
        support_automation_rules, was_created = _ensure_collection(
            http_client,
            resolved_pb_url,
            token,
            support_automation_rules_payload,
        )
        if was_created:
            created.append("support_automation_rules")

        support_automation_runs_payload = _base_collection_payload(
            "support_automation_runs",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("rule", support_automation_rules["id"], required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("trigger"),
                _text_field("status"),
                _number_field("actions_applied"),
                _editor_field("error"),
                _json_field("context"),
                _json_field("result"),
                _date_field("started_at"),
                _date_field("completed_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_automation_runs_rule_started ON support_automation_runs (rule, started_at)",
                "CREATE INDEX idx_support_automation_runs_project_status ON support_automation_runs (project, status, started_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_automation_runs_payload)
        if was_created:
            created.append("support_automation_runs")

        support_issue_events_payload = _base_collection_payload(
            "support_issue_events",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("event_type", required=True),
                _text_field("actor_email"),
                _text_field("title"),
                _editor_field("body"),
                _text_field("from_status"),
                _text_field("to_status"),
                _text_field("from_priority"),
                _text_field("to_priority"),
                _json_field("metadata"),
                _date_field("occurred_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_issue_events_issue_occurred ON support_issue_events (issue, occurred_at)",
                "CREATE INDEX idx_support_issue_events_project_type ON support_issue_events (project, event_type, occurred_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_issue_events_payload)
        if was_created:
            created.append("support_issue_events")

        support_notes_payload = _base_collection_payload(
            "support_internal_notes",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("author_email"),
                _editor_field("body", required=True),
                _text_field("visibility"),
                _json_field("metadata"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_notes_issue_created ON support_internal_notes (issue, created)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_notes_payload)
        if was_created:
            created.append("support_internal_notes")

        support_assignments_payload = _base_collection_payload(
            "support_issue_assignments",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("assignee_email"),
                _text_field("assigned_by"),
                _text_field("status"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_assignments_issue_created ON support_issue_assignments (issue, created)",
                "CREATE INDEX idx_support_assignments_assignee_created ON support_issue_assignments (assignee_email, created)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_assignments_payload)
        if was_created:
            created.append("support_issue_assignments")

        support_notifications_payload = _base_collection_payload(
            "support_notifications",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("recipient_email", required=True),
                _text_field("type", required=True),
                _text_field("title", required=True),
                _editor_field("body"),
                _text_field("status", required=True),
                _json_field("metadata"),
                _date_field("read_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_notifications_recipient_status_created ON support_notifications (project, recipient_email, status, created)",
                "CREATE INDEX idx_support_notifications_issue_recipient ON support_notifications (issue, recipient_email)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_notifications_payload)
        if was_created:
            created.append("support_notifications")

        support_watchers_payload = _base_collection_payload(
            "support_issue_watchers",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("watcher_email", required=True),
                _text_field("added_by"),
                _text_field("source"),
                _text_field("status", required=True),
                _json_field("metadata"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_watchers_issue_email ON support_issue_watchers (issue, watcher_email)",
                "CREATE INDEX idx_support_watchers_project_email_status ON support_issue_watchers (project, watcher_email, status)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_watchers_payload)
        if was_created:
            created.append("support_issue_watchers")

        support_sla_policies_payload = _base_collection_payload(
            "support_sla_policies",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("name", required=True),
                _bool_field("active"),
                _number_field("first_response_minutes"),
                _number_field("resolution_minutes"),
                _json_field("business_hours"),
                _json_field("metadata"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_sla_policies_project_active ON support_sla_policies (project, active)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_sla_policies_payload)
        if was_created:
            created.append("support_sla_policies")

        support_sla_payload = _base_collection_payload(
            "support_sla_events",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("event_type", required=True),
                _text_field("status", required=True),
                _date_field("target_at"),
                _date_field("occurred_at"),
                _json_field("metadata"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_sla_issue_type ON support_sla_events (issue, event_type)",
                "CREATE INDEX idx_support_sla_project_status_target ON support_sla_events (project, status, target_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_sla_payload)
        if was_created:
            created.append("support_sla_events")

        support_portal_payload = _base_collection_payload(
            "support_customer_portal_sessions",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("token_hash", required=True),
                _text_field("status", required=True),
                _date_field("expires_at"),
                _date_field("last_accessed_at"),
                _text_field("created_by"),
                _json_field("metadata"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_portal_token_hash ON support_customer_portal_sessions (token_hash)",
                "CREATE INDEX idx_support_portal_issue_status ON support_customer_portal_sessions (issue, status)",
            ],
        )
        support_portal, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_portal_payload)
        if was_created:
            created.append("support_customer_portal_sessions")

        support_csat_payload = _base_collection_payload(
            "support_csat_feedback",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _relation_field_cascade("portal_session", support_portal["id"], required=True),
                _number_field("rating"),
                _editor_field("comment"),
                _text_field("customer_email"),
                _text_field("customer_name"),
                _text_field("source"),
                _json_field("metadata"),
                _date_field("received_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_csat_portal_session ON support_csat_feedback (portal_session)",
                "CREATE INDEX idx_support_csat_project_received ON support_csat_feedback (project, received_at)",
                "CREATE INDEX idx_support_csat_issue_received ON support_csat_feedback (issue, received_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_csat_payload)
        if was_created:
            created.append("support_csat_feedback")

        support_channels_payload = _base_collection_payload(
            "support_channels",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _text_field("channel_key", required=True),
                _text_field("type", required=True),
                _text_field("name", required=True),
                _text_field("status"),
                _json_field("config"),
                _date_field("last_sync_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_channels_project_key ON support_channels (project, channel_key)",
                "CREATE INDEX idx_support_channels_project_type ON support_channels (project, type)",
            ],
        )
        support_channels, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_channels_payload)
        if was_created:
            created.append("support_channels")

        support_channel_cursors_payload = _base_collection_payload(
            "support_channel_cursors",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("channel", support_channels["id"], required=True),
                _text_field("cursor_key", required=True),
                _text_field("cursor_value"),
                _text_field("status"),
                _editor_field("last_error"),
                _json_field("metadata"),
                _date_field("last_synced_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_channel_cursors_channel_key ON support_channel_cursors (channel, cursor_key)",
                "CREATE INDEX idx_support_channel_cursors_project_status ON support_channel_cursors (project, status, updated)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_channel_cursors_payload)
        if was_created:
            created.append("support_channel_cursors")

        support_channel_sync_runs_payload = _base_collection_payload(
            "support_channel_sync_runs",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("channel", support_channels["id"], required=True),
                _text_field("source"),
                _text_field("status"),
                _number_field("processed"),
                _number_field("failed"),
                _number_field("skipped"),
                _editor_field("error"),
                _json_field("result"),
                _date_field("started_at"),
                _date_field("completed_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_support_channel_sync_runs_channel_started ON support_channel_sync_runs (channel, started_at)",
                "CREATE INDEX idx_support_channel_sync_runs_project_status ON support_channel_sync_runs (project, status, started_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_channel_sync_runs_payload)
        if was_created:
            created.append("support_channel_sync_runs")

        support_channel_webhook_events_payload = _base_collection_payload(
            "support_channel_webhook_events",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("channel", support_channels["id"], required=True),
                _relation_field("outbound_message", support_outbound["id"]),
                _text_field("provider", required=True),
                _text_field("event_id", required=True),
                _text_field("event_type"),
                _text_field("provider_message_id"),
                _text_field("status", required=True),
                _editor_field("error"),
                _json_field("payload"),
                _json_field("result"),
                _date_field("received_at"),
                _date_field("processed_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_channel_webhook_events_channel_event ON support_channel_webhook_events (channel, event_id)",
                "CREATE INDEX idx_support_channel_webhook_events_project_status ON support_channel_webhook_events (project, status, received_at)",
                "CREATE INDEX idx_support_channel_webhook_events_provider_message ON support_channel_webhook_events (provider_message_id, received_at)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_channel_webhook_events_payload)
        if was_created:
            created.append("support_channel_webhook_events")

        support_web_chat_sessions_payload = _base_collection_payload(
            "support_web_chat_sessions",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("channel", support_channels["id"], required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("session_key", required=True),
                _text_field("visitor_id"),
                _text_field("visitor_email"),
                _text_field("visitor_name"),
                _text_field("page_url"),
                _text_field("status", required=True),
                _json_field("metadata"),
                _date_field("last_message_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_web_chat_sessions_key ON support_web_chat_sessions (session_key)",
                "CREATE INDEX idx_support_web_chat_sessions_project_status ON support_web_chat_sessions (project, status, last_message_at)",
                "CREATE INDEX idx_support_web_chat_sessions_channel_updated ON support_web_chat_sessions (channel, updated)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_web_chat_sessions_payload)
        if was_created:
            created.append("support_web_chat_sessions")

        knowledge_articles_payload = _base_collection_payload(
            "knowledge_articles",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field("source_issue", support_issues["id"]),
                _text_field("title", required=True),
                _editor_field("body", required=True),
                _text_field("status", required=True),
                _json_field("tags"),
                _json_field("metadata"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_knowledge_articles_project_updated ON knowledge_articles (project, updated)",
                "CREATE INDEX idx_knowledge_articles_project_status ON knowledge_articles (project, status)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, knowledge_articles_payload)
        if was_created:
            created.append("knowledge_articles")

        support_knowledge_gaps_payload = _base_collection_payload(
            "support_knowledge_gaps",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("issue", support_issues["id"], required=True),
                _text_field("gap_key", required=True),
                _text_field("title", required=True),
                _editor_field("evidence"),
                _text_field("status"),
                _text_field("severity"),
                _text_field("suggested_article_title"),
                _json_field("metadata"),
                _date_field("first_seen_at"),
                _date_field("last_seen_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_knowledge_gaps_project_key ON support_knowledge_gaps (project, gap_key)",
                "CREATE INDEX idx_support_knowledge_gaps_project_status ON support_knowledge_gaps (project, status, updated)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_knowledge_gaps_payload)
        if was_created:
            created.append("support_knowledge_gaps")

        support_account_insights_payload = _base_collection_payload(
            "support_account_insights",
            [
                _relation_field("tenant", tenants_id),
                _relation_field_cascade("project", projects_id, required=True),
                _relation_field_cascade("account", support_accounts["id"], required=True),
                _relation_field("source_issue", support_issues["id"]),
                _text_field("insight_key", required=True),
                _text_field("type", required=True),
                _text_field("title", required=True),
                _editor_field("body"),
                _text_field("severity"),
                _text_field("status"),
                _json_field("metadata"),
                _date_field("first_seen_at"),
                _date_field("last_seen_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE UNIQUE INDEX idx_support_account_insights_account_key ON support_account_insights (account, insight_key)",
                "CREATE INDEX idx_support_account_insights_project_type ON support_account_insights (project, type, status)",
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, support_account_insights_payload)
        if was_created:
            created.append("support_account_insights")

        llm_usage_fields = [
            _relation_field("tenant", tenants_id),
            _relation_field("project", projects_id),
            _text_field("run_id"),
            _text_field("stage"),
            _text_field("provider"),
            _text_field("model"),
            _text_field("billing_mode"),
            _number_field("duration_ms"),
            _number_field("input_tokens"),
            _number_field("output_tokens"),
            _number_field("cached_input_tokens"),
            _number_field("total_tokens"),
            _number_field("raw_cost_usd_micros"),
            _number_field("billed_cost_usd_micros"),
            _number_field("cost_markup"),
            _bool_field("metadata_available"),
            _json_field("raw_usage"),
            _created_field(),
            _updated_field(),
        ]
        if chats is not None:
            llm_usage_fields.insert(2, _relation_field("chat", chats["id"]))
        llm_usage_fields.insert(3, _relation_field("eval_run", eval_runs_id))
        llm_usage_payload = _base_collection_payload("llm_usage_events", llm_usage_fields)
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, llm_usage_payload)
        if was_created:
            created.append("llm_usage_events")
        for field_def in (
            _text_field("billing_mode"),
            _number_field("duration_ms"),
            _number_field("raw_cost_usd_micros"),
            _number_field("billed_cost_usd_micros"),
            _number_field("cost_markup"),
            _bool_field("stripe_reported"),
            _date_field("stripe_reported_at"),
            _text_field("stripe_meter_event_id"),
            _text_field("stripe_report_error"),
        ):
            _ensure_field_on_collection(
                http_client, resolved_pb_url, token,
                "llm_usage_events",
                field_def,
            )

        # ── Billing fields on tenants ──────────────────────────────────────
        for field_def in (
            _text_field("stripe_customer_id"),
            _text_field("subscription_id"),
            _text_field("subscription_status"),
            _text_field("plan"),
            _text_field("account_type"),
            _bool_field("cancel_at_period_end"),
            _date_field("current_period_start"),
            _date_field("current_period_end"),
        ):
            _ensure_field_on_collection(
                http_client, resolved_pb_url, token,
                "tenants",
                field_def,
            )

        # ── Support / feedback email fields on tenants ─────────────────────
        for field_def in (
            _text_field("support_email"),
            _text_field("feedback_email"),
        ):
            _ensure_field_on_collection(
                http_client, resolved_pb_url, token,
                "tenants",
                field_def,
            )

        # ── Org identity + LLM provider fields on tenants ─────────────────
        for field_def in (
            _text_field("org_name"),
            _editor_field("org_description"),
            _text_field("addin_primary_color"),
            _text_field("llm_provider"),
            _text_field("llm_model"),
            _text_field("llm_api_key"),
            _text_field("llm_custom_base_url"),
            _text_field("llm_custom_model"),
            _bool_field("phishing_monitoring_enabled"),
            _bool_field("prompt_injection_monitoring_enabled"),
            _bool_field("allow_signups"),
        ):
            _ensure_field_on_collection(
                http_client, resolved_pb_url, token,
                "tenants",
                field_def,
            )

        # ── Secrets (JSON key-value map) on tenants + projects ────────────
        _ensure_field_on_collection(
            http_client, resolved_pb_url, token,
            "tenants",
            _json_field("secrets"),
        )
        _ensure_field_on_collection(
            http_client, resolved_pb_url, token,
            "projects",
            _json_field("secrets"),
        )

        # ── Feedback collection ───────────────────────────────────────────
        feedback_payload = _base_collection_payload(
            "feedback",
            [
                _text_field("chat_id", required=True),
                _text_field("user_email", required=True),
                _text_field("rating", required=True),
                _json_field("affected_stages"),
                _text_field("feedback_text"),
                _text_field("intent_name"),
                _relation_field("tenant", tenants_id),
                _relation_field("project", projects_id),
                _created_field(),
                _updated_field(),
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, feedback_payload)
        if was_created:
            created.append("feedback")

        # ── Intent learnings collection (AI-generated from feedback) ──────
        learnings_payload = _base_collection_payload(
            "intent_learnings",
            [
                _text_field("intent_name", required=True),
                _text_field("learning", required=True),
                _text_field("source_feedback_id"),
                _json_field("affected_stages"),
                _relation_field("tenant", tenants_id),
                _relation_field("project", projects_id),
                _created_field(),
                _updated_field(),
            ],
        )
        _, was_created = _ensure_collection(http_client, resolved_pb_url, token, learnings_payload)
        if was_created:
            created.append("intent_learnings")
        else:
            _ensure_field_on_collection(
                http_client,
                resolved_pb_url,
                token,
                "intent_learnings",
                _json_field("affected_stages"),
            )

        # ── Controlled intent-learning proposals ─────────────────────────
        learning_proposals_payload = _base_collection_payload(
            "intent_learning_proposals",
            [
                _text_field("intent_name", required=True),
                _text_field("operation", required=True),
                _text_field("status", required=True),
                _editor_field("proposed_learning"),
                _editor_field("before_learning"),
                _text_field("target_learning_id"),
                _text_field("source_feedback_id"),
                _json_field("affected_stages"),
                _text_field("base_learning_hash", required=True),
                _text_field("proposal_hash", required=True),
                _text_field("evaluated_proposal_hash"),
                _text_field("evaluated_base_hash"),
                _json_field("eval_summary"),
                _json_field("eval_case_ids"),
                _text_field("eval_case_hash"),
                _text_field("eval_policy_hash"),
                _text_field("eval_dimension"),
                _number_field("minimum_score"),
                _editor_field("error"),
                _editor_field("rejection_reason"),
                _text_field("created_by"),
                _text_field("evaluated_by"),
                _text_field("published_by"),
                _text_field("rejected_by"),
                _text_field("active_learning_id"),
                _text_field("runbook_id", required=True),
                _text_field("runbook_updated", required=True),
                _relation_field("tenant", tenants_id),
                _relation_field("project", projects_id, required=True),
                _text_field("eval_set"),
                _text_field("eval_run"),
                _date_field("evaluated_at"),
                _date_field("published_at"),
                _date_field("rejected_at"),
                _created_field(),
                _updated_field(),
            ],
            indexes=[
                "CREATE INDEX idx_intent_learning_proposals_scope "
                "ON intent_learning_proposals (project, intent_name, status)",
                "CREATE INDEX idx_intent_learning_proposals_feedback "
                "ON intent_learning_proposals (source_feedback_id)",
            ],
        )
        _, was_created = _ensure_collection(
            http_client,
            resolved_pb_url,
            token,
            learning_proposals_payload,
        )
        if was_created:
            created.append("intent_learning_proposals")

    if created:
        logger.info("PocketBase app collection bootstrap created: %s", ", ".join(created))
    else:
        logger.info("PocketBase app collections already current")

    return AppCollectionsBootstrapResult(created_collections=created)
