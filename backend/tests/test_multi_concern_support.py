from automail.db.pocketbase import issues
from automail.support import issue_agent


def _action(name: str = "submit") -> dict:
    return {
        "name": name,
        "label": "Submit",
        "type": "button",
        "webhook": "https://example.test/action",
        "method": "POST",
    }


def test_runbook_actions_remain_scoped_to_concern_instances():
    intent_result = {
        "concerns": [
            {
                "concernId": "cancel-contract",
                "intentName": "contract-cancellation",
                "outcome": {"actions": [_action()]},
            },
            {
                "concernId": "buy-product",
                "intentName": "product-purchase",
                "outcome": {"actions": [_action()]},
            },
        ]
    }

    proposals = issues._runbook_action_proposals(intent_result)

    assert [(item["concernId"], item["runbook"]) for item in proposals] == [
        ("cancel-contract", "contract-cancellation"),
        ("buy-product", "product-purchase"),
    ]
    assert proposals[0]["payload"]["concernId"] == "cancel-contract"
    assert proposals[1]["payload"]["concernId"] == "buy-product"


def test_equivalent_same_runbook_actions_merge_concern_scope():
    intent_result = {
        "concerns": [
            {
                "concernId": "webhook-diagnosis",
                "intentName": "saas-webhook-recovery",
                "outcome": {
                    "actions": [
                        _action("rotate_signing_secret"),
                        _action("replay_webhook_events"),
                    ]
                },
            },
            {
                "concernId": "requested-recovery",
                "intentName": "saas-webhook-recovery",
                "outcome": {
                    "actions": [
                        _action("rotate_signing_secret"),
                        _action("replay_webhook_events"),
                    ]
                },
            },
            {
                "concernId": "secret-offer",
                "intentName": "saas-webhook-recovery",
                "outcome": {
                    "actions": [
                        _action("rotate_signing_secret"),
                        _action("replay_webhook_events"),
                    ]
                },
            },
        ]
    }

    proposals = issues._runbook_action_proposals(intent_result)

    assert [item["name"] for item in proposals] == [
        "rotate_signing_secret",
        "replay_webhook_events",
    ]
    for proposal in proposals:
        assert proposal["concernId"] == "webhook-diagnosis"
        assert proposal["concernIds"] == [
            "webhook-diagnosis",
            "requested-recovery",
            "secret-offer",
        ]
        assert proposal["payload"]["concernIds"] == proposal["concernIds"]


def test_same_runbook_action_keeps_distinct_executable_configs():
    first = _action("replay_webhook_events")
    first["payload"] = {"endpointId": "wh_orders_prod"}
    second = _action("replay_webhook_events")
    second["payload"] = {"endpointId": "wh_invoices_prod"}
    intent_result = {
        "concerns": [
            {
                "concernId": "orders-webhook",
                "intentName": "saas-webhook-recovery",
                "outcome": {"actions": [first]},
            },
            {
                "concernId": "invoices-webhook",
                "intentName": "saas-webhook-recovery",
                "outcome": {"actions": [second]},
            },
        ]
    }

    proposals = issues._runbook_action_proposals(intent_result)

    assert len(proposals) == 2
    assert [item["payload"]["endpointId"] for item in proposals] == [
        "wh_orders_prod",
        "wh_invoices_prod",
    ]


