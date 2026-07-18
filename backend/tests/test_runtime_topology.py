from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from automail.core.runtime_topology import inspect_runtime_topology, validate_runtime_topology


def test_default_topology_is_supported() -> None:
    topology = validate_runtime_topology({})

    assert topology.api_replicas == 1
    assert topology.storage_mode == "pocketbase-sqlite"
    assert topology.worker_mode == "in-process"
    assert topology.local_application_data is True
    assert topology.enabled_in_process_schedulers == ()
    assert topology.supported is True


def test_enabled_schedulers_are_reported() -> None:
    topology = validate_runtime_topology(
        {
            "MANTLY_API_REPLICAS": "1",
            "SUPPORT_SYNC_INTERVAL_SECONDS": "30",
            "SUPPORT_DELIVERY_INTERVAL_SECONDS": "15",
        }
    )

    assert topology.enabled_in_process_schedulers == (
        "SUPPORT_SYNC_INTERVAL_SECONDS",
        "SUPPORT_DELIVERY_INTERVAL_SECONDS",
    )


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"MANTLY_API_REPLICAS": "2"}, "MANTLY_API_REPLICAS must remain 1"),
        ({"MANTLY_STORAGE_MODE": "postgres"}, "MANTLY_STORAGE_MODE='postgres' is not implemented"),
        ({"MANTLY_WORKER_MODE": "external"}, "MANTLY_WORKER_MODE='external' is not implemented"),
        ({"MANTLY_LOCAL_APPLICATION_DATA": "false"}, "MANTLY_LOCAL_APPLICATION_DATA=false is not implemented"),
        (
            {"MANTLY_WORKER_MODE": "disabled", "SUPPORT_DELIVERY_INTERVAL_SECONDS": "10"},
            "conflicts with enabled scheduler intervals",
        ),
    ],
)
def test_unsupported_topologies_are_rejected(env: dict[str, str], message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        validate_runtime_topology(env)


def test_invalid_numeric_configuration_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="MANTLY_API_REPLICAS must be an integer"):
        inspect_runtime_topology({"MANTLY_API_REPLICAS": "many"})
    with pytest.raises(RuntimeError, match="SUPPORT_SYNC_INTERVAL_SECONDS cannot be negative"):
        inspect_runtime_topology({"SUPPORT_SYNC_INTERVAL_SECONDS": "-1"})


def test_sitecustomize_blocks_python_process_with_multiple_replicas() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["MANTLY_API_REPLICAS"] = "2"
    env["PYTHONPATH"] = str(backend_root)

    result = subprocess.run(
        [sys.executable, "-c", "print('must-not-run')"],
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "must-not-run" not in result.stdout
    assert "Mantly startup blocked" in combined
    assert "MANTLY_API_REPLICAS must remain 1" in combined
