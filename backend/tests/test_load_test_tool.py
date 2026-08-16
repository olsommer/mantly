from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _load_module() -> ModuleType:
    script = Path(__file__).resolve().parents[2] / "scripts" / "load_test.py"
    spec = importlib.util.spec_from_file_location("mantly_load_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Handler(BaseHTTPRequestHandler):
    active = 0
    max_active = 0
    activity_lock = threading.Lock()

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        with self.activity_lock:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
        try:
            if self.path == "/api/slow":
                time.sleep(0.2)
            if self.path == "/api/failure":
                self.send_response(503)
            elif self.path == "/api/redirect":
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            else:
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(b'{"ok":true}')
            except (BrokenPipeError, ConnectionResetError):
                pass
        finally:
            with self.activity_lock:
                type(self).active -= 1

    def log_message(self, format: str, *args: object) -> None:
        return


def _thresholds(**overrides: int | float) -> dict[str, int | float]:
    values: dict[str, int | float] = {
        "errorRateMax": 0.0,
        "p95MsMax": 1000,
        "throughputPerSecondMin": 1,
        "minimumRequests": 1,
        "minimumRequestsPerTarget": 1,
    }
    values.update(overrides)
    return values


def _write_scenario(
    path: Path,
    *,
    kind: str = "smoke",
    targets: list[dict[str, object]] | None = None,
    thresholds: dict[str, int | float] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "scenarioId": "test-capacity-scenario",
                "kind": kind,
                "targets": targets
                or [
                    {
                        "name": "health",
                        "method": "GET",
                        "path": "/api/health",
                        "workloads": ["health"],
                        "weight": 1,
                        "expectedStatuses": [200],
                    }
                ],
                "thresholds": thresholds if thresholds is not None else _thresholds(),
            }
        ),
        encoding="utf-8",
    )