def test_merged_action_scope_is_visible_to_every_owned_concern():
    issue = {
        "aiRuns": [
            {
                "source": "channel:email-main",
                "metadata": {"sourceMessageId": "message-1"},
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "webhook-diagnosis",
                            "matched": True,
                            "intentName": "saas-webhook-recovery",
                            "outcome": {},
                        },
                        {
                            "concernId": "requested-recovery",
                            "matched": True,
                            "intentName": "saas-webhook-recovery",
                            "outcome": {},
                        },
                    ]
                },
            }
        ],
        "actionExecutions": [
            {
                "id": "action-1",
                "type": "runbook_webhook",
                "status": "pending",
                "metadata": {
                    "source": "runbook",
                    "approvalRequired": True,
                    "sourceMessageId": "message-1",
                    "concernId": "webhook-diagnosis",
                    "concernIds": [
                        "webhook-diagnosis",
                        "requested-recovery",
                    ],
                    "runbook": "saas-webhook-recovery",
                },
                "result": {
                    "proposedAction": {
                        "name": "rotate_signing_secret",
                        "label": "Rotate signing secret",
                        "concernId": "webhook-diagnosis",
                        "concernIds": [
                            "webhook-diagnosis",
                            "requested-recovery",
                        ],
                    }
                },
            }
        ],
    }

    ticket = issue_agent._automatic_ticket_context(issue)
    action = ticket["runbookActions"][0]
    scoped = issue_agent._scoped_grounding_ticket_evidence(ticket)

    assert action["concernIds"] == [
        "webhook-diagnosis",
        "requested-recovery",
    ]
    scoped_actions = {
        concern["concernId"]: concern.get("runbookActions", [])
        for concern in scoped["concerns"]
    }
    assert [item["name"] for item in scoped_actions["webhook-diagnosis"]] == [
        "rotate_signing_secret"
    ]
    assert [item["name"] for item in scoped_actions["requested-recovery"]] == [
        "rotate_signing_secret"
    ]


def test_successful_merged_action_evidence_is_scoped_to_every_concern():
    evidence_id = "action:execution-1"
    ticket = {
        "runbookActions": [
            {
                "name": "rotate_signing_secret",
                "label": "Rotate signing secret",
                "status": "success",
                "applied": True,
                "webhookResult": {"status": "ok"},
                "proof": {"status": "success", "reference": "ROT-42"},
                "evidenceId": evidence_id,
                "concernId": "webhook-diagnosis",
                "concernIds": [
                    "webhook-diagnosis",
                    "requested-recovery",
                ],
            }
        ]
    }

    evidence_by_concern = issue_agent._successful_action_evidence_ids_by_concern(
        ticket
    )

    assert evidence_by_concern == {
        "webhook-diagnosis": frozenset({evidence_id}),
        "requested-recovery": frozenset({evidence_id}),
    }


def test_same_runbook_open_ticket_actions_merge_into_one_approval():
    first = _action("open_ticket")
    first["initialValue"] = "Verify the return address and authorization."
    second = _action("open_ticket")
    second["initialValue"] = "Confirm who controls the refund timing."
    intent_result = {
        "concerns": [
            {
                "concernId": "return-logistics",
                "intentName": "warehouse-exception",
                "outcome": {"actions": [first]},
            },
            {
                "concernId": "refund-timing",
                "intentName": "warehouse-exception",
                "outcome": {"actions": [second]},
            },
        ]
    }

    proposals = issues._runbook_action_proposals(intent_result)

    assert len(proposals) == 1
    assert proposals[0]["concernId"] == "return-logistics"
    assert proposals[0]["concernIds"] == ["return-logistics", "refund-timing"]
    assert proposals[0]["payload"]["concernIds"] == ["return-logistics", "refund-timing"]
    assert proposals[0]["payload"]["open_ticket"] == (
        "Verify the return address and authorization.\n\n"
        "Confirm who controls the refund timing."
    )


def test_same_runbook_open_ticket_actions_keep_distinct_business_payloads():
    first = _action("open_ticket")
    first["payload"] = {"orderId": "ORDER-1"}
    second = _action("open_ticket")
    second["payload"] = {"orderId": "ORDER-2"}
    intent_result = {
        "concerns": [
            {
                "concernId": "first-order",
                "intentName": "warehouse-exception",
                "outcome": {"actions": [first]},
            },
            {
                "concernId": "second-order",
                "intentName": "warehouse-exception",
                "outcome": {"actions": [second]},
            },
        ]
    }

    proposals = issues._runbook_action_proposals(intent_result)

    assert len(proposals) == 2
    assert [item["payload"]["orderId"] for item in proposals] == ["ORDER-1", "ORDER-2"]


