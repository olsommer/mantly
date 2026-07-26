"""Fail when critical runtime areas fall below their explicit coverage floors."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CoverageArea:
    minimum: float
    files: tuple[str, ...]


CRITICAL_AREAS = {
    "authorization": CoverageArea(
        minimum=70.0,
        files=(
            "automail/api/auth.py",
            "automail/api/auth_utils.py",
            "automail/api/admin/deps.py",
        ),
    ),
    "support-inbox": CoverageArea(
        minimum=60.0,
        files=(
            "automail/api/admin/issues.py",
            "automail/db/pocketbase/issues.py",
        ),
    ),
    "delivery": CoverageArea(
        minimum=60.0,
        files=(
            "automail/support/delivery.py",
            "automail/support/scheduler.py",
        ),
    ),
    "automation": CoverageArea(
        minimum=60.0,
        files=(
            "automail/api/admin/automations.py",
            "automail/support/pending_action_claims.py",
        ),
    ),
}


def _coverage_file(files: dict[str, Any], expected: str) -> dict[str, Any]:
    normalized_expected = expected.replace("\\", "/")
    matches = [
        value
        for key, value in files.items()
        if key.replace("\\", "/").endswith(normalized_expected)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one coverage entry ending in {normalized_expected!r}; "
            f"found {len(matches)}"
        )
    return matches[0]


def _area_percentage(files: dict[str, Any], area: CoverageArea) -> tuple[float, int, int]:
    covered = 0
    total = 0
    for expected in area.files:
        summary = _coverage_file(files, expected).get("summary", {})
        covered += int(summary.get("covered_lines", 0))
        total += int(summary.get("num_statements", 0))
        covered += int(summary.get("covered_branches", 0))
        total += int(summary.get("num_branches", 0))
    if total <= 0:
        raise ValueError("Critical coverage area has no executable statements or branches")
    return covered * 100.0 / total, covered, total


def check_critical_coverage(report: dict[str, Any]) -> list[str]:
    files = report.get("files")
    if not isinstance(files, dict):
        return ["Coverage report has no file-level data"]
    failures: list[str] = []
    for name, area in CRITICAL_AREAS.items():
        try:
            percentage, covered, total = _area_percentage(files, area)
        except ValueError as exc:
            failures.append(f"{name}: {exc}")
            continue
        print(
            f"{name:16} {percentage:5.1f}% "
            f"({covered}/{total} line+branch outcomes; minimum {area.minimum:.1f}%)"
        )
        if percentage + 1e-9 < area.minimum:
            failures.append(
                f"{name}: {percentage:.1f}% is below {area.minimum:.1f}%"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path, help="coverage.py JSON report")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read coverage report: {exc}", file=sys.stderr)
        return 2
    failures = check_critical_coverage(report)
    if failures:
        for failure in failures:
            print(f"CRITICAL COVERAGE FAILURE: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
