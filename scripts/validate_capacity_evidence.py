#!/usr/bin/env python3
"""Validate the complete operational evidence required for a capacity decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import re
import sys
from collections import Counter
from datetime import datetime
from typing import Any

MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
LOAD_RUN_MINIMUMS = {
    "steady": (3, 30 * 60),
    "burst": (1, 5 * 60),
    "soak": (1, 4 * 60 * 60),
    "degraded-provider": (1, 5 * 60),
}
REQUIRED_EXERCISES = frozenset({"restart-catch-up", "storage-growth", "recovery"})
REQUIRED_THRESHOLD_CHECKS = frozenset(
    {
        "errorRateMax",
        "p95MsMax",
        "throughputPerSecondMin",
        "minimumRequests",
        "minimumRequestsPerTarget",
    }
)
REQUIRED_CAPACITY_WORKLOADS = frozenset(
    {
        "attachment-processing",
        "inbound-ingestion",
        "inbox-read",
        "knowledge-lookup",
        "model-execution",
        "outbound-delivery",
        "runbook-match",
        "tool-lookup",
    }
)
REQUIRED_RESOURCE_METRICS = frozenset(
    {
        "cpu",
        "memory",
        "diskIo",
        "diskFree",
        "sqliteLocks",
        "queueAge",
        "providerErrors",
        "cost",
    }
)
REQUIRED_ENVELOPE_FIELDS = frozenset(
    {
        "activeTenants",
        "concurrentInboxUsers",
        "ticketsPerDay",
        "messagesPerDay",
        "inboundEventsPerSecond",
        "outboundDeliveriesPerSecond",
        "concurrentAutomationExecutions",
        "attachmentAndKnowledgeGiB",
        "approvedRequestsPerSecond",
        "observedBottleneckRequestsPerSecond",
        "headroomPercent",
    }
)


class CapacityEvidenceError(ValueError):
    pass


def _iso_datetime(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CapacityEvidenceError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CapacityEvidenceError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CapacityEvidenceError(f"{label} must include a UTC offset")
    return parsed


def _identifier(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{2,199}", value):
        raise CapacityEvidenceError(f"{label} must be a stable 3-200 character identifier")
    return value


def _artifact_path(base: pathlib.Path, value: object, *, label: str) -> pathlib.Path:
    if not isinstance(value, str) or not value.strip():
        raise CapacityEvidenceError(f"{label}.artifact is required")
    relative = pathlib.Path(value)
    if relative.is_absolute():
        raise CapacityEvidenceError(f"{label}.artifact must be relative to the manifest")
    resolved = (base / relative).resolve()
    if base != resolved and base not in resolved.parents:
        raise CapacityEvidenceError(f"{label}.artifact escapes the manifest directory")
    return resolved


def _load_artifact(base: pathlib.Path, reference: object, *, label: str) -> dict[str, Any]:
    if not isinstance(reference, dict):
        raise CapacityEvidenceError(f"{label} must be an object")
    path = _artifact_path(base, reference.get("artifact"), label=label)
    expected_hash = reference.get("sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise CapacityEvidenceError(f"{label}.sha256 must be a lowercase SHA-256 digest")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CapacityEvidenceError(f"cannot read {label} artifact {path.name}") from exc
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise CapacityEvidenceError(f"{label} artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise CapacityEvidenceError(f"{label} artifact hash does not match")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CapacityEvidenceError(f"{label} artifact must be UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise CapacityEvidenceError(f"{label} artifact must contain a JSON object")
    return payload


def _validate_topology(payload: dict[str, Any]) -> None:
    if payload.get("observedExternally") is not True:
        raise CapacityEvidenceError("topology must be observed externally")
    if payload.get("supported") is not True or payload.get("errors") != []:
        raise CapacityEvidenceError("topology inventory is unsupported")
    if payload.get("serviceCounts") != {"app": 1, "caddy": 1, "pocketbase": 1}:
        raise CapacityEvidenceError("topology must contain exactly one app, caddy, and pocketbase service")
    containers = payload.get("containers")
    if not isinstance(containers, list) or len(containers) != 3:
        raise CapacityEvidenceError("topology must contain three inspected containers")


def _validate_load_run(
    payload: dict[str, Any],
    *,
    expected_kind: str,
    release_id: str,
    environment_id: str,
    minimum_duration: int,
) -> tuple[str, str, float, float]:
    if payload.get("releaseId") != release_id or payload.get("environmentId") != environment_id:
        raise CapacityEvidenceError(f"{expected_kind} run release/environment does not match the manifest")
    if payload.get("runKind") != expected_kind:
        raise CapacityEvidenceError(f"load run kind must be {expected_kind}")
    if payload.get("scenarioKind") != "capacity":
        raise CapacityEvidenceError(f"{expected_kind} run must use a capacity scenario, not a smoke scenario")
    workloads = payload.get("workloads")
    if (
        not isinstance(workloads, list)
        or any(not isinstance(value, str) for value in workloads)
        or not REQUIRED_CAPACITY_WORKLOADS.issubset(workloads)
    ):
        raise CapacityEvidenceError(f"{expected_kind} run is missing pilot-critical workload coverage")
    configured = payload.get("configured")
    if not isinstance(configured, dict) or float(configured.get("durationSeconds") or 0) < minimum_duration:
        raise CapacityEvidenceError(f"{expected_kind} run duration is below {minimum_duration} seconds")
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, dict) or thresholds.get("allPassed") is not True:
        raise CapacityEvidenceError(f"{expected_kind} run thresholds did not pass")
    if thresholds.get("missingRequiredChecks") != []:
        raise CapacityEvidenceError(f"{expected_kind} run has missing threshold checks")
    checks = thresholds.get("checks")
    if not isinstance(checks, dict) or not REQUIRED_THRESHOLD_CHECKS.issubset(checks):
        raise CapacityEvidenceError(f"{expected_kind} run has a vacuous threshold set")
    if any(not isinstance(check, dict) or check.get("pass") is not True for check in checks.values()):
        raise CapacityEvidenceError(f"{expected_kind} run contains a failed threshold")
    minimum_policy = {
        "minimumRequests": 100,
        "minimumRequestsPerTarget": 20,
    }
    for name, minimum in minimum_policy.items():
        target = checks[name].get("target")
        if isinstance(target, bool) or not isinstance(target, (int, float)) or target < minimum:
            raise CapacityEvidenceError(f"{expected_kind} run threshold {name} is below {minimum}")
    error_target = checks["errorRateMax"].get("target")
    p95_target = checks["p95MsMax"].get("target")
    throughput_target = checks["throughputPerSecondMin"].get("target")
    if isinstance(error_target, bool) or not isinstance(error_target, (int, float)) or not 0 <= error_target <= 0.02:
        raise CapacityEvidenceError(f"{expected_kind} run error-rate threshold is not operationally bounded")
    if isinstance(p95_target, bool) or not isinstance(p95_target, (int, float)) or not 0 < p95_target <= 2000:
        raise CapacityEvidenceError(f"{expected_kind} run p95 threshold is not operationally bounded")
    if (
        isinstance(throughput_target, bool)
        or not isinstance(throughput_target, (int, float))
        or not math.isfinite(float(throughput_target))
        or throughput_target <= 0
    ):
        raise CapacityEvidenceError(f"{expected_kind} run throughput threshold is invalid")
    throughput = payload.get("throughputPerSecond")
    elapsed = payload.get("runElapsedSeconds")
    if (
        isinstance(throughput, bool)
        or not isinstance(throughput, (int, float))
        or not math.isfinite(float(throughput))
        or throughput <= 0
        or isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or elapsed <= 0
    ):
        raise CapacityEvidenceError(f"{expected_kind} run has invalid measured throughput/timing")
    scenario_sha = payload.get("scenarioSha256")
    if not isinstance(scenario_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", scenario_sha):
        raise CapacityEvidenceError(f"{expected_kind} run has no scenario digest")
    started_at = _iso_datetime(payload.get("startedAt"), label=f"{expected_kind} run startedAt").isoformat()
    return scenario_sha, started_at, float(throughput), float(throughput_target)


def _validate_exercise(
    payload: dict[str, Any],
    *,
    expected_kind: str,
    release_id: str,
    environment_id: str,
) -> None:
    if payload.get("releaseId") != release_id or payload.get("environmentId") != environment_id:
        raise CapacityEvidenceError(f"{expected_kind} exercise release/environment does not match")
    if payload.get("kind") != expected_kind or payload.get("passed") is not True:
        raise CapacityEvidenceError(f"{expected_kind} exercise did not pass")
    observations = payload.get("observations")
    if not isinstance(observations, list) or not observations:
        raise CapacityEvidenceError(f"{expected_kind} exercise needs non-empty observations")
    started = _iso_datetime(payload.get("startedAt"), label=f"{expected_kind} exercise startedAt")
    completed = _iso_datetime(payload.get("completedAt"), label=f"{expected_kind} exercise completedAt")
    if completed <= started:
        raise CapacityEvidenceError(f"{expected_kind} exercise completion must follow its start")


def validate_manifest(manifest: dict[str, Any], *, base: pathlib.Path) -> dict[str, object]:
    if manifest.get("schemaVersion") != "1.0":
        raise CapacityEvidenceError("manifest.schemaVersion must be '1.0'")
    release_id = _identifier(manifest.get("releaseId"), label="manifest.releaseId")
    environment_id = _identifier(manifest.get("environmentId"), label="manifest.environmentId")

    topology = _load_artifact(base, manifest.get("topology"), label="topology")
    _validate_topology(topology)

    load_run_refs = manifest.get("loadRuns")
    if not isinstance(load_run_refs, list):
        raise CapacityEvidenceError("manifest.loadRuns must be a list")
    counts: Counter[str] = Counter()
    scenario_hashes: set[str] = set()
    steady_starts: set[str] = set()
    seen_artifacts: set[str] = set()
    measured_throughputs: list[float] = []
    throughput_thresholds: list[float] = []
    for index, reference in enumerate(load_run_refs):
        if not isinstance(reference, dict):
            raise CapacityEvidenceError(f"loadRuns[{index}] must be an object")
        kind = reference.get("kind")
        if kind not in LOAD_RUN_MINIMUMS:
            raise CapacityEvidenceError(f"loadRuns[{index}].kind is invalid")
        artifact = str(reference.get("artifact") or "")
        if artifact in seen_artifacts:
            raise CapacityEvidenceError("load run artifacts must be distinct")
        seen_artifacts.add(artifact)
        payload = _load_artifact(base, reference, label=f"loadRuns[{index}]")
        scenario_hash, started_at, measured_throughput, throughput_threshold = _validate_load_run(
            payload,
            expected_kind=kind,
            release_id=release_id,
            environment_id=environment_id,
            minimum_duration=LOAD_RUN_MINIMUMS[kind][1],
        )
        counts[kind] += 1
        scenario_hashes.add(scenario_hash)
        measured_throughputs.append(measured_throughput)
        throughput_thresholds.append(throughput_threshold)
        if kind == "steady":
            if started_at in steady_starts:
                raise CapacityEvidenceError("steady runs must have distinct start times")
            steady_starts.add(started_at)
    for kind, (minimum_count, _) in LOAD_RUN_MINIMUMS.items():
        if counts[kind] < minimum_count:
            raise CapacityEvidenceError(f"manifest requires at least {minimum_count} {kind} run(s)")
    if len(scenario_hashes) != 1:
        raise CapacityEvidenceError("all load runs must use the same immutable capacity scenario")

    exercise_refs = manifest.get("exercises")
    if not isinstance(exercise_refs, list):
        raise CapacityEvidenceError("manifest.exercises must be a list")
    exercise_kinds: set[str] = set()
    for index, reference in enumerate(exercise_refs):
        if not isinstance(reference, dict) or reference.get("kind") not in REQUIRED_EXERCISES:
            raise CapacityEvidenceError(f"exercises[{index}].kind is invalid")
        kind = str(reference["kind"])
        if kind in exercise_kinds:
            raise CapacityEvidenceError(f"exercise {kind} is duplicated")
        exercise_kinds.add(kind)
        payload = _load_artifact(base, reference, label=f"exercises[{index}]")
        _validate_exercise(
            payload,
            expected_kind=kind,
            release_id=release_id,
            environment_id=environment_id,
        )
    if exercise_kinds != REQUIRED_EXERCISES:
        missing = ", ".join(sorted(REQUIRED_EXERCISES - exercise_kinds))
        raise CapacityEvidenceError(f"manifest missing required exercises: {missing}")

    resource_payload = _load_artifact(base, manifest.get("resourceEvidence"), label="resourceEvidence")
    if resource_payload.get("releaseId") != release_id or resource_payload.get("environmentId") != environment_id:
        raise CapacityEvidenceError("resource evidence release/environment does not match")
    metrics = resource_payload.get("metrics")
    if not isinstance(metrics, dict) or not REQUIRED_RESOURCE_METRICS.issubset(metrics):
        raise CapacityEvidenceError("resource evidence is missing required metrics")
    for name in REQUIRED_RESOURCE_METRICS:
        metric = metrics[name]
        if not isinstance(metric, dict) or metric.get("pass") is not True:
            raise CapacityEvidenceError(f"resource metric {name} did not pass")
        observed = metric.get("observed")
        if isinstance(observed, bool) or not isinstance(observed, (int, float)) or not math.isfinite(float(observed)):
            raise CapacityEvidenceError(f"resource metric {name} has no finite observation")
        if not isinstance(metric.get("unit"), str) or not metric["unit"].strip():
            raise CapacityEvidenceError(f"resource metric {name} has no unit")

    envelope = manifest.get("operatingEnvelope")
    if not isinstance(envelope, dict) or not REQUIRED_ENVELOPE_FIELDS.issubset(envelope):
        raise CapacityEvidenceError("operatingEnvelope is incomplete")
    for name in REQUIRED_ENVELOPE_FIELDS:
        value = envelope[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value <= 0:
            raise CapacityEvidenceError(f"operatingEnvelope.{name} must be positive")
    if float(envelope["headroomPercent"]) < 30:
        raise CapacityEvidenceError("operatingEnvelope.headroomPercent must be at least 30")
    approved_rate = float(envelope["approvedRequestsPerSecond"])
    bottleneck_rate = float(envelope["observedBottleneckRequestsPerSecond"])
    if approved_rate >= bottleneck_rate:
        raise CapacityEvidenceError("approved request rate must remain below the observed bottleneck")
    calculated_headroom = (1 - approved_rate / bottleneck_rate) * 100
    if calculated_headroom + 0.001 < 30 or abs(calculated_headroom - float(envelope["headroomPercent"])) > 0.5:
        raise CapacityEvidenceError("operating envelope headroom does not match the approved/bottleneck rates")
    if any(value < approved_rate for value in measured_throughputs):
        raise CapacityEvidenceError("a measured load-run throughput is below the approved request rate")
    if any(value < approved_rate for value in throughput_thresholds):
        raise CapacityEvidenceError("a load-run throughput threshold is below the approved request rate")

    approvals = manifest.get("approvals")
    if not isinstance(approvals, dict):
        raise CapacityEvidenceError("manifest.approvals must be an object")
    for role in ("architecture", "operations"):
        approval = approvals.get(role)
        if not isinstance(approval, dict) or approval.get("decision") != "approved":
            raise CapacityEvidenceError(f"{role} approval is missing")
        _identifier(approval.get("approvedBy"), label=f"approvals.{role}.approvedBy")
        _iso_datetime(approval.get("approvedAt"), label=f"approvals.{role}.approvedAt")

    return {
        "schemaVersion": "1.0",
        "accepted": True,
        "releaseId": release_id,
        "environmentId": environment_id,
        "scenarioSha256": next(iter(scenario_hashes)),
        "loadRunCounts": dict(sorted(counts.items())),
        "operatingEnvelope": envelope,
        "topologyInventorySha256": topology.get("inventorySha256"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = pathlib.Path(args.manifest).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise CapacityEvidenceError("manifest must contain a JSON object")
        result = validate_manifest(manifest, base=manifest_path.parent)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, CapacityEvidenceError) as exc:
        print(f"capacity evidence rejected: {exc}", file=sys.stderr)
        return 1
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
