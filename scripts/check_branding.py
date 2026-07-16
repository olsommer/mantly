#!/usr/bin/env python3
"""Verify canonical Mantly package, image, and persistence identifiers."""

from __future__ import annotations

import json
import pathlib
import re
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]

EXPECTED_PACKAGES = {
    "admin/package.json": ("@mantly/admin", "1.0.0"),
    "addin/package.json": ("@mantly/outlook-addin", "1.0.0"),
    "landing/package.json": ("@mantly/landing", "1.0.0"),
}

FORBIDDEN_TOKENS = {
    "isarai-email-agent": "legacy application image/package identifier",
    "isarai-pocketbase": "legacy PocketBase image identifier",
    "isarai_pb_data": "legacy PocketBase Compose volume key",
    "isarai_app_data": "legacy application Compose volume key",
    "isarai-test": "legacy test image identifier",
    'name = "backend"': "generic backend package name",
    'description = "Add your description here"': "placeholder backend description",
}

ALLOWED_LEGACY_PATHS = {
    pathlib.PurePosixPath("docs/operations/naming-migration.md"),
    pathlib.PurePosixPath("scripts/migrate-compose-volumes.sh"),
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


def _read_json(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {relative}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return value


def _iter_text_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    ignored_parts = {".git", ".venv", "node_modules", "dist", "coverage", "__pycache__"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or ignored_parts.intersection(path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        files.append(path)
    return files


def main() -> int:
    errors: list[str] = []

    backend = (ROOT / "backend/pyproject.toml").read_text(encoding="utf-8")
    if not re.search(r'^name = "mantly-backend"$', backend, flags=re.MULTILINE):
        errors.append("backend/pyproject.toml must use name = \"mantly-backend\"")
    if not re.search(
        r'^description = "Agentic email-first customer support runtime and API"$',
        backend,
        flags=re.MULTILINE,
    ):
        errors.append("backend/pyproject.toml must contain the canonical description")

    for relative, (expected_name, expected_version) in EXPECTED_PACKAGES.items():
        package = _read_json(relative)
        if package.get("name") != expected_name:
            errors.append(f"{relative}: expected name {expected_name!r}")
        if package.get("version") != expected_version:
            errors.append(f"{relative}: expected version {expected_version!r}")
        if package.get("private") is not True:
            errors.append(f"{relative}: private must be true")

        lock_relative = relative.replace("package.json", "package-lock.json")
        lock = _read_json(lock_relative)
        root_package = lock.get("packages", {}).get("") if isinstance(lock.get("packages"), dict) else None
        if lock.get("name") != expected_name or lock.get("version") != expected_version:
            errors.append(f"{lock_relative}: top-level name/version do not match package.json")
        if not isinstance(root_package, dict):
            errors.append(f"{lock_relative}: packages[''] is missing")
        elif root_package.get("name") != expected_name or root_package.get("version") != expected_version:
            errors.append(f"{lock_relative}: packages[''] name/version do not match package.json")

    for path in _iter_text_files():
        relative = pathlib.PurePosixPath(path.relative_to(ROOT).as_posix())
        if relative in ALLOWED_LEGACY_PATHS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for token, description in FORBIDDEN_TOKENS.items():
            if token in text:
                errors.append(f"{relative}: contains {description}: {token}")

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for expected in ("mantly_pb_data", "mantly_app_data"):
        if expected not in compose:
            errors.append(f"docker-compose.yml must contain canonical volume {expected}")

    result = {
        "schemaVersion": "1.0",
        "ok": not errors,
        "checkedPackages": sorted(EXPECTED_PACKAGES),
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
