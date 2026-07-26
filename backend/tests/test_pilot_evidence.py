from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from automail.pilot_evidence import (
    GUARD_OPERATORS,
    KPI_OPERATORS,
    PilotEvidenceError,
    evaluate_pilot,
    load_metric_schema,
    validate_metric_record,
    validate_target_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "pilot-metrics-schema.json"
TARGETS_PATH = REPO_ROOT / "docs" / "pilot-targets.example.yml"
RESULTS_PATH = REPO_ROOT / "docs" / "pilot-results.example.yml"


def valid_metric_record() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "pilot_id": "pilot-2026-01",
        "tenant_id": "tenant-1",
        "ticket_id": "ticket-1",
        "source_message_id": "message-1",
        "received_at": "2026-07-01T08:00:00Z",
        "first_response_at": "2026-07-01T08:05:00Z",
        "resolved_at": "2026-07-01T08:10:00Z",
        "observation_window_end": "2026-07-08T08:10:00Z",
        "eligibility": "eligible",
        "runbook_id": "delivery-status",
        "runbook_version": "1.0.0",
        "match_confidence": 0.99,
        "match_review": "correct",
        "handling_classification": "verified_autonomous",
        "autonomous_candidate": True,
        "human_touch_count": 0,
        "approval_required": False,
        "draft_generated": True,
        "material_edit": False,
        "action_attempts": 1,
        "action_failures": 0,
        "duplicate_side_effect": False,
        "delivery_status": "delivered",
        "delivery_attempts": 1,
        "review_result": "pass",
        "review_categories": [],
        "unsafe_or_materially_incorrect": False,
        "critical_outcome": False,
        "recovery_required": False,
        "model_provider": "example-provider",
        "model_name": "example-model",
        "input_tokens": 100,
        "output_tokens": 50,
        "llm_cost": 0.02,
        "tool_and_delivery_cost": 0.01,
        "human_minutes": 0,
        "evidence_refs": ["support_issue:ticket-1", "support_ai_run:run-1"],
    }


def target_template() -> dict[str, object]:
    loaded = yaml.safe_load(TARGETS_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def completed_targets() -> dict[str, object]:
    targets = target_template()
    targets.update(
        {
            "pilot_id": "pilot-2026-01",
            "customer_identifier": "customer-17",
            "operational_owner": "Support operations lead",
            "economic_buyer": "Chief operating officer",
            "mailbox_or_queue": "pilot-support@customer.invalid",
            "pilot_window": {"start": "2026-09-01", "end": "2026-09-30"},
            "baseline": {
                "start": "2026-07-01",
                "end": "2026-07-31",
                "labour_cost_per_hour": 35.0,
                "cost_per_resolved_ticket": 12.0,
            },
            "commercial_decision_date": "2026-10-05",
            "approvals": {
                "product_owner": "Product lead, 2026-08-25",
                "engineering_owner": "Engineering lead, 2026-08-25",
                "customer_operational_owner": "Support lead, 2026-08-26",
                "privacy_or_legal_owner": "Privacy lead, 2026-08-26",
            },
        }
    )
    runbooks = targets["runbooks"]
    assert isinstance(runbooks, list)
    for index, runbook in enumerate(runbooks, start=1):
        assert isinstance(runbook, dict)
        runbook["version"] = f"1.0.{index}"
    return targets


def passing_results(targets: dict[str, object]) -> dict[str, object]:
    raw_kpis = targets["kpis"]
    raw_guards = targets["guards"]
    assert isinstance(raw_kpis, dict)
    assert isinstance(raw_guards, dict)
    return {
        "schema_version": "1.0",
        "pilot_id": targets["pilot_id"],
        "eligible_ticket_count": 200,
        "kpis": {
            key: entry["target"]
            for key, entry in raw_kpis.items()
        },
        "guards": {
            key: entry["target"]
            for key, entry in raw_guards.items()
        },
        "customer_decision": "continue",
        "evidence": {
            "target_contract_approved": True,
            "baseline_uses_same_population_rules": True,
            "metric_records_schema_validated": True,
            "metric_records_semantically_validated": True,
            "results_reproducible": True,
        },
    }


def test_metric_schema_accepts_complete_verified_autonomous_record() -> None:
    schema = load_metric_schema(SCHEMA_PATH)
    validate_metric_record(valid_metric_record(), schema)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resolved_at", None),
        ("first_response_at", None),
        ("delivery_status", "unknown"),
        ("delivery_status", "queued"),
        ("review_result", "unknown"),
        ("human_touch_count", 1),
        ("duplicate_side_effect", True),
    ],
)
def test_metric_schema_rejects_invalid_verified_autonomous_values(
    field: str,
    value: object,
) -> None:
    schema = load_metric_schema(SCHEMA_PATH)
    record = valid_metric_record()
    record[field] = value

    with pytest.raises(PilotEvidenceError):
        validate_metric_record(record, schema)


def test_metric_schema_rejects_missing_required_timing() -> None:
    schema = load_metric_schema(SCHEMA_PATH)
    record = valid_metric_record()
    del record["resolved_at"]

    with pytest.raises(PilotEvidenceError):
        validate_metric_record(record, schema)


