"""Fallback path checks for moved backend modules."""

import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_template_default_points_to_repo_manifest(monkeypatch):
    monkeypatch.delenv("MANIFEST_TEMPLATE_PATH", raising=False)

    import automail.api.admin.manifest as manifest

    manifest = importlib.reload(manifest)
    expected = REPO_ROOT / "addin" / "manifest.xml"
    assert manifest._MANIFEST_TEMPLATE_PATH == expected
    assert expected.exists()


def test_demo_eval_root_default_points_to_repo_demo(monkeypatch):
    monkeypatch.delenv("DEMO_DATA_DIR", raising=False)

    from automail.api.admin.evals import _demo_root

    expected = REPO_ROOT / "demo"
    assert _demo_root() == expected
    assert (expected / "emails" / "emails.json").exists()


def test_demo_eval_expectations_match_logistics_emails():
    from automail.api.admin.eval_helpers import _demo_expected_outcomes

    status = _demo_expected_outcomes({"id": "zen-shipment-status"})
    exception = _demo_expected_outcomes({"id": "zen-delivery-exception"})

    assert status["expected_intent_name"] == "shipment-status-request"
    assert status["expected_actions"] == []
    assert exception["expected_intent_name"] == "delivery-exception"
    assert exception["expected_actions"] == [{"name": "open_ticket", "label": "Open ticket"}]


def test_brand_path_default_points_to_repo_brand(monkeypatch):
    monkeypatch.delenv("APP_BRAND_PATH", raising=False)

    from automail.core.brand import _brand_path

    expected = REPO_ROOT / "brand.json"
    assert _brand_path() == expected
    assert expected.exists()
