#!/usr/bin/env python3
"""Finalize the stacked licensing branch and repair permanent validators."""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

apply_script = ROOT / "scripts/apply_distribution_boundary.py"
if apply_script.exists():
    subprocess.run([sys.executable, str(apply_script)], cwd=ROOT, check=True)

validator = ROOT / "scripts/check_branding.py"
text = validator.read_text(encoding="utf-8")
needle = '''ALLOWED_LEGACY_PATHS = {
    pathlib.PurePosixPath("docs/operations/naming-migration.md"),
    pathlib.PurePosixPath("scripts/migrate-compose-volumes.sh"),
}'''
replacement = '''ALLOWED_LEGACY_PATHS = {
    pathlib.PurePosixPath("docs/operations/naming-migration.md"),
    pathlib.PurePosixPath("scripts/migrate-compose-volumes.sh"),
    pathlib.PurePosixPath("scripts/check_branding.py"),
}'''
if needle in text:
    text = text.replace(needle, replacement, 1)
elif 'pathlib.PurePosixPath("scripts/check_branding.py")' not in text:
    raise SystemExit("branding validator allowlist marker not found")
validator.write_text(text, encoding="utf-8")

# Keep the capacity harness import-safe in the cumulative branch even when the
# earlier one-shot correction raced with branch creation.
load_path = ROOT / "scripts/load_test.py"
load_text = load_path.read_text(encoding="utf-8")
if "\nimport sys\n" not in load_text:
    load_text = load_text.replace("import statistics\n", "import statistics\nimport sys\n", 1)
load_path.write_text(load_text, encoding="utf-8")

test_path = ROOT / "backend/tests/test_load_test_tool.py"
test_text = test_path.read_text(encoding="utf-8")
if "\nimport sys\n" not in test_text:
    test_text = test_text.replace("import json\n", "import json\nimport sys\n", 1)
marker = "    module = importlib.util.module_from_spec(spec)\n"
insertion = marker + "    sys.modules[spec.name] = module\n"
if insertion not in test_text:
    if marker not in test_text:
        raise SystemExit("capacity test loader marker not found")
    test_text = test_text.replace(marker, insertion, 1)
test_path.write_text(test_text, encoding="utf-8")
