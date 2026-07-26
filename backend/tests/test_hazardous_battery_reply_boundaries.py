from __future__ import annotations

import httpx
import pytest

from automail.db.pocketbase import issues
from automail.support.delivery import DeliveryResult

_HAZARD_ISSUE = {
    "id": "issue-battery",
    "subject": "Leaking lithium battery",
    "status": "ongoing",
    "assigneeEmail": "lead@example.com",
    "assignee_email": "lead@example.com",
    "messages": [
        {
            "direction": "customer",
            "body": "The lithium battery in the parcel is leaking and getting hot.",
        }
    ],
}

_COMPLETE_GUIDANCE = (
    "Stop handling, using, and charging the item immediately. "
    "Isolate it only if this can be done safely, and keep it away from heat and "
    "flammable materials only if safe. Do not ship or return it until you receive "
    "confirmed hazardous-goods instructions after human review. If smoke, fire, or "
    "unusual heat is present or develops, move away and contact local emergency "
    "services or the local fire authority."
)


def _outbound(*, body: str, metadata: dict | None = None) -> dict:
    return {
        "id": "reply-battery",
        "issue": "issue-battery",
        "channel": "email",
        "to_address": "customer@example.com",
        "from_address": "lead@example.com",
        "subject": "Re: Leaking lithium battery",
        "body": body,
        "status": "draft",
        "metadata": metadata or {"approvalRequired": True, "approved": False},
    }


def test_approval_rejects_contradictory_human_battery_safety_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = _outbound(body=_COMPLETE_GUIDANCE + " Return it now.")
    monkeypatch.setattr(
        issues,
        "_first",
        lambda collection, *_args, **_kwargs: (
            reply if collection == "support_outbound_messages" else None
        ),
    )
    monkeypatch.setattr(issues, "get_issue", lambda *_args, **_kwargs: _HAZARD_ISSUE)
    monkeypatch.setattr(
        issues,
        "_patch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe reply must not be approved")
        ),
    )

    with pytest.raises(ValueError) as exc:
        issues.approve_issue_reply(
            "issue-battery",
            "reply-battery",
            tenant_id="tenant-1",
            project_id="project-1",
            approved_by="lead@example.com",
        )

    assert "Reply safety validation failed: safety_guidance_missing:" in str(exc.value)
    assert "contradictory_shipping_or_return_guidance" in str(exc.value)


def test_approval_rejects_missing_issue_context_before_metadata_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = _outbound(body="Prepared answer.")
    patches: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        issues,
        "_first",
        lambda collection, *_args, **_kwargs: (
            reply if collection == "support_outbound_messages" else None
        ),
    )
    monkeypatch.setattr(issues, "get_issue", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        issues,
        "_patch",
        lambda path, data: patches.append((path, data)) or data,
    )

    with pytest.raises(ValueError) as exc:
        issues.approve_issue_reply(
            "issue-battery",
            "reply-battery",
            tenant_id="tenant-1",
            project_id="project-1",
            approved_by="lead@example.com",
        )

    assert str(exc.value) == (
        "Reply safety validation failed: safety_context_unavailable"
    )
    assert patches == []


