import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from automail.core.config import AdminConfig
from automail.pipeline.intent.intents_factory import get_intent_response_rules
from automail.pipeline.store import (
    PipelineSource,
    compose_intent_content,
    config_from_payload,
    config_payload,
    ensure_project_pipeline,
    list_project_intents,
    parse_intent_content,
)


def test_parse_intent_content_splits_frontmatter_and_body():
    frontmatter, body = parse_intent_content(
        "---\n"
        "name: claim\n"
        "description: Handle claim\n"
        "active: false\n"
        "---\n"
        "\n"
        "Reply with claim instructions.\n"
    )

    assert frontmatter["name"] == "claim"
    assert frontmatter["description"] == "Handle claim"
    assert frontmatter["active"] is False
    assert body == "Reply with claim instructions."


def test_parse_intent_content_accepts_body_without_frontmatter():
    frontmatter, body = parse_intent_content("Only instructions")

    assert frontmatter == {}
    assert body == "Only instructions"


def test_compose_intent_content_preserves_metadata_and_pb_fields():
    content = compose_intent_content(
        {
            "name": "claim",
            "description": "Handle claim",
            "active": True,
            "require_review": False,
            "actions": [{"type": "button", "name": "open", "label": "Open"}],
            "tools": [{"name": "lookup"}],
            "response": {"enabled": True, "response_rules": ["Use a concise tone"]},
            "content": "Reply with claim instructions.",
        }
    )

    frontmatter, body = parse_intent_content(content)
    assert frontmatter["name"] == "claim"
    assert frontmatter["description"] == "Handle claim"
    assert frontmatter["actions"] == [{"type": "button", "name": "open", "label": "Open"}]
    assert frontmatter["tools"] == [{"name": "lookup"}]
    assert frontmatter["response"] == {"enabled": True, "response_rules": ["Use a concise tone"]}
    assert body == "Reply with claim instructions."
    assert "\ntools:\n  - name: lookup\n" in content


def test_list_project_intents_hydrates_child_tools_and_actions(monkeypatch):
    def fake_list_all(collection, *_args, **_kwargs):
        if collection == "project_intents":
            return [{"id": "intent-1", "name": "claim", "metadata": {}, "content": "Body", "response": {"enabled": True}}]
        if collection == "intent_actions":
            return [{"type": "button", "label": "Open", "config": {"name": "open"}}]
        if collection == "intent_tools":
            return [{"name": "lookup", "method": "POST", "url_template": "https://example.test", "input_schema": {}}]
        return []

    monkeypatch.setattr("automail.pipeline.store._list_all", fake_list_all)

    intents = list_project_intents(PipelineSource("project-1", "draft"))

    assert intents[0]["actions"] == [{"name": "open", "type": "button", "label": "Open"}]
    assert intents[0]["response"] == {"enabled": True}
    assert intents[0]["tools"][0]["name"] == "lookup"


def test_response_config_is_used_for_response_rules(monkeypatch):
    monkeypatch.setattr(
        "automail.pipeline.intent.intents_factory.get_intent_frontmatters",
        lambda intents_dir=None: [
            {
                "name": "claim",
                "response": {"enabled": True, "response_rules": ["Use a concise tone"]},
            }
        ],
    )

    assert get_intent_response_rules("claim") == ["Use a concise tone"]


def test_config_payload_roundtrip():
    config = AdminConfig(
        org_name="Mantly",
        org_description="Email agent",
        use_custom_org=True,
        llm_provider="custom",
        llm_custom_base_url="https://llm.example.test",
        llm_custom_model="model-a",
        use_custom_llm=True,
        identity_notes="Find customer",
        tool={"type": "http"},
        use_custom_security=True,
        phishing_monitoring_enabled=True,
    )

    assert config_from_payload(config_payload(config)) == config


def test_ensure_project_pipeline_creates_missing_pb_configs(monkeypatch):
    calls = []

    monkeypatch.setattr("automail.pipeline.store._first", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "automail.pipeline.store.write_project_config",
        lambda source, config: calls.append((source.project_id, source.mode, source.tenant_id, config)),
    )

    ensure_project_pipeline("project-1", tenant_id="tenant-1")

    assert [(project_id, mode, tenant_id) for project_id, mode, tenant_id, _config in calls] == [
        ("project-1", "draft", "tenant-1"),
        ("project-1", "live", "tenant-1"),
    ]
    assert all(isinstance(config, AdminConfig) for *_source, config in calls)
