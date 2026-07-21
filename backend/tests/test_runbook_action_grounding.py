import json

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
    monkeypatch.setattr(
        issues,
        "_list_all",
        lambda *_args, **_kwargs: [stored] if stored else [],
    )
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
    assert created[0]["idempotency_key"].startswith(
        "runbook:issue1:message1:"
    )
    assert created[0]["idempotency_key"].endswith(
        created[0]["metadata"]["proposalFingerprint"]
    )
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


def test_pending_equivalent_runbook_action_is_reused_across_followup_messages(
    monkeypatch,
):
    records: list[dict] = []

    def intent_result(concern_id: str, *, webhook: str) -> dict:
        return {
            "concerns": [
                {
                    "concernId": concern_id,
                    "intentName": "saas-webhook-recovery",
                    "outcome": {
                        "actions": [
                            {
                                "name": "rotate_signing_secret",
                                "label": "Rotate Signing Secret",
                                "type": "button",
                                "webhook": webhook,
                                "method": "POST",
                                "payload": {"accountId": "ACME-4421"},
                            }
                        ]
                    },
                }
            ]
        }

    def fake_create(_issue_id: str, **kwargs):
        record = {
            "id": f"execution{len(records) + 1}",
            "issue": "issue1",
            "action_key": kwargs["action_key"],
            "label": kwargs["label"],
            "type": kwargs["action_type"],
            "status": kwargs["status"],
            "requested_by": kwargs["requested_by"],
            "result": kwargs["result"],
            "metadata": kwargs["metadata"],
        }
        records.append(record)
        return issues._normalize_action_execution(record)

    def fake_patch(path: str, data: dict):
        execution_id = path.rsplit("/", 1)[-1]
        record = next(item for item in records if item["id"] == execution_id)
        record.update(data)
        return record

    monkeypatch.setattr(issues, "_first", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        issues,
        "_list_all",
        lambda *_args, **_kwargs: list(reversed(records)),
    )
    monkeypatch.setattr(issues, "_patch", fake_patch)
    monkeypatch.setattr(issues, "create_issue_action_execution", fake_create)

    first = issues._prepare_runbook_action_approvals(
        issue_id="issue1",
        intent_result=intent_result(
            "initial-action-request",
            webhook="https://actions.invalid/rotate",
        ),
        source_message_id="message1",
        tenant_id="tenant1",
        project_id="project1",
    )
    followup = issues._prepare_runbook_action_approvals(
        issue_id="issue1",
        intent_result=intent_result(
            "followup-status",
            webhook="https://actions.invalid/rotate",
        ),
        source_message_id="message2",
        tenant_id="tenant1",
        project_id="project1",
    )

    assert [item["id"] for item in first] == ["execution1"]
    assert [item["id"] for item in followup] == ["execution1"]
    assert len(records) == 1
    assert records[0]["metadata"]["sourceMessageId"] == "message2"
    assert records[0]["metadata"]["sourceMessageIds"] == ["message1", "message2"]
    assert records[0]["metadata"]["concernId"] == "followup-status"
    assert records[0]["metadata"]["concernIds"] == [
        "initial-action-request",
        "followup-status",
    ]
    assert records[0]["result"]["proposedAction"]["concernIds"] == [
        "initial-action-request",
        "followup-status",
    ]

    records[0]["status"] = "success"
    records[0]["metadata"]["approved"] = True
    records[0]["metadata"]["reviewStatus"] = "approved"
    repeated_after_completion = issues._prepare_runbook_action_approvals(
        issue_id="issue1",
        intent_result=intent_result(
            "later-action-request",
            webhook="https://actions.invalid/rotate",
        ),
        source_message_id="message3",
        tenant_id="tenant1",
        project_id="project1",
    )

    assert [item["id"] for item in repeated_after_completion] == ["execution2"]
    assert len(records) == 2

    distinct = issues._prepare_runbook_action_approvals(
        issue_id="issue1",
        intent_result=intent_result(
            "different-config",
            webhook="https://actions.invalid/rotate-v2",
        ),
        source_message_id="message4",
        tenant_id="tenant1",
        project_id="project1",
    )

    assert [item["id"] for item in distinct] == ["execution3"]
    assert len(records) == 3


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
    assert len(grounding_calls) == (1 if verified else 2)
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
        assert [citation["id"] for citation in reply_calls[0]["metadata"]["citations"]] == ["article1"]
    else:
        assert result["draftBlockedReason"] == "ungrounded_answer"
        assert result["reply"] is None
        assert result["run"]["id"] == "run1"
        assert reply_calls == []
        assert result["groundingGate"]["coverageRepair"]["attempted"] is True
        assert result["groundingGate"]["coverageRepair"]["verified"] is False
        assert (
            result["groundingGate"]["coverageRepair"]["resultReasonCode"]
            == "ungrounded_answer"
        )


