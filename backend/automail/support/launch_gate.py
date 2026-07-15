"""CLI gate for support launch-proof readiness."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

import httpx

from automail.support.schema_gate import check_support_schema, evaluate_schema_health

EXIT_READY = 0
EXIT_ERROR = 1
EXIT_BLOCKED = 2


@dataclass(slots=True)
class LaunchGateResult:
    ok: bool
    status: str
    blockers: list[str]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _channel_label(item: dict[str, Any]) -> str:
    name = _text(item.get("name"))
    key = _text(item.get("channelKey") or item.get("key"))
    channel_type = _text(item.get("type"))
    if name and key and name != key:
        return f"{name} ({key})"
    return name or key or channel_type or "unknown channel"


def _launch_item_summary(item: dict[str, Any]) -> str:
    key = _text(item.get("key")) or "blocker"
    label = _text(item.get("label")) or key
    detail = _text(item.get("detail"))
    action = _text(item.get("action"))
    rendered = f"{label}: {detail}" if detail and detail != label else label
    if action:
        rendered = f"{rendered} [action: {action}]"
    return rendered


def _channel_launch_blockers(proof: dict[str, Any]) -> list[str]:
    """Return actionable channel launch proof blocker detail for deploy CLI output."""
    channels = _as_dict(proof.get("channels"))
    blockers: list[str] = []
    for item in _as_list(channels.get("items")):
        if not isinstance(item, dict) or bool(item.get("ready")):
            continue
        channel = _channel_label(item)
        raw_blockers = _as_list(item.get("blockers"))
        if not raw_blockers:
            raw_blockers = [
                check for check in _as_list(item.get("checklist"))
                if isinstance(check, dict) and _text(check.get("status")) not in {"done", "ready", "success"}
            ]
        for blocker in raw_blockers:
            if not isinstance(blocker, dict):
                continue
            blockers.append(f"channel {channel} blocked: {_launch_item_summary(blocker)}")
    return blockers


def _ticket_creation_check(channel: dict[str, Any]) -> dict[str, Any]:
    for check in _as_list(channel.get("checklist")):
        if isinstance(check, dict) and _text(check.get("key")) == "ticket_mode":
            return check
    return {}


def _launch_ticket_creation_summary(proof: dict[str, Any]) -> dict[str, Any]:
    existing = proof.get("ticketCreation")
    if isinstance(existing, dict):
        return existing
    channels = _as_dict(proof.get("channels"))
    items: list[dict[str, Any]] = []
    for channel in _as_list(channels.get("items")):
        if not isinstance(channel, dict) or not bool(channel.get("required", True)):
            continue
        check = _ticket_creation_check(channel)
        ready = _text(check.get("status")) == "done" or _text(check.get("runStatus")) == "per_message"
        items.append({
            "channelId": _text(channel.get("channelId")),
            "channelKey": _text(channel.get("channelKey")),
            "name": _text(channel.get("name")),
            "type": _text(channel.get("type")),
            "mode": _text(check.get("runStatus")),
            "ready": ready,
            "detail": _text(check.get("detail")),
        })
    ready_count = sum(1 for item in items if item["ready"])
    return {
        "total": len(items),
        "ready": ready_count,
        "blocked": max(len(items) - ready_count, 0),
        "wrongMode": sum(1 for item in items if not item["ready"]),
        "items": items,
    }


REPLY_ROUTE_PROOF_KEYS = (
    "human_approved_real_channel_reply",
    "real_channel_reply",
    "lifecycle_smoke",
    "outbound_smoke",
    "email_delivery",
    "web_chat_delivery",
)


def _reply_route_check(channel: dict[str, Any]) -> dict[str, Any]:
    checklist = [check for check in _as_list(channel.get("checklist")) if isinstance(check, dict)]
    for key in REPLY_ROUTE_PROOF_KEYS:
        for check in checklist:
            if _text(check.get("key")) == key and _text(check.get("status")) == "done":
                return check
    for key in REPLY_ROUTE_PROOF_KEYS:
        for check in checklist:
            if _text(check.get("key")) == key:
                return check
    return {}


def _launch_reply_route_summary(proof: dict[str, Any]) -> dict[str, Any]:
    existing = proof.get("replyRoute")
    if isinstance(existing, dict):
        return existing
    channels = _as_dict(proof.get("channels"))
    items: list[dict[str, Any]] = []
    for channel in _as_list(channels.get("items")):
        if not isinstance(channel, dict) or not bool(channel.get("required", True)):
            continue
        check = _reply_route_check(channel)
        delivery_route = _as_dict(check.get("deliveryRoute"))
        ready = _text(check.get("status")) == "done"
        items.append({
            "channelId": _text(channel.get("channelId")),
            "channelKey": _text(channel.get("channelKey")),
            "name": _text(channel.get("name")),
            "type": _text(channel.get("type")),
            "ready": ready,
            "proofKey": _text(check.get("key")),
            "transport": _text(check.get("transport")) or _text(delivery_route.get("transport")),
            "provider": _text(check.get("provider")) or _text(delivery_route.get("provider")),
            "providerMessageId": _text(check.get("providerMessageId")),
            "runId": _text(check.get("runId")),
            "issueId": _text(check.get("issueId")),
            "replyId": _text(check.get("replyId")),
            "detail": _text(check.get("detail")),
        })
    ready_count = sum(1 for item in items if item["ready"])
    return {
        "total": len(items),
        "ready": ready_count,
        "blocked": max(len(items) - ready_count, 0),
        "items": items,
    }


def _channel_autopilot_check(channel: dict[str, Any]) -> dict[str, Any]:
    checklist = [check for check in _as_list(channel.get("checklist")) if isinstance(check, dict)]
    for check in checklist:
        if _text(check.get("key")) == "channel_autopilot" and _text(check.get("status")) == "done":
            return check
    for key in ("channel_autopilot", "auto_prepare"):
        for check in checklist:
            if _text(check.get("key")) == key:
                return check
    return {}


def _launch_channel_autopilot_summary(proof: dict[str, Any]) -> dict[str, Any]:
    existing = proof.get("channelAutopilot")
    if isinstance(existing, dict):
        return existing
    channels = _as_dict(proof.get("channels"))
    items: list[dict[str, Any]] = []
    for channel in _as_list(channels.get("items")):
        if not isinstance(channel, dict) or not bool(channel.get("required", True)):
            continue
        check = _channel_autopilot_check(channel)
        proof_key = _text(check.get("key"))
        ready = proof_key == "channel_autopilot" and _text(check.get("status")) == "done"
        items.append({
            "channelId": _text(channel.get("channelId")),
            "channelKey": _text(channel.get("channelKey")),
            "name": _text(channel.get("name")),
            "type": _text(channel.get("type")),
            "ready": ready,
            "proofKey": proof_key,
            "runStatus": _text(check.get("runStatus")),
            "runId": _text(check.get("runId")),
            "issueId": _text(check.get("issueId")),
            "replyId": _text(check.get("replyId")),
            "aiRunId": _text(check.get("aiRunId")),
            "detail": _text(check.get("detail")),
        })
    ready_count = sum(1 for item in items if item["ready"])
    return {
        "required": True,
        "total": len(items),
        "ready": ready_count,
        "blocked": max(len(items) - ready_count, 0),
        "items": items,
    }


def _launch_knowledge_assist_summary(proof: dict[str, Any]) -> dict[str, Any]:
    existing = proof.get("knowledgeAssist")
    if isinstance(existing, dict):
        return existing
    evidence = _as_dict(proof.get("evidence"))
    items = [item for item in _as_list(evidence.get("knowledgeAssist")) if isinstance(item, dict)]
    warnings = [item for item in _as_list(proof.get("warnings")) if isinstance(item, dict)]
    open_gap_warning = next((item for item in warnings if _text(item.get("key")) == "open_knowledge_gaps"), {})
    citation_runs = sum(1 for item in items if int(item.get("citationCount") or 0) > 0)
    gap_runs = sum(1 for item in items if _text(item.get("knowledgeGapId")))
    ready = bool(items)
    return {
        "required": True,
        "ready": ready,
        "blocked": 0 if ready else 1,
        "articles": 0,
        "openGaps": int(open_gap_warning.get("count") or 0),
        "successfulRuns": len(items),
        "citationRuns": citation_runs,
        "gapRuns": gap_runs,
        "items": items,
    }


def _launch_account_intelligence_summary(proof: dict[str, Any]) -> dict[str, Any]:
    existing = proof.get("accountIntelligence")
    if isinstance(existing, dict):
        return existing
    evidence = _as_dict(proof.get("evidence"))
    items = [item for item in _as_list(evidence.get("accountIntelligence")) if isinstance(item, dict)]
    failed_sync_runs = sum(int(item.get("failedExternalSyncRuns") or 0) for item in items)
    ready = bool(items)
    return {
        "required": True,
        "ready": ready,
        "blocked": 0 if ready else 1,
        "accounts": len({ _text(item.get("accountId")) for item in items if _text(item.get("accountId")) }),
        "actions": len(items),
        "openRisks": sum(int(item.get("openRisks") or 0) for item in items),
        "featureRequests": sum(int(item.get("openFeatureRequests") or 0) for item in items),
        "failedSyncRuns": failed_sync_runs,
        "items": items,
    }


def _launch_human_loop_summary(proof: dict[str, Any]) -> dict[str, Any]:
    existing = proof.get("humanLoop")
    if isinstance(existing, dict):
        return existing
    evidence = _as_dict(proof.get("evidence"))
    items = [item for item in _as_list(evidence.get("humanLoopAutomation")) if isinstance(item, dict)]
    blockers = [item for item in _as_list(proof.get("blockers")) if isinstance(item, dict)]
    warnings = [item for item in _as_list(proof.get("warnings")) if isinstance(item, dict)]
    human_loop_blocker = next(
        (
            item for item in blockers
            if _text(item.get("key")) in {"no_human_loop_automation", "automation_proof_missing"}
        ),
        {},
    )
    pending_approval_warning = next(
        (item for item in warnings if _text(item.get("key")) == "pending_approvals"),
        {},
    )
    ready = bool(items) and not human_loop_blocker
    rules = int(human_loop_blocker.get("count") or len(items) or 0)
    return {
        "required": True,
        "ready": ready,
        "blocked": 0 if ready else 1,
        "rules": rules,
        "successfulRuns": len(items),
        "pendingApprovals": int(pending_approval_warning.get("count") or 0),
        "items": items,
    }


def _launch_ticket_workflow_summary(proof: dict[str, Any]) -> dict[str, Any]:
    existing = proof.get("ticketWorkflow")
    if isinstance(existing, dict):
        return existing
    evidence = _as_dict(proof.get("evidence"))
    items = [item for item in _as_list(evidence.get("workflowLifecycle")) if isinstance(item, dict)]
    blockers = [item for item in _as_list(proof.get("blockers")) if isinstance(item, dict)]
    workflow_blocker = next(
        (item for item in blockers if _text(item.get("key")) == "workflow_lifecycle_proof_missing"),
        {},
    )
    ready = bool(items) and not workflow_blocker
    return {
        "required": True,
        "ready": ready,
        "blocked": 0 if ready else 1,
        "transitions": 0,
        "ongoingTransitions": 0,
        "doneTransitions": 0,
        "successfulIssues": len(items),
        "items": items,
    }


def build_launch_proof_bundle(
    *,
    project_id: str,
    proof: dict[str, Any],
    schema_payload: dict[str, Any] | None = None,
    run_history: list[dict[str, Any]] | None = None,
    run_history_error: str = "",
    activation_plan: dict[str, Any] | None = None,
    activation_plan_error: str = "",
) -> dict[str, Any]:
    """Build a portable launch-proof artifact for CI/deploy handoff."""
    history = run_history or []
    return {
        "kind": "support_launch_proof_bundle",
        "projectId": project_id,
        "exportedAt": datetime.now(UTC).isoformat(),
        "status": str(proof.get("status") or "unknown"),
        "schemaGate": schema_payload,
        "launchProof": proof,
        "ticketCreation": _launch_ticket_creation_summary(proof),
        "replyRoute": _launch_reply_route_summary(proof),
        "channelAutopilot": _launch_channel_autopilot_summary(proof),
        "knowledgeAssist": _launch_knowledge_assist_summary(proof),
        "accountIntelligence": _launch_account_intelligence_summary(proof),
        "humanLoop": _launch_human_loop_summary(proof),
        "ticketWorkflow": _launch_ticket_workflow_summary(proof),
        "activationPlan": activation_plan,
        "activationPlanError": activation_plan_error,
        "latestRun": history[0] if history else None,
        "runHistory": history,
        "runHistoryError": run_history_error,
    }


def _schema_blocked_launch_proof(schema_health: dict[str, Any], schema_result: Any) -> dict[str, Any]:
    details = "; ".join(str(blocker) for blocker in getattr(schema_result, "blockers", []) if blocker)
    return {
        "status": "blocked",
        "schema": schema_health,
        "channels": {"blocked": 0, "items": []},
        "blockers": [
            {
                "key": "schema_gate_blocked",
                "label": "Schema gate blocked",
                "count": len(getattr(schema_result, "blockers", []) or []) or 1,
                "detail": details or f"schema status is {getattr(schema_result, 'status', 'unknown')}",
            }
        ],
        "warnings": [],
    }


def _emit_launch_proof_bundle(
    *,
    args: argparse.Namespace,
    proof: dict[str, Any],
    schema_payload: dict[str, Any] | None,
    run_history: list[dict[str, Any]] | None = None,
    run_history_error: str = "",
    activation_plan: dict[str, Any] | None = None,
    activation_plan_error: str = "",
) -> None:
    history = run_history
    history_error = run_history_error
    if history is None:
        history = []
        try:
            history = fetch_launch_proof_runs(
                base_url=args.base_url,
                project_id=args.project_id,
                token=args.token,
                timeout=args.timeout,
                limit=args.runs_limit,
            )
        except Exception as exc:
            history_error = str(exc)
    plan = activation_plan
    plan_error = activation_plan_error
    if plan is None and not plan_error:
        try:
            plan = fetch_channel_activation_plan(
                base_url=args.base_url,
                project_id=args.project_id,
                token=args.token,
                timeout=args.timeout,
            )
        except Exception as exc:
            plan_error = str(exc)

    bundle = build_launch_proof_bundle(
        project_id=args.project_id,
        proof=proof,
        schema_payload=schema_payload,
        run_history=history,
        run_history_error=history_error,
        activation_plan=plan,
        activation_plan_error=plan_error,
    )
    if args.bundle_json:
        print(json.dumps(bundle, indent=2, sort_keys=True))
    if args.bundle_file:
        _write_bundle(args.bundle_file, bundle)


def evaluate_launch_proof(
    proof: dict[str, Any],
    *,
    allow_needs_attention: bool = False,
) -> LaunchGateResult:
    """Evaluate a launch-proof payload into an exit decision."""
    status = str(proof.get("status") or "unknown")
    blockers: list[str] = []

    status_ok = status == "ready" or (allow_needs_attention and status == "needs_attention")
    if not status_ok:
        blockers.append(f"launch status is {status}")

    schema = _as_dict(proof.get("schema"))
    if not bool(schema.get("ready")):
        missing_collections = len(_as_list(schema.get("missingCollections")))
        missing_fields = len(_as_list(schema.get("missingFields")))
        missing_migrations = len(_as_list(schema.get("missingMigrationFiles")))
        blockers.append(
            "schema not ready "
            f"({missing_collections} collections, {missing_fields} fields, {missing_migrations} migrations missing)"
        )

    channels = _as_dict(proof.get("channels"))
    blocked_channels = int(channels.get("blocked") or 0)
    if blocked_channels:
        blockers.append(f"{blocked_channels} channel launch proofs blocked")
        blockers.extend(_channel_launch_blockers(proof))

    for item in _as_list(proof.get("blockers")):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "blocker")
        label = str(item.get("label") or key)
        count = int(item.get("count") or 0)
        blockers.append(f"{label} ({count})")

    if status == "needs_attention" and not allow_needs_attention:
        for item in _as_list(proof.get("warnings")):
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "warning")
            label = str(item.get("label") or key)
            count = int(item.get("count") or 0)
            blockers.append(f"{label} ({count})")

    # Preserve order but remove duplicates from overlapping summary checks.
    deduped = list(dict.fromkeys(blockers))
    return LaunchGateResult(ok=not deduped, status=status, blockers=deduped)


def fetch_launch_proof(
    *,
    base_url: str,
    project_id: str,
    token: str = "",
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Fetch launch proof from an admin API base URL."""
    url = (
        f"{base_url.rstrip('/')}/api/admin/projects/"
        f"{quote(project_id, safe='')}/support/launch-proof"
    )
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("launch-proof response is not a JSON object")
    return data


