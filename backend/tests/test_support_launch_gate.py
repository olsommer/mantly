import json
import os
import subprocess
import tarfile
from pathlib import Path

from automail.support import channel_lifecycle_smoke, launch_gate, package_gate, schema_gate


def test_evaluate_launch_proof_ready():
    result = launch_gate.evaluate_launch_proof(
        {
            "status": "ready",
            "schema": {"ready": True},
            "channels": {"blocked": 0},
            "blockers": [],
        }
    )

    assert result.ok is True
    assert result.status == "ready"
    assert result.blockers == []


def test_channel_lifecycle_smoke_evaluates_sent_result_ready():
    result = channel_lifecycle_smoke.evaluate_lifecycle_smoke(
        {
            "status": "sent",
            "sent": True,
            "failed": False,
            "issueId": "issue1",
            "replyId": "reply1",
            "provider": "slack_webhook",
            "providerMessageId": "slack:reply:1",
            "inbound": {"transport": "http"},
        }
    )

    assert result.ok is True
    assert result.status == "sent"
    assert result.issue_id == "issue1"
    assert result.reply_id == "reply1"
    assert result.provider == "slack_webhook"
    assert result.provider_message_id == "slack:reply:1"
    assert result.transport == "http"


def test_channel_lifecycle_smoke_blocks_missing_reply_proof():
    result = channel_lifecycle_smoke.evaluate_lifecycle_smoke(
        {
            "status": "sent",
            "sent": True,
            "failed": False,
            "issueId": "issue1",
            "replyId": "",
        }
    )

    assert result.ok is False
    assert result.issue_id == "issue1"
    assert result.reply_id == ""


