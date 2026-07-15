"""PocketBase-backed pipeline config and intent storage."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

import yaml

from automail.core.config import AdminConfig
from automail.db.pocketbase.client import _delete, _first, _list_all, _patch, _post, generate_id

logger = logging.getLogger(__name__)

PipelineMode = Literal["draft", "live"]

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


class _IndentedSafeDumper(yaml.SafeDumper):
    """PyYAML dumper that indents block lists under their parent key."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        return super().increase_indent(flow=flow, indentless=False)


@dataclass(frozen=True)
class PipelineSource:
    project_id: str
    mode: PipelineMode
    tenant_id: str | None = None


def config_payload(config: AdminConfig) -> dict[str, Any]:
    return {
        "orgName": config.org_name,
        "orgDescription": config.org_description,
        "useCustomOrg": config.use_custom_org,
        "llmModel": config.llm_model,
        "llmProvider": config.llm_provider,
        "llmApiKey": config.llm_api_key,
        "llmCustomBaseUrl": config.llm_custom_base_url,
        "llmCustomModel": config.llm_custom_model,
        "useCustomLlm": config.use_custom_llm,
        "identityNotes": config.identity_notes,
        "tool": config.tool,
        "useCustomSecurity": config.use_custom_security,
        "phishingMonitoringEnabled": config.phishing_monitoring_enabled,
        "promptInjectionMonitoringEnabled": config.prompt_injection_monitoring_enabled,
    }


def config_from_payload(raw: dict[str, Any] | None) -> AdminConfig:
    raw = raw or {}
    return AdminConfig(
        org_name=raw.get("orgName") or raw.get("org_name") or "",
        org_description=raw.get("orgDescription") or raw.get("org_description") or "",
        use_custom_org=raw.get("useCustomOrg", raw.get("use_custom_org", False)),
        llm_model=raw.get("llmModel") or raw.get("llm_model") or "",
        llm_provider=raw.get("llmProvider", raw.get("llm_provider", "gemini")),
        llm_api_key=raw.get("llmApiKey", raw.get("llm_api_key", "")),
        llm_custom_base_url=raw.get("llmCustomBaseUrl", raw.get("llm_custom_base_url", "")),
        llm_custom_model=raw.get("llmCustomModel", raw.get("llm_custom_model", "")),
        use_custom_llm=raw.get("useCustomLlm", raw.get("use_custom_llm", False)),
        identity_notes=raw.get("identityNotes", raw.get("identity_notes", "")),
        tool=raw.get("tool"),
        use_custom_security=raw.get(
            "useCustomSecurity",
            raw.get(
                "use_custom_security",
                bool(
                    raw.get("phishingMonitoringEnabled", raw.get("phishing_monitoring_enabled", False))
                    or raw.get(
                        "promptInjectionMonitoringEnabled",
                        raw.get("prompt_injection_monitoring_enabled", False),
                    )
                ),
            ),
        ),
        phishing_monitoring_enabled=raw.get(
            "phishingMonitoringEnabled",
            raw.get("phishing_monitoring_enabled", False),
        ),
        prompt_injection_monitoring_enabled=raw.get(
            "promptInjectionMonitoringEnabled",
            raw.get("prompt_injection_monitoring_enabled", False),
        ),
    )


