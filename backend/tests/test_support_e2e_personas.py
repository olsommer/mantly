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
    AssertionRecorder,
    LiveE2EError,
    _assert_case,
    _business_state_fingerprint,
    _fixture_tool_audit,
    _issue_fingerprint,
    _knowledge_any_of_audit,
    _pending_action_audit,
    _preflight_target_for_run,
    _replay_receipt_audit,
    _semantic_response_judge,
    _target_validation_error,
    _wait_for_channel_test_job,
    _wait_for_issue,
    build_intent_content,
    parse_target,
    run_knowledge_checks,
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
        assert all(
            check.source_case_id in {case.id for case in persona.cases}
            for check in persona.knowledge_checks
        )


def test_knowledge_check_rejects_unknown_source_case() -> None:
    raw = yaml.safe_load((PERSONA_DIR / "lawyer.yaml").read_text(encoding="utf-8"))
    raw["knowledge_checks"][0]["source_case_id"] = "L99"

    with pytest.raises(ValidationError, match="unknown source case"):
        E2EPersona.model_validate(raw)


def test_knowledge_check_uses_its_explicit_source_case() -> None:
    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "lawyer"
    )
    target = parse_target("lawyer=project123:channel456")
    expected_article_id = "article-law-fees-retainer"

    class FakeApi:
        def __init__(self) -> None:
            self.answer_paths: list[str] = []

        def get(self, path: str) -> dict:
            assert path == "/api/admin/projects/project123/issues/issue-l05"
            return {"id": "issue-l05", "outboundMessages": []}

        def post(self, path: str, _payload: dict) -> dict:
            if path.endswith("/eval/e2e-response-judge"):
                return {"passed": True, "score": 100, "threshold": 90}
            self.answer_paths.append(path)
            assert path == (
                "/api/admin/projects/project123/issues/issue-l05/agent-answer"
            )
            return {
                "answer": "Verified synthetic billing facts with exceptions unapproved.",
                "reply": None,
                "autoSend": False,
                "knowledgeAccessedArticleIds": [expected_article_id],
            }

    api = FakeApi()
    results = run_knowledge_checks(
        api,  # type: ignore[arg-type]
        target,
        persona,
        {"law-fees-retainer": expected_article_id},
        [
            {"id": "L01", "issueId": "issue-l01"},
            {"id": "L05", "issueId": "issue-l05"},
        ],
    )

    assert results[0]["sourceCaseId"] == "L05"
    assert results[0]["issueId"] == "issue-l05"
    assert api.answer_paths == [
        "/api/admin/projects/project123/issues/issue-l05/agent-answer"
    ]


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
    lawyer_runbooks = {
        runbook.key: runbook for runbook in personas["lawyer"].runbooks
    }
    fulfillment_cases = {case.id: case for case in personas["fulfillment"].cases}
    fulfillment_runbooks = {
        runbook.key: runbook for runbook in personas["fulfillment"].runbooks
    }
    saas_cases = {case.id: case for case in personas["saas-support"].cases}
    lawyer_knowledge_checks = {
        check.id: check for check in personas["lawyer"].knowledge_checks
    }
    fulfillment_knowledge_checks = {
        check.id: check for check in personas["fulfillment"].knowledge_checks
    }
    saas_knowledge_checks = {
        check.id: check for check in personas["saas-support"].knowledge_checks
    }

    assert "law-gmbh-formation" in lawyer_cases["L06"].expected.knowledge_ids
    assert lawyer_runbooks["law-gmbh-formation"].required_guidance == [
        (
            "State explicitly that the formation consultation request is pending "
            "human review and is not confirmed."
        )
    ]
    conflict_intake_purpose = lawyer_runbooks["law-conflict-intake"].purpose
    existing_conflict_purpose = lawyer_runbooks["law-potential-conflict"].purpose
    assert "prospective-client or pre-engagement" in conflict_intake_purpose
    assert "no existing customer matter is required" in conflict_intake_purpose
    assert "their own existing or open firm matter" in existing_conflict_purpose
    assert "Never use this runbook for prospective-client" in existing_conflict_purpose
    assert [
        concern.runbook_key for concern in lawyer_cases["L08"].concerns
    ] == ["law-potential-conflict"]
    assert lawyer_cases["L08"].concerns[0].answer_obligations == [
        (
            "State the tool-confirmed matter status and whether substantive "
            "discussion is already paused."
        ),
        (
            "Address stopping discussion, recording the report, and escalating "
            "review separately."
        ),
    ]
    assert lawyer_cases["L08"].expected.minimum_concern_count == 1
    assert lawyer_cases["L08"].expected.tool_fixture_ids == [
        "matter-mat-2026-221"
    ]
    assert "Is any payment plan approved?" in lawyer_knowledge_checks["K01"].question
    assert any(
        "payment plan" in requirement
        for requirement in lawyer_knowledge_checks["K01"].must_mark_unverified
    )
    assert lawyer_knowledge_checks["K01"].source_case_id == "L05"
    assert fulfillment_knowledge_checks["K01"].source_case_id == "E05"
    fulfillment_knowledge_question = fulfillment_knowledge_checks["K01"].question
    for required_question in (
        "What is the current state of ZF-20991?",
        "May it be returned today?",
        "Is a return authorization confirmed?",
        "Is a return reference confirmed?",
        "Is a return route confirmed?",
        "Is refund approval confirmed?",
        "Is a refund date confirmed?",
        "Who controls final refund approval and posting time?",
    ):
        assert required_question in fulfillment_knowledge_question
    assert fulfillment_knowledge_checks["K01"].must_mark_unverified == [
        "Return route, authorization, reference, refund approval, and refund date."
    ]
    assert saas_knowledge_checks["K01"].source_case_id == "S02"
    assert fulfillment_cases["E06"].expected.minimum_concern_count == 2
    assert fulfillment_cases["E06"].expected.knowledge_ids == []
    assert set(fulfillment_cases["E06"].expected.knowledge_any_of) == {
        "fulfillment-battery-safety",
        "fulfillment-returns-refunds",
    }
    assert fulfillment_cases["E06"].expected.tool_fixture_ids == []
    assert fulfillment_cases["E07"].expected.tool_fixture_ids == []
    assert fulfillment_cases["E08"].expected.tool_fixture_ids == [
        "order-zf-10482"
    ]
    assert fulfillment_cases["E10"].expected.tool_fixture_ids == [
        "order-zf-20991"
    ]
    assert fulfillment_cases["E05"].expected.single_combined_reply is True
    assert [
        concern.runbook_key for concern in fulfillment_cases["E04"].concerns
    ] == ["fulfillment-delivery-exception"]
    assert fulfillment_runbooks[
        "fulfillment-delivery-exception"
    ].subsumes_runbooks == ["fulfillment-shipment-status"]
    assert fulfillment_runbooks[
        "fulfillment-delivery-exception"
    ].required_read_only_tools == ["fixture_shipment_zf_88310"]
    assert fulfillment_runbooks["fulfillment-partial-shipment"].response_rules == [
        (
            "A false separate_parcel_confirmed lookup result proves only that no "
            "second parcel is confirmed. Never infer or claim from that negative "
            "evidence that units are missing."
        )
    ]
    assert fulfillment_runbooks[
        "fulfillment-partial-shipment"
    ].required_guidance == [
        (
            "State the ordered units, every confirmed tracking number, and whether a "
            "second parcel is confirmed only from the successful order lookup."
        ),
        (
            "If no second parcel is confirmed, state explicitly that this does not "
            "prove any units are missing."
        ),
    ]
    assert fulfillment_runbooks["fulfillment-b2b-sla"].required_guidance == [
        (
            "Address affected order IDs and quantities separately: repeat every "
            "supplied value and explicitly request each missing field."
        ),
        (
            "State the campaign deadline exactly when supplied; otherwise ask for "
            "the deadline."
        ),
        (
            "State the reported operational impact when supplied; otherwise ask for "
            "the impact."
        ),
    ]
    assert saas_cases["S03"].expected.minimum_concern_count == 1
    assert sum(
        len(concern.answer_obligations) for concern in saas_cases["S03"].concerns
    ) == 4
    saas_runbooks = {
        runbook.key: runbook for runbook in personas["saas-support"].runbooks
    }
    assert {
        concern.runbook_key for concern in saas_cases["S08"].concerns
    } == {"saas-sso-scim-setup"}
    assert {
        concern.runbook_key for concern in saas_cases["S09"].concerns
    } == {"saas-audit-reporting"}
    assert any(
        "verified domains" in rule
        for rule in saas_runbooks["saas-sso-scim-setup"].required_guidance
    )
    assert "pricing questions" in saas_runbooks["saas-sso-scim-setup"].purpose
    assert "Price-only" in saas_runbooks["saas-subscription-change"].purpose
    assert any(
        "remove the exposed token" in rule
        for rule in saas_runbooks["saas-token-exposure"].required_guidance
    )
    token_guidance = saas_runbooks["saas-token-exposure"].required_guidance
    assert "Never repeat the secret." in token_guidance
    assert "Never email the secret or any replacement." in token_guidance
    assert "Require the approved secure channel for any replacement." in token_guidance
    token_exposure_purpose = saas_runbooks["saas-token-exposure"].purpose
    assert "actually exposed" in token_exposure_purpose
    assert all(
        marker in token_exposure_purpose
        for marker in ("leaked", "published", "committed")
    )
    assert {
        concern.runbook_key for concern in saas_cases["S10"].concerns
    } == {"saas-prompt-injection"}
    prompt_injection_purpose = saas_runbooks["saas-prompt-injection"].purpose
    assert "explicit instruction overrides" in prompt_injection_purpose
    assert "internal-prompt manipulation" in prompt_injection_purpose
    assert "that exact exposed credential or its replacement" in prompt_injection_purpose
    incident_guidance = saas_runbooks["saas-service-incident"].required_guidance
    assert len(incident_guidance) == 5
    assert [rule.split(" only from", 1)[0] for rule in incident_guidance] == [
        "State the incident status",
        "State the affected region",
        "State the affected service",
        "State the exact start time",
        "State the ETA",
    ]
    assert all("successful service-status lookup" in rule for rule in incident_guidance)
    assert "if it is absent, say that it is unavailable" in incident_guidance[-1]
    assert saas_runbooks["saas-webhook-recovery"].required_guidance == [
        "State that delivery remains unverified.",
        (
            "State that the approved recovery actions must complete before delivery "
            "can be considered recovered."
        ),
        (
            "State that a separate post-action delivery check must succeed before "
            "delivery can be considered fixed."
        ),
    ]
    assert saas_runbooks["saas-invoice-dispute"].required_guidance == [
        "State the invoice status only from the successful invoice lookup.",
        "State the exact invoice due date only from the successful invoice lookup.",
        (
            "State that credit eligibility and any amount remain unverified unless "
            "successful action evidence explicitly proves approval."
        ),
    ]
    assert saas_runbooks["saas-invoice-dispute"].required_read_only_tools == [
        "fixture_saas_invoice_inv_9012",
        "fixture_saas_subscription_northwind",
    ]
    assert saas_runbooks["saas-privacy-export"].required_read_only_tools == [
        "fixture_saas_account_acme_4421"
    ]
    assert saas_runbooks["saas-workspace-deletion"].required_read_only_tools == [
        "fixture_saas_account_acme_4421"
    ]
    assert saas_runbooks["saas-workspace-deletion"].required_guidance == [
        "State explicitly that a Billing Admin cannot authorize workspace deletion."
    ]
    assert saas_runbooks["saas-token-exposure"].required_read_only_tools == [
        "fixture_saas_token_acme_prod_7f2a"
    ]
    assert saas_cases["S10"].expected.tool_fixture_ids == []
    assert any(case.follow_ups for case in saas_cases.values())


