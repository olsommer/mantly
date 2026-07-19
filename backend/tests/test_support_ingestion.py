import base64
from email.message import EmailMessage

from automail.models import Email
from automail.support import ingestion


def test_parse_imap_message_preserves_attachments():
    raw = EmailMessage()
    raw["Subject"] = "Invoice"
    raw["From"] = "Customer <customer@example.com>"
    raw["Message-ID"] = "<provider-msg-1@example.com>"
    raw.set_content("Please see the attached invoice.")
    raw.add_attachment(
        b"invoice bytes",
        maintype="application",
        subtype="pdf",
        filename="invoice.pdf",
    )

    message = ingestion._parse_imap_message("42", raw.as_bytes())

    assert message is not None
    assert message.id == "provider-msg-1@example.com"
    assert message.attachments == [{
        "filename": "invoice.pdf",
        "base64": base64.b64encode(b"invoice bytes").decode("ascii"),
        "contentType": "application/pdf",
    }]


def test_email_attachment_keeps_content_type_alias():
    email = Email(
        id="msg-1",
        subject="Invoice",
        fromAddress="customer@example.com",
        body="See attached.",
        attachments=[{
            "filename": "invoice.pdf",
            "base64": base64.b64encode(b"invoice bytes").decode("ascii"),
            "contentType": "application/pdf",
        }],
    )

    assert email.attachments[0].content_type == "application/pdf"


def test_sync_support_channel_processes_buffer_messages_once(monkeypatch):
    processed: list[tuple[str, str, str]] = []
    cursors: list[dict] = []
    cursor_keys: list[str] = []
    sync_runs: list[dict] = []

    monkeypatch.setattr(
        ingestion,
        "get_channel",
        lambda *_args, **_kwargs: {
            "id": "channel1",
            "channelKey": "email:support",
            "type": "email",
            "status": "active",
            "config": {
                "adapter": "buffer",
                "inboundMessages": [
                    {
                        "id": "old-msg",
                        "subject": "Already processed",
                        "fromAddress": "old@example.com",
                        "body": "Done.",
                    },
                    {
                        "id": "msg-1",
                        "threadId": "thread-1",
                        "messageId": "provider-msg-1",
                        "subject": "Need support",
                        "fromAddress": "customer@example.com",
                        "body": "Please help.",
                    },
                ],
            },
        },
    )
    def fake_get_cursor(*_args, **kwargs):
        cursor_keys.append(kwargs["cursor_key"])
        return {
            "id": "cursor1",
            "cursorValue": "old-msg",
            "metadata": {"processedIds": ["old-msg"]},
        }

    monkeypatch.setattr(ingestion, "get_channel_cursor", fake_get_cursor)

    def fake_process(body, **kwargs):
        processed.append((body.email.id, kwargs["project_id_override"], kwargs["source"]))
        assert body.email.thread_id == "thread-1"
        assert body.email.message_id == "provider-msg-1"
        return []

    monkeypatch.setattr(ingestion, "process_email_for_context", fake_process)
    monkeypatch.setattr(
        ingestion,
        "get_issue_by_chat_id",
        lambda chat_id, **_kwargs: {
            "id": f"issue:{chat_id}",
            "metadata": {
                "ticketCreationMode": "per_message",
                "sourceIssueId": chat_id,
                "sourceMessageId": chat_id,
                "resolver": {
                    "kind": "ticket_resolver",
                    "provider": "email",
                    "issueId": f"issue:{chat_id}",
                    "ticketCreationMode": "per_message",
                    "resolverAction": "created",
                    "sourceIssueId": chat_id,
                    "sourceMessageId": chat_id,
                },
            },
        },
    )
    monkeypatch.setattr(
        ingestion,
        "upsert_channel_cursor",
        lambda *_args, **kwargs: cursors.append(kwargs) or {"id": "cursor1", **kwargs},
    )
    monkeypatch.setattr(
        ingestion,
        "record_channel_sync_run",
        lambda **kwargs: sync_runs.append(kwargs) or {"id": "sync1", **kwargs},
    )

    result = ingestion.sync_support_channel(
        "channel1",
        tenant_id="tenant1",
        project_id="project1",
        actor_email="agent@example.com",
    )

    assert processed == [("channel:email:support:msg-1", "project1", "channel:email:support")]
    assert result["processed"] == 1
    assert result["failed"] == 0
    assert result["skipped"] == 1
    assert result["cursorKey"] == "inbound:buffer"
    assert result["items"][0]["issueId"] == "issue:channel:email:support:msg-1"
    assert result["items"][0]["ticketCreationMode"] == "per_message"
    assert result["items"][0]["resolver"]["provider"] == "email"
    assert result["items"][0]["resolver"]["resolverAction"] == "created"
    assert cursor_keys == ["inbound:buffer"]
    assert cursors[0]["cursor_key"] == "inbound:buffer"
    assert cursors[0]["cursor_value"] == "msg-1"
    assert cursors[0]["status"] == "success"
    assert cursors[0]["metadata"]["cursorKey"] == "inbound:buffer"
    assert cursors[0]["metadata"]["processedIds"] == ["msg-1", "old-msg"]
    assert sync_runs[0]["source"] == "admin"
    assert sync_runs[0]["result"]["status"] == "success"
    assert sync_runs[0]["result"]["items"][0]["resolver"]["sourceIssueId"] == "channel:email:support:msg-1"