def test_approval_rejects_unavailable_issue_context_before_metadata_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = _outbound(body="Prepared answer.")
    request = httpx.Request("GET", "https://pocketbase.test/support_issues")
    response = httpx.Response(503, request=request)
    monkeypatch.setattr(
        issues,
        "_first",
        lambda collection, *_args, **_kwargs: (
            reply if collection == "support_outbound_messages" else None
        ),
    )

    def fail_get_issue(*_args, **_kwargs):
        raise httpx.HTTPStatusError(
            "service unavailable",
            request=request,
            response=response,
        )

    monkeypatch.setattr(issues, "get_issue", fail_get_issue)
    monkeypatch.setattr(
        issues,
        "_patch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("reply must not be approved without issue context")
        ),
    )

    with pytest.raises(ValueError) as exc:
        issues.approve_issue_reply(
            "issue-battery",
            "reply-battery",
            tenant_id="tenant-1",
            project_id="project-1",
            approved_by="lead@example.com",
        )

    assert str(exc.value) == (
        "Reply safety validation failed: safety_context_unavailable"
    )


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        (
            "Please wait for our specialist before doing anything else.",
            "stop_handling_using_charging",
        ),
        (
            _COMPLETE_GUIDANCE + " Place it in a hot oven.",
            "contradictory_unsafe_isolation_or_placement_guidance",
        ),
    ],
    ids=["missing-guidance", "unsafe-hot-oven-placement"],
)
def test_final_delivery_rejects_invalid_guidance_despite_human_approval(
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    expected_code: str,
) -> None:
    reply = {
        **_outbound(
            body=body,
            metadata={
                "approvalRequired": False,
                "approved": True,
                "humanApproved": True,
                "approvedBy": "lead@example.com",
            },
        ),
        "status": "queued",
    }
    patches: list[tuple[str, dict]] = []
    events: list[dict] = []

    def fake_first(collection: str, *_args, **_kwargs):
        if collection == "support_outbound_messages":
            return reply
        if collection == "support_issues":
            return {
                **{
                    key: value
                    for key, value in _HAZARD_ISSUE.items()
                    if key != "messages"
                },
                "subject": "Order question",
            }
        if collection == "support_messages":
            return {
                "id": "message-latest",
                "direction": "visitor",
                "body": "The lithium battery in the parcel is leaking and getting hot.",
                "occurred_at": "2026-07-18T10:00:00Z",
            }
        return None

    monkeypatch.setattr(issues, "_first", fake_first)
    monkeypatch.setattr(
        issues,
        "_list_all",
        lambda collection, *_args, **_kwargs: (
            [fake_first("support_messages")]
            if collection == "support_messages"
            else []
        ),
    )
    monkeypatch.setattr(
        issues,
        "_patch",
        lambda path, data: patches.append((path, data)) or data,
    )
    monkeypatch.setattr(
        issues,
        "_record_issue_event",
        lambda **kwargs: events.append(kwargs),
    )
    monkeypatch.setattr(
        issues,
        "_claim_issue_reply_delivery",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe reply must not receive a delivery claim")
        ),
    )
    monkeypatch.setattr(
        issues,
        "send_support_email_reply",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe reply must not reach the provider")
        ),
    )

    with pytest.raises(ValueError) as exc:
        issues.deliver_issue_reply(
            "issue-battery",
            "reply-battery",
            tenant_id="tenant-1",
            project_id="project-1",
            actor_email="lead@example.com",
        )

    assert "Reply safety validation failed: safety_guidance_missing:" in str(exc.value)
    assert expected_code in str(exc.value)
    assert patches[0][1]["status"] == "draft"
    assert patches[0][1]["metadata"]["approvalRequired"] is True
    assert patches[0][1]["metadata"]["approved"] is False
    assert "humanApproved" not in patches[0][1]["metadata"]
    assert events[0]["event_type"] == "reply_safety_invalidated"


@pytest.mark.parametrize(
    "metadata",
    [
        {"source": "admin_inbox", "approvalRequired": False},
        {
            "source": "automation",
            "approvalRequired": False,
            "automationContext": {"actionType": "queue_reply"},
        },
    ],
)
def test_final_delivery_requires_human_approval_for_complete_hazard_reply(
    monkeypatch: pytest.MonkeyPatch,
    metadata: dict,
) -> None:
    reply = {
        **_outbound(body=_COMPLETE_GUIDANCE, metadata=metadata),
        "status": "queued",
    }
    patches: list[tuple[str, dict]] = []

    def fake_first(collection: str, *_args, **_kwargs):
        if collection == "support_outbound_messages":
            return reply
        if collection == "support_issues":
            return {key: value for key, value in _HAZARD_ISSUE.items() if key != "messages"}
        if collection == "support_messages":
            return {
                "id": "message-latest",
                "direction": "customer",
                "body": "The lithium battery is leaking.",
                "occurred_at": "2026-07-18T10:00:00Z",
            }
        return None

    monkeypatch.setattr(issues, "_first", fake_first)
    monkeypatch.setattr(
        issues,
        "_list_all",
        lambda collection, *_args, **_kwargs: (
            [fake_first("support_messages")]
            if collection == "support_messages"
            else []
        ),
    )
    monkeypatch.setattr(
        issues,
        "_patch",
        lambda path, data: patches.append((path, data)) or data,
    )
    monkeypatch.setattr(issues, "_record_issue_event", lambda **_kwargs: None)
    monkeypatch.setattr(
        issues,
        "_claim_issue_reply_delivery",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("unapproved hazard reply must not receive a delivery claim")
        ),
    )
    monkeypatch.setattr(
        issues,
        "send_support_email_reply",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("unapproved hazard reply must not reach the provider")
        ),
    )

    with pytest.raises(ValueError) as exc:
        issues.deliver_issue_reply(
            "issue-battery",
            "reply-battery",
            tenant_id="tenant-1",
            project_id="project-1",
        )

    assert str(exc.value).endswith("safety_human_approval_required")
    assert patches[0][1]["status"] == "draft"
    assert patches[0][1]["metadata"]["approvalRequired"] is True
    assert patches[0][1]["metadata"]["reviewStatus"] == "pending"