def test_metric_semantics_reject_failure_count_above_attempts() -> None:
    schema = load_metric_schema(SCHEMA_PATH)
    record = valid_metric_record()
    record.update(
        {
            "handling_classification": "failed_automation",
            "action_attempts": 1,
            "action_failures": 2,
            "delivery_status": "failed",
            "review_result": "major_issue",
        }
    )

    with pytest.raises(PilotEvidenceError, match="action_failures exceeds"):
        validate_metric_record(record, schema)


def test_metric_semantics_reject_timestamp_reversal() -> None:
    schema = load_metric_schema(SCHEMA_PATH)
    record = valid_metric_record()
    record["resolved_at"] = "2026-07-01T08:04:00Z"

    with pytest.raises(PilotEvidenceError, match="resolved_at precedes"):
        validate_metric_record(record, schema)


def test_excluded_record_requires_reason_and_rejects_outcome_fields() -> None:
    schema = load_metric_schema(SCHEMA_PATH)
    record = valid_metric_record()
    record.update(
        {
            "eligibility": "excluded",
            "handling_classification": "excluded",
            "exclusion_reason": "spam_or_malware",
        }
    )

    with pytest.raises(PilotEvidenceError, match="eligible-only fields"):
        validate_metric_record(record, schema)


def test_target_template_has_complete_numeric_kpi_and_guard_structure() -> None:
    targets = target_template()

    validate_target_contract(targets, completed=False)

    assert set(targets["kpis"]) == set(KPI_OPERATORS)  # type: ignore[arg-type]
    assert set(targets["guards"]) == set(GUARD_OPERATORS)  # type: ignore[arg-type]


def test_target_template_cannot_be_used_as_approved_contract() -> None:
    with pytest.raises(PilotEvidenceError, match="placeholder"):
        validate_target_contract(target_template(), completed=True)


def test_pilot_pass_requires_every_kpi_guard_and_evidence_flag() -> None:
    targets = completed_targets()
    results = passing_results(targets)

    evaluation = evaluate_pilot(targets, results)

    assert evaluation.passed is True
    assert evaluation.failures == ()


def test_result_example_matches_strict_contract_shape() -> None:
    targets = completed_targets()
    loaded = yaml.safe_load(RESULTS_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    loaded["pilot_id"] = targets["pilot_id"]

    evaluation = evaluate_pilot(targets, loaded)

    assert evaluation.passed is True
    assert evaluation.failures == ()


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("kpis", "runbook_match_precision"),
        ("guards", "schema_validation_error_count"),
    ],
)
def test_pilot_fails_when_required_result_is_missing(section: str, key: str) -> None:
    targets = completed_targets()
    results = passing_results(targets)
    values = results[section]
    assert isinstance(values, dict)
    del values[key]

    evaluation = evaluate_pilot(targets, results)

    assert evaluation.passed is False
    assert any("missing values" in failure for failure in evaluation.failures)


def test_pilot_fails_when_kpi_misses_target() -> None:
    targets = completed_targets()
    results = passing_results(targets)
    kpis = results["kpis"]
    assert isinstance(kpis, dict)
    kpis["verified_full_automation_rate"] = 0.19

    evaluation = evaluate_pilot(targets, results)

    assert evaluation.passed is False
    assert any("verified_full_automation_rate missed target" in failure for failure in evaluation.failures)


def test_pilot_fails_when_kpi_is_null() -> None:
    targets = completed_targets()
    results = passing_results(targets)
    kpis = results["kpis"]
    assert isinstance(kpis, dict)
    kpis["verified_full_automation_rate"] = None

    evaluation = evaluate_pilot(targets, results)

    assert evaluation.passed is False
    assert any(
        "results.kpis.verified_full_automation_rate must be a finite number" in failure
        for failure in evaluation.failures
    )


def test_pilot_fails_when_safety_guard_misses_target() -> None:
    targets = completed_targets()
    results = passing_results(targets)
    guards = results["guards"]
    assert isinstance(guards, dict)
    guards["critical_outcome_count"] = 1

    evaluation = evaluate_pilot(targets, results)

    assert evaluation.passed is False
    assert any("critical_outcome_count missed target" in failure for failure in evaluation.failures)


def test_pilot_fails_on_unknown_customer_decision() -> None:
    targets = completed_targets()
    results = passing_results(targets)
    results["customer_decision"] = "unknown"

    evaluation = evaluate_pilot(targets, results)

    assert evaluation.passed is False
    assert any("customer_decision must be one of" in failure for failure in evaluation.failures)


def test_pilot_fails_when_evidence_is_false() -> None:
    targets = completed_targets()
    results = passing_results(targets)
    evidence = results["evidence"]
    assert isinstance(evidence, dict)
    evidence["metric_records_semantically_validated"] = False

    evaluation = evaluate_pilot(targets, results)

    assert evaluation.passed is False
    assert any(
        "metric_records_semantically_validated must be true" in failure
        for failure in evaluation.failures
    )


def test_pilot_fails_below_minimum_sample() -> None:
    targets = completed_targets()
    results = passing_results(targets)
    results["eligible_ticket_count"] = 199

    evaluation = evaluate_pilot(targets, results)

    assert evaluation.passed is False
    assert any("eligible ticket sample missed minimum" in failure for failure in evaluation.failures)
