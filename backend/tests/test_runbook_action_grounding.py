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
        "payload": {
            "actionName": "open_ticket",
            "actionLabel": "Open ticket",
            "concernId": "primary",
            "runbook": "",
        },
        "query": {},
        "body": {"order": "{orderId}"},
        "headers": {},
        "concernId": "primary",
        "runbook": "",
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


def _stub_channel_agent_answer(
    monkeypatch,
    *,
    verified: bool,
    draft_citation_ids: tuple[str, ...] = (),
    grounded_citation_ids: tuple[str, ...] = ("article1",),
):
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
        "reviewStatus": "reviewed",
        "freshnessStatus": "fresh",
        "metadata": {"visibility": "public", "public": True},
    }
    unused_article = {
        "id": "article2",
        "title": "Returns policy",
        "body": "Returns require approval.",
        "status": "published",
        "metadata": {"visibility": "public", "public": True},
    }
    articles = [article, unused_article]
    reply_calls: list[dict] = []
    grounding_calls: list[dict] = []
    monkeypatch.setattr(issues, "get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(issues, "_agent_answer_runs_for_context", lambda _issue: [])
    monkeypatch.setattr(issues, "_agent_account_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(issues, "_agent_conversation_context", lambda _issue: {})
    monkeypatch.setattr(
        issues,
        "_knowledge_article_records_for_agent",
        lambda **_kwargs: articles,
    )
    monkeypatch.setattr(
        issues,
        "_rank_knowledge_articles_for_issue",
        lambda *_args, **_kwargs: articles,
    )
    monkeypatch.setattr(
        issues,
        "_rank_knowledge_articles_for_automatic_answer",
        lambda *_args, **_kwargs: articles,
    )
    monkeypatch.setattr(
        issues,
        "draft_issue_automation_answer",
        lambda **_kwargs: IssueAgentDraft(
            answer="Shipment ZF-42 is in transit.",
            confidence="high",
            generation_mode="llm",
            citation_ids=draft_citation_ids,
        ),
    )

    def fake_grounding(**kwargs):
        grounding_calls.append(kwargs)
        return AutomationGroundingAssessment(
            verified=verified,
            status="passed" if verified else "failed",
            reason_code="" if verified else "ungrounded_answer",
            checked_at="2026-07-16T10:05:00Z",
            citation_ids=grounded_citation_ids,
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
        assert [article["id"] for article in grounding_calls[0]["articles"]] == [
            "article1",
            "article2",
        ]
        assert reply_calls[0]["metadata"]["knowledgeArticleIds"] == ["article1"]
        assert [
            citation["id"] for citation in reply_calls[0]["metadata"]["citations"]
        ] == ["article1"]
    else:
        assert result["draftBlockedReason"] == "ungrounded_answer"
        assert result["reply"] is None
        assert result["run"]["id"] == "run1"
        assert reply_calls == []


def test_channel_grounding_reloads_pending_actions_created_during_composition(monkeypatch):
    reply_calls, grounding_calls = _stub_channel_agent_answer(
        monkeypatch,
        verified=True,
    )
    stale_issue = {
        "id": "issue1",
        "subject": "Urgent fulfillment escalation",
        "messages": [
            {
                "id": "message1",
                "direction": "customer",
                "body": "Please escalate this fulfillment issue immediately.",
            }
        ],
        "aiRuns": [],
        "actionExecutions": [],
    }
    fresh_issue = {
        **stale_issue,
        "aiRuns": [
            {
                "source": "channel:email-main",
                "metadata": {"sourceMessageId": "message1"},
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "urgent-fulfillment",
                            "matched": True,
                            "intentName": "urgent-fulfillment",
                        }
                    ]
                },
            }
        ],
        "actionExecutions": [
            {
                "type": "runbook_webhook",
                "status": "pending",
                "label": "Open ticket",
                "metadata": {
                    "source": "runbook",
                    "approvalRequired": True,
                    "sourceMessageId": "message1",
                    "concernId": "urgent-fulfillment",
                    "concernIds": ["urgent-fulfillment"],
                    "runbook": "urgent-fulfillment",
                },
                "result": {
                    "proposedAction": {
                        "name": "open_ticket",
                        "label": "Open ticket",
                        "concernId": "urgent-fulfillment",
                        "concernIds": ["urgent-fulfillment"],
                    }
                },
            }
        ],
    }
    issue_reads: list[dict] = []

    def fake_get_issue(*_args, **_kwargs):
        issue = stale_issue if not issue_reads else fresh_issue
        issue_reads.append(issue)
        return issue

    monkeypatch.setattr(issues, "get_issue", fake_get_issue)
    monkeypatch.setattr(
        issues,
        "draft_issue_automation_answer",
        lambda **_kwargs: IssueAgentDraft(
            answer="We have immediately escalated this case to our operations team.",
            confidence="high",
            generation_mode="llm",
        ),
    )

    def assess_with_real_preflight(**kwargs):
        grounding_calls.append(kwargs)
        return issue_agent.assess_issue_automation_grounding(**kwargs)

    grounding_calls.clear()
    monkeypatch.setattr(issues, "assess_issue_automation_grounding", assess_with_real_preflight)
    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: pytest.fail("grounding LLM must not run"),
    )

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

    assert len(issue_reads) == 2
    assert grounding_calls[0]["issue"] is fresh_issue
    assert result is not None
    assert result["draftBlockedReason"] == "pending_action_claim"
    assert result["groundingGate"]["pendingActions"] == ["Open ticket"]
    assert result["reply"] is None
    assert reply_calls == []


