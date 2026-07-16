import pytest

from automail.api.admin import actions as admin_actions
from automail.db.pocketbase import issues
from automail.support import issue_agent
from automail.support.issue_agent import AutomationGroundingAssessment, IssueAgentDraft


def test_runbook_webhook_action_preparation_is_filtered_and_idempotent(monkeypatch):
    created: list[dict] = []
    stored: dict[str, object] = {}

    def fake_first(collection: str, *_args, **_kwargs):
        if collection != "support_action_executions" or not stored:
            return None
        return stored

    def fake_create(_issue_id: str, **kwargs):
        created.append(kwargs)
        stored.update(
            {
                "id": "execution1",
                "issue": "issue1",
                "action_key": kwargs["action_key"],
                "label": kwargs["label"],
                "type": kwargs["action_type"],
                "status": kwargs["status"],
                "requested_by": kwargs["requested_by"],
                "result": kwargs["result"],
                "metadata": kwargs["metadata"],
            }
        )
        return issues._normalize_action_execution(stored)

    monkeypatch.setattr(issues, "_first", fake_first)
    monkeypatch.setattr(issues, "create_issue_action_execution", fake_create)
    intent_result = {
        "actions": [
            {
                "name": "open_ticket",
                "label": "Open ticket",
                "type": "button",
                "webhook": "https://hooks.example.test/open-ticket",
                "method": "POST",
                "body": {"order": "{orderId}"},
            },
            {
                "name": "blank_webhook",
                "label": "Broken button",
                "type": "button",
                "webhook": "",
            },
            {
                "name": "order_id",
                "label": "Order ID",
                "type": "input",
                "separate_call": False,
                "webhook": "https://hooks.example.test/collect",
            },
            {
                "name": "disabled",
                "label": "Disabled action",
                "type": "button",
                "enabled": False,
                "webhook": "https://hooks.example.test/disabled",
            },
        ]
    }

    first = issues._prepare_runbook_action_approvals(
        issue_id="issue1",
        intent_result=intent_result,
        source_message_id="message1",
        tenant_id="tenant1",
        project_id="project1",
    )
    second = issues._prepare_runbook_action_approvals(
        issue_id="issue1",
        intent_result=intent_result,
        source_message_id="message1",
        tenant_id="tenant1",
        project_id="project1",
    )

    assert [item["id"] for item in first] == ["execution1"]
    assert [item["id"] for item in second] == ["execution1"]
    assert len(created) == 1
    assert created[0]["status"] == "pending"
    assert created[0]["action_type"] == "runbook_webhook"
    assert created[0]["metadata"]["source"] == "runbook"
    assert created[0]["metadata"]["approvalRequired"] is True
    assert created[0]["result"]["proposedAction"] == {
        "type": "runbook_webhook",
        "name": "open_ticket",
        "label": "Open ticket",
        "actionType": "button",
        "webhook": "https://hooks.example.test/open-ticket",
        "method": "POST",
        "payload": {"actionName": "open_ticket", "actionLabel": "Open ticket"},
        "query": {},
        "body": {"order": "{orderId}"},
        "headers": {},
    }


def _pending_runbook_execution(*, action_type: str = "runbook_webhook") -> dict:
    return {
        "id": "execution1",
        "issue": "issue1",
        "action_key": "runbook-message1-open-ticket",
        "label": "Open ticket",
        "type": "runbook_webhook",
        "status": "pending",
        "requested_by": "automation",
        "result": {
            "proposedAction": {
                "type": action_type,
                "name": "open_ticket",
                "label": "Open ticket",
                "webhook": "https://hooks.example.test/open-ticket",
                "method": "POST",
                "payload": {"orderId": "ORDER-42"},
            }
        },
        "metadata": {
            "source": "runbook",
            "approvalRequired": True,
            "reviewStatus": "pending",
        },
        "started_at": "2026-07-16T10:00:00Z",
    }


def _stub_action_execution_persistence(monkeypatch, rec: dict):
    patched: list[dict] = []
    events: list[dict] = []
    monkeypatch.setattr(issues, "_first", lambda *_args, **_kwargs: rec)
    monkeypatch.setattr(
        issues,
        "_patch",
        lambda _path, data: patched.append(data) or data,
    )
    monkeypatch.setattr(
        issues,
        "_record_issue_event",
        lambda **kwargs: events.append(kwargs) or {},
    )
    monkeypatch.setattr(
        issues,
        "get_issue",
        lambda *_args, **_kwargs: {"id": "issue1"},
    )
    return patched, events


