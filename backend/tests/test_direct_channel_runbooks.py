from automail.db.pocketbase import issues
from automail.models import IntentAction, IntentResult, RunbookOutcome
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
        lambda **_kwargs: DirectChannelRunbookResult(
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
    assert ai_run["tenant"] == "tenant1"
    assert ai_run["project"] == "project1"
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