def test_issue_reply_context_contains_every_concern_and_safe_tool_facts():
    issue = {
        "id": "issue1",
        "subject": "Cancel and buy",
        "aiRuns": [
            {
                "source": "agent_field_extraction",
                "status": "success",
                "intentResult": {"fields": {"order": "ZF-1"}},
            },
            {
                "source": "channel:email-main",
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "cancel-contract",
                            "text": "Cancel contract C-184",
                            "matched": True,
                            "intentName": "contract-cancellation",
                            "confidence": "high",
                            "outcome": {
                                "status": "pending_approval",
                                "requiresHuman": True,
                                "replyRequirements": ["Do not claim cancellation completed."],
                            },
                        },
                        {
                            "concernId": "buy-product",
                            "text": "Buy three XYZ Pro units",
                            "concernSummary": "Customer wants to buy XYZ Pro.",
                            "summary": "Verified XYZ Pro is available for purchase.",
                            "matched": True,
                            "intentName": "product-purchase",
                            "confidence": "high",
                            "outcome": {
                                "status": "success",
                                "toolEvidence": [
                                    {
                                        "toolName": "product_lookup",
                                        "method": "GET",
                                        "status": "success",
                                        "facts": [
                                            {"path": "product", "value": "XYZ Pro"},
                                            {"path": "available", "value": True},
                                            {"path": "price", "value": 500},
                                        ],
                                        "headers": {"Authorization": "secret"},
                                    }
                                ],
                            },
                        },
                    ]
                },
                "toolCalls": [
                    {
                        "name": "product_lookup",
                        "method": "GET",
                        "status": "success",
                        "responseFacts": {
                            "product": "XYZ Pro",
                            "available": True,
                            "price": 500,
                        },
                        "headers": {"Authorization": "secret"},
                    }
                ],
            }
        ],
    }

    ticket = issue_agent._ticket_context(issue)

    assert [item["id"] for item in ticket["concerns"]] == [
        "cancel-contract",
        "buy-product",
    ]
    assert ticket["concerns"][0]["requiresHuman"] is True
    assert ticket["concerns"][1]["concernSummary"] == "Customer wants to buy XYZ Pro."
    assert (
        ticket["concerns"][1]["runbookOutcomeSummary"]
        == "Verified XYZ Pro is available for purchase."
    )
    assert ticket["concerns"][1]["toolEvidence"] == [
        {
            "name": "product_lookup",
            "method": "GET",
            "status": "success",
            "evidenceId": "tool:buy-product:product_lookup",
            "responseFacts": [
                {"path": "product", "value": "XYZ Pro"},
                {"path": "available", "value": True},
                {"path": "price", "value": 500},
            ],
        }
    ]
    assert "headers" not in ticket["concerns"][1]["toolEvidence"][0]
    assert "toolEvidence" not in ticket


def test_failed_tool_call_cannot_expose_response_facts():
    evidence = issue_agent._automatic_tool_evidence_context(
        [
            {
                "name": "contract_lookup",
                "method": "GET",
                "status": "http_500",
                "responseFacts": {"effectiveDate": "2026-08-31"},
            }
        ]
    )

    assert evidence == [
        {
            "name": "contract_lookup",
            "method": "GET",
            "status": "http_500",
        }
    ]


def test_newest_empty_runbook_run_does_not_revive_older_concerns_or_evidence():
    issue = {
        "aiRuns": [
            {
                "source": "channel:email-main",
                "status": "failed",
                "metadata": {"sourceMessageId": "message-new"},
                "intentResult": {},
            },
            {
                "source": "channel:email-main",
                "status": "success",
                "metadata": {"sourceMessageId": "message-old"},
                "intentResult": {
                    "concerns": [{
                        "concernId": "old-concern",
                        "matched": True,
                        "intentName": "old-runbook",
                        "toolEvidence": [{
                            "name": "old_lookup",
                            "status": "success",
                            "responseFacts": {"status": "old"},
                        }],
                    }],
                },
            },
        ]
    }

    concerns, evidence, scope = issue_agent._automatic_runbook_concern_context(issue)

    assert concerns == []
    assert evidence == []
    assert scope == {"sourceMessageId": "message-new"}
    assert "concerns" not in issue_agent._ticket_context(issue)