def test_ingest_email_webhook_processes_message_and_records_sync_run(monkeypatch):
    processed: list[tuple[str, str, str, str]] = []
    sync_runs: list[dict] = []

    monkeypatch.setattr(
        ingestion,
        "get_channel_by_key",
        lambda *_args, **_kwargs: {
            "id": "channel1",
            "channelKey": "email:support",
            "type": "email",
            "status": "active",
            "config": {"ticketCreationMode": "per_message"},
        },
    )

    def fake_process(body, **kwargs):
        processed.append((body.email.id, body.email.message_id, kwargs["source"], kwargs["creator_override"]))
        assert body.email.subject == "Need help"
        assert body.email.from_address == "customer@example.com"
        assert body.email.body_html == "<p>Please help.</p>"
        return []

    monkeypatch.setattr(ingestion, "process_email_for_context", fake_process)
    def fake_get_issue(chat_id, **_kwargs):
        return {
            "id": f"issue:{chat_id}",
            "metadata": {
                "ticketCreationMode": "per_message",
                "sourceIssueId": chat_id,
                "sourceMessageId": chat_id,
                "resolver": {
                    "kind": "ticket_resolver",
                    "provider": "email",
                    "issueId": f"issue:{chat_id}",
                    "ticketCreationMode": "per_message",
                    "resolverAction": "created",
                    "sourceIssueId": chat_id,
                    "sourceMessageId": chat_id,
                },
            },
        }

    monkeypatch.setattr(ingestion, "get_issue_by_chat_id", fake_get_issue)
    monkeypatch.setattr(
        ingestion,
        "record_channel_sync_run",
        lambda **kwargs: sync_runs.append(kwargs) or {"id": "sync1", **kwargs},
    )

    result = ingestion.ingest_email_webhook(
        "email:support",
        tenant_id="tenant1",
        project_id="project1",
        actor_email="ingress@example.com",
        payload={
            "email": {
                "MessageID": "provider-msg-1",
                "Subject": "Need help",
                "From": "customer@example.com",
                "TextBody": "Please help.",
                "HtmlBody": "<p>Please help.</p>",
                "attachments": [{
                    "filename": "context.txt",
                    "base64": base64.b64encode(b"context").decode("ascii"),
                    "contentType": "text/plain",
                }],
            },
        },
    )

    assert processed == [(
        "channel:email:support:provider-msg-1",
        "provider-msg-1",
        "channel:email:support",
        "ingress@example.com",
    )]
    assert result["adapter"] == "email_webhook"
    assert result["processed"] == 1
    assert result["failed"] == 0
    assert result["items"][0]["issueId"] == "issue:channel:email:support:provider-msg-1"
    assert result["items"][0]["ticketCreationMode"] == "per_message"
    assert result["items"][0]["resolver"]["provider"] == "email"
    assert result["items"][0]["resolver"]["resolverAction"] == "created"
    assert sync_runs[0]["channel_id"] == "channel1"
    assert sync_runs[0]["source"] == "email-webhook"
    assert sync_runs[0]["result"]["status"] == "success"
    assert sync_runs[0]["result"]["items"][0]["resolver"]["sourceMessageId"] == (
        "channel:email:support:provider-msg-1"
    )


