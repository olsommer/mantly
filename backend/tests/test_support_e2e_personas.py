from __future__ import annotations

# ruff: noqa: E402, I001

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import HTTPException
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from e2e.live import (
    LiveE2EError,
    _business_state_fingerprint,
    _fixture_tool_audit,
    _issue_fingerprint,
    _pending_action_audit,
    _preflight_target_for_run,
    _replay_receipt_audit,
    _target_validation_error,
    _wait_for_channel_test_job,
    build_intent_content,
    parse_target,
    seed_persona,
)
from e2e.schema import E2EPersona, REQUIRED_PROCESSING_STAGES, load_personas
from automail.api.admin import evals as evals_api


PERSONA_DIR = REPO_ROOT / "e2e" / "personas"


def test_builtin_e2e_personas_are_strictly_valid() -> None:
    personas = load_personas(PERSONA_DIR)

    assert {persona.id for persona in personas} == {
        "fulfillment",
        "lawyer",
        "saas-support",
    }
    assert sum(len(persona.cases) for persona in personas) == 30
    for persona in personas:
        assert len(persona.cases) == 10
        assert tuple(persona.test_policy.processing_stages) == REQUIRED_PROCESSING_STAGES
        assert persona.test_policy.allow_external_send is False
        assert persona.test_policy.allow_external_actions is False
        assert any(len(case.concerns) > 1 for case in persona.cases)
        assert all(case.expected.sent_count == 0 for case in persona.cases)
        assert all(case.expected.queued_count == 0 for case in persona.cases)
        assert all(case.expected.idempotency.state_unchanged for case in persona.cases)
        assert all(check.create_draft is False for check in persona.knowledge_checks)


def test_personas_use_only_synthetic_portable_state() -> None:
    forbidden_runtime_fragments = {
        "law-postdeploy",
        "zf-postdeploy",
        "bq3z1vav74vm7qp",
        "hsw7ampb96wuzf2",
        "rfz8yhn0wagoagu",
        "ikot2tmmlfce4cn",
        "admin_auth_token",
    }

    for path in PERSONA_DIR.glob("*.yaml"):
        raw = path.read_text(encoding="utf-8")
        lowered = raw.lower()
        assert not any(fragment in lowered for fragment in forbidden_runtime_fragments)

    for persona in load_personas(PERSONA_DIR):
        assert all(article.synthetic for article in persona.seed.knowledge)
        assert all(
            case.inbound.from_address.endswith("@example.test")
            for case in persona.cases
        )


def _webhook_receipt(
    receipt_id: str,
    *,
    replay: bool,
    status: str = "skipped",
    linked_issue_id: str = "issue1",
) -> dict:
    event_id = "event1"
    message_id = "message1"
    return {
        "id": receipt_id,
        "channelId": "channel1",
        "eventId": f"admin-test-job:{event_id}:nonce" if replay else event_id,
        "eventType": "admin_channel_test_message" if replay else "message_created",
        "providerMessageId": message_id,
        "status": status,
        "payload": {"eventId": event_id, "messageId": message_id},
        "result": {
            "status": status if replay else "success",
            "issueId": linked_issue_id,
            "messageId": message_id,
            "resolver": {
                "issueId": linked_issue_id,
                "providerMessageId": message_id,
            },
        },
    }


def _audit_replay_receipts(
    before_receipts: list[dict], after_receipts: list[dict]
) -> tuple[bool, dict]:
    return _replay_receipt_audit(
        {"id": "issue1", "channelWebhookEvents": before_receipts},
        {"id": "issue1", "channelWebhookEvents": after_receipts},
        issue_id="issue1",
        channel_id="channel1",
        event_id="event1",
        message_id="message1",
    )


def test_live_runner_business_fingerprint_excludes_receipts_only() -> None:
    before = {
        "id": "issue1",
        "status": "open",
        "channelWebhookEvents": [_webhook_receipt("receipt1", replay=False)],
        "outboundMessages": [{"id": "reply1", "status": "draft"}],
    }
    after = {
        **before,
        "channelWebhookEvents": [
            *before["channelWebhookEvents"],
            _webhook_receipt("receipt2", replay=True),
        ],
    }

    assert _business_state_fingerprint(before) == _business_state_fingerprint(after)
    assert _issue_fingerprint(before) != _issue_fingerprint(after)


def test_live_runner_replay_receipt_audit_accepts_one_linked_skipped_receipt() -> None:
    original = _webhook_receipt("receipt1", replay=False)
    replay = _webhook_receipt("receipt2", replay=True)

    passed, evidence = _audit_replay_receipts([original], [replay, original])

    assert passed is True
    assert evidence["originalReceiptsPreserved"] is True
    assert evidence["newReceiptValid"] is True


