"""PocketBase bootstrap proof against representative existing schema and data."""

import os
from uuid import uuid4

import httpx
import pytest

from automail.db.pocketbase.bootstrap_app_schema import ensure_app_collections_schema

PB_URL = os.getenv("PB_EXISTING_SNAPSHOT_TEST_URL", "").rstrip("/")
PB_EMAIL = os.getenv("PB_EXISTING_SNAPSHOT_TEST_EMAIL", "")
PB_PASSWORD = os.getenv("PB_EXISTING_SNAPSHOT_TEST_PASSWORD", "")

pytestmark = [
    pytest.mark.no_gemini,
    pytest.mark.skipif(
        not (PB_URL and PB_EMAIL and PB_PASSWORD),
        reason="representative PocketBase snapshot test is not configured",
    ),
]


def _authenticate(client: httpx.Client) -> str:
    response = client.post(
        f"{PB_URL}/api/collections/_superusers/auth-with-password",
        json={"identity": PB_EMAIL, "password": PB_PASSWORD},
    )
    response.raise_for_status()
    return str(response.json()["token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _collection(client: httpx.Client, token: str, name: str) -> dict:
    response = client.get(f"{PB_URL}/api/collections/{name}", headers=_headers(token))
    response.raise_for_status()
    return response.json()


def _make_representative_old_collection(
    client: httpx.Client,
    token: str,
    name: str,
    *,
    missing_field: str,
) -> None:
    collection = _collection(client, token, name)
    fields = [
        field
        for field in collection.get("fields", [])
        if field.get("name") not in {missing_field, "legacy_snapshot_marker"}
    ]
    fields.append(
        {
            "name": "legacy_snapshot_marker",
            "type": "text",
            "required": False,
        }
    )
    response = client.patch(
        f"{PB_URL}/api/collections/{name}",
        headers=_headers(token),
        json={"fields": fields},
    )
    response.raise_for_status()


def _create_record(client: httpx.Client, token: str, collection: str, data: dict) -> dict:
    response = client.post(
        f"{PB_URL}/api/collections/{collection}/records",
        headers=_headers(token),
        json=data,
    )
    response.raise_for_status()
    return response.json()


def _record(client: httpx.Client, token: str, collection: str, record_id: str) -> dict:
    response = client.get(
        f"{PB_URL}/api/collections/{collection}/records/{record_id}",
        headers=_headers(token),
    )
    response.raise_for_status()
    return response.json()


def _field_names(collection: dict) -> set[str]:
    return {
        str(field.get("name"))
        for field in collection.get("fields", [])
        if field.get("name")
    }


def test_bootstrap_upgrades_existing_schema_without_losing_records_or_extension_fields():
    suffix = uuid4().hex[:10]
    with httpx.Client(timeout=20) as client:
        token = _authenticate(client)
        _make_representative_old_collection(
            client,
            token,
            "projects",
            missing_field="description",
        )
        _make_representative_old_collection(
            client,
            token,
            "support_issues",
            missing_field="merge_note",
        )

        tenant = _create_record(
            client,
            token,
            "tenants",
            {"name": f"Existing snapshot tenant {suffix}"},
        )
        project = _create_record(
            client,
            token,
            "projects",
            {
                "name": f"Existing snapshot project {suffix}",
                "tenant": tenant["id"],
                "legacy_snapshot_marker": "project-preserved",
            },
        )
        issue = _create_record(
            client,
            token,
            "support_issues",
            {
                "tenant": tenant["id"],
                "project": project["id"],
                "source_email_id": f"existing:{suffix}",
                "channel": "email",
                "source": "migration-fixture",
                "status": "open",
                "priority": "normal",
                "subject": "Existing issue survives bootstrap",
                "legacy_snapshot_marker": "issue-preserved",
            },
        )

        ensure_app_collections_schema(
            client=client,
            pb_url=PB_URL,
            pb_admin_email=PB_EMAIL,
            pb_admin_password=PB_PASSWORD,
        )
        ensure_app_collections_schema(
            client=client,
            pb_url=PB_URL,
            pb_admin_email=PB_EMAIL,
            pb_admin_password=PB_PASSWORD,
        )

        project_after = _record(client, token, "projects", project["id"])
        issue_after = _record(client, token, "support_issues", issue["id"])
        project_fields = _field_names(_collection(client, token, "projects"))
        issue_fields = _field_names(_collection(client, token, "support_issues"))

    assert project_after["name"] == f"Existing snapshot project {suffix}"
    assert project_after["legacy_snapshot_marker"] == "project-preserved"
    assert issue_after["subject"] == "Existing issue survives bootstrap"
    assert issue_after["legacy_snapshot_marker"] == "issue-preserved"
    assert {"description", "legacy_snapshot_marker"} <= project_fields
    assert {"merge_note", "legacy_snapshot_marker"} <= issue_fields
