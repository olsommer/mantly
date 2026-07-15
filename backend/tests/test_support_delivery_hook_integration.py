"""Live PocketBase proof for atomic outbound delivery claims."""

from __future__ import annotations

import hashlib
import os
import secrets
import string
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

PB_URL = os.getenv("PB_DELIVERY_HOOK_TEST_URL", "").rstrip("/")
PB_ADMIN_EMAIL = os.getenv("PB_DELIVERY_HOOK_TEST_EMAIL", "hooktest@example.com")
PB_ADMIN_PASSWORD = os.getenv("PB_DELIVERY_HOOK_TEST_PASSWORD", "")

pytestmark = pytest.mark.skipif(
    not PB_URL or not PB_ADMIN_PASSWORD,
    reason="live PocketBase delivery hook is not configured",
)


def _id(prefix: str) -> str:
    suffix_length = 15 - len(prefix)
    return prefix + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(suffix_length))


def _auth_token() -> str:
    response = httpx.post(
        f"{PB_URL}/api/collections/_superusers/auth-with-password",
        json={"identity": PB_ADMIN_EMAIL, "password": PB_ADMIN_PASSWORD},
        timeout=10,
    )
    response.raise_for_status()
    return str(response.json()["token"])


def _record(client: httpx.Client, collection: str, data: dict) -> dict:
    response = client.post(f"/api/collections/{collection}/records", json=data)
    response.raise_for_status()
    return response.json()


def _get_record(client: httpx.Client, collection: str, record_id: str) -> dict:
    response = client.get(f"/api/collections/{collection}/records/{record_id}")
    response.raise_for_status()
    return response.json()


def _delivery_case(
    client: httpx.Client,
    *,
    issue_fields: dict | None = None,
    outbound_fields: dict | None = None,
) -> tuple[dict, dict, str, str]:
    tenant_id = _id("tenant")
    project_id = _id("project")
    issue_id = _id("issue")
    outbound_id = _id("reply")
    _record(client, "tenants", {"id": tenant_id, "name": "Delivery hook test"})
    _record(
        client,
        "projects",
        {"id": project_id, "tenant": tenant_id, "name": "Delivery hook test"},
    )
    issue_data = {
        "id": issue_id,
        "tenant": tenant_id,
        "project": project_id,
        "source_email_id": _id("source"),
        "channel": "email",
        "status": "open",
        "priority": "normal",
        "subject": "Atomic claim",
        "from_address": "customer@example.test",
    }
    issue_data.update(issue_fields or {})
    issue = _record(client, "support_issues", issue_data)
    outbound_data = {
        "id": outbound_id,
        "tenant": tenant_id,
        "project": project_id,
        "issue": issue_id,
        "channel": "email",
        "to_address": "customer@example.test",
        "subject": "Re: Atomic claim",
        "body": "One provider call only.",
        "status": "queued",
        "metadata": {},
    }
    outbound_data.update(outbound_fields or {})
    outbound = _record(client, "support_outbound_messages", outbound_data)
    return issue, outbound, tenant_id, project_id


def _claim_payload(
    issue: dict,
    outbound: dict,
    tenant_id: str,
    project_id: str,
) -> dict:
    return {
        "issue_id": issue["id"],
        "project_id": project_id,
        "tenant_id": tenant_id,
        "expected_outbound_updated": outbound["updated"],
        "expected_issue_updated": issue["updated"],
        "expected_body_sha256": hashlib.sha256(outbound["body"].encode()).hexdigest(),
        "allow_failed": False,
        "worker_id": "integration-test",
        "lease_seconds": 900,
    }


def _assert_claim_rolled_back(client: httpx.Client, outbound: dict) -> None:
    current = _get_record(client, "support_outbound_messages", outbound["id"])
    assert current["status"] == outbound["status"]
    assert current["updated"] == outbound["updated"]
    assert not current.get("delivery_claim_token")
    assert not current.get("delivery_attempt_key")
    assert not current.get("delivery_claimed_at")
    assert not current.get("delivery_claim_expires_at")


