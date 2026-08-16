#!/usr/bin/env python3
"""Verify a restored Mantly deployment without copying customer content.

The verifier fails closed unless service URLs, PocketBase superuser credentials,
and representative restore expectations are provided. It prints a privacy-
minimized JSON result and never prints the password, token, or restored content.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable

DEFAULT_COLLECTIONS = (
    "tenants",
    "users",
    "projects",
    "project_intents",
    "knowledge_articles",
    "support_issues",
    "support_messages",
    "support_internal_notes",
    "support_outbound_messages",
    "support_action_executions",
    "support_ai_runs",
)
REQUIRED_EVIDENCE_CHECKS = {
    "tenant_project",
    "ticket_timeline",
    "outbound_reply",
    "runbook_knowledge",
    "attachment",
    "audit_history",
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    duration_ms: int


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 10.0,
) -> tuple[int, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = token

    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            parsed: Any = None
            if raw:
                parsed = json.loads(raw.decode("utf-8"))
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        detail: Any = None
        if raw:
            try:
                detail = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                detail = {"error": "non-json HTTP error response"}
        return exc.code, detail


def timed_check(name: str, fn: Callable[[], object]) -> Check:
    started = time.monotonic()
    try:
        detail = fn()
        return Check(name=name, ok=True, detail=str(detail), duration_ms=int((time.monotonic() - started) * 1000))
    except Exception as exc:  # noqa: BLE001 - verifier must report every failed boundary
        return Check(
            name=name,
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )


def require_success(url: str, label: str) -> str:
    status, payload = request_json(url)
    if status < 200 or status >= 300:
        raise RuntimeError(f"{label} returned HTTP {status}")
    if isinstance(payload, dict):
        safe_keys = sorted(str(key) for key in payload)
        return f"HTTP {status}; JSON keys={safe_keys}"
    return f"HTTP {status}"


def authenticate(pb_url: str, email: str, password: str) -> str:
    status, payload = request_json(
        f"{pb_url.rstrip('/')}/api/collections/_superusers/auth-with-password",
        method="POST",
        payload={"identity": email, "password": password},
    )
    if status < 200 or status >= 300 or not isinstance(payload, dict):
        raise RuntimeError(f"PocketBase superuser authentication returned HTTP {status}")
    token = payload.get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("PocketBase authentication response did not contain a token")
    return token


def collection_detail(pb_url: str, collection: str, token: str, minimum: int) -> str:
    encoded = urllib.parse.quote(collection, safe="")
    status, payload = request_json(
        f"{pb_url.rstrip('/')}/api/collections/{encoded}/records?page=1&perPage=1&skipTotal=0",
        token=token,
    )
    if status < 200 or status >= 300:
        raise RuntimeError(f"collection {collection} returned HTTP {status}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"collection {collection} returned a non-object response")
    total = payload.get("totalItems")
    if not isinstance(total, int):
        raise RuntimeError(f"collection {collection} did not return totalItems")
    if total < minimum:
        raise RuntimeError(f"collection {collection} has {total} records; expected at least {minimum}")
    return f"readable; totalItems={total}; minimum={minimum}"


def record_detail(
    pb_url: str,
    collection: str,
    record_id: str,
    required_fields: list[str],
    token: str,
) -> str:
    encoded_collection = urllib.parse.quote(collection, safe="")
    encoded_id = urllib.parse.quote(record_id, safe="")
    status, payload = request_json(
        f"{pb_url.rstrip('/')}/api/collections/{encoded_collection}/records/{encoded_id}",
        token=token,
    )
    if status < 200 or status >= 300:
        raise RuntimeError(f"record check returned HTTP {status}")
    if not isinstance(payload, dict):
        raise RuntimeError("record check returned a non-object response")
    missing = [field for field in required_fields if payload.get(field) in (None, "", [], {})]
    if missing:
        raise RuntimeError(f"required fields are empty: {', '.join(sorted(missing))}")
    return f"record present; requiredFields={sorted(required_fields)}"


def load_expectations(path: str) -> tuple[dict[str, int], list[dict[str, Any]]]:
    try:
        expectations = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read restore expectations: {exc}") from exc
    if not isinstance(expectations, dict) or expectations.get("schemaVersion") != "1.0":
        raise ValueError("restore expectations schemaVersion must be 1.0")

    minimums = expectations.get("collectionMinimums")
    if not isinstance(minimums, dict):
        raise ValueError("restore expectations collectionMinimums must be an object")
    normalized_minimums: dict[str, int] = {}
    for collection in DEFAULT_COLLECTIONS:
        minimum = minimums.get(collection)
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
            raise ValueError(f"collectionMinimums.{collection} must be a positive integer")
        normalized_minimums[collection] = minimum

    record_checks = expectations.get("recordChecks")
    if not isinstance(record_checks, list):
        raise ValueError("restore expectations recordChecks must be a list")
    observed_names: set[str] = set()
    normalized_checks: list[dict[str, Any]] = []
    for index, check in enumerate(record_checks):
        if not isinstance(check, dict):
            raise ValueError(f"recordChecks[{index}] must be an object")
        name = check.get("name")
        collection = check.get("collection")
        record_id = check.get("id")
        required_fields = check.get("requiredFields")
        if name not in REQUIRED_EVIDENCE_CHECKS:
            raise ValueError(f"recordChecks[{index}].name is invalid")
        if name in observed_names:
            raise ValueError(f"duplicate record check: {name}")
        if not isinstance(collection, str) or not collection:
            raise ValueError(f"recordChecks[{index}].collection is required")
        if not isinstance(record_id, str) or not record_id:
            raise ValueError(f"recordChecks[{index}].id is required")
        if (
            not isinstance(required_fields, list)
            or not required_fields
            or any(not isinstance(field, str) or not field for field in required_fields)
        ):
            raise ValueError(f"recordChecks[{index}].requiredFields must contain field names")
        observed_names.add(name)
        normalized_checks.append(
            {
                "name": name,
                "collection": collection,
                "id": record_id,
                "requiredFields": required_fields,
            }
        )
    missing_checks = REQUIRED_EVIDENCE_CHECKS - observed_names
    if missing_checks:
        raise ValueError(f"restore expectations omit evidence checks: {', '.join(sorted(missing_checks))}")
    return normalized_minimums, normalized_checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("RESTORE_API_URL", ""), required=False)
    parser.add_argument("--pb-url", default=os.getenv("RESTORE_PB_URL", ""), required=False)
    parser.add_argument("--pb-admin-email", default=os.getenv("PB_ADMIN_EMAIL", ""), required=False)
    parser.add_argument("--pb-admin-password", default=os.getenv("PB_ADMIN_PASSWORD", ""), required=False)
    parser.add_argument(
        "--collections",
        default=os.getenv("RESTORE_REQUIRED_COLLECTIONS", ",".join(DEFAULT_COLLECTIONS)),
        help="Comma-separated PocketBase collections required after restore.",
    )
    parser.add_argument(
        "--expectations",
        default=os.getenv("RESTORE_EXPECTATIONS_FILE", ""),
        help="JSON expectations containing minimum counts and representative record checks.",
    )
    parser.add_argument("--output", default="", help="Optional JSON evidence file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks: list[Check] = []
    required_arguments = {
        "RESTORE_API_URL/--api-url": args.api_url,
        "RESTORE_PB_URL/--pb-url": args.pb_url,
        "PB_ADMIN_EMAIL/--pb-admin-email": args.pb_admin_email,
        "PB_ADMIN_PASSWORD/--pb-admin-password": args.pb_admin_password,
        "RESTORE_EXPECTATIONS_FILE/--expectations": args.expectations,
    }
    missing_arguments = [name for name, value in required_arguments.items() if not value]
    if missing_arguments:
        checks.append(
            Check(
                "verification_configuration",
                False,
                f"missing required inputs: {', '.join(missing_arguments)}",
                0,
            )
        )
        minimums: dict[str, int] = {}
        record_checks: list[dict[str, Any]] = []
    else:
        try:
            minimums, record_checks = load_expectations(args.expectations)
            checks.append(Check("verification_configuration", True, "complete expectations loaded", 0))
        except ValueError as exc:
            minimums = {}
            record_checks = []
            checks.append(Check("verification_configuration", False, str(exc), 0))

    if args.api_url:
        checks.append(
            timed_check(
                "fastapi_health",
                lambda: require_success(f"{args.api_url.rstrip('/')}/api/health", "FastAPI health"),
            )
        )
    else:
        checks.append(Check("fastapi_health", False, "RESTORE_API_URL not provided", 0))

    if args.pb_url:
        checks.append(
            timed_check(
                "pocketbase_health",
                lambda: require_success(f"{args.pb_url.rstrip('/')}/api/health", "PocketBase health"),
            )
        )
    else:
        checks.append(Check("pocketbase_health", False, "RESTORE_PB_URL not provided", 0))

    token = ""
    if args.pb_url and args.pb_admin_email and args.pb_admin_password:
        started = time.monotonic()
        try:
            token = authenticate(args.pb_url, args.pb_admin_email, args.pb_admin_password)
            checks.append(
                Check(
                    "pocketbase_superuser_auth",
                    True,
                    "authenticated; token redacted",
                    int((time.monotonic() - started) * 1000),
                )
            )
        except Exception as exc:  # noqa: BLE001 - verifier reports the failed boundary
            checks.append(
                Check(
                    "pocketbase_superuser_auth",
                    False,
                    f"{type(exc).__name__}: {exc}",
                    int((time.monotonic() - started) * 1000),
                )
            )
    else:
        checks.append(
            Check(
                "pocketbase_superuser_auth",
                False,
                "PocketBase URL or superuser credentials not provided",
                0,
            )
        )

    if token and minimums:
        collections = [value.strip() for value in args.collections.split(",") if value.strip()]
        if set(collections) != set(DEFAULT_COLLECTIONS):
            checks.append(
                Check(
                    "required_collections",
                    False,
                    "collection override must contain the complete recovery contract",
                    0,
                )
            )
        for collection in collections:
            checks.append(
                timed_check(
                    f"collection:{collection}",
                    lambda collection=collection: collection_detail(
                        args.pb_url,
                        collection,
                        token,
                        minimums.get(collection, 1),
                    ),
                )
            )
        for record_check in record_checks:
            checks.append(
                timed_check(
                    f"evidence:{record_check['name']}",
                    lambda record_check=record_check: record_detail(
                        args.pb_url,
                        record_check["collection"],
                        record_check["id"],
                        record_check["requiredFields"],
                        token,
                    ),
                )
            )

    report = {
        "schemaVersion": "1.0",
        "ok": all(check.ok for check in checks),
        "checks": [asdict(check) for check in checks],
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    sys.stdout.write(rendered)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
