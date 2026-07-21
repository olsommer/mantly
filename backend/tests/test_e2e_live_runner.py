from __future__ import annotations

# ruff: noqa: E402
import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from e2e import live
from e2e.live import (
    CaseSelector,
    LiveE2EError,
    _case_selection_error,
    _selected_cases,
    _write_report_checkpoint,
    parse_case_selector,
    parse_target,
    run_knowledge_checks,
)
from e2e.schema import load_personas

PERSONA_DIR = REPO_ROOT / "e2e" / "personas"


class _FakeAdminApi:
    created_timeout: float | None = None
    closed = False

    def __init__(
        self,
        _api_base: str,
        _token: str,
        *,
        timeout_seconds: float,
    ) -> None:
        type(self).created_timeout = timeout_seconds
        type(self).closed = False

    def close(self) -> None:
        type(self).closed = True


def _stub_live_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "AdminApi", _FakeAdminApi)
    monkeypatch.setattr(
        live,
        "_existing_article_ids",
        lambda _api, _target, _persona: {},
    )
    monkeypatch.setattr(
        live,
        "_preflight_target_for_run",
        lambda _api, _target, _persona: None,
    )
    monkeypatch.setenv(live.DEFAULT_TOKEN_ENV, "synthetic-test-token")


def test_case_selector_is_scoped_and_preserves_default_case_order() -> None:
    personas = {persona.id: persona for persona in load_personas(PERSONA_DIR)}
    lawyer = personas["lawyer"]

    assert parse_case_selector("lawyer=L08") == CaseSelector("lawyer", "L08")
    assert [case.id for case in _selected_cases(lawyer, [])] == [
        case.id for case in lawyer.cases
    ]
    assert [
        case.id
        for case in _selected_cases(
            lawyer,
            [CaseSelector("lawyer", "L09"), CaseSelector("lawyer", "L08")],
        )
    ] == ["L08", "L09"]

    with pytest.raises(argparse.ArgumentTypeError, match="PERSONA_ID=CASE_ID"):
        parse_case_selector("L08")
    with pytest.raises(argparse.ArgumentTypeError, match="invalid case ID"):
        parse_case_selector("lawyer=l08")


def test_case_selector_validation_rejects_untargeted_and_unknown_cases() -> None:
    personas = {persona.id: persona for persona in load_personas(PERSONA_DIR)}
    targets = [parse_target("lawyer=project-law:channel-law")]

    assert "also have a --target" in _case_selection_error(
        [CaseSelector("fulfillment", "E01")],
        targets,
        personas,
    )
    assert "Unknown case" in _case_selection_error(
        [CaseSelector("lawyer", "L99")],
        targets,
        personas,
    )


