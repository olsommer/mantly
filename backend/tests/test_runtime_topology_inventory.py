from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_module() -> ModuleType:
    script = Path(__file__).resolve().parents[2] / "scripts" / "runtime_topology_inventory.py"
    spec = importlib.util.spec_from_file_location("mantly_runtime_topology_inventory", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _compose_record(service: str, *, container_id: str | None = None) -> dict[str, object]:
    return {
        "ID": container_id or f"{service}-container-id",
        "Name": f"mantly-{service}-1",
        "Image": f"mantly-{service}:test",
        "Project": "mantly",
        "Service": service,
        "State": "running",
        "Health": "healthy" if service in {"app", "pocketbase"} else "",
    }


def _inspect_record(service: str, destinations: tuple[str, ...]) -> dict[str, object]:
    return {
        "Id": f"{service}-container-id",
        "Image": f"sha256:{service}",
        "State": {
            "Status": "running",
            "Health": {"Status": "healthy"} if service in {"app", "pocketbase"} else {},
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": f"mantly-{service}-{index}",
                "Destination": destination,
                "RW": True,
            }
            for index, destination in enumerate(destinations)
        ],
    }


def _valid_records() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    compose = [_compose_record(service) for service in ("app", "caddy", "pocketbase")]
    inspected = [
        _inspect_record("app", ("/app/data",)),
        _inspect_record("caddy", ("/data", "/config")),
        _inspect_record("pocketbase", ("/pb/pb_data",)),
    ]
    return compose, inspected


def test_parse_json_records_supports_array_and_json_lines() -> None:
    module = _load_module()
    records = [{"Service": "app"}, {"Service": "pocketbase"}]
    assert module.parse_json_records(json.dumps(records), label="array") == records
    assert module.parse_json_records("\n".join(json.dumps(item) for item in records), label="lines") == records


def test_external_inventory_accepts_exact_healthy_single_node_topology() -> None:
    module = _load_module()
    compose, inspected = _valid_records()

    result = module.build_inventory(
        compose,
        inspected,
        compose_file="C:/deployment/docker-compose.yml",
        observed_at="2026-07-26T00:00:00+00:00",
    )

    assert result["observedExternally"] is True
    assert result["supported"] is True
    assert result["errors"] == []
    assert result["serviceCounts"] == {"app": 1, "caddy": 1, "pocketbase": 1}
    assert len(result["inventorySha256"]) == 64
    serialized = json.dumps(result)
    assert "mantly-app-0" not in serialized


def test_external_inventory_rejects_actual_second_api_container() -> None:
    module = _load_module()
    compose, inspected = _valid_records()
    second = _compose_record("app", container_id="app-container-id-2")
    second["Name"] = "mantly-app-2"
    compose.append(second)
    second_inspect = _inspect_record("app", ("/app/data",))
    second_inspect["Id"] = "app-container-id-2"
    inspected.append(second_inspect)

    result = module.build_inventory(compose, inspected, compose_file="docker-compose.yml")

    assert result["supported"] is False
    assert "service app count is 2, expected exactly 1" in result["errors"]


def test_external_inventory_rejects_unhealthy_service_and_missing_mount() -> None:
    module = _load_module()
    compose, inspected = _valid_records()
    inspected[0]["State"] = {"Status": "running", "Health": {"Status": "unhealthy"}}
    inspected[2]["Mounts"] = []

    result = module.build_inventory(compose, inspected, compose_file="docker-compose.yml")

    assert result["supported"] is False
    assert "service app health is unhealthy, expected healthy" in result["errors"]
    assert "service pocketbase must have exactly one mount at /pb/pb_data" in result["errors"]
