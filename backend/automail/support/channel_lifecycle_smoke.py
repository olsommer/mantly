"""CLI runner for one support channel lifecycle smoke proof."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.parse import quote
from uuid import uuid4

import httpx

EXIT_READY = 0
EXIT_ERROR = 1
EXIT_BLOCKED = 2


@dataclass(slots=True)
class ChannelLifecycleSmokeResult:
    ok: bool
    status: str
    issue_id: str
    reply_id: str
    provider: str
    provider_message_id: str
    transport: str
    error: str


def _text(value: Any) -> str:
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _base_url(value: str) -> str:
    return value.rstrip("/")


def _headers(token: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def fetch_json(
    method: str,
    url: str,
    *,
    token: str = "",
    payload: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout) as client:
        response = client.request(method, url, headers=_headers(token), json=payload)
        response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("response is not a JSON object")
    return data


def resolve_channel_id(
    *,
    base_url: str,
    project_id: str,
    channel_id: str = "",
    channel_key: str = "",
    token: str = "",
    timeout: float = 15.0,
) -> str:
    if channel_id.strip():
        return channel_id.strip()
    clean_key = channel_key.strip()
    if not clean_key:
        raise ValueError("channel id or channel key is required")

    url = f"{_base_url(base_url)}/api/admin/projects/{quote(project_id, safe='')}/channels?limit=200"
    data = fetch_json("GET", url, token=token, timeout=timeout)
    for item in _as_list(data.get("items")):
        channel = _as_dict(item)
        key = _text(channel.get("channelKey") or channel.get("channel_key"))
        if key == clean_key:
            resolved = _text(channel.get("id"))
            if not resolved:
                raise ValueError(f"channel key has no id: {clean_key}")
            return resolved
    raise ValueError(f"channel key not found: {clean_key}")


def smoke_payload(args: argparse.Namespace) -> dict[str, Any]:
    message_id = args.message_id.strip() or f"lifecycle-smoke-{uuid4().hex}"
    return {
        "body": args.body,
        "replyBody": args.reply_body,
        "authorName": args.author_name,
        "authorEmail": args.author_email,
        "authorId": args.author_id or f"customer-{message_id}",
        "fromAddress": args.from_address,
        "channelId": args.provider_channel_id,
        "threadId": args.thread_id,
        "messageId": message_id,
        "eventId": args.event_id or message_id,
        "transport": args.transport,
        "attachments": args.attachments,
        "replyAttachments": args.reply_attachments,
    }


def evaluate_lifecycle_smoke(
    result: dict[str, Any],
    *,
    allow_deferred: bool = False,
) -> ChannelLifecycleSmokeResult:
    status = _text(result.get("status"))
    issue_id = _text(result.get("issueId") or result.get("issue_id"))
    reply_id = _text(result.get("replyId") or result.get("reply_id"))
    provider = _text(result.get("provider"))
    provider_message_id = _text(result.get("providerMessageId") or result.get("provider_message_id"))
    inbound = _as_dict(result.get("inbound"))
    transport = _text(inbound.get("transport") or result.get("transport"))
    sent = result.get("sent") is True or status == "sent"
    deferred = allow_deferred and (result.get("deferred") is True or status == "queued")
    failed = result.get("failed") is True
    ok = bool(issue_id and reply_id and (sent or deferred) and not failed)
    return ChannelLifecycleSmokeResult(
        ok=ok,
        status=status or "unknown",
        issue_id=issue_id,
        reply_id=reply_id,
        provider=provider,
        provider_message_id=provider_message_id,
        transport=transport,
        error=_text(result.get("error")),
    )


def run_channel_lifecycle_smoke(args: argparse.Namespace) -> dict[str, Any]:
    channel_id = resolve_channel_id(
        base_url=args.api_url,
        project_id=args.project_id,
        channel_id=args.channel_id,
        channel_key=args.channel_key,
        token=args.token,
        timeout=args.timeout,
    )
    url = (
        f"{_base_url(args.api_url)}/api/admin/projects/"
        f"{quote(args.project_id, safe='')}/channels/{quote(channel_id, safe='')}/lifecycle-smoke"
    )
    return fetch_json(
        "POST",
        url,
        token=args.token,
        payload=smoke_payload(args),
        timeout=args.timeout,
    )


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("attachment must be a JSON object")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one support channel lifecycle smoke proof.")
    parser.add_argument("--api-url", default=os.getenv("SUPPORT_SMOKE_API_URL") or os.getenv("MANTLY_BASE_URL") or os.getenv("APP_BASE_URL") or "")
    parser.add_argument("--project-id", default=os.getenv("SUPPORT_SMOKE_PROJECT_ID") or os.getenv("SUPPORT_PROJECT_ID") or "")
    parser.add_argument("--tenant-id", default=os.getenv("SUPPORT_SMOKE_TENANT_ID") or "")
    parser.add_argument("--channel-id", default=os.getenv("SUPPORT_SMOKE_CHANNEL_ID") or "")
    parser.add_argument("--channel-key", default=os.getenv("SUPPORT_SMOKE_CHANNEL_KEY") or "")
    parser.add_argument("--token", default=os.getenv("SUPPORT_ADMIN_TOKEN") or os.getenv("ADMIN_AUTH_TOKEN") or os.getenv("ADMIN_API_TOKEN") or "")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("SUPPORT_SMOKE_TIMEOUT", "15")))
    parser.add_argument("--transport", choices=("http", "direct"), default=os.getenv("SUPPORT_SMOKE_TRANSPORT") or "http")
    parser.add_argument("--body", default=os.getenv("SUPPORT_SMOKE_BODY") or "Lifecycle smoke customer message")
    parser.add_argument("--reply-body", default=os.getenv("SUPPORT_SMOKE_REPLY_BODY") or "Lifecycle smoke support reply.")
    parser.add_argument("--author-name", default=os.getenv("SUPPORT_SMOKE_AUTHOR_NAME") or "Lifecycle Smoke Customer")
    parser.add_argument("--author-email", default=os.getenv("SUPPORT_SMOKE_AUTHOR_EMAIL") or "smoke-customer@example.invalid")
    parser.add_argument("--author-id", default=os.getenv("SUPPORT_SMOKE_AUTHOR_ID") or "")
    parser.add_argument("--from-address", default=os.getenv("SUPPORT_SMOKE_FROM_ADDRESS") or "support-agent@example.com")
    parser.add_argument("--provider-channel-id", default=os.getenv("SUPPORT_SMOKE_PROVIDER_CHANNEL_ID") or "")
    parser.add_argument("--thread-id", default=os.getenv("SUPPORT_SMOKE_THREAD_ID") or "")
    parser.add_argument("--message-id", default=os.getenv("SUPPORT_SMOKE_MESSAGE_ID") or "")
    parser.add_argument("--event-id", default=os.getenv("SUPPORT_SMOKE_EVENT_ID") or "")
    parser.add_argument("--attachment", action="append", type=_json_object, default=[])
    parser.add_argument("--reply-attachment", action="append", type=_json_object, default=[])
    parser.add_argument("--allow-deferred", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print raw smoke JSON before the summary.")
    return parser


def _validate_args(args: argparse.Namespace) -> list[str]:
    missing = []
    if not args.api_url.strip():
        missing.append("--api-url or SUPPORT_SMOKE_API_URL/MANTLY_BASE_URL")
    if not args.project_id.strip():
        missing.append("--project-id or SUPPORT_PROJECT_ID")
    if not args.channel_id.strip() and not args.channel_key.strip():
        missing.append("--channel-id or --channel-key")
    if not args.body.strip() and not args.attachments:
        missing.append("--body or --attachment")
    if not args.reply_body.strip():
        missing.append("--reply-body")
    return missing


def _print_summary(result: ChannelLifecycleSmokeResult, *, stream: Any | None = None) -> None:
    output = stream or sys.stdout
    print(
        "support channel lifecycle smoke: "
        f"{'ok' if result.ok else 'blocked'} "
        f"status={result.status or '-'} "
        f"transport={result.transport or '-'} "
        f"issue={result.issue_id or '-'} "
        f"reply={result.reply_id or '-'} "
        f"provider={result.provider or '-'} "
        f"providerMessage={result.provider_message_id or '-'}",
        file=output,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    args.attachments = args.attachment
    args.reply_attachments = args.reply_attachment
    missing = _validate_args(args)
    if missing:
        print("support channel lifecycle smoke: missing " + ", ".join(missing), file=sys.stderr)
        return EXIT_ERROR

    try:
        payload = run_channel_lifecycle_smoke(args)
    except Exception as exc:
        print(f"support channel lifecycle smoke: error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))

    result = evaluate_lifecycle_smoke(payload, allow_deferred=args.allow_deferred)
    _print_summary(result)
    if result.ok:
        return EXIT_READY
    if result.error:
        print(f"error: {result.error}", file=sys.stderr)
    return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