def test_channel_lifecycle_smoke_resolves_channel_key_and_posts(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def fake_fetch(method: str, url: str, *, token: str = "", payload=None, timeout: float = 15.0):
        calls.append((method, url, payload))
        assert token == "token123"
        assert timeout == 7
        if method == "GET":
            return {"items": [{"id": "channel1", "channelKey": "slack-main"}]}
        return {
            "status": "sent",
            "sent": True,
            "failed": False,
            "issueId": "issue1",
            "replyId": "reply1",
            "provider": "slack_webhook",
            "providerMessageId": "slack:reply:1",
            "inbound": {"transport": "http"},
        }

    monkeypatch.setattr(channel_lifecycle_smoke, "fetch_json", fake_fetch)
    args = channel_lifecycle_smoke._parser().parse_args([
        "--api-url",
        "https://app.example.test",
        "--project-id",
        "project1",
        "--channel-key",
        "slack-main",
        "--token",
        "token123",
        "--timeout",
        "7",
        "--body",
        "Customer message",
        "--reply-body",
        "Reply body",
    ])
    args.attachments = args.attachment
    args.reply_attachments = args.reply_attachment

    payload = channel_lifecycle_smoke.run_channel_lifecycle_smoke(args)
    result = channel_lifecycle_smoke.evaluate_lifecycle_smoke(payload)

    assert result.ok is True
    assert calls[0][0] == "GET"
    assert calls[0][1] == "https://app.example.test/api/admin/projects/project1/channels?limit=200"
    assert calls[1][0] == "POST"
    assert calls[1][1] == "https://app.example.test/api/admin/projects/project1/channels/channel1/lifecycle-smoke"
    assert calls[1][2]["transport"] == "http"
    assert calls[1][2]["body"] == "Customer message"
    assert calls[1][2]["replyBody"] == "Reply body"


def test_channel_lifecycle_smoke_main_allows_attachment_only_message(monkeypatch, capsys):
    calls: list[dict] = []

    def fake_run(args):
        calls.append({
            "body": args.body,
            "attachments": args.attachments,
            "replyAttachments": args.reply_attachments,
        })
        return {
            "status": "sent",
            "sent": True,
            "failed": False,
            "issueId": "issue1",
            "replyId": "reply1",
            "provider": "slack_webhook",
            "providerMessageId": "slack:reply:1",
            "inbound": {"transport": "http"},
        }

    monkeypatch.setattr(channel_lifecycle_smoke, "run_channel_lifecycle_smoke", fake_run)

    code = channel_lifecycle_smoke.main([
        "--api-url",
        "https://app.example.test",
        "--project-id",
        "project1",
        "--channel-key",
        "slack-main",
        "--body",
        "",
        "--reply-body",
        "Reply body",
        "--attachment",
        '{"id":"file1","filename":"incident.txt","url":"https://files.example/incident.txt"}',
    ])

    captured = capsys.readouterr()
    assert code == channel_lifecycle_smoke.EXIT_READY
    assert "support channel lifecycle smoke: ok status=sent transport=http" in captured.out
    assert calls == [{
        "body": "",
        "attachments": [{"id": "file1", "filename": "incident.txt", "url": "https://files.example/incident.txt"}],
        "replyAttachments": [],
    }]


def test_evaluate_launch_proof_reports_warning_details_when_attention_blocks():
    result = launch_gate.evaluate_launch_proof(
        {
            "status": "needs_attention",
            "schema": {"ready": True},
            "channels": {"blocked": 0},
            "blockers": [],
            "warnings": [
                {"key": "open_knowledge_gaps", "label": "Open knowledge gaps", "count": 2}
            ],
        }
    )

    assert result.ok is False
    assert result.status == "needs_attention"
    assert result.blockers == [
        "launch status is needs_attention",
        "Open knowledge gaps (2)",
    ]


def test_evaluate_launch_proof_can_allow_attention_warnings():
    result = launch_gate.evaluate_launch_proof(
        {
            "status": "needs_attention",
            "schema": {"ready": True},
            "channels": {"blocked": 0},
            "blockers": [],
            "warnings": [
                {"key": "open_knowledge_gaps", "label": "Open knowledge gaps", "count": 2}
            ],
        },
        allow_needs_attention=True,
    )

    assert result.ok is True
    assert result.status == "needs_attention"
    assert result.blockers == []


def test_evaluate_launch_proof_blocks_schema_and_channel_failures():
    result = launch_gate.evaluate_launch_proof(
        {
            "status": "blocked",
            "schema": {
                "ready": False,
                "missingCollections": ["support_messages"],
                "missingFields": ["support_issues.tags"],
                "missingMigrationFiles": ["48_support_issue_tags.js"],
            },
            "channels": {"blocked": 2},
            "blockers": [
                {"key": "channel_lifecycle_smoke_missing", "label": "Lifecycle smoke missing", "count": 1}
            ],
        }
    )

    assert result.ok is False
    assert result.status == "blocked"
    assert result.blockers == [
        "launch status is blocked",
        "schema not ready (1 collections, 1 fields, 1 migrations missing)",
        "2 channel launch proofs blocked",
        "Lifecycle smoke missing (1)",
    ]


def test_evaluate_launch_proof_includes_channel_blocker_detail():
    result = launch_gate.evaluate_launch_proof(
        {
            "status": "blocked",
            "schema": {"ready": True},
            "channels": {
                "blocked": 1,
                "items": [
                    {
                        "channelKey": "slack-main",
                        "name": "Slack Main",
                        "type": "slack",
                        "required": True,
                        "ready": False,
                        "blockers": [
                            {
                                "key": "live_smoke_target",
                                "label": "Live proof target configured",
                                "detail": "Set smokeChannelId to a real Slack channel ID before launch proof",
                                "action": "configure_smoke_target",
                            }
                        ],
                    }
                ],
            },
            "blockers": [],
        }
    )

    assert result.ok is False
    assert result.blockers == [
        "launch status is blocked",
        "1 channel launch proofs blocked",
        (
            "channel Slack Main (slack-main) blocked: Live proof target configured: "
            "Set smokeChannelId to a real Slack channel ID before launch proof "
            "[action: configure_smoke_target]"
        ),
    ]


def test_main_exits_ready(monkeypatch, capsys):
    monkeypatch.setattr(
        launch_gate,
        "fetch_launch_proof",
        lambda **_kwargs: {
            "status": "ready",
            "schema": {"ready": True},
            "channels": {"blocked": 0},
            "blockers": [],
        },
    )

    code = launch_gate.main(["--base-url", "https://app.example.test", "--project-id", "project1"])

    captured = capsys.readouterr()
    assert code == launch_gate.EXIT_READY
    assert "support launch gate: ready (ready)" in captured.out
    assert captured.err == ""


def test_main_run_executes_proof_actions_before_evaluation(monkeypatch, capsys):
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {
            "status": "ready",
            "schema": {"ready": True},
            "channels": {"blocked": 0},
            "blockers": [],
        }

    monkeypatch.setattr(launch_gate, "run_launch_proof", fake_run)
    monkeypatch.setattr(
        launch_gate,
        "fetch_launch_proof",
        lambda **_kwargs: {"status": "blocked"},
    )

    code = launch_gate.main([
        "--base-url",
        "https://app.example.test",
        "--project-id",
        "project1",
        "--token",
        "token1",
        "--run",
    ])

    captured = capsys.readouterr()
    assert code == launch_gate.EXIT_READY
    assert calls == [{
        "base_url": "https://app.example.test",
        "project_id": "project1",
        "token": "token1",
        "timeout": 15.0,
    }]
    assert "support launch gate: ready (ready)" in captured.out
    assert captured.err == ""


def test_build_launch_proof_bundle_includes_runtime_artifacts():
    proof = {
        "status": "ready",
        "schema": {"ready": True},
        "channels": {
            "blocked": 0,
            "items": [
                {
                    "channelId": "channel1",
                    "channelKey": "slack-main",
                    "name": "Slack",
                    "type": "slack",
                    "required": True,
                    "checklist": [
                        {
                            "key": "ticket_mode",
                            "status": "done",
                            "runStatus": "per_message",
                            "detail": "New messages create new tickets",
                        },
                        {
                            "key": "lifecycle_smoke",
                            "status": "done",
                            "runId": "life1",
                            "transport": "http",
                            "providerMessageId": "slack:C123:1",
                            "issueId": "issue1",
                            "replyId": "reply1",
                            "detail": "Lifecycle smoke delivered reply",
                        },
                        {
                            "key": "channel_autopilot",
                            "status": "done",
                            "runId": "event-autopilot-1",
                            "issueId": "issue1",
                            "replyId": "reply1",
                            "aiRunId": "run1",
                            "detail": "Agent prepared triage, fields, and draft reply1 for ticket issue1",
                        }
                    ],
                }
            ],
        },
        "evidence": {
            "humanLoopAutomation": [
                {
                    "kind": "human_loop_automation",
                    "label": "Human-loop automation proof",
                    "detail": "Automation prepared an approval-required agent draft",
                    "issueId": "issue1",
                    "replyId": "reply1",
                    "runId": "auto1",
                }
            ],
            "workflowLifecycle": [
                {
                    "kind": "workflow_lifecycle",
                    "label": "Workflow lifecycle proof",
                    "detail": "Ticket moved through Ongoing and Done",
                    "issueId": "issue1",
                    "eventIds": ["event-ongoing", "event-done"],
                }
            ],
            "knowledgeAssist": [
                {
                    "kind": "knowledge_assist",
                    "label": "Ticket knowledge assist proof",
                    "detail": "Agent answer cited 1 knowledge article(s)",
                    "issueId": "issue1",
                    "replyId": "reply1",
                    "runId": "run1",
                    "citationCount": 1,
                    "knowledgeArticleIds": ["article1"],
                }
            ],
            "accountIntelligence": [
                {
                    "kind": "account_intelligence",
                    "label": "Account intelligence proof",
                    "detail": "1 urgent ticket needs owner follow-up.",
                    "accountId": "account1",
                    "accountName": "Acme",
                    "healthStatus": "at_risk",
                    "actionKind": "review_urgent_tickets",
                    "actionLabel": "Review urgent tickets",
                    "openIssues": 1,
                    "openRisks": 1,
                    "openFeatureRequests": 1,
                    "failedExternalSyncRuns": 0,
                }
            ]
        },
        "blockers": [],
    }
    schema_payload = {"health": {"ready": True}}
    run_history = [{"id": "run1", "status": "success"}]
    activation_plan = {
        "kind": "support_channel_activation_plan",
        "projectId": "project1",
        "summary": {"nextActionCount": 1},
    }

    bundle = launch_gate.build_launch_proof_bundle(
        project_id="project1",
        proof=proof,
        schema_payload=schema_payload,
        run_history=run_history,
        activation_plan=activation_plan,
    )

    assert bundle["kind"] == "support_launch_proof_bundle"
    assert bundle["projectId"] == "project1"
    assert bundle["status"] == "ready"
    assert bundle["launchProof"] == proof
    assert bundle["ticketCreation"]["total"] == 1
    assert bundle["ticketCreation"]["ready"] == 1
    assert bundle["ticketCreation"]["blocked"] == 0
    assert bundle["ticketCreation"]["items"][0]["mode"] == "per_message"
    assert bundle["replyRoute"]["total"] == 1
    assert bundle["replyRoute"]["ready"] == 1
    assert bundle["replyRoute"]["blocked"] == 0
    assert bundle["replyRoute"]["items"][0]["proofKey"] == "lifecycle_smoke"
    assert bundle["replyRoute"]["items"][0]["replyId"] == "reply1"
    assert bundle["channelAutopilot"]["total"] == 1
    assert bundle["channelAutopilot"]["ready"] == 1
    assert bundle["channelAutopilot"]["blocked"] == 0
    assert bundle["channelAutopilot"]["items"][0]["proofKey"] == "channel_autopilot"
    assert bundle["channelAutopilot"]["items"][0]["aiRunId"] == "run1"
    assert bundle["knowledgeAssist"]["ready"] is True
    assert bundle["knowledgeAssist"]["blocked"] == 0
    assert bundle["knowledgeAssist"]["successfulRuns"] == 1
    assert bundle["knowledgeAssist"]["citationRuns"] == 1
    assert bundle["knowledgeAssist"]["gapRuns"] == 0
    assert bundle["knowledgeAssist"]["items"][0]["runId"] == "run1"
    assert bundle["accountIntelligence"]["ready"] is True
    assert bundle["accountIntelligence"]["blocked"] == 0
    assert bundle["accountIntelligence"]["accounts"] == 1
    assert bundle["accountIntelligence"]["actions"] == 1
    assert bundle["accountIntelligence"]["openRisks"] == 1
    assert bundle["accountIntelligence"]["featureRequests"] == 1
    assert bundle["accountIntelligence"]["items"][0]["accountId"] == "account1"
    assert bundle["humanLoop"]["ready"] is True
    assert bundle["humanLoop"]["blocked"] == 0
    assert bundle["humanLoop"]["rules"] == 1
    assert bundle["humanLoop"]["successfulRuns"] == 1
    assert bundle["humanLoop"]["items"][0]["replyId"] == "reply1"
    assert bundle["ticketWorkflow"]["ready"] is True
    assert bundle["ticketWorkflow"]["blocked"] == 0
    assert bundle["ticketWorkflow"]["successfulIssues"] == 1
    assert bundle["ticketWorkflow"]["items"][0]["issueId"] == "issue1"
    assert bundle["activationPlan"] == activation_plan
    assert bundle["activationPlanError"] == ""
    assert bundle["schemaGate"] == schema_payload
    assert bundle["latestRun"] == run_history[0]
    assert bundle["runHistory"] == run_history
    assert bundle["runHistoryError"] == ""
    assert bundle["exportedAt"]


def test_main_writes_launch_proof_bundle_file(monkeypatch, tmp_path, capsys):
    bundle_file = tmp_path / "launch-proof.json"

    monkeypatch.setattr(
        launch_gate,
        "fetch_launch_proof",
        lambda **_kwargs: {
            "status": "ready",
            "schema": {"ready": True},
            "channels": {"blocked": 0},
            "blockers": [],
        },
    )
    monkeypatch.setattr(
        launch_gate,
        "fetch_launch_proof_runs",
        lambda **_kwargs: [{"id": "run1", "status": "success"}],
    )
    monkeypatch.setattr(
        launch_gate,
        "fetch_channel_activation_plan",
        lambda **_kwargs: {"kind": "support_channel_activation_plan", "projectId": "project1"},
    )

    code = launch_gate.main([
        "--base-url",
        "https://app.example.test",
        "--project-id",
        "project1",
        "--bundle-file",
        str(bundle_file),
    ])

    captured = capsys.readouterr()
    payload = json.loads(bundle_file.read_text())
    assert code == launch_gate.EXIT_READY
    assert payload["kind"] == "support_launch_proof_bundle"
    assert payload["projectId"] == "project1"
    assert payload["launchProof"]["status"] == "ready"
    assert payload["activationPlan"]["kind"] == "support_channel_activation_plan"
    assert payload["activationPlanError"] == ""
    assert payload["latestRun"]["id"] == "run1"
    assert payload["runHistory"] == [{"id": "run1", "status": "success"}]
    assert "support launch gate: ready (ready)" in captured.out
    assert captured.err == ""


def test_main_uses_launch_gate_bundle_file_env(monkeypatch, tmp_path, capsys):
    bundle_file = tmp_path / "env-launch-proof.json"

    monkeypatch.setenv("SUPPORT_LAUNCH_GATE_BUNDLE_FILE", str(bundle_file))
    monkeypatch.setattr(
        launch_gate,
        "fetch_launch_proof",
        lambda **_kwargs: {
            "status": "ready",
            "schema": {"ready": True},
            "channels": {"blocked": 0},
            "blockers": [],
        },
    )
    monkeypatch.setattr(launch_gate, "fetch_launch_proof_runs", lambda **_kwargs: [])
    monkeypatch.setattr(
        launch_gate,
        "fetch_channel_activation_plan",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("activation plan unavailable")),
    )

    code = launch_gate.main([
        "--base-url",
        "https://app.example.test",
        "--project-id",
        "project1",
    ])

    captured = capsys.readouterr()
    payload = json.loads(bundle_file.read_text())
    assert code == launch_gate.EXIT_READY
    assert payload["kind"] == "support_launch_proof_bundle"
    assert payload["projectId"] == "project1"
    assert payload["activationPlan"] is None
    assert payload["activationPlanError"] == "activation plan unavailable"
    assert payload["runHistory"] == []
    assert "support launch gate: ready (ready)" in captured.out
    assert captured.err == ""