def test_l08_seeds_matter_lookup_on_the_conflict_runbook() -> None:
    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "lawyer"
    )
    content = build_intent_content(
        persona,
        "law-potential-conflict",
        "https://api.mantly.io",
    )
    frontmatter = yaml.safe_load(content.split("---", 2)[1])

    assert "fixture_matter_mat_2026_221" in {
        tool["name"] for tool in frontmatter["tools"]
    }


def test_policy_only_cases_skip_logistics_lookups_without_losing_tool_coverage() -> None:
    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "fulfillment"
    )
    cases = {case.id: case for case in persona.cases}

    def tool_names(runbook_key: str) -> set[str]:
        content = build_intent_content(
            persona,
            runbook_key,
            "https://api.mantly.io",
        )
        frontmatter = yaml.safe_load(content.split("---", 2)[1])
        return {tool["name"] for tool in frontmatter["tools"]}

    assert cases["E06"].expected.tool_fixture_ids == []
    assert cases["E07"].expected.tool_fixture_ids == []
    assert tool_names("fulfillment-hazardous-battery") == set()
    assert tool_names("fulfillment-product-remedy") == set()
    assert tool_names("fulfillment-wrong-item") == set()
    assert "fixture_shipment_zf_10482" in tool_names("fulfillment-shipment-status")
    assert "fixture_order_zf_10482" in tool_names("fulfillment-partial-shipment")
    assert "fixture_order_zf_20991" in tool_names("fulfillment-return-refund")