def _args(
    module: ModuleType,
    server: ThreadingHTTPServer,
    scenario: Path,
    **overrides: object,
) -> SimpleNamespace:
    values: dict[str, object] = {
        "release_id": "test-release-sha",
        "environment_id": "isolated-test",
        "run_kind": "steady",
        "base_url": f"http://127.0.0.1:{server.server_port}",
        "allowed_host": [f"127.0.0.1:{server.server_port}"],
        "allow_private_target": True,
        "scenario": str(scenario),
        "duration": 0.25,
        "concurrency": 4,
        "rate": 20.0,
        "timeout": 2.0,
        "max_requests": module.MAX_REQUESTS,
        "seed": 42,
        "header_env": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_percentile_and_scenario_validation(tmp_path: Path) -> None:
    module = _load_module()
    assert module.percentile([10.0, 20.0, 30.0], 0.5) == 20.0
    assert module.percentile([], 0.95) is None

    scenario = tmp_path / "scenario.json"
    _write_scenario(scenario)
    parsed = module.parse_scenario(scenario)
    assert parsed.targets[0].name == "health"
    assert parsed.thresholds == _thresholds()
    assert len(parsed.sha256) == 64


def test_scenario_rejects_vacuous_thresholds_and_authority_paths(tmp_path: Path) -> None:
    module = _load_module()
    scenario = tmp_path / "scenario.json"
    _write_scenario(scenario, thresholds={})
    with pytest.raises(module.LoadTestError, match="missing required checks"):
        module.parse_scenario(scenario)

    _write_scenario(
        scenario,
        targets=[
            {
                "name": "escape",
                "method": "GET",
                "path": "//169.254.169.254/latest",
                "workloads": ["health"],
                "expectedStatuses": [200],
            }
        ],
    )
    with pytest.raises(module.LoadTestError, match="exactly one"):
        module.parse_scenario(scenario)

    _write_scenario(scenario, kind="capacity")
    with pytest.raises(module.LoadTestError, match="missing required workloads"):
        module.parse_scenario(scenario)


def test_base_url_requires_exact_allowlist_and_blocks_link_local() -> None:
    module = _load_module()
    with pytest.raises(module.LoadTestError, match="not present"):
        module.validate_base_url(
            "https://example.com",
            ["other.example:443"],
            allow_private_target=False,
        )
    with pytest.raises(module.LoadTestError, match="forbidden address"):
        module.validate_base_url(
            "http://169.254.169.254",
            ["169.254.169.254:80"],
            allow_private_target=True,
        )


def test_load_harness_generates_deterministic_threshold_evidence(tmp_path: Path) -> None:
    module = _load_module()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        scenario = tmp_path / "scenario.json"
        _write_scenario(
            scenario,
            thresholds=_thresholds(
                throughputPerSecondMin=5,
                minimumRequests=5,
                minimumRequestsPerTarget=5,
            ),
        )
        args = _args(module, server, scenario, duration=0.5)
        result = module.run_load_test(args)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result["requests"] >= 5
    assert result["errors"] == 0
    assert result["byTarget"]["health"]["requests"] == result["requests"]
    assert result["thresholds"]["allPassed"] is True
    assert result["thresholds"]["missingRequiredChecks"] == []
    assert result["throughputPerSecond"] <= result["requestThroughputPerSecond"]
    assert result["capacityApprovalEligible"] is False
    assert "headers" not in result


def test_failed_status_counts_as_error_and_redirect_is_not_followed() -> None:
    module = _load_module()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        policy = module.validate_base_url(
            f"http://127.0.0.1:{server.server_port}",
            [f"127.0.0.1:{server.server_port}"],
            allow_private_target=True,
        )
        target = module.Target(
            name="failure",
            method="GET",
            path="/api/failure",
            workloads=("health",),
            weight=1,
            expected_statuses=(200,),
            body=None,
            content_type=None,
        )
        sample = module.execute_request(policy, target, {}, 2.0)
        redirect = module.execute_request(
            policy,
            module.Target(
                name="redirect",
                method="GET",
                path="/api/redirect",
                workloads=("health",),
                weight=1,
                expected_statuses=(200,),
                body=None,
                content_type=None,
            ),
            {},
            2.0,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert sample.status == 503
    assert sample.ok is False
    assert sample.error is None
    assert redirect.status == 302
    assert redirect.ok is False


def test_timeout_is_recorded_and_completion_time_drives_throughput(tmp_path: Path) -> None:
    module = _load_module()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        scenario = tmp_path / "scenario.json"
        _write_scenario(
            scenario,
            targets=[
                {
                    "name": "slow",
                    "method": "GET",
                    "path": "/api/slow",
                    "workloads": ["health"],
                    "weight": 1,
                    "expectedStatuses": [200],
                }
            ],
            thresholds=_thresholds(p95MsMax=2000),
        )
        result = module.run_load_test(
            _args(
                module,
                server,
                scenario,
                duration=0.05,
                concurrency=1,
                rate=20.0,
            )
        )
        policy = module.validate_base_url(
            f"http://127.0.0.1:{server.server_port}",
            [f"127.0.0.1:{server.server_port}"],
            allow_private_target=True,
        )
        timeout_sample = module.execute_request(
            policy,
            module.Target(
                name="slow-timeout",
                method="GET",
                path="/api/slow",
                workloads=("health",),
                weight=1,
                expected_statuses=(200,),
                body=None,
                content_type=None,
            ),
            {},
            0.02,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result["runElapsedSeconds"] >= 0.15
    assert result["throughputPerSecond"] < 8
    assert timeout_sample.ok is False
    assert timeout_sample.status == 0
    assert timeout_sample.error in {"TimeoutError", "URLError"}


def test_in_flight_requests_never_exceed_configured_concurrency(tmp_path: Path) -> None:
    module = _load_module()
    _Handler.active = 0
    _Handler.max_active = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        scenario = tmp_path / "scenario.json"
        _write_scenario(
            scenario,
            targets=[
                {
                    "name": "slow",
                    "method": "GET",
                    "path": "/api/slow",
                    "workloads": ["health"],
                    "weight": 1,
                    "expectedStatuses": [200],
                }
            ],
            thresholds=_thresholds(p95MsMax=2000),
        )
        result = module.run_load_test(
            _args(
                module,
                server,
                scenario,
                duration=0.25,
                concurrency=2,
                rate=100.0,
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result["scheduledRequests"] < 25
    assert _Handler.max_active <= 2
