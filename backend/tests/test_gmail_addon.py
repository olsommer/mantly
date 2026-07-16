import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest

from automail.addon.gmail.adapter import gmail_message_to_email
from automail.addon.gmail.auth import GmailAddonIdentity
from automail.addon.gmail.cards import build_result_card
from automail.addon.gmail.events import GMAIL_CURRENT_ACTION_COMPOSE_SCOPE
from automail.models import Email, EmailResponse, IdentityResult, IntentAction, IntentResult, Message

FIXTURES = Path(__file__).parent / "fixtures" / "gmail_addon"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def gmail_id_token(email: str, *, verified: bool = True) -> str:
    return jwt.encode(
        {"email": email, "email_verified": verified},
        "test-secret-with-at-least-thirty-two-bytes",
        algorithm="HS256",
    )


@pytest.mark.no_gemini
def test_gmail_adapter_parses_plain_text_message():
    message = {
        "id": "msg-123",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Gmail subject"},
                {"name": "From", "value": "Client <client@example.com>"},
                {"name": "Message-ID", "value": "<internet-msg-123@example.com>"},
                {"name": "In-Reply-To", "value": "<internet-parent@example.com>"},
                {"name": "References", "value": "<root@example.com> <internet-parent@example.com>"},
            ],
            "mimeType": "text/plain",
            "body": {"data": "SGVsbG8gZnJvbSBHbWFpbA"},
        },
        "threadId": "thread-123",
    }

    email = gmail_message_to_email(message)

    assert email.id == "gmail:msg-123"
    assert email.thread_id == "gmail:thread-123"
    assert email.message_id == "gmail:msg-123"
    assert email.internet_message_id == "internet-msg-123@example.com"
    assert email.in_reply_to == "internet-parent@example.com"
    assert email.references == ["root@example.com", "internet-parent@example.com"]
    assert email.subject == "Gmail subject"
    assert email.from_address == "client@example.com"
    assert email.body == "Hello from Gmail"


@pytest.mark.no_gemini
def test_gmail_homepage_returns_card(client):
    response = client.post("/addons/gmail/homepage", json=load_fixture("homepage.json"))

    assert response.status_code == 200
    data = response.json()
    card = data["action"]["navigations"][0]["pushCard"]
    assert card["header"]["title"] == "Mantly"


@pytest.mark.no_gemini
def test_gmail_message_route_fetches_current_email(client, monkeypatch):
    monkeypatch.setattr(
        "automail.addon.gmail.router.fetch_current_email",
        lambda event: Email(
            id="gmail:msg-123",
            subject="Subject",
            from_address="client@example.com",
            body="Hello",
            attachments=[],
        ),
    )

    response = client.post("/addons/gmail/message", json=load_fixture("message_open.json"))

    assert response.status_code == 200
    card = response.json()["action"]["navigations"][0]["pushCard"]
    widgets = card["sections"][0]["widgets"]
    assert widgets[0]["decoratedText"]["text"] == "Subject"
    assert widgets[-1]["buttonList"]["buttons"][0]["onClick"]["action"]["function"].endswith(
        "/addons/gmail/action"
    )


@pytest.mark.no_gemini
def test_gmail_analyze_action_reuses_shared_process_core(client, monkeypatch):
    seen = {}
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {"action": "analyze"}

    email = Email(
        id="gmail:msg-123",
        subject="Subject",
        from_address="client@example.com",
        body="Hello",
        attachments=[],
    )
    monkeypatch.setattr("automail.addon.gmail.router.fetch_current_email", lambda addon_event: email)
    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_issue_by_chat_id",
        lambda *_args, **_kwargs: {
            "id": "issue-123",
            "status": "open",
            "workflowStatus": "open",
            "priority": "high",
            "assigneeEmail": "agent@example.com",
            "pendingApprovalCount": 1,
        },
    )
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_issue",
        lambda *_args, **_kwargs: {
            "id": "issue-123",
            "status": "open",
            "workflowStatus": "open",
            "priority": "high",
            "assigneeEmail": "agent@example.com",
            "pendingApprovalCount": 1,
        },
    )

    def fake_process(body, *, tenant_id, payload, source, project_id_override):
        seen["creator"] = body.creator
        seen["tenant_id"] = tenant_id
        seen["source"] = source
        seen["project_id"] = project_id_override
        return [
            Message(role="email", user="email", content="original"),
            Message(
                role="response",
                user="response",
                content=EmailResponse(
                    email_body="Generated reply",
                    email_attachments=[
                        {"filename": "Versicherungsbestaetigung_Keller.pdf"}
                    ],
                    identity_result=IdentityResult(
                        customer_found=True,
                        data={
                            "customerName": "Anna Keller",
                            "policy": "Betriebshaftpflicht",
                            "policyNumber": "BH-2048-77",
                            "status": "Aktiv",
                        },
                    ),
                    intent_result=IntentResult(
                        matched=True,
                        intent_name="Versicherungsbestätigung",
                        actions=[
                            IntentAction(
                                name="category",
                                label="Category",
                                type="dropdown",
                                options=["A", "B"],
                                webhook="https://example.com/category",
                            ),
                            IntentAction(
                                name="dueDate",
                                label="Due Date",
                                type="calendar",
                                initial_value="2026-05-22",
                                webhook="https://example.com/date",
                            ),
                            IntentAction(
                                name="note",
                                label="Note",
                                type="input",
                                initial_value="Check details",
                                webhook="https://example.com/note",
                            ),
                            IntentAction(
                                name="send",
                                label="Send",
                                type="button",
                                webhook="https://example.com/send",
                            ),
                        ],
                    ),
                ),
            ),
        ]

    monkeypatch.setattr("automail.addon.gmail.router.process_email_for_context", fake_process)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert seen == {
        "creator": "user@example.com",
        "tenant_id": "tenant-a",
        "source": "gmail",
        "project_id": "project-a",
    }
    card = response.json()["action"]["navigations"][0]["updateCard"]
    assert "header" not in card
    section_by_header = {section["header"]: section for section in card["sections"]}
    assert set(section_by_header) == {"Customer", "Intent", "Actions", "Response", "Issue"}

    customer_widgets = section_by_header["Customer"]["widgets"]
    assert customer_widgets[0]["decoratedText"]["startIcon"]["knownIcon"] == "PERSON"
    assert customer_widgets[0]["decoratedText"]["text"] == '<font color="#188038"><b>Customer found</b></font>'
    assert customer_widgets[1]["decoratedText"]["topLabel"] == "Customer"
    assert customer_widgets[1]["decoratedText"]["text"] == "Anna Keller"
    assert customer_widgets[1]["decoratedText"]["startIcon"]["knownIcon"] == "DESCRIPTION"
    assert customer_widgets[3]["decoratedText"]["topLabel"] == "Policy Number"
    assert customer_widgets[3]["decoratedText"]["text"] == "BH-2048-77"

    intent_widgets = section_by_header["Intent"]["widgets"]
    assert "Versicherungsbestätigung" in intent_widgets[0]["decoratedText"]["text"]
    assert "topLabel" not in intent_widgets[0]["decoratedText"]
    assert intent_widgets[0]["decoratedText"]["startIcon"]["knownIcon"] == "BOOKMARK"

    actions_widgets = section_by_header["Actions"]["widgets"]
    assert any("selectionInput" in widget for widget in actions_widgets)
    assert any("dateTimePicker" in widget for widget in actions_widgets)
    assert any("textInput" in widget for widget in actions_widgets)
    action_buttons = [
        button
        for widget in actions_widgets
        if "buttonList" in widget
        for button in widget["buttonList"]["buttons"]
    ]
    assert {button["text"] for button in action_buttons} == {"Category", "Due Date", "Note", "Send"}
    assert all(
        button["onClick"]["action"]["function"].endswith("/addons/gmail/action")
        for button in action_buttons
    )

    response_widgets = section_by_header["Response"]["widgets"]
    assert response_widgets[0]["decoratedText"]["topLabel"] == "Attachments (1)"
    assert response_widgets[0]["decoratedText"]["text"] == "Versicherungsbestaetigung_Keller.pdf"
    assert response_widgets[-1]["decoratedText"]["topLabel"] == "Draft"
    assert response_widgets[-1]["decoratedText"]["text"] == "Generated reply"
    assert response_widgets[-1]["decoratedText"]["startIcon"]["knownIcon"] == "EMAIL"

    issue_widgets = section_by_header["Issue"]["widgets"]
    assert issue_widgets[0]["decoratedText"]["topLabel"] == "Status"
    assert issue_widgets[0]["decoratedText"]["text"] == "Open"
    assert issue_widgets[1]["decoratedText"]["topLabel"] == "Priority"
    assert issue_widgets[1]["decoratedText"]["text"] == "High"
    assert issue_widgets[2]["decoratedText"]["topLabel"] == "Assignee"
    assert issue_widgets[2]["decoratedText"]["text"] == "agent@example.com"
    assert issue_widgets[3]["decoratedText"]["topLabel"] == "Next action"
    assert issue_widgets[3]["decoratedText"]["text"] == "Review approval"
    assert issue_widgets[4]["decoratedText"]["text"] == "1 approval pending"
    issue_buttons = [
        button
        for widget in issue_widgets
        if "buttonList" in widget
        for button in widget["buttonList"]["buttons"]
    ]
    assert {button["text"] for button in issue_buttons} == {"Request changes", "Approve", "Approve & send", "Open issue"}
    note_inputs = [
        widget["textInput"]
        for widget in issue_widgets
        if "textInput" in widget
    ]
    assert note_inputs == [{"name": "replyChangeNote", "label": "Change request note", "type": "SINGLE_LINE", "value": ""}]
    changes = next(button for button in issue_buttons if button["text"] == "Request changes")
    assert changes["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "requestIssueReplyChanges"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
    ]
    approve = next(button for button in issue_buttons if button["text"] == "Approve")
    assert approve["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "approveIssueReply"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
    ]
    approve_send = next(button for button in issue_buttons if button["text"] == "Approve & send")
    assert approve_send["color"]
    assert approve_send["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "approveSendIssueReply"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
    ]
    issue_button = next(button for button in issue_buttons if button["text"] == "Open issue")
    assert issue_button["onClick"]["openLink"]["url"] == "https://app.mantly.io/tenant-a/project-a/inbox/issue-123"

    footer_button = card["fixedFooter"]["primaryButton"]
    assert footer_button["text"] == "Apply Response"
    assert footer_button["color"]
    assert footer_button["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "applyResponse"},
        {"key": "chatId", "value": "gmail:msg-123"},
    ]