def test_e04_seeds_subsumption_and_required_lookup_contracts() -> None:
    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "fulfillment"
    )
    content = build_intent_content(
        persona,
        "fulfillment-delivery-exception",
        "https://api.mantly.io",
    )
    frontmatter = yaml.safe_load(content.split("---", 2)[1])

    assert frontmatter["subsumes_runbooks"] == [
        "fulfillment-shipment-status"
    ]
    assert frontmatter["required_read_only_tools"] == [
        "fixture_shipment_zf_88310"
    ]
    assert {tool["name"] for tool in frontmatter["tools"]} == {
        "fixture_shipment_zf_88310"
    }


def test_fulfillment_reply_quality_constraints_reach_runtime_runbooks() -> None:
    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "fulfillment"
    )
    runbooks = {runbook.key: runbook for runbook in persona.runbooks}
    partial_shipment = yaml.safe_load(
        build_intent_content(
            persona,
            "fulfillment-partial-shipment",
            "https://api.mantly.io",
        ).split("---", 2)[1]
    )
    b2b_sla = yaml.safe_load(
        build_intent_content(
            persona,
            "fulfillment-b2b-sla",
            "https://api.mantly.io",
        ).split("---", 2)[1]
    )

    assert partial_shipment["response"]["response_rules"][1:] == runbooks[
        "fulfillment-partial-shipment"
    ].response_rules
    assert partial_shipment["response"]["required_guidance"] == runbooks[
        "fulfillment-partial-shipment"
    ].required_guidance
    assert len(partial_shipment["response"]["required_guidance"]) == 2
    assert partial_shipment["response"]["required_guidance"][1].endswith(
        "does not prove any units are missing."
    )
    assert b2b_sla["response"]["required_guidance"] == runbooks[
        "fulfillment-b2b-sla"
    ].required_guidance
    assert len(b2b_sla["response"]["required_guidance"]) == 3


