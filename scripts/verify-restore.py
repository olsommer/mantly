#!/usr/bin/env python3
"""Verify a restored Mantly deployment without copying customer content.

The verifier checks service health and, when PocketBase superuser credentials are
provided, authenticates and proves that required collections are readable. It
prints a JSON result suitable for restore-drill evidence and never prints the
provided password or authentication token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any

DEFAULT_COLLECTIONS = (
    "tenants",
    "users",
    "projects",
    "support_issues",
    "support_messages",
    "support_outbound_messages",
    "support_action_executions",
    "support_ai_runs",
)


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


def timed_check(name: str, fn: Any) -> Check:
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
        safe_keys = sorted(str(key) for key in payload.keys())
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


def collection_detail(pb_url: str, collection: str, token: str) -> str:
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
    return f"readable; totalItems={total if isinstance(total, int) else 'unknown'}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("RESTORE_API_URL", ""))
    parser.add_argument("--pb-url", default=os.getenv("RESTORE_PB_URL", ""))
    parser.add_argument("--pb-admin-email", default=os.getenv("PB_ADMIN_EMAIL", ""))
    parser.add_argument("--pb-admin-password", default=os.getenv("PB_ADMIN_PASSWORD", ""))
    parser.add_argument(
        "--collections",
        default=os.getenv("RESTORE_REQUIRED_COLLECTIONS", ",".join(DEFAULT_COLLECTIONS)),
        help="Comma-separated PocketBase collections required after restore.",
    )
    parser.add_argument("--output", default="", help="Optional JSON evidence file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks: list[Check] = []

    if args.api_url:
        checks.append(
            timed_check(
                "fastapi_health",
                lambda: require_success(f"{args.api_url.rstrip('/')}/api/health", "FastAPI health"),
            )
        )
    else:
        checks.append(Check("fastapi_health", True, "skipped: RESTORE_API_URL not provided", 0))

    if args.pb_url:
        checks.append(
            timed_check(
                "pocketbase_health",
                lambda: require_success(f"{args.pb_url.rstrip('/')}/api/health", "PocketBase health"),
            )
        )
    else:
        checks.append(Check("pocketbase_health", True, "skipped: RESTORE_PB_URL not provided", 0))

    token = ""
    if args.pb_url and args.pb_admin_email and args.pb_admin_password:
        auth_check = timed_check(
            "pocketbase_superuser_auth",
            lambda: authenticate(args.pb_url, args.pb_admin_email, args.pb_admin_password),
        )
        if auth_check.ok:
            # The detail returned by authenticate is a credential; never retain it.
            token = authenticate(args.pb_url, args.pb_admin_email, args.pb_admin_password)
            auth_check.detail = "authenticated; token redacted"
        checks.append(auth_check)
    elif args.pb_url:
        checks.append(
            Check(
                "pocketbase_superuser_auth",
                True,
                "skipped: PB_ADMIN_EMAIL/PB_ADMIN_PASSWORD not provided",
                0,
            )
        )

    if token:
        collections = [value.strip() for value in args.collections.split(",") if value.strip()]
        for collection in collections:
            checks.append(
                timed_check(
                    f"collection:{collection}",
                    lambda collection=collection: collection_detail(args.pb_url, collection, token),
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