@pytest.mark.no_gemini
def test_gmail_result_card_surfaces_failed_delivery_retry():
    card = build_result_card(
        [
            Message(role="email", user="email", content="original"),
            Message(
                role="response",
                user="response",
                content=EmailResponse(email_body="Generated reply", email_attachments=[]),
            ),
        ],
        chat_id="gmail:msg-123",
        action_url="https://api.mantly.io/addons/gmail/action",
        issue={
            "id": "issue-123",
            "status": "ongoing",
            "workflowStatus": "ongoing",
            "priority": "high",
            "assigneeEmail": "agent@example.com",
            "pendingDeliveryCount": 1,
            "failedDeliveryCount": 2,
        },
        issue_url="https://app.mantly.io/tenant-a/project-a/inbox/issue-123",
    )

    issue_widgets = {widget["decoratedText"]["topLabel"]: widget["decoratedText"] for widget in card["sections"][-1]["widgets"] if "decoratedText" in widget}
    assert issue_widgets["Delivery"]["text"] == "2 deliveries failed"
    buttons = [
        button
        for widget in card["sections"][-1]["widgets"]
        if "buttonList" in widget
        for button in widget["buttonList"]["buttons"]
    ]
    retry_button = next(button for button in buttons if button["text"] == "Retry delivery")
    assert retry_button["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "retryFailedDelivery"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
    ]
    assert buttons[-1]["text"] == "Open issue"


@pytest.mark.no_gemini
def test_gmail_result_card_surfaces_pending_approval_actions():
    card = build_result_card(
        [
            Message(role="email", user="email", content="original"),
            Message(
                role="response",
                user="response",
                content=EmailResponse(email_body="Generated reply", email_attachments=[]),
            ),
        ],
        chat_id="gmail:msg-123",
        action_url="https://api.mantly.io/addons/gmail/action",
        issue={
            "id": "issue-123",
            "status": "ongoing",
            "workflowStatus": "ongoing",
            "priority": "high",
            "assigneeEmail": "agent@example.com",
            "pendingApprovalCount": 2,
        },
        issue_url="https://app.mantly.io/tenant-a/project-a/inbox/issue-123",
    )

    buttons = [
        button
        for widget in card["sections"][-1]["widgets"]
        if "buttonList" in widget
        for button in widget["buttonList"]["buttons"]
    ]
    approve = next(button for button in buttons if button["text"] == "Approve")
    assert approve["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "approveIssueReply"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
    ]
    request_changes = next(button for button in buttons if button["text"] == "Request changes")
    assert request_changes["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "requestIssueReplyChanges"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
    ]
    approve_send = next(button for button in buttons if button["text"] == "Approve & send")
    assert approve_send["color"]
    assert approve_send["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "approveSendIssueReply"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
    ]


@pytest.mark.no_gemini
def test_gmail_result_card_surfaces_queue_approval_action_for_current_reply():
    card = build_result_card(
        [
            Message(role="email", user="email", content="original"),
            Message(
                role="response",
                user="response",
                content=EmailResponse(email_body="Generated reply", email_attachments=[]),
            ),
        ],
        chat_id="gmail:msg-123",
        action_url="https://api.mantly.io/addons/gmail/action",
        issue={
            "id": "issue-123",
            "status": "ongoing",
            "workflowStatus": "ongoing",
            "priority": "normal",
            "assigneeEmail": "agent@example.com",
            "pendingApprovalCount": 0,
        },
        issue_url="https://app.mantly.io/tenant-a/project-a/inbox/issue-123",
    )

    buttons = [
        button
        for widget in card["sections"][-1]["widgets"]
        if "buttonList" in widget
        for button in widget["buttonList"]["buttons"]
    ]
    queue = next(button for button in buttons if button["text"] == "Queue approval")
    assert queue["color"]
    assert queue["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "queueIssueReply"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
    ]


