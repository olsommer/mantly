from __future__ import annotations

import html
import os
import re
from datetime import date, datetime, time, timezone
from typing import Any

from automail.core.brand import get_brand
from automail.models import Email, EmailResponse, IdentityResult, IntentAction, Message

MANTLY_BLUE = {"red": 0.145, "green": 0.388, "blue": 0.922}

IDENTITY_FIELD_LABELS = {
    "name": "Customer",
    "customer": "Customer",
    "customer_name": "Customer",
    "customerName": "Customer",
    "policy": "Policy",
    "policy_type": "Policy",
    "policyType": "Policy",
    "policy_number": "Policy Number",
    "policyNumber": "Policy Number",
    "status": "Status",
}

IDENTITY_FIELD_ORDER = (
    "name",
    "customer",
    "customer_name",
    "customerName",
    "policy",
    "policy_type",
    "policyType",
    "policy_number",
    "policyNumber",
    "status",
)


def _clean(value: str, limit: int = 3500, *, escape: bool = True) -> str:
    value = value.strip()
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "..."
    if escape:
        value = html.escape(value)
    return value.replace("\n", "<br>")


def _text(text: str) -> dict[str, Any]:
    return {"textParagraph": {"text": _clean(text)}}


def _html_text(text: str, *, limit: int = 3500) -> dict[str, Any]:
    return {"textParagraph": {"text": text[:limit]}}


def _icon(name: str, alt_text: str = "") -> dict[str, str]:
    icon = {"knownIcon": name}
    if alt_text:
        icon["altText"] = alt_text
    return icon


def _decorated(
    top_label: str,
    text: str,
    *,
    bottom_label: str = "",
    icon: str = "",
    escape_text: bool = True,
) -> dict[str, Any]:
    decorated: dict[str, Any] = {
        "text": _clean(text, 600, escape=escape_text),
        "wrapText": True,
    }
    if top_label:
        decorated["topLabel"] = top_label
    if icon:
        decorated["startIcon"] = _icon(icon, top_label)
    if bottom_label:
        decorated["bottomLabel"] = _clean(bottom_label, 300)
    return {"decoratedText": decorated}


def _status(text: str, *, color: str, icon: str = "") -> dict[str, Any]:
    safe_text = html.escape(text.strip() or "Status")
    return _decorated(
        "Status",
        f'<font color="{color}"><b>{safe_text}</b></font>',
        icon=icon,
        escape_text=False,
    )


def _button(
    text: str,
    function_url: str,
    parameters: dict[str, str],
    *,
    color: dict[str, float] | None = None,
) -> dict[str, Any]:
    button: dict[str, Any] = {
        "text": text,
        "onClick": {
            "action": {
                "function": function_url,
                "parameters": [
                    {"key": key, "value": value}
                    for key, value in parameters.items()
                ],
            }
        },
    }
    if color:
        button["color"] = color
    return button


def _open_link_button(text: str, url: str) -> dict[str, Any]:
    return {"text": text, "onClick": {"openLink": {"url": url}}}


def _button_set(buttons: list[dict[str, Any]]) -> dict[str, Any]:
    return {"buttonList": {"buttons": buttons}}


def _text_input(name: str, label: str, *, value: str = "") -> dict[str, Any]:
    return {
        "textInput": {
            "name": name,
            "label": label,
            "type": "SINGLE_LINE",
            "value": value,
        }
    }


def _divider() -> dict[str, Any]:
    return {"divider": {}}


def _asset_base_url() -> str:
    return (
        os.getenv("GMAIL_ADDON_ASSET_BASE_URL", "").strip()
        or os.getenv("ASSET_BASE_URL", "").strip()
        or get_brand().support_url
    ).rstrip("/")


def _card(title: str, widgets: list[dict[str, Any]]) -> dict[str, Any]:
    return _card_with_sections(title, [{"widgets": widgets}])


