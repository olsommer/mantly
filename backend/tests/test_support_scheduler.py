import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from automail.api.admin import channels as admin_channels
from automail.api.admin import issues as admin_issue_api
from automail.support import scheduler


def _provider_delivery_proof(provider: str = "slack", channel_id: str = "C_LIVE") -> dict:
    return {
        "deliveryRoute": {
            "provider": provider,
            "channel": provider,
            "transport": "provider_api",
            "channelId": channel_id,
            "targetUrl": f"https://api.example.test/{provider}",
        },
        "providerResponse": {"statusCode": 200, "body": {"ok": True}},
    }


def _inbound_smoke_result(
    channel_id: str = "C_LIVE",
    issue_id: str = "issue1",
    smoke_target: dict | None = None,
) -> dict:
    return {
        "ready": True,
        "transport": "http",
        "issueId": issue_id,
        "smokeTarget": smoke_target or {"channelId": channel_id},
    }


def _attachment_lifecycle_run(
    *,
    provider_delivery: bool = False,
    auth: dict | None = None,
    provider: str = "slack",
    channel_id: str = "C_LIVE",
) -> dict:
    inbound = {"transport": "http", "issueId": "issue-attachment"}
    if auth:
        inbound["http"] = {"auth": auth}
    result = {
        "ready": True,
        "sent": True,
        "inbound": inbound,
        "issueId": "issue-attachment",
        "replyId": "reply-attachment",
        "attachmentCount": 1,
        "fileOnly": True,
    }
    if provider_delivery:
        result.update({
            "providerMessageId": f"{provider}:{channel_id}:file",
            **_provider_delivery_proof(provider=provider, channel_id=channel_id),
        })
    return {
        "id": "lifeSmokeFileOnly1",
        "channel": "channel1",
        "source": "admin-lifecycle-smoke",
        "status": "sent",
        "processed": 1,
        "failed": 0,
        "result": result,
    }


def test_run_scheduled_support_sync_delegates_scope(monkeypatch):
    seen: dict = {}

    def fake_sync(**kwargs):
        seen.update(kwargs)
        return {"channels": 1, "processed": 2, "failed": 0, "skipped": 0, "items": []}

    monkeypatch.setattr(scheduler, "sync_support_channels_for_scope", fake_sync)

    result = scheduler.run_scheduled_support_sync(
        tenant_id="tenant1",
        project_id="project1",
        limit=10,
        source="cron",
    )

    assert result["processed"] == 2
    assert seen["tenant_id"] == "tenant1"
    assert seen["project_id"] == "project1"
    assert seen["actor_email"] == "support-sync"
    assert seen["source"] == "cron"


def test_run_scheduled_support_processing_expiry_delegates_scope(monkeypatch):
    seen: dict = {}

    def fake_expiry(**kwargs):
        seen.update(kwargs)
        return {"inspected": 2, "expired": 1, "failed": 0, "items": []}

    monkeypatch.setattr(
        scheduler,
        "expire_stale_direct_channel_processing_runs_for_scope",
        fake_expiry,
    )

    result = scheduler.run_scheduled_support_processing_expiry(
        tenant_id="tenant1",
        project_id="project1",
        limit=12,
        source="cron",
    )

    assert result["expired"] == 1
    assert seen == {
        "tenant_id": "tenant1",
        "project_id": "project1",
        "limit": 12,
        "source": "cron",
    }


def test_support_processing_expiry_scheduler_starts_by_default(monkeypatch):
    created: dict = {}

    class FakeThread:
        def __init__(self, *, target, args, daemon, name):
            created.update({
                "target": target,
                "args": args,
                "daemon": daemon,
                "name": name,
            })

        def start(self):
            created["started"] = True

    monkeypatch.setattr(scheduler, "_processing_expiry_started", False)
    monkeypatch.delenv("SUPPORT_PROCESSING_EXPIRY_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("SUPPORT_PROCESSING_EXPIRY_TENANT_ID", raising=False)
    monkeypatch.delenv("SUPPORT_PROCESSING_EXPIRY_PROJECT_ID", raising=False)
    monkeypatch.delenv("SUPPORT_PROCESSING_EXPIRY_LIMIT", raising=False)
    monkeypatch.setattr(scheduler.threading, "Thread", FakeThread)

    assert scheduler.start_support_processing_expiry_scheduler() is True
    assert created == {
        "target": scheduler._loop_processing_expiry,
        "args": (60, None, None, 200),
        "daemon": True,
        "name": "support-processing-expiry-scheduler",
        "started": True,
    }


def test_run_scheduled_support_delivery_records_run(monkeypatch):
    delivered: list[dict] = []
    recorded: list[dict] = []

    def fake_deliver(**kwargs):
        delivered.append(kwargs)
        return {"processed": 2, "sent": 1, "failed": 1, "items": []}

    monkeypatch.setattr(scheduler, "deliver_queued_issue_replies_for_scope", fake_deliver)
    monkeypatch.setattr(
        scheduler,
        "record_delivery_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "run1"},
    )

    result = scheduler.run_scheduled_support_delivery(
        tenant_id="tenant1",
        project_id="project1",
        limit=10,
        source="cron",
    )

    assert result["processed"] == 2
    assert result["status"] == "partial"
    assert delivered == [{"tenant_id": "tenant1", "project_id": "project1", "limit": 10, "include_failed": False}]
    assert recorded[0]["source"] == "cron"
    assert recorded[0]["result"]["failed"] == 1


def test_run_scheduled_support_delivery_can_retry_failed(monkeypatch):
    delivered: list[dict] = []

    def fake_deliver(**kwargs):
        delivered.append(kwargs)
        return {"processed": 1, "sent": 1, "failed": 0, "retryFailed": True, "items": []}

    monkeypatch.setattr(scheduler, "deliver_queued_issue_replies_for_scope", fake_deliver)
    monkeypatch.setattr(scheduler, "record_delivery_run", lambda **_kwargs: {"id": "run1"})

    result = scheduler.run_scheduled_support_delivery(
        tenant_id="tenant1",
        project_id="project1",
        limit=5,
        source="admin",
        retry_failed=True,
    )

    assert result["sent"] == 1
    assert result["retryFailed"] is True
    assert delivered == [{"tenant_id": "tenant1", "project_id": "project1", "limit": 5, "include_failed": True}]


def test_channel_setup_base_url_uses_forwarded_proto_and_host(monkeypatch):
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    monkeypatch.delenv("API_PUBLIC_URL", raising=False)
    request = SimpleNamespace(
        headers={"x-forwarded-proto": "https", "x-forwarded-host": "api.example.test"},
        url=SimpleNamespace(scheme="http", netloc="internal:8080"),
    )

    assert admin_channels._base_url(request) == "https://api.example.test"


def test_bulk_inbound_smoke_skips_chat_channels(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        admin_channels,
        "list_channels",
        lambda **_kwargs: [
            {"id": "webchat1", "channelKey": "web-chat", "type": "chat", "status": "active"},
            {"id": "webhook1", "channelKey": "webhook-main", "type": "webhook", "status": "active"},
        ],
    )

    def fake_smoke(channel: dict, **_kwargs):
        calls.append(channel["channelKey"])
        return {
            "channelId": channel["id"],
            "channelKey": channel["channelKey"],
            "type": channel["type"],
            "ready": True,
            "status": "success",
            "processed": 1,
            "failed": 0,
            "skipped": 0,
            "items": [{"issueId": "issue1"}],
        }

    monkeypatch.setattr(admin_channels, "_run_channel_smoke", fake_smoke)
    monkeypatch.setattr(admin_channels, "record_channel_sync_run", lambda **kwargs: {"id": "run1", **kwargs})

    result = asyncio.run(
        admin_channels.smoke_channels(
            admin_channels.ChannelTestMessageInput(body="Launch proof", transport="http"),
            SimpleNamespace(tenant_id="tenant1", project_id="project1"),
            SimpleNamespace(),
            limit=25,
        )
    )

    assert calls == ["webhook-main"]
    assert result["channels"] == 1
    assert result["processed"] == 1


def test_run_scheduled_support_delivery_reports_deferred(monkeypatch):
    recorded: list[dict] = []

    monkeypatch.setattr(
        scheduler,
        "deliver_queued_issue_replies_for_scope",
        lambda **_kwargs: {"processed": 0, "sent": 0, "failed": 0, "deferred": 2, "items": []},
    )
    monkeypatch.setattr(
        scheduler,
        "record_delivery_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "run1"},
    )

    result = scheduler.run_scheduled_support_delivery(
        tenant_id="tenant1",
        project_id="project1",
        limit=5,
        source="cron",
    )

    assert result["status"] == "deferred"
    assert result["deferred"] == 2
    assert recorded[0]["result"]["status"] == "deferred"


def test_run_scheduled_support_delivery_rolls_up_failed_errors(monkeypatch):
    recorded: list[dict] = []
    monkeypatch.setattr(
        scheduler,
        "deliver_queued_issue_replies_for_scope",
        lambda **_kwargs: {
            "processed": 2,
            "sent": 0,
            "failed": 2,
            "blocked": 0,
            "items": [
                {"id": "reply1", "status": "failed", "error": "SMTP_HOST is not configured"},
                {"id": "reply2", "status": "failed", "error": "Slack channelId is required"},
            ],
        },
    )
    monkeypatch.setattr(
        scheduler,
        "record_delivery_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "run1"},
    )

    result = scheduler.run_scheduled_support_delivery(
        tenant_id="tenant1",
        project_id="project1",
        limit=5,
        source="cron",
    )

    assert result["status"] == "failed"
    assert result["error"] == "2 failed: SMTP_HOST is not configured; Slack channelId is required"
    assert recorded[0]["result"]["error"] == result["error"]


def test_run_scheduled_support_delivery_marks_blocked(monkeypatch):
    recorded: list[dict] = []
    monkeypatch.setattr(
        scheduler,
        "deliver_queued_issue_replies_for_scope",
        lambda **_kwargs: {
            "processed": 1,
            "sent": 0,
            "failed": 0,
            "blocked": 1,
            "items": [
                {"id": "reply1", "status": "queued", "error": "Reply requires approval before sending"},
            ],
        },
    )
    monkeypatch.setattr(
        scheduler,
        "record_delivery_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "run1"},
    )

    result = scheduler.run_scheduled_support_delivery(
        tenant_id="tenant1",
        project_id="project1",
        limit=5,
        source="cron",
    )

    assert result["status"] == "blocked"
    assert result["error"] == "1 blocked: Reply requires approval before sending"
    assert recorded[0]["result"]["status"] == "blocked"


def test_run_scheduled_support_crm_sync_delegates_scope(monkeypatch):
    seen: dict = {}

    def fake_sync(**kwargs):
        seen.update(kwargs)
        return {"connectors": 1, "processed": 2, "failed": 0, "skipped": 0, "objectsSeen": 3, "items": []}

    monkeypatch.setattr(scheduler, "sync_support_crm_connectors_for_scope", fake_sync)

    result = scheduler.run_scheduled_support_crm_sync(
        tenant_id="tenant1",
        project_id="project1",
        limit=10,
        source="cron",
    )

    assert result["processed"] == 2
    assert result["objectsSeen"] == 3
    assert seen == {"tenant_id": "tenant1", "project_id": "project1", "limit": 10, "source": "cron"}


def test_run_scheduled_support_sla_escalations_delegates_scope(monkeypatch):
    seen: dict = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return {"processed": 2, "escalated": 1, "skipped": 1, "failed": 0, "items": []}

    monkeypatch.setattr(scheduler, "run_sla_breach_escalations_for_scope", fake_run)

    result = scheduler.run_scheduled_support_sla_escalations(
        tenant_id="tenant1",
        project_id="project1",
        limit=10,
        source="cron",
    )

    assert result["escalated"] == 1
    assert seen == {
        "tenant_id": "tenant1",
        "project_id": "project1",
        "limit": 10,
        "actor_email": "sla-monitor",
        "source": "cron",
    }


def test_run_scheduled_support_sla_escalations_requires_project():
    result = scheduler.run_scheduled_support_sla_escalations(tenant_id="tenant1", project_id=None)

    assert result["failed"] == 1
    assert result["error"] == "projectId is required for SLA escalation scans"


def test_internal_support_sync_requires_configured_token(client, monkeypatch):
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)

    resp = client.post("/api/internal/support/sync", json={"projectId": "project1"})

    assert resp.status_code == 404


def test_internal_support_sync_runs_with_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "secret-token")

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"channels": 1, "processed": 3, "failed": 0, "skipped": 1, "items": []}

    monkeypatch.setattr("automail.api.internal_support.run_scheduled_support_sync", fake_run)

    resp = client.post(
        "/api/internal/support/sync",
        headers={"X-Support-Sync-Token": "secret-token"},
        json={"tenantId": "tenant1", "projectId": "project1", "limit": 7},
    )

    assert resp.status_code == 200
    assert resp.json()["processed"] == 3
    assert calls == [{"tenant_id": "tenant1", "project_id": "project1", "limit": 7, "source": "cron"}]


def test_internal_support_sync_rejects_bad_token(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "secret-token")

    resp = client.post(
        "/api/internal/support/sync",
        headers={"Authorization": "Bearer wrong-token"},
        json={},
    )

    assert resp.status_code == 401


def test_internal_support_delivery_runs_with_sync_token_fallback(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_DELIVERY_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "secret-token")

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"processed": 2, "sent": 2, "failed": 0, "items": []}

    monkeypatch.setattr("automail.api.internal_support.run_scheduled_support_delivery", fake_run)

    resp = client.post(
        "/api/internal/support/delivery",
        headers={"Authorization": "Bearer secret-token"},
        json={"tenantId": "tenant1", "projectId": "project1", "limit": 11},
    )

    assert resp.status_code == 200
    assert resp.json()["sent"] == 2
    assert calls == [{"tenant_id": "tenant1", "project_id": "project1", "limit": 11, "source": "cron", "retry_failed": False}]


def test_internal_support_delivery_can_retry_failed(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setenv("SUPPORT_DELIVERY_TOKEN", "delivery-token")

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"processed": 1, "sent": 1, "failed": 0, "retryFailed": True, "items": []}

    monkeypatch.setattr("automail.api.internal_support.run_scheduled_support_delivery", fake_run)

    resp = client.post(
        "/api/internal/support/delivery",
        headers={"X-Support-Sync-Token": "delivery-token"},
        json={"tenantId": "tenant1", "projectId": "project1", "limit": 3, "retryFailed": True},
    )

    assert resp.status_code == 200
    assert resp.json()["retryFailed"] is True
    assert calls == [{"tenant_id": "tenant1", "project_id": "project1", "limit": 3, "source": "cron", "retry_failed": True}]


def test_admin_support_delivery_can_retry_failed(client, monkeypatch):
    calls: list[dict] = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"processed": 1, "sent": 1, "failed": 0, "retryFailed": True, "items": []}

    monkeypatch.setattr("automail.api.admin.support_delivery.run_scheduled_support_delivery", fake_run)

    resp = client.post("/api/admin/projects/project1/support/delivery/run?limit=7&retry_failed=true", json={})

    assert resp.status_code == 200
    assert resp.json()["retryFailed"] is True
    assert calls == [{"tenant_id": "", "project_id": "project1", "limit": 7, "source": "admin", "retry_failed": True}]


def test_internal_support_delivery_prefers_delivery_token(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "sync-token")
    monkeypatch.setenv("SUPPORT_DELIVERY_TOKEN", "delivery-token")
    monkeypatch.setattr(
        "automail.api.internal_support.run_scheduled_support_delivery",
        lambda **_kwargs: {"processed": 0, "sent": 0, "failed": 0, "items": []},
    )

    bad = client.post(
        "/api/internal/support/delivery",
        headers={"X-Support-Sync-Token": "sync-token"},
        json={},
    )
    good = client.post(
        "/api/internal/support/delivery",
        headers={"X-Support-Sync-Token": "delivery-token"},
        json={},
    )

    assert bad.status_code == 401
    assert good.status_code == 200


def test_internal_support_crm_sync_runs_with_sync_token_fallback(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_CRM_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "secret-token")

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"connectors": 1, "processed": 4, "failed": 0, "skipped": 0, "objectsSeen": 5, "items": []}

    monkeypatch.setattr("automail.api.internal_support.run_scheduled_support_crm_sync", fake_run)

    resp = client.post(
        "/api/internal/support/crm-sync",
        headers={"Authorization": "Bearer secret-token"},
        json={"tenantId": "tenant1", "projectId": "project1", "limit": 9},
    )

    assert resp.status_code == 200
    assert resp.json()["objectsSeen"] == 5
    assert calls == [{"tenant_id": "tenant1", "project_id": "project1", "limit": 9, "source": "cron"}]


def test_internal_support_crm_sync_prefers_crm_token(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "sync-token")
    monkeypatch.setenv("SUPPORT_CRM_SYNC_TOKEN", "crm-token")
    monkeypatch.setattr(
        "automail.api.internal_support.run_scheduled_support_crm_sync",
        lambda **_kwargs: {"connectors": 0, "processed": 0, "failed": 0, "skipped": 0, "objectsSeen": 0, "items": []},
    )

    bad = client.post(
        "/api/internal/support/crm-sync",
        headers={"X-Support-Sync-Token": "sync-token"},
        json={},
    )
    good = client.post(
        "/api/internal/support/crm-sync",
        headers={"X-Support-Sync-Token": "crm-token"},
        json={},
    )

    assert bad.status_code == 401
    assert good.status_code == 200


def test_internal_support_sla_runs_with_sync_token_fallback(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_SLA_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "secret-token")

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"processed": 2, "escalated": 1, "skipped": 1, "failed": 0, "items": []}

    monkeypatch.setattr("automail.api.internal_support.run_scheduled_support_sla_escalations", fake_run)

    resp = client.post(
        "/api/internal/support/sla",
        headers={"Authorization": "Bearer secret-token"},
        json={"tenantId": "tenant1", "projectId": "project1", "limit": 11},
    )

    assert resp.status_code == 200
    assert resp.json()["escalated"] == 1
    assert calls == [{"tenant_id": "tenant1", "project_id": "project1", "limit": 11, "source": "cron"}]


def test_internal_support_sla_requires_project_id(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_SLA_TOKEN", "sla-token")
    monkeypatch.setattr(
        "automail.api.internal_support.run_scheduled_support_sla_escalations",
        lambda **_kwargs: {"processed": 0, "escalated": 0, "skipped": 0, "failed": 0, "items": []},
    )

    resp = client.post(
        "/api/internal/support/sla",
        headers={"X-Support-Sync-Token": "sla-token"},
        json={},
    )

    assert resp.status_code == 400


def test_internal_support_crm_webhook_ingests_with_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_CRM_WEBHOOK_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "secret-token")

    def fake_ingest(connector_key: str, **kwargs):
        calls.append({"connector_key": connector_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "objectsSeen": 1, "items": []}

    monkeypatch.setattr("automail.api.internal_support.ingest_crm_webhook", fake_ingest)

    resp = client.post(
        "/api/internal/support/crm-webhooks/hubspot-main",
        headers={"X-Support-Sync-Token": "secret-token"},
        json={
            "tenantId": "tenant1",
            "projectId": "project1",
            "payload": {"eventId": "evt-1", "objectType": "account", "data": {"id": "acc-1", "name": "Acme"}},
        },
    )

    assert resp.status_code == 200
    assert resp.json()["processed"] == 1
    assert calls == [{
        "connector_key": "hubspot-main",
        "payload": {"eventId": "evt-1", "objectType": "account", "data": {"id": "acc-1", "name": "Acme"}},
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "webhook",
    }]


def test_internal_support_crm_webhook_prefers_webhook_token(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "sync-token")
    monkeypatch.setenv("SUPPORT_CRM_WEBHOOK_TOKEN", "webhook-token")
    monkeypatch.setattr(
        "automail.api.internal_support.ingest_crm_webhook",
        lambda *_args, **_kwargs: {"status": "success", "processed": 0, "failed": 0, "skipped": 0, "objectsSeen": 0, "items": []},
    )

    bad = client.post(
        "/api/internal/support/crm-webhooks/hubspot-main",
        headers={"X-Support-Sync-Token": "sync-token"},
        json={},
    )
    good = client.post(
        "/api/internal/support/crm-webhooks/hubspot-main",
        headers={"X-Support-Sync-Token": "webhook-token"},
        json={},
    )

    assert bad.status_code == 401
    assert good.status_code == 200


def test_internal_support_channel_webhook_ingests_with_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_CHANNEL_WEBHOOK_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "secret-token")

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "unmatched": 0, "items": []}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)

    resp = client.post(
        "/api/internal/support/channel-webhooks/email:support",
        headers={"X-Support-Sync-Token": "secret-token"},
        json={
            "tenantId": "tenant1",
            "projectId": "project1",
            "payload": {"eventId": "evt-1", "eventType": "delivered", "providerMessageId": "mail-1"},
        },
    )

    assert resp.status_code == 200
    assert resp.json()["processed"] == 1
    assert calls == [{
        "channel_key": "email:support",
        "payload": {"eventId": "evt-1", "eventType": "delivered", "providerMessageId": "mail-1"},
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "webhook",
    }]


def test_internal_support_channel_webhook_keeps_event_loop_responsive(monkeypatch):
    from starlette.requests import Request

    from automail.api import internal_support

    started = threading.Event()
    release = threading.Event()
    auth_threads: list[int] = []
    worker_threads: list[int] = []
    raw_body = json.dumps({
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {
            "messageId": "msg-generic-liveness",
            "fromAddress": "customer@example.com",
            "body": "Where is my order?",
        },
    }).encode()

    def fake_ingest(_channel_key: str, **_kwargs):
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(timeout=2)
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "items": []}

    def fake_require(*_args, **_kwargs):
        auth_threads.append(threading.get_ident())

    monkeypatch.setattr(internal_support, "ingest_channel_webhook", fake_ingest)
    monkeypatch.setattr(internal_support, "_require_channel_webhook_request", fake_require)

    async def scenario():
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": raw_body, "more_body": False}

        request = Request({
            "type": "http",
            "method": "POST",
            "path": "/api/internal/support/channel-webhooks/fulfillment-main",
            "headers": [],
        }, receive)
        event_loop_thread = threading.get_ident()
        request_task = asyncio.create_task(
            internal_support.receive_support_channel_webhook("fulfillment-main", request)
        )
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=1.5)
            assert request_task.done() is False
            assert len(auth_threads) == 1
            assert len(worker_threads) == 1
            assert auth_threads[0] != event_loop_thread
            assert worker_threads[0] != event_loop_thread
            await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
        finally:
            release.set()

        result = await asyncio.wait_for(request_task, timeout=1)
        assert result["processed"] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("route_name", "auth_name", "ingest_name", "path"),
    [
        (
            "receive_support_slack_event",
            "_require_slack_request",
            "ingest_slack_event",
            "/api/internal/support/slack/slack-main",
        ),
        (
            "receive_support_teams_event",
            "_require_provider_channel_request",
            "ingest_teams_event",
            "/api/internal/support/teams/teams-main",
        ),
    ],
)
def test_direct_provider_webhooks_keep_event_loop_responsive(
    monkeypatch,
    route_name,
    auth_name,
    ingest_name,
    path,
):
    from starlette.requests import Request

    from automail.api import internal_support

    started = threading.Event()
    release = threading.Event()
    auth_threads: list[int] = []
    worker_threads: list[int] = []
    raw_body = json.dumps({
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {"messageId": "provider-message-1", "text": "Where is my order?"},
    }).encode()

    def fake_ingest(_channel_key: str, **_kwargs):
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(timeout=2)
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0}

    def fake_require(*_args, **_kwargs):
        auth_threads.append(threading.get_ident())

    monkeypatch.setattr(internal_support, ingest_name, fake_ingest)
    monkeypatch.setattr(internal_support, auth_name, fake_require)

    async def scenario():
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": raw_body, "more_body": False}

        request = Request({
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
        }, receive)
        event_loop_thread = threading.get_ident()
        route = getattr(internal_support, route_name)
        request_task = asyncio.create_task(route(path.rsplit("/", 1)[-1], request))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=1.5)
            assert request_task.done() is False
            assert auth_threads and auth_threads[0] != event_loop_thread
            assert worker_threads and worker_threads[0] != event_loop_thread
            await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
        finally:
            release.set()

        result = await asyncio.wait_for(request_task, timeout=1)
        assert result["processed"] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("route_name", ["start_web_chat", "add_web_chat_message"])
def test_public_web_chat_posts_keep_event_loop_responsive(monkeypatch, route_name):
    from automail.api import support_web_chat

    started = threading.Event()
    release = threading.Event()
    worker_threads: list[int] = []

    def fake_create(*_args, **_kwargs):
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(timeout=2)
        return {"id": "result1", "sessionKey": "session1"}

    dependency_name = (
        "create_web_chat_session"
        if route_name == "start_web_chat"
        else "create_web_chat_message"
    )
    monkeypatch.setattr(support_web_chat, dependency_name, fake_create)

    async def scenario():
        event_loop_thread = threading.get_ident()
        if route_name == "start_web_chat":
            request_task = asyncio.create_task(
                support_web_chat.start_web_chat(
                    "project1",
                    support_web_chat.WebChatSessionCreate(initial_message="Need help"),
                )
            )
        else:
            request_task = asyncio.create_task(
                support_web_chat.add_web_chat_message(
                    "session1",
                    support_web_chat.WebChatMessageCreate(body="Still need help"),
                )
            )
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=1.5)
            assert request_task.done() is False
            assert worker_threads and worker_threads[0] != event_loop_thread
            await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
        finally:
            release.set()

        result = await asyncio.wait_for(request_task, timeout=1)
        assert result["id"] == "result1"

    asyncio.run(scenario())


def test_internal_support_sync_keeps_event_loop_responsive(monkeypatch):
    from starlette.requests import Request

    from automail.api import internal_support

    started = threading.Event()
    release = threading.Event()
    auth_threads: list[int] = []
    worker_threads: list[int] = []

    def fake_require(*_args, **_kwargs):
        auth_threads.append(threading.get_ident())

    def fake_run(**_kwargs):
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(timeout=2)
        return {"processed": 1}

    monkeypatch.setattr(internal_support, "_require_support_token", fake_require)
    monkeypatch.setattr(internal_support, "run_scheduled_support_sync", fake_run)

    async def scenario():
        request = Request({"type": "http", "method": "POST", "path": "/api/internal/support/sync", "headers": []})
        event_loop_thread = threading.get_ident()
        request_task = asyncio.create_task(
            internal_support.run_support_sync(
                internal_support.SupportSyncRequest(project_id="project1"),
                request,
            )
        )
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=1.5)
            assert request_task.done() is False
            assert auth_threads and auth_threads[0] != event_loop_thread
            assert worker_threads and worker_threads[0] != event_loop_thread
        finally:
            release.set()
        assert (await asyncio.wait_for(request_task, timeout=1))["processed"] == 1

    asyncio.run(scenario())


def test_internal_crm_webhook_keeps_event_loop_responsive(monkeypatch):
    from starlette.requests import Request

    from automail.api import internal_support

    started = threading.Event()
    release = threading.Event()
    auth_threads: list[int] = []
    worker_threads: list[int] = []
    raw_body = json.dumps({
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {"eventId": "evt-1"},
    }).encode()

    def fake_require(*_args, **_kwargs):
        auth_threads.append(threading.get_ident())

    def fake_ingest(_connector_key: str, **_kwargs):
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(timeout=2)
        return {"processed": 1}

    monkeypatch.setattr(internal_support, "_require_support_token", fake_require)
    monkeypatch.setattr(internal_support, "ingest_crm_webhook", fake_ingest)

    async def scenario():
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": raw_body, "more_body": False}

        request = Request({
            "type": "http",
            "method": "POST",
            "path": "/api/internal/support/crm-webhooks/hubspot-main",
            "headers": [(b"content-type", b"application/json")],
        }, receive)
        event_loop_thread = threading.get_ident()
        request_task = asyncio.create_task(
            internal_support.receive_support_crm_webhook("hubspot-main", request)
        )
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=1.5)
            assert request_task.done() is False
            assert auth_threads and auth_threads[0] != event_loop_thread
            assert worker_threads and worker_threads[0] != event_loop_thread
        finally:
            release.set()
        assert (await asyncio.wait_for(request_task, timeout=1))["processed"] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("message", "status_code"),
    [("Channel not found", 404), ("Invalid inbound payload", 400)],
)
def test_internal_support_channel_webhook_preserves_value_error_mapping(
    client,
    monkeypatch,
    message,
    status_code,
):
    from automail.api import internal_support

    monkeypatch.setattr(internal_support, "_require_channel_webhook_request", lambda *_args, **_kwargs: None)

    def fail_ingest(*_args, **_kwargs):
        raise ValueError(message)

    monkeypatch.setattr(internal_support, "ingest_channel_webhook", fail_ingest)

    response = client.post(
        "/api/internal/support/channel-webhooks/fulfillment-main",
        json={"tenantId": "tenant1", "projectId": "project1", "payload": {}},
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == message


def test_internal_support_channel_webhook_prefers_channel_token(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "sync-token")
    monkeypatch.setenv("SUPPORT_CHANNEL_WEBHOOK_TOKEN", "channel-token")
    monkeypatch.setattr(
        "automail.api.internal_support.ingest_channel_webhook",
        lambda *_args, **_kwargs: {"status": "success", "processed": 0, "failed": 0, "skipped": 0, "unmatched": 0, "items": []},
    )

    bad = client.post(
        "/api/internal/support/channel-webhooks/email:support",
        headers={"X-Support-Sync-Token": "sync-token"},
        json={},
    )
    good = client.post(
        "/api/internal/support/channel-webhooks/email:support",
        headers={"X-Support-Sync-Token": "channel-token"},
        json={},
    )

    assert bad.status_code == 401
    assert good.status_code == 200


def test_internal_support_email_webhook_ingests_with_email_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "sync-token")
    monkeypatch.setenv("SUPPORT_EMAIL_WEBHOOK_TOKEN", "email-token")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "email",
            "config": {},
        },
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {
            "status": "success",
            "processed": 1,
            "failed": 0,
            "skipped": 0,
            "items": [{"issueId": "issue1"}],
        }

    monkeypatch.setattr("automail.api.internal_support.ingest_email_webhook", fake_ingest)

    bad = client.post(
        "/api/internal/support/email/email:support",
        headers={"X-Support-Sync-Token": "sync-token"},
        json={
            "tenantId": "tenant1",
            "projectId": "project1",
            "payload": {"messageId": "msg-1", "fromAddress": "customer@example.com", "body": "Need help"},
        },
    )
    good = client.post(
        "/api/internal/support/email/email:support",
        headers={"X-Support-Sync-Token": "email-token"},
        json={
            "tenantId": "tenant1",
            "projectId": "project1",
            "actorEmail": "ingress@example.com",
            "payload": {"messageId": "msg-1", "fromAddress": "customer@example.com", "body": "Need help"},
        },
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert good.json()["processed"] == 1
    assert calls == [{
        "channel_key": "email:support",
        "payload": {"messageId": "msg-1", "fromAddress": "customer@example.com", "body": "Need help"},
        "tenant_id": "tenant1",
        "project_id": "project1",
        "actor_email": "ingress@example.com",
        "source": "email-webhook",
    }]


def test_internal_support_email_webhook_keeps_event_loop_responsive(monkeypatch):
    from starlette.requests import Request

    from automail.api import internal_support

    started = threading.Event()
    release = threading.Event()
    auth_threads: list[int] = []
    worker_threads: list[int] = []
    raw_body = json.dumps({
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {
            "messageId": "msg-liveness",
            "fromAddress": "customer@example.com",
            "body": "Need help",
        },
    }).encode()

    def fake_ingest(_channel_key: str, **_kwargs):
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(timeout=2)
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "items": []}

    def fake_require(*_args, **_kwargs):
        auth_threads.append(threading.get_ident())

    monkeypatch.setattr(internal_support, "ingest_email_webhook", fake_ingest)
    monkeypatch.setattr(internal_support, "_require_provider_channel_request", fake_require)

    async def scenario():
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": raw_body, "more_body": False}

        request = Request({
            "type": "http",
            "method": "POST",
            "path": "/api/internal/support/email/email:support",
            "headers": [],
        }, receive)
        event_loop_thread = threading.get_ident()
        request_task = asyncio.create_task(
            internal_support.receive_support_email_event("email:support", request)
        )
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=1.5)
            assert request_task.done() is False
            assert len(auth_threads) == 1
            assert len(worker_threads) == 1
            assert auth_threads[0] != event_loop_thread
            assert worker_threads[0] != event_loop_thread
            await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
        finally:
            release.set()

        result = await asyncio.wait_for(request_task, timeout=1)
        assert result["processed"] == 1

    asyncio.run(scenario())


def test_internal_support_channel_webhook_outbound_echo_uses_outbound_token(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_CHANNEL_WEBHOOK_TOKEN", "channel-token")
    monkeypatch.setenv("SUPPORT_WEBHOOK_OUTBOUND_TOKEN", "outbound-token")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "webhook",
            "config": {"outboundWebhookTokenEnv": "SUPPORT_WEBHOOK_OUTBOUND_TOKEN"},
        },
    )

    bad = client.post(
        "/api/internal/support/channel-webhooks/webhook-main/outbound-echo?tenant_id=tenant1&project_id=project1",
        headers={"Authorization": "Bearer channel-token"},
        json={"messageId": "reply1", "body": "Done."},
    )
    good = client.post(
        "/api/internal/support/channel-webhooks/webhook-main/outbound-echo?tenant_id=tenant1&project_id=project1",
        headers={"Authorization": "Bearer outbound-token"},
        json={"messageId": "reply1", "body": "Done."},
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert good.json()["provider"] == "webhook_echo"
    assert good.json()["providerMessageId"] == "webhook:reply1"


def test_internal_support_channel_webhook_accepts_channel_signature(client, monkeypatch):
    import hashlib
    import hmac
    import json

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_CHANNEL_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_DISCORD_SIGNING_SECRET", "signing-secret")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "discord",
            "config": {
                "signatureSecretEnv": "SUPPORT_DISCORD_SIGNING_SECRET",
                "signatureHeader": "X-Discord-Signature",
            },
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "unmatched": 0, "items": []}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    payload = {
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {"eventId": "evt-1", "eventType": "message_created", "text": "Need help"},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(b"signing-secret", raw, hashlib.sha256).hexdigest()

    bad = client.post(
        "/api/internal/support/channel-webhooks/discord-main",
        content=raw,
        headers={"Content-Type": "application/json", "X-Discord-Signature": "sha256=bad"},
    )
    good = client.post(
        "/api/internal/support/channel-webhooks/discord-main",
        content=raw,
        headers={"Content-Type": "application/json", "X-Discord-Signature": signature},
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert calls == [{
        "channel_key": "discord-main",
        "payload": {"eventId": "evt-1", "eventType": "message_created", "text": "Need help"},
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "webhook",
    }]


def test_internal_support_channel_webhook_rejects_stale_timestamped_signature(client, monkeypatch):
    import hashlib
    import hmac
    import json

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_CHANNEL_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_DISCORD_SIGNING_SECRET", "signing-secret")
    monkeypatch.setattr("automail.api.internal_support.time.time", lambda: 1_700_000_000)
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "discord",
            "config": {
                "signatureSecretEnv": "SUPPORT_DISCORD_SIGNING_SECRET",
                "signatureHeader": "X-Discord-Signature",
                "signatureTimestampRequired": True,
                "signatureTimestampHeader": "X-Bridge-Timestamp",
                "signatureToleranceSeconds": 60,
            },
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "unmatched": 0, "items": []}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    payload = {
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {"eventId": "evt-1", "eventType": "message_created", "text": "Need help"},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def signature(timestamp: str) -> str:
        signed_payload = f"{timestamp}.".encode("utf-8") + raw
        return "sha256=" + hmac.new(b"signing-secret", signed_payload, hashlib.sha256).hexdigest()

    stale = client.post(
        "/api/internal/support/channel-webhooks/discord-main",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Discord-Signature": signature("1699999000"),
            "X-Bridge-Timestamp": "1699999000",
        },
    )
    good = client.post(
        "/api/internal/support/channel-webhooks/discord-main",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Discord-Signature": signature("1700000000"),
            "X-Bridge-Timestamp": "1700000000",
        },
    )

    assert stale.status_code == 401
    assert stale.json()["detail"] == "Stale channel webhook signature timestamp"
    assert good.status_code == 200
    assert calls[0]["channel_key"] == "discord-main"


def test_internal_support_channel_webhook_accepts_project_secret_signature(client, monkeypatch):
    import hashlib
    import hmac
    import json

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_DISCORD_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("SUPPORT_CHANNEL_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setattr(
        "automail.api.internal_support.load_runtime_secrets",
        lambda tenant_id, project_id: {"SUPPORT_DISCORD_SIGNING_SECRET": "stored-secret"}
        if (tenant_id, project_id) == ("tenant1", "project1")
        else {},
    )
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "discord",
            "config": {
                "signatureSecretEnv": "SUPPORT_DISCORD_SIGNING_SECRET",
                "signatureHeader": "X-Discord-Signature",
            },
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    payload = {
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {"eventId": "evt-1", "eventType": "message_created", "text": "Need help"},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(b"stored-secret", raw, hashlib.sha256).hexdigest()

    resp = client.post(
        "/api/internal/support/channel-webhooks/discord-main",
        content=raw,
        headers={"Content-Type": "application/json", "X-Discord-Signature": signature},
    )

    assert resp.status_code == 200
    assert resp.json()["issueId"] == "issue1"
    assert calls == [{
        "channel_key": "discord-main",
        "payload": {"eventId": "evt-1", "eventType": "message_created", "text": "Need help"},
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "webhook",
    }]


def test_internal_support_slack_url_verification_with_token(client, monkeypatch):
    monkeypatch.delenv("SUPPORT_SLACK_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_SLACK_WEBHOOK_TOKEN", "slack-token")

    resp = client.post(
        "/api/internal/support/slack/slack-main",
        headers={"X-Support-Sync-Token": "slack-token"},
        json={"type": "url_verification", "challenge": "challenge-code"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"challenge": "challenge-code"}


def test_internal_support_slack_event_accepts_project_secret_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_SLACK_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("SUPPORT_SLACK_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setattr(
        "automail.api.internal_support.load_runtime_secrets",
        lambda tenant_id, project_id: {"SUPPORT_SLACK_WEBHOOK_TOKEN": "stored-slack-token"}
        if (tenant_id, project_id) == ("tenant1", "project1")
        else {},
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "ignored": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_slack_event", fake_ingest)

    resp = client.post(
        "/api/internal/support/slack/slack-main",
        headers={"X-Support-Sync-Token": "stored-slack-token"},
        json={
            "tenantId": "tenant1",
            "projectId": "project1",
            "payload": {
                "team_id": "T123",
                "event": {"type": "message", "channel": "C123", "user": "U123", "ts": "1.0", "text": "Help"},
            },
        },
    )

    assert resp.status_code == 200
    assert resp.json()["issueId"] == "issue1"
    assert calls[0]["tenant_id"] == "tenant1"
    assert calls[0]["project_id"] == "project1"


def test_internal_support_slack_event_accepts_channel_token_key(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_SLACK_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("SUPPORT_SLACK_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setattr(
        "automail.api.internal_support.load_runtime_secrets",
        lambda tenant_id, project_id: {"ACME_SLACK_WEBHOOK_TOKEN": "stored-channel-token"}
        if (tenant_id, project_id) == ("tenant1", "project1")
        else {},
    )
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "slack",
            "config": {"webhookTokenEnv": "ACME_SLACK_WEBHOOK_TOKEN"},
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "ignored": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_slack_event", fake_ingest)

    resp = client.post(
        "/api/internal/support/slack/slack-main",
        headers={"X-Support-Sync-Token": "stored-channel-token"},
        json={
            "tenantId": "tenant1",
            "projectId": "project1",
            "payload": {
                "team_id": "T123",
                "event": {"type": "message", "channel": "C123", "user": "U123", "ts": "1.0", "text": "Help"},
            },
        },
    )

    assert resp.status_code == 200
    assert resp.json()["issueId"] == "issue1"
    assert calls[0]["channel_key"] == "slack-main"


def test_internal_support_slack_event_ingests_with_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_SLACK_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("SUPPORT_SLACK_WEBHOOK_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "secret-token")

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "ignored": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_slack_event", fake_ingest)

    resp = client.post(
        "/api/internal/support/slack/slack-main",
        headers={"X-Support-Sync-Token": "secret-token"},
        json={
            "tenantId": "tenant1",
            "projectId": "project1",
            "payload": {
                "team_id": "T123",
                "event": {"type": "message", "channel": "C123", "user": "U123", "ts": "1.0", "text": "Help"},
            },
        },
    )

    assert resp.status_code == 200
    assert resp.json()["issueId"] == "issue1"
    assert calls == [{
        "channel_key": "slack-main",
        "payload": {
            "team_id": "T123",
            "event": {"type": "message", "channel": "C123", "user": "U123", "ts": "1.0", "text": "Help"},
        },
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "slack-webhook",
    }]


def test_internal_support_slack_accepts_signed_request(client, monkeypatch):
    import hashlib
    import hmac
    import json
    import time

    monkeypatch.setenv("SUPPORT_SLACK_SIGNING_SECRET", "signing-secret")
    monkeypatch.delenv("SUPPORT_SLACK_WEBHOOK_TOKEN", raising=False)
    payload = {"type": "url_verification", "challenge": "signed-challenge"}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(
        b"signing-secret",
        f"v0:{timestamp}:".encode("utf-8") + raw,
        hashlib.sha256,
    ).hexdigest()

    resp = client.post(
        "/api/internal/support/slack/slack-main",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {"challenge": "signed-challenge"}


def test_internal_support_slack_accepts_channel_signed_request(client, monkeypatch):
    import hashlib
    import hmac
    import json
    import time

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_SLACK_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("SUPPORT_SLACK_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("ACME_SLACK_SIGNING_SECRET", "workspace-secret")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda *_args, **_kwargs: {
            "id": "channel1",
            "channelKey": "slack-main",
            "type": "slack",
            "config": {"slackSigningSecretEnv": "ACME_SLACK_SIGNING_SECRET"},
        },
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "ignored": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_slack_event", fake_ingest)

    payload = {
        "team_id": "T123",
        "event": {"type": "message", "channel": "C123", "user": "U123", "ts": "1.0", "text": "Help"},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(
        b"workspace-secret",
        f"v0:{timestamp}:".encode("utf-8") + raw,
        hashlib.sha256,
    ).hexdigest()

    bad = client.post(
        "/api/internal/support/slack/slack-main?project_id=project1",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": "v0=bad",
        },
    )
    good = client.post(
        "/api/internal/support/slack/slack-main?project_id=project1",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        },
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert good.json()["issueId"] == "issue1"
    assert calls == [{
        "channel_key": "slack-main",
        "payload": payload,
        "tenant_id": None,
        "project_id": "project1",
        "source": "slack-webhook",
    }]


def test_internal_support_teams_validation_token(client):
    resp = client.get("/api/internal/support/teams/teams-main?validationToken=teams-challenge")

    assert resp.status_code == 200
    assert resp.text == "teams-challenge"


def test_internal_support_teams_event_ingests_with_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_TEAMS_WEBHOOK_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "secret-token")

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "ignored": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_teams_event", fake_ingest)

    resp = client.post(
        "/api/internal/support/teams/teams-main",
        headers={"X-Support-Sync-Token": "secret-token"},
        json={
            "tenantId": "tenant1",
            "projectId": "project1",
            "payload": {
                "type": "message",
                "id": "msg-1",
                "text": "Need help",
                "conversation": {"id": "conv-1"},
            },
        },
    )

    assert resp.status_code == 200
    assert resp.json()["issueId"] == "issue1"
    assert calls == [{
        "channel_key": "teams-main",
        "payload": {
            "type": "message",
            "id": "msg-1",
            "text": "Need help",
            "conversation": {"id": "conv-1"},
        },
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "teams-webhook",
    }]


def test_internal_support_teams_event_accepts_channel_signature(client, monkeypatch):
    import hashlib
    import hmac
    import json

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_TEAMS_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_TEAMS_SIGNING_SECRET", "signing-secret")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "teams",
            "config": {
                "signatureSecretEnv": "SUPPORT_TEAMS_SIGNING_SECRET",
                "signatureHeader": "X-Teams-Signature",
            },
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "ignored": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_teams_event", fake_ingest)
    payload = {
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {
            "type": "message",
            "id": "msg-1",
            "text": "Need help",
            "conversation": {"id": "conv-1"},
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(b"signing-secret", raw, hashlib.sha256).hexdigest()

    bad = client.post(
        "/api/internal/support/teams/teams-main",
        content=raw,
        headers={"Content-Type": "application/json", "X-Teams-Signature": "sha256=bad"},
    )
    good = client.post(
        "/api/internal/support/teams/teams-main",
        content=raw,
        headers={"Content-Type": "application/json", "X-Teams-Signature": signature},
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert good.json()["issueId"] == "issue1"
    assert calls == [{
        "channel_key": "teams-main",
        "payload": {
            "type": "message",
            "id": "msg-1",
            "text": "Need help",
            "conversation": {"id": "conv-1"},
        },
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "teams-webhook",
    }]


def test_internal_support_teams_event_accepts_provider_signature_key(client, monkeypatch):
    import hashlib
    import hmac
    import json

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_TEAMS_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("ACME_TEAMS_SIGNING_SECRET", "teams-secret")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "teams",
            "config": {
                "teamsSigningSecretEnv": "ACME_TEAMS_SIGNING_SECRET",
                "signatureHeader": "X-Teams-Signature",
            },
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "ignored": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_teams_event", fake_ingest)
    payload = {
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {
            "type": "message",
            "id": "msg-1",
            "text": "Need help",
            "conversation": {"id": "conv-1"},
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(b"teams-secret", raw, hashlib.sha256).hexdigest()

    resp = client.post(
        "/api/internal/support/teams/teams-main",
        content=raw,
        headers={"Content-Type": "application/json", "X-Teams-Signature": signature},
    )

    assert resp.status_code == 200
    assert resp.json()["issueId"] == "issue1"
    assert calls[0]["channel_key"] == "teams-main"


def test_internal_support_discord_event_ingests_with_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_DISCORD_WEBHOOK_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "secret-token")

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)

    resp = client.post(
        "/api/internal/support/discord/discord-main",
        headers={"X-Support-Sync-Token": "secret-token"},
        json={
            "tenantId": "tenant1",
            "projectId": "project1",
            "payload": {
                "t": "MESSAGE_CREATE",
                "d": {
                    "id": "msg-1",
                    "channel_id": "chan-1",
                    "guild_id": "guild-1",
                    "content": "Need help",
                    "author": {"id": "user-1", "username": "Ana"},
                },
            },
        },
    )

    assert resp.status_code == 200
    assert resp.json()["issueId"] == "issue1"
    assert calls == [{
        "channel_key": "discord-main",
        "payload": {
            "t": "MESSAGE_CREATE",
            "d": {
                "id": "msg-1",
                "channel_id": "chan-1",
                "guild_id": "guild-1",
                "content": "Need help",
                "author": {"id": "user-1", "username": "Ana"},
            },
        },
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "discord-webhook",
    }]


def test_internal_support_discord_event_accepts_channel_signature(client, monkeypatch):
    import hashlib
    import hmac
    import json

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_DISCORD_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_DISCORD_SIGNING_SECRET", "signing-secret")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "discord",
            "config": {
                "signatureSecretEnv": "SUPPORT_DISCORD_SIGNING_SECRET",
                "signatureHeader": "X-Discord-Signature",
            },
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    payload = {
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {
            "t": "MESSAGE_CREATE",
            "d": {
                "id": "msg-1",
                "channel_id": "chan-1",
                "guild_id": "guild-1",
                "content": "Need help",
                "author": {"id": "user-1", "username": "Ana"},
            },
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(b"signing-secret", raw, hashlib.sha256).hexdigest()

    bad = client.post(
        "/api/internal/support/discord/discord-main",
        content=raw,
        headers={"Content-Type": "application/json", "X-Discord-Signature": "sha256=bad"},
    )
    good = client.post(
        "/api/internal/support/discord/discord-main",
        content=raw,
        headers={"Content-Type": "application/json", "X-Discord-Signature": signature},
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert calls == [{
        "channel_key": "discord-main",
        "payload": payload["payload"],
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "discord-webhook",
    }]


def test_internal_support_discord_event_accepts_provider_signature_key(client, monkeypatch):
    import hashlib
    import hmac
    import json

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_DISCORD_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("ACME_DISCORD_SIGNING_SECRET", "discord-secret")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "discord",
            "config": {
                "discordSigningSecretEnv": "ACME_DISCORD_SIGNING_SECRET",
                "signatureHeader": "X-Discord-Signature",
            },
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    payload = {
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {
            "t": "MESSAGE_CREATE",
            "d": {
                "id": "msg-1",
                "channel_id": "chan-1",
                "guild_id": "guild-1",
                "content": "Need help",
                "author": {"id": "user-1", "username": "Ana"},
            },
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(b"discord-secret", raw, hashlib.sha256).hexdigest()

    resp = client.post(
        "/api/internal/support/discord/discord-main",
        content=raw,
        headers={"Content-Type": "application/json", "X-Discord-Signature": signature},
    )

    assert resp.status_code == 200
    assert resp.json()["issueId"] == "issue1"
    assert calls[0]["channel_key"] == "discord-main"


def test_internal_support_telegram_event_ingests_with_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_TELEGRAM_WEBHOOK_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_SYNC_TOKEN", "secret-token")

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)

    resp = client.post(
        "/api/internal/support/telegram/telegram-main",
        headers={"X-Support-Sync-Token": "secret-token"},
        json={
            "tenantId": "tenant1",
            "projectId": "project1",
            "payload": {
                "update_id": 123,
                "message": {
                    "message_id": 456,
                    "chat": {"id": "chat-1", "title": "Customer chat"},
                    "from": {"id": "user-1", "first_name": "Ana"},
                    "text": "Need help",
                },
            },
        },
    )

    assert resp.status_code == 200
    assert resp.json()["issueId"] == "issue1"
    assert calls == [{
        "channel_key": "telegram-main",
        "payload": {
            "update_id": 123,
            "message": {
                "message_id": 456,
                "chat": {"id": "chat-1", "title": "Customer chat"},
                "from": {"id": "user-1", "first_name": "Ana"},
                "text": "Need help",
            },
        },
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "telegram-webhook",
    }]


def test_internal_support_telegram_event_accepts_secret_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_TELEGRAM_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_TELEGRAM_SECRET_TOKEN", "telegram-secret")

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    payload = {
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {
            "update_id": 123,
            "message": {
                "message_id": 456,
                "chat": {"id": "chat-1", "title": "Customer chat"},
                "from": {"id": "user-1", "first_name": "Ana"},
                "text": "Need help",
            },
        },
    }

    bad = client.post(
        "/api/internal/support/telegram/telegram-main",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        json=payload,
    )
    good = client.post(
        "/api/internal/support/telegram/telegram-main",
        headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-secret"},
        json=payload,
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert calls == [{
        "channel_key": "telegram-main",
        "payload": payload["payload"],
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "telegram-webhook",
    }]


def test_internal_support_telegram_event_accepts_channel_secret_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_TELEGRAM_SECRET_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_TELEGRAM_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("ACME_TELEGRAM_SECRET", "telegram-secret")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "telegram",
            "config": {"telegramSecretTokenEnv": "ACME_TELEGRAM_SECRET"},
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    payload = {
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {
            "update_id": 123,
            "message": {
                "message_id": 456,
                "chat": {"id": "chat-1", "title": "Customer chat"},
                "from": {"id": "user-1", "first_name": "Ana"},
                "text": "Need help",
            },
        },
    }

    bad = client.post(
        "/api/internal/support/telegram/telegram-main",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        json=payload,
    )
    good = client.post(
        "/api/internal/support/telegram/telegram-main",
        headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-secret"},
        json=payload,
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert calls == [{
        "channel_key": "telegram-main",
        "payload": payload["payload"],
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "telegram-webhook",
    }]


def test_internal_support_telegram_event_prefers_hmac_when_signing_secret_configured(client, monkeypatch):
    import hashlib
    import hmac
    import json

    calls: list[dict] = []
    monkeypatch.setenv("SUPPORT_TELEGRAM_SECRET_TOKEN", "telegram-secret")
    monkeypatch.setenv("ACME_TELEGRAM_SIGNING_SECRET", "signing-secret")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "telegram",
            "config": {"telegramSigningSecretEnv": "ACME_TELEGRAM_SIGNING_SECRET"},
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    payload = {
        "tenantId": "tenant1",
        "projectId": "project1",
        "payload": {
            "update_id": 123,
            "message": {
                "message_id": 456,
                "chat": {"id": "chat-1", "title": "Customer chat"},
                "from": {"id": "user-1", "first_name": "Ana"},
                "text": "Need help",
            },
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"signing-secret", raw, hashlib.sha256).hexdigest()

    token_only = client.post(
        "/api/internal/support/telegram/telegram-main",
        headers={"Content-Type": "application/json", "X-Telegram-Bot-Api-Secret-Token": "telegram-secret"},
        content=raw,
    )
    signed = client.post(
        "/api/internal/support/telegram/telegram-main",
        headers={"Content-Type": "application/json", "X-Support-Signature": f"sha256={signature}"},
        content=raw,
    )

    assert token_only.status_code == 401
    assert signed.status_code == 200
    assert calls == [{
        "channel_key": "telegram-main",
        "payload": payload["payload"],
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "telegram-webhook",
    }]


def test_internal_support_twilio_event_ingests_form_with_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setenv("SUPPORT_TWILIO_WEBHOOK_TOKEN", "twilio-token")

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)

    resp = client.post(
        "/api/internal/support/twilio/sms-main?tenant_id=tenant1&project_id=project1",
        data={
            "MessageSid": "SM123",
            "AccountSid": "AC123",
            "From": "+15551234567",
            "To": "+15550001111",
            "Body": "Need help by SMS",
            "NumMedia": "0",
            "SmsStatus": "received",
        },
        headers={"X-Support-Sync-Token": "twilio-token"},
    )

    assert resp.status_code == 200
    assert calls == [{
        "channel_key": "sms-main",
        "payload": {
            "MessageSid": "SM123",
            "AccountSid": "AC123",
            "From": "+15551234567",
            "To": "+15550001111",
            "Body": "Need help by SMS",
            "NumMedia": "0",
            "SmsStatus": "received",
        },
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "twilio-webhook",
    }]


def test_internal_support_sms_alias_ingests_form_with_token(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setenv("SUPPORT_TWILIO_WEBHOOK_TOKEN", "twilio-token")

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)

    resp = client.post(
        "/api/internal/support/sms/sms-main?tenant_id=tenant1&project_id=project1",
        data={
            "MessageSid": "SM123",
            "AccountSid": "AC123",
            "From": "+15551234567",
            "To": "+15550001111",
            "Body": "Need help by SMS",
            "NumMedia": "0",
            "SmsStatus": "received",
        },
        headers={"X-Support-Sync-Token": "twilio-token"},
    )

    assert resp.status_code == 200
    assert calls == [{
        "channel_key": "sms-main",
        "payload": {
            "MessageSid": "SM123",
            "AccountSid": "AC123",
            "From": "+15551234567",
            "To": "+15550001111",
            "Body": "Need help by SMS",
            "NumMedia": "0",
            "SmsStatus": "received",
        },
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "twilio-webhook",
    }]


def test_internal_support_messenger_event_accepts_meta_signature(client, monkeypatch):
    import hashlib
    import hmac

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_MESSENGER_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_MESSENGER_APP_SECRET", "messenger-app-secret")
    monkeypatch.setenv("SUPPORT_MESSENGER_VERIFY_TOKEN", "messenger-verify")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "messenger",
            "config": {
                "messengerSigningSecretEnv": "SUPPORT_MESSENGER_APP_SECRET",
                "messengerVerifyTokenEnv": "SUPPORT_MESSENGER_VERIFY_TOKEN",
            },
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    verify = client.get(
        "/api/internal/support/messenger/messenger-main"
        "?tenant_id=tenant1&project_id=project1&hub.mode=subscribe&hub.verify_token=messenger-verify&hub.challenge=abc123"
    )
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-1",
                "messaging": [
                    {
                        "sender": {"id": "psid-1"},
                        "recipient": {"id": "page-1"},
                        "timestamp": 1710000000000,
                        "message": {"mid": "m_customer_1", "text": "Need help"},
                    }
                ],
            }
        ],
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"messenger-app-secret", raw, hashlib.sha256).hexdigest()

    bad = client.post(
        "/api/internal/support/messenger/messenger-main?tenant_id=tenant1&project_id=project1",
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=bad"},
        content=raw,
    )
    good = client.post(
        "/api/internal/support/messenger/messenger-main?tenant_id=tenant1&project_id=project1",
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={signature}"},
        content=raw,
    )

    assert verify.status_code == 200
    assert verify.text == "abc123"
    assert bad.status_code == 401
    assert good.status_code == 200
    assert calls == [{
        "channel_key": "messenger-main",
        "payload": payload,
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "messenger-webhook",
    }]


def test_internal_support_instagram_event_accepts_meta_signature(client, monkeypatch):
    import hashlib
    import hmac

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_INSTAGRAM_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_INSTAGRAM_APP_SECRET", "instagram-app-secret")
    monkeypatch.setenv("SUPPORT_INSTAGRAM_VERIFY_TOKEN", "instagram-verify")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "instagram",
            "config": {
                "instagramSigningSecretEnv": "SUPPORT_INSTAGRAM_APP_SECRET",
                "instagramVerifyTokenEnv": "SUPPORT_INSTAGRAM_VERIFY_TOKEN",
            },
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    verify = client.get(
        "/api/internal/support/instagram/instagram-main"
        "?tenant_id=tenant1&project_id=project1&hub.mode=subscribe&hub.verify_token=instagram-verify&hub.challenge=abc123"
    )
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "ig-1",
                "messaging": [
                    {
                        "sender": {"id": "igid-1"},
                        "recipient": {"id": "ig-1"},
                        "timestamp": 1710000000000,
                        "message": {"mid": "ig_mid_customer_1", "text": "Need help"},
                    }
                ],
            }
        ],
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"instagram-app-secret", raw, hashlib.sha256).hexdigest()

    bad = client.post(
        "/api/internal/support/instagram/instagram-main?tenant_id=tenant1&project_id=project1",
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=bad"},
        content=raw,
    )
    good = client.post(
        "/api/internal/support/instagram/instagram-main?tenant_id=tenant1&project_id=project1",
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={signature}"},
        content=raw,
    )

    assert verify.status_code == 200
    assert verify.text == "abc123"
    assert bad.status_code == 401
    assert good.status_code == 200
    assert calls == [{
        "channel_key": "instagram-main",
        "payload": payload,
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "instagram-webhook",
    }]


def test_internal_support_twitter_event_accepts_crc_and_signature(client, monkeypatch):
    import base64
    import hashlib
    import hmac

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_X_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_X_CONSUMER_SECRET", "twitter-consumer-secret")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "twitter",
            "config": {"twitterConsumerSecretEnv": "SUPPORT_X_CONSUMER_SECRET"},
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    verify = client.get(
        "/api/internal/support/twitter/twitter-main"
        "?tenant_id=tenant1&project_id=project1&crc_token=challenge-token"
    )
    expected_crc = base64.b64encode(
        hmac.new(b"twitter-consumer-secret", b"challenge-token", hashlib.sha256).digest()
    ).decode("ascii")
    payload = {
        "for_user_id": "4337869213",
        "direct_message_events": [
            {
                "type": "message_create",
                "id": "954491830116155396",
                "created_timestamp": "1516403560557",
                "message_create": {
                    "target": {"recipient_id": "4337869213"},
                    "sender_id": "3001969357",
                    "message_data": {"text": "Need help"},
                },
            }
        ],
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = base64.b64encode(hmac.new(b"twitter-consumer-secret", raw, hashlib.sha256).digest()).decode("ascii")

    bad = client.post(
        "/api/internal/support/twitter/twitter-main?tenant_id=tenant1&project_id=project1",
        headers={"Content-Type": "application/json", "x-twitter-webhooks-signature": "sha256=bad"},
        content=raw,
    )
    good = client.post(
        "/api/internal/support/twitter/twitter-main?tenant_id=tenant1&project_id=project1",
        headers={"Content-Type": "application/json", "x-twitter-webhooks-signature": f"sha256={signature}"},
        content=raw,
    )

    assert verify.status_code == 200
    assert verify.json() == {"response_token": f"sha256={expected_crc}"}
    assert bad.status_code == 401
    assert good.status_code == 200
    assert calls == [{
        "channel_key": "twitter-main",
        "payload": payload,
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "twitter-webhook",
    }]


def test_internal_support_line_event_accepts_line_signature(client, monkeypatch):
    import base64
    import hashlib
    import hmac

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_LINE_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_LINE_CHANNEL_SECRET", "line-channel-secret")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "line",
            "config": {"lineChannelSecretEnv": "SUPPORT_LINE_CHANNEL_SECRET"},
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    payload = {
        "destination": "line-bot-user-id",
        "events": [
            {
                "type": "message",
                "timestamp": 1710000000000,
                "webhookEventId": "line-event-1",
                "replyToken": "line-reply-token",
                "source": {"type": "user", "userId": "line-user-id"},
                "message": {"id": "line-message-1", "type": "text", "text": "Need help"},
            }
        ],
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = base64.b64encode(hmac.new(b"line-channel-secret", raw, hashlib.sha256).digest()).decode("ascii")

    bad = client.post(
        "/api/internal/support/line/line-main?tenant_id=tenant1&project_id=project1",
        headers={"Content-Type": "application/json", "X-Line-Signature": "bad"},
        content=raw,
    )
    good = client.post(
        "/api/internal/support/line/line-main?tenant_id=tenant1&project_id=project1",
        headers={"Content-Type": "application/json", "X-Line-Signature": signature},
        content=raw,
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert calls == [{
        "channel_key": "line-main",
        "payload": payload,
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "line-webhook",
    }]


def test_internal_support_viber_event_accepts_content_signature(client, monkeypatch):
    import hashlib
    import hmac

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_VIBER_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_VIBER_AUTH_TOKEN", "viber-auth-token")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "viber",
            "config": {"viberAuthTokenEnv": "SUPPORT_VIBER_AUTH_TOKEN"},
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    payload = {
        "event": "message",
        "timestamp": 1710000000000,
        "message_token": 491266184665523145,
        "sender": {"id": "viber-user-id", "name": "Customer"},
        "message": {"type": "text", "text": "Need help"},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"viber-auth-token", raw, hashlib.sha256).hexdigest()

    bad = client.post(
        "/api/internal/support/viber/viber-main?tenant_id=tenant1&project_id=project1",
        headers={"Content-Type": "application/json", "X-Viber-Content-Signature": "bad"},
        content=raw,
    )
    good = client.post(
        "/api/internal/support/viber/viber-main?tenant_id=tenant1&project_id=project1",
        headers={"Content-Type": "application/json", "X-Viber-Content-Signature": signature},
        content=raw,
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert calls == [{
        "channel_key": "viber-main",
        "payload": payload,
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "viber-webhook",
    }]


def test_internal_support_twilio_event_accepts_native_signature(client, monkeypatch):
    import base64
    import hashlib
    import hmac

    calls: list[dict] = []
    monkeypatch.delenv("SUPPORT_TWILIO_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("SUPPORT_TWILIO_AUTH_TOKEN", "twilio-auth-token")
    monkeypatch.setattr(
        "automail.api.internal_support.get_channel_by_key",
        lambda channel_key, **kwargs: {
            "id": "channel1",
            "channelKey": channel_key,
            "type": "sms",
            "config": {
                "authTokenEnv": "SUPPORT_TWILIO_AUTH_TOKEN",
            },
        } if kwargs == {"tenant_id": "tenant1", "project_id": "project1"} else None,
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.internal_support.ingest_channel_webhook", fake_ingest)
    url = "http://testserver/api/internal/support/twilio/sms-main?tenant_id=tenant1&project_id=project1"
    payload = {
        "MessageSid": "SM123",
        "AccountSid": "AC123",
        "From": "+15551234567",
        "To": "+15550001111",
        "Body": "Need help by SMS",
        "NumMedia": "0",
        "SmsStatus": "received",
    }
    signed = url + "".join(f"{key}{value}" for key, value in sorted(payload.items()))
    signature = base64.b64encode(
        hmac.new(b"twilio-auth-token", signed.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")

    bad = client.post(url, data=payload, headers={"X-Twilio-Signature": "bad"})
    good = client.post(url, data=payload, headers={"X-Twilio-Signature": signature})

    assert bad.status_code == 401
    assert good.status_code == 200
    assert calls == [{
        "channel_key": "sms-main",
        "payload": payload,
        "tenant_id": "tenant1",
        "project_id": "project1",
        "source": "twilio-webhook",
    }]


def test_admin_issue_agent_answer_prepares_draft(client, monkeypatch):
    calls: list[dict] = []

    def fake_prepare(issue_id: str, **kwargs):
        calls.append({"issue_id": issue_id, **kwargs})
        return {
            "answer": "Suggested answer",
            "confidence": "high",
            "citations": [],
            "reply": {"id": "reply1", "status": "draft"},
            "approvalRequired": True,
        }

    monkeypatch.setattr("automail.api.admin.issues.create_issue_agent_answer", fake_prepare)

    resp = client.post(
        "/api/admin/projects/project1/issues/issue1/agent-answer",
        json={"question": "What do we say?", "createDraft": True, "includeFeedbackLink": True},
    )

    assert resp.status_code == 200
    assert resp.json()["answer"] == "Suggested answer"
    assert calls == [{
        "issue_id": "issue1",
        "tenant_id": "",
        "project_id": "project1",
        "author_email": "",
        "question": "What do we say?",
        "create_draft": True,
        "include_feedback_link": True,
        "approval_required": True,
        "auto_send": False,
        "use_knowledge_agent": True,
        "knowledge_actor_role": "automation",
    }]


def test_admin_issue_create_manual_ticket(client, monkeypatch):
    calls: list[dict] = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return {"id": "issue1", "subject": kwargs["subject"], "channel": "email", "source": "admin_inbox"}

    monkeypatch.setattr("automail.api.admin.issues.create_manual_issue", fake_create)

    resp = client.post(
        "/api/admin/projects/project1/issues",
        json={
            "subject": "Manual request",
            "fromAddress": "ana@example.com",
            "contactName": "Ana",
            "body": "Please help.",
            "priority": "high",
            "assigneeEmail": "agent@example.com",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == "issue1"
    assert calls == [{
        "tenant_id": "",
        "project_id": "project1",
        "creator_email": "",
        "subject": "Manual request",
        "from_address": "ana@example.com",
        "body": "Please help.",
        "account_id": "",
        "contact_id": "",
        "contact_name": "Ana",
        "account_name": "",
        "priority": "high",
        "assignee_email": "agent@example.com",
        "queue_key": "",
        "queue_name": "",
    }]


def test_admin_issue_create_defaults_assignee_to_editor(monkeypatch):
    calls: list[dict] = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return {"id": "issue1", "assigneeEmail": kwargs["assignee_email"]}

    monkeypatch.setattr("automail.api.admin.issues.create_manual_issue", fake_create)

    result = asyncio.run(
        admin_issue_api.create_issue(
            admin_issue_api.IssueCreate(
                subject="Manual request",
                fromAddress="ana@example.com",
                body="Please help.",
            ),
            SimpleNamespace(tenant_id="tenant1", project_id="project1"),
            SimpleNamespace(email="Agent@Example.com"),
        )
    )

    assert result["assigneeEmail"] == "agent@example.com"
    assert calls[0]["creator_email"] == "Agent@Example.com"
    assert calls[0]["assignee_email"] == "agent@example.com"


def test_admin_automation_preview_routes_scope(client, monkeypatch):
    calls: list[dict] = []

    def fake_preview(issue_id: str, **kwargs):
        calls.append({"issue_id": issue_id, **kwargs})
        return {
            "issueId": issue_id,
            "trigger": kwargs["trigger"],
            "rules": 1,
            "matched": 1,
            "items": [
                {
                    "rule": {"id": "rule1", "name": "Autopilot"},
                    "matched": True,
                    "conditions": {"requiresHuman": True},
                    "actions": [{"type": "assign", "status": "would_run", "assigneeEmail": "agent@example.com"}],
                }
            ],
        }

    monkeypatch.setattr("automail.api.admin.automations.preview_automation_rules_for_issue", fake_preview)

    resp = client.post(
        "/api/admin/projects/project1/automations/preview",
        json={"issueId": "issue1", "trigger": "issue_created"},
    )

    assert resp.status_code == 200
    assert resp.json()["matched"] == 1
    assert calls == [{
        "issue_id": "issue1",
        "tenant_id": "",
        "project_id": "project1",
        "trigger": "issue_created",
        "preview_rule": None,
    }]

    calls.clear()
    resp = client.post(
        "/api/admin/projects/project1/automations/preview",
        json={
            "issueId": "issue1",
            "trigger": "manual",
            "previewRule": {
                "name": "Current draft",
                "active": True,
                "trigger": "manual",
                "conditions": {"requiresHuman": True},
                "actions": [{"type": "assign", "assigneeEmail": "lead@example.com"}],
            },
        },
    )

    assert resp.status_code == 200
    assert calls == [{
        "issue_id": "issue1",
        "tenant_id": "",
        "project_id": "project1",
        "trigger": "manual",
        "preview_rule": {
            "name": "Current draft",
            "active": True,
            "trigger": "manual",
            "conditions": {"requiresHuman": True},
            "actions": [{"type": "assign", "assigneeEmail": "lead@example.com"}],
        },
    }]


def test_admin_automation_backlog_run_routes_scope(client, monkeypatch):
    calls: list[dict] = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {
            "issues": 2,
            "processed": 1,
            "failed": 0,
            "skipped": 1,
            "runs": 1,
            "items": [{"issueId": "issue1", "processed": 1, "failed": 0, "skipped": False, "items": []}],
        }

    monkeypatch.setattr("automail.api.admin.automations.run_automation_rules_for_backlog", fake_run)

    resp = client.post(
        "/api/admin/projects/project1/automations/run/backlog",
        json={"trigger": "issue_created", "status": "open", "queueKey": "support", "limit": 50},
    )

    assert resp.status_code == 200
    assert resp.json()["processed"] == 1
    assert calls == [{
        "tenant_id": "",
        "project_id": "project1",
        "trigger": "issue_created",
        "status": "open",
        "queue_key": "support",
        "limit": 50,
        "actor_email": "",
    }]


def test_admin_knowledge_gap_create_article_routes_scope(client, monkeypatch):
    calls: list[dict] = []

    def fake_create(gap_id: str, **kwargs):
        calls.append({"gap_id": gap_id, **kwargs})
        return {
            "id": "article1",
            "title": "API outage runbook",
            "body": "Use status page.",
            "status": kwargs["status"],
            "sourceIssueId": "issue1",
            "tags": ["support-gap"],
        }

    monkeypatch.setattr("automail.api.admin.knowledge.create_knowledge_article_from_gap", fake_create)

    resp = client.post(
        "/api/admin/projects/project1/knowledge/gaps/gap1/article",
        json={"status": "draft"},
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == "article1"
    assert calls == [{
        "gap_id": "gap1",
        "tenant_id": "",
        "project_id": "project1",
        "status": "draft",
        "actor_email": "",
        "actor_role": "root",
    }]


def test_admin_knowledge_article_create_routes_source_metadata(client, monkeypatch):
    calls: list[dict] = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return {
            "id": "article1",
            "title": kwargs["title"],
            "body": kwargs["body"],
            "status": kwargs["status"],
            "sourceIssueId": kwargs["source_issue_id"],
            "sourceUrl": kwargs["source_url"],
            "visibility": kwargs["visibility"],
            "public": kwargs["visibility"] == "public",
            "tags": kwargs["tags"],
        }

    monkeypatch.setattr("automail.api.admin.knowledge.create_knowledge_article", fake_create)

    resp = client.post(
        "/api/admin/projects/project1/knowledge",
        json={
            "title": "Reset password",
            "body": "Use the reset link.",
            "status": "published",
            "sourceIssueId": "issue1",
            "sourceUrl": "https://docs.example.com/reset",
            "visibility": "internal",
            "tags": ["auth"],
        },
    )

    assert resp.status_code == 200
    assert resp.json()["sourceUrl"] == "https://docs.example.com/reset"
    assert calls == [{
        "tenant_id": "",
        "project_id": "project1",
        "title": "Reset password",
        "body": "Use the reset link.",
        "status": "published",
        "source_issue_id": "issue1",
        "source_gap_id": "",
        "source_url": "https://docs.example.com/reset",
        "visibility": "internal",
        "automation_allowed": None,
        "tags": ["auth"],
        "actor_email": "",
    }]


def test_admin_issue_by_chat_returns_linked_ticket(client, monkeypatch):
    calls: list[dict] = []

    def fake_get(chat_id: str, **kwargs):
        calls.append({"chat_id": chat_id, **kwargs})
        return {
            "id": "issue1",
            "chatId": chat_id,
            "subject": "Shipment blocked",
            "status": "open",
            "workflowStatus": "open",
            "priority": "high",
            "assigneeEmail": "agent@example.com",
            "pendingApprovalCount": 1,
            "hasPendingApproval": True,
        }

    monkeypatch.setattr("automail.api.admin.issues.get_issue_by_chat_id", fake_get)

    resp = client.get("/api/admin/projects/project1/issues/by-chat/gmail%3Amsg-123")

    assert resp.status_code == 200
    assert resp.json()["id"] == "issue1"
    assert resp.json()["chatId"] == "gmail:msg-123"
    assert resp.json()["pendingApprovalCount"] == 1
    assert calls == [{
        "chat_id": "gmail:msg-123",
        "tenant_id": "",
        "project_id": "project1",
        "actor_email": "",
        "actor_role": "root",
    }]


def test_admin_support_schema_health_returns_runtime_status(client, monkeypatch):
    calls: list[bool] = []

    def fake_health() -> dict:
        calls.append(True)
        return {
            "status": "missing",
            "ready": False,
            "requiredCollections": 2,
            "presentCollections": 1,
            "missingCollections": ["support_messages"],
            "items": [
                {"name": "support_issues", "exists": True, "error": ""},
                {"name": "support_messages", "exists": False, "error": "not found"},
            ],
        }

    monkeypatch.setattr("automail.api.admin.support_settings.support_schema_health", fake_health)

    resp = client.get("/api/admin/projects/project1/support/schema-health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "missing"
    assert resp.json()["missingCollections"] == ["support_messages"]
    assert calls == [True]


def test_admin_support_launch_proof_returns_runtime_artifact(client, monkeypatch):
    calls: list[dict[str, str | None]] = []

    def fake_launch_proof(*, tenant_id: str | None, project_id: str) -> dict:
        calls.append({"tenant_id": tenant_id, "project_id": project_id})
        return {
            "status": "blocked",
            "schema": {"ready": True},
            "channels": {
                "total": 1,
                "active": 1,
                "required": 1,
                "ready": 0,
                "blocked": 1,
                "items": [],
            },
            "blockers": [{"key": "channel_lifecycle_smoke_missing", "label": "Missing lifecycle", "count": 1}],
            "checkedAt": "2026-07-03T10:00:00Z",
        }

    monkeypatch.setattr("automail.api.admin.support_analytics.support_launch_proof", fake_launch_proof)

    resp = client.get("/api/admin/projects/project1/support/launch-proof")

    assert resp.status_code == 200
    assert resp.json()["status"] == "blocked"
    assert resp.json()["channels"]["blocked"] == 1
    assert resp.json()["blockers"][0]["key"] == "channel_lifecycle_smoke_missing"
    assert calls == [{"tenant_id": "", "project_id": "project1"}]


def test_admin_account_create_insight_routes_scope(client, monkeypatch):
    calls: list[dict] = []

    def fake_create(account_id: str, **kwargs):
        calls.append({"account_id": account_id, **kwargs})
        return {
            "id": "insight1",
            "accountId": account_id,
            "type": kwargs["insight_type"],
            "title": kwargs["title"],
            "body": kwargs["body"],
            "severity": kwargs["severity"],
            "status": kwargs["status"],
            "metadata": kwargs["metadata"],
        }

    monkeypatch.setattr("automail.api.admin.accounts.create_account_insight", fake_create)

    resp = client.post(
        "/api/admin/projects/project1/accounts/account1/insights",
        json={
            "type": "feature_request",
            "title": "API export",
            "body": "Customer needs CSV export.",
            "severity": "info",
            "status": "open",
            "metadata": {"owner": "product"},
        },
    )

    assert resp.status_code == 200
    assert resp.json()["title"] == "API export"
    assert calls == [{
        "account_id": "account1",
        "tenant_id": "",
        "project_id": "project1",
        "insight_type": "feature_request",
        "title": "API export",
        "body": "Customer needs CSV export.",
        "severity": "info",
        "status": "open",
        "source_issue_id": "",
        "insight_key": "",
        "metadata": {"owner": "product"},
    }]


def test_admin_issue_bulk_update_routes_each_ticket(client, monkeypatch):
    calls: list[dict] = []

    def fake_update(issue_id: str, **kwargs):
        calls.append({"issue_id": issue_id, **kwargs})
        return {
            "id": issue_id,
            "status": kwargs["updates"]["status"],
            "assigneeEmail": kwargs["updates"]["assignee_email"],
            "tags": kwargs["updates"]["tags"],
        }

    monkeypatch.setattr("automail.api.admin.issues.update_issue", fake_update)

    resp = client.post(
        "/api/admin/projects/project1/issues/bulk-update",
        json={
            "issueIds": ["issue1", "issue2"],
            "status": "ongoing",
            "assigneeEmail": "agent@example.com",
            "tags": ["vip", "billing"],
        },
    )

    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()["items"]] == ["issue1", "issue2"]
    assert resp.json()["failed"] == []
    assert calls == [
        {
            "issue_id": "issue1",
            "tenant_id": "",
            "project_id": "project1",
            "updates": {
                "status": "ongoing",
                "assignee_email": "agent@example.com",
                "tags": ["vip", "billing"],
                "assigned_by": "",
                "run_automations": True,
            },
        },
        {
            "issue_id": "issue2",
            "tenant_id": "",
            "project_id": "project1",
            "updates": {
                "status": "ongoing",
                "assignee_email": "agent@example.com",
                "tags": ["vip", "billing"],
                "assigned_by": "",
                "run_automations": True,
            },
        },
    ]


def test_admin_issue_merge_routes_to_target(client, monkeypatch):
    calls: list[dict] = []

    def fake_merge(source_issue_id: str, **kwargs):
        calls.append({"source_issue_id": source_issue_id, **kwargs})
        return {"id": kwargs["target_issue_id"], "subject": "Target ticket"}

    monkeypatch.setattr("automail.api.admin.issues.merge_issues", fake_merge)

    resp = client.post(
        "/api/admin/projects/project1/issues/source1/merge",
        json={"targetIssueId": "target1", "note": "Duplicate"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"id": "target1", "subject": "Target ticket"}
    assert calls == [{
        "source_issue_id": "source1",
        "target_issue_id": "target1",
        "tenant_id": "",
        "project_id": "project1",
        "actor_email": "",
        "note": "Duplicate",
    }]


def test_admin_issue_duplicate_suggestions_route(client, monkeypatch):
    calls: list[dict] = []

    monkeypatch.setattr(
        "automail.api.admin.issues.get_issue",
        lambda issue_id, **_kwargs: {"id": issue_id},
    )

    def fake_suggest(issue_id: str, **kwargs):
        calls.append({"issue_id": issue_id, **kwargs})
        return [{"issue": {"id": "target1"}, "score": 92, "reasons": ["same contact"]}]

    monkeypatch.setattr("automail.api.admin.issues.suggest_issue_duplicates", fake_suggest)

    resp = client.get("/api/admin/projects/project1/issues/source1/duplicate-suggestions?limit=3")

    assert resp.status_code == 200
    assert resp.json()["items"] == [{"issue": {"id": "target1"}, "score": 92, "reasons": ["same contact"]}]
    assert calls == [{
        "issue_id": "source1",
        "tenant_id": "",
        "project_id": "project1",
        "limit": 3,
    }]


def test_admin_issue_bulk_add_labels_merges_existing_tags(client, monkeypatch):
    updates: list[dict] = []

    def fake_get_issue(issue_id: str, **_kwargs):
        if issue_id == "issue1":
            return {"id": issue_id, "tags": ["vip", "billing"]}
        if issue_id == "issue2":
            return {"id": issue_id, "tags": ["support"]}
        return None

    def fake_update(issue_id: str, **kwargs):
        updates.append({"issue_id": issue_id, **kwargs})
        return {"id": issue_id, "tags": kwargs["updates"]["tags"]}

    monkeypatch.setattr("automail.api.admin.issues.get_issue", fake_get_issue)
    monkeypatch.setattr("automail.api.admin.issues.update_issue", fake_update)

    resp = client.post(
        "/api/admin/projects/project1/issues/labels/bulk-add",
        json={"issueIds": ["issue1", "issue2"], "tags": ["Billing", "vip", "enterprise"]},
    )

    assert resp.status_code == 200
    assert resp.json()["items"] == [
        {"id": "issue1", "tags": ["vip", "billing", "enterprise"]},
        {"id": "issue2", "tags": ["support", "Billing", "vip", "enterprise"]},
    ]
    assert [call["updates"]["tags"] for call in updates] == [
        ["vip", "billing", "enterprise"],
        ["support", "Billing", "vip", "enterprise"],
    ]
    assert all(call["updates"]["actor_email"] == "" for call in updates)
    assert all(call["updates"]["run_automations"] is True for call in updates)


def test_admin_issue_bulk_remove_labels_preserves_unmatched_tags(client, monkeypatch):
    updates: list[dict] = []

    monkeypatch.setattr(
        "automail.api.admin.issues.get_issue",
        lambda issue_id, **_kwargs: {"id": issue_id, "tags": ["vip", "billing", "support"]},
    )

    def fake_update(issue_id: str, **kwargs):
        updates.append({"issue_id": issue_id, **kwargs})
        return {"id": issue_id, "tags": kwargs["updates"]["tags"]}

    monkeypatch.setattr("automail.api.admin.issues.update_issue", fake_update)

    resp = client.post(
        "/api/admin/projects/project1/issues/labels/bulk-remove",
        json={"issueIds": ["issue1"], "tags": ["VIP", "missing"]},
    )

    assert resp.status_code == 200
    assert resp.json()["items"] == [{"id": "issue1", "tags": ["billing", "support"]}]
    assert updates[0]["updates"]["tags"] == ["billing", "support"]


def test_admin_issue_patch_returns_close_blocker(client, monkeypatch):
    def fake_update(*_args, **_kwargs):
        raise ValueError("Cannot close ticket until pending approvals are resolved")

    monkeypatch.setattr("automail.api.admin.issues.update_issue", fake_update)

    resp = client.patch(
        "/api/admin/projects/project1/issues/issue1",
        json={"status": "done"},
    )

    assert resp.status_code == 400
    assert "pending approvals" in resp.json()["detail"]


def test_admin_inbox_views_routes_scope_and_owner(client, monkeypatch):
    calls: list[dict] = []

    def fake_list(**kwargs):
        calls.append({"fn": "list", **kwargs})
        return [{"id": "view1", "name": "VIP", "filters": {"tagFilter": "vip"}}]

    def fake_upsert(**kwargs):
        calls.append({"fn": "upsert", **kwargs})
        return {"id": kwargs["view_id"] or "view1", "name": kwargs["name"], "filters": kwargs["filters"]}

    def fake_delete(view_id: str, **kwargs):
        calls.append({"fn": "delete", "view_id": view_id, **kwargs})
        return True

    monkeypatch.setattr("automail.api.admin.issues.list_inbox_views", fake_list)
    monkeypatch.setattr("automail.api.admin.issues.upsert_inbox_view", fake_upsert)
    monkeypatch.setattr("automail.api.admin.issues.delete_inbox_view", fake_delete)

    list_resp = client.get("/api/admin/projects/project1/support/inbox-views")
    save_resp = client.post(
        "/api/admin/projects/project1/support/inbox-views",
        json={
            "name": "VIP",
            "visibility": "shared",
            "filters": {
                "statusFilter": "open",
                "queueFilter": "support",
                "tagFilter": "vip",
                "query": "billing",
                "viewMode": "board",
            },
            "sortOrder": 7,
        },
    )
    delete_resp = client.delete("/api/admin/projects/project1/support/inbox-views/view1")

    assert list_resp.status_code == 200
    assert list_resp.json()["items"][0]["name"] == "VIP"
    assert save_resp.status_code == 200
    assert save_resp.json()["filters"]["tagFilter"] == "vip"
    assert delete_resp.status_code == 200
    assert delete_resp.json() == {"status": "deleted"}
    assert calls == [
        {"fn": "list", "tenant_id": "", "project_id": "project1", "owner_email": ""},
        {
            "fn": "upsert",
            "tenant_id": "",
            "project_id": "project1",
            "owner_email": "",
            "view_id": "",
            "name": "VIP",
            "visibility": "shared",
            "filters": {
                "statusFilter": "open",
                "queueFilter": "support",
                "tagFilter": "vip",
                "query": "billing",
                "viewMode": "board",
            },
            "sort_order": 7,
        },
        {"fn": "delete", "view_id": "view1", "tenant_id": "", "project_id": "project1", "owner_email": ""},
    ]


def test_admin_reply_macros_routes_scope_and_owner(client, monkeypatch):
    calls: list[dict] = []

    def fake_list(**kwargs):
        calls.append({"fn": "list", **kwargs})
        return [
            {
                "id": "macro1",
                "title": "Billing",
                "body": "Hello",
                "visibility": "shared",
                "ownerEmail": "",
                "status": "active",
                "tags": ["billing"],
                "metadata": {},
            }
        ]

    def fake_upsert(**kwargs):
        calls.append({"fn": "upsert", **kwargs})
        return {
            "id": kwargs["macro_id"] or "macro2",
            "title": kwargs["title"],
            "body": kwargs["body"],
            "visibility": kwargs["visibility"],
            "status": kwargs["status"],
            "tags": kwargs["tags"] or [],
        }

    def fake_archive(macro_id: str, **kwargs):
        calls.append({"fn": "archive", "macro_id": macro_id, **kwargs})
        return {"id": macro_id, "status": "archived"}

    monkeypatch.setattr("automail.api.admin.issues.list_reply_macros", fake_list)
    monkeypatch.setattr("automail.api.admin.issues.upsert_reply_macro", fake_upsert)
    monkeypatch.setattr("automail.api.admin.issues.archive_reply_macro", fake_archive)

    list_resp = client.get("/api/admin/projects/project1/support/reply-macros?status=active")
    save_resp = client.post(
        "/api/admin/projects/project1/support/reply-macros",
        json={"title": "Billing", "body": "Hello", "visibility": "shared", "tags": ["billing"]},
    )
    delete_resp = client.delete("/api/admin/projects/project1/support/reply-macros/macro2")

    assert list_resp.status_code == 200
    assert list_resp.json()["items"][0]["title"] == "Billing"
    assert save_resp.status_code == 200
    assert save_resp.json()["id"] == "macro2"
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "archived"
    assert calls == [
        {
            "fn": "list",
            "tenant_id": "",
            "project_id": "project1",
            "owner_email": "",
            "status": "active",
            "limit": 200,
        },
        {
            "fn": "upsert",
            "tenant_id": "",
            "project_id": "project1",
            "owner_email": "",
            "macro_id": "",
            "title": "Billing",
            "body": "Hello",
            "visibility": "shared",
            "status": "active",
            "tags": ["billing"],
            "metadata": None,
        },
        {
            "fn": "archive",
            "macro_id": "macro2",
            "tenant_id": "",
            "project_id": "project1",
            "owner_email": "",
        },
    ]


def test_admin_issue_reply_approve_records_editor(client, monkeypatch):
    calls: list[dict] = []

    def fake_approve(issue_id: str, reply_id: str, **kwargs):
        calls.append({"issue_id": issue_id, "reply_id": reply_id, **kwargs})
        return {
            "id": reply_id,
            "status": "draft",
            "metadata": {"approvalRequired": False, "approved": True, "reviewStatus": "approved"},
        }

    monkeypatch.setattr("automail.api.admin.issues.approve_issue_reply_record", fake_approve)
    monkeypatch.setattr(
        "automail.api.admin.issues.get_issue",
        lambda *_args, **_kwargs: {
            "id": "issue1",
            "outboundMessages": [{"id": "reply1", "metadata": {}}],
        },
    )

    resp = client.post(
        "/api/admin/projects/project1/issues/issue1/replies/reply1/approve",
        json={},
    )

    assert resp.status_code == 200
    assert resp.json()["metadata"]["approved"] is True
    assert resp.json()["metadata"]["reviewStatus"] == "approved"
    assert calls == [{
        "issue_id": "issue1",
        "reply_id": "reply1",
        "tenant_id": "",
        "project_id": "project1",
        "approved_by": "",
    }]


def test_admin_issue_reply_create_can_require_approval(client, monkeypatch):
    calls: list[dict] = []

    def fake_create(issue_id: str, **kwargs):
        calls.append({"issue_id": issue_id, **kwargs})
        return {
            "id": "reply1",
            "status": kwargs["status"],
            "metadata": kwargs["metadata"],
        }

    monkeypatch.setattr("automail.api.admin.issues.create_issue_reply", fake_create)

    resp = client.post(
        "/api/admin/projects/project1/issues/issue1/replies",
        json={"body": "Approval draft.", "status": "queued", "approvalRequired": True},
    )

    assert resp.status_code == 200
    assert resp.json()["metadata"] == {"approvalRequired": True, "approved": False, "reviewStatus": "pending"}
    assert calls == [{
        "issue_id": "issue1",
        "tenant_id": "",
        "project_id": "project1",
        "author_email": "",
        "body": "Approval draft.",
        "status": "queued",
        "metadata": {"approvalRequired": True, "approved": False, "reviewStatus": "pending"},
    }]


def test_admin_issue_reply_create_can_include_feedback_link(client, monkeypatch):
    calls: list[dict] = []

    def fake_create(issue_id: str, **kwargs):
        calls.append({"issue_id": issue_id, **kwargs})
        return {
            "id": "reply1",
            "status": kwargs["status"],
            "metadata": kwargs["metadata"],
        }

    monkeypatch.setattr("automail.api.admin.issues.create_issue_reply", fake_create)

    resp = client.post(
        "/api/admin/projects/project1/issues/issue1/replies",
        json={"body": "Please rate us.", "status": "queued", "includeFeedbackLink": True},
    )

    assert resp.status_code == 200
    assert resp.json()["metadata"] == {"includeFeedbackLink": True}
    assert calls == [{
        "issue_id": "issue1",
        "tenant_id": "",
        "project_id": "project1",
        "author_email": "",
        "body": "Please rate us.",
        "status": "queued",
        "metadata": {"includeFeedbackLink": True},
    }]


def test_admin_issue_reply_request_changes_records_editor(client, monkeypatch):
    calls: list[dict] = []

    def fake_request_changes(issue_id: str, reply_id: str, **kwargs):
        calls.append({"issue_id": issue_id, "reply_id": reply_id, **kwargs})
        return {
            "id": reply_id,
            "status": "draft",
            "metadata": {
                "approvalRequired": True,
                "approved": False,
                "reviewStatus": "changes_requested",
                "changesNote": kwargs["note"],
            },
        }

    monkeypatch.setattr("automail.api.admin.issues.request_issue_reply_changes", fake_request_changes)
    monkeypatch.setattr(
        "automail.api.admin.issues.get_issue",
        lambda *_args, **_kwargs: {
            "id": "issue1",
            "outboundMessages": [{"id": "reply1", "metadata": {}}],
        },
    )

    resp = client.post(
        "/api/admin/projects/project1/issues/issue1/replies/reply1/changes",
        json={"note": "Shorten and cite the SLA."},
    )

    assert resp.status_code == 200
    assert resp.json()["metadata"]["reviewStatus"] == "changes_requested"
    assert resp.json()["metadata"]["changesNote"] == "Shorten and cite the SLA."
    assert calls == [{
        "issue_id": "issue1",
        "reply_id": "reply1",
        "tenant_id": "",
        "project_id": "project1",
        "requested_by": "",
        "note": "Shorten and cite the SLA.",
    }]


def test_admin_issue_bulk_approve_processes_pending_replies_without_sending(client, monkeypatch):
    calls: list[tuple[str, str, str]] = []
    issue_detail = {
        "id": "issue1",
        "pendingApprovalCount": 1,
        "outboundMessages": [
            {
                "id": "reply1",
                "status": "queued",
                "metadata": {"approvalRequired": True, "approved": False},
            },
            {
                "id": "reply2",
                "status": "queued",
                "metadata": {"approvalRequired": False},
            },
        ],
    }
    refreshed_issue = {
        **issue_detail,
        "pendingApprovalCount": 0,
        "hasPendingApproval": False,
        "outboundMessages": [
            {
                "id": "reply1",
                "status": "queued",
                "metadata": {"approvalRequired": False, "approved": True},
            },
        ],
    }
    get_calls = 0

    def fake_get_issue(issue_id: str, **kwargs):
        nonlocal get_calls
        get_calls += 1
        calls.append(("get", issue_id, kwargs["project_id"]))
        return issue_detail if get_calls == 1 else refreshed_issue

    def fake_approve(issue_id: str, reply_id: str, **_kwargs):
        calls.append(("approve", issue_id, reply_id))
        return {
            "id": reply_id,
            "status": "queued",
            "metadata": {"approvalRequired": False, "approved": True},
        }

    def fake_deliver(*_args, **_kwargs):
        raise AssertionError("approve-only endpoint must not send replies")

    monkeypatch.setattr("automail.api.admin.issues.get_issue", fake_get_issue)
    monkeypatch.setattr("automail.api.admin.issues.approve_issue_reply_record", fake_approve)
    monkeypatch.setattr("automail.api.admin.issues.deliver_issue_reply", fake_deliver)

    resp = client.post(
        "/api/admin/projects/project1/issues/replies/bulk-approve",
        json={"issueIds": ["issue1"]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == 1
    assert data["approved"] == 1
    assert data["sent"] == 0
    assert data["failed"] == []
    assert data["items"][0]["replyId"] == "reply1"
    assert data["issues"][0]["pendingApprovalCount"] == 0
    assert calls == [
        ("get", "issue1", "project1"),
        ("approve", "issue1", "reply1"),
        ("get", "issue1", "project1"),
    ]


def test_admin_issue_bulk_approve_reports_approval_preflight_failure(client, monkeypatch):
    calls: list[tuple[str, str, str]] = []
    issue_detail = {
        "id": "issue1",
        "pendingApprovalCount": 1,
        "outboundMessages": [
            {
                "id": "reply1",
                "status": "queued",
                "metadata": {"approvalRequired": True, "approved": False},
            },
        ],
    }

    def fake_get_issue(issue_id: str, **kwargs):
        calls.append(("get", issue_id, kwargs["project_id"]))
        return issue_detail

    def fake_approve(issue_id: str, reply_id: str, **_kwargs):
        calls.append(("approve", issue_id, reply_id))
        raise ValueError("reviewer@example.com is not allowed for queue VIP")

    def fake_deliver(*_args, **_kwargs):
        raise AssertionError("approve-only endpoint must not send replies")

    monkeypatch.setattr("automail.api.admin.issues.get_issue", fake_get_issue)
    monkeypatch.setattr("automail.api.admin.issues.approve_issue_reply_record", fake_approve)
    monkeypatch.setattr("automail.api.admin.issues.deliver_issue_reply", fake_deliver)

    resp = client.post(
        "/api/admin/projects/project1/issues/replies/bulk-approve",
        json={"issueIds": ["issue1"]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == 0
    assert data["approved"] == 0
    assert data["sent"] == 0
    assert data["items"] == []
    assert data["failed"] == [{
        "id": "issue1",
        "replyId": "reply1",
        "error": "reviewer@example.com is not allowed for queue VIP",
    }]
    assert calls == [
        ("get", "issue1", "project1"),
        ("approve", "issue1", "reply1"),
        ("get", "issue1", "project1"),
    ]


def test_admin_issue_bulk_approve_send_processes_pending_replies(client, monkeypatch):
    calls: list[tuple[str, str, str]] = []
    issue_detail = {
        "id": "issue1",
        "pendingApprovalCount": 1,
        "outboundMessages": [
            {
                "id": "reply1",
                "status": "queued",
                "metadata": {"approvalRequired": True, "approved": False},
            },
            {
                "id": "reply2",
                "status": "queued",
                "metadata": {"approvalRequired": False},
            },
        ],
    }
    refreshed_issue = {
        **issue_detail,
        "pendingApprovalCount": 0,
        "outboundMessages": [
            {
                "id": "reply1",
                "status": "sent",
                "metadata": {"approvalRequired": False, "approved": True},
            },
        ],
    }
    get_calls = 0

    def fake_get_issue(issue_id: str, **kwargs):
        nonlocal get_calls
        get_calls += 1
        calls.append(("get", issue_id, kwargs["project_id"]))
        return issue_detail if get_calls == 1 else refreshed_issue

    def fake_approve(issue_id: str, reply_id: str, **kwargs):
        calls.append(("approve", issue_id, reply_id))
        return {
            "id": reply_id,
            "status": "queued",
            "metadata": {"approvalRequired": False, "approved": True},
        }

    def fake_deliver(issue_id: str, reply_id: str, **kwargs):
        calls.append(("deliver", issue_id, reply_id))
        return {
            "id": reply_id,
            "status": "sent",
            "error": "",
            "metadata": {"approvalRequired": False, "approved": True},
        }

    monkeypatch.setattr("automail.api.admin.issues.get_issue", fake_get_issue)
    monkeypatch.setattr("automail.api.admin.issues.approve_issue_reply_record", fake_approve)
    monkeypatch.setattr("automail.api.admin.issues.deliver_issue_reply", fake_deliver)
    monkeypatch.setattr("automail.api.admin.issues.issue_reply_delivery_readiness", lambda *_args, **_kwargs: {"ready": True})

    resp = client.post(
        "/api/admin/projects/project1/issues/replies/bulk-approve-send",
        json={"issueIds": ["issue1"]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == 1
    assert data["sent"] == 1
    assert data["failed"] == []
    assert data["items"][0]["replyId"] == "reply1"
    assert data["issues"][0]["pendingApprovalCount"] == 0
    assert calls == [
        ("get", "issue1", "project1"),
        ("approve", "issue1", "reply1"),
        ("deliver", "issue1", "reply1"),
        ("get", "issue1", "project1"),
    ]


def test_admin_issue_bulk_approve_send_preflights_reply_readiness(client, monkeypatch):
    calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        "automail.api.admin.issues.get_issue",
        lambda issue_id, **kwargs: {
            "id": issue_id,
            "pendingApprovalCount": 1,
            "outboundMessages": [
                {
                    "id": "reply1",
                    "status": "queued",
                    "metadata": {"approvalRequired": True, "approved": False},
                },
            ],
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.issues.issue_reply_delivery_readiness",
        lambda *_args, **_kwargs: {
            "ready": False,
            "blockers": ["missing_runtime_secrets"],
            "missingEnvVars": ["SUPPORT_TELEGRAM_BOT_TOKEN"],
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.issues.approve_issue_reply_record",
        lambda issue_id, reply_id, **_kwargs: calls.append(("approve", issue_id, reply_id)),
    )
    monkeypatch.setattr(
        "automail.api.admin.issues.deliver_issue_reply",
        lambda issue_id, reply_id, **_kwargs: calls.append(("deliver", issue_id, reply_id)),
    )

    resp = client.post(
        "/api/admin/projects/project1/issues/replies/bulk-approve-send",
        json={"issueIds": ["issue1"]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == 0
    assert data["sent"] == 0
    assert data["items"] == []
    assert data["failed"] == [{
        "id": "issue1",
        "replyId": "reply1",
        "error": "Reply channel is blocked: missing_runtime_secrets; missing env: SUPPORT_TELEGRAM_BOT_TOKEN",
    }]
    assert calls == []


def test_admin_issue_bulk_approve_send_reports_missing_pending_reply(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.issues.get_issue",
        lambda *_args, **_kwargs: {
            "id": "issue1",
            "outboundMessages": [
                {"id": "reply1", "status": "queued", "metadata": {"approvalRequired": False}},
            ],
        },
    )

    resp = client.post(
        "/api/admin/projects/project1/issues/replies/bulk-approve-send",
        json={"issueIds": ["issue1"]},
    )

    assert resp.status_code == 200
    assert resp.json()["processed"] == 0
    assert resp.json()["failed"] == [{"id": "issue1", "error": "No pending approval reply"}]


def test_admin_issue_bulk_approve_actions_processes_pending_proposals(client, monkeypatch):
    calls: list[tuple[str, str, str]] = []
    issue_detail = {
        "id": "issue1",
        "pendingApprovalCount": 2,
        "actionExecutions": [
            {
                "id": "action1",
                "status": "pending",
                "metadata": {"approvalRequired": True, "reviewStatus": "pending"},
            },
            {
                "id": "action2",
                "status": "pending",
                "metadata": {"approvalRequired": True, "reviewStatus": "pending"},
            },
            {
                "id": "action3",
                "status": "success",
                "metadata": {"approvalRequired": True, "reviewStatus": "approved"},
            },
        ],
    }

    def fake_get_issue(issue_id: str, **kwargs):
        calls.append(("get", issue_id, kwargs["project_id"]))
        return issue_detail

    def fake_approve(issue_id: str, execution_id: str, **kwargs):
        calls.append(("approve", issue_id, execution_id))
        return {
            "execution": {
                "id": execution_id,
                "status": "success",
                "metadata": {
                    "approvalRequired": True,
                    "reviewStatus": "approved",
                    "approvedBy": kwargs["approved_by"],
                },
            },
            "issue": {
                **issue_detail,
                "pendingApprovalCount": 0,
                "hasPendingApproval": False,
            },
        }

    monkeypatch.setattr("automail.api.admin.issues.get_issue", fake_get_issue)
    monkeypatch.setattr("automail.api.admin.issues.approve_issue_action_execution", fake_approve)

    resp = client.post(
        "/api/admin/projects/project1/issues/actions/bulk-approve",
        json={"issueIds": ["issue1"]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == 2
    assert data["approved"] == 2
    assert data["failed"] == []
    assert [item["executionId"] for item in data["items"]] == ["action1", "action2"]
    assert data["issues"][0]["pendingApprovalCount"] == 0
    assert calls == [
        ("get", "issue1", "project1"),
        ("approve", "issue1", "action1"),
        ("approve", "issue1", "action2"),
    ]


def test_admin_issue_bulk_reject_actions_processes_pending_proposals(client, monkeypatch):
    calls: list[tuple[str, str, str]] = []
    issue_detail = {
        "id": "issue1",
        "pendingApprovalCount": 1,
        "actionExecutions": [
            {
                "id": "action1",
                "status": "pending",
                "metadata": {"approvalRequired": True, "reviewStatus": "pending"},
            },
        ],
    }

    def fake_get_issue(issue_id: str, **kwargs):
        calls.append(("get", issue_id, kwargs["project_id"]))
        return issue_detail

    def fake_reject(issue_id: str, execution_id: str, **kwargs):
        calls.append(("reject", issue_id, execution_id))
        return {
            "execution": {
                "id": execution_id,
                "status": "skipped",
                "error": kwargs["note"],
                "metadata": {
                    "approvalRequired": True,
                    "reviewStatus": "rejected",
                    "rejectedBy": kwargs["rejected_by"],
                },
            },
            "issue": {
                **issue_detail,
                "pendingApprovalCount": 0,
                "hasPendingApproval": False,
            },
        }

    monkeypatch.setattr("automail.api.admin.issues.get_issue", fake_get_issue)
    monkeypatch.setattr("automail.api.admin.issues.reject_issue_action_execution", fake_reject)

    resp = client.post(
        "/api/admin/projects/project1/issues/actions/bulk-reject",
        json={"issueIds": ["issue1"], "note": "Needs owner check"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == 1
    assert data["rejected"] == 1
    assert data["failed"] == []
    assert data["items"][0]["executionId"] == "action1"
    assert data["items"][0]["error"] == "Needs owner check"
    assert data["issues"][0]["pendingApprovalCount"] == 0
    assert calls == [
        ("get", "issue1", "project1"),
        ("reject", "issue1", "action1"),
    ]


def test_admin_issue_bulk_approve_actions_reports_missing_pending_action(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.issues.get_issue",
        lambda *_args, **_kwargs: {
            "id": "issue1",
            "actionExecutions": [
                {"id": "action1", "status": "success", "metadata": {"approvalRequired": True}},
            ],
        },
    )

    resp = client.post(
        "/api/admin/projects/project1/issues/actions/bulk-approve",
        json={"issueIds": ["issue1"]},
    )

    assert resp.status_code == 200
    assert resp.json()["processed"] == 0
    assert resp.json()["failed"] == [{"id": "issue1", "error": "No pending approval action"}]


def test_admin_issue_bulk_retry_failed_processes_failed_replies(client, monkeypatch):
    calls: list[tuple[str, str, str]] = []
    issue_detail = {
        "id": "issue1",
        "failedDeliveryCount": 1,
        "hasFailedDelivery": True,
        "outboundMessages": [
            {"id": "reply1", "status": "failed", "metadata": {"approvalRequired": False}},
            {"id": "reply2", "status": "sent", "metadata": {}},
        ],
    }
    refreshed_issue = {
        **issue_detail,
        "failedDeliveryCount": 0,
        "hasFailedDelivery": False,
        "outboundMessages": [
            {"id": "reply1", "status": "sent", "metadata": {"approvalRequired": False}},
        ],
    }
    get_calls = 0

    def fake_get_issue(issue_id: str, **kwargs):
        nonlocal get_calls
        get_calls += 1
        calls.append(("get", issue_id, kwargs["project_id"]))
        return issue_detail if get_calls == 1 else refreshed_issue

    def fake_deliver(issue_id: str, reply_id: str, **kwargs):
        calls.append(("deliver", issue_id, reply_id))
        return {
            "id": reply_id,
            "status": "sent",
            "error": "",
            "metadata": {"approvalRequired": False},
        }

    monkeypatch.setattr("automail.api.admin.issues.get_issue", fake_get_issue)
    monkeypatch.setattr("automail.api.admin.issues.deliver_issue_reply", fake_deliver)

    resp = client.post(
        "/api/admin/projects/project1/issues/replies/bulk-retry-failed",
        json={"issueIds": ["issue1"]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == 1
    assert data["sent"] == 1
    assert data["failed"] == []
    assert data["items"][0]["replyId"] == "reply1"
    assert data["issues"][0]["hasFailedDelivery"] is False
    assert calls == [
        ("get", "issue1", "project1"),
        ("deliver", "issue1", "reply1"),
        ("get", "issue1", "project1"),
    ]


def test_admin_issue_bulk_retry_failed_reports_missing_failed_reply(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.issues.get_issue",
        lambda *_args, **_kwargs: {
            "id": "issue1",
            "outboundMessages": [
                {"id": "reply1", "status": "queued", "metadata": {}},
            ],
        },
    )

    resp = client.post(
        "/api/admin/projects/project1/issues/replies/bulk-retry-failed",
        json={"issueIds": ["issue1"]},
    )

    assert resp.status_code == 200
    assert resp.json()["processed"] == 0
    assert resp.json()["failed"] == [{"id": "issue1", "error": "No failed reply"}]


def test_admin_issue_reply_send_requires_approval(client, monkeypatch):
    def fake_deliver(*_args, **_kwargs):
        raise ValueError("Reply requires approval before sending")

    monkeypatch.setattr("automail.api.admin.issues.deliver_issue_reply", fake_deliver)
    monkeypatch.setattr(
        "automail.api.admin.issues.get_issue",
        lambda *_args, **_kwargs: {
            "id": "issue1",
            "outboundMessages": [{"id": "reply1", "metadata": {}}],
        },
    )

    resp = client.post("/api/admin/projects/project1/issues/issue1/replies/reply1/send", json={})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Reply requires approval before sending"


def test_admin_issue_reply_patch_records_editor(client, monkeypatch):
    calls: list[dict] = []

    def fake_update(issue_id: str, reply_id: str, **kwargs):
        calls.append({"issue_id": issue_id, "reply_id": reply_id, **kwargs})
        return {
            "id": reply_id,
            "body": "Edited answer.",
            "status": "draft",
            "metadata": {"approvalRequired": True},
        }

    monkeypatch.setattr("automail.api.admin.issues.update_issue_reply", fake_update)
    monkeypatch.setattr(
        "automail.api.admin.issues.get_issue",
        lambda *_args, **_kwargs: {
            "id": "issue1",
            "outboundMessages": [{"id": "reply1", "metadata": {}}],
        },
    )

    resp = client.patch(
        "/api/admin/projects/project1/issues/issue1/replies/reply1",
        json={"body": "Edited answer.", "status": "draft"},
    )

    assert resp.status_code == 200
    assert resp.json()["body"] == "Edited answer."
    assert calls == [{
        "issue_id": "issue1",
        "reply_id": "reply1",
        "tenant_id": "",
        "project_id": "project1",
        "editor_email": "",
        "body": "Edited answer.",
        "status": "draft",
    }]


def test_admin_channels_include_setup_metadata(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_SLACK_WEBHOOK_TOKEN", "secret")
    monkeypatch.delenv("SUPPORT_SLACK_OUTBOUND_URL", raising=False)
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "slack-main",
                "type": "slack",
                "name": "Slack",
                "status": "active",
                "config": {
                    "outboundWebhookUrlEnv": "SUPPORT_SLACK_OUTBOUND_URL",
                    "outboundWebhookTokenEnv": "SUPPORT_SLACK_OUTBOUND_TOKEN",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    assert setup["inboundWebhookUrl"].endswith("/api/internal/support/channel-webhooks/slack-main?project_id=project1")
    assert setup["providerWebhookUrl"].endswith("/api/internal/support/slack/slack-main?project_id=project1")
    assert setup["tokenHeader"] == "X-Support-Sync-Token"
    assert setup["providerTokenEnv"] == "SUPPORT_SLACK_WEBHOOK_TOKEN"
    assert setup["signatureEnv"] == "SUPPORT_SLACK_SIGNING_SECRET"
    assert setup["signatureHeader"] == "X-Slack-Signature"
    assert setup["providerSignatureConfigKey"] == "slackSigningSecretEnv"
    assert setup["providerName"] == "Slack"
    assert setup["authConfigured"] is True
    assert setup["inboundReady"] is True
    assert setup["ticketCreationMode"] == "per_message"
    assert setup["autoPrepareTriage"] is True
    assert setup["autoPrepareCustomFields"] is True
    assert setup["autoPrepareConfigKeys"][:5] == [
        "autoPrepareTriage",
        "autoPrepareCustomFields",
        "autoPrepareAgentReply",
        "autoPrepareAgentReplyOnUpdate",
        "agentAutoSend",
    ]
    assert setup["outboundWebhookConfigured"] is True
    assert setup["outboundReady"] is False
    assert setup["outboundWebhookUrlEnv"] == "SUPPORT_SLACK_OUTBOUND_URL"
    assert setup["outboundWebhookTokenEnv"] == "SUPPORT_SLACK_OUTBOUND_TOKEN"
    assert setup["messagePayloadExample"]["eventType"] == "message_created"
    assert setup["health"]["status"] == "degraded"
    assert setup["health"]["inboundReady"] is True
    assert setup["health"]["outboundReady"] is False
    assert "SUPPORT_SLACK_OUTBOUND_URL" in setup["health"]["missingEnvVars"]
    assert [step["key"] for step in setup["setupChecklist"]] == [
        "status",
        "inbound_url",
        "auth",
        "outbound",
        "test",
    ]
    assert any(env["name"] == "SUPPORT_SLACK_WEBHOOK_TOKEN" and env["configured"] for env in setup["envVars"])
    assert any(env["name"] == "SUPPORT_SLACK_OUTBOUND_URL" and not env["configured"] for env in setup["envVars"])
    assert setup["providerSteps"][0].startswith("Create a Slack app")
    manifest = setup["slackManifest"]
    assert manifest["oauth_config"]["redirect_urls"][0].endswith(
        "/api/admin/projects/project1/channels/slack/oauth/callback"
    )
    assert "chat:write" in manifest["oauth_config"]["scopes"]["bot"]
    assert "app_mentions:read" in manifest["oauth_config"]["scopes"]["bot"]
    assert manifest["settings"]["event_subscriptions"]["request_url"] == setup["providerWebhookUrl"]
    assert "message.channels" in manifest["settings"]["event_subscriptions"]["bot_events"]
    assert "secret" not in json.dumps(manifest)
    install_package = setup["installPackage"]
    assert install_package["version"] == 1
    assert install_package["projectId"] == "project1"
    assert install_package["channel"]["key"] == "slack-main"
    assert install_package["inbound"]["primaryUrl"] == setup["providerWebhookUrl"]
    assert install_package["inbound"]["genericWebhookUrl"] == setup["inboundWebhookUrl"]
    assert install_package["auth"]["tokenHeader"] == "X-Support-Sync-Token"
    assert install_package["auth"]["tokenEnv"] == "SUPPORT_SLACK_WEBHOOK_TOKEN"
    assert install_package["outbound"]["webhookUrlEnv"] == "SUPPORT_SLACK_OUTBOUND_URL"
    assert install_package["health"]["status"] == "degraded"
    assert install_package["payloadExamples"]["message"]["eventType"] == "message_created"
    assert install_package["slackManifest"]["settings"]["event_subscriptions"]["request_url"] == setup["providerWebhookUrl"]


def test_admin_channels_activation_backlog_export(client, monkeypatch):
    monkeypatch.setattr("automail.api.admin.channels.load_runtime_secrets", lambda tenant_id, project_id: {})
    monkeypatch.setattr("automail.api.admin.channels.list_channel_sync_runs", lambda **_kwargs: [])
    monkeypatch.setattr("automail.api.admin.channels.support_launch_proof", lambda **_kwargs: {"channels": {"items": []}})
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "slack-main",
                "type": "slack",
                "name": "Slack",
                "status": "paused",
                "config": {
                    "ticketCreationMode": "per_message",
                    "autoPrepareAgentReply": True,
                    "autoPrepareAgentReplyOnUpdate": True,
                    "defaultAssigneeEmail": "owner@example.com",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels/activation-backlog")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["kind"] == "support_channel_activation_backlog"
    assert payload["projectId"] == "project1"
    assert payload["summary"]["totalSurfaces"] == 14
    assert payload["summary"]["configuredSurfaces"] == 1
    assert payload["summary"]["readySurfaces"] == 0
    assert payload["summary"]["backlogSurfaces"] == 14
    assert payload["summary"]["nextActionCount"] == 14
    assert payload["summary"]["nextActionPhases"]["create"] == 13
    assert payload["summary"]["nextActionPhases"]["targets"] == 1
    slack = next(item for item in payload["channels"] if item["surface"]["type"] == "slack")
    assert slack["channel"]["key"] == "slack-main"
    assert slack["channel"]["status"] == "paused"
    assert "Paused" in slack["surface"]["blockers"]
    assert "smokeChannelId" in slack["launch"]["missingLiveTargets"]
    assert any(command["command"] for command in slack["launch"]["commands"])
    assert slack["setupPackage"]["installPackage"]["channel"]["key"] == "slack-main"
    slack_action = next(action for action in payload["nextActions"] if action["surfaceType"] == "slack")
    assert slack_action["phase"] == "targets"
    assert slack_action["action"] == "configure_smoke_target"
    assert "smokeChannelId" in slack_action["liveTargets"]
    assert payload["summary"]["adapterMatrixRows"] == 14
    assert payload["summary"]["adapterMatrixBlocked"] == 14
    assert payload["summary"]["providerRunbookRows"] == 14
    assert payload["summary"]["providerRunbookBlocked"] == 14
    assert payload["summary"]["initialProviderRows"] == 4
    assert payload["summary"]["initialProviderBlocked"] == 4
    slack_adapter = next(item for item in payload["adapterMatrix"] if item["surfaceType"] == "slack")
    assert slack_adapter["channelKey"] == "slack-main"
    assert slack_adapter["channelStatus"] == "paused"
    assert slack_adapter["inbound"]["adapter"] == "slack"
    assert slack_adapter["outbound"]["adapter"] == "provider"
    assert slack_adapter["nextAction"]["action"] == "configure_smoke_target"
    assert "smokeChannelId" in slack_adapter["missingLiveTargets"]
    slack_runbook = slack["providerRunbook"]
    assert slack_runbook["kind"] == "support_channel_provider_runbook"
    assert slack_runbook["surfaceType"] == "slack"
    assert slack_runbook["launchWave"] == "initial"
    assert slack_runbook["initialProvider"] is True
    assert slack_runbook["channelKey"] == "slack-main"
    assert slack_runbook["phase"] == "targets"
    assert "Create a Slack app and subscribe it to message events." in slack_runbook["providerSteps"]
    assert "smokeChannelId" in slack_runbook["missingLiveTargets"]
    assert any(action["key"] == "lifecycle_smoke" for action in slack_runbook["proofActions"])
    assert any(command["command"] for command in slack_runbook["commands"])
    assert "installPackage" in slack_runbook["setupPackageKeys"]
    assert payload["summary"]["requiredMissingEnvVars"]
    assert "SUPPORT_TEAMS_APP_ID" in payload["summary"]["requiredMissingEnvVars"]
    missing_types = {item["surface"]["type"] for item in payload["channels"] if item["channel"] is None}
    assert {"teams", "discord", "telegram", "line", "viber", "whatsapp", "messenger", "instagram", "twitter", "sms", "chat", "webhook"} <= missing_types
    teams = next(item for item in payload["channels"] if item["surface"]["type"] == "teams")
    assert teams["providerRunbook"]["launchWave"] == "later"
    assert teams["providerRunbook"]["initialProvider"] is False
    assert teams["providerRunbook"]["phase"] == "create"
    assert "Create a Teams bot or Graph change notification bridge." in teams["providerRunbook"]["providerSteps"]


def test_admin_channels_activation_plan_export(client, monkeypatch):
    monkeypatch.setattr("automail.api.admin.channels.load_runtime_secrets", lambda tenant_id, project_id: {})
    monkeypatch.setattr("automail.api.admin.channels.list_channel_sync_runs", lambda **_kwargs: [])
    monkeypatch.setattr("automail.api.admin.channels.support_launch_proof", lambda **_kwargs: {"channels": {"items": []}})
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "slack-main",
                "type": "slack",
                "name": "Slack",
                "status": "paused",
                "config": {
                    "ticketCreationMode": "per_message",
                    "autoPrepareAgentReply": True,
                    "autoPrepareAgentReplyOnUpdate": True,
                    "defaultAssigneeEmail": "owner@example.com",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels/activation-plan")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["kind"] == "support_channel_activation_plan"
    assert payload["projectId"] == "project1"
    assert payload["source"] == "api"
    assert payload["summary"]["totalSurfaces"] == 14
    assert payload["summary"]["nextActionPhases"]["create"] == 13
    assert payload["nextActions"]
    assert "SUPPORT_TEAMS_APP_ID" in payload["secrets"]["missingEnvVars"]
    assert "# Teams" in payload["secrets"]["template"]
    assert "SUPPORT_TEAMS_APP_ID=" in payload["secrets"]["template"]
    slack = next(item for item in payload["surfaces"] if item["surfaceType"] == "slack")
    assert slack["channelKey"] == "slack-main"
    assert slack["channelStatus"] == "paused"
    assert slack["ticketing"]["everyMessage"] is True
    assert slack["ticketing"]["ownerRouting"] is True
    assert "smokeChannelId" in slack["missingLiveTargets"]
    assert any(command["command"] for command in slack["setupCommands"])
    assert slack["setupPackage"]["installPackage"]["channel"]["key"] == "slack-main"
    assert slack["nextActions"][0]["action"] == "configure_smoke_target"
    assert slack["providerRunbook"]["phase"] == "targets"
    assert slack["providerRunbook"]["launchWave"] == "initial"
    assert "smokeChannelId" in slack["providerRunbook"]["missingLiveTargets"]
    assert "installPackage" in slack["providerRunbook"]["setupPackageKeys"]
    slack_adapter = next(item for item in payload["adapterMatrix"] if item["surfaceType"] == "slack")
    assert slack_adapter["channelKey"] == "slack-main"
    assert slack_adapter["outbound"]["adapter"] == "provider"
    assert slack_adapter["nextAction"]["action"] == "configure_smoke_target"
    teams = next(item for item in payload["surfaces"] if item["surfaceType"] == "teams")
    assert teams["channelStatus"] == "missing"
    assert teams["requiredMissingEnvVars"]
    assert teams["nextActions"][0]["action"] == "create_channel"
    assert teams["providerRunbook"]["phase"] == "create"
    assert teams["providerRunbook"]["launchWave"] == "later"
    assert "SUPPORT_TEAMS_APP_ID" in [item["name"] for item in teams["providerRunbook"]["secretEnvVars"]]
    teams_adapter = next(item for item in payload["adapterMatrix"] if item["surfaceType"] == "teams")
    assert teams_adapter["channelStatus"] == "missing"
    assert teams_adapter["nextAction"]["action"] == "create_channel"


def test_admin_channels_bootstrap_activation_backlog_creates_missing_surfaces(client, monkeypatch):
    channels = [
        {
            "id": "channel-slack",
            "channelKey": "slack-main",
            "type": "slack",
            "name": "Slack",
            "status": "paused",
            "config": {"ticketCreationMode": "per_message"},
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        }
    ]
    upserts: list[dict] = []
    sync_runs: list[dict] = []

    def fake_list_channels(**_kwargs):
        return list(channels)

    def fake_upsert_channel(**kwargs):
        upserts.append(kwargs)
        channel = {
            "id": f"channel-{kwargs['channel_key']}",
            "channelKey": kwargs["channel_key"],
            "type": kwargs["channel_type"],
            "name": kwargs["name"],
            "status": kwargs["status"],
            "config": kwargs["config"],
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        }
        channels.append(channel)
        return channel

    def fake_record_channel_sync_run(**kwargs):
        sync_runs.append(kwargs)
        return {"id": f"run-{len(sync_runs)}", **kwargs}

    monkeypatch.setattr("automail.api.admin.channels.load_runtime_secrets", lambda tenant_id, project_id: {})
    monkeypatch.setattr("automail.api.admin.channels.list_channel_sync_runs", lambda **_kwargs: [])
    monkeypatch.setattr("automail.api.admin.channels.list_channel_webhook_events", lambda **_kwargs: [])
    monkeypatch.setattr("automail.api.admin.channels.support_launch_proof", lambda **_kwargs: {"channels": {"items": []}})
    monkeypatch.setattr("automail.api.admin.channels.list_channels", fake_list_channels)
    monkeypatch.setattr("automail.api.admin.channels.upsert_channel", fake_upsert_channel)
    monkeypatch.setattr("automail.api.admin.channels.record_channel_sync_run", fake_record_channel_sync_run)

    resp = client.post(
        "/api/admin/projects/project1/channels/activation-backlog/bootstrap",
        json={"surfaces": ["slack", "discord", "telegram"], "status": "paused"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["created"] == 2
    assert {item["channelKey"] for item in payload["items"]} == {"discord-main", "telegram-main"}
    assert {item["channelKey"] for item in payload["bootstrapRuns"]} == {"discord-main", "telegram-main"}
    assert all(item["status"] == "recorded" and item["runId"] for item in payload["bootstrapRuns"])
    assert payload["skipped"] == [{"surfaceType": "slack", "surfaceLabel": "Slack", "reason": "configured"}]
    assert [call["channel_key"] for call in upserts] == ["discord-main", "telegram-main"]
    assert all(call["status"] == "paused" for call in upserts)
    assert [call["source"] for call in sync_runs] == ["admin-activation-bootstrap", "admin-activation-bootstrap"]
    assert [call["channel_id"] for call in sync_runs] == ["channel-discord-main", "channel-telegram-main"]
    assert all(call["result"]["proof"]["kind"] == "activation_bootstrap" for call in sync_runs)
    for call in upserts:
        config = call["config"]
        assert config["ticketCreationMode"] == "per_message"
        assert config["autoPrepareTriage"] is True
        assert config["autoPrepareCustomFields"] is True
        assert config["autoPrepareAgentReply"] is True
        assert config["autoPrepareAgentReplyOnUpdate"] is True
        assert config["agentAutoSend"] is False
        assert config["defaultQueueKey"] == "support"
        assert config["defaultQueueName"] == "Support"
    assert payload["activationBacklog"]["summary"]["configuredSurfaces"] == 3
    configured = {
        item["surface"]["type"]
        for item in payload["activationBacklog"]["surfaces"]
        if item["surface"]["configured"]
    }
    assert {"slack", "discord", "telegram"} <= configured


def test_admin_channels_activate_ready_surfaces_records_activation_proof(client, monkeypatch):
    channels = [
        {
            "id": "channel-web-chat",
            "channelKey": "web-chat",
            "type": "web_chat",
            "name": "Web chat",
            "status": "paused",
            "config": {
                "ticketCreationMode": "per_message",
                "autoPrepareTriage": True,
                "autoPrepareCustomFields": True,
                "autoPrepareAgentReply": True,
                "autoPrepareAgentReplyOnUpdate": True,
                "agentAutoSend": False,
                "defaultQueueKey": "support",
                "defaultQueueName": "Support",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        }
    ]
    upserts: list[dict] = []
    sync_runs: list[dict] = []

    def fake_list_channels(**_kwargs):
        return list(channels)

    def fake_upsert_channel(**kwargs):
        upserts.append(kwargs)
        channels[0] = {**channels[0], "status": kwargs["status"], "config": kwargs["config"]}
        return channels[0]

    def fake_with_channel_setup(channel, *_args, **_kwargs):
        return {
            **channel,
            "setup": {
                "health": {"inboundReady": True, "outboundReady": True, "requiredMissingEnvVars": []},
                "ticketCreationMode": "per_message",
                "autoPrepareTriage": True,
                "autoPrepareCustomFields": True,
                "autoPrepareAgentReply": True,
                "autoPrepareAgentReplyOnUpdate": True,
                "agentAutoSend": False,
                "inboundReady": True,
                "outboundReady": True,
                "webChatUrl": "https://api.example.test/support/web-chat/project1?channel_key=web-chat",
                "launch": {
                    "required": True,
                    "ready": False,
                    "blockers": [{"key": "web_chat_session", "label": "Session missing", "action": "web_chat_session"}],
                },
            },
        }

    def fake_record_channel_sync_run(**kwargs):
        sync_runs.append(kwargs)
        return {"id": f"run-{len(sync_runs)}", **kwargs}

    monkeypatch.setattr("automail.api.admin.channels.list_channels", fake_list_channels)
    monkeypatch.setattr("automail.api.admin.channels.upsert_channel", fake_upsert_channel)
    monkeypatch.setattr("automail.api.admin.channels._with_channel_setup", fake_with_channel_setup)
    monkeypatch.setattr("automail.api.admin.channels.list_channel_sync_runs", lambda **_kwargs: [])
    monkeypatch.setattr("automail.api.admin.channels.list_channel_webhook_events", lambda **_kwargs: [])
    monkeypatch.setattr("automail.api.admin.channels.support_launch_proof", lambda **_kwargs: {"channels": {"items": []}})
    monkeypatch.setattr("automail.api.admin.channels.load_runtime_secrets", lambda tenant_id, project_id: {})
    monkeypatch.setattr("automail.api.admin.channels.record_channel_sync_run", fake_record_channel_sync_run)

    resp = client.post(
        "/api/admin/projects/project1/channels/activation-backlog/activate-ready",
        json={},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["activated"] == 1
    assert payload["items"][0]["status"] == "active"
    assert payload["activationRuns"] == [{
        "channelId": "channel-web-chat",
        "channelKey": "web-chat",
        "surfaceType": "chat",
        "runId": "run-1",
        "status": "recorded",
        "error": "",
    }]
    assert upserts[0]["status"] == "active"
    assert sync_runs[0]["source"] == "admin-activation-ready"
    assert sync_runs[0]["result"]["proof"]["kind"] == "activation_ready"
    assert payload["activationBacklog"]["summary"]["activeSurfaces"] == 1
    chat_action = next(
        item for item in payload["activationBacklog"]["nextActions"]
        if item["surfaceType"] == "chat"
    )
    assert chat_action["phase"] == "proof"


def test_channel_activation_requires_follow_up_and_approval_gate():
    item = admin_channels._activation_surface_item(
        "slack",
        "Slack",
        {
            "id": "channel1",
            "channelKey": "slack-main",
            "type": "slack",
            "name": "Slack",
            "status": "active",
            "config": {
                "ticketCreationMode": "per_message",
                "autoPrepareTriage": True,
                "autoPrepareCustomFields": True,
                "autoPrepareAgentReply": True,
                "autoPrepareAgentReplyOnUpdate": False,
                "agentAutoSend": True,
                "defaultAssigneeEmail": "owner@example.com",
                "smokeChannelId": "C123",
            },
            "setup": {
                "health": {"inboundReady": True, "outboundReady": True},
                "envVars": [
                    {"name": "SUPPORT_SLACK_WEBHOOK_TOKEN", "purpose": "auth", "required": True, "configured": True},
                    {"name": "SUPPORT_SLACK_OUTBOUND_URL", "purpose": "outbound", "required": True, "configured": True},
                ],
                "launch": {"required": False, "ready": True, "blockers": []},
            },
        },
    )

    assert item["surface"]["ready"] is False
    assert "Manual follow-up" in item["surface"]["blockers"]
    assert "No approval gate" in item["surface"]["blockers"]
    assert item["automation"]["autoPrepareAgentReplyOnUpdate"] is False
    assert item["automation"]["humanReview"] is False

    action = admin_channels._activation_next_action(item, 0)

    assert action
    assert action["phase"] == "config"
    assert action["action"] == "ticket_defaults"
    assert "autoPrepareAgentReplyOnUpdate" in action["detail"]
    assert "approvalRequired" in action["detail"]


def test_admin_channels_marks_default_slack_signature_required_when_secret_present(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_SLACK_SIGNING_SECRET": "signing-secret",
            "SUPPORT_SLACK_WEBHOOK_TOKEN": "slack-token",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "slack-main",
                "type": "slack",
                "name": "Slack",
                "status": "active",
                "config": {},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    assert setup["authConfigured"] is True
    assert setup["inboundReady"] is True
    assert setup["signatureRequired"] is True
    assert setup["signatureEnv"] == "SUPPORT_SLACK_SIGNING_SECRET"
    assert any(
        env["name"] == "SUPPORT_SLACK_SIGNING_SECRET" and env["configured"] and env["required"]
        for env in setup["envVars"]
    )


def test_admin_channels_marks_default_slack_bot_secret_outbound_ready(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_SLACK_WEBHOOK_TOKEN": "slack-token",
            "SUPPORT_SLACK_BOT_TOKEN": "xoxb-test",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "slack-main",
                "type": "slack",
                "name": "Slack",
                "status": "active",
                "config": {},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    assert setup["outboundReady"] is True
    assert setup["outboundTransport"] == "bot"
    assert setup["outboundBotTokenEnv"] == "SUPPORT_SLACK_BOT_TOKEN"
    assert setup["outboundWebhookConfigured"] is True
    assert setup["health"]["outboundReady"] is True
    assert setup["installPackage"]["outbound"]["ready"] is True
    assert any(
        env["name"] == "SUPPORT_SLACK_BOT_TOKEN" and env["configured"] and env["required"]
        for env in setup["envVars"]
    )


def test_admin_channels_marks_native_bot_secret_outbound_ready_for_providers(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_TEAMS_WEBHOOK_TOKEN": "teams-token",
            "SUPPORT_TEAMS_APP_ID": "teams-app",
            "SUPPORT_TEAMS_APP_PASSWORD": "teams-secret",
            "SUPPORT_DISCORD_WEBHOOK_TOKEN": "discord-token",
            "SUPPORT_DISCORD_BOT_TOKEN": "discord-bot",
            "SUPPORT_TELEGRAM_SECRET_TOKEN": "telegram-secret",
            "SUPPORT_TELEGRAM_BOT_TOKEN": "telegram-bot",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel-teams",
                "channelKey": "teams-main",
                "type": "teams",
                "name": "Teams",
                "status": "active",
                "config": {},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel-discord",
                "channelKey": "discord-main",
                "type": "discord",
                "name": "Discord",
                "status": "active",
                "config": {},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel-telegram",
                "channelKey": "telegram-main",
                "type": "telegram",
                "name": "Telegram",
                "status": "active",
                "config": {},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup_by_key = {item["channelKey"]: item["setup"] for item in resp.json()["items"]}
    for setup in setup_by_key.values():
        assert setup["outboundReady"] is True
        assert setup["outboundTransport"] == "bot"
        assert setup["outboundWebhookConfigured"] is True
        assert setup["health"]["outboundReady"] is True
        assert setup["installPackage"]["outbound"]["configured"] is True
        assert setup["installPackage"]["outbound"]["ready"] is True
        assert next(step for step in setup["setupChecklist"] if step["key"] == "outbound")["status"] == "done"
    assert setup_by_key["teams-main"]["outboundBotCredentialEnvVars"] == [
        "SUPPORT_TEAMS_APP_ID",
        "SUPPORT_TEAMS_APP_PASSWORD",
    ]
    assert setup_by_key["discord-main"]["outboundBotTokenEnv"] == "SUPPORT_DISCORD_BOT_TOKEN"
    assert setup_by_key["telegram-main"]["outboundBotTokenEnv"] == "SUPPORT_TELEGRAM_BOT_TOKEN"


def test_admin_channels_setup_includes_launch_smoke_state(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_SLACK_WEBHOOK_TOKEN", "secret")
    monkeypatch.setenv("SUPPORT_SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "slack-main",
                "type": "slack",
                "name": "Slack",
                "status": "active",
                "config": {
                    "outboundWebhookUrl": "https://slack.com/api/chat.postMessage",
                    "outboundWebhookTokenEnv": "SUPPORT_SLACK_BOT_TOKEN",
                    "outboundTokenRequired": True,
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channel_sync_runs",
        lambda **_kwargs: [
            {
                "id": "life1",
                "channelId": "channel1",
                "source": "admin-lifecycle-smoke",
                "status": "failed",
                "processed": 1,
                "failed": 1,
                "error": "delivery failed",
                "result": {"ready": True, "sent": False, "error": "delivery failed"},
                "startedAt": "2026-01-03T10:00:00+00:00",
            },
            {
                "id": "out1",
                "channelId": "channel1",
                "source": "admin-outbound-smoke",
                "status": "sent",
                "processed": 1,
                "failed": 0,
                "result": {"ready": True, "sent": True},
                "startedAt": "2026-01-02T10:00:00+00:00",
            },
            {
                "id": "in1",
                "channelId": "channel1",
                "source": "admin-smoke",
                "status": "success",
                "processed": 1,
                "failed": 0,
                "result": _inbound_smoke_result(),
                "startedAt": "2026-01-01T10:00:00+00:00",
            },
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    assert setup["launch"]["required"] is True
    assert setup["launch"]["ready"] is False
    assert setup["launch"]["passed"] == 2
    assert setup["launch"]["missing"] == 1
    assert setup["launch"]["failed"] == 1
    assert setup["launch"]["lastCheckedAt"] == "2026-01-03T10:00:00+00:00"
    assert setup["launch"]["blockers"] == [
        {
            "key": "lifecycle_smoke",
            "label": "Lifecycle smoke passed",
            "status": "warning",
            "detail": "delivery failed",
            "action": "lifecycle_smoke",
            "runId": "life1",
        },
        {
            "key": "attachment_lifecycle_smoke",
            "label": "Attachment lifecycle smoke passed",
            "status": "missing",
            "detail": "Run attachment-only HTTP lifecycle smoke to prove Slack files create tickets and replies deliver",
            "action": "attachment_lifecycle_smoke",
            "runId": "",
        },
    ]
    checks = {item["key"]: item for item in setup["launchChecklist"]}
    assert checks["inbound_smoke"]["status"] == "done"
    assert checks["inbound_smoke"]["runId"] == "in1"
    assert checks["outbound_smoke"]["status"] == "done"
    assert checks["outbound_smoke"]["runId"] == "out1"
    assert checks["lifecycle_smoke"]["status"] == "warning"
    assert checks["lifecycle_smoke"]["detail"] == "delivery failed"
    assert checks["lifecycle_smoke"]["action"] == "lifecycle_smoke"
    assert checks["attachment_lifecycle_smoke"]["status"] == "missing"
    assert setup["installPackage"]["launch"]["failed"] == 1


def test_admin_channels_setup_includes_real_inbound_ticket_event(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_DISCORD_WEBHOOK_TOKEN", "secret")
    monkeypatch.setattr(
        "automail.api.admin.channels.support_launch_proof",
        lambda **_kwargs: {
            "channels": {
                "items": [
                    {
                        "channelId": "channel1",
                        "required": True,
                        "ready": False,
                        "checks": 1,
                        "passed": 1,
                        "blockers": [],
                        "checklist": [
                            {
                                "key": "real_channel_reply",
                                "label": "Real app reply delivered",
                                "status": "done",
                                "detail": "Real provider ticket was answered from the app",
                                "runId": "reply1",
                                "source": "app-reply",
                                "runStatus": "sent",
                                "processed": 1,
                                "failed": 0,
                                "sent": 1,
                                "issueId": "issue1",
                                "replyId": "reply1",
                                "provider": "discord_bot",
                                "providerMessageId": "discord:reply1",
                                "inboundProviderMessageId": "m-1",
                                "deliveryRoute": {"transport": "bot_api"},
                            },
                            {
                                "key": "channel_autopilot",
                                "label": "Channel autopilot prep proof",
                                "status": "done",
                                "detail": "Agent prepared draft",
                                "runId": "autopilot-event1",
                                "source": "channel_autopilot",
                                "runStatus": "prepared",
                                "processed": 1,
                                "failed": 0,
                                "issueId": "issue1",
                                "replyId": "reply1",
                                "aiRunId": "run1",
                            }
                        ],
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "discord-main",
                "type": "discord",
                "name": "Discord",
                "status": "active",
                "config": {
                    "ticketCreationMode": "per_message",
                    "defaultAssigneeEmail": "owner@example.com",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )
    monkeypatch.setattr("automail.api.admin.channels.list_channel_sync_runs", lambda **_kwargs: [])
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channel_webhook_events",
        lambda **_kwargs: [
            {
                "id": "event1",
                "channelId": "channel1",
                "provider": "discord",
                "eventId": "msg-1",
                "eventType": "MESSAGE_CREATE",
                "providerMessageId": "m-1",
                "status": "processed",
                "result": {
                    "matched": True,
                    "kind": "inbound_message",
                    "status": "success",
                    "issueId": "issue1",
                },
                "receivedAt": "2026-07-04T09:00:00+00:00",
                "processedAt": "2026-07-04T09:00:01+00:00",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    checks = {item["key"]: item for item in setup["launchChecklist"]}
    proof = checks["inbound_ticket_event"]
    assert proof["status"] == "done"
    assert proof["source"] == "provider-webhook"
    assert proof["runId"] == "event1"
    assert proof["issueId"] == "issue1"
    assert proof["provider"] == "discord"
    assert proof["providerMessageId"] == "m-1"
    handoff = checks["real_channel_handoff"]
    assert handoff["status"] == "done"
    assert handoff["issueId"] == "issue1"
    assert handoff["replyId"] == "reply1"
    assert handoff["aiRunId"] == "run1"
    reply = checks["real_channel_reply"]
    assert reply["status"] == "done"
    assert reply["issueId"] == "issue1"
    assert reply["replyId"] == "reply1"
    assert reply["provider"] == "discord_bot"
    assert reply["providerMessageId"] == "discord:reply1"
    assert reply["inboundProviderMessageId"] == "m-1"
    assert reply["deliveryRoute"]["transport"] == "bot_api"
    assert setup["launch"]["passed"] == 4
    assert setup["launch"]["checks"] == len(setup["launchChecklist"])
    assert all(blocker["key"] != "inbound_ticket_event" for blocker in setup["launch"]["blockers"])
    assert setup["installPackage"]["launch"]["checklist"][0]["key"] == "real_channel_handoff"


def test_admin_channels_web_chat_setup_includes_embed_snippet(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "web-chat",
                "type": "chat",
                "name": "Web chat",
                "status": "active",
                "config": {"ticketCreationMode": "per_thread"},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    assert setup["webChatUrl"].endswith("/support/web-chat/project1?channel_key=web-chat")
    assert setup["webChatEmbedScriptUrl"].endswith("/support/web-chat/project1/embed.js?channel_key=web-chat")
    assert setup["webChatEmbedSnippet"] == f'<script async src="{setup["webChatEmbedScriptUrl"]}"></script>'
    assert setup["authConfigured"] is True
    assert setup["inboundReady"] is True
    assert setup["outboundReady"] is True
    assert setup["outboundTransport"] == "internal"
    assert setup["health"]["status"] == "ready"
    assert setup["launch"]["required"] is True
    assert setup["launch"]["ready"] is False
    assert [item["key"] for item in setup["launchChecklist"]] == ["web_chat_session", "web_chat_delivery"]
    assert {item["key"] for item in setup["launch"]["blockers"]} == {"web_chat_session", "web_chat_delivery"}
    assert setup["providerSteps"][0].startswith("Install the web chat embed script")
    assert setup["installPackage"]["inbound"]["webChatEmbedScriptUrl"] == setup["webChatEmbedScriptUrl"]
    assert setup["installPackage"]["inbound"]["webChatEmbedSnippet"] == setup["webChatEmbedSnippet"]
    assert setup["installPackage"]["health"]["status"] == "ready"


def test_admin_channels_email_fallback_requires_sync_ticket_artifact(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "email1",
                "channelKey": "support-email",
                "type": "email",
                "name": "Support email",
                "status": "active",
                "config": {"ticketCreationMode": "per_message", "autoPrepareAgentReply": True},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channel_sync_runs",
        lambda **_kwargs: [
            {
                "id": "sync1",
                "channelId": "email1",
                "source": "scheduler",
                "status": "success",
                "processed": 1,
                "failed": 0,
                "result": {"items": [{"emailId": "channel:support-email:message1", "status": "processed"}]},
                "startedAt": "2026-07-03T09:00:00+00:00",
                "completedAt": "2026-07-03T09:01:00+00:00",
            },
        ],
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.support_launch_proof",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("launch proof unavailable")),
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    assert setup["emailWebhookUrl"].endswith("/api/internal/support/email/support-email?project_id=project1")
    assert setup["emailWebhookConfig"]["mode"] == "email_json_webhook"
    assert setup["emailWebhookConfig"]["payloadExample"]["email"]["messageId"] == "provider-message-123"
    assert setup["providerTokenEnv"] == "SUPPORT_EMAIL_WEBHOOK_TOKEN"
    assert setup["outboundDeliveryModes"] == ["smtp", "email_webhook"]
    assert setup["outboundWebhookUrlEnv"] == "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_URL"
    assert setup["outboundWebhookTokenEnv"] == "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_TOKEN"
    assert setup["launch"]["required"] is True
    assert setup["launch"]["ready"] is False
    assert setup["launch"]["passed"] == 0
    assert setup["launch"]["missing"] == 2
    assert setup["launch"]["failed"] == 1
    assert [item["key"] for item in setup["launchChecklist"]] == ["email_auth", "email_sync", "email_delivery"]
    assert setup["launchChecklist"][0]["status"] == "missing"
    assert setup["launchChecklist"][1]["status"] == "warning"
    assert setup["launchChecklist"][1]["detail"] == "Sync run did not record a created ticket"
    assert setup["launchChecklist"][1]["issueId"] == ""
    assert setup["launchChecklist"][2]["status"] == "missing"
    assert {item["key"] for item in setup["launch"]["blockers"]} == {"email_auth", "email_sync", "email_delivery"}


def test_admin_channels_uses_launch_proof_for_web_chat_setup(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "web-chat",
                "type": "chat",
                "name": "Web chat",
                "status": "active",
                "config": {"ticketCreationMode": "per_message"},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )
    monkeypatch.setattr("automail.api.admin.channels.list_channel_sync_runs", lambda **_kwargs: [])
    monkeypatch.setattr(
        "automail.api.admin.channels.support_launch_proof",
        lambda **_kwargs: {
            "channels": {
                "items": [
                    {
                        "channelId": "channel1",
                        "required": True,
                        "ready": False,
                        "checks": 2,
                        "passed": 1,
                        "lastCheckedAt": "2026-07-03T09:10:00+00:00",
                        "blockers": [
                            {
                                "key": "web_chat_delivery",
                                "label": "Web chat reply delivered",
                                "status": "missing",
                                "detail": "Send an Inbox web chat reply to prove replies reach visitors",
                                "runId": "",
                            }
                        ],
                        "checklist": [
                            {
                                "key": "web_chat_session",
                                "label": "Web chat session created",
                                "status": "done",
                                "detail": "open session linked to ticket issue1",
                                "runId": "session1",
                                "sessionId": "session1",
                                "source": "web_chat",
                                "runStatus": "open",
                                "processed": 1,
                                "failed": 0,
                                "sent": 0,
                                "startedAt": "2026-07-03T09:10:00+00:00",
                                "issueId": "issue1",
                            },
                            {
                                "key": "web_chat_delivery",
                                "label": "Web chat reply delivered",
                                "status": "missing",
                                "detail": "Send an Inbox web chat reply to prove replies reach visitors",
                                "runId": "",
                                "sessionId": "session1",
                                "source": "web_chat",
                                "runStatus": "",
                                "processed": 0,
                                "failed": 0,
                                "sent": 0,
                                "startedAt": "",
                                "issueId": "issue1",
                            },
                        ],
                    }
                ]
            }
        },
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    assert setup["launch"]["required"] is True
    assert setup["launch"]["ready"] is False
    assert setup["launch"]["passed"] == 1
    assert setup["launch"]["missing"] == 1
    assert setup["launch"]["blockers"][0]["key"] == "web_chat_delivery"
    assert setup["launch"]["blockers"][0]["action"] == "web_chat_delivery"
    assert [item["key"] for item in setup["launchChecklist"]] == ["web_chat_session", "web_chat_delivery"]
    assert setup["launchChecklist"][0]["sessionId"] == "session1"
    assert setup["launchChecklist"][1]["issueId"] == "issue1"


def test_admin_channels_slack_setup_accepts_channel_signature_env(client, monkeypatch):
    monkeypatch.delenv("SUPPORT_SLACK_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("SUPPORT_SLACK_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SYNC_TOKEN", raising=False)
    monkeypatch.setenv("ACME_SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "slack-main",
                "type": "slack",
                "name": "Slack",
                "status": "active",
                "config": {
                    "slackSigningSecretEnv": "ACME_SLACK_SIGNING_SECRET",
                    "outboundWebhookUrl": "https://adapter.example.com/slack",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    assert setup["signatureEnv"] == "ACME_SLACK_SIGNING_SECRET"
    assert setup["authConfigured"] is True
    assert setup["inboundReady"] is True
    assert any(env["name"] == "ACME_SLACK_SIGNING_SECRET" and env["required"] for env in setup["envVars"])


def test_admin_channels_slack_manifest_accepts_config_overrides(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "slack-main",
                "type": "slack",
                "name": "Slack",
                "status": "active",
                "config": {
                    "appDisplayName": "Acme Support",
                    "botDisplayName": "Acme Bot",
                    "oauthScopes": ["chat:write", "channels:history"],
                    "botEvents": ["message.channels"],
                    "outboundWebhookUrl": "https://slack.com/api/chat.postMessage",
                    "outboundWebhookTokenEnv": "SUPPORT_SLACK_BOT_TOKEN",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    manifest = resp.json()["items"][0]["setup"]["slackManifest"]
    assert manifest["display_information"]["name"] == "Acme Support"
    assert manifest["features"]["bot_user"]["display_name"] == "Acme Bot"
    assert manifest["oauth_config"]["scopes"]["bot"] == ["channels:history", "chat:write"]
    assert manifest["settings"]["event_subscriptions"]["bot_events"] == ["message.channels"]


def test_admin_channels_teams_setup_includes_bridge_config(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_TEAMS_WEBHOOK_TOKEN", "secret")
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "teams-main",
                "type": "teams",
                "name": "Teams",
                "status": "active",
                "config": {
                    "teamsAppIdEnv": "ACME_TEAMS_APP_ID",
                    "teamsAppPasswordEnv": "ACME_TEAMS_APP_PASSWORD",
                    "activityTypes": ["message"],
                    "outboundWebhookUrlEnv": "SUPPORT_TEAMS_OUTBOUND_URL",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    bridge_config = setup["teamsBridgeConfig"]
    assert bridge_config["mode"] == "bot_activity_bridge"
    assert bridge_config["sidecar"]["module"] == "automail.support.bridge_app"
    assert bridge_config["sidecar"]["publicPath"] == "/bridge/teams/teams-main"
    assert bridge_config["sidecar"]["env"]["SUPPORT_BRIDGE_TOKEN_ENV"] == "SUPPORT_TEAMS_WEBHOOK_TOKEN"
    assert bridge_config["botFramework"] == {
        "appIdEnv": "ACME_TEAMS_APP_ID",
        "appPasswordEnv": "ACME_TEAMS_APP_PASSWORD",
        "activityTypes": ["message"],
    }
    assert bridge_config["validation"]["urlTemplate"].endswith(
        "/api/internal/support/teams/teams-main?project_id=project1&validationToken={validationToken}"
    )
    assert bridge_config["forward"]["url"] == setup["providerWebhookUrl"]
    assert bridge_config["forward"]["headers"] == {"X-Support-Sync-Token": "${SUPPORT_TEAMS_WEBHOOK_TOKEN}"}
    assert bridge_config["forward"]["payloadWrapper"] == {
        "projectId": "project1",
        "payload": "<teams activity>",
    }
    assert bridge_config["payloadExample"]["type"] == "message"
    assert "validationToken" in bridge_config["notes"][2]
    assert "SUPPORT_TEAMS_WEBHOOK_TOKEN\": \"secret\"" not in json.dumps(bridge_config)
    assert setup["installPackage"]["teamsBridgeConfig"]["forward"]["url"] == setup["providerWebhookUrl"]


def test_admin_channels_teams_bridge_config_defaults(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "teams-main",
                "type": "teams",
                "name": "Teams",
                "status": "active",
                "config": {},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    bridge_config = resp.json()["items"][0]["setup"]["teamsBridgeConfig"]
    assert bridge_config["botFramework"]["appIdEnv"] == "SUPPORT_TEAMS_APP_ID"
    assert bridge_config["botFramework"]["appPasswordEnv"] == "SUPPORT_TEAMS_APP_PASSWORD"
    assert bridge_config["botFramework"]["activityTypes"] == ["message"]


def test_admin_channels_discord_setup_includes_bridge_config(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_DISCORD_WEBHOOK_TOKEN", "secret")
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "discord-main",
                "type": "discord",
                "name": "Discord",
                "status": "active",
                "config": {
                    "discordBotTokenEnv": "ACME_DISCORD_BOT_TOKEN",
                    "gatewayIntents": ["GuildMessages", "MessageContent"],
                    "gatewayEvents": ["MESSAGE_CREATE"],
                    "outboundWebhookUrlEnv": "SUPPORT_DISCORD_WEBHOOK_URL",
                    "outboundTransport": "bot",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    bridge_config = setup["discordBridgeConfig"]
    assert bridge_config["mode"] == "gateway_bridge"
    assert bridge_config["sidecar"]["module"] == "automail.support.bridge_app"
    assert bridge_config["sidecar"]["publicPath"] == "/bridge/discord/discord-main"
    assert bridge_config["sidecar"]["env"]["SUPPORT_BRIDGE_TOKEN_ENV"] == "SUPPORT_DISCORD_WEBHOOK_TOKEN"
    assert bridge_config["gatewayWorker"]["module"] == "automail.support.discord_gateway"
    assert bridge_config["gatewayWorker"]["command"] == "python -m automail.support.discord_gateway"
    assert bridge_config["gatewayWorker"]["env"]["SUPPORT_BRIDGE_DISCORD_CHANNEL_KEY"] == "discord-main"
    assert bridge_config["gatewayWorker"]["env"]["SUPPORT_BRIDGE_DISCORD_GATEWAY_EVENTS"] == "MESSAGE_CREATE"
    assert bridge_config["gatewayWorker"]["env"]["SUPPORT_BRIDGE_TOKEN_ENV"] == "SUPPORT_DISCORD_WEBHOOK_TOKEN"
    assert bridge_config["botTokenEnv"] == "ACME_DISCORD_BOT_TOKEN"
    assert bridge_config["gatewayIntents"] == ["GuildMessages", "MessageContent"]
    assert bridge_config["gatewayEvents"] == ["MESSAGE_CREATE"]
    assert bridge_config["forward"]["url"] == setup["providerWebhookUrl"]
    assert bridge_config["forward"]["headers"] == {"X-Support-Sync-Token": "${SUPPORT_DISCORD_WEBHOOK_TOKEN}"}
    assert bridge_config["forward"]["payloadWrapper"] == {
        "projectId": "project1",
        "payload": "<discord gateway event>",
    }
    assert bridge_config["payloadExample"]["t"] == "MESSAGE_CREATE"
    assert "Message Content intent" in bridge_config["notes"][1]
    assert setup["providerSteps"][0].startswith("Create a Discord bot")
    assert any("Gateway worker" in step for step in setup["providerSteps"])
    assert not any("execute-webhook" in step for step in setup["providerSteps"])
    assert setup["outboundTransport"] == "bot"
    assert setup["outboundBotTokenEnv"] == "ACME_DISCORD_BOT_TOKEN"
    assert "SUPPORT_DISCORD_WEBHOOK_TOKEN\": \"secret\"" not in json.dumps(bridge_config)
    assert setup["installPackage"]["discordBridgeConfig"]["forward"]["url"] == setup["providerWebhookUrl"]


def test_admin_channels_discord_bridge_config_defaults(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "discord-main",
                "type": "discord",
                "name": "Discord",
                "status": "active",
                "config": {},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    bridge_config = resp.json()["items"][0]["setup"]["discordBridgeConfig"]
    assert bridge_config["botTokenEnv"] == "SUPPORT_DISCORD_BOT_TOKEN"
    assert bridge_config["gatewayIntents"] == ["Guilds", "GuildMessages", "DirectMessages", "MessageContent"]
    assert bridge_config["gatewayEvents"] == ["MESSAGE_CREATE"]


def test_admin_channels_setup_reads_project_secrets(client, monkeypatch):
    monkeypatch.delenv("SUPPORT_SLACK_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_SLACK_OUTBOUND_URL", raising=False)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "ACME_SLACK_WEBHOOK_TOKEN": "stored-token",
            "SUPPORT_SLACK_OUTBOUND_URL": "https://adapter.example.com/slack",
        } if (tenant_id, project_id) == ("", "project1") else {},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "slack-main",
                "type": "slack",
                "name": "Slack",
                "status": "active",
                "config": {
                    "webhookTokenEnv": "ACME_SLACK_WEBHOOK_TOKEN",
                    "outboundWebhookUrlEnv": "SUPPORT_SLACK_OUTBOUND_URL",
                    "outboundWebhookTokenEnv": "SUPPORT_SLACK_OUTBOUND_TOKEN",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    assert setup["authConfigured"] is True
    assert setup["inboundReady"] is True
    assert setup["outboundReady"] is True
    assert setup["providerTokenEnv"] == "ACME_SLACK_WEBHOOK_TOKEN"
    assert any(env["name"] == "ACME_SLACK_WEBHOOK_TOKEN" and env["configured"] for env in setup["envVars"])
    assert any(env["name"] == "SUPPORT_SLACK_OUTBOUND_URL" and env["configured"] for env in setup["envVars"])


def test_admin_channel_validate_setup_reports_runtime_readiness(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_SLACK_WEBHOOK_TOKEN", "secret")
    monkeypatch.setenv("SUPPORT_SLACK_OUTBOUND_URL", "https://adapter.example.com/slack")
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "slack-main",
            "type": "slack",
            "name": "Slack",
            "status": "active",
            "config": {
                "outboundWebhookUrlEnv": "SUPPORT_SLACK_OUTBOUND_URL",
                "outboundWebhookTokenEnv": "SUPPORT_SLACK_OUTBOUND_TOKEN",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["ready"] is True
    assert body["summary"]["missing"] == 0
    assert body["summary"]["envConfigured"] >= 2
    assert body["setup"]["inboundReady"] is True
    assert body["setup"]["outboundReady"] is True
    assert any(check["key"] == "test" and check["status"] == "manual" for check in body["checks"])


def test_admin_channel_validate_setup_checks_slack_provider_token(client, monkeypatch):
    recorded: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "ok": True,
                "team": "Acme",
                "team_id": "T123",
                "user": "Support Bot",
                "user_id": "U123",
                "bot_id": "B123",
            }

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url: str, headers: dict):
            assert url == "https://slack.com/api/auth.test"
            assert headers == {"Authorization": "Bearer xoxb-secret"}
            return FakeResponse()

    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_SLACK_WEBHOOK_TOKEN": "inbound-token",
            "SUPPORT_SLACK_BOT_TOKEN": "xoxb-secret",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "slack-main",
            "type": "slack",
            "name": "Slack",
            "status": "active",
            "config": {
                "outboundWebhookUrl": "https://slack.com/api/chat.postMessage",
                "outboundWebhookTokenEnv": "SUPPORT_SLACK_BOT_TOKEN",
                "outboundTokenRequired": True,
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "validation-run-1", **kwargs},
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["runId"] == "validation-run-1"
    provider = body["providerValidation"]
    assert provider["provider"] == "slack"
    assert provider["status"] == "ready"
    assert provider["checked"] is True
    assert provider["identity"]["team_id"] == "T123"
    assert "xoxb-secret" not in str(provider)
    assert recorded[0]["channel_id"] == "channel1"
    assert recorded[0]["source"] == "admin-validation"
    assert recorded[0]["result"]["status"] == "success"
    assert recorded[0]["result"]["ready"] is True
    assert recorded[0]["result"]["processed"] == 1
    assert recorded[0]["result"]["failed"] == 0
    assert recorded[0]["result"]["providerValidation"]["status"] == "ready"


def test_admin_channel_validate_setup_fails_on_telegram_provider_error(client, monkeypatch):
    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"ok": False, "description": "Unauthorized"}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str):
            assert url == "https://api.telegram.org/bottelegram-secret/getMe"
            return FakeResponse()

    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_TELEGRAM_WEBHOOK_TOKEN": "inbound-token",
            "SUPPORT_TELEGRAM_BOT_TOKEN": "telegram-secret",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "telegram-main",
            "type": "telegram",
            "name": "Telegram",
            "status": "active",
            "config": {
                "outboundWebhookUrlTemplate": "https://api.telegram.org/bot{SUPPORT_TELEGRAM_BOT_TOKEN}/sendMessage",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is False
    provider = body["providerValidation"]
    assert provider["provider"] == "telegram"
    assert provider["status"] == "failed"
    assert provider["checked"] is True
    assert provider["detail"] == "Unauthorized"


def test_admin_channel_validate_setup_checks_whatsapp_cloud_api(client, monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "id": "phone-1",
                "display_phone_number": "+15550001111",
                "verified_name": "Acme Support",
                "quality_rating": "GREEN",
            }

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse()

    recorded: list[dict] = []
    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_WHATSAPP_VERIFY_TOKEN": "verify-token",
            "SUPPORT_WHATSAPP_APP_SECRET": "app-secret",
            "SUPPORT_WHATSAPP_PHONE_NUMBER_ID": "phone-1",
            "SUPPORT_WHATSAPP_ACCESS_TOKEN": "whatsapp-secret",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "whatsapp-main",
            "type": "whatsapp",
            "name": "WhatsApp",
            "status": "active",
            "config": {
                "whatsappSigningSecretEnv": "SUPPORT_WHATSAPP_APP_SECRET",
                "verifyTokenEnv": "SUPPORT_WHATSAPP_VERIFY_TOKEN",
                "phoneNumberIdEnv": "SUPPORT_WHATSAPP_PHONE_NUMBER_ID",
                "outboundWebhookUrlTemplate": "https://graph.facebook.com/v20.0/{SUPPORT_WHATSAPP_PHONE_NUMBER_ID}/messages",
                "outboundWebhookTokenEnv": "SUPPORT_WHATSAPP_ACCESS_TOKEN",
                "outboundPayloadMode": "whatsapp",
                "outboundTokenRequired": True,
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "validation-run-whatsapp", **kwargs},
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["runId"] == "validation-run-whatsapp"
    provider = body["providerValidation"]
    assert provider["provider"] == "whatsapp"
    assert provider["status"] == "ready"
    assert provider["checked"] is True
    assert provider["identity"]["id"] == "phone-1"
    assert provider["identity"]["verified_name"] == "Acme Support"
    assert captured["url"] == "https://graph.facebook.com/v20.0/phone-1"
    assert captured["kwargs"]["headers"] == {"Authorization": "Bearer whatsapp-secret"}
    assert captured["kwargs"]["params"] == {"fields": "id,display_phone_number,verified_name,quality_rating"}
    assert "whatsapp-secret" not in str(provider)
    assert recorded[0]["result"]["providerValidation"]["status"] == "ready"


def test_admin_channel_validate_setup_checks_messenger_graph_api(client, monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"id": "page-1", "name": "Acme Support", "username": "acme-support"}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse()

    recorded: list[dict] = []
    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_MESSENGER_VERIFY_TOKEN": "verify-token",
            "SUPPORT_MESSENGER_APP_SECRET": "app-secret",
            "SUPPORT_MESSENGER_PAGE_ID": "page-1",
            "SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN": "messenger-secret",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "messenger-main",
            "type": "messenger",
            "name": "Messenger",
            "status": "active",
            "config": {
                "messengerSigningSecretEnv": "SUPPORT_MESSENGER_APP_SECRET",
                "verifyTokenEnv": "SUPPORT_MESSENGER_VERIFY_TOKEN",
                "pageIdEnv": "SUPPORT_MESSENGER_PAGE_ID",
                "outboundWebhookTokenEnv": "SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN",
                "outboundTransport": "messenger",
                "outboundPayloadMode": "messenger",
                "outboundTokenRequired": True,
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "validation-run-messenger", **kwargs},
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["runId"] == "validation-run-messenger"
    provider = body["providerValidation"]
    assert provider["provider"] == "messenger"
    assert provider["status"] == "ready"
    assert provider["checked"] is True
    assert provider["identity"]["id"] == "page-1"
    assert provider["identity"]["name"] == "Acme Support"
    assert captured["url"] == "https://graph.facebook.com/v20.0/page-1"
    assert captured["kwargs"]["headers"] == {"Authorization": "Bearer messenger-secret"}
    assert captured["kwargs"]["params"] == {"fields": "id,name,username,category"}
    assert "messenger-secret" not in str(provider)
    assert recorded[0]["result"]["providerValidation"]["status"] == "ready"


def test_admin_channel_validate_setup_checks_instagram_graph_api(client, monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"id": "ig-1", "username": "acme_support", "name": "Acme Support"}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse()

    recorded: list[dict] = []
    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_INSTAGRAM_VERIFY_TOKEN": "verify-token",
            "SUPPORT_INSTAGRAM_APP_SECRET": "app-secret",
            "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID": "ig-1",
            "SUPPORT_INSTAGRAM_ACCESS_TOKEN": "instagram-secret",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "instagram-main",
            "type": "instagram",
            "name": "Instagram DM",
            "status": "active",
            "config": {
                "instagramSigningSecretEnv": "SUPPORT_INSTAGRAM_APP_SECRET",
                "verifyTokenEnv": "SUPPORT_INSTAGRAM_VERIFY_TOKEN",
                "instagramAccountIdEnv": "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID",
                "instagramAccessTokenEnv": "SUPPORT_INSTAGRAM_ACCESS_TOKEN",
                "outboundTransport": "instagram",
                "outboundWebhookTokenEnv": "SUPPORT_INSTAGRAM_ACCESS_TOKEN",
                "outboundPayloadMode": "instagram",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "validation-run-instagram", **kwargs},
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["runId"] == "validation-run-instagram"
    provider = body["providerValidation"]
    assert provider["provider"] == "instagram"
    assert provider["status"] == "ready"
    assert provider["checked"] is True
    assert provider["identity"]["id"] == "ig-1"
    assert provider["identity"]["username"] == "acme_support"
    assert captured["url"] == "https://graph.facebook.com/v20.0/ig-1"
    assert captured["kwargs"]["headers"] == {"Authorization": "Bearer instagram-secret"}
    assert captured["kwargs"]["params"] == {"fields": "id,username,name"}
    assert "instagram-secret" not in str(provider)
    assert recorded[0]["result"]["providerValidation"]["status"] == "ready"


def test_admin_channel_validate_setup_checks_twitter_api(client, monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"data": {"id": "4337869213", "name": "Acme Support", "username": "acme_support"}}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse()

    recorded: list[dict] = []
    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_X_CONSUMER_SECRET": "consumer-secret",
            "SUPPORT_X_BEARER_TOKEN": "bearer-secret",
            "SUPPORT_X_USER_ACCESS_TOKEN": "user-secret",
            "SUPPORT_X_USER_ID": "4337869213",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "twitter-main",
            "type": "twitter",
            "name": "X DM",
            "status": "active",
            "config": {
                "twitterConsumerSecretEnv": "SUPPORT_X_CONSUMER_SECRET",
                "twitterBearerTokenEnv": "SUPPORT_X_BEARER_TOKEN",
                "twitterUserAccessTokenEnv": "SUPPORT_X_USER_ACCESS_TOKEN",
                "twitterUserIdEnv": "SUPPORT_X_USER_ID",
                "outboundTransport": "twitter",
                "outboundWebhookTokenEnv": "SUPPORT_X_USER_ACCESS_TOKEN",
                "outboundPayloadMode": "twitter",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "validation-run-twitter", **kwargs},
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["runId"] == "validation-run-twitter"
    provider = body["providerValidation"]
    assert provider["provider"] == "twitter"
    assert provider["status"] == "ready"
    assert provider["checked"] is True
    assert provider["identity"]["id"] == "4337869213"
    assert provider["identity"]["username"] == "acme_support"
    assert captured["url"] == "https://api.x.com/2/users/4337869213"
    assert captured["kwargs"]["headers"] == {"Authorization": "Bearer bearer-secret"}
    assert captured["kwargs"]["params"] == {"user.fields": "id,name,username"}
    assert "bearer-secret" not in str(provider)
    assert recorded[0]["result"]["providerValidation"]["status"] == "ready"


def test_admin_channel_validate_setup_checks_line_bot_info(client, monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"userId": "Ubot123", "basicId": "@acme", "displayName": "Acme Support"}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse()

    recorded: list[dict] = []
    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_LINE_CHANNEL_SECRET": "line-secret",
            "SUPPORT_LINE_CHANNEL_ACCESS_TOKEN": "line-access-token",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "line-main",
            "type": "line",
            "name": "LINE",
            "status": "active",
            "config": {
                "lineChannelSecretEnv": "SUPPORT_LINE_CHANNEL_SECRET",
                "lineChannelAccessTokenEnv": "SUPPORT_LINE_CHANNEL_ACCESS_TOKEN",
                "outboundPayloadMode": "line",
                "outboundTransport": "line",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "validation-run-line", **kwargs},
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["runId"] == "validation-run-line"
    provider = body["providerValidation"]
    assert provider["provider"] == "line"
    assert provider["status"] == "ready"
    assert provider["checked"] is True
    assert provider["identity"]["userId"] == "Ubot123"
    assert provider["identity"]["displayName"] == "Acme Support"
    assert captured["url"] == "https://api.line.me/v2/bot/info"
    assert captured["kwargs"]["headers"] == {"Authorization": "Bearer line-access-token"}
    assert "line-access-token" not in str(provider)
    assert recorded[0]["result"]["providerValidation"]["status"] == "ready"


def test_admin_channel_validate_setup_checks_viber_account_info(client, monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "status": 0,
                "status_message": "ok",
                "id": "pa:123",
                "name": "Acme Support",
                "uri": "acme-support",
            }

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url: str, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse()

    recorded: list[dict] = []
    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_VIBER_AUTH_TOKEN": "viber-auth-token",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "viber-main",
            "type": "viber",
            "name": "Viber",
            "status": "active",
            "config": {
                "viberAuthTokenEnv": "SUPPORT_VIBER_AUTH_TOKEN",
                "outboundPayloadMode": "viber",
                "outboundTransport": "viber",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "validation-run-viber", **kwargs},
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["runId"] == "validation-run-viber"
    provider = body["providerValidation"]
    assert provider["provider"] == "viber"
    assert provider["status"] == "ready"
    assert provider["checked"] is True
    assert provider["identity"]["id"] == "pa:123"
    assert provider["identity"]["name"] == "Acme Support"
    assert captured["url"] == "https://chatapi.viber.com/pa/get_account_info"
    assert captured["kwargs"]["headers"] == {"X-Viber-Auth-Token": "viber-auth-token"}
    assert captured["kwargs"]["json"] == {}
    assert "viber-auth-token" not in str(provider)
    assert recorded[0]["result"]["providerValidation"]["status"] == "ready"


def test_admin_channel_validate_setup_requires_whatsapp_cloud_api_env(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_WHATSAPP_VERIFY_TOKEN": "verify-token",
            "SUPPORT_WHATSAPP_APP_SECRET": "app-secret",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "whatsapp-main",
            "type": "whatsapp",
            "name": "WhatsApp",
            "status": "active",
            "config": {
                "whatsappSigningSecretEnv": "SUPPORT_WHATSAPP_APP_SECRET",
                "verifyTokenEnv": "SUPPORT_WHATSAPP_VERIFY_TOKEN",
                "phoneNumberIdEnv": "SUPPORT_WHATSAPP_PHONE_NUMBER_ID",
                "outboundWebhookUrlTemplate": "https://graph.facebook.com/v20.0/{SUPPORT_WHATSAPP_PHONE_NUMBER_ID}/messages",
                "outboundWebhookTokenEnv": "SUPPORT_WHATSAPP_ACCESS_TOKEN",
                "outboundPayloadMode": "whatsapp",
                "outboundTokenRequired": True,
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is False
    provider = body["providerValidation"]
    assert provider["provider"] == "whatsapp"
    assert provider["status"] == "skipped"
    assert provider["checked"] is False
    assert provider["required"] is True
    assert provider["envVars"] == ["SUPPORT_WHATSAPP_ACCESS_TOKEN", "SUPPORT_WHATSAPP_PHONE_NUMBER_ID"]


def test_admin_channel_validate_setup_checks_twilio_credentials(client, monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "sid": "AC123",
                "friendly_name": "Acme Twilio",
                "status": "active",
                "type": "Full",
            }

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse()

    recorded: list[dict] = []
    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_TWILIO_WEBHOOK_TOKEN": "inbound-token",
            "SUPPORT_TWILIO_ACCOUNT_SID": "AC123",
            "SUPPORT_TWILIO_AUTH_TOKEN": "auth-token",
            "SUPPORT_TWILIO_FROM_NUMBER": "+15550001111",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "sms-main",
            "type": "sms",
            "name": "SMS",
            "status": "active",
            "config": {
                "accountSidEnv": "SUPPORT_TWILIO_ACCOUNT_SID",
                "authTokenEnv": "SUPPORT_TWILIO_AUTH_TOKEN",
                "fromNumberEnv": "SUPPORT_TWILIO_FROM_NUMBER",
                "outboundPayloadMode": "provider",
                "outboundTransport": "twilio",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "validation-run-sms", **kwargs},
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["runId"] == "validation-run-sms"
    provider = body["providerValidation"]
    assert provider["provider"] == "sms"
    assert provider["status"] == "ready"
    assert provider["identity"]["sid"] == "AC123"
    assert provider["identity"]["sender"] == "+15550001111"
    assert captured["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC123.json"
    assert captured["kwargs"]["auth"] == ("AC123", "auth-token")
    assert "auth-token" not in str(provider)
    assert recorded[0]["result"]["providerValidation"]["status"] == "ready"


def test_admin_channels_sms_setup_exposes_sms_alias(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_TWILIO_WEBHOOK_TOKEN": "inbound-token",
            "SUPPORT_TWILIO_ACCOUNT_SID": "AC123",
            "SUPPORT_TWILIO_AUTH_TOKEN": "auth-token",
            "SUPPORT_TWILIO_FROM_NUMBER": "+15550001111",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "sms-main",
                "type": "sms",
                "name": "SMS",
                "status": "active",
                "config": {
                    "accountSidEnv": "SUPPORT_TWILIO_ACCOUNT_SID",
                    "authTokenEnv": "SUPPORT_TWILIO_AUTH_TOKEN",
                    "fromNumberEnv": "SUPPORT_TWILIO_FROM_NUMBER",
                    "outboundTransport": "twilio",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    assert setup["providerWebhookUrl"].endswith("/api/internal/support/twilio/sms-main?project_id=project1")
    assert setup["smsWebhookUrl"].endswith("/api/internal/support/sms/sms-main?project_id=project1")
    assert setup["smsWebhookPath"] == "/api/internal/support/sms/sms-main"
    twilio_config = setup["twilioWebhookConfig"]
    assert twilio_config["webhookUrl"] == setup["providerWebhookUrl"]
    assert twilio_config["smsWebhookUrl"] == setup["smsWebhookUrl"]
    assert twilio_config["alternateWebhookUrls"] == [setup["smsWebhookUrl"]]
    assert twilio_config["incomingMessage"]["url"] == setup["smsWebhookUrl"]
    assert twilio_config["incomingMessage"]["providerUrl"] == setup["providerWebhookUrl"]
    install_package = setup["installPackage"]
    assert install_package["inbound"]["primaryUrl"] == setup["providerWebhookUrl"]
    assert install_package["inbound"]["smsWebhookUrl"] == setup["smsWebhookUrl"]
    assert install_package["twilioWebhookConfig"]["smsWebhookUrl"] == setup["smsWebhookUrl"]


def test_admin_channel_validate_setup_requires_twilio_env(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {"SUPPORT_TWILIO_WEBHOOK_TOKEN": "inbound-token"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "sms-main",
            "type": "sms",
            "name": "SMS",
            "status": "active",
            "config": {
                "accountSidEnv": "SUPPORT_TWILIO_ACCOUNT_SID",
                "authTokenEnv": "SUPPORT_TWILIO_AUTH_TOKEN",
                "fromNumberEnv": "SUPPORT_TWILIO_FROM_NUMBER",
                "outboundPayloadMode": "provider",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    provider = resp.json()["providerValidation"]
    assert provider["provider"] == "sms"
    assert provider["status"] == "skipped"
    assert provider["checked"] is False
    assert provider["required"] is True
    assert provider["envVars"] == [
        "SUPPORT_TWILIO_ACCOUNT_SID",
        "SUPPORT_TWILIO_AUTH_TOKEN",
        "SUPPORT_TWILIO_FROM_NUMBER",
        "SUPPORT_TWILIO_MESSAGING_SERVICE_SID",
    ]


def test_admin_channel_validate_setup_checks_teams_bot_credentials(client, monkeypatch):
    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "access_token": "teams-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url: str, data: dict):
            assert url == "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
            assert data == {
                "grant_type": "client_credentials",
                "client_id": "teams-app-id",
                "client_secret": "teams-app-password",
                "scope": "https://api.botframework.com/.default",
            }
            return FakeResponse()

    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_TEAMS_WEBHOOK_TOKEN": "inbound-token",
            "SUPPORT_TEAMS_APP_ID": "teams-app-id",
            "SUPPORT_TEAMS_APP_PASSWORD": "teams-app-password",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "teams-main",
            "type": "teams",
            "name": "Teams",
            "status": "active",
            "config": {
                "outboundWebhookUrl": "https://adapter.example.com/teams",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    provider = body["providerValidation"]
    assert provider["provider"] == "teams"
    assert provider["status"] == "ready"
    assert provider["checked"] is True
    assert provider["identity"] == {
        "appId": "teams-app-id",
        "tokenType": "Bearer",
        "expiresIn": 3600,
    }
    assert "teams-app-password" not in str(provider)


def test_admin_channel_validate_setup_blocks_missing_teams_bot_credentials(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_TEAMS_WEBHOOK_TOKEN": "inbound-token",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "teams-main",
            "type": "teams",
            "name": "Teams",
            "status": "active",
            "config": {
                "outboundWebhookUrl": "https://adapter.example.com/teams",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is False
    provider = body["providerValidation"]
    assert provider["provider"] == "teams"
    assert provider["status"] == "skipped"
    assert provider["checked"] is False
    assert provider["required"] is True
    assert provider["envVars"] == ["SUPPORT_TEAMS_APP_ID", "SUPPORT_TEAMS_APP_PASSWORD"]
    assert "Teams app credential env missing" in provider["detail"]
    assert body["summary"]["envMissing"] >= 2


def test_admin_channel_validate_setup_checks_discord_bot_token(client, monkeypatch):
    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"id": "bot123", "username": "support-bot", "global_name": "Support Bot"}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url: str, headers: dict | None = None):
            assert url == "https://discord.com/api/v10/users/@me"
            assert headers == {"Authorization": "Bot discord-secret"}
            return FakeResponse()

    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_DISCORD_WEBHOOK_TOKEN": "inbound-token",
            "SUPPORT_DISCORD_BOT_TOKEN": "discord-secret",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "discord-main",
            "type": "discord",
            "name": "Discord",
            "status": "active",
            "config": {
                "discordBotTokenEnv": "SUPPORT_DISCORD_BOT_TOKEN",
                "outboundTransport": "bot",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    provider = body["providerValidation"]
    assert provider["provider"] == "discord"
    assert provider["status"] == "ready"
    assert provider["checked"] is True
    assert provider["identity"] == {
        "id": "bot123",
        "username": "support-bot",
        "global_name": "Support Bot",
    }
    assert "discord-secret" not in str(provider)


def test_admin_channel_validate_setup_blocks_missing_discord_bot_token(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_DISCORD_WEBHOOK_TOKEN": "inbound-token",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "discord-main",
            "type": "discord",
            "name": "Discord",
            "status": "active",
            "config": {
                "outboundTransport": "bot",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/validate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is False
    provider = body["providerValidation"]
    assert provider["provider"] == "discord"
    assert provider["status"] == "skipped"
    assert provider["checked"] is False
    assert provider["required"] is True
    assert provider["envVars"] == ["SUPPORT_DISCORD_BOT_TOKEN"]
    assert "Discord bot token env missing" in provider["detail"]


def test_admin_channels_slack_direct_provider_requires_bot_token(client, monkeypatch):
    monkeypatch.setenv("SUPPORT_SLACK_WEBHOOK_TOKEN", "secret")
    monkeypatch.delenv("SUPPORT_SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "slack-main",
                "type": "slack",
                "name": "Slack",
                "status": "active",
                "config": {
                    "outboundWebhookUrl": "https://slack.com/api/chat.postMessage",
                    "outboundWebhookTokenEnv": "SUPPORT_SLACK_BOT_TOKEN",
                    "outboundTokenRequired": True,
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            }
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    setup = resp.json()["items"][0]["setup"]
    assert setup["outboundWebhookUrl"] == "https://slack.com/api/chat.postMessage"
    assert setup["outboundWebhookTokenEnv"] == "SUPPORT_SLACK_BOT_TOKEN"
    assert setup["outboundTokenRequired"] is True
    assert setup["outboundReady"] is False
    assert setup["health"]["status"] == "degraded"
    assert setup["health"]["requiredMissingEnvVars"] == ["SUPPORT_SLACK_BOT_TOKEN"]
    assert any(
        env["name"] == "SUPPORT_SLACK_BOT_TOKEN" and env["required"] and not env["configured"]
        for env in setup["envVars"]
    )
    assert any(check["key"] == "outbound" and check["detail"] == "Outbound token env missing" for check in setup["setupChecklist"])


def test_admin_channel_configure_telegram_webhook(client, monkeypatch):
    posted: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"ok": True, "result": True, "description": "Webhook was set"}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url: str, json: dict):
            posted["url"] = url
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_TELEGRAM_BOT_TOKEN": "telegram-bot-token",
            "ACME_TELEGRAM_SECRET": "Secret_123",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "telegram-main",
            "type": "telegram",
            "name": "Telegram",
            "status": "active",
            "config": {
                "telegramSecretTokenEnv": "ACME_TELEGRAM_SECRET",
                "outboundWebhookUrlTemplate": "https://api.telegram.org/bot{SUPPORT_TELEGRAM_BOT_TOKEN}/sendMessage",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/telegram/webhook",
        json={"allowedUpdates": ["message"], "dropPendingUpdates": True},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "configured"
    assert body["webhookUrl"].endswith("/api/internal/support/telegram/telegram-main?project_id=project1")
    assert body["botTokenEnv"] == "SUPPORT_TELEGRAM_BOT_TOKEN"
    assert body["secretTokenEnv"] == "ACME_TELEGRAM_SECRET"
    assert body["allowedUpdates"] == ["message"]
    assert body["telegram"] == {"ok": True, "result": True, "description": "Webhook was set"}
    assert posted["url"] == "https://api.telegram.org/bottelegram-bot-token/setWebhook"
    assert posted["json"] == {
        "url": body["webhookUrl"],
        "secret_token": "Secret_123",
        "drop_pending_updates": True,
        "allowed_updates": ["message"],
    }
    assert "telegram-bot-token" not in json.dumps(body)
    assert "Secret_123" not in json.dumps(body)


def test_admin_channel_configure_telegram_webhook_requires_secret_token(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {"SUPPORT_TELEGRAM_BOT_TOKEN": "telegram-bot-token"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "telegram-main",
            "type": "telegram",
            "name": "Telegram",
            "status": "active",
            "config": {
                "outboundWebhookUrlTemplate": "https://api.telegram.org/bot{SUPPORT_TELEGRAM_BOT_TOKEN}/sendMessage",
            },
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        },
    )

    resp = client.post("/api/admin/projects/project1/channels/channel1/telegram/webhook", json={})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Telegram secret token env missing: SUPPORT_TELEGRAM_SECRET_TOKEN"


def test_admin_channel_presets_include_provider_defaults(client):
    resp = client.get("/api/admin/projects/project1/channels/presets")

    assert resp.status_code == 200
    presets = {item["type"]: item for item in resp.json()["items"]}
    assert set(presets) >= {"email", "slack", "teams", "discord", "telegram", "line", "viber", "whatsapp", "messenger", "sms", "chat", "webhook"}
    for preset in presets.values():
        assert preset["ticketCreationMode"] == "per_message"
        assert preset["config"]["ticketCreationMode"] == "per_message"
        assert preset["autoPrepareTriage"] is True
        assert preset["autoPrepareCustomFields"] is True
        assert preset["autoPrepareAgentReply"] is True
        assert preset["autoPrepareAgentReplyOnUpdate"] is True
        assert preset["agentAutoSend"] is False
        assert preset["config"]["autoPrepareTriage"] is True
        assert preset["config"]["autoPrepareCustomFields"] is True
        assert preset["config"]["autoPrepareAgentReply"] is True
        assert preset["config"]["autoPrepareAgentReplyOnUpdate"] is True
        assert preset["config"]["agentAutoSend"] is False
        assert preset["supportDefaults"] == {
            "ticketCreation": "new_ticket_per_message",
            "autopilotPrep": ["triage", "custom_fields", "approval_draft"],
            "humanReview": True,
        }

    slack = presets["slack"]
    assert slack["channelKey"] == "slack-main"
    assert slack["outboundPayloadMode"] == "provider"
    assert slack["outboundWebhookUrlEnv"] == ""
    assert slack["outboundWebhookTokenEnv"] == ""
    assert slack["config"]["adapter"] == "slack"
    assert slack["config"]["ticketCreationMode"] == "per_message"
    assert slack["config"]["outboundTransport"] == "bot"
    assert slack["config"]["slackBotTokenEnv"] == "SUPPORT_SLACK_BOT_TOKEN"
    assert slack["config"]["outboundTokenRequired"] is True
    assert any(env["name"] == "SUPPORT_SLACK_SIGNING_SECRET" for env in slack["authEnvVars"])
    assert any(env["name"] == "SUPPORT_SLACK_WEBHOOK_TOKEN" for env in slack["authEnvVars"])
    assert any(env["name"] == "SUPPORT_SLACK_BOT_TOKEN" and env["required"] for env in slack["outboundEnvVars"])

    teams = presets["teams"]
    assert teams["outboundWebhookUrlEnv"] == ""
    assert teams["outboundWebhookTokenEnv"] == ""
    assert teams["config"]["outboundTransport"] == "bot"
    assert teams["config"]["teamsAppIdEnv"] == "SUPPORT_TEAMS_APP_ID"
    assert teams["config"]["teamsAppPasswordEnv"] == "SUPPORT_TEAMS_APP_PASSWORD"
    assert any(env["name"] == "SUPPORT_TEAMS_APP_ID" and env["required"] for env in teams["authEnvVars"])
    assert any(env["name"] == "SUPPORT_TEAMS_APP_PASSWORD" and env["required"] for env in teams["outboundEnvVars"])

    discord = presets["discord"]
    assert discord["outboundWebhookUrlEnv"] == ""
    assert discord["outboundWebhookTokenEnv"] == ""
    assert discord["config"]["outboundTransport"] == "bot"
    assert discord["config"]["discordBotTokenEnv"] == "SUPPORT_DISCORD_BOT_TOKEN"
    assert discord["outboundEnvVars"] == [
        {"name": "SUPPORT_DISCORD_BOT_TOKEN", "purpose": "Discord bot token with Send Messages", "required": True}
    ]
    assert any(env["name"] == "SUPPORT_DISCORD_BOT_TOKEN" and env["required"] for env in discord["authEnvVars"])

    telegram = presets["telegram"]
    assert telegram["outboundWebhookUrlEnv"] == ""
    assert telegram["outboundWebhookTokenEnv"] == ""
    assert telegram["config"]["outboundTransport"] == "bot"
    assert telegram["config"]["botTokenEnv"] == "SUPPORT_TELEGRAM_BOT_TOKEN"
    assert any(env["name"] == "SUPPORT_TELEGRAM_BOT_TOKEN" and env["required"] for env in telegram["outboundEnvVars"])

    line = presets["line"]
    assert line["channelKey"] == "line-main"
    assert line["outboundWebhookUrlEnv"] == ""
    assert line["outboundWebhookTokenEnv"] == "SUPPORT_LINE_CHANNEL_ACCESS_TOKEN"
    assert line["config"]["adapter"] == "line"
    assert line["config"]["outboundPayloadMode"] == "line"
    assert line["config"]["outboundTransport"] == "line"
    assert line["config"]["lineChannelSecretEnv"] == "SUPPORT_LINE_CHANNEL_SECRET"
    assert line["config"]["lineChannelAccessTokenEnv"] == "SUPPORT_LINE_CHANNEL_ACCESS_TOKEN"
    assert line["config"]["signatureHeader"] == "X-Line-Signature"
    assert any(env["name"] == "SUPPORT_LINE_CHANNEL_SECRET" and env["required"] for env in line["authEnvVars"])
    assert any(env["name"] == "SUPPORT_LINE_CHANNEL_ACCESS_TOKEN" and env["required"] for env in line["outboundEnvVars"])

    viber = presets["viber"]
    assert viber["channelKey"] == "viber-main"
    assert viber["outboundWebhookUrlEnv"] == ""
    assert viber["outboundWebhookTokenEnv"] == "SUPPORT_VIBER_AUTH_TOKEN"
    assert viber["config"]["adapter"] == "viber"
    assert viber["config"]["outboundPayloadMode"] == "viber"
    assert viber["config"]["outboundTransport"] == "viber"
    assert viber["config"]["viberAuthTokenEnv"] == "SUPPORT_VIBER_AUTH_TOKEN"
    assert viber["config"]["signatureHeader"] == "X-Viber-Content-Signature"
    assert any(env["name"] == "SUPPORT_VIBER_AUTH_TOKEN" and env["required"] for env in viber["authEnvVars"])
    assert any(env["name"] == "SUPPORT_VIBER_AUTH_TOKEN" and env["required"] for env in viber["outboundEnvVars"])

    whatsapp = presets["whatsapp"]
    assert whatsapp["outboundWebhookUrlEnv"] == ""
    assert whatsapp["outboundWebhookTokenEnv"] == "SUPPORT_WHATSAPP_ACCESS_TOKEN"
    assert whatsapp["config"]["outboundPayloadMode"] == "whatsapp"
    assert whatsapp["config"]["outboundTransport"] == "whatsapp"
    assert whatsapp["config"]["whatsappSigningSecretEnv"] == "SUPPORT_WHATSAPP_APP_SECRET"
    assert whatsapp["config"]["verifyTokenEnv"] == "SUPPORT_WHATSAPP_VERIFY_TOKEN"
    assert whatsapp["config"]["outboundWebhookUrlTemplate"] == (
        "https://graph.facebook.com/v20.0/{SUPPORT_WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    assert any(env["name"] == "SUPPORT_WHATSAPP_VERIFY_TOKEN" and env["required"] for env in whatsapp["authEnvVars"])
    assert any(env["name"] == "SUPPORT_WHATSAPP_PHONE_NUMBER_ID" and env["required"] for env in whatsapp["outboundEnvVars"])
    assert any(env["name"] == "SUPPORT_WHATSAPP_ACCESS_TOKEN" and env["required"] for env in whatsapp["outboundEnvVars"])

    messenger = presets["messenger"]
    assert messenger["outboundWebhookUrlEnv"] == ""
    assert messenger["outboundWebhookTokenEnv"] == "SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN"
    assert messenger["config"]["outboundPayloadMode"] == "messenger"
    assert messenger["config"]["outboundTransport"] == "messenger"
    assert messenger["config"]["messengerSigningSecretEnv"] == "SUPPORT_MESSENGER_APP_SECRET"
    assert messenger["config"]["verifyTokenEnv"] == "SUPPORT_MESSENGER_VERIFY_TOKEN"
    assert messenger["config"]["outboundWebhookUrlTemplate"] == (
        "https://graph.facebook.com/v20.0/{SUPPORT_MESSENGER_PAGE_ID}/messages"
    )
    assert any(env["name"] == "SUPPORT_MESSENGER_VERIFY_TOKEN" and env["required"] for env in messenger["authEnvVars"])
    assert any(env["name"] == "SUPPORT_MESSENGER_PAGE_ID" and env["required"] for env in messenger["outboundEnvVars"])
    assert any(env["name"] == "SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN" and env["required"] for env in messenger["outboundEnvVars"])

    instagram = presets["instagram"]
    assert instagram["outboundWebhookUrlEnv"] == ""
    assert instagram["outboundWebhookTokenEnv"] == "SUPPORT_INSTAGRAM_ACCESS_TOKEN"
    assert instagram["config"]["outboundPayloadMode"] == "instagram"
    assert instagram["config"]["outboundTransport"] == "instagram"
    assert instagram["config"]["instagramSigningSecretEnv"] == "SUPPORT_INSTAGRAM_APP_SECRET"
    assert instagram["config"]["verifyTokenEnv"] == "SUPPORT_INSTAGRAM_VERIFY_TOKEN"
    assert instagram["config"]["outboundWebhookUrlTemplate"] == (
        "https://graph.facebook.com/v20.0/{SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID}/messages"
    )
    assert any(env["name"] == "SUPPORT_INSTAGRAM_VERIFY_TOKEN" and env["required"] for env in instagram["authEnvVars"])
    assert any(env["name"] == "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID" and env["required"] for env in instagram["outboundEnvVars"])
    assert any(env["name"] == "SUPPORT_INSTAGRAM_ACCESS_TOKEN" and env["required"] for env in instagram["outboundEnvVars"])

    twitter = presets["twitter"]
    assert twitter["outboundWebhookUrlEnv"] == ""
    assert twitter["outboundWebhookTokenEnv"] == "SUPPORT_X_USER_ACCESS_TOKEN"
    assert twitter["config"]["outboundPayloadMode"] == "twitter"
    assert twitter["config"]["outboundTransport"] == "twitter"
    assert twitter["config"]["twitterConsumerSecretEnv"] == "SUPPORT_X_CONSUMER_SECRET"
    assert twitter["config"]["twitterBearerTokenEnv"] == "SUPPORT_X_BEARER_TOKEN"
    assert twitter["config"]["twitterUserAccessTokenEnv"] == "SUPPORT_X_USER_ACCESS_TOKEN"
    assert twitter["config"]["twitterUserIdEnv"] == "SUPPORT_X_USER_ID"
    assert any(env["name"] == "SUPPORT_X_CONSUMER_SECRET" and env["required"] for env in twitter["authEnvVars"])
    assert any(env["name"] == "SUPPORT_X_BEARER_TOKEN" and env["required"] for env in twitter["outboundEnvVars"])
    assert any(env["name"] == "SUPPORT_X_USER_ACCESS_TOKEN" and env["required"] for env in twitter["outboundEnvVars"])

    sms = presets["sms"]
    assert sms["channelKey"] == "sms-main"
    assert sms["providerName"] == "SMS"
    assert sms["outboundWebhookUrlEnv"] == ""
    assert sms["outboundWebhookTokenEnv"] == ""
    assert sms["config"]["adapter"] == "sms"
    assert sms["config"]["provider"] == "twilio"
    assert sms["config"]["accountSidEnv"] == "SUPPORT_TWILIO_ACCOUNT_SID"
    assert sms["config"]["authTokenEnv"] == "SUPPORT_TWILIO_AUTH_TOKEN"
    assert sms["config"]["fromNumberEnv"] == "SUPPORT_TWILIO_FROM_NUMBER"
    assert sms["config"]["messagingServiceSidEnv"] == "SUPPORT_TWILIO_MESSAGING_SERVICE_SID"
    assert sms["config"]["outboundTransport"] == "twilio"
    assert any(env["name"] == "SUPPORT_TWILIO_WEBHOOK_TOKEN" for env in sms["authEnvVars"])
    assert any(env["name"] == "SUPPORT_TWILIO_ACCOUNT_SID" and env["required"] for env in sms["outboundEnvVars"])
    assert any(env["name"] == "SUPPORT_TWILIO_AUTH_TOKEN" and env["required"] for env in sms["outboundEnvVars"])
    assert any(env["name"] == "SUPPORT_TWILIO_FROM_NUMBER" and not env["required"] for env in sms["outboundEnvVars"])
    assert any(env["name"] == "SUPPORT_TWILIO_MESSAGING_SERVICE_SID" and not env["required"] for env in sms["outboundEnvVars"])

    email = presets["email"]
    assert email["config"]["adapter"] == "imap"
    assert email["config"]["passwordEnv"] == "SUPPORT_IMAP_PASSWORD"
    assert email["outboundWebhookUrlEnv"] == "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_URL"
    assert email["outboundWebhookTokenEnv"] == "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_TOKEN"
    assert email["config"]["outboundWebhookUrlEnv"] == "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_URL"
    assert any(env["name"] == "SMTP_HOST" and env["required"] for env in email["outboundEnvVars"])
    assert any(env["name"] == "SUPPORT_EMAIL_OUTBOUND_WEBHOOK_URL" for env in email["outboundEnvVars"])


def test_line_provider_smoke_payload_uses_messaging_api_shape():
    payload, provider, event_id, message_id = admin_channels._provider_smoke_payload(
        "line-main",
        "line",
        admin_channels.ChannelTestMessageInput(
            body="Need help",
            author_id="Ucustomer",
            channel_id="Ubot",
            message_id="line-message-1",
            event_id="line-event-1",
        ),
    )

    assert provider == "line"
    assert event_id == "line-event-1"
    assert message_id == "line-message-1"
    assert payload["destination"] == "Ubot"
    assert payload["events"][0]["webhookEventId"] == "line-event-1"
    assert payload["events"][0]["source"] == {"type": "user", "userId": "Ucustomer"}
    assert payload["events"][0]["message"] == {"id": "line-message-1", "type": "text", "text": "Need help"}


def test_viber_provider_smoke_payload_uses_bot_api_shape():
    payload, provider, event_id, message_id = admin_channels._provider_smoke_payload(
        "viber-main",
        "viber",
        admin_channels.ChannelTestMessageInput(
            body="Need help",
            author_id="viber-user-id",
            author_name="Viber Customer",
            channel_id="viber-bot",
            message_id="491266184665523145",
            event_id="viber-event-1",
        ),
    )

    assert provider == "viber"
    assert event_id == "viber-event-1"
    assert message_id == "491266184665523145"
    assert payload["event"] == "message"
    assert payload["message_token"] == 491266184665523145
    assert payload["chat_hostname"] == "viber-bot"
    assert payload["sender"]["id"] == "viber-user-id"
    assert payload["sender"]["name"] == "Viber Customer"
    assert payload["message"] == {"type": "text", "text": "Need help", "tracking_data": "viber-event-1"}


def test_sms_provider_smoke_payload_uses_twilio_form_shape():
    payload, provider, event_id, message_id = admin_channels._provider_smoke_payload(
        "sms-main",
        "sms",
        admin_channels.ChannelTestMessageInput(
            body="",
            author_id="+15551234567",
            channel_id="+15550001111",
            message_id="SM123",
            event_id="admin-smoke-event",
            attachments=[
                {
                    "id": "media-1",
                    "url": "https://files.example/invoice.pdf",
                    "contentType": "application/pdf",
                }
            ],
        ),
    )

    assert provider == "sms"
    assert event_id == "admin-smoke-event"
    assert message_id == "SM123"
    assert payload == {
        "MessageSid": "SM123",
        "SmsSid": "SM123",
        "AccountSid": "AC_ADMIN_SMOKE",
        "From": "+15551234567",
        "To": "+15550001111",
        "Body": "",
        "NumMedia": "1",
        "SmsStatus": "received",
        "MediaUrl0": "https://files.example/invoice.pdf",
        "MediaContentType0": "application/pdf",
    }


def test_sms_http_smoke_posts_form_with_twilio_signature(monkeypatch):
    import base64
    import hashlib
    import hmac
    from urllib.parse import parse_qsl

    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"status": "success", "processed": 1, "failed": 0, "items": []}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url: str, *, content: bytes, headers: dict[str, str]):
            captured.update({"url": url, "content": content, "headers": headers, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr(admin_channels.httpx, "Client", FakeClient)
    setup = {
        "providerWebhookUrl": "https://support.example.test/api/internal/support/twilio/sms-main?tenant_id=tenant1&project_id=project1",
        "twilioSignatureHeader": "X-Twilio-Signature",
        "twilioSignatureAuthTokenEnv": "SUPPORT_TWILIO_AUTH_TOKEN",
    }
    payload = {
        "MessageSid": "SM123",
        "From": "+15551234567",
        "To": "+15550001111",
        "Body": "Need help",
    }

    result, http_result = admin_channels._post_smoke_http(
        "sms",
        setup,
        payload,
        {"SUPPORT_TWILIO_AUTH_TOKEN": "twilio-auth-token"},
    )

    posted = dict(parse_qsl(captured["content"].decode("utf-8")))
    signed = captured["url"] + "".join(f"{key}{value}" for key, value in sorted(payload.items()))
    expected = base64.b64encode(
        hmac.new(b"twilio-auth-token", signed.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    assert result["status"] == "success"
    assert posted == payload
    assert captured["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert captured["headers"]["X-Twilio-Signature"] == expected
    assert captured["timeout"] == 60.0
    assert http_result["auth"] == {
        "mode": "twilio_signature",
        "env": "SUPPORT_TWILIO_AUTH_TOKEN",
        "header": "X-Twilio-Signature",
    }


def test_smoke_http_timeout_uses_email_specific_default_and_config(monkeypatch):
    monkeypatch.delenv("SUPPORT_SMOKE_TIMEOUT", raising=False)
    monkeypatch.delenv("SUPPORT_EMAIL_SMOKE_TIMEOUT", raising=False)

    assert admin_channels._smoke_http_timeout("email") == 180.0
    assert admin_channels._smoke_http_timeout("slack") == 60.0

    monkeypatch.setenv("SUPPORT_SMOKE_TIMEOUT", "75")
    assert admin_channels._smoke_http_timeout("email") == 75.0
    assert admin_channels._smoke_http_timeout("slack") == 75.0

    monkeypatch.setenv("SUPPORT_EMAIL_SMOKE_TIMEOUT", "240")
    assert admin_channels._smoke_http_timeout("email") == 240.0
    assert admin_channels._smoke_http_timeout("slack") == 75.0


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("0", 1.0),
        ("999", 300.0),
        ("not-a-number", 180.0),
        ("nan", 180.0),
    ],
)
def test_email_smoke_http_timeout_is_bounded(monkeypatch, configured, expected):
    monkeypatch.delenv("SUPPORT_SMOKE_TIMEOUT", raising=False)
    monkeypatch.setenv("SUPPORT_EMAIL_SMOKE_TIMEOUT", configured)

    assert admin_channels._smoke_http_timeout("email") == expected


def test_email_http_smoke_timeout_has_stable_error(monkeypatch):
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, timeout: float):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url: str, *, content: bytes, headers: dict[str, str]):
            raise admin_channels.httpx.ReadTimeout(
                "The read operation timed out",
                request=admin_channels.httpx.Request("POST", url),
            )

    monkeypatch.delenv("SUPPORT_SMOKE_TIMEOUT", raising=False)
    monkeypatch.delenv("SUPPORT_EMAIL_SMOKE_TIMEOUT", raising=False)
    monkeypatch.setattr(admin_channels.httpx, "Client", FakeClient)

    with pytest.raises(
        admin_channels.SmokeHttpTimeoutError,
        match="Smoke endpoint timed out after 180 seconds",
    ):
        admin_channels._post_smoke_http(
            "email",
            {"providerWebhookUrl": "https://support.example.test/api/internal/support/email/email-main"},
            {"email": {"messageId": "email-message-1", "body": "Need help"}},
            {"SUPPORT_SYNC_TOKEN": "sync-token"},
        )

    assert captured["timeout"] == 180.0


def test_email_http_smoke_uses_provider_pipeline_url():
    setup = {
        "providerWebhookUrl": "https://support.example.test/api/internal/support/email/email-main",
        "inboundWebhookUrl": "https://support.example.test/api/internal/support/channel-webhooks/email-main",
    }

    assert admin_channels._smoke_url("email", setup) == setup["providerWebhookUrl"]
    assert admin_channels._smoke_url("webhook", setup) == setup["inboundWebhookUrl"]


def test_email_provider_smoke_payload_uses_email_webhook_shape():
    payload, provider, event_id, message_id = admin_channels._provider_smoke_payload(
        "email-main",
        "email",
        admin_channels.ChannelTestMessageInput(
            body="Where is order ZF-1042?\nPlease use confirmed shipment facts only.",
            author_name="Lena Schmidt",
            author_email="lena.schmidt@example-shop.de",
            thread_id="email-thread-1",
            message_id="email-message-1",
            event_id="email-event-1",
            attachments=[{
                "id": "packing-slip-1",
                "filename": "packing-slip.pdf",
                "contentType": "application/pdf",
            }],
        ),
    )

    assert provider == "email"
    assert event_id == "email-event-1"
    assert message_id == "email-message-1"
    assert payload == {
        "email": {
            "messageId": "email-message-1",
            "threadId": "email-thread-1",
            "subject": "Where is order ZF-1042?",
            "fromAddress": "lena.schmidt@example-shop.de",
            "fromName": "Lena Schmidt",
            "body": "Where is order ZF-1042?\nPlease use confirmed shipment facts only.",
            "attachments": [{
                "id": "packing-slip-1",
                "filename": "packing-slip.pdf",
                "contentType": "application/pdf",
            }],
        },
        "metadata": {
            "source": "admin_smoke",
            "channelKey": "email-main",
            "eventId": "email-event-1",
        },
    }


def test_whatsapp_provider_smoke_payload_uses_cloud_api_shape():
    payload, provider, event_id, message_id = admin_channels._provider_smoke_payload(
        "whatsapp-main",
        "whatsapp",
        admin_channels.ChannelTestMessageInput(
            body="",
            author_name="Ana Customer",
            author_id="15551234567",
            channel_id="phone-1",
            message_id="wamid.admin-smoke",
            event_id="admin-smoke-event",
            attachments=[
                {
                    "id": "media-1",
                    "filename": "invoice.pdf",
                    "contentType": "application/pdf",
                    "size": 8192,
                }
            ],
        ),
    )

    value = payload["entry"][0]["changes"][0]["value"]
    message = value["messages"][0]
    assert provider == "whatsapp"
    assert event_id == "admin-smoke-event"
    assert message_id == "wamid.admin-smoke"
    assert payload["object"] == "whatsapp_business_account"
    assert value["metadata"]["phone_number_id"] == "phone-1"
    assert value["contacts"][0]["wa_id"] == "15551234567"
    assert message["from"] == "15551234567"
    assert message["id"] == "wamid.admin-smoke"
    assert message["type"] == "document"
    assert message["document"]["id"] == "media-1"
    assert message["document"]["filename"] == "invoice.pdf"
    assert "text" not in message


def test_messenger_provider_smoke_payload_uses_page_webhook_shape():
    payload, provider, event_id, message_id = admin_channels._provider_smoke_payload(
        "messenger-main",
        "messenger",
        admin_channels.ChannelTestMessageInput(
            body="Need help",
            author_id="psid-1",
            channel_id="page-1",
            message_id="m_admin_smoke",
            event_id="admin-smoke-event",
            attachments=[
                {
                    "id": "image-1",
                    "url": "https://files.example/image.png",
                    "contentType": "image/png",
                }
            ],
        ),
    )

    messaging = payload["entry"][0]["messaging"][0]
    assert provider == "messenger"
    assert event_id == "admin-smoke-event"
    assert message_id == "m_admin_smoke"
    assert payload["object"] == "page"
    assert payload["entry"][0]["id"] == "page-1"
    assert messaging["sender"]["id"] == "psid-1"
    assert messaging["recipient"]["id"] == "page-1"
    assert messaging["message"]["mid"] == "m_admin_smoke"
    assert messaging["message"]["text"] == "Need help"
    assert messaging["message"]["attachments"][0]["payload"]["url"] == "https://files.example/image.png"


def test_admin_slack_install_url_returns_signed_authorize_url(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_SLACK_CLIENT_ID": "client-123",
            "SUPPORT_SLACK_CLIENT_SECRET": "client-secret",
        },
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/slack/install-url",
        json={"channelKey": "slack-main", "name": "Slack"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["channelKey"] == "slack-main"
    assert body["redirectUri"].endswith("/api/admin/projects/project1/channels/slack/oauth/callback")
    assert body["installUrl"].startswith("https://slack.com/oauth/v2/authorize?")
    assert "client_id=client-123" in body["installUrl"]
    assert "chat%3Awrite" in body["installUrl"]
    assert "client-secret" not in body["installUrl"]


def test_admin_slack_oauth_callback_stores_token_and_channel(client, monkeypatch):
    project_secrets: dict[str, str] = {
        "SUPPORT_SLACK_CLIENT_ID": "client-123",
        "SUPPORT_SLACK_CLIENT_SECRET": "client-secret",
    }
    stored: dict[str, str] = {}
    channels: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "ok": True,
                "access_token": "xoxb-installed",
                "app_id": "A123",
                "bot_user_id": "B123",
                "team": {"id": "T123", "name": "Acme"},
            }

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url: str, data: dict):
            assert url == "https://slack.com/api/oauth.v2.access"
            assert data["client_id"] == "client-123"
            assert data["client_secret"] == "client-secret"
            assert data["code"] == "oauth-code"
            assert data["redirect_uri"].endswith("/api/admin/projects/project1/channels/slack/oauth/callback")
            return FakeResponse()

    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr("automail.api.admin.channels.load_runtime_secrets", lambda tenant_id, project_id: dict(project_secrets))
    monkeypatch.setattr("automail.api.admin.channels.get_project_secrets", lambda project_id: dict(project_secrets))

    def fake_update_project_secrets(project_id: str, secrets: dict[str, str]):
        stored.update(secrets)
        return secrets

    def fake_upsert_channel(**kwargs):
        channels.append(kwargs)
        return {
            "id": "channel1",
            "channelKey": kwargs["channel_key"],
            "type": kwargs["channel_type"],
            "name": kwargs["name"],
            "status": kwargs["status"],
            "config": kwargs["config"],
        }

    monkeypatch.setattr("automail.api.admin.channels.update_project_secrets", fake_update_project_secrets)
    monkeypatch.setattr("automail.api.admin.channels.get_channel_by_key", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.admin.channels.upsert_channel", fake_upsert_channel)

    install_resp = client.post(
        "/api/admin/projects/project1/channels/slack/install-url",
        json={"channelKey": "slack-main", "name": "Slack"},
    )
    state = install_resp.json()["installUrl"].split("state=", 1)[1].split("&", 1)[0]

    resp = client.get(f"/api/admin/projects/project1/channels/slack/oauth/callback?code=oauth-code&state={state}")

    assert resp.status_code == 200
    assert "Slack installed" in resp.text
    assert stored["SUPPORT_SLACK_BOT_TOKEN"] == "xoxb-installed"
    assert channels[0]["channel_key"] == "slack-main"
    assert channels[0]["config"]["teamId"] == "T123"
    assert channels[0]["config"]["workspaceName"] == "Acme"
    assert channels[0]["config"]["outboundTransport"] == "bot"
    assert channels[0]["config"]["slackBotTokenEnv"] == "SUPPORT_SLACK_BOT_TOKEN"
    assert channels[0]["config"]["outboundWebhookTokenEnv"] == ""
    assert "xoxb-installed" not in resp.text


def test_admin_channel_save_keeps_outbound_reply_config(client, monkeypatch):
    calls: list[dict] = []

    def fake_upsert(**kwargs):
        calls.append(kwargs)
        return {
            "id": "channel1",
            "channelKey": kwargs["channel_key"],
            "type": kwargs["channel_type"],
            "name": kwargs["name"],
            "status": kwargs["status"],
            "config": kwargs["config"],
            "lastSyncAt": "",
            "created": "",
            "updated": "",
        }

    monkeypatch.setattr("automail.api.admin.channels.upsert_channel", fake_upsert)

    resp = client.post(
        "/api/admin/projects/project1/channels",
        json={
            "channelKey": "discord-main",
            "type": "discord",
            "name": "Discord",
            "status": "active",
            "config": {
                "ticketCreationMode": "per_message",
                "outboundWebhookUrl": "https://adapter.example.com/reply",
                "outboundWebhookTokenEnv": "SUPPORT_DISCORD_OUTBOUND_TOKEN",
                "outboundPayloadMode": "provider",
            },
        },
    )

    assert resp.status_code == 200
    assert calls == [{
        "tenant_id": "",
        "project_id": "project1",
        "channel_key": "discord-main",
        "channel_type": "discord",
        "name": "Discord",
        "status": "active",
        "config": {
            "ticketCreationMode": "per_message",
            "outboundWebhookUrl": "https://adapter.example.com/reply",
            "outboundWebhookTokenEnv": "SUPPORT_DISCORD_OUTBOUND_TOKEN",
            "outboundPayloadMode": "provider",
        },
    }]
    setup = resp.json()["setup"]
    assert setup["outboundWebhookConfigured"] is True
    assert setup["outboundReady"] is True
    assert setup["outboundWebhookUrl"] == "https://adapter.example.com/reply"
    assert setup["outboundWebhookTokenEnv"] == "SUPPORT_DISCORD_OUTBOUND_TOKEN"


def test_admin_channels_include_provider_urls(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "discord-main",
                "type": "discord",
                "name": "Discord",
                "status": "active",
                "config": {},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel2",
                "channelKey": "teams-main",
                "type": "teams",
                "name": "Teams",
                "status": "active",
                "config": {},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel3",
                "channelKey": "telegram-main",
                "type": "telegram",
                "name": "Telegram",
                "status": "active",
                "config": {},
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel-line",
                "channelKey": "line-main",
                "type": "line",
                "name": "LINE",
                "status": "active",
                "config": {
                    "lineChannelSecretEnv": "SUPPORT_LINE_CHANNEL_SECRET",
                    "lineChannelAccessTokenEnv": "SUPPORT_LINE_CHANNEL_ACCESS_TOKEN",
                    "outboundPayloadMode": "line",
                    "outboundTransport": "line",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel-viber",
                "channelKey": "viber-main",
                "type": "viber",
                "name": "Viber",
                "status": "active",
                "config": {
                    "viberAuthTokenEnv": "SUPPORT_VIBER_AUTH_TOKEN",
                    "outboundPayloadMode": "viber",
                    "outboundTransport": "viber",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel4",
                "channelKey": "whatsapp-main",
                "type": "whatsapp",
                "name": "WhatsApp",
                "status": "active",
                "config": {
                    "whatsappSigningSecretEnv": "SUPPORT_WHATSAPP_APP_SECRET",
                    "verifyTokenEnv": "SUPPORT_WHATSAPP_VERIFY_TOKEN",
                    "phoneNumberIdEnv": "SUPPORT_WHATSAPP_PHONE_NUMBER_ID",
                    "outboundWebhookUrlTemplate": "https://graph.facebook.com/v20.0/{SUPPORT_WHATSAPP_PHONE_NUMBER_ID}/messages",
                    "outboundWebhookTokenEnv": "SUPPORT_WHATSAPP_ACCESS_TOKEN",
                    "outboundPayloadMode": "whatsapp",
                    "outboundTokenRequired": True,
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel5",
                "channelKey": "messenger-main",
                "type": "messenger",
                "name": "Messenger",
                "status": "active",
                "config": {
                    "messengerSigningSecretEnv": "SUPPORT_MESSENGER_APP_SECRET",
                    "verifyTokenEnv": "SUPPORT_MESSENGER_VERIFY_TOKEN",
                    "pageIdEnv": "SUPPORT_MESSENGER_PAGE_ID",
                    "outboundWebhookUrlTemplate": "https://graph.facebook.com/v20.0/{SUPPORT_MESSENGER_PAGE_ID}/messages",
                    "outboundWebhookTokenEnv": "SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN",
                    "outboundPayloadMode": "messenger",
                    "outboundTokenRequired": True,
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel6",
                "channelKey": "instagram-main",
                "type": "instagram",
                "name": "Instagram DM",
                "status": "active",
                "config": {
                    "instagramSigningSecretEnv": "SUPPORT_INSTAGRAM_APP_SECRET",
                    "verifyTokenEnv": "SUPPORT_INSTAGRAM_VERIFY_TOKEN",
                    "instagramAccountIdEnv": "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID",
                    "instagramAccessTokenEnv": "SUPPORT_INSTAGRAM_ACCESS_TOKEN",
                    "outboundTransport": "instagram",
                    "outboundWebhookUrlTemplate": (
                        "https://graph.facebook.com/v20.0/{SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID}/messages"
                    ),
                    "outboundWebhookTokenEnv": "SUPPORT_INSTAGRAM_ACCESS_TOKEN",
                    "outboundPayloadMode": "instagram",
                    "outboundTokenRequired": True,
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel7",
                "channelKey": "twitter-main",
                "type": "twitter",
                "name": "X DM",
                "status": "active",
                "config": {
                    "twitterConsumerSecretEnv": "SUPPORT_X_CONSUMER_SECRET",
                    "twitterBearerTokenEnv": "SUPPORT_X_BEARER_TOKEN",
                    "twitterUserAccessTokenEnv": "SUPPORT_X_USER_ACCESS_TOKEN",
                    "twitterUserIdEnv": "SUPPORT_X_USER_ID",
                    "outboundTransport": "twitter",
                    "outboundWebhookTokenEnv": "SUPPORT_X_USER_ACCESS_TOKEN",
                    "outboundPayloadMode": "twitter",
                    "outboundTokenRequired": True,
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    channels = {item["channelKey"]: item["setup"] for item in resp.json()["items"]}
    assert channels["discord-main"]["providerWebhookUrl"].endswith(
        "/api/internal/support/discord/discord-main?project_id=project1"
    )
    assert channels["discord-main"]["providerTokenEnv"] == "SUPPORT_DISCORD_WEBHOOK_TOKEN"
    assert channels["discord-main"]["providerSignatureConfigKey"] == "signatureSecretEnv"
    assert channels["teams-main"]["providerWebhookUrl"].endswith(
        "/api/internal/support/teams/teams-main?project_id=project1"
    )
    assert channels["teams-main"]["providerTokenEnv"] == "SUPPORT_TEAMS_WEBHOOK_TOKEN"
    assert channels["teams-main"]["providerSignatureConfigKey"] == "signatureSecretEnv"
    assert channels["telegram-main"]["providerWebhookUrl"].endswith(
        "/api/internal/support/telegram/telegram-main?project_id=project1"
    )
    assert channels["telegram-main"]["providerTokenEnv"] == "SUPPORT_TELEGRAM_WEBHOOK_TOKEN"
    assert channels["telegram-main"]["providerSecretHeader"] == "X-Telegram-Bot-Api-Secret-Token"
    assert channels["telegram-main"]["providerSecretEnv"] == "SUPPORT_TELEGRAM_SECRET_TOKEN"
    telegram_config = channels["telegram-main"]["telegramWebhookConfig"]
    assert telegram_config["mode"] == "bot_api_webhook"
    assert telegram_config["botTokenEnv"] == "SUPPORT_TELEGRAM_BOT_TOKEN"
    assert telegram_config["secretTokenEnv"] == "SUPPORT_TELEGRAM_SECRET_TOKEN"
    assert telegram_config["setWebhook"]["urlTemplate"] == "https://api.telegram.org/bot{SUPPORT_TELEGRAM_BOT_TOKEN}/setWebhook"
    assert telegram_config["setWebhook"]["json"]["url"] == channels["telegram-main"]["providerWebhookUrl"]
    assert telegram_config["setWebhook"]["json"]["secret_token"] == "${SUPPORT_TELEGRAM_SECRET_TOKEN}"
    assert telegram_config["payloadExample"]["message"]["text"] == "Customer message"
    assert channels["telegram-main"]["messagePayloadExample"]["update_id"] == 123456
    assert channels["telegram-main"]["installPackage"]["telegramWebhookConfig"]["webhookUrl"] == channels["telegram-main"]["providerWebhookUrl"]
    assert channels["line-main"]["providerWebhookUrl"].endswith(
        "/api/internal/support/line/line-main?project_id=project1"
    )
    assert channels["line-main"]["providerTokenEnv"] == "SUPPORT_LINE_WEBHOOK_TOKEN"
    assert channels["line-main"]["signatureHeader"] == "X-Line-Signature"
    assert channels["line-main"]["signatureEnv"] == "SUPPORT_LINE_CHANNEL_SECRET"
    assert channels["line-main"]["signatureRequired"] is True
    assert channels["line-main"]["outboundTransport"] == "provider_api"
    assert channels["line-main"]["outboundProviderCredentialEnvVars"] == ["SUPPORT_LINE_CHANNEL_ACCESS_TOKEN"]
    line_config = channels["line-main"]["lineWebhookConfig"]
    assert line_config["mode"] == "messaging_api_webhook"
    assert line_config["channelSecretEnv"] == "SUPPORT_LINE_CHANNEL_SECRET"
    assert line_config["channelAccessTokenEnv"] == "SUPPORT_LINE_CHANNEL_ACCESS_TOKEN"
    assert line_config["payloadExample"]["events"][0]["message"]["text"] == "Customer message"
    assert channels["line-main"]["messagePayloadExample"]["events"][0]["message"]["text"] == "Customer message"
    assert channels["line-main"]["installPackage"]["lineWebhookConfig"]["webhookUrl"] == channels["line-main"]["providerWebhookUrl"]
    assert channels["viber-main"]["providerWebhookUrl"].endswith(
        "/api/internal/support/viber/viber-main?project_id=project1"
    )
    assert channels["viber-main"]["providerTokenEnv"] == "SUPPORT_VIBER_WEBHOOK_TOKEN"
    assert channels["viber-main"]["signatureHeader"] == "X-Viber-Content-Signature"
    assert channels["viber-main"]["signatureEnv"] == "SUPPORT_VIBER_AUTH_TOKEN"
    assert channels["viber-main"]["signatureRequired"] is True
    assert channels["viber-main"]["outboundTransport"] == "provider_api"
    assert channels["viber-main"]["outboundWebhookTokenEnv"] == "SUPPORT_VIBER_AUTH_TOKEN"
    assert channels["viber-main"]["outboundProviderCredentialEnvVars"] == ["SUPPORT_VIBER_AUTH_TOKEN"]
    viber_config = channels["viber-main"]["viberWebhookConfig"]
    assert viber_config["mode"] == "bot_api_webhook"
    assert viber_config["authTokenEnv"] == "SUPPORT_VIBER_AUTH_TOKEN"
    assert viber_config["setWebhook"]["json"]["url"] == channels["viber-main"]["providerWebhookUrl"]
    assert viber_config["payloadExample"]["message"]["text"] == "Customer message"
    assert channels["viber-main"]["messagePayloadExample"]["message"]["text"] == "Customer message"
    assert channels["viber-main"]["installPackage"]["viberWebhookConfig"]["webhookUrl"] == channels["viber-main"]["providerWebhookUrl"]
    assert channels["whatsapp-main"]["providerWebhookUrl"].endswith(
        "/api/internal/support/whatsapp/whatsapp-main?project_id=project1"
    )
    assert channels["whatsapp-main"]["providerTokenEnv"] == "SUPPORT_WHATSAPP_WEBHOOK_TOKEN"
    assert channels["whatsapp-main"]["providerVerifyTokenEnv"] == "SUPPORT_WHATSAPP_VERIFY_TOKEN"
    assert channels["whatsapp-main"]["signatureHeader"] == "X-Hub-Signature-256"
    assert channels["whatsapp-main"]["signatureEnv"] == "SUPPORT_WHATSAPP_APP_SECRET"
    assert channels["whatsapp-main"]["signatureRequired"] is True
    whatsapp_config = channels["whatsapp-main"]["whatsappWebhookConfig"]
    assert whatsapp_config["mode"] == "cloud_api_webhook"
    assert whatsapp_config["verifyTokenEnv"] == "SUPPORT_WHATSAPP_VERIFY_TOKEN"
    assert whatsapp_config["phoneNumberIdEnv"] == "SUPPORT_WHATSAPP_PHONE_NUMBER_ID"
    assert whatsapp_config["accessTokenEnv"] == "SUPPORT_WHATSAPP_ACCESS_TOKEN"
    assert whatsapp_config["messagesEndpointTemplate"] == (
        "https://graph.facebook.com/v20.0/{SUPPORT_WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    assert whatsapp_config["payloadExample"]["object"] == "whatsapp_business_account"
    assert channels["whatsapp-main"]["messagePayloadExample"]["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] == "Customer message"
    assert channels["whatsapp-main"]["installPackage"]["whatsappWebhookConfig"]["webhookUrl"] == channels["whatsapp-main"]["providerWebhookUrl"]
    whatsapp_bridge = channels["whatsapp-main"]["metaBridgeConfig"]
    assert whatsapp_bridge["mode"] == "meta_webhook_bridge"
    assert whatsapp_bridge["sidecar"]["publicPath"] == "/bridge/whatsapp/whatsapp-main"
    assert whatsapp_bridge["sidecar"]["env"]["SUPPORT_BRIDGE_TOKEN_ENV"] == "SUPPORT_WHATSAPP_WEBHOOK_TOKEN"
    assert whatsapp_bridge["sidecar"]["env"]["SUPPORT_BRIDGE_SIGNATURE_SECRET_ENV"] == "SUPPORT_WHATSAPP_APP_SECRET"
    assert whatsapp_bridge["validation"]["queryParams"]["hub.verify_token"] == "${SUPPORT_WHATSAPP_VERIFY_TOKEN}"
    assert whatsapp_bridge["forward"]["coreUrl"] == channels["whatsapp-main"]["providerWebhookUrl"]
    assert channels["whatsapp-main"]["installPackage"]["metaBridgeConfig"]["validation"]["publicPath"] == "/bridge/whatsapp/whatsapp-main"
    assert channels["messenger-main"]["providerWebhookUrl"].endswith(
        "/api/internal/support/messenger/messenger-main?project_id=project1"
    )
    assert channels["messenger-main"]["providerTokenEnv"] == "SUPPORT_MESSENGER_WEBHOOK_TOKEN"
    assert channels["messenger-main"]["providerVerifyTokenEnv"] == "SUPPORT_MESSENGER_VERIFY_TOKEN"
    assert channels["messenger-main"]["signatureHeader"] == "X-Hub-Signature-256"
    assert channels["messenger-main"]["signatureEnv"] == "SUPPORT_MESSENGER_APP_SECRET"
    assert channels["messenger-main"]["signatureRequired"] is True
    messenger_config = channels["messenger-main"]["messengerWebhookConfig"]
    assert messenger_config["mode"] == "facebook_page_messenger_webhook"
    assert messenger_config["verifyTokenEnv"] == "SUPPORT_MESSENGER_VERIFY_TOKEN"
    assert messenger_config["pageIdEnv"] == "SUPPORT_MESSENGER_PAGE_ID"
    assert messenger_config["pageAccessTokenEnv"] == "SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN"
    assert messenger_config["messagesEndpointTemplate"] == (
        "https://graph.facebook.com/v20.0/{SUPPORT_MESSENGER_PAGE_ID}/messages"
    )
    assert messenger_config["payloadExample"]["object"] == "page"
    assert channels["messenger-main"]["messagePayloadExample"]["entry"][0]["messaging"][0]["message"]["text"] == "Customer message"
    assert channels["messenger-main"]["installPackage"]["messengerWebhookConfig"]["webhookUrl"] == channels["messenger-main"]["providerWebhookUrl"]
    messenger_bridge = channels["messenger-main"]["metaBridgeConfig"]
    assert messenger_bridge["mode"] == "meta_webhook_bridge"
    assert messenger_bridge["sidecar"]["publicPath"] == "/bridge/messenger/messenger-main"
    assert messenger_bridge["sidecar"]["env"]["SUPPORT_BRIDGE_TOKEN_ENV"] == "SUPPORT_MESSENGER_WEBHOOK_TOKEN"
    assert messenger_bridge["sidecar"]["env"]["SUPPORT_BRIDGE_SIGNATURE_SECRET_ENV"] == "SUPPORT_MESSENGER_APP_SECRET"
    assert messenger_bridge["validation"]["queryParams"]["hub.verify_token"] == "${SUPPORT_MESSENGER_VERIFY_TOKEN}"
    assert messenger_bridge["forward"]["coreUrl"] == channels["messenger-main"]["providerWebhookUrl"]
    assert channels["messenger-main"]["installPackage"]["metaBridgeConfig"]["validation"]["publicPath"] == "/bridge/messenger/messenger-main"
    assert channels["instagram-main"]["providerWebhookUrl"].endswith(
        "/api/internal/support/instagram/instagram-main?project_id=project1"
    )
    assert channels["instagram-main"]["providerTokenEnv"] == "SUPPORT_INSTAGRAM_WEBHOOK_TOKEN"
    assert channels["instagram-main"]["providerVerifyTokenEnv"] == "SUPPORT_INSTAGRAM_VERIFY_TOKEN"
    assert channels["instagram-main"]["signatureHeader"] == "X-Hub-Signature-256"
    assert channels["instagram-main"]["signatureEnv"] == "SUPPORT_INSTAGRAM_APP_SECRET"
    assert channels["instagram-main"]["signatureRequired"] is True
    assert channels["instagram-main"]["outboundTransport"] == "provider_api"
    assert channels["instagram-main"]["outboundWebhookTokenEnv"] == "SUPPORT_INSTAGRAM_ACCESS_TOKEN"
    assert channels["instagram-main"]["outboundProviderCredentialEnvVars"] == [
        "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID",
        "SUPPORT_INSTAGRAM_ACCESS_TOKEN",
    ]
    instagram_config = channels["instagram-main"]["instagramWebhookConfig"]
    assert instagram_config["mode"] == "instagram_messaging_webhook"
    assert instagram_config["verifyTokenEnv"] == "SUPPORT_INSTAGRAM_VERIFY_TOKEN"
    assert instagram_config["instagramAccountIdEnv"] == "SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID"
    assert instagram_config["accessTokenEnv"] == "SUPPORT_INSTAGRAM_ACCESS_TOKEN"
    assert instagram_config["messagesEndpointTemplate"] == (
        "https://graph.facebook.com/v20.0/{SUPPORT_INSTAGRAM_BUSINESS_ACCOUNT_ID}/messages"
    )
    assert instagram_config["payloadExample"]["object"] == "instagram"
    assert channels["instagram-main"]["messagePayloadExample"]["entry"][0]["messaging"][0]["message"]["text"] == "Customer message"
    assert channels["instagram-main"]["installPackage"]["instagramWebhookConfig"]["webhookUrl"] == channels["instagram-main"]["providerWebhookUrl"]
    instagram_bridge = channels["instagram-main"]["metaBridgeConfig"]
    assert instagram_bridge["mode"] == "meta_webhook_bridge"
    assert instagram_bridge["sidecar"]["publicPath"] == "/bridge/instagram/instagram-main"
    assert instagram_bridge["sidecar"]["env"]["SUPPORT_BRIDGE_TOKEN_ENV"] == "SUPPORT_INSTAGRAM_WEBHOOK_TOKEN"
    assert instagram_bridge["sidecar"]["env"]["SUPPORT_BRIDGE_SIGNATURE_SECRET_ENV"] == "SUPPORT_INSTAGRAM_APP_SECRET"
    assert instagram_bridge["validation"]["queryParams"]["hub.verify_token"] == "${SUPPORT_INSTAGRAM_VERIFY_TOKEN}"
    assert instagram_bridge["forward"]["coreUrl"] == channels["instagram-main"]["providerWebhookUrl"]
    assert channels["instagram-main"]["installPackage"]["metaBridgeConfig"]["validation"]["publicPath"] == "/bridge/instagram/instagram-main"
    assert channels["twitter-main"]["providerWebhookUrl"].endswith(
        "/api/internal/support/twitter/twitter-main?project_id=project1"
    )
    assert channels["twitter-main"]["providerTokenEnv"] == "SUPPORT_X_WEBHOOK_TOKEN"
    assert channels["twitter-main"]["signatureHeader"] == "x-twitter-webhooks-signature"
    assert channels["twitter-main"]["signatureEnv"] == "SUPPORT_X_CONSUMER_SECRET"
    assert channels["twitter-main"]["signatureRequired"] is True
    assert channels["twitter-main"]["outboundTransport"] == "provider_api"
    assert channels["twitter-main"]["outboundWebhookTokenEnv"] == "SUPPORT_X_USER_ACCESS_TOKEN"
    assert channels["twitter-main"]["outboundProviderCredentialEnvVars"] == [
        "SUPPORT_X_USER_ACCESS_TOKEN",
        "SUPPORT_X_BEARER_TOKEN",
        "SUPPORT_X_USER_ID",
    ]
    twitter_config = channels["twitter-main"]["twitterWebhookConfig"]
    assert twitter_config["mode"] == "x_account_activity_webhook"
    assert twitter_config["crc"]["queryParam"] == "crc_token"
    assert twitter_config["crc"]["consumerSecretEnv"] == "SUPPORT_X_CONSUMER_SECRET"
    assert twitter_config["bearerTokenEnv"] == "SUPPORT_X_BEARER_TOKEN"
    assert twitter_config["userAccessTokenEnv"] == "SUPPORT_X_USER_ACCESS_TOKEN"
    assert twitter_config["subscribedUserIdEnv"] == "SUPPORT_X_USER_ID"
    assert twitter_config["sendMessageEndpointTemplate"] == (
        "https://api.x.com/2/dm_conversations/with/{participant_id}/messages"
    )
    assert twitter_config["payloadExample"]["direct_message_events"][0]["message_create"]["message_data"]["text"] == "Customer message"
    assert channels["twitter-main"]["installPackage"]["twitterWebhookConfig"]["webhookUrl"] == channels["twitter-main"]["providerWebhookUrl"]
    twitter_bridge = channels["twitter-main"]["twitterBridgeConfig"]
    assert twitter_bridge["mode"] == "x_webhook_bridge"
    assert twitter_bridge["sidecar"]["publicPath"] == "/bridge/twitter/twitter-main"
    assert twitter_bridge["sidecar"]["env"]["SUPPORT_BRIDGE_TOKEN_ENV"] == "SUPPORT_X_WEBHOOK_TOKEN"
    assert twitter_bridge["sidecar"]["env"]["SUPPORT_BRIDGE_SIGNATURE_SECRET_ENV"] == "SUPPORT_X_CONSUMER_SECRET"
    assert twitter_bridge["validation"]["queryParams"]["crc_token"] == "{crc_token}"
    assert twitter_bridge["forward"]["coreUrl"] == channels["twitter-main"]["providerWebhookUrl"]
    assert channels["twitter-main"]["installPackage"]["twitterBridgeConfig"]["validation"]["publicPath"] == "/bridge/twitter/twitter-main"


def test_admin_channels_report_provider_signature_key_readiness(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "ACME_TEAMS_SIGNING_SECRET": "teams-secret",
            "ACME_DISCORD_SIGNING_SECRET": "discord-secret",
            "SUPPORT_TELEGRAM_SECRET_TOKEN": "telegram-secret",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {
                "id": "channel1",
                "channelKey": "teams-main",
                "type": "teams",
                "name": "Teams",
                "status": "active",
                "config": {
                    "teamsSigningSecretEnv": "ACME_TEAMS_SIGNING_SECRET",
                    "signatureHeader": "X-Teams-Signature",
                    "signatureTimestampRequired": True,
                    "signatureTimestampHeader": "X-Teams-Timestamp",
                    "signatureToleranceSeconds": 120,
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel2",
                "channelKey": "discord-main",
                "type": "discord",
                "name": "Discord",
                "status": "active",
                "config": {
                    "discordSigningSecretEnv": "ACME_DISCORD_SIGNING_SECRET",
                    "signatureHeader": "X-Discord-Signature",
                    "signatureTimestampRequired": True,
                    "signatureTimestampHeader": "X-Discord-Timestamp",
                    "signatureToleranceSeconds": 120,
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
            {
                "id": "channel3",
                "channelKey": "telegram-main",
                "type": "telegram",
                "name": "Telegram",
                "status": "active",
                "config": {
                    "telegramSigningSecretEnv": "ACME_TELEGRAM_SIGNING_SECRET",
                    "telegramSecretTokenEnv": "SUPPORT_TELEGRAM_SECRET_TOKEN",
                    "signatureHeader": "X-Telegram-Signature",
                },
                "lastSyncAt": "",
                "created": "",
                "updated": "",
            },
        ],
    )

    resp = client.get("/api/admin/projects/project1/channels")

    assert resp.status_code == 200
    channels = {item["channelKey"]: item["setup"] for item in resp.json()["items"]}
    teams = channels["teams-main"]
    discord = channels["discord-main"]
    telegram = channels["telegram-main"]
    assert teams["authConfigured"] is True
    assert teams["inboundReady"] is True
    assert teams["signatureRequired"] is True
    assert teams["signatureEnv"] == "ACME_TEAMS_SIGNING_SECRET"
    assert teams["signatureHeader"] == "X-Teams-Signature"
    assert teams["signatureTimestampHeader"] == "X-Teams-Timestamp"
    assert teams["signatureTimestampRequired"] is True
    assert teams["signatureToleranceSeconds"] == 120
    assert teams["providerSignatureConfigKey"] == "teamsSigningSecretEnv"
    assert teams["teamsBridgeConfig"]["signature"]["timestampHeader"] == "X-Teams-Timestamp"
    assert teams["teamsBridgeConfig"]["signature"]["algorithm"] == "hmac_sha256_timestamp_dot_raw_body"
    assert any(env["name"] == "ACME_TEAMS_SIGNING_SECRET" and env["configured"] and env["required"] for env in teams["envVars"])
    assert discord["authConfigured"] is True
    assert discord["inboundReady"] is True
    assert discord["signatureRequired"] is True
    assert discord["signatureEnv"] == "ACME_DISCORD_SIGNING_SECRET"
    assert discord["signatureHeader"] == "X-Discord-Signature"
    assert discord["signatureTimestampHeader"] == "X-Discord-Timestamp"
    assert discord["signatureTimestampRequired"] is True
    assert discord["signatureToleranceSeconds"] == 120
    assert discord["providerSignatureConfigKey"] == "discordSigningSecretEnv"
    assert discord["discordBridgeConfig"]["signature"]["timestampHeader"] == "X-Discord-Timestamp"
    assert discord["discordBridgeConfig"]["signature"]["algorithm"] == "hmac_sha256_timestamp_dot_raw_body"
    assert any(env["name"] == "ACME_DISCORD_SIGNING_SECRET" and env["configured"] and env["required"] for env in discord["envVars"])
    assert telegram["authConfigured"] is False
    assert telegram["inboundReady"] is False
    assert telegram["signatureRequired"] is True
    assert telegram["signatureEnv"] == "ACME_TELEGRAM_SIGNING_SECRET"
    assert telegram["providerSignatureConfigKey"] == "telegramSigningSecretEnv"
    assert telegram["health"]["status"] == "needs_setup"
    assert "ACME_TELEGRAM_SIGNING_SECRET" in telegram["health"]["requiredMissingEnvVars"]
    assert any(env["name"] == "ACME_TELEGRAM_SIGNING_SECRET" and not env["configured"] and env["required"] for env in telegram["envVars"])


def test_admin_channel_test_message_ingests_normalized_message(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "discord-main",
            "type": "discord",
            "name": "Discord",
            "status": "active",
        },
    )

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {
            "status": "success",
            "processed": 1,
            "failed": 0,
            "skipped": 0,
            "items": [{"kind": "inbound_message", "issueId": "issue1", "messageId": "msg1"}],
        }

    monkeypatch.setattr("automail.api.admin.channels.ingest_channel_webhook", fake_ingest)

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/test-message",
        json={
            "body": "Production API is down.",
            "authorName": "Ana",
            "authorEmail": "ana@example.com",
            "channelId": "C123",
            "threadId": "thread-1",
            "messageId": "message-1",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == 1
    assert data["items"][0]["issueId"] == "issue1"
    assert calls[0]["channel_key"] == "discord-main"
    assert calls[0]["tenant_id"] == ""
    assert calls[0]["project_id"] == "project1"
    assert calls[0]["source"] == "admin-test"
    payload = calls[0]["payload"]
    assert payload["provider"] == "discord"
    assert payload["content"] == "Production API is down."
    assert payload["channelId"] == "C123"
    assert payload["threadId"] == "thread-1"
    assert payload["messageId"] == "message-1"
    assert payload["author"]["email"] == "ana@example.com"
    assert payload["metadata"]["source"] == "admin_test_message"


def test_admin_channel_webhook_event_rematch(client, monkeypatch):
    calls: list[dict] = []

    def fake_rematch(event_id: str, **kwargs):
        calls.append({"event_id": event_id, **kwargs})
        return {
            "id": event_id,
            "status": "processed",
            "outboundMessageId": "reply123",
            "result": {"matched": True, "rematched": True},
        }

    monkeypatch.setattr("automail.api.admin.channels.rematch_channel_webhook_event", fake_rematch)

    resp = client.post(
        "/api/admin/projects/project1/channels/webhook-events/eventRow1/rematch",
        json={"outboundMessageId": "reply123"},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"
    assert calls == [{
        "event_id": "eventRow1",
        "tenant_id": "",
        "project_id": "project1",
        "outbound_message_id": "reply123",
    }]


def test_admin_channel_smoke_uses_slack_native_payload(client, monkeypatch):
    calls: list[dict] = []
    recorded: list[dict] = []
    completed: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "slack-main",
            "type": "slack",
            "name": "Slack",
            "status": "active",
            "config": {},
        },
    )
    monkeypatch.setattr("automail.api.admin.channels.load_runtime_secrets", lambda *_args, **_kwargs: {})

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "ignored": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.admin.channels.ingest_slack_event", fake_ingest)
    monkeypatch.setattr(
        "automail.api.admin.channels.update_issue",
        lambda issue_id, **kwargs: completed.append({"issue_id": issue_id, **kwargs}) or {"id": issue_id, "status": "done"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "run1", **kwargs},
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/smoke",
        json={
            "body": "Production API is down.",
            "authorName": "Ana",
            "authorEmail": "ana@example.com",
            "channelId": "C123",
            "threadId": "thread-1",
            "messageId": "1710000000.000100",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "slack"
    assert data["issueId"] == "issue1"
    assert data["cleanup"]["status"] == "done"
    assert data["runId"] == "run1"
    assert data["items"][0]["issueId"] == "issue1"
    assert data["validation"]["channelId"] == "channel1"
    assert calls[0]["channel_key"] == "slack-main"
    assert calls[0]["source"] == "admin-smoke"
    payload = calls[0]["payload"]
    assert payload["type"] == "event_callback"
    assert payload["event_id"].startswith("admin-smoke-")
    assert payload["event"]["type"] == "message"
    assert payload["event"]["channel"] == "C123"
    assert payload["event"]["thread_ts"] == "thread-1"
    assert payload["event"]["text"] == "Production API is down."
    assert recorded[0]["channel_id"] == "channel1"
    assert recorded[0]["source"] == "admin-smoke"
    assert recorded[0]["result"]["processed"] == 1
    assert completed == [{
        "issue_id": "issue1",
        "tenant_id": "",
        "project_id": "project1",
        "updates": {"status": "done", "workflow_source": "admin-channel-smoke-cleanup"},
    }]


def test_admin_channel_smoke_maps_http_timeout_to_gateway_timeout(client, monkeypatch):
    monkeypatch.setattr(
        admin_channels,
        "get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "email-main",
            "type": "email",
            "status": "active",
        },
    )

    def timeout(*_args, **_kwargs):
        raise admin_channels.SmokeHttpTimeoutError(
            "Smoke endpoint timed out after 180 seconds"
        )

    monkeypatch.setattr(admin_channels, "_run_channel_smoke", timeout)

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/smoke",
        json={"body": "Where is order ZF-1042?", "transport": "http"},
    )

    assert resp.status_code == 504
    assert resp.json() == {"detail": "Smoke endpoint timed out after 180 seconds"}


def test_admin_channel_smoke_accepts_slack_file_only_payload(client, monkeypatch):
    calls: list[dict] = []
    recorded: list[dict] = []
    completed: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "slack-main",
            "type": "slack",
            "name": "Slack",
            "status": "active",
            "config": {},
        },
    )
    monkeypatch.setattr("automail.api.admin.channels.load_runtime_secrets", lambda *_args, **_kwargs: {})

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "ignored": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.admin.channels.ingest_slack_event", fake_ingest)
    monkeypatch.setattr(
        "automail.api.admin.channels.update_issue",
        lambda issue_id, **kwargs: completed.append({"issue_id": issue_id, **kwargs}) or {"id": issue_id, "status": "done"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "run1", **kwargs},
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/smoke",
        json={
            "body": "",
            "channelId": "C123",
            "messageId": "1710000000.000100",
            "attachments": [{
                "id": "F123",
                "filename": "outage-screenshot.png",
                "contentType": "image/png",
                "size": 1234,
                "url": "https://files.example/outage-screenshot.png",
            }],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["attachmentCount"] == 1
    assert data["fileOnly"] is True
    assert data["cleanup"]["workflowSource"] == "admin-channel-smoke-cleanup"
    payload = calls[0]["payload"]
    assert payload["event"]["text"] == ""
    assert payload["event"]["subtype"] == "file_share"
    assert payload["event"]["files"] == [{
        "id": "F123",
        "name": "outage-screenshot.png",
        "title": "outage-screenshot.png",
        "mimetype": "image/png",
        "filetype": "png",
        "url_private": "https://files.example/outage-screenshot.png",
        "size": 1234,
    }]
    assert recorded[0]["result"]["attachmentCount"] == 1
    assert recorded[0]["result"]["fileOnly"] is True
    assert completed[0]["updates"]["status"] == "done"


def test_admin_channel_outbound_smoke_sends_provider_reply(client, monkeypatch):
    from automail.support.delivery import DeliveryResult

    calls: list[dict] = []
    recorded: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "slack-main",
            "type": "slack",
            "name": "Slack",
            "status": "active",
            "config": {
                "outboundWebhookUrl": "https://slack.com/api/chat.postMessage",
                "outboundWebhookTokenEnv": "SUPPORT_SLACK_BOT_TOKEN",
                "outboundTokenRequired": True,
                "outboundPayloadMode": "provider",
            },
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda *_args, **_kwargs: {"SUPPORT_SLACK_BOT_TOKEN": "xoxb-test"},
    )

    def fake_send(**kwargs):
        calls.append(kwargs)
        return DeliveryResult(
            status="sent",
            provider="slack_webhook",
            provider_message_id="slack:C123:1710000000.000200",
            metadata=_provider_delivery_proof(),
        )

    monkeypatch.setattr("automail.api.admin.channels.send_support_channel_reply", fake_send)
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "run1", **kwargs},
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/outbound-smoke",
        json={
            "body": "Thanks, we are checking.",
            "channelId": "C123",
            "threadId": "1710000000.000100",
            "providerMessageId": "1710000000.000100",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "sent"
    assert data["sent"] is True
    assert data["failed"] is False
    assert data["provider"] == "slack_webhook"
    assert data["providerMessageId"] == "slack:C123:1710000000.000200"
    assert data["deliveryRoute"]["provider"] == "slack"
    assert data["providerResponse"]["statusCode"] == 200
    assert data["runId"] == "run1"
    assert data["validation"]["channelId"] == "channel1"
    assert calls[0]["channel"] == "slack"
    assert calls[0]["channel_config"]["outboundPayloadMode"] == "provider"
    assert calls[0]["body"] == "Thanks, we are checking."
    assert calls[0]["metadata"]["source"] == "admin_outbound_smoke"
    assert calls[0]["metadata"]["issueSource"] == "slack-main"
    assert calls[0]["metadata"]["channelId"] == "C123"
    assert calls[0]["metadata"]["threadTs"] == "1710000000.000100"
    assert calls[0]["secrets"]["SUPPORT_SLACK_BOT_TOKEN"] == "xoxb-test"
    assert recorded[0]["channel_id"] == "channel1"
    assert recorded[0]["source"] == "admin-outbound-smoke"
    assert recorded[0]["result"]["processed"] == 1
    assert recorded[0]["result"]["failed"] is False


def test_channel_outbound_smoke_uses_configured_live_target_defaults(monkeypatch):
    from automail.support.delivery import DeliveryResult

    calls: list[dict] = []
    channel = {
        "id": "channel1",
        "channelKey": "slack-main",
        "type": "slack",
        "status": "active",
        "config": {
            "outboundTransport": "bot",
            "smokeChannelId": "C_LIVE",
            "smokeThreadTs": "1710000000.000100",
            "smokeProviderMessageId": "1710000000.000100",
        },
    }
    monkeypatch.setattr(
        admin_channels,
        "_channel_setup_validation",
        lambda channel, ctx, request: {"ready": True, "channelId": channel["id"]},
    )
    monkeypatch.setattr(admin_channels, "load_runtime_secrets", lambda *_args, **_kwargs: {"SUPPORT_SLACK_BOT_TOKEN": "xoxb"})

    def fake_send(**kwargs):
        calls.append(kwargs)
        return DeliveryResult(
            status="sent",
            provider="slack_bot",
            provider_message_id="slack:C_LIVE:1710000000.000200",
            metadata=_provider_delivery_proof(provider="slack_bot", channel_id="C_LIVE"),
        )

    monkeypatch.setattr(admin_channels, "send_support_channel_reply", fake_send)

    result = admin_channels._run_channel_outbound_smoke(
        channel,
        body=admin_channels.ChannelOutboundSmokeInput(body="Launch proof support reply."),
        ctx=SimpleNamespace(tenant_id="tenant1", project_id="project1"),
        request=SimpleNamespace(),
    )

    assert result["status"] == "sent"
    assert calls[0]["to_address"] == "C_LIVE"
    assert calls[0]["metadata"]["channelId"] == "C_LIVE"
    assert calls[0]["metadata"]["threadTs"] == "1710000000.000100"
    assert calls[0]["metadata"]["providerMessageId"] == "1710000000.000100"
    assert calls[0]["metadata"]["sourceMessageId"].startswith("admin-outbound-smoke-")


def test_channel_inbound_smoke_uses_configured_live_target_defaults(monkeypatch):
    captured: dict[str, object] = {}
    completed: list[dict] = []
    channel = {
        "id": "channel1",
        "channelKey": "slack-main",
        "type": "slack",
        "status": "active",
        "config": {
            "smokeChannelId": "C_LIVE",
            "smokeThreadTs": "1710000000.000100",
            "smokeProviderMessageId": "1710000000.000123",
        },
    }
    monkeypatch.setattr(
        admin_channels,
        "_channel_setup_validation",
        lambda channel, ctx, request: {"ready": True, "channelId": channel["id"]},
    )

    def fake_ingest(channel_key: str, *, payload: dict, **_kwargs):
        captured["channel_key"] = channel_key
        captured["payload"] = payload
        return {
            "status": "success",
            "processed": 1,
            "failed": 0,
            "items": [{"issueId": "issue1", "messageId": "message1"}],
        }

    monkeypatch.setattr(admin_channels, "ingest_slack_event", fake_ingest)
    monkeypatch.setattr(
        admin_channels,
        "update_issue",
        lambda issue_id, **kwargs: completed.append({"issue_id": issue_id, **kwargs}) or {"id": issue_id, "status": "done"},
    )

    result = admin_channels._run_channel_smoke(
        channel,
        body=admin_channels.ChannelTestMessageInput(body="Launch proof external channel message."),
        ctx=SimpleNamespace(tenant_id="tenant1", project_id="project1"),
        request=SimpleNamespace(),
    )

    payload = captured["payload"]
    assert result["status"] == "success"
    assert captured["channel_key"] == "slack-main"
    assert payload["event"]["channel"] == "C_LIVE"
    assert payload["event"]["thread_ts"] == "1710000000.000100"
    assert payload["event"]["ts"] == "1710000000.000123"
    assert result["cleanup"] == {
        "issueId": "issue1",
        "status": "done",
        "workflowSource": "admin-channel-smoke-cleanup",
    }
    assert completed == [{
        "issue_id": "issue1",
        "tenant_id": "tenant1",
        "project_id": "project1",
        "updates": {"status": "done", "workflow_source": "admin-channel-smoke-cleanup"},
    }]


def test_admin_channel_lifecycle_smoke_creates_approves_and_delivers_reply(client, monkeypatch):
    created: list[dict] = []
    approved: list[dict] = []
    delivered: list[dict] = []
    recorded: list[dict] = []
    completed: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "slack-main",
            "type": "slack",
            "name": "Slack",
            "status": "active",
            "config": {},
        },
    )

    def fake_smoke(channel: dict, *, body, ctx, request):
        assert channel["id"] == "channel1"
        assert body.body == "Production API is down."
        return {
            "channelId": "channel1",
            "channelKey": "slack-main",
            "type": "slack",
            "provider": "slack",
            "transport": body.transport,
            "ready": True,
            "validation": {"ready": True},
            "payload": {},
            "ingestion": {"status": "success"},
            "http": {},
            "eventId": "event1",
            "messageId": "msg-in",
            "issueId": "issue1",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "skipped": 0,
            "items": [{"issueId": "issue1", "messageId": "msg-in"}],
        }

    def fake_create(issue_id: str, **kwargs):
        created.append({"issue_id": issue_id, **kwargs})
        return {"id": "reply1", "status": "queued", "metadata": kwargs["metadata"]}

    def fake_approve(issue_id: str, reply_id: str, **kwargs):
        approved.append({"issue_id": issue_id, "reply_id": reply_id, **kwargs})
        return {"id": reply_id, "status": "queued", "metadata": {"approved": True}}

    def fake_deliver(issue_id: str, reply_id: str, **kwargs):
        delivered.append({"issue_id": issue_id, "reply_id": reply_id, **kwargs})
        return {
            "id": reply_id,
            "status": "sent",
            "provider": "slack_webhook",
            "providerMessageId": "slack:C123:2",
            "error": "",
        }

    monkeypatch.setattr("automail.api.admin.channels._run_channel_smoke", fake_smoke)
    monkeypatch.setattr("automail.api.admin.channels.create_issue_reply", fake_create)
    monkeypatch.setattr("automail.api.admin.channels.approve_issue_reply", fake_approve)
    monkeypatch.setattr("automail.api.admin.channels.deliver_issue_reply", fake_deliver)
    monkeypatch.setattr(
        "automail.api.admin.channels.update_issue",
        lambda issue_id, **kwargs: completed.append({"issue_id": issue_id, **kwargs}) or {"id": issue_id, "status": "done"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "run1", **kwargs},
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/lifecycle-smoke",
        json={
            "body": "Production API is down.",
            "replyBody": "Thanks, we are checking.",
            "authorName": "Ana",
            "authorEmail": "ana@example.com",
            "fromAddress": "support-agent@example.com",
            "channelId": "C123",
            "threadId": "1710000000.000100",
            "messageId": "1710000000.000100",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "sent"
    assert data["sent"] is True
    assert data["failed"] is False
    assert data["issueId"] == "issue1"
    assert data["replyId"] == "reply1"
    assert data["cleanup"] == {
        "issueId": "issue1",
        "status": "done",
        "workflowSource": "admin-channel-lifecycle-smoke-cleanup",
    }
    assert data["provider"] == "slack_webhook"
    assert data["providerMessageId"] == "slack:C123:2"
    assert data["runId"] == "run1"
    assert created[0]["issue_id"] == "issue1"
    assert created[0]["author_email"] == "support-agent@example.com"
    assert created[0]["status"] == "queued"
    assert created[0]["source"] == "admin_lifecycle_smoke"
    assert created[0]["metadata"]["approvalRequired"] is True
    assert created[0]["metadata"]["reviewStatus"] == "pending"
    assert approved == [{
        "issue_id": "issue1",
        "reply_id": "reply1",
        "tenant_id": "",
        "project_id": "project1",
        "approved_by": "support-agent@example.com",
    }]
    assert delivered == [{
        "issue_id": "issue1",
        "reply_id": "reply1",
        "tenant_id": "",
        "project_id": "project1",
    }]
    assert recorded[0]["channel_id"] == "channel1"
    assert recorded[0]["source"] == "admin-lifecycle-smoke"
    assert recorded[0]["result"]["status"] == "sent"
    assert completed == [{
        "issue_id": "issue1",
        "tenant_id": "",
        "project_id": "project1",
        "updates": {"status": "done", "workflow_source": "admin-channel-lifecycle-smoke-cleanup"},
    }]


def test_admin_email_channel_lifecycle_smoke_records_sync_and_delivery(client, monkeypatch):
    ingested: list[dict] = []
    created: list[dict] = []
    approved: list[dict] = []
    delivered: list[dict] = []
    delivery_runs: list[dict] = []
    sync_runs: list[dict] = []
    completed: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "support-email",
            "type": "email",
            "name": "Support email",
            "status": "active",
            "config": {},
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels._channel_setup_validation",
        lambda channel, ctx, request: {"ready": True, "channelId": channel["id"], "setup": {"authConfigured": True}},
    )

    def fake_ingest(channel_key: str, **kwargs):
        ingested.append({"channel_key": channel_key, **kwargs})
        return {
            "status": "success",
            "processed": 1,
            "failed": 0,
            "items": [{"issueId": "issue-email", "messageId": "message-email"}],
        }

    def fake_create(issue_id: str, **kwargs):
        created.append({"issue_id": issue_id, **kwargs})
        return {"id": "reply-email", "status": "queued", "metadata": kwargs["metadata"]}

    def fake_approve(issue_id: str, reply_id: str, **kwargs):
        approved.append({"issue_id": issue_id, "reply_id": reply_id, **kwargs})
        return {"id": reply_id, "status": "queued", "metadata": {"approved": True}}

    def fake_deliver(issue_id: str, reply_id: str, **kwargs):
        delivered.append({"issue_id": issue_id, "reply_id": reply_id, **kwargs})
        return {
            "id": reply_id,
            "status": "sent",
            "provider": "smtp",
            "providerMessageId": "smtp:reply-email",
            "metadata": {
                "deliveryRoute": {"provider": "smtp"},
                "providerResponse": {"statusCode": 250},
            },
        }

    monkeypatch.setattr("automail.api.admin.channels.ingest_email_webhook", fake_ingest)
    monkeypatch.setattr("automail.api.admin.channels.create_issue_reply", fake_create)
    monkeypatch.setattr("automail.api.admin.channels.approve_issue_reply", fake_approve)
    monkeypatch.setattr("automail.api.admin.channels.deliver_issue_reply", fake_deliver)
    monkeypatch.setattr(
        "automail.api.admin.channels.update_issue",
        lambda issue_id, **kwargs: completed.append({"issue_id": issue_id, **kwargs}) or {"id": issue_id, "status": "done"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_delivery_run",
        lambda **kwargs: delivery_runs.append(kwargs) or {"id": "delivery-run1", **kwargs},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: sync_runs.append(kwargs) or {"id": "sync-run1", **kwargs},
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/lifecycle-smoke",
        json={
            "body": "Need help with onboarding.",
            "replyBody": "Thanks, we are checking.",
            "authorName": "Ana",
            "authorEmail": "ana@example.com",
            "fromAddress": "agent@example.com",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "email"
    assert data["status"] == "sent"
    assert data["sent"] is True
    assert data["failed"] is False
    assert data["issueId"] == "issue-email"
    assert data["replyId"] == "reply-email"
    assert data["cleanup"] == {
        "issueId": "issue-email",
        "status": "done",
        "workflowSource": "admin-email-lifecycle-smoke-cleanup",
    }
    assert data["provider"] == "smtp"
    assert data["deliveryRun"]["id"] == "delivery-run1"
    assert data["runId"] == "sync-run1"
    assert ingested[0]["channel_key"] == "support-email"
    assert ingested[0]["source"] == "admin-email-lifecycle-smoke"
    assert ingested[0]["payload"]["email"]["fromAddress"] == "ana@example.com"
    assert created[0]["issue_id"] == "issue-email"
    assert created[0]["source"] == "admin_lifecycle_smoke"
    assert created[0]["metadata"]["approvalRequired"] is True
    assert approved[0]["approved_by"] == "agent@example.com"
    assert delivered[0] == {
        "issue_id": "issue-email",
        "reply_id": "reply-email",
        "tenant_id": "",
        "project_id": "project1",
    }
    assert delivery_runs[0]["source"] == "admin-email-lifecycle-smoke"
    assert delivery_runs[0]["result"]["sent"] == 1
    assert delivery_runs[0]["result"]["items"][0]["provider"] == "smtp"
    assert sync_runs[0]["source"] == "admin-lifecycle-smoke"
    assert sync_runs[0]["result"]["deliveryRun"]["id"] == "delivery-run1"
    assert completed == [{
        "issue_id": "issue-email",
        "tenant_id": "",
        "project_id": "project1",
        "updates": {"status": "done", "workflow_source": "admin-email-lifecycle-smoke-cleanup"},
    }]


def test_admin_email_channel_lifecycle_smoke_requires_ingress_auth(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "support-email",
            "type": "email",
            "name": "Support email",
            "status": "active",
            "config": {},
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels._channel_setup_validation",
        lambda channel, ctx, request: {
            "ready": False,
            "channelId": channel["id"],
            "setup": {"authConfigured": False},
        },
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/lifecycle-smoke",
        json={"body": "Need help with onboarding.", "replyBody": "Thanks, we are checking."},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Configure email inbound webhook token, fallback sync token, or HMAC signature before lifecycle proof"


def test_admin_channel_lifecycle_smoke_accepts_file_only_attachment(client, monkeypatch):
    created: list[dict] = []
    recorded: list[dict] = []
    completed: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "slack-main",
            "type": "slack",
            "name": "Slack",
            "status": "active",
            "config": {},
        },
    )

    def fake_smoke(channel: dict, *, body, ctx, request):
        assert channel["id"] == "channel1"
        assert body.body == ""
        assert body.attachments[0]["filename"] == "outage-screenshot.png"
        return {
            "channelId": "channel1",
            "channelKey": "slack-main",
            "type": "slack",
            "provider": "slack",
            "transport": body.transport,
            "ready": True,
            "validation": {"ready": True},
            "payload": {"event": {"files": [{"name": "outage-screenshot.png"}]}},
            "ingestion": {"status": "success"},
            "http": {},
            "eventId": "event1",
            "messageId": "msg-in",
            "issueId": "issue1",
            "attachmentCount": 1,
            "fileOnly": True,
            "status": "success",
            "processed": 1,
            "failed": 0,
            "skipped": 0,
            "items": [{"issueId": "issue1", "messageId": "msg-in"}],
        }

    def fake_create(issue_id: str, **kwargs):
        created.append({"issue_id": issue_id, **kwargs})
        return {"id": "reply1", "status": "queued", "metadata": kwargs["metadata"]}

    monkeypatch.setattr("automail.api.admin.channels._run_channel_smoke", fake_smoke)
    monkeypatch.setattr("automail.api.admin.channels.create_issue_reply", fake_create)
    monkeypatch.setattr(
        "automail.api.admin.channels.update_issue",
        lambda issue_id, **kwargs: completed.append({"issue_id": issue_id, **kwargs}) or {"id": issue_id, "status": "done"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.approve_issue_reply",
        lambda issue_id, reply_id, **kwargs: {"id": reply_id, "status": "queued", "metadata": {"approved": True}},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.deliver_issue_reply",
        lambda issue_id, reply_id, **kwargs: {
            "id": reply_id,
            "status": "sent",
            "provider": "slack_webhook",
            "providerMessageId": "slack:C123:2",
            "error": "",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.record_channel_sync_run",
        lambda **kwargs: recorded.append(kwargs) or {"id": "run1", **kwargs},
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/lifecycle-smoke",
        json={
            "body": "",
            "replyBody": "Thanks, we are checking.",
            "channelId": "C123",
            "messageId": "1710000000.000100",
            "attachments": [{
                "filename": "outage-screenshot.png",
                "contentType": "image/png",
            }],
            "replyAttachments": [{
                "filename": "diagnostic.txt",
                "contentType": "text/plain",
                "base64": "b2s=",
            }],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "sent"
    assert data["attachmentCount"] == 1
    assert data["replyAttachmentCount"] == 1
    assert data["fileOnly"] is True
    assert data["issueId"] == "issue1"
    assert data["replyId"] == "reply1"
    assert data["cleanup"]["workflowSource"] == "admin-channel-lifecycle-smoke-cleanup"
    assert created[0]["metadata"]["approvalRequired"] is True
    assert created[0]["attachments"] == [{
        "filename": "diagnostic.txt",
        "contentType": "text/plain",
        "base64": "b2s=",
    }]
    assert recorded[0]["result"]["attachmentCount"] == 1
    assert recorded[0]["result"]["replyAttachmentCount"] == 1
    assert recorded[0]["result"]["fileOnly"] is True
    assert completed[0]["updates"]["status"] == "done"


def test_admin_crm_connector_validate_route_scopes_project(client, monkeypatch):
    calls: list[dict] = []

    def fake_validate(connector_id: str, **kwargs):
        calls.append({"connector_id": connector_id, **kwargs})
        return {
            "connectorId": connector_id,
            "connectorKey": "hubspot-main",
            "provider": "hubspot",
            "adapter": "hubspot",
            "ready": True,
            "status": "ready",
            "checks": [{"key": "token", "label": "Private app token", "status": "done", "detail": "HUBSPOT_TOKEN"}],
            "envVars": [{"name": "HUBSPOT_TOKEN", "required": True, "configured": True, "status": "done"}],
            "sample": {"companies": 1, "contacts": 1},
            "error": "",
        }

    monkeypatch.setattr("automail.api.admin.channels.validate_crm_connector", fake_validate)

    resp = client.post("/api/admin/projects/project1/crm/connectors/crm1/validate", json={})

    assert resp.status_code == 200
    assert resp.json()["ready"] is True
    assert calls == [{
        "connector_id": "crm1",
        "tenant_id": "",
        "project_id": "project1",
    }]


def test_admin_channel_smoke_run_checks_active_channels(client, monkeypatch):
    calls: list[str] = []
    recorded: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {"id": "channel1", "channelKey": "slack-main", "type": "slack", "status": "active"},
            {"id": "channel2", "channelKey": "discord-main", "type": "discord", "status": "active"},
            {"id": "channel3", "channelKey": "email-main", "type": "email", "status": "paused"},
        ],
    )

    def fake_run(channel: dict, *, body, ctx, request):
        calls.append(channel["id"])
        if channel["id"] == "channel2":
            raise ValueError("provider token missing")
        return {
            "channelId": channel["id"],
            "channelKey": channel["channelKey"],
            "type": channel["type"],
            "provider": channel["type"],
            "transport": body.transport,
            "ready": True,
            "validation": {"ready": True},
            "payload": {},
            "ingestion": {"status": "success"},
            "http": {},
            "eventId": "event1",
            "messageId": "message1",
            "issueId": "issue1",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "skipped": 0,
            "items": [{"issueId": "issue1"}],
        }

    monkeypatch.setattr("automail.api.admin.channels._run_channel_smoke", fake_run)

    def fake_record_channel_sync_run(**kwargs):
        recorded.append(kwargs)
        return {"id": f"run{len(recorded)}", **kwargs}

    monkeypatch.setattr("automail.api.admin.channels.record_channel_sync_run", fake_record_channel_sync_run)

    resp = client.post(
        "/api/admin/projects/project1/channels/smoke/run",
        json={"body": "Production API is down.", "transport": "direct"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "partial"
    assert data["channels"] == 2
    assert data["ready"] == 1
    assert data["processed"] == 1
    assert data["failed"] == 1
    assert data["items"][0]["channelKey"] == "slack-main"
    assert data["items"][0]["runId"] == "run1"
    assert data["failures"] == [{
        "channelId": "channel2",
        "channelKey": "discord-main",
        "error": "provider token missing",
        "runId": "run2",
    }]
    assert calls == ["channel1", "channel2"]
    assert [run["channel_id"] for run in recorded] == ["channel1", "channel2"]
    assert [run["source"] for run in recorded] == ["admin-smoke-run", "admin-smoke-run"]
    assert recorded[0]["result"]["status"] == "success"
    assert recorded[1]["result"]["status"] == "failed"
    assert recorded[1]["result"]["error"] == "provider token missing"


def test_admin_channel_launch_status_requires_http_surface_for_inbound_and_lifecycle():
    channel = {"id": "channel1", "channelKey": "slack-main", "type": "slack", "status": "active"}
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "transport": "direct"},
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "sent": True},
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "sent": True, "inbound": {"transport": "direct"}},
        },
    ]

    direct_launch = admin_channels._channel_launch_status(channel, runs)

    assert direct_launch["ready"] is False
    assert direct_launch["passed"] == 1
    assert {item["key"] for item in direct_launch["blockers"]} == {
        "inbound_smoke",
        "lifecycle_smoke",
        "attachment_lifecycle_smoke",
    }
    assert direct_launch["checklist"][0]["transport"] == "direct"
    assert direct_launch["checklist"][0]["detail"] == "Run HTTP channel smoke to prove provider endpoint/auth creates a ticket"
    assert direct_launch["checklist"][2]["transport"] == "direct"
    assert direct_launch["checklist"][2]["detail"] == "Run HTTP lifecycle smoke to prove provider endpoint, ticket, approval, and delivery"

    runs[0]["result"]["transport"] = "http"
    runs[2]["result"]["inbound"]["transport"] = "http"
    http_without_artifacts = admin_channels._channel_launch_status(channel, runs)

    assert http_without_artifacts["ready"] is False
    assert http_without_artifacts["passed"] == 1
    assert {item["key"] for item in http_without_artifacts["blockers"]} == {
        "inbound_smoke",
        "lifecycle_smoke",
        "attachment_lifecycle_smoke",
    }
    assert http_without_artifacts["checklist"][0]["detail"] == "Smoke run did not record a created ticket"
    assert http_without_artifacts["checklist"][2]["detail"] == "Smoke run did not record a created ticket"

    runs[0]["result"]["issueId"] = "issue1"
    runs[2]["result"]["issueId"] = "issue1"
    runs[2]["result"]["replyId"] = "reply1"
    http_launch = admin_channels._channel_launch_status(channel, runs)

    assert http_launch["ready"] is False
    assert http_launch["passed"] == 3
    assert {item["key"] for item in http_launch["blockers"]} == {"attachment_lifecycle_smoke"}
    assert http_launch["checklist"][0]["transport"] == "http"
    assert http_launch["checklist"][0]["issueId"] == "issue1"
    assert http_launch["checklist"][2]["transport"] == "http"
    assert http_launch["checklist"][2]["issueId"] == "issue1"
    assert http_launch["checklist"][2]["replyId"] == "reply1"
    assert http_launch["checklist"][3]["detail"] == (
        "Run attachment-only HTTP lifecycle smoke to prove Slack files create tickets and replies deliver"
    )

    runs.append(_attachment_lifecycle_run())
    attachment_launch = admin_channels._channel_launch_status(channel, runs)

    assert attachment_launch["ready"] is True
    assert attachment_launch["passed"] == 4
    assert attachment_launch["blockers"] == []
    assert attachment_launch["checklist"][3]["attachmentCount"] == 1
    assert attachment_launch["checklist"][3]["fileOnly"] is True


def test_admin_channel_launch_status_requires_provider_message_for_provider_delivery():
    channel = {
        "id": "channel1",
        "channelKey": "slack-main",
        "type": "slack",
        "status": "active",
        "config": {"outboundPayloadMode": "provider", "smokeChannelId": "C_LIVE"},
    }
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": _inbound_smoke_result(),
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "sent": True},
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {"transport": "http", "issueId": "issue1"},
                "issueId": "issue1",
                "replyId": "reply1",
            },
        },
        {
            "id": "validation1",
            "channel": "channel1",
            "source": "admin-validation",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "providerValidation": {"status": "ready"}},
        },
        _attachment_lifecycle_run(provider_delivery=True),
    ]

    missing_provider_launch = admin_channels._channel_launch_status(channel, runs)

    assert missing_provider_launch["ready"] is False
    assert missing_provider_launch["passed"] == 4
    assert {item["key"] for item in missing_provider_launch["blockers"]} == {"outbound_smoke", "lifecycle_smoke"}
    assert missing_provider_launch["checklist"][3]["detail"] == "Provider delivery did not record a provider message ID"
    assert missing_provider_launch["checklist"][4]["detail"] == "Provider delivery did not record a provider message ID"

    runs[1]["result"]["providerMessageId"] = "slack:C123:2"
    runs[2]["result"]["delivery"] = {
        "providerMessageId": "slack:C123:3",
    }
    missing_delivery_proof_launch = admin_channels._channel_launch_status(channel, runs)

    assert missing_delivery_proof_launch["ready"] is False
    assert {item["key"] for item in missing_delivery_proof_launch["blockers"]} == {
        "outbound_smoke",
        "lifecycle_smoke",
    }
    assert missing_delivery_proof_launch["checklist"][3]["detail"] == (
        "Provider delivery did not record delivery route and provider response"
    )
    assert missing_delivery_proof_launch["checklist"][4]["detail"] == (
        "Provider delivery did not record delivery route and provider response"
    )

    runs[1]["result"].update(_provider_delivery_proof())
    runs[2]["result"]["delivery"]["metadata"] = _provider_delivery_proof()
    ready_launch = admin_channels._channel_launch_status(channel, runs)

    assert ready_launch["ready"] is True
    assert ready_launch["passed"] == 6
    assert ready_launch["blockers"] == []
    assert ready_launch["checklist"][3]["providerMessageId"] == "slack:C123:2"
    assert ready_launch["checklist"][3]["deliveryRoute"]["provider"] == "slack"
    assert ready_launch["checklist"][3]["providerResponse"]["statusCode"] == 200
    assert ready_launch["checklist"][4]["providerMessageId"] == "slack:C123:3"
    assert ready_launch["checklist"][4]["deliveryRoute"]["provider"] == "slack"
    assert ready_launch["checklist"][4]["providerResponse"]["statusCode"] == 200


def test_admin_channel_launch_status_requires_live_provider_target_for_provider_delivery():
    channel = {
        "id": "channel1",
        "channelKey": "slack-main",
        "type": "slack",
        "status": "active",
        "config": {"outboundPayloadMode": "provider"},
    }
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": _inbound_smoke_result(),
        },
        {
            "id": "validation1",
            "channel": "channel1",
            "source": "admin-validation",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "providerValidation": {"status": "ready"}},
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "providerMessageId": "slack:C_LIVE:2",
                **_provider_delivery_proof(channel_id="C_LIVE"),
            },
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {"transport": "http", "issueId": "issue1"},
                "issueId": "issue1",
                "replyId": "reply1",
                "providerMessageId": "slack:C_LIVE:3",
                **_provider_delivery_proof(channel_id="C_LIVE"),
            },
        },
        _attachment_lifecycle_run(provider_delivery=True, channel_id="C_LIVE"),
    ]

    missing_target = admin_channels._channel_launch_status(channel, runs)

    assert missing_target["ready"] is False
    assert missing_target["passed"] == 5
    assert {item["key"] for item in missing_target["blockers"]} == {"live_smoke_target"}
    assert missing_target["checklist"][0]["detail"] == (
        "Set smokeChannelId to a real Slack channel ID before launch proof"
    )

    channel["config"]["smokeChannelId"] = "C_LIVE"
    ready = admin_channels._channel_launch_status(channel, runs)

    assert ready["ready"] is True
    assert ready["passed"] == 6
    assert ready["blockers"] == []


def test_admin_channel_launch_status_rejects_stale_provider_target_proof():
    channel = {
        "id": "channel1",
        "channelKey": "slack-main",
        "type": "slack",
        "status": "active",
        "config": {"outboundPayloadMode": "provider", "smokeChannelId": "C_NEW"},
    }
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": _inbound_smoke_result(channel_id="C_OLD"),
        },
        {
            "id": "validation1",
            "channel": "channel1",
            "source": "admin-validation",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "providerValidation": {"status": "ready"}},
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "providerMessageId": "slack:C_OLD:2",
                **_provider_delivery_proof(channel_id="C_OLD"),
            },
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {"transport": "http", "issueId": "issue1"},
                "issueId": "issue1",
                "replyId": "reply1",
                "providerMessageId": "slack:C_OLD:3",
                **_provider_delivery_proof(channel_id="C_OLD"),
            },
        },
        _attachment_lifecycle_run(provider_delivery=True, channel_id="C_OLD"),
    ]

    launch = admin_channels._channel_launch_status(channel, runs)
    checklist = {item["key"]: item for item in launch["checklist"]}

    assert launch["ready"] is False
    assert launch["passed"] == 2
    assert {item["key"] for item in launch["blockers"]} == {
        "inbound_smoke",
        "outbound_smoke",
        "lifecycle_smoke",
        "attachment_lifecycle_smoke",
    }
    assert checklist["inbound_smoke"]["detail"] == (
        "Inbound smoke target does not match current live proof target: smokeChannelId=C_NEW"
    )
    assert checklist["outbound_smoke"]["detail"] == (
        "Smoke run target does not match current live proof target: smokeChannelId=C_NEW"
    )
    assert checklist["lifecycle_smoke"]["detail"] == (
        "Smoke run target does not match current live proof target: smokeChannelId=C_NEW"
    )
    assert checklist["attachment_lifecycle_smoke"]["detail"] == (
        "Smoke run target does not match current live proof target: smokeChannelId=C_NEW"
    )


def test_admin_channel_launch_status_requires_provider_message_for_default_bot_secret():
    channel = {
        "id": "channel1",
        "channelKey": "slack-main",
        "type": "slack",
        "status": "active",
        "config": {"smokeChannelId": "C_LIVE"},
    }
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": _inbound_smoke_result(),
        },
        {
            "id": "validation1",
            "channel": "channel1",
            "source": "admin-validation",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "providerValidation": {"status": "ready"}},
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "sent": True},
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {"transport": "http", "issueId": "issue1"},
                "issueId": "issue1",
                "replyId": "reply1",
            },
        },
        _attachment_lifecycle_run(provider_delivery=True),
    ]

    missing_provider_launch = admin_channels._channel_launch_status(
        channel,
        runs,
        {"SUPPORT_SLACK_BOT_TOKEN": "xoxb-test"},
    )

    assert missing_provider_launch["ready"] is False
    assert {item["key"] for item in missing_provider_launch["blockers"]} == {"outbound_smoke", "lifecycle_smoke"}
    assert missing_provider_launch["checklist"][3]["detail"] == "Provider delivery did not record a provider message ID"
    assert missing_provider_launch["checklist"][4]["detail"] == "Provider delivery did not record a provider message ID"

    runs[2]["result"]["providerMessageId"] = "slack:C123:2"
    runs[2]["result"].update(_provider_delivery_proof())
    runs[3]["result"]["delivery"] = {
        "providerMessageId": "slack:C123:3",
        "metadata": _provider_delivery_proof(),
    }
    ready_launch = admin_channels._channel_launch_status(channel, runs, {"SUPPORT_SLACK_BOT_TOKEN": "xoxb-test"})

    assert ready_launch["ready"] is True
    assert ready_launch["passed"] == 6
    assert ready_launch["blockers"] == []


def test_admin_channel_launch_status_requires_whatsapp_provider_validation_and_delivery_proof():
    channel = {
        "id": "channel1",
        "channelKey": "whatsapp-main",
        "type": "whatsapp",
        "status": "active",
        "config": {
            "outboundPayloadMode": "whatsapp",
            "outboundWebhookUrlTemplate": "https://graph.facebook.com/v20.0/{SUPPORT_WHATSAPP_PHONE_NUMBER_ID}/messages",
            "outboundWebhookTokenEnv": "SUPPORT_WHATSAPP_ACCESS_TOKEN",
            "smokeToAddress": "4915112345678",
        },
    }
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": _inbound_smoke_result(
                smoke_target={"waId": "4915112345678", "senderId": "4915112345678"},
            ),
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "providerMessageId": "whatsapp:wamid.reply-1",
                **_provider_delivery_proof(provider="whatsapp", channel_id="4915112345678"),
            },
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {"transport": "http", "issueId": "issue1"},
                "issueId": "issue1",
                "replyId": "reply1",
                "delivery": {
                    "providerMessageId": "whatsapp:wamid.reply-2",
                    "metadata": _provider_delivery_proof(provider="whatsapp", channel_id="4915112345678"),
                },
            },
        },
        _attachment_lifecycle_run(provider_delivery=True, provider="whatsapp", channel_id="4915112345678"),
    ]

    missing_validation = admin_channels._channel_launch_status(channel, runs)

    assert missing_validation["ready"] is False
    assert {item["key"] for item in missing_validation["blockers"]} == {"provider_validation"}
    assert missing_validation["checklist"][2]["key"] == "provider_validation"
    assert missing_validation["checklist"][2]["detail"] == "Run setup validation to prove provider credentials work"

    runs.append({
        "id": "validation1",
        "channel": "channel1",
        "source": "admin-validation",
        "status": "success",
        "processed": 1,
        "failed": 0,
        "result": {"ready": True, "providerValidation": {"status": "ready", "checked": True}},
    })
    ready_launch = admin_channels._channel_launch_status(channel, runs)

    assert ready_launch["ready"] is True
    assert ready_launch["passed"] == 6
    assert ready_launch["blockers"] == []
    assert ready_launch["checklist"][3]["providerMessageId"] == "whatsapp:wamid.reply-1"
    assert ready_launch["checklist"][3]["deliveryRoute"]["provider"] == "whatsapp"


def test_admin_channel_launch_status_requires_provider_validation_for_provider_delivery():
    channel = {
        "id": "channel1",
        "channelKey": "slack-main",
        "type": "slack",
        "status": "active",
        "config": {"outboundTransport": "bot", "smokeChannelId": "C_LIVE"},
    }
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": _inbound_smoke_result(),
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "providerMessageId": "slack:C123:2",
                **_provider_delivery_proof(),
            },
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {"transport": "http", "issueId": "issue1"},
                "issueId": "issue1",
                "replyId": "reply1",
                "providerMessageId": "slack:C123:3",
                **_provider_delivery_proof(),
            },
        },
        _attachment_lifecycle_run(provider_delivery=True),
    ]

    missing_validation = admin_channels._channel_launch_status(channel, runs)

    assert missing_validation["ready"] is False
    assert missing_validation["passed"] == 5
    assert {item["key"] for item in missing_validation["blockers"]} == {"provider_validation"}
    assert missing_validation["checklist"][2]["detail"] == "Run setup validation to prove provider credentials work"

    runs.append({
        "id": "validation1",
        "channel": "channel1",
        "source": "admin-validation",
        "status": "success",
        "processed": 1,
        "failed": 0,
        "result": {
            "ready": True,
            "providerValidation": {"status": "ready", "detail": "Slack bot token accepted"},
        },
    })
    ready = admin_channels._channel_launch_status(channel, runs)

    assert ready["ready"] is True
    assert ready["passed"] == 6
    assert ready["blockers"] == []


def test_admin_channel_launch_status_requires_twilio_validation_and_delivery_proof():
    channel = {
        "id": "channel1",
        "channelKey": "sms-main",
        "type": "sms",
        "status": "active",
        "config": {
            "outboundTransport": "twilio",
            "accountSidEnv": "SUPPORT_TWILIO_ACCOUNT_SID",
            "authTokenEnv": "SUPPORT_TWILIO_AUTH_TOKEN",
            "fromNumberEnv": "SUPPORT_TWILIO_FROM_NUMBER",
            "smokeToAddress": "+14155550123",
        },
    }
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": _inbound_smoke_result(
                smoke_target={"phone": "+14155550123", "senderId": "+14155550123"},
            ),
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "providerMessageId": "twilio:SM_REPLY_1",
            },
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {"transport": "http", "issueId": "issue1"},
                "issueId": "issue1",
                "replyId": "reply1",
                "delivery": {"providerMessageId": "twilio:SM_REPLY_2"},
            },
        },
    ]

    missing_validation = admin_channels._channel_launch_status(channel, runs)

    assert missing_validation["ready"] is False
    assert missing_validation["passed"] == 2
    assert {item["key"] for item in missing_validation["blockers"]} == {
        "provider_validation",
        "outbound_smoke",
        "lifecycle_smoke",
        "attachment_lifecycle_smoke",
    }
    assert missing_validation["checklist"][2]["detail"] == "Run setup validation to prove provider credentials work"
    assert missing_validation["checklist"][3]["detail"] == (
        "Provider delivery did not record delivery route and provider response"
    )
    assert missing_validation["checklist"][4]["detail"] == (
        "Provider delivery did not record delivery route and provider response"
    )

    runs.append({
        "id": "validation1",
        "channel": "channel1",
        "source": "admin-validation",
        "status": "success",
        "processed": 1,
        "failed": 0,
        "result": {
            "ready": True,
            "providerValidation": {"status": "ready", "detail": "Twilio API credentials accepted"},
        },
    })
    runs[1]["result"].update(_provider_delivery_proof(provider="twilio_sms", channel_id="+14155550123"))
    runs[2]["result"]["delivery"]["metadata"] = _provider_delivery_proof(
        provider="twilio_sms",
        channel_id="+14155550123",
    )
    runs.append(_attachment_lifecycle_run(
        provider_delivery=True,
        provider="twilio_sms",
        channel_id="+14155550123",
    ))
    ready = admin_channels._channel_launch_status(channel, runs)

    assert ready["ready"] is True
    assert ready["passed"] == 6
    assert ready["blockers"] == []
    assert ready["checklist"][3]["providerMessageId"] == "twilio:SM_REPLY_1"
    assert ready["checklist"][3]["deliveryRoute"]["provider"] == "twilio_sms"
    assert ready["checklist"][3]["providerResponse"]["statusCode"] == 200
    assert ready["checklist"][4]["providerMessageId"] == "twilio:SM_REPLY_2"
    assert ready["checklist"][4]["deliveryRoute"]["provider"] == "twilio_sms"


def test_admin_channel_launch_status_requires_twilio_signature_when_auth_token_present():
    channel = {
        "id": "channel1",
        "channelKey": "sms-main",
        "type": "sms",
        "status": "active",
        "config": {
            "outboundTransport": "twilio",
            "authTokenEnv": "SUPPORT_TWILIO_AUTH_TOKEN",
            "smokeToAddress": "+14155550123",
        },
    }

    token_auth = {"mode": "token", "header": "X-Support-Sync-Token"}
    signature_auth = {"mode": "twilio_signature", "header": "X-Twilio-Signature"}
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "transport": "http",
                "issueId": "issue1",
                "http": {"auth": token_auth},
                "smokeTarget": {"phone": "+14155550123", "senderId": "+14155550123"},
            },
        },
        {
            "id": "validation1",
            "channel": "channel1",
            "source": "admin-validation",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "providerValidation": {"status": "ready", "detail": "Twilio API credentials accepted"},
            },
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "providerMessageId": "twilio:SM_REPLY_1",
                **_provider_delivery_proof(provider="twilio_sms", channel_id="+14155550123"),
            },
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {
                    "transport": "http",
                    "issueId": "issue1",
                    "http": {"auth": token_auth},
                },
                "issueId": "issue1",
                "replyId": "reply1",
                "delivery": {
                    "providerMessageId": "twilio:SM_REPLY_2",
                        "metadata": _provider_delivery_proof(provider="twilio_sms", channel_id="+14155550123"),
                },
            },
        },
        _attachment_lifecycle_run(
            provider_delivery=True,
            auth=token_auth,
            provider="twilio_sms",
            channel_id="+14155550123",
        ),
    ]

    token_launch = admin_channels._channel_launch_status(
        channel,
        runs,
        {"SUPPORT_TWILIO_AUTH_TOKEN": "twilio-auth-token"},
    )

    assert token_launch["ready"] is False
    assert {item["key"] for item in token_launch["blockers"]} == {
        "inbound_smoke",
        "lifecycle_smoke",
        "attachment_lifecycle_smoke",
    }
    assert token_launch["checklist"][1]["detail"] == "Smoke run did not record required Twilio signature auth"
    assert token_launch["checklist"][4]["detail"] == "Smoke run did not record required Twilio signature auth"
    assert token_launch["checklist"][5]["detail"] == "Smoke run did not record required Twilio signature auth"

    runs[0]["result"]["http"]["auth"] = signature_auth
    runs[3]["result"]["inbound"]["http"]["auth"] = signature_auth
    runs[4]["result"]["inbound"]["http"]["auth"] = signature_auth
    ready = admin_channels._channel_launch_status(
        channel,
        runs,
        {"SUPPORT_TWILIO_AUTH_TOKEN": "twilio-auth-token"},
    )

    assert ready["ready"] is True
    assert ready["blockers"] == []
    assert ready["checklist"][1]["authMode"] == "twilio_signature"
    assert ready["checklist"][4]["authMode"] == "twilio_signature"
    assert ready["checklist"][5]["authMode"] == "twilio_signature"


def test_admin_channel_launch_status_requires_timestamp_auth_for_replay_protected_hmac():
    channel = {
        "id": "channel1",
        "channelKey": "discord-main",
        "type": "discord",
        "status": "active",
        "config": {
            "signatureSecretEnv": "SUPPORT_DISCORD_SIGNING_SECRET",
            "signatureTimestampRequired": True,
        },
    }
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "transport": "http",
                "issueId": "issue1",
                "http": {
                    "auth": {
                        "mode": "hmac_signature",
                        "header": "X-Discord-Signature",
                    }
                },
            },
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "sent": True},
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {
                    "transport": "http",
                    "issueId": "issue1",
                    "http": {
                        "auth": {
                            "mode": "hmac_signature",
                            "header": "X-Discord-Signature",
                        }
                    },
                },
                "issueId": "issue1",
                "replyId": "reply1",
            },
        },
        _attachment_lifecycle_run(
            auth={"mode": "hmac_signature", "header": "X-Discord-Signature"},
        ),
    ]

    missing_timestamp_auth = admin_channels._channel_launch_status(channel, runs)

    assert missing_timestamp_auth["ready"] is False
    assert {item["key"] for item in missing_timestamp_auth["blockers"]} == {
        "inbound_smoke",
        "lifecycle_smoke",
        "attachment_lifecycle_smoke",
    }
    assert missing_timestamp_auth["checklist"][0]["detail"] == "Smoke run did not record timestamp-bound HMAC auth"
    assert missing_timestamp_auth["checklist"][2]["detail"] == "Smoke run did not record timestamp-bound HMAC auth"
    assert missing_timestamp_auth["checklist"][3]["detail"] == "Smoke run did not record timestamp-bound HMAC auth"

    runs[0]["result"]["http"]["auth"]["timestampHeader"] = "X-Discord-Timestamp"
    runs[2]["result"]["inbound"]["http"]["auth"]["timestampHeader"] = "X-Discord-Timestamp"
    runs[3]["result"]["inbound"]["http"]["auth"] = {
        "mode": "hmac_signature",
        "header": "X-Discord-Signature",
        "timestampHeader": "X-Discord-Timestamp",
    }
    ready = admin_channels._channel_launch_status(channel, runs)

    assert ready["ready"] is True
    assert ready["passed"] == 4
    assert ready["blockers"] == []
    assert ready["checklist"][0]["signatureTimestampHeader"] == "X-Discord-Timestamp"
    assert ready["checklist"][2]["signatureTimestampHeader"] == "X-Discord-Timestamp"
    assert ready["checklist"][3]["signatureTimestampHeader"] == "X-Discord-Timestamp"


def test_admin_channel_launch_status_requires_signature_auth_for_signed_channel():
    channel = {
        "id": "channel1",
        "channelKey": "teams-main",
        "type": "teams",
        "status": "active",
        "config": {"teamsSigningSecretEnv": "SUPPORT_TEAMS_SIGNING_SECRET"},
    }
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "transport": "http",
                "issueId": "issue1",
                "http": {"auth": {"mode": "token", "header": "X-Support-Sync-Token"}},
            },
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "sent": True},
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {
                    "transport": "http",
                    "issueId": "issue1",
                    "http": {"auth": {"mode": "token", "header": "X-Support-Sync-Token"}},
                },
                "issueId": "issue1",
                "replyId": "reply1",
            },
        },
        _attachment_lifecycle_run(
            auth={"mode": "token", "header": "X-Support-Sync-Token"},
        ),
    ]

    token_launch = admin_channels._channel_launch_status(channel, runs)

    assert token_launch["ready"] is False
    assert {item["key"] for item in token_launch["blockers"]} == {
        "inbound_smoke",
        "lifecycle_smoke",
        "attachment_lifecycle_smoke",
    }
    assert token_launch["checklist"][0]["detail"] == "Smoke run did not record required signature auth"
    assert token_launch["checklist"][2]["detail"] == "Smoke run did not record required signature auth"
    assert token_launch["checklist"][3]["detail"] == "Smoke run did not record required signature auth"

    runs[0]["result"]["http"]["auth"] = {"mode": "hmac_signature", "header": "X-Support-Signature"}
    runs[2]["result"]["inbound"]["http"]["auth"] = {"mode": "hmac_signature", "header": "X-Support-Signature"}
    runs[3]["result"]["inbound"]["http"]["auth"] = {"mode": "hmac_signature", "header": "X-Support-Signature"}
    ready = admin_channels._channel_launch_status(channel, runs)

    assert ready["ready"] is True
    assert ready["blockers"] == []
    assert ready["checklist"][0]["authMode"] == "hmac_signature"
    assert ready["checklist"][2]["authMode"] == "hmac_signature"
    assert ready["checklist"][3]["authMode"] == "hmac_signature"


def test_admin_channel_launch_status_requires_slack_signature_when_default_secret_present():
    channel = {"id": "channel1", "channelKey": "slack-main", "type": "slack", "status": "active", "config": {}}
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "transport": "http",
                "issueId": "issue1",
                "http": {"auth": {"mode": "token", "header": "X-Support-Sync-Token"}},
            },
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "sent": True},
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {
                    "transport": "http",
                    "issueId": "issue1",
                    "http": {"auth": {"mode": "token", "header": "X-Support-Sync-Token"}},
                },
                "issueId": "issue1",
                "replyId": "reply1",
            },
        },
        _attachment_lifecycle_run(
            auth={"mode": "token", "header": "X-Support-Sync-Token"},
        ),
    ]

    token_launch = admin_channels._channel_launch_status(
        channel,
        runs,
        {"SUPPORT_SLACK_SIGNING_SECRET": "signing-secret"},
    )

    assert token_launch["ready"] is False
    assert {item["key"] for item in token_launch["blockers"]} == {
        "inbound_smoke",
        "lifecycle_smoke",
        "attachment_lifecycle_smoke",
    }
    assert token_launch["checklist"][0]["detail"] == "Smoke run did not record required signature auth"
    assert token_launch["checklist"][2]["detail"] == "Smoke run did not record required signature auth"

    runs[0]["result"]["http"]["auth"] = {"mode": "slack_signature", "header": "X-Slack-Signature"}
    runs[2]["result"]["inbound"]["http"]["auth"] = {"mode": "slack_signature", "header": "X-Slack-Signature"}
    runs[3]["result"]["inbound"]["http"]["auth"] = {"mode": "slack_signature", "header": "X-Slack-Signature"}
    ready = admin_channels._channel_launch_status(channel, runs, {"SUPPORT_SLACK_SIGNING_SECRET": "signing-secret"})

    assert ready["ready"] is True
    assert ready["blockers"] == []
    assert ready["checklist"][0]["authMode"] == "slack_signature"
    assert ready["checklist"][2]["authMode"] == "slack_signature"


def test_admin_channel_launch_status_requires_telegram_secret_token_when_configured():
    channel = {"id": "channel1", "channelKey": "telegram-main", "type": "telegram", "status": "active", "config": {}}
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "transport": "http",
                "issueId": "issue1",
                "http": {"auth": {"mode": "token", "header": "X-Support-Sync-Token"}},
            },
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "sent": True},
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {
                    "transport": "http",
                    "issueId": "issue1",
                    "http": {"auth": {"mode": "token", "header": "X-Support-Sync-Token"}},
                },
                "issueId": "issue1",
                "replyId": "reply1",
            },
        },
        _attachment_lifecycle_run(
            auth={"mode": "token", "header": "X-Support-Sync-Token"},
        ),
    ]

    token_launch = admin_channels._channel_launch_status(
        channel,
        runs,
        {"SUPPORT_TELEGRAM_SECRET_TOKEN": "telegram-secret"},
    )

    assert token_launch["ready"] is False
    assert {item["key"] for item in token_launch["blockers"]} == {
        "inbound_smoke",
        "lifecycle_smoke",
        "attachment_lifecycle_smoke",
    }
    assert token_launch["checklist"][0]["detail"] == "Smoke run did not record required Telegram secret-token auth"
    assert token_launch["checklist"][2]["detail"] == "Smoke run did not record required Telegram secret-token auth"
    assert token_launch["checklist"][3]["detail"] == "Smoke run did not record required Telegram secret-token auth"

    runs[0]["result"]["http"]["auth"] = {
        "mode": "telegram_secret_token",
        "header": "X-Telegram-Bot-Api-Secret-Token",
    }
    runs[2]["result"]["inbound"]["http"]["auth"] = {
        "mode": "telegram_secret_token",
        "header": "X-Telegram-Bot-Api-Secret-Token",
    }
    runs[3]["result"]["inbound"]["http"]["auth"] = {
        "mode": "telegram_secret_token",
        "header": "X-Telegram-Bot-Api-Secret-Token",
    }
    ready = admin_channels._channel_launch_status(channel, runs, {"SUPPORT_TELEGRAM_SECRET_TOKEN": "telegram-secret"})

    assert ready["ready"] is True
    assert ready["blockers"] == []
    assert ready["checklist"][0]["authMode"] == "telegram_secret_token"
    assert ready["checklist"][2]["authMode"] == "telegram_secret_token"
    assert ready["checklist"][3]["authMode"] == "telegram_secret_token"


def test_admin_channel_launch_status_preserves_slack_timestamp_auth_artifact():
    channel = {"id": "channel1", "channelKey": "slack-main", "type": "slack", "status": "active"}
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "transport": "http",
                "issueId": "issue1",
                "http": {
                    "auth": {
                        "mode": "slack_signature",
                        "header": "X-Slack-Signature",
                        "timestampHeader": "X-Slack-Request-Timestamp",
                    }
                },
            },
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True, "sent": True},
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {
                    "transport": "http",
                    "issueId": "issue1",
                    "http": {
                        "auth": {
                            "mode": "slack_signature",
                            "header": "X-Slack-Signature",
                            "timestampHeader": "X-Slack-Request-Timestamp",
                        }
                    },
                },
                "issueId": "issue1",
                "replyId": "reply1",
            },
        },
        _attachment_lifecycle_run(),
    ]

    launch = admin_channels._channel_launch_status(channel, runs)

    assert launch["ready"] is True
    assert launch["blockers"] == []
    assert launch["checklist"][0]["signatureTimestampHeader"] == "X-Slack-Request-Timestamp"
    assert launch["checklist"][2]["signatureTimestampHeader"] == "X-Slack-Request-Timestamp"


def test_admin_channel_launch_status_rejects_legacy_validation_without_provider_result():
    channel = {
        "id": "channel1",
        "channelKey": "slack-main",
        "type": "slack",
        "status": "active",
        "config": {"outboundTransport": "bot", "smokeChannelId": "C_LIVE"},
    }
    runs = [
        {
            "id": "smoke1",
            "channel": "channel1",
            "source": "admin-smoke",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": _inbound_smoke_result(),
        },
        {
            "id": "validation1",
            "channel": "channel1",
            "source": "admin-validation",
            "status": "success",
            "processed": 1,
            "failed": 0,
            "result": {"ready": True},
        },
        {
            "id": "outSmoke1",
            "channel": "channel1",
            "source": "admin-outbound-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "providerMessageId": "slack:C123:2",
                **_provider_delivery_proof(),
            },
        },
        {
            "id": "lifeSmoke1",
            "channel": "channel1",
            "source": "admin-lifecycle-smoke",
            "status": "sent",
            "processed": 1,
            "failed": 0,
            "result": {
                "ready": True,
                "sent": True,
                "inbound": {"transport": "http", "issueId": "issue1"},
                "issueId": "issue1",
                "replyId": "reply1",
                "providerMessageId": "slack:C123:3",
                **_provider_delivery_proof(),
            },
        },
        _attachment_lifecycle_run(provider_delivery=True),
    ]

    launch = admin_channels._channel_launch_status(channel, runs)

    assert launch["ready"] is False
    assert launch["passed"] == 5
    assert {item["key"] for item in launch["blockers"]} == {"provider_validation"}
    assert launch["checklist"][2]["status"] == "warning"
    assert launch["checklist"][2]["detail"] == "success: 1 processed, 0 failed"


def test_admin_channel_launch_status_from_proof_preserves_artifact_ids():
    launch = admin_channels._channel_launch_status_from_proof({
        "required": True,
        "ready": True,
        "checks": 1,
        "passed": 1,
        "lastCheckedAt": "2026-07-03T10:00:00+00:00",
        "blockers": [],
        "checklist": [
            {
                "key": "lifecycle_smoke",
                "label": "Lifecycle smoke passed",
                "status": "done",
                "detail": "ok",
                "runId": "run1",
                "source": "admin-lifecycle-smoke",
                "runStatus": "sent",
                "processed": 1,
                "failed": 0,
                "sent": 1,
                "transport": "http",
                "startedAt": "2026-07-03T10:00:00+00:00",
                "providerMessageId": "slack:C123:3",
                **_provider_delivery_proof(),
                "issueId": "issue1",
                "replyId": "reply1",
            },
        ],
    })

    assert launch is not None
    assert launch["checklist"][0]["providerMessageId"] == "slack:C123:3"
    assert launch["checklist"][0]["deliveryRoute"]["provider"] == "slack"
    assert launch["checklist"][0]["providerResponse"]["statusCode"] == 200
    assert launch["checklist"][0]["issueId"] == "issue1"
    assert launch["checklist"][0]["replyId"] == "reply1"


def test_admin_channel_outbound_smoke_run_checks_active_external_channels(client, monkeypatch):
    calls: list[str] = []
    recorded: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {"id": "channel1", "channelKey": "slack-main", "type": "slack", "status": "active"},
            {"id": "channel2", "channelKey": "telegram-main", "type": "telegram", "status": "active"},
            {"id": "channel3", "channelKey": "email-main", "type": "email", "status": "active"},
            {"id": "channel4", "channelKey": "discord-main", "type": "discord", "status": "paused"},
        ],
    )

    def fake_run(channel: dict, *, body, ctx, request):
        calls.append(channel["id"])
        if channel["id"] == "channel2":
            raise ValueError("chat id missing")
        return {
            "channelId": channel["id"],
            "channelKey": channel["channelKey"],
            "type": channel["type"],
            "ready": True,
            "validation": {"ready": True},
            "messageId": "message1",
            "provider": "slack_webhook",
            "providerMessageId": "slack:C123:1",
            "status": "sent",
            "sent": True,
            "deferred": False,
            "failed": False,
            "processed": 1,
            "skipped": 0,
            "error": "",
            "retryAfterSeconds": 0,
            "metadata": {},
        }

    monkeypatch.setattr("automail.api.admin.channels._run_channel_outbound_smoke", fake_run)

    def fake_record_channel_sync_run(**kwargs):
        recorded.append(kwargs)
        return {"id": f"run{len(recorded)}", **kwargs}

    monkeypatch.setattr("automail.api.admin.channels.record_channel_sync_run", fake_record_channel_sync_run)

    resp = client.post(
        "/api/admin/projects/project1/channels/outbound-smoke/run",
        json={"body": "Thanks, we are checking.", "channelId": "C123"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "partial"
    assert data["channels"] == 2
    assert data["ready"] == 1
    assert data["processed"] == 2
    assert data["sent"] == 1
    assert data["deferred"] == 0
    assert data["failed"] == 1
    assert data["items"][0]["channelKey"] == "slack-main"
    assert data["items"][0]["runId"] == "run1"
    assert data["failures"] == [{
        "channelId": "channel2",
        "channelKey": "telegram-main",
        "error": "chat id missing",
        "runId": "run2",
    }]
    assert calls == ["channel1", "channel2"]
    assert [run["channel_id"] for run in recorded] == ["channel1", "channel2"]
    assert [run["source"] for run in recorded] == ["admin-outbound-smoke", "admin-outbound-smoke"]
    assert recorded[0]["result"]["status"] == "sent"
    assert recorded[1]["result"]["status"] == "failed"
    assert recorded[1]["result"]["error"] == "chat id missing"


def test_admin_channel_lifecycle_smoke_run_checks_active_external_channels(client, monkeypatch):
    calls: list[str] = []
    recorded: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.list_channels",
        lambda **_kwargs: [
            {"id": "channel1", "channelKey": "slack-main", "type": "slack", "status": "active"},
            {"id": "channel2", "channelKey": "telegram-main", "type": "telegram", "status": "active"},
            {"id": "channel3", "channelKey": "email-main", "type": "email", "status": "active"},
            {"id": "channel4", "channelKey": "discord-main", "type": "discord", "status": "paused"},
        ],
    )

    def fake_run(channel: dict, *, body, ctx, request, actor_email):
        calls.append(channel["id"])
        if channel["id"] == "channel2":
            raise ValueError("chat id missing")
        return {
            "channelId": channel["id"],
            "channelKey": channel["channelKey"],
            "type": channel["type"],
            "ready": True,
            "validation": {"ready": True},
            "inbound": {"status": "success"},
            "issueId": "issue1",
            "replyId": "reply1",
            "messageId": "message1",
            "provider": "slack_webhook",
            "providerMessageId": "slack:C123:1",
            "status": "sent",
            "sent": True,
            "deferred": False,
            "failed": False,
            "processed": 1,
            "skipped": 0,
            "error": "",
            "approval": {},
            "delivery": {},
        }

    monkeypatch.setattr("automail.api.admin.channels._run_channel_lifecycle_smoke", fake_run)

    def fake_record_channel_sync_run(**kwargs):
        recorded.append(kwargs)
        return {"id": f"run{len(recorded)}", **kwargs}

    monkeypatch.setattr("automail.api.admin.channels.record_channel_sync_run", fake_record_channel_sync_run)

    resp = client.post(
        "/api/admin/projects/project1/channels/lifecycle-smoke/run",
        json={"body": "Production API is down.", "replyBody": "Thanks, we are checking."},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "partial"
    assert data["channels"] == 2
    assert data["ready"] == 1
    assert data["processed"] == 2
    assert data["sent"] == 1
    assert data["deferred"] == 0
    assert data["failed"] == 1
    assert data["items"][0]["channelKey"] == "slack-main"
    assert data["items"][0]["runId"] == "run1"
    assert data["failures"] == [{
        "channelId": "channel2",
        "channelKey": "telegram-main",
        "error": "chat id missing",
        "runId": "run2",
    }]
    assert calls == ["channel1", "channel2"]
    assert [run["channel_id"] for run in recorded] == ["channel1", "channel2"]
    assert [run["source"] for run in recorded] == ["admin-lifecycle-smoke", "admin-lifecycle-smoke"]
    assert recorded[0]["result"]["status"] == "sent"
    assert recorded[1]["result"]["status"] == "failed"
    assert recorded[1]["result"]["error"] == "chat id missing"


def test_admin_channel_smoke_uses_teams_native_payload(client, monkeypatch):
    calls: list[dict] = []
    completed: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "teams-main",
            "type": "teams",
            "name": "Teams",
            "status": "active",
            "config": {},
        },
    )
    monkeypatch.setattr("automail.api.admin.channels.load_runtime_secrets", lambda *_args, **_kwargs: {})

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {"status": "success", "processed": 1, "ignored": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    monkeypatch.setattr("automail.api.admin.channels.ingest_teams_event", fake_ingest)
    monkeypatch.setattr(
        "automail.api.admin.channels.update_issue",
        lambda issue_id, **kwargs: completed.append({"issue_id": issue_id, **kwargs}) or {"id": issue_id, "status": "done"},
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/smoke",
        json={
            "body": "Need help",
            "authorName": "Ana",
            "channelId": "teams-channel-1",
            "threadId": "conversation-1",
            "messageId": "message-1",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "teams"
    assert data["messageId"] == "msg1"
    assert data["cleanup"]["workflowSource"] == "admin-channel-smoke-cleanup"
    assert calls[0]["channel_key"] == "teams-main"
    assert calls[0]["source"] == "admin-smoke"
    payload = calls[0]["payload"]
    assert payload["type"] == "message"
    assert payload["id"] == "message-1"
    assert payload["text"] == "Need help"
    assert payload["conversation"]["id"] == "conversation-1"
    assert payload["channelData"]["channel"]["id"] == "teams-channel-1"
    assert payload["from"]["name"] == "Ana"
    assert completed[0]["updates"]["status"] == "done"


def test_admin_channel_smoke_uses_discord_gateway_payload(client, monkeypatch):
    calls: list[dict] = []
    completed: list[dict] = []
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "discord-main",
            "type": "discord",
            "name": "Discord",
            "status": "active",
            "config": {},
        },
    )
    monkeypatch.setattr("automail.api.admin.channels.load_runtime_secrets", lambda *_args, **_kwargs: {})

    def fake_ingest(channel_key: str, **kwargs):
        calls.append({"channel_key": channel_key, **kwargs})
        return {
            "status": "success",
            "processed": 1,
            "failed": 0,
            "skipped": 0,
            "items": [{"kind": "inbound_message", "issueId": "issue1", "messageId": "msg1"}],
        }

    monkeypatch.setattr("automail.api.admin.channels.ingest_channel_webhook", fake_ingest)
    monkeypatch.setattr(
        "automail.api.admin.channels.update_issue",
        lambda issue_id, **kwargs: completed.append({"issue_id": issue_id, **kwargs}) or {"id": issue_id, "status": "done"},
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/smoke",
        json={
            "body": "Production API is down.",
            "authorName": "Ana",
            "authorEmail": "ana@example.com",
            "channelId": "discord-channel-1",
            "messageId": "discord-message-1",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "discord"
    assert data["issueId"] == "issue1"
    assert data["cleanup"]["workflowSource"] == "admin-channel-smoke-cleanup"
    assert calls[0]["channel_key"] == "discord-main"
    assert calls[0]["source"] == "discord-admin-smoke"
    payload = calls[0]["payload"]
    assert payload["t"] == "MESSAGE_CREATE"
    assert payload["d"]["id"] == "discord-message-1"
    assert payload["d"]["channel_id"] == "discord-channel-1"
    assert payload["d"]["content"] == "Production API is down."
    assert payload["d"]["author"]["username"] == "Ana"
    assert payload["d"]["author"]["email"] == "ana@example.com"
    assert completed[0]["updates"]["status"] == "done"


def test_admin_channel_smoke_http_posts_signed_slack_payload(client, monkeypatch):
    import hashlib
    import hmac

    posted: dict[str, object] = {}
    completed: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url: str, content: bytes, headers: dict):
            posted["url"] = url
            posted["content"] = content
            posted["headers"] = headers
            timestamp = headers["X-Slack-Request-Timestamp"]
            expected = "v0=" + hmac.new(
                b"signing-secret",
                f"v0:{timestamp}:".encode("utf-8") + content,
                hashlib.sha256,
            ).hexdigest()
            assert headers["X-Slack-Signature"] == expected
            return FakeResponse()

    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.update_issue",
        lambda issue_id, **kwargs: completed.append({"issue_id": issue_id, **kwargs}) or {"id": issue_id, "status": "done"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {"SUPPORT_SLACK_SIGNING_SECRET": "signing-secret"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "slack-main",
            "type": "slack",
            "name": "Slack",
            "status": "active",
            "config": {"slackSigningSecretEnv": "SUPPORT_SLACK_SIGNING_SECRET"},
        },
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/smoke",
        json={"body": "Need help", "channelId": "C123", "messageId": "1710000000.000100", "transport": "http"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["transport"] == "http"
    assert data["issueId"] == "issue1"
    assert data["cleanup"]["workflowSource"] == "admin-channel-smoke-cleanup"
    assert data["http"]["auth"]["mode"] == "slack_signature"
    assert data["http"]["auth"]["env"] == "SUPPORT_SLACK_SIGNING_SECRET"
    assert data["http"]["auth"]["timestampHeader"] == "X-Slack-Request-Timestamp"
    assert str(posted["url"]).endswith("/api/internal/support/slack/slack-main?project_id=project1")
    assert b'"type":"event_callback"' in posted["content"]
    assert b'"channel":"C123"' in posted["content"]
    assert completed[0]["updates"]["status"] == "done"


def test_admin_channel_smoke_http_prefers_telegram_hmac_when_signing_secret_configured(client, monkeypatch):
    import hashlib
    import hmac

    posted: dict[str, object] = {}
    completed: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url: str, content: bytes, headers: dict):
            posted["url"] = url
            posted["content"] = content
            posted["headers"] = headers
            expected = hmac.new(b"signing-secret", content, hashlib.sha256).hexdigest()
            assert headers["X-Support-Signature"] == f"sha256={expected}"
            assert "X-Telegram-Bot-Api-Secret-Token" not in headers
            return FakeResponse()

    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.update_issue",
        lambda issue_id, **kwargs: completed.append({"issue_id": issue_id, **kwargs}) or {"id": issue_id, "status": "done"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {
            "SUPPORT_TELEGRAM_SECRET_TOKEN": "telegram-secret",
            "SUPPORT_TELEGRAM_SIGNING_SECRET": "signing-secret",
        },
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "telegram-main",
            "type": "telegram",
            "name": "Telegram",
            "status": "active",
            "config": {
                "telegramSecretTokenEnv": "SUPPORT_TELEGRAM_SECRET_TOKEN",
                "telegramSigningSecretEnv": "SUPPORT_TELEGRAM_SIGNING_SECRET",
            },
        },
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/smoke",
        json={"body": "Need help", "channelId": "chat-1", "messageId": "123", "transport": "http"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["transport"] == "http"
    assert data["issueId"] == "issue1"
    assert data["cleanup"]["workflowSource"] == "admin-channel-smoke-cleanup"
    assert data["http"]["auth"]["mode"] == "hmac_signature"
    assert data["http"]["auth"]["env"] == "SUPPORT_TELEGRAM_SIGNING_SECRET"
    assert str(posted["url"]).endswith("/api/internal/support/telegram/telegram-main?project_id=project1")
    assert b'"message_id":123' in posted["content"]
    assert completed[0]["updates"]["status"] == "done"


def test_admin_channel_smoke_http_records_telegram_secret_token_auth(client, monkeypatch):
    posted: dict[str, object] = {}
    completed: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"status": "success", "processed": 1, "failed": 0, "skipped": 0, "issueId": "issue1", "messageId": "msg1"}

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url: str, content: bytes, headers: dict):
            posted["url"] = url
            posted["content"] = content
            posted["headers"] = headers
            assert headers["X-Telegram-Bot-Api-Secret-Token"] == "telegram-secret"
            assert "X-Support-Signature" not in headers
            return FakeResponse()

    monkeypatch.setattr("automail.api.admin.channels.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "automail.api.admin.channels.update_issue",
        lambda issue_id, **kwargs: completed.append({"issue_id": issue_id, **kwargs}) or {"id": issue_id, "status": "done"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.load_runtime_secrets",
        lambda tenant_id, project_id: {"SUPPORT_TELEGRAM_SECRET_TOKEN": "telegram-secret"},
    )
    monkeypatch.setattr(
        "automail.api.admin.channels.get_channel",
        lambda channel_id, **_kwargs: {
            "id": channel_id,
            "channelKey": "telegram-main",
            "type": "telegram",
            "name": "Telegram",
            "status": "active",
            "config": {"telegramSecretTokenEnv": "SUPPORT_TELEGRAM_SECRET_TOKEN"},
        },
    )

    resp = client.post(
        "/api/admin/projects/project1/channels/channel1/smoke",
        json={"body": "Need help", "channelId": "chat-1", "messageId": "123", "transport": "http"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["transport"] == "http"
    assert data["issueId"] == "issue1"
    assert data["cleanup"]["workflowSource"] == "admin-channel-smoke-cleanup"
    assert data["http"]["auth"]["mode"] == "telegram_secret_token"
    assert data["http"]["auth"]["env"] == "SUPPORT_TELEGRAM_SECRET_TOKEN"
    assert data["http"]["auth"]["header"] == "X-Telegram-Bot-Api-Secret-Token"
    assert str(posted["url"]).endswith("/api/internal/support/telegram/telegram-main?project_id=project1")
    assert completed[0]["updates"]["status"] == "done"


def test_public_support_portal_returns_issue(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.support_portal.get_customer_portal",
        lambda token: {
            "session": {"id": "portal1"},
            "issue": {"id": "issue1", "subject": "Need help", "messages": []},
        } if token == "portal-token" else None,
    )

    resp = client.get("/api/support/portal/portal-token")

    assert resp.status_code == 200
    assert resp.json()["issue"]["id"] == "issue1"


def test_public_support_portal_accepts_customer_message(client, monkeypatch):
    calls: list[dict] = []

    def fake_create(token: str, **kwargs):
        calls.append({"token": token, **kwargs})
        return {"id": "message1", "body": kwargs["body"], "direction": "customer"}

    monkeypatch.setattr("automail.api.support_portal.create_customer_portal_message", fake_create)

    resp = client.post(
        "/api/support/portal/portal-token/messages",
        json={"body": "Still need help.", "senderEmail": "customer@example.com"},
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == "message1"
    assert calls == [{
        "token": "portal-token",
        "body": "Still need help.",
        "sender_name": "",
        "sender_email": "customer@example.com",
    }]


def test_public_support_portal_accepts_feedback(client, monkeypatch):
    calls: list[dict] = []

    def fake_create(token: str, **kwargs):
        calls.append({"token": token, **kwargs})
        return {"id": "feedback1", "rating": kwargs["rating"], "comment": kwargs["comment"]}

    monkeypatch.setattr("automail.api.support_portal.create_customer_portal_feedback", fake_create)

    resp = client.post(
        "/api/support/portal/portal-token/feedback",
        json={"rating": 5, "comment": "Solved fast.", "senderEmail": "customer@example.com"},
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == "feedback1"
    assert calls == [{
        "token": "portal-token",
        "rating": 5,
        "comment": "Solved fast.",
        "sender_name": "",
        "sender_email": "customer@example.com",
    }]


def test_public_support_portal_page_includes_project_knowledge_search(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.support_portal.get_customer_portal",
        lambda token: {
            "session": {"id": "portal1", "projectId": "project1"},
            "issue": {"id": "issue1", "subject": "Need help", "messages": []},
            "feedback": None,
        } if token == "portal-token" else None,
    )

    resp = client.get("/support/portal/portal-token")

    assert resp.status_code == 200
    body = resp.text
    assert 'data-portal-help="true"' in body
    assert "Help articles" in body
    assert 'const portalProjectId = "project1";' in body
    assert "renderHelpArticles" in body
    assert "openHelpArticle" in body
    assert "'/api/support/knowledge/' + encodeURIComponent(portalProjectId)" in body
    assert "void searchHelp('');" in body


def test_public_knowledge_lists_published_articles(client, monkeypatch):
    calls: list[dict] = []

    def fake_list(**kwargs):
        calls.append(kwargs)
        return [
            {
                "id": "article1",
                "title": "Reset password",
                "excerpt": "Use the reset link.",
                "status": "published",
                "tags": ["auth"],
                "updated": "2026-07-03 10:00:00.000Z",
            }
        ]

    monkeypatch.setattr("automail.api.support_knowledge.list_public_knowledge_articles", fake_list)

    resp = client.get("/api/support/knowledge/project1", params={"q": "reset", "limit": 20})

    assert resp.status_code == 200
    assert resp.json()["items"][0]["id"] == "article1"
    assert calls == [{
        "tenant_id": None,
        "project_id": "project1",
        "query": "reset",
        "limit": 20,
    }]


def test_public_knowledge_article_detail_hides_missing_articles(client, monkeypatch):
    calls: list[dict] = []

    def fake_get(article_id: str, **kwargs):
        calls.append({"article_id": article_id, **kwargs})
        if article_id != "article1":
            return None
        return {
            "id": "article1",
            "title": "Reset password",
            "body": "Use the reset link.",
            "excerpt": "Use the reset link.",
            "status": "published",
            "tags": ["auth"],
            "updated": "2026-07-03 10:00:00.000Z",
        }

    monkeypatch.setattr("automail.api.support_knowledge.get_public_knowledge_article", fake_get)

    ok = client.get("/api/support/knowledge/project1/articles/article1")
    missing = client.get("/api/support/knowledge/project1/articles/draft1")

    assert ok.status_code == 200
    assert ok.json()["body"] == "Use the reset link."
    assert missing.status_code == 404
    assert calls[0] == {
        "article_id": "article1",
        "tenant_id": None,
        "project_id": "project1",
    }


def test_public_knowledge_page_renders_search_and_article_links(client, monkeypatch):
    monkeypatch.setattr(
        "automail.api.support_knowledge.list_public_knowledge_articles",
        lambda **_kwargs: [
            {
                "id": "article1",
                "title": "Reset password",
                "excerpt": "Use the reset link.",
                "status": "published",
                "tags": ["auth"],
                "updated": "2026-07-03 10:00:00.000Z",
            }
        ],
    )

    resp = client.get("/support/knowledge/project1", params={"q": "reset"})

    assert resp.status_code == 200
    assert 'data-public-help-center="true"' in resp.text
    assert "Help center" in resp.text
    assert "Reset password" in resp.text
    assert "/support/knowledge/project1/articles/article1" in resp.text


def test_public_web_chat_starts_session(client, monkeypatch):
    calls: list[dict] = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return {"id": "session1", "sessionKey": "web-session-token", "issue": {"id": "issue1"}, "message": {"id": "msg1"}}

    monkeypatch.setattr("automail.api.support_web_chat.create_web_chat_session", fake_create)

    resp = client.post(
        "/api/support/web-chat/project1/sessions",
        json={
            "channelKey": "web-chat",
            "visitorEmail": "ana@example.com",
            "visitorName": "Ana",
            "initialMessage": "Need help.",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["sessionKey"] == "web-session-token"
    assert calls == [{
        "tenant_id": None,
        "project_id": "project1",
        "channel_key": "web-chat",
        "visitor_id": "",
        "visitor_email": "ana@example.com",
        "visitor_name": "Ana",
        "page_url": "",
        "initial_message": "Need help.",
        "metadata": None,
    }]


def test_public_web_chat_accepts_message(client, monkeypatch):
    calls: list[dict] = []

    def fake_create(session_key: str, **kwargs):
        calls.append({"session_key": session_key, **kwargs})
        return {"id": "msg2", "body": kwargs["body"]}

    monkeypatch.setattr("automail.api.support_web_chat.create_web_chat_message", fake_create)

    resp = client.post(
        "/api/support/web-chat/sessions/web-session-token/messages",
        json={"body": "Still need help.", "senderEmail": "ana@example.com"},
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == "msg2"
    assert calls == [{
        "session_key": "web-session-token",
        "body": "Still need help.",
        "sender_name": "",
        "sender_email": "ana@example.com",
    }]


def test_public_web_chat_page_preserves_customer_page_context(client):
    resp = client.get(
        "/support/web-chat/project1",
        params={
            "channel_key": "web-chat",
            "page_url": "https://customer.example/pricing?plan=pro",
            "page_title": "Pricing",
            "referrer": "https://google.example/search",
        },
    )

    assert resp.status_code == 200
    body = resp.text
    assert 'const sourcePageUrl = "https://customer.example/pricing?plan=pro" || window.location.href;' in body
    assert 'const sourcePageTitle = "Pricing" || document.title;' in body
    assert 'const sourceReferrer = "https://google.example/search" || document.referrer;' in body
    assert "pageUrl: sourcePageUrl" in body
    assert "metadata: metadata()" in body
    assert 'data-web-chat-help="true"' in body
    assert "const helpSearchEl = document.getElementById('helpSearch');" in body
    assert "'/api/support/knowledge/' + encodeURIComponent(projectId)" in body
    assert "'/articles/' + encodeURIComponent(articleId)" in body
    assert "void searchHelp('');" in body
    assert "window.setInterval(refresh, 10000);" in body


def test_public_web_chat_help_uses_project_scoped_knowledge(client):
    resp = client.get("/support/web-chat/project1", params={"channel_key": "web-chat"})

    assert resp.status_code == 200
    body = resp.text
    assert "Help articles" in body
    assert 'id="helpSearch"' in body
    assert "renderHelpArticles" in body
    assert "openHelpArticle" in body
    assert "/api/support/knowledge/" in body
    assert "encodeURIComponent(projectId)" in body


def test_public_web_chat_embed_script_uses_script_origin(client):
    resp = client.get(
        "/support/web-chat/project1/embed.js",
        params={"channel_key": "web-chat", "label": "Ask us", "position": "bottom-left"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    body = resp.text
    assert "const projectId = \"project1\";" in body
    assert "const channelKey = \"web-chat\";" in body
    assert "const label = \"Ask us\";" in body
    assert "const position = \"bottom-left\";" in body
    assert "const scriptUrl = currentScript && currentScript.src ? new URL(currentScript.src) : new URL(window.location.href);" in body
    assert "const baseUrl = scriptUrl.origin;" in body
    assert "chatUrl.searchParams.set('channel_key', channelKey);" in body
    assert "chatUrl.searchParams.set('page_url', window.location.href);" in body
    assert "if (document.title) chatUrl.searchParams.set('page_title', document.title);" in body
    assert "if (document.referrer) chatUrl.searchParams.set('referrer', document.referrer);" in body
    assert "automail-support-chat-status" in body
    assert "event.origin !== baseUrl" in body
    assert "data-automail-support-chat-latest-ticket" in body
    assert "data-automail-support-chat-ticket-count" in body
    assert "data-automail-support-chat-message-count" in body
    assert "document.body.appendChild(root);" in body
