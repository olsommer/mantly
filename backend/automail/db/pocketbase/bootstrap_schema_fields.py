"""PocketBase schema field and collection helpers."""

import logging
from typing import Any

import httpx

from automail.db.pocketbase.bootstrap_common import _get_collection

logger = logging.getLogger(__name__)


def _find_field(fields: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Return the first field with the given name, or None."""
    return next((field for field in fields if field.get("name") == name), None)


def _text_field(name: str, *, required: bool = False) -> dict[str, Any]:
    return {"name": name, "type": "text", "required": required}


def _editor_field(name: str, *, required: bool = False) -> dict[str, Any]:
    return {"name": name, "type": "editor", "required": required}


def _json_field(name: str) -> dict[str, Any]:
    return {"name": name, "type": "json", "required": False}


def _bool_field(name: str) -> dict[str, Any]:
    return {"name": name, "type": "bool", "required": False}


def _number_field(name: str) -> dict[str, Any]:
    return {"name": name, "type": "number", "required": False}


def _date_field(name: str) -> dict[str, Any]:
    return {"name": name, "type": "date", "required": False}


def _file_field(name: str, *, required: bool = False, max_size: int = 10 * 1024 * 1024) -> dict[str, Any]:
    return {
        "name": name,
        "type": "file",
        "required": required,
        "maxSelect": 1,
        "maxSize": max_size,
        "mimeTypes": [],
        "thumbs": [],
        "protected": False,
    }


def _created_field() -> dict[str, Any]:
    return {"name": "created", "type": "autodate", "onCreate": True, "onUpdate": False}


def _updated_field() -> dict[str, Any]:
    return {"name": "updated", "type": "autodate", "onCreate": True, "onUpdate": True}


def _relation_field(name: str, collection_id: str, *, required: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "type": "relation",
        "required": required,
        "collectionId": collection_id,
        "maxSelect": 1,
        "cascadeDelete": False,
    }


def _relation_field_cascade(name: str, collection_id: str, *, required: bool = False) -> dict[str, Any]:
    """Like _relation_field but with cascadeDelete=True."""
    return {
        "name": name,
        "type": "relation",
        "required": required,
        "collectionId": collection_id,
        "maxSelect": 1,
        "cascadeDelete": True,
    }


def _ensure_field_on_collection(
    client: httpx.Client,
    pb_url: str,
    token: str,
    collection_name: str,
    field_def: dict[str, Any],
) -> bool:
    """Add a field to an existing collection if it doesn't already exist.

    Returns True if the field was added, False if it was already present.
    Silently returns False if the collection doesn't exist.
    """
    collection = _get_collection(client, pb_url, token, collection_name)
    if collection is None:
        return False

    fields = list(collection.get("fields") or [])
    if _find_field(fields, field_def["name"]) is not None:
        return False

    response = client.patch(
        f"{pb_url}/api/collections/{collection_name}",
        headers={"Authorization": f"Bearer {token}"},
        json={"fields": fields + [field_def]},
    )
    response.raise_for_status()
    logger.info(
        "Added field '%s' to PocketBase collection '%s'",
        field_def["name"],
        collection_name,
    )
    return True


def _ensure_field_options_on_collection(
    client: httpx.Client,
    pb_url: str,
    token: str,
    collection_name: str,
    field_def: dict[str, Any],
    option_names: set[str],
) -> bool:
    collection = _get_collection(client, pb_url, token, collection_name)
    if collection is None:
        return False

    fields = list(collection.get("fields") or [])
    existing = _find_field(fields, field_def["name"])
    if existing is None:
        return False

    changed = False
    updated_fields = []
    for field in fields:
        if field.get("name") != field_def["name"]:
            updated_fields.append(field)
            continue
        updated = dict(field)
        for option_name in option_names:
            if updated.get(option_name) != field_def.get(option_name):
                updated[option_name] = field_def.get(option_name)
                changed = True
        updated_fields.append(updated)

    if not changed:
        return False

    response = client.patch(
        f"{pb_url}/api/collections/{collection_name}",
        headers={"Authorization": f"Bearer {token}"},
        json={"fields": updated_fields},
    )
    response.raise_for_status()
    logger.info(
        "Updated field '%s' options on PocketBase collection '%s'",
        field_def["name"],
        collection_name,
    )
    return True


def _base_collection_payload(
    name: str,
    fields: list[dict[str, Any]],
    *,
    indexes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": "base",
        "fields": fields,
        "indexes": indexes or [],
        "listRule": None,
        "viewRule": None,
        "createRule": None,
        "updateRule": None,
        "deleteRule": None,
    }


def _create_collection(
    client: httpx.Client,
    pb_url: str,
    token: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(
        f"{pb_url}/api/collections",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def _ensure_collection(
    client: httpx.Client,
    pb_url: str,
    token: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    collection = _get_collection(client, pb_url, token, payload["name"])
    if collection is not None:
        return collection, False
    return _create_collection(client, pb_url, token, payload), True