def _card_with_sections(
    title: str,
    sections: list[dict[str, Any]],
    *,
    fixed_footer: dict[str, Any] | None = None,
    show_header: bool = True,
) -> dict[str, Any]:
    brand = get_brand()
    asset_base_url = _asset_base_url()
    card: dict[str, Any] = {"sections": sections}
    if show_header:
        card["header"] = {
            "title": title,
            "subtitle": brand.name,
            "imageUrl": f"{asset_base_url}/assets/icon-128.png" if asset_base_url else "",
            "imageType": "CIRCLE",
        }
    if fixed_footer:
        card["fixedFooter"] = fixed_footer
    return card


def _section(header: str, widgets: list[dict[str, Any]]) -> dict[str, Any]:
    return {"header": header, "widgets": widgets}


def push_card(card: dict[str, Any]) -> dict[str, Any]:
    return {"action": {"navigations": [{"pushCard": card}]}}


def update_card(card: dict[str, Any]) -> dict[str, Any]:
    return {"action": {"navigations": [{"updateCard": card}]}}


def request_scopes(scopes: list[str]) -> dict[str, Any]:
    return {"requesting_google_scopes": {"scopes": scopes}}


def notification(text: str) -> dict[str, Any]:
    return {"action": {"notification": {"text": text}}}


def open_created_draft(*, draft_id: str, thread_id: str) -> dict[str, Any]:
    return {
        "hostAppAction": {
            "gmailAction": {
                "openCreatedDraftActionMarkup": {
                    "draftId": draft_id,
                    "draftThreadId": thread_id,
                }
            }
        }
    }


def build_home_card(*, app_url: str) -> dict[str, Any]:
    return _card(
        "Mantly",
        [
            _text("Open a Gmail message and start Mantly from the side panel."),
            _button_set([_open_link_button("Open Mantly", app_url)]),
        ],
    )


def build_message_card(email: Email, *, action_url: str) -> dict[str, Any]:
    widgets = [
        _decorated("Subject", email.subject),
        _decorated("From", email.from_address or "Unknown sender"),
        _text(email.body[:700] if email.body else "No readable message body found."),
        _button_set([
            _button("Analyze", action_url, {"action": "analyze"}),
        ]),
    ]
    return _card("Current Email", widgets)


def build_authorize_card(*, app_url: str) -> dict[str, Any]:
    return _card(
        "Authorize Gmail",
        [
            _text("Mantly needs your verified Google identity before it can use your workspace."),
            _text("Reload the add-on and accept the requested Gmail permissions. If this keeps happening, open Mantly and sign in."),
            _button_set([_open_link_button("Open Mantly", app_url)]),
        ],
    )


def build_connect_card(*, email: str, connect_url: str, signup_url: str) -> dict[str, Any]:
    account_text = f"{email} is not connected to a Mantly workspace." if email else "This Google account is not connected to a Mantly workspace."
    return _card(
        "Connect Mantly",
        [
            _text(account_text),
            _text("Sign in with the same email in Mantly or ask an admin to invite this Google account."),
            _button_set([
                _open_link_button("Open Mantly", connect_url),
                _open_link_button("Sign up", signup_url),
            ]),
        ],
    )


def build_tenant_missing_card(*, email: str, connect_url: str) -> dict[str, Any]:
    return _card(
        "Mantly Access Needed",
        [
            _text(f"{email or 'This Google account'} exists in Mantly but is not assigned to a workspace."),
            _text("Ask your Mantly admin to add this user to a workspace, then reload the Gmail add-on."),
            _button_set([_open_link_button("Open Mantly", connect_url)]),
        ],
    )


def _response_from_messages(messages: list[Message]) -> EmailResponse | None:
    for message in messages:
        if message.role != "response":
            continue
        content: object = message.content
        if isinstance(content, EmailResponse):
            return content
        if isinstance(content, dict):
            return EmailResponse.model_validate(content)
    return None


def _label_for_identity_key(key: str) -> str:
    if key in IDENTITY_FIELD_LABELS:
        return IDENTITY_FIELD_LABELS[key]
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", key).replace("_", " ").strip()
    return spaced.title() if spaced else "Field"


