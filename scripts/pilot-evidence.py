#!/usr/bin/env python3
"""Validate and summarize a Mantly design-partner pilot evidence folder."""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import yaml

HANDLING_CLASSIFICATIONS = {
    "verified_autonomous",
    "autonomous_candidate_observing",
    "assisted",
    "manual",
    "failed_automation",
    "excluded",
}
DECISIONS = {
    "pay_and_continue",
    "commercial_trial",
    "expand",
    "iterate_and_repeat",
    "pause",
    "stop_or_reject",
}
REQUIRED_REPORT_HEADINGS = (
    "## Scope and deviations",
    "## Sample and exclusions",
    "## Baseline",
    "## KPI results",
    "## Runbook results",
    "## Safety and quality",
    "## Reliability and recovery",
    "## Operator and customer feedback",
    "## Commercial decision",
    "## Follow-up work",
)
REQUIRED_TARGET_PATHS = (
    ("schema_version",),
    ("pilot_id",),
    ("customer_identifier",),
    ("operational_owner",),
    ("economic_buyer",),
    ("pilot_window", "start"),
    ("pilot_window", "end"),
    ("mailbox_or_queue",),
    ("workflow",),
    ("minimum_eligible_ticket_count",),
    ("observation_window_days",),
    ("baseline", "start"),
    ("baseline", "end"),
    ("baseline", "labour_cost_per_hour"),
    ("runbooks",),
    ("targets", "verified_full_automation_rate_min"),
    ("targets", "recurring_cost_reduction_min"),
    ("targets", "runbook_match_precision_min"),
    ("targets", "critical_outcomes_max"),
    ("targets", "unsafe_or_materially_incorrect_rate_max"),
    ("commercial_decision_date",),
    ("approvals", "product_owner"),
    ("approvals", "engineering_owner"),
    ("approvals", "customer_operational_owner"),
)
BASELINE_REQUIRED_COLUMNS = {
    "ticket_id",
    "received_at",
    "first_response_at",
    "resolved_at",
    "human_minutes",
    "labour_cost",
    "other_cost",
    "runbook_id",
}


@dataclass(frozen=True)
class EvidencePaths:
    root: pathlib.Path
    targets: pathlib.Path
    metrics: pathlib.Path
    baseline: pathlib.Path
    report: pathlib.Path
    decision: pathlib.Path
    risk_register: pathlib.Path