def test_runbook_webhook_approval_persists_success(monkeypatch):
    rec = _pending_runbook_execution()
    patched, events = _stub_action_execution_persistence(monkeypatch, rec)
    calls: list[dict] = []

    def fake_execute(body, **kwargs):
        calls.append({"body": body, **kwargs})
        return {
            "status": "ok",
            "response": {"ticketReference": "ZF-42", "status": "opened"},
        }

    monkeypatch.setattr(admin_actions, "execute_action_webhook_sync", fake_execute)

    result = issues.approve_issue_action_execution(
        "issue1",
        "execution1",
        tenant_id="tenant1",
        project_id="project1",
        approved_by="agent@example.test",
        authorization_header="Bearer test-token",
    )

    assert result is not None
    assert result["execution"]["status"] == "success"
    assert result["execution"]["metadata"]["reviewStatus"] == "approved"
    assert result["execution"]["result"]["application"] == {
        "applied": True,
        "type": "runbook_webhook",
        "name": "open_ticket",
        "webhookResult": {
            "status": "ok",
            "response": {"ticketReference": "ZF-42", "status": "opened"},
        },
    }
    assert patched[0]["status"] == "success"
    assert calls[0]["authorization_header"] == "Bearer test-token"
    assert calls[0]["body"].payload == {"orderId": "ORDER-42"}
    assert events[0]["event_type"] == "action_approved"


@pytest.mark.parametrize(
    ("rec", "executor_error", "expected_error"),
    [
        (_pending_runbook_execution(), RuntimeError("webhook unavailable"), "webhook unavailable"),
        (
            _pending_runbook_execution(action_type="unsupported_action"),
            None,
            "No built-in executor for proposed action: unsupported_action",
        ),
    ],
)
def test_failed_or_unknown_action_approval_persists_failed_never_success(
    monkeypatch,
    rec,
    executor_error,
    expected_error,
):
    patched, events = _stub_action_execution_persistence(monkeypatch, rec)
    if executor_error is not None:
        monkeypatch.setattr(
            admin_actions,
            "execute_action_webhook_sync",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(executor_error),
        )

    with pytest.raises(ValueError, match=expected_error):
        issues.approve_issue_action_execution(
            "issue1",
            "execution1",
            tenant_id="tenant1",
            project_id="project1",
            approved_by="agent@example.test",
        )

    assert len(patched) == 1
    assert patched[0]["status"] == "failed"
    assert patched[0]["metadata"]["reviewStatus"] == "failed"
    assert patched[0]["metadata"]["approved"] is False
    assert patched[0]["result"]["application"]["applied"] is False
    assert expected_error in patched[0]["error"]
    assert events[0]["event_type"] == "action_failed"