def test_main_schema_gate_runs_before_fetch(monkeypatch, capsys):
    calls: list[str] = []

    def fake_schema(**kwargs):
        calls.append(f"schema:{kwargs['bootstrap']}")
        return {
            "bootstrap": {},
            "health": {
                "status": "ready",
                "ready": True,
                "presentCollections": 37,
                "requiredCollections": 37,
                "presentFields": 13,
                "requiredFields": 13,
                "missingCollections": [],
                "missingFields": [],
                "missingMigrationFiles": [],
            },
        }

    def fake_fetch(**kwargs):
        calls.append(f"fetch:{kwargs['project_id']}")
        return {
            "status": "ready",
            "schema": {"ready": True},
            "channels": {"blocked": 0},
            "blockers": [],
        }

    monkeypatch.setattr(launch_gate, "check_support_schema", fake_schema)
    monkeypatch.setattr(launch_gate, "fetch_launch_proof", fake_fetch)

    code = launch_gate.main([
        "--base-url",
        "https://app.example.test",
        "--project-id",
        "project1",
        "--schema-gate",
    ])

    captured = capsys.readouterr()
    assert code == launch_gate.EXIT_READY
    assert calls == ["schema:True", "fetch:project1"]
    assert "support launch gate: schema preflight ready (37/37 collections, 13/13 fields)" in captured.out
    assert "support launch gate: ready (ready)" in captured.out
    assert captured.err == ""