def test_newest_unrelated_ai_run_does_not_hide_latest_runbook_context():
    issue = {
        "aiRuns": [
            {
                "source": "agent_field_extraction",
                "intentResult": {"fields": {"order": "ZF-1"}},
            },
            {
                "source": "legacy-email-pipeline",
                "intentResult": {
                    "matched": True,
                    "concerns": [{
                        "concernId": "current-concern",
                        "matched": True,
                        "intentName": "current-runbook",
                    }],
                },
            },
        ]
    }

    concerns, _evidence, _scope = issue_agent._automatic_runbook_concern_context(issue)

    assert [concern["id"] for concern in concerns] == ["current-concern"]


def test_tool_evidence_ids_scope_modern_concerns_and_keep_legacy_flat_records():
    modern = {
        "concerns": [
            {
                "id": "first-concern",
                "toolEvidence": [{
                    "name": "shared-lookup",
                    "status": "success",
                    "evidenceId": "tool:first-concern:shared-lookup",
                    "responseFacts": {"status": "first"},
                }],
            },
            {
                "id": "second-concern",
                "toolEvidence": [{
                    "name": "shared-lookup",
                    "status": "success",
                    "evidenceId": "tool:second-concern:shared-lookup",
                    "responseFacts": {"status": "second"},
                }],
            },
        ]
    }
    legacy = {
        "toolEvidence": [{
            "name": "legacy-lookup",
            "status": "success",
            "evidenceId": "tool:legacy-lookup",
            "responseFacts": {"status": "legacy"},
        }]
    }
    spoofed = {
        "toolEvidence": [{
            "name": "legacy-lookup",
            "status": "success",
            "evidenceId": "tool:first-concern:legacy-lookup",
            "responseFacts": {"status": "spoofed"},
        }]
    }
    mis_scoped = {
        "concerns": [{
            "id": "first-concern",
            "toolEvidence": [{
                "name": "shared-lookup",
                "status": "success",
                "evidenceId": "tool:second-concern:shared-lookup",
                "responseFacts": {"status": "spoofed"},
            }],
        }]
    }

    assert issue_agent._automatic_tool_evidence_ids(modern) == (
        "tool:first-concern:shared-lookup",
        "tool:second-concern:shared-lookup",
    )
    assert issue_agent._automatic_tool_evidence_ids(legacy) == ("tool:legacy-lookup",)
    assert issue_agent._automatic_tool_evidence_ids(spoofed) == ()
    assert issue_agent._automatic_tool_evidence_ids(mis_scoped) == ()


def test_direct_runbook_outcome_keeps_review_reason_and_requirements():
    issue = {
        "aiRuns": [
            {
                "source": "channel:email-main",
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "cancel-contract",
                            "concernSummary": "Cancel contract C-184",
                            "summary": "Contract remains active; cancellation requires approval.",
                            "sourceText": "Cancel C-184",
                            "matched": True,
                            "intentName": "contract-cancellation",
                            "status": "requires_human",
                            "requiresHuman": True,
                            "requiresHumanReason": "Cancellation requires approval.",
                            "replyRequirements": ["Describe cancellation as pending."],
                            "forbiddenClaims": ["The contract is already cancelled."],
                        }
                    ]
                },
            }
        ]
    }

    ticket = issue_agent._ticket_context(issue)

    assert ticket["concerns"] == [
        {
            "id": "cancel-contract",
            "text": "Cancel C-184",
            "matched": True,
            "runbook": "contract-cancellation",
            "confidence": "",
            "status": "requires_human",
            "requiresHuman": True,
            "concernSummary": "Cancel contract C-184",
            "runbookOutcomeSummary": "Contract remains active; cancellation requires approval.",
            "reason": "Cancellation requires approval.",
            "replyRequirements": ["Describe cancellation as pending."],
            "forbiddenClaims": ["The contract is already cancelled."],
        }
    ]
    assert issue_agent._answer_obligations_from_issue(issue) == ()