class EvidenceError(ValueError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("validate", "summarize"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("folder", help="Pilot evidence folder")
        subparser.add_argument(
            "--allow-incomplete-sample",
            action="store_true",
            help="Allow eligible ticket count below the approved minimum; intended only for fixtures or an approved exception.",
        )
        subparser.add_argument(
            "--now",
            default="",
            help="Override current UTC time for deterministic verification, e.g. 2026-07-16T00:00:00Z.",
        )
        if command == "summarize":
            subparser.add_argument("--json-out", default="summary.json")
            subparser.add_argument("--markdown-out", default="summary.md")
    return parser.parse_args()


def evidence_paths(folder: str) -> EvidencePaths:
    root = pathlib.Path(folder).resolve()
    return EvidencePaths(
        root=root,
        targets=root / "targets.yml",
        metrics=root / "ticket-metrics.ndjson",
        baseline=root / "baseline.csv",
        report=root / "report.md",
        decision=root / "decision.yml",
        risk_register=root / "risk-register.md",
    )


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EvidenceError(f"cannot read YAML {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvidenceError(f"{path.name} must contain a YAML object")
    return data


def value_at(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            raise EvidenceError(f"targets.yml is missing {'.'.join(path)}")
        current = current[part]
    return current


def require_approved_targets(targets: dict[str, Any]) -> None:
    for path in REQUIRED_TARGET_PATHS:
        value = value_at(targets, path)
        if value is None or value == "" or value == []:
            raise EvidenceError(f"targets.yml value {'.'.join(path)} is not approved/completed")

    if targets.get("schema_version") != "1.0":
        raise EvidenceError("targets.yml schema_version must be 1.0")
    if not isinstance(targets.get("minimum_eligible_ticket_count"), int) or targets["minimum_eligible_ticket_count"] <= 0:
        raise EvidenceError("minimum_eligible_ticket_count must be a positive integer")
    if not isinstance(targets.get("observation_window_days"), int) or targets["observation_window_days"] < 0:
        raise EvidenceError("observation_window_days must be a non-negative integer")

    runbooks = targets.get("runbooks")
    if not isinstance(runbooks, list) or len(runbooks) != 3:
        raise EvidenceError("targets.yml must approve exactly three runbooks")
    observed: set[tuple[str, str]] = set()
    for index, runbook in enumerate(runbooks):
        if not isinstance(runbook, dict):
            raise EvidenceError(f"runbooks[{index}] must be an object")
        runbook_id = runbook.get("id")
        version = runbook.get("version")
        autonomy = runbook.get("autonomy")
        if not isinstance(runbook_id, str) or not runbook_id:
            raise EvidenceError(f"runbooks[{index}].id is required")
        if not isinstance(version, str) or not version:
            raise EvidenceError(f"runbooks[{index}].version is required")
        if autonomy not in {"automatic", "semi-automatic", "manual"}:
            raise EvidenceError(f"runbooks[{index}].autonomy is invalid")
        key = (runbook_id, version)
        if key in observed:
            raise EvidenceError(f"duplicate runbook/version in targets.yml: {runbook_id}@{version}")
        observed.add(key)

    for name, value in targets.get("targets", {}).items():
        if name.endswith("_rate_min") or name.endswith("_rate_max") or name.endswith("_reduction_min") or name.endswith("_precision_min"):
            if value is not None and (not isinstance(value, (int, float)) or not 0 <= float(value) <= 1):
                raise EvidenceError(f"target {name} must be null or a number between 0 and 1")


def parse_timestamp(value: Any, field: str, *, allow_none: bool = True) -> datetime | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value:
        raise EvidenceError(f"{field} must be an ISO-8601 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise EvidenceError(f"{field} is not a valid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise EvidenceError(f"{field} must contain a timezone: {value}")
    return parsed.astimezone(timezone.utc)


def load_metrics(path: pathlib.Path) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvidenceError(f"cannot read {path.name}: {exc}") from exc

    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"{path.name}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(item, dict):
            raise EvidenceError(f"{path.name}:{line_number}: each record must be an object")
        item["_line"] = line_number
        metrics.append(item)
    if not metrics:
        raise EvidenceError(f"{path.name} contains no metric records")
    return metrics


def validate_metrics(
    metrics: list[dict[str, Any]],
    targets: dict[str, Any],
    now: datetime,
    *,
    allow_incomplete_sample: bool,
) -> None:
    seen_ticket_ids: set[str] = set()
    seen_source_ids: set[str] = set()
    approved_runbooks = {(item["id"], item["version"]) for item in targets["runbooks"]}

    for item in metrics:
        line = item["_line"]
        prefix = f"ticket-metrics.ndjson:{line}"
        for field in ("schema_version", "pilot_id", "tenant_id", "ticket_id", "source_message_id", "received_at", "eligibility", "handling_classification"):
            if item.get(field) in (None, ""):
                raise EvidenceError(f"{prefix}: missing required field {field}")
        if item["schema_version"] != "1.0":
            raise EvidenceError(f"{prefix}: schema_version must be 1.0")
        if item["pilot_id"] != targets["pilot_id"]:
            raise EvidenceError(f"{prefix}: pilot_id does not match targets.yml")

        ticket_id = str(item["ticket_id"])
        source_id = str(item["source_message_id"])
        if ticket_id in seen_ticket_ids:
            raise EvidenceError(f"{prefix}: duplicate ticket_id {ticket_id}")
        if source_id in seen_source_ids:
            raise EvidenceError(f"{prefix}: duplicate source_message_id {source_id}")
        seen_ticket_ids.add(ticket_id)
        seen_source_ids.add(source_id)

        classification = item["handling_classification"]
        if classification not in HANDLING_CLASSIFICATIONS:
            raise EvidenceError(f"{prefix}: invalid handling_classification {classification}")
        eligibility = item["eligibility"]
        if eligibility not in {"eligible", "excluded"}:
            raise EvidenceError(f"{prefix}: eligibility must be eligible or excluded")
        if eligibility == "excluded":
            if classification != "excluded" or not item.get("exclusion_reason"):
                raise EvidenceError(f"{prefix}: excluded records require classification=excluded and exclusion_reason")
        elif classification == "excluded":
            raise EvidenceError(f"{prefix}: eligible record cannot use classification=excluded")

        received = parse_timestamp(item.get("received_at"), f"{prefix}.received_at", allow_none=False)
        first_response = parse_timestamp(item.get("first_response_at"), f"{prefix}.first_response_at")
        resolved = parse_timestamp(item.get("resolved_at"), f"{prefix}.resolved_at")
        observation_end = parse_timestamp(item.get("observation_window_end"), f"{prefix}.observation_window_end")
        assert received is not None
        if first_response and first_response < received:
            raise EvidenceError(f"{prefix}: first_response_at precedes received_at")
        if resolved and resolved < received:
            raise EvidenceError(f"{prefix}: resolved_at precedes received_at")
        if observation_end and resolved and observation_end < resolved:
            raise EvidenceError(f"{prefix}: observation_window_end precedes resolved_at")

        runbook_id = item.get("runbook_id")
        runbook_version = item.get("runbook_version")
        if runbook_id or runbook_version:
            if (runbook_id, runbook_version) not in approved_runbooks:
                raise EvidenceError(f"{prefix}: unapproved runbook/version {runbook_id}@{runbook_version}")

        for integer_field in ("human_touch_count", "action_attempts", "action_failures", "delivery_attempts", "input_tokens", "output_tokens"):
            value = item.get(integer_field, 0)
            if not isinstance(value, int) or value < 0:
                raise EvidenceError(f"{prefix}: {integer_field} must be a non-negative integer")
        for numeric_field in ("llm_cost", "tool_and_delivery_cost", "human_minutes"):
            value = item.get(numeric_field, 0)
            if not isinstance(value, (int, float)) or value < 0:
                raise EvidenceError(f"{prefix}: {numeric_field} must be a non-negative number")
        confidence = item.get("match_confidence")
        if confidence is not None and (not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
            raise EvidenceError(f"{prefix}: match_confidence must be null or between 0 and 1")
        if item.get("action_failures", 0) > item.get("action_attempts", 0):
            raise EvidenceError(f"{prefix}: action_failures cannot exceed action_attempts")

        if classification == "verified_autonomous":
            if item.get("human_touch_count", 0) != 0:
                raise EvidenceError(f"{prefix}: verified autonomous ticket has human touches")
            if not resolved or not observation_end or observation_end > now:
                raise EvidenceError(f"{prefix}: verified autonomous ticket requires a completed observation window")
            if item.get("review_result") != "pass":
                raise EvidenceError(f"{prefix}: verified autonomous ticket requires review_result=pass")
            if item.get("delivery_status") not in {"sent", "delivered", "not_required"}:
                raise EvidenceError(f"{prefix}: verified autonomous ticket requires successful delivery status")
            if item.get("recovery_required") is True:
                raise EvidenceError(f"{prefix}: verified autonomous ticket required recovery")
            if item.get("unsafe_or_materially_incorrect") is True or item.get("critical_outcome") is True:
                raise EvidenceError(f"{prefix}: unsafe/critical ticket cannot be verified autonomous")

    eligible_count = sum(item["eligibility"] == "eligible" for item in metrics)
    if eligible_count < targets["minimum_eligible_ticket_count"] and not allow_incomplete_sample:
        raise EvidenceError(
            f"eligible sample {eligible_count} is below approved minimum {targets['minimum_eligible_ticket_count']}"
        )


def load_baseline(path: pathlib.Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise EvidenceError("baseline.csv has no header")
            missing = BASELINE_REQUIRED_COLUMNS - set(reader.fieldnames)
            if missing:
                raise EvidenceError(f"baseline.csv missing columns: {', '.join(sorted(missing))}")
            rows = list(reader)
    except OSError as exc:
        raise EvidenceError(f"cannot read baseline.csv: {exc}") from exc
    if not rows:
        raise EvidenceError("baseline.csv contains no records")

    seen: set[str] = set()
    for line_number, row in enumerate(rows, start=2):
        ticket_id = row.get("ticket_id", "")
        if not ticket_id:
            raise EvidenceError(f"baseline.csv:{line_number}: ticket_id is required")
        if ticket_id in seen:
            raise EvidenceError(f"baseline.csv:{line_number}: duplicate ticket_id {ticket_id}")
        seen.add(ticket_id)
        received = parse_timestamp(row.get("received_at"), f"baseline.csv:{line_number}.received_at", allow_none=False)
        first_response = parse_timestamp(row.get("first_response_at"), f"baseline.csv:{line_number}.first_response_at")
        resolved = parse_timestamp(row.get("resolved_at"), f"baseline.csv:{line_number}.resolved_at")
        assert received is not None
        if first_response and first_response < received:
            raise EvidenceError(f"baseline.csv:{line_number}: first response precedes receipt")
        if resolved and resolved < received:
            raise EvidenceError(f"baseline.csv:{line_number}: resolution precedes receipt")
        for field in ("human_minutes", "labour_cost", "other_cost"):
            try:
                value = float(row.get(field, ""))
            except ValueError as exc:
                raise EvidenceError(f"baseline.csv:{line_number}: {field} must be numeric") from exc
            if value < 0:
                raise EvidenceError(f"baseline.csv:{line_number}: {field} cannot be negative")
    return rows


def validate_documents(paths: EvidencePaths) -> dict[str, Any]:
    try:
        report = paths.report.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceError(f"cannot read report.md: {exc}") from exc
    if not report.startswith("# Pilot report"):
        raise EvidenceError("report.md must start with '# Pilot report'")
    for heading in REQUIRED_REPORT_HEADINGS:
        if heading not in report:
            raise EvidenceError(f"report.md missing required heading: {heading}")

    decision = load_yaml(paths.decision)
    if decision.get("schema_version") != "1.0":
        raise EvidenceError("decision.yml schema_version must be 1.0")
    if decision.get("decision") not in DECISIONS:
        raise EvidenceError(f"decision.yml decision must be one of: {', '.join(sorted(DECISIONS))}")
    for field in ("decision_date", "decided_by", "rationale", "evidence_refs"):
        value = decision.get(field)
        if value is None or value == "" or value == []:
            raise EvidenceError(f"decision.yml {field} is required")
    if not isinstance(decision.get("decided_by"), list) or not all(
        isinstance(value, str) and value for value in decision["decided_by"]
    ):
        raise EvidenceError("decision.yml decided_by must be a non-empty string list")
    if not isinstance(decision.get("evidence_refs"), list) or not all(
        isinstance(value, str) and value for value in decision["evidence_refs"]
    ):
        raise EvidenceError("decision.yml evidence_refs must be a non-empty string list")

    try:
        risk_register = paths.risk_register.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceError(f"cannot read risk-register.md: {exc}") from exc
    for required in ("# Pilot risk register", "## Open risks", "## Closed or accepted risks"):
        if required not in risk_register:
            raise EvidenceError(f"risk-register.md missing required heading: {required}")
    return decision


def percentile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def duration_seconds(start: Any, end: Any, start_field: str, end_field: str) -> float | None:
    start_dt = parse_timestamp(start, start_field, allow_none=False)
    end_dt = parse_timestamp(end, end_field)
    if end_dt is None:
        return None
    assert start_dt is not None
    return (end_dt - start_dt).total_seconds()


def timing_summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "medianSeconds": statistics.median(values) if values else None,
        "p90Seconds": percentile(values, 0.90),
        "p95Seconds": percentile(values, 0.95),
    }


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def baseline_summary(rows: list[dict[str, str]], labour_rate: float) -> dict[str, Any]:
    first_response_values: list[float] = []
    resolution_values: list[float] = []
    costs: list[float] = []
    by_runbook: Counter[str] = Counter()

    for index, row in enumerate(rows, start=2):
        response = duration_seconds(row["received_at"], row["first_response_at"], f"baseline:{index}.received", f"baseline:{index}.response")
        resolution = duration_seconds(row["received_at"], row["resolved_at"], f"baseline:{index}.received", f"baseline:{index}.resolved")
        if response is not None:
            first_response_values.append(response)
        if resolution is not None:
            resolution_values.append(resolution)
        explicit_labour_cost = float(row["labour_cost"])
        labour_cost = explicit_labour_cost or (float(row["human_minutes"]) / 60 * labour_rate)
        costs.append(labour_cost + float(row["other_cost"]))
        by_runbook[row.get("runbook_id") or "unclassified"] += 1

    return {
        "ticketCount": len(rows),
        "costTotal": sum(costs),
        "costPerTicket": sum(costs) / len(costs),
        "firstResponse": timing_summary(first_response_values),
        "resolution": timing_summary(resolution_values),
        "byRunbook": dict(sorted(by_runbook.items())),
    }


def summarize(metrics: list[dict[str, Any]], baseline: list[dict[str, str]], targets: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    eligible = [item for item in metrics if item["eligibility"] == "eligible"]
    excluded = [item for item in metrics if item["eligibility"] == "excluded"]
    classifications = Counter(item["handling_classification"] for item in eligible)
    by_runbook_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in eligible:
        by_runbook_records[str(item.get("runbook_id") or "no-match")].append(item)

    selected = [item for item in eligible if item.get("runbook_id")]
    reviewed_matches = [item for item in selected if item.get("match_review") in {"correct", "incorrect"}]
    correct_matches = [item for item in reviewed_matches if item.get("match_review") == "correct"]
    materially_influenced = [item for item in eligible if item["handling_classification"] not in {"manual"}]
    unsafe = [item for item in materially_influenced if item.get("unsafe_or_materially_incorrect") is True]
    critical = [item for item in eligible if item.get("critical_outcome") is True]

    first_response_values = [
        value
        for item in eligible
        if (value := duration_seconds(item["received_at"], item.get("first_response_at"), "received_at", "first_response_at")) is not None
    ]
    resolution_values = [
        value
        for item in eligible
        if (value := duration_seconds(item["received_at"], item.get("resolved_at"), "received_at", "resolved_at")) is not None
    ]

    labour_rate = float(targets["baseline"]["labour_cost_per_hour"])
    pilot_cost_total = sum(
        float(item.get("human_minutes", 0)) / 60 * labour_rate
        + float(item.get("llm_cost", 0))
        + float(item.get("tool_and_delivery_cost", 0))
        for item in eligible
    )
    baseline_result = baseline_summary(baseline, labour_rate)
    pilot_cost_per_ticket = pilot_cost_total / len(eligible) if eligible else None
    baseline_cost_per_ticket = baseline_result["costPerTicket"]
    cost_reduction = (
        (baseline_cost_per_ticket - pilot_cost_per_ticket) / baseline_cost_per_ticket
        if pilot_cost_per_ticket is not None and baseline_cost_per_ticket > 0
        else None
    )

    full_automation_rate = rate(classifications["verified_autonomous"], len(eligible))
    match_precision = rate(len(correct_matches), len(reviewed_matches))
    match_coverage = rate(len(selected), len(eligible))
    unsafe_rate = rate(len(unsafe), len(materially_influenced))

    by_runbook: dict[str, Any] = {}
    for runbook_id, records in sorted(by_runbook_records.items()):
        counts = Counter(item["handling_classification"] for item in records)
        reviewed = [item for item in records if item.get("match_review") in {"correct", "incorrect"}]
        correct = [item for item in reviewed if item.get("match_review") == "correct"]
        by_runbook[runbook_id] = {
            "eligibleTickets": len(records),
            "handling": dict(sorted(counts.items())),
            "verifiedAutomationRate": rate(counts["verified_autonomous"], len(records)),
            "matchPrecision": rate(len(correct), len(reviewed)),
            "unsafeOrMateriallyIncorrect": sum(item.get("unsafe_or_materially_incorrect") is True for item in records),
            "criticalOutcomes": sum(item.get("critical_outcome") is True for item in records),
            "actionFailures": sum(int(item.get("action_failures", 0)) for item in records),
            "manualRecoveries": sum(item.get("recovery_required") is True for item in records),
        }

    target_values = targets["targets"]
    target_results = {
        "verifiedFullAutomationRate": {
            "actual": full_automation_rate,
            "target": target_values["verified_full_automation_rate_min"],
            "pass": full_automation_rate is not None and full_automation_rate >= float(target_values["verified_full_automation_rate_min"]),
        },
        "recurringCostReduction": {
            "actual": cost_reduction,
            "target": target_values["recurring_cost_reduction_min"],
            "pass": cost_reduction is not None and cost_reduction >= float(target_values["recurring_cost_reduction_min"]),
        },
        "runbookMatchPrecision": {
            "actual": match_precision,
            "target": target_values["runbook_match_precision_min"],
            "pass": match_precision is not None and match_precision >= float(target_values["runbook_match_precision_min"]),
        },
        "criticalOutcomes": {
            "actual": len(critical),
            "target": target_values["critical_outcomes_max"],
            "pass": len(critical) <= int(target_values["critical_outcomes_max"]),
        },
        "unsafeOrMateriallyIncorrectRate": {
            "actual": unsafe_rate,
            "target": target_values["unsafe_or_materially_incorrect_rate_max"],
            "pass": unsafe_rate is not None and unsafe_rate <= float(target_values["unsafe_or_materially_incorrect_rate_max"]),
        },
    }

    return {
        "schemaVersion": "1.0",
        "pilotId": targets["pilot_id"],
        "customerIdentifier": targets["customer_identifier"],
        "sample": {
            "records": len(metrics),
            "eligible": len(eligible),
            "excluded": len(excluded),
            "exclusions": dict(sorted(Counter(str(item.get("exclusion_reason")) for item in excluded).items())),
        },
        "handling": dict(sorted(classifications.items())),
        "verifiedFullAutomationRate": full_automation_rate,
        "runbookMatchPrecision": match_precision,
        "runbookMatchCoverage": match_coverage,
        "unsafeOrMateriallyIncorrectRate": unsafe_rate,
        "criticalOutcomes": len(critical),
        "actionAttempts": sum(int(item.get("action_attempts", 0)) for item in eligible),
        "actionFailures": sum(int(item.get("action_failures", 0)) for item in eligible),
        "manualRecoveries": sum(item.get("recovery_required") is True for item in eligible),
        "firstResponse": timing_summary(first_response_values),
        "resolution": timing_summary(resolution_values),
        "cost": {
            "pilotTotal": pilot_cost_total,
            "pilotPerEligibleTicket": pilot_cost_per_ticket,
            "baselinePerTicket": baseline_cost_per_ticket,
            "recurringReduction": cost_reduction,
        },
        "baseline": baseline_result,
        "byRunbook": by_runbook,
        "targets": target_results,
        "allTargetsPassed": all(result["pass"] for result in target_results.values()),
        "commercialDecision": decision["decision"],
        "commercialDecisionDate": decision["decision_date"],
    }


def percentage(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}s"


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Pilot KPI summary",
        "",
        f"- Pilot: `{summary['pilotId']}`",
        f"- Customer: `{summary['customerIdentifier']}`",
        f"- Eligible tickets: **{summary['sample']['eligible']}**",
        f"- Excluded tickets: **{summary['sample']['excluded']}**",
        f"- Verified full-automation rate: **{percentage(summary['verifiedFullAutomationRate'])}**",
        f"- Runbook match precision: **{percentage(summary['runbookMatchPrecision'])}**",
        f"- Unsafe/materially incorrect rate: **{percentage(summary['unsafeOrMateriallyIncorrectRate'])}**",
        f"- Critical outcomes: **{summary['criticalOutcomes']}**",
        f"- Recurring cost reduction: **{percentage(summary['cost']['recurringReduction'])}**",
        f"- Commercial decision: **{summary['commercialDecision']}**",
        "",
        "## Target evaluation",
        "",
        "| KPI | Actual | Target | Pass |",
        "| --- | ---: | ---: | :---: |",
    ]
    for name, result in summary["targets"].items():
        actual = result["actual"]
        target = result["target"]
        if "Rate" in name or "Reduction" in name or "Precision" in name:
            actual_text = percentage(actual)
            target_text = percentage(float(target))
        else:
            actual_text = str(actual)
            target_text = str(target)
        lines.append(f"| {name} | {actual_text} | {target_text} | {'yes' if result['pass'] else 'no'} |")

    lines.extend(
        [
            "",
            "## Timing",
            "",
            "| Metric | Median | p90 | p95 |",
            "| --- | ---: | ---: | ---: |",
            f"| First response | {seconds(summary['firstResponse']['medianSeconds'])} | {seconds(summary['firstResponse']['p90Seconds'])} | {seconds(summary['firstResponse']['p95Seconds'])} |",
            f"| Resolution | {seconds(summary['resolution']['medianSeconds'])} | {seconds(summary['resolution']['p90Seconds'])} | {seconds(summary['resolution']['p95Seconds'])} |",
            "",
            "## Runbooks",
            "",
            "| Runbook | Eligible | Verified automation | Match precision | Critical |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for runbook_id, result in summary["byRunbook"].items():
        lines.append(
            f"| {runbook_id} | {result['eligibleTickets']} | {percentage(result['verifiedAutomationRate'])} | {percentage(result['matchPrecision'])} | {result['criticalOutcomes']} |"
        )
    lines.extend(
        [
            "",
            f"**All precommitted targets passed:** {'yes' if summary['allTargetsPassed'] else 'no'}",
            "",
            "This summary is generated from the validated evidence folder. It does not replace the narrative report, safety review, confidence limitations, or customer decision evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    paths = evidence_paths(args.folder)
    if not paths.root.is_dir():
        raise EvidenceError(f"evidence folder does not exist: {paths.root}")
    targets = load_yaml(paths.targets)
    require_approved_targets(targets)
    now = parse_timestamp(args.now, "--now", allow_none=False) if args.now else datetime.now(timezone.utc)
    assert now is not None
    metrics = load_metrics(paths.metrics)
    validate_metrics(metrics, targets, now, allow_incomplete_sample=args.allow_incomplete_sample)
    baseline = load_baseline(paths.baseline)
    decision = validate_documents(paths)

    summary = summarize(metrics, baseline, targets, decision)
    result = {
        "schemaVersion": "1.0",
        "ok": True,
        "folder": str(paths.root),
        "eligibleTickets": summary["sample"]["eligible"],
        "excludedTickets": summary["sample"]["excluded"],
        "allTargetsPassed": summary["allTargetsPassed"],
        "commercialDecision": summary["commercialDecision"],
    }

    if args.command == "summarize":
        json_out = pathlib.Path(args.json_out)
        markdown_out = pathlib.Path(args.markdown_out)
        if not json_out.is_absolute():
            json_out = paths.root / json_out
        if not markdown_out.is_absolute():
            markdown_out = paths.root / markdown_out
        json_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown_out.write_text(render_markdown(summary), encoding="utf-8")
        result["summaryJson"] = str(json_out)
        result["summaryMarkdown"] = str(markdown_out)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    args = parse_args()
    try:
        return run(args)
    except EvidenceError as exc:
        print(json.dumps({"schemaVersion": "1.0", "ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