def test_main_schema_gate_can_skip_bootstrap(monkeypatch, capsys):
    calls: list[bool] = []

    monkeypatch.setattr(
        launch_gate,
        "check_support_schema",
        lambda **kwargs: calls.append(kwargs["bootstrap"]) or {
            "bootstrap": {},
            "health": {
                "status": "ready",
                "ready": True,
                "presentCollections": 37,
                "requiredCollections": 37,
                "presentFields": 13,
                "requiredFields": 13,
                "missingCollections": [],
                "missingFields": [],
                "missingMigrationFiles": [],
            },
        },
    )
    monkeypatch.setattr(
        launch_gate,
        "fetch_launch_proof",
        lambda **_kwargs: {
            "status": "ready",
            "schema": {"ready": True},
            "channels": {"blocked": 0},
            "blockers": [],
        },
    )

    code = launch_gate.main([
        "--base-url",
        "https://app.example.test",
        "--project-id",
        "project1",
        "--schema-gate",
        "--no-schema-bootstrap",
    ])

    assert code == launch_gate.EXIT_READY
    assert calls == [False]
    assert "schema preflight ready" in capsys.readouterr().out


def test_main_schema_gate_blocks_before_fetch(monkeypatch, capsys):
    monkeypatch.setattr(
        launch_gate,
        "check_support_schema",
        lambda **_kwargs: {
            "bootstrap": {},
            "health": {
                "status": "missing",
                "ready": False,
                "missingCollections": ["support_messages"],
                "missingFields": ["support_issues.tags"],
                "missingMigrationFiles": [],
            },
        },
    )
    monkeypatch.setattr(
        launch_gate,
        "fetch_launch_proof",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("fetch should be skipped")),
    )

    code = launch_gate.main([
        "--base-url",
        "https://app.example.test",
        "--project-id",
        "project1",
        "--schema-gate",
    ])

    captured = capsys.readouterr()
    assert code == launch_gate.EXIT_BLOCKED
    assert captured.out == ""
    assert "support launch gate: schema preflight blocked (missing)" in captured.err
    assert "1 support collections missing" in captured.err
    assert "1 support fields missing" in captured.err