def test_runbook_summaries_are_removed_from_grounding_evidence():
    issue = {
        "aiRuns": [
            {
                "source": "channel:email-main",
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "access-security",
                            "concernSummary": "Customer reports an unknown login.",
                            "summary": "A Warsaw login was verified.",
                            "sourceText": "I saw a login from Warsaw.",
                            "matched": True,
                            "intentName": "access-security",
                            "status": "ready",
                        }
                    ]
                },
            }
        ]
    }

    ticket = issue_agent._ticket_context(issue)
    scoped = issue_agent._scoped_grounding_ticket_evidence(ticket)

    assert ticket["concerns"][0]["concernSummary"] == "Customer reports an unknown login."
    assert ticket["concerns"][0]["runbookOutcomeSummary"] == "A Warsaw login was verified."
    grounding_context = scoped["concerns"][0]["context"]
    assert "concernSummary" not in grounding_context
    assert "runbookOutcomeSummary" not in grounding_context
    assert grounding_context["text"] == "I saw a login from Warsaw."


def test_reply_attachments_are_allowlisted_and_always_files_are_forced():
    issue = {
        "aiRuns": [
            {
                "source": "channel:email-main",
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "returns",
                            "matched": True,
                            "intentName": "returns",
                            "attachments": [
                                {"filename": "return-label.pdf", "mode": "dynamic"},
                                {"filename": "terms.pdf", "mode": "always"},
                                {"filename": "generated-rma.pdf", "mode": "generated"},
                            ],
                        }
                    ]
                },
            }
        ]
    }

    selected = issue_agent._validated_response_attachments(
        issue,
        ["return-label.pdf", "invented.pdf"],
    )

    assert selected == (
        "return-label.pdf",
        "terms.pdf",
        "generated-rma.pdf",
    )


def test_generated_runbook_attachment_resolves_only_from_pipeline_ai_message(monkeypatch):
    issue = {
        "messages": [
            {
                "direction": "customer",
                "attachments": [{"filename": "generated.pdf", "base64": "WRONG"}],
            },
            {
                "direction": "ai",
                "attachments": [
                    {
                        "filename": "generated.pdf",
                        "content_base64": "UklHSFQ=",
                        "content_type": "application/pdf",
                    }
                ],
            },
        ],
        "aiRuns": [],
    }
    monkeypatch.setattr(
        "automail.api.attachments.load_attachment_files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PB lookup not expected")),
    )

    resolved, unresolved = issues._resolve_runbook_reply_attachments(
        issue,
        ("generated.pdf",),
        tenant_id="tenant1",
        project_id="project1",
    )

    assert resolved[0]["content_base64"] == "UklHSFQ="
    assert unresolved == ()


def test_static_runbook_attachment_uses_strict_owner_lookup(monkeypatch):
    intent_result = {
        "concerns": [
            {
                "intentName": "returns",
                "attachments": [{"filename": "terms.pdf", "mode": "always"}],
            }
        ]
    }
    issue = {
        "messages": [],
        "aiRuns": [{"source": "channel:email", "intentResult": intent_result}],
    }
    calls: list[dict] = []

    def load(response, intents_dir=None, **kwargs):
        calls.append(
            {
                "filenames": response.response_attachments,
                "project": intents_dir.project_id,
                **kwargs,
            }
        )
        return [{"filename": "terms.pdf", "content_base64": "VEVSTVM="}]

    monkeypatch.setattr("automail.api.attachments.load_attachment_files", load)

    resolved, unresolved = issues._resolve_runbook_reply_attachments(
        issue,
        ("terms.pdf",),
        tenant_id="tenant1",
        project_id="project1",
    )

    assert unresolved == ()
    assert resolved[0]["filename"] == "terms.pdf"
    assert calls == [
        {
            "filenames": ["terms.pdf"],
            "project": "project1",
            "intent_result": intent_result,
            "strict_intent_ownership": True,
        }
    ]