@pytest.mark.no_gemini
def test_gmail_result_card_suppresses_queue_action_when_approval_flag_is_set():
    card = build_result_card(
        [
            Message(role="email", user="email", content="original"),
            Message(
                role="response",
                user="response",
                content=EmailResponse(email_body="Generated reply", email_attachments=[]),
            ),
        ],
        chat_id="gmail:msg-123",
        action_url="https://api.mantly.io/addons/gmail/action",
        issue={
            "id": "issue-123",
            "status": "ongoing",
            "workflowStatus": "ongoing",
            "priority": "normal",
            "assigneeEmail": "agent@example.com",
            "pendingApprovalCount": 0,
            "hasPendingApproval": True,
        },
        issue_url="https://app.mantly.io/tenant-a/project-a/inbox/issue-123",
    )

    buttons = [
        button
        for widget in card["sections"][-1]["widgets"]
        if "buttonList" in widget
        for button in widget["buttonList"]["buttons"]
    ]
    assert "Queue approval" not in {button["text"] for button in buttons}
    assert "Approve" in {button["text"] for button in buttons}


@pytest.mark.no_gemini
def test_gmail_result_card_surfaces_pending_action_approval_controls():
    card = build_result_card(
        [
            Message(role="email", user="email", content="original"),
            Message(
                role="response",
                user="response",
                content=EmailResponse(email_body="Generated reply", email_attachments=[]),
            ),
        ],
        chat_id="gmail:msg-123",
        action_url="https://api.mantly.io/addons/gmail/action",
        issue={
            "id": "issue-123",
            "status": "ongoing",
            "workflowStatus": "ongoing",
            "priority": "normal",
            "assigneeEmail": "agent@example.com",
            "pendingApprovalCount": 1,
            "pendingReplyApprovalCount": 0,
            "pendingActionApprovalCount": 1,
            "actionExecutions": [
                {
                    "id": "action-1",
                    "actionKey": "set_priority",
                    "label": "Escalate priority",
                    "status": "pending",
                    "metadata": {"approvalRequired": True, "reviewStatus": "pending"},
                    "result": {"proposedAction": {"type": "set_priority", "priority": "high"}},
                }
            ],
        },
        issue_url="https://app.mantly.io/tenant-a/project-a/inbox/issue-123",
    )

    issue_widgets = [
        widget["decoratedText"]["text"]
        for widget in card["sections"][-1]["widgets"]
        if "decoratedText" in widget
    ]
    assert "Review action" in issue_widgets
    assert "1 action proposal" in issue_widgets
    assert "Escalate priority" in issue_widgets
    buttons = [
        button
        for widget in card["sections"][-1]["widgets"]
        if "buttonList" in widget
        for button in widget["buttonList"]["buttons"]
    ]
    assert "Approve" not in {button["text"] for button in buttons}
    approve = next(button for button in buttons if button["text"] == "Approve action")
    assert approve["color"]
    assert approve["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "approveIssueAction"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
        {"key": "actionId", "value": "action-1"},
    ]
    reject = next(button for button in buttons if button["text"] == "Reject action")
    assert reject["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "rejectIssueAction"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
        {"key": "actionId", "value": "action-1"},
    ]


@pytest.mark.no_gemini
def test_gmail_result_card_surfaces_ready_to_close_action():
    card = build_result_card(
        [
            Message(role="email", user="email", content="original"),
            Message(
                role="response",
                user="response",
                content=EmailResponse(email_body="Generated reply", email_attachments=[]),
            ),
        ],
        chat_id="gmail:msg-123",
        action_url="https://api.mantly.io/addons/gmail/action",
        issue={
            "id": "issue-123",
            "status": "ongoing",
            "workflowStatus": "ongoing",
            "priority": "normal",
            "assigneeEmail": "agent@example.com",
            "needsResponse": False,
            "pendingApprovalCount": 0,
            "pendingDeliveryCount": 0,
            "failedDeliveryCount": 0,
        },
        issue_url="https://app.mantly.io/tenant-a/project-a/inbox/issue-123",
    )

    issue_widgets = [
        widget
        for widget in card["sections"][-1]["widgets"]
        if "decoratedText" in widget
    ]
    assert issue_widgets[3]["decoratedText"]["topLabel"] == "Next action"
    assert issue_widgets[3]["decoratedText"]["text"] == "Ready to close"
    buttons = [
        button
        for widget in card["sections"][-1]["widgets"]
        if "buttonList" in widget
        for button in widget["buttonList"]["buttons"]
    ]
    mark_done = next(button for button in buttons if button["text"] == "Mark done")
    assert mark_done["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "markIssueDone"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
    ]


@pytest.mark.no_gemini
def test_gmail_result_card_surfaces_assign_to_me_action():
    card = build_result_card(
        [
            Message(role="email", user="email", content="original"),
            Message(
                role="response",
                user="response",
                content=EmailResponse(email_body="Generated reply", email_attachments=[]),
            ),
        ],
        chat_id="gmail:msg-123",
        action_url="https://api.mantly.io/addons/gmail/action",
        issue={
            "id": "issue-123",
            "status": "open",
            "workflowStatus": "open",
            "priority": "normal",
            "assigneeEmail": "",
        },
        issue_url="https://app.mantly.io/tenant-a/project-a/inbox/issue-123",
    )

    issue_widgets = [
        widget
        for widget in card["sections"][-1]["widgets"]
        if "decoratedText" in widget
    ]
    assert issue_widgets[2]["decoratedText"]["text"] == "Unassigned"
    assert issue_widgets[3]["decoratedText"]["text"] == "Assign owner"
    buttons = [
        button
        for widget in card["sections"][-1]["widgets"]
        if "buttonList" in widget
        for button in widget["buttonList"]["buttons"]
    ]
    assign = next(button for button in buttons if button["text"] == "Assign to me")
    assert assign["onClick"]["action"]["parameters"] == [
        {"key": "action", "value": "claimIssue"},
        {"key": "chatId", "value": "gmail:msg-123"},
        {"key": "issueId", "value": "issue-123"},
    ]


