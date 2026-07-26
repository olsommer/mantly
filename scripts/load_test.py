#!/usr/bin/env python3
"""Small dependency-free HTTP load harness for Mantly capacity evidence.

Use synthetic tenants and blocked/test providers. The tool intentionally avoids
printing request headers or bodies because they may contain credentials or
customer data.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import ipaddress
import json
import math
import pathlib
import random
import re
import socket
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MAX_SCENARIO_BYTES = 1024 * 1024
MAX_JSON_BODY_BYTES = 1024 * 1024
MAX_TARGETS = 100
MAX_CONCURRENCY = 256
MAX_RATE_PER_SECOND = 1000.0
MAX_DURATION_SECONDS = 6 * 60 * 60
MAX_TIMEOUT_SECONDS = 120.0
MAX_REQUESTS = 1_000_000

_SUPPORTED_THRESHOLD_NAMES = frozenset(
    {
        "errorRateMax",
        "p95MsMax",
        "p99MsMax",
        "throughputPerSecondMin",
        "minimumRequests",
        "minimumRequestsPerTarget",
    }
)
_REQUIRED_THRESHOLD_NAMES = frozenset(
    {
        "errorRateMax",
        "p95MsMax",
        "throughputPerSecondMin",
        "minimumRequests",
        "minimumRequestsPerTarget",
    }
)
CAPACITY_WORKLOADS = frozenset(
    {
        "attachment-processing",
        "inbound-ingestion",
        "inbox-read",
        "knowledge-lookup",
        "model-execution",
        "outbound-delivery",
        "runbook-match",
        "tool-lookup",
    }
)
_SUPPORTED_WORKLOADS = CAPACITY_WORKLOADS | {"health", "readiness"}
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "x-load-test",
    }
)


@dataclass(frozen=True)
class Target:
    name: str
    method: str
    path: str
    workloads: tuple[str, ...]
    weight: int
    expected_statuses: tuple[int, ...]
    body: bytes | None
    content_type: str | None


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    kind: str
    targets: tuple[Target, ...]
    thresholds: dict[str, int | float]
    sha256: str


@dataclass(frozen=True)
class TargetPolicy:
    base_url: str
    host: str
    port: int
    resolved_addresses: tuple[str, ...]


@dataclass(frozen=True)
class Sample:
    target: str
    status: int
    duration_ms: float
    ok: bool
    error: str | None


class LoadTestError(ValueError):
    pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def percentile(values: list[float], probability: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def latency_summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "minMs": min(values) if values else None,
        "medianMs": statistics.median(values) if values else None,
        "p90Ms": percentile(values, 0.90),
        "p95Ms": percentile(values, 0.95),
        "p99Ms": percentile(values, 0.99),
        "maxMs": max(values) if values else None,
        "averageMs": statistics.fmean(values) if values else None,
    }


def _validate_route(route: str, *, target_name: str) -> None:
    if len(route) > 4096:
        raise LoadTestError(f"scenario target {target_name}: path exceeds 4096 characters")
    if not route.startswith("/") or route.startswith("//"):
        raise LoadTestError(f"scenario target {target_name}: path must start with exactly one /")
    if "\\" in route or any(ord(character) < 32 for character in route):
        raise LoadTestError(f"scenario target {target_name}: path contains forbidden characters")
    parsed = urllib.parse.urlsplit(route)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise LoadTestError(f"scenario target {target_name}: path must be a relative HTTP path without a fragment")


def _validated_thresholds(raw: object) -> dict[str, int | float]:
    if not isinstance(raw, dict):
        raise LoadTestError("scenario.thresholds must be an object")
    unknown = sorted(set(raw) - _SUPPORTED_THRESHOLD_NAMES)
    if unknown:
        raise LoadTestError(f"unsupported threshold(s): {', '.join(unknown)}")
    missing = sorted(_REQUIRED_THRESHOLD_NAMES - set(raw))
    if missing:
        raise LoadTestError(f"scenario.thresholds missing required checks: {', '.join(missing)}")

    thresholds: dict[str, int | float] = {}
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise LoadTestError(f"threshold {name} must be a finite number")
        if name in {"minimumRequests", "minimumRequestsPerTarget"}:
            if not isinstance(value, int) or value < 1:
                raise LoadTestError(f"threshold {name} must be a positive integer")
        elif name == "errorRateMax":
            if not 0 <= float(value) <= 1:
                raise LoadTestError("threshold errorRateMax must be between 0 and 1")
        elif float(value) <= 0:
            raise LoadTestError(f"threshold {name} must be greater than 0")
        thresholds[name] = value
    return thresholds


def parse_scenario(path: pathlib.Path) -> Scenario:
    try:
        scenario_bytes = path.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise LoadTestError(f"cannot read scenario {path}: {exc}") from exc
    if len(scenario_bytes) > MAX_SCENARIO_BYTES:
        raise LoadTestError(f"scenario exceeds {MAX_SCENARIO_BYTES} bytes")
    try:
        raw = json.loads(scenario_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LoadTestError(f"cannot read scenario {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LoadTestError("scenario root must be an object")
    if raw.get("schemaVersion") != "1.0":
        raise LoadTestError("scenario.schemaVersion must be '1.0'")
    scenario_id = raw.get("scenarioId")
    if not isinstance(scenario_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,99}", scenario_id):
        raise LoadTestError("scenario.scenarioId must be a stable 3-100 character identifier")
    kind = raw.get("kind")
    if kind not in {"smoke", "capacity"}:
        raise LoadTestError("scenario.kind must be 'smoke' or 'capacity'")
    targets_raw = raw.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise LoadTestError("scenario.targets must be a non-empty list")
    if len(targets_raw) > MAX_TARGETS:
        raise LoadTestError(f"scenario.targets cannot exceed {MAX_TARGETS} entries")

    targets: list[Target] = []
    target_names: set[str] = set()
    for index, item in enumerate(targets_raw):
        if not isinstance(item, dict):
            raise LoadTestError(f"scenario target {index} must be an object")
        name = item.get("name")
        method = str(item.get("method", "GET")).upper()
        route = item.get("path")
        workloads_raw = item.get("workloads")
        weight = item.get("weight", 1)
        expected = item.get("expectedStatuses", [200])
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,99}", name):
            raise LoadTestError(f"scenario target {index}.name must be a stable 2-100 character identifier")
        if name in target_names:
            raise LoadTestError(f"scenario target name {name!r} is duplicated")
        target_names.add(name)
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise LoadTestError(f"scenario target {name}: unsupported method {method}")
        if not isinstance(route, str):
            raise LoadTestError(f"scenario target {name}: path must be a string")
        _validate_route(route, target_name=name)
        if (
            not isinstance(workloads_raw, list)
            or not workloads_raw
            or any(not isinstance(value, str) or value not in _SUPPORTED_WORKLOADS for value in workloads_raw)
        ):
            raise LoadTestError(
                f"scenario target {name}: workloads must be a non-empty list of supported workload classifications"
            )
        workloads = tuple(dict.fromkeys(workloads_raw))
        if not isinstance(weight, int) or isinstance(weight, bool) or not 1 <= weight <= 1_000_000:
            raise LoadTestError(f"scenario target {name}: weight must be an integer between 1 and 1000000")
        if (
            not isinstance(expected, list)
            or not expected
            or any(isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599 for value in expected)
        ):
            raise LoadTestError(f"scenario target {name}: expectedStatuses must be HTTP status integers")
        body_value = item.get("jsonBody")
        body: bytes | None = None
        content_type: str | None = None
        if body_value is not None:
            body = json.dumps(body_value, separators=(",", ":")).encode("utf-8")
            if len(body) > MAX_JSON_BODY_BYTES:
                raise LoadTestError(f"scenario target {name}: jsonBody exceeds {MAX_JSON_BODY_BYTES} bytes")
            content_type = "application/json"
        targets.append(
            Target(
                name=name,
                method=method,
                path=route,
                workloads=workloads,
                weight=weight,
                expected_statuses=tuple(expected),
                body=body,
                content_type=content_type,
            )
        )
    thresholds = _validated_thresholds(raw.get("thresholds"))
    if sum(target.weight for target in targets) > 1_000_000:
        raise LoadTestError("sum of scenario target weights cannot exceed 1000000")
    covered_workloads = {workload for target in targets for workload in target.workloads}
    if kind == "capacity":
        missing_workloads = sorted(CAPACITY_WORKLOADS - covered_workloads)
        if missing_workloads:
            raise LoadTestError(
                f"capacity scenario missing required workloads: {', '.join(missing_workloads)}"
            )
    return Scenario(
        scenario_id=scenario_id,
        kind=kind,
        targets=tuple(targets),
        thresholds=thresholds,
        sha256=hashlib.sha256(scenario_bytes).hexdigest(),
    )


def parse_header_env(values: list[str]) -> dict[str, str]:
    import os

    headers: dict[str, str] = {}
    header_names: set[str] = set()
    for value in values:
        if "=" not in value:
            raise LoadTestError("--header-env must use Header-Name=ENV_VAR")
        header, env_name = value.split("=", 1)
        header = header.strip()
        env_name = env_name.strip()
        if not header or not env_name:
            raise LoadTestError("--header-env requires non-empty header and environment variable")
        if not _HEADER_NAME_RE.fullmatch(header):
            raise LoadTestError(f"invalid HTTP header name: {header!r}")
        if header.lower() in _FORBIDDEN_HEADERS:
            raise LoadTestError(f"--header-env cannot set controlled header {header!r}")
        if header.lower() in header_names:
            raise LoadTestError(f"--header-env repeats header {header!r}")
        header_names.add(header.lower())
        if not _ENV_NAME_RE.fullmatch(env_name):
            raise LoadTestError(f"invalid environment variable name: {env_name!r}")
        secret = os.getenv(env_name)
        if secret is None:
            raise LoadTestError(f"environment variable {env_name} is not set")
        if any(ord(character) < 32 or ord(character) == 127 for character in secret):
            raise LoadTestError(f"environment variable {env_name} contains a control character")
        if len(secret) > 8192:
            raise LoadTestError(f"environment variable {env_name} exceeds the header value limit")
        headers[header] = secret
    return headers


def _normalized_host(value: str) -> str:
    return value.rstrip(".").encode("idna").decode("ascii").lower()


def _allowed_authority(value: str, *, scheme: str) -> tuple[str, int]:
    clean = value.strip()
    if not clean or any(token in clean for token in ("/", "\\", "@", "?", "#")):
        raise LoadTestError(f"invalid --allowed-host value: {value!r}")
    try:
        parsed = urllib.parse.urlsplit(f"//{clean}")
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise LoadTestError(f"invalid --allowed-host value: {value!r}") from exc
    if not host:
        raise LoadTestError(f"invalid --allowed-host value: {value!r}")
    return _normalized_host(host), port or (443 if scheme == "https" else 80)


def _resolved_addresses(host: str, port: int) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise LoadTestError(f"cannot resolve load-test host {host!r}") from exc
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for record in records:
        raw_address = record[4][0].split("%", 1)[0]
        try:
            addresses.add(ipaddress.ip_address(raw_address))
        except ValueError as exc:
            raise LoadTestError(f"resolver returned an invalid address for {host!r}") from exc
    if not addresses:
        raise LoadTestError(f"load-test host {host!r} resolved to no addresses")
    return tuple(sorted(addresses, key=lambda address: (address.version, int(address))))


def validate_base_url(
    base_url: str,
    allowed_hosts: list[str],
    *,
    allow_private_target: bool,
) -> TargetPolicy:
    try:
        parsed = urllib.parse.urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        raise LoadTestError("invalid --base-url") from exc
    if parsed.scheme not in {"http", "https"}:
        raise LoadTestError("--base-url scheme must be http or https")
    if parsed.username or parsed.password:
        raise LoadTestError("--base-url cannot contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise LoadTestError("--base-url must be an origin without path, query, or fragment")
    if not parsed.hostname:
        raise LoadTestError("--base-url must include a host")
    if parsed.scheme == "http" and not allow_private_target:
        raise LoadTestError("plain HTTP is allowed only with --allow-private-target in an isolated environment")

    host = _normalized_host(parsed.hostname)
    effective_port = port or (443 if parsed.scheme == "https" else 80)
    allowed = {_allowed_authority(value, scheme=parsed.scheme) for value in allowed_hosts}
    if (host, effective_port) not in allowed:
        raise LoadTestError(
            f"--base-url authority {host}:{effective_port} is not present in the exact --allowed-host list"
        )

    addresses = _resolved_addresses(host, effective_port)
    for address in addresses:
        if address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified:
            raise LoadTestError(f"load-test target resolves to forbidden address {address}")
        if not address.is_global and not allow_private_target:
            raise LoadTestError(
                f"load-test target resolves to non-public address {address}; "
                "use --allow-private-target only for an authorized isolated environment"
            )
    canonical_host = f"[{host}]" if ":" in host else host
    default_port = 443 if parsed.scheme == "https" else 80
    authority = canonical_host if effective_port == default_port else f"{canonical_host}:{effective_port}"
    return TargetPolicy(
        base_url=f"{parsed.scheme}://{authority}",
        host=host,
        port=effective_port,
        resolved_addresses=tuple(str(address) for address in addresses),
    )


def choose_target(targets: tuple[Target, ...], randomizer: random.Random) -> Target:
    total = sum(target.weight for target in targets)
    selected = randomizer.randint(1, total)
    cumulative = 0
    for target in targets:
        cumulative += target.weight
        if selected <= cumulative:
            return target
    return targets[-1]


def execute_request(policy: TargetPolicy, target: Target, headers: dict[str, str], timeout: float) -> Sample:
    url = policy.base_url.rstrip("/") + target.path
    request_headers = dict(headers)
    request_headers["Accept"] = "application/json"
    request_headers["X-Load-Test"] = "synthetic-capacity-evidence"
    if target.content_type:
        request_headers["Content-Type"] = target.content_type
    request = urllib.request.Request(
        url,
        data=target.body,
        headers=request_headers,
        method=target.method,
    )
    started = time.perf_counter()
    status = 0
    error: str | None = None
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())
        with opener.open(request, timeout=timeout) as response:
            status = response.status
            response.read(1024)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.read(1024)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        error = type(exc).__name__
    duration_ms = (time.perf_counter() - started) * 1000
    return Sample(
        target=target.name,
        status=status,
        duration_ms=duration_ms,
        ok=error is None and status in target.expected_statuses,
        error=error,
    )


def threshold_result(summary: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    target_request_counts = [int(item["requests"]) for item in summary["byTarget"].values()]
    mappings = {
        "errorRateMax": summary["errorRate"],
        "p95MsMax": summary["latency"]["p95Ms"],
        "p99MsMax": summary["latency"]["p99Ms"],
        "throughputPerSecondMin": summary["throughputPerSecond"],
        "minimumRequests": summary["requests"],
        "minimumRequestsPerTarget": min(target_request_counts, default=0),
    }
    for name, actual in mappings.items():
        if name not in thresholds:
            continue
        target = thresholds[name]
        if isinstance(target, bool) or not isinstance(target, (int, float)):
            raise LoadTestError(f"threshold {name} must be numeric")
        if actual is None:
            passed = False
        elif name.endswith("Max"):
            passed = actual <= target
        else:
            passed = actual >= target
        checks[name] = {"actual": actual, "target": target, "pass": passed}
    missing = sorted(_REQUIRED_THRESHOLD_NAMES - set(checks))
    return {
        "checks": checks,
        "missingRequiredChecks": missing,
        "allPassed": not missing and bool(checks) and all(item["pass"] for item in checks.values()),
    }


def run_load_test(args: argparse.Namespace) -> dict[str, Any]:
    scenario = parse_scenario(pathlib.Path(args.scenario))
    headers = parse_header_env(args.header_env)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{2,199}", args.release_id):
        raise LoadTestError("release-id must be a stable 3-200 character identifier")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,99}", args.environment_id):
        raise LoadTestError("environment-id must be a stable 3-100 character identifier")
    if args.run_kind not in {"steady", "burst", "soak", "degraded-provider"}:
        raise LoadTestError("run-kind is invalid")
    policy = validate_base_url(
        args.base_url,
        args.allowed_host,
        allow_private_target=args.allow_private_target,
    )
    if not 0 < args.duration <= MAX_DURATION_SECONDS:
        raise LoadTestError(f"duration must be greater than 0 and at most {MAX_DURATION_SECONDS} seconds")
    if not 0 < args.concurrency <= MAX_CONCURRENCY:
        raise LoadTestError(f"concurrency must be between 1 and {MAX_CONCURRENCY}")
    if not 0 < args.rate <= MAX_RATE_PER_SECOND:
        raise LoadTestError(f"rate must be greater than 0 and at most {MAX_RATE_PER_SECOND}")
    if not 0 < args.timeout <= MAX_TIMEOUT_SECONDS:
        raise LoadTestError(f"timeout must be greater than 0 and at most {MAX_TIMEOUT_SECONDS} seconds")
    if not 0 < args.max_requests <= MAX_REQUESTS:
        raise LoadTestError(f"max-requests must be between 1 and {MAX_REQUESTS}")
    planned_requests = math.ceil(args.duration * args.rate)
    if planned_requests > args.max_requests:
        raise LoadTestError(
            f"configured duration and rate schedule about {planned_requests} requests, "
            f"above --max-requests {args.max_requests}"
        )

    randomizer = random.Random(args.seed)
    samples: list[Sample] = []
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()
    stop_at = started_monotonic + args.duration
    interval = 1.0 / args.rate
    next_slot = started_monotonic
    submitted = 0
    futures: dict[concurrent.futures.Future[Sample], str] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        while time.monotonic() < stop_at and submitted < args.max_requests:
            now = time.monotonic()
            done = {future for future in futures if future.done()}
            for future in done:
                try:
                    samples.append(future.result())
                except Exception as exc:
                    raise LoadTestError(
                        f"request worker failed for target {futures[future]!r}: {type(exc).__name__}"
                    ) from exc
                del futures[future]
            if len(futures) >= args.concurrency:
                concurrent.futures.wait(
                    futures,
                    timeout=min(max(stop_at - now, 0.0), 0.05),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                continue
            if now < next_slot:
                time.sleep(min(next_slot - now, 0.05))
                continue
            target = choose_target(scenario.targets, randomizer)
            future = executor.submit(execute_request, policy, target, headers, args.timeout)
            futures[future] = target.name
            submitted += 1
            next_slot = max(next_slot + interval, time.monotonic())
        for future in concurrent.futures.as_completed(futures):
            try:
                samples.append(future.result())
            except Exception as exc:
                raise LoadTestError(
                    f"request worker failed for target {futures[future]!r}: {type(exc).__name__}"
                ) from exc

    completed_at = datetime.now(timezone.utc)
    elapsed_seconds = max(time.monotonic() - started_monotonic, 0.001)
    succeeded = [sample for sample in samples if sample.ok]
    errors = [sample for sample in samples if not sample.ok]
    by_target: dict[str, Any] = {}
    for target in scenario.targets:
        target_samples = [sample for sample in samples if sample.target == target.name]
        target_errors = [sample for sample in target_samples if not sample.ok]
        by_target[target.name] = {
            "workloads": list(target.workloads),
            "requests": len(target_samples),
            "errors": len(target_errors),
            "errorRate": len(target_errors) / len(target_samples) if target_samples else None,
            "latency": latency_summary([sample.duration_ms for sample in target_samples]),
            "statusCounts": dict(sorted(Counter(str(sample.status) for sample in target_samples).items())),
            "errorKinds": dict(sorted(Counter(sample.error or f"HTTP_{sample.status}" for sample in target_errors).items())),
        }

    summary: dict[str, Any] = {
        "schemaVersion": "1.0",
        "releaseId": args.release_id,
        "environmentId": args.environment_id,
        "runKind": args.run_kind,
        "startedAt": started_at.isoformat(),
        "generatedAt": completed_at.isoformat(),
        "runElapsedSeconds": elapsed_seconds,
        "baseUrl": policy.base_url,
        "resolvedAddresses": list(policy.resolved_addresses),
        "scenario": pathlib.Path(args.scenario).name,
        "scenarioId": scenario.scenario_id,
        "scenarioKind": scenario.kind,
        "scenarioSha256": scenario.sha256,
        "workloads": sorted({workload for target in scenario.targets for workload in target.workloads}),
        "configured": {
            "durationSeconds": args.duration,
            "concurrency": args.concurrency,
            "targetRatePerSecond": args.rate,
            "timeoutSeconds": args.timeout,
            "maxRequests": args.max_requests,
            "seed": args.seed,
        },
        "requests": len(samples),
        "scheduledRequests": submitted,
        "successes": len(succeeded),
        "errors": len(errors),
        "errorRate": len(errors) / len(samples) if samples else 1.0,
        "throughputPerSecond": len(succeeded) / elapsed_seconds,
        "requestThroughputPerSecond": len(samples) / elapsed_seconds,
        "latency": latency_summary([sample.duration_ms for sample in samples]),
        "statusCounts": dict(sorted(Counter(str(sample.status) for sample in samples).items())),
        "errorKinds": dict(sorted(Counter(sample.error or f"HTTP_{sample.status}" for sample in errors).items())),
        "byTarget": by_target,
        "capacityApprovalEligible": False,
        "capacityApprovalReason": (
            "one harness run is never capacity approval; validate the complete multi-run operational evidence package"
        ),
    }
    summary["thresholds"] = threshold_result(summary, scenario.thresholds)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", required=True, help="Immutable commit SHA or image-set identifier.")
    parser.add_argument("--environment-id", required=True, help="Stable identifier for the isolated capacity environment.")
    parser.add_argument(
        "--run-kind",
        required=True,
        choices=("steady", "burst", "soak", "degraded-provider"),
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--allowed-host",
        action="append",
        required=True,
        help="Exact authorized host[:port]. Repeat for each approved target; the base URL must match one.",
    )
    parser.add_argument(
        "--allow-private-target",
        action="store_true",
        help="Permit loopback/private targets for an explicitly authorized isolated environment. Link-local targets remain blocked.",
    )
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--rate", type=float, default=5.0, help="Target requests per second")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-requests", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--header-env",
        action="append",
        default=[],
        metavar="HEADER=ENV_VAR",
        help="Read a sensitive header value from an environment variable without writing it to the scenario/report.",
    )
    parser.add_argument("--output", default="load-test-result.json")
    parser.add_argument("--fail-on-threshold", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_load_test(args)
    except LoadTestError as exc:
        print(json.dumps({"schemaVersion": "1.0", "ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    output = pathlib.Path(args.output)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["thresholds"]["allPassed"], "output": str(output), **result}, indent=2, sort_keys=True))
    if args.fail_on_threshold and not result["thresholds"]["allPassed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
