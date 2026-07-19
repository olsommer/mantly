"""Static gate for support-workspace release packaging."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

EXIT_READY = 0
EXIT_ERROR = 1
EXIT_BLOCKED = 2


@dataclass(frozen=True)
class PackageRequirement:
    category: str
    path: str
    required_text: tuple[str, ...] = ()


@dataclass
class PackageGateResult:
    ok: bool
    checked: int
    missing_paths: list[dict[str, str]]
    missing_content: list[dict[str, Any]]
    missing_executable: list[dict[str, str]]


SUPPORT_MIGRATIONS: tuple[str, ...] = (
    "25_support_issues.js",
    "26_support_accounts_contacts_messages.js",
    "27_support_collaboration_knowledge_channels.js",
    "28_support_account_insights.js",
    "29_support_knowledge_gaps.js",
    "30_support_outbound_messages.js",
    "31_support_ai_runs.js",
    "32_support_action_executions.js",
    "33_support_issue_events.js",
    "34_support_channel_cursors.js",
    "35_support_channel_sync_runs.js",
    "36_support_delivery_runs.js",
    "37_support_automations.js",
    "38_support_sla_policies.js",
    "39_support_customer_portal_sessions.js",
    "40_support_external_objects.js",
    "41_support_crm_connectors.js",
    "42_support_crm_webhook_events.js",
    "43_support_channel_webhook_events.js",
    "44_support_web_chat_sessions.js",
    "45_support_notifications.js",
    "46_support_issue_watchers.js",
    "47_support_queues.js",
    "48_support_issue_tags.js",
    "49_support_inbox_views.js",
    "50_support_reply_macros.js",
    "51_chat_email_thread_metadata.js",
    "52_support_issue_merge_fields.js",
    "53_support_csat_feedback.js",
    "54_support_issue_metadata.js",
    "55_support_launch_proof_runs.js",
    "56_support_agent_messages.js",
    "57_support_delivery_claims.js",
    "58_intent_learning_proposals.js",
    "59_support_outbound_idempotency.js",
    "60_llm_usage_duration.js",
    "61_email_processing_claims.js",
    "63_support_channel_webhook_claims.js",
)


REQUIRED_PACKAGE_FILES: tuple[PackageRequirement, ...] = (
    PackageRequirement(
        "customer-package",
        "scripts/package-customer.sh",
        (
            "support-launch-gate.sh",
            "support-schema-gate.sh",
            "support-channel-lifecycle-smoke.sh",
            "support-channel-activation-plan.sh",
            "deploy-onprem.md",
            "release-manifest.json",
            "supportLaunchProof",
            "supportChannelActivationPlan",
            "supportPackageGate",
            "support-launch-proof.json",
            "support-channel-activation-plan",
            "support-channel-activation-secrets",
            "REGISTRY",
            "validate_version",
            "validate_registry",
            "Invalid VERSION",
            "Invalid REGISTRY",
        ),
    ),
    PackageRequirement(
        "customer-package",
        "scripts/support-channel-lifecycle-smoke.mjs",
        ("lifecycle-smoke", "--transport http", "--channel-key"),
    ),
    PackageRequirement(
        "customer-package",
        "deploy/support-channel-lifecycle-smoke.sh",
        ("automail.support.channel_lifecycle_smoke", "SUPPORT_PROJECT_ID", "ADMIN_AUTH_TOKEN"),
    ),
    PackageRequirement(
        "customer-package",
        "scripts/release-onprem.sh",
        (
            "package-customer.sh",
            "SKIP_CUSTOMER_PACKAGE",
            "validate_version",
            "validate_registry",
            "Invalid VERSION",
            "Invalid REGISTRY",
        ),
    ),
    PackageRequirement(
        "customer-package",
        "deploy/.env.example",
        (
            "SUPPORT_LAUNCH_GATE_TIMEOUT",
            "REGISTRY",
            "SUPPORT_LAUNCH_GATE_BUNDLE_FILE",
            "SUPPORT_LAUNCH_GATE_BUNDLE_OUT",
            "SUPPORT_LAUNCH_GATE_COPY_BUNDLE",
            "SUPPORT_CHANNEL_ACTIVATION_PLAN_OUT",
            "SUPPORT_CHANNEL_ACTIVATION_SECRETS_OUT",
            "SUPPORT_CHANNEL_ACTIVATION_WRITE_SECRETS",
        ),
    ),
    PackageRequirement(
        "customer-package",
        "deploy/docker-compose.yml",
        (
            "automail.support.bridge_app",
            "automail.support.discord_gateway",
            "LICENSE_KEY",
            "${REGISTRY:-ghcr.io/isarlabs}/isarai-email-agent",
            "${REGISTRY:-ghcr.io/isarlabs}/isarai-pocketbase",
        ),
    ),
    PackageRequirement("customer-package", "deploy/Caddyfile"),
    PackageRequirement(
        "customer-package",
        "deploy/support-launch-gate.sh",
        (
            "launch_gate",
            "--schema-gate",
            "--bundle-file",
            "SUPPORT_LAUNCH_GATE_BUNDLE_FILE",
            "SUPPORT_LAUNCH_GATE_BUNDLE_OUT",
            "SUPPORT_LAUNCH_GATE_COPY_BUNDLE",
            "app:$EFFECTIVE_BUNDLE_FILE",
        ),
    ),
    PackageRequirement("customer-package", "deploy/support-schema-gate.sh", ("schema_gate",)),
    PackageRequirement(
        "customer-package",
        "deploy/support-channel-activation-plan.sh",
        (
            "channels/activation-plan",
            "SUPPORT_CHANNEL_ACTIVATION_PLAN_OUT",
            "SUPPORT_CHANNEL_ACTIVATION_SECRETS_OUT",
            "ADMIN_AUTH_TOKEN",
        ),
    ),
    PackageRequirement(
        "customer-package",
        "docs/deploy-onprem.md",
        (
            "support-launch-gate.sh",
            "support-schema-gate.sh",
            "support-channel-lifecycle-smoke.sh",
            "support-channel-activation-plan.sh",
            "release-manifest.json",
            "supportPackageGate",
            "support-launch-proof.json",
            "supportChannelActivationPlan",
            "support-channel-activation-plan",
            "REGISTRY",
            "SUPPORT_LAUNCH_GATE_BUNDLE_FILE",
            "SUPPORT_LAUNCH_GATE_BUNDLE_OUT",
            "SUPPORT_LAUNCH_GATE_COPY_BUNDLE",
            "SUPPORT_CHANNEL_ACTIVATION_PLAN_OUT",
            "SUPPORT_CHANNEL_ACTIVATION_SECRETS_OUT",
            "SKIP_CUSTOMER_PACKAGE",
            "support-bridge",
            "discord-gateway",
        ),
    ),
    PackageRequirement(
        "customer-package",
        "docs/pylon-pivot-rfc.md",
        (
            "launch proof",
            "Live low CSAT is now actionable immediately",
            "confidence_guard",
            "workflow_lifecycle_proof_missing",
        ),
    ),
)


REQUIRED_EXECUTABLE_FILES: tuple[PackageRequirement, ...] = (
    PackageRequirement("customer-package", "scripts/package-customer.sh"),
    PackageRequirement("customer-package", "scripts/release-onprem.sh"),
    PackageRequirement("customer-package", "scripts/support-channel-lifecycle-smoke.mjs"),
    PackageRequirement("customer-package", "deploy/support-launch-gate.sh"),
    PackageRequirement("customer-package", "deploy/support-schema-gate.sh"),
    PackageRequirement("customer-package", "deploy/support-channel-lifecycle-smoke.sh"),
    PackageRequirement("customer-package", "deploy/support-channel-activation-plan.sh"),
)

REQUIRED_BACKEND_FILES: tuple[PackageRequirement, ...] = (
    PackageRequirement(
        "pocketbase-runtime",
        "pocketbase/Dockerfile",
        ("COPY pocketbase/pb_hooks/ /pb/pb_hooks/",),
    ),
    PackageRequirement(
        "pocketbase-runtime",
        "pocketbase/start.sh",
        ("--hooksDir=/pb/pb_hooks",),
    ),
    PackageRequirement(
        "pocketbase-runtime",
        "pocketbase/pb_hooks/support_delivery.pb.js",
        (
            "/api/mantly/support-delivery/{id}/claim",
            "/api/mantly/support-delivery/{id}/complete",
            "/api/mantly/support-delivery/{id}/reconcile-expired",
            "runInTransaction",
            "delivery_claim_token",
        ),
    ),
    PackageRequirement(
        "pocketbase-runtime",
        "pocketbase/pb_hooks/support_delivery_helpers.js",
        ("module.exports", "support_outbound_messages"),
    ),
    PackageRequirement(
        "pocketbase-runtime",
        "pocketbase/pb_hooks/support_channel_webhook_claims.pb.js",
        (
            "/api/mantly/support-channel-webhooks/{id}/claim",
            "/api/mantly/support-channel-webhooks/{id}/complete",
            "runInTransaction",
            "processing_claim_token",
            "retry_policy_version",
        ),
    ),
    PackageRequirement(
        "backend-entrypoint",
        "backend/automail/main.py",
        (
            "internal_support_router",
            "support_knowledge_router",
            "support_portal_router",
            "support_web_chat_router",
            "start_support_sync_scheduler",
        ),
    ),
    PackageRequirement(
        "backend-entrypoint",
        "backend/automail/api/admin/router.py",
        (
            "issues.router",
            "accounts.router",
            "automations.router",
            "channels.router",
            "knowledge.router",
            "support_analytics.router",
            "support_delivery.router",
            "support_settings.router",
        ),
    ),
    PackageRequirement(
        "support-backend",
        "backend/automail/db/pocketbase/issues.py",
        (
            "support_launch_proof",
            "LOW_CSAT_RECOVERY_MAX_RATING",
            "lowCsatRecovery",
            "confidence_guard",
            "autoSendBlockedReason",
            "workflow_lifecycle_proof_missing",
            "ticketCreation",
            "replyRoute",
            "channelAutopilot",
            "knowledgeAssist",
            "accountIntelligence",
            "humanLoop",
            "ticketWorkflow",
            "_web_chat_session_transcript",
            "issueIds",
            "messageCount",
        ),
    ),
    PackageRequirement("support-backend", "backend/automail/db/pocketbase/bootstrap_app_schema.py"),
    PackageRequirement("support-backend", "backend/automail/api/internal_support.py"),
    PackageRequirement("support-backend", "backend/automail/api/support_knowledge.py"),
    PackageRequirement("support-backend", "backend/automail/api/support_portal.py"),
    PackageRequirement(
        "support-backend",
        "backend/automail/api/support_web_chat.py",
        (
            "data.messages",
            "latestTicketId",
            "Ticket opened:",
            "automail-support-chat-status",
            "data-automail-support-chat-latest-ticket",
        ),
    ),
    PackageRequirement("support-backend", "backend/automail/api/admin/accounts.py"),
    PackageRequirement("support-backend", "backend/automail/api/admin/automations.py"),
    PackageRequirement(
        "support-backend",
        "backend/automail/api/admin/channels.py",
        (
            "get_channel_activation_plan",
            "/projects/{pid}/channels/activation-plan",
            "support_channel_activation_plan",
        ),
    ),
    PackageRequirement("support-backend", "backend/automail/api/admin/issues.py"),
    PackageRequirement("support-backend", "backend/automail/api/admin/knowledge.py"),
    PackageRequirement(
        "support-backend",
        "backend/automail/api/admin/support_analytics.py",
        (
            "workflow_lifecycle_proof_missing",
            "automation_proof_missing",
            "record_launch_proof_run",
            "low_csat_followups",
        ),
    ),
    PackageRequirement("support-backend", "backend/automail/api/admin/support_delivery.py"),
    PackageRequirement("support-backend", "backend/automail/api/admin/support_settings.py"),
    PackageRequirement("support-service", "backend/automail/support/bridge.py"),
    PackageRequirement("support-service", "backend/automail/support/bridge_app.py"),
    PackageRequirement("support-service", "backend/automail/support/channel_lifecycle_smoke.py"),
    PackageRequirement("support-service", "backend/automail/support/crm.py"),
    PackageRequirement("support-service", "backend/automail/support/delivery.py"),
    PackageRequirement("support-service", "backend/automail/support/discord_gateway.py"),
    PackageRequirement("support-service", "backend/automail/support/ingestion.py"),
    PackageRequirement("support-service", "backend/automail/support/issue_agent.py"),
    PackageRequirement("support-service", "backend/automail/support/issue_fields.py"),
    PackageRequirement("support-service", "backend/automail/support/issue_triage.py"),
    PackageRequirement(
        "support-service",
        "backend/automail/support/launch_gate.py",
        (
            "support_launch_proof_bundle",
            "_channel_launch_blockers",
            "channel {channel} blocked",
            "_schema_blocked_launch_proof",
            "schema_gate_blocked",
            "schema gate blocked before launch proof fetch",
            "schema gate blocked before activation plan fetch",
            "fetch_channel_activation_plan",
            "activationPlan",
            "activationPlanError",
            "SUPPORT_LAUNCH_GATE_BUNDLE_FILE",
            "SUPPORT_LAUNCH_BUNDLE_FILE",
            "ticketCreation",
            "replyRoute",
            "channelAutopilot",
            "knowledgeAssist",
            "accountIntelligence",
            "humanLoop",
            "ticketWorkflow",
        ),
    ),
    PackageRequirement("support-service", "backend/automail/support/package_gate.py"),
    PackageRequirement("support-service", "backend/automail/support/scheduler.py"),
    PackageRequirement("support-service", "backend/automail/support/schema_gate.py"),
    PackageRequirement("support-prompts", "backend/automail/support/prompts/issue_agent_system_prompt.md"),
    PackageRequirement("support-prompts", "backend/automail/support/prompts/issue_agent_user_prompt.md"),
    PackageRequirement("support-prompts", "backend/automail/support/prompts/issue_field_extraction_system_prompt.md"),
    PackageRequirement("support-prompts", "backend/automail/support/prompts/issue_field_extraction_user_prompt.md"),
    PackageRequirement("support-prompts", "backend/automail/support/prompts/issue_triage_system_prompt.md"),
    PackageRequirement("support-prompts", "backend/automail/support/prompts/issue_triage_user_prompt.md"),
)

REQUIRED_ADMIN_FILES: tuple[PackageRequirement, ...] = (
    PackageRequirement(
        "admin-entrypoint",
        "admin/src/App.tsx",
        (
            "./routes/Inbox",
            "./routes/Accounts",
            "./routes/Knowledge",
            "./routes/Channels",
            "./routes/Automations",
            "./routes/Analytics",
            "/:tenantId/:projectId/inbox",
            "/:tenantId/:projectId/accounts",
            "/:tenantId/:projectId/knowledge",
            "/:tenantId/:projectId/channels",
            "/:tenantId/:projectId/automations",
            "/:tenantId/:projectId/analytics",
        ),
    ),
    PackageRequirement(
        "admin-entrypoint",
        "admin/src/components/app-sidebar.tsx",
        ("Inbox", "Accounts", "Knowledge", "Analytics", "Workflow rules", "Channel setup"),
    ),
    PackageRequirement(
        "support-admin",
        "admin/src/api/endpoints.ts",
        (
            "SupportWebChatSession",
            "issueIds",
            "messageCount",
            "SupportChannelActivationPlan",
            "getChannelActivationPlan",
            "/channels/activation-plan",
        ),
    ),
    PackageRequirement(
        "support-admin",
        "admin/src/routes/Inbox.tsx",
        (
            "autoSendBlockedReason",
            "low-csat",
            "ticketNextAction",
            "Ticket creation proof",
            "data-ticket-source-proof",
            "data-ticket-source-proof-mode",
            "data-ticket-source-proof-action",
            "data-ticket-reply-route-fix",
            "data-ticket-reply-route-fix-action",
            "Support views",
            "supportViewPresets",
            "data-inbox-support-views",
            "data-inbox-support-view",
        ),
    ),
    PackageRequirement(
        "support-admin",
        "admin/src/routes/InboxAgentPanel.tsx",
        (
            "data-ticket-agent-quick-action",
            "Agent chat",
            "Ask only",
            "Prepare draft",
            "Save article",
            "Use as reply",
        ),
    ),
    PackageRequirement(
        "support-admin",
        "admin/src/routes/InboxMessageTimeline.tsx",
        (
            "data-ticket-split-message",
            "Message timeline",
            "No messages",
            "InboxAttachments",
        ),
    ),
    PackageRequirement(
        "support-admin",
        "admin/src/routes/InboxAttachments.tsx",
        (
            "Attachments",
            "Paperclip",
            "formatBytes",
        ),
    ),
    PackageRequirement("support-admin", "admin/src/routes/Accounts.tsx"),
    PackageRequirement("support-admin", "admin/src/routes/Knowledge.tsx"),
    PackageRequirement(
        "support-admin",
        "admin/src/routes/Channels.tsx",
        (
            "webChatSessionIssueIds",
            "data-web-chat-session-message-count",
            "data-channel-live-target-proof",
            "data-channel-live-target-field",
            "data-channel-ticket-creation-proof",
            "data-channel-ticket-creation-row",
            "support_channel_activation_plan",
            "data-channel-activation-plan-download",
            "data-channel-activation-secret-template-download",
        ),
    ),
    PackageRequirement("support-admin", "admin/src/routes/Automations.tsx"),
    PackageRequirement(
        "support-admin",
        "admin/src/routes/Analytics.tsx",
        (
            "workflow_lifecycle_proof_missing",
            "automation_proof_missing",
            "runLaunchProof",
            "Channel readiness ledger",
            "data-channel-readiness-ledger",
            "data-channel-readiness-row",
            "data-analytics-ticket-creation-proof",
            "data-analytics-ticket-creation-row",
            "data-analytics-reply-route-proof",
            "data-analytics-reply-route-row",
            "data-analytics-human-loop-proof",
            "data-analytics-human-loop-row",
            "data-analytics-channel-autopilot-proof",
            "data-analytics-channel-autopilot-row",
            "data-analytics-knowledge-assist-proof",
            "data-analytics-knowledge-assist-row",
            "data-analytics-account-intelligence-proof",
            "data-analytics-account-intelligence-row",
            "data-analytics-ticket-workflow-proof",
            "data-analytics-ticket-workflow-row",
        ),
    ),
)

REQUIRED_TEST_FILES: tuple[PackageRequirement, ...] = (
    PackageRequirement("support-tests", "backend/tests/test_pb_bootstrap.py", ("support_issues",)),
    PackageRequirement("support-tests", "backend/tests/test_support_bridge.py"),
    PackageRequirement("support-tests", "backend/tests/test_support_crm.py"),
    PackageRequirement("support-tests", "backend/tests/test_support_ingestion.py"),
    PackageRequirement("support-tests", "backend/tests/test_support_issues.py"),
    PackageRequirement("support-tests", "backend/tests/test_support_delivery_hook_integration.py"),
    PackageRequirement("support-tests", "backend/tests/test_support_launch_gate.py"),
    PackageRequirement("support-tests", "backend/tests/test_support_scheduler.py"),
)

REQUIRED_MIGRATION_FILES: tuple[PackageRequirement, ...] = tuple(
    PackageRequirement("support-migration", f"backend/pb_migrations/{name}") for name in SUPPORT_MIGRATIONS
)

REQUIRED_FILES: tuple[PackageRequirement, ...] = (
    REQUIRED_PACKAGE_FILES
    + REQUIRED_BACKEND_FILES
    + REQUIRED_ADMIN_FILES
    + REQUIRED_TEST_FILES
    + REQUIRED_MIGRATION_FILES
)


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def check_package_readiness(root: str | Path | None = None) -> PackageGateResult:
    """Check that release-critical support files and wiring are present."""
    repo_root = Path(root).resolve() if root is not None else default_repo_root()
    missing_paths: list[dict[str, str]] = []
    missing_content: list[dict[str, Any]] = []
    missing_executable: list[dict[str, str]] = []

    for requirement in REQUIRED_FILES:
        target = repo_root / requirement.path
        if not target.is_file():
            missing_paths.append({
                "category": requirement.category,
                "path": requirement.path,
            })
            continue

        if not requirement.required_text:
            continue

        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            missing_content.append({
                "category": requirement.category,
                "path": requirement.path,
                "missing": [f"read failed: {exc}"],
            })
            continue

        missing = [needle for needle in requirement.required_text if needle not in text]
        if missing:
            missing_content.append({
                "category": requirement.category,
                "path": requirement.path,
                "missing": missing,
            })

    for requirement in REQUIRED_EXECUTABLE_FILES:
        target = repo_root / requirement.path
        if not target.is_file():
            continue
        if os.access(target, os.X_OK):
            continue
        missing_executable.append({
            "category": requirement.category,
            "path": requirement.path,
        })

    return PackageGateResult(
        ok=not missing_paths and not missing_content and not missing_executable,
        checked=len(REQUIRED_FILES) + len(REQUIRED_EXECUTABLE_FILES),
        missing_paths=missing_paths,
        missing_content=missing_content,
        missing_executable=missing_executable,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gate support workspace release package readiness.")
    parser.add_argument("--root", default="", help="Repository root. Defaults to this module's repo root.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable check output.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = check_package_readiness(args.root or None)
    except Exception as exc:
        print(f"support package gate: check failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))

    if result.ok:
        print(f"support package gate: ready ({result.checked} checks)")
        return EXIT_READY

    print(f"support package gate: blocked ({result.checked} checks)", file=sys.stderr)
    for item in result.missing_paths:
        print(f"- missing {item['category']}: {item['path']}", file=sys.stderr)
    for item in result.missing_content:
        missing = ", ".join(str(value) for value in item["missing"])
        print(f"- incomplete {item['category']}: {item['path']} missing {missing}", file=sys.stderr)
    for item in result.missing_executable:
        print(f"- not executable {item['category']}: {item['path']}", file=sys.stderr)
    return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
