"""CLI gate for PocketBase support schema readiness."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Sequence

from automail.db.pocketbase.bootstrap_app_schema import ensure_app_collections_schema
from automail.db.pocketbase.issues import support_schema_health

EXIT_READY = 0
EXIT_ERROR = 1
EXIT_BLOCKED = 2


@dataclass(slots=True)
class SchemaGateResult:
    ok: bool
    status: str
    blockers: list[str]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _bootstrap_payload(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    payload = getattr(value, "__dict__", None)
    return payload if isinstance(payload, dict) else {}


def evaluate_schema_health(health: dict[str, Any]) -> SchemaGateResult:
    """Evaluate support schema health into an exit decision."""
    status = str(health.get("status") or "unknown")
    blockers: list[str] = []
    missing_collections = [str(item) for item in _as_list(health.get("missingCollections")) if item]
    missing_fields = [str(item) for item in _as_list(health.get("missingFields")) if item]
    missing_migrations = [str(item) for item in _as_list(health.get("missingMigrationFiles")) if item]

    if not bool(health.get("ready")):
        if missing_collections:
            blockers.append(f"{len(missing_collections)} support collections missing")
        if missing_fields:
            blockers.append(f"{len(missing_fields)} support fields missing")
        if missing_migrations:
            blockers.append(f"{len(missing_migrations)} migration files missing")
        if not blockers:
            blockers.append(f"schema status is {status}")

    return SchemaGateResult(ok=not blockers, status=status, blockers=blockers)


def check_support_schema(*, bootstrap: bool = True) -> dict[str, Any]:
    """Optionally bootstrap support collections, then return schema health."""
    bootstrap_result: Any = None
    if bootstrap:
        bootstrap_result = ensure_app_collections_schema()
    health = support_schema_health()
    return {
        "bootstrap": _bootstrap_payload(bootstrap_result),
        "health": health,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gate deploys on PocketBase support schema readiness.")
    parser.add_argument(
        "--no-bootstrap",
        action="store_true",
        help="Only check schema health; do not run the app schema bootstrap first.",
    )
    parser.add_argument("--json", action="store_true", help="Print raw schema health JSON before the summary.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        payload = check_support_schema(bootstrap=not args.no_bootstrap)
    except Exception as exc:
        print(f"support schema gate: check failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))

    result = evaluate_schema_health(health)
    if result.ok:
        print(
            "support schema gate: ready "
            f"({health.get('presentCollections', 0)}/{health.get('requiredCollections', 0)} collections, "
            f"{health.get('presentFields', 0)}/{health.get('requiredFields', 0)} fields)"
        )
        return EXIT_READY

    print(f"support schema gate: blocked ({result.status})", file=sys.stderr)
    for blocker in result.blockers:
        print(f"- {blocker}", file=sys.stderr)
    return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
