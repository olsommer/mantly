from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from types import ModuleType

import pytest


def _load_verifier() -> ModuleType:
    path = pathlib.Path(__file__).parents[2] / "scripts" / "verify-restore.py"
    spec = importlib.util.spec_from_file_location("verify_restore", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_restore_expectations_cover_every_required_evidence_class() -> None:
    verifier = _load_verifier()
    path = pathlib.Path(__file__).parents[2] / "tests" / "fixtures" / "backup" / "restore-expectations.json"

    minimums, checks = verifier.load_expectations(str(path))

    assert set(minimums) == set(verifier.DEFAULT_COLLECTIONS)
    assert {check["name"] for check in checks} == verifier.REQUIRED_EVIDENCE_CHECKS


def test_restore_expectations_reject_missing_attachment_evidence(tmp_path: pathlib.Path) -> None:
    verifier = _load_verifier()
    source = pathlib.Path(__file__).parents[2] / "tests" / "fixtures" / "backup" / "restore-expectations.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["recordChecks"] = [
        check for check in payload["recordChecks"] if check["name"] != "attachment"
    ]
    path = tmp_path / "expectations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="attachment"):
        verifier.load_expectations(str(path))


def test_collection_minimum_fails_when_restored_records_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_verifier()
    monkeypatch.setattr(verifier, "request_json", lambda *args, **kwargs: (200, {"totalItems": 0}))

    with pytest.raises(RuntimeError, match="expected at least 1"):
        verifier.collection_detail("http://pocketbase", "projects", "token", 1)


def test_record_check_fails_when_required_attachment_hash_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_verifier()
    monkeypatch.setattr(
        verifier,
        "request_json",
        lambda *args, **kwargs: (200, {"attachment_name": "fixture.txt"}),
    )

    with pytest.raises(RuntimeError, match="attachment_sha256"):
        verifier.record_detail(
            "http://pocketbase",
            "support_messages",
            "message-001",
            ["attachment_name", "attachment_sha256"],
            "token",
        )