def test_l06_consultation_guidance_reaches_runtime_runbook() -> None:
    persona = next(item for item in load_personas(PERSONA_DIR) if item.id == "lawyer")
    runbooks = {runbook.key: runbook for runbook in persona.runbooks}
    formation = yaml.safe_load(
        build_intent_content(
            persona,
            "law-gmbh-formation",
            "https://api.mantly.io",
        ).split("---", 2)[1]
    )

    assert formation["response"]["required_guidance"] == runbooks[
        "law-gmbh-formation"
    ].required_guidance
    assert formation["response"]["required_guidance"] == [
        (
            "State explicitly that the formation consultation request is pending "
            "human review and is not confirmed."
        )
    ]


def test_pending_actions_must_belong_to_a_matched_runbook() -> None:
    raw = yaml.safe_load((PERSONA_DIR / "lawyer.yaml").read_text(encoding="utf-8"))
    raw["cases"][0]["expected"]["pending_actions"].append("undeclared_action")

    with pytest.raises(ValidationError, match="not declared by its runbooks"):
        E2EPersona.model_validate(raw)


def test_subsumption_contract_must_reference_another_declared_runbook() -> None:
    raw = yaml.safe_load(
        (PERSONA_DIR / "fulfillment.yaml").read_text(encoding="utf-8")
    )
    exception = next(
        runbook
        for runbook in raw["runbooks"]
        if runbook["key"] == "fulfillment-delivery-exception"
    )
    exception["subsumes_runbooks"] = ["unknown-runbook"]

    with pytest.raises(ValidationError, match="subsumes unknown runbooks"):
        E2EPersona.model_validate(raw)

    exception["subsumes_runbooks"] = ["fulfillment-delivery-exception"]
    with pytest.raises(ValidationError, match="cannot subsume itself"):
        E2EPersona.model_validate(raw)


def test_knowledge_any_of_must_reference_seeded_knowledge() -> None:
    raw = yaml.safe_load((PERSONA_DIR / "fulfillment.yaml").read_text(encoding="utf-8"))
    raw["cases"][0]["expected"]["knowledge_any_of"] = ["unknown-article"]

    with pytest.raises(ValidationError, match="unknown knowledge_any_of"):
        E2EPersona.model_validate(raw)


def test_knowledge_any_of_cannot_be_explicitly_empty() -> None:
    raw = yaml.safe_load((PERSONA_DIR / "fulfillment.yaml").read_text(encoding="utf-8"))
    raw["cases"][0]["expected"]["knowledge_any_of"] = []

    with pytest.raises(ValidationError, match="List should have at least 1 item"):
        E2EPersona.model_validate(raw)


@pytest.mark.parametrize(
    ("actual_article_ids", "expected_passed"),
    [
        ({"article-battery"}, True),
        ({"article-returns"}, True),
        ({"article-unrelated"}, False),
        (set(), False),
    ],
)
def test_live_runner_knowledge_any_of_accepts_at_least_one_expected_citation(
    actual_article_ids: set[str],
    expected_passed: bool,
) -> None:
    passed, evidence = _knowledge_any_of_audit(
        ["fulfillment-battery-safety", "fulfillment-returns-refunds"],
        {
            "fulfillment-battery-safety": "article-battery",
            "fulfillment-returns-refunds": "article-returns",
        },
        actual_article_ids,
    )

    assert passed is expected_passed
    assert evidence["matched"] == sorted(
        {"article-battery", "article-returns"} & actual_article_ids
    )


def test_live_runner_knowledge_any_of_rejects_missing_article_mapping() -> None:
    passed, evidence = _knowledge_any_of_audit(
        ["fulfillment-battery-safety", "fulfillment-returns-refunds"],
        {"fulfillment-battery-safety": "article-battery"},
        {"article-battery"},
    )

    assert passed is False
    assert evidence["missingMappings"] == ["fulfillment-returns-refunds"]


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


def test_live_runner_returns_terminal_issue_with_no_expected_draft_for_assertions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = parse_target("fulfillment=project123:channel456")
    issue = {
        "id": "issue-no-draft",
        "aiRuns": [
            {
                "id": "run-1",
                "status": "needs_human",
                "metadata": {
                    "processingProgress": {
                        "status": "completed",
                        "stage": "completed",
                        "stages": [
                            {"key": key, "status": "completed"}
                            for key in REQUIRED_PROCESSING_STAGES
                        ],
                    }
                },
            }
        ],
        "outboundMessages": [],
    }

    class FakeApi:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, _path: str) -> dict:
            self.calls += 1
            return issue

    api = FakeApi()
    monkeypatch.setattr("e2e.live.time.sleep", lambda _seconds: None)

    result = _wait_for_issue(
        api,  # type: ignore[arg-type]
        target,
        "issue-no-draft",
        expected_drafts=1,
        timeout_seconds=60,
        poll_seconds=0,
    )

    assert result is issue
    assert api.calls == 2


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