def test_missing_generated_attachment_never_falls_back_to_static_file(monkeypatch):
    issue = {
        "messages": [],
        "aiRuns": [
            {
                "source": "slack",
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "returns",
                            "matched": True,
                            "intentName": "returns",
                            "attachments": [
                                {
                                    "filename": "return-label.pdf",
                                    "source": "tool",
                                    "mode": "generated",
                                }
                            ],
                        }
                    ]
                },
                "metadata": {
                    "kind": "direct_channel_runbooks",
                    "generatedAttachments": [],
                },
            }
        ],
    }
    monkeypatch.setattr(
        "automail.api.attachments.load_attachment_files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("generated file must not use static lookup")
        ),
    )

    resolved, unresolved = issues._resolve_runbook_reply_attachments(
        issue,
        ("return-label.pdf",),
        tenant_id="tenant1",
        project_id="project1",
    )

    assert resolved == []
    assert unresolved == ("return-label.pdf",)


def test_reply_context_excludes_action_evidence_from_older_messages():
    issue = {
        "aiRuns": [
            {
                "source": "channel:email-main",
                "metadata": {"emailId": "message-new"},
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "concern-new",
                            "matched": True,
                            "intentName": "returns",
                        }
                    ]
                },
            }
        ],
        "actionExecutions": [
            {
                "type": "runbook_webhook",
                "status": "success",
                "metadata": {
                    "source": "runbook",
                    "sourceMessageId": "message-old",
                    "concernId": "concern-old",
                },
                "result": {
                    "application": {
                        "applied": True,
                        "webhookResult": {"status": "ok", "response": {"status": "cancelled"}},
                    }
                },
            },
            {
                "type": "runbook_webhook",
                "status": "pending",
                "metadata": {
                    "source": "runbook",
                    "approvalRequired": True,
                    "sourceMessageId": "message-new",
                    "concernId": "concern-new",
                },
                "result": {"proposedAction": {"name": "create_return"}},
            },
        ],
    }

    ticket = issue_agent._ticket_context(issue)

    assert ticket["runbookActions"] == [
        {
            "name": "create_return",
            "label": "create_return",
            "status": "pending_approval",
            "concernId": "concern-new",
        }
    ]


def test_inbox_composer_requires_exact_concern_coverage():
    issue = {
        "aiRuns": [
            {
                "source": "channel:email-main",
                "intentResult": {
                    "concerns": [
                        {"concernId": "cancel", "matched": True, "intentName": "cancel"},
                        {"concernId": "buy", "matched": True, "intentName": "buy"},
                    ]
                },
            }
        ]
    }

    exact = issue_agent._validated_concern_coverage(
        issue,
        ["buy", "cancel"],
        model_requires_human=False,
        model_reason="",
    )
    missing = issue_agent._validated_concern_coverage(
        issue,
        ["cancel"],
        model_requires_human=False,
        model_reason="",
    )

    assert exact == (("buy", "cancel"), False, "")
    assert missing[1] is True
    assert "exact coverage" in missing[2]


def test_inbox_composer_requires_every_question_obligation():
    issue = {
        "aiRuns": [
            {
                "source": "channel:email-main",
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "billing",
                            "matched": True,
                            "intentName": "billing",
                            "answerObligations": [
                                {
                                    "obligationId": "billing:fee",
                                    "question": "What is the consultation fee?",
                                },
                                {
                                    "obligationId": "billing:retainer",
                                    "question": "Is a retainer required?",
                                },
                                {
                                    "obligationId": "billing:due-date",
                                    "question": "When is the invoice due?",
                                },
                            ],
                        }
                    ]
                },
            }
        ]
    }

    ticket = issue_agent._ticket_context(issue)
    exact = issue_agent._validated_obligation_coverage(
        issue,
        ["billing:retainer", "billing:due-date", "billing:fee"],
    )
    missing = issue_agent._validated_obligation_coverage(
        issue,
        ["billing:fee", "billing:retainer"],
    )

    assert [item["id"] for item in ticket["concerns"][0]["answerObligations"]] == [
        "billing:fee",
        "billing:retainer",
        "billing:due-date",
    ]
    assert exact == (
        ("billing:retainer", "billing:due-date", "billing:fee"),
        False,
        "",
    )
    assert missing[1] is True
    assert "every answer obligation" in missing[2]