def test_atomic_report_checkpoint_keeps_previous_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = tmp_path / "report.json"
    previous = '{"previous": true}\n'
    report_path.write_text(previous, encoding="utf-8")

    def fail_replace(source: str | Path, destination: str | Path) -> None:
        assert Path(destination) == report_path
        staged = json.loads(Path(source).read_text(encoding="utf-8"))
        assert staged["status"] == "running"
        raise OSError("simulated replace failure")

    monkeypatch.setattr(live.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        _write_report_checkpoint(
            {"personas": [], "startedAt": "synthetic"},
            report_path,
            status="running",
        )

    assert report_path.read_text(encoding="utf-8") == previous
    assert list(tmp_path.glob(".report.json.*.tmp")) == []


def test_targeted_main_checkpoints_seed_and_uses_separate_request_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_live_dependencies(monkeypatch)
    report_path = tmp_path / "targeted.json"
    observed_cases: list[str] = []

    def fake_run_case(
        _api: Any,
        _target: Any,
        _persona: Any,
        case: Any,
        _article_ids: dict[str, str],
        _run_id: str,
        *,
        timeout_seconds: float,
        poll_seconds: float,
    ) -> dict[str, Any]:
        seed_checkpoint = json.loads(report_path.read_text(encoding="utf-8"))
        assert seed_checkpoint["status"] == "running"
        assert seed_checkpoint["personas"][0]["knowledgeArticleIds"] == {}
        assert timeout_seconds == 91.0
        assert poll_seconds == 0.5
        observed_cases.append(case.id)
        return {"id": case.id, "passed": True, "assertions": []}

    monkeypatch.setattr(live, "run_case", fake_run_case)

    result = live.main(
        [
            "--api-base",
            "https://api.example.test",
            "--target",
            "lawyer=project-law:channel-law",
            "--target",
            "fulfillment=project-fulfillment:channel-fulfillment",
            "--case",
            "lawyer=L08",
            "--run-id",
            "targeted-test",
            "--timeout-seconds",
            "91",
            "--request-timeout-seconds",
            "7.5",
            "--poll-seconds",
            "0.5",
            "--report",
            str(report_path),
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 0
    assert observed_cases == ["L08"]
    assert _FakeAdminApi.created_timeout == 7.5
    assert _FakeAdminApi.closed is True
    assert report["status"] == "completed"
    assert report["passed"] is True
    assert report["summary"]["caseCount"] == 1
    assert report["personas"][0]["selectedCaseIds"] == ["L08"]
    assert [item["personaId"] for item in report["personas"]] == ["lawyer"]
    assert report["caseSelection"] == [{"caseId": "L08", "personaId": "lawyer"}]


def test_interrupt_preserves_the_last_completed_case_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_live_dependencies(monkeypatch)
    report_path = tmp_path / "interrupted.json"
    calls: list[str] = []

    def fake_run_case(
        _api: Any,
        _target: Any,
        _persona: Any,
        case: Any,
        _article_ids: dict[str, str],
        _run_id: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(case.id)
        if case.id == "L01":
            return {
                "id": "L01",
                "passed": False,
                "error": "exact synthetic failure",
                "assertions": [
                    {
                        "name": "synthetic_assertion",
                        "passed": False,
                        "evidence": "exact evidence",
                    }
                ],
            }
        checkpoint = json.loads(report_path.read_text(encoding="utf-8"))
        assert checkpoint["personas"][0]["cases"][0]["error"] == (
            "exact synthetic failure"
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(live, "run_case", fake_run_case)

    result = live.main(
        [
            "--api-base",
            "https://api.example.test",
            "--target",
            "lawyer=project-law:channel-law",
            "--case",
            "lawyer=L01",
            "--case",
            "lawyer=L02",
            "--run-id",
            "interrupt-test",
            "--report",
            str(report_path),
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 130
    assert calls == ["L01", "L02"]
    assert _FakeAdminApi.closed is True
    assert report["status"] == "interrupted"
    assert report["passed"] is False
    assert report["summary"]["failedCases"] == 1
    assert report["personas"][0]["cases"] == [
        {
            "id": "L01",
            "passed": False,
            "error": "exact synthetic failure",
            "assertions": [
                {
                    "name": "synthetic_assertion",
                    "passed": False,
                    "evidence": "exact evidence",
                }
            ],
        }
    ]


def test_seed_failure_is_checkpointed_before_the_next_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_live_dependencies(monkeypatch)
    report_path = tmp_path / "seed-failure.json"

    def fake_existing_article_ids(
        _api: Any,
        target: Any,
        _persona: Any,
    ) -> dict[str, str]:
        if target.persona_id == "lawyer":
            raise LiveE2EError("exact synthetic seed failure")
        checkpoint = json.loads(report_path.read_text(encoding="utf-8"))
        assert checkpoint["personas"][0]["seedError"] == (
            "exact synthetic seed failure"
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(live, "_existing_article_ids", fake_existing_article_ids)

    result = live.main(
        [
            "--api-base",
            "https://api.example.test",
            "--target",
            "lawyer=project-law:channel-law",
            "--target",
            "fulfillment=project-fulfillment:channel-fulfillment",
            "--run-id",
            "seed-failure-test",
            "--report",
            str(report_path),
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 130
    assert report["status"] == "interrupted"
    assert report["personas"][0]["seedError"] == "exact synthetic seed failure"
    assert report["personas"][0]["passed"] is False


def test_knowledge_failure_is_checkpointed_before_a_later_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_live_dependencies(monkeypatch)
    report_path = tmp_path / "knowledge-interrupt.json"

    monkeypatch.setattr(
        live,
        "run_case",
        lambda _api, _target, _persona, case, *_args, **_kwargs: {
            "id": case.id,
            "issueId": "issue-l05",
            "passed": True,
            "assertions": [],
        },
    )

    def fake_knowledge_checks(
        _api: Any,
        _target: Any,
        _persona: Any,
        _article_ids: dict[str, str],
        _cases: list[dict[str, Any]],
        *,
        source_case_ids: set[str] | None,
        on_completed: Any,
    ) -> list[dict[str, Any]]:
        assert source_case_ids == {"L05"}
        failure = {
            "id": "K01",
            "passed": False,
            "error": "exact synthetic knowledge failure",
            "assertions": [
                {"name": "knowledge_assertion", "passed": False}
            ],
        }
        on_completed(failure)
        checkpoint = json.loads(report_path.read_text(encoding="utf-8"))
        assert checkpoint["personas"][0]["knowledgeChecks"] == [failure]
        raise KeyboardInterrupt

    monkeypatch.setattr(live, "run_knowledge_checks", fake_knowledge_checks)

    result = live.main(
        [
            "--api-base",
            "https://api.example.test",
            "--target",
            "lawyer=project-law:channel-law",
            "--case",
            "lawyer=L05",
            "--run-id",
            "knowledge-interrupt-test",
            "--report",
            str(report_path),
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 130
    assert report["status"] == "interrupted"
    assert report["summary"]["failedKnowledgeChecks"] == 1
    assert report["personas"][0]["knowledgeChecks"][0]["error"] == (
        "exact synthetic knowledge failure"
    )


def test_knowledge_check_filter_and_completion_callback_preserve_failure() -> None:
    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "lawyer"
    )
    target = parse_target("lawyer=project-law:channel-law")

    class FailingApi:
        def get(self, _path: str) -> dict[str, Any]:
            raise LiveE2EError("synthetic knowledge failure")

    excluded = run_knowledge_checks(
        FailingApi(),  # type: ignore[arg-type]
        target,
        persona,
        {},
        [{"id": "L05", "issueId": "issue-l05"}],
        source_case_ids={"L08"},
    )
    completed: list[dict[str, Any]] = []
    included = run_knowledge_checks(
        FailingApi(),  # type: ignore[arg-type]
        target,
        persona,
        {},
        [{"id": "L05", "issueId": "issue-l05"}],
        source_case_ids={"L05"},
        on_completed=completed.append,
    )

    assert excluded == []
    assert completed == included
    assert included[0]["passed"] is False
    assert included[0]["error"] == "synthetic knowledge failure"