def test_live_runner_seeds_explicit_mandatory_runbook_response_rules() -> None:
    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "saas-support"
    )

    token_frontmatter = yaml.safe_load(
        build_intent_content(
            persona,
            "saas-token-exposure",
            "https://api.mantly.io",
        ).split("---", 2)[1]
    )
    sso_frontmatter = yaml.safe_load(
        build_intent_content(
            persona,
            "saas-sso-scim-setup",
            "https://api.mantly.io",
        ).split("---", 2)[1]
    )

    token_guidance = token_frontmatter["response"]["required_guidance"]
    sso_guidance = sso_frontmatter["response"]["required_guidance"]
    assert any("remove the exposed token" in rule for rule in token_guidance)
    assert any("stop using the exposed token" in rule for rule in token_guidance)
    assert any("Preserve repository and access evidence" in rule for rule in token_guidance)
    assert any("approved secure channel" in rule for rule in token_guidance)
    assert any("verified domains" in rule for rule in sso_guidance)


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

    duplicate, safe_duplicate, duplicate_evidence, _actual = _pending_action_audit(
        {
            "actionExecutions": [
                action("request_export"),
                action("request_export"),
            ]
        },
        ["request_export"],
    )
    assert duplicate is False
    assert safe_duplicate is True
    assert duplicate_evidence["expectedCounts"] == {"request_export": 1}
    assert duplicate_evidence["actualCounts"] == {"request_export": 2}
    assert duplicate_evidence["duplicates"] == {"request_export": 2}


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


def test_live_runner_runtime_preflight_rejects_subsumption_drift() -> None:
    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "fulfillment"
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
                            "tags": [f"e2e-id:fulfillment:{fixture.id}"],
                        }
                        for fixture in persona.seed.knowledge
                    ]
                }
            if path.endswith("/channels?limit=200"):
                return {
                    "items": [
                        {
                            "id": "channel456",
                            "channelKey": "e2e-fulfillment-email",
                            "status": "active",
                            "config": {
                                "adapter": "buffer",
                                "e2ePersona": "fulfillment",
                                "agentAutoSend": False,
                                "syncEnabled": False,
                            },
                        }
                    ]
                }
            if path.endswith("/publish/status"):
                return {"hasUnpublishedChanges": False}
            if path.endswith("/intents"):
                return [{"name": runbook.key} for runbook in persona.runbooks]
            marker = "/intents/"
            if marker in path:
                runbook_name = path.rsplit(marker, 1)[1]
                content = build_intent_content(
                    persona,
                    runbook_name,
                    self.api_base,
                )
                if runbook_name == "fulfillment-delivery-exception":
                    head, raw_frontmatter, body = content.split("---", 2)
                    frontmatter = yaml.safe_load(raw_frontmatter)
                    frontmatter["subsumes_runbooks"] = []
                    content = (
                        f"{head}---\n"
                        f"{yaml.safe_dump(frontmatter, sort_keys=False)}"
                        f"---{body}"
                    )
                return {"name": runbook_name, "content": content}
            raise AssertionError(f"unexpected path: {path}")

    target = parse_target("fulfillment=project123:channel456")

    with pytest.raises(LiveE2EError, match="subsumption contract drifted"):
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
    assert "grading rubric, not content" in expected_response
    assert "explicitly deny it" in expected_response
    assert "does not violate the constraint" in expected_response
    assert "MUST COVER" in expected_response
    assert "MUST NOT CLAIM" in expected_response
    assert "MUST EXPLICITLY MARK UNVERIFIED" in expected_response
    assert captured["actual"]["agentResponse"]["responseText"] == body.response_text
    assert captured["expected"]["expected_customer_found"] is True
    assert captured["expected"]["expected_intent_matched"] is True
    assert captured["actual"]["identityResult"]["found"] is True
    assert captured["actual"]["intentResult"] == {
        "matched": True,
        "intentName": "e2e-synthetic-response",
        "actions": [],
    }
    assert captured["expected"]["expected_intent_name"] == "e2e-synthetic-response"
    assert captured["kwargs"]["timeout"] == 60
    assert captured["kwargs"]["max_retries"] == 1