def test_main_schema_gate_blocked_writes_bundle_file(monkeypatch, tmp_path, capsys):
    bundle_file = tmp_path / "schema-blocked-launch-proof.json"

    monkeypatch.setattr(
        launch_gate,
        "check_support_schema",
        lambda **_kwargs: {
            "bootstrap": {"created_collections": []},
            "health": {
                "status": "missing",
                "ready": False,
                "missingCollections": ["support_messages"],
                "missingFields": ["support_issues.tags"],
                "missingMigrationFiles": [],
            },
        },
    )
    monkeypatch.setattr(
        launch_gate,
        "fetch_launch_proof",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("fetch should be skipped")),
    )
    monkeypatch.setattr(
        launch_gate,
        "fetch_launch_proof_runs",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("run history fetch should be skipped")),
    )
    monkeypatch.setattr(
        launch_gate,
        "fetch_channel_activation_plan",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("activation plan fetch should be skipped")),
    )

    code = launch_gate.main([
        "--base-url",
        "https://app.example.test",
        "--project-id",
        "project1",
        "--schema-gate",
        "--bundle-file",
        str(bundle_file),
    ])

    captured = capsys.readouterr()
    payload = json.loads(bundle_file.read_text())
    assert code == launch_gate.EXIT_BLOCKED
    assert payload["kind"] == "support_launch_proof_bundle"
    assert payload["projectId"] == "project1"
    assert payload["status"] == "blocked"
    assert payload["schemaGate"]["health"]["status"] == "missing"
    assert payload["launchProof"]["status"] == "blocked"
    assert payload["launchProof"]["schema"]["missingCollections"] == ["support_messages"]
    assert payload["launchProof"]["blockers"][0] == {
        "key": "schema_gate_blocked",
        "label": "Schema gate blocked",
        "count": 2,
        "detail": "1 support collections missing; 1 support fields missing",
    }
    assert payload["latestRun"] is None
    assert payload["runHistory"] == []
    assert payload["runHistoryError"] == "schema gate blocked before launch proof fetch"
    assert payload["activationPlan"] is None
    assert payload["activationPlanError"] == "schema gate blocked before activation plan fetch"
    assert captured.out == ""
    assert "support launch gate: schema preflight blocked (missing)" in captured.err