def _stub_channel_agent_answer(monkeypatch, *, verified: bool):
    issue = {
        "id": "issue1",
        "subject": "Shipment status",
        "messages": [
            {
                "id": "message1",
                "direction": "customer",
                "body": "Where is shipment ZF-42?",
            }
        ],
    }
    article = {
        "id": "article1",
        "title": "Shipment status",
        "body": "Shipment ZF-42 is in transit.",
        "status": "published",
        "metadata": {"visibility": "public", "public": True},
    }
    reply_calls: list[dict] = []
    grounding_calls: list[dict] = []
    monkeypatch.setattr(issues, "get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(issues, "_agent_answer_runs_for_context", lambda _issue: [])
    monkeypatch.setattr(issues, "_agent_account_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(issues, "_agent_conversation_context", lambda _issue: {})
    monkeypatch.setattr(
        issues,
        "_knowledge_article_records_for_agent",
        lambda **_kwargs: [article],
    )
    monkeypatch.setattr(
        issues,
        "_rank_knowledge_articles_for_issue",
        lambda *_args, **_kwargs: [article],
    )
    monkeypatch.setattr(
        issues,
        "_rank_knowledge_articles_for_automatic_answer",
        lambda *_args, **_kwargs: [article],
    )
    monkeypatch.setattr(
        issues,
        "draft_issue_automation_answer",
        lambda **_kwargs: IssueAgentDraft(
            answer="Shipment ZF-42 is in transit.",
            confidence="high",
            generation_mode="llm",
            citation_ids=("article1",),
        ),
    )

    def fake_grounding(**kwargs):
        grounding_calls.append(kwargs)
        return AutomationGroundingAssessment(
            verified=verified,
            status="passed" if verified else "failed",
            reason_code="" if verified else "ungrounded_answer",
            checked_at="2026-07-16T10:05:00Z",
            citation_ids=("article1",),
            claim_count=1,
            unsupported_claims=() if verified else ("Shipment ZF-42 is in transit.",),
            provider="test",
            model="grounding-model",
        )

    def fake_create_reply(_issue_id: str, **kwargs):
        reply_calls.append(kwargs)
        return {"id": "reply1", "status": kwargs["status"], "metadata": kwargs["metadata"]}

    monkeypatch.setattr(issues, "assess_issue_automation_grounding", fake_grounding)
    monkeypatch.setattr(issues, "create_issue_reply", fake_create_reply)
    monkeypatch.setattr(
        issues,
        "_record_agent_answer_ai_run",
        lambda **_kwargs: {"id": "run1"},
    )
    monkeypatch.setattr(issues, "_upsert_agent_answer_knowledge_gap", lambda **_kwargs: None)
    monkeypatch.setattr(issues, "_record_issue_event", lambda **_kwargs: {})
    return reply_calls, grounding_calls


@pytest.mark.parametrize("verified", [False, True])
def test_channel_autopilot_draft_is_grounded_before_reply(monkeypatch, verified):
    reply_calls, grounding_calls = _stub_channel_agent_answer(monkeypatch, verified=verified)

    result = issues.create_issue_agent_answer(
        "issue1",
        tenant_id="tenant1",
        project_id="project1",
        author_email="automation",
        approval_required=True,
        auto_send=False,
        automation_context={"source": "channel_autopilot"},
        use_knowledge_agent=False,
    )

    assert result is not None
    assert len(grounding_calls) == 1
    assert grounding_calls[0]["answer"] == "Shipment ZF-42 is in transit."
    if verified:
        assert result["draftBlockedReason"] == ""
        assert result["reply"]["id"] == "reply1"
        assert len(reply_calls) == 1
    else:
        assert result["draftBlockedReason"] == "ungrounded_answer"
        assert result["reply"] is None
        assert result["run"]["id"] == "run1"
        assert reply_calls == []


def test_blocked_channel_autopilot_package_is_handled_without_pipeline_fallback(monkeypatch):
    blocked = {
        "reply": None,
        "run": {"id": "run1"},
        "draftBlockedReason": "ungrounded_answer",
    }
    monkeypatch.setattr(
        issues,
        "_channel_auto_prepare_agent_reply",
        lambda **_kwargs: blocked,
    )

    result = issues._ensure_email_channel_autopilot_package(
        issue={"id": "issue1"},
        channel={"id": "channel1"},
        tenant_id="tenant1",
        project_id="project1",
        source="channel:email:support",
        message_id="message1",
    )

    assert result is blocked
    assert bool(result) is True


def test_automatic_action_context_distinguishes_pending_from_proven_success():
    context = issue_agent._automatic_ticket_context(
        {
            "id": "issue1",
            "subject": "Delivery exception",
            "status": "ongoing",
            "aiSummary": "A ticket was already opened.",
            "actionExecutions": [
                {
                    "type": "agent_triage",
                    "status": "success",
                    "metadata": {"source": "agent_triage"},
                },
                {
                    "type": "runbook_webhook",
                    "actionKey": "open_ticket",
                    "label": "Open ticket",
                    "status": "pending",
                    "metadata": {"source": "runbook", "approvalRequired": True},
                    "result": {
                        "proposedAction": {
                            "name": "open_ticket",
                            "label": "Open fulfillment ticket",
                        }
                    },
                },
                {
                    "type": "runbook_webhook",
                    "status": "failed",
                    "metadata": {"source": "runbook", "approvalRequired": True},
                    "result": {"proposedAction": {"name": "failed_ticket"}},
                },
                {
                    "type": "runbook_webhook",
                    "status": "success",
                    "completedAt": "2026-07-16T10:10:00Z",
                    "metadata": {"source": "runbook"},
                    "result": {
                        "proposedAction": {
                            "name": "confirm_ticket",
                            "label": "Confirm ticket",
                        },
                        "application": {
                            "applied": True,
                            "webhookResult": {
                                "status": "ok",
                                "response": {
                                    "ticketReference": "ZF-42",
                                    "status": "opened",
                                    "secret": "must-not-reach-the-agent",
                                    "nested": {"raw": "must-not-reach-the-agent"},
                                },
                            },
                        },
                    },
                },
                {
                    "type": "runbook_webhook",
                    "status": "success",
                    "metadata": {"source": "runbook"},
                    "result": {
                        "proposedAction": {"name": "false_success"},
                        "application": {
                            "applied": False,
                            "webhookResult": {"status": "ok", "response": {"id": "bad"}},
                        },
                    },
                },
            ],
        }
    )

    assert "status" not in context
    assert "summary" not in context
    assert context["runbookActions"] == [
        {
            "name": "open_ticket",
            "label": "Open fulfillment ticket",
            "status": "pending_approval",
        },
        {
            "name": "confirm_ticket",
            "label": "Confirm ticket",
            "status": "success",
            "completedAt": "2026-07-16T10:10:00Z",
            "proof": {"status": "opened", "ticketReference": "ZF-42"},
        },
    ]


def test_automatic_evidence_excludes_generated_messages_and_related_agent_replies():
    messages = issue_agent._automatic_message_context(
        [
            {"direction": "customer", "body": "Please open a ticket."},
            {"direction": "ai", "body": "The ticket was opened."},
            {"direction": "agent", "body": "We escalated this."},
        ]
    )
    conversation = issue_agent._automatic_conversation_context(
        {
            "key": "account:shop",
            "messages": [
                {"direction": "customer", "body": "Any update?"},
                {"direction": "agent", "body": "The refund was completed."},
            ],
        }
    )

    assert messages == [
        {
            "direction": "customer",
            "sender": "",
            "body": "Please open a ticket.",
            "occurredAt": "",
        }
    ]
    assert conversation["messages"] == [
        {
            "issueId": "",
            "ticketSubject": "",
            "direction": "customer",
            "sender": "",
            "body": "Any update?",
            "occurredAt": "",
        }
    ]
