from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _load_module() -> ModuleType:
    script = Path(__file__).resolve().parents[2] / "scripts" / "load_test.py"
    spec = importlib.util.spec_from_file_location("mantly_load_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path == "/api/failure":
            self.send_response(503)
        else:
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, format: str, *args: object) -> None:
        return


def test_percentile_and_scenario_validation(tmp_path: Path) -> None:
    module = _load_module()
    assert module.percentile([10.0, 20.0, 30.0], 0.5) == 20.0
    assert module.percentile([], 0.95) is None

    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "name": "health",
                        "method": "GET",
                        "path": "/api/health",
                        "weight": 1,
                        "expectedStatuses": [200],
                    }
                ],
                "thresholds": {"errorRateMax": 0.01},
            }
        ),
        encoding="utf-8",
    )
    targets, thresholds = module.parse_scenario(scenario)
    assert targets[0].name == "health"
    assert thresholds == {"errorRateMax": 0.01}


def test_load_harness_generates_deterministic_threshold_evidence(tmp_path: Path) -> None:
    module = _load_module()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        scenario = tmp_path / "scenario.json"
        scenario.write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            "name": "health",
                            "method": "GET",
                            "path": "/api/health",
                            "weight": 1,
                            "expectedStatuses": [200],
                        }
                    ],
                    "thresholds": {
                        "errorRateMax": 0.0,
                        "p95MsMax": 1000,
                        "throughputPerSecondMin": 5,
                    },
                }
            ),
            encoding="utf-8",
        )
        args = SimpleNamespace(
            base_url=f"http://127.0.0.1:{server.server_port}",
            scenario=str(scenario),
            duration=0.5,
            concurrency=4,
            rate=20.0,
            timeout=2.0,
            seed=42,
            header_env=[],
        )
        result = module.run_load_test(args)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result["requests"] >= 5
    assert result["errors"] == 0
    assert result["byTarget"]["health"]["requests"] == result["requests"]
    assert result["thresholds"]["allPassed"] is True
    assert "headers" not in result


def test_failed_status_counts_as_error(tmp_path: Path) -> None:
    module = _load_module()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        target = module.Target(
            name="failure",
            method="GET",
            path="/api/failure",
            weight=1,
            expected_statuses=(200,),
            body=None,
            content_type=None,
        )
        sample = module.execute_request(
            f"http://127.0.0.1:{server.server_port}",
            target,
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