@pytest.mark.parametrize("change", ["remove", "mutate"])
def test_live_runner_replay_receipt_audit_rejects_original_receipt_change(
    change: str,
) -> None:
    original = _webhook_receipt("receipt1", replay=False)
    replay = _webhook_receipt("receipt2", replay=True)
    after_originals = []
    if change == "mutate":
        after_originals = [
            {**original, "status": "failed"},
        ]

    passed, evidence = _audit_replay_receipts(
        [original],
        [replay, *after_originals],
    )

    assert passed is False
    assert evidence["originalReceiptsPreserved"] is False


@pytest.mark.parametrize(
    "replay",
    [
        _webhook_receipt("receipt2", replay=True, status="processed"),
        _webhook_receipt("receipt2", replay=True, linked_issue_id="issue2"),
    ],
    ids=["wrong-status", "wrong-linkage"],
)
def test_live_runner_replay_receipt_audit_rejects_invalid_new_receipt(
    replay: dict,
) -> None:
    original = _webhook_receipt("receipt1", replay=False)

    passed, evidence = _audit_replay_receipts([original], [replay, original])

    assert passed is False
    assert evidence["originalReceiptsPreserved"] is True
    assert evidence["newReceiptValid"] is False


def test_live_runner_business_fingerprint_detects_material_ticket_change() -> None:
    before = {
        "id": "issue1",
        "status": "open",
        "outboundMessages": [{"id": "reply1", "status": "draft"}],
    }
    after = {
        **before,
        "outboundMessages": [{"id": "reply1", "status": "sent"}],
    }

    assert _business_state_fingerprint(before) != _business_state_fingerprint(after)


def test_personas_preserve_the_high_value_regression_cases() -> None:
    personas = {persona.id: persona for persona in load_personas(PERSONA_DIR)}
    lawyer_cases = {case.id: case for case in personas["lawyer"].cases}
    fulfillment_cases = {case.id: case for case in personas["fulfillment"].cases}
    saas_cases = {case.id: case for case in personas["saas-support"].cases}

    assert "law-gmbh-formation" in lawyer_cases["L06"].expected.knowledge_ids
    assert "law-potential-conflict" in {
        concern.runbook_key for concern in lawyer_cases["L08"].concerns
    }
    assert fulfillment_cases["E06"].expected.minimum_concern_count == 2
    assert "fulfillment-battery-safety" in fulfillment_cases["E06"].expected.knowledge_ids
    assert fulfillment_cases["E05"].expected.single_combined_reply is True
    assert saas_cases["S03"].expected.minimum_concern_count == 1
    assert sum(
        len(concern.answer_obligations) for concern in saas_cases["S03"].concerns
    ) == 4
    assert saas_cases["S10"].expected.tool_fixture_ids == []
    assert any(case.follow_ups for case in saas_cases.values())


def test_pending_actions_must_belong_to_a_matched_runbook() -> None:
    raw = yaml.safe_load((PERSONA_DIR / "lawyer.yaml").read_text(encoding="utf-8"))
    raw["cases"][0]["expected"]["pending_actions"].append("undeclared_action")

    with pytest.raises(ValidationError, match="not declared by its runbooks"):
        E2EPersona.model_validate(raw)


def test_live_runner_target_and_seeded_runbook_are_safe() -> None:
    target = parse_target("lawyer=project123:channel456")
    assert (target.persona_id, target.project_id, target.channel_id) == (
        "lawyer",
        "project123",
        "channel456",
    )

    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "lawyer"
    )
    content = build_intent_content(
        persona,
        "law-conflict-intake",
        "https://api.mantly.io",
    )
    frontmatter_text = content.split("---", 2)[1]
    frontmatter = yaml.safe_load(frontmatter_text)

    assert frontmatter["name"] == "law-conflict-intake"
    assert frontmatter["response"]["enabled"] is False
    assert any(
        "Never claim a selected action completed" in rule
        for rule in frontmatter["response"]["response_rules"]
    )
    assert all(
        not rule.startswith("Forbidden claim:")
        for rule in frontmatter["response"]["response_rules"]
    )
    assert {tool["name"] for tool in frontmatter["tools"]} == {
        "fixture_conflict_helvetia_pending",
        "fixture_conflict_northlake_pending",
    }
    assert all(
        tool["urlTemplate"].startswith(
            "https://api.mantly.io/demo/e2e/tool/lawyer/"
        )
        for tool in frontmatter["tools"]
    )
    assert all(
        action["webhook"].startswith("https://actions.invalid/e2e/lawyer/")
        for action in frontmatter["actions"]
    )


