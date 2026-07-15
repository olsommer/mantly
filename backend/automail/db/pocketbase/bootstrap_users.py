"""PocketBase users collection schema bootstrap."""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from automail.db.pocketbase.bootstrap_common import (
    _USERS_COLLECTION_ID,
    PB_ADMIN_EMAIL,
    PB_ADMIN_PASSWORD,
    PB_URL,
    _authenticate_superuser,
)
from automail.db.pocketbase.bootstrap_schema_fields import (
    _bool_field,
    _date_field,
    _find_field,
    _number_field,
    _text_field,
)

logger = logging.getLogger(__name__)

_MUST_CHANGE_PASSWORD_FIELD_NAME = "must_change_password"
_MUST_CHANGE_PASSWORD_FIELD_ID = "bool915273641"
_MUST_CHANGE_PASSWORD_FIELD = {
    "hidden": False,
    "id": _MUST_CHANGE_PASSWORD_FIELD_ID,
    "name": _MUST_CHANGE_PASSWORD_FIELD_NAME,
    "presentable": False,
    "required": False,
    "system": False,
    "type": "bool",
}


@dataclass(slots=True)
class UsersSchemaBootstrapResult:
    updated: bool
    changed_create_rule: bool
    added_must_change_password_field: bool
    added_name_field: bool = False
    added_language_field: bool = False


def _get_users_collection(client: httpx.Client, pb_url: str, token: str) -> dict[str, Any]:
    response = client.get(
        f"{pb_url}/api/collections/{_USERS_COLLECTION_ID}",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()


def _find_must_change_password_field(fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    return _find_field(fields, _MUST_CHANGE_PASSWORD_FIELD_NAME)


def ensure_users_collection_schema(
    *,
    client: httpx.Client | None = None,
    pb_url: str | None = None,
    pb_admin_email: str | None = None,
    pb_admin_password: str | None = None,
) -> UsersSchemaBootstrapResult:
    """Ensure the PB users collection matches the backend's expected auth schema."""
    resolved_pb_url = (pb_url or PB_URL).rstrip("/")
    resolved_email = (pb_admin_email if pb_admin_email is not None else PB_ADMIN_EMAIL).strip()
    resolved_password = pb_admin_password if pb_admin_password is not None else PB_ADMIN_PASSWORD

    with httpx.Client(timeout=10.0) if client is None else client as http_client:
        token = _authenticate_superuser(
            http_client,
            resolved_pb_url,
            resolved_email,
            resolved_password,
        )
        collection = _get_users_collection(http_client, resolved_pb_url, token)
        fields = list(collection.get("fields") or [])

        auth_field_defs = [
            _text_field("name"),
            _text_field("language"),
            _MUST_CHANGE_PASSWORD_FIELD.copy(),
            _bool_field("password_login_enabled"),
            _text_field("login_code_hash"),
            _date_field("login_code_expires"),
            _number_field("login_code_attempts"),
        ]

        must_change_password_field = _find_must_change_password_field(fields)
        if must_change_password_field and must_change_password_field.get("type") != "bool":
            raise RuntimeError(
                "PocketBase users collection contains must_change_password with an unexpected type."
            )

        existing_names = {field.get("name") for field in fields}
        fields_to_add = [field_def for field_def in auth_field_defs if field_def["name"] not in existing_names]
        add_field = bool(fields_to_add)
        change_create_rule = collection.get("createRule") is not None

        if not add_field and not change_create_rule:
            return UsersSchemaBootstrapResult(
                updated=False,
                changed_create_rule=False,
                added_must_change_password_field=False,
                added_name_field=False,
                added_language_field=False,
            )

        payload: dict[str, Any] = {}
        if add_field:
            payload["fields"] = fields + fields_to_add
        if change_create_rule:
            payload["createRule"] = None

        response = http_client.patch(
            f"{resolved_pb_url}/api/collections/{_USERS_COLLECTION_ID}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        response.raise_for_status()

        logger.info(
            "PocketBase users collection updated: createRule_locked=%s auth_fields_added=%s",
            change_create_rule,
            [field["name"] for field in fields_to_add],
        )
        return UsersSchemaBootstrapResult(
            updated=True,
            changed_create_rule=change_create_rule,
            added_must_change_password_field=any(
                field["name"] == _MUST_CHANGE_PASSWORD_FIELD_NAME
                for field in fields_to_add
            ),
            added_name_field=any(field["name"] == "name" for field in fields_to_add),
            added_language_field=any(field["name"] == "language" for field in fields_to_add),
        )
