from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from automail.api.process import process_email_for_context
from automail.billing import addons as billing_addons
from automail.billing import agent_runs
from automail.billing.agent_runs import reserve_agent_run
from automail.billing.usage import check_limit, get_usage
from automail.db.pocketbase import issues
from automail.models import AgentResponse, Email, IdentityResult, IntentResult, ProcessEmailRequest
from automail.support import channel_runbooks
from automail.support.channel_runbooks import DirectChannelRunbookResult


def test_usage_counts_one_cross_channel_agent_run_ledger(monkeypatch):
    collections: list[str] = []

    def fake_list_all(collection: str, *_args, **_kwargs):
        collections.append(collection)
        if collection == "agent_runs":
            return [
                {"source": "channel:email-main"},
                {"source": "slack"},
                {"source": "teams"},
                {"source": "web_chat"},
                {"source": "customer_portal"},
            ]
        if collection == "projects":
            return [{"id": "project1"}]
        if collection == "users":
            return [{"id": "user1"}]
        return []

    monkeypatch.setattr(
        "automail.billing.usage.get_tenant_record",
        lambda _tenant_id: {"current_period_start": "2026-07-01T00:00:00+00:00"},
    )
    monkeypatch.setattr("automail.db.pocketbase.client._list_all", fake_list_all)

    usage = get_usage("tenant1")

    assert usage["agent_runs_this_period"] == 5
    assert usage["emails_this_period"] == 5
    assert "chats" not in collections


def test_reservation_is_idempotent_for_retries(monkeypatch):
    stored: dict[str, dict] = {}
    posted: list[dict] = []

    monkeypatch.setattr(agent_runs, "IS_SAAS", True)
    monkeypatch.setattr(
        agent_runs,
        "_existing_agent_run",
        lambda _tenant_id, key: stored.get(key),
    )
    monkeypatch.setattr("automail.billing.usage.check_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.db.pocketbase.client.generate_id", lambda: "agentrun1")

    def fake_post(_path: str, data: dict) -> dict:
        posted.append(data)
        stored[data["idempotency_key"]] = {**data, "created": "2026-07-21 10:00:00.000Z"}
        return stored[data["idempotency_key"]]

    monkeypatch.setattr("automail.db.pocketbase.client._post", fake_post)
    monkeypatch.setattr(
        "automail.billing.addons.sync_stripe_addons_best_effort",
        lambda _tenant_id: {},
    )
    key = agent_runs.direct_channel_agent_run_key(
        project_id="project1",
        source="slack",
        source_message_id="slack:T1:C1:100.1",
    )

    first = reserve_agent_run(
        tenant_id="tenant1",
        project_id="project1",
        source="slack",
        idempotency_key=key,
    )
    retry = reserve_agent_run(
        tenant_id="tenant1",
        project_id="project1",
        source="slack",
        idempotency_key=key,
    )

    assert first.created is True
    assert retry.created is False
    assert first.record == retry.record
    assert len(posted) == 1


def test_hosted_agent_run_quota_uses_ledger_count(monkeypatch):
    monkeypatch.setattr("automail.billing.usage.IS_SAAS", True)
    monkeypatch.setattr("automail.billing.usage.get_effective_tenant_plan", lambda _tenant_id: "free")
    monkeypatch.setattr("automail.billing.usage._get_limit", lambda _plan, _resource: 2)
    monkeypatch.setattr("automail.billing.usage.get_agent_runs_this_period", lambda _tenant_id: 2)
    monkeypatch.setattr("automail.billing.usage._addon_price_for_resource", lambda _resource: "")

    with pytest.raises(HTTPException) as error:
        check_limit("tenant1", "agent_runs_per_month")

    assert error.value.status_code == 402
    assert error.value.detail["resource"] == "agent_runs_per_month"
    assert error.value.detail["current"] == 2


