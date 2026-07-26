#!/usr/bin/env python3
"""Generate a deterministic license inventory for the default Community build."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

NODE_APPLICATIONS = ("admin", "addin", "landing")
POLICY_PATH = pathlib.PurePosixPath("docs/legal/dependency-license-policy.json")
SPDX_TOKEN = re.compile(r"\(|\)|AND|OR|WITH|[A-Za-z0-9][A-Za-z0-9.+-]*")


class InventoryError(RuntimeError):
    """Raised when locked dependency evidence is incomplete or inconsistent."""


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_spdx_expression(expression: str) -> bool:
    """Validate the SPDX expression grammar used by this repository policy."""

    tokens = SPDX_TOKEN.findall(expression)
    if not tokens or "".join(tokens) != re.sub(r"\s+", "", expression):
        return False
    position = 0

    def parse_primary() -> bool:
        nonlocal position
        if position >= len(tokens):
            return False
        if tokens[position] == "(":
            position += 1
            if not parse_or() or position >= len(tokens) or tokens[position] != ")":
                return False
            position += 1
            return True
        if tokens[position] in {"AND", "OR", "WITH", ")"}:
            return False
        position += 1
        if position < len(tokens) and tokens[position] == "WITH":
            position += 1
            if position >= len(tokens) or tokens[position] in {"AND", "OR", "WITH", "(", ")"}:
                return False
            position += 1
        return True

    def parse_and() -> bool:
        nonlocal position
        if not parse_primary():
            return False
        while position < len(tokens) and tokens[position] == "AND":
            position += 1
            if not parse_primary():
                return False
        return True

    def parse_or() -> bool:
        nonlocal position
        if not parse_and():
            return False
        while position < len(tokens) and tokens[position] == "OR":
            position += 1
            if not parse_and():
                return False
        return True

    return parse_or() and position == len(tokens)


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"{label} must be a non-empty string")
    return value.strip()


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise InventoryError(f"{label} must be an object")
    return value


def load_policy(root: pathlib.Path) -> dict[str, Any]:
    path = root / pathlib.Path(POLICY_PATH)
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"cannot read {POLICY_PATH.as_posix()}: {exc}") from exc
    if not isinstance(policy, dict) or policy.get("schemaVersion") != "1.0":
        raise InventoryError(f"{POLICY_PATH.as_posix()}: unsupported schemaVersion")

    accepted_raw = policy.get("acceptedSpdxExpressions")
    if not isinstance(accepted_raw, list) or not accepted_raw:
        raise InventoryError("acceptedSpdxExpressions must be a non-empty array")
    accepted = [_require_string(value, "acceptedSpdxExpressions entry") for value in accepted_raw]
    if accepted != sorted(set(accepted)):
        raise InventoryError("acceptedSpdxExpressions must be sorted and unique")
    invalid = [value for value in accepted if not parse_spdx_expression(value)]
    if invalid:
        raise InventoryError(f"invalid SPDX expressions in policy: {', '.join(invalid)}")
    accepted_set = set(accepted)

    aliases = _require_mapping(policy.get("metadataAliases"), "metadataAliases")
    for raw, normalized in aliases.items():
        _require_string(raw, "metadataAliases key")
        expression = _require_string(normalized, f"metadataAliases[{raw!r}]")
        if expression not in accepted_set:
            raise InventoryError(f"metadata alias {raw!r} resolves to an unaccepted expression")

    for section in ("pythonOverrides", "nodeOverrides"):
        overrides = _require_mapping(policy.get(section), section)
        for key, raw_record in overrides.items():
            _require_string(key, f"{section} key")
            record = _require_mapping(raw_record, f"{section}[{key!r}]")
            expression = _require_string(record.get("spdx"), f"{section}[{key!r}].spdx")
            _require_string(record.get("evidence"), f"{section}[{key!r}].evidence")
            if expression not in accepted_set:
                raise InventoryError(f"{section}[{key!r}] uses an unaccepted SPDX expression")

    prohibited = policy.get("prohibitedNodePackages")
    if not isinstance(prohibited, list) or any(not isinstance(value, str) or not value for value in prohibited):
        raise InventoryError("prohibitedNodePackages must be an array of package names")
    if prohibited != sorted(set(prohibited)):
        raise InventoryError("prohibitedNodePackages must be sorted and unique")

    bundled = policy.get("bundledComponents")
    if not isinstance(bundled, list):
        raise InventoryError("bundledComponents must be an array")
    for index, raw_record in enumerate(bundled):
        record = _require_mapping(raw_record, f"bundledComponents[{index}]")
        for field in ("ecosystem", "package", "version", "spdx", "usage", "evidencePath", "evidenceSha256"):
            _require_string(record.get(field), f"bundledComponents[{index}].{field}")
        if record["spdx"] not in accepted_set:
            raise InventoryError(f"bundledComponents[{index}] uses an unaccepted SPDX expression")
        evidence = root / str(record["evidencePath"])
        if not evidence.is_file():
            raise InventoryError(f"bundledComponents[{index}] evidence is missing: {record['evidencePath']}")
        actual_hash = sha256_file(evidence)
        if actual_hash != record["evidenceSha256"]:
            raise InventoryError(
                f"bundledComponents[{index}] evidence hash changed: expected {record['evidenceSha256']}, "
                f"found {actual_hash}"
            )
        version_path = record.get("versionEvidencePath")
        version_variable = record.get("versionVariable")
        if version_path is not None or version_variable is not None:
            version_file = root / _require_string(
                version_path, f"bundledComponents[{index}].versionEvidencePath"
            )
            variable = _require_string(version_variable, f"bundledComponents[{index}].versionVariable")
            if not version_file.is_file():
                raise InventoryError(f"bundledComponents[{index}] version evidence is missing: {version_path}")
            pattern = re.compile(rf"(?m)^(?:ENV\s+)?{re.escape(variable)}=(?P<version>[^\s]+)\s*$")
            match = pattern.search(version_file.read_text(encoding="utf-8"))
            if match is None or match.group("version") != record["version"]:
                found = match.group("version") if match is not None else "missing"
                raise InventoryError(
                    f"bundledComponents[{index}] version mismatch: policy={record['version']}, evidence={found}"
                )
    return policy


def _metadata_license(distribution: importlib.metadata.Distribution) -> str:
    metadata = distribution.metadata
    expression = metadata.get("License-Expression")
    if expression and expression.strip():
        return expression.strip()
    declared = metadata.get("License")
    if declared and declared.strip() and declared.strip().upper() != "UNKNOWN":
        return declared.strip()
    return ""


def _display_declared_license(value: str) -> str:
    if not value:
        return "missing"
    if "\n" not in value and len(value) <= 160:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"non-SPDX license text (sha256:{digest})"


def resolve_license(
    *,
    package: str,
    version: str,
    declared: str,
    policy: Mapping[str, Any],
    ecosystem: str,
) -> tuple[str, str, str]:
    """Return expression, evidence source, and tracked/unreviewed policy status."""

    override_section = "pythonOverrides" if ecosystem == "python" else "nodeOverrides"
    overrides = _require_mapping(policy.get(override_section), override_section)
    key = f"{package}@{version}"
    override = overrides.get(key)
    if override is not None:
        record = _require_mapping(override, f"{override_section}[{key!r}]")
        expression = _require_string(record.get("spdx"), f"{override_section}[{key!r}].spdx")
        evidence = f"version-pinned override: {_require_string(record.get('evidence'), 'override evidence')}"
    else:
        aliases = _require_mapping(policy.get("metadataAliases"), "metadataAliases")
        expression = str(aliases.get(declared, declared)).strip()
        evidence = "locked package metadata"

    accepted = set(policy.get("acceptedSpdxExpressions", []))
    status = "tracked" if expression in accepted and parse_spdx_expression(expression) else "unreviewed"
    return expression or "unknown", evidence, status


def _uv_export(root: pathlib.Path) -> list[Requirement]:
    uv = shutil.which("uv")
    if uv is None:
        raise InventoryError("uv executable is required to export the frozen Python environment")
    command = [
        uv,
        "export",
        "--directory",
        str(root / "backend"),
        "--frozen",
        "--no-dev",
        "--no-emit-project",
        "--no-hashes",
        "--format",
        "requirements-txt",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InventoryError(f"cannot export frozen Python dependencies: {exc}") from exc
    if result.returncode != 0:
        raise InventoryError(f"uv export failed: {result.stderr.strip()}")

    requirements: list[Requirement] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            requirement = Requirement(line)
        except ValueError as exc:
            raise InventoryError(f"cannot parse uv export line {line!r}: {exc}") from exc
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        requirements.append(requirement)
    return requirements


def collect_python(root: pathlib.Path, policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    pyproject = tomllib.loads(
        (root / "backend/pyproject.toml").read_text(encoding="utf-8")
    )
    direct_project = pyproject.get("project", {}).get("dependencies", [])
    if not isinstance(direct_project, list):
        raise InventoryError("backend/pyproject.toml: project.dependencies must be an array")
    direct = {
        canonicalize_name(Requirement(value).name)
        for value in direct_project
        if isinstance(value, str)
    }
    components: list[dict[str, Any]] = []
    observed: set[str] = set()
    for requirement in _uv_export(root):
        name = canonicalize_name(requirement.name)
        versions = [specifier.version for specifier in requirement.specifier if specifier.operator == "=="]
        if len(versions) != 1 or len(list(requirement.specifier)) != 1:
            raise InventoryError(f"frozen export did not pin exactly one version for {name}: {requirement.specifier}")
        version = versions[0]
        key = f"{name}@{version}"
        if key in observed:
            continue
        observed.add(key)
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise InventoryError(f"frozen Python dependency is not installed: {key}") from exc
        if distribution.version != version:
            raise InventoryError(f"installed Python version mismatch for {name}: lock={version}, installed={distribution.version}")
        declared = _metadata_license(distribution)
        expression, evidence, status = resolve_license(
            package=name,
            version=version,
            declared=declared,
            policy=policy,
            ecosystem="python",
        )
        components.append(
            {
                "ecosystem": "python",
                "scope": "backend default runtime",
                "package": name,
                "version": version,
                "spdx": expression,
                "declaredLicense": _display_declared_license(declared),
                "direct": name in direct,
                "source": f"https://pypi.org/project/{name}/{version}/",
                "evidence": evidence,
                "policyStatus": status,
            }
        )
    return components


def _node_package_name(path: str, metadata: Mapping[str, Any]) -> str:
    explicit = metadata.get("name")
    if isinstance(explicit, str) and explicit:
        return explicit
    marker = "node_modules/"
    if marker not in path:
        raise InventoryError(f"cannot derive package name from lock path: {path}")
    return path.rsplit(marker, 1)[1]


def collect_node(root: pathlib.Path, policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    prohibited = set(policy.get("prohibitedNodePackages", []))
    components: list[dict[str, Any]] = []
    for application in NODE_APPLICATIONS:
        lock_path = root / application / "package-lock.json"
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InventoryError(f"cannot read {application}/package-lock.json: {exc}") from exc
        packages = lock.get("packages")
        if not isinstance(packages, dict):
            raise InventoryError(f"{application}/package-lock.json: packages object is missing")
        root_package = packages.get("", {})
        direct_dependencies = root_package.get("dependencies", {}) if isinstance(root_package, dict) else {}
        direct_names = set(direct_dependencies) if isinstance(direct_dependencies, dict) else set()

        for package_path, raw_metadata in sorted(packages.items()):
            if not package_path or not isinstance(raw_metadata, dict) or raw_metadata.get("dev") is True:
                continue
            name = _node_package_name(package_path, raw_metadata)
            version = raw_metadata.get("version")
            if not isinstance(version, str) or not version:
                raise InventoryError(f"{application}: production package {name} has no locked version")
            if name in prohibited:
                raise InventoryError(f"{application}: prohibited package {name}@{version}")
            declared = raw_metadata.get("license")
            declared_text = declared.strip() if isinstance(declared, str) else ""
            expression, evidence, status = resolve_license(
                package=name,
                version=version,
                declared=declared_text,
                policy=policy,
                ecosystem="node",
            )
            source = raw_metadata.get("resolved")
            components.append(
                {
                    "ecosystem": "node",
                    "scope": f"{application} production/bundled",
                    "package": name,
                    "version": version,
                    "spdx": expression,
                    "declaredLicense": declared_text or "missing",
                    "direct": name in direct_names,
                    "source": source if isinstance(source, str) else "",
                    "evidence": evidence,
                    "policyStatus": status,
                }
            )
    return components


def collect_bundled(policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for raw_record in policy.get("bundledComponents", []):
        record = dict(raw_record)
        components.append(
            {
                "ecosystem": record["ecosystem"],
                "scope": record["usage"],
                "package": record["package"],
                "version": record["version"],
                "spdx": record["spdx"],
                "declaredLicense": record["spdx"],
                "direct": True,
                "source": record["evidencePath"],
                "evidence": f"checked-in license sha256:{record['evidenceSha256']}",
                "policyStatus": "tracked",
            }
        )
    return components


def input_hashes(root: pathlib.Path, policy: Mapping[str, Any]) -> dict[str, str]:
    paths = [
        pathlib.Path(POLICY_PATH),
        pathlib.Path("backend/uv.lock"),
        *(pathlib.Path(application) / "package-lock.json" for application in NODE_APPLICATIONS),
    ]
    for record in policy.get("bundledComponents", []):
        paths.append(pathlib.Path(record["evidencePath"]))
        version_path = record.get("versionEvidencePath")
        if isinstance(version_path, str):
            paths.append(pathlib.Path(version_path))
    return {path.as_posix(): sha256_file(root / path) for path in sorted(set(paths))}


def build_report(root: pathlib.Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    components = collect_python(root, policy) + collect_node(root, policy) + collect_bundled(policy)
    components.sort(
        key=lambda item: (
            str(item["ecosystem"]),
            str(item["scope"]),
            str(item["package"]).lower(),
            str(item["version"]),
        )
    )
    unreviewed = [item for item in components if item["policyStatus"] != "tracked"]
    return {
        "schemaVersion": "2.0",
        "repositoryLicense": "AGPL-3.0-only",
        "target": {
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": sys.platform,
        },
        "inputs": input_hashes(root, policy),
        "summary": {
            "components": len(components),
            "tracked": len(components) - len(unreviewed),
            "unreviewed": len(unreviewed),
        },
        "components": components,
        "disclaimer": (
            "Automated metadata inventory only; passing does not constitute legal advice, "
            "license compatibility approval, or satisfaction of notice/source obligations."
        ),
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    target = report["target"]
    lines = [
        "# Locked third-party dependency inventory",
        "",
        f"Repository license: `{report['repositoryLicense']}`.",
        f"Target: Python {target['python']} on `{target['platform']}`.",
        "",
        f"> {report['disclaimer']}",
        "",
        "## Summary",
        "",
        f"- Components: **{summary['components']}**",
        f"- Tracked by policy: **{summary['tracked']}**",
        f"- Unreviewed: **{summary['unreviewed']}**",
        "",
        "## Components",
        "",
        "| Ecosystem | Scope | Package | Version | SPDX | Direct | Status | Source |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for component in report["components"]:
        values = (
            component["ecosystem"],
            component["scope"],
            component["package"],
            component["version"],
            component["spdx"],
            "yes" if component["direct"] else "no",
            component["policyStatus"],
            component["source"],
        )
        safe = [str(value).replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(safe) + " |")
    lines.append("")
    return "\n".join(lines)


def _write_output(path_value: str, content: str) -> None:
    path = pathlib.Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--json-out", default="", help="Optional JSON output path; stdout when omitted.")
    parser.add_argument("--markdown-out", default="", help="Optional Markdown output path.")
    parser.add_argument("--check", action="store_true", help="Fail when any component is not tracked by policy.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    try:
        policy = load_policy(root)
        report = build_report(root, policy)
        rendered_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.json_out:
            _write_output(args.json_out, rendered_json)
        else:
            sys.stdout.write(rendered_json)
        if args.markdown_out:
            _write_output(args.markdown_out, render_markdown(report))
        if args.check and report["summary"]["unreviewed"]:
            return 1
        return 0
    except (InventoryError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"schemaVersion": "2.0", "ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
