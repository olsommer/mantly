from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/generate_third_party_notice.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("mantly_license_inventory", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool():
    return load_tool()


def test_spdx_parser_requires_a_complete_expression(tool) -> None:
    assert tool.parse_spdx_expression("MIT")
    assert tool.parse_spdx_expression("(MPL-2.0 OR Apache-2.0)")
    assert tool.parse_spdx_expression("GPL-2.0-only WITH Classpath-exception-2.0")

    assert not tool.parse_spdx_expression("")
    assert not tool.parse_spdx_expression("MIT OR")
    assert not tool.parse_spdx_expression("MIT / GPL-3.0-only")
    assert not tool.parse_spdx_expression("(MIT")


def test_license_resolution_never_uses_substring_matching(tool) -> None:
    policy = {
        "acceptedSpdxExpressions": ["Apache-2.0", "MIT"],
        "metadataAliases": {"Apache 2.0": "Apache-2.0"},
        "pythonOverrides": {
            "legacy@1.0.0": {
                "spdx": "MIT",
                "evidence": "Pinned license file review.",
            }
        },
        "nodeOverrides": {},
    }

    expression, evidence, status = tool.resolve_license(
        package="example",
        version="1.0.0",
        declared="MIT OR LicenseRef-Proprietary",
        policy=policy,
        ecosystem="python",
    )
    assert expression == "MIT OR LicenseRef-Proprietary"
    assert evidence == "locked package metadata"
    assert status == "unreviewed"

    expression, evidence, status = tool.resolve_license(
        package="legacy",
        version="1.0.0",
        declared="unknown",
        policy=policy,
        ecosystem="python",
    )
    assert expression == "MIT"
    assert evidence.startswith("version-pinned override:")
    assert status == "tracked"


def test_repository_policy_and_locked_node_graph_are_fully_tracked(tool) -> None:
    policy = tool.load_policy(ROOT)
    components = tool.collect_node(ROOT, policy)

    assert components
    assert all(component["policyStatus"] == "tracked" for component in components)
    assert any(
        component["package"] == "format"
        and component["version"] == "0.2.2"
        and component["spdx"] == "MIT"
        for component in components
    )


def test_rendering_is_byte_stable(tool) -> None:
    report = {
        "repositoryLicense": "AGPL-3.0-only",
        "target": {"python": "3.12.0", "platform": "linux"},
        "summary": {"components": 1, "tracked": 1, "unreviewed": 0},
        "components": [
            {
                "ecosystem": "python",
                "scope": "backend default runtime",
                "package": "example",
                "version": "1.0.0",
                "spdx": "MIT",
                "direct": True,
                "policyStatus": "tracked",
                "source": "https://example.invalid/example",
            }
        ],
        "disclaimer": "Inventory only.",
    }

    rendered = tool.render_markdown(report)

    # Byte-exact expectations. Comparing render_markdown(report) against itself
    # cannot fail, so it asserted nothing about the rendered bytes.
    assert rendered.startswith("# Locked third-party dependency inventory\n")
    assert "Repository license: `AGPL-3.0-only`.\n" in rendered
    assert "Target: Python 3.12.0 on `linux`.\n" in rendered
    assert "- Components: **1**\n" in rendered
    assert "- Tracked by policy: **1**\n" in rendered
    assert "- Unreviewed: **0**\n" in rendered
    assert (
        "| python | backend default runtime | example | 1.0.0 | MIT | yes | tracked "
        "| https://example.invalid/example |"
    ) in rendered

    # Key order must not leak into the output. A dict-ordering dependence is the
    # realistic way this renderer would stop being byte-stable across runs.
    reordered = {key: report[key] for key in reversed(list(report))}
    reordered["components"] = [
        {key: component[key] for key in reversed(list(component))}
        for component in report["components"]
    ]
    assert tool.render_markdown(reordered) == rendered