def test_live_runner_waits_for_async_channel_test_job() -> None:
    target = parse_target("lawyer=project123:channel456")

    class FakeApi:
        def __init__(self) -> None:
            self.paths: list[str] = []
            self.responses = iter([
                {
                    "runId": "job-row-1",
                    "status": "processing",
                    "processed": 0,
                    "failed": 0,
                    "skipped": 0,
                },
                {
                    "runId": "job-row-1",
                    "status": "processed",
                    "processed": 1,
                    "failed": 0,
                    "skipped": 0,
                    "issueId": "issue-1",
                },
            ])

        def get(self, path: str) -> dict:
            self.paths.append(path)
            return next(self.responses)

    api = FakeApi()
    result = _wait_for_channel_test_job(
        api,  # type: ignore[arg-type]
        target,
        {"runId": "job-row-1", "status": "queued"},
        timeout_seconds=1,
        poll_seconds=0,
    )

    assert result["issueId"] == "issue-1"
    assert api.paths == [
        "/api/admin/projects/project123/channels/test-message-jobs/job-row-1",
        "/api/admin/projects/project123/channels/test-message-jobs/job-row-1",
    ]


def test_live_runner_rejects_async_channel_test_without_run_id() -> None:
    target = parse_target("lawyer=project123:channel456")

    with pytest.raises(LiveE2EError, match="durable run ID"):
        _wait_for_channel_test_job(
            SimpleNamespace(),  # type: ignore[arg-type]
            target,
            {"status": "queued"},
            timeout_seconds=1,
            poll_seconds=0,
        )


def test_live_runner_keeps_case_specific_negatives_out_of_shared_runbooks() -> None:
    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "fulfillment"
    )
    content = build_intent_content(
        persona,
        "fulfillment-shipment-status",
        "https://api.mantly.io",
    )
    frontmatter = yaml.safe_load(content.split("---", 2)[1])

    rules = frontmatter["response"]["response_rules"]
    assert not any("Shipment status, location, ETA" in rule for rule in rules)


def test_live_runner_rejects_extra_or_failed_fixture_tools() -> None:
    issue = {
        "aiRuns": [
            {
                "toolCalls": [
                    {"name": "fixture_expected", "status": "success"},
                    {"name": "fixture_extra", "status": "success"},
                    {"name": "fixture_broken", "status": "fixture_not_found"},
                    {"name": "identity_lookup", "status": "success"},
                ]
            }
        ]
    }

    passed, evidence, successful = _fixture_tool_audit(issue, ["expected"])

    assert passed is False
    assert successful == {"fixture_expected", "fixture_extra"}
    assert evidence["fixtureErrors"] == {
        "fixture_broken": "fixture_not_found"
    }


def test_live_runner_requires_exact_pending_action_set() -> None:
    def action(name: str) -> dict:
        return {
            "status": "pending",
            "metadata": {
                "runbookAction": name,
                "proposedAction": {
                    "name": name,
                    "webhook": f"https://actions.invalid/e2e/test/{name}",
                },
            },
        }

    exact, safe, _evidence, actual = _pending_action_audit(
        {"actionExecutions": [action("request_export")]},
        ["request_export"],
    )
    assert exact is True
    assert safe is True
    assert actual == {"request_export"}

    exact_with_extra, safe_with_extra, evidence, _actual = _pending_action_audit(
        {
            "actionExecutions": [
                action("request_export"),
                action("request_workspace_deletion"),
            ]
        },
        ["request_export"],
    )
    assert exact_with_extra is False
    assert safe_with_extra is True
    assert evidence["actual"] == ["request_export", "request_workspace_deletion"]


def test_live_runner_preflight_rejects_active_automation_rule() -> None:
    class FakeApi:
        def get(self, path: str) -> dict:
            assert path.endswith("/automations?limit=200")
            return {"items": [{"id": "automation1", "name": "Auto send", "active": True}]}

    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "lawyer"
    )
    target = parse_target("lawyer=project123:channel456")

    with pytest.raises(
        LiveE2EError,
        match="active automation rules.*Auto send",
    ):
        seed_persona(FakeApi(), target, persona)  # type: ignore[arg-type]


