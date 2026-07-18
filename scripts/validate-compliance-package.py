#!/usr/bin/env python3
"""Validate the repository's DACH compliance evidence package.

This is a structural and claim-discipline gate, not a legal compliance opinion.
It ensures the required evidence files exist and that the provider inventory is
complete enough to force deployment-specific review rather than silently
omitting a data recipient.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

REQUIRED_DOCUMENTS = (
    "docs/compliance/data-processing-overview.md",
    "docs/compliance/dpa-and-security-schedule-checklist.md",
    "docs/compliance/data-export-and-tenant-deletion.md",
    "docs/compliance/customer-security-privacy-evidence-index.md",
    "docs/compliance/lifecycle-exercise-template.md",
    "docs/security/data-retention.md",
    "docs/security/threat-model.md",
    "docs/security/incident-response.md",
    "docs/operations/backup-and-recovery.md",
)

REQUIRED_PROVIDER_KEYS = {
    "key",
    "enabled",
    "required",
    "legalEntity",
    "service",
    "role",
    "purpose",
    "dataCategories",
    "dataSubjects",
    "processingLocations",
    "supportAccessLocations",
    "retention",
    "trainingOrSecondaryUse",
    "transferMechanism",
    "contractReference",
    "securityReference",
    "deletionReference",
    "incidentNotificationReference",
    "customerAlternative",
    "owner",
    "legalReviewComplete",
}

REQUIRED_PROVIDER_TYPES = {
    "infrastructure-host",
    "managed-model-provider",
    "email-or-channel-provider",
    "smtp-transactional-email",
    "payment-provider",
    "observability-provider",
    "backup-storage-provider",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument(
        "--inventory",
        default="docs/compliance/subprocessors.example.json",
        help="Provider inventory relative to root",
    )
    parser.add_argument(
        "--allow-approved-template",
        action="store_true",
        help="Allow legalReviewComplete=true in the repository example. Normally forbidden.",
    )
    return parser.parse_args()


def require_nonempty_string(value: Any, field: str, provider: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"provider {provider}: {field} must be a non-empty string")


def require_string_list(value: Any, field: str, provider: str, errors: list[str], *, allow_empty: bool = False) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"provider {provider}: {field} must be a list of non-empty strings")
        return
    if not allow_empty and not value:
        errors.append(f"provider {provider}: {field} must not be empty")


def main() -> int:
    args = parse_args()
    root = pathlib.Path(args.root).resolve()
    errors: list[str] = []
    checked: list[str] = []

    for relative in REQUIRED_DOCUMENTS:
        path = root / relative
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing or empty required document: {relative}")
            continue
        checked.append(relative)

    inventory_path = root / args.inventory
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read provider inventory {args.inventory}: {exc}")
        inventory = {}

    if inventory:
        if inventory.get("schemaVersion") != "1.0":
            errors.append("provider inventory schemaVersion must be 1.0")
        if inventory.get("status") != "template-not-approved":
            errors.append("repository example inventory must remain status=template-not-approved")

        deployment = inventory.get("deployment")
        if not isinstance(deployment, dict):
            errors.append("provider inventory deployment must be an object")
        else:
            for field in ("name", "mode", "primaryProcessingRegion", "customer"):
                require_nonempty_string(deployment.get(field), f"deployment.{field}", "inventory", errors)
            reviewers = deployment.get("reviewedBy")
            if not isinstance(reviewers, list):
                errors.append("deployment.reviewedBy must be a list")

        providers = inventory.get("providers")
        if not isinstance(providers, list) or not providers:
            errors.append("provider inventory must contain a non-empty providers list")
            providers = []

        observed_keys: set[str] = set()
        for index, provider in enumerate(providers):
            if not isinstance(provider, dict):
                errors.append(f"provider at index {index} must be an object")
                continue
            key = provider.get("key")
            provider_name = key if isinstance(key, str) and key else f"index-{index}"
            missing = sorted(REQUIRED_PROVIDER_KEYS - provider.keys())
            if missing:
                errors.append(f"provider {provider_name}: missing fields {', '.join(missing)}")
            if isinstance(key, str):
                if key in observed_keys:
                    errors.append(f"duplicate provider key: {key}")
                observed_keys.add(key)
            for field in ("legalEntity", "service", "role", "retention", "trainingOrSecondaryUse", "transferMechanism", "customerAlternative", "owner"):
                require_nonempty_string(provider.get(field), field, provider_name, errors)
            for field in ("purpose", "dataCategories", "dataSubjects"):
                require_string_list(provider.get(field), field, provider_name, errors)
            for field in ("processingLocations", "supportAccessLocations"):
                require_string_list(provider.get(field), field, provider_name, errors, allow_empty=True)
            for field in ("enabled", "required", "legalReviewComplete"):
                if not isinstance(provider.get(field), bool):
                    errors.append(f"provider {provider_name}: {field} must be boolean")
            if provider.get("legalReviewComplete") is True and not args.allow_approved_template:
                errors.append(
                    f"provider {provider_name}: repository example must not claim completed legal review"
                )

        missing_types = sorted(REQUIRED_PROVIDER_TYPES - observed_keys)
        if missing_types:
            errors.append(f"provider inventory omits required categories: {', '.join(missing_types)}")

    forbidden_claims = (
        "fully gdpr compliant",
        "fully fadp compliant",
        "100% compliant",
        "zero risk",
        "guaranteed compliant",
    )
    for relative in REQUIRED_DOCUMENTS:
        path = root / relative
        if not path.is_file():
            continue
        normalized = path.read_text(encoding="utf-8").lower()
        for claim in forbidden_claims:
            if claim in normalized:
                errors.append(f"unsupported absolute compliance claim in {relative}: {claim!r}")

    report = {
        "schemaVersion": "1.0",
        "ok": not errors,
        "checkedDocuments": sorted(checked),
        "inventory": args.inventory,
        "errors": errors,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
