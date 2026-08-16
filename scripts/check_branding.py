#!/usr/bin/env python3
"""Validate canonical Mantly metadata without changing repository files."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
from typing import Any

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
RELEASE_VERSION = "0.1.0"

EXPECTED_PACKAGES = {
    "admin/package.json": "@mantly/admin",
    "addin/package.json": "@mantly/outlook-addin",
    "landing/package.json": "@mantly/landing",
}

FORBIDDEN_TOKENS = {
    "isarai-email-agent": "legacy application image/package identifier",
    "isarai-pocketbase": "legacy PocketBase image identifier",
    "isarai_pb_data": "legacy PocketBase Compose volume key",
    "isarai_app_data": "legacy application Compose volume key",
    "isarai_dev_data": "legacy development Compose volume key",
    "isarai-test": "legacy test image identifier",
    "isarai-email-agent-uv-cache": "legacy cache identifier",
    'name = "backend"': "generic backend package name",
    'description = "Add your description here"': "placeholder backend description",
}

# These files must name the retired identifiers so operators can discover and
# migrate existing resources. The validator itself defines the forbidden set.
ALLOWED_LEGACY_PATHS = {
    pathlib.PurePosixPath("docs/operations/naming-migration.md"),
    pathlib.PurePosixPath("scripts/migrate-compose-volumes.sh"),
    pathlib.PurePosixPath("scripts/check_branding.py"),
}

REQUIRED_TEXT = {
    "docker-compose.yml": ("mantly_pb_data", "mantly_app_data"),
    "docker-compose.dev.yml": ("  mantly:", "mantly_dev_data"),
    "docker-compose.onprem.yml": ("image: mantly-api-onprem:latest",),
    "deploy/docker-compose.yml": (
        "${REGISTRY:-ghcr.io/isarlabs}/mantly-api:",
        "${REGISTRY:-ghcr.io/isarlabs}/mantly-pocketbase:",
    ),
    "scripts/release-onprem.sh": (
        'APP_IMAGE="$REGISTRY/mantly-api"',
        'PB_IMAGE="$REGISTRY/mantly-pocketbase"',
        'BUILDER_NAME="mantly-multiarch"',
    ),
    "scripts/package-customer.sh": (
        '"app": "$REGISTRY/mantly-api:$IMAGE_TAG"',
        '"pocketbase": "$REGISTRY/mantly-pocketbase:$IMAGE_TAG"',
    ),
}

TEXT_SUFFIXES = {
    "",
    ".caddy",
    ".conf",
    ".css",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".lock",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def _read_json(root: pathlib.Path, relative: str) -> dict[str, Any]:
    path = root / relative
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {relative}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return value


def _iter_text_files(root: pathlib.Path) -> list[pathlib.Path]:
    if (root / ".git").exists():
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z"],
                check=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError(f"cannot inventory tracked repository files: {exc}") from exc
        return [
            path
            for raw_path in result.stdout.split(b"\0")
            if raw_path
            and (path := root / os.fsdecode(raw_path)).is_file()
            and path.suffix.lower() in TEXT_SUFFIXES
        ]

    files: list[pathlib.Path] = []
    ignored_parts = {".git", ".venv", "node_modules", "dist", "coverage", "__pycache__"}
    for path in root.rglob("*"):
        if not path.is_file() or ignored_parts.intersection(path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        files.append(path)
    return files


def validate(root: pathlib.Path) -> list[str]:
    errors: list[str] = []

    try:
        backend = (root / "backend/pyproject.toml").read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read backend/pyproject.toml: {exc}")
    else:
        expected_backend_fields = {
            "name": "mantly-backend",
            "version": RELEASE_VERSION,
            "description": "Agentic email-first customer support runtime and API",
        }
        for field, expected in expected_backend_fields.items():
            if not re.search(
                rf'^{re.escape(field)} = "{re.escape(expected)}"$',
                backend,
                flags=re.MULTILINE,
            ):
                errors.append(f"backend/pyproject.toml: expected {field} = {expected!r}")

    try:
        lock = (root / "backend/uv.lock").read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read backend/uv.lock: {exc}")
    else:
        expected_lock_entry = (
            'name = "mantly-backend"\n'
            f'version = "{RELEASE_VERSION}"\n'
            'source = { virtual = "." }'
        )
        if expected_lock_entry not in lock:
            errors.append("backend/uv.lock: root package name/version do not match pyproject.toml")

    for relative, expected_name in EXPECTED_PACKAGES.items():
        try:
            package = _read_json(root, relative)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if package.get("name") != expected_name:
            errors.append(f"{relative}: expected name {expected_name!r}")
        if package.get("version") != RELEASE_VERSION:
            errors.append(f"{relative}: expected version {RELEASE_VERSION!r}")
        if package.get("private") is not True:
            errors.append(f"{relative}: private must be true")

        lock_relative = relative.replace("package.json", "package-lock.json")
        try:
            package_lock = _read_json(root, lock_relative)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        packages = package_lock.get("packages")
        root_package = packages.get("") if isinstance(packages, dict) else None
        if (
            package_lock.get("name") != expected_name
            or package_lock.get("version") != RELEASE_VERSION
        ):
            errors.append(f"{lock_relative}: top-level name/version do not match package.json")
        if not isinstance(root_package, dict):
            errors.append(f"{lock_relative}: packages[''] is missing")
        elif (
            root_package.get("name") != expected_name
            or root_package.get("version") != RELEASE_VERSION
        ):
            errors.append(f"{lock_relative}: packages[''] name/version do not match package.json")

    for relative, required_tokens in REQUIRED_TEXT.items():
        try:
            text = (root / relative).read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read {relative}: {exc}")
            continue
        for token in required_tokens:
            if token not in text:
                errors.append(f"{relative}: missing canonical identifier {token!r}")

    try:
        text_files = _iter_text_files(root)
    except ValueError as exc:
        errors.append(str(exc))
    else:
        for path in text_files:
            relative = pathlib.PurePosixPath(path.relative_to(root).as_posix())
            if relative in ALLOWED_LEGACY_PATHS:
                continue
            try:
                lowered = path.read_text(encoding="utf-8").lower()
            except UnicodeDecodeError:
                continue
            for token, description in FORBIDDEN_TOKENS.items():
                if token.lower() in lowered:
                    errors.append(f"{relative}: contains {description}: {token}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=REPOSITORY_ROOT,
        help="repository root to validate",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    errors = validate(root)
    result = {
        "schemaVersion": "1.0",
        "releaseVersion": RELEASE_VERSION,
        "root": str(root),
        "ok": not errors,
        "checkedPackages": sorted(EXPECTED_PACKAGES),
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
