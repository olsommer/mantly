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
    assert ticket["concerns"][1]["toolEvidence"] == [
        {
            "name": "product_lookup",
            "method": "GET",
            "status": "success",
            "evidenceId": "tool:product_lookup",
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
            "reason": "Cancellation requires approval.",
            "replyRequirements": ["Describe cancellation as pending."],
            "forbiddenClaims": ["The contract is already cancelled."],
        }
    ]


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