def test_ingest_email_webhook_reports_replay_as_skipped(monkeypatch):
    sync_runs: list[dict] = []
    issue = {
        "id": "issue-existing",
        "metadata": {
            "ticketCreationMode": "per_thread",
            "sourceIssueId": "channel:email:support:provider-msg-1",
            "sourceMessageId": "provider-msg-1",
            "resolver": {
                "provider": "email",
                "resolverAction": "updated",
            },
        },
    }
    monkeypatch.setattr(
        ingestion,
        "get_channel_by_key",
        lambda *_args, **_kwargs: {
            "id": "channel1",
            "channelKey": "email:support",
            "type": "email",
            "status": "active",
        },
    )
    monkeypatch.setattr(ingestion, "get_issue_by_chat_id", lambda *_args, **_kwargs: issue)
    def fake_cached_process(*_args, **kwargs):
        kwargs["processing_metadata"]["cached"] = True
        return []

    monkeypatch.setattr(ingestion, "process_email_for_context", fake_cached_process)
    monkeypatch.setattr(
        ingestion,
        "record_channel_sync_run",
        lambda **kwargs: sync_runs.append(kwargs),
    )

    result = ingestion.ingest_email_webhook(
        "email:support",
        tenant_id="tenant1",
        project_id="project1",
        payload={
            "email": {
                "messageId": "provider-msg-1",
                "threadId": "thread-1",
                "subject": "Need help",
                "fromAddress": "customer@example.com",
                "body": "Please help.",
            },
        },
    )

    assert result["status"] == "skipped"
    assert result["processed"] == 0
    assert result["failed"] == 0
    assert result["skipped"] == 1
    assert result["items"][0]["issueId"] == "issue-existing"
    assert result["items"][0]["messageId"] == "provider-msg-1"
    assert sync_runs[0]["result"] == result


def test_sync_support_channel_migrates_legacy_inbound_cursor(monkeypatch):
    processed: list[str] = []
    cursor_keys: list[str] = []
    cursors: list[dict] = []

    monkeypatch.setattr(
        ingestion,
        "get_channel",
        lambda *_args, **_kwargs: {
            "id": "channel1",
            "channelKey": "email:support",
            "type": "email",
            "status": "active",
            "config": {
                "adapter": "buffer",
                "inboundMessages": [
                    {
                        "id": "old-msg",
                        "subject": "Already processed",
                        "fromAddress": "old@example.com",
                        "body": "Done.",
                    },
                    {
                        "id": "msg-2",
                        "subject": "Need support",
                        "fromAddress": "customer@example.com",
                        "body": "Please help.",
                    },
                ],
            },
        },
    )

    def fake_get_cursor(*_args, **kwargs):
        cursor_keys.append(kwargs["cursor_key"])
        if kwargs["cursor_key"] == "inbound":
            return {
                "id": "legacy-cursor",
                "cursorValue": "old-msg",
                "metadata": {"processedIds": ["old-msg"]},
            }
        return None

    monkeypatch.setattr(ingestion, "get_channel_cursor", fake_get_cursor)
    monkeypatch.setattr(ingestion, "process_email_for_context", lambda body, **_kwargs: processed.append(body.email.id) or [])
    monkeypatch.setattr(ingestion, "get_issue_by_chat_id", lambda *_args, **_kwargs: {"id": "issue1"})
    monkeypatch.setattr(
        ingestion,
        "upsert_channel_cursor",
        lambda *_args, **kwargs: cursors.append(kwargs) or {"id": "cursor1", **kwargs},
    )
    monkeypatch.setattr(ingestion, "record_channel_sync_run", lambda **kwargs: {"id": "sync1", **kwargs})

    result = ingestion.sync_support_channel(
        "channel1",
        tenant_id="tenant1",
        project_id="project1",
        actor_email="agent@example.com",
    )

    assert cursor_keys == ["inbound:buffer", "inbound"]
    assert processed == ["channel:email:support:msg-2"]
    assert result["cursorKey"] == "inbound:buffer"
    assert result["processed"] == 1
    assert result["skipped"] == 1
    assert cursors[0]["cursor_key"] == "inbound:buffer"
    assert cursors[0]["metadata"]["migratedFromCursorKey"] == "inbound"
    assert cursors[0]["metadata"]["processedIds"] == ["msg-2", "old-msg"]