@pytest.mark.no_gemini
def test_gmail_analyze_action_creates_missing_issue_from_chat(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {"action": "analyze"}
    upsert_calls: list[dict] = []

    email = Email(
        id="gmail:msg-123",
        subject="Subject",
        from_address="client@example.com",
        body="Hello",
        attachments=[],
    )
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(
            email_body="Generated reply",
            email_attachments=[],
        ),
    )
    chat = {
        "id": "gmail:msg-123",
        "email_id": "gmail:msg-123",
        "messages": [response_message.model_dump()],
        "metadata": {"source": "gmail", "threadId": "thread-123"},
    }

    monkeypatch.setattr("automail.addon.gmail.router.fetch_current_email", lambda addon_event: email)
    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue_by_chat_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("automail.addon.gmail.router.get_chat", lambda *_args, **_kwargs: chat)

    def fake_upsert_issue_from_chat(next_chat, **kwargs):
        upsert_calls.append({"chat": next_chat, **kwargs})
        return {
            "id": "issue-created",
            "status": "open",
            "workflowStatus": "open",
            "priority": "normal",
            "assigneeEmail": "",
            "pendingApprovalCount": 0,
        }

    monkeypatch.setattr("automail.addon.gmail.router.upsert_issue_from_chat", fake_upsert_issue_from_chat)
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_issue",
        lambda *_args, **_kwargs: {
            "id": "issue-created",
            "status": "open",
            "workflowStatus": "open",
            "priority": "normal",
            "assigneeEmail": "",
            "pendingApprovalCount": 0,
        },
    )
    monkeypatch.setattr(
        "automail.addon.gmail.router.process_email_for_context",
        lambda *_args, **_kwargs: [Message(role="email", user="email", content="original"), response_message],
    )

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert upsert_calls == [{
        "chat": chat,
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "source": "gmail",
    }]
    card = response.json()["action"]["navigations"][0]["updateCard"]
    section_by_header = {section["header"]: section for section in card["sections"]}
    issue_button = section_by_header["Issue"]["widgets"][-1]["buttonList"]["buttons"][0]
    assert issue_button["text"] == "Open issue"
    assert issue_button["onClick"]["openLink"]["url"] == "https://app.mantly.io/tenant-a/project-a/inbox/issue-created"


@pytest.mark.no_gemini
def test_gmail_retry_failed_delivery_action_refreshes_issue_card(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "retryFailedDelivery",
        "chatId": "gmail:msg-123",
        "issueId": "issue-123",
    }
    delivered: list[tuple[str, str, dict]] = []
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(email_body="Generated reply", email_attachments=[]),
    )
    failed_issue = {
        "id": "issue-123",
        "status": "ongoing",
        "workflowStatus": "ongoing",
        "priority": "high",
        "assigneeEmail": "agent@example.com",
        "failedDeliveryCount": 1,
        "pendingDeliveryCount": 0,
        "outboundMessages": [{"id": "reply-1", "status": "failed"}],
    }
    refreshed_issue = {
        **failed_issue,
        "failedDeliveryCount": 0,
        "pendingDeliveryCount": 1,
        "outboundMessages": [{"id": "reply-1", "status": "queued"}],
    }
    issues = iter([failed_issue, refreshed_issue])

    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue", lambda *_args, **_kwargs: next(issues))
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda *_args, **_kwargs: {"messages": [response_message.model_dump()]},
    )

    def fake_deliver(issue_id: str, reply_id: str, **kwargs):
        delivered.append((issue_id, reply_id, kwargs))
        return {"id": reply_id, "status": "queued"}

    monkeypatch.setattr("automail.addon.gmail.router.deliver_issue_reply", fake_deliver)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert delivered == [("issue-123", "reply-1", {"tenant_id": "tenant-a", "project_id": "project-a"})]
    card = response.json()["action"]["navigations"][0]["updateCard"]
    section_by_header = {section["header"]: section for section in card["sections"]}
    issue_text = [
        widget["decoratedText"]["text"]
        for widget in section_by_header["Issue"]["widgets"]
        if "decoratedText" in widget
    ]
    assert "1 delivery queued" in issue_text
    assert "1 delivery failed" not in issue_text


@pytest.mark.no_gemini
def test_gmail_approve_issue_reply_action_refreshes_issue_card(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "approveIssueReply",
        "chatId": "gmail:msg-123",
        "issueId": "issue-123",
    }
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(email_body="Generated reply", email_attachments=[]),
    )
    pending_issue = {
        "id": "issue-123",
        "status": "ongoing",
        "workflowStatus": "ongoing",
        "priority": "high",
        "assigneeEmail": "agent@example.com",
        "pendingApprovalCount": 1,
        "pendingDeliveryCount": 0,
        "outboundMessages": [
            {
                "id": "reply-1",
                "status": "draft",
                "metadata": {"approvalRequired": True, "approved": False, "reviewStatus": "pending"},
            }
        ],
    }
    refreshed_issue = {
        **pending_issue,
        "pendingApprovalCount": 0,
        "pendingDeliveryCount": 1,
        "outboundMessages": [
            {
                "id": "reply-1",
                "status": "queued",
                "metadata": {"approvalRequired": False, "approved": True, "reviewStatus": "approved"},
            }
        ],
    }
    issues = iter([pending_issue, refreshed_issue])
    approved: list[tuple[str, str, dict]] = []

    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue", lambda *_args, **_kwargs: next(issues))
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda *_args, **_kwargs: {"messages": [response_message.model_dump()]},
    )

    def fake_approve(issue_id: str, reply_id: str, **kwargs):
        approved.append((issue_id, reply_id, kwargs))
        return {"id": reply_id, "status": "queued", "metadata": {"approved": True}}

    monkeypatch.setattr("automail.addon.gmail.router.approve_issue_reply", fake_approve)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert approved == [("issue-123", "reply-1", {
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "approved_by": "user@example.com",
    })]
    card = response.json()["action"]["navigations"][0]["updateCard"]
    section_by_header = {section["header"]: section for section in card["sections"]}
    issue_text = [
        widget["decoratedText"]["text"]
        for widget in section_by_header["Issue"]["widgets"]
        if "decoratedText" in widget
    ]
    assert "1 delivery queued" in issue_text
    assert "1 approval pending" not in issue_text


@pytest.mark.no_gemini
def test_gmail_request_issue_reply_changes_action_refreshes_issue_card(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "requestIssueReplyChanges",
        "chatId": "gmail:msg-123",
        "issueId": "issue-123",
    }
    event["commonEventObject"]["formInputs"] = {
        "replyChangeNote": {"stringInputs": {"value": ["Make it shorter."]}},
    }
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(email_body="Generated reply", email_attachments=[]),
    )
    pending_issue = {
        "id": "issue-123",
        "status": "ongoing",
        "workflowStatus": "ongoing",
        "priority": "high",
        "assigneeEmail": "agent@example.com",
        "pendingApprovalCount": 1,
        "pendingReplyApprovalCount": 1,
        "outboundMessages": [
            {
                "id": "reply-1",
                "status": "queued",
                "metadata": {"approvalRequired": True, "approved": False, "reviewStatus": "pending"},
            }
        ],
    }
    refreshed_issue = {
        **pending_issue,
        "pendingApprovalCount": 0,
        "pendingReplyApprovalCount": 0,
        "outboundMessages": [
            {
                "id": "reply-1",
                "status": "draft",
                "metadata": {
                    "approvalRequired": True,
                    "approved": False,
                    "reviewStatus": "changes_requested",
                    "changesNote": "Make it shorter.",
                },
            }
        ],
    }
    issues = iter([pending_issue, refreshed_issue])
    requested: list[tuple[str, str, dict]] = []

    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue", lambda *_args, **_kwargs: next(issues))
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda *_args, **_kwargs: {"messages": [response_message.model_dump()]},
    )

    def fake_request(issue_id: str, reply_id: str, **kwargs):
        requested.append((issue_id, reply_id, kwargs))
        return {"id": reply_id, "status": "draft", "metadata": {"reviewStatus": "changes_requested"}}

    monkeypatch.setattr("automail.addon.gmail.router.request_issue_reply_changes", fake_request)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert requested == [("issue-123", "reply-1", {
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "requested_by": "user@example.com",
        "note": "Make it shorter.",
    })]
    card = response.json()["action"]["navigations"][0]["updateCard"]
    section_by_header = {section["header"]: section for section in card["sections"]}
    issue_text = [
        widget["decoratedText"]["text"]
        for widget in section_by_header["Issue"]["widgets"]
        if "decoratedText" in widget
    ]
    assert "1 approval pending" not in issue_text


