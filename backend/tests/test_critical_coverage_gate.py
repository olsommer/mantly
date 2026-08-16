import importlib.util
import sys
from pathlib import Path


def _load_gate():
    path = Path(__file__).parents[2] / "scripts" / "check_critical_coverage.py"
    spec = importlib.util.spec_from_file_location("check_critical_coverage", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _report(module, percentage: float):
    files = {}
    for area in module.CRITICAL_AREAS.values():
        for path in area.files:
            files[path] = {
                "summary": {
                    "covered_lines": int(percentage),
                    "num_statements": 100,
                    "covered_branches": int(percentage),
                    "num_branches": 100,
                }
            }
    return {"files": files}


def test_critical_coverage_gate_accepts_areas_at_their_floors():
    gate = _load_gate()

    assert gate.check_critical_coverage(_report(gate, 70)) == []


def test_critical_coverage_gate_rejects_low_and_missing_areas():
    gate = _load_gate()

    failures = gate.check_critical_coverage(_report(gate, 59))
    assert any("authorization" in failure for failure in failures)
    assert any("support-inbox" in failure for failure in failures)

    missing = gate.check_critical_coverage({"files": {}})
    assert len(missing) == len(gate.CRITICAL_AREAS)