def test_main_exits_blocked(monkeypatch, capsys):
    monkeypatch.setattr(
        launch_gate,
        "fetch_launch_proof",
        lambda **_kwargs: {
            "status": "blocked",
            "schema": {"ready": True},
            "channels": {"blocked": 1},
            "blockers": [{"key": "channel_smoke_missing", "label": "Channel smoke missing", "count": 1}],
        },
    )

    code = launch_gate.main(["--base-url", "https://app.example.test", "--project-id", "project1"])

    captured = capsys.readouterr()
    assert code == launch_gate.EXIT_BLOCKED
    assert captured.out == ""
    assert "support launch gate: blocked (blocked)" in captured.err
    assert "Channel smoke missing (1)" in captured.err


def test_main_requires_base_url(capsys):
    code = launch_gate.main(["--project-id", "project1"])

    captured = capsys.readouterr()
    assert code == launch_gate.EXIT_ERROR
    assert "--base-url" in captured.err


def test_schema_gate_evaluate_ready():
    result = schema_gate.evaluate_schema_health(
        {
            "status": "ready",
            "ready": True,
            "missingCollections": [],
            "missingFields": [],
            "missingMigrationFiles": [],
        }
    )

    assert result.ok is True
    assert result.status == "ready"
    assert result.blockers == []


def test_schema_gate_evaluate_blocks_missing_schema():
    result = schema_gate.evaluate_schema_health(
        {
            "status": "missing",
            "ready": False,
            "missingCollections": ["support_issues", "support_messages"],
            "missingFields": ["support_issues.tags"],
            "missingMigrationFiles": ["48_support_issue_tags.js"],
        }
    )

    assert result.ok is False
    assert result.status == "missing"
    assert result.blockers == [
        "2 support collections missing",
        "1 support fields missing",
        "1 migration files missing",
    ]


def test_schema_gate_main_bootstraps_before_check(monkeypatch, capsys):
    calls: list[str] = []

    monkeypatch.setattr(
        schema_gate,
        "ensure_app_collections_schema",
        lambda: calls.append("bootstrap") or {"created_collections": ["support_issues"]},
    )
    monkeypatch.setattr(
        schema_gate,
        "support_schema_health",
        lambda: {
            "status": "ready",
            "ready": True,
            "presentCollections": 37,
            "requiredCollections": 37,
            "presentFields": 13,
            "requiredFields": 13,
            "missingCollections": [],
            "missingFields": [],
            "missingMigrationFiles": [],
        },
    )

    code = schema_gate.main([])

    captured = capsys.readouterr()
    assert code == schema_gate.EXIT_READY
    assert calls == ["bootstrap"]
    assert "support schema gate: ready (37/37 collections, 13/13 fields)" in captured.out
    assert captured.err == ""


def test_schema_gate_main_can_skip_bootstrap(monkeypatch, capsys):
    monkeypatch.setattr(
        schema_gate,
        "ensure_app_collections_schema",
        lambda: (_ for _ in ()).throw(AssertionError("bootstrap should be skipped")),
    )
    monkeypatch.setattr(
        schema_gate,
        "support_schema_health",
        lambda: {
            "status": "missing",
            "ready": False,
            "missingCollections": ["support_messages"],
            "missingFields": [],
            "missingMigrationFiles": [],
        },
    )

    code = schema_gate.main(["--no-bootstrap"])

    captured = capsys.readouterr()
    assert code == schema_gate.EXIT_BLOCKED
    assert captured.out == ""
    assert "support schema gate: blocked (missing)" in captured.err
    assert "1 support collections missing" in captured.err


def test_package_gate_current_repo_ready():
    result = package_gate.check_package_readiness()

    assert result.ok is True
    assert result.checked == len(package_gate.REQUIRED_FILES) + len(package_gate.REQUIRED_EXECUTABLE_FILES)
    assert result.missing_paths == []
    assert result.missing_content == []
    assert result.missing_executable == []


