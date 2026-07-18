import json

import pytest

from automail.db.pocketbase import issues
from automail.integrations.http_tool import (
    HttpToolExecutionFenced,
    ToolDefinition,
    _capture_generated_file,
    _make_http_tool,
    _record_tool_call,
    fence_http_tool_execution,
)
from automail.models import (
    ConcernRoute,
    IntentAction,
    IntentResult,
    IntentReviewOutput,
    RunbookOutcome,
)
from automail.support import channel_runbooks
from automail.support.channel_runbooks import DirectChannelRunbookResult


def test_direct_channel_runner_keeps_two_concerns_in_one_result(monkeypatch):
    captured = {}

    def fake_run_intent_agent(**kwargs):
        captured.update(kwargs)
        return (
            IntentResult(
                matched=True,
                intent_name="cancel_contract",
                concerns=[
                    RunbookOutcome(
                        concern_id="concern-cancel",
                        concern_summary="Cancel contract",
                        source_text="Cancel our contract.",
                        matched=True,
                        intent_name="cancel_contract",
                        status="ready",
                        summary="Contract cancellation requested",
                    ),
                    RunbookOutcome(
                        concern_id="concern-buy",
                        concern_summary="Buy boxes",
                        source_text="Also quote 200 boxes.",
                        matched=True,
                        intent_name="buy_boxes",
                        status="ready",
                        summary="Box quote requested",
                        actions=[
                            IntentAction(
                                name="request_quote",
                                label="Request quote",
                                webhook="https://example.test/quote",
                            )
                        ],
                    ),
                ],
            ),
            None,
        )

    monkeypatch.setattr(channel_runbooks, "run_intent_agent", fake_run_intent_agent)

    result = channel_runbooks.run_direct_channel_runbooks(
        source_message_id="slack:T1:C1:100.1",
        subject="Cancel and buy",
        body="Cancel our contract. Also quote 200 boxes.",
        from_address="slack:T1:U1",
        identity={
            "account_name": "Acme",
            "account_domain": "",
            "contact_email": "slack:T1:U1",
            "contact_name": "Ana",
        },
        identity_data={"provider": "slack", "userId": "U1"},
        config_source="live-source",
        tenant_id="tenant1",
        project_id="project1",
    )

    assert len(result.intent_result["concerns"]) == 2
    assert result.requires_human is False
    assert result.summary == "Contract cancellation requested; Box quote requested"
    assert captured["email"].id == "slack:T1:C1:100.1"
    assert captured["email"].body == "Cancel our contract. Also quote 200 boxes."
    assert captured["identity_result"].data["provider"] == "slack"
    assert captured["intents_dir"] == "live-source"
    assert captured["tenant_id"] == "tenant1"
    assert captured["project_id"] == "project1"
    assert result.intent_result["concerns"][1]["actions"][0]["payload"]["userId"] == "U1"


def test_direct_channel_merges_isolated_concern_activity_in_route_order(monkeypatch):
    routes = [
        ConcernRoute(summary="First", source_text="First request", intent_name="first-runbook"),
        ConcernRoute(summary="Second", source_text="Second request", intent_name="second-runbook"),
    ]
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_known_intent_names",
        lambda intents_dir=None: {"first-runbook", "second-runbook"},
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent._run_intent_router_agent",
        lambda *_args, **_kwargs: (routes, None),
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_require_review",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_tools",
        lambda intent_name, **_kwargs: [{"name": f"lookup-{intent_name}"}],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_actions",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_config",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "automail.pipeline.intent.agent.get_intent_response_attachments",
        lambda *_args, **_kwargs: [],
    )

    def process(intent_name, *_args, **_kwargs):
        _record_tool_call(
            ToolDefinition(
                name=f"lookup-{intent_name}",
                description="Lookup",
                method="GET",
                url_template="https://example.test/lookup",
            ),
            status="success",
            response_text=json.dumps({"status": intent_name}),
        )
        _capture_generated_file(
            ToolDefinition(
                name=f"file-{intent_name}",
                description="Generate",
                method="POST",
                url_template="https://example.test/file",
                expects_file=True,
                file_name_path="filename",
                file_content_type_path="contentType",
                file_content_base64_path="contentBase64",
            ),
            json.dumps({
                "filename": f"{intent_name}.pdf",
                "contentType": "application/pdf",
                "contentBase64": "cGRm",
            }),
        )
        return IntentReviewOutput(summary=f"Processed {intent_name}")

    monkeypatch.setattr("automail.pipeline.intent.agent._run_processing_agent", process)

    result = channel_runbooks.run_direct_channel_runbooks(
        source_message_id="slack:T1:C1:100.2",
        subject="Two requests",
        body="First request. Second request.",
        from_address="slack:T1:U1",
        identity={},
        identity_data={},
        config_source=None,
        tenant_id=None,
        project_id="project1",
    )

    assert [call["name"] for call in result.tool_calls] == [
        "lookup-first-runbook",
        "lookup-second-runbook",
    ]
    assert [item["filename"] for item in result.generated_attachments] == [
        "first-runbook.pdf",
        "second-runbook.pdf",
    ]