def test_agent_run_ledger_drives_run_addon_blocks(monkeypatch):
    created_items: list[dict] = []

    class SubscriptionItem:
        @staticmethod
        def create(**kwargs):
            created_items.append(kwargs)

    monkeypatch.setattr(billing_addons, "IS_SAAS", True)
    monkeypatch.setattr(billing_addons, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(billing_addons, "STRIPE_EXTRA_EMAIL_BLOCK_PRICE_ID", "price_run_block")
    monkeypatch.setattr(billing_addons, "STRIPE_EXTRA_EMAIL_BLOCK_SIZE", 100)
    monkeypatch.setattr(billing_addons, "STRIPE_EXTRA_PROJECT_PRICE_ID", "")
    monkeypatch.setattr(billing_addons, "STRIPE_EXTRA_USER_PRICE_ID", "")
    monkeypatch.setattr(
        billing_addons,
        "_ensure_stripe",
        lambda: SimpleNamespace(SubscriptionItem=SubscriptionItem),
    )
    monkeypatch.setattr(
        billing_addons,
        "get_tenant_record",
        lambda _tenant_id: {"plan": "pro", "subscription_id": "sub1"},
    )
    monkeypatch.setattr(
        billing_addons,
        "_retrieve_stripe_subscription",
        lambda *_args, **_kwargs: {"id": "sub1", "status": "active"},
    )
    monkeypatch.setattr(billing_addons, "_subscription_items_by_price", lambda _subscription: {})
    monkeypatch.setattr(
        billing_addons,
        "get_usage",
        lambda _tenant_id: {
            "agent_runs_this_period": 351,
            "projects": 1,
            "users": 1,
        },
    )

    synced = billing_addons.sync_stripe_addons("tenant1")

    assert synced == {"price_run_block": 3}
    assert created_items == [
        {
            "subscription": "sub1",
            "price": "price_run_block",
            "quantity": 3,
            "proration_behavior": "none",
        }
    ]


def test_community_agent_runs_are_unlimited_without_ledger(monkeypatch):
    monkeypatch.setattr(agent_runs, "IS_SAAS", False)
    monkeypatch.setattr(
        agent_runs,
        "_existing_agent_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PocketBase must not be queried")),
    )

    reservation = reserve_agent_run(
        tenant_id="tenant1",
        project_id="project1",
        source="web_chat",
        idempotency_key="channel:key",
    )

    assert reservation.metered is False
    assert reservation.record is None


def _pipeline_result() -> SimpleNamespace:
    return SimpleNamespace(
        agent_response=AgentResponse(response_text="Handled", activated_intent="support"),
        identity_result=IdentityResult(customer_found=True, data={"customerId": "customer1"}),
        intent_result=IntentResult(matched=True, intent_name="support"),
        phishing_result=None,
        prompt_injection_result=None,
        token_usage={},
        tools_used=[],
    )