def run_launch_proof(
    *,
    base_url: str,
    project_id: str,
    token: str = "",
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Run launch-proof actions from an admin API base URL."""
    url = (
        f"{base_url.rstrip('/')}/api/admin/projects/"
        f"{quote(project_id, safe='')}/support/launch-proof/run"
    )
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, headers=headers)
        response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("launch-proof run response is not a JSON object")
    proof = data.get("launchProof")
    if isinstance(proof, dict):
        return proof
    readiness = data.get("launchReadiness")
    if isinstance(readiness, dict):
        return readiness
    return data


def fetch_launch_proof_runs(
    *,
    base_url: str,
    project_id: str,
    token: str = "",
    timeout: float = 15.0,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Fetch recent persisted launch-proof run records."""
    url = (
        f"{base_url.rstrip('/')}/api/admin/projects/"
        f"{quote(project_id, safe='')}/support/launch-proof/runs"
        f"?limit={max(1, limit)}"
    )
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    raise ValueError("launch-proof runs response is not a JSON object or list")


def fetch_channel_activation_plan(
    *,
    base_url: str,
    project_id: str,
    token: str = "",
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Fetch channel activation setup handoff from an admin API base URL."""
    url = (
        f"{base_url.rstrip('/')}/api/admin/projects/"
        f"{quote(project_id, safe='')}/channels/activation-plan"
    )
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("channel activation plan response is not a JSON object")
    return data


def _write_bundle(path: str, bundle: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gate deploys on support launch proof readiness.")
    parser.add_argument("--base-url", default=os.getenv("MANTLY_BASE_URL") or os.getenv("APP_BASE_URL") or "")
    parser.add_argument("--project-id", default=os.getenv("SUPPORT_PROJECT_ID") or "")
    parser.add_argument("--token", default=os.getenv("ADMIN_AUTH_TOKEN") or "")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("SUPPORT_LAUNCH_GATE_TIMEOUT", "15")))
    parser.add_argument(
        "--allow-needs-attention",
        action="store_true",
        help="Exit 0 for needs_attention status when schema and channel proof are otherwise ready.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run server-side launch-proof actions before evaluating readiness.",
    )
    parser.add_argument(
        "--schema-gate",
        action="store_true",
        help="Run PocketBase support schema bootstrap/check before fetching launch proof.",
    )
    parser.add_argument(
        "--no-schema-bootstrap",
        action="store_true",
        help="With --schema-gate, only check schema health and skip bootstrap.",
    )
    parser.add_argument("--json", action="store_true", help="Print raw launch-proof JSON before the summary.")
    parser.add_argument("--bundle-json", action="store_true", help="Print portable launch-proof bundle JSON before the summary.")
    parser.add_argument(
        "--bundle-file",
        default=os.getenv("SUPPORT_LAUNCH_GATE_BUNDLE_FILE") or os.getenv("SUPPORT_LAUNCH_BUNDLE_FILE") or "",
        help="Write portable launch-proof bundle JSON to this file.",
    )
    parser.add_argument("--runs-limit", type=int, default=int(os.getenv("SUPPORT_LAUNCH_GATE_RUNS_LIMIT", "10")), help="Recent launch-proof runs to include in bundle output.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.base_url:
        print("support launch gate: --base-url or MANTLY_BASE_URL/APP_BASE_URL required", file=sys.stderr)
        return EXIT_ERROR
    if not args.project_id:
        print("support launch gate: --project-id or SUPPORT_PROJECT_ID required", file=sys.stderr)
        return EXIT_ERROR

    schema_payload: dict[str, Any] | None = None
    if args.schema_gate:
        try:
            schema_payload = check_support_schema(bootstrap=not args.no_schema_bootstrap)
        except Exception as exc:
            print(f"support launch gate: schema preflight failed: {exc}", file=sys.stderr)
            return EXIT_ERROR

        schema_health = _as_dict(schema_payload.get("health"))
        if args.json:
            print(json.dumps({"schemaGate": schema_payload}, indent=2, sort_keys=True))

        schema_result = evaluate_schema_health(schema_health)
        if not schema_result.ok:
            if args.bundle_json or args.bundle_file:
                _emit_launch_proof_bundle(
                    args=args,
                    proof=_schema_blocked_launch_proof(schema_health, schema_result),
                    schema_payload=schema_payload,
                    run_history=[],
                    run_history_error="schema gate blocked before launch proof fetch",
                    activation_plan_error="schema gate blocked before activation plan fetch",
                )
            print(f"support launch gate: schema preflight blocked ({schema_result.status})", file=sys.stderr)
            for blocker in schema_result.blockers:
                print(f"- {blocker}", file=sys.stderr)
            return EXIT_BLOCKED

        print(
            "support launch gate: schema preflight ready "
            f"({schema_health.get('presentCollections', 0)}/{schema_health.get('requiredCollections', 0)} collections, "
            f"{schema_health.get('presentFields', 0)}/{schema_health.get('requiredFields', 0)} fields)"
        )

    try:
        fetcher = run_launch_proof if args.run else fetch_launch_proof
        proof = fetcher(
            base_url=args.base_url,
            project_id=args.project_id,
            token=args.token,
            timeout=args.timeout,
        )
    except Exception as exc:
        print(f"support launch gate: fetch failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(proof, indent=2, sort_keys=True))

    if args.bundle_json or args.bundle_file:
        _emit_launch_proof_bundle(
            args=args,
            proof=proof,
            schema_payload=schema_payload,
        )

    result = evaluate_launch_proof(proof, allow_needs_attention=args.allow_needs_attention)
    if result.ok:
        print(f"support launch gate: ready ({result.status})")
        return EXIT_READY

    print(f"support launch gate: blocked ({result.status})", file=sys.stderr)
    for blocker in result.blockers:
        print(f"- {blocker}", file=sys.stderr)
    return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
