from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from types import ModuleType

import pytest


def _load_validator() -> ModuleType:
    path = pathlib.Path(__file__).parents[2] / "scripts" / "validate-compliance-package.py"
    spec = importlib.util.spec_from_file_location("validate_compliance_package", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_repository_template_is_valid_but_not_approved(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    validator = _load_validator()
    root = pathlib.Path(__file__).parents[2]

    monkeypatch.setattr(sys, "argv", ["validator", "--root", str(root)])
    assert validator.main() == 0
    template_report = json.loads(capsys.readouterr().out)
    assert template_report["deploymentReady"] is False

    monkeypatch.setattr(sys, "argv", ["validator", "--root", str(root), "--require-approved"])
    assert validator.main() == 1
    approved_report = json.loads(capsys.readouterr().out)
    assert approved_report["deploymentReady"] is False
    assert any("status must be approved" in error for error in approved_report["errors"])


def test_completed_provider_and_lifecycle_evidence_can_pass_approved_mode(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    validator = _load_validator()
    root = pathlib.Path(__file__).parents[2]
    inventory = json.loads(
        (root / "docs/compliance/subprocessors.example.json").read_text(encoding="utf-8")
    )
    inventory["status"] = "approved"
    inventory["deployment"] = {
        "name": "pilot-deployment",
        "mode": "hosted-saas",
        "primaryProcessingRegion": "eu-central",
        "customer": "approved-customer-id",
        "lastReviewedAt": "2026-07-20T12:00:00Z",
        "reviewedBy": ["privacy-owner", "security-owner"],
    }
    for provider in inventory["providers"]:
        if provider["required"] or provider["enabled"]:
            provider["enabled"] = True
            provider["legalReviewComplete"] = True
            provider["legalEntity"] = f"approved-{provider['key']}-entity"
            provider["role"] = "approved-processor-role"
            provider["retention"] = "approved-contract-retention"
            provider["trainingOrSecondaryUse"] = "approved-no-secondary-use"
            provider["transferMechanism"] = "approved-transfer-assessment"
            provider["owner"] = "approved-provider-owner"
            provider["processingLocations"] = ["EU"]
            provider["supportAccessLocations"] = ["EU"]
            for field in validator.REFERENCE_FIELDS:
                provider[field] = f"evidence:{provider['key']}:{field}"
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    lifecycle = {
        "schemaVersion": "1.0",
        "status": "passed",
        "completedAt": "2026-07-21T12:00:00Z",
        "releaseCommit": "0123456789abcdef",
        "approvals": {
            "operator": "operator",
            "independentVerifier": "verifier",
            "engineeringOwner": "engineer",
            "privacySecurityOwner": "privacy",
        },
        "evidenceRefs": ["evidence:lifecycle-report", "evidence:deletion-replay"],
    }
    lifecycle_path = tmp_path / "lifecycle.json"
    lifecycle_path.write_text(json.dumps(lifecycle), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validator",
            "--root",
            str(root),
            "--inventory",
            str(inventory_path),
            "--lifecycle-evidence",
            str(lifecycle_path),
            "--require-approved",
        ],
    )
    assert validator.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["deploymentReady"] is True
