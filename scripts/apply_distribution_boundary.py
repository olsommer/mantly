#!/usr/bin/env python3
"""Apply final licensing, package, and merge-order updates for the stacked PR.

The companion pull-request workflow removes this one-shot script after committing
its result. Permanent rights, inventory, packaging, and validation tools remain.
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

PR_STACK = [
    (1, 13, "#2", "Freeze V1 scope", "P0", "closed by merge"),
    (2, 14, "#1", "Define pilot KPIs", "P0", "closed by merge"),
    (3, 15, "#3", "Security baseline", "P0", "closed by merge"),
    (4, 16, "#4", "Complete CI quality contract", "P0", "closed by merge"),
    (5, 17, "#5", "Verified backup and recovery", "P0", "closed by merge"),
    (6, 18, "#7", "DACH privacy/compliance package", "P0", "repository package; customer legal approval remains"),
    (7, 19, "#6", "Design-partner evidence tooling", "P0", "issue remains open until real pilot evidence"),
    (8, 20, "#9", "Observability and alert response", "P1", "closed by merge"),
    (9, 21, "#8", "Scaling limits and evolution", "P1", "closed by merge"),
    (10, 22, "#10", "Canonical naming and migration", "P1", "closed by merge"),
    (11, 23, "#11", "Licensing and distribution boundary", "P1", "issue remains open until counsel approval"),
]

CANONICAL_REPLACEMENTS = {
    "isarai-email-agent": "mantly",
    "isarai-pocketbase": "mantly-pocketbase",
    "isarai_pb_data": "mantly_pb_data",
    "isarai_app_data": "mantly_app_data",
    "isarai-test": "mantly-test",
    "isarai-email-agent-uv-cache": "mantly-uv-cache",
}


def append_once(path: pathlib.Path, marker: str, content: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker not in text:
        path.write_text(text.rstrip() + "\n\n" + content.strip() + "\n", encoding="utf-8")


def normalize_branding_fallback() -> None:
    """Ensure the final branch is canonical even if PR #22's one-shot job raced."""

    package_metadata = {
        "admin": ("@mantly/admin", "1.0.0"),
        "addin": ("@mantly/outlook-addin", "1.0.0"),
        "landing": ("@mantly/landing", "1.0.0"),
    }
    for directory, (name, version) in package_metadata.items():
        package_path = ROOT / directory / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package.update({"name": name, "version": version, "private": True})
        package_path.write_text(json.dumps(package, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        lock_path = ROOT / directory / "package-lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["name"] = name
        lock["version"] = version
        root_package = lock.setdefault("packages", {}).setdefault("", {})
        root_package["name"] = name
        root_package["version"] = version
        lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pyproject_path = ROOT / "backend/pyproject.toml"
    pyproject = pyproject_path.read_text(encoding="utf-8")
    pyproject = re.sub(r'^name = "backend"$', 'name = "mantly-backend"', pyproject, count=1, flags=re.MULTILINE)
    pyproject = re.sub(r'^version = "0\.1\.0"$', 'version = "1.0.0"', pyproject, count=1, flags=re.MULTILINE)
    pyproject = pyproject.replace(
        'description = "Add your description here"',
        'description = "Agentic email-first customer support runtime and API"',
    )
    pyproject_path.write_text(pyproject, encoding="utf-8")

    lock_path = ROOT / "backend/uv.lock"
    lock = lock_path.read_text(encoding="utf-8")
    lock = re.sub(
        r'(?m)^name = "backend"$\nversion = "0\.1\.0"$',
        'name = "mantly-backend"\nversion = "1.0.0"',
        lock,
        count=1,
    )
    lock_path.write_text(lock, encoding="utf-8")

    skip = {
        pathlib.PurePosixPath("docs/operations/naming-migration.md"),
        pathlib.PurePosixPath("scripts/migrate-compose-volumes.sh"),
        pathlib.PurePosixPath("scripts/check_branding.py"),
        pathlib.PurePosixPath("scripts/apply_distribution_boundary.py"),
    }
    ignored = {".git", ".venv", "node_modules", "dist", "coverage", "__pycache__"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or ignored.intersection(path.parts):
            continue
        relative = pathlib.PurePosixPath(path.relative_to(ROOT).as_posix())
        if relative in skip:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = text
        for legacy, canonical in CANONICAL_REPLACEMENTS.items():
            updated = updated.replace(legacy, canonical)
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def update_merge_order() -> None:
    lines = [
        "# Production-hardening merge order",
        "",
        "Status: **authoritative stacked PR order**",
        "",
        "All PRs target `main`, but each branch was created from its predecessor. Merge strictly in the order below. After each merge, update or rebase the next branch onto the new `main`, resolve conflicts without dropping predecessor changes, and require all checks on the exact merge head.",
        "",
        "| Order | PR | Roadmap issue | Workstream | Priority | Completion boundary |",
        "| ---: | --- | --- | --- | --- | --- |",
    ]
    for order, pr, issue, title, priority, boundary in PR_STACK:
        lines.append(
            f"| {order} | [#{pr}](https://github.com/olsommer/mantly/pull/{pr}) | {issue} | {title} | {priority} | {boundary} |"
        )
    lines.extend(
        [
            "",
            "## Dependency chain",
            "",
            "```text",
            "#13 → #14 → #15 → #16 → #17 → #18 → #19 → #20 → #21 → #22 → #23",
            "```",
            "",
            "Do not merge a later PR first even when its individual checks pass: later branches include and depend on the contracts introduced earlier.",
            "",
            "## Merge procedure",
            "",
            "For each PR:",
            "",
            "1. Confirm the previous PR in this table is merged.",
            "2. Update/rebase the branch onto current `main` and force-push only with lease when necessary.",
            "3. Re-run all required workflows, including security, recovery, compliance, pilot evidence, observability/topology, branding, and licensing gates introduced by predecessors.",
            "4. Review the cumulative diff for scope, generated/one-shot workflow removal, migrations, and customer-facing claims.",
            "5. Merge using the repository's reviewed strategy and record the resulting commit/image digest.",
            "6. Deploy only an artifact built from the merged commit; do not rebuild an old commit against a changed dependency graph.",
            "",
            "## External go-live gates",
            "",
            "Repository merge completion is not the same as commercial production readiness:",
            "",
            "- **Issue #6 stays open** until a real design partner processes the approved real-ticket sample and provides reviewed safety/quality evidence plus an explicit commercial decision.",
            "- **Issue #11 stays open** until qualified legal counsel approves the customer-facing SaaS/on-prem terms and the release-specific third-party review is complete.",
            "- Customer-specific DPA, provider/region inventory, retention schedule, restore drill, lifecycle exercise, operational contacts, capacity result, and risk acceptances remain deployment evidence.",
            "",
            "## Rollback",
            "",
            "Use immutable previously verified artifacts. Naming/volume migration, storage changes, or licensing/package changes require their documented rollback and data-verification procedures. Never alternate writes between old and new persistent volumes.",
            "",
        ]
    )
    (ROOT / "docs/merge-order.md").write_text("\n".join(lines), encoding="utf-8")


def update_readme_and_vision() -> None:
    append_once(
        ROOT / "README.md",
        "## Licensing and distribution",
        """
## Licensing and distribution

Mantly is currently proprietary private-source software. Repository access,
evaluation access, or receipt of a container/package does not itself grant rights
to use, modify, redistribute, host, or sublicense the software. Hosted SaaS and
customer-managed/on-premises rights are granted only through an applicable
written agreement.

See [`LICENSE.md`](LICENSE.md), [`NOTICE.md`](NOTICE.md), the [licensing ADR](docs/decisions/0002-licensing-and-distribution.md), and the [commercial distribution checklist](docs/legal/commercial-distribution-checklist.md). Mantly is not currently represented as open source or source available. Customer-specific terms and third-party review require qualified legal approval before commercial reliance.
""",
    )

    vision_path = ROOT / "docs/product-vision.md"
    vision = vision_path.read_text(encoding="utf-8")
    vision = vision.replace(
        "likely self-hostable or source-available",
        "customer-managed/on-premises under proprietary commercial terms",
    )
    vision = vision.replace(
        "likely self-hostable/source-available",
        "customer-managed/on-premises under proprietary commercial terms",
    )
    vision_path.write_text(vision, encoding="utf-8")
    append_once(
        vision_path,
        "## Licensing decision",
        """
## Licensing decision

The current decision is proprietary private-source software with hosted SaaS and
customer-managed/on-premises rights granted through written commercial terms.
Source review, escrow, modification, redistribution, continuity, and affiliate
rights are negotiated explicitly. The product is not described as open source or
source available. See `decisions/0002-licensing-and-distribution.md`.
""",
    )

    append_once(
        ROOT / "docs/deploy-onprem.md",
        "## Licensing and customer continuity",
        """
## Licensing and customer continuity

Customer-managed deployment requires an executed commercial license/support
agreement. The repository notice is not the full customer license. The agreement
must define permitted entities/environments/copies, validation and grace behavior,
backup/restore/export rights, support/security updates, modifications/integrations,
source review or escrow where purchased, termination, and continuity.

License enforcement must not make customer data unrecoverable. Keep verified
backups, exports, recovery documentation, and agreed continuity rights independent
of the license server. See `docs/decisions/0002-licensing-and-distribution.md` and
`docs/legal/commercial-distribution-checklist.md`.
""",
    )


def update_package_script() -> None:
    path = ROOT / "scripts/package-customer.sh"
    text = path.read_text(encoding="utf-8")

    staging_line = 'mkdir -p "$STAGING/scripts" "$STAGING/docs/operations"'
    replacement = '''mkdir -p "$STAGING/scripts" "$STAGING/docs/operations" "$STAGING/docs/legal"

LICENSE_EVIDENCE_DIR="$OUT_DIR/${PACKAGE_NAME}-license-evidence"
rm -rf "$LICENSE_EVIDENCE_DIR"
mkdir -p "$LICENSE_EVIDENCE_DIR"
if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to generate the locked third-party inventory" >&2
    exit 1
fi
(cd "$ROOT/backend" && uv sync --frozen >/dev/null)
(cd "$ROOT/backend" && uv run python ../scripts/generate_third_party_notice.py \
    --root .. \
    --json-out "$LICENSE_EVIDENCE_DIR/third-party-inventory.json" \
    --markdown-out "$LICENSE_EVIDENCE_DIR/THIRD_PARTY_NOTICES.md")'''
    if "LICENSE_EVIDENCE_DIR=" not in text:
        if staging_line not in text:
            raise RuntimeError("customer package staging marker not found")
        text = text.replace(staging_line, replacement, 1)

    copy_marker = 'cp "$ROOT/docs/deploy-onprem.md" "$STAGING/README.md"'
    copy_block = '''cp "$ROOT/docs/deploy-onprem.md" "$STAGING/README.md"
cp "$ROOT/LICENSE.md" "$STAGING/LICENSE.md"
cp "$ROOT/NOTICE.md" "$STAGING/NOTICE.md"
cp "$LICENSE_EVIDENCE_DIR/THIRD_PARTY_NOTICES.md" "$STAGING/THIRD_PARTY_NOTICES.md"
cp "$LICENSE_EVIDENCE_DIR/third-party-inventory.json" "$STAGING/third-party-inventory.json"
cp "$ROOT/docs/decisions/0002-licensing-and-distribution.md" "$STAGING/docs/legal/licensing-decision.md"
cp "$ROOT/docs/legal/commercial-distribution-checklist.md" "$STAGING/docs/legal/commercial-distribution-checklist.md"
cp "$ROOT/docs/legal/third-party-licenses.md" "$STAGING/docs/legal/third-party-licenses.md"'''
    if 'cp "$ROOT/LICENSE.md"' not in text:
        if copy_marker not in text:
            raise RuntimeError("customer package README copy marker not found")
        text = text.replace(copy_marker, copy_block, 1)

    manifest_marker = '  "supportPackageGate": $SUPPORT_PACKAGE_GATE_JSON'
    licensing_block = '''  "licensing": {
    "model": "proprietary-private-source",
    "repositoryNotice": "LICENSE.md",
    "notice": "NOTICE.md",
    "thirdPartyNotices": "THIRD_PARTY_NOTICES.md",
    "thirdPartyInventory": "third-party-inventory.json",
    "commercialAgreementRequired": true,
    "legalReviewRequired": true
  },
  "supportPackageGate": $SUPPORT_PACKAGE_GATE_JSON'''
    if '"model": "proprietary-private-source"' not in text:
        if manifest_marker not in text:
            raise RuntimeError("release manifest supportPackageGate marker not found")
        text = text.replace(manifest_marker, licensing_block, 1)

    cleanup_marker = 'rm -rf "$STAGING"'
    if 'rm -rf "$LICENSE_EVIDENCE_DIR"' not in text.split(cleanup_marker, 1)[-1]:
        text = text.replace(cleanup_marker, cleanup_marker + '\nrm -rf "$LICENSE_EVIDENCE_DIR"', 1)

    path.write_text(text, encoding="utf-8")


def sanitize_inventory_sources() -> None:
    path = ROOT / "scripts/generate_third_party_notice.py"
    text = path.read_text(encoding="utf-8")
    if "import urllib.parse" not in text:
        text = text.replace("import tomllib\n", "import tomllib\nimport urllib.parse\n", 1)
    if "def sanitize_source(" not in text:
        marker = "def classify(license_value: str) -> str:\n"
        helper = '''def sanitize_source(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme and parsed.netloc:
        hostname = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return urllib.parse.urlunsplit((parsed.scheme, hostname + port, parsed.path, "", ""))
    return value.split("?", 1)[0].split("#", 1)[0]


'''
        if marker not in text:
            raise RuntimeError("inventory classify marker not found")
        text = text.replace(marker, helper + marker, 1)
    text = text.replace("source=metadata_source(metadata),", "source=sanitize_source(metadata_source(metadata)),")
    text = text.replace("source=source,\n", "source=sanitize_source(source),\n")
    path.write_text(text, encoding="utf-8")


def add_quality_gates() -> None:
    quality_path = ROOT / "scripts/check-quality.sh"
    quality = quality_path.read_text(encoding="utf-8")
    marker = 'run "Canonical branding contract" python3 "$ROOT/scripts/check_branding.py"\n'
    command = marker + 'run "Licensing evidence tool syntax" python3 -m py_compile "$ROOT/scripts/generate_third_party_notice.py"\n'
    if "Licensing evidence tool syntax" not in quality:
        if marker not in quality:
            # PR #22's one-shot job may not have run before this branch was cut.
            pilot_marker = 'run "Pilot metric schema" python -m json.tool "$ROOT/docs/pilot-metrics-schema.json"\n'
            if pilot_marker not in quality:
                raise RuntimeError("local quality insertion marker not found")
            command = pilot_marker + 'run "Canonical branding contract" python3 "$ROOT/scripts/check_branding.py"\n' + 'run "Licensing evidence tool syntax" python3 -m py_compile "$ROOT/scripts/generate_third_party_notice.py"\n'
            quality = quality.replace(pilot_marker, command, 1)
        else:
            quality = quality.replace(marker, command, 1)
        quality_path.write_text(quality, encoding="utf-8")


def fix_known_capacity_tool_imports() -> None:
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
            raise RuntimeError("capacity test module loader marker not found")
        test_text = test_text.replace(marker, insertion, 1)
    test_path.write_text(test_text, encoding="utf-8")


def main() -> int:
    normalize_branding_fallback()
    fix_known_capacity_tool_imports()
    update_merge_order()
    update_readme_and_vision()
    update_package_script()
    sanitize_inventory_sources()
    add_quality_gates()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