def test_slack_runs_two_concerns_before_ticket_automation(monkeypatch):
    ids = iter(["issue1", "msg1", "run1"])
    operations = []
    posted = []
    patched = []
    approvals = []
    automations = []
    usage_events = []
    intent_result = {
        "matched": True,
        "intentName": "cancel_contract",
        "actions": [],
        "concerns": [
            {
                "concernId": "concern-cancel",
                "matched": True,
                "intentName": "cancel_contract",
                "status": "ready",
                "summary": "Cancellation ready",
                "actions": [],
            },
            {
                "concernId": "concern-buy",
                "matched": True,
                "intentName": "buy_boxes",
                "status": "ready",
                "summary": "Quote ready",
                "actions": [],
            },
        ],
    }

    monkeypatch.setattr(issues, "generate_id", lambda: next(ids))
    monkeypatch.setattr(
        issues,
        "get_channel_by_key",
        lambda *_args, **_kwargs: {
            "id": "channel1",
            "channelKey": "slack-main",
            "projectId": "project1",
            "tenantId": "tenant1",
            "status": "active",
            "config": {"teamId": "T1", "workspaceName": "Acme"},
        },
    )
    monkeypatch.setattr(issues, "_upsert_account", lambda **_kwargs: {"id": "account1"})
    monkeypatch.setattr(issues, "_upsert_contact", lambda **_kwargs: {"id": "contact1"})
    monkeypatch.setattr(issues, "_first", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(issues, "_ensure_issue_sla_events", lambda **_kwargs: None)
    monkeypatch.setattr(issues, "_sync_channel_account_insights", lambda **_kwargs: None)
    monkeypatch.setattr(issues, "_refresh_account_contact_counts", lambda **_kwargs: None)
    monkeypatch.setattr(issues, "_channel_auto_prepare_agent_reply", lambda **_kwargs: None)
    monkeypatch.setattr(issues, "_processing_claim_is_active", lambda _run: True)
    monkeypatch.setattr(
        issues,
        "_prepare_runbook_action_approvals",
        lambda **kwargs: approvals.append(kwargs) or [],
    )
    monkeypatch.setattr(
        "automail.db.pocketbase.client.store_llm_usage_events",
        lambda calls, **kwargs: usage_events.append((calls, kwargs)),
    )
    monkeypatch.setattr(
        channel_runbooks,
        "run_direct_channel_runbooks",
        lambda **_kwargs: operations.append("runbooks") or DirectChannelRunbookResult(
            identity_result={"customerFound": True},
            intent_result=intent_result,
            token_usage={
                "totalTokens": 42,
                "calls": [{"stage": "intent", "model": "test-model", "totalTokens": 42}],
            },
            tool_calls=[{"name": "lookup_contract", "status": "success"}],
            generated_attachments=[
                {
                    "filename": "quote.pdf",
                    "contentBase64": "cGRm",
                    "contentType": "application/pdf",
                }
            ],
            activated_intent="cancel_contract",
            summary="Cancellation ready; Quote ready",
            requires_human=False,
        ),
    )

    def fake_post(path, data):
        operations.append(path)
        posted.append((path, data))
        return data

    def fake_automation(**kwargs):
        operations.append("automation")
        automations.append(kwargs)
        return {"processed": 0, "failed": 0, "items": []}

    monkeypatch.setattr(issues, "_post", fake_post)
    monkeypatch.setattr(issues, "_patch", lambda path, data: patched.append((path, data)) or data)
    monkeypatch.setattr(issues, "_run_automation_rules_for_issue", fake_automation)

    result = issues.ingest_slack_event(
        "slack-main",
        tenant_id="tenant1",
        project_id="project1",
        payload={
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel": "C1",
                "user": "U1",
                "ts": "100.1",
                "text": "Cancel our contract. Also quote 200 boxes.",
            },
        },
    )

    ai_run = next(data for path, data in posted if path == "/api/collections/support_ai_runs/records")
    assert result["status"] == "success"
    assert ai_run["intent_result"]["concerns"] == intent_result["concerns"]
    assert ai_run["metadata"]["sourceMessageId"] == "slack:T1:C1:100.1"
    assert ai_run["metadata"]["generatedAttachments"][0]["filename"] == "quote.pdf"
    assert ai_run["status"] == "processing"
    assert ai_run["metadata"]["processingProgress"]["stage"] == "automation"
    assert ai_run["metadata"]["processingProgress"]["terminalStatus"] == "success"
    assert ai_run["tenant"] == "tenant1"
    assert ai_run["project"] == "project1"
    assert operations.index("/api/collections/support_ai_runs/records") < operations.index("runbooks")
    assert operations.index("/api/collections/support_ai_runs/records") < operations.index("automation")
    assert automations[0]["issue"]["activated_intent"] == "cancel_contract"
    assert automations[0]["issue"]["requires_human"] is False
    assert approvals[0]["source_message_id"] == "slack:T1:C1:100.1"
    assert approvals[0]["intent_result"]["concerns"] == intent_result["concerns"]
    assert usage_events == [
        (
            [{"stage": "intent", "model": "test-model", "totalTokens": 42}],
            {"tenant_id": "tenant1", "project_id": "project1", "run_id": "run1"},
        )
    ]
    assert any(
        path == "/api/collections/support_issues/records/issue1"
        and data.get("activated_intent") == "cancel_contract"
        for path, data in patched
    )


