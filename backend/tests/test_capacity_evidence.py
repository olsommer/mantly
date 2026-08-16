from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_module() -> ModuleType:
    script = Path(__file__).resolve().parents[2] / "scripts" / "validate_capacity_evidence.py"
    spec = importlib.util.spec_from_file_location("mantly_validate_capacity_evidence", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_artifact(base: Path, name: str, payload: dict[str, Any], **extra: object) -> dict[str, object]:
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    (base / name).write_bytes(raw)
    return {"artifact": name, "sha256": hashlib.sha256(raw).hexdigest(), **extra}


def _load_run(kind: str, *, started_at: datetime, duration: int) -> dict[str, Any]:
    checks = {
        "errorRateMax": {"actual": 0, "target": 0.01, "pass": True},
        "p95MsMax": {"actual": 100, "target": 500, "pass": True},
        "throughputPerSecondMin": {"actual": 5, "target": 4.5, "pass": True},
        "minimumRequests": {"actual": 1000, "target": 100, "pass": True},
        "minimumRequestsPerTarget": {"actual": 100, "target": 20, "pass": True},
    }
    return {
        "schemaVersion": "1.0",
        "releaseId": "release-abc123",
        "environmentId": "capacity-test",
        "runKind": kind,
        "startedAt": started_at.isoformat(),
        "generatedAt": (started_at + timedelta(seconds=duration)).isoformat(),
        "runElapsedSeconds": duration + 1,
        "scenarioKind": "capacity",
        "scenarioSha256": "a" * 64,
        "workloads": [
            "attachment-processing",
            "inbound-ingestion",
            "inbox-read",
            "knowledge-lookup",
            "model-execution",
            "outbound-delivery",
            "runbook-match",
            "tool-lookup",
        ],
        "configured": {"durationSeconds": duration},
        "throughputPerSecond": 5.0,
        "thresholds": {
            "checks": checks,
            "missingRequiredChecks": [],
            "allPassed": True,
        },
    }


def _manifest_fixture(tmp_path: Path) -> tuple[dict[str, Any], list[dict[str, object]]]:
    topology = {
        "schemaVersion": "1.0",
        "observedExternally": True,
        "supported": True,
        "errors": [],
        "serviceCounts": {"app": 1, "caddy": 1, "pocketbase": 1},
        "containers": [{"service": service} for service in ("app", "caddy", "pocketbase")],
        "inventorySha256": "b" * 64,
    }
    topology_ref = _write_artifact(tmp_path, "topology.json", topology)

    base_time = datetime(2026, 7, 26, tzinfo=timezone.utc)
    load_specs = [
        ("steady", 1800),
        ("steady", 1800),
        ("steady", 1800),
        ("burst", 300),
        ("soak", 14400),
        ("degraded-provider", 300),
    ]
    load_refs: list[dict[str, object]] = []
    for index, (kind, duration) in enumerate(load_specs):
        payload = _load_run(kind, started_at=base_time + timedelta(days=index), duration=duration)
        load_refs.append(
            _write_artifact(
                tmp_path,
                f"load-{index}.json",
                payload,
                kind=kind,
            )
        )

    exercise_refs: list[dict[str, object]] = []
    for index, kind in enumerate(("restart-catch-up", "storage-growth", "recovery")):
        started = base_time + timedelta(days=10 + index)
        payload = {
            "schemaVersion": "1.0",
            "releaseId": "release-abc123",
            "environmentId": "capacity-test",
            "kind": kind,
            "passed": True,
            "startedAt": started.isoformat(),
            "completedAt": (started + timedelta(minutes=5)).isoformat(),
            "observations": [{"name": "verified", "value": True}],
        }
        exercise_refs.append(
            _write_artifact(
                tmp_path,
                f"exercise-{kind}.json",
                payload,
                kind=kind,
            )
        )

    resource_ref = _write_artifact(
        tmp_path,
        "resources.json",
        {
            "schemaVersion": "1.0",
            "releaseId": "release-abc123",
            "environmentId": "capacity-test",
            "metrics": {
                name: {"observed": 1, "unit": "test-unit", "pass": True}
                for name in (
                    "cpu",
                    "memory",
                    "diskIo",
                    "diskFree",
                    "sqliteLocks",
                    "queueAge",
                    "providerErrors",
                    "cost",
                )
            },
        },
    )
    manifest = {
        "schemaVersion": "1.0",
        "releaseId": "release-abc123",
        "environmentId": "capacity-test",
        "topology": topology_ref,
        "loadRuns": load_refs,
        "exercises": exercise_refs,
        "resourceEvidence": resource_ref,
        "operatingEnvelope": {
            "activeTenants": 1,
            "concurrentInboxUsers": 10,
            "ticketsPerDay": 200,
            "messagesPerDay": 400,
            "inboundEventsPerSecond": 1,
            "outboundDeliveriesPerSecond": 1,
            "concurrentAutomationExecutions": 5,
            "attachmentAndKnowledgeGiB": 10,
            "approvedRequestsPerSecond": 4.2,
            "observedBottleneckRequestsPerSecond": 6,
            "headroomPercent": 30,
        },
        "approvals": {
            "architecture": {
                "approvedBy": "architecture-owner",
                "approvedAt": "2026-07-26T00:00:00+00:00",
                "decision": "approved",
            },
            "operations": {
                "approvedBy": "operations-owner",
                "approvedAt": "2026-07-26T00:00:00+00:00",
                "decision": "approved",
            },
        },
    }
    return manifest, load_refs


def test_complete_capacity_evidence_is_accepted(tmp_path: Path) -> None:
    module = _load_module()
    manifest, _ = _manifest_fixture(tmp_path)

    result = module.validate_manifest(manifest, base=tmp_path.resolve())

    assert result["accepted"] is True
    assert result["loadRunCounts"] == {
        "burst": 1,
        "degraded-provider": 1,
        "soak": 1,
        "steady": 3,
    }
    assert result["scenarioSha256"] == "a" * 64


def test_vacuous_load_thresholds_are_rejected(tmp_path: Path) -> None:
    module = _load_module()
    manifest, load_refs = _manifest_fixture(tmp_path)
    first_ref = load_refs[0]
    first_path = tmp_path / str(first_ref["artifact"])
    payload = json.loads(first_path.read_text(encoding="utf-8"))
    payload["thresholds"]["checks"] = {}
    replacement = _write_artifact(
        tmp_path,
        first_path.name,
        payload,
        kind="steady",
    )
    manifest["loadRuns"][0] = replacement

    with pytest.raises(module.CapacityEvidenceError, match="vacuous threshold"):
        module.validate_manifest(manifest, base=tmp_path.resolve())


def test_artifacts_cannot_escape_manifest_directory(tmp_path: Path) -> None:
    module = _load_module()
    manifest, _ = _manifest_fixture(tmp_path)
    manifest["topology"] = {"artifact": "../topology.json", "sha256": "a" * 64}

    with pytest.raises(module.CapacityEvidenceError, match="escapes"):
        module.validate_manifest(manifest, base=tmp_path.resolve())