@pytest.mark.parametrize(
    "answer",
    [
        "We are initiating the steps to open this investigation.",
        "We have immediately escalated this case to our operations team.",
        "A delivery-exception investigation is being initiated.",
    ],
)
def test_grounding_preflight_blocks_pending_action_claim_without_llm(monkeypatch, answer):
    issue = {
        "id": "issue1",
        "subject": "Missing parcel",
        "aiRuns": [
            {
                "source": "channel:email-main",
                "metadata": {"sourceMessageId": "message1"},
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "delivery",
                            "matched": True,
                            "intentName": "delivery-investigation",
                        }
                    ]
                },
            }
        ],
        "actionExecutions": [
            {
                "type": "runbook_webhook",
                "status": "pending",
                "label": "Open delivery investigation",
                "metadata": {
                    "source": "runbook",
                    "approvalRequired": True,
                    "sourceMessageId": "message1",
                    "concernId": "delivery",
                    "concernIds": ["delivery"],
                    "runbook": "delivery-investigation",
                },
                "result": {
                    "proposedAction": {
                        "name": "open_ticket",
                        "label": "Open delivery investigation",
                        "concernId": "delivery",
                        "concernIds": ["delivery"],
                    }
                },
            }
        ],
    }
    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: pytest.fail("grounding LLM must not run"),
    )

    result = issue_agent.assess_issue_automation_grounding(
        issue=issue,
        messages=[],
        answer=answer,
        articles=[],
        tenant_id="tenant1",
        project_id="project1",
    )

    assert result.verified is False
    assert result.reason_code == "pending_action_claim"
    assert result.pending_action_claims == (answer,)
    assert result.pending_actions == ("Open delivery investigation",)


def test_grounding_preflight_blocks_wrong_reply_language_without_llm(monkeypatch):
    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: pytest.fail("grounding LLM must not run"),
    )

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue1", "subject": "Status for ZF-10482"},
        messages=[
            {
                "direction": "customer",
                "body": "Please tell me the current shipment status and estimated delivery window.",
            }
        ],
        answer=(
            "Hallo Lena, Ihre Bestellung ist unterwegs. Die voraussichtliche "
            "Zustellung erfolgt am nächsten Werktag."
        ),
        articles=[],
        tenant_id="tenant1",
        project_id="project1",
    )

    assert result.verified is False
    assert result.reason_code == "language_mismatch"
    assert "German" in result.error
    assert "English" in result.error


def test_channel_autopilot_auto_send_uses_grounder_derived_citation(monkeypatch):
    reply_calls, grounding_calls = _stub_channel_agent_answer(monkeypatch, verified=True)

    result = issues.create_issue_agent_answer(
        "issue1",
        tenant_id="tenant1",
        project_id="project1",
        author_email="automation",
        approval_required=False,
        auto_send=True,
        automation_context={"source": "channel_autopilot"},
        use_knowledge_agent=False,
    )

    assert result is not None
    assert len(grounding_calls) == 1
    assert result["autoSend"] is True
    assert result["autoSendBlockedReason"] == ""
    assert result["reply"]["status"] == "queued"
    assert reply_calls[0]["metadata"]["knowledgeArticleIds"] == ["article1"]


@pytest.mark.parametrize(
    (
        "draft_citation_ids",
        "grounded_citation_ids",
        "expected_auto_send",
        "expected_blocked_reason",
        "expected_article_ids",
    ),
    [
        ((), ("article1",), True, "", ["article1"]),
        (("article1",), (), False, "missing_citations", []),
        (("article1",), ("article2",), False, "unreviewed_citations", ["article2"]),
    ],
)
def test_non_channel_auto_send_checks_exact_grounder_derived_citations(
    monkeypatch,
    draft_citation_ids,
    grounded_citation_ids,
    expected_auto_send,
    expected_blocked_reason,
    expected_article_ids,
):
    reply_calls, grounding_calls = _stub_channel_agent_answer(
        monkeypatch,
        verified=True,
        draft_citation_ids=draft_citation_ids,
        grounded_citation_ids=grounded_citation_ids,
    )

    result = issues.create_issue_agent_answer(
        "issue1",
        tenant_id="tenant1",
        project_id="project1",
        author_email="automation",
        approval_required=False,
        auto_send=True,
        automation_context={"source": "automation"},
        use_knowledge_agent=False,
    )

    assert result is not None
    assert len(grounding_calls) == 1
    assert result["autoSend"] is expected_auto_send
    assert result["autoSendBlockedReason"] == expected_blocked_reason
    assert result["reply"]["status"] == ("queued" if expected_auto_send else "draft")
    assert reply_calls[0]["metadata"]["knowledgeArticleIds"] == expected_article_ids


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