def test_direct_channel_attachment_uses_latest_run_only():
    old_attachment = {
        "filename": "quote.pdf",
        "contentBase64": "b2xk",
        "contentType": "application/pdf",
    }
    new_attachment = {
        "filename": "quote.pdf",
        "contentBase64": "bmV3",
        "contentType": "application/pdf",
    }
    issue = {
        "messages": [
            {
                "direction": "ai",
                "attachments": [old_attachment],
                "metadata": {"sourceMessageId": "email-old"},
            }
        ],
        "aiRuns": [
            {
                "source": "slack",
                "intentResult": {"concerns": [{"concernId": "new"}]},
                "metadata": {
                    "kind": "direct_channel_runbooks",
                    "sourceMessageId": "slack:T1:C1:new",
                    "generatedAttachments": [new_attachment],
                },
            },
            {
                "source": "slack",
                "intentResult": {"concerns": [{"concernId": "old"}]},
                "metadata": {
                    "sourceMessageId": "slack:T1:C1:old",
                    "generatedAttachments": [old_attachment],
                },
            },
        ],
    }

    assert issues._persisted_runbook_reply_attachment(issue, "quote.pdf") == new_attachment
    issue["aiRuns"][0]["metadata"]["generatedAttachments"] = []
    assert issues._persisted_runbook_reply_attachment(issue, "quote.pdf") is None


def test_empty_latest_runbook_run_blocks_older_generated_attachment_fallback():
    old_attachment = {
        "filename": "quote.pdf",
        "contentBase64": "b2xk",
        "contentType": "application/pdf",
    }
    issue = {
        "messages": [],
        "aiRuns": [
            {
                "source": "agent_field_extraction",
                "intentResult": {"fields": {"order": "ZF-1"}},
            },
            {
                "source": "slack",
                "status": "failed",
                "intentResult": {},
                "metadata": {
                    "kind": "direct_channel_runbooks",
                    "sourceMessageId": "slack:T1:C1:new",
                },
            },
            {
                "source": "slack",
                "status": "success",
                "intentResult": {"concerns": [{"concernId": "old"}]},
                "metadata": {
                    "kind": "direct_channel_runbooks",
                    "sourceMessageId": "slack:T1:C1:old",
                    "generatedAttachments": [old_attachment],
                },
            },
        ],
    }

    assert issues._latest_runbook_ai_run(issue) is issue["aiRuns"][1]
    assert issues._latest_runbook_intent_result(issue) == {}
    assert issues._persisted_runbook_reply_attachment(issue, "quote.pdf") is None