def test_email_reserves_before_pipeline_and_uses_adapter_independent_key(monkeypatch):
    operations: list[tuple[str, dict]] = []

    monkeypatch.setattr("automail.api.process.ensure_draft_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.process.get_live_source", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.process.get_chat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.process.parse_email_attachments", lambda _email: {})
    monkeypatch.setattr("automail.api.process.load_attachment_files", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.api.process.resolve_intent_action_payloads", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.process.store_email_analysis", lambda *_args, **_kwargs: "chat1")
    monkeypatch.setattr("automail.api.process._sync_issue_from_chat", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        "automail.api.process.RunRecorder",
        lambda **_kwargs: SimpleNamespace(finish=lambda **_finish_kwargs: None),
    )
    monkeypatch.setattr(
        "automail.db.pocketbase.client.store_llm_usage_events",
        lambda *_args, **_kwargs: None,
    )

    def fake_reserve(**kwargs):
        operations.append(("reserve", kwargs))
        return SimpleNamespace(created=True, metered=True, record={"id": "run1"})

    def fake_pipeline(*_args, **_kwargs):
        operations.append(("pipeline", {}))
        assert operations[0][0] == "reserve"
        return _pipeline_result()

    monkeypatch.setattr("automail.api.process.reserve_agent_run", fake_reserve)
    monkeypatch.setattr("automail.api.process.run_pipeline", fake_pipeline)
    request = ProcessEmailRequest(
        email=Email(
            id="provider-message-1",
            subject="Help",
            from_address="customer@example.test",
            body="Please help.",
            attachments=[],
        ),
        creator="agent@example.test",
        project_id="project1",
    )

    process_email_for_context(
        request,
        tenant_id="tenant1",
        payload=None,
        source="gmail",
        project_id_override="project1",
    )

    reservation = operations[0][1]
    assert reservation["source"] == "gmail"
    assert reservation["idempotency_key"] == agent_runs.email_agent_run_key(
        project_id="project1",
        email_id="provider-message-1",
    )


def test_cached_email_retry_does_not_reserve_or_recheck_quota(monkeypatch):
    request = ProcessEmailRequest(
        email=Email(
            id="provider-message-1",
            subject="Help",
            from_address="customer@example.test",
            body="Please help.",
            attachments=[],
        ),
        creator="agent@example.test",
        project_id="project1",
    )
    cached_messages = [
        {
            "user": "email",
            "role": "email",
            "content": "Subject: Help\nFrom: customer@example.test\n\nPlease help.",
        },
        {
            "user": "response",
            "role": "response",
            "content": {"emailBody": "Handled", "emailAttachments": []},
        },
    ]

    monkeypatch.setattr("automail.api.process.ensure_draft_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.process.get_live_source", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "automail.api.process.get_chat",
        lambda *_args, **_kwargs: {
            "email_id": "provider-message-1",
            "messages": cached_messages,
            "activated_intent": "support",
        },
    )
    monkeypatch.setattr("automail.api.process._sync_issue_from_chat", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        "automail.api.process.RunRecorder",
        lambda **_kwargs: SimpleNamespace(finish=lambda **_finish_kwargs: None),
    )
    monkeypatch.setattr(
        "automail.api.process.reserve_agent_run",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("cached retry must not reserve")),
    )
    monkeypatch.setattr(
        "automail.api.process.run_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cached retry must not run AI")),
    )

    result = process_email_for_context(
        request,
        tenant_id="tenant1",
        payload=None,
        source="gmail",
        project_id_override="project1",
    )

    assert len(result) == 2


@pytest.mark.parametrize("source", ["slack", "teams", "generic", "web_chat", "customer_portal"])
def test_direct_channels_reserve_at_shared_runbook_boundary(monkeypatch, source):
    operations: list[str] = []

    monkeypatch.setattr(issues, "_direct_channel_processing_run", lambda **_kwargs: None)
    monkeypatch.setattr(issues, "_processing_claim_is_active", lambda _run: True)
    monkeypatch.setattr(
        issues,
        "_start_processing_run",
        lambda **kwargs: operations.append("start")
        or {
            "id": "support-run1",
            "tenant": kwargs["tenant_id"],
            "project": kwargs["project_id"],
            "status": "processing",
            "metadata": {},
            "started_at": "2026-07-21T10:00:00+00:00",
        },
    )
    monkeypatch.setattr(issues, "_patch", lambda _path, data: data)
    monkeypatch.setattr(issues, "_prepare_runbook_action_approvals", lambda **_kwargs: [])
    monkeypatch.setattr("automail.pipeline.drafts.get_live_source", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "automail.billing.agent_runs.reserve_agent_run",
        lambda **_kwargs: operations.append("reserve")
        or SimpleNamespace(created=True, metered=True, record={"id": "meter1"}),
    )

    def fake_runbooks(**_kwargs):
        operations.append("runbooks")
        return DirectChannelRunbookResult(
            identity_result={},
            intent_result={"matched": False, "concerns": []},
            token_usage={},
            tool_calls=[],
            generated_attachments=[],
            activated_intent="",
            summary="No runbook matched",
            requires_human=True,
        )

    monkeypatch.setattr(channel_runbooks, "run_direct_channel_runbooks", fake_runbooks)

    issues._apply_direct_channel_runbooks(
        issue={"id": "issue1", "requires_human": True},
        source=source,
        source_message_id=f"{source}:message1",
        subject="Help",
        body="Please help.",
        identity={"contact_email": "customer@example.test", "contact_name": "Customer"},
        identity_data={"provider": source},
        tenant_id="tenant1",
        project_id="project1",
    )

    assert operations[:3] == ["reserve", "start", "runbooks"]