def test_channel_autopilot_marks_grounding_block_as_withheld(monkeypatch):
    events: list[dict] = []
    blocked = {
        "reply": None,
        "run": {"id": "run1"},
        "draftBlockedReason": "grounding_check_failed",
    }
    monkeypatch.setattr(issues, "create_issue_agent_answer", lambda *_args, **_kwargs: blocked)
    monkeypatch.setattr(issues, "_record_issue_event", lambda **kwargs: events.append(kwargs))

    result = issues._channel_auto_prepare_agent_reply(
        channel={
            "id": "channel1",
            "channelKey": "email-main",
            "type": "email",
            "config": {
                "autoPrepareAgentReply": True,
                "autoPrepareTriage": False,
                "autoPrepareCustomFields": False,
            },
        },
        issue_id="issue1",
        tenant_id="tenant1",
        project_id="project1",
        source="channel:email-main",
        message_id="message1",
    )

    assert result is blocked
    assert result["autopilotActions"][-1] == {
        "type": "prepare_agent_reply",
        "status": "withheld",
        "replyId": "",
        "runId": "run1",
        "reason": "grounding_check_failed",
        "autoSendRequested": False,
        "autoSend": False,
        "autoSendPolicy": "",
        "autoSendBlockedReason": "",
    }
    assert events[0]["title"] == "Channel autopilot withheld"
    assert events[0]["metadata"]["draftBlockedReason"] == "grounding_check_failed"


def test_automation_customer_reply_requires_persisted_reply_id():
    without_reply = {
        "items": [
            {
                "result": {
                    "actions": [
                        {"type": "prepare_agent_reply", "status": "prepared", "replyId": ""}
                    ]
                }
            }
        ]
    }
    with_reply = {
        "items": [
            {
                "result": {
                    "actions": [
                        {"type": "prepare_agent_reply", "status": "prepared", "replyId": "reply1"}
                    ]
                }
            }
        ]
    }
    with_queued_reply = {
        "items": [
            {
                "result": {
                    "actions": [
                        {"type": "queue_reply", "replyId": "reply2"}
                    ]
                }
            }
        ]
    }

    assert issues._automation_created_customer_reply(without_reply) is False
    assert issues._automation_created_customer_reply(with_reply) is True
    assert issues._automation_created_customer_reply(with_queued_reply) is True


def test_automatic_action_context_distinguishes_pending_from_proven_success():
    issue = {
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
                    "completedAt": "2026-07-16T10:08:00Z",
                    "error": "webhook unavailable: " + ("x" * 600),
                    "metadata": {"source": "runbook", "approvalRequired": True},
                    "result": {"proposedAction": {"name": "failed_ticket"}},
                },
                {
                    "type": "runbook_webhook",
                    "status": "skipped",
                    "completedAt": "2026-07-16T10:09:00Z",
                    "metadata": {"source": "runbook", "approvalRequired": True},
                    "result": {
                        "proposedAction": {"name": "rejected_ticket", "label": "Rejected ticket"},
                        "approval": {"note": "Rejected by operator"},
                    },
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
    context = issue_agent._automatic_ticket_context(issue)
    knowledge_context = issue_agent._ticket_context(issue)

    assert "status" not in context
    assert "summary" not in context
    expected_actions = [
        {
            "name": "open_ticket",
            "label": "Open fulfillment ticket",
            "status": "pending_approval",
        },
        {
            "name": "failed_ticket",
            "label": "failed_ticket",
            "status": "failed",
            "completedAt": "2026-07-16T10:08:00Z",
            "error": ("webhook unavailable: " + ("x" * 600))[:500],
        },
        {
            "name": "rejected_ticket",
            "label": "Rejected ticket",
            "status": "skipped",
            "completedAt": "2026-07-16T10:09:00Z",
            "error": "Rejected by operator",
        },
        {
            "name": "confirm_ticket",
            "label": "Confirm ticket",
            "status": "success",
            "completedAt": "2026-07-16T10:10:00Z",
            "proof": {"status": "opened", "ticketReference": "ZF-42"},
        },
    ]
    assert context["runbookActions"] == expected_actions
    assert knowledge_context["runbookActions"] == expected_actions


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