@pytest.mark.no_gemini
def test_gmail_request_issue_reply_changes_action_uses_default_note(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "requestIssueReplyChanges",
        "chatId": "gmail:msg-123",
        "issueId": "issue-123",
    }
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(email_body="Generated reply", email_attachments=[]),
    )
    issue = {
        "id": "issue-123",
        "status": "ongoing",
        "workflowStatus": "ongoing",
        "priority": "high",
        "assigneeEmail": "agent@example.com",
        "pendingApprovalCount": 1,
        "pendingReplyApprovalCount": 1,
        "outboundMessages": [
            {
                "id": "reply-1",
                "status": "queued",
                "metadata": {"approvalRequired": True, "approved": False, "reviewStatus": "pending"},
            }
        ],
    }
    requested: list[dict] = []

    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda *_args, **_kwargs: {"messages": [response_message.model_dump()]},
    )

    def fake_request(issue_id: str, reply_id: str, **kwargs):
        requested.append({"issue_id": issue_id, "reply_id": reply_id, **kwargs})
        return {"id": reply_id, "status": "draft", "metadata": {"reviewStatus": "changes_requested"}}

    monkeypatch.setattr("automail.addon.gmail.router.request_issue_reply_changes", fake_request)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert requested[0]["note"] == "Requested from Gmail add-on"


@pytest.mark.no_gemini
def test_gmail_approve_send_issue_reply_action_delivers_and_refreshes_issue_card(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "approveSendIssueReply",
        "chatId": "gmail:msg-123",
        "issueId": "issue-123",
    }
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(email_body="Generated reply", email_attachments=[]),
    )
    pending_reply = {
        "id": "reply-1",
        "status": "draft",
        "metadata": {"approvalRequired": True, "approved": False, "reviewStatus": "pending"},
    }
    pending_issue = {
        "id": "issue-123",
        "status": "ongoing",
        "workflowStatus": "ongoing",
        "priority": "high",
        "assigneeEmail": "agent@example.com",
        "needsResponse": False,
        "pendingApprovalCount": 1,
        "pendingDeliveryCount": 0,
        "outboundMessages": [pending_reply],
    }
    refreshed_issue = {
        **pending_issue,
        "pendingApprovalCount": 0,
        "pendingDeliveryCount": 0,
        "outboundMessages": [
            {
                "id": "reply-1",
                "status": "sent",
                "metadata": {"approvalRequired": False, "approved": True, "reviewStatus": "approved"},
            }
        ],
    }
    issues = iter([pending_issue, refreshed_issue])
    approved: list[tuple[str, str, dict]] = []
    delivered: list[tuple[str, str, dict]] = []
    readiness_checks: list[tuple[dict, dict, dict]] = []

    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue", lambda *_args, **_kwargs: next(issues))
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda *_args, **_kwargs: {"messages": [response_message.model_dump()]},
    )

    def fake_readiness(issue: dict, reply: dict, **kwargs):
        readiness_checks.append((issue, reply, kwargs))
        return {"ready": True}

    def fake_approve(issue_id: str, reply_id: str, **kwargs):
        approved.append((issue_id, reply_id, kwargs))
        return {"id": reply_id, "status": "queued", "metadata": {"approved": True}}

    def fake_deliver(issue_id: str, reply_id: str, **kwargs):
        delivered.append((issue_id, reply_id, kwargs))
        return {"id": reply_id, "status": "sent"}

    monkeypatch.setattr("automail.addon.gmail.router.issue_reply_delivery_readiness", fake_readiness)
    monkeypatch.setattr("automail.addon.gmail.router.approve_issue_reply", fake_approve)
    monkeypatch.setattr("automail.addon.gmail.router.deliver_issue_reply", fake_deliver)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert readiness_checks == [(pending_issue, pending_reply, {"tenant_id": "tenant-a", "project_id": "project-a"})]
    assert approved == [("issue-123", "reply-1", {
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "approved_by": "user@example.com",
    })]
    assert delivered == [("issue-123", "reply-1", {
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "actor_email": "user@example.com",
    })]
    card = response.json()["action"]["navigations"][0]["updateCard"]
    section_by_header = {section["header"]: section for section in card["sections"]}
    issue_text = [
        widget["decoratedText"]["text"]
        for widget in section_by_header["Issue"]["widgets"]
        if "decoratedText" in widget
    ]
    assert "Ready to close" in issue_text
    assert "1 approval pending" not in issue_text


@pytest.mark.no_gemini
def test_gmail_queue_issue_reply_action_creates_approval_reply_and_refreshes_card(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "queueIssueReply",
        "chatId": "gmail:msg-123",
        "issueId": "issue-123",
    }
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(
            email_body="Generated reply",
            email_attachments=[
                {
                    "filename": "answer.pdf",
                    "base64": "cGRm",
                    "contentType": "application/pdf",
                }
            ],
        ),
    )
    issue = {
        "id": "issue-123",
        "status": "open",
        "workflowStatus": "open",
        "priority": "normal",
        "assigneeEmail": "",
        "pendingApprovalCount": 0,
        "outboundMessages": [],
    }
    refreshed_issue = {
        **issue,
        "status": "ongoing",
        "workflowStatus": "ongoing",
        "assigneeEmail": "user@example.com",
        "pendingApprovalCount": 1,
        "hasPendingApproval": True,
        "outboundMessages": [
            {
                "id": "reply-1",
                "status": "queued",
                "metadata": {"approvalRequired": True, "approved": False, "reviewStatus": "pending"},
            }
        ],
    }
    issues = iter([issue, refreshed_issue])
    created: list[dict] = []

    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue", lambda *_args, **_kwargs: next(issues))
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda *_args, **_kwargs: {"messages": [response_message.model_dump()]},
    )

    def fake_create(issue_id: str, **kwargs):
        created.append({"issue_id": issue_id, **kwargs})
        return {"id": "reply-1", "status": "queued", "metadata": kwargs["metadata"]}

    monkeypatch.setattr("automail.addon.gmail.router.create_issue_reply", fake_create)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert created == [{
        "issue_id": "issue-123",
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "author_email": "user@example.com",
        "body": "Generated reply",
        "status": "queued",
        "source": "gmail_addon",
        "metadata": {"approvalRequired": True, "approved": False, "reviewStatus": "pending"},
        "attachments": [{"filename": "answer.pdf", "base64": "cGRm", "contentType": "application/pdf"}],
    }]
    card = response.json()["action"]["navigations"][0]["updateCard"]
    section_by_header = {section["header"]: section for section in card["sections"]}
    issue_text = [
        widget["decoratedText"]["text"]
        for widget in section_by_header["Issue"]["widgets"]
        if "decoratedText" in widget
    ]
    buttons = [
        button["text"]
        for widget in section_by_header["Issue"]["widgets"]
        if "buttonList" in widget
        for button in widget["buttonList"]["buttons"]
    ]
    assert "Review approval" in issue_text
    assert "1 approval pending" in issue_text
    assert "Queue approval" not in buttons


