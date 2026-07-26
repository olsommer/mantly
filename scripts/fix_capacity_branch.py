#!/usr/bin/env python3
"""Repair the capacity harness imports on the already-open stacked branch."""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

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
        raise SystemExit("capacity module-loader marker not found")
    test_text = test_text.replace(marker, insertion, 1)
test_path.write_text(test_text, encoding="utf-8")