def test_channel_autopilot_repairs_pure_incomplete_answer_once(monkeypatch):
    reply_calls, grounding_calls = _stub_channel_agent_answer(
        monkeypatch,
        verified=True,
    )
    draft_calls: list[dict] = []
    original_answer = "Invoice INV-9012 is open and bills 120 seats."
    repaired_answer = (
        "Invoice INV-9012 is open and bills 120 seats. "
        "The exact mismatch cause is not established; investigation is pending review. "
        "The requested credit is pending review and has not been approved."
    )
    uncovered = (
        "Explain exactly why the invoice has a seat mismatch.",
        "Credit the difference.",
    )

    def fake_draft(**kwargs):
        draft_calls.append(kwargs)
        answer = original_answer if len(draft_calls) == 1 else repaired_answer
        return IssueAgentDraft(
            answer=answer,
            confidence="high",
            generation_mode="llm",
        )

    def fake_grounding(**kwargs):
        grounding_calls.append(kwargs)
        if len(grounding_calls) == 1:
            return AutomationGroundingAssessment(
                verified=False,
                status="failed",
                reason_code="incomplete_answer",
                checked_at="2026-07-19T10:05:00Z",
                answer_sha256=issue_agent.grounding_text_sha256(kwargs["answer"]),
                uncovered_obligations=uncovered,
                provider="test",
                model="grounding-model",
            )
        return AutomationGroundingAssessment(
            verified=True,
            status="passed",
            reason_code="",
            checked_at="2026-07-19T10:05:01Z",
            answer_sha256=issue_agent.grounding_text_sha256(kwargs["answer"]),
            provider="test",
            model="grounding-model",
        )

    monkeypatch.setattr(issues, "draft_issue_automation_answer", fake_draft)
    monkeypatch.setattr(issues, "assess_issue_automation_grounding", fake_grounding)
    grounding_calls.clear()

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
    assert len(draft_calls) == 2
    assert draft_calls[1]["coverage_repair_answer"] == original_answer
    assert draft_calls[1]["coverage_repair_obligations"] == uncovered
    assert [call["answer"] for call in grounding_calls] == [
        original_answer,
        repaired_answer,
    ]
    assert result["draftBlockedReason"] == ""
    assert result["reply"]["id"] == "reply1"
    assert reply_calls[0]["body"] == repaired_answer
    assert reply_calls[0]["metadata"]["groundingGate"]["coverageRepair"] == {
        "attempted": True,
        "triggerReasonCode": "incomplete_answer",
        "uncoveredObligations": list(uncovered),
        "originalAnswerSha256": issue_agent.grounding_text_sha256(original_answer),
        "generationMode": "llm",
        "generationError": "",
        "repairedAnswerSha256": issue_agent.grounding_text_sha256(repaired_answer),
        "verified": True,
        "resultReasonCode": "",
    }


def test_channel_grounding_repair_removes_live_e10_orphan_fragment(monkeypatch):
    reply_calls, grounding_calls = _stub_channel_agent_answer(
        monkeypatch,
        verified=True,
    )
    draft_calls: list[dict] = []
    original_answer = (
        "Please do not ship the item directly today. A return reference. "
        "A return address is not yet confirmed."
    )
    repaired_answer = (
        "Please do not ship the item directly today. Reference. "
        "A return address and reference are not yet confirmed."
    )
    cleaned_answer = (
        "Please do not ship the item directly today. "
        "A return address and reference are not yet confirmed."
    )
    unsupported = ("A return reference.",)
    uncovered = ("Give the return address and reference",)

    def fake_draft(**kwargs):
        draft_calls.append(kwargs)
        return IssueAgentDraft(
            answer=original_answer if len(draft_calls) == 1 else repaired_answer,
            confidence="high",
            generation_mode="llm",
        )

    def fake_grounding(**kwargs):
        grounding_calls.append(kwargs)
        if len(grounding_calls) == 1:
            return AutomationGroundingAssessment(
                verified=False,
                status="failed",
                reason_code="incomplete_answer",
                checked_at="2026-07-20T08:00:00Z",
                answer_sha256=issue_agent.grounding_text_sha256(kwargs["answer"]),
                uncovered_obligations=uncovered,
                unsupported_claims=unsupported,
                provider="test",
                model="grounding-model",
            )
        return AutomationGroundingAssessment(
            verified=True,
            status="passed",
            reason_code="",
            checked_at="2026-07-20T08:00:01Z",
            answer_sha256=issue_agent.grounding_text_sha256(kwargs["answer"]),
            provider="test",
            model="grounding-model",
        )

    monkeypatch.setattr(issues, "draft_issue_automation_answer", fake_draft)
    monkeypatch.setattr(issues, "assess_issue_automation_grounding", fake_grounding)
    grounding_calls.clear()

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
    assert [call["answer"] for call in grounding_calls] == [
        original_answer,
        cleaned_answer,
    ]
    assert reply_calls[0]["body"] == cleaned_answer
    assert result["groundingGate"]["coverageRepair"]["repairedAnswerSha256"] == (
        issue_agent.grounding_text_sha256(cleaned_answer)
    )