def test_e2e_semantic_judge_marks_empty_rubric_sections_as_none(monkeypatch) -> None:
    body = evals_api.E2EResponseJudgeInput(
        response_text="The estimated delivery window is the next business day.",
        must_cover=["Every shipment field returned by the lookup."],
    )
    ctx = SimpleNamespace(project_id="project1", tenant_id="tenant1")
    captured: dict = {}

    def fake_judge(expected, actual, has_response, **kwargs):
        captured.update(expected=expected, actual=actual, has_response=has_response)
        return SimpleNamespace(
            response=SimpleNamespace(score=100, reasoning="All criteria satisfied."),
            token_usage={},
        )

    monkeypatch.setattr(evals_api, "e2e_fixture_runtime_enabled", lambda: True)
    monkeypatch.setattr(evals_api, "get_draft_source", lambda *_args, **_kwargs: "draft")
    monkeypatch.setattr(evals_api, "run_judge", fake_judge)

    result = asyncio.run(evals_api.judge_e2e_response(body, ctx))

    assert result["passed"] is True
    expected_response = captured["expected"]["expected_response"]
    assert "Never infer a requirement, move an item between sections" in expected_response
    assert "A section containing NONE imposes zero requirements" in expected_response
    assert expected_response.count("- NONE (this section imposes zero requirements).") == 2
    assert expected_response.endswith(
        "MUST EXPLICITLY MARK UNVERIFIED OR PENDING:\n"
        "- NONE (this section imposes zero requirements)."
    )


class _FakeSemanticJudgeApi:
    def __init__(self, results: list[dict]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict]] = []

    def post(self, path: str, body: dict) -> dict:
        self.calls.append((path, body))
        return self.results.pop(0)


def _run_semantic_judge(results: list[dict]) -> tuple[dict, _FakeSemanticJudgeApi]:
    api = _FakeSemanticJudgeApi(results)
    result = _semantic_response_judge(
        api,  # type: ignore[arg-type]
        parse_target("lawyer=project123:channel456"),
        response_text="A synthetic response.",
        must_cover=["The required synthetic fact."],
        must_not_claim=["A prohibited synthetic claim."],
    )
    return result, api


def test_live_semantic_judge_initial_pass_uses_one_attempt() -> None:
    original_reasoning = "The response covers the synthetic requirement."

    result, api = _run_semantic_judge(
        [
            {
                "passed": True,
                "score": 94,
                "threshold": 93,
                "reasoning": original_reasoning,
            }
        ]
    )

    assert len(api.calls) == 1
    assert result["passed"] is True
    assert result["score"] == 94
    assert result["threshold"] == 93
    assert result["reasoning"] == original_reasoning
    assert result["attemptCount"] == 1
    assert result["passedAttemptCount"] == 1
    assert result["attempts"] == [
        {
            "attempt": 1,
            "passed": True,
            "score": 94,
            "threshold": 93,
            "reasoning": original_reasoning,
        }
    ]


def test_live_semantic_judge_empty_response_fails_locally_without_request() -> None:
    api = _FakeSemanticJudgeApi([])

    result = _semantic_response_judge(
        api,  # type: ignore[arg-type]
        parse_target("lawyer=project123:channel456"),
        response_text=" \n\t",
        must_cover=["The required synthetic fact."],
        must_not_claim=["A prohibited synthetic claim."],
    )

    assert api.calls == []
    assert result == {
        "passed": False,
        "score": 0,
        "threshold": 90,
        "reasoning": (
            "Semantic evaluation was skipped because the runtime produced no "
            "non-empty response text. Inspect the draft-count and grounding "
            "assertions for the upstream withholding reason."
        ),
        "evaluationStatus": "skipped",
        "skipReason": "empty_response_text",
        "responseTextPresent": False,
        "attemptCount": 0,
        "passedAttemptCount": 0,
        "attempts": [],
    }


def test_live_case_without_draft_preserves_deterministic_assertions() -> None:
    persona = next(
        item for item in load_personas(PERSONA_DIR) if item.id == "saas-support"
    )
    case = next(item for item in persona.cases if item.id == "S09")
    target = parse_target("saas-support=project123:channel456")
    issue = {
        "id": "issue-no-draft",
        "aiRuns": [
            {
                "id": "run-1",
                "status": "needs_human",
                "metadata": {
                    "processingProgress": {
                        "status": "completed",
                        "stage": "completed",
                        "stages": [
                            {"key": key, "status": "completed"}
                            for key in REQUIRED_PROCESSING_STAGES
                        ],
                    }
                },
            }
        ],
        "outboundMessages": [],
    }

    class NoPostApi:
        def post(self, _path: str, _body: dict) -> dict:
            raise AssertionError("empty drafts must not reach the semantic judge API")

    recorder = AssertionRecorder()
    observed = _assert_case(
        recorder,
        NoPostApi(),  # type: ignore[arg-type]
        target,
        persona,
        case,
        issue,
        {},
    )
    assertions = {item["name"]: item for item in recorder.assertions}

    assert assertions["exactly_one_combined_draft"]["passed"] is False
    assert assertions["grounding_passed"]["passed"] is False
    assert assertions["answer_obligations_covered"]["passed"] is False
    assert assertions["semantic_persona_reply_rubric"] == {
        "name": "semantic_persona_reply_rubric",
        "passed": False,
        "evidence": observed["semanticJudge"],
    }
    assert observed["semanticJudge"]["skipReason"] == "empty_response_text"
    assert observed["semanticJudge"]["attemptCount"] == 0