def _stringify_identity_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if item is not None)
    if isinstance(value, dict):
        return ", ".join(
            f"{_label_for_identity_key(str(key))}: {item}"
            for key, item in value.items()
            if item is not None and str(item).strip()
        )
    return str(value).strip()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip().casefold()


def _ordered_identity_items(data: dict[str, Any]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    items: list[tuple[str, str]] = []

    for key in IDENTITY_FIELD_ORDER:
        if key not in data:
            continue
        value = _stringify_identity_value(data[key])
        if value:
            items.append((_label_for_identity_key(key), value))
            seen.add(key)

    for key, raw_value in data.items():
        if key in seen or str(key).startswith("_"):
            continue
        value = _stringify_identity_value(raw_value)
        if value:
            items.append((_label_for_identity_key(str(key)), value))

    return items[:6]


def _customer_section(identity_result: IdentityResult | None) -> dict[str, Any] | None:
    if not identity_result:
        return _section(
            "Customer",
            [_decorated("", "-", icon="CLOCK")],
        )

    widgets: list[dict[str, Any]] = []
    if identity_result.error:
        widgets.append(_status("Customer lookup error", color="#d93025", icon="PERSON"))
        widgets.append(_decorated("Details", identity_result.error, icon="DESCRIPTION"))
    elif identity_result.customer_found:
        widgets.append(_status("Customer found", color="#188038", icon="PERSON"))
    elif not identity_result.data and not identity_result.tool_calls_made:
        return _section(
            "Customer",
            [_decorated("", "-", icon="CLOCK")],
        )
    else:
        return _section("Customer", [_decorated("Customer", "Not found", icon="PERSON")])

    data = identity_result.data if isinstance(identity_result.data, dict) else {}
    identity_items = _ordered_identity_items(data)
    if identity_items:
        widgets.extend(_decorated(label, value, icon="DESCRIPTION") for label, value in identity_items)
    elif not identity_result.error:
        widgets.append(_decorated("Customer data", "No data returned.", icon="DESCRIPTION"))

    return _section("Customer", widgets)


def _intent_section(response: EmailResponse, intent: str) -> dict[str, Any] | None:
    intent_result = response.intent_result
    if not intent and not intent_result:
        return None

    matched = bool(intent_result.matched) if intent_result else bool(intent)
    if intent:
        color = "#1a73e8" if matched else "#5f6368"
        status = f'<font color="{color}"><b>{html.escape(intent)}</b></font>'
    elif intent_result and intent_result.error:
        status = f'<font color="#d93025"><b>{html.escape(intent_result.error)}</b></font>'
    else:
        status = '<font color="#5f6368"><b>No match</b></font>'

    widgets = [
        _decorated(
            "",
            status,
            icon="BOOKMARK",
            escape_text=False,
        )
    ]
    review_reason = (response.requires_human_reason or "Needs human review").strip()
    repeated_review = _normalize_text(review_reason) == _normalize_text(intent)
    if response.requires_human and matched and not repeated_review:
        widgets.append(_decorated("Review", review_reason, icon="DESCRIPTION"))

    return _section("Intent", widgets)


def _date_value_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return None
    return int(datetime.combine(parsed, time.min, tzinfo=timezone.utc).timestamp() * 1000)


def _action_callback(action: IntentAction, chat_id: str) -> dict[str, str]:
    return {
        "action": "triggerIntentAction",
        "chatId": chat_id,
        "actionName": action.name,
    }


def _action_run_button(action: IntentAction, *, chat_id: str, action_url: str) -> dict[str, Any] | None:
    if not action.webhook:
        return None
    return _button(action.label or "Run", action_url, _action_callback(action, chat_id))


def _action_input_widget(action: IntentAction) -> dict[str, Any]:
    return {
        "textInput": {
            "name": action.name,
            "label": action.label,
            "type": "SINGLE_LINE",
            "value": action.initial_value or "",
        }
    }


def _action_dropdown_widget(action: IntentAction) -> dict[str, Any]:
    initial = action.initial_value or ""
    return {
        "selectionInput": {
            "name": action.name,
            "label": action.label,
            "type": "DROPDOWN",
            "items": [
                {
                    "text": option,
                    "value": option,
                    "selected": option == initial,
                }
                for option in action.options
            ],
        }
    }


def _action_calendar_widget(action: IntentAction) -> dict[str, Any]:
    picker: dict[str, Any] = {
        "name": action.name,
        "label": action.label,
        "type": "DATE_ONLY",
    }
    value_ms = _date_value_ms(action.initial_value)
    if value_ms is not None:
        picker["valueMsEpoch"] = value_ms
    return {"dateTimePicker": picker}


def _action_widgets(action: IntentAction, *, chat_id: str, action_url: str) -> list[dict[str, Any]]:
    effective_type = action.type or "button"
    run_button = _action_run_button(action, chat_id=chat_id, action_url=action_url)
    if effective_type == "button":
        return [_button_set([run_button])] if run_button else []

    if effective_type == "dropdown":
        widgets = [_action_dropdown_widget(action)]
    elif effective_type == "calendar":
        widgets = [_action_calendar_widget(action)]
    else:
        widgets = [_action_input_widget(action)]

    if run_button:
        widgets.append(_button_set([run_button]))
    return widgets


def _actions_section(response: EmailResponse, *, chat_id: str, action_url: str) -> dict[str, Any] | None:
    intent_result = response.intent_result
    if not intent_result or not intent_result.matched or not intent_result.actions:
        return None

    widgets: list[dict[str, Any]] = []
    for action in intent_result.actions:
        action_items = _action_widgets(action, chat_id=chat_id, action_url=action_url)
        if not action_items:
            continue
        if widgets:
            widgets.append(_divider())
        widgets.extend(action_items)

    return _section("Actions", widgets) if widgets else None


def _attachment_names(response: EmailResponse) -> list[str]:
    names: list[str] = []
    for item in response.email_attachments:
        if isinstance(item, dict):
            filename = str(item.get("filename", "")).strip()
            if filename:
                names.append(filename)
    return names


def _response_section(response: EmailResponse) -> dict[str, Any]:
    attachment_names = _attachment_names(response)
    widgets: list[dict[str, Any]] = []

    if attachment_names:
        count = len(attachment_names)
        widgets.append(_decorated(f"Attachments ({count})", attachment_names[0], icon="DESCRIPTION"))
        for filename in attachment_names[1:4]:
            widgets.append(_decorated("Attachment", filename, icon="DESCRIPTION"))
        if len(attachment_names) > 4:
            widgets.append(_decorated("Attachment", f"+{len(attachment_names) - 4} more", icon="DESCRIPTION"))
        widgets.append(_divider())

    widgets.append(_decorated("Draft", response.email_body or "No response text generated.", icon="EMAIL"))
    return _section("Response", widgets)


def _issue_int(issue: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = issue.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return 0


def _issue_bool(issue: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = issue.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            clean = value.strip().lower()
            if clean in {"1", "true", "yes", "on"}:
                return True
            if clean in {"0", "false", "no", "off"}:
                return False
    return False


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _action_execution_requires_approval(execution: dict[str, Any]) -> bool:
    metadata = _record(execution.get("metadata"))
    review_status = str(metadata.get("reviewStatus") or "pending").strip().lower()
    return (
        str(execution.get("status") or "").strip().lower() == "pending"
        and metadata.get("approvalRequired") is True
        and review_status == "pending"
        and bool(str(execution.get("id") or "").strip())
    )


def _pending_action_executions(issue: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        execution for execution in issue.get("actionExecutions", [])
        if isinstance(execution, dict) and _action_execution_requires_approval(execution)
    ]


def _pending_reply_approval_count(issue: dict[str, Any], total_pending: int, action_pending: int) -> int:
    if "pendingReplyApprovalCount" in issue:
        return _issue_int(issue, "pendingReplyApprovalCount")
    if _issue_bool(issue, "hasPendingReplyApproval"):
        return max(1, total_pending - action_pending)
    if "pendingActionApprovalCount" in issue or _issue_bool(issue, "hasPendingActionApproval"):
        return max(0, total_pending - action_pending)
    return total_pending


def _pending_action_approval_count(issue: dict[str, Any]) -> int:
    count = _issue_int(issue, "pendingActionApprovalCount")
    if count:
        return count
    pending_actions = _pending_action_executions(issue)
    if pending_actions:
        return len(pending_actions)
    return 1 if _issue_bool(issue, "hasPendingActionApproval") else 0


def _issue_customer_waiting(issue: dict[str, Any]) -> bool:
    if "needsResponse" in issue:
        return _issue_bool(issue, "needsResponse")
    direction = str(issue.get("latestMessageDirection") or "").strip().lower()
    return direction in {"customer", "visitor"}


def _issue_next_action(
    issue: dict[str, Any],
    *,
    failed_deliveries: int,
    pending_reply_approvals: int,
    pending_action_approvals: int,
    pending_deliveries: int,
) -> tuple[str, str, str]:
    assignee = str(issue.get("assigneeEmail") or "").strip()
    status = str(issue.get("workflowStatus") or issue.get("status") or "open").strip().lower()
    if failed_deliveries > 0:
        count = failed_deliveries or 1
        return (
            "Fix failed delivery",
            "Retry delivery from this surface.",
            f"{count} delivery failed" if count == 1 else f"{count} deliveries failed",
        )
    if pending_reply_approvals > 0:
        count = pending_reply_approvals or 1
        return (
            "Review approval",
            "Review or send the prepared reply.",
            f"{count} approval pending" if count == 1 else f"{count} approvals pending",
        )
    if pending_action_approvals > 0:
        count = pending_action_approvals or 1
        return (
            "Review action",
            "Approve or reject the proposed action.",
            f"{count} action pending" if count == 1 else f"{count} actions pending",
        )
    if not assignee:
        return ("Assign owner", "Claim this issue before work starts.", "Unassigned")
    if _issue_bool(issue, "hasOverdueSla"):
        return ("Handle overdue SLA", "Open the issue and recover the SLA.", "SLA overdue")
    if _issue_customer_waiting(issue):
        return ("Reply to customer", "Customer is waiting for a response.", "Response needed")
    if pending_deliveries > 0:
        count = pending_deliveries or 1
        return (
            "Monitor delivery",
            "A reply is queued for delivery.",
            f"{count} delivery queued" if count == 1 else f"{count} deliveries queued",
        )
    if status not in {"done", "closed"}:
        return ("Ready to close", "No open blocker detected.", "Clear")
    return ("No immediate action", "Issue is clear for now.", "Clear")


def _action_execution_proposed_action(execution: dict[str, Any]) -> dict[str, Any]:
    result = _record(execution.get("result"))
    metadata = _record(execution.get("metadata"))
    proposed = result.get("proposedAction") or result.get("proposed_action")
    if isinstance(proposed, dict):
        return proposed
    proposed = metadata.get("proposedAction") or metadata.get("proposed_action")
    return proposed if isinstance(proposed, dict) else {}


def _action_execution_detail(execution: dict[str, Any]) -> str:
    action = _action_execution_proposed_action(execution)
    if not action:
        result = _record(execution.get("result"))
        metadata = _record(execution.get("metadata"))
        return str(result.get("summary") or metadata.get("summary") or "").strip()
    action_type = str(
        action.get("type")
        or action.get("actionType")
        or action.get("action_type")
        or action.get("action")
        or ""
    ).strip()
    if action_type in {"assign", "set_assignee"}:
        assignee = str(action.get("assigneeEmail") or action.get("assignee_email") or action.get("email") or "").strip()
        return f"Assign to {assignee}" if assignee else "Assign ticket"
    if action_type == "set_status":
        status = str(action.get("status") or "").strip()
        return f"Set status to {status}" if status else "Set status"
    if action_type == "set_priority":
        priority = str(action.get("priority") or "").strip()
        return f"Set priority to {priority}" if priority else "Set priority"
    if action_type in {"set_custom_fields", "set_custom_field", "update_custom_fields"}:
        fields = action.get("customFields") or action.get("custom_fields") or action.get("fields") or action.get("values")
        labels = [
            f"{key}={value}"
            for key, value in (_record(fields)).items()
            if str(key).strip() and str(value).strip()
        ]
        return f"Set fields {', '.join(labels[:3])}" if labels else "Set fields"
    if action_type in {"add_note", "internal_note"}:
        return "Add internal note"
    return str(action.get("label") or action.get("title") or action_type or "Proposed action").strip()


def _issue_section(
    issue: dict[str, Any] | None,
    *,
    issue_url: str = "",
    action_url: str = "",
    chat_id: str = "",
    can_queue_reply: bool = False,
) -> dict[str, Any] | None:
    if not issue:
        return None

    issue_id = str(issue.get("id") or "").strip()
    status = str(issue.get("workflowStatus") or issue.get("status") or "open").strip() or "open"
    priority = str(issue.get("priority") or "normal").strip() or "normal"
    assignee = str(issue.get("assigneeEmail") or "").strip() or "Unassigned"
    pending_approvals = _issue_int(issue, "pendingApprovalCount")
    if pending_approvals == 0 and _issue_bool(issue, "hasPendingApproval"):
        pending_approvals = 1
    pending_action_approvals = _pending_action_approval_count(issue)
    pending_reply_approvals = _pending_reply_approval_count(issue, pending_approvals, pending_action_approvals)
    failed_deliveries = _issue_int(issue, "failedDeliveryCount")
    if failed_deliveries == 0 and _issue_bool(issue, "hasFailedDelivery"):
        failed_deliveries = 1
    pending_deliveries = _issue_int(issue, "pendingDeliveryCount")
    if pending_deliveries == 0 and _issue_bool(issue, "hasPendingDelivery"):
        pending_deliveries = 1
    next_title, next_detail, next_badge = _issue_next_action(
        issue,
        failed_deliveries=failed_deliveries,
        pending_reply_approvals=pending_reply_approvals,
        pending_action_approvals=pending_action_approvals,
        pending_deliveries=pending_deliveries,
    )
    can_claim = bool(action_url and issue_id and assignee == "Unassigned")
    can_mark_done = (
        bool(action_url and issue_id)
        and next_title == "Ready to close"
        and str(issue.get("workflowStatus") or issue.get("status") or "open").strip().lower() not in {"done", "closed"}
    )
    widgets: list[dict[str, Any]] = [
        _decorated("Status", status.title(), icon="BOOKMARK"),
        _decorated("Priority", priority.title(), icon="STAR"),
        _decorated("Assignee", assignee, icon="PERSON"),
        _decorated("Next action", next_title, bottom_label=f"{next_badge} · {next_detail}", icon="CLOCK"),
    ]
    next_buttons: list[dict[str, Any]] = []
    if can_claim:
        next_buttons.append(_button("Assign to me", action_url, {"action": "claimIssue", "chatId": chat_id, "issueId": issue_id}))
    if can_queue_reply and action_url and issue_id and pending_approvals == 0:
        next_buttons.append(_button(
            "Queue approval",
            action_url,
            {"action": "queueIssueReply", "chatId": chat_id, "issueId": issue_id},
            color=MANTLY_BLUE,
        ))
    if can_mark_done:
        next_buttons.append(_button("Mark done", action_url, {"action": "markIssueDone", "chatId": chat_id, "issueId": issue_id}))
    if next_buttons:
        widgets.append(_button_set(next_buttons))
    if pending_reply_approvals:
        label = "1 approval pending" if pending_reply_approvals == 1 else f"{pending_reply_approvals} approvals pending"
        widgets.append(_decorated("Human review", label, icon="CLOCK"))
        if action_url and issue_id:
            widgets.append(_text_input("replyChangeNote", "Change request note"))
            widgets.append(_button_set([
                _button(
                    "Request changes",
                    action_url,
                    {"action": "requestIssueReplyChanges", "chatId": chat_id, "issueId": issue_id},
                ),
                _button(
                    "Approve",
                    action_url,
                    {"action": "approveIssueReply", "chatId": chat_id, "issueId": issue_id},
                ),
                _button(
                    "Approve & send",
                    action_url,
                    {"action": "approveSendIssueReply", "chatId": chat_id, "issueId": issue_id},
                    color=MANTLY_BLUE,
                ),
            ]))
    pending_actions = _pending_action_executions(issue)
    if pending_action_approvals:
        label = "1 action proposal" if pending_action_approvals == 1 else f"{pending_action_approvals} action proposals"
        widgets.append(_decorated("Action review", label, icon="BOOKMARK"))
        for action in pending_actions[:2]:
            action_id = str(action.get("id") or "").strip()
            detail = _action_execution_detail(action)
            label = str(action.get("label") or action.get("actionKey") or action.get("action_key") or "Proposed action").strip()
            widgets.append(_decorated("Proposal", label, bottom_label=detail, icon="DESCRIPTION"))
            widgets.append(_button_set([
                _button(
                    "Reject action",
                    action_url,
                    {"action": "rejectIssueAction", "chatId": chat_id, "issueId": issue_id, "actionId": action_id},
                ),
                _button(
                    "Approve action",
                    action_url,
                    {"action": "approveIssueAction", "chatId": chat_id, "issueId": issue_id, "actionId": action_id},
                    color=MANTLY_BLUE,
                ),
            ]))
    if pending_deliveries:
        label = "1 delivery queued" if pending_deliveries == 1 else f"{pending_deliveries} deliveries queued"
        widgets.append(_decorated("Delivery", label, icon="CLOCK"))
    if failed_deliveries:
        label = "1 delivery failed" if failed_deliveries == 1 else f"{failed_deliveries} deliveries failed"
        widgets.append(_decorated("Delivery", label, icon="WARNING"))
        if action_url and issue_id:
            widgets.append(_button_set([
                _button(
                    "Retry delivery",
                    action_url,
                    {"action": "retryFailedDelivery", "chatId": chat_id, "issueId": issue_id},
                )
            ]))
    if issue_url:
        widgets.append(_button_set([_open_link_button("Open issue", issue_url)]))
    return _section("Issue", widgets)


def _apply_response_footer(*, chat_id: str, action_url: str) -> dict[str, Any]:
    return {
        "primaryButton": _button(
            "Apply Response",
            action_url,
            {"action": "applyResponse", "chatId": chat_id},
            color=MANTLY_BLUE,
        )
    }


def build_result_card(
    messages: list[Message],
    *,
    chat_id: str,
    action_url: str,
    issue: dict[str, Any] | None = None,
    issue_url: str = "",
) -> dict[str, Any]:
    response = _response_from_messages(messages)
    if response is None:
        return build_error_card("Mantly did not return an email response.")

    intent = response.activated_intent or ""
    if response.intent_result and response.intent_result.intent_name:
        intent = response.intent_result.intent_name

    sections: list[dict[str, Any]] = []
    customer_section = _customer_section(response.identity_result)
    if customer_section:
        sections.append(customer_section)

    intent_section = _intent_section(response, intent)
    if intent_section:
        sections.append(intent_section)

    actions_section = _actions_section(response, chat_id=chat_id, action_url=action_url)
    if actions_section:
        sections.append(actions_section)

    sections.append(_response_section(response))
    issue_section = _issue_section(
        issue,
        issue_url=issue_url,
        action_url=action_url,
        chat_id=chat_id,
        can_queue_reply=bool(response.email_body.strip()),
    )
    if issue_section:
        sections.append(issue_section)
    fixed_footer = (
        _apply_response_footer(chat_id=chat_id, action_url=action_url)
        if response.email_body.strip()
        else None
    )

    return _card_with_sections("Mantly Result", sections, fixed_footer=fixed_footer, show_header=False)


def build_error_card(message: str) -> dict[str, Any]:
    return _card("Mantly Error", [_text(message)])