@pytest.mark.parametrize(
    ("answer", "unsupported"),
    [
        (
            (
                "Please do not ship today.\n\nReference.\n\n"
                "A return address and reference are not yet confirmed."
            ),
            ("A return reference.",),
        ),
        (
            (
                "Please do not ship today. Reference. "
                "Use reference RET-42 on the approved return label."
            ),
            ("A return reference.",),
        ),
        (
            (
                "Please do not ship today. Reference is pending. "
                "A return address and reference are not yet confirmed."
            ),
            ("A return reference.",),
        ),
        (
            (
                "Please do not ship today. Reference. "
                "A return address and reference are not yet confirmed."
            ),
            ("A return label.",),
        ),
        (
            (
                "Please do not ship today. Reference. "
                "The reference identifies a refund that is still pending."
            ),
            ("A return reference.",),
        ),
        (
            (
                "We will keep you updated. Escalate this incident. "
                "The instruction to escalate this incident is not yet confirmed."
            ),
            ("Escalate this incident.",),
        ),
        (
            (
                "Do not touch the damaged parcel. Contact emergency services. "
                "The instruction to contact emergency services is not yet confirmed."
            ),
            ("Contact emergency services.",),
        ),
        (
            (
                "Please do not ship today. Reference. "
                "A return address and reference are not yet confirmed."
            ),
            ("Reference.",),
        ),
        (
            (
                "Please do not ship today. Return reference. "
                "The return reference has not yet been issued."
            ),
            ("A return reference.",),
        ),
        (
            (
                "Keep clear of the damaged parcel. Stop. "
                "A safety hold and stop are not yet confirmed."
            ),
            ("A safety stop.",),
        ),
    ],
)
def test_grounding_repair_orphan_cleanup_preserves_unanchored_content(
    answer,
    unsupported,
):
    assert issues._clean_grounding_repair_orphan_fragments(
        answer,
        unsupported_claims=unsupported,
    ) == answer


def test_grounding_repair_orphan_cleanup_removes_only_anchored_inline_fragment():
    answer = (
        "Return policy applies. Reference. "
        "A return address and reference are not yet confirmed. Keep the item packaged."
    )

    assert issues._clean_grounding_repair_orphan_fragments(
        answer,
        unsupported_claims=("A return reference.",),
    ) == (
        "Return policy applies. "
        "A return address and reference are not yet confirmed. Keep the item packaged."
    )