def test_live_semantic_judge_initial_failure_two_followup_passes_uses_majority() -> None:
    long_failure_reasoning = "missed " + ("detail " * 200)
    result, api = _run_semantic_judge(
        [
            {
                "passed": False,
                "score": 88,
                "threshold": 90,
                "reasoning": long_failure_reasoning,
            },
            {"passed": True, "score": 96, "threshold": 95, "reasoning": "strong"},
            {"passed": True, "score": 94, "threshold": 92, "reasoning": "complete"},
        ]
    )

    assert len(api.calls) == 3
    assert result["passed"] is True
    assert result["score"] == 94
    assert result["threshold"] == 92
    assert result["reasoning"] == "complete"
    assert result["passedAttemptCount"] == 2
    assert [attempt["passed"] for attempt in result["attempts"]] == [False, True, True]
    assert len(result["attempts"][0]["reasoning"]) == 800
    assert result["attempts"][0]["reasoning"].endswith("…")


def test_live_semantic_judge_one_followup_pass_cannot_mask_two_failures() -> None:
    result, api = _run_semantic_judge(
        [
            {"passed": False, "score": 89, "threshold": 90, "reasoning": "incomplete"},
            {"passed": True, "score": 98, "threshold": 90, "reasoning": "lucky pass"},
            {"passed": False, "score": 87, "threshold": 90, "reasoning": "omission"},
        ]
    )

    assert len(api.calls) == 3
    assert result["passed"] is False
    assert result["score"] == 87
    assert result["threshold"] == 90
    assert result["reasoning"] == "omission"
    assert result["passedAttemptCount"] == 1
    assert [attempt["score"] for attempt in result["attempts"]] == [89, 98, 87]


def test_live_semantic_judge_excludes_exact_live_rubric_protocol_errors() -> None:
    result, api = _run_semantic_judge(
        [
            {
                "passed": False,
                "score": 0,
                "threshold": 90,
                "reasoning": (
                    "The expected response was a detailed grading rubric. The actual "
                    "response was a shipment status update. These are completely "
                    "different types of content with no semantic alignment. The "
                    "pipeline failed to produce the expected rubric text."
                ),
            },
            {
                "passed": False,
                "score": 0,
                "threshold": 90,
                "reasoning": (
                    "The expected response is a grading rubric, which is a "
                    "meta-instruction for evaluating a response. The actual response "
                    "is a customer-facing message about an order status. These are "
                    "semantically entirely different; the actual response does not "
                    "convey the expected rubric."
                ),
            },
            {
                "passed": True,
                "score": 95,
                "threshold": 90,
                "reasoning": "The customer response correctly applies the rubric.",
            },
        ]
    )

    assert len(api.calls) == 3
    assert result["passed"] is True
    assert result["score"] == 95
    assert result["reasoning"] == "The customer response correctly applies the rubric."
    assert result["validAttemptCount"] == 1
    assert result["invalidProtocolAttemptCount"] == 2
    assert result["passedAttemptCount"] == 1
    assert [item.get("invalidProtocol", False) for item in result["attempts"]] == [
        True,
        True,
        False,
    ]


def test_live_semantic_judge_excludes_e01_live_rubric_protocol_wording() -> None:
    result, api = _run_semantic_judge(
        [
            {
                "passed": False,
                "score": 0,
                "threshold": 90,
                "reasoning": (
                    "The expected response was the text of a grading rubric, as "
                    "indicated by the 'e2e-response-rubric' intent. However, the "
                    "actual pipeline output a customer-facing shipment status update. "
                    "This is a complete mismatch; the pipeline failed to convey the "
                    "expected rubric content."
                ),
            },
            {
                "passed": True,
                "score": 100,
                "threshold": 90,
                "reasoning": "The customer response correctly applies the rubric.",
            },
            {
                "passed": False,
                "score": 0,
                "threshold": 90,
                "reasoning": (
                    "The expected response was the text of a grading rubric. The "
                    "pipeline failed to convey the expected rubric content."
                ),
            },
        ]
    )

    assert len(api.calls) == 3
    assert result["passed"] is True
    assert result["score"] == 100
    assert result["validAttemptCount"] == 1
    assert result["invalidProtocolAttemptCount"] == 2
    assert result["passedAttemptCount"] == 1
    assert [item.get("invalidProtocol", False) for item in result["attempts"]] == [
        True,
        False,
        True,
    ]