def test_sync_support_channel_records_imap_config_error(monkeypatch):
    cursors: list[dict] = []
    monkeypatch.setattr(
        ingestion,
        "get_channel",
        lambda *_args, **_kwargs: {
            "id": "channel1",
            "channelKey": "email:support",
            "type": "email",
            "status": "active",
            "config": {"adapter": "imap", "host": "imap.example.com"},
        },
    )
    monkeypatch.setattr(ingestion, "get_channel_cursor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ingestion,
        "upsert_channel_cursor",
        lambda *_args, **kwargs: cursors.append(kwargs) or {"id": "cursor1", **kwargs},
    )

    result = ingestion.sync_support_channel(
        "channel1",
        tenant_id="tenant1",
        project_id="project1",
        actor_email="agent@example.com",
    )

    assert result["status"] == "failed"
    assert result["cursorKey"] == "inbound:imap:imap.example.com:account:inbox"
    assert "IMAP host, username, and password" in result["error"]
    assert cursors[0]["cursor_key"] == "inbound:imap:imap.example.com:account:inbox"
    assert cursors[0]["status"] == "failed"
    assert cursors[0]["last_error"] == result["error"]


def test_sync_support_channels_runs_configured_channel_sources(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        ingestion,
        "list_channels",
        lambda **_kwargs: [
            {"id": "channel1", "type": "email"},
            {"id": "channel2", "type": "slack", "config": {"adapter": "buffer", "inboundMessages": []}},
            {"id": "channel3", "type": "discord", "config": {"syncEnabled": True}},
            {"id": "channel4", "type": "telegram", "config": {"adapter": "webhook"}},
            {"id": "channel5", "type": "slack", "config": {"syncEnabled": False, "adapter": "buffer"}},
        ],
    )

    def fake_sync(channel_id: str, **_kwargs):
        calls.append(channel_id)
        return {"processed": 2, "failed": 1, "skipped": 0}

    monkeypatch.setattr(ingestion, "sync_support_channel", fake_sync)

    result = ingestion.sync_support_channels(
        tenant_id="tenant1",
        project_id="project1",
        actor_email="agent@example.com",
    )

    assert calls == ["channel1", "channel2", "channel3"]
    assert result["channels"] == 3
    assert result["processed"] == 6
    assert result["failed"] == 3


def test_sync_support_channels_for_scope_uses_channel_project(monkeypatch):
    calls: list[tuple[str, str | None, str]] = []
    monkeypatch.setattr(
        ingestion,
        "list_syncable_channels",
        lambda **_kwargs: [
            {"id": "channel1", "tenantId": "tenant1", "projectId": "project1", "type": "email"},
            {
                "id": "channel2",
                "tenantId": "tenant1",
                "projectId": "project1",
                "type": "slack",
                "config": {"adapter": "buffer", "messages": []},
            },
            {"id": "channel3", "tenantId": "tenant1", "projectId": "project1", "type": "discord", "config": {}},
            {"id": "channel4", "tenantId": "", "projectId": "", "type": "email"},
        ],
    )

    def fake_sync(channel_id: str, **kwargs):
        calls.append((channel_id, kwargs.get("tenant_id"), kwargs["project_id"]))
        return {"processed": 1, "failed": 0, "skipped": 0}

    monkeypatch.setattr(ingestion, "sync_support_channel", fake_sync)

    result = ingestion.sync_support_channels_for_scope(limit=5, source="scheduler")

    assert calls == [("channel1", "tenant1", "project1"), ("channel2", "tenant1", "project1")]
    assert result["channels"] == 2
    assert result["processed"] == 2