def test_channel_autopilot_repairs_s02_factual_corruption_once(monkeypatch):
    reply_calls, grounding_calls = _stub_channel_agent_answer(
        monkeypatch,
        verified=True,
    )
    draft_calls: list[dict] = []
    original_answer = "The affected service is authentication in the EU region 40 00Z."
    repaired_answer = (
        "Authentication is affected in the EU region. "
        "The incident began at 2026-07-19T07:40:00Z."
    )
    unsupported = (original_answer,)
    contradictions = (
        "The answer merges region EU with started_at 2026-07-19T07:40:00Z.",
    )

    def fake_draft(**kwargs):
        draft_calls.append(kwargs)
        answer = original_answer if len(draft_calls) == 1 else repaired_answer
        return IssueAgentDraft(
            answer=answer,
            confidence="high",
            generation_mode="llm",
        )

    def fake_grounding(**kwargs):
        grounding_calls.append(kwargs)
        if len(grounding_calls) == 1:
            return AutomationGroundingAssessment(
                verified=False,
                status="failed",
                reason_code="ungrounded_answer",
                checked_at="2026-07-19T10:05:00Z",
                answer_sha256=issue_agent.grounding_text_sha256(kwargs["answer"]),
                unsupported_claims=unsupported,
                contradictions=contradictions,
                provider="test",
                model="grounding-model",
            )
        return AutomationGroundingAssessment(
            verified=True,
            status="passed",
            reason_code="",
            checked_at="2026-07-19T10:05:01Z",
            answer_sha256=issue_agent.grounding_text_sha256(kwargs["answer"]),
            provider="test",
            model="grounding-model",
        )

    monkeypatch.setattr(issues, "draft_issue_automation_answer", fake_draft)
    monkeypatch.setattr(issues, "assess_issue_automation_grounding", fake_grounding)
    grounding_calls.clear()

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
    assert len(draft_calls) == 2
    assert draft_calls[1]["coverage_repair_answer"] == original_answer
    assert draft_calls[1]["coverage_repair_obligations"] == ()
    assert draft_calls[1]["grounding_repair_unsupported_claims"] == unsupported
    assert draft_calls[1]["grounding_repair_contradictions"] == contradictions
    assert [call["answer"] for call in grounding_calls] == [
        original_answer,
        repaired_answer,
    ]
    assert result["draftBlockedReason"] == ""
    assert result["reply"]["id"] == "reply1"
    assert reply_calls[0]["body"] == repaired_answer
    assert reply_calls[0]["metadata"]["groundingGate"]["coverageRepair"] == {
        "attempted": True,
        "triggerReasonCode": "ungrounded_answer",
        "uncoveredObligations": [],
        "unsupportedClaims": list(unsupported),
        "contradictions": list(contradictions),
        "originalAnswerSha256": issue_agent.grounding_text_sha256(original_answer),
        "generationMode": "llm",
        "generationError": "",
        "repairedAnswerSha256": issue_agent.grounding_text_sha256(repaired_answer),
        "verified": True,
        "resultReasonCode": "",
    }


def test_channel_autopilot_preserves_s02_start_time_after_action_repair_then_regrounds(
    monkeypatch,
):
    reply_calls, grounding_calls = _stub_channel_agent_answer(
        monkeypatch,
        verified=True,
    )
    guidance = "State the exact start time only from the successful service-status lookup."
    obligation_id = "service-incident:required-guidance-1"
    omitted_answer = (
        "INC-204 affects the EU authentication service and is under investigation. "
        "The ETA is unavailable."
    )
    unsafe_repair_answer = (
        "We opened a P1 escalation for the incident that began at "
        "2026-07-19T07:40:00Z."
    )
    repaired_answer = (
        "The P1 escalation remains pending human review and is not confirmed as "
        "opened.\n\n"
        "The incident began at 2026-07-19T07:40:00Z."
    )
    incident_issue = {
        "id": "issue1",
        "subject": "EU authentication outage",
        "messages": [
            {
                "id": "message1",
                "direction": "customer",
                "body": "When did incident INC-204 start?",
            }
        ],
        "aiRuns": [
            {
                "source": "channel:email-main",
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "service-incident",
                            "matched": True,
                            "intentName": "saas-service-incident",
                            "requiredGuidance": [guidance],
                            "toolEvidence": [
                                {
                                    "name": "service_status_inc_204",
                                    "method": "GET",
                                    "status": "success",
                                    "responseFacts": {
                                        "status": "investigating",
                                        "affected_region": "EU",
                                        "affected_service": "authentication",
                                        "started_at": "2026-07-19T07:40:00Z",
                                    },
                                }
                            ],
                        }
                    ]
                },
            }
        ],
        "actionExecutions": [
            {
                "id": "execution-p1",
                "type": "runbook_webhook",
                "status": "pending",
                "label": "Open P1 Escalation",
                "metadata": {
                    "source": "runbook",
                    "approvalRequired": True,
                    "concernId": "service-incident",
                    "runbook": "saas-service-incident",
                    "proposedAction": {
                        "name": "open_p1_escalation",
                        "label": "Open P1 Escalation",
                    },
                },
            }
        ],
    }
    draft_calls: list[dict] = []

    def fake_draft(**kwargs):
        draft_calls.append(kwargs)
        return IssueAgentDraft(
            answer=(
                omitted_answer
                if len(draft_calls) == 1
                else unsafe_repair_answer
            ),
            confidence="high",
            generation_mode="llm",
        )

    def fake_grounding(**kwargs):
        grounding_calls.append(kwargs)
        if len(grounding_calls) == 1:
            return AutomationGroundingAssessment(
                verified=False,
                status="failed",
                reason_code="incomplete_answer",
                checked_at="2026-07-20T09:00:00Z",
                answer_sha256=issue_agent.grounding_text_sha256(kwargs["answer"]),
                answer_obligations=(
                    {
                        "id": obligation_id,
                        "concernId": "service-incident",
                        "question": guidance,
                        "kind": "runbook_requirement",
                    },
                ),
                obligation_assessments=(
                    {
                        "obligationId": obligation_id,
                        "covered": False,
                        "resolution": "not_covered",
                    },
                ),
                uncovered_obligations=(guidance,),
                provider="test",
                model="grounding-model",
            )
        assert kwargs["answer"] == repaired_answer
        return AutomationGroundingAssessment(
            verified=True,
            status="passed",
            reason_code="",
            checked_at="2026-07-20T09:00:01Z",
            answer_sha256=issue_agent.grounding_text_sha256(kwargs["answer"]),
            answer_obligations=(
                {
                    "id": obligation_id,
                    "concernId": "service-incident",
                    "question": guidance,
                    "kind": "runbook_requirement",
                },
            ),
            obligation_assessments=(
                {
                    "obligationId": obligation_id,
                    "covered": True,
                    "resolution": "answered",
                },
            ),
            provider="test",
            model="grounding-model",
        )

    monkeypatch.setattr(issues, "get_issue", lambda *_args, **_kwargs: incident_issue)
    monkeypatch.setattr(issues, "draft_issue_automation_answer", fake_draft)
    monkeypatch.setattr(issues, "assess_issue_automation_grounding", fake_grounding)
    grounding_calls.clear()

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
    assert len(draft_calls) == 2
    assert [call["answer"] for call in grounding_calls] == [
        omitted_answer,
        repaired_answer,
    ]
    assert result["draftBlockedReason"] == ""
    assert reply_calls[0]["body"] == repaired_answer
    assert result["groundingGate"]["coverageRepair"]["verified"] is True