def test_package_gate_covers_pylon_release_invariants():
    requirements = {
        requirement.path: set(requirement.required_text)
        for requirement in package_gate.REQUIRED_FILES
    }

    assert {
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
    }.issubset(requirements["backend/automail/db/pocketbase/issues.py"])
    assert {
        "SupportWebChatSession",
        "issueIds",
        "messageCount",
        "SupportChannelActivationPlan",
        "getChannelActivationPlan",
        "/channels/activation-plan",
    }.issubset(requirements["admin/src/api/endpoints.ts"])
    assert {
        "get_channel_activation_plan",
        "/projects/{pid}/channels/activation-plan",
        "support_channel_activation_plan",
    }.issubset(requirements["backend/automail/api/admin/channels.py"])
    assert {
        "webChatSessionIssueIds",
        "data-web-chat-session-message-count",
        "data-channel-live-target-proof",
        "data-channel-live-target-field",
        "data-channel-ticket-creation-proof",
        "data-channel-ticket-creation-row",
        "support_channel_activation_plan",
        "data-channel-activation-plan-download",
        "data-channel-activation-secret-template-download",
    }.issubset(requirements["admin/src/routes/Channels.tsx"])
    assert {
        "data.messages",
        "latestTicketId",
        "Ticket opened:",
        "automail-support-chat-status",
        "data-automail-support-chat-latest-ticket",
    }.issubset(requirements["backend/automail/api/support_web_chat.py"])
    assert {
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
    }.issubset(requirements["admin/src/routes/Inbox.tsx"])
    assert {
        "data-ticket-agent-quick-action",
        "Agent chat",
        "Ask only",
        "Prepare draft",
        "Save article",
        "Use as reply",
    }.issubset(requirements["admin/src/routes/InboxAgentPanel.tsx"])
    assert {
        "data-ticket-split-message",
        "Message timeline",
        "No messages",
        "InboxAttachments",
    }.issubset(requirements["admin/src/routes/InboxMessageTimeline.tsx"])
    assert {
        "Attachments",
        "Paperclip",
        "formatBytes",
    }.issubset(requirements["admin/src/routes/InboxAttachments.tsx"])
    assert {
        "Live low CSAT is now actionable immediately",
        "confidence_guard",
        "workflow_lifecycle_proof_missing",
    }.issubset(requirements["docs/pylon-pivot-rfc.md"])
    assert {
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
    }.issubset(requirements["backend/automail/support/launch_gate.py"])
    assert {
        "--bundle-file",
        "SUPPORT_LAUNCH_GATE_BUNDLE_FILE",
        "SUPPORT_LAUNCH_GATE_BUNDLE_OUT",
        "SUPPORT_LAUNCH_GATE_COPY_BUNDLE",
        "app:$EFFECTIVE_BUNDLE_FILE",
    }.issubset(requirements["deploy/support-launch-gate.sh"])
    assert {
        "SUPPORT_LAUNCH_GATE_TIMEOUT",
        "REGISTRY",
        "SUPPORT_LAUNCH_GATE_BUNDLE_FILE",
        "SUPPORT_LAUNCH_GATE_BUNDLE_OUT",
        "SUPPORT_LAUNCH_GATE_COPY_BUNDLE",
        "SUPPORT_CHANNEL_ACTIVATION_PLAN_OUT",
        "SUPPORT_CHANNEL_ACTIVATION_SECRETS_OUT",
        "SUPPORT_CHANNEL_ACTIVATION_WRITE_SECRETS",
    }.issubset(requirements["deploy/.env.example"])
    assert {
        "${REGISTRY:-ghcr.io/isarlabs}/isarai-email-agent",
        "${REGISTRY:-ghcr.io/isarlabs}/isarai-pocketbase",
    }.issubset(requirements["deploy/docker-compose.yml"])
    assert {
        "release-manifest.json",
        "support-channel-activation-plan.sh",
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
    }.issubset(requirements["scripts/package-customer.sh"])
    assert {
        "channels/activation-plan",
        "SUPPORT_CHANNEL_ACTIVATION_PLAN_OUT",
        "SUPPORT_CHANNEL_ACTIVATION_SECRETS_OUT",
        "ADMIN_AUTH_TOKEN",
    }.issubset(requirements["deploy/support-channel-activation-plan.sh"])
    assert {
        "package-customer.sh",
        "SKIP_CUSTOMER_PACKAGE",
        "validate_version",
        "validate_registry",
        "Invalid VERSION",
        "Invalid REGISTRY",
    }.issubset(requirements["scripts/release-onprem.sh"])
    assert {
        "support-channel-lifecycle-smoke.sh",
        "support-channel-activation-plan.sh",
        "release-manifest.json",
        "supportPackageGate",
        "support-launch-proof.json",
        "supportChannelActivationPlan",
        "support-channel-activation-plan",
        "SUPPORT_CHANNEL_ACTIVATION_PLAN_OUT",
        "SUPPORT_CHANNEL_ACTIVATION_SECRETS_OUT",
        "REGISTRY",
        "SUPPORT_LAUNCH_GATE_BUNDLE_FILE",
        "SUPPORT_LAUNCH_GATE_BUNDLE_OUT",
        "SUPPORT_LAUNCH_GATE_COPY_BUNDLE",
        "SKIP_CUSTOMER_PACKAGE",
    }.issubset(requirements["docs/deploy-onprem.md"])
    assert {
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
    }.issubset(requirements["admin/src/routes/Analytics.tsx"])


