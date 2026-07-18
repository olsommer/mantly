"""Validate deployment topology against the capabilities of this release."""

from __future__ import annotations

import os
import socket
from dataclasses import asdict, dataclass
from typing import Mapping

_SCHEDULER_INTERVALS = (
    "SUPPORT_SYNC_INTERVAL_SECONDS",
    "SUPPORT_DELIVERY_INTERVAL_SECONDS",
    "SUPPORT_CRM_SYNC_INTERVAL_SECONDS",
    "SUPPORT_SLA_INTERVAL_SECONDS",
)


@dataclass(frozen=True)
class RuntimeTopology:
    instance_id: str
    api_replicas: int
    storage_mode: str
    worker_mode: str
    local_application_data: bool
    enabled_in_process_schedulers: tuple[str, ...]
    supported: bool

    def as_public_dict(self) -> dict[str, object]:
        return asdict(self)


def _positive_int(value: str | None, *, name: str, default: int) -> int:
    raw = str(value if value is not None else default).strip()
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if parsed < 1:
        raise RuntimeError(f"{name} must be at least 1")
    return parsed


def _enabled_schedulers(env: Mapping[str, str]) -> tuple[str, ...]:
    enabled: list[str] = []
    for name in _SCHEDULER_INTERVALS:
        raw = env.get(name, "0").strip() or "0"
        try:
            interval = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer number of seconds, got {raw!r}") from exc
        if interval < 0:
            raise RuntimeError(f"{name} cannot be negative")
        if interval > 0:
            enabled.append(name)
    return tuple(enabled)


def inspect_runtime_topology(env: Mapping[str, str] | None = None) -> RuntimeTopology:
    values = os.environ if env is None else env
    replicas = _positive_int(values.get("MANTLY_API_REPLICAS"), name="MANTLY_API_REPLICAS", default=1)
    storage_mode = values.get("MANTLY_STORAGE_MODE", "pocketbase-sqlite").strip().lower()
    worker_mode = values.get("MANTLY_WORKER_MODE", "in-process").strip().lower()
    local_application_data = values.get("MANTLY_LOCAL_APPLICATION_DATA", "true").strip().lower() == "true"
    instance_id = values.get("MANTLY_INSTANCE_ID", "").strip() or socket.gethostname()
    schedulers = _enabled_schedulers(values)

    supported = (
        replicas == 1
        and storage_mode == "pocketbase-sqlite"
        and worker_mode in {"in-process", "disabled"}
        and local_application_data
    )
    return RuntimeTopology(
        instance_id=instance_id,
        api_replicas=replicas,
        storage_mode=storage_mode,
        worker_mode=worker_mode,
        local_application_data=local_application_data,
        enabled_in_process_schedulers=schedulers,
        supported=supported,
    )


def validate_runtime_topology(env: Mapping[str, str] | None = None) -> RuntimeTopology:
    """Reject deployments whose correctness is not supported by this release.

    The current implementation uses PocketBase/SQLite, local application data,
    and optional in-process scheduler threads. It deliberately supports one API
    process. Horizontal scaling requires the external worker, durable lease,
    Postgres/object-storage migration described in the architecture docs.
    """

    topology = inspect_runtime_topology(env)
    errors: list[str] = []

    if topology.api_replicas != 1:
        errors.append(
            "MANTLY_API_REPLICAS must remain 1: this release does not support "
            "multiple API writers against PocketBase/SQLite or duplicated in-process schedulers"
        )
    if topology.storage_mode != "pocketbase-sqlite":
        errors.append(
            f"MANTLY_STORAGE_MODE={topology.storage_mode!r} is not implemented; "
            "the supported value is 'pocketbase-sqlite'"
        )
    if topology.worker_mode not in {"in-process", "disabled"}:
        errors.append(
            f"MANTLY_WORKER_MODE={topology.worker_mode!r} is not implemented; "
            "the supported values are 'in-process' and 'disabled'"
        )
    if not topology.local_application_data:
        errors.append(
            "MANTLY_LOCAL_APPLICATION_DATA=false is not implemented; this release requires the mounted /app/data volume"
        )
    if topology.worker_mode == "disabled" and topology.enabled_in_process_schedulers:
        errors.append(
            "MANTLY_WORKER_MODE=disabled conflicts with enabled scheduler intervals: "
            + ", ".join(topology.enabled_in_process_schedulers)
        )

    if errors:
        raise RuntimeError("Unsupported Mantly runtime topology:\n- " + "\n- ".join(errors))
    return topology