def test_channel_factual_repair_is_rechecked_and_fails_closed_on_missing_safety(
    monkeypatch,
):
    reply_calls, grounding_calls = _stub_channel_agent_answer(
        monkeypatch,
        verified=True,
    )
    battery_issue = {
        "id": "issue1",
        "subject": "Leaking lithium battery and incident status",
        "messages": [
            {
                "id": "message1",
                "direction": "customer",
                "body": (
                    "The parcel contains a leaking lithium battery pack and is getting hot. "
                    "Which service and region are affected, and when did the incident start?"
                ),
            }
        ],
    }
    original_answer = (
        "Stop handling, using, and charging the item immediately. Isolate it only if this "
        "can be done safely, and keep it away from heat and flammable materials only if safe. "
        "Do not ship or return it until confirmed hazardous-goods instructions arrive after "
        "human review. If smoke, fire, or unusual heat is present or develops, move away and "
        "contact local emergency services or the local fire authority. The affected service "
        "is authentication in the EU region 40 00Z."
    )
    unsafe_repair = (
        "Authentication is affected in the EU region. "
        "The incident began at 2026-07-19T07:40:00Z."
    )
    draft_calls: list[dict] = []

    def fake_draft(**kwargs):
        draft_calls.append(kwargs)
        return IssueAgentDraft(
            answer=original_answer if len(draft_calls) == 1 else unsafe_repair,
            confidence="high",
            generation_mode="llm",
        )

    original_grounding = issue_agent.assess_issue_automation_grounding

    def fake_grounding(**kwargs):
        grounding_calls.append(kwargs)
        if len(grounding_calls) == 1:
            return AutomationGroundingAssessment(
                verified=False,
                status="failed",
                reason_code="incomplete_answer",
                checked_at="2026-07-19T10:05:00Z",
                answer_sha256=issue_agent.grounding_text_sha256(kwargs["answer"]),
                uncovered_obligations=("Give immediate damaged-battery safety guidance.",),
                unsupported_claims=(
                    "The affected service is authentication in the EU region 40 00Z.",
                ),
                contradictions=(
                    "The answer merges region EU with started_at 2026-07-19T07:40:00Z.",
                ),
                provider="test",
                model="grounding-model",
            )
        return original_grounding(**kwargs)

    monkeypatch.setattr(issues, "get_issue", lambda *_args, **_kwargs: battery_issue)
    monkeypatch.setattr(issues, "draft_issue_automation_answer", fake_draft)
    monkeypatch.setattr(issues, "assess_issue_automation_grounding", fake_grounding)
    grounding_calls.clear()

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
    assert len(draft_calls) == 2
    assert len(grounding_calls) == 2
    assert result["draftBlockedReason"] == "safety_guidance_missing"
    assert result["reply"] is None
    assert reply_calls == []
    repair_metadata = result["groundingGate"]["coverageRepair"]
    assert repair_metadata["attempted"] is True
    assert repair_metadata["verified"] is False
    assert repair_metadata["resultReasonCode"] == "safety_guidance_missing"