def test_live_runner_preflight_has_zero_writes_for_foreign_knowledge() -> None:
    class FakeApi:
        writes: list[tuple[str, str]] = []

        def get(self, path: str) -> dict:
            if path.endswith("/automations?limit=200"):
                return {"items": []}
            if path.endswith("/knowledge?status=all&limit=200"):
                return {
                    "items": [
                        {
                            "id": "stale1",
                            "title": "Stale same-persona article",
                            "tags": ["e2e-id:lawyer:obsolete-fixture"],
                        }
                    ]
                }
            raise AssertionError(f"unexpected read after unsafe knowledge: {path}")

        def put(self, path: str, _payload: dict) -> None:
            self.writes.append(("PUT", path))

        def post(self, path: str, _payload: dict | None = None) -> None:
            self.writes.append(("POST", path))

        def patch(self, path: str, _payload: dict) -> None:
            self.writes.append(("PATCH", path))

        def delete(self, path: str) -> None:
            self.writes.append(("DELETE", path))

    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "lawyer"
    )
    target = parse_target("lawyer=project123:channel456")
    api = FakeApi()

    with pytest.raises(LiveE2EError, match="non-persona knowledge"):
        seed_persona(api, target, persona)  # type: ignore[arg-type]

    assert api.writes == []


def test_live_runner_runtime_preflight_rejects_channel_network_drift() -> None:
    class FakeApi:
        def get(self, path: str) -> dict:
            if path.endswith("/automations?limit=200"):
                return {"items": []}
            if path.endswith("/knowledge?status=all&limit=200"):
                return {"items": []}
            if path.endswith("/channels?limit=200"):
                return {
                    "items": [
                        {
                            "id": "channel456",
                            "channelKey": "e2e-lawyer-email",
                            "config": {
                                "e2ePersona": "lawyer",
                                "agentAutoSend": False,
                                "syncEnabled": False,
                                "pollingEnabled": "true",
                            },
                        }
                    ]
                }
            raise AssertionError(f"unexpected read after unsafe channel: {path}")

    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "lawyer"
    )
    target = parse_target("lawyer=project123:channel456")

    with pytest.raises(LiveE2EError, match="pollingEnabled"):
        _preflight_target_for_run(FakeApi(), target, persona)  # type: ignore[arg-type]


def test_live_runner_requires_a_distinct_project_per_persona() -> None:
    targets = [
        parse_target("lawyer=project123:channel456"),
        parse_target("fulfillment=project123:channel789"),
    ]

    assert "distinct disposable project" in _target_validation_error(targets)


def test_live_runner_runtime_preflight_rejects_unpublished_drift() -> None:
    class FakeApi:
        def get(self, path: str) -> dict:
            if path.endswith("/automations?limit=200"):
                return {"items": []}
            if path.endswith("/knowledge?status=all&limit=200"):
                return {"items": []}
            if path.endswith("/channels?limit=200"):
                return {
                    "items": [
                        {
                            "id": "channel456",
                            "channelKey": "e2e-lawyer-email",
                            "config": {
                                "e2ePersona": "lawyer",
                                "agentAutoSend": False,
                                "syncEnabled": False,
                            },
                        }
                    ]
                }
            if path.endswith("/publish/status"):
                return {"hasUnpublishedChanges": True}
            raise AssertionError(f"unexpected read after unpublished drift: {path}")

    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "lawyer"
    )
    target = parse_target("lawyer=project123:channel456")

    with pytest.raises(LiveE2EError, match="unpublished changes"):
        _preflight_target_for_run(FakeApi(), target, persona)  # type: ignore[arg-type]


def test_live_runner_runtime_preflight_rejects_external_runbook_tool() -> None:
    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "lawyer"
    )

    class FakeApi:
        api_base = "https://api.mantly.io"

        def get(self, path: str) -> dict | list[dict]:
            if path.endswith("/automations?limit=200"):
                return {"items": []}
            if path.endswith("/knowledge?status=all&limit=200"):
                return {
                    "items": [
                        {
                            "id": fixture.id,
                            "title": fixture.title,
                            "tags": [f"e2e-id:lawyer:{fixture.id}"],
                        }
                        for fixture in persona.seed.knowledge
                    ]
                }
            if path.endswith("/channels?limit=200"):
                return {
                    "items": [
                        {
                            "id": "channel456",
                            "channelKey": "e2e-lawyer-email",
                            "status": "active",
                            "config": {
                                "adapter": "buffer",
                                "e2ePersona": "lawyer",
                                "agentAutoSend": False,
                                "syncEnabled": False,
                            },
                        }
                    ]
                }
            if path.endswith("/publish/status"):
                return {"hasUnpublishedChanges": False}
            if path.endswith("/intents"):
                return [
                    {
                        "name": runbook.key,
                        "actions": [
                            {
                                "name": action,
                                "webhook": f"https://actions.invalid/e2e/lawyer/{action}",
                            }
                            for action in runbook.proposed_actions
                        ],
                        "active": True,
                        "require_review": True,
                        "response": {"enabled": False},
                    }
                    for runbook in persona.runbooks
                ]
            marker = "/intents/"
            if marker in path:
                runbook_name = path.rsplit(marker, 1)[1]
                content = build_intent_content(persona, runbook_name, self.api_base)
                if runbook_name == "law-conflict-intake":
                    content = content.replace(
                        "https://api.mantly.io/demo/e2e/tool/lawyer/",
                        "https://external.example/lookup/",
                    )
                return {"name": runbook_name, "content": content}
            raise AssertionError(f"unexpected path: {path}")

    target = parse_target("lawyer=project123:channel456")

    with pytest.raises(LiveE2EError, match="not an exact fixture lookup"):
        _preflight_target_for_run(FakeApi(), target, persona)  # type: ignore[arg-type]


