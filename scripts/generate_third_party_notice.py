#!/usr/bin/env python3
"""Generate a review-oriented third-party dependency inventory."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import pathlib
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from typing import Any

PERMISSIVE_MARKERS = (
    "MIT",
    "ISC",
    "BSD",
    "Apache-2.0",
    "Apache 2.0",
    "0BSD",
    "CC0",
    "BlueOak",
    "Python Software Foundation",
)
REVIEW_MARKERS = (
    "AGPL",
    "GPL",
    "LGPL",
    "SSPL",
    "EUPL",
    "EPL",
    "CDDL",
    "MPL",
    "OSL",
    "BUSL",
    "Commons Clause",
    "Non-Commercial",
    "NonCommercial",
    "Research",
)


@dataclass(frozen=True)
class Component:
    ecosystem: str
    package: str
    version: str
    license: str
    source: str | None
    usage: str
    review_category: str
    metadata_note: str | None = None


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def classify(license_value: str) -> str:
    normalized = license_value.strip()
    if not normalized or normalized.lower() in {"unknown", "none", "n/a"}:
        return "legal-review-required"
    if any(marker.lower() in normalized.lower() for marker in REVIEW_MARKERS):
        return "legal-review-required"
    if any(marker.lower() in normalized.lower() for marker in PERMISSIVE_MARKERS):
        return "notice-review"
    return "legal-review-required"


def python_requirement_names(root: pathlib.Path) -> set[str]:
    backend = root / "backend"
    try:
        result = subprocess.run(
            ["uv", "export", "--frozen", "--no-dev", "--format", "requirements-txt"],
            cwd=backend,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"cannot export Python production dependencies: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"uv export failed: {result.stderr.strip()}")

    names: set[str] = set()
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = line.split(" ; ", 1)[0]
        match = re.match(r"([A-Za-z0-9_.-]+)", line)
        if match:
            names.add(normalize_name(match.group(1)))
    return names


def metadata_license(metadata: importlib.metadata.PackageMetadata) -> str:
    expression = metadata.get("License-Expression")
    if expression:
        return expression.strip()
    license_value = metadata.get("License")
    if license_value and license_value.strip() and license_value.strip().upper() != "UNKNOWN":
        return license_value.strip()
    classifiers = metadata.get_all("Classifier") or []
    license_classifiers = [value.removeprefix("License :: ") for value in classifiers if value.startswith("License :: ")]
    return "; ".join(license_classifiers) if license_classifiers else "unknown"


def metadata_source(metadata: importlib.metadata.PackageMetadata) -> str | None:
    for value in metadata.get_all("Project-URL") or []:
        if "," in value:
            _, url = value.split(",", 1)
            if url.strip():
                return url.strip()
    return metadata.get("Home-page") or None


def collect_python(root: pathlib.Path) -> list[Component]:
    required = python_requirement_names(root)
    installed: dict[str, importlib.metadata.Distribution] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            installed[normalize_name(name)] = distribution

    components: list[Component] = []
    for name in sorted(required):
        distribution = installed.get(name)
        if distribution is None:
            components.append(
                Component(
                    ecosystem="python",
                    package=name,
                    version="unknown",
                    license="unknown",
                    source=None,
                    usage="backend production dependency",
                    review_category="legal-review-required",
                    metadata_note="dependency exported by uv but not installed in the current environment",
                )
            )
            continue
        metadata = distribution.metadata
        license_value = metadata_license(metadata)
        components.append(
            Component(
                ecosystem="python",
                package=metadata.get("Name") or name,
                version=distribution.version,
                license=license_value,
                source=metadata_source(metadata),
                usage="backend production dependency",
                review_category=classify(license_value),
            )
        )
    return components


def package_name_from_lock_path(path: str, metadata: dict[str, Any]) -> str:
    explicit = metadata.get("name")
    if isinstance(explicit, str) and explicit:
        return explicit
    marker = "node_modules/"
    if marker in path:
        return path.rsplit(marker, 1)[1]
    return path or "root"


def collect_node(root: pathlib.Path) -> list[Component]:
    components: list[Component] = []
    for directory in ("admin", "addin", "landing"):
        path = root / directory / "package-lock.json"
        lock = json.loads(path.read_text(encoding="utf-8"))
        packages = lock.get("packages")
        if not isinstance(packages, dict):
            raise RuntimeError(f"{path}: packages map is missing")
        for package_path, raw in packages.items():
            if package_path == "" or not isinstance(raw, dict) or raw.get("dev") is True:
                continue
            version = raw.get("version")
            if not isinstance(version, str) or not version:
                continue
            license_value = raw.get("license")
            license_text = license_value if isinstance(license_value, str) and license_value else "unknown"
            source = raw.get("resolved") if isinstance(raw.get("resolved"), str) else None
            components.append(
                Component(
                    ecosystem="node",
                    package=package_name_from_lock_path(package_path, raw),
                    version=version,
                    license=license_text,
                    source=source,
                    usage=f"{directory} production/bundled dependency",
                    review_category=classify(license_text),
                )
            )
    return components


def repository_identity(root: pathlib.Path) -> dict[str, str]:
    pyproject = tomllib.loads((root / "backend/pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    commit = "unknown"
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode == 0:
        commit = result.stdout.strip()
    return {
        "product": "Mantly",
        "backendPackage": str(project.get("name", "unknown")),
        "version": str(project.get("version", "unknown")),
        "gitCommit": commit,
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Third-party dependency inventory",
        "",
        f"Generated for commit `{report['release']['gitCommit']}`.",
        "",
        "> This generated inventory is review input, not automatic legal approval. Verify upstream terms and include required full notices/source offers before distribution.",
        "",
        "## Summary",
        "",
        f"- Components: **{report['summary']['components']}**",
        f"- Notice review: **{report['summary']['noticeReview']}**",
        f"- Legal review required: **{report['summary']['legalReviewRequired']}**",
        "",
        "## Components",
        "",
        "| Ecosystem | Package | Version | Declared license | Usage | Review | Source |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in report["components"]:
        values = [
            item["ecosystem"],
            item["package"],
            item["version"],
            item["license"],
            item["usage"],
            item["review_category"],
            item.get("source") or "",
        ]
        safe = [str(value).replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(safe) + " |")
    lines.extend(
        [
            "",
            "## Release decision",
            "",
            "Every `legal-review-required` item needs an approved decision or replacement before external distribution. Package metadata can be incomplete; review assets, images, models, data, fonts, and service terms separately.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--json-out", default="third-party-inventory.json")
    parser.add_argument("--markdown-out", default="THIRD_PARTY_NOTICES.md")
    parser.add_argument("--fail-on-review", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = pathlib.Path(args.root).resolve()
    try:
        components = collect_python(root) + collect_node(root)
        components = sorted(components, key=lambda item: (item.ecosystem, item.package.lower(), item.version))
        review_count = sum(item.review_category == "legal-review-required" for item in components)
        report = {
            "schemaVersion": "1.0",
            "release": repository_identity(root),
            "summary": {
                "components": len(components),
                "noticeReview": len(components) - review_count,
                "legalReviewRequired": review_count,
            },
            "components": [asdict(item) for item in components],
        }
        pathlib.Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pathlib.Path(args.markdown_out).write_text(markdown(report), encoding="utf-8")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        if args.fail_on_review and review_count:
            return 1
        return 0
    except Exception as exc:  # noqa: BLE001 - release tool must return a concise failed gate
        print(json.dumps({"schemaVersion": "1.0", "ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