def test_existing_direct_run_resumes_missing_action_approvals(monkeypatch):
    intent_result = {
        "matched": True,
        "intentName": "cancel_contract",
        "concerns": [
            {
                "concernId": "concern-cancel",
                "matched": True,
                "intentName": "cancel_contract",
                "actions": [],
            }
        ],
    }
    existing_run = {
        "id": "run1",
        "activated_intent": "cancel_contract",
        "requires_human": False,
        "intent_result": intent_result,
    }
    approvals = []
    patches = []
    monkeypatch.setattr(issues, "_first", lambda collection, *_args, **_kwargs: existing_run if collection == "support_ai_runs" else None)
    monkeypatch.setattr(issues, "_patch", lambda path, data: patches.append((path, data)) or data)
    monkeypatch.setattr(
        issues,
        "_prepare_runbook_action_approvals",
        lambda **kwargs: approvals.append(kwargs) or [],
    )
    monkeypatch.setattr(
        channel_runbooks,
        "run_direct_channel_runbooks",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("existing run must not execute twice")),
    )

    result = issues._apply_direct_channel_runbooks(
        issue={"id": "issue1", "requires_human": True},
        source="slack",
        source_message_id="slack:T1:C1:100.1",
        subject="Cancel",
        body="Cancel our contract.",
        identity={"contact_email": "slack:T1:U1"},
        identity_data={"provider": "slack"},
        tenant_id="tenant1",
        project_id="project1",
    )

    assert result["activated_intent"] == "cancel_contract"
    assert result["requires_human"] is False
    assert approvals[0]["source_message_id"] == "slack:T1:C1:100.1"
    assert approvals[0]["intent_result"] == intent_result
    assert patches[0][0] == "/api/collections/support_issues/records/issue1"


def test_existing_processing_direct_run_is_not_treated_as_completed(monkeypatch):
    existing_run = {
        "id": "run1",
        "status": "processing",
        "updated": issues._now_iso(),
        "intent_result": {},
        "metadata": {
            "processingProgress": {
                "status": "processing",
                "stage": "runbooks",
            }
        },
    }
    monkeypatch.setattr(
        issues,
        "_first",
        lambda collection, *_args, **_kwargs: existing_run if collection == "support_ai_runs" else None,
    )
    monkeypatch.setattr(
        channel_runbooks,
        "run_direct_channel_runbooks",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("active run must not execute twice")),
    )

    with pytest.raises(RuntimeError, match="already in progress"):
        issues._apply_direct_channel_runbooks(
            issue={"id": "issue1", "requires_human": True},
            source="slack",
            source_message_id="slack:T1:C1:100.1",
            subject="Cancel",
            body="Cancel our contract.",
            identity={"contact_email": "slack:T1:U1"},
            identity_data={"provider": "slack"},
            tenant_id="tenant1",
            project_id="project1",
        )


def test_stale_direct_run_is_never_reclaimed_or_replayed(monkeypatch):
    logical_run_key = issues._direct_channel_run_key(
        source="slack",
        source_message_id="slack:T1:C1:100.1",
    )
    stale_run = {
        "id": "run-stale",
        "issue": "issue1",
        "run_key": logical_run_key,
        "source": "slack",
        "status": "processing",
        "requires_human": False,
        "intent_result": {},
        "metadata": {
            "kind": "direct_channel_runbooks",
            "processingProgress": {
                "status": "processing",
                "stage": "runbooks",
                "updatedAt": "2026-07-17T00:00:00+00:00",
                "stages": [{"key": "runbooks", "label": "Matching concerns", "status": "processing"}],
            },
        },
        "started_at": "2026-07-17T00:00:00+00:00",
        "updated": "2026-07-17T00:00:00+00:00",
    }
    monkeypatch.setattr(
        issues,
        "_first",
        lambda collection, *_args, **_kwargs: stale_run
        if collection == "support_ai_runs"
        else None,
    )
    monkeypatch.setattr(
        channel_runbooks,
        "run_direct_channel_runbooks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("stale runbooks must not be replayed automatically")
        ),
    )

    with pytest.raises(issues.DirectChannelProcessingInProgress):
        issues._apply_direct_channel_runbooks(
            issue={"id": "issue1", "requires_human": True},
            source="slack",
            source_message_id="slack:T1:C1:100.1",
            subject="Question",
            body="Can you help?",
            identity={"contact_email": "slack:T1:U1"},
            identity_data={"provider": "slack"},
            tenant_id="tenant1",
            project_id="project1",
        )

    assert stale_run["status"] == "processing"
    assert stale_run["run_key"] == logical_run_key


