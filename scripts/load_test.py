#!/usr/bin/env python3
"""Small dependency-free HTTP load harness for Mantly capacity evidence.

Use synthetic tenants and blocked/test providers. The tool intentionally avoids
printing request headers or bodies because they may contain credentials or
customer data.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import pathlib
import random
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Target:
    name: str
    method: str
    path: str
    weight: int
    expected_statuses: tuple[int, ...]
    body: bytes | None
    content_type: str | None


@dataclass(frozen=True)
class Sample:
    target: str
    status: int
    duration_ms: float
    ok: bool
    error: str | None


class LoadTestError(ValueError):
    pass


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


def parse_scenario(path: pathlib.Path) -> tuple[list[Target], dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoadTestError(f"cannot read scenario {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LoadTestError("scenario root must be an object")
    targets_raw = raw.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise LoadTestError("scenario.targets must be a non-empty list")

    targets: list[Target] = []
    for index, item in enumerate(targets_raw):
        if not isinstance(item, dict):
            raise LoadTestError(f"scenario target {index} must be an object")
        name = item.get("name")
        method = str(item.get("method", "GET")).upper()
        route = item.get("path")
        weight = item.get("weight", 1)
        expected = item.get("expectedStatuses", [200])
        if not isinstance(name, str) or not name:
            raise LoadTestError(f"scenario target {index}.name is required")
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise LoadTestError(f"scenario target {name}: unsupported method {method}")
        if not isinstance(route, str) or not route.startswith("/"):
            raise LoadTestError(f"scenario target {name}: path must start with /")
        if not isinstance(weight, int) or weight < 1:
            raise LoadTestError(f"scenario target {name}: weight must be a positive integer")
        if not isinstance(expected, list) or not expected or any(not isinstance(value, int) for value in expected):
            raise LoadTestError(f"scenario target {name}: expectedStatuses must be integers")
        body_value = item.get("jsonBody")
        body: bytes | None = None
        content_type: str | None = None
        if body_value is not None:
            body = json.dumps(body_value, separators=(",", ":")).encode("utf-8")
            content_type = "application/json"
        targets.append(
            Target(
                name=name,
                method=method,
                path=route,
                weight=weight,
                expected_statuses=tuple(expected),
                body=body,
                content_type=content_type,
            )
        )
    thresholds = raw.get("thresholds", {})
    if not isinstance(thresholds, dict):
        raise LoadTestError("scenario.thresholds must be an object")
    return targets, thresholds


def parse_header_env(values: list[str]) -> dict[str, str]:
    import os

    headers: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise LoadTestError("--header-env must use Header-Name=ENV_VAR")
        header, env_name = value.split("=", 1)
        header = header.strip()
        env_name = env_name.strip()
        if not header or not env_name:
            raise LoadTestError("--header-env requires non-empty header and environment variable")
        secret = os.getenv(env_name)
        if secret is None:
            raise LoadTestError(f"environment variable {env_name} is not set")
        headers[header] = secret
    return headers


def choose_target(targets: list[Target], randomizer: random.Random) -> Target:
    total = sum(target.weight for target in targets)
    selected = randomizer.randint(1, total)
    cumulative = 0
    for target in targets:
        cumulative += target.weight
        if selected <= cumulative:
            return target
    return targets[-1]


def execute_request(base_url: str, target: Target, headers: dict[str, str], timeout: float) -> Sample:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", target.path.lstrip("/"))
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
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
    mappings = {
        "errorRateMax": summary["errorRate"],
        "p95MsMax": summary["latency"]["p95Ms"],
        "p99MsMax": summary["latency"]["p99Ms"],
        "throughputPerSecondMin": summary["throughputPerSecond"],
    }
    for name, actual in mappings.items():
        if name not in thresholds:
            continue
        target = thresholds[name]
        if not isinstance(target, (int, float)):
            raise LoadTestError(f"threshold {name} must be numeric")
        if actual is None:
            passed = False
        elif name.endswith("Max"):
            passed = actual <= target
        else:
            passed = actual >= target
        checks[name] = {"actual": actual, "target": target, "pass": passed}
    return {"checks": checks, "allPassed": all(item["pass"] for item in checks.values())}


def run_load_test(args: argparse.Namespace) -> dict[str, Any]:
    targets, thresholds = parse_scenario(pathlib.Path(args.scenario))
    headers = parse_header_env(args.header_env)
    if args.duration <= 0 or args.concurrency <= 0 or args.rate <= 0:
        raise LoadTestError("duration, concurrency and rate must be positive")
    if args.rate < args.concurrency / max(args.timeout, 0.1):
        # This is not an error; it simply means workers will often wait for the rate limiter.
        pass

    randomizer = random.Random(args.seed)
    samples: list[Sample] = []
    samples_lock = threading.Lock()
    stop_at = time.monotonic() + args.duration
    interval = 1.0 / args.rate
    next_slot = time.monotonic()
    futures: set[concurrent.futures.Future[Sample]] = set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        while time.monotonic() < stop_at:
            now = time.monotonic()
            if now < next_slot:
                time.sleep(min(next_slot - now, 0.05))
                continue
            target = choose_target(targets, randomizer)
            futures.add(executor.submit(execute_request, args.base_url, target, headers, args.timeout))
            next_slot += interval
            done = {future for future in futures if future.done()}
            for future in done:
                with samples_lock:
                    samples.append(future.result())
            futures -= done
        for future in concurrent.futures.as_completed(futures):
            samples.append(future.result())

    completed_at = datetime.now(timezone.utc)
    succeeded = [sample for sample in samples if sample.ok]
    errors = [sample for sample in samples if not sample.ok]
    duration_actual = max(args.duration, 0.001)
    by_target: dict[str, Any] = {}
    for target in targets:
        target_samples = [sample for sample in samples if sample.target == target.name]
        target_errors = [sample for sample in target_samples if not sample.ok]
        by_target[target.name] = {
            "requests": len(target_samples),
            "errors": len(target_errors),
            "errorRate": len(target_errors) / len(target_samples) if target_samples else 0.0,
            "latency": latency_summary([sample.duration_ms for sample in target_samples]),
            "statusCounts": dict(sorted(Counter(str(sample.status) for sample in target_samples).items())),
            "errorKinds": dict(sorted(Counter(sample.error or f"HTTP_{sample.status}" for sample in target_errors).items())),
        }

    summary: dict[str, Any] = {
        "schemaVersion": "1.0",
        "generatedAt": completed_at.isoformat(),
        "baseUrl": urllib.parse.urlsplit(args.base_url)._replace(query="", fragment="").geturl(),
        "scenario": pathlib.Path(args.scenario).name,
        "configured": {
            "durationSeconds": args.duration,
            "concurrency": args.concurrency,
            "targetRatePerSecond": args.rate,
            "timeoutSeconds": args.timeout,
            "seed": args.seed,
        },
        "requests": len(samples),
        "successes": len(succeeded),
        "errors": len(errors),
        "errorRate": len(errors) / len(samples) if samples else 1.0,
        "throughputPerSecond": len(samples) / duration_actual,
        "latency": latency_summary([sample.duration_ms for sample in samples]),
        "statusCounts": dict(sorted(Counter(str(sample.status) for sample in samples).items())),
        "errorKinds": dict(sorted(Counter(sample.error or f"HTTP_{sample.status}" for sample in errors).items())),
        "byTarget": by_target,
    }
    summary["thresholds"] = threshold_result(summary, thresholds)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--rate", type=float, default=5.0, help="Target requests per second")
    parser.add_argument("--timeout", type=float, default=15.0)
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