def test_final_delivery_preserves_unresolved_hazard_across_customer_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = {
        **_outbound(
            body=_COMPLETE_GUIDANCE,
            metadata={"source": "admin_inbox", "approvalRequired": False},
        ),
        "subject": "Re: Replacement request",
        "status": "queued",
    }

    def fake_first(collection: str, *_args, **_kwargs):
        if collection == "support_outbound_messages":
            return reply
        if collection == "support_issues":
            return {
                "id": "issue-battery",
                "subject": "Replacement request",
                "status": "ongoing",
                "assignee_email": "lead@example.com",
                "message_count": 2,
            }
        return None

    def fake_list_all(collection: str, *_args, **kwargs):
        assert collection == "support_messages"
        assert kwargs["sort"] == "occurred_at,created"
        return [
            {
                "id": "message-hazard",
                "direction": "customer",
                "body": "The lithium battery is leaking and hot.",
                "occurred_at": "2026-07-18T09:00:00Z",
            },
            {
                "id": "message-follow-up",
                "direction": "customer",
                "body": "Can you send the replacement today?",
                "occurred_at": "2026-07-18T10:00:00Z",
            },
        ]

    monkeypatch.setattr(issues, "_first", fake_first)
    monkeypatch.setattr(issues, "_list_all", fake_list_all)
    monkeypatch.setattr(issues, "_patch", lambda _path, data: data)
    monkeypatch.setattr(issues, "_record_issue_event", lambda **_kwargs: None)
    monkeypatch.setattr(
        issues,
        "_claim_issue_reply_delivery",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("unresolved hazard must require human approval")
        ),
    )

    with pytest.raises(ValueError) as exc:
        issues.deliver_issue_reply(
            "issue-battery",
            "reply-battery",
            tenant_id="tenant-1",
            project_id="project-1",
        )

    assert str(exc.value).endswith("safety_human_approval_required")