def test_channel_grounding_repairs_against_pending_actions_created_during_composition(monkeypatch):
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

    grounding_calls.clear()

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
    assert grounding_calls[0]["answer"] == (
        "The ticket remains pending human review and is not confirmed as opened."
    )
    assert result is not None
    assert result["draftBlockedReason"] == ""
    assert result["reply"]["id"] == "reply1"
    assert reply_calls[0]["body"] == (
        "The ticket remains pending human review and is not confirmed as opened."
    )


@pytest.mark.parametrize(
    "answer",
    [
        "We are initiating the steps to open this investigation.",
        "We have immediately escalated this case to our operations team.",
        "A delivery-exception investigation is being initiated.",
        "This urgent B2B SLA incident has been escalated for human operations review.",
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


def test_grounding_preflight_blocks_live_pending_agent_triage_claims(monkeypatch):
    source_message_id = "channel:email-main:law-r10-c03-message"
    answer = (
        "We have noted the critical deadline of 20 July 2026 and have escalated "
        "your request for immediate human triage due to its urgency. While we "
        "cannot promise a same-day consultation, we are prioritizing your matter."
    )
    issue = {
        "id": "issue1",
        "subject": "Urgent legal consultation",
        "aiRuns": [
            {
                "source": "channel:email-main",
                "metadata": {"emailId": source_message_id},
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "legal-intake",
                            "matched": True,
                            "intentName": "legal-intake-qa",
                        }
                    ]
                },
            }
        ],
        "actionExecutions": [
            {
                "type": "agent_triage",
                "actionKey": "agent_triage",
                "label": "Prior-message agent triage",
                "status": "pending",
                "metadata": {
                    "source": "agent_triage",
                    "approvalRequired": True,
                    "automationContext": {"sourceMessageId": "channel:email-main:older-message"},
                },
                "result": {
                    "proposedAction": {
                        "type": "triage_ticket",
                        "priority": "urgent",
                    }
                },
            },
            {
                "type": "agent_triage",
                "actionKey": "agent_triage",
                "label": "Agent triage",
                "status": "pending",
                "metadata": {
                    "source": "agent_triage",
                    "approvalRequired": True,
                    "approved": False,
                    "automationContext": {
                        "sourceMessageId": source_message_id,
                        "messageId": "law-r10-c03-message",
                    },
                },
                "result": {
                    "proposedAction": {
                        "type": "triage_ticket",
                        "priority": "urgent",
                        "status": "ongoing",
                    }
                },
            },
        ],
    }
    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: pytest.fail("grounding LLM must not run"),
    )

    ticket_context = issue_agent._automatic_ticket_context(issue)
    result = issue_agent.assess_issue_automation_grounding(
        issue=issue,
        messages=[],
        answer=answer,
        articles=[],
        tenant_id="tenant1",
        project_id="project1",
    )

    assert ticket_context["runbookActions"] == [
        {
            "name": "agent_triage",
            "label": "Agent triage",
            "status": "pending_approval",
        }
    ]
    assert result.verified is False
    assert result.reason_code == "pending_action_claim"
    assert result.pending_action_claims == (
        (
            "We have noted the critical deadline of 20 July 2026 and have escalated "
            "your request for immediate human triage due to its urgency."
        ),
        ("While we cannot promise a same-day consultation, we are prioritizing your matter."),
    )
    assert result.pending_actions == ("Agent triage",)


