#!/usr/bin/env python3
"""Observe and validate the deployed single-node topology through Docker.

The application cannot prove its own replica count from an environment variable.
This command queries the orchestrator, inspects every container and durable
mount, then emits a redacted inventory suitable for deployment evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ServiceContract:
    healthy: bool
    writable_mounts: tuple[str, ...]


SERVICE_CONTRACTS = {
    "app": ServiceContract(healthy=True, writable_mounts=("/app/data",)),
    "caddy": ServiceContract(healthy=False, writable_mounts=("/data", "/config")),
    "pocketbase": ServiceContract(healthy=True, writable_mounts=("/pb/pb_data",)),
}


class TopologyInventoryError(RuntimeError):
    pass


def _value(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in record:
            return record[name]
    return None


def parse_json_records(raw: str, *, label: str) -> list[dict[str, Any]]:
    clean = raw.strip()
    if not clean:
        return []
    try:
        decoded = json.loads(clean)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        return [decoded]
    if isinstance(decoded, list) and all(isinstance(item, dict) for item in decoded):
        return decoded

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(clean.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TopologyInventoryError(f"{label} line {line_number} is not valid JSON") from exc
        if not isinstance(item, dict):
            raise TopologyInventoryError(f"{label} line {line_number} must be a JSON object")
        records.append(item)
    return records


def _source_fingerprint(source: object) -> str:
    value = str(source or "").strip()
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _safe_mounts(record: dict[str, Any]) -> list[dict[str, object]]:
    raw_mounts = record.get("Mounts")
    if not isinstance(raw_mounts, list):
        return []
    mounts: list[dict[str, object]] = []
    for raw in raw_mounts:
        if not isinstance(raw, dict):
            continue
        destination = str(_value(raw, "Destination", "destination") or "").strip()
        mount_type = str(_value(raw, "Type", "type") or "").strip().lower()
        read_write = bool(_value(raw, "RW", "rw"))
        source = _value(raw, "Name", "name") or _value(raw, "Source", "source")
        mounts.append(
            {
                "destination": destination,
                "type": mount_type,
                "readWrite": read_write,
                "sourceFingerprint": _source_fingerprint(source),
            }
        )
    return sorted(mounts, key=lambda item: str(item["destination"]))


def _inspect_by_id(
    container_id: str,
    inspect_records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    exact = [record for record in inspect_records if str(_value(record, "Id", "ID") or "") == container_id]
    if len(exact) == 1:
        return exact[0]
    prefix = [
        record
        for record in inspect_records
        if str(_value(record, "Id", "ID") or "")
        and (
            str(_value(record, "Id", "ID") or "").startswith(container_id)
            or container_id.startswith(str(_value(record, "Id", "ID") or ""))
        )
    ]
    return prefix[0] if len(prefix) == 1 else None


def _container_record(
    compose_record: dict[str, Any],
    inspect_records: list[dict[str, Any]],
    errors: list[str],
) -> dict[str, object]:
    container_id = str(_value(compose_record, "ID", "Id") or "").strip()
    service = str(_value(compose_record, "Service", "service") or "").strip()
    name = str(_value(compose_record, "Name", "name") or "").strip()
    state = str(_value(compose_record, "State", "state") or "").strip().lower()
    health = str(_value(compose_record, "Health", "health") or "").strip().lower()
    image = str(_value(compose_record, "Image", "image") or "").strip()
    inspected = _inspect_by_id(container_id, inspect_records) if container_id else None
    if not container_id:
        errors.append(f"service {service or '<unknown>'} has no container ID")
    if inspected is None:
        errors.append(f"service {service or '<unknown>'} container {container_id or '<missing>'} was not inspected")
        mounts: list[dict[str, object]] = []
        image_id = ""
    else:
        mounts = _safe_mounts(inspected)
        image_id = str(_value(inspected, "Image", "ImageID") or "").strip()
        if not image_id:
            errors.append(f"service {service or '<unknown>'} has no inspected image ID")
        inspected_state = inspected.get("State")
        if isinstance(inspected_state, dict):
            state = str(inspected_state.get("Status") or state).strip().lower()
            health_record = inspected_state.get("Health")
            if isinstance(health_record, dict):
                health = str(health_record.get("Status") or health).strip().lower()
    return {
        "service": service,
        "name": name,
        "containerId": container_id,
        "image": image,
        "imageId": image_id,
        "state": state,
        "health": health or "not-configured",
        "mounts": mounts,
    }


def _validate_container(
    container: dict[str, object],
    contract: ServiceContract,
    errors: list[str],
) -> None:
    service = str(container["service"])
    if container["state"] != "running":
        errors.append(f"service {service} is {container['state'] or 'unknown'}, expected running")
    if contract.healthy and container["health"] != "healthy":
        errors.append(f"service {service} health is {container['health']}, expected healthy")
    mounts = container["mounts"]
    assert isinstance(mounts, list)
    for destination in contract.writable_mounts:
        matching = [
            mount
            for mount in mounts
            if isinstance(mount, dict) and mount.get("destination") == destination
        ]
        if len(matching) != 1:
            errors.append(f"service {service} must have exactly one mount at {destination}")
            continue
        mount = matching[0]
        if mount.get("type") not in {"bind", "volume"}:
            errors.append(f"service {service} mount {destination} must be a bind or named volume")
        if mount.get("readWrite") is not True:
            errors.append(f"service {service} mount {destination} must be writable")
        if not mount.get("sourceFingerprint"):
            errors.append(f"service {service} mount {destination} has no observable source")


def build_inventory(
    compose_records: list[dict[str, Any]],
    inspect_records: list[dict[str, Any]],
    *,
    compose_file: str,
    observed_at: str | None = None,
) -> dict[str, object]:
    errors: list[str] = []
    containers = [
        _container_record(record, inspect_records, errors)
        for record in compose_records
    ]
    services = [str(container["service"]) for container in containers]
    service_counts = {service: services.count(service) for service in sorted(set(services))}
    unexpected = sorted(set(services) - set(SERVICE_CONTRACTS))
    if unexpected:
        errors.append(f"unexpected compose services: {', '.join(unexpected)}")
    for service, contract in SERVICE_CONTRACTS.items():
        matching = [container for container in containers if container["service"] == service]
        if len(matching) != 1:
            errors.append(f"service {service} count is {len(matching)}, expected exactly 1")
            continue
        _validate_container(matching[0], contract, errors)

    durable_sources: dict[str, str] = {}
    for container in containers:
        service = str(container["service"])
        mounts = container["mounts"]
        if not isinstance(mounts, list):
            continue
        for mount in mounts:
            if not isinstance(mount, dict):
                continue
            fingerprint = str(mount.get("sourceFingerprint") or "")
            destination = str(mount.get("destination") or "")
            if not fingerprint:
                continue
            prior = durable_sources.get(fingerprint)
            current = f"{service}:{destination}"
            if prior and prior != current:
                errors.append(f"durable mount source is shared by {prior} and {current}")
            durable_sources[fingerprint] = current

    projects = {
        str(_value(record, "Project", "project") or "").strip()
        for record in compose_records
        if str(_value(record, "Project", "project") or "").strip()
    }
    if len(projects) != 1:
        errors.append(f"expected one observed Compose project, found {len(projects)}")

    payload: dict[str, object] = {
        "schemaVersion": "1.0",
        "observedAt": observed_at or datetime.now(timezone.utc).isoformat(),
        "observationSource": "docker compose ps --all plus docker inspect",
        "observedExternally": True,
        "composeFile": pathlib.Path(compose_file).name,
        "composeProject": next(iter(projects), ""),
        "serviceCounts": service_counts,
        "containers": sorted(containers, key=lambda item: (str(item["service"]), str(item["name"]))),
        "errors": errors,
        "supported": not errors,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["inventorySha256"] = hashlib.sha256(serialized).hexdigest()
    return payload


def _run(command: list[str], *, cwd: pathlib.Path, timeout: float) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise TopologyInventoryError("docker CLI was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise TopologyInventoryError(f"command timed out after {timeout:g}s: {' '.join(command[:3])}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        safe_detail = detail[-1][:500] if detail else f"exit {result.returncode}"
        raise TopologyInventoryError(f"command failed: {' '.join(command[:3])}: {safe_detail}")
    return result.stdout


def observe_inventory(
    compose_file: pathlib.Path,
    *,
    timeout: float,
    project_name: str | None = None,
) -> dict[str, object]:
    resolved = compose_file.resolve()
    if not resolved.is_file():
        raise TopologyInventoryError(f"compose file does not exist: {resolved}")
    compose_command = ["docker", "compose", "--file", resolved.name]
    if project_name:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project_name):
            raise TopologyInventoryError("project name must match [a-z0-9][a-z0-9_-]{0,62}")
        compose_command.extend(["--project-name", project_name])
    compose_command.extend(["ps", "--all", "--format", "json"])
    compose_output = _run(
        compose_command,
        cwd=resolved.parent,
        timeout=timeout,
    )
    compose_records = parse_json_records(compose_output, label="docker compose ps")
    container_ids = [
        str(_value(record, "ID", "Id") or "").strip()
        for record in compose_records
        if str(_value(record, "ID", "Id") or "").strip()
    ]
    inspect_records: list[dict[str, Any]] = []
    if container_ids:
        inspect_output = _run(
            ["docker", "inspect", "--type", "container", *container_ids],
            cwd=resolved.parent,
            timeout=timeout,
        )
        inspect_records = parse_json_records(inspect_output, label="docker inspect")
    return build_inventory(
        compose_records,
        inspect_records,
        compose_file=str(resolved),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", default="docker-compose.yml")
    parser.add_argument("--project-name", help="Exact deployed Compose project name when it differs from the directory.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0 < args.timeout <= 120:
        print("topology inventory error: --timeout must be between 0 and 120 seconds", file=sys.stderr)
        return 2
    try:
        inventory = observe_inventory(
            pathlib.Path(args.compose_file),
            timeout=args.timeout,
            project_name=args.project_name,
        )
    except TopologyInventoryError as exc:
        print(f"topology inventory error: {exc}", file=sys.stderr)
        return 2
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": inventory["supported"], "output": str(output)}, sort_keys=True))
    return 0 if inventory["supported"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
