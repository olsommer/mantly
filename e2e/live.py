"""Run the portable personas against a live, isolated Mantly QA project.

The bearer token is read from an environment variable and is never printed or
written to the JSON report.  ``--seed`` is intentionally destructive for draft
runbooks: runbooks not declared by the selected persona are removed.  Only use
it with disposable QA projects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import string
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml  # pyright: ignore[reportMissingModuleSource]

from .schema import REQUIRED_PROCESSING_STAGES, E2EPersona, PersonaCase, load_personas

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERSONA_DIR = ROOT / "e2e" / "personas"
DEFAULT_TOKEN_ENV = "MANTLY_E2E_BEARER_TOKEN"
TERMINAL_CHANNEL_TEST_JOB_STATUSES = {
    "processed",
    "failed",
    "skipped",
    "ignored",
    "unmatched",
}
PENDING_ACTION_STATUSES = {"pending", "pending_approval", "needs_human"}
DELIVERED_REPLY_STATUSES = {"queued", "sending", "sent", "delivered"}
_RUBRIC_META_WORDS = {
    "answer",
    "based",
    "confirmed",
    "customer",
    "every",
    "facts",
    "field",
    "give",
    "lookup",
    "must",
    "only",
    "reply",
    "returned",
    "state",
    "tool",
    "verified",
}
_UNVERIFIED_MARKERS = re.compile(
    r"\b(?:cannot|can't|not|pending|requires?|unknown|unavailable|unconfirmed|unverified)\b",
    re.IGNORECASE,
)


class LiveE2EError(RuntimeError):
    """A safe, reportable live-runner failure."""


@dataclass(frozen=True)
class Target:
    persona_id: str
    project_id: str
    channel_id: str


@dataclass
class AssertionRecorder:
    assertions: list[dict[str, Any]] = field(default_factory=list)

    def check(self, name: str, passed: bool, evidence: Any = None) -> bool:
        item: dict[str, Any] = {"name": name, "passed": bool(passed)}
        if evidence is not None:
            item["evidence"] = _json_safe(evidence)
        self.assertions.append(item)
        return bool(passed)

    @property
    def passed(self) -> bool:
        return all(item["passed"] for item in self.assertions)


class AdminApi:
    def __init__(self, api_base: str, token: str, *, timeout_seconds: float) -> None:
        self.api_base = api_base.rstrip("/")
        self.client = httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, path: str, *, json_body: Any = None) -> Any:
        url = f"{self.api_base}/{path.lstrip('/')}"
        try:
            response = self.client.request(method, url, json=json_body)
        except httpx.HTTPError as exc:
            raise LiveE2EError(f"{method} {path} failed: {type(exc).__name__}: {exc}") from exc
        if response.status_code >= 400:
            body = response.text.replace("\n", " ")[:800]
            raise LiveE2EError(f"{method} {path} returned HTTP {response.status_code}: {body}")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise LiveE2EError(f"{method} {path} returned non-JSON data") from exc

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, json_body=body or {})

    def put(self, path: str, body: Any) -> Any:
        return self.request("PUT", path, json_body=body)

    def patch(self, path: str, body: Any) -> Any:
        return self.request("PATCH", path, json_body=body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)


def _json_safe(value: Any) -> Any:
    """Bound report evidence while keeping enough detail to diagnose a failure."""

    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)[:2_000]
    if len(encoded) <= 4_000:
        return json.loads(encoded)
    return {"truncated": True, "preview": encoded[:4_000]}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return clean[:80] or "e2e"


def _fixture_tool_name(fixture_id: str) -> str:
    return f"fixture_{fixture_id.replace('-', '_')}"


def parse_target(raw: str) -> Target:
    """Parse ``PERSONA=PROJECT_ID:CHANNEL_ID`` without accepting empty IDs."""

    persona_id, separator, scope = raw.partition("=")
    project_id, channel_separator, channel_id = scope.partition(":")
    if not separator or not channel_separator or not persona_id or not project_id or not channel_id:
        raise argparse.ArgumentTypeError(
            "target must be PERSONA_ID=PROJECT_ID:CHANNEL_ID"
        )
    if not re.fullmatch(r"[a-z][a-z0-9-]*", persona_id):
        raise argparse.ArgumentTypeError(f"invalid persona ID in target: {persona_id!r}")
    return Target(persona_id=persona_id, project_id=project_id, channel_id=channel_id)


def _target_validation_error(targets: list[Target]) -> str:
    persona_ids = [target.persona_id for target in targets]
    if len(persona_ids) != len(set(persona_ids)):
        return "Each persona may appear in --target only once."
    project_ids = [target.project_id for target in targets]
    if len(project_ids) != len(set(project_ids)):
        return (
            "Each persona must use a distinct disposable project because config, "
            "knowledge, and runbooks are project-scoped."
        )
    return ""


def _api_base(raw: str) -> str:
    value = raw.rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise argparse.ArgumentTypeError("--api-base must be an absolute HTTP(S) URL")
    return value


def _fixture_ids_for_runbook(persona: E2EPersona, runbook_key: str) -> list[str]:
    fixture_ids: list[str] = []
    for case in persona.cases:
        if runbook_key not in {concern.runbook_key for concern in case.concerns}:
            continue
        for fixture_id in case.expected.tool_fixture_ids:
            if fixture_id not in fixture_ids:
                fixture_ids.append(fixture_id)
    return fixture_ids


def build_intent_content(persona: E2EPersona, runbook_key: str, api_base: str) -> str:
    """Build a response-free runbook backed by fixture-specific read-only tools."""

    runbook = next(item for item in persona.runbooks if item.key == runbook_key)
    fixture_by_id = {fixture.id: fixture for fixture in persona.seed.tool_fixtures}
    fixture_ids = _fixture_ids_for_runbook(persona, runbook_key)
    tools = []
    for fixture_id in fixture_ids:
        fixture = fixture_by_id[fixture_id]
        tools.append(
            {
                "name": _fixture_tool_name(fixture.id),
                "description": (
                    f"Read-only deterministic QA lookup {fixture.id}. Use it when the "
                    f"customer request contains {json.dumps(fixture.input, ensure_ascii=False, sort_keys=True)}. "
                    "Call the tool before stating lookup facts."
                ),
                "method": "GET",
                "urlTemplate": f"{api_base}/demo/e2e/tool/{persona.id}/{fixture.tool}",
                "body": fixture.input,
                "inputSchema": [],
            }
        )
    actions = [
        {
            "name": action,
            "label": action.replace("_", " ").title(),
            "type": "button",
            "description": "Approval-gated synthetic QA proposal. Never claim it completed.",
            "separateCall": True,
            "webhook": f"https://actions.invalid/e2e/{persona.id}/{action}",
            "method": "POST",
        }
        for action in runbook.proposed_actions
    ]
    frontmatter = {
        "name": runbook.key,
        "description": runbook.purpose,
        "active": True,
        "require_review": True,
        "required_read_only_tools": runbook.required_read_only_tools,
        "subsumes_runbooks": runbook.subsumes_runbooks,
        "tools": tools,
        "actions": actions,
        "response": {
            "enabled": False,
            "response_rules": [
                "Never claim a selected action completed before exact success evidence exists.",
                *runbook.response_rules,
            ],
            "required_guidance": runbook.required_guidance,
        },
    }
    examples: list[str] = []
    obligations: list[str] = []
    for case in persona.cases:
        matching = [
            concern for concern in case.concerns if concern.runbook_key == runbook.key
        ]
        if not matching:
            continue
        examples.append(f"- {case.title}: {case.inbound.body}")
        for concern in matching:
            obligations.extend(f"- {item}" for item in concern.answer_obligations)
    body = "\n".join(
        [
            f"# {runbook.key}",
            "",
            runbook.purpose,
            "",
            "## Activation examples",
            *(examples or ["- Activate only when the stated purpose matches."]),
            "",
            "## Processing contract",
            "- Process only this concern; do not compose or persist a customer response.",
            "- Use every relevant read-only lookup and retain its verified facts for the Inbox composer.",
            "- Select only configured actions materially applicable to this concern.",
            "- Suppress actions whose prerequisites or requester authority are insufficient.",
            "- Every selected action remains a proposal requiring human approval.",
            "- Never say a proposed action ran, succeeded, or changed external state.",
            "- Record missing or unverified facts explicitly.",
            "",
            "## Answer obligations passed to the Inbox composer",
            *(obligations or ["- Address the customer's request without inventing facts."]),
        ]
    )
    yaml_text = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    ).strip()
    return f"---\n{yaml_text}\n---\n\n{body}\n"


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [item for item in payload["items"] if isinstance(item, dict)]
    return []


def _active_automation_names(rules: list[dict[str, Any]]) -> list[str]:
    return [
        str(rule.get("name") or rule.get("id") or "unknown")
        for rule in rules
        if rule.get("active") is True
        or rule.get("enabled") is True
        or str(rule.get("status") or "").lower() in {"active", "enabled"}
    ]


def _foreign_knowledge_titles(
    articles: list[dict[str, Any]], persona: E2EPersona
) -> list[str]:
    marker_prefix = f"e2e-id:{persona.id}:"
    allowed_markers = {
        _knowledge_marker(persona.id, fixture.id) for fixture in persona.seed.knowledge
    }
    return [
        str(article.get("title") or article.get("id") or "unknown")
        for article in articles
        if (
            len(
                markers := {
                    str(tag)
                    for tag in (article.get("tags") or [])
                    if str(tag).startswith(marker_prefix)
                }
            )
            != 1
            or not markers.issubset(allowed_markers)
        )
    ]


def _unsafe_channel_config_keys(channel: dict[str, Any]) -> list[str]:
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}

    def optional_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            clean = value.strip().lower()
            if clean in {"1", "true", "yes", "on"}:
                return True
            if clean in {"0", "false", "no", "off"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        return None

    truthy_network_keys = {
        "agentAutoSend",
        "agent_auto_send",
        "auto_send_agent_reply",
        "syncEnabled",
        "sync_enabled",
        "inboundSyncEnabled",
        "inbound_sync_enabled",
        "pollingEnabled",
        "polling_enabled",
    }
    outbound_keys = {
        "outboundWebhookUrl",
        "outboundWebhookUrlEnv",
        "outboundWebhookUrlTemplate",
        "outboundWebhookTokenEnv",
        "outbound_webhook_url",
        "outbound_webhook_url_env",
        "outbound_webhook_url_template",
        "outbound_webhook_token_env",
        "emailOutboundWebhookUrlEnv",
        "emailOutboundWebhookTokenEnv",
        "outboundEnvVars",
    }
    unsafe = (
        [key for key in truthy_network_keys if optional_bool(config.get(key)) is True]
        + [key for key in outbound_keys if config.get(key)]
    )
    sync_aliases = (
        "syncEnabled",
        "sync_enabled",
        "inboundSyncEnabled",
        "inbound_sync_enabled",
        "pollingEnabled",
        "polling_enabled",
    )
    explicit_sync_values = [
        optional_bool(config[key]) for key in sync_aliases if key in config
    ]
    if (
        str(channel.get("status") or "active").lower() == "active"
        and False not in explicit_sync_values
    ):
        unsafe.append("implicitInboundSync")
    return sorted(set(unsafe))


def _preflight_target_for_seed(
    api: AdminApi,
    target: Target,
    persona: E2EPersona,
) -> None:
    """Prove the target is disposable before the first mutating request."""

    project_base = f"/api/admin/projects/{target.project_id}"
    active_rules = _active_automation_names(
        _items(api.get(f"{project_base}/automations?limit=200"))
    )
    if active_rules:
        raise LiveE2EError(
            "QA project has active automation rules; use a fresh disposable project: "
            + ", ".join(active_rules[:10])
        )

    existing_knowledge = _items(
        api.get(f"{project_base}/knowledge?status=all&limit=200")
    )
    foreign_articles = _foreign_knowledge_titles(existing_knowledge, persona)
    if foreign_articles:
        raise LiveE2EError(
            "QA project contains non-persona knowledge; use a fresh disposable "
            f"project: {', '.join(foreign_articles[:10])}"
        )

    channels = _items(api.get(f"{project_base}/channels?limit=200"))
    extra_channels = [
        str(item.get("name") or item.get("channelKey") or item.get("id") or "unknown")
        for item in channels
        if str(item.get("id") or "") != target.channel_id
    ]
    if extra_channels:
        raise LiveE2EError(
            "QA project contains non-target channels; use a one-channel disposable "
            f"project: {', '.join(extra_channels[:10])}"
        )
    channel = next(
        (item for item in channels if str(item.get("id") or "") == target.channel_id),
        None,
    )
    if channel is None:
        raise LiveE2EError(
            f"channel {target.channel_id!r} was not found in project {target.project_id!r}"
        )
    if not str(channel.get("channelKey") or "").strip():
        raise LiveE2EError(f"channel {target.channel_id!r} has no channelKey")
    unsafe_channel_keys = _unsafe_channel_config_keys(channel)
    if unsafe_channel_keys:
        raise LiveE2EError(
            "QA channel is externally active; use a fresh disposable channel: "
            + ", ".join(unsafe_channel_keys)
        )

    intents = api.get(f"{project_base}/intents")
    if not isinstance(intents, list):
        raise LiveE2EError(f"GET {project_base}/intents did not return a runbook list")
    expected_names = {runbook.key for runbook in persona.runbooks}
    existing_names = {
        str(item.get("name") or "") for item in intents if isinstance(item, dict)
    } - {""}
    foreign_runbooks = existing_names - expected_names
    if foreign_runbooks:
        raise LiveE2EError(
            "QA project contains non-persona runbooks; use a fresh disposable "
            f"project: {', '.join(sorted(foreign_runbooks)[:10])}"
        )


def _preflight_target_for_run(
    api: AdminApi,
    target: Target,
    persona: E2EPersona,
) -> None:
    """Fail closed if a seeded target drifted into an externally active state."""

    project_base = f"/api/admin/projects/{target.project_id}"
    active_rules = _active_automation_names(
        _items(api.get(f"{project_base}/automations?limit=200"))
    )
    if active_rules:
        raise LiveE2EError(
            "QA project has active automation rules: "
            + ", ".join(active_rules[:10])
        )

    existing_knowledge = _items(
        api.get(f"{project_base}/knowledge?status=all&limit=200")
    )
    foreign_articles = _foreign_knowledge_titles(existing_knowledge, persona)
    if foreign_articles:
        raise LiveE2EError(
            "QA project contains non-persona knowledge: "
            + ", ".join(foreign_articles[:10])
        )
    channels = _items(api.get(f"{project_base}/channels?limit=200"))
    extra_channels = [
        str(item.get("name") or item.get("channelKey") or item.get("id") or "unknown")
        for item in channels
        if str(item.get("id") or "") != target.channel_id
    ]
    if extra_channels:
        raise LiveE2EError(
            "QA project contains non-target channels: " + ", ".join(extra_channels[:10])
        )
    channel = next(
        (item for item in channels if str(item.get("id") or "") == target.channel_id),
        None,
    )
    if channel is None:
        raise LiveE2EError(f"QA channel {target.channel_id!r} is missing")
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    unsafe_channel_keys = _unsafe_channel_config_keys(channel)
    if unsafe_channel_keys:
        raise LiveE2EError(
            "QA channel is externally active; unsafe config keys: "
            + ", ".join(unsafe_channel_keys)
        )
    if config.get("e2ePersona") != persona.id:
        raise LiveE2EError("QA channel is missing the expected e2ePersona marker")

    publish_status = api.get(f"{project_base}/publish/status")
    if not isinstance(publish_status, dict):
        raise LiveE2EError("QA publish status did not return an object")
    if publish_status.get("hasUnpublishedChanges") is not False:
        raise LiveE2EError(
            "QA project has unpublished changes; inspected draft may differ from live runtime"
        )

    expected_markers = sorted(
        _knowledge_marker(persona.id, fixture.id) for fixture in persona.seed.knowledge
    )
    actual_markers = sorted(
        str(tag)
        for article in existing_knowledge
        for tag in (article.get("tags") or [])
        if str(tag).startswith(f"e2e-id:{persona.id}:")
    )
    if actual_markers != expected_markers:
        raise LiveE2EError(
            "QA knowledge fixture set drifted: expected "
            f"{expected_markers}, got {actual_markers}"
        )

    intents = api.get(f"{project_base}/intents")
    if not isinstance(intents, list):
        raise LiveE2EError(f"GET {project_base}/intents did not return a runbook list")
    by_name = {
        str(item.get("name") or ""): item
        for item in intents
        if isinstance(item, dict) and item.get("name")
    }
    expected_by_name = {runbook.key: runbook for runbook in persona.runbooks}
    if set(by_name) != set(expected_by_name):
        raise LiveE2EError(
            "QA runbook set drifted: expected "
            f"{sorted(expected_by_name)}, got {sorted(by_name)}"
        )
    for name, expected in expected_by_name.items():
        intent_detail = api.get(f"{project_base}/intents/{name}")
        if not isinstance(intent_detail, dict) or not isinstance(
            intent_detail.get("content"), str
        ):
            raise LiveE2EError(f"QA runbook {name!r} content is unavailable")
        try:
            intent = yaml.safe_load(intent_detail["content"].split("---", 2)[1])
        except (IndexError, yaml.YAMLError) as exc:
            raise LiveE2EError(f"QA runbook {name!r} has invalid frontmatter") from exc
        if not isinstance(intent, dict):
            raise LiveE2EError(f"QA runbook {name!r} frontmatter is not an object")
        actions = [
            action for action in (intent.get("actions") or []) if isinstance(action, dict)
        ]
        action_names = {str(action.get("name") or "") for action in actions} - {""}
        if action_names != set(expected.proposed_actions):
            raise LiveE2EError(f"QA runbook {name!r} action set drifted")
        unsafe_webhooks = [
            str(action.get("webhook") or "")
            for action in actions
            if (urlparse(str(action.get("webhook") or "")).hostname or "")
            != "actions.invalid"
        ]
        if unsafe_webhooks:
            raise LiveE2EError(f"QA runbook {name!r} has a non-fixture action webhook")
        expected_fixture_ids = _fixture_ids_for_runbook(persona, name)
        expected_tools = {
            _fixture_tool_name(fixture_id): (
                f"{api.api_base}/demo/e2e/tool/{persona.id}/"
                f"{next(fixture.tool for fixture in persona.seed.tool_fixtures if fixture.id == fixture_id)}"
            )
            for fixture_id in expected_fixture_ids
        }
        tools = [
            tool for tool in (intent.get("tools") or []) if isinstance(tool, dict)
        ]
        actual_tools = {str(tool.get("name") or ""): tool for tool in tools}
        if set(actual_tools) != set(expected_tools):
            raise LiveE2EError(f"QA runbook {name!r} tool set drifted")
        if set(intent.get("required_read_only_tools") or []) != set(
            expected.required_read_only_tools
        ):
            raise LiveE2EError(
                f"QA runbook {name!r} required read-only tool contract drifted"
            )
        raw_subsumed = intent.get(
            "subsumes_runbooks",
            intent.get("subsumesRunbooks", []),
        )
        actual_subsumed = (
            [item.strip() for item in raw_subsumed]
            if isinstance(raw_subsumed, list)
            and all(isinstance(item, str) and item.strip() for item in raw_subsumed)
            else []
        )
        if (
            not isinstance(raw_subsumed, list)
            or len(actual_subsumed) != len(raw_subsumed)
            or len(actual_subsumed) != len(set(actual_subsumed))
            or set(actual_subsumed) != set(expected.subsumes_runbooks)
        ):
            raise LiveE2EError(
                f"QA runbook {name!r} subsumption contract drifted"
            )
        for tool_name, expected_url in expected_tools.items():
            tool = actual_tools[tool_name]
            unsafe_tool_fields = [
                key
                for key in ("headers", "auth", "authorization", "secret", "token")
                if tool.get(key)
            ]
            if (
                str(tool.get("method") or "").upper() != "GET"
                or str(tool.get("urlTemplate") or "") != expected_url
                or unsafe_tool_fields
            ):
                raise LiveE2EError(
                    f"QA runbook {name!r} tool {tool_name!r} is not an exact fixture lookup"
                )
        response = intent.get("response") if isinstance(intent.get("response"), dict) else {}
        if (
            response.get("enabled") is not False
            or intent.get("require_review") is not True
            or intent.get("active") is not True
        ):
            raise LiveE2EError(
                f"QA runbook {name!r} is not response-disabled and review-gated"
            )


def _seed_config(api: AdminApi, target: Target, persona: E2EPersona) -> None:
    path = f"/api/admin/projects/{target.project_id}/config"
    current = api.get(path)
    if not isinstance(current, dict):
        raise LiveE2EError(f"GET {path} did not return a config object")
    payload = {
        **current,
        "orgName": persona.business.name,
        "orgDescription": (
            f"Synthetic E2E project for {persona.business.industry}. "
            f"Persona: {persona.id}. No real customer or external action data."
        ),
        "useCustomOrg": True,
        "identityNotes": (
            f"Synthetic QA senders use @example.test. Operator role: {persona.operator.role}. "
            "Do not infer identity, authority, authentication, or completed actions."
        ),
        "tool": None,
    }
    api.put(path, payload)


def _knowledge_marker(persona_id: str, fixture_id: str) -> str:
    return f"e2e-id:{persona_id}:{fixture_id}"


def _seed_knowledge(
    api: AdminApi,
    target: Target,
    persona: E2EPersona,
) -> dict[str, str]:
    path = f"/api/admin/projects/{target.project_id}/knowledge"
    existing = _items(api.get(f"{path}?status=all&limit=200"))
    foreign_articles = _foreign_knowledge_titles(existing, persona)
    if foreign_articles:
        raise LiveE2EError(
            "QA project contains non-persona knowledge; use a fresh disposable "
            f"project: {', '.join(foreign_articles[:10])}"
        )
    by_marker: dict[str, dict[str, Any]] = {}
    for article in existing:
        for tag in article.get("tags") or []:
            by_marker[str(tag)] = article
    seeded: dict[str, str] = {}
    reviewed_at = _now_iso()
    for fixture in persona.seed.knowledge:
        marker = _knowledge_marker(persona.id, fixture.id)
        title = f"[E2E {persona.id}/{fixture.id}] {fixture.title}"
        payload = {
            "title": title,
            "body": fixture.body,
            "status": "published",
            "visibility": fixture.visibility,
            "automationAllowed": fixture.automation_allowed,
            "tags": list(dict.fromkeys([*fixture.tags, "e2e", persona.id, marker])),
        }
        article = by_marker.get(marker)
        if article and article.get("id"):
            updated = api.patch(f"{path}/{article['id']}", payload)
        else:
            updated = api.post(path, payload)
        if not isinstance(updated, dict) or not updated.get("id"):
            raise LiveE2EError(f"knowledge fixture {fixture.id} did not return an article ID")
        article_id = str(updated["id"])
        reviewed = api.patch(
            f"{path}/{article_id}",
            {"reviewStatus": "reviewed", "lastReviewedAt": reviewed_at},
        )
        if not isinstance(reviewed, dict):
            raise LiveE2EError(f"knowledge fixture {fixture.id} review did not return an object")
        seeded[fixture.id] = article_id
    return seeded


def _seed_runbooks(api: AdminApi, target: Target, persona: E2EPersona) -> None:
    base = f"/api/admin/projects/{target.project_id}/intents"
    expected = {runbook.key for runbook in persona.runbooks}
    existing = api.get(base)
    if not isinstance(existing, list):
        raise LiveE2EError(f"GET {base} did not return a runbook list")
    for intent in existing:
        if not isinstance(intent, dict):
            continue
        name = str(intent.get("name") or "")
        if name and name not in expected:
            api.delete(f"{base}/{name}")
    for runbook in persona.runbooks:
        api.put(
            f"{base}/{runbook.key}",
            {"content": build_intent_content(persona, runbook.key, api.api_base)},
        )
    final_names = {
        str(item.get("name") or "")
        for item in api.get(base)
        if isinstance(item, dict)
    }
    if final_names != expected:
        raise LiveE2EError(
            f"runbook seed mismatch: expected {sorted(expected)}, got {sorted(final_names)}"
        )


def _seed_channel(api: AdminApi, target: Target, persona: E2EPersona) -> None:
    path = f"/api/admin/projects/{target.project_id}/channels"
    channels = _items(api.get(f"{path}?limit=200"))
    channel = next(
        (item for item in channels if str(item.get("id") or "") == target.channel_id),
        None,
    )
    if channel is None:
        raise LiveE2EError(
            f"channel {target.channel_id!r} was not found in project {target.project_id!r}"
        )
    channel_key = str(channel.get("channelKey") or "").strip()
    if not channel_key:
        raise LiveE2EError(f"channel {target.channel_id!r} has no channelKey")
    old_config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    config = {
        **old_config,
        "adapter": "buffer",
        "ticketCreationMode": "per_thread",
        "autoPrepareTriage": True,
        "autoPrepareCustomFields": True,
        "autoPrepareAgentReply": True,
        "autoPrepareAgentReplyOnUpdate": True,
        "agentAutoSend": False,
        "agent_auto_send": False,
        "auto_send_agent_reply": False,
        "syncEnabled": False,
        "sync_enabled": False,
        "inboundSyncEnabled": False,
        "inbound_sync_enabled": False,
        "pollingEnabled": False,
        "polling_enabled": False,
        "outboundWebhookUrl": "",
        "outboundWebhookUrlEnv": "",
        "outboundWebhookUrlTemplate": "",
        "outboundWebhookTokenEnv": "",
        "outbound_webhook_url": "",
        "outbound_webhook_url_env": "",
        "outbound_webhook_url_template": "",
        "outbound_webhook_token_env": "",
        "emailOutboundWebhookUrlEnv": "",
        "emailOutboundWebhookTokenEnv": "",
        "outboundEnvVars": [],
        "e2ePersona": persona.id,
    }
    updated = api.post(
        path,
        {
            "channelKey": channel_key,
            "type": "email",
            "name": f"E2E {persona.name}",
            "status": "active",
            "config": config,
        },
    )
    if not isinstance(updated, dict) or str(updated.get("id") or "") != target.channel_id:
        raise LiveE2EError(
            f"channel upsert changed identity: expected {target.channel_id!r}, "
            f"got {str(updated.get('id') or '')!r}"
        )
    updated_config = updated.get("config") if isinstance(updated.get("config"), dict) else {}
    if updated_config.get("agentAutoSend") is not False:
        raise LiveE2EError("channel seed did not disable agent auto-send")


def seed_persona(
    api: AdminApi,
    target: Target,
    persona: E2EPersona,
) -> dict[str, str]:
    _preflight_target_for_seed(api, target, persona)
    _seed_config(api, target, persona)
    article_ids = _seed_knowledge(api, target, persona)
    _seed_runbooks(api, target, persona)
    _seed_channel(api, target, persona)
    api.post(f"/api/admin/projects/{target.project_id}/publish")
    _preflight_target_for_run(api, target, persona)
    return article_ids


def _case_token(persona_id: str, run_id: str, case_id: str) -> str:
    return _slug(f"{persona_id}-{run_id}-{case_id}")


def _sender_address(template: str, token: str) -> str:
    local, _, domain = template.partition("@")
    return f"{local}+{token}@{domain}"


def _message_payload(
    persona: E2EPersona,
    case: PersonaCase,
    token: str,
    *,
    thread_id: str,
    message_id: str,
    event_id: str,
    body: str | None = None,
) -> dict[str, Any]:
    attachments = [
        {"filename": attachment.filename, "contentType": "application/octet-stream"}
        for attachment in case.inbound.attachments
    ]
    subject = f"{case.inbound.subject} [{token}]"
    content = body if body is not None else case.inbound.body
    return {
        "body": f"{subject}\n\n{content}",
        "authorName": case.inbound.from_name,
        "authorEmail": _sender_address(case.inbound.from_address, token),
        "authorId": f"e2e-{token}",
        "provider": "email",
        "channelId": f"e2e-email-{persona.id}",
        "threadId": thread_id,
        "messageId": message_id,
        "eventId": event_id,
        "transport": "direct",
        "attachments": attachments,
    }


def _issue_id_from_ingest(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("issueId", "issue_id"):
        if payload.get(key):
            return str(payload[key])
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        for key in ("issueId", "issue_id"):
            if item.get(key):
                return str(item[key])
    return ""


def _count_from_ingest(payload: Any, key: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _wait_for_channel_test_job(
    api: AdminApi,
    target: Target,
    accepted: Any,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    """Resolve the 202 test-message contract to its durable terminal result."""

    if not isinstance(accepted, dict):
        raise LiveE2EError("test-message enqueue returned no result object")
    status = str(accepted.get("status") or "").lower()
    if status in TERMINAL_CHANNEL_TEST_JOB_STATUSES:
        return accepted
    run_id = str(accepted.get("runId") or accepted.get("run_id") or "")
    if not run_id:
        raise LiveE2EError("test-message enqueue did not return a durable run ID")
    path = (
        f"/api/admin/projects/{target.project_id}/channels/"
        f"test-message-jobs/{run_id}"
    )
    deadline = time.monotonic() + timeout_seconds
    latest = accepted
    while time.monotonic() < deadline:
        latest = api.get(path)
        if not isinstance(latest, dict):
            raise LiveE2EError(f"channel test job {run_id} returned no result object")
        status = str(latest.get("status") or "").lower()
        if status in TERMINAL_CHANNEL_TEST_JOB_STATUSES:
            return latest
        time.sleep(poll_seconds)
    raise LiveE2EError(
        f"channel test job {run_id} did not reach a terminal state; "
        f"last status was {latest.get('status') or 'unknown'}"
    )


def _progress_stages(issue: dict[str, Any]) -> dict[str, str]:
    stages: dict[str, str] = {}
    for run in issue.get("aiRuns") or []:
        if not isinstance(run, dict):
            continue
        metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
        progress = (
            metadata.get("processingProgress")
            if isinstance(metadata.get("processingProgress"), dict)
            else {}
        )
        for item in progress.get("stages") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            if key:
                stages[key] = str(item.get("status") or "")
    return stages


def _matched_concerns(issue: dict[str, Any]) -> list[dict[str, Any]]:
    for run in issue.get("aiRuns") or []:
        if not isinstance(run, dict):
            continue
        result = run.get("intentResult") if isinstance(run.get("intentResult"), dict) else {}
        concerns = result.get("concerns")
        if isinstance(concerns, list) and concerns:
            return [item for item in concerns if isinstance(item, dict) and item.get("matched", True)]
    return []


def _concern_runbook(concern: dict[str, Any]) -> str:
    outcome = concern.get("outcome") if isinstance(concern.get("outcome"), dict) else {}
    return str(
        concern.get("intentName")
        or concern.get("intent_name")
        or outcome.get("intentName")
        or outcome.get("intent_name")
        or ""
    )


def _all_tool_calls(issue: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for run in issue.get("aiRuns") or []:
        if not isinstance(run, dict):
            continue
        for call in run.get("toolCalls") or []:
            if isinstance(call, dict):
                calls.append(call)
    return calls


def _reply_metadata(reply: dict[str, Any]) -> dict[str, Any]:
    return reply.get("metadata") if isinstance(reply.get("metadata"), dict) else {}


def _rubric_terms(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) >= 4 and token not in _RUBRIC_META_WORDS
    }


def _rubric_term_evidence(answer: str, rules: list[str]) -> list[dict[str, Any]]:
    answer_terms = _rubric_terms(answer)
    evidence: list[dict[str, Any]] = []
    for rule in rules:
        expected = _rubric_terms(rule)
        matched = expected.intersection(answer_terms)
        required = min(2, len(expected))
        evidence.append(
            {
                "rule": rule,
                "expectedTerms": sorted(expected),
                "matchedTerms": sorted(matched),
                "passed": len(matched) >= required,
            }
        )
    return evidence


def _draft_replies(issue: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in issue.get("outboundMessages") or []
        if isinstance(item, dict)
        and str(item.get("status") or "").lower() in {"draft", "pending_approval", "needs_human"}
    ]


def _processing_is_terminal(issue: dict[str, Any]) -> bool:
    runs = [run for run in issue.get("aiRuns") or [] if isinstance(run, dict)]
    if not runs:
        return False
    if any(
        str(run.get("status") or "").lower() == "processing"
        for run in runs
    ):
        return False
    stages = _progress_stages(issue)
    if set(REQUIRED_PROCESSING_STAGES) - set(stages):
        return False
    return True


def _processing_completed(issue: dict[str, Any]) -> bool:
    if not _processing_is_terminal(issue):
        return False
    stages = _progress_stages(issue)
    return all(
        stages[key].lower() in {"completed", "failed", "skipped"}
        for key in REQUIRED_PROCESSING_STAGES
    )


def _is_terminal(issue: dict[str, Any], expected_drafts: int) -> bool:
    if not _processing_is_terminal(issue):
        return False
    return len(_draft_replies(issue)) >= expected_drafts


def _issue_fingerprint(issue: dict[str, Any]) -> str:
    """Hash the full durable ticket projection while excluding clock-only fields."""

    volatile_keys = {
        "ageSeconds",
        "durationMs",
        "elapsedMs",
        "remainingSeconds",
        "timestamp",
    }

    def stable(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: stable(item)
                for key, item in sorted(value.items())
                if key not in volatile_keys
                and not key.endswith("At")
                and key not in {"created", "updated"}
            }
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    durable = stable(issue)
    encoded = json.dumps(durable, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _business_state_fingerprint(issue: dict[str, Any]) -> str:
    """Hash ticket state without webhook receipts, which have their own replay audit."""

    business_state = {
        key: value for key, value in issue.items() if key != "channelWebhookEvents"
    }
    return _issue_fingerprint(business_state)


def _replay_receipt_audit(
    before_issue: dict[str, Any],
    after_issue: dict[str, Any],
    *,
    issue_id: str,
    channel_id: str,
    event_id: str,
    message_id: str,
) -> tuple[bool, dict[str, Any]]:
    """Require one correctly linked skipped receipt without changing prior receipts."""

    before_receipts = [
        item
        for item in before_issue.get("channelWebhookEvents") or []
        if isinstance(item, dict)
    ]
    after_receipts = [
        item
        for item in after_issue.get("channelWebhookEvents") or []
        if isinstance(item, dict)
    ]
    before_by_id = {
        str(item.get("id") or ""): item for item in before_receipts if item.get("id")
    }
    after_by_id = {
        str(item.get("id") or ""): item for item in after_receipts if item.get("id")
    }
    before_ids = set(before_by_id)
    after_ids = set(after_by_id)
    new_ids = after_ids - before_ids
    preserved_ids = before_ids.intersection(after_ids)
    original_receipts_preserved = (
        len(before_by_id) == len(before_receipts)
        and len(after_by_id) == len(after_receipts)
        and preserved_ids == before_ids
        and all(
            _issue_fingerprint(before_by_id[receipt_id])
            == _issue_fingerprint(after_by_id[receipt_id])
            for receipt_id in preserved_ids
        )
    )

    new_receipt = after_by_id[next(iter(new_ids))] if len(new_ids) == 1 else {}
    payload = (
        new_receipt.get("payload")
        if isinstance(new_receipt.get("payload"), dict)
        else {}
    )
    result = (
        new_receipt.get("result")
        if isinstance(new_receipt.get("result"), dict)
        else {}
    )
    resolver = result.get("resolver") if isinstance(result.get("resolver"), dict) else {}
    expected_event_prefix = f"admin-test-job:{event_id}:"
    new_receipt_valid = (
        len(new_ids) == 1
        and len(after_receipts) == len(before_receipts) + 1
        and str(new_receipt.get("channelId") or "") == channel_id
        and str(new_receipt.get("eventId") or "").startswith(expected_event_prefix)
        and str(new_receipt.get("eventType") or "") == "admin_channel_test_message"
        and str(new_receipt.get("providerMessageId") or "") == message_id
        and str(new_receipt.get("status") or "").lower() == "skipped"
        and str(payload.get("eventId") or "") == event_id
        and str(payload.get("messageId") or "") == message_id
        and str(result.get("status") or "").lower() == "skipped"
        and str(result.get("issueId") or "") == issue_id
        and str(result.get("messageId") or "") == message_id
        and str(resolver.get("issueId") or "") == issue_id
        and str(resolver.get("providerMessageId") or "") == message_id
    )
    evidence = {
        "beforeReceiptIds": sorted(before_ids),
        "afterReceiptIds": sorted(after_ids),
        "newReceiptIds": sorted(new_ids),
        "originalReceiptsPreserved": original_receipts_preserved,
        "newReceiptValid": new_receipt_valid,
        "newReceipt": {
            "id": str(new_receipt.get("id") or ""),
            "channelId": str(new_receipt.get("channelId") or ""),
            "eventId": str(new_receipt.get("eventId") or ""),
            "eventType": str(new_receipt.get("eventType") or ""),
            "providerMessageId": str(new_receipt.get("providerMessageId") or ""),
            "status": str(new_receipt.get("status") or ""),
            "payloadEventId": str(payload.get("eventId") or ""),
            "payloadMessageId": str(payload.get("messageId") or ""),
            "resultStatus": str(result.get("status") or ""),
            "resultIssueId": str(result.get("issueId") or ""),
            "resultMessageId": str(result.get("messageId") or ""),
            "resolverIssueId": str(resolver.get("issueId") or ""),
            "resolverProviderMessageId": str(
                resolver.get("providerMessageId") or ""
            ),
        },
    }
    return original_receipts_preserved and new_receipt_valid, evidence


def _fetch_issue(api: AdminApi, target: Target, issue_id: str) -> dict[str, Any]:
    result = api.get(f"/api/admin/projects/{target.project_id}/issues/{issue_id}")
    if not isinstance(result, dict):
        raise LiveE2EError(f"issue {issue_id} did not return an object")
    return result


def _wait_for_issue(
    api: AdminApi,
    target: Target,
    issue_id: str,
    *,
    expected_drafts: int,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_issue: dict[str, Any] = {}
    stable_fingerprint = ""
    stable_count = 0
    missing_draft_fingerprint = ""
    missing_draft_count = 0
    while time.monotonic() < deadline:
        last_issue = _fetch_issue(api, target, issue_id)
        if _is_terminal(last_issue, expected_drafts):
            fingerprint = _issue_fingerprint(last_issue)
            stable_count = stable_count + 1 if fingerprint == stable_fingerprint else 1
            stable_fingerprint = fingerprint
            if stable_count >= 2:
                return last_issue
        else:
            stable_count = 0
            stable_fingerprint = ""
            draft_count = len(_draft_replies(last_issue))
            if expected_drafts > draft_count and _processing_completed(last_issue):
                fingerprint = _issue_fingerprint(last_issue)
                missing_draft_count = (
                    missing_draft_count + 1
                    if fingerprint == missing_draft_fingerprint
                    else 1
                )
                missing_draft_fingerprint = fingerprint
                if missing_draft_count >= 2:
                    raise LiveE2EError(
                        f"issue {issue_id} completed processing with {draft_count} "
                        f"drafts; expected at least {expected_drafts}"
                    )
            else:
                missing_draft_count = 0
                missing_draft_fingerprint = ""
        time.sleep(max(0.25, poll_seconds))
    stages = _progress_stages(last_issue)
    raise LiveE2EError(
        f"issue {issue_id} did not reach stable terminal state within {timeout_seconds:.0f}s; "
        f"stages={stages}, drafts={len(_draft_replies(last_issue))}"
    )


def _citation_ids(reply: dict[str, Any]) -> set[str]:
    metadata = _reply_metadata(reply)
    found = {
        str(item)
        for key in (
            "knowledgeArticleIds",
            "knowledgeAccessedArticleIds",
            "knowledgeContextArticleIds",
        )
        for item in (metadata.get(key) if isinstance(metadata.get(key), list) else [])
        if item
    }
    for citation in metadata.get("citations") or []:
        if isinstance(citation, dict):
            value = citation.get("id") or citation.get("articleId")
            if value:
                found.add(str(value))
    return found


def _knowledge_any_of_audit(
    expected_fixture_ids: list[str],
    article_ids: dict[str, str],
    actual_article_ids: set[str],
) -> tuple[bool, dict[str, Any]]:
    missing_mappings = sorted(
        fixture_id for fixture_id in expected_fixture_ids if fixture_id not in article_ids
    )
    expected_article_ids = {
        article_ids[fixture_id]
        for fixture_id in expected_fixture_ids
        if fixture_id in article_ids
    }
    matched_article_ids = expected_article_ids & actual_article_ids
    passed = not expected_fixture_ids or (
        not missing_mappings and bool(matched_article_ids)
    )
    return passed, {
        "expectedAnyOf": sorted(expected_article_ids),
        "actual": sorted(actual_article_ids),
        "matched": sorted(matched_article_ids),
        "missingMappings": missing_mappings,
    }


def _action_name(action: dict[str, Any]) -> str:
    metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
    proposal = metadata.get("proposedAction") if isinstance(metadata.get("proposedAction"), dict) else {}
    return str(metadata.get("runbookAction") or proposal.get("name") or "")


def _action_webhook(action: dict[str, Any]) -> str:
    metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
    proposal = metadata.get("proposedAction") if isinstance(metadata.get("proposedAction"), dict) else {}
    return str(proposal.get("webhook") or "")


def _fixture_tool_audit(
    issue: dict[str, Any], expected_fixture_ids: list[str]
) -> tuple[bool, dict[str, Any], set[str]]:
    all_calls = _all_tool_calls(issue)
    fixture_calls = [
        call
        for call in all_calls
        if str(call.get("name") or "").startswith("fixture_")
    ]
    unexpected = sorted(
        {
            str(call.get("name") or "")
            for call in all_calls
            if str(call.get("name") or "")
            and not str(call.get("name") or "").startswith("fixture_")
        }
    )
    successful = {
        str(call.get("name") or "")
        for call in fixture_calls
        if str(call.get("status") or "").lower() in {"success", "succeeded", "ok"}
    }
    expected = {_fixture_tool_name(item) for item in expected_fixture_ids}
    errors = {
        str(call.get("name") or ""): str(call.get("status") or "")
        for call in fixture_calls
        if str(call.get("status") or "").lower()
        in {"fixture_not_found", "fixture_error", "failed"}
    }
    evidence = {
        "expected": sorted(expected),
        "successful": sorted(successful),
        "fixtureErrors": errors,
        "unexpectedTools": unexpected,
    }
    return expected == successful and not errors and not unexpected, evidence, successful


def _pending_action_audit(
    issue: dict[str, Any], expected_action_names: list[str]
) -> tuple[bool, bool, dict[str, Any], set[str]]:
    actions = [item for item in issue.get("actionExecutions") or [] if isinstance(item, dict)]
    actual = {_action_name(item) for item in actions if _action_name(item)}
    expected = set(expected_action_names)
    unsafe_statuses = {
        _action_name(item): str(item.get("status") or "")
        for item in actions
        if str(item.get("status") or "").lower() not in PENDING_ACTION_STATUSES
    }
    unsafe_webhooks = {
        _action_name(item): _action_webhook(item)
        for item in actions
        if _action_webhook(item)
        and (urlparse(_action_webhook(item)).hostname or "") != "actions.invalid"
    }
    evidence = {
        "expected": sorted(expected),
        "actual": sorted(actual),
        "unsafeStatuses": unsafe_statuses,
        "unsafeWebhooks": unsafe_webhooks,
    }
    return (
        expected == actual and not unsafe_statuses,
        not unsafe_webhooks,
        evidence,
        actual,
    )


def _semantic_response_judge(
    api: AdminApi,
    target: Target,
    *,
    response_text: str,
    must_cover: list[str],
    must_not_claim: list[str],
    must_mark_unverified: list[str] | None = None,
) -> dict[str, Any]:
    result = api.post(
        f"/api/admin/projects/{target.project_id}/eval/e2e-response-judge",
        {
            "response_text": response_text,
            "must_cover": must_cover,
            "must_not_claim": must_not_claim,
            "must_mark_unverified": must_mark_unverified or [],
        },
    )
    if not isinstance(result, dict):
        raise LiveE2EError("semantic response judge returned no result object")
    return result


def _assert_case(
    recorder: AssertionRecorder,
    api: AdminApi,
    target: Target,
    persona: E2EPersona,
    case: PersonaCase,
    issue: dict[str, Any],
    article_ids: dict[str, str],
) -> dict[str, Any]:
    concerns = _matched_concerns(issue)
    expected_runbooks = {concern.runbook_key for concern in case.concerns}
    actual_runbooks = {_concern_runbook(concern) for concern in concerns if _concern_runbook(concern)}
    recorder.check(
        "minimum_concern_count",
        len(concerns) >= case.expected.minimum_concern_count,
        {"minimum": case.expected.minimum_concern_count, "actual": len(concerns)},
    )
    recorder.check(
        "exact_runbook_set",
        actual_runbooks == expected_runbooks,
        {"expected": sorted(expected_runbooks), "actual": sorted(actual_runbooks)},
    )

    tools_passed, tool_evidence, successful_tools = _fixture_tool_audit(
        issue, case.expected.tool_fixture_ids
    )
    recorder.check(
        "expected_fixture_tools_succeeded",
        tools_passed,
        tool_evidence,
    )

    replies = [item for item in issue.get("outboundMessages") or [] if isinstance(item, dict)]
    drafts = _draft_replies(issue)
    delivered = [
        item for item in replies if str(item.get("status") or "").lower() in DELIVERED_REPLY_STATUSES
    ]
    recorder.check(
        "exactly_one_combined_draft",
        len(drafts) == case.expected.draft_count == 1,
        {"expected": case.expected.draft_count, "actual": len(drafts)},
    )
    recorder.check(
        "no_queued_or_sent_reply",
        not delivered,
        {"statuses": [str(item.get("status") or "") for item in replies]},
    )
    draft = drafts[0] if drafts else {}
    draft_body = str(draft.get("body") or "")
    metadata = _reply_metadata(draft)
    recorder.check(
        "human_approval_required",
        metadata.get("approvalRequired") is True
        and metadata.get("approved") is not True
        and metadata.get("autoSend") is not True,
        {
            "approvalRequired": metadata.get("approvalRequired"),
            "approved": metadata.get("approved"),
            "autoSend": metadata.get("autoSend"),
        },
    )

    gate = metadata.get("groundingGate") if isinstance(metadata.get("groundingGate"), dict) else {}
    grounding_issues = {
        key: gate.get(key) or []
        for key in (
            "unsupportedClaims",
            "contradictions",
            "uncoveredObligations",
            "pendingActionClaims",
        )
    }
    recorder.check(
        "grounding_passed",
        gate.get("verified") is True
        and str(gate.get("status") or "").lower() == "passed"
        and not any(grounding_issues.values()),
        {
            "verified": gate.get("verified"),
            "status": gate.get("status"),
            **grounding_issues,
        },
    )
    expected_obligation_count = sum(len(item.answer_obligations) for item in case.concerns)
    assessments = [
        item for item in gate.get("obligationAssessments") or [] if isinstance(item, dict)
    ]
    runtime_obligation_ids = {
        str(obligation.get("obligationId") or obligation.get("obligation_id") or "")
        for concern in concerns
        for obligation in (concern.get("answerObligations") or concern.get("answer_obligations") or [])
        if isinstance(obligation, dict)
        and str(obligation.get("obligationId") or obligation.get("obligation_id") or "")
    }
    covered_obligation_ids = {
        str(item.get("obligationId") or item.get("obligation_id") or "")
        for item in assessments
        if item.get("covered") is True
        and str(item.get("resolution") or "answered").lower()
        in {"answered", "fulfilled_action", "pending_or_unavailable"}
        and str(item.get("obligationId") or item.get("obligation_id") or "")
    }
    recorder.check(
        "answer_obligations_covered",
        len(runtime_obligation_ids) >= expected_obligation_count
        and runtime_obligation_ids <= covered_obligation_ids,
        {
            "expectedMinimum": expected_obligation_count,
            "runtime": sorted(runtime_obligation_ids),
            "covered": sorted(covered_obligation_ids),
            "missing": sorted(runtime_obligation_ids - covered_obligation_ids),
        },
    )
    recorder.check(
        "persona_reply_rubric_grounded",
        gate.get("verified") is True
        and runtime_obligation_ids <= covered_obligation_ids
        and not any(grounding_issues.values()),
        {
            "mustCover": case.expected.must_cover,
            "mustNotClaim": case.expected.must_not_claim,
        },
    )
    cover_evidence = _rubric_term_evidence(draft_body, case.expected.must_cover)
    semantic_judge = _semantic_response_judge(
        api,
        target,
        response_text=draft_body,
        must_cover=case.expected.must_cover,
        must_not_claim=case.expected.must_not_claim,
    )
    recorder.check(
        "semantic_persona_reply_rubric",
        semantic_judge.get("passed") is True
        and int(semantic_judge.get("score") or 0) >= int(semantic_judge.get("threshold") or 90),
        semantic_judge,
    )

    expected_article_ids = {
        article_ids[item] for item in case.expected.knowledge_ids if item in article_ids
    }
    actual_article_ids = _citation_ids(draft)
    recorder.check(
        "expected_knowledge_cited",
        expected_article_ids <= actual_article_ids,
        {"expected": sorted(expected_article_ids), "actual": sorted(actual_article_ids)},
    )
    any_knowledge_passed, any_knowledge_evidence = _knowledge_any_of_audit(
        case.expected.knowledge_any_of,
        article_ids,
        actual_article_ids,
    )
    recorder.check(
        "expected_knowledge_any_of_cited",
        any_knowledge_passed,
        any_knowledge_evidence,
    )

    stages = _progress_stages(issue)
    missing_stages = [stage for stage in persona.test_policy.processing_stages if stage not in stages]
    incomplete_stages = {
        key: value
        for key, value in stages.items()
        if key in persona.test_policy.processing_stages
        and value.lower() not in {"completed", "success", "passed"}
    }
    recorder.check(
        "canonical_nine_processing_stages",
        not missing_stages and not incomplete_stages,
        {"stages": stages, "missing": missing_stages, "incomplete": incomplete_stages},
    )

    actions_passed, webhooks_passed, action_evidence, actual_actions = (
        _pending_action_audit(issue, case.expected.pending_actions)
    )
    recorder.check(
        "expected_actions_are_pending",
        actions_passed,
        action_evidence,
    )
    recorder.check(
        "action_webhooks_are_non_routable",
        webhooks_passed,
        action_evidence,
    )
    return {
        "concernCount": len(concerns),
        "runbooks": sorted(actual_runbooks),
        "successfulTools": sorted(successful_tools),
        "draftPreview": draft_body[:800],
        "processingStages": stages,
        "pendingActions": sorted(actual_actions),
        "citationArticleIds": sorted(actual_article_ids),
        "rubricTermDiagnostics": cover_evidence,
        "semanticJudge": semantic_judge,
    }


def _run_follow_ups(
    api: AdminApi,
    target: Target,
    persona: E2EPersona,
    case: PersonaCase,
    token: str,
    thread_id: str,
    original_issue_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, follow_up in enumerate(case.follow_ups, start=1):
        message_id = f"e2e-msg-{token}-f{index}"
        event_id = f"e2e-event-{token}-f{index}"
        payload = _message_payload(
            persona,
            case,
            token,
            thread_id=thread_id,
            message_id=message_id,
            event_id=event_id,
            body=follow_up.body,
        )
        ingest = api.post(
            f"/api/admin/projects/{target.project_id}/channels/{target.channel_id}/test-message",
            payload,
        )
        ingest = _wait_for_channel_test_job(
            api,
            target,
            ingest,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        issue_id = _issue_id_from_ingest(ingest)
        same_ticket = issue_id == original_issue_id
        issue: dict[str, Any] = {}
        if issue_id:
            issue = _wait_for_issue(
                api,
                target,
                issue_id,
                expected_drafts=1,
                timeout_seconds=timeout_seconds,
                poll_seconds=poll_seconds,
            )
        replies = [
            item
            for item in issue.get("outboundMessages") or []
            if isinstance(item, dict)
        ]

        def source_matches(actual: str) -> bool:
            return actual == message_id or actual.endswith(f":{message_id}")

        pending_replies: list[dict[str, Any]] = []
        stale_pending_reply_ids: list[str] = []
        superseded_reply_ids: list[str] = []
        for reply in replies:
            metadata = reply.get("metadata") if isinstance(reply.get("metadata"), dict) else {}
            automation_context = (
                metadata.get("automationContext")
                if isinstance(metadata.get("automationContext"), dict)
                else {}
            )
            source_message_id = str(
                automation_context.get("sourceMessageId")
                or metadata.get("sourceMessageId")
                or ""
            )
            if metadata.get("supersededBySourceMessageId"):
                superseded_reply_ids.append(str(reply.get("id") or ""))
            if (
                str(reply.get("status") or "").lower() == "draft"
                and metadata.get("approvalRequired") is True
                and metadata.get("approved") is not True
                and str(metadata.get("reviewStatus") or "").lower() == "pending"
            ):
                pending_replies.append(reply)
                if not source_matches(source_message_id):
                    stale_pending_reply_ids.append(str(reply.get("id") or ""))
        approval_state_fresh = not stale_pending_reply_ids
        results.append(
            {
                "id": follow_up.id,
                "issueId": issue_id,
                "sameTicket": same_ticket,
                "newMessageId": message_id,
                "pendingReplyIds": [str(reply.get("id") or "") for reply in pending_replies],
                "stalePendingReplyIds": stale_pending_reply_ids,
                "supersededReplyIds": superseded_reply_ids,
                "approvalStateFresh": approval_state_fresh,
                "passed": same_ticket and bool(issue_id) and approval_state_fresh,
            }
        )
    return results


def run_case(
    api: AdminApi,
    target: Target,
    persona: E2EPersona,
    case: PersonaCase,
    article_ids: dict[str, str],
    run_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    recorder = AssertionRecorder()
    token = _case_token(persona.id, run_id, case.id.lower())
    thread_id = f"e2e-thread-{token}"
    message_id = f"e2e-msg-{token}"
    event_id = f"e2e-event-{token}"
    payload = _message_payload(
        persona,
        case,
        token,
        thread_id=thread_id,
        message_id=message_id,
        event_id=event_id,
    )
    result: dict[str, Any] = {
        "id": case.id,
        "title": case.title,
        "threadId": thread_id,
        "messageId": message_id,
        "startedAt": _now_iso(),
        "assertions": recorder.assertions,
    }
    try:
        ingest = api.post(
            f"/api/admin/projects/{target.project_id}/channels/{target.channel_id}/test-message",
            payload,
        )
        ingest = _wait_for_channel_test_job(
            api,
            target,
            ingest,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        issue_id = _issue_id_from_ingest(ingest)
        recorder.check("inbound_created_ticket", bool(issue_id), {"issueId": issue_id})
        result["issueId"] = issue_id
        if not issue_id:
            raise LiveE2EError(f"case {case.id} ingestion did not return an issue ID")
        issue = _wait_for_issue(
            api,
            target,
            issue_id,
            expected_drafts=case.expected.draft_count,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        result["observed"] = _assert_case(
            recorder,
            api,
            target,
            persona,
            case,
            issue,
            article_ids,
        )
        before_replay = _business_state_fingerprint(issue)
        replay = api.post(
            f"/api/admin/projects/{target.project_id}/channels/{target.channel_id}/test-message",
            payload,
        )
        replay = _wait_for_channel_test_job(
            api,
            target,
            replay,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        replay_issue_id = _issue_id_from_ingest(replay)
        replay_issue = _wait_for_issue(
            api,
            target,
            issue_id,
            expected_drafts=case.expected.draft_count,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        after_replay = _business_state_fingerprint(replay_issue)
        receipt_delta_valid, receipt_delta_evidence = _replay_receipt_audit(
            issue,
            replay_issue,
            issue_id=issue_id,
            channel_id=target.channel_id,
            event_id=event_id,
            message_id=message_id,
        )
        processed = _count_from_ingest(replay, "processed")
        skipped = _count_from_ingest(replay, "skipped")
        recorder.check(
            "idempotent_replay_counts",
            processed == case.expected.idempotency.processed_on_replay
            and skipped == case.expected.idempotency.skipped_on_replay,
            {
                "expectedProcessed": case.expected.idempotency.processed_on_replay,
                "actualProcessed": processed,
                "expectedSkipped": case.expected.idempotency.skipped_on_replay,
                "actualSkipped": skipped,
            },
        )
        recorder.check(
            "idempotent_replay_state",
            replay_issue_id == issue_id and before_replay == after_replay,
            {
                "originalIssueId": issue_id,
                "replayIssueId": replay_issue_id,
                "before": before_replay,
                "after": after_replay,
            },
        )
        recorder.check(
            "idempotent_replay_receipt_delta",
            receipt_delta_valid,
            receipt_delta_evidence,
        )
        follow_ups = _run_follow_ups(
            api,
            target,
            persona,
            case,
            token,
            thread_id,
            issue_id,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        if follow_ups:
            recorder.check(
                "follow_ups_stay_on_same_ticket",
                all(item["passed"] for item in follow_ups),
                follow_ups,
            )
            result["followUps"] = follow_ups
    except Exception as exc:
        recorder.check("runner_completed_case", False, str(exc))
        result["error"] = str(exc)
    result["passed"] = recorder.passed
    result["finishedAt"] = _now_iso()
    return result


def run_knowledge_checks(
    api: AdminApi,
    target: Target,
    persona: E2EPersona,
    article_ids: dict[str, str],
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issue_by_case = {
        str(item.get("id") or ""): str(item.get("issueId") or "")
        for item in cases
        if item.get("issueId")
    }
    results: list[dict[str, Any]] = []
    for check in persona.knowledge_checks:
        recorder = AssertionRecorder()
        source_case = next(
            case for case in persona.cases if case.id == check.source_case_id
        )
        issue_id = issue_by_case.get(source_case.id, "")
        result: dict[str, Any] = {
            "id": check.id,
            "sourceCaseId": source_case.id,
            "issueId": issue_id,
            "assertions": recorder.assertions,
        }
        try:
            if not issue_id:
                raise LiveE2EError(
                    f"knowledge check {check.id} has no successful source issue"
                )
            before = _fetch_issue(api, target, issue_id)
            before_reply_ids = {
                str(item.get("id") or "")
                for item in before.get("outboundMessages") or []
                if isinstance(item, dict)
            }
            answer = api.post(
                f"/api/admin/projects/{target.project_id}/issues/{issue_id}/agent-answer",
                {
                    "question": check.question,
                    "createDraft": False,
                    "includeFeedbackLink": False,
                    "approvalRequired": True,
                    "autoSend": False,
                },
            )
            if not isinstance(answer, dict):
                raise LiveE2EError(f"knowledge check {check.id} returned no answer object")
            after = _fetch_issue(api, target, issue_id)
            after_reply_ids = {
                str(item.get("id") or "")
                for item in after.get("outboundMessages") or []
                if isinstance(item, dict)
            }
            reply_value = answer.get("reply")
            recorder.check(
                "knowledge_agent_answered_without_draft",
                bool(str(answer.get("answer") or "").strip())
                and (reply_value is None or reply_value == "")
                and before_reply_ids == after_reply_ids,
                {
                    "answerPresent": bool(str(answer.get("answer") or "").strip()),
                    "reply": reply_value,
                    "beforeReplyIds": sorted(before_reply_ids),
                    "afterReplyIds": sorted(after_reply_ids),
                },
            )
            expected = {
                article_ids[item]
                for item in check.expected_citation_ids
                if item in article_ids
            }
            actual = {
                str(item)
                for key in (
                    "knowledgeAccessedArticleIds",
                    "knowledgeContextArticleIds",
                )
                for item in (answer.get(key) if isinstance(answer.get(key), list) else [])
                if item
            }
            for citation in answer.get("citations") or []:
                if isinstance(citation, dict):
                    citation_id = citation.get("id") or citation.get("articleId")
                    if citation_id:
                        actual.add(str(citation_id))
            recorder.check(
                "knowledge_agent_used_expected_articles",
                expected <= actual,
                {"expected": sorted(expected), "actual": sorted(actual)},
            )
            recorder.check(
                "knowledge_agent_did_not_send",
                answer.get("autoSend") is not True,
                {"autoSend": answer.get("autoSend")},
            )
            answer_text = str(answer.get("answer") or "")
            cover_evidence = _rubric_term_evidence(answer_text, check.must_cover)
            unverified_evidence = _rubric_term_evidence(
                answer_text,
                check.must_mark_unverified,
            )
            semantic_judge = _semantic_response_judge(
                api,
                target,
                response_text=answer_text,
                must_cover=check.must_cover,
                must_not_claim=[],
                must_mark_unverified=check.must_mark_unverified,
            )
            recorder.check(
                "semantic_knowledge_reply_rubric",
                semantic_judge.get("passed") is True
                and int(semantic_judge.get("score") or 0)
                >= int(semantic_judge.get("threshold") or 90),
                semantic_judge,
            )
            result["answerPreview"] = answer_text[:1_000]
            result["citationArticleIds"] = sorted(actual)
            result["rubricTermDiagnostics"] = {
                "mustCover": cover_evidence,
                "mustMarkUnverified": unverified_evidence,
                "uncertaintyLanguagePresent": (
                    _UNVERIFIED_MARKERS.search(answer_text) is not None
                ),
            }
            result["semanticJudge"] = semantic_judge
        except Exception as exc:
            recorder.check("runner_completed_knowledge_check", False, str(exc))
            result["error"] = str(exc)
        result["passed"] = recorder.passed
        results.append(result)
    return results


def _summarize(report: dict[str, Any]) -> dict[str, Any]:
    personas = report.get("personas") or []
    cases = [case for persona in personas for case in persona.get("cases") or []]
    checks = [check for persona in personas for check in persona.get("knowledgeChecks") or []]
    assertions = [
        assertion
        for item in [*cases, *checks]
        for assertion in item.get("assertions") or []
    ]
    return {
        "personaCount": len(personas),
        "caseCount": len(cases),
        "passedCases": sum(1 for case in cases if case.get("passed") is True),
        "failedCases": sum(1 for case in cases if case.get("passed") is not True),
        "knowledgeCheckCount": len(checks),
        "passedKnowledgeChecks": sum(1 for check in checks if check.get("passed") is True),
        "failedKnowledgeChecks": sum(1 for check in checks if check.get("passed") is not True),
        "assertionCount": len(assertions),
        "failedAssertions": sum(1 for item in assertions if item.get("passed") is not True),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed and run portable Mantly personas against isolated live QA projects."
    )
    parser.add_argument("--api-base", required=True, type=_api_base)
    parser.add_argument(
        "--target",
        required=True,
        action="append",
        type=parse_target,
        metavar="PERSONA=PROJECT:CHANNEL",
        help="Repeat once per persona.",
    )
    parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        help=f"Environment variable containing the bearer token (default: {DEFAULT_TOKEN_ENV}).",
    )
    parser.add_argument("--persona-dir", type=Path, default=DEFAULT_PERSONA_DIR)
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = os.environ.get(args.token_env, "").strip()
    if not token:
        print(
            f"Missing bearer token in environment variable {args.token_env!r}.",
            file=sys.stderr,
        )
        return 2
    personas = {persona.id: persona for persona in load_personas(args.persona_dir)}
    targets: list[Target] = args.target
    target_error = _target_validation_error(targets)
    if target_error:
        print(target_error, file=sys.stderr)
        return 2
    target_ids = [target.persona_id for target in targets]
    unknown = set(target_ids) - set(personas)
    if unknown:
        print(f"Unknown persona target(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    run_id = args.run_id.strip() or (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + "".join(random.SystemRandom().choices(string.ascii_lowercase + string.digits, k=6))
    )
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "runId": run_id,
        "apiBase": args.api_base,
        "seeded": bool(args.seed),
        "startedAt": _now_iso(),
        "personas": [],
    }
    api = AdminApi(args.api_base, token, timeout_seconds=args.timeout_seconds)
    try:
        for target in targets:
            persona = personas[target.persona_id]
            persona_report: dict[str, Any] = {
                "personaId": persona.id,
                "projectId": target.project_id,
                "channelId": target.channel_id,
                "cases": [],
                "knowledgeChecks": [],
            }
            report["personas"].append(persona_report)
            print(f"[{persona.id}] target ready; seed={bool(args.seed)}", flush=True)
            try:
                if args.seed:
                    article_ids = seed_persona(api, target, persona)
                else:
                    article_ids = _existing_article_ids(api, target, persona)
                _preflight_target_for_run(api, target, persona)
                persona_report["knowledgeArticleIds"] = article_ids
            except Exception as exc:
                persona_report["seedError"] = str(exc)
                persona_report["passed"] = False
                print(f"[{persona.id}] seed failed: {exc}", file=sys.stderr, flush=True)
                continue
            runtime_safe = True
            for index, case in enumerate(persona.cases, start=1):
                try:
                    _preflight_target_for_run(api, target, persona)
                except Exception as exc:
                    runtime_safe = False
                    persona_report["runtimeSafetyError"] = str(exc)
                    persona_report["passed"] = False
                    print(
                        f"[{persona.id}] runtime safety preflight failed: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    break
                print(f"[{persona.id}] {index}/{len(persona.cases)} {case.id}: {case.title}", flush=True)
                case_report = run_case(
                    api,
                    target,
                    persona,
                    case,
                    article_ids,
                    run_id,
                    timeout_seconds=args.timeout_seconds,
                    poll_seconds=args.poll_seconds,
                )
                persona_report["cases"].append(case_report)
                status = "PASS" if case_report["passed"] else "FAIL"
                print(f"[{persona.id}] {case.id}: {status}", flush=True)
            if not runtime_safe:
                continue
            persona_report["knowledgeChecks"] = run_knowledge_checks(
                api,
                target,
                persona,
                article_ids,
                persona_report["cases"],
            )
            persona_report["passed"] = all(
                item.get("passed") is True
                for item in [
                    *persona_report["cases"],
                    *persona_report["knowledgeChecks"],
                ]
            )
    finally:
        api.close()
    report["finishedAt"] = _now_iso()
    report["summary"] = _summarize(report)
    report["passed"] = (
        bool(report["personas"])
        and all(persona.get("passed") is True for persona in report["personas"])
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], sort_keys=True), flush=True)
    print(f"Report: {args.report}", flush=True)
    return 0 if report["passed"] else 1


def _existing_article_ids(
    api: AdminApi,
    target: Target,
    persona: E2EPersona,
) -> dict[str, str]:
    articles = _items(
        api.get(f"/api/admin/projects/{target.project_id}/knowledge?status=all&limit=200")
    )
    by_marker = {
        str(tag): str(article.get("id") or "")
        for article in articles
        for tag in (article.get("tags") or [])
        if article.get("id")
    }
    result = {
        fixture.id: by_marker.get(_knowledge_marker(persona.id, fixture.id), "")
        for fixture in persona.seed.knowledge
    }
    missing = [fixture_id for fixture_id, article_id in result.items() if not article_id]
    if missing:
        raise LiveE2EError(
            f"persona knowledge is not seeded: {', '.join(missing)}; rerun with --seed"
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
