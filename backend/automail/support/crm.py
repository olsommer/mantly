"""CRM connector sync for support account intelligence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

from automail.core.runtime_secrets import load_runtime_secrets
from automail.db.pocketbase.client import (
    get_crm_connector,
    get_crm_connector_by_key,
    get_crm_cursor,
    get_crm_webhook_event,
    list_crm_connectors,
    list_syncable_crm_connectors,
    record_crm_sync_run,
    record_crm_webhook_event,
    record_external_sync_run,
    update_crm_webhook_event,
    upsert_crm_cursor,
    upsert_external_object,
    upsert_support_account,
    upsert_support_contact,
)


@dataclass(frozen=True)
class IncomingCrmObject:
    id: str
    object_type: str
    raw: dict[str, Any]
    cursor_value: str = ""


def _string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _path_value(value: Any, path: str) -> Any:
    current = value
    for part in path.replace("[", ".").replace("]", "").split("."):
        clean = part.strip()
        if not clean:
            continue
        if isinstance(current, dict):
            current = current.get(clean)
        elif isinstance(current, list) and clean.isdigit():
            index = int(clean)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return None
    return current


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _adapter_kind(config: dict[str, Any]) -> str:
    return (_string(config.get("adapter") or config.get("mode") or config.get("source")) or "buffer").lower()


def _provider(connector: dict[str, Any]) -> str:
    config = _record(connector.get("config"))
    return (_string(connector.get("provider")) or _string(config.get("provider")) or "crm").lower()


def _processed_ids(cursor: dict[str, Any] | None) -> set[str]:
    metadata = cursor.get("metadata") if cursor else {}
    if not isinstance(metadata, dict):
        return set()
    ids = metadata.get("processedIds")
    if not isinstance(ids, list):
        return set()
    return {_string(item) for item in ids if _string(item)}


def _first_string(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _string(data.get(key))
        if value:
            return value
    for nested_key in ("account", "customer", "company", "contact", "data", "properties"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            value = _first_string(nested, keys)
            if value:
                return value
    return ""


def _domain_from_email(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def _external_id(raw: dict[str, Any]) -> str:
    return _first_string(
        raw,
        (
            "externalId",
            "external_id",
            "id",
            "accountId",
            "account_id",
            "customerId",
            "customer_id",
            "companyId",
            "company_id",
            "objectId",
            "object_id",
            "contactId",
            "contact_id",
            "personId",
            "person_id",
            "userId",
            "user_id",
        ),
    )


def _direct_string(raw: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _string(raw.get(key))
        if value:
            return value
    return ""


def _object_external_id(raw: dict[str, Any], object_type: str) -> str:
    if object_type == "contact":
        return (
            _direct_string(raw, ("contactId", "contact_id", "personId", "person_id", "userId", "user_id"))
            or _direct_string(raw, ("objectId", "object_id"))
            or _direct_string(raw, ("externalId", "external_id", "id"))
        )
    return (
        _direct_string(
            raw,
            (
                "accountId",
                "account_id",
                "customerId",
                "customer_id",
                "companyId",
                "company_id",
                "organisationId",
                "organizationId",
                "objectId",
                "object_id",
            ),
        )
        or _direct_string(raw, ("externalId", "external_id", "id"))
    )


def _external_url(raw: dict[str, Any]) -> str:
    return _first_string(
        raw,
        (
            "externalUrl",
            "external_url",
            "url",
            "accountUrl",
            "account_url",
            "customerUrl",
            "customer_url",
            "contactUrl",
            "contact_url",
            "profileUrl",
            "profile_url",
        ),
    )


def _display_name(raw: dict[str, Any]) -> str:
    return _first_string(
        raw,
        (
            "displayName",
            "display_name",
            "name",
            "accountName",
            "account_name",
            "companyName",
            "company_name",
            "customerName",
            "customer_name",
            "contactName",
            "contact_name",
            "fullName",
            "full_name",
            "email",
        ),
    )


def _normalize_type(value: str) -> str:
    clean = value.strip().lower()
    if clean in {"company", "customer", "organization", "organisation"}:
        return "account"
    if clean in {"person", "user", "lead"}:
        return "contact"
    return clean


def _record_to_object(raw: dict[str, Any], default_type: str) -> IncomingCrmObject | None:
    object_type = _normalize_type(
        _string(raw.get("objectType") or raw.get("object_type") or raw.get("type") or default_type)
    )
    if object_type not in {"account", "contact"}:
        return None
    external_id = _object_external_id(raw, object_type)
    if not external_id:
        return None
    return IncomingCrmObject(
        id=f"{object_type}:{external_id}",
        object_type=object_type,
        raw=raw,
        cursor_value=_string(raw.get("cursor") or raw.get("updatedAt") or raw.get("updated_at") or external_id),
    )


def _payload_events(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("events", "items", "records", "objects"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    for key in ("object", "record", "data", "payload", "properties"):
        value = event.get(key)
        if isinstance(value, dict):
            return {**event, **value}
    return event


def _event_type(event: dict[str, Any]) -> str:
    return _string(event.get("eventType") or event.get("event_type") or event.get("type") or event.get("action"))


def _event_id(event: dict[str, Any], item: IncomingCrmObject | None, index: int) -> str:
    explicit = _string(event.get("eventId") or event.get("event_id") or event.get("id") or event.get("eventId"))
    if explicit:
        return explicit
    event_type = _event_type(event) or "upsert"
    if item:
        return f"{event_type}:{item.id}"
    return f"{event_type}:unknown:{index}"


def _buffer_objects(
    config: dict[str, Any],
    *,
    cursor: dict[str, Any] | None,
    limit: int,
) -> tuple[list[IncomingCrmObject], int]:
    buckets: list[tuple[str, list[Any]]] = [
        ("", _list(config.get("records"))),
        ("", _list(config.get("objects"))),
        ("", _list(config.get("crmObjects") or config.get("crm_objects"))),
        ("account", _list(config.get("accounts"))),
        ("contact", _list(config.get("contacts"))),
    ]
    processed = _processed_ids(cursor)
    objects: list[IncomingCrmObject] = []
    skipped = 0
    for default_type, records in buckets:
        for raw in records:
            if not isinstance(raw, dict):
                skipped += 1
                continue
            item = _record_to_object(raw, default_type or "account")
            if not item:
                skipped += 1
                continue
            if item.id in processed:
                skipped += 1
                continue
            objects.append(item)
            if len(objects) >= limit:
                return objects, skipped
    return objects, skipped


def _secret_value(env_name: str, secrets: dict[str, str] | None) -> str:
    clean_name = env_name.strip()
    if not clean_name:
        return ""
    if secrets is not None:
        secret_value = str(secrets.get(clean_name) or "").strip()
        if secret_value:
            return secret_value
    return os.getenv(clean_name, "").strip()


def _http_endpoint_url(config: dict[str, Any]) -> str:
    url = _string(
        config.get("endpointUrl")
        or config.get("endpoint_url")
        or config.get("url")
        or config.get("recordsUrl")
        or config.get("records_url")
    )
    if not url:
        raise ValueError("HTTP CRM endpoint URL is not configured")
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    allow_insecure = bool(config.get("allowInsecureHttp") or config.get("allow_insecure_http"))
    if parsed.scheme != "https" and not allow_insecure and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("HTTP CRM endpoint URL must use https")
    return url


def _http_method(config: dict[str, Any]) -> str:
    method = _string(config.get("method") or config.get("httpMethod") or config.get("http_method")) or "GET"
    return method.upper()


def _http_token_env(config: dict[str, Any]) -> str:
    return _string(config.get("tokenEnv") or config.get("token_env") or config.get("apiKeyEnv") or config.get("api_key_env"))


def _http_token(config: dict[str, Any], secrets: dict[str, str] | None) -> str:
    direct = _string(config.get("token") or config.get("apiKey") or config.get("api_key"))
    if direct:
        return direct
    return _secret_value(_http_token_env(config), secrets)


def _http_secret_template(value: str, secrets: dict[str, str] | None) -> str:
    clean = value.strip()
    if (clean.startswith("{") and clean.endswith("}")) or (clean.startswith("${") and clean.endswith("}")):
        env_name = clean[2:-1] if clean.startswith("${") else clean[1:-1]
        return _secret_value(env_name, secrets)
    return value


def _http_headers(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in _record(config.get("headers")).items():
        clean_key = _string(key)
        clean_value = _http_secret_template(_string(value), secrets)
        if clean_key and clean_value:
            headers[clean_key] = clean_value
    token = _http_token(config, secrets)
    if token and "Authorization" not in headers:
        auth_scheme = _string(config.get("authScheme") or config.get("auth_scheme")) or "Bearer"
        headers["Authorization"] = f"{auth_scheme} {token}" if auth_scheme.lower() != "none" else token
    api_key_header = _string(config.get("apiKeyHeader") or config.get("api_key_header"))
    if token and api_key_header:
        headers[api_key_header] = token
    return headers


def _http_params(config: dict[str, Any], *, cursor_value: str, limit: int) -> dict[str, str]:
    params: dict[str, str] = {}
    for key, value in _record(config.get("params") or config.get("query")).items():
        clean_key = _string(key)
        clean_value = _string(value)
        if clean_key and clean_value:
            params[clean_key] = clean_value
    cursor_param = _string(config.get("cursorParam") or config.get("cursor_param")) or "cursor"
    limit_param = _string(config.get("limitParam") or config.get("limit_param")) or "limit"
    if cursor_param and cursor_value:
        params[cursor_param] = cursor_value
    if limit_param:
        params[limit_param] = str(max(1, min(limit, 100)))
    return params


def _http_json_body(config: dict[str, Any], *, cursor_value: str, limit: int) -> dict[str, Any]:
    body = dict(_record(config.get("body") or config.get("json")))
    cursor_field = _string(config.get("cursorField") or config.get("cursor_field")) or "cursor"
    limit_field = _string(config.get("limitField") or config.get("limit_field")) or "limit"
    if cursor_field and cursor_value:
        body[cursor_field] = cursor_value
    if limit_field:
        body[limit_field] = max(1, min(limit, 100))
    return body


def _http_records(data: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    records_path = _string(config.get("recordsPath") or config.get("records_path") or config.get("itemsPath") or config.get("items_path"))
    records = _path_value(data, records_path) if records_path else None
    if isinstance(records, list):
        return [item for item in records if isinstance(item, dict)]
    if isinstance(records, dict):
        return _payload_events(records)
    return _payload_events(data)


def _http_request_records(
    config: dict[str, Any],
    *,
    cursor_value: str,
    limit: int,
    secrets: dict[str, str] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = _http_endpoint_url(config)
    method = _http_method(config)
    headers = _http_headers(config, secrets)
    timeout = int(config.get("timeoutSeconds") or config.get("timeout_seconds") or 20)
    with httpx.Client(timeout=timeout) as client:
        if method == "GET":
            response = client.get(url, params=_http_params(config, cursor_value=cursor_value, limit=limit), headers=headers)
        else:
            response = client.request(
                method,
                url,
                params=_http_params(config, cursor_value=cursor_value, limit=limit) if config.get("query") else None,
                json=_http_json_body(config, cursor_value=cursor_value, limit=limit),
                headers=headers,
            )
        response.raise_for_status()
        data = response.json()
    return _http_records(data, config), data if isinstance(data, dict) else {}


def _http_objects(
    config: dict[str, Any],
    *,
    cursor: dict[str, Any] | None,
    limit: int,
    secrets: dict[str, str] | None,
) -> tuple[list[IncomingCrmObject], int]:
    cursor_value = _string(cursor.get("cursorValue")) if cursor else ""
    processed = _processed_ids(cursor)
    records, _data = _http_request_records(config, cursor_value=cursor_value, limit=limit, secrets=secrets)
    default_type = _normalize_type(_string(config.get("defaultObjectType") or config.get("default_object_type")) or "account")
    cursor_path = _string(config.get("cursorPath") or config.get("cursor_path") or config.get("recordCursorPath") or config.get("record_cursor_path"))
    objects: list[IncomingCrmObject] = []
    skipped = 0
    for record in records:
        raw = dict(record)
        if cursor_path:
            cursor_from_path = _string(_path_value(record, cursor_path))
            if cursor_from_path:
                raw["cursor"] = cursor_from_path
        item = _record_to_object(raw, default_type)
        if not item:
            skipped += 1
            continue
        if item.id in processed:
            skipped += 1
            continue
        objects.append(item)
        if len(objects) >= limit:
            break
    objects.sort(key=lambda item: item.cursor_value or item.id)
    return objects[:limit], skipped


def _hubspot_token(config: dict[str, Any], secrets: dict[str, str] | None) -> str:
    direct = _string(config.get("accessToken") or config.get("access_token") or config.get("token"))
    if direct:
        return direct
    return _secret_value(_hubspot_token_env(config), secrets)


def _hubspot_token_env(config: dict[str, Any]) -> str:
    return (
        _string(config.get("accessTokenEnv") or config.get("access_token_env"))
        or _string(config.get("privateAppTokenEnv") or config.get("private_app_token_env"))
        or _string(config.get("tokenEnv") or config.get("token_env"))
        or "HUBSPOT_PRIVATE_APP_TOKEN"
    )


def _hubspot_datetime_ms(value: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    if clean.isdigit():
        return clean
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return clean
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return str(int(parsed.timestamp() * 1000))


def _hubspot_timestamp(record: dict[str, Any]) -> str:
    properties = _record(record.get("properties"))
    return (
        _string(properties.get("hs_lastmodifieddate"))
        or _string(record.get("updatedAt") or record.get("updated_at"))
        or _string(properties.get("createdate"))
        or _string(record.get("createdAt") or record.get("created_at"))
        or _string(record.get("id"))
    )


def _hubspot_external_url(config: dict[str, Any], object_kind: str, object_id: str) -> str:
    portal_id = _string(config.get("portalId") or config.get("portal_id") or config.get("hubId") or config.get("hub_id"))
    if not portal_id or not object_id:
        return ""
    object_slug = "company" if object_kind == "companies" else "contact"
    return f"https://app.hubspot.com/contacts/{portal_id}/{object_slug}/{object_id}"


def _hubspot_name(*parts: str) -> str:
    return " ".join(part for part in (part.strip() for part in parts) if part).strip()


def _hubspot_raw(record: dict[str, Any], object_kind: str, config: dict[str, Any]) -> dict[str, Any]:
    properties = _record(record.get("properties"))
    object_id = _string(record.get("id") or properties.get("hs_object_id"))
    timestamp = _hubspot_timestamp(record)
    if object_kind == "companies":
        return {
            "objectType": "account",
            "id": object_id,
            "accountId": object_id,
            "companyId": object_id,
            "name": _string(properties.get("name")),
            "accountName": _string(properties.get("name")),
            "domain": _string(properties.get("domain") or properties.get("website")),
            "website": _string(properties.get("website")),
            "externalUrl": _hubspot_external_url(config, object_kind, object_id),
            "updatedAt": timestamp,
            "cursor": _hubspot_datetime_ms(timestamp),
            "properties": properties,
            "hubspot": record,
        }
    first_name = _string(properties.get("firstname"))
    last_name = _string(properties.get("lastname"))
    company_name = _string(properties.get("company"))
    associated_company_id = _string(properties.get("associatedcompanyid"))
    return {
        "objectType": "contact",
        "id": object_id,
        "contactId": object_id,
        "personId": object_id,
        "email": _string(properties.get("email")),
        "firstName": first_name,
        "lastName": last_name,
        "name": _hubspot_name(first_name, last_name) or _string(properties.get("email")),
        "contactName": _hubspot_name(first_name, last_name),
        "companyName": company_name,
        "accountName": company_name,
        "accountId": associated_company_id,
        "companyId": associated_company_id,
        "externalUrl": _hubspot_external_url(config, object_kind, object_id),
        "updatedAt": timestamp,
        "cursor": _hubspot_datetime_ms(timestamp),
        "properties": properties,
        "hubspot": record,
    }


def _hubspot_properties(object_kind: str, config: dict[str, Any]) -> list[str]:
    raw_key = "companyProperties" if object_kind == "companies" else "contactProperties"
    raw_properties = config.get(raw_key) or config.get(raw_key.replace("Properties", "_properties"))
    if isinstance(raw_properties, list):
        properties = [_string(item) for item in raw_properties if _string(item)]
    elif object_kind == "companies":
        properties = ["name", "domain", "website", "hs_lastmodifieddate", "createdate"]
    else:
        properties = [
            "email",
            "firstname",
            "lastname",
            "company",
            "associatedcompanyid",
            "hs_lastmodifieddate",
            "createdate",
        ]
    return list(dict.fromkeys(properties))


def _hubspot_search_payload(
    object_kind: str,
    *,
    cursor_value: str,
    page_after: str,
    limit: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "limit": max(1, min(limit, 100)),
        "properties": _hubspot_properties(object_kind, config),
        "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}],
    }
    cursor_ms = _hubspot_datetime_ms(cursor_value)
    if cursor_ms:
        payload["filterGroups"] = [
            {
                "filters": [
                    {
                        "propertyName": "hs_lastmodifieddate",
                        "operator": "GT",
                        "value": cursor_ms,
                    }
                ]
            }
        ]
    if page_after:
        payload["after"] = page_after
    return payload


def _hubspot_objects(
    config: dict[str, Any],
    *,
    cursor: dict[str, Any] | None,
    limit: int,
    secrets: dict[str, str] | None,
) -> tuple[list[IncomingCrmObject], int]:
    token = _hubspot_token(config, secrets)
    if not token:
        raise ValueError("HubSpot private app token is not configured")
    api_base = _string(config.get("apiBaseUrl") or config.get("api_base_url") or config.get("hubspotApiBaseUrl"))
    api_base = api_base.rstrip("/") or "https://api.hubapi.com"
    cursor_value = _string(cursor.get("cursorValue")) if cursor else ""
    processed = _processed_ids(cursor)
    objects: list[IncomingCrmObject] = []
    skipped = 0
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    object_kinds = ["companies", "contacts"]
    with httpx.Client(timeout=int(config.get("timeoutSeconds") or config.get("timeout_seconds") or 20)) as client:
        for object_kind in object_kinds:
            page_after = ""
            while len(objects) < limit:
                payload = _hubspot_search_payload(
                    object_kind,
                    cursor_value=cursor_value,
                    page_after=page_after,
                    limit=min(100, max(1, limit - len(objects))),
                    config=config,
                )
                response = client.post(
                    f"{api_base}/crm/v3/objects/{object_kind}/search",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                results = _list(data.get("results")) if isinstance(data, dict) else []
                if not results:
                    break
                for record in results:
                    if not isinstance(record, dict):
                        skipped += 1
                        continue
                    raw = _hubspot_raw(record, object_kind, config)
                    item = _record_to_object(raw, "account" if object_kind == "companies" else "contact")
                    if not item:
                        skipped += 1
                        continue
                    if item.id in processed:
                        skipped += 1
                        continue
                    objects.append(item)
                    if len(objects) >= limit:
                        break
                paging = data.get("paging") if isinstance(data, dict) else None
                next_page = _record(_record(paging).get("next"))
                page_after = _string(next_page.get("after"))
                if not page_after or len(objects) >= limit:
                    break
    objects.sort(key=lambda item: item.cursor_value or item.id)
    return objects[:limit], skipped


def _salesforce_token(config: dict[str, Any], secrets: dict[str, str] | None) -> str:
    direct = _string(config.get("accessToken") or config.get("access_token") or config.get("token"))
    if direct:
        return direct
    return _secret_value(_salesforce_token_env(config), secrets)


def _salesforce_token_env(config: dict[str, Any]) -> str:
    return (
        _string(config.get("accessTokenEnv") or config.get("access_token_env"))
        or _string(config.get("tokenEnv") or config.get("token_env"))
        or "SALESFORCE_ACCESS_TOKEN"
    )


def _salesforce_instance_url(config: dict[str, Any], secrets: dict[str, str] | None) -> str:
    direct = _string(config.get("instanceUrl") or config.get("instance_url") or config.get("baseUrl") or config.get("base_url"))
    if direct:
        return direct.rstrip("/")
    return _secret_value(_salesforce_instance_url_env(config), secrets).rstrip("/")


def _salesforce_instance_url_env(config: dict[str, Any]) -> str:
    return (
        _string(config.get("instanceUrlEnv") or config.get("instance_url_env"))
        or _string(config.get("baseUrlEnv") or config.get("base_url_env"))
        or "SALESFORCE_INSTANCE_URL"
    )


def _salesforce_api_version(config: dict[str, Any]) -> str:
    raw = _string(config.get("apiVersion") or config.get("api_version")) or "v61.0"
    return raw if raw.startswith("v") else f"v{raw}"


def _salesforce_datetime(value: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return clean
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _salesforce_domain_from_website(value: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    parsed = urlsplit(clean if "://" in clean else f"https://{clean}")
    return parsed.netloc.lower().removeprefix("www.")


def _salesforce_record_value(record: dict[str, Any], key: str) -> str:
    value: Any = record
    for part in key.split("."):
        if not isinstance(value, dict):
            return ""
        value = value.get(part)
    return _string(value)


def _salesforce_external_url(config: dict[str, Any], instance_url: str, object_name: str, object_id: str) -> str:
    app_base_url = _string(config.get("appBaseUrl") or config.get("app_base_url")).rstrip("/") or instance_url
    if not app_base_url or not object_id:
        return ""
    return f"{app_base_url}/lightning/r/{object_name}/{object_id}/view"


def _salesforce_timestamp(record: dict[str, Any]) -> str:
    return _string(record.get("SystemModstamp") or record.get("LastModifiedDate") or record.get("CreatedDate") or record.get("Id"))


def _salesforce_raw(record: dict[str, Any], object_name: str, config: dict[str, Any], instance_url: str) -> dict[str, Any]:
    object_id = _string(record.get("Id"))
    timestamp = _salesforce_timestamp(record)
    if object_name == "Account":
        website = _salesforce_record_value(record, "Website")
        domain = _salesforce_domain_from_website(website)
        return {
            "objectType": "account",
            "id": object_id,
            "accountId": object_id,
            "customerId": object_id,
            "name": _salesforce_record_value(record, "Name"),
            "accountName": _salesforce_record_value(record, "Name"),
            "domain": domain,
            "website": website,
            "industry": _salesforce_record_value(record, "Industry"),
            "externalUrl": _salesforce_external_url(config, instance_url, object_name, object_id),
            "updatedAt": timestamp,
            "cursor": _salesforce_datetime(timestamp),
            "fields": record,
            "salesforce": record,
        }
    account = _record(record.get("Account"))
    account_name = _salesforce_record_value(record, "Account.Name")
    account_website = _salesforce_record_value(record, "Account.Website")
    domain = _salesforce_domain_from_website(account_website)
    first_name = _salesforce_record_value(record, "FirstName")
    last_name = _salesforce_record_value(record, "LastName")
    return {
        "objectType": "contact",
        "id": object_id,
        "contactId": object_id,
        "personId": object_id,
        "email": _salesforce_record_value(record, "Email"),
        "firstName": first_name,
        "lastName": last_name,
        "name": _salesforce_record_value(record, "Name") or _hubspot_name(first_name, last_name),
        "contactName": _salesforce_record_value(record, "Name") or _hubspot_name(first_name, last_name),
        "companyName": account_name,
        "accountName": account_name,
        "accountId": _salesforce_record_value(record, "AccountId") or _string(account.get("Id")),
        "companyId": _salesforce_record_value(record, "AccountId") or _string(account.get("Id")),
        "domain": domain,
        "website": account_website,
        "externalUrl": _salesforce_external_url(config, instance_url, object_name, object_id),
        "updatedAt": timestamp,
        "cursor": _salesforce_datetime(timestamp),
        "fields": record,
        "salesforce": record,
    }


def _salesforce_fields(object_name: str, config: dict[str, Any]) -> list[str]:
    raw_key = "accountFields" if object_name == "Account" else "contactFields"
    raw_fields = config.get(raw_key) or config.get(raw_key.replace("Fields", "_fields"))
    if isinstance(raw_fields, list):
        fields = [_string(item) for item in raw_fields if _string(item)]
    elif object_name == "Account":
        fields = ["Id", "Name", "Website", "Industry", "LastModifiedDate", "SystemModstamp", "CreatedDate"]
    else:
        fields = [
            "Id",
            "Email",
            "FirstName",
            "LastName",
            "Name",
            "AccountId",
            "Account.Name",
            "Account.Website",
            "LastModifiedDate",
            "SystemModstamp",
            "CreatedDate",
        ]
    return list(dict.fromkeys(fields))


def _salesforce_query(object_name: str, *, cursor_value: str, limit: int, config: dict[str, Any]) -> str:
    fields = ", ".join(_salesforce_fields(object_name, config))
    cursor_datetime = _salesforce_datetime(cursor_value)
    where = f" WHERE SystemModstamp > {cursor_datetime}" if cursor_datetime else ""
    return f"SELECT {fields} FROM {object_name}{where} ORDER BY SystemModstamp ASC LIMIT {max(1, min(limit, 200))}"


def _salesforce_fetch_records(
    *,
    client: httpx.Client,
    instance_url: str,
    api_version: str,
    query: str,
    headers: dict[str, str],
    remaining: int,
) -> list[dict[str, Any]]:
    url = f"{instance_url}/services/data/{api_version}/query"
    params: dict[str, str] | None = {"q": query}
    records: list[dict[str, Any]] = []
    while url and len(records) < remaining:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            break
        for record in _list(data.get("records")):
            if isinstance(record, dict):
                records.append(record)
                if len(records) >= remaining:
                    break
        if data.get("done") is True or not data.get("nextRecordsUrl"):
            break
        url = f"{instance_url}{data['nextRecordsUrl']}"
        params = None
    return records


def _salesforce_objects(
    config: dict[str, Any],
    *,
    cursor: dict[str, Any] | None,
    limit: int,
    secrets: dict[str, str] | None,
) -> tuple[list[IncomingCrmObject], int]:
    token = _salesforce_token(config, secrets)
    if not token:
        raise ValueError("Salesforce access token is not configured")
    instance_url = _salesforce_instance_url(config, secrets)
    if not instance_url:
        raise ValueError("Salesforce instance URL is not configured")
    if urlsplit(instance_url).scheme != "https":
        raise ValueError("Salesforce instance URL must use https")
    api_version = _salesforce_api_version(config)
    cursor_value = _string(cursor.get("cursorValue")) if cursor else ""
    processed = _processed_ids(cursor)
    objects: list[IncomingCrmObject] = []
    skipped = 0
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx.Client(timeout=int(config.get("timeoutSeconds") or config.get("timeout_seconds") or 20)) as client:
        for object_name in ("Account", "Contact"):
            if len(objects) >= limit:
                break
            query = _salesforce_query(object_name, cursor_value=cursor_value, limit=limit - len(objects), config=config)
            for record in _salesforce_fetch_records(
                client=client,
                instance_url=instance_url,
                api_version=api_version,
                query=query,
                headers=headers,
                remaining=limit - len(objects),
            ):
                raw = _salesforce_raw(record, object_name, config, instance_url)
                item = _record_to_object(raw, "account" if object_name == "Account" else "contact")
                if not item:
                    skipped += 1
                    continue
                if item.id in processed:
                    skipped += 1
                    continue
                objects.append(item)
                if len(objects) >= limit:
                    break
    objects.sort(key=lambda item: item.cursor_value or item.id)
    return objects[:limit], skipped


def _load_objects(
    config: dict[str, Any],
    *,
    cursor: dict[str, Any] | None,
    limit: int,
    secrets: dict[str, str] | None = None,
) -> tuple[str, list[IncomingCrmObject], int]:
    adapter = _adapter_kind(config)
    if adapter == "buffer":
        objects, skipped = _buffer_objects(config, cursor=cursor, limit=limit)
        return adapter, objects, skipped
    if adapter in {"hubspot", "hubspot_private_app"}:
        objects, skipped = _hubspot_objects(config, cursor=cursor, limit=limit, secrets=secrets)
        return "hubspot", objects, skipped
    if adapter in {"salesforce", "salesforce_rest"}:
        objects, skipped = _salesforce_objects(config, cursor=cursor, limit=limit, secrets=secrets)
        return "salesforce", objects, skipped
    if adapter in {"http", "https", "rest", "generic_http"}:
        objects, skipped = _http_objects(config, cursor=cursor, limit=limit, secrets=secrets)
        return "http", objects, skipped
    raise ValueError(f"CRM adapter '{adapter}' is not implemented")


def _check(status: str, key: str, label: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "detail": detail, **extra}


def _http_error_detail(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        try:
            data = response.json()
        except ValueError:
            data = response.text
        if isinstance(data, dict):
            for key in ("message", "error", "error_description", "detail"):
                value = data.get(key)
                if value:
                    return f"HTTP {response.status_code}: {value}"
        if isinstance(data, str) and data.strip():
            return f"HTTP {response.status_code}: {data.strip()[:240]}"
        return f"HTTP {response.status_code}: {response.reason_phrase}"
    return str(exc)


def _env_check(env_name: str, value: str, *, required: bool = True) -> dict[str, Any]:
    status = "done" if value else "missing" if required else "manual"
    return {
        "name": env_name,
        "required": required,
        "configured": bool(value),
        "status": status,
    }


def _validate_hubspot(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    token = _hubspot_token(config, secrets)
    token_env = _hubspot_token_env(config)
    checks = [
        _check("done" if token else "missing", "token", "Private app token", token_env if token else f"{token_env} is not configured")
    ]
    env_vars = [_env_check(token_env, token)]
    if not token:
        return {
            "ready": False,
            "status": "missing",
            "checks": checks,
            "envVars": env_vars,
            "sample": {},
            "error": f"{token_env} is not configured",
        }
    api_base = _string(config.get("apiBaseUrl") or config.get("api_base_url") or config.get("hubspotApiBaseUrl"))
    api_base = api_base.rstrip("/") or "https://api.hubapi.com"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    sample: dict[str, int] = {}
    try:
        with httpx.Client(timeout=int(config.get("timeoutSeconds") or config.get("timeout_seconds") or 20)) as client:
            for object_kind, label in (("companies", "Companies"), ("contacts", "Contacts")):
                response = client.post(
                    f"{api_base}/crm/v3/objects/{object_kind}/search",
                    json={"limit": 1, "properties": _hubspot_properties(object_kind, config)},
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                sample[object_kind] = len(_list(data.get("results")) if isinstance(data, dict) else [])
                checks.append(_check("done", object_kind, label, "Reachable", count=sample[object_kind]))
    except Exception as exc:
        detail = _http_error_detail(exc)
        checks.append(_check("missing", "provider", "HubSpot API", detail))
        return {
            "ready": False,
            "status": "failed",
            "checks": checks,
            "envVars": env_vars,
            "sample": sample,
            "error": detail,
        }
    return {
        "ready": True,
        "status": "ready",
        "checks": checks,
        "envVars": env_vars,
        "sample": sample,
        "error": "",
    }


def _validate_salesforce(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    token = _salesforce_token(config, secrets)
    instance_url = _salesforce_instance_url(config, secrets)
    token_env = _salesforce_token_env(config)
    instance_url_env = _salesforce_instance_url_env(config)
    checks = [
        _check("done" if token else "missing", "token", "Access token", token_env if token else f"{token_env} is not configured"),
        _check(
            "done" if instance_url else "missing",
            "instance_url",
            "Instance URL",
            instance_url if instance_url else f"{instance_url_env} is not configured",
        ),
    ]
    env_vars = [
        _env_check(token_env, token),
        _env_check(instance_url_env, instance_url),
    ]
    if not token or not instance_url:
        missing = ", ".join(env["name"] for env in env_vars if env["required"] and not env["configured"])
        return {
            "ready": False,
            "status": "missing",
            "checks": checks,
            "envVars": env_vars,
            "sample": {},
            "error": f"Missing required Salesforce env vars: {missing}",
        }
    if urlsplit(instance_url).scheme != "https":
        detail = "Salesforce instance URL must use https"
        checks.append(_check("missing", "instance_url_scheme", "Instance URL scheme", detail))
        return {
            "ready": False,
            "status": "failed",
            "checks": checks,
            "envVars": env_vars,
            "sample": {},
            "error": detail,
        }
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    api_version = _salesforce_api_version(config)
    sample: dict[str, int] = {}
    try:
        with httpx.Client(timeout=int(config.get("timeoutSeconds") or config.get("timeout_seconds") or 20)) as client:
            for object_name, label in (("Account", "Accounts"), ("Contact", "Contacts")):
                query = _salesforce_query(object_name, cursor_value="", limit=1, config=config)
                records = _salesforce_fetch_records(
                    client=client,
                    instance_url=instance_url,
                    api_version=api_version,
                    query=query,
                    headers=headers,
                    remaining=1,
                )
                sample[object_name.lower()] = len(records)
                checks.append(_check("done", object_name.lower(), label, "Reachable", count=len(records)))
    except Exception as exc:
        detail = _http_error_detail(exc)
        checks.append(_check("missing", "provider", "Salesforce API", detail))
        return {
            "ready": False,
            "status": "failed",
            "checks": checks,
            "envVars": env_vars,
            "sample": sample,
            "error": detail,
        }
    return {
        "ready": True,
        "status": "ready",
        "checks": checks,
        "envVars": env_vars,
        "sample": sample,
        "error": "",
    }


def _validate_http(config: dict[str, Any], secrets: dict[str, str] | None) -> dict[str, Any]:
    token_env = _http_token_env(config)
    token = _http_token(config, secrets)
    env_vars = [_env_check(token_env, token)] if token_env else []
    checks: list[dict[str, Any]] = []
    if token_env:
        checks.append(_check("done" if token else "missing", "token", "API token", token_env if token else f"{token_env} is not configured"))
        if not token:
            return {
                "ready": False,
                "status": "missing",
                "checks": checks,
                "envVars": env_vars,
                "sample": {},
                "error": f"{token_env} is not configured",
            }
    try:
        endpoint_url = _http_endpoint_url(config)
    except ValueError as exc:
        detail = str(exc)
        checks.append(_check("missing", "endpoint", "Endpoint URL", detail))
        return {
            "ready": False,
            "status": "missing",
            "checks": checks,
            "envVars": env_vars,
            "sample": {},
            "error": detail,
        }
    checks.append(_check("done", "endpoint", "Endpoint URL", endpoint_url))
    try:
        records, _data = _http_request_records(config, cursor_value="", limit=1, secrets=secrets)
    except Exception as exc:
        detail = _http_error_detail(exc)
        checks.append(_check("missing", "provider", "HTTP CRM API", detail))
        return {
            "ready": False,
            "status": "failed",
            "checks": checks,
            "envVars": env_vars,
            "sample": {},
            "error": detail,
        }
    sample = {"records": len(records)}
    checks.append(_check("done", "records", "Records", "Reachable", count=len(records)))
    return {
        "ready": True,
        "status": "ready",
        "checks": checks,
        "envVars": env_vars,
        "sample": sample,
        "error": "",
    }


def validate_crm_connector(
    connector_id: str,
    *,
    tenant_id: str | None,
    project_id: str,
) -> dict[str, Any]:
    connector = get_crm_connector(connector_id, tenant_id=tenant_id, project_id=project_id)
    if not connector:
        raise ValueError("CRM connector not found")
    config = _record(connector.get("config"))
    adapter = _adapter_kind(config)
    provider = _provider(connector)
    if _string(connector.get("status")) not in {"", "active"}:
        validation = {
            "ready": False,
            "status": "skipped",
            "checks": [_check("manual", "status", "Connector status", "Connector is not active")],
            "envVars": [],
            "sample": {},
            "error": "CRM connector is not active",
        }
    elif adapter == "buffer":
        objects, skipped = _buffer_objects(config, cursor=None, limit=5)
        validation = {
            "ready": True,
            "status": "ready",
            "checks": [_check("done", "buffer", "Buffer records", f"{len(objects)} records ready", skipped=skipped)],
            "envVars": [],
            "sample": {"objects": len(objects), "skipped": skipped},
            "error": "",
        }
    elif adapter in {"hubspot", "hubspot_private_app"}:
        validation = _validate_hubspot(config, load_runtime_secrets(tenant_id, project_id) or {})
    elif adapter in {"salesforce", "salesforce_rest"}:
        validation = _validate_salesforce(config, load_runtime_secrets(tenant_id, project_id) or {})
    elif adapter in {"http", "https", "rest", "generic_http"}:
        adapter = "http"
        validation = _validate_http(config, load_runtime_secrets(tenant_id, project_id) or {})
    else:
        validation = {
            "ready": False,
            "status": "unsupported",
            "checks": [_check("missing", "adapter", "CRM adapter", f"CRM adapter '{adapter}' is not implemented")],
            "envVars": [],
            "sample": {},
            "error": f"CRM adapter '{adapter}' is not implemented",
        }
    return {
        "connectorId": connector_id,
        "connectorKey": connector.get("connectorKey", ""),
        "provider": provider,
        "adapter": adapter,
        **validation,
    }


def _public_raw(raw: dict[str, Any]) -> dict[str, Any]:
    public = dict(raw)
    public.pop("hubspot", None)
    public.pop("salesforce", None)
    return public


def _account_identity(raw: dict[str, Any]) -> dict[str, str]:
    name = _first_string(
        raw,
        (
            "accountName",
            "account_name",
            "companyName",
            "company_name",
            "customerName",
            "customer_name",
            "organization",
            "organisation",
            "name",
            "displayName",
            "display_name",
        ),
    )
    domain = _first_string(raw, ("domain", "accountDomain", "account_domain", "companyDomain", "website"))
    return {
        "account_name": name or domain or _external_id(raw),
        "account_domain": domain,
        "contact_email": "",
        "contact_name": "",
    }


def _contact_identity(raw: dict[str, Any]) -> dict[str, str]:
    contact_email = _first_string(raw, ("email", "contactEmail", "contact_email", "sender_email"))
    account_name = _first_string(
        raw,
        (
            "accountName",
            "account_name",
            "companyName",
            "company_name",
            "customerName",
            "customer_name",
            "organization",
            "organisation",
        ),
    )
    account_domain = (
        _first_string(raw, ("domain", "accountDomain", "account_domain", "companyDomain", "website"))
        or _domain_from_email(contact_email)
    )
    contact_name = _first_string(
        raw,
        ("contactName", "contact_name", "fullName", "full_name", "personName", "name", "displayName", "display_name"),
    )
    return {
        "account_name": account_name or account_domain or _external_id(raw),
        "account_domain": account_domain,
        "contact_email": contact_email,
        "contact_name": contact_name,
    }


def _sync_account_object(
    item: IncomingCrmObject,
    *,
    provider: str,
    tenant_id: str | None,
    project_id: str,
) -> dict[str, Any]:
    account = upsert_support_account(
        identity=_account_identity(item.raw),
        identity_data=item.raw,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    if not account:
        raise ValueError("CRM account record has no stable account key")
    external = upsert_external_object(
        account_id=account["id"],
        contact_id="",
        provider=provider,
        object_type="account",
        external_id=_object_external_id(item.raw, "account"),
        external_url=_external_url(item.raw),
        display_name=_display_name(item.raw),
        raw=_public_raw(item.raw),
        tenant_id=tenant_id,
        project_id=project_id,
    )
    synced = [external] if external else []
    for contact_raw in _list(item.raw.get("contacts")):
        if not isinstance(contact_raw, dict):
            continue
        nested = _record_to_object({**contact_raw, "account": item.raw}, "contact")
        if not nested:
            continue
        nested_result = _sync_contact_object(
            nested,
            provider=provider,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if nested_result.get("externalObject"):
            synced.append(nested_result["externalObject"])
    record_external_sync_run(
        account_id=account["id"],
        provider=provider,
        status="success",
        objects_seen=len(synced),
        result={"recordId": item.id, "objects": synced},
        tenant_id=tenant_id,
        project_id=project_id,
    )
    return {
        "id": item.id,
        "objectType": "account",
        "externalId": _object_external_id(item.raw, "account"),
        "accountId": account["id"],
        "contactId": "",
        "objectsSeen": len(synced),
        "externalObject": external,
    }


def _sync_contact_object(
    item: IncomingCrmObject,
    *,
    provider: str,
    tenant_id: str | None,
    project_id: str,
) -> dict[str, Any]:
    identity = _contact_identity(item.raw)
    account = upsert_support_account(
        identity=identity,
        identity_data=item.raw,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    if not account:
        raise ValueError("CRM contact record has no stable account key")
    contact = upsert_support_contact(
        identity=identity,
        identity_data=item.raw,
        account_id=account["id"],
        tenant_id=tenant_id,
        project_id=project_id,
    )
    if not contact:
        raise ValueError("CRM contact record has no stable contact key")
    external = upsert_external_object(
        account_id=account["id"],
        contact_id=contact["id"],
        provider=provider,
        object_type="contact",
        external_id=_object_external_id(item.raw, "contact"),
        external_url=_external_url(item.raw),
        display_name=_display_name(item.raw),
        raw=_public_raw(item.raw),
        tenant_id=tenant_id,
        project_id=project_id,
    )
    synced = [external] if external else []
    record_external_sync_run(
        account_id=account["id"],
        provider=provider,
        status="success",
        objects_seen=len(synced),
        result={"recordId": item.id, "objects": synced},
        tenant_id=tenant_id,
        project_id=project_id,
    )
    return {
        "id": item.id,
        "objectType": "contact",
        "externalId": _object_external_id(item.raw, "contact"),
        "accountId": account["id"],
        "contactId": contact["id"],
        "objectsSeen": len(synced),
        "externalObject": external,
    }


def _sync_object(
    item: IncomingCrmObject,
    *,
    provider: str,
    tenant_id: str | None,
    project_id: str,
) -> dict[str, Any]:
    if item.object_type == "contact":
        return _sync_contact_object(item, provider=provider, tenant_id=tenant_id, project_id=project_id)
    return _sync_account_object(item, provider=provider, tenant_id=tenant_id, project_id=project_id)


def _record_sync_run(
    *,
    tenant_id: str | None,
    project_id: str,
    connector_id: str,
    source: str,
    result: dict[str, Any],
    started_at: str,
) -> None:
    try:
        record_crm_sync_run(
            tenant_id=tenant_id,
            project_id=project_id,
            connector_id=connector_id,
            source=source,
            result=result,
            started_at=started_at,
            completed_at=_now_iso(),
        )
    except Exception:
        pass


def ingest_crm_webhook(
    connector_key: str,
    *,
    payload: Any,
    tenant_id: str | None = None,
    project_id: str | None = None,
    source: str = "webhook",
) -> dict[str, Any]:
    connector = get_crm_connector_by_key(connector_key, tenant_id=tenant_id, project_id=project_id)
    if not connector:
        raise ValueError("CRM connector not found")
    connector_id = _string(connector.get("id"))
    connector_project_id = _string(connector.get("projectId") or project_id)
    if not connector_project_id:
        raise ValueError("CRM connector has no project")
    connector_tenant_id = _string(connector.get("tenantId")) or tenant_id
    provider = _provider(connector)
    started_at = _now_iso()
    processed = 0
    failed = 0
    skipped = 0
    objects_seen = 0
    items: list[dict[str, Any]] = []
    events = _payload_events(payload)
    if not events:
        result = {
            "connectorId": connector_id,
            "connectorKey": connector.get("connectorKey", connector_key),
            "provider": provider,
            "status": "idle",
            "processed": 0,
            "failed": 0,
            "skipped": 0,
            "objectsSeen": 0,
            "items": [],
            "error": "",
        }
        _record_sync_run(
            tenant_id=connector_tenant_id,
            project_id=connector_project_id,
            connector_id=connector_id,
            source=source,
            result=result,
            started_at=started_at,
        )
        return result

    for index, event in enumerate(events):
        raw = _event_data(event)
        item = _record_to_object(raw, _normalize_type(_string(event.get("objectType") or event.get("object_type")) or "account"))
        event_type = _event_type(event) or "upsert"
        event_id = _event_id(event, item, index)
        object_type = item.object_type if item else _normalize_type(_string(event.get("objectType") or event.get("object_type")))
        external_id = _object_external_id(raw, object_type or "account") if raw else ""
        existing = get_crm_webhook_event(
            connector_id,
            event_id,
            tenant_id=connector_tenant_id,
            project_id=connector_project_id,
        )
        if existing and existing.get("status") == "processed":
            skipped += 1
            items.append(
                {
                    "id": event_id,
                    "eventId": event_id,
                    "eventType": event_type,
                    "objectType": object_type,
                    "externalId": external_id,
                    "status": "skipped",
                    "error": "Event already processed",
                }
            )
            continue
        if existing:
            webhook_event = existing
        else:
            webhook_event = record_crm_webhook_event(
                tenant_id=connector_tenant_id,
                project_id=connector_project_id,
                connector_id=connector_id,
                provider=provider,
                event_id=event_id,
                event_type=event_type,
                object_type=object_type,
                external_id=external_id,
                status="received",
                payload=event,
                received_at=started_at,
            )
        if not item:
            failed += 1
            error = "Webhook event has no supported CRM object"
            update_crm_webhook_event(
                webhook_event["id"],
                tenant_id=connector_tenant_id,
                project_id=connector_project_id,
                status="failed",
                error=error,
            )
            items.append(
                {
                    "id": event_id,
                    "eventId": event_id,
                    "eventType": event_type,
                    "objectType": object_type,
                    "externalId": external_id,
                    "status": "failed",
                    "error": error,
                }
            )
            continue
        try:
            synced = _sync_object(
                item,
                provider=provider,
                tenant_id=connector_tenant_id,
                project_id=connector_project_id,
            )
            processed += 1
            objects_seen += int(synced.get("objectsSeen") or 0)
            update_crm_webhook_event(
                webhook_event["id"],
                tenant_id=connector_tenant_id,
                project_id=connector_project_id,
                status="processed",
                result=synced,
            )
            items.append(
                {
                    "eventId": event_id,
                    "eventType": event_type,
                    "status": "processed",
                    **synced,
                }
            )
        except Exception as exc:
            failed += 1
            error = str(exc)
            update_crm_webhook_event(
                webhook_event["id"],
                tenant_id=connector_tenant_id,
                project_id=connector_project_id,
                status="failed",
                error=error,
            )
            items.append(
                {
                    "id": event_id,
                    "eventId": event_id,
                    "eventType": event_type,
                    "objectType": item.object_type,
                    "externalId": _object_external_id(item.raw, item.object_type),
                    "status": "failed",
                    "error": error,
                }
            )

    status = "failed" if failed and not processed else "partial" if failed else "success"
    if skipped and not processed and not failed:
        status = "skipped"
    result = {
        "connectorId": connector_id,
        "connectorKey": connector.get("connectorKey", connector_key),
        "provider": provider,
        "status": status,
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "objectsSeen": objects_seen,
        "items": items,
        "error": next((item.get("error", "") for item in items if item.get("status") == "failed"), ""),
    }
    _record_sync_run(
        tenant_id=connector_tenant_id,
        project_id=connector_project_id,
        connector_id=connector_id,
        source=source,
        result=result,
        started_at=started_at,
    )
    return result


def sync_support_crm_connector(
    connector_id: str,
    *,
    tenant_id: str | None,
    project_id: str,
    limit: int = 25,
    source: str = "admin",
) -> dict[str, Any]:
    started_at = _now_iso()
    connector = get_crm_connector(connector_id, tenant_id=tenant_id, project_id=project_id)
    if not connector:
        raise ValueError("CRM connector not found")
    connector_key = _string(connector.get("connectorKey"))
    config = _record(connector.get("config"))
    cursor = get_crm_cursor(connector_id, tenant_id=tenant_id, project_id=project_id, cursor_key="poll")
    provider = _provider(connector)
    if _string(connector.get("status")) not in {"", "active"}:
        result = {
            "connectorId": connector_id,
            "connectorKey": connector_key,
            "provider": provider,
            "adapter": _adapter_kind(config),
            "status": "skipped",
            "processed": 0,
            "failed": 0,
            "skipped": 0,
            "objectsSeen": 0,
            "cursorValue": cursor.get("cursorValue", "") if cursor else "",
            "items": [],
            "error": "CRM connector is not active",
        }
        _record_sync_run(
            tenant_id=tenant_id,
            project_id=project_id,
            connector_id=connector_id,
            source=source,
            result=result,
            started_at=started_at,
        )
        return result

    adapter = _adapter_kind(config)
    processed_ids = _processed_ids(cursor)
    secrets = load_runtime_secrets(tenant_id, project_id) or {}
    items: list[dict[str, Any]] = []
    cursor_value = cursor.get("cursorValue", "") if cursor else ""
    skipped = 0
    error = ""
    try:
        adapter, objects, skipped = _load_objects(
            config,
            cursor=cursor,
            limit=max(1, min(limit, 100)),
            secrets=secrets,
        )
    except Exception as exc:
        error = str(exc)
        upsert_crm_cursor(
            connector_id,
            tenant_id=tenant_id,
            project_id=project_id,
            cursor_key="poll",
            cursor_value=_string(cursor_value),
            status="failed",
            last_error=error,
            metadata={"adapter": adapter, "processedIds": sorted(processed_ids)[-500:]},
        )
        result = {
            "connectorId": connector_id,
            "connectorKey": connector_key,
            "provider": provider,
            "adapter": adapter,
            "status": "failed",
            "processed": 0,
            "failed": 0,
            "skipped": skipped,
            "objectsSeen": 0,
            "cursorValue": _string(cursor_value),
            "items": [],
            "error": error,
        }
        _record_sync_run(
            tenant_id=tenant_id,
            project_id=project_id,
            connector_id=connector_id,
            source=source,
            result=result,
            started_at=started_at,
        )
        return result

    for item in objects:
        try:
            synced = _sync_object(item, provider=provider, tenant_id=tenant_id, project_id=project_id)
            processed_ids.add(item.id)
            cursor_value = item.cursor_value or item.id
            items.append({"status": "processed", **synced})
        except Exception as exc:
            items.append(
                {
                    "id": item.id,
                    "objectType": item.object_type,
                    "externalId": _object_external_id(item.raw, item.object_type),
                    "status": "failed",
                    "error": str(exc),
                }
            )

    failed = sum(1 for item in items if item["status"] == "failed")
    processed = sum(1 for item in items if item["status"] == "processed")
    objects_seen = sum(int(item.get("objectsSeen") or 0) for item in items)
    status = "failed" if failed and not processed else "partial" if failed else "success"
    if not items and not error:
        status = "idle"
    upsert_crm_cursor(
        connector_id,
        tenant_id=tenant_id,
        project_id=project_id,
        cursor_key="poll",
        cursor_value=_string(cursor_value),
        status=status,
        last_error=next((item.get("error", "") for item in items if item["status"] == "failed"), ""),
        metadata={"adapter": adapter, "processedIds": sorted(processed_ids)[-500:]},
    )
    result = {
        "connectorId": connector_id,
        "connectorKey": connector_key,
        "provider": provider,
        "adapter": adapter,
        "status": status,
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "objectsSeen": objects_seen,
        "cursorValue": _string(cursor_value),
        "items": items,
        "error": error,
    }
    _record_sync_run(
        tenant_id=tenant_id,
        project_id=project_id,
        connector_id=connector_id,
        source=source,
        result=result,
        started_at=started_at,
    )
    return result


def sync_support_crm_connectors(
    *,
    tenant_id: str | None,
    project_id: str,
    limit: int = 25,
    source: str = "admin",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for connector in list_crm_connectors(tenant_id=tenant_id, project_id=project_id, limit=200):
        results.append(
            sync_support_crm_connector(
                _string(connector.get("id")),
                tenant_id=tenant_id,
                project_id=project_id,
                limit=limit,
                source=source,
            )
        )
    return {
        "connectors": len(results),
        "processed": sum(result["processed"] for result in results),
        "failed": sum(result["failed"] for result in results),
        "skipped": sum(result["skipped"] for result in results),
        "objectsSeen": sum(result["objectsSeen"] for result in results),
        "items": results,
    }


def sync_support_crm_connectors_for_scope(
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int = 25,
    source: str = "scheduler",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for connector in list_syncable_crm_connectors(tenant_id=tenant_id, project_id=project_id, limit=500):
        connector_project_id = _string(connector.get("projectId") or project_id)
        if not connector_project_id:
            continue
        results.append(
            sync_support_crm_connector(
                _string(connector.get("id")),
                tenant_id=_string(connector.get("tenantId")) or tenant_id,
                project_id=connector_project_id,
                limit=limit,
                source=source,
            )
        )
    return {
        "connectors": len(results),
        "processed": sum(result["processed"] for result in results),
        "failed": sum(result["failed"] for result in results),
        "skipped": sum(result["skipped"] for result in results),
        "objectsSeen": sum(result["objectsSeen"] for result in results),
        "items": results,
    }