def test_package_customer_manifest_includes_package_gate_evidence():
    root = Path(__file__).resolve().parents[2]
    version = "test-manifest"
    tar_path = root / "dist" / f"mantly-{version}.tar.gz"
    tar_path.unlink(missing_ok=True)

    result = subprocess.run(
        ["bash", str(root / "scripts/package-customer.sh"), version],
        cwd=root,
        env={**os.environ, "REGISTRY": "ghcr.io/isarlabs"},
        capture_output=True,
        text=True,
        check=False,
    )

    try:
        assert result.returncode == 0, result.stderr
        assert tar_path.is_file()
        with tarfile.open(tar_path, "r:gz") as archive:
            names = set(archive.getnames())
            assert f"mantly-{version}/support-channel-activation-plan.sh" in names
            member = archive.extractfile(f"mantly-{version}/release-manifest.json")
            assert member is not None
            manifest = json.loads(member.read().decode("utf-8"))

        assert manifest["supportPackageGate"] == {
            "ready": True,
            "checked": len(package_gate.REQUIRED_FILES) + len(package_gate.REQUIRED_EXECUTABLE_FILES),
        }
        assert "support-channel-activation-plan.sh" in manifest["supportScripts"]
        assert manifest["supportLaunchProof"]["bundleFile"] == "support-launch-proof.json"
        assert manifest["supportChannelActivationPlan"] == {
            "kind": "support_channel_activation_plan",
            "script": "./support-channel-activation-plan.sh",
            "apiPath": "/api/admin/projects/<project-id>/channels/activation-plan",
            "adminRoute": "/channels",
            "downloadFile": "support-channel-activation-plan-<project-id>.json",
            "planFile": "support-channel-activation-plan.json",
            "secretTemplateFile": "support-channel-activation-secrets.env",
        }
    finally:
        tar_path.unlink(missing_ok=True)


def test_package_customer_rejects_invalid_version_before_packaging():
    root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        ["bash", str(root / "scripts/package-customer.sh"), "bad tag"],
        cwd=root,
        env={**os.environ, "REGISTRY": "ghcr.io/isarlabs"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 64
    assert "Invalid VERSION 'bad tag'" in result.stderr
    assert "Checking support package readiness" not in result.stdout


def test_release_onprem_rejects_invalid_registry_before_build():
    root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        ["bash", str(root / "scripts/release-onprem.sh"), "1.2.3"],
        cwd=root,
        env={**os.environ, "REGISTRY": "bad registry"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 64
    assert "Invalid REGISTRY 'bad registry'" in result.stderr
    assert "Checking support package readiness" not in result.stdout
    assert "docker buildx" not in result.stdout


def test_package_gate_reports_missing_paths(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "deploy-onprem.md").write_text("support-launch-gate.sh", encoding="utf-8")

    result = package_gate.check_package_readiness(tmp_path)

    assert result.ok is False
    assert {
        "category": "customer-package",
        "path": "scripts/package-customer.sh",
    } in result.missing_paths


def test_package_gate_reports_missing_content(tmp_path):
    for requirement in package_gate.REQUIRED_FILES:
        target = tmp_path / requirement.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(requirement.required_text), encoding="utf-8")

    app_path = tmp_path / "admin/src/App.tsx"
    app_path.write_text("./routes/Inbox", encoding="utf-8")

    result = package_gate.check_package_readiness(tmp_path)

    assert result.ok is False
    assert {
        "category": "admin-entrypoint",
        "path": str(Path("admin/src/App.tsx")),
        "missing": [
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
        ],
    } in result.missing_content


def test_package_gate_reports_non_executable_release_helpers(tmp_path):
    for requirement in package_gate.REQUIRED_FILES:
        target = tmp_path / requirement.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(requirement.required_text), encoding="utf-8")

    for requirement in package_gate.REQUIRED_EXECUTABLE_FILES:
        target = tmp_path / requirement.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        target.chmod(0o755)

    blocked = tmp_path / "deploy/support-launch-gate.sh"
    blocked.chmod(0o644)

    result = package_gate.check_package_readiness(tmp_path)

    assert result.ok is False
    assert result.missing_paths == []
    assert result.missing_content == []
    assert result.missing_executable == [{
        "category": "customer-package",
        "path": "deploy/support-launch-gate.sh",
    }]


def test_package_gate_main_exits_ready(capsys):
    code = package_gate.main([])

    captured = capsys.readouterr()
    assert code == package_gate.EXIT_READY
    assert "support package gate: ready" in captured.out
    assert captured.err == ""