@pytest.mark.no_gemini
def test_gmail_queue_issue_reply_action_skips_when_approval_is_pending(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "queueIssueReply",
        "chatId": "gmail:msg-123",
        "issueId": "issue-123",
    }
    issue = {
        "id": "issue-123",
        "status": "ongoing",
        "workflowStatus": "ongoing",
        "priority": "normal",
        "assigneeEmail": "agent@example.com",
        "pendingApprovalCount": 1,
        "outboundMessages": [
            {
                "id": "reply-1",
                "status": "queued",
                "metadata": {"approvalRequired": True, "approved": False, "reviewStatus": "pending"},
            }
        ],
    }

    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue", lambda *_args, **_kwargs: issue)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert response.json() == {"action": {"notification": {"text": "Approval already pending"}}}


@pytest.mark.no_gemini
def test_gmail_approve_issue_action_refreshes_issue_card(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "approveIssueAction",
        "chatId": "gmail:msg-123",
        "issueId": "issue-123",
        "actionId": "action-1",
    }
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(email_body="Generated reply", email_attachments=[]),
    )
    issue = {
        "id": "issue-123",
        "status": "ongoing",
        "workflowStatus": "ongoing",
        "priority": "normal",
        "assigneeEmail": "agent@example.com",
        "pendingApprovalCount": 1,
        "pendingReplyApprovalCount": 0,
        "pendingActionApprovalCount": 1,
        "actionExecutions": [
            {
                "id": "action-1",
                "actionKey": "set_priority",
                "label": "Escalate priority",
                "status": "pending",
                "metadata": {"approvalRequired": True, "reviewStatus": "pending"},
                "result": {"proposedAction": {"type": "set_priority", "priority": "high"}},
            }
        ],
    }
    refreshed_issue = {
        **issue,
        "priority": "high",
        "pendingApprovalCount": 0,
        "pendingActionApprovalCount": 0,
        "actionExecutions": [
            {
                **issue["actionExecutions"][0],
                "status": "success",
                "metadata": {"approvalRequired": True, "reviewStatus": "approved", "approved": True},
            }
        ],
    }
    approved: list[dict] = []

    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda *_args, **_kwargs: {"messages": [response_message.model_dump()]},
    )

    def fake_approve(issue_id: str, execution_id: str, **kwargs):
        approved.append({"issue_id": issue_id, "execution_id": execution_id, **kwargs})
        return {"execution": refreshed_issue["actionExecutions"][0], "issue": refreshed_issue}

    monkeypatch.setattr("automail.addon.gmail.router.approve_issue_action_execution", fake_approve)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert approved == [{
        "issue_id": "issue-123",
        "execution_id": "action-1",
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "approved_by": "user@example.com",
        "authorization_header": "",
    }]
    card = response.json()["action"]["navigations"][0]["updateCard"]
    section_by_header = {section["header"]: section for section in card["sections"]}
    issue_text = [
        widget["decoratedText"]["text"]
        for widget in section_by_header["Issue"]["widgets"]
        if "decoratedText" in widget
    ]
    assert "High" in issue_text
    assert "1 action proposal" not in issue_text


@pytest.mark.no_gemini
def test_gmail_reject_issue_action_refreshes_issue_card(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "rejectIssueAction",
        "chatId": "gmail:msg-123",
        "issueId": "issue-123",
        "actionId": "action-1",
    }
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(email_body="Generated reply", email_attachments=[]),
    )
    pending_action = {
        "id": "action-1",
        "actionKey": "set_status",
        "label": "Close ticket",
        "status": "pending",
        "metadata": {"approvalRequired": True, "reviewStatus": "pending"},
        "result": {"proposedAction": {"type": "set_status", "status": "done"}},
    }
    issue = {
        "id": "issue-123",
        "status": "ongoing",
        "workflowStatus": "ongoing",
        "priority": "normal",
        "assigneeEmail": "agent@example.com",
        "pendingApprovalCount": 1,
        "pendingReplyApprovalCount": 0,
        "pendingActionApprovalCount": 1,
        "actionExecutions": [pending_action],
    }
    refreshed_issue = {
        **issue,
        "pendingApprovalCount": 0,
        "pendingActionApprovalCount": 0,
        "actionExecutions": [
            {
                **pending_action,
                "status": "skipped",
                "metadata": {"approvalRequired": True, "reviewStatus": "rejected", "rejected": True},
            }
        ],
    }
    rejected: list[dict] = []

    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda *_args, **_kwargs: {"messages": [response_message.model_dump()]},
    )

    def fake_reject(issue_id: str, execution_id: str, **kwargs):
        rejected.append({"issue_id": issue_id, "execution_id": execution_id, **kwargs})
        return {"execution": refreshed_issue["actionExecutions"][0], "issue": refreshed_issue}

    monkeypatch.setattr("automail.addon.gmail.router.reject_issue_action_execution", fake_reject)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert rejected == [{
        "issue_id": "issue-123",
        "execution_id": "action-1",
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "rejected_by": "user@example.com",
        "note": "Rejected from Gmail add-on",
    }]
    card = response.json()["action"]["navigations"][0]["updateCard"]
    section_by_header = {section["header"]: section for section in card["sections"]}
    buttons = [
        button["text"]
        for widget in section_by_header["Issue"]["widgets"]
        if "buttonList" in widget
        for button in widget["buttonList"]["buttons"]
    ]
    assert "Approve action" not in buttons
    assert "Reject action" not in buttons