def test_grounding_preflight_blocks_active_internal_review_with_pending_triage(
    monkeypatch,
):
    source_message_id = "channel:email-main:law-rerun-c08-message"
    answer = "This matter is now undergoing an internal review process."
    issue = {
        "id": "issue1",
        "subject": "Legal matter review",
        "aiRuns": [
            {
                "source": "channel:email-main",
                "metadata": {"emailId": source_message_id},
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "legal-intake",
                            "matched": True,
                            "intentName": "legal-intake-qa",
                        }
                    ]
                },
            }
        ],
        "actionExecutions": [
            {
                "type": "agent_triage",
                "actionKey": "agent_triage",
                "label": "Agent triage",
                "status": "pending",
                "metadata": {
                    "source": "agent_triage",
                    "approvalRequired": True,
                    "approved": False,
                    "automationContext": {
                        "sourceMessageId": source_message_id,
                        "messageId": "law-rerun-c08-message",
                    },
                },
                "result": {
                    "proposedAction": {
                        "type": "triage_ticket",
                        "priority": "normal",
                        "status": "ongoing",
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

    ticket_context = issue_agent._automatic_ticket_context(issue)
    result = issue_agent.assess_issue_automation_grounding(
        issue=issue,
        messages=[],
        answer=answer,
        articles=[],
        tenant_id="tenant1",
        project_id="project1",
    )

    assert ticket_context["runbookActions"] == [
        {
            "name": "agent_triage",
            "label": "Agent triage",
            "status": "pending_approval",
        }
    ]
    assert result.verified is False
    assert result.reason_code == "pending_action_claim"
    assert result.pending_action_claims == (answer,)
    assert result.pending_actions == ("Agent triage",)


def test_grounding_preflight_rejects_safe_but_internal_triage_disclosure(
    monkeypatch,
):
    source_message_id = "channel:email-main:saas-s02-message"
    issue = {
        "id": "issue1",
        "subject": "Service incident",
        "aiRuns": [
            {
                "source": "channel:email-main",
                "metadata": {"emailId": source_message_id},
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "service-incident",
                            "matched": True,
                            "intentName": "service-incident",
                        }
                    ]
                },
            }
        ],
        "actionExecutions": [
            {
                "type": "agent_triage",
                "actionKey": "agent_triage",
                "label": "Agent triage",
                "status": "pending",
                "metadata": {
                    "source": "agent_triage",
                    "approvalRequired": True,
                    "automationContext": {"sourceMessageId": source_message_id},
                },
            }
        ],
    }
    answer = "Agent triage and opening your support ticket are pending human review."
    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: pytest.fail("grounding LLM must not run"),
    )

    result = issue_agent.assess_issue_automation_grounding(
        issue=issue,
        messages=[{"direction": "customer", "body": "Please open a support ticket."}],
        answer=answer,
        articles=[],
        tenant_id="tenant1",
        project_id="project1",
    )

    assert result.verified is False
    assert result.reason_code == issue_agent.INTERNAL_STATE_DISCLOSURE_REASON_CODE
    assert result.unsupported_claims == (answer,)