def parse_intent_content(content: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content.strip()
    frontmatter = yaml.safe_load(match.group(1)) or {}
    return frontmatter, match.group(2).strip()


def compose_intent_content(record: dict[str, Any]) -> str:
    frontmatter = {
        **(record.get("metadata") or {}),
        "name": record.get("name", ""),
        "description": record.get("description", ""),
        "active": record.get("active", True),
        "require_review": record.get("require_review", False),
    }
    if record.get("tools"):
        frontmatter["tools"] = record.get("tools") or []
    if record.get("actions"):
        frontmatter["actions"] = record.get("actions") or []
    if record.get("response"):
        frontmatter["response"] = record.get("response") or {}
    frontmatter_text = yaml.dump(
        frontmatter,
        Dumper=_IndentedSafeDumper,
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    body = str(record.get("content") or "").strip()
    return f"---\n{frontmatter_text}\n---\n\n{body}\n"


def _escape(value: str) -> str:
    return value.replace("'", "\\'")


def _config_filter(source: PipelineSource) -> str:
    return f"project='{_escape(source.project_id)}' && mode='{source.mode}'"


def _intent_filter(source: PipelineSource, name: str | None = None) -> str:
    filters = [f"project='{_escape(source.project_id)}'", f"mode='{source.mode}'"]
    if name is not None:
        filters.append(f"name='{_escape(name)}'")
    return " && ".join(filters)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"false", "0", "no", "off"}


def read_project_config(source: PipelineSource) -> AdminConfig:
    rec = _first("project_configs", _config_filter(source))
    if not rec:
        return AdminConfig()
    return config_from_payload(rec.get("config"))


def _source_payload(source: PipelineSource) -> dict[str, Any]:
    payload = {
        "project": source.project_id,
        "mode": source.mode,
    }
    if source.tenant_id:
        payload["tenant"] = source.tenant_id
    return payload


def write_project_config(source: PipelineSource, config: AdminConfig) -> None:
    payload = {
        **_source_payload(source),
        "config": config_payload(config),
    }
    rec = _first("project_configs", _config_filter(source))
    if rec:
        _patch(f"/api/collections/project_configs/records/{rec['id']}", payload)
    else:
        _post("/api/collections/project_configs/records", {"id": generate_id(), **payload})


def _intent_child_filter(intent_id: str) -> str:
    return f"intent='{_escape(intent_id)}'"


def _intent_action_payload(source: PipelineSource, intent_id: str, action: dict[str, Any], sort_order: int) -> dict[str, Any]:
    config = {k: v for k, v in action.items() if k not in {"type", "label", "enabled", "sort_order", "sortOrder"}}
    payload = {
        **_source_payload(source),
        "intent": intent_id,
        "type": str(action.get("type") or ""),
        "label": str(action.get("label") or ""),
        "enabled": _as_bool(action.get("enabled"), default=True),
        "sort_order": int(action.get("sort_order", action.get("sortOrder", sort_order)) or sort_order),
        "config": config,
    }
    return payload


def _intent_tool_payload(source: PipelineSource, intent_id: str, tool: dict[str, Any], sort_order: int) -> dict[str, Any]:
    payload = {
        **_source_payload(source),
        "intent": intent_id,
        "name": str(tool.get("name") or ""),
        "description": str(tool.get("description") or ""),
        "method": str(tool.get("method") or "GET"),
        "url_template": str(tool.get("urlTemplate") or tool.get("url_template") or ""),
        "headers": tool.get("headers") if isinstance(tool.get("headers"), dict) else {},
        "body": tool.get("body"),
        "input_schema": tool.get("inputSchema") or tool.get("input_schema") or {},
        "file_config": tool.get("file") if isinstance(tool.get("file"), dict) else {},
        "enabled": _as_bool(tool.get("enabled"), default=True),
        "sort_order": int(tool.get("sort_order", tool.get("sortOrder", sort_order)) or sort_order),
    }
    return payload


def list_intent_actions(intent_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for rec in _list_all("intent_actions", _intent_child_filter(intent_id), sort="sort_order"):
        action = dict(rec.get("config") or {})
        if rec.get("type"):
            action["type"] = rec.get("type")
        if rec.get("label"):
            action["label"] = rec.get("label")
        if rec.get("enabled") is False:
            action["enabled"] = False
        actions.append(action)
    return actions


def list_intent_tools(intent_id: str) -> list[dict[str, Any]]:
    return [
        {
            "name": rec.get("name", ""),
            "description": rec.get("description", ""),
            "method": rec.get("method", "GET"),
            "urlTemplate": rec.get("url_template", ""),
            "headers": rec.get("headers") or {},
            "body": rec.get("body"),
            "inputSchema": rec.get("input_schema") or {},
            "file": rec.get("file_config") or {},
            **({"enabled": False} if rec.get("enabled") is False else {}),
        }
        for rec in _list_all("intent_tools", _intent_child_filter(intent_id), sort="sort_order")
    ]


def _delete_intent_children(intent_id: str) -> None:
    for collection in ("intent_actions", "intent_tools"):
        for rec in _list_all(collection, _intent_child_filter(intent_id)):
            _delete(f"/api/collections/{collection}/records/{rec['id']}")


def _replace_intent_children(
    source: PipelineSource,
    intent_id: str,
    actions: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> None:
    _delete_intent_children(intent_id)
    for index, action in enumerate(actions):
        if isinstance(action, dict):
            _post(
                "/api/collections/intent_actions/records",
                {"id": generate_id(), **_intent_action_payload(source, intent_id, action, index)},
            )
    for index, tool in enumerate(tools):
        if isinstance(tool, dict):
            _post(
                "/api/collections/intent_tools/records",
                {"id": generate_id(), **_intent_tool_payload(source, intent_id, tool, index)},
            )


def _hydrate_intent(rec: dict[str, Any]) -> dict[str, Any]:
    if not rec.get("id"):
        return rec
    actions = list_intent_actions(rec["id"])
    tools = list_intent_tools(rec["id"])
    metadata = dict(rec.get("metadata") or {})
    return {
        **rec,
        "metadata": metadata,
        "actions": actions,
        "tools": tools,
        "response": rec.get("response") or {},
    }


def list_project_intents(source: PipelineSource) -> list[dict[str, Any]]:
    return [_hydrate_intent(rec) for rec in _list_all("project_intents", _intent_filter(source), sort="name")]


def get_project_intent(source: PipelineSource, name: str) -> dict[str, Any] | None:
    target = name.strip().lower()
    for rec in list_project_intents(source):
        if str(rec.get("name", "")).lower() == target:
            return rec
    return None


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def upsert_project_intent(source: PipelineSource, name: str, content: str) -> dict[str, Any]:
    fm, body = parse_intent_content(content)
    intent_name = str(fm.get("name") or name).strip()
    if not intent_name:
        raise ValueError("Intent name is required")
    actions = _dict_list(fm.get("actions"))
    tools = _dict_list(fm.get("tools"))
    response = fm.get("response") if isinstance(fm.get("response"), dict) else {}
    known_keys = {"name", "description", "active", "require_review", "actions", "tools", "response"}
    payload = {
        **_source_payload(source),
        "name": intent_name,
        "description": str(fm.get("description") or ""),
        "active": _as_bool(fm.get("active"), default=True),
        "require_review": _as_bool(fm.get("require_review"), default=False),
        "response": response,
        "metadata": {k: v for k, v in fm.items() if k not in known_keys},
        "content": body,
    }
    rec = get_project_intent(source, name) or get_project_intent(source, intent_name)
    if rec:
        _patch(f"/api/collections/project_intents/records/{rec['id']}", payload)
        _replace_intent_children(source, rec["id"], actions, tools)
        return {"id": rec["id"], **payload, "actions": actions, "tools": tools}
    created = _post("/api/collections/project_intents/records", {"id": generate_id(), **payload})
    _replace_intent_children(source, created["id"], actions, tools)
    return {**created, "actions": actions, "tools": tools}


def delete_project_intent(source: PipelineSource, name: str) -> bool:
    rec = get_project_intent(source, name)
    if not rec:
        return False
    _delete_intent_children(rec["id"])
    return _delete(f"/api/collections/project_intents/records/{rec['id']}")


def replace_live_from_draft(project_id: str, tenant_id: str | None = None) -> None:
    draft = PipelineSource(project_id=project_id, mode="draft", tenant_id=tenant_id)
    live = PipelineSource(project_id=project_id, mode="live", tenant_id=tenant_id)
    write_project_config(live, read_project_config(draft))
    for rec in list_project_intents(live):
        _delete_intent_children(rec["id"])
        _delete(f"/api/collections/project_intents/records/{rec['id']}")
    for rec in list_project_intents(draft):
        payload = {
            "id": generate_id(),
            "project": project_id,
            "mode": "live",
            "name": rec.get("name", ""),
            "description": rec.get("description", ""),
            "active": rec.get("active", True),
            "require_review": rec.get("require_review", False),
            "response": rec.get("response") or {},
            "metadata": rec.get("metadata") or {},
            "content": rec.get("content") or "",
        }
        record_tenant = tenant_id or rec.get("tenant")
        if record_tenant:
            payload["tenant"] = record_tenant
        created = _post("/api/collections/project_intents/records", payload)
        _replace_intent_children(live, created["id"], _dict_list(rec.get("actions")), _dict_list(rec.get("tools")))


def has_unpublished_project_changes(project_id: str, tenant_id: str | None = None) -> bool:
    draft = PipelineSource(project_id=project_id, mode="draft", tenant_id=tenant_id)
    live = PipelineSource(project_id=project_id, mode="live", tenant_id=tenant_id)
    if config_payload(read_project_config(draft)) != config_payload(read_project_config(live)):
        return True

    def comparable(source: PipelineSource) -> list[dict]:
        return [
            {
                "name": rec.get("name", ""),
                "description": rec.get("description", ""),
                "active": rec.get("active", True),
                "require_review": rec.get("require_review", False),
                "actions": rec.get("actions") or [],
                "tools": rec.get("tools") or [],
                "response": rec.get("response") or {},
                "metadata": rec.get("metadata") or {},
                "content": rec.get("content") or "",
            }
            for rec in list_project_intents(source)
        ]

    return comparable(draft) != comparable(live)


def ensure_project_pipeline(project_id: str, tenant_id: str | None = None) -> None:
    """Ensure blank PocketBase draft/live config records exist for a project."""
    for mode in ("draft", "live"):
        source = PipelineSource(project_id, mode, tenant_id)  # type: ignore[arg-type]
        if not _first("project_configs", _config_filter(source)):
            write_project_config(source, AdminConfig())