@pytest.mark.no_gemini
def test_gmail_claim_issue_action_refreshes_issue_card(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "claimIssue",
        "chatId": "gmail:msg-123",
        "issueId": "issue-123",
    }
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(email_body="Generated reply", email_attachments=[]),
    )
    issue = {
        "id": "issue-123",
        "status": "open",
        "workflowStatus": "open",
        "priority": "normal",
        "assigneeEmail": "",
    }
    updates: list[dict] = []

    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda *_args, **_kwargs: {"messages": [response_message.model_dump()]},
    )

    def fake_update(issue_id: str, **kwargs):
        updates.append({"issue_id": issue_id, **kwargs})
        return {**issue, "assigneeEmail": "user@example.com"}

    monkeypatch.setattr("automail.addon.gmail.router.update_issue", fake_update)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert updates == [{
        "issue_id": "issue-123",
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "updates": {
            "assignee_email": "user@example.com",
            "workflow_source": "gmail_addon_claim",
        },
    }]
    card = response.json()["action"]["navigations"][0]["updateCard"]
    section_by_header = {section["header"]: section for section in card["sections"]}
    issue_text = [
        widget["decoratedText"]["text"]
        for widget in section_by_header["Issue"]["widgets"]
        if "decoratedText" in widget
    ]
    assert "user@example.com" in issue_text


@pytest.mark.no_gemini
def test_gmail_mark_done_action_refreshes_issue_card(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "markIssueDone",
        "chatId": "gmail:msg-123",
        "issueId": "issue-123",
    }
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(email_body="Generated reply", email_attachments=[]),
    )
    issue = {
        "id": "issue-123",
        "status": "ongoing",
        "workflowStatus": "ongoing",
        "priority": "normal",
        "assigneeEmail": "agent@example.com",
        "needsResponse": False,
    }
    updates: list[dict] = []

    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr("automail.addon.gmail.router.get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda *_args, **_kwargs: {"messages": [response_message.model_dump()]},
    )

    def fake_update(issue_id: str, **kwargs):
        updates.append({"issue_id": issue_id, **kwargs})
        return {**issue, "status": "done", "workflowStatus": "done"}

    monkeypatch.setattr("automail.addon.gmail.router.update_issue", fake_update)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert updates == [{
        "issue_id": "issue-123",
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "updates": {
            "status": "done",
            "workflow_source": "gmail_addon_done",
        },
    }]
    card = response.json()["action"]["navigations"][0]["updateCard"]
    section_by_header = {section["header"]: section for section in card["sections"]}
    issue_text = [
        widget["decoratedText"]["text"]
        for widget in section_by_header["Issue"]["widgets"]
        if "decoratedText" in widget
    ]
    assert "Done" in issue_text


@pytest.mark.no_gemini
def test_gmail_result_card_collapses_missing_customer_and_duplicate_review():
    reason = "The email is about a tender, not a legal intake enquiry."
    card = build_result_card(
        [
            Message(role="email", user="email", content="original"),
            Message(
                role="response",
                user="response",
                content=EmailResponse(
                    email_body="Needs review.",
                    email_attachments=[],
                    requires_human=True,
                    requires_human_reason=reason,
                    identity_result=IdentityResult(customer_found=False, tool_calls_made=["crm"]),
                    intent_result=IntentResult(matched=False, intent_name=reason),
                ),
            ),
        ],
        chat_id="gmail:msg-123",
        action_url="https://api.mantly.io/addons/gmail/action",
    )

    section_by_header = {section["header"]: section for section in card["sections"]}
    assert "Feedback" not in section_by_header
    assert section_by_header["Customer"]["widgets"][0]["decoratedText"]["text"] == "Not found"
    intent_widgets = section_by_header["Intent"]["widgets"]
    assert len(intent_widgets) == 1
    assert reason in intent_widgets[0]["decoratedText"]["text"]


@pytest.mark.no_gemini
def test_gmail_result_card_shows_idle_customer_when_identity_inactive():
    card = build_result_card(
        [
            Message(role="email", user="email", content="original"),
            Message(
                role="response",
                user="response",
                content=EmailResponse(
                    email_body="Generated reply.",
                    email_attachments=[],
                    identity_result=IdentityResult(),
                ),
            ),
        ],
        chat_id="gmail:msg-123",
        action_url="https://api.mantly.io/addons/gmail/action",
    )

    customer_widget = card["sections"][0]["widgets"][0]["decoratedText"]
    assert "topLabel" not in customer_widget
    assert customer_widget["text"] == "-"
    assert "bottomLabel" not in customer_widget
    assert customer_widget["startIcon"]["knownIcon"] == "CLOCK"


@pytest.mark.no_gemini
def test_gmail_intent_action_triggers_shared_webhook_executor(client, monkeypatch):
    captured = {}
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "triggerIntentAction",
        "chatId": "gmail:msg-123",
        "actionName": "send",
    }
    event["commonEventObject"]["formInputs"] = {
        "category": {"stringInputs": {"value": ["A"]}},
        "note": {"stringInputs": {"value": ["Call back"]}},
        "dueDate": {
            "dateInput": {
                "msSinceEpoch": int(datetime(2026, 5, 22, tzinfo=timezone.utc).timestamp() * 1000)
            }
        },
    }
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(
            email_body="Generated reply",
            email_attachments=[],
            intent_result=IntentResult(
                matched=True,
                intent_name="Matched",
                actions=[
                    IntentAction(
                        name="category",
                        label="Category",
                        type="dropdown",
                        options=["A", "B"],
                        webhook="https://example.com/category",
                    ),
                    IntentAction(
                        name="dueDate",
                        label="Due Date",
                        type="calendar",
                        webhook="https://example.com/date",
                    ),
                    IntentAction(
                        name="note",
                        label="Note",
                        type="input",
                        webhook="https://example.com/note",
                    ),
                    IntentAction(
                        name="send",
                        label="Send",
                        type="button",
                        webhook="https://example.com/send",
                        payload={"policyNumber": "BH-2048-77"},
                    ),
                ],
            ),
        ),
    )
    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda chat_id, tenant_id=None, project_id=None: {"messages": [response_message.model_dump()]},
    )

    async def fake_execute(body, *, tenant_id, project_id, user_email, authorization_header=""):
        captured["webhook"] = body.webhook
        captured["payload"] = body.payload
        captured["tenant_id"] = tenant_id
        captured["project_id"] = project_id
        captured["user_email"] = user_email
        return {"status": "ok"}

    monkeypatch.setattr("automail.addon.gmail.router.execute_action_webhook", fake_execute)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert response.json() == {"action": {"notification": {"text": "Action completed"}}}
    assert captured == {
        "webhook": "https://example.com/send",
        "payload": {
            "policyNumber": "BH-2048-77",
            "actionName": "send",
            "actionLabel": "Send",
            "chatId": "gmail:msg-123",
            "category": "A",
            "dueDate": "2026-05-22",
            "note": "Call back",
        },
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "user_email": "user@example.com",
    }