def test_expiry_sweeper_terminalizes_without_replay_or_key_change(monkeypatch):
    stale_run = {
        "id": "run-stale",
        "issue": "issue1",
        "run_key": "logical-run-key",
        "source": "slack",
        "status": "processing",
        "metadata": {
            "kind": "direct_channel_runbooks",
            "processingClaim": {"version": 1, "token": "owner-1"},
            "processingProgress": {
                "status": "processing",
                "stage": "runbooks",
                "updatedAt": "2026-07-17T00:00:00+00:00",
            },
        },
        "started_at": "2026-07-17T00:00:00+00:00",
        "tenant": "tenant1",
        "project": "project1",
    }
    patches = []
    events = []

    def fake_patch(path, data):
        patches.append((path, data))
        if path.endswith("/run-stale"):
            stale_run.update(data)
        return data

    unrelated_run = {
        "id": "run-unrelated",
        "status": "processing",
        "metadata": {"kind": "agent_answer_progress"},
    }
    monkeypatch.setattr(
        issues,
        "_list_all",
        lambda *_args, **_kwargs: [unrelated_run, stale_run],
    )
    monkeypatch.setattr(
        issues,
        "_first",
        lambda collection, *_args, **_kwargs: stale_run
        if collection == "support_ai_runs"
        else None,
    )
    monkeypatch.setattr(issues, "_patch", fake_patch)
    monkeypatch.setattr(issues, "_record_issue_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(
        channel_runbooks,
        "run_direct_channel_runbooks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("expiry must not replay runbooks or tools")
        ),
    )
    monkeypatch.setattr(
        issues,
        "_run_automation_rules_for_issue",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("expiry must not replay ticket automation")
        ),
    )

    result = issues.expire_stale_direct_channel_processing_runs_for_scope(
        tenant_id="tenant1",
        project_id="project1",
        limit=1,
        lease_seconds=1,
    )

    assert result["inspected"] == 1
    assert result["expired"] == 1
    assert stale_run["status"] == "failed"
    assert stale_run["run_key"] == "logical-run-key"
    assert stale_run["metadata"]["processingExpiry"]["replayed"] is False
    assert stale_run["metadata"]["processingClaim"]["expiredAt"]
    assert ("/api/collections/support_issues/records/issue1", {"requires_human": True}) in patches
    assert len(events) == 1
    assert events[0]["record_id"]


