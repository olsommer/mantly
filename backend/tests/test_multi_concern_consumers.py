import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from automail.api.attachments import load_attachment_files
from automail.models import (
    AgentResponse,
    Email,
    IdentityResult,
    IntentAction,
    IntentResult,
    ProcessEmailRequest,
    RunbookAttachment,
    RunbookOutcome,
)
from automail.monitoring.summaries import actions_from_intent
from automail.pipeline.intent.consumers import resolve_intent_action_payloads


def _action(name: str, *, payload: dict | None = None) -> IntentAction:
    return IntentAction(
        name=name,
        label=f"Run {name}",
        type="button",
        method="POST",
        payload=payload or {},
    )


def _concern(
    concern_id: str,
    runbook: str,
    *,
    actions: list[IntentAction] | None = None,
    attachments: list[RunbookAttachment] | None = None,
) -> RunbookOutcome:
    return RunbookOutcome(
        concern_id=concern_id,
        matched=True,
        intent_name=runbook,
        status="ready",
        actions=actions or [],
        attachments=attachments or [],
    )


def _pipeline_result(intent_result: IntentResult) -> SimpleNamespace:
    return SimpleNamespace(
        agent_response=AgentResponse(
            response_text="One reply.",
            activated_intent="cancel-contract",
            response_attachments=["quote.pdf"],
        ),
        identity_result=IdentityResult(data={"customerId": "customer-7"}),
        intent_result=intent_result,
        phishing_result=None,
        prompt_injection_result=None,
        token_usage={},
        tools_used=[],
    )


def _request_body() -> ProcessEmailRequest:
    return ProcessEmailRequest(
        email=Email(
            id="message-1",
            subject="Cancel and buy",
            from_address="buyer@example.test",
            body="Cancel C-1 and quote XYZ.",
            attachments=[],
        ),
        creator="agent@example.test",
    )


def test_monitoring_summarizes_actions_from_every_concern_with_scope():
    result = IntentResult(
        matched=True,
        intent_name="cancel-contract",
        actions=[_action("cancel")],
        concerns=[
            _concern("concern-cancel", "cancel-contract", actions=[_action("cancel")]),
            _concern("concern-buy", "buy-product", actions=[_action("buy")]),
        ],
    )

    assert actions_from_intent(result) == [
        {
            "type": "button",
            "label": "Run cancel",
            "method": "POST",
            "status": "available",
            "concernId": "concern-cancel",
            "runbook": "cancel-contract",
        },
        {
            "type": "button",
            "label": "Run buy",
            "method": "POST",
            "status": "available",
            "concernId": "concern-buy",
            "runbook": "buy-product",
        },
    ]


def test_identity_payload_resolution_updates_legacy_and_every_concern_action():
    result = IntentResult(
        matched=True,
        intent_name="cancel-contract",
        actions=[_action("cancel", payload={"contractId": "C-1"})],
        concerns=[
            _concern(
                "concern-cancel",
                "cancel-contract",
                actions=[_action("cancel", payload={"contractId": "C-1"})],
            ),
            _concern(
                "concern-buy",
                "buy-product",
                actions=[_action("buy", payload={"sku": "XYZ"})],
            ),
        ],
    )

    resolve_intent_action_payloads(result, {"customerId": "customer-7", "sku": "identity-sku"})

    assert result.actions[0].payload == {"customerId": "customer-7", "sku": "identity-sku", "contractId": "C-1"}
    assert result.concerns[0].actions[0].payload == {
        "customerId": "customer-7",
        "sku": "identity-sku",
        "contractId": "C-1",
    }
    assert result.concerns[1].actions[0].payload == {
        "customerId": "customer-7",
        "sku": "XYZ",
    }