def test_delivery_hook_claim_is_atomic_and_completion_is_token_fenced():
    unauthenticated = httpx.post(
        f"{PB_URL}/api/mantly/support-delivery/missing/claim",
        json={},
        timeout=10,
    )
    assert unauthenticated.status_code == 401

    token = _auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=PB_URL, headers=headers, timeout=10) as client:
        issue, outbound, tenant_id, project_id = _delivery_case(client)
    outbound_id = outbound["id"]
    claim_payload = _claim_payload(issue, outbound, tenant_id, project_id)

    def claim() -> httpx.Response:
        return httpx.post(
            f"{PB_URL}/api/mantly/support-delivery/{outbound_id}/claim",
            headers=headers,
            json=claim_payload,
            timeout=10,
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        responses = list(executor.map(lambda _index: claim(), range(10)))
    winners = [response for response in responses if response.status_code == 200]
    conflicts = [response for response in responses if response.status_code == 409]
    assert len(winners) == 1
    assert len(conflicts) == 9
    claim_result = winners[0].json()
    assert claim_result["claimed"] is True
    assert claim_result["state"] == "sending"
    assert claim_result["attempt_key"] == f"support-outbound:{outbound_id}"
    assert claim_result["claim_token"]

    completion_payload = {
        "claim_token": claim_result["claim_token"],
        "status": "sent",
        "certainty": "accepted",
        "provider": "integration",
        "provider_message_id": "provider-message-1",
        "metadata_patch": {"deliveryAttempts": 1},
    }
    wrong_token = httpx.post(
        f"{PB_URL}/api/mantly/support-delivery/{outbound_id}/complete",
        headers=headers,
        json={**completion_payload, "claim_token": "wrong-token"},
        timeout=10,
    )
    assert wrong_token.status_code == 409

    completed = httpx.post(
        f"{PB_URL}/api/mantly/support-delivery/{outbound_id}/complete",
        headers=headers,
        json=completion_payload,
        timeout=10,
    )
    assert completed.status_code == 200
    assert completed.json()["outbound"]["status"] == "sent"
    assert completed.json()["outbound"]["provider_message_id"] == "provider-message-1"

    duplicate = httpx.post(
        f"{PB_URL}/api/mantly/support-delivery/{outbound_id}/complete",
        headers=headers,
        json=completion_payload,
        timeout=10,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["idempotent"] is True
    assert duplicate.json()["outbound"]["provider_message_id"] == "provider-message-1"
    assert duplicate.json()["outbound"]["metadata"]["deliveryAttempts"] == 1


@pytest.mark.parametrize(
    ("failed_precondition", "expected_message"),
    [
        # PocketBase 0.36 sentenizes ApiError messages before serializing them.
        ("body", "Delivery_body_changed."),
        ("issue_version", "Delivery_issue_changed."),
    ],
)
def test_delivery_claim_precondition_failure_rolls_back_ownership(
    failed_precondition: str,
    expected_message: str,
):
    token = _auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=PB_URL, headers=headers, timeout=10) as client:
        issue, outbound, tenant_id, project_id = _delivery_case(client)
        payload = _claim_payload(issue, outbound, tenant_id, project_id)
        if failed_precondition == "body":
            payload["expected_body_sha256"] = hashlib.sha256(b"stale body").hexdigest()
        else:
            payload["expected_issue_updated"] = "2000-01-01 00:00:00.000Z"

        response = client.post(
            f"/api/mantly/support-delivery/{outbound['id']}/claim",
            json=payload,
        )

        assert response.status_code == 409
        assert response.json()["message"] == expected_message
        _assert_claim_rolled_back(client, outbound)


def test_delivery_claim_requires_configured_approval_before_ownership():
    token = _auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=PB_URL, headers=headers, timeout=10) as client:
        issue, outbound, tenant_id, project_id = _delivery_case(
            client,
            outbound_fields={
                "metadata": {
                    "approvalRequired": True,
                    "approved": False,
                }
            },
        )
        response = client.post(
            f"/api/mantly/support-delivery/{outbound['id']}/claim",
            json=_claim_payload(issue, outbound, tenant_id, project_id),
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Delivery_approval_required."
        _assert_claim_rolled_back(client, outbound)


def test_delivery_claim_blocks_unreviewed_automatic_reply_for_terminal_issue():
    token = _auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=PB_URL, headers=headers, timeout=10) as client:
        issue, outbound, tenant_id, project_id = _delivery_case(
            client,
            issue_fields={"status": "closed"},
            outbound_fields={
                "metadata": {
                    "source": "agent_answer",
                    "autoSend": True,
                    "humanApproved": False,
                }
            },
        )
        response = client.post(
            f"/api/mantly/support-delivery/{outbound['id']}/claim",
            json=_claim_payload(issue, outbound, tenant_id, project_id),
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Delivery_issue_terminal."
        _assert_claim_rolled_back(client, outbound)


def test_expired_claim_reconciliation_is_destructive_and_idempotent():
    token = _auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    expired_at = "2000-01-01 00:00:00.000Z"
    with httpx.Client(base_url=PB_URL, headers=headers, timeout=10) as client:
        _issue, outbound, _tenant_id, _project_id = _delivery_case(
            client,
            outbound_fields={
                "status": "sending",
                "delivery_attempt_key": "support-outbound:expired-test",
                "delivery_claimed_at": expired_at,
                "delivery_claim_expires_at": expired_at,
                "metadata": {"deliveryCertainty": "in_flight"},
            },
        )
        expected_expires_at = outbound["delivery_claim_expires_at"]
        assert expected_expires_at

        reconciled = client.post(
            f"/api/mantly/support-delivery/{outbound['id']}/reconcile-expired",
            json={"expected_expires_at": expected_expires_at},
        )

        assert reconciled.status_code == 200
        result = reconciled.json()
        assert result["idempotent"] is False
        assert result["state"] == "delivery_uncertain"
        assert result["outbound"]["status"] == "delivery_uncertain"
        assert not result["outbound"]["delivery_claim_expires_at"]
        assert result["outbound"]["error"] == "Delivery outcome uncertain after claim expiry"
        assert result["outbound"]["metadata"]["deliveryCertainty"] == "uncertain"
        assert result["outbound"]["metadata"]["deliveryReconcileReason"] == "claim_lease_expired"

        duplicate = client.post(
            f"/api/mantly/support-delivery/{outbound['id']}/reconcile-expired",
            json={"expected_expires_at": expected_expires_at},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["idempotent"] is True
        assert duplicate.json()["state"] == "delivery_uncertain"
