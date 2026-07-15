"""Factory for loading intent configs from PocketBase."""
from pathlib import Path


def get_intent_frontmatters(intents_dir: Path | None = None) -> list[dict]:
    """Return frontmatter-shaped dicts for project intents."""
    if hasattr(intents_dir, "project_id") and hasattr(intents_dir, "mode"):
        from automail.pipeline.store import list_project_intents

        return [
            {
                **(rec.get("metadata") or {}),
                "name": rec.get("name", ""),
                "description": rec.get("description", ""),
                "active": rec.get("active", True),
                "require_review": rec.get("require_review", False),
                "actions": rec.get("actions") or [],
                "tools": rec.get("tools") or [],
                "response": rec.get("response") or {},
            }
            for rec in list_project_intents(intents_dir)  # type: ignore[arg-type]
            if rec.get("name")
        ]
    return []


def get_known_intent_names(intents_dir: Path | None = None) -> set[str]:
    """Return active, non-_else intent names used for classification."""
    return {
        fm.get("name", "").lower()
        for fm in get_intent_frontmatters(intents_dir=intents_dir)
        if fm.get("name")
        and fm.get("name") != "_else"
        and fm.get("active", True) is not False
        and str(fm.get("active", True)).lower() != "false"
    }


def get_intent_body(intent_name: str, intents_dir: Path | None = None) -> str | None:
    """Return the body (instructions) of a named intent, or None if not found."""
    if hasattr(intents_dir, "project_id") and hasattr(intents_dir, "mode"):
        from automail.pipeline.store import get_project_intent

        rec = get_project_intent(intents_dir, intent_name)  # type: ignore[arg-type]
        return str(rec.get("content") or "") if rec else None
    return None


def get_intent_actions(intent_name: str, intents_dir: Path | None = None) -> list[dict]:
    """Return the actions list from a named intent's frontmatter."""
    target = intent_name.strip().lower()
    for frontmatter in get_intent_frontmatters(intents_dir=intents_dir):
        if frontmatter.get("name", "").lower() == target:
            actions = frontmatter.get("actions", [])
            return actions if isinstance(actions, list) else []
    return []


def get_intent_description(intent_name: str, intents_dir: Path | None = None) -> str:
    """Return the human-readable description of a named intent."""
    target = intent_name.strip().lower()
    for frontmatter in get_intent_frontmatters(intents_dir=intents_dir):
        if frontmatter.get("name", "").lower() == target:
            return str(frontmatter.get("description") or "").strip()
    return ""


def get_intent_tools(intent_name: str, intents_dir: Path | None = None) -> list[dict]:
    """Return the tools list from a named intent's frontmatter, or ``[]``.

    Each entry is a raw dict matching the identity tool shape (name,
    description, method, urlTemplate, headers, body, inputSchema).
    """
    target = intent_name.strip().lower()
    for frontmatter in get_intent_frontmatters(intents_dir=intents_dir):
        if frontmatter.get("name", "").lower() == target:
            tools = frontmatter.get("tools", [])
            return tools if isinstance(tools, list) else []
    return []


def get_intent_require_review(intent_name: str, intents_dir: Path | None = None) -> bool:
    """Return whether a matched intent must stop for human review."""
    target = intent_name.strip().lower()
    for frontmatter in get_intent_frontmatters(intents_dir=intents_dir):
        if frontmatter.get("name", "").lower() == target:
            value = frontmatter.get("require_review", False)
            if isinstance(value, bool):
                return value
            return str(value).lower() == "true"
    return False


def get_intent_response_config(intent_name: str, intents_dir: Path | None = None) -> dict:
    """Return response drafting config for a named intent."""
    target = intent_name.strip().lower()
    for frontmatter in get_intent_frontmatters(intents_dir=intents_dir):
        if frontmatter.get("name", "").lower() == target:
            response = frontmatter.get("response") or {}
            return response if isinstance(response, dict) else {}
    return {}


def get_intent_response_rules(intent_name: str, intents_dir: Path | None = None) -> list[str]:
    """Return per-intent response rules for a named intent.

    Response rules are read from the intent-level ``response`` config.
    """
    response = get_intent_response_config(intent_name, intents_dir=intents_dir)
    rules = response.get("response_rules", [])
    if isinstance(rules, list):
        return [str(r).strip() for r in rules if str(r).strip()]
    if isinstance(rules, str) and rules.strip():
        return [rules.strip()]
    return []


def _escape_pb(value: str) -> str:
    return value.replace("'", "\\'")


def _pb_intent_attachment_records(intent_name: str, intents_dir: Path | None = None) -> list[dict]:
    project_id = getattr(intents_dir, "project_id", None)
    if not project_id:
        return []

    from automail.db.pocketbase.client import _list_all

    return _list_all(
        "intent_attachments",
        (
            f"project='{_escape_pb(str(project_id))}'"
            f" && intent='{_escape_pb(intent_name.strip())}'"
        ),
        sort="filename",
        per_page=200,
    )


def get_intent_response_attachments(intent_name: str, intents_dir: Path | None = None) -> list[dict]:
    """Return per-intent response attachment metadata for a named intent.

    Each entry has ``filename``, ``description``, and ``mode`` ('always' | 'dynamic').
    Metadata is read from intent-level ``response.attachments``; uploaded
    PocketBase files are merged in so files without saved metadata still appear
    in the response prompt.
    """
    response = get_intent_response_config(intent_name, intents_dir=intents_dir)
    raw = response.get("attachments", [])
    configured: dict[str, dict] = {}
    if not isinstance(raw, list):
        raw = []
    for item in raw:
        if isinstance(item, dict) and item.get("filename"):
            filename = str(item["filename"]).strip()
            configured[filename] = {
                "filename": filename,
                "description": str(item.get("description", "")).strip(),
                "mode": str(item.get("mode", "always")).strip(),
            }

    result: list[dict] = []
    seen: set[str] = set()
    for rec in _pb_intent_attachment_records(intent_name, intents_dir=intents_dir):
        filename = str(rec.get("filename") or "").strip()
        if not filename:
            continue
        meta = configured.get(filename)
        result.append(
            meta
            or {
                "filename": filename,
                "description": "",
                "mode": "dynamic",
            },
        )
        seen.add(filename)

    if not result:
        return list(configured.values())

    for filename, meta in configured.items():
        if filename not in seen:
            result.append(meta)
    return result


def get_use_feedback_learnings(intent_name: str, intents_dir: Path | None = None) -> bool:
    """Return whether AI-generated feedback learnings should be injected.

    Reads ``use_feedback_learnings`` from the intent-level ``response`` config.
    Defaults to ``True`` when response generation is enabled and the value is
    not explicitly set.
    """
    response = get_intent_response_config(intent_name, intents_dir=intents_dir)
    value = response.get("use_feedback_learnings", True)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() != "false"