def test_process_passes_multi_concern_result_to_attachment_loader(monkeypatch):
    from automail.api.process import process_email_for_context

    result = IntentResult(
        matched=True,
        intent_name="cancel-contract",
        actions=[_action("cancel")],
        concerns=[
            _concern("concern-cancel", "cancel-contract", actions=[_action("cancel")]),
            _concern(
                "concern-buy",
                "buy-product",
                actions=[_action("buy")],
                attachments=[RunbookAttachment(filename="quote.pdf")],
            ),
        ],
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr("automail.api.process.get_chat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.process.parse_email_attachments", lambda _email: {})
    monkeypatch.setattr("automail.api.process.run_pipeline", lambda *_args, **_kwargs: _pipeline_result(result))
    monkeypatch.setattr(
        "automail.api.process.load_attachment_files",
        lambda _response, intents_dir=None, intent_result=None, strict_intent_ownership=False: captured.update(
            {
                "intent_result": intent_result,
                "strict_intent_ownership": strict_intent_ownership,
            }
        ) or [],
    )
    monkeypatch.setattr("automail.api.process.store_email_analysis", lambda *_args, **_kwargs: "record-1")
    monkeypatch.setattr("automail.api.process._sync_issue_from_chat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "automail.api.process.RunRecorder",
        lambda **_kwargs: SimpleNamespace(finish=lambda **_finish_kwargs: None),
    )
    monkeypatch.setattr("automail.db.pocketbase.client.store_llm_usage_events", lambda *_args, **_kwargs: None)

    process_email_for_context(_request_body(), tenant_id=None, payload=None)

    assert captured["intent_result"] is result
    assert captured["strict_intent_ownership"] is True
    assert result.concerns[1].actions[0].payload == {"customerId": "customer-7"}


def test_admin_preview_passes_multi_concern_result_to_attachment_loader(monkeypatch):
    from automail.api.admin.preview import preview_email

    result = IntentResult(
        matched=True,
        intent_name="cancel-contract",
        actions=[_action("cancel")],
        concerns=[
            _concern("concern-cancel", "cancel-contract", actions=[_action("cancel")]),
            _concern(
                "concern-buy",
                "buy-product",
                actions=[_action("buy")],
                attachments=[RunbookAttachment(filename="quote.pdf")],
            ),
        ],
    )
    captured: dict[str, object] = {}
    source = SimpleNamespace(project_id="project-1", tenant_id="tenant-1", mode="draft")

    class FakeRequest:
        async def json(self):
            return _request_body().model_dump(by_alias=True)

    monkeypatch.setattr("automail.api.admin.preview.get_draft_source", lambda *_args, **_kwargs: source)
    monkeypatch.setattr("automail.api.admin.preview.ensure_draft_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.api.admin.preview.get_token_payload", lambda _request: None)
    monkeypatch.setattr(
        "automail.api.admin.preview.RunRecorder",
        lambda **_kwargs: SimpleNamespace(finish=lambda **_finish_kwargs: None),
    )
    monkeypatch.setattr("automail.pipeline.run_pipeline", lambda *_args, **_kwargs: _pipeline_result(result))
    monkeypatch.setattr(
        "automail.api.attachments.load_attachment_files",
        lambda _response, intents_dir=None, intent_result=None, strict_intent_ownership=False: captured.update(
            {
                "intent_result": intent_result,
                "strict_intent_ownership": strict_intent_ownership,
            }
        ) or [],
    )
    monkeypatch.setattr("automail.db.pocketbase.client.upsert_email_analysis", lambda *_args, **_kwargs: None)

    asyncio.run(
        preview_email.__wrapped__(
            FakeRequest(),
            SimpleNamespace(project_id="project-1", tenant_id="tenant-1"),
        )
    )

    assert captured["intent_result"] is result
    assert captured["strict_intent_ownership"] is True
    assert result.concerns[1].actions[0].payload == {"customerId": "customer-7"}


def test_attachment_loader_prefers_secondary_runbook_that_owns_selected_file(monkeypatch):
    filters: list[str] = []

    def fake_list_all(collection, filter_str="", sort="-created", per_page=200):
        assert collection == "intent_attachments"
        filters.append(filter_str)
        if "intent='buy-product'" in filter_str:
            return [
                {
                    "id": "attachment-2",
                    "filename": "quote.pdf",
                    "file": "stored-quote.pdf",
                    "content_type": "application/pdf",
                }
            ]
        return []

    monkeypatch.setattr("automail.api.attachments._list_all", fake_list_all)
    monkeypatch.setattr(
        "automail.api.attachments._get_binary",
        lambda path: (b"secondary-runbook", "application/pdf"),
    )
    result = IntentResult(
        matched=True,
        intent_name="cancel-contract",
        concerns=[
            _concern("concern-cancel", "cancel-contract"),
            _concern(
                "concern-buy",
                "buy-product",
                attachments=[RunbookAttachment(filename="quote.pdf")],
            ),
        ],
    )
    response = AgentResponse(
        response_text="Attached.",
        activated_intent="cancel-contract",
        response_attachments=["quote.pdf"],
    )

    attachments = load_attachment_files(
        response,
        intents_dir=SimpleNamespace(project_id="project-1"),
        intent_result=result,
        strict_intent_ownership=True,
    )

    assert filters == [
        "project='project-1' && filename='quote.pdf' && intent='buy-product'",
    ]
    assert attachments == [
        {
            "filename": "quote.pdf",
            "content_base64": "c2Vjb25kYXJ5LXJ1bmJvb2s=",
            "content_type": "application/pdf",
            "size": 17,
        }
    ]


def test_strict_attachment_loading_rejects_filename_without_runbook_owner(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "automail.api.attachments._list_all",
        lambda _collection, filter_str="", **_kwargs: calls.append(filter_str) or [],
    )
    result = IntentResult(
        matched=True,
        intent_name="cancel-contract",
        concerns=[_concern("concern-cancel", "cancel-contract")],
    )
    response = AgentResponse(
        response_text="Attached.",
        activated_intent="cancel-contract",
        response_attachments=["unowned.pdf"],
    )

    with pytest.raises(HTTPException, match="unowned.pdf"):
        load_attachment_files(
            response,
            intents_dir=SimpleNamespace(project_id="project-1"),
            intent_result=result,
            strict_intent_ownership=True,
        )

    assert calls == []


def test_dict_shaped_nested_outcomes_remain_supported():
    result = {
        "intentName": "legacy-primary",
        "actions": [],
        "concerns": [
            {
                "concernId": "concern-secondary",
                "intentName": "secondary-runbook",
                "outcome": {"actions": [_action("secondary").model_dump(by_alias=True)]},
            }
        ],
    }

    assert actions_from_intent(result)[0]["runbook"] == "secondary-runbook"
    resolve_intent_action_payloads(result, {"customerId": "customer-7"})
    assert result["concerns"][0]["outcome"]["actions"][0]["payload"] == {
        "customerId": "customer-7",
    }