def test_live_semantic_judge_preserves_e01_shaped_requirement_failures() -> None:
    result, api = _run_semantic_judge(
        [
            {
                "passed": False,
                "score": 70,
                "threshold": 90,
                "reasoning": (
                    "The expected response was the text of a grading rubric. The "
                    "actual response failed to convey the expected rubric requirement "
                    "that the resolution date remain unverified; instead it guaranteed "
                    "tomorrow."
                ),
            },
            {
                "passed": True,
                "score": 100,
                "threshold": 90,
                "reasoning": "The customer response correctly applies the rubric.",
            },
            {
                "passed": False,
                "score": 75,
                "threshold": 90,
                "reasoning": (
                    "The expected response was the text of a grading rubric. The "
                    "actual response failed to reproduce the expected rubric item "
                    "requiring every returned shipment field because it omitted the "
                    "tracking number."
                ),
            },
        ]
    )

    assert len(api.calls) == 3
    assert result["passed"] is False
    assert result["validAttemptCount"] == 3
    assert result["invalidProtocolAttemptCount"] == 0
    assert result["passedAttemptCount"] == 1
    assert all("invalidProtocol" not in item for item in result["attempts"])


def test_live_semantic_judge_preserves_genuine_rubric_failures() -> None:
    result, api = _run_semantic_judge(
        [
            {
                "passed": False,
                "score": 70,
                "threshold": 90,
                "reasoning": (
                    "The grading rubric says the refund date must remain unverified, "
                    "but the response does not convey the expected rubric requirement "
                    "and instead guarantees it."
                ),
            },
            {"passed": True, "score": 95, "threshold": 90, "reasoning": "pass"},
            {
                "passed": False,
                "score": 75,
                "threshold": 90,
                "reasoning": (
                    "Under the grading rubric, the actual answer failed to reproduce "
                    "the expected rubric's required current shipment status and ETA."
                ),
            },
        ]
    )

    assert len(api.calls) == 3
    assert result["passed"] is False
    assert result["validAttemptCount"] == 3
    assert result["invalidProtocolAttemptCount"] == 0
    assert result["passedAttemptCount"] == 1
    assert all("invalidProtocol" not in item for item in result["attempts"])


def test_live_semantic_judge_uses_majority_of_mixed_valid_attempts() -> None:
    result, api = _run_semantic_judge(
        [
            {
                "passed": False,
                "score": 0,
                "threshold": 90,
                "reasoning": (
                    "The expected response was a grading rubric. The pipeline failed "
                    "to reproduce the expected rubric."
                ),
            },
            {"passed": True, "score": 96, "threshold": 90, "reasoning": "pass one"},
            {"passed": True, "score": 94, "threshold": 90, "reasoning": "pass two"},
        ]
    )

    assert len(api.calls) == 3
    assert result["passed"] is True
    assert result["score"] == 94
    assert result["reasoning"] == "pass two"
    assert result["validAttemptCount"] == 2
    assert result["invalidProtocolAttemptCount"] == 1
    assert result["passedAttemptCount"] == 2


def test_live_semantic_judge_all_invalid_attempts_are_skipped_failure() -> None:
    invalid_reasons = [
        "The expected response was a grading rubric; the pipeline failed to produce the expected rubric.",
        "The expected response was a detailed grading rubric, but the response does not convey the expected rubric.",
        "The expected response is a grading rubric and the response does not reproduce the expected rubric.",
    ]
    result, api = _run_semantic_judge(
        [
            {
                "passed": False,
                "score": 0,
                "threshold": 90,
                "reasoning": reasoning,
            }
            for reasoning in invalid_reasons
        ]
    )

    assert len(api.calls) == 3
    assert result["passed"] is False
    assert result["score"] == 0
    assert result["threshold"] == 90
    assert result["evaluationStatus"] == "skipped"
    assert result["skipReason"] == "all_attempts_invalid_protocol"
    assert result["validAttemptCount"] == 0
    assert result["invalidProtocolAttemptCount"] == 3
    assert result["passedAttemptCount"] == 0
    assert all(item["invalidProtocol"] is True for item in result["attempts"])


def test_live_semantic_judge_majority_pass_uses_coherent_pass_representative() -> None:
    result, api = _run_semantic_judge(
        [
            {"passed": False, "score": 99, "threshold": 101, "reasoning": "failure"},
            {"passed": True, "score": 90, "threshold": 90, "reasoning": "pass low"},
            {"passed": True, "score": 100, "threshold": 100, "reasoning": "pass high"},
        ]
    )

    assert len(api.calls) == 3
    assert result["passed"] is True
    assert result["score"] == 90
    assert result["threshold"] == 90
    assert result["reasoning"] == "pass low"
    assert result["score"] >= result["threshold"]


def test_live_semantic_judge_majority_fail_uses_coherent_failure_representative() -> None:
    result, api = _run_semantic_judge(
        [
            {"passed": False, "score": 89, "threshold": 90, "reasoning": "failure low"},
            {"passed": True, "score": 95, "threshold": 90, "reasoning": "pass"},
            {"passed": False, "score": 96, "threshold": 100, "reasoning": "failure high"},
        ]
    )

    assert len(api.calls) == 3
    assert result["passed"] is False
    assert result["score"] == 89
    assert result["threshold"] == 90
    assert result["reasoning"] == "failure low"
