from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from automail.api.process import process_email_for_context
from automail.db.pocketbase import email_processing_claims as claims
from automail.models import AgentResponse, Email, IdentityResult, IntentResult, ProcessEmailRequest


class _FakeClaimStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: dict[str, dict[str, Any]] = {}

    def list_all(self, collection: str, *_args, **_kwargs) -> list[dict[str, Any]]:
        assert collection == "email_processing_claims"
        with self._lock:
            return [dict(record) for record in self.records.values()]

    def post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        assert path == "/api/collections/email_processing_claims/records"
        with self._lock:
            if data["id"] in self.records:
                request = httpx.Request("POST", "http://pb.test" + path)
                response = httpx.Response(400, request=request, json={"message": "duplicate"})
                raise httpx.HTTPStatusError("duplicate", request=request, response=response)
            self.records[data["id"]] = dict(data)
            return dict(data)

    def patch(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        record_id = path.rsplit("/", 1)[-1]
        with self._lock:
            self.records[record_id].update(data)
            return dict(self.records[record_id])


def _install_claim_store(monkeypatch, store: _FakeClaimStore) -> None:
    monkeypatch.setattr(claims, "_list_all", store.list_all)
    monkeypatch.setattr(claims, "_post", store.post)
    monkeypatch.setattr(claims, "_patch", store.patch)


def _request() -> ProcessEmailRequest:
    return ProcessEmailRequest(
        email=Email(
            id="channel:email-main:provider-message-1",
            subject="Cancel and quote",
            from_address="customer@example.test",
            body="Cancel order 7 and quote the replacement.",
            attachments=[],
        ),
        creator="email-webhook",
        project_id="project-1",
    )


def _pipeline_result() -> SimpleNamespace:
    return SimpleNamespace(
        agent_response=AgentResponse(
            response_text="We can help with both requests.",
            activated_intent="order-change",
        ),
        identity_result=IdentityResult(customer_found=True, data={"customerId": "customer-1"}),
        intent_result=IntentResult(matched=True, intent_name="order-change"),
        phishing_result=None,
        prompt_injection_result=None,
        token_usage={},
        tools_used=[],
    )


def test_atomic_claim_elects_one_owner_for_overlapping_workers(monkeypatch):
    store = _FakeClaimStore()
    _install_claim_store(monkeypatch, store)
    barrier = threading.Barrier(2)
    original_latest = claims._latest_claim

    def synchronized_latest(*, project_id: str, email_id: str):
        result = original_latest(project_id=project_id, email_id=email_id)
        if not result:
            barrier.wait(timeout=2)
        return result

    monkeypatch.setattr(claims, "_latest_claim", synchronized_latest)
    results: list[dict[str, Any]] = []

    def acquire() -> None:
        results.append(
            claims.acquire_email_processing_claim(
                email_id="message-1",
                tenant_id="tenant-1",
                project_id="project-1",
            )
        )

    workers = [threading.Thread(target=acquire) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)

    assert all(not worker.is_alive() for worker in workers)
    assert sum(result["owned"] is True for result in results) == 1
    assert {result["attempt"] for result in results} == {1}
    assert len(store.records) == 1


def test_expired_claim_recovery_advances_attempt_without_reusing_record(monkeypatch):
    store = _FakeClaimStore()
    _install_claim_store(monkeypatch, store)
    first = claims.acquire_email_processing_claim(
        email_id="message-1",
        tenant_id="tenant-1",
        project_id="project-1",
        lease_seconds=1,
    )
    store.patch(
        f"/api/collections/email_processing_claims/records/{first['id']}",
        {"lease_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},
    )

    recovered = claims.acquire_email_processing_claim(
        email_id="message-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert recovered["owned"] is True
    assert recovered["attempt"] == 2
    assert recovered["id"] != first["id"]
    assert len(store.records) == 2


def test_overlapping_connected_email_runs_pipeline_store_and_sync_once(monkeypatch):
    store = _FakeClaimStore()
    _install_claim_store(monkeypatch, store)
    pipeline_started = threading.Event()
    release_pipeline = threading.Event()
    sync_started = threading.Event()
    release_sync = threading.Event()
    chat_lock = threading.Lock()
    stored_chat: dict[str, Any] | None = None
    counts = {"pipeline": 0, "store": 0, "sync": 0, "recorder": 0}

    def get_chat(*_args, **_kwargs):
        with chat_lock:
            return dict(stored_chat) if stored_chat else None

    def run_pipeline(*_args, **_kwargs):
        counts["pipeline"] += 1
        pipeline_started.set()
        assert release_pipeline.wait(timeout=3)
        return _pipeline_result()

    def store_email_analysis(email_id, creator, messages, **kwargs):
        nonlocal stored_chat
        counts["store"] += 1
        with chat_lock:
            stored_chat = {
                "record_id": "chat-record-1",
                "id": email_id,
                "email_id": email_id,
                "creator": creator,
                "messages": messages,
                "activated_intent": kwargs.get("activated_intent"),
            }
        return "chat-record-1"

    def sync_issue(*_args, **_kwargs):
        counts["sync"] += 1
        sync_started.set()
        assert release_sync.wait(timeout=3)
        return True

    def recorder(**_kwargs):
        counts["recorder"] += 1
        return SimpleNamespace(finish=lambda **_finish_kwargs: None)

    monkeypatch.setattr("automail.api.process.ensure_draft_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.process.get_live_source", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.process.get_chat", get_chat)
    monkeypatch.setattr(claims, "get_chat", get_chat)
    monkeypatch.setattr("automail.api.process.parse_email_attachments", lambda _email: {})
    monkeypatch.setattr("automail.api.process.run_pipeline", run_pipeline)
    monkeypatch.setattr("automail.api.process.load_attachment_files", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.api.process.store_email_analysis", store_email_analysis)
    monkeypatch.setattr("automail.api.process._sync_issue_from_chat", sync_issue)
    monkeypatch.setattr("automail.api.process.RunRecorder", recorder)
    monkeypatch.setattr(
        "automail.db.pocketbase.client.store_llm_usage_events",
        lambda *_args, **_kwargs: None,
    )

    results: list[list[Any]] = []
    errors: list[BaseException] = []

    def process() -> None:
        try:
            results.append(
                process_email_for_context(
                    _request(),
                    tenant_id=None,
                    payload=None,
                    source="channel:email-main",
                    project_id_override="project-1",
                )
            )
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=process)
    second = threading.Thread(target=process)
    first.start()
    assert pipeline_started.wait(timeout=2), errors
    second.start()
    assert not release_pipeline.wait(timeout=0.05)
    assert counts["pipeline"] == 1
    release_pipeline.set()
    assert sync_started.wait(timeout=2), errors
    assert second.is_alive()
    assert results == []
    assert counts == {"pipeline": 1, "store": 1, "sync": 1, "recorder": 1}
    release_sync.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert len(results) == 2
    assert [message.model_dump() for message in results[0]] == [
        message.model_dump() for message in results[1]
    ]
    assert counts == {"pipeline": 1, "store": 1, "sync": 1, "recorder": 1}
    assert len(store.records) == 1
    assert next(iter(store.records.values()))["status"] == "completed"


def test_connected_email_claim_fails_when_issue_sync_does_not_complete(monkeypatch):
    store = _FakeClaimStore()
    _install_claim_store(monkeypatch, store)
    monkeypatch.setattr("automail.api.process.ensure_draft_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.process.get_live_source", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.process.get_chat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.process.parse_email_attachments", lambda _email: {})
    monkeypatch.setattr("automail.api.process.run_pipeline", lambda *_args, **_kwargs: _pipeline_result())
    monkeypatch.setattr("automail.api.process.load_attachment_files", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("automail.api.process.store_email_analysis", lambda *_args, **_kwargs: "chat-record-1")
    monkeypatch.setattr("automail.api.process._sync_issue_from_chat", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "automail.api.process.RunRecorder",
        lambda **_kwargs: SimpleNamespace(finish=lambda **_finish_kwargs: None),
    )
    monkeypatch.setattr(
        "automail.db.pocketbase.client.store_llm_usage_events",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(HTTPException) as error:
        process_email_for_context(
            _request(),
            tenant_id=None,
            payload=None,
            source="channel:email-main",
            project_id_override="project-1",
        )

    assert error.value.status_code == 500
    assert len(store.records) == 1
    assert next(iter(store.records.values()))["status"] == "failed"
