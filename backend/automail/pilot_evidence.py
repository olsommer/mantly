"""Fail-closed validation for pilot metric records, targets, and pass decisions."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final, Literal, cast

import yaml
from jsonschema import Draft202012Validator, FormatChecker

Comparison = Literal[">=", "<="]

KPI_OPERATORS: Final[dict[str, Comparison]] = {
    "verified_full_automation_rate": ">=",
    "recurring_cost_reduction_rate": ">=",
    "unsafe_or_materially_incorrect_outcome_rate": "<=",
    "customer_continuation_score": ">=",
    "runbook_match_precision": ">=",
    "runbook_match_coverage": ">=",
    "draft_acceptance_rate": ">=",
    "human_escalation_rate": "<=",
    "first_response_time_p90_seconds": "<=",
    "resolution_time_p90_seconds": "<=",
    "failed_action_rate": "<=",
    "manual_recovery_rate": "<=",
    "variable_ai_and_delivery_cost_per_eligible_ticket_eur": "<=",
    "variable_ai_and_delivery_cost_per_verified_autonomous_ticket_eur": "<=",
    "quality_review_pass_rate": ">=",
}

GUARD_OPERATORS: Final[dict[str, Comparison]] = {
    "critical_outcome_count": "<=",
    "unsafe_or_materially_incorrect_outcome_count": "<=",
    "tenant_isolation_incident_count": "<=",
    "duplicate_irreversible_side_effect_count": "<=",
    "schema_validation_error_count": "<=",
    "semantic_validation_error_count": "<=",
    "missing_required_evidence_count": "<=",
    "unknown_outcome_count": "<=",
    "unresolved_eligible_ticket_count": "<=",
    "required_review_sample_completion_rate": ">=",
}

REQUIRED_EVIDENCE_FLAGS: Final[tuple[str, ...]] = (
    "target_contract_approved",
    "baseline_uses_same_population_rules",
    "metric_records_schema_validated",
    "metric_records_semantically_validated",
    "results_reproducible",
)

ALLOWED_CUSTOMER_DECISIONS: Final[dict[str, int]] = {
    "pay": 1,
    "continue": 1,
    "expand": 1,
    "iterate": 0,
    "pause": 0,
    "stop": 0,
}

REQUIRED_RUNBOOK_IDS: Final[set[str]] = {
    "delivery-status",
    "delivery-address-change",
    "cancellation-or-refund-eligibility",
}

PLACEHOLDER_MARKERS: Final[tuple[str, ...]] = (
    "replace-",
    "yyyy-",
    "name-or-role",
    "support@example.com",
)

ELIGIBLE_ONLY_FIELDS: Final[set[str]] = {
    "first_response_at",
    "resolved_at",
    "observation_window_end",
    "runbook_id",
    "runbook_version",
    "match_confidence",
    "match_review",
    "autonomous_candidate",
    "human_touch_count",
    "approval_required",
    "draft_generated",
    "material_edit",
    "action_attempts",
    "action_failures",
    "duplicate_side_effect",
    "delivery_status",
    "delivery_attempts",
    "review_result",
    "review_categories",
    "unsafe_or_materially_incorrect",
    "critical_outcome",
    "recovery_required",
    "model_provider",
    "model_name",
    "input_tokens",
    "output_tokens",
    "llm_cost",
    "tool_and_delivery_cost",
    "human_minutes",
}


class PilotEvidenceError(ValueError):
    """Raised when pilot evidence violates the precommitted contract."""


@dataclass(frozen=True)
class PilotEvaluation:
    """Strict pilot evaluation result."""

    passed: bool
    failures: tuple[str, ...]


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise PilotEvidenceError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise PilotEvidenceError(f"{label} must be an array")
    return cast(list[object], value)


def _text(value: object, label: str, *, completed: bool = True) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PilotEvidenceError(f"{label} must be a non-empty string")
    clean = value.strip()
    if completed and any(marker in clean.lower() for marker in PLACEHOLDER_MARKERS):
        raise PilotEvidenceError(f"{label} still contains a template placeholder")
    return clean


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PilotEvidenceError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise PilotEvidenceError(f"{label} must be a finite number")
    return result


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PilotEvidenceError(f"{label} must be an integer")
    return value


def _iso_date(value: object, label: str, *, completed: bool) -> str:
    raw = _text(value, label, completed=completed)
    if completed:
        try:
            date.fromisoformat(raw)
        except ValueError as exc:
            raise PilotEvidenceError(f"{label} must be an ISO date") from exc
    return raw


def _iso_datetime(value: object, label: str) -> datetime:
    raw = _text(value, label)
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise PilotEvidenceError(f"{label} must be an RFC 3339 date-time") from exc
    if parsed.tzinfo is None:
        raise PilotEvidenceError(f"{label} must include a timezone")
    return parsed


def load_yaml_mapping(path: Path) -> Mapping[str, object]:
    """Load a YAML object without accepting an empty or scalar document."""

    loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _mapping(loaded, str(path))


def load_metric_schema(path: Path) -> Mapping[str, object]:
    """Load and validate the checked-in Draft 2020-12 metric schema."""

    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    schema = _mapping(loaded, str(path))
    Draft202012Validator.check_schema(schema)
    return schema


def validate_metric_record(record: Mapping[str, object], schema: Mapping[str, object]) -> None:
    """Validate one metric record with JSON Schema plus cross-field semantics."""

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(cast(Any, record)),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise PilotEvidenceError(f"metric record failed JSON Schema validation: {details}")

    eligibility = cast(str, record["eligibility"])
    if eligibility == "excluded":
        present = sorted(ELIGIBLE_ONLY_FIELDS.intersection(record))
        if present:
            raise PilotEvidenceError(
                "excluded metric record contains eligible-only fields: " + ", ".join(present)
            )
        return

    received_at = _iso_datetime(record["received_at"], "received_at")
    first_response_at = _iso_datetime(record["first_response_at"], "first_response_at")
    resolved_at = _iso_datetime(record["resolved_at"], "resolved_at")
    if first_response_at < received_at:
        raise PilotEvidenceError("first_response_at precedes received_at")
    if resolved_at < first_response_at:
        raise PilotEvidenceError("resolved_at precedes first_response_at")
    if "observation_window_end" in record:
        observation_window_end = _iso_datetime(
            record["observation_window_end"],
            "observation_window_end",
        )
        if observation_window_end < resolved_at:
            raise PilotEvidenceError("observation_window_end precedes resolved_at")

    action_attempts = _integer(record["action_attempts"], "action_attempts")
    action_failures = _integer(record["action_failures"], "action_failures")
    if action_failures > action_attempts:
        raise PilotEvidenceError("action_failures exceeds action_attempts")

    delivery_attempts = _integer(record["delivery_attempts"], "delivery_attempts")
    delivery_status = cast(str, record["delivery_status"])
    if delivery_status == "not_required" and delivery_attempts != 0:
        raise PilotEvidenceError("not_required delivery must have zero delivery_attempts")
    if delivery_status != "not_required" and delivery_attempts < 1:
        raise PilotEvidenceError("attempted delivery must have at least one delivery_attempt")

    has_runbook_id = "runbook_id" in record
    has_runbook_version = "runbook_version" in record
    if has_runbook_id != has_runbook_version:
        raise PilotEvidenceError("runbook_id and runbook_version must be present together")

    match_review = cast(str, record["match_review"])
    if match_review in {"correct", "incorrect"} and not has_runbook_id:
        raise PilotEvidenceError("reviewed runbook match is missing runbook identity")
    if match_review == "no_match_expected" and has_runbook_id:
        raise PilotEvidenceError("no_match_expected cannot identify a selected runbook")

    human_touch_count = _integer(record["human_touch_count"], "human_touch_count")
    if record["material_edit"] is True and human_touch_count == 0:
        raise PilotEvidenceError("material_edit requires a human touch")
    if record["recovery_required"] is True and record["autonomous_candidate"] is not True:
        raise PilotEvidenceError("recovery_required requires autonomous_candidate=true")

    handling = cast(str, record["handling_classification"])
    if handling in {"verified_autonomous", "autonomous_candidate_observing"}:
        if record["autonomous_candidate"] is not True:
            raise PilotEvidenceError(f"{handling} requires autonomous_candidate=true")

    input_tokens = _integer(record["input_tokens"], "input_tokens")
    output_tokens = _integer(record["output_tokens"], "output_tokens")
    llm_cost = _number(record["llm_cost"], "llm_cost")
    model_fields_present = "model_provider" in record and "model_name" in record
    if input_tokens > 0 or output_tokens > 0 or llm_cost > 0:
        if not model_fields_present:
            raise PilotEvidenceError("model usage requires model_provider and model_name")
    if ("model_provider" in record) != ("model_name" in record):
        raise PilotEvidenceError("model_provider and model_name must be present together")


def _validate_threshold_group(
    raw_group: object,
    expected: Mapping[str, Comparison],
    label: str,
    *,
    completed: bool,
) -> None:
    group = _mapping(raw_group, label)
    missing = sorted(set(expected).difference(group))
    unknown = sorted(set(group).difference(expected))
    if missing:
        raise PilotEvidenceError(f"{label} missing required entries: {', '.join(missing)}")
    if unknown:
        raise PilotEvidenceError(f"{label} contains unknown entries: {', '.join(unknown)}")

    for key, expected_operator in expected.items():
        entry = _mapping(group[key], f"{label}.{key}")
        if set(entry) != {"operator", "target", "owner", "data_source"}:
            raise PilotEvidenceError(
                f"{label}.{key} must contain exactly operator, target, owner, and data_source"
            )
        operator = _text(entry["operator"], f"{label}.{key}.operator")
        if operator != expected_operator:
            raise PilotEvidenceError(
                f"{label}.{key}.operator must be {expected_operator}, got {operator}"
            )
        target = _number(entry["target"], f"{label}.{key}.target")
        if "rate" in key or key.endswith("_score"):
            if not 0 <= target <= 1:
                raise PilotEvidenceError(f"{label}.{key}.target must be between 0 and 1")
        if target < 0:
            raise PilotEvidenceError(f"{label}.{key}.target must not be negative")
        _text(entry["owner"], f"{label}.{key}.owner", completed=completed)
        _text(entry["data_source"], f"{label}.{key}.data_source", completed=completed)


def validate_target_contract(targets: Mapping[str, object], *, completed: bool = True) -> None:
    """Validate a target contract; completed mode rejects all placeholders."""

    required = {
        "schema_version",
        "pilot_id",
        "customer_identifier",
        "operational_owner",
        "economic_buyer",
        "pilot_window",
        "mailbox_or_queue",
        "workflow",
        "currency",
        "expected_eligible_ticket_count",
        "minimum_eligible_ticket_count",
        "observation_window_days",
        "baseline",
        "runbooks",
        "kpis",
        "guards",
        "review_sampling",
        "pause_conditions",
        "approved_exclusion_reasons",
        "commercial_decision_date",
        "instrumentation_follow_up",
        "approvals",
    }
    missing = sorted(required.difference(targets))
    if missing:
        raise PilotEvidenceError("target contract missing fields: " + ", ".join(missing))

    if targets["schema_version"] != "1.0":
        raise PilotEvidenceError("target contract schema_version must be 1.0")
    for key in (
        "pilot_id",
        "customer_identifier",
        "operational_owner",
        "economic_buyer",
        "mailbox_or_queue",
        "workflow",
    ):
        _text(targets[key], key, completed=completed)
    if targets["currency"] != "EUR":
        raise PilotEvidenceError("currency must be EUR for the DACH V1 pilot contract")

    pilot_window = _mapping(targets["pilot_window"], "pilot_window")
    pilot_start = _iso_date(pilot_window.get("start"), "pilot_window.start", completed=completed)
    pilot_end = _iso_date(pilot_window.get("end"), "pilot_window.end", completed=completed)
    if completed and date.fromisoformat(pilot_end) < date.fromisoformat(pilot_start):
        raise PilotEvidenceError("pilot_window.end precedes pilot_window.start")

    minimum_tickets = _integer(
        targets["minimum_eligible_ticket_count"],
        "minimum_eligible_ticket_count",
    )
    expected_tickets = _integer(
        targets["expected_eligible_ticket_count"],
        "expected_eligible_ticket_count",
    )
    if minimum_tickets < 200:
        raise PilotEvidenceError("minimum_eligible_ticket_count must be at least 200")
    if expected_tickets < minimum_tickets:
        raise PilotEvidenceError(
            "expected_eligible_ticket_count must meet minimum_eligible_ticket_count"
        )
    if _integer(targets["observation_window_days"], "observation_window_days") < 7:
        raise PilotEvidenceError("observation_window_days must be at least 7")

    baseline = _mapping(targets["baseline"], "baseline")
    baseline_start = _iso_date(baseline.get("start"), "baseline.start", completed=completed)
    baseline_end = _iso_date(baseline.get("end"), "baseline.end", completed=completed)
    if completed and date.fromisoformat(baseline_end) < date.fromisoformat(baseline_start):
        raise PilotEvidenceError("baseline.end precedes baseline.start")
    if _number(baseline.get("labour_cost_per_hour"), "baseline.labour_cost_per_hour") <= 0:
        raise PilotEvidenceError("baseline.labour_cost_per_hour must be greater than zero")
    if _number(
        baseline.get("cost_per_resolved_ticket"),
        "baseline.cost_per_resolved_ticket",
    ) <= 0:
        raise PilotEvidenceError("baseline.cost_per_resolved_ticket must be greater than zero")

    runbooks = _sequence(targets["runbooks"], "runbooks")
    if len(runbooks) != 3:
        raise PilotEvidenceError("runbooks must contain exactly three entries")
    runbook_ids: set[str] = set()
    for index, raw_runbook in enumerate(runbooks):
        runbook = _mapping(raw_runbook, f"runbooks[{index}]")
        runbook_ids.add(_text(runbook.get("id"), f"runbooks[{index}].id"))
        _text(
            runbook.get("version"),
            f"runbooks[{index}].version",
            completed=completed,
        )
        autonomy = _text(runbook.get("autonomy"), f"runbooks[{index}].autonomy")
        if autonomy not in {"automatic", "semi-automatic", "manual"}:
            raise PilotEvidenceError(f"runbooks[{index}].autonomy has an unknown value")
    if runbook_ids != REQUIRED_RUNBOOK_IDS:
        raise PilotEvidenceError("runbooks must match the three V1 runbook IDs")

    _validate_threshold_group(
        targets["kpis"],
        KPI_OPERATORS,
        "kpis",
        completed=completed,
    )
    _validate_threshold_group(
        targets["guards"],
        GUARD_OPERATORS,
        "guards",
        completed=completed,
    )

    sampling = _mapping(targets["review_sampling"], "review_sampling")
    if _integer(
        sampling.get("first_eligible_tickets_full_review"),
        "review_sampling.first_eligible_tickets_full_review",
    ) < 50:
        raise PilotEvidenceError("first 50 eligible tickets require full review")
    for key in (
        "autonomous_sample_rate_after_initial",
        "assisted_sample_rate",
        "manual_no_match_sample_rate",
    ):
        value = _number(sampling.get(key), f"review_sampling.{key}")
        if not 0 < value <= 1:
            raise PilotEvidenceError(f"review_sampling.{key} must be in (0, 1]")

    pause_conditions = _sequence(targets["pause_conditions"], "pause_conditions")
    if not pause_conditions:
        raise PilotEvidenceError("pause_conditions must not be empty")
    for index, value in enumerate(pause_conditions):
        _text(value, f"pause_conditions[{index}]")

    exclusions = _sequence(
        targets["approved_exclusion_reasons"],
        "approved_exclusion_reasons",
    )
    if not exclusions:
        raise PilotEvidenceError("approved_exclusion_reasons must not be empty")
    for index, value in enumerate(exclusions):
        _text(value, f"approved_exclusion_reasons[{index}]")

    _iso_date(
        targets["commercial_decision_date"],
        "commercial_decision_date",
        completed=completed,
    )
    follow_up = _text(targets["instrumentation_follow_up"], "instrumentation_follow_up")
    if follow_up != "https://github.com/olsommer/mantly/issues/6":
        raise PilotEvidenceError("instrumentation_follow_up must link issue #6")

    approvals = _mapping(targets["approvals"], "approvals")
    required_approvals = {
        "product_owner",
        "engineering_owner",
        "customer_operational_owner",
        "privacy_or_legal_owner",
    }
    if set(approvals) != required_approvals:
        raise PilotEvidenceError("approvals must contain all four required owners")
    for key in sorted(required_approvals):
        _text(approvals[key], f"approvals.{key}", completed=completed)


def _compare(actual: float, target: float, operator: Comparison) -> bool:
    if operator == ">=":
        return actual >= target
    return actual <= target


def _evaluate_threshold_group(
    results: object,
    targets: object,
    expected: Mapping[str, Comparison],
    label: str,
    failures: list[str],
) -> Mapping[str, object] | None:
    try:
        result_group = _mapping(results, f"results.{label}")
        target_group = _mapping(targets, f"targets.{label}")
    except PilotEvidenceError as exc:
        failures.append(str(exc))
        return None

    missing = sorted(set(expected).difference(result_group))
    unknown = sorted(set(result_group).difference(expected))
    if missing:
        failures.append(f"results.{label} missing values: {', '.join(missing)}")
    if unknown:
        failures.append(f"results.{label} contains unknown values: {', '.join(unknown)}")

    for key, operator in expected.items():
        if key not in result_group:
            continue
        try:
            actual = _number(result_group[key], f"results.{label}.{key}")
            target_entry = _mapping(target_group[key], f"targets.{label}.{key}")
            target = _number(target_entry["target"], f"targets.{label}.{key}.target")
        except (KeyError, PilotEvidenceError) as exc:
            failures.append(str(exc))
            continue
        if not _compare(actual, target, operator):
            failures.append(
                f"{label}.{key} missed target: actual {actual:g} {operator} target {target:g}"
            )
    return result_group


def evaluate_pilot(
    targets: Mapping[str, object],
    results: Mapping[str, object],
) -> PilotEvaluation:
    """Evaluate every required KPI and guard; missing evidence always fails."""

    validate_target_contract(targets, completed=True)
    failures: list[str] = []

    if results.get("schema_version") != "1.0":
        failures.append("results.schema_version must be 1.0")
    if results.get("pilot_id") != targets["pilot_id"]:
        failures.append("results.pilot_id does not match target contract")

    try:
        eligible_ticket_count = _integer(
            results.get("eligible_ticket_count"),
            "results.eligible_ticket_count",
        )
        minimum_ticket_count = _integer(
            targets["minimum_eligible_ticket_count"],
            "minimum_eligible_ticket_count",
        )
        if eligible_ticket_count < minimum_ticket_count:
            failures.append(
                "eligible ticket sample missed minimum: "
                f"{eligible_ticket_count} < {minimum_ticket_count}"
            )
    except PilotEvidenceError as exc:
        failures.append(str(exc))

    result_kpis = _evaluate_threshold_group(
        results.get("kpis"),
        targets["kpis"],
        KPI_OPERATORS,
        "kpis",
        failures,
    )
    _evaluate_threshold_group(
        results.get("guards"),
        targets["guards"],
        GUARD_OPERATORS,
        "guards",
        failures,
    )

    decision = results.get("customer_decision")
    if not isinstance(decision, str) or decision not in ALLOWED_CUSTOMER_DECISIONS:
        failures.append(
            "customer_decision must be one of: "
            + ", ".join(sorted(ALLOWED_CUSTOMER_DECISIONS))
        )
    elif result_kpis is not None and "customer_continuation_score" in result_kpis:
        try:
            reported_score = _number(
                result_kpis["customer_continuation_score"],
                "results.kpis.customer_continuation_score",
            )
            if reported_score != ALLOWED_CUSTOMER_DECISIONS[decision]:
                failures.append(
                    "customer_continuation_score does not match customer_decision"
                )
        except PilotEvidenceError as exc:
            failures.append(str(exc))

    try:
        evidence = _mapping(results.get("evidence"), "results.evidence")
        missing_flags = sorted(set(REQUIRED_EVIDENCE_FLAGS).difference(evidence))
        unknown_flags = sorted(set(evidence).difference(REQUIRED_EVIDENCE_FLAGS))
        if missing_flags:
            failures.append("results.evidence missing flags: " + ", ".join(missing_flags))
        if unknown_flags:
            failures.append("results.evidence contains unknown flags: " + ", ".join(unknown_flags))
        for flag in REQUIRED_EVIDENCE_FLAGS:
            if evidence.get(flag) is not True:
                failures.append(f"results.evidence.{flag} must be true")
    except PilotEvidenceError as exc:
        failures.append(str(exc))

    return PilotEvaluation(passed=not failures, failures=tuple(failures))


def load_metric_records(path: Path) -> list[Mapping[str, object]]:
    """Load either a JSON array or newline-delimited JSON metric export."""

    raw = path.read_text(encoding="utf-8")
    stripped = raw.lstrip()
    loaded_records: list[object]
    if stripped.startswith("["):
        loaded: object = json.loads(raw)
        loaded_records = list(_sequence(loaded, str(path)))
    else:
        loaded_records = [
            json.loads(line)
            for line in raw.splitlines()
            if line.strip()
        ]
    if not loaded_records:
        raise PilotEvidenceError(f"{path} contains no metric records")
    return [
        _mapping(record, f"{path} record {index}")
        for index, record in enumerate(loaded_records, start=1)
    ]


def _default_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "pilot-metrics-schema.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--metrics", type=Path)
    parser.add_argument("--schema", type=Path, default=_default_schema_path())
    parser.add_argument(
        "--allow-template-placeholders",
        action="store_true",
        help="Validate the checked-in template structure; never evaluates a pilot pass.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""

    args = _build_parser().parse_args(argv)
    if args.allow_template_placeholders and args.results is not None:
        print("template placeholders cannot be used for pilot evaluation", file=sys.stderr)
        return 2

    try:
        targets = load_yaml_mapping(args.targets)
        validate_target_contract(
            targets,
            completed=not args.allow_template_placeholders,
        )

        if args.metrics is not None:
            schema = load_metric_schema(args.schema)
            for record in load_metric_records(args.metrics):
                validate_metric_record(record, schema)

        if args.results is not None:
            results = load_yaml_mapping(args.results)
            evaluation = evaluate_pilot(targets, results)
            if not evaluation.passed:
                for failure in evaluation.failures:
                    print(f"FAIL: {failure}", file=sys.stderr)
                return 1
            print("PASS: every required KPI, guard, and evidence check passed")
            return 0

        print("PASS: target contract and supplied metric records are valid")
        return 0
    except (OSError, json.JSONDecodeError, yaml.YAMLError, PilotEvidenceError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