def test_final_delivery_accepts_complete_proven_human_approved_hazard_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = {
        "source": "admin_inbox",
        "approvalRequired": False,
        "approved": True,
        "humanApproved": True,
        "approvalSource": "human_review",
        "reviewStatus": "approved",
        "approvedBy": "lead@example.com",
        "approvedAt": "2026-07-18T10:05:00Z",
    }
    reply = {
        **_outbound(body=_COMPLETE_GUIDANCE, metadata=metadata),
        "status": "queued",
    }
    claims: list[dict] = []
    sent: list[dict] = []

    def fake_first(collection: str, *_args, **_kwargs):
        if collection == "support_outbound_messages":
            return reply
        if collection == "support_issues":
            return {key: value for key, value in _HAZARD_ISSUE.items() if key != "messages"}
        if collection == "support_messages":
            return {
                "id": "message-latest",
                "direction": "customer",
                "body": "The lithium battery is leaking.",
                "occurred_at": "2026-07-18T10:00:00Z",
            }
        return None

    def fake_claim(**kwargs):
        claims.append(kwargs)
        return {
            "claimed": True,
            "state": "sending",
            "claim_token": "claim-token",
            "attempt_key": "attempt-key",
            "claimed_at": "2026-07-18T10:06:00Z",
            "outbound": {**reply, "status": "sending"},
        }

    def fake_complete(**kwargs):
        return {
            **kwargs["reply"],
            "status": kwargs["status"],
            "provider": kwargs["provider"],
            "provider_message_id": kwargs["provider_message_id"],
            "metadata": kwargs["metadata_after"],
        }

    monkeypatch.setattr(issues, "_first", fake_first)
    monkeypatch.setattr(
        issues,
        "_list_all",
        lambda collection, *_args, **_kwargs: (
            [fake_first("support_messages")]
            if collection == "support_messages"
            else []
        ),
    )
    monkeypatch.setattr(issues, "_claim_issue_reply_delivery", fake_claim)
    monkeypatch.setattr(issues, "_complete_issue_reply_delivery", fake_complete)
    monkeypatch.setattr(
        issues,
        "send_support_email_reply",
        lambda **kwargs: sent.append(kwargs)
        or DeliveryResult(
            status="sent",
            provider="smtp",
            provider_message_id="smtp:reply-battery",
        ),
    )
    monkeypatch.setattr(issues, "_append_outbound_timeline_message", lambda **_kwargs: None)
    monkeypatch.setattr(issues, "_record_issue_event", lambda **_kwargs: None)
    monkeypatch.setattr(issues, "_mark_issue_sla_met", lambda **_kwargs: None)
    monkeypatch.setattr(issues, "update_issue", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(issues, "_run_reply_lifecycle_automations", lambda **_kwargs: None)

    delivered = issues.deliver_issue_reply(
        "issue-battery",
        "reply-battery",
        tenant_id="tenant-1",
        project_id="project-1",
        actor_email="lead@example.com",
    )

    assert delivered is not None
    assert delivered["status"] == "sent"
    assert len(claims) == 1
    assert len(sent) == 1


def test_final_safety_message_lookup_prefers_latest_occurrence_over_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        {
            "id": "backfilled-old",
            "direction": "customer",
            "body": "Older occurrence imported later.",
            "occurred_at": "2026-07-17T09:00:00Z",
            "created": "2026-07-18T11:00:00Z",
        },
        {
            "id": "actual-latest",
            "direction": "customer",
            "body": "The battery is leaking now.",
            "occurred_at": "2026-07-18T10:00:00Z",
            "created": "2026-07-18T10:01:00Z",
        },
    ]
    seen_sorts: list[str] = []

    def fake_list_all(
        _collection: str,
        _filter: str,
        *,
        sort: str,
        per_page: int,
    ):
        seen_sorts.append(sort)
        assert per_page == 200
        return sorted(records, key=lambda item: (item["occurred_at"], item["created"]))

    monkeypatch.setattr(issues, "_list_all", fake_list_all)

    messages = issues._latest_customer_safety_messages(
        "issue-battery",
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert seen_sorts == ["occurred_at,created"]
    assert messages[-1]["id"] == "actual-latest"
    assert messages[-1]["body"] == "The battery is leaking now."


def test_final_safety_message_lookup_fails_closed_on_read_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("GET", "https://pocketbase.test/support_messages")
    response = httpx.Response(503, request=request)

    def fail_list_all(
        _collection: str,
        _filter: str,
        *,
        sort: str,
        per_page: int,
    ):
        assert sort == "occurred_at,created"
        assert per_page == 200
        raise httpx.HTTPStatusError(
            "service unavailable",
            request=request,
            response=response,
        )

    monkeypatch.setattr(issues, "_list_all", fail_list_all)

    with pytest.raises(ValueError) as exc:
        issues._latest_customer_safety_messages(
            "issue-battery",
            tenant_id="tenant-1",
            project_id="project-1",
        )

    assert str(exc.value) == (
        "Reply safety validation failed: safety_context_unavailable"
    )


def test_final_delivery_fails_closed_when_declared_customer_messages_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = {
        **_outbound(
            body=_COMPLETE_GUIDANCE,
            metadata={
                "approvalRequired": False,
                "approved": True,
                "humanApproved": True,
                "approvalSource": "human_review",
                "reviewStatus": "approved",
                "approvedBy": "lead@example.com",
                "approvedAt": "2026-07-18T10:05:00Z",
            },
        ),
        "status": "queued",
    }
    patches: list[tuple[str, dict]] = []

    def fake_first(collection: str, *_args, **_kwargs):
        if collection == "support_outbound_messages":
            return reply
        if collection == "support_issues":
            return {
                "id": "issue-battery",
                "subject": "Leaking battery",
                "status": "ongoing",
                "assignee_email": "lead@example.com",
                "message_count": 2,
            }
        if collection == "support_messages":
            return None
        return None

    monkeypatch.setattr(issues, "_first", fake_first)
    monkeypatch.setattr(issues, "_list_all", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        issues,
        "_patch",
        lambda path, data: patches.append((path, data)) or data,
    )
    monkeypatch.setattr(issues, "_record_issue_event", lambda **_kwargs: None)
    monkeypatch.setattr(
        issues,
        "_claim_issue_reply_delivery",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("missing safety context must block the delivery claim")
        ),
    )

    with pytest.raises(ValueError) as exc:
        issues.deliver_issue_reply(
            "issue-battery",
            "reply-battery",
            tenant_id="tenant-1",
            project_id="project-1",
        )

    assert str(exc.value) == (
        "Reply safety validation failed: safety_context_unavailable"
    )
    assert patches[0][1]["status"] == "draft"
    assert patches[0][1]["metadata"]["safetyBlockedReason"] == (
        "safety_context_unavailable"
    )


