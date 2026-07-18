#!/usr/bin/env python3
"""One-shot branch migration for canonical Mantly repository identifiers.

This file is deleted by the temporary pull-request workflow after it applies and
validates the migration. The permanent migration and validation tools remain.
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

PACKAGE_METADATA = {
    "admin": ("@mantly/admin", "1.0.0"),
    "addin": ("@mantly/outlook-addin", "1.0.0"),
    "landing": ("@mantly/landing", "1.0.0"),
}

LEGACY_REPLACEMENTS = {
    "isarai-email-agent": "mantly",
    "isarai-pocketbase": "mantly-pocketbase",
    "isarai_pb_data": "mantly_pb_data",
    "isarai_app_data": "mantly_app_data",
    "isarai-test": "mantly-test",
    "isarai-email-agent-uv-cache": "mantly-uv-cache",
}

SKIP_LEGACY_REPLACEMENT = {
    pathlib.PurePosixPath("docs/operations/naming-migration.md"),
    pathlib.PurePosixPath("scripts/migrate-compose-volumes.sh"),
    pathlib.PurePosixPath("scripts/check_branding.py"),
    pathlib.PurePosixPath("scripts/apply_branding_cleanup.py"),
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


def write_json(path: pathlib.Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def update_package(directory: str, name: str, version: str) -> None:
    package_path = ROOT / directory / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["name"] = name
    package["version"] = version
    package["private"] = True
    write_json(package_path, package)

    lock_path = ROOT / directory / "package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["name"] = name
    lock["version"] = version
    packages = lock.setdefault("packages", {})
    root_package = packages.setdefault("", {})
    root_package["name"] = name
    root_package["version"] = version
    write_json(lock_path, lock)


def update_backend_metadata() -> None:
    pyproject_path = ROOT / "backend/pyproject.toml"
    text = pyproject_path.read_text(encoding="utf-8")
    text, name_count = re.subn(
        r'^name = "backend"$',
        'name = "mantly-backend"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    text, version_count = re.subn(
        r'^version = "0\.1\.0"$',
        'version = "1.0.0"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    text, description_count = re.subn(
        r'^description = "Add your description here"$',
        'description = "Agentic email-first customer support runtime and API"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if name_count != 1 or version_count != 1 or description_count != 1:
        raise RuntimeError("backend/pyproject.toml did not match the expected legacy metadata")
    pyproject_path.write_text(text, encoding="utf-8")

    lock_path = ROOT / "backend/uv.lock"
    lock = lock_path.read_text(encoding="utf-8")
    lock, count = re.subn(
        r'(?m)^name = "backend"$\nversion = "0\.1\.0"$',
        'name = "mantly-backend"\nversion = "1.0.0"',
        lock,
        count=1,
    )
    if count != 1:
        raise RuntimeError("backend/uv.lock root package metadata did not match")
    lock_path.write_text(lock, encoding="utf-8")


def replace_legacy_identifiers() -> None:
    ignored_parts = {".git", ".venv", "node_modules", "dist", "coverage", "__pycache__"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or ignored_parts.intersection(path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relative = pathlib.PurePosixPath(path.relative_to(ROOT).as_posix())
        if relative in SKIP_LEGACY_REPLACEMENT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = text
        for legacy, canonical in LEGACY_REPLACEMENTS.items():
            updated = updated.replace(legacy, canonical)
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def fix_capacity_tool() -> None:
    script_path = ROOT / "scripts/load_test.py"
    script = script_path.read_text(encoding="utf-8")
    if "\nimport sys\n" not in script:
        script = script.replace("import statistics\n", "import statistics\nimport sys\n", 1)
        script_path.write_text(script, encoding="utf-8")

    test_path = ROOT / "backend/tests/test_load_test_tool.py"
    test = test_path.read_text(encoding="utf-8")
    if "\nimport sys\n" not in test:
        test = test.replace("import json\n", "import json\nimport sys\n", 1)
    marker = "    module = importlib.util.module_from_spec(spec)\n"
    insertion = marker + "    sys.modules[spec.name] = module\n"
    if insertion not in test:
        if marker not in test:
            raise RuntimeError("load-test import fixture did not match expected content")
        test = test.replace(marker, insertion, 1)
    test_path.write_text(test, encoding="utf-8")


def install_branding_gates() -> None:
    workflow_path = ROOT / ".github/workflows/test.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    marker = "          python -m json.tool docs/pilot-metrics-schema.json >/dev/null\n"
    command = marker + "          python3 scripts/check_branding.py\n"
    if "python3 scripts/check_branding.py" not in workflow:
        if marker not in workflow:
            raise RuntimeError("test workflow repository-contract marker not found")
        workflow = workflow.replace(marker, command, 1)
        workflow_path.write_text(workflow, encoding="utf-8")

    quality_path = ROOT / "scripts/check-quality.sh"
    quality = quality_path.read_text(encoding="utf-8")
    marker = 'run "Pilot metric schema" python -m json.tool "$ROOT/docs/pilot-metrics-schema.json"\n'
    command = marker + 'run "Canonical branding contract" python3 "$ROOT/scripts/check_branding.py"\n'
    if "Canonical branding contract" not in quality:
        if marker not in quality:
            raise RuntimeError("local quality pilot-schema marker not found")
        quality = quality.replace(marker, command, 1)
        quality_path.write_text(quality, encoding="utf-8")


def main() -> int:
    update_backend_metadata()
    for directory, (name, version) in PACKAGE_METADATA.items():
        update_package(directory, name, version)
    replace_legacy_identifiers()
    fix_capacity_tool()
    install_branding_gates()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