def test_expired_owner_cannot_persist_late_runbook_results(monkeypatch):
    claim_active = True
    patches: list[tuple[str, dict]] = []
    processing_run = {
        "id": "run-owner-1",
        "issue": "issue1",
        "run_key": "logical-run-key",
        "source": "slack",
        "status": "processing",
        "tenant": "tenant1",
        "project": "project1",
        "metadata": {
            "kind": "direct_channel_runbooks",
            "processingClaim": {"version": 1, "token": "owner-1"},
        },
    }

    def finish_after_expiry(**_kwargs):
        nonlocal claim_active
        claim_active = False
        return DirectChannelRunbookResult(
            identity_result={"customerFound": True},
            intent_result={"matched": False, "concerns": []},
            token_usage={},
            tool_calls=[],
            generated_attachments=[],
            activated_intent="",
            summary="Late result",
            requires_human=False,
        )

    monkeypatch.setattr(issues, "_first", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(issues, "_start_processing_run", lambda **_kwargs: processing_run)
    monkeypatch.setattr(issues, "_processing_claim_is_active", lambda _run: claim_active)
    monkeypatch.setattr(issues, "_patch", lambda path, data: patches.append((path, data)) or data)
    monkeypatch.setattr("automail.pipeline.drafts.get_live_source", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(channel_runbooks, "run_direct_channel_runbooks", finish_after_expiry)

    with pytest.raises(issues.ProcessingClaimExpired):
        issues._apply_direct_channel_runbooks(
            issue={"id": "issue1", "requires_human": True},
            source="slack",
            source_message_id="slack:T1:C1:100.1",
            subject="Question",
            body="Can you help?",
            identity={"contact_email": "slack:T1:U1"},
            identity_data={"provider": "slack"},
            tenant_id="tenant1",
            project_id="project1",
        )

    assert patches == []


def test_expired_owner_cannot_start_http_tool_request(monkeypatch):
    network_calls: list[dict] = []
    monkeypatch.setattr(
        "automail.integrations.http_tool.httpx.request",
        lambda **kwargs: network_calls.append(kwargs),
    )
    http_tool = _make_http_tool(
        ToolDefinition(
            name="cancel-order",
            description="Cancel an order",
            method="POST",
            url_template="https://example.test/orders/cancel",
        ),
        sender_email="customer@example.com",
    )

    with fence_http_tool_execution(lambda: False), pytest.raises(HttpToolExecutionFenced):
        http_tool.invoke({})

    assert network_calls == []


def test_channel_autopilot_stops_when_claim_expires_during_triage(monkeypatch):
    claim_active = True
    processing_run = {
        "id": "run-owner-1",
        "status": "processing",
        "metadata": {"processingClaim": {"token": "owner-1"}},
    }

    def expire_during_triage(*_args, **_kwargs):
        nonlocal claim_active
        claim_active = False
        return {"triage": {"type": "triage_ticket"}}

    monkeypatch.setattr(issues, "_processing_claim_is_active", lambda _run: claim_active)
    monkeypatch.setattr(issues, "_advance_processing_run", lambda *_args, **_kwargs: processing_run)
    monkeypatch.setattr(issues, "prepare_issue_triage", expire_during_triage)
    monkeypatch.setattr(
        issues,
        "prepare_issue_custom_fields",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fields must not start after triage loses the claim")
        ),
    )
    monkeypatch.setattr(
        issues,
        "create_issue_agent_answer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("composer must not start after triage loses the claim")
        ),
    )
    monkeypatch.setattr(
        issues,
        "_record_issue_event",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("expired owner must not persist autopilot events")
        ),
    )

    with pytest.raises(issues.ProcessingClaimExpired):
        issues._channel_auto_prepare_agent_reply(
            channel={
                "id": "channel1",
                "type": "slack",
                "config": {
                    "autoPrepareAgentReply": True,
                    "autoPrepareTriage": True,
                    "autoPrepareCustomFields": True,
                },
            },
            issue_id="issue1",
            tenant_id="tenant1",
            project_id="project1",
            source="slack",
            message_id="slack:T1:C1:100.1",
            processing_run=processing_run,
        )


def test_channel_autopilot_discards_answer_when_claim_expires_during_composer(monkeypatch):
    claim_active = True
    processing_run = {
        "id": "run-owner-1",
        "status": "processing",
        "metadata": {"processingClaim": {"token": "owner-1"}},
    }

    def expire_during_composer(*_args, **_kwargs):
        nonlocal claim_active
        claim_active = False
        return {"reply": {"id": "late-reply"}, "run": {"id": "late-run"}}

    monkeypatch.setattr(issues, "_processing_claim_is_active", lambda _run: claim_active)
    monkeypatch.setattr(issues, "_advance_processing_run", lambda *_args, **_kwargs: processing_run)
    monkeypatch.setattr(issues, "create_issue_agent_answer", expire_during_composer)
    monkeypatch.setattr(
        issues,
        "_record_issue_event",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("late composer result must not be retained")
        ),
    )

    with pytest.raises(issues.ProcessingClaimExpired):
        issues._channel_auto_prepare_agent_reply(
            channel={
                "id": "channel1",
                "type": "slack",
                "config": {
                    "autoPrepareAgentReply": True,
                    "autoPrepareTriage": False,
                    "autoPrepareCustomFields": False,
                },
            },
            issue_id="issue1",
            tenant_id="tenant1",
            project_id="project1",
            source="slack",
            message_id="slack:T1:C1:100.1",
            processing_run=processing_run,
        )