@pytest.mark.no_gemini
@pytest.mark.parametrize("action", ["triggerIntentAction", "feedback"])
def test_gmail_mutations_require_project_membership(client, monkeypatch, action):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": action,
        "chatId": "gmail:msg-123",
        "actionName": "send",
        "rating": "like",
    }
    called = {"webhook": False, "feedback": False}
    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda _event: GmailAddonIdentity(
            email="outsider@example.com",
            tenant_id="tenant-a",
            payload=SimpleNamespace(user_id="user-outsider"),
        ),
    )
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat_project",
        lambda *_args, **_kwargs: "project-a",
    )
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_user_project_role",
        lambda *_args, **_kwargs: None,
    )

    async def fake_webhook(*_args, **_kwargs):
        called["webhook"] = True

    def fake_feedback(*_args, **_kwargs):
        called["feedback"] = True

    monkeypatch.setattr("automail.addon.gmail.router.execute_action_webhook", fake_webhook)
    monkeypatch.setattr("automail.addon.gmail.router.submit_feedback_for_context", fake_feedback)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert "required project access" in json.dumps(response.json()).lower()
    assert called == {"webhook": False, "feedback": False}


@pytest.mark.no_gemini
def test_gmail_analyze_checks_project_membership_before_processing(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {"action": "analyze"}
    called = False
    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda _event: GmailAddonIdentity(
            email="outsider@example.com",
            tenant_id="tenant-a",
            payload=SimpleNamespace(user_id="user-outsider"),
        ),
    )
    monkeypatch.setattr(
        "automail.addon.gmail.router.fetch_current_email",
        lambda _event: Email(
            id="gmail:msg-123",
            subject="Subject",
            from_address="client@example.com",
            body="Hello",
            attachments=[],
        ),
    )
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat_project",
        lambda *_args, **_kwargs: "project-a",
    )
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_user_project_role",
        lambda *_args, **_kwargs: None,
    )

    def fake_process(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("automail.addon.gmail.router.process_email_for_context", fake_process)

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert "required project access" in json.dumps(response.json()).lower()
    assert called is False


@pytest.mark.no_gemini
def test_gmail_apply_response_requests_compose_scope(client):
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {
        "action": "applyResponse",
        "chatId": "gmail:msg-123",
    }

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert response.json() == {
        "requesting_google_scopes": {
            "scopes": [GMAIL_CURRENT_ACTION_COMPOSE_SCOPE]
        }
    }


@pytest.mark.no_gemini
def test_gmail_apply_response_opens_created_draft(client, monkeypatch):
    event = load_fixture("message_open.json")
    event["authorizationEventObject"]["authorizedScopes"].append(GMAIL_CURRENT_ACTION_COMPOSE_SCOPE)
    event["commonEventObject"]["parameters"] = {
        "action": "applyResponse",
        "chatId": "gmail:msg-123",
    }
    response_message = Message(
        role="response",
        user="response",
        content=EmailResponse(
            email_body="Generated reply",
            email_attachments=[],
        ),
    )
    email = Email(
        id="gmail:msg-123",
        subject="Subject",
        from_address="client@example.com",
        body="Hello",
        attachments=[],
    )
    monkeypatch.setattr(
        "automail.addon.gmail.router.resolve_addon_identity",
        lambda addon_event: GmailAddonIdentity(email="user@example.com", tenant_id="tenant-a", payload=None),
    )
    monkeypatch.setattr("automail.addon.gmail.router.get_chat_project", lambda chat_id, tenant_id=None: "project-a")
    monkeypatch.setattr(
        "automail.addon.gmail.router.get_chat",
        lambda chat_id, tenant_id=None, project_id=None: {"messages": [response_message.model_dump()]},
    )
    monkeypatch.setattr("automail.addon.gmail.router.fetch_current_email", lambda addon_event: email)
    monkeypatch.setattr(
        "automail.addon.gmail.router.create_reply_draft",
        lambda addon_event, fetched_email, response: {"id": "r123", "threadId": "thread-123"},
    )

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert response.json() == {
        "hostAppAction": {
            "gmailAction": {
                "openCreatedDraftActionMarkup": {
                    "draftId": "r123",
                    "draftThreadId": "thread-123",
                }
            }
        }
    }


@pytest.mark.no_gemini
def test_gmail_analyze_requests_missing_scopes(client):
    event = load_fixture("message_open.json")
    event["authorizationEventObject"]["authorizedScopes"] = ["https://www.googleapis.com/auth/userinfo.email"]
    event["commonEventObject"]["parameters"] = {"action": "analyze"}

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    assert response.json() == {
        "requesting_google_scopes": {
            "scopes": ["https://www.googleapis.com/auth/gmail.addons.current.message.readonly"]
        }
    }


@pytest.mark.no_gemini
def test_gmail_analyze_missing_google_identity_returns_authorize_card(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_ADDON_VERIFY_REQUESTS", "false")
    monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", True)
    event = load_fixture("message_open.json")
    event["commonEventObject"]["parameters"] = {"action": "analyze"}

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    card = response.json()["action"]["navigations"][0]["updateCard"]
    assert card["header"]["title"] == "Authorize Gmail"


@pytest.mark.no_gemini
def test_gmail_analyze_unknown_mantly_user_returns_connect_card(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_ADDON_VERIFY_REQUESTS", "false")
    monkeypatch.setenv("GOOGLE_ADDON_OAUTH_CLIENT_ID", "gmail-client")
    monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", True)
    monkeypatch.setattr(
        "automail.addon.gmail.auth._verify_google_jwt",
        lambda *_args, **_kwargs: {"email": "unknown@example.com", "email_verified": True},
    )
    monkeypatch.setattr("automail.addon.gmail.auth.get_user_by_email", lambda email: None)
    event = load_fixture("message_open.json")
    event["authorizationEventObject"]["userIdToken"] = gmail_id_token("unknown@example.com")
    event["commonEventObject"]["parameters"] = {"action": "analyze"}

    response = client.post("/addons/gmail/action", json=event)

    assert response.status_code == 200
    card = response.json()["action"]["navigations"][0]["updateCard"]
    assert card["header"]["title"] == "Connect Mantly"
    buttons = card["sections"][0]["widgets"][-1]["buttonList"]["buttons"]
    assert "/gmail/connect" in buttons[0]["onClick"]["openLink"]["url"]
    assert "unknown%40example.com" in buttons[0]["onClick"]["openLink"]["url"]
    assert "view=signup" in buttons[1]["onClick"]["openLink"]["url"]


@pytest.mark.no_gemini
def test_gmail_message_user_without_tenant_returns_access_card(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_ADDON_VERIFY_REQUESTS", "false")
    monkeypatch.setenv("GOOGLE_ADDON_OAUTH_CLIENT_ID", "gmail-client")
    monkeypatch.setattr("automail.core.auth.REQUIRE_AUTH", True)
    monkeypatch.setattr(
        "automail.addon.gmail.auth._verify_google_jwt",
        lambda *_args, **_kwargs: {"email": "member@example.com", "email_verified": True},
    )
    monkeypatch.setattr("automail.addon.gmail.auth.get_user_by_email", lambda email: {"id": "user-a", "tenant": ""})
    event = load_fixture("message_open.json")
    event["authorizationEventObject"]["userIdToken"] = gmail_id_token("member@example.com")

    response = client.post("/addons/gmail/message", json=event)

    assert response.status_code == 200
    card = response.json()["action"]["navigations"][0]["pushCard"]
    assert card["header"]["title"] == "Mantly Access Needed"