def test_scoped_grounding_evidence_excludes_internal_triage_action() -> None:
    ticket = {
        "concerns": [{"id": "service-incident", "matched": True}],
        "runbookActions": [
            {
                "name": "agent_triage",
                "label": "Agent triage",
                "status": "pending_approval",
                "concernId": "service-incident",
            },
            {
                "name": "open_p1_escalation",
                "label": "Open P1 escalation",
                "status": "pending_approval",
                "concernId": "service-incident",
            },
        ],
    }

    scoped = issue_agent._scoped_grounding_ticket_evidence(ticket)

    assert scoped == {
        "concerns": [
            {
                "evidenceId": "concern:service-incident",
                "concernId": "service-incident",
                "context": {"id": "service-incident", "matched": True},
                "runbookActions": [
                    {
                        "name": "open_p1_escalation",
                        "label": "Open P1 escalation",
                        "status": "pending_approval",
                        "concernId": "service-incident",
                    }
                ],
            }
        ]
    }


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
            "Hallo Lena, Ihre Bestellung ist unterwegs. Die voraussichtliche Zustellung erfolgt am nächsten Werktag."
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
        "items": [{"result": {"actions": [{"type": "prepare_agent_reply", "status": "prepared", "replyId": ""}]}}]
    }
    with_reply = {
        "items": [{"result": {"actions": [{"type": "prepare_agent_reply", "status": "prepared", "replyId": "reply1"}]}}]
    }
    with_queued_reply = {"items": [{"result": {"actions": [{"type": "queue_reply", "replyId": "reply2"}]}}]}

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
                    "proposedAction": {"name": "semantic_failure"},
                    "application": {
                        "applied": True,
                        "webhookResult": {
                            "status": "ok",
                            "response": {
                                "status": "failed",
                                "reference": "BAD-STATUS-1",
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
                    "proposedAction": {"name": "error_with_reference"},
                    "application": {
                        "applied": True,
                        "webhookResult": {
                            "status": "ok",
                            "response": {
                                "error": "could not cancel",
                                "reference": "ERR-1",
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
                    "proposedAction": {"name": "failed_with_id"},
                    "application": {
                        "applied": True,
                        "webhookResult": {
                            "status": "ok",
                            "response": {"failed": True, "id": "ERR1"},
                        },
                    },
                },
            },
            {
                "type": "runbook_webhook",
                "status": "success",
                "metadata": {"source": "runbook"},
                "result": {
                    "proposedAction": {"name": "failure_with_confirmation"},
                    "application": {
                        "applied": True,
                        "webhookResult": {
                            "status": "ok",
                            "response": {
                                "failure": "warehouse rejected",
                                "confirmationNumber": "ERR-2",
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
                    "proposedAction": {"name": "not_found_status"},
                    "application": {
                        "applied": True,
                        "webhookResult": {
                            "status": "ok",
                            "response": {"status": "not_found"},
                        },
                    },
                },
            },
            {
                "type": "runbook_webhook",
                "status": "success",
                "metadata": {"source": "runbook"},
                "result": {
                    "proposedAction": {"name": "missing_status"},
                    "application": {
                        "applied": True,
                        "webhookResult": {
                            "status": "ok",
                            "response": {"status": "missing"},
                        },
                    },
                },
            },
            {
                "type": "runbook_webhook",
                "status": "success",
                "metadata": {"source": "runbook"},
                "result": {
                    "proposedAction": {"name": "negative_confirmation"},
                    "application": {
                        "applied": True,
                        "webhookResult": {
                            "status": "ok",
                            "response": {
                                "ok": False,
                                "reference": "BAD-OK-1",
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
            "applied": True,
            "webhookResult": {"status": "ok"},
            "proof": {"status": "opened", "ticketReference": "ZF-42"},
        },
    ]
    assert context["runbookActions"] == expected_actions
    assert knowledge_context["runbookActions"] == expected_actions


def test_automatic_action_context_bounds_every_copied_proof_value():
    issue = {
        "id": "issue-proof-bounds",
        "actionExecutions": [
            {
                "type": "runbook_webhook",
                "status": "success",
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
                                "status": "complete",
                                "reference": "X" * 100_000,
                            },
                        },
                    },
                },
            }
        ],
    }

    context = issue_agent._automatic_ticket_context(issue)

    assert context["runbookActions"] == [
        {
            "name": "confirm_ticket",
            "label": "Confirm ticket",
            "status": "success",
            "completedAt": "",
            "applied": True,
            "webhookResult": {"status": "ok"},
            "proof": {"status": "complete"},
        }
    ]
    assert len(json.dumps(context)) < 1_000


@pytest.mark.parametrize(
    "response",
    [
        {"status": "success", "result": "failed", "reference": "X-1"},
        {"status": "complete", "message": "action failed", "reference": "X-1"},
        {"status": "complete", "outcome": "pending approval", "reference": "X-1"},
        {
            "status": "complete",
            "details": {"status": "failed"},
            "reference": "X-1",
        },
        {"status": "complete", "data": "refund failed", "reference": "X-1"},
        {"message": "we didn't issue the refund", "reference": "X-1"},
        {"message": "we haven't issued the refund", "reference": "X-1"},
        {"message": "no refund was issued", "reference": "X-1"},
        {"message": "refund without being issued", "reference": "X-1"},
        {"status": "queued", "reference": "X-1"},
        {"success": "false", "reference": "X-1"},
        {"status": 500, "reference": "X-1"},
    ],
)
def test_automatic_action_context_rejects_ambiguous_or_negative_webhook_proof(
    response: dict[str, object],
) -> None:
    issue = {
        "id": "issue-invalid-proof",
        "actionExecutions": [
            {
                "id": "execution-invalid-proof",
                "type": "runbook_webhook",
                "status": "success",
                "metadata": {
                    "source": "runbook",
                    "concernId": "concern-refund",
                },
                "result": {
                    "proposedAction": {
                        "name": "issue_refund",
                        "label": "Issue refund",
                    },
                    "application": {
                        "applied": True,
                        "webhookResult": {
                            "status": "ok",
                            "response": response,
                        },
                    },
                },
            }
        ],
    }

    context = issue_agent._automatic_ticket_context(issue)

    assert context.get("runbookActions", []) == []


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