def test_final_delivery_allows_a_truly_message_less_ordinary_ticket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = {
        **_outbound(
            body="Your replacement will ship today.",
            metadata={"approvalRequired": False},
        ),
        "subject": "Re: Replacement request",
        "status": "queued",
    }
    claims: list[dict] = []

    def fake_first(collection: str, *_args, **_kwargs):
        if collection == "support_outbound_messages":
            return reply
        if collection == "support_issues":
            return {
                "id": "issue-battery",
                "subject": "Replacement request",
                "status": "ongoing",
                "assignee_email": "lead@example.com",
                "message_count": 0,
            }
        if collection == "support_messages":
            return None
        return None

    def fake_claim(**kwargs):
        claims.append(kwargs)
        return {
            "claimed": False,
            "state": "sent",
            "outbound": {**reply, "status": "sent"},
        }

    monkeypatch.setattr(issues, "_first", fake_first)
    monkeypatch.setattr(issues, "_list_all", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(issues, "_claim_issue_reply_delivery", fake_claim)

    delivered = issues.deliver_issue_reply(
        "issue-battery",
        "reply-battery",
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert delivered is not None
    assert delivered["status"] == "sent"
    assert len(claims) == 1


def test_approval_accepts_complete_compliant_human_battery_safety_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = _outbound(
        body=_COMPLETE_GUIDANCE,
        metadata={
            "approvalRequired": True,
            "approved": False,
            "safetyBlockedReason": "prior failure",
            "safetyBlockedAt": "2026-07-18T09:00:00Z",
        },
    )
    patches: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        issues,
        "_first",
        lambda collection, *_args, **_kwargs: (
            reply if collection == "support_outbound_messages" else None
        ),
    )
    monkeypatch.setattr(issues, "get_issue", lambda *_args, **_kwargs: _HAZARD_ISSUE)
    monkeypatch.setattr(
        issues,
        "_patch",
        lambda path, data: patches.append((path, data)) or data,
    )
    monkeypatch.setattr(issues, "_record_issue_event", lambda **_kwargs: None)
    monkeypatch.setattr(issues, "_claim_issue_for_reply_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(issues, "_run_reply_lifecycle_automations", lambda **_kwargs: None)

    approved = issues.approve_issue_reply(
        "issue-battery",
        "reply-battery",
        tenant_id="tenant-1",
        project_id="project-1",
        approved_by="lead@example.com",
    )

    assert approved is not None
    assert approved["metadata"]["approved"] is True
    assert approved["metadata"]["humanApproved"] is True
    assert approved["metadata"]["approvalRequired"] is False
    assert "safetyBlockedReason" not in approved["metadata"]
    assert "safetyBlockedAt" not in approved["metadata"]
    assert patches[0][0].endswith("/reply-battery")