def test_live_runner_seed_preflight_rejects_extra_project_channel() -> None:
    class FakeApi:
        writes: list[tuple[str, str]] = []

        def get(self, path: str) -> dict:
            if path.endswith("/automations?limit=200"):
                return {"items": []}
            if path.endswith("/knowledge?status=all&limit=200"):
                return {"items": []}
            if path.endswith("/channels?limit=200"):
                return {
                    "items": [
                        {
                            "id": "channel456",
                            "channelKey": "e2e-lawyer-email",
                            "status": "active",
                            "config": {"syncEnabled": False},
                        },
                        {
                            "id": "real-channel",
                            "channelKey": "support-email",
                            "status": "active",
                            "config": {"adapter": "imap"},
                        },
                    ]
                }
            raise AssertionError(f"unexpected read after extra channel: {path}")

        def put(self, path: str, _payload: dict) -> None:
            self.writes.append(("PUT", path))

        def post(self, path: str, _payload: dict | None = None) -> None:
            self.writes.append(("POST", path))

        def patch(self, path: str, _payload: dict) -> None:
            self.writes.append(("PATCH", path))

        def delete(self, path: str) -> None:
            self.writes.append(("DELETE", path))

    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "lawyer"
    )
    target = parse_target("lawyer=project123:channel456")
    api = FakeApi()

    with pytest.raises(LiveE2EError, match="non-target channels"):
        seed_persona(api, target, persona)  # type: ignore[arg-type]

    assert api.writes == []


def test_e2e_semantic_judge_is_gated_and_uses_response_rubric(monkeypatch) -> None:
    body = evals_api.E2EResponseJudgeInput(
        response_text="The export is pending owner verification.",
        must_cover=["Explain owner verification."],
        must_not_claim=["A completed export."],
        must_mark_unverified=["The export link."],
    )
    ctx = SimpleNamespace(project_id="project1", tenant_id="tenant1")
    monkeypatch.setattr(evals_api, "e2e_fixture_runtime_enabled", lambda: False)
    with pytest.raises(HTTPException) as disabled:
        asyncio.run(evals_api.judge_e2e_response(body, ctx))
    assert disabled.value.status_code == 404

    captured: dict = {}

    def fake_judge(expected, actual, has_response, **kwargs):
        captured.update(
            expected=expected,
            actual=actual,
            has_response=has_response,
            kwargs=kwargs,
        )
        return SimpleNamespace(
            response=SimpleNamespace(score=94, reasoning="All criteria satisfied."),
            token_usage={"totalTokens": 123},
        )

    monkeypatch.setattr(evals_api, "e2e_fixture_runtime_enabled", lambda: True)
    monkeypatch.setattr(evals_api, "get_draft_source", lambda *_args, **_kwargs: "draft")
    monkeypatch.setattr(evals_api, "run_judge", fake_judge)

    result = asyncio.run(evals_api.judge_e2e_response(body, ctx))

    assert result["passed"] is True
    assert result["score"] == 94
    expected_response = captured["expected"]["expected_response"]
    assert "MUST COVER" in expected_response
    assert "MUST NOT CLAIM" in expected_response
    assert "MUST EXPLICITLY MARK UNVERIFIED" in expected_response
    assert captured["actual"]["agentResponse"]["responseText"] == body.response_text
    assert captured["expected"]["expected_customer_found"] is True
    assert captured["expected"]["expected_intent_matched"] is True
    assert captured["actual"]["identityResult"]["found"] is True
    assert captured["actual"]["intentResult"] == {
        "matched": True,
        "intentName": "e2e-response-rubric",
        "actions": [],
    }
