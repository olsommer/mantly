from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest
from langchain.messages import AIMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult

from automail import llm as llm_module
from automail.core import config as config_module
from automail.db.pocketbase import issues
from automail.llm import usage as usage_module
from automail.support import issue_agent
from automail.support import knowledge_workspace as knowledge_workspace_module
from automail.support.issue_agent import (
    AutomationAnswerOutput,
    AutomationGroundingObligationAssessment,
    AutomationGroundingOutput,
    AutomationGroundingUnitAssessment,
    KnowledgeAgentOutput,
)
from automail.support.knowledge_workspace import (
    MAX_COMMAND_CHARS,
    MAX_STDOUT_CHARS,
    KnowledgeWorkspace,
)


def _articles() -> list[dict[str, Any]]:
    return [
        {
            "id": "shipping-policy",
            "title": "Delayed shipment policy",
            "body": "A delayed parcel should arrive within seven business days. Ask for the tracking number if it is missing.",
            "tags": ["shipping", "delay"],
            "status": "published",
            "reviewStatus": "reviewed",
            "freshnessStatus": "fresh",
            "needsReview": False,
            "sourceUrl": "https://docs.example.com/shipping/delays",
        },
        {
            "id": "refund-policy",
            "title": "Refund policy",
            "body": "Refunds return to the original payment method after approval.",
            "tags": ["refund"],
            "status": "published",
            "reviewStatus": "reviewed",
            "freshnessStatus": "fresh",
            "needsReview": False,
        },
    ]


def _workspace(*, articles: list[dict[str, Any]] | None = None) -> KnowledgeWorkspace:
    return KnowledgeWorkspace(
        ticket={
            "id": "issue-1",
            "subject": "Parcel has not moved",
            "channel": "email",
            "summary": "Tracking has not changed for three days.",
        },
        messages=[
            {
                "direction": "customer",
                "sender": "customer@example.com",
                "body": "Where is my parcel?",
            }
        ],
        account={"accountId": "account-1"},
        conversation={"key": "conversation-1"},
        prior_agent_answers=[],
        question="What should we answer?",
        articles=_articles() if articles is None else articles,
    )


def _command_result(workspace: KnowledgeWorkspace, command: str) -> dict[str, Any]:
    result = json.loads(workspace.run(command))
    assert isinstance(result, dict)
    return result


def _article_path(workspace: KnowledgeWorkspace, article_id: str) -> str:
    result = _command_result(workspace, "cat knowledge/index.jsonl")
    assert result["exitCode"] == 0
    records = [json.loads(line) for line in result["stdout"].splitlines() if line.strip()]
    return next(record["path"] for record in records if record["id"] == article_id)


def test_message_context_includes_bounded_extracted_attachment_text() -> None:
    messages = [
        {
            "direction": "customer",
            "sender": "customer@example.com",
            "body": "Please review the attached termination letter.",
            "attachments": [
                {
                    "filename": "termination.txt",
                    "extractedText": "Termination date: 31 October. " + ("x" * 3_000),
                },
                {"filename": "scan.pdf", "contentType": "application/pdf"},
            ],
        }
    ]

    context = issue_agent._message_context(messages)

    assert len(context) == 1
    assert "Please review the attached termination letter." in context[0]["body"]
    assert "Attachments (extracted text, untrusted):" in context[0]["body"]
    assert "### termination.txt" in context[0]["body"]
    assert "Termination date: 31 October." in context[0]["body"]
    assert "scan.pdf" not in context[0]["body"]
    assert len(context[0]["body"]) < 4_200


def _shipment_tool_issue() -> dict[str, Any]:
    return {
        "id": "issue-1",
        "aiRuns": [
            {
                "source": "channel:email-main",
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "shipment-status",
                            "matched": True,
                            "intentName": "shipment-status",
                            "outcome": {
                                "toolEvidence": [
                                    {
                                        "name": "lookup-zf-e2e-shipment",
                                        "method": "GET",
                                        "status": "success",
                                        "responseFacts": {
                                            "trackingNumber": "UPS1Z999AA10123456784",
                                            "status": "in_transit",
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                },
            }
        ],
    }


def _shipment_tool_issue_with_pending_actions() -> dict[str, Any]:
    issue = _shipment_tool_issue()
    issue["aiRuns"][0]["metadata"] = {"emailId": "message1"}
    issue["actionExecutions"] = [
        {
            "type": "agent_triage",
            "actionKey": "agent_triage",
            "label": "Agent triage",
            "status": "pending",
            "metadata": {
                "source": "agent_triage",
                "approvalRequired": True,
                "automationContext": {"messageId": "message1"},
            },
            "result": {
                "proposedAction": {
                    "type": "triage_ticket",
                    "priority": "urgent",
                }
            },
        },
        {
            "type": "runbook_webhook",
            "actionKey": "open_ticket",
            "label": "Open ticket",
            "status": "pending",
            "metadata": {
                "source": "runbook",
                "approvalRequired": True,
                "sourceMessageId": "message1",
                "concernId": "shipment-status",
                "runbook": "shipment-status",
            },
            "result": {
                "proposedAction": {
                    "name": "open_ticket",
                    "label": "Open ticket",
                }
            },
        },
    ]
    return issue


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "Préparez une réponse fondée sur les connaissances publiées.",
            "La recherche dans les connaissances n’a pas pu être terminée.",
        ),
        (
            "Bitte bereiten Sie eine Antwort aus dem Wissen vor.",
            "Die Wissensrecherche konnte nicht abgeschlossen werden.",
        ),
        (
            "Prepare an answer from published knowledge.",
            "Knowledge research could not be completed.",
        ),
    ],
)
def test_knowledge_failure_answer_preserves_query_language(question: str, expected: str) -> None:
    assert issue_agent._knowledge_failure_answer(question).startswith(expected)


def test_knowledge_failure_answer_uses_latest_customer_language_for_generic_question() -> None:
    answer = issue_agent._knowledge_failure_answer(
        "Prepare the best support answer.",
        [{"direction": "customer", "body": "Pouvez-vous indiquer la réponse pour ce document ?"}],
    )

    assert answer.startswith("La recherche dans les connaissances n’a pas pu être terminée.")


def test_workspace_searches_and_reads_authorized_articles() -> None:
    workspace = _workspace()

    search = _command_result(workspace, 'rg -lF "seven business days" knowledge/articles')

    assert search["exitCode"] == 0
    assert "shipping-policy" in search["stdout"]
    assert "refund-policy" not in search["stdout"]

    article_path = _article_path(workspace, "shipping-policy")
    article = _command_result(workspace, f"cat {article_path}")

    assert article["exitCode"] == 0
    assert "Ask for the tracking number" in article["stdout"]
    assert any(path.endswith("0001--shipping-policy.json") for path in workspace.read_paths)
    assert any("shipping-policy" in call["readArticleIds"] for call in workspace.tool_calls)


@pytest.mark.parametrize(
    ("command", "expected_error"),
    [
        ("cat /etc/passwd", "No such file or directory"),
        ("curl https://example.com", "Command rejected by limits"),
        ("python -c 'print(1)'", "Command rejected by limits"),
        ("sh -c 'cat /etc/passwd'", "Command rejected by limits"),
        ("bash -c 'cat /etc/passwd'", "Command rejected by limits"),
    ],
)
def test_workspace_denies_host_network_and_process_access(command: str, expected_error: str) -> None:
    result = _command_result(_workspace(), command)

    assert result["exitCode"] != 0
    assert expected_error in result["stderr"]


@pytest.mark.parametrize(
    "command",
    [
        'rg -lF "seven business days" $PWD/knowledge/articles',
        "head $PWD/knowledge/articles/0001--shipping-policy.json",
        "cat $PWD/knowledge/articles/*.json",
        "cat ${PWD}/knowledge/articles/0001--shipping-policy.json",
        "head ~/knowledge/articles/0001--shipping-policy.json",
        "cat knowledge/{articles,other}/0001--shipping-policy.json",
        'rg -F "seven business days" knowledge/a?ticles',
        "head knowledge/a?ticles/0001--shipping-policy.json",
        "cat knowledge/a?ticles/*.json",
        "cat knowledge/[a]rticles/0001--shipping-policy.json",
        "cat README.md#x knowledge/articles/0001--shipping-policy.json",
        "head README.md#x knowledge/articles/0001--shipping-policy.json",
        "cut -c1-200 README.md#x knowledge/articles/0001--shipping-policy.json",
        'rg -Frl "seven business days" knowledge/articles',
        "head //workspace/knowledge/articles/0001--shipping-policy.json",
        "cat //workspace/knowledge/articles/0001--shipping-policy.json",
        'rg -F "seven business days" //workspace/knowledge/articles',
        "head knowledge/@(articles)/0001--shipping-policy.json",
        "head knowledge/+(articles)/0001--shipping-policy.json",
        "head knowledge/!(other)/0001--shipping-policy.json",
    ],
)
def test_workspace_rejects_shell_path_expansion_and_parser_ambiguity(command: str) -> None:
    workspace = _workspace()

    result = _command_result(workspace, command)

    assert result == {
        "exitCode": 2,
        "stdout": "",
        "stderr": "Command rejected by limits.",
    }
    assert (
        workspace.validated_citation_ids(
            ["shipping-policy"],
            ["knowledge/articles/0001--shipping-policy.json"],
        )
        == ()
    )


def test_workspace_cannot_write_virtual_or_host_files(tmp_path: Path) -> None:
    workspace = _workspace()
    host_target = tmp_path / "escaped.txt"

    virtual_write = _command_result(workspace, "cat request.json > copied.json")
    host_write = _command_result(workspace, f"cat request.json > {host_target}")

    assert virtual_write["exitCode"] != 0
    assert host_write["exitCode"] != 0
    assert "rejected" in virtual_write["stderr"].lower()
    assert "rejected" in host_write["stderr"].lower()
    assert _command_result(workspace, "cat copied.json")["exitCode"] != 0
    assert not host_target.exists()


def test_workspace_rejects_uniq_output_overwrite_and_preserves_citation_content() -> None:
    workspace = _workspace()
    article_path = _article_path(workspace, "shipping-policy")

    overwrite = _command_result(workspace, f"uniq request.json {article_path}")
    article = _command_result(workspace, f"cat {article_path}")

    assert overwrite["exitCode"] == 2
    assert "rejected" in overwrite["stderr"].lower()
    assert "seven business days" in article["stdout"]
    assert '"question"' not in article["stdout"]


def test_citations_require_a_read_and_are_deduplicated() -> None:
    workspace = _workspace()
    article_path = _article_path(workspace, "shipping-policy")

    assert (
        workspace.validated_citation_ids(
            ["shipping-policy", "refund-policy"],
            [article_path],
        )
        == ()
    )

    assert _command_result(workspace, f"cat {article_path}")["exitCode"] == 0

    assert workspace.validated_citation_ids(
        ["shipping-policy", "shipping-policy", "missing", "refund-policy", ""],
        [article_path],
    ) == ("shipping-policy",)


def test_citation_evidence_binds_exact_standalone_cat_chunk() -> None:
    workspace = _workspace()
    article_path = _article_path(workspace, "shipping-policy")

    assert _command_result(workspace, f"cat {article_path}")["exitCode"] == 0

    evidence = workspace.validated_citation_evidence(
        ["shipping-policy"],
        [article_path],
    )

    assert len(evidence) == 1
    assert evidence[0]["articleId"] == "shipping-policy"
    assert evidence[0]["path"] == article_path
    assert evidence[0]["excerpt"].startswith("A delayed parcel")
    assert evidence[0]["bodySha256"] == hashlib.sha256(_articles()[0]["body"].encode("utf-8")).hexdigest()
    assert len(evidence[0]["contentSha256"]) == 64


def test_broad_search_does_not_make_every_scanned_article_citable() -> None:
    workspace = _workspace()

    search = _command_result(workspace, 'rg -lF "seven business days" knowledge/articles')

    assert search["exitCode"] == 0
    assert (
        workspace.validated_citation_ids(
            ["shipping-policy", "refund-policy"],
            ["knowledge/articles/0001--shipping-policy.json"],
        )
        == ()
    )
    assert set(workspace.tool_calls[-1]["accessedArticleIds"]) == {"shipping-policy", "refund-policy"}
    assert workspace.tool_calls[-1]["readArticleIds"] == []

    shipping_path = _article_path(workspace, "shipping-policy")
    assert _command_result(workspace, f"cat {shipping_path}")["exitCode"] == 0
    assert workspace.validated_citation_ids(
        ["refund-policy", "shipping-policy"],
        [shipping_path],
    ) == ("shipping-policy",)


def test_workspace_rejects_oversized_commands() -> None:
    workspace = _workspace()

    result = _command_result(workspace, "x" * (MAX_COMMAND_CHARS + 1))

    assert result == {
        "exitCode": 2,
        "stdout": "",
        "stderr": "Command rejected by limits.",
    }
    assert workspace.tool_calls[-1]["rejected"] is True
    assert len(workspace.tool_calls[-1]["command"]) == MAX_COMMAND_CHARS


def test_workspace_chunks_large_articles_for_bounded_citable_reads() -> None:
    workspace = _workspace(
        articles=[
            {
                "id": "large-article",
                "title": "Large article",
                "body": "A" * 45_000 + "TAIL-EVIDENCE",
                "status": "published",
            }
        ]
    )
    index = _command_result(workspace, "cat knowledge/index.jsonl")
    record = json.loads(index["stdout"])
    article_path = record["paths"][-1]

    result = _command_result(workspace, f"cat {article_path}")

    assert result["exitCode"] == 0
    assert record["chunkCount"] > 1
    assert result["truncated"] is False
    assert "TAIL-EVIDENCE" in result["stdout"]
    assert record["bodyTruncated"] is False
    assert workspace.validated_citation_ids(
        ["large-article"],
        [article_path],
    ) == ("large-article",)


def test_workspace_truncates_large_context_output_without_authorizing_citation() -> None:
    workspace = KnowledgeWorkspace(
        ticket={"id": "issue-1"},
        messages=[{"direction": "customer", "body": "A" * (MAX_STDOUT_CHARS + 1_000)}],
        account={},
        conversation={},
        prior_agent_answers=[],
        question="What should we answer?",
        articles=_articles(),
    )

    result = _command_result(workspace, "cat ticket/messages.jsonl")

    assert result["exitCode"] == 0
    assert result["truncated"] is True
    assert len(result["stdout"]) == MAX_STDOUT_CHARS
    assert workspace.tool_calls[-1]["outputTruncated"] is True
    assert workspace.tool_calls[-1]["stdoutChars"] > MAX_STDOUT_CHARS
    assert (
        workspace.validated_citation_ids(
            ["shipping-policy"],
            ["knowledge/articles/0001--shipping-policy.json"],
        )
        == ()
    )


def test_workspace_marks_total_corpus_truncation_and_requires_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_limit = 8_000
    monkeypatch.setattr(knowledge_workspace_module, "MAX_CORPUS_CHARS", corpus_limit)
    workspace = _workspace(
        articles=[
            {
                "id": "oversized-article",
                "title": "Oversized article",
                "body": "A" * (corpus_limit + 1) + "UNMOUNTED-TAIL",
                "status": "published",
            }
        ]
    )
    index = _command_result(workspace, "cat knowledge/index.jsonl")
    record = json.loads(index["stdout"])
    article_path = record["paths"][-1]

    assert record["bodyTruncated"] is True
    assert record["mountedBodyChars"] == corpus_limit
    assert record["originalBodyChars"] > record["mountedBodyChars"]
    assert _command_result(workspace, f"cat {article_path}")["exitCode"] == 0
    citations = workspace.validated_citation_ids(["oversized-article"], [article_path])
    assert citations == ("oversized-article",)
    assert workspace.truncated_citation_ids(citations) == ("oversized-article",)


def test_article_search_requires_file_list_mode_and_pipelines_are_rejected() -> None:
    workspace = _workspace()

    exposed_content = _command_result(workspace, 'rg -F "seven business days" knowledge/articles')
    file_list = _command_result(workspace, 'rg -lF "seven business days" knowledge/articles')
    pipeline = _command_result(workspace, "cat knowledge/index.jsonl | head")

    assert exposed_content["exitCode"] == 2
    assert file_list["exitCode"] == 0
    assert "shipping-policy" in file_list["stdout"]
    assert pipeline["exitCode"] == 2


@pytest.mark.parametrize("reader", ["cut", "head", "nl", "tail"])
def test_article_content_requires_one_exact_cat(reader: str) -> None:
    workspace = _workspace(
        articles=[
            {
                "id": "large-article",
                "title": "Large article",
                "body": "FIRST" + "A" * 4_100 + "TAIL-EVIDENCE",
                "status": "published",
            }
        ]
    )
    index = _command_result(workspace, "cat knowledge/index.jsonl")
    record = json.loads(index["stdout"])
    first_path, last_path = record["paths"][0], record["paths"][-1]

    partial_read = _command_result(workspace, f"{reader} {last_path}")
    multi_cat = _command_result(workspace, f"cat {first_path} {last_path}")
    exact_read = _command_result(workspace, f"cat {last_path}")

    assert partial_read["exitCode"] == 2
    assert multi_cat["exitCode"] == 2
    assert exact_read["exitCode"] == 0
    assert "TAIL-EVIDENCE" in exact_read["stdout"]
    assert workspace.validated_citation_ids(["large-article"], [first_path]) == ()
    assert workspace.validated_citation_ids(["large-article"], [last_path]) == ("large-article",)


class _FakeAgent:
    def __init__(
        self,
        *,
        tool: Any,
        commands: list[str],
        output: KnowledgeAgentOutput,
        invoke_assertion: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    ) -> None:
        self._tool = tool
        self._commands = commands
        self._output = output
        self._invoke_assertion = invoke_assertion

    def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
        if self._invoke_assertion:
            self._invoke_assertion(inputs, config)
        for command in self._commands:
            self._tool.invoke({"command": command})
        return {"structured_response": self._output}


def _patch_agent_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    commands: list[str],
    output: KnowledgeAgentOutput,
    captured: dict[str, Any] | None = None,
) -> None:
    fake_llm = object()
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(llm_module, "resolve_effective_config", lambda config, _tenant, _project: config)
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: fake_llm)
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    def fake_create_agent(**kwargs: Any) -> _FakeAgent:
        if captured is not None:
            captured.update(kwargs)

        def assert_invoke(inputs: dict[str, Any], config: dict[str, Any]) -> None:
            assert "Search before answering" in inputs["messages"][0]["content"]
            assert config["recursion_limit"] == 48
            assert config["metadata"]["tenant_id"] == "tenant-1"
            assert config["metadata"]["project_id"] == "project-1"
            assert config["metadata"]["issue_id"] == "issue-1"

        return _FakeAgent(
            tool=kwargs["tools"][0],
            commands=commands,
            output=output,
            invoke_assertion=assert_invoke,
        )

    monkeypatch.setattr(issue_agent, "create_agent", fake_create_agent)


def _draft() -> issue_agent.IssueAgentDraft:
    return issue_agent.draft_issue_agent_answer(
        issue={
            "id": "issue-1",
            "subject": "Parcel delayed",
            "channel": "email",
            "aiSummary": "Tracking has not changed for three days.",
        },
        messages=[
            {
                "direction": "customer",
                "sender": "customer@example.com",
                "body": "Where is my parcel?",
            }
        ],
        question="What should we answer?",
        articles=_articles(),
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="We need a human to investigate this shipment.",
        fallback_confidence="low",
    )


def test_draft_uses_create_agent_structured_output_and_validated_citation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _patch_agent_dependencies(
        monkeypatch,
        commands=[
            "cat README.md request.json ticket/ticket.json",
            'rg -lF "seven business days" knowledge/articles',
            "cat knowledge/articles/0001--shipping-policy.json",
        ],
        output=KnowledgeAgentOutput(
            answer="Your parcel should arrive within seven business days. Please send the tracking number if it remains delayed.",
            confidence="high",
            citation_ids=["shipping-policy", "shipping-policy"],
            citation_paths=["knowledge/articles/0001--shipping-policy.json"],
            missing_information=[" Tracking number "],
        ),
        captured=captured,
    )

    result = _draft()

    assert result.generation_mode == "knowledge_agent"
    assert result.confidence == "high"
    assert result.citation_ids == ("shipping-policy",)
    assert result.missing_information == ("Tracking number",)
    assert result.error == ""
    assert len(result.tool_calls) == 3
    assert result.tool_calls[-1]["readArticleIds"] == ["shipping-policy"]
    assert captured["name"] == "ticket_knowledge_agent"
    assert captured["middleware"][0].run_limit == issue_agent.KNOWLEDGE_AGENT_MODEL_CALL_LIMIT
    assert captured["middleware"][1].run_limit == issue_agent.KNOWLEDGE_AGENT_TOOL_CALL_LIMIT
    assert captured["model"] is not None
    assert captured["response_format"].schema is KnowledgeAgentOutput
    assert len(captured["middleware"]) == 2


def test_draft_removes_terminal_thank_you_closing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_agent_dependencies(
        monkeypatch,
        commands=["cat README.md request.json ticket/ticket.json"],
        output=KnowledgeAgentOutput(
            answer="The motor claim is ready for lawyer review.\n\nThank you,",
            confidence="medium",
            citation_ids=[],
        ),
    )

    result = _draft()

    assert result.generation_mode == "knowledge_agent"
    assert result.answer == "The motor claim is ready for lawyer review."


def test_draft_real_agent_completes_at_configured_tool_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SequentialToolModel(BaseChatModel):
        calls: int = 0
        commands: list[str]

        @property
        def _llm_type(self) -> str:
            return "sequential-tool-test"

        def bind_tools(
            self,
            _tools: Sequence[Any],
            **_kwargs: Any,
        ) -> SequentialToolModel:
            return self

        def _generate(self, *_args: Any, **_kwargs: Any) -> ChatResult:
            self.calls += 1
            if self.calls <= len(self.commands):
                tool_call = {
                    "name": "knowledge_bash",
                    "args": {"command": self.commands[self.calls - 1]},
                    "id": f"knowledge-bash-{self.calls}",
                    "type": "tool_call",
                }
            else:
                tool_call = {
                    "name": "KnowledgeAgentOutput",
                    "args": {
                        "answer": "Your parcel should arrive within seven business days.",
                        "confidence": "high",
                        "citation_ids": ["shipping-policy"],
                        "citation_paths": ["knowledge/articles/0001--shipping-policy.json"],
                        "missing_information": [],
                    },
                    "id": "knowledge-answer",
                    "type": "tool_call",
                }
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[tool_call]))])

    model = SequentialToolModel(
        commands=[
            "cat README.md request.json ticket/ticket.json ticket/messages.jsonl "
            "ticket/account.json ticket/conversation.json history/agent.jsonl",
            "cat knowledge/index.jsonl",
            'rg -lF "seven business days" knowledge/articles',
            "ls ticket",
            "wc -l knowledge/index.jsonl",
            "cat knowledge/articles/0001--shipping-policy.json",
            "cat knowledge/articles/0002--refund-policy.json",
            "stat request.json",
        ]
    )
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: model)
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    result = _draft()

    assert result.generation_mode == "knowledge_agent"
    assert result.answer == "Your parcel should arrive within seven business days."
    assert result.citation_ids == ("shipping-policy",)
    assert result.error == ""
    assert model.calls == issue_agent.KNOWLEDGE_AGENT_MODEL_CALL_LIMIT
    assert len(result.tool_calls) == issue_agent.KNOWLEDGE_AGENT_TOOL_CALL_LIMIT


def test_draft_rejects_hallucinated_citations_and_downgrades_high_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_agent_dependencies(
        monkeypatch,
        commands=["cat README.md request.json ticket/ticket.json"],
        output=KnowledgeAgentOutput(
            answer="We are reviewing the delay.",
            confidence="high",
            citation_ids=["invented-policy"],
        ),
    )

    result = _draft()

    assert result.generation_mode == "knowledge_agent"
    assert result.citation_ids == ()
    assert result.confidence == "medium"


def test_draft_downgrades_high_confidence_for_unreviewed_citation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    articles = _articles()
    articles[0]["reviewStatus"] = "needs_review"
    articles[0]["freshnessStatus"] = "needs_review"
    articles[0]["needsReview"] = True
    _patch_agent_dependencies(
        monkeypatch,
        commands=[
            "cat README.md request.json ticket/ticket.json",
            "cat knowledge/articles/0001--shipping-policy.json",
        ],
        output=KnowledgeAgentOutput(
            answer="Your parcel should arrive within seven business days.",
            confidence="high",
            citation_ids=["shipping-policy"],
            citation_paths=["knowledge/articles/0001--shipping-policy.json"],
        ),
    )

    result = issue_agent.draft_issue_agent_answer(
        issue={"id": "issue-1", "subject": "Parcel delayed"},
        messages=[],
        question="What should we answer?",
        articles=articles,
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="Human review required.",
        fallback_confidence="low",
    )

    assert result.citation_ids == ("shipping-policy",)
    assert result.confidence == "medium"


def test_automation_draft_uses_structured_selected_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    fake_llm = object()
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(llm_module, "resolve_effective_config", lambda config, _tenant, _project: config)
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: fake_llm)
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeAutomationAgent:
        def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            captured.update(inputs=inputs, config=config)
            return {
                "structured_response": AutomationAnswerOutput(
                    answer="Your parcel should arrive within seven business days.",
                    confidence="high",
                    citation_ids=["shipping-policy", "invented-policy", "shipping-policy"],
                    missing_information=["Tracking number"],
                )
            }

    def fake_create_agent(**kwargs: Any) -> FakeAutomationAgent:
        captured.update(agent_kwargs=kwargs)
        return FakeAutomationAgent()

    monkeypatch.setattr(issue_agent, "create_agent", fake_create_agent)

    result = issue_agent.draft_issue_automation_answer(
        issue={"id": "issue-1", "subject": "Parcel delayed"},
        messages=[],
        question="What should we answer?",
        articles=_articles(),
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="Human review required.",
        fallback_confidence="low",
    )

    assert result.answer == "Your parcel should arrive within seven business days."
    assert result.confidence == "high"
    assert result.generation_mode == "llm"
    assert result.citation_ids == ("shipping-policy",)
    assert result.missing_information == ("Tracking number",)
    assert captured["agent_kwargs"]["tools"] == []
    assert captured["agent_kwargs"]["response_format"].schema is AutomationAnswerOutput
    assert captured["config"]["recursion_limit"] == 6


def test_automation_draft_retries_once_in_latest_customer_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    fake_llm = object()
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(llm_module, "resolve_effective_config", lambda config, _tenant, _project: config)
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: fake_llm)
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeAutomationAgent:
        def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_answer"
            prompts.append(inputs["messages"][0]["content"])
            answer = (
                "Hallo, Ihre Bestellung ist unterwegs. Die Zustellung erfolgt morgen."
                if len(prompts) == 1
                else "Hello, your order is in transit. The estimated delivery is tomorrow."
            )
            return {
                "structured_response": AutomationAnswerOutput(
                    answer=answer,
                    confidence="medium",
                )
            }

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeAutomationAgent())

    result = issue_agent.draft_issue_automation_answer(
        issue={"id": "issue-1", "subject": "Order status"},
        messages=[
            {
                "direction": "customer",
                "body": "Please tell me the current order status and estimated delivery.",
            }
        ],
        question="Prepare the best support answer.",
        articles=[],
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="Human review required.",
        fallback_confidence="low",
    )

    assert len(prompts) == 2
    assert "## Required Reply Language\nEnglish" in prompts[0]
    assert "## Correction Required" in prompts[1]
    assert result.answer.startswith("Hello")
    assert result.generation_mode == "llm"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Please tell me the current status of my order.", "en"),
        ("Bitte sagen Sie mir den Status meiner Bestellung.", "de"),
        ("Bonjour, mon colis est en retard.", "fr"),
        ("Hola, necesito ayuda con mi pedido.", "es"),
        ("Ciao, vorrei sapere lo stato del mio ordine.", "it"),
        ("We have received your request and it is pending review.", "en"),
        ("Wir haben Ihre Anfrage erhalten und prüfen sie.", "de"),
        ("Nous examinons votre demande, qui est en cours.", "fr"),
        ("Estamos revisando su solicitud pendiente.", "es"),
        ("Stiamo esaminando la sua richiesta, che è in sospeso.", "it"),
    ],
)
def test_supported_language_detection_handles_short_support_messages(
    message: str,
    expected: str,
) -> None:
    assert issue_agent._detected_supported_language(message) == expected


def test_latest_customer_language_does_not_use_identity_metadata() -> None:
    messages = [
        {
            "direction": "customer",
            "sender": "Hans Mueller <hans@example.de>",
            "body": "Please help with my current order status.",
        }
    ]

    assert issue_agent._latest_customer_language(messages) == "en"


def _pending_action_obligation_issue(
    *,
    questions: list[str],
    pending: bool = True,
) -> dict[str, Any]:
    concern_id = "concern-b2b-urgent"
    return {
        "id": "issue-b2b-urgent",
        "subject": "P1 B2B SLA incident",
        "aiRuns": [
            {
                "source": "channel:email-main",
                "metadata": {"emailId": "message-b2b-urgent"},
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": concern_id,
                            "matched": True,
                            "intentName": "b2b-sla-urgent",
                            "answerObligations": [
                                {
                                    "obligationId": f"{concern_id}:obligation-{index}",
                                    "question": question,
                                }
                                for index, question in enumerate(questions, start=1)
                            ],
                        }
                    ]
                },
            }
        ],
        "actionExecutions": (
            [
                {
                    "type": "runbook_webhook",
                    "status": "pending",
                    "label": "Open P1 incident ticket",
                    "metadata": {
                        "source": "runbook",
                        "approvalRequired": True,
                        "sourceMessageId": "message-b2b-urgent",
                        "concernId": concern_id,
                        "runbook": "b2b-sla-urgent",
                    },
                    "result": {
                        "proposedAction": {
                            "name": "open_ticket",
                            "label": "Open P1 incident ticket",
                        }
                    },
                }
            ]
            if pending
            else []
        ),
    }


_EXECUTIVE_ESCALATION_PENDING_NOTICE = (
    "Executive escalation is not confirmed. A related next step for your request "
    "remains pending human review."
)


def test_action_state_repair_answers_only_omitted_e09_obligation() -> None:
    issue = _pending_action_obligation_issue(
        questions=[
            "Confirm executive escalation",
            "Guarantee inventory and dispatch",
            "Confirm SLA compensation",
            "State the exact data you need",
        ]
    )
    answer = (
        "We are unable to guarantee inventory and dispatch or confirm SLA "
        "compensation at this time.\n\n"
        "Please provide the affected orders, quantities, campaign deadline, and "
        "operational impact.\n\n"
        "Any requested action that requires human review is pending and is not "
        "confirmed as started or completed."
    )

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=issue,
        messages=[
            {
                "direction": "customer",
                "body": (
                    "Confirm executive escalation, guarantee inventory and dispatch, "
                    "confirm SLA compensation, and state the exact data you need."
                ),
            }
        ],
        answer=answer,
    )

    assert repaired == answer + "\n\n" + _EXECUTIVE_ESCALATION_PENDING_NOTICE
    assert "Inventory and dispatch is not confirmed" not in repaired
    assert "SLA compensation is not confirmed" not in repaired

    ticket = issue_agent._automatic_ticket_context(issue)
    assert issue_agent.check_pending_action_claims(
        answer=repaired,
        runbook_actions=ticket["runbookActions"],
    ).blocked is False


def test_action_state_repair_canonicalizes_live_e09_confirmation_gerunds() -> None:
    issue = _pending_action_obligation_issue(
        questions=[
            "Confirm executive escalation.",
            "Guarantee inventory and dispatch.",
            "Confirm SLA compensation.",
            "State the exact data you need.",
        ]
    )
    answer = (
        "Thank you for reaching out regarding the P1 incident with your 87 blocked "
        "launch orders. Confirming executive escalation, guaranteeing inventory and "
        "dispatch, and confirming SLA compensation are all pending this review. To "
        "help us investigate, please provide the full list of affected orders, exact "
        "quantities, campaign deadline, and operational impact details.\n\n"
        "Any requested action that requires human review is pending and is not "
        "confirmed as started or completed."
    )

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=issue,
        messages=[
            {
                "direction": "customer",
                "body": (
                    "Confirm executive escalation, guarantee inventory and dispatch, "
                    "confirm SLA compensation, and state the exact data you need."
                ),
            }
        ],
        answer=answer,
    )

    assert repaired == (
        answer
        + "\n\n"
        + _EXECUTIVE_ESCALATION_PENDING_NOTICE
        + "\n\nSLA compensation is not confirmed. A related next step for your "
        "request remains pending human review."
    )
    assert "Inventory and dispatch is not confirmed" not in repaired
    ticket = issue_agent._automatic_ticket_context(issue)
    assert issue_agent.check_pending_action_claims(
        answer=repaired,
        runbook_actions=ticket["runbookActions"],
    ).blocked is False


@pytest.mark.parametrize(
    "answer",
    [
        "Confirming executive escalation is complete.",
        "Confirming executive escalation has been completed.",
        "Confirming executive escalation was successful.",
        "Confirming executive escalation is no longer pending.",
    ],
)
def test_action_state_repair_removes_positive_confirmation_gerund(
    answer: str,
) -> None:
    issue = _pending_action_obligation_issue(
        questions=["Confirm executive escalation."]
    )

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=issue,
        messages=[{"direction": "customer", "body": "Confirm executive escalation."}],
        answer=answer,
    )

    assert answer not in repaired
    assert _EXECUTIVE_ESCALATION_PENDING_NOTICE in repaired
    ticket = issue_agent._automatic_ticket_context(issue)
    assert issue_agent.check_pending_action_claims(
        answer=repaired,
        runbook_actions=ticket["runbookActions"],
    ).blocked is False


def test_action_state_repair_does_not_duplicate_safe_negative_paraphrase() -> None:
    answer = (
        "We cannot confirm executive escalation. A policy note explains that "
        "confirming executive escalation remains pending human review."
    )

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=_pending_action_obligation_issue(
            questions=["Confirm executive escalation."]
        ),
        messages=[{"direction": "customer", "body": "Confirm executive escalation."}],
        answer=answer,
    )

    assert repaired == answer


@pytest.mark.parametrize(
    "answer",
    [
        "Confirming executive escalation, but SLA compensation remains pending.",
        "Confirming executive escalation; inventory approval remains pending.",
        "Confirming executive escalation is pending, but it is actually complete.",
        "Confirming executive escalation remains pending, though it was actually completed.",
        "Confirming executive escalation is pending; it is actually complete.",
        "Confirming executive escalation remains pending. It is actually complete.",
        "Confirming executive escalation remains pending. It is definitely complete.",
        "Confirming executive escalation remains pending. It definitely is complete.",
        "Confirming executive escalation remains pending. This has in fact been completed.",
        "Confirming executive escalation remains pending. It is not pending; it is complete.",
        "Confirming executive escalation remains pending. It is complete, if that helps.",
        "Confirming executive escalation remains pending. This is not merely reviewed; it is confirmed.",
    ],
)
def test_action_state_repair_does_not_borrow_unrelated_pending_clause(
    answer: str,
) -> None:
    issue = _pending_action_obligation_issue(
        questions=["Confirm executive escalation."]
    )

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=issue,
        messages=[{"direction": "customer", "body": "Confirm executive escalation."}],
        answer=answer,
    )

    assert answer not in repaired
    assert _EXECUTIVE_ESCALATION_PENDING_NOTICE in repaired
    ticket = issue_agent._automatic_ticket_context(issue)
    assert issue_agent.check_pending_action_claims(
        answer=repaired,
        runbook_actions=ticket["runbookActions"],
    ).blocked is False


def test_action_state_repair_is_noop_when_subject_is_already_answered() -> None:
    answer = _EXECUTIVE_ESCALATION_PENDING_NOTICE

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=_pending_action_obligation_issue(
            questions=["Confirm executive escalation"]
        ),
        messages=[{"direction": "customer", "body": "Confirm executive escalation."}],
        answer=answer,
    )

    assert repaired == answer


def test_action_state_repair_is_noop_without_pending_human_action() -> None:
    answer = "We have received your request."

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=_pending_action_obligation_issue(
            questions=["Confirm executive escalation"],
            pending=False,
        ),
        messages=[{"direction": "customer", "body": "Confirm executive escalation."}],
        answer=answer,
    )

    assert repaired == answer


def test_action_state_repair_ignores_unscoped_pending_triage() -> None:
    issue = _pending_action_obligation_issue(
        questions=["Confirm executive escalation"]
    )
    action = issue["actionExecutions"][0]
    action["type"] = "agent_triage"
    action["metadata"]["source"] = "agent_triage"
    action["metadata"].pop("concernId")
    action["metadata"]["automationContext"] = {
        "messageId": "message-b2b-urgent"
    }
    answer = "We have received the P1 incident report."

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=issue,
        messages=[{"direction": "customer", "body": "Confirm executive escalation."}],
        answer=answer,
    )

    assert repaired == answer


def test_action_state_repair_preserves_topic_only_policy_mention() -> None:
    answer = "Our executive escalation criteria apply to P1 incidents."

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=_pending_action_obligation_issue(
            questions=["Confirm executive escalation"]
        ),
        messages=[{"direction": "customer", "body": "Confirm executive escalation."}],
        answer=answer,
    )

    assert repaired == answer


def test_action_state_repair_preserves_positive_topic_answer_byte_for_byte() -> None:
    answer = "Shipment status is in transit."

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=_pending_action_obligation_issue(
            questions=["Confirm shipment status"]
        ),
        messages=[{"direction": "customer", "body": "Confirm shipment status."}],
        answer=answer,
    )

    assert repaired == answer


@pytest.mark.parametrize(
    "question",
    [
        "Confirm you have escalated it",
        "Confirm you escalated it",
        "Confirm it changed",
    ],
)
def test_action_state_repair_ignores_pronoun_only_confirmation_clause(
    question: str,
) -> None:
    answer = "We have received your escalation request."

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=_pending_action_obligation_issue(
            questions=[question]
        ),
        messages=[
            {
                "direction": "customer",
                "body": question + ".",
            }
        ],
        answer=answer,
    )

    assert repaired == answer
    assert "Escalated it is not confirmed" not in repaired
    assert "It changed is not confirmed" not in repaired


def test_action_state_repair_does_not_cross_concern_boundaries() -> None:
    issue = _pending_action_obligation_issue(
        questions=["Confirm executive escalation"]
    )
    issue["aiRuns"][0]["intentResult"]["concerns"].append(
        {
            "concernId": "concern-refund",
            "matched": True,
            "intentName": "refund-request",
            "answerObligations": [
                {
                    "obligationId": "concern-refund:obligation-1",
                    "question": "Confirm refund authorization",
                }
            ],
        }
    )
    answer = _EXECUTIVE_ESCALATION_PENDING_NOTICE

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=issue,
        messages=[
            {
                "direction": "customer",
                "body": "Confirm executive escalation and refund authorization.",
            }
        ],
        answer=answer,
    )

    assert repaired == answer


def test_action_state_repair_localizes_missing_obligation_notice() -> None:
    answer = "Wir benötigen dafür eine menschliche Prüfung."

    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=_pending_action_obligation_issue(
            questions=["Bestätigen Sie die Eskalation an die Geschäftsleitung"]
        ),
        messages=[
            {
                "direction": "customer",
                "body": (
                    "Bitte bestätigen Sie die Eskalation an die Geschäftsleitung. "
                    "Vielen Dank für Ihre Hilfe mit dieser Anfrage."
                ),
            }
        ],
        answer=answer,
    )

    assert repaired == (
        answer
        + "\n\nFür die Eskalation an die Geschäftsleitung liegt keine Bestätigung "
        "vor. Ein damit verbundener nächster Schritt für Ihre Anfrage wartet "
        "weiterhin auf menschliche Prüfung."
    )
    ticket = issue_agent._automatic_ticket_context(
        _pending_action_obligation_issue(
            questions=["Bestätigen Sie die Eskalation an die Geschäftsleitung"]
        )
    )
    assert issue_agent.check_pending_action_claims(
        answer=repaired,
        runbook_actions=ticket["runbookActions"],
    ).blocked is False


def test_automation_draft_retries_once_for_pending_action_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(llm_module, "resolve_effective_config", lambda config, _tenant, _project: config)
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeAutomationAgent:
        def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_answer"
            prompts.append(inputs["messages"][0]["content"])
            answer = (
                "We have opened a delivery investigation."
                if len(prompts) == 1
                else "The investigation is pending approval. We can open it after review."
            )
            return {
                "structured_response": AutomationAnswerOutput(
                    answer=answer,
                    confidence="medium",
                    covered_concern_ids=["delivery"],
                )
            }

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeAutomationAgent())
    issue = {
        "id": "issue-1",
        "subject": "Missing parcel",
        "aiRuns": [
            {
                "source": "channel:email-main",
                "metadata": {"emailId": "message1"},
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "delivery",
                            "matched": True,
                            "intentName": "delivery-investigation",
                        }
                    ]
                },
            }
        ],
        "actionExecutions": [
            {
                "type": "runbook_webhook",
                "status": "pending",
                "label": "Open delivery investigation",
                "metadata": {
                    "source": "runbook",
                    "approvalRequired": True,
                    "sourceMessageId": "message1",
                    "concernId": "delivery",
                    "runbook": "delivery-investigation",
                },
                "result": {
                    "proposedAction": {
                        "name": "open_ticket",
                        "label": "Open delivery investigation",
                    }
                },
            }
        ],
    }

    result = issue_agent.draft_issue_automation_answer(
        issue=issue,
        messages=[{"direction": "customer", "body": "Please investigate my missing parcel."}],
        question="Prepare the best support answer.",
        articles=[],
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="Human review required.",
        fallback_confidence="low",
    )

    assert len(prompts) == 2
    assert "pending business action" in prompts[1]
    assert result.answer == "The investigation is pending approval. We can open it after review."
    assert issue_agent.check_pending_action_claims(
        answer=result.answer,
        runbook_actions=[{"label": "Open delivery investigation", "status": "pending_approval"}],
    ).blocked is False


def test_automation_draft_accepts_exact_readonly_tracking_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    answer = (
        "I've checked tracking for UPS1Z999AA10123456784, and it is in transit."
    )
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeAutomationAgent:
        def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_answer"
            prompts.append(inputs["messages"][0]["content"])
            return {
                "structured_response": AutomationAnswerOutput(
                    answer=answer,
                    confidence="high",
                    covered_concern_ids=["shipment-status"],
                )
            }

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeAutomationAgent())

    result = issue_agent.draft_issue_automation_answer(
        issue=_shipment_tool_issue_with_pending_actions(),
        messages=[
            {
                "direction": "customer",
                "body": "Where is UPS1Z999AA10123456784?",
            }
        ],
        question="Prepare the best support answer.",
        articles=[],
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="Human review required.",
        fallback_confidence="low",
    )

    assert len(prompts) == 1
    assert result.answer == answer
    assert result.generation_mode == "llm"


def test_automation_draft_retries_once_for_mutated_business_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    expected_tracking = "UPS1Z999AA10123456784"
    mutated_tracking = "UPS1Z999AA10123456785"
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(llm_module, "resolve_effective_config", lambda config, _tenant, _project: config)
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeAutomationAgent:
        def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_answer"
            prompts.append(inputs["messages"][0]["content"])
            tracking = mutated_tracking if len(prompts) == 1 else expected_tracking
            return {
                "structured_response": AutomationAnswerOutput(
                    answer=f"Tracking {tracking} is in transit.",
                    confidence="medium",
                )
            }

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeAutomationAgent())

    result = issue_agent.draft_issue_automation_answer(
        issue={"id": "issue-1", "subject": "Shipment status"},
        messages=[
            {
                "direction": "customer",
                "body": f"Where is shipment {expected_tracking}?",
            }
        ],
        question="Prepare the best support answer.",
        articles=[],
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="Human review required.",
        fallback_confidence="low",
    )

    assert len(prompts) == 2
    assert "unsupported business identifiers" in prompts[1]
    assert mutated_tracking in prompts[1]
    assert expected_tracking in prompts[1]
    assert result.answer == f"Tracking {expected_tracking} is in transit."
    assert result.generation_mode == "llm"


def test_business_identifier_sources_are_exact_and_exclude_dates_and_plain_numbers() -> None:
    identifiers = issue_agent._allowed_business_identifiers(
        messages=[
            {
                "direction": "customer",
                "body": "On 2026-07-17, check UPS1Z999AA10123456784 and number 1234567890.",
            }
        ],
        ticket={
            "toolEvidence": [
                {
                    "name": "lookup-zf-e2e-shipment",
                    "status": "success",
                    "evidenceId": "tool:lookup-zf-e2e-shipment",
                    "responseFacts": {"order": "ZF-20991"},
                }
            ]
        },
        articles=[
            {
                "id": "shipping-policy",
                "body": "Carrier reference DHL00340434292135100123 is authoritative for this test.",
            }
        ],
    )

    assert identifiers == (
        "UPS1Z999AA10123456784",
        "ZF-20991",
        "DHL00340434292135100123",
    )
    assert issue_agent._business_identifiers(
        "2026-07-17 1234567890 ordinary words 24-hours"
    ) == ()


def test_automatic_context_omits_current_workflow_state_but_binds_related_tickets() -> None:
    conversation = {
        "key": "email:thread-1",
        "currentIssueId": "issue-1",
        "tickets": [
            {"id": "issue-1", "subject": "Current", "status": "open", "needsResponse": True},
            {"id": "issue-2", "subject": "Related", "status": "open", "needsResponse": True},
        ],
    }

    ticket_context = issue_agent._automatic_ticket_context({"id": "issue-1", "subject": "Current", "status": "open"})
    conversation_context = issue_agent._automatic_conversation_context(conversation)
    open_snapshots = issue_agent.grounding_context_snapshots(
        issue={"id": "issue-1", "subject": "Current", "status": "open"},
        messages=[],
        conversation_context=conversation,
    )
    current_ongoing_snapshots = issue_agent.grounding_context_snapshots(
        issue={"id": "issue-1", "subject": "Current", "status": "ongoing"},
        messages=[],
        conversation_context={
            **conversation,
            "tickets": [
                {"id": "issue-1", "subject": "Current", "status": "ongoing", "needsResponse": False},
                conversation["tickets"][1],
            ],
        },
    )
    related_done_snapshots = issue_agent.grounding_context_snapshots(
        issue={"id": "issue-1", "subject": "Current", "status": "ongoing"},
        messages=[],
        conversation_context={
            **conversation,
            "tickets": [
                conversation["tickets"][0],
                {"id": "issue-2", "subject": "Related", "status": "done", "needsResponse": False},
            ],
        },
    )

    assert "status" not in ticket_context
    assert "status" not in conversation_context["tickets"][0]
    assert "needsResponse" not in conversation_context["tickets"][0]
    assert conversation_context["tickets"][1]["status"] == "open"
    assert conversation_context["tickets"][1]["needsResponse"] is True
    assert current_ongoing_snapshots == open_snapshots
    assert related_done_snapshots != open_snapshots


def _issue_with_grounding_obligations(
    *,
    concern_id: str,
    questions: list[tuple[str, str]],
    tool_evidence: list[dict[str, Any]] | None = None,
    action_executions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {}
    if tool_evidence:
        outcome["toolEvidence"] = tool_evidence
    issue: dict[str, Any] = {
        "id": "issue-obligations",
        "subject": "Grounding obligation regression",
        "aiRuns": [
            {
                "source": "channel:email-main",
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": concern_id,
                            "matched": True,
                            "intentName": "grounding-regression",
                            "answerObligations": [
                                {
                                    "obligationId": obligation_id,
                                    "question": question,
                                }
                                for obligation_id, question in questions
                            ],
                            "outcome": outcome,
                        }
                    ]
                },
            }
        ],
    }
    if action_executions:
        issue["actionExecutions"] = action_executions
    return issue


def _assess_with_grounding_output(
    monkeypatch: pytest.MonkeyPatch,
    *,
    issue: dict[str, Any],
    answer: str,
    resolutions: list[tuple[str, str, list[str]]],
    unit_evidence_ids: list[str] | None = None,
    verdict: str | None = None,
) -> tuple[issue_agent.AutomationGroundingAssessment, str]:
    answer_units = issue_agent._grounding_answer_units(answer)
    evidence_ids = unit_evidence_ids or ["ticket"]
    output = AutomationGroundingOutput(
        verdict=verdict or (
            "not_grounded"
            if any(resolution == "not_covered" for _, resolution, _ in resolutions)
            else "grounded"
        ),
        answer_sha256=issue_agent.grounding_text_sha256(answer),
        unit_assessments=[
            AutomationGroundingUnitAssessment(
                unit_id=unit["id"],
                unit_sha256=unit["sha256"],
                supported=True,
                evidence_ids=evidence_ids,
            )
            for unit in answer_units
        ],
        obligation_assessments=[
            AutomationGroundingObligationAssessment(
                obligation_id=obligation_id,
                resolution=resolution,
                answer_unit_ids=answer_unit_ids,
            )
            for obligation_id, resolution, answer_unit_ids in resolutions
        ],
    )
    prompts: list[str] = []
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(
        usage_module,
        "record_usage_from_result",
        lambda *_args, **_kwargs: None,
    )

    class FakeGroundingAgent:
        def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            prompts.append(inputs["messages"][0]["content"])
            return {"structured_response": output}

    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: FakeGroundingAgent(),
    )
    result = issue_agent.assess_issue_automation_grounding(
        issue=issue,
        messages=[],
        answer=answer,
        articles=[],
        tenant_id="tenant-1",
        project_id="project-1",
    )
    return result, prompts[0]


def _assess_with_grounding_outputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    issue: dict[str, Any],
    answer: str,
    outputs: list[AutomationGroundingOutput],
    articles: list[dict[str, Any]] | None = None,
) -> tuple[issue_agent.AutomationGroundingAssessment, list[str]]:
    prompts: list[str] = []
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(
        usage_module,
        "record_usage_from_result",
        lambda *_args, **_kwargs: None,
    )

    class FakeGroundingAgent:
        def invoke(
            self,
            inputs: dict[str, Any],
            *,
            config: dict[str, Any],
        ) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            prompts.append(inputs["messages"][0]["content"])
            return {"structured_response": outputs[len(prompts) - 1]}

    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: FakeGroundingAgent(),
    )
    result = issue_agent.assess_issue_automation_grounding(
        issue=issue,
        messages=[],
        answer=answer,
        articles=articles or [],
        tenant_id="tenant-1",
        project_id="project-1",
    )
    return result, prompts


def test_repaired_e09_notice_is_hashed_and_grounded_to_its_concern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concern_id = "concern-b2b-urgent"
    obligation_id = f"{concern_id}:obligation-1"
    evidence_id = f"concern:{concern_id}"
    issue = _pending_action_obligation_issue(
        questions=["Confirm executive escalation"]
    )
    repaired = issue_agent.repair_issue_automation_answer_action_state(
        issue=issue,
        messages=[{"direction": "customer", "body": "Confirm executive escalation."}],
        answer="",
    )
    answer_units = issue_agent._grounding_answer_units(repaired)

    result, prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer=repaired,
        resolutions=[
            (
                obligation_id,
                "pending_or_unavailable",
                [answer_units[0]["id"]],
            )
        ],
        unit_evidence_ids=[evidence_id],
    )

    assert repaired == _EXECUTIVE_ESCALATION_PENDING_NOTICE
    assert len(answer_units) == 2
    assert result.verified is True
    assert result.answer_sha256 == issue_agent.grounding_text_sha256(repaired)
    assert result.obligation_assessments[0]["resolution"] == "pending_or_unavailable"
    assert result.obligation_assessments[0]["covered"] is True
    assert all(
        assessment["evidenceIds"] == [evidence_id]
        for assessment in result.unit_assessments
    )
    assert any(
        snapshot["id"] == "ticket:scoped"
        for snapshot in result.context_snapshots
    )
    assert evidence_id in prompt


def test_automation_draft_requires_independent_grounding_for_auto_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeLlm:
        _mantly_usage_context = {"provider": "test", "model": "grounding-model"}

    fake_llm = FakeLlm()
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(llm_module, "resolve_effective_config", lambda config, _tenant, _project: config)

    def fake_create_llm(*_args: Any, **kwargs: Any) -> FakeLlm:
        captured["llm_kwargs"] = kwargs
        return fake_llm

    monkeypatch.setattr(llm_module, "create_llm", fake_create_llm)
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeGroundingAgent:
        def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            answer = "Your parcel should arrive within seven business days."
            assert answer in inputs["messages"][0]["content"]
            return {
                "structured_response": AutomationGroundingOutput(
                    verdict="grounded",
                    answer_sha256=issue_agent.grounding_text_sha256(answer),
                    checked_citation_ids=["shipping-policy"],
                    unit_assessments=[
                        AutomationGroundingUnitAssessment(
                            unit_id="u001",
                            unit_sha256=issue_agent.grounding_text_sha256(answer),
                            supported=True,
                            evidence_ids=["shipping-policy"],
                        )
                    ],
                    contradictions=[],
                )
            }

    def fake_create_agent(**kwargs: Any) -> FakeGroundingAgent:
        captured["agent_kwargs"] = kwargs
        return FakeGroundingAgent()

    monkeypatch.setattr(issue_agent, "create_agent", fake_create_agent)

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1", "subject": "Parcel delayed"},
        messages=[],
        answer="Your parcel should arrive within seven business days.",
        articles=[_articles()[0]],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert captured["llm_kwargs"] == {"timeout": 30, "max_retries": 0, "temperature": 0}
    assert captured["agent_kwargs"]["tools"] == []
    assert captured["agent_kwargs"]["response_format"].schema is AutomationGroundingOutput
    assert captured["agent_kwargs"]["middleware"][0].run_limit == 1
    assert result.verified is True
    assert result.status == "passed"
    assert result.provider == "test"
    assert result.model == "grounding-model"
    assert result.answer_sha256 == issue_agent.grounding_text_sha256(
        "Your parcel should arrive within seven business days."
    )
    assert result.answer_units[0]["id"] == "u001"
    assert result.evidence_snapshots[0]["bodySha256"]
    assert result.evidence_snapshots[0]["evidenceSha256"]


@pytest.mark.parametrize(
    ("model_evidence_id", "expected_verified"),
    [
        ("tool:shipment-status:lookup-zf-e2e-shipment", True),
        ("tool:shipment-status:lookup-zf-e2e-shipmen", False),
    ],
)
def test_grounding_accepts_only_exact_ticket_tool_evidence_ids(
    monkeypatch: pytest.MonkeyPatch,
    model_evidence_id: str,
    expected_verified: bool,
) -> None:
    answer = "Shipment UPS1Z999AA10123456784 is in transit."
    prompts: list[str] = []
    issue = _shipment_tool_issue()
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeGroundingAgent:
        def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            prompts.append(inputs["messages"][0]["content"])
            return {
                "structured_response": AutomationGroundingOutput(
                    verdict="grounded",
                    answer_sha256=issue_agent.grounding_text_sha256(answer),
                    unit_assessments=[
                        AutomationGroundingUnitAssessment(
                            unit_id="u001",
                            unit_sha256=issue_agent.grounding_text_sha256(answer),
                            supported=True,
                            evidence_ids=[model_evidence_id],
                        )
                    ],
                )
            }

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeGroundingAgent())

    result = issue_agent.assess_issue_automation_grounding(
        issue=issue,
        messages=[
            {
                "direction": "customer",
                "body": "Where is UPS1Z999AA10123456784?",
            }
        ],
        answer=answer,
        articles=[],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert '"tool:shipment-status:lookup-zf-e2e-shipment"' in prompts[0]
    assert result.verified is expected_verified
    if expected_verified:
        assert result.status == "passed"
    else:
        assert result.status == "error"
        assert "unknown evidence IDs" in result.error


def test_grounding_allows_proven_tracking_check_with_unrelated_pending_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = (
        "I've checked tracking for UPS1Z999AA10123456784, and it is in transit."
    )
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeGroundingAgent:
        def invoke(self, _inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            return {
                "structured_response": AutomationGroundingOutput(
                    verdict="grounded",
                    answer_sha256=issue_agent.grounding_text_sha256(answer),
                    unit_assessments=[
                        AutomationGroundingUnitAssessment(
                            unit_id="u001",
                            unit_sha256=issue_agent.grounding_text_sha256(answer),
                            supported=True,
                            evidence_ids=["tool:shipment-status:lookup-zf-e2e-shipment"],
                        )
                    ],
                )
            }

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeGroundingAgent())

    result = issue_agent.assess_issue_automation_grounding(
        issue=_shipment_tool_issue_with_pending_actions(),
        messages=[
            {
                "direction": "customer",
                "body": "Where is UPS1Z999AA10123456784?",
            }
        ],
        answer=answer,
        articles=[],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert result.verified is True
    assert result.status == "passed"
    assert result.pending_action_claims == ()


def test_grounding_blocks_tracking_check_with_mismatched_evidence_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = "I've checked tracking for UPS1Z999AA10123456785."
    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: pytest.fail("grounding LLM must not run"),
    )

    result = issue_agent.assess_issue_automation_grounding(
        issue=_shipment_tool_issue_with_pending_actions(),
        messages=[
            {
                "direction": "customer",
                "body": "Where is UPS1Z999AA10123456784?",
            }
        ],
        answer=answer,
        articles=[],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert result.verified is False
    assert result.reason_code == "pending_action_claim"
    assert result.pending_action_claims == (answer,)


def test_grounding_preflight_rejects_mutated_business_identifier_without_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_tracking = "UPS1Z999AA10123456784"
    mutated_tracking = "UPS1Z999AA10123456785"

    def fail_create_agent(**_kwargs: Any) -> Any:
        raise AssertionError("grounding model must not run")

    monkeypatch.setattr(issue_agent, "create_agent", fail_create_agent)

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1", "subject": "Shipment status"},
        messages=[
            {
                "direction": "customer",
                "body": f"Where is shipment {expected_tracking}?",
            }
        ],
        answer=f"Shipment {mutated_tracking} is in transit.",
        articles=[],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert result.verified is False
    assert result.status == "failed"
    assert result.reason_code == issue_agent.BUSINESS_IDENTIFIER_MISMATCH_REASON_CODE
    assert result.unsupported_claims == (mutated_tracking,)
    assert mutated_tracking in result.error


@pytest.mark.parametrize(
    ("output", "expected_status", "expected_reason"),
    [
        (
            AutomationGroundingOutput(
                verdict="not_grounded",
                answer_sha256=issue_agent.grounding_text_sha256("A refund has already been issued."),
                checked_citation_ids=["shipping-policy"],
                unit_assessments=[
                    AutomationGroundingUnitAssessment(
                        unit_id="u001",
                        unit_sha256=issue_agent.grounding_text_sha256("A refund has already been issued."),
                        supported=False,
                        evidence_ids=[],
                    )
                ],
                contradictions=[],
            ),
            "failed",
            "ungrounded_answer",
        ),
        (
            AutomationGroundingOutput(
                verdict="grounded",
                answer_sha256=issue_agent.grounding_text_sha256("A refund has already been issued."),
                checked_citation_ids=["shipping-policy"],
                unit_assessments=[
                    AutomationGroundingUnitAssessment(
                        unit_id="u001",
                        unit_sha256=issue_agent.grounding_text_sha256("A refund has already been issued."),
                        supported=True,
                        evidence_ids=["invented-evidence"],
                    )
                ],
                contradictions=[],
            ),
            "error",
            "grounding_check_failed",
        ),
    ],
)
def test_grounding_gate_fails_closed_for_unsupported_or_unknown_evidence(
    monkeypatch: pytest.MonkeyPatch,
    output: AutomationGroundingOutput,
    expected_status: str,
    expected_reason: str,
) -> None:
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(llm_module, "resolve_effective_config", lambda config, _tenant, _project: config)
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeGroundingAgent:
        def invoke(self, _inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            return {"structured_response": output}

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeGroundingAgent())

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1", "subject": "Parcel delayed"},
        messages=[],
        answer="A refund has already been issued.",
        articles=[_articles()[0]],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert result.verified is False
    assert result.status == expected_status
    assert result.reason_code == expected_reason


def test_grounding_answer_units_cover_every_non_whitespace_character() -> None:
    answer = f"First supported sentence. Second supported sentence!\nLong policy detail {'x' * 620}"

    units = issue_agent._grounding_answer_units(answer)

    assert len(units) == 4
    assert [unit["id"] for unit in units] == ["u001", "u002", "u003", "u004"]
    assert all(len(unit["text"]) <= issue_agent._GROUNDING_MAX_UNIT_CHARS for unit in units)
    assert all(unit["sha256"] == issue_agent.grounding_text_sha256(unit["text"]) for unit in units)
    covered = {index for unit in units for index in range(unit["start"], unit["end"])}
    assert all(character.isspace() or index in covered for index, character in enumerate(answer))


def test_grounding_gate_rejects_supported_answer_that_omits_one_customer_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = "The delayed parcel should arrive within seven business days."
    answer_hash = issue_agent.grounding_text_sha256(answer)
    issue = {
        "id": "issue-1",
        "subject": "Delivery and address change",
        "aiRuns": [
            {
                "source": "channel:email-main",
                "intentResult": {
                    "concerns": [
                        {
                            "concernId": "delivery",
                            "matched": True,
                            "intentName": "delivery-status",
                            "answerObligations": [
                                {
                                    "obligationId": "delivery:arrival",
                                    "question": "When will the delayed parcel arrive?",
                                },
                                {
                                    "obligationId": "delivery:address",
                                    "question": "Can the delivery address be changed?",
                                },
                            ],
                        }
                    ]
                },
            }
        ],
    }
    output = AutomationGroundingOutput(
        verdict="not_grounded",
        answer_sha256=answer_hash,
        checked_citation_ids=["shipping-policy"],
        unit_assessments=[
            AutomationGroundingUnitAssessment(
                unit_id="u001",
                unit_sha256=answer_hash,
                supported=True,
                evidence_ids=["shipping-policy"],
            )
        ],
        obligation_assessments=[
            AutomationGroundingObligationAssessment(
                obligation_id="delivery:arrival",
                resolution="answered",
                answer_unit_ids=["u001"],
            ),
            AutomationGroundingObligationAssessment(
                obligation_id="delivery:address",
                resolution="not_covered",
                answer_unit_ids=[],
            ),
        ],
        contradictions=[],
    )
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeGroundingAgent:
        def invoke(self, _inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            return {"structured_response": output}

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeGroundingAgent())

    result = issue_agent.assess_issue_automation_grounding(
        issue=issue,
        messages=[],
        answer=answer,
        articles=[_articles()[0]],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert result.verified is False
    assert result.status == "failed"
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == ("Can the delivery address be changed?",)
    assert result.obligation_assessments == (
        {
            "obligationId": "delivery:arrival",
            "resolution": "answered",
            "covered": True,
            "answerUnitIds": ["u001"],
        },
        {
            "obligationId": "delivery:address",
            "resolution": "not_covered",
            "covered": False,
            "answerUnitIds": [],
        },
    )


def test_grounding_r11_c06_discuss_later_does_not_cover_three_gmbh_obligations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    questions = [
        ("gmbh:steps", "Outline the preliminary formation steps."),
        ("gmbh:documents", "Outline the typical formation documents."),
        ("gmbh:capital", "Outline the capital requirement."),
    ]
    issue = _issue_with_grounding_obligations(
        concern_id="gmbh-formation",
        questions=questions,
    )
    answer = (
        "During this consultation, we can discuss the preliminary formation steps, "
        "typical documents, and capital requirements relevant to your situation."
    )

    result, _prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (obligation_id, "not_covered", ["u001"])
            for obligation_id, _question in questions
        ],
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == tuple(question for _, question in questions)
    assert [item["resolution"] for item in result.obligation_assessments] == [
        "not_covered",
        "not_covered",
        "not_covered",
    ]
    assert all(item["covered"] is False for item in result.obligation_assessments)


def test_grounding_r10_c09_intake_and_assess_later_does_not_cover_rescheduling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    questions = [
        ("reschedule:process", "What is the rescheduling process?"),
        ("reschedule:availability", "What consultation slots are available?"),
    ]
    issue = _issue_with_grounding_obligations(
        concern_id="reschedule-consultation",
        questions=questions,
    )
    answer = (
        "Please send your preferred dates and we can assess rescheduling and "
        "availability during a later consultation."
    )

    result, _prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            (obligation_id, "not_covered", ["u001"])
            for obligation_id, _question in questions
        ],
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == tuple(question for _, question in questions)


def test_grounding_r10_c02_intake_prerequisites_do_not_cover_run_conflict_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = _issue_with_grounding_obligations(
        concern_id="conflict-check",
        questions=[("conflict:run", "Run the conflict check.")],
    )
    answer = (
        "Please send the full legal names of the client, counterparties, and related "
        "entities so that a conflict check can be performed later."
    )

    result, _prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[("conflict:run", "not_covered", ["u001"])],
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == ("Run the conflict check.",)
    assert result.obligation_assessments[0]["covered"] is False


def test_grounding_explicit_pending_state_with_next_step_addresses_obligation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = _issue_with_grounding_obligations(
        concern_id="conflict-check",
        questions=[("conflict:run", "Run the conflict check.")],
    )
    answer = (
        "The conflict check has not run; it is pending human review. "
        "Next, our conflicts team will review the submitted names."
    )
    answer_unit_ids = [
        unit["id"] for unit in issue_agent._grounding_answer_units(answer)
    ]

    result, _prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[
            ("conflict:run", "pending_or_unavailable", answer_unit_ids)
        ],
    )

    assert result.verified is True
    assert result.uncovered_obligations == ()
    assert result.obligation_assessments == (
        {
            "obligationId": "conflict:run",
            "resolution": "pending_or_unavailable",
            "covered": True,
            "answerUnitIds": answer_unit_ids,
        },
    )


@pytest.mark.parametrize(
    ("evidence_id", "expected_verified", "expected_resolution"),
    [
        ("action:execution-conflict", True, "fulfilled_action"),
        ("tool:conflict-check:conflict-check-tool", True, "fulfilled_action"),
        ("ticket", False, "not_covered"),
        ("tool:other-concern:conflict-check-tool", False, "not_covered"),
    ],
)
def test_grounding_fulfilled_action_requires_exact_success_evidence_from_same_concern(
    monkeypatch: pytest.MonkeyPatch,
    evidence_id: str,
    expected_verified: bool,
    expected_resolution: str,
) -> None:
    issue = _issue_with_grounding_obligations(
        concern_id="conflict-check",
        questions=[("conflict:run", "Run the conflict check.")],
        tool_evidence=[
            {
                "name": "conflict-check-tool",
                "status": "success",
                "responseFacts": {"status": "clear"},
            }
        ],
        action_executions=[
            {
                "id": "execution-conflict",
                "type": "runbook_webhook",
                "status": "success",
                "completedAt": "2026-07-18T10:00:00Z",
                "metadata": {
                    "source": "runbook",
                    "concernId": "conflict-check",
                },
                "result": {
                    "proposedAction": {
                        "name": "run_conflict_check",
                        "label": "Run conflict check",
                    },
                    "application": {
                        "applied": True,
                        "webhookResult": {
                            "status": "ok",
                            "response": {"status": "clear"},
                        },
                    },
                },
            }
        ],
    )
    issue["aiRuns"][0]["intentResult"]["concerns"].append(
        {
            "concernId": "other-concern",
            "matched": True,
            "intentName": "other-runbook",
            "outcome": {
                "toolEvidence": [
                    {
                        "name": "conflict-check-tool",
                        "status": "success",
                        "responseFacts": {"status": "complete"},
                    }
                ]
            },
        }
    )
    answer = "The conflict check is complete."

    result, prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[("conflict:run", "fulfilled_action", ["u001"])],
        unit_evidence_ids=[evidence_id],
    )

    assert '"action:execution-conflict"' in prompt
    assert result.verified is expected_verified
    assert result.obligation_assessments[0]["resolution"] == expected_resolution
    assert result.obligation_assessments[0]["covered"] is expected_verified
    if expected_verified:
        assert result.uncovered_obligations == ()
    else:
        assert result.reason_code == "incomplete_answer"
        assert result.uncovered_obligations == ("Run the conflict check.",)


def _two_concern_shared_tool_grounding_issue() -> dict[str, Any]:
    issue = _issue_with_grounding_obligations(
        concern_id="first-concern",
        questions=[("first:status", "What is the first concern status?")],
        tool_evidence=[
            {
                "name": "shared-status",
                "status": "success",
                "responseFacts": {"status": "inactive"},
            }
        ],
    )
    issue["aiRuns"][0]["intentResult"]["concerns"].append(
        {
            "concernId": "second-concern",
            "matched": True,
            "intentName": "second-runbook",
            "outcome": {
                "toolEvidence": [
                    {
                        "name": "shared-status",
                        "status": "success",
                        "responseFacts": {"status": "active"},
                    }
                ]
            },
        }
    )
    return issue


def test_grounding_filters_mixed_unit_evidence_per_obligation_concern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = _two_concern_shared_tool_grounding_issue()

    result, _prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer="The first concern status is inactive.",
        resolutions=[("first:status", "answered", ["u001"])],
        unit_evidence_ids=[
            "tool:first-concern:shared-status",
            "tool:second-concern:shared-status",
        ],
    )

    assert result.verified is True
    assert result.obligation_assessments[0]["resolution"] == "answered"


@pytest.mark.parametrize(
    ("obligation_evidence_ids", "expected_verified"),
    [
        (["tool:second-concern:shared-status"], False),
        (
            [
                "tool:first-concern:shared-status",
                "tool:second-concern:shared-status",
            ],
            True,
        ),
    ],
)
def test_grounding_filters_explicit_foreign_obligation_evidence_from_mixed_unit(
    monkeypatch: pytest.MonkeyPatch,
    obligation_evidence_ids: list[str],
    expected_verified: bool,
) -> None:
    issue = _two_concern_shared_tool_grounding_issue()
    answer = "The first concern status is inactive."
    unit = issue_agent._grounding_answer_units(answer)[0]
    output = AutomationGroundingOutput(
        verdict="grounded",
        answer_sha256=issue_agent.grounding_text_sha256(answer),
        unit_assessments=[
            AutomationGroundingUnitAssessment(
                unit_id=unit["id"],
                unit_sha256=unit["sha256"],
                supported=True,
                evidence_ids=[
                    "tool:first-concern:shared-status",
                    "tool:second-concern:shared-status",
                ],
            )
        ],
        obligation_assessments=[
            AutomationGroundingObligationAssessment(
                obligation_id="first:status",
                resolution="answered",
                answer_unit_ids=[unit["id"]],
                evidence_ids=obligation_evidence_ids,
            )
        ],
    )

    result, prompts = _assess_with_grounding_outputs(
        monkeypatch,
        issue=issue,
        answer=answer,
        outputs=[output],
    )

    assert len(prompts) == 1
    assert result.verified is expected_verified
    if expected_verified:
        assert result.obligation_assessments[0]["resolution"] == "answered"
        assert result.obligation_assessments[0]["evidenceIds"] == [
            "tool:first-concern:shared-status"
        ]
    else:
        assert result.reason_code == "incomplete_answer"
        assert result.obligation_assessments[0]["resolution"] == "not_covered"


def _successful_grounding_action(
    execution_id: str,
    concern_id: str,
) -> dict[str, Any]:
    return {
        "id": execution_id,
        "type": "runbook_webhook",
        "status": "success",
        "completedAt": "2026-07-18T10:00:00Z",
        "metadata": {
            "source": "runbook",
            "concernId": concern_id,
        },
        "result": {
            "proposedAction": {
                "name": "set_status",
                "label": "Set status",
            },
            "application": {
                "applied": True,
                "webhookResult": {
                    "status": "ok",
                    "response": {"status": "active"},
                },
            },
        },
    }


@pytest.mark.parametrize("resolution", ["answered", "pending_or_unavailable"])
def test_grounding_rejects_other_concern_tool_for_every_addressed_obligation(
    monkeypatch: pytest.MonkeyPatch,
    resolution: str,
) -> None:
    issue = _two_concern_shared_tool_grounding_issue()
    answer = "The first concern status is active."

    result, prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer=answer,
        resolutions=[("first:status", resolution, ["u001"])],
        unit_evidence_ids=["tool:second-concern:shared-status"],
    )

    assert '"tool:first-concern:shared-status"' in prompt
    assert '"tool:second-concern:shared-status"' in prompt
    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.obligation_assessments[0]["resolution"] == "not_covered"
    assert result.uncovered_obligations == ("What is the first concern status?",)


@pytest.mark.parametrize("resolution", ["answered", "pending_or_unavailable"])
def test_grounding_rejects_other_concern_action_for_every_addressed_obligation(
    monkeypatch: pytest.MonkeyPatch,
    resolution: str,
) -> None:
    issue = _two_concern_shared_tool_grounding_issue()
    issue["actionExecutions"] = [
        _successful_grounding_action("execution-first", "first-concern"),
        _successful_grounding_action("execution-second", "second-concern"),
    ]

    result, prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer="The first concern status is active.",
        resolutions=[("first:status", resolution, ["u001"])],
        unit_evidence_ids=["action:execution-second"],
    )

    assert '"action:execution-first"' in prompt
    assert '"action:execution-second"' in prompt
    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.obligation_assessments[0]["resolution"] == "not_covered"
    assert result.uncovered_obligations == ("What is the first concern status?",)


@pytest.mark.parametrize("resolution", ["answered", "pending_or_unavailable"])
def test_grounding_rejects_other_concern_container_for_addressed_obligation(
    monkeypatch: pytest.MonkeyPatch,
    resolution: str,
) -> None:
    issue = _two_concern_shared_tool_grounding_issue()

    result, _prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer="The first concern status is active.",
        resolutions=[("first:status", resolution, ["u001"])],
        unit_evidence_ids=["concern:second-concern"],
    )

    assert result.verified is False
    assert result.reason_code == "incomplete_answer"
    assert result.obligation_assessments[0]["resolution"] == "not_covered"


@pytest.mark.parametrize(
    "evidence_id",
    ["tool:first-concern:shared-status", "concern:first-concern"],
)
def test_grounding_accepts_same_concern_tool_or_container_evidence(
    monkeypatch: pytest.MonkeyPatch,
    evidence_id: str,
) -> None:
    issue = _two_concern_shared_tool_grounding_issue()

    result, _prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer="The first concern status was checked.",
        resolutions=[("first:status", "answered", ["u001"])],
        unit_evidence_ids=[evidence_id],
    )

    assert result.verified is True
    assert result.obligation_assessments[0]["resolution"] == "answered"


def test_grounding_ticket_id_contains_only_global_safe_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = _two_concern_shared_tool_grounding_issue()
    issue["actionExecutions"] = [
        _successful_grounding_action("execution-first", "first-concern"),
        _successful_grounding_action("execution-second", "second-concern"),
    ]
    issue["aiRuns"][0]["intentResult"]["concerns"][0]["answerObligations"] = [
        {
            "obligationId": "first:subject",
            "question": "What is this ticket's subject?",
        }
    ]

    result, prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer="The ticket subject is Grounding obligation regression.",
        resolutions=[("first:subject", "answered", ["u001"])],
        unit_evidence_ids=["ticket"],
    )

    global_ticket = prompt.split(
        "## Global Ticket Evidence (`ticket`)\n",
        1,
    )[1].split("\n\n## Concern-Scoped Runbook Evidence\n", 1)[0]
    scoped_ticket = prompt.split(
        "## Concern-Scoped Runbook Evidence\n",
        1,
    )[1].split("\n\n## Account Intelligence\n", 1)[0]

    assert '"subject": "Grounding obligation regression"' in global_ticket
    assert '"concerns"' not in global_ticket
    assert '"toolEvidence"' not in global_ticket
    assert '"runbookActions"' not in global_ticket
    assert "shared-status" not in global_ticket
    assert "execution-second" not in global_ticket
    assert '"evidenceId": "concern:first-concern"' in scoped_ticket
    assert '"evidenceId": "tool:second-concern:shared-status"' in scoped_ticket
    assert '"evidenceId": "action:execution-second"' in scoped_ticket
    assert result.verified is True
    assert result.obligation_assessments[0]["resolution"] == "answered"


def test_grounding_context_hashes_global_and_scoped_ticket_evidence_separately() -> None:
    issue = _two_concern_shared_tool_grounding_issue()
    initial = {
        snapshot["id"]: snapshot["contextSha256"]
        for snapshot in issue_agent.grounding_context_snapshots(
            issue=issue,
            messages=[],
        )
    }
    issue["aiRuns"][0]["intentResult"]["concerns"][1]["outcome"][
        "toolEvidence"
    ][0]["responseFacts"]["status"] = "paused"
    changed = {
        snapshot["id"]: snapshot["contextSha256"]
        for snapshot in issue_agent.grounding_context_snapshots(
            issue=issue,
            messages=[],
        )
    }

    assert initial["ticket"] == changed["ticket"]
    assert initial["ticket:scoped"] != changed["ticket:scoped"]


def test_grounding_allows_legacy_tool_id_only_from_explicit_flat_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = _issue_with_grounding_obligations(
        concern_id="legacy-concern",
        questions=[("legacy:status", "What is the legacy status?")],
    )
    legacy_ticket = issue_agent._automatic_ticket_context(issue)
    legacy_ticket["toolEvidence"] = [
        {
            "name": "legacy-status",
            "status": "success",
            "evidenceId": "tool:legacy-status",
            "responseFacts": {"status": "active"},
        }
    ]
    monkeypatch.setattr(
        issue_agent,
        "_automatic_ticket_context",
        lambda _issue: legacy_ticket,
    )

    result, _prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer="The legacy status is active.",
        resolutions=[("legacy:status", "answered", ["u001"])],
        unit_evidence_ids=["tool:legacy-status"],
    )

    assert result.verified is True
    assert issue_agent._scoped_tool_evidence_concerns(legacy_ticket) == {}


def test_grounding_prompt_defines_strict_obligation_resolution_contract() -> None:
    prompt = issue_agent._GROUNDING_SYSTEM_PROMPT

    assert "`answered`" in prompt
    assert "`fulfilled_action`" in prompt
    assert "`pending_or_unavailable`" in prompt
    assert "`not_covered`" in prompt
    assert "generic intake prerequisites" in prompt
    assert "can be assessed or discussed later" in prompt
    assert "unrelated future consultation" in prompt
    assert "successful exact `tool:*` or `action:*` evidence ID" in prompt


def test_grounding_obligation_schema_requires_resolution_and_derives_covered() -> None:
    schema = AutomationGroundingObligationAssessment.model_json_schema()
    assessment = AutomationGroundingObligationAssessment(
        obligation_id="conflict:run",
        resolution="pending_or_unavailable",
    )

    assert "resolution" in schema["required"]
    assert "covered" not in schema["properties"]
    assert assessment.model_dump()["covered"] is True


def test_grounding_missing_obligation_assessment_is_reported_as_uncovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = _issue_with_grounding_obligations(
        concern_id="conflict-check",
        questions=[("conflict:run", "Run the conflict check.")],
    )

    result, _prompt = _assess_with_grounding_output(
        monkeypatch,
        issue=issue,
        answer="The request was received.",
        resolutions=[],
        verdict="grounded",
    )

    assert result.verified is False
    assert result.status == "error"
    assert result.uncovered_obligations == ("Run the conflict check.",)


@pytest.mark.parametrize("second_attempt_valid", [True, False])
def test_grounding_retries_unknown_obligation_protocol_once_with_identical_input(
    monkeypatch: pytest.MonkeyPatch,
    second_attempt_valid: bool,
) -> None:
    issue = _issue_with_grounding_obligations(
        concern_id="delivery",
        questions=[("delivery:status", "What is the current delivery status?")],
    )
    answer = "The delivery is pending carrier confirmation."
    unit = issue_agent._grounding_answer_units(answer)[0]

    def output(obligation_id: str) -> AutomationGroundingOutput:
        return AutomationGroundingOutput(
            verdict="grounded",
            answer_sha256=issue_agent.grounding_text_sha256(answer),
            unit_assessments=[
                AutomationGroundingUnitAssessment(
                    unit_id=unit["id"],
                    unit_sha256=unit["sha256"],
                    supported=True,
                    evidence_ids=["ticket"],
                )
            ],
            obligation_assessments=[
                AutomationGroundingObligationAssessment(
                    obligation_id=obligation_id,
                    resolution="pending_or_unavailable",
                    answer_unit_ids=[unit["id"]],
                )
            ],
        )

    malformed = output("delivery:invented")
    responses = [
        malformed,
        output("delivery:status") if second_attempt_valid else malformed,
    ]
    invocations: list[tuple[dict[str, Any], dict[str, Any]]] = []
    captured_agent_kwargs: dict[str, Any] = {}
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(
        usage_module,
        "record_usage_from_result",
        lambda *_args, **_kwargs: None,
    )

    class FakeGroundingAgent:
        def invoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            invocations.append((inputs, config))
            return {"structured_response": responses[len(invocations) - 1]}

    def fake_create_agent(**kwargs: Any) -> FakeGroundingAgent:
        captured_agent_kwargs.update(kwargs)
        return FakeGroundingAgent()

    monkeypatch.setattr(issue_agent, "create_agent", fake_create_agent)

    result = issue_agent.assess_issue_automation_grounding(
        issue=issue,
        messages=[],
        answer=answer,
        articles=[],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert len(invocations) == issue_agent.GROUNDING_MODEL_CALL_LIMIT == 2
    assert invocations[0] == invocations[1]
    assert captured_agent_kwargs["middleware"][0].run_limit == 1
    assert result.as_metadata()["modelCallLimit"] == 2
    assert result.verified is second_attempt_valid
    if second_attempt_valid:
        assert result.status == "passed"
    else:
        assert result.status == "error"
        assert "unknown answer-obligation ID" in result.error


def test_grounding_reassesses_supported_multi_concern_status_and_safe_deferral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipment_concern_id = "concern-shipment"
    address_concern_id = "concern-address"
    shipment_evidence_id = f"tool:{shipment_concern_id}:lookup-shipment"
    address_evidence_id = f"tool:{address_concern_id}:lookup-order-shipment"
    obligations = [
        ("shipment:status", "Give the current shipment status."),
        ("shipment:event", "Give the last carrier event."),
        ("shipment:eta", "Give the estimated delivery date."),
    ]
    issue = _issue_with_grounding_obligations(
        concern_id=shipment_concern_id,
        questions=obligations,
        tool_evidence=[
            {
                "name": "lookup-shipment",
                "status": "success",
                "responseFacts": {
                    "orderId": "ZF-20991",
                    "trackingNumber": "UPS1Z999AA10123456784",
                    "status": "In transit",
                    "lastEvent": "Departed from facility",
                    "lastLocation": "UPS Koeln Hub",
                    "lastEventTime": "07:15",
                    "estimatedDelivery": "next business day",
                },
            }
        ],
    )
    issue["aiRuns"][0]["intentResult"]["concerns"].append(
        {
            "concernId": address_concern_id,
            "matched": True,
            "intentName": "address-change",
            "answerObligations": [
                {
                    "obligationId": "address:change",
                    "question": "Change the address today and confirm it.",
                },
                {
                    "obligationId": "address:redirect",
                    "question": "Request a carrier redirect.",
                },
            ],
            "outcome": {
                "toolEvidence": [
                    {
                        "name": "lookup-order-shipment",
                        "status": "success",
                        "responseFacts": {
                            "orderId": "ZF-20991",
                            "trackingNumber": "UPS1Z999AA10123456784",
                            "status": "In transit",
                            "directAddressChangeAllowed": False,
                            "carrierRedirectAvailable": True,
                            "carrier": "UPS",
                            "requiresHumanReview": True,
                            "requestedAddress": "24 New Street, Zurich 8001",
                        },
                    }
                ]
            },
        }
    )
    answer = (
        "Hello Noah,\n\n"
        "ZenFulfillment is handling your order ZF-20991. "
        "Your shipment, with tracking number UPS1Z999AA10123456784, is currently In transit. "
        "The last carrier event recorded was 'Departed from facility' from UPS Koeln Hub today at 07:15. "
        "We estimate delivery for the next business day.\n\n"
        "Regarding your request to change the delivery address for ZF-20991 to 24 New Street, "
        "Zurich 8001: Since your shipment is already in transit, ZenFulfillment cannot directly "
        "change the address. We can submit a request for a carrier redirect to UPS, but this action "
        "requires human review and is subject to carrier availability and approval. We cannot confirm "
        "an address change until it is verified by a human operator or a tool confirms the change.\n\n"
        "We will keep you updated as soon as we have more information regarding the redirect request."
    )
    units = {unit["id"]: unit for unit in issue_agent._grounding_answer_units(answer)}
    assert list(units) == [f"u{index:03d}" for index in range(1, 10)]
    unit_evidence = {
        "u001": ["ticket"],
        "u002": [shipment_evidence_id, address_evidence_id],
        "u003": [shipment_evidence_id, address_evidence_id],
        "u004": [shipment_evidence_id, address_evidence_id],
        "u005": [shipment_evidence_id, address_evidence_id],
        "u006": [shipment_evidence_id, address_evidence_id],
        "u007": [shipment_evidence_id, address_evidence_id],
        "u008": [address_evidence_id],
        "u009": [address_evidence_id],
    }
    obligation_units = {
        "shipment:status": ["u003"],
        "shipment:event": ["u004"],
        "shipment:eta": ["u005"],
        "address:change": ["u006", "u007", "u008"],
        "address:redirect": ["u007", "u009"],
    }
    obligation_evidence = {
        "shipment:status": [shipment_evidence_id],
        "shipment:event": [shipment_evidence_id],
        "shipment:eta": [shipment_evidence_id],
        "address:change": [address_evidence_id],
        "address:redirect": [address_evidence_id],
    }

    def output(*, corrected: bool) -> AutomationGroundingOutput:
        return AutomationGroundingOutput(
            verdict="grounded" if corrected else "not_grounded",
            answer_sha256=issue_agent.grounding_text_sha256(answer),
            unit_assessments=[
                AutomationGroundingUnitAssessment(
                    unit_id=unit_id,
                    unit_sha256=unit["sha256"],
                    supported=True,
                    evidence_ids=unit_evidence[unit_id],
                )
                for unit_id, unit in units.items()
            ],
            obligation_assessments=[
                AutomationGroundingObligationAssessment(
                    obligation_id=obligation_id,
                    resolution=(
                        ("pending_or_unavailable" if obligation_id.startswith("address:") else "answered")
                        if corrected
                        else "not_covered"
                    ),
                    answer_unit_ids=obligation_units[obligation_id],
                    evidence_ids=obligation_evidence[obligation_id],
                )
                for obligation_id in obligation_units
            ],
        )

    result, prompts = _assess_with_grounding_outputs(
        monkeypatch,
        issue=issue,
        answer=answer,
        outputs=[output(corrected=False), output(corrected=True)],
    )

    assert len(prompts) == 2
    assert prompts[0] != prompts[1]
    assert "Required Second-Pass Obligation Adjudication" in prompts[1]
    assert result.verified is True
    assert result.status == "passed"
    assert result.uncovered_obligations == ()
    assert [assessment["resolution"] for assessment in result.obligation_assessments] == [
        "answered",
        "answered",
        "answered",
        "pending_or_unavailable",
        "pending_or_unavailable",
    ]
    assert all(
        assessment["evidenceIds"] == obligation_evidence[assessment["obligationId"]]
        for assessment in result.obligation_assessments
    )


def test_grounding_reassessment_keeps_adversarial_no_answer_uncovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = _issue_with_grounding_obligations(
        concern_id="shipment",
        questions=[
            ("shipment:status", "What is the current shipment status?"),
            ("shipment:eta", "When will it arrive?"),
        ],
    )
    answer = "Thanks for your message. We will look into it and get back to you."
    units = issue_agent._grounding_answer_units(answer)
    output = AutomationGroundingOutput(
        verdict="not_grounded",
        answer_sha256=issue_agent.grounding_text_sha256(answer),
        unit_assessments=[
            AutomationGroundingUnitAssessment(
                unit_id=unit["id"],
                unit_sha256=unit["sha256"],
                supported=True,
                evidence_ids=["ticket"],
            )
            for unit in units
        ],
        obligation_assessments=[
            AutomationGroundingObligationAssessment(
                obligation_id=obligation_id,
                resolution="not_covered",
                answer_unit_ids=[unit["id"] for unit in units],
                evidence_ids=["ticket"],
            )
            for obligation_id in ("shipment:status", "shipment:eta")
        ],
    )

    result, prompts = _assess_with_grounding_outputs(
        monkeypatch,
        issue=issue,
        answer=answer,
        outputs=[output, output],
    )

    assert len(prompts) == 2
    assert result.verified is False
    assert result.status == "failed"
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == (
        "What is the current shipment status?",
        "When will it arrive?",
    )


def test_grounding_resolves_knowledge_backed_negative_refund_guarantee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concern_id = "concern-return"
    obligation_id = "return:refund-guarantee"
    article_id = "return-policy"
    issue = _issue_with_grounding_obligations(
        concern_id=concern_id,
        questions=[(obligation_id, "Guarantee the refund by Friday.")],
    )
    answer = (
        "Regarding the refund, its timing is controlled by the merchant and cannot "
        "be guaranteed by ZenFulfillment."
    )
    unit = issue_agent._grounding_answer_units(answer)[0]
    output = AutomationGroundingOutput(
        verdict="not_grounded",
        answer_sha256=issue_agent.grounding_text_sha256(answer),
        checked_citation_ids=[article_id],
        unit_assessments=[
            AutomationGroundingUnitAssessment(
                unit_id=unit["id"],
                unit_sha256=unit["sha256"],
                supported=True,
                evidence_ids=[article_id],
            )
        ],
        obligation_assessments=[
            AutomationGroundingObligationAssessment(
                obligation_id=obligation_id,
                resolution="not_covered",
                answer_unit_ids=[unit["id"]],
                evidence_ids=[article_id, f"concern:{concern_id}"],
            )
        ],
    )
    article = {
        "id": article_id,
        "title": "Return authorization and refund timing",
        "body": (
            "A return requires merchant authorization and a return reference before "
            "shipping. The merchant controls refund timing; ZenFulfillment cannot "
            "guarantee it."
        ),
        "tags": ["return", "refund"],
        "status": "published",
        "reviewStatus": "reviewed",
        "freshnessStatus": "fresh",
        "needsReview": False,
    }

    result, prompts = _assess_with_grounding_outputs(
        monkeypatch,
        issue=issue,
        answer=answer,
        outputs=[output, output],
        articles=[article],
    )

    assert len(prompts) == 2
    assert "requested guarantee cannot be made" in prompts[1]
    assert result.verified is True
    assert result.status == "passed"
    assert result.uncovered_obligations == ()
    assert result.obligation_assessments == (
        {
            "obligationId": obligation_id,
            "resolution": "pending_or_unavailable",
            "covered": True,
            "answerUnitIds": [unit["id"]],
            "evidenceIds": [article_id],
        },
    )


@pytest.mark.parametrize(
    "answer",
    [
        "Delivery timing cannot be guaranteed by ZenFulfillment.",
        "The refund by Friday is guaranteed by ZenFulfillment.",
        "The refund request is logged, but delivery timing cannot be guaranteed.",
        "We cannot deny that the refund is guaranteed.",
    ],
)
def test_negative_guarantee_resolution_requires_matching_subject_and_refusal(
    answer: str,
) -> None:
    unit = issue_agent._grounding_answer_units(answer)[0]

    assert issue_agent._knowledge_backed_negative_guarantee_answers_obligation(
        question="Guarantee the refund by Friday.",
        answer_unit_ids=(unit["id"],),
        expected_units={unit["id"]: unit},
        supported_unit_evidence_ids={unit["id"]: frozenset({"return-policy"})},
        citation_ids=frozenset({"return-policy"}),
    ) is False


@pytest.mark.parametrize(
    ("answer", "article_body"),
    [
        (
            "The refund request is logged, but delivery timing cannot be guaranteed.",
            "The refund request is logged, but delivery timing cannot be guaranteed.",
        ),
        (
            "We cannot deny that the refund is guaranteed.",
            "For this test, the refund is guaranteed.",
        ),
        (
            "We cannot guarantee the refund policy is complete.",
            "The refund policy is complete.",
        ),
        (
            "We cannot guarantee the refund email was delivered.",
            "The refund email was delivered.",
        ),
        (
            "Regarding the refund, its timing is guaranteed while delivery cannot be guaranteed.",
            "Refund timing is guaranteed while delivery timing cannot be guaranteed.",
        ),
        (
            "Our policy does not say that we cannot guarantee the refund.",
            "Our policy does not say that we cannot guarantee the refund.",
        ),
        (
            "It is false that we cannot guarantee the refund.",
            "It is false that we cannot guarantee the refund.",
        ),
        (
            "We cannot guarantee the refund, but it is guaranteed.",
            "We cannot guarantee the refund, but it is guaranteed.",
        ),
        (
            "It remains unclear whether the refund cannot be guaranteed.",
            "It remains unclear whether the refund cannot be guaranteed.",
        ),
        (
            'The statement "the refund cannot be guaranteed" is false.',
            'The statement "the refund cannot be guaranteed" is false.',
        ),
    ],
)
def test_grounding_does_not_apply_negative_guarantee_override_across_clauses(
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
    article_body: str,
) -> None:
    concern_id = "concern-return"
    obligation_id = "return:refund-guarantee"
    article_id = "return-policy"
    issue = _issue_with_grounding_obligations(
        concern_id=concern_id,
        questions=[(obligation_id, "Guarantee the refund by Friday.")],
    )
    unit = issue_agent._grounding_answer_units(answer)[0]
    output = AutomationGroundingOutput(
        verdict="not_grounded",
        answer_sha256=issue_agent.grounding_text_sha256(answer),
        checked_citation_ids=[article_id],
        unit_assessments=[
            AutomationGroundingUnitAssessment(
                unit_id=unit["id"],
                unit_sha256=unit["sha256"],
                supported=True,
                evidence_ids=[article_id],
            )
        ],
        obligation_assessments=[
            AutomationGroundingObligationAssessment(
                obligation_id=obligation_id,
                resolution="not_covered",
                answer_unit_ids=[unit["id"]],
                evidence_ids=[article_id, f"concern:{concern_id}"],
            )
        ],
    )
    article = {
        "id": article_id,
        "title": "Adversarial return policy",
        "body": article_body,
        "tags": ["return", "refund"],
        "status": "published",
        "reviewStatus": "reviewed",
        "freshnessStatus": "fresh",
        "needsReview": False,
    }

    result, prompts = _assess_with_grounding_outputs(
        monkeypatch,
        issue=issue,
        answer=answer,
        outputs=[output, output],
        articles=[article],
    )

    assert len(prompts) == 2
    assert result.verified is False
    assert result.status == "failed"
    assert result.reason_code == "incomplete_answer"
    assert result.uncovered_obligations == ("Guarantee the refund by Friday.",)


@pytest.mark.parametrize("failure_kind", ["unsupported", "unknown_evidence"])
def test_grounding_does_not_retry_semantic_or_unknown_evidence_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    answer = "The parcel is delayed."
    unit = issue_agent._grounding_answer_units(answer)[0]
    output = AutomationGroundingOutput(
        verdict="not_grounded" if failure_kind == "unsupported" else "grounded",
        answer_sha256=issue_agent.grounding_text_sha256(answer),
        unit_assessments=[
            AutomationGroundingUnitAssessment(
                unit_id=unit["id"],
                unit_sha256=unit["sha256"],
                supported=failure_kind != "unsupported",
                evidence_ids=(
                    []
                    if failure_kind == "unsupported"
                    else ["invented-evidence"]
                ),
            )
        ],
    )
    invocations = 0
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(
        usage_module,
        "record_usage_from_result",
        lambda *_args, **_kwargs: None,
    )

    class FakeGroundingAgent:
        def invoke(self, _inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            nonlocal invocations
            invocations += 1
            assert config["run_name"] == "issue_automation_grounding"
            return {"structured_response": output}

    monkeypatch.setattr(
        issue_agent,
        "create_agent",
        lambda **_kwargs: FakeGroundingAgent(),
    )

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1", "subject": "Parcel delayed"},
        messages=[],
        answer=answer,
        articles=[],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert invocations == 1
    assert result.verified is False
    if failure_kind == "unsupported":
        assert result.status == "failed"
        assert result.reason_code == "ungrounded_answer"
    else:
        assert result.status == "error"
        assert "unknown evidence IDs" in result.error


def test_grounding_gate_rejects_incomplete_unit_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = "The parcel is delayed. It should arrive within seven business days."
    units = issue_agent._grounding_answer_units(answer)
    assessments = [
        AutomationGroundingUnitAssessment(
            unit_id=unit["id"],
            unit_sha256=unit["sha256"],
            supported=True,
            evidence_ids=["shipping-policy"],
        )
        for unit in units
    ]
    assessments.pop()
    output = AutomationGroundingOutput(
        verdict="grounded",
        answer_sha256=issue_agent.grounding_text_sha256(answer),
        checked_citation_ids=["shipping-policy"],
        unit_assessments=assessments,
        contradictions=[],
    )
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeGroundingAgent:
        def invoke(self, _inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            return {"structured_response": output}

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeGroundingAgent())

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1", "subject": "Parcel delayed"},
        messages=[],
        answer=answer,
        articles=[_articles()[0]],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert result.verified is False
    assert result.status == "error"
    assert result.reason_code == "grounding_check_failed"


@pytest.mark.parametrize(
    ("checked_citation_ids", "model_unit_sha256"),
    [
        ([], ""),
        (["shipping-policy", "shipping-policy"], ""),
        (["messages", "ticket"], "one-character-short-model-echo"),
        (["unknown-redundant-echo"], ""),
    ],
)
def test_grounding_gate_uses_supported_unit_evidence_instead_of_redundant_echoes(
    monkeypatch: pytest.MonkeyPatch,
    checked_citation_ids: list[str],
    model_unit_sha256: str,
) -> None:
    answer = "The parcel is delayed."
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeGroundingAgent:
        def invoke(self, _inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            return {
                "structured_response": AutomationGroundingOutput(
                    verdict="grounded",
                    answer_sha256="incorrect-redundant-top-level-hash",
                    checked_citation_ids=checked_citation_ids,
                    unit_assessments=[
                        AutomationGroundingUnitAssessment(
                            unit_id="u001",
                            unit_sha256=(
                                model_unit_sha256
                                or issue_agent.grounding_text_sha256(answer)
                            ),
                            supported=True,
                            evidence_ids=["shipping-policy"],
                        )
                    ],
                    contradictions=[],
                )
            }

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeGroundingAgent())

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1", "subject": "Parcel delayed"},
        messages=[],
        answer=answer,
        articles=_articles(),
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert result.verified is True
    assert result.status == "passed"
    assert result.citation_ids == ("shipping-policy",)
    assert [snapshot["id"] for snapshot in result.evidence_snapshots] == ["shipping-policy"]
    assert result.unit_assessments[0]["unitSha256"] == issue_agent.grounding_text_sha256(answer)


def test_grounding_prompt_allows_unused_supplied_articles() -> None:
    prompt = issue_agent._GROUNDING_SYSTEM_PROMPT

    assert "Omit unused articles; the list may be empty." in prompt
    assert "Never force an unused article onto an answer unit" in prompt
    assert "must contain every supplied knowledge article ID" not in prompt
    assert "Every supplied knowledge citation ID must support" not in prompt


def test_grounding_gate_skips_model_when_answer_has_too_many_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = False

    def fail_create_agent(**_kwargs: Any) -> Any:
        nonlocal invoked
        invoked = True
        raise AssertionError("grounding model must not run")

    monkeypatch.setattr(issue_agent, "create_agent", fail_create_agent)
    answer = "\n".join(f"Supported line {index}." for index in range(51))

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1"},
        messages=[],
        answer=answer,
        articles=[_articles()[0]],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert invoked is False
    assert result.verified is False
    assert result.reason_code == "grounding_check_failed"
    assert len(result.answer_units) == 51


def test_grounding_gate_skips_model_for_incomplete_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    invoked = False

    def fail_create_agent(**_kwargs: Any) -> Any:
        nonlocal invoked
        invoked = True
        raise AssertionError("grounding model must not run")

    monkeypatch.setattr(issue_agent, "create_agent", fail_create_agent)
    article = _articles()[0]
    article["body"] = "A" * (issue_agent.GROUNDING_MAX_ARTICLE_CHARS + 1)

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1"},
        messages=[],
        answer="Candidate answer.",
        articles=[article],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert invoked is False
    assert result.verified is False
    assert result.reason_code == "grounding_evidence_incomplete"
    assert result.evidence_snapshots[0]["bodyChars"] > issue_agent.GROUNDING_MAX_ARTICLE_CHARS


def test_grounding_gate_capacity_exhaustion_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoCapacity:
        def acquire(self, *, blocking: bool, timeout: float) -> bool:
            assert blocking is True
            assert timeout == issue_agent.GROUNDING_AGENT_SLOT_WAIT_SECONDS
            return False

    monkeypatch.setattr(issue_agent, "_GROUNDING_AGENT_SLOTS", NoCapacity())

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1"},
        messages=[],
        answer="Candidate answer.",
        articles=[_articles()[0]],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert result.verified is False
    assert result.reason_code == "grounding_check_failed"
    assert "capacity" in result.error.lower()


def test_grounding_gate_waits_for_capacity_within_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = "Candidate answer."
    slot = threading.BoundedSemaphore(1)
    assert slot.acquire(blocking=False)
    release_timer = threading.Timer(0.02, slot.release)
    release_timer.start()
    monkeypatch.setattr(issue_agent, "_GROUNDING_AGENT_SLOTS", slot)
    monkeypatch.setattr(issue_agent, "GROUNDING_AGENT_SLOT_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeGroundingAgent:
        def invoke(self, _inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            return {
                "structured_response": AutomationGroundingOutput(
                    verdict="grounded",
                    answer_sha256=issue_agent.grounding_text_sha256(answer),
                    checked_citation_ids=["shipping-policy"],
                    unit_assessments=[
                        AutomationGroundingUnitAssessment(
                            unit_id="u001",
                            unit_sha256=issue_agent.grounding_text_sha256(answer),
                            supported=True,
                            evidence_ids=["shipping-policy"],
                        )
                    ],
                )
            }

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeGroundingAgent())

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1"},
        messages=[],
        answer=answer,
        articles=[_articles()[0]],
        tenant_id="tenant-1",
        project_id="project-1",
    )
    release_timer.join(timeout=1)

    assert result.verified is True
    assert result.status == "passed"


def test_grounding_gate_deadline_holds_slot_and_records_late_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = "Candidate answer."
    unblock = threading.Event()
    worker_started = threading.Event()
    slot_released = threading.Event()
    usage_results: list[dict[str, Any]] = []

    class TrackingSlot:
        def acquire(self, *, blocking: bool, timeout: float) -> bool:
            assert blocking is True
            assert timeout == issue_agent.GROUNDING_AGENT_SLOT_WAIT_SECONDS
            return True

        def release(self) -> None:
            slot_released.set()

    class SlowAgent:
        def invoke(self, _inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_grounding"
            worker_started.set()
            assert unblock.wait(timeout=1)
            return {
                "structured_response": AutomationGroundingOutput(
                    verdict="grounded",
                    answer_sha256=issue_agent.grounding_text_sha256(answer),
                    checked_citation_ids=["shipping-policy"],
                    unit_assessments=[
                        AutomationGroundingUnitAssessment(
                            unit_id="u001",
                            unit_sha256=issue_agent.grounding_text_sha256(answer),
                            supported=True,
                            evidence_ids=["shipping-policy"],
                        )
                    ],
                )
            }

    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(
        usage_module,
        "record_usage_from_result",
        lambda response, _context: usage_results.append(response),
    )
    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: SlowAgent())
    monkeypatch.setattr(issue_agent, "_GROUNDING_AGENT_SLOTS", TrackingSlot())
    monkeypatch.setattr(issue_agent, "GROUNDING_AGENT_DEADLINE_SECONDS", 0.01)

    result = issue_agent.assess_issue_automation_grounding(
        issue={"id": "issue-1"},
        messages=[],
        answer=answer,
        articles=[_articles()[0]],
        tenant_id="tenant-1",
        project_id="project-1",
    )

    assert worker_started.is_set()
    assert result.verified is False
    assert result.reason_code == "grounding_check_failed"
    assert result.error == "Grounding evaluator deadline exceeded"
    assert slot_released.is_set() is False
    unblock.set()
    assert slot_released.wait(timeout=1)
    assert len(usage_results) == 1


def test_draft_falls_back_when_agent_does_not_read_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_agent_dependencies(
        monkeypatch,
        commands=[],
        output=KnowledgeAgentOutput(
            answer="Unsupported answer.",
            confidence="high",
            citation_ids=[],
        ),
    )

    result = _draft()

    assert result.answer == (
        "Knowledge research could not be completed. No grounded answer was produced. "
        "Please review this ticket manually before replying."
    )
    assert result.confidence == "low"
    assert result.generation_mode == "deterministic_fallback"
    assert "did not inspect the workspace" in result.error
    assert result.tool_calls == ()


def test_draft_fails_closed_when_agent_capacity_is_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoCapacity:
        def acquire(self, *, blocking: bool) -> bool:
            assert blocking is False
            return False

    monkeypatch.setattr(issue_agent, "_KNOWLEDGE_AGENT_SLOTS", NoCapacity())

    result = _draft()

    assert result.answer == (
        "Knowledge research could not be completed. No grounded answer was produced. "
        "Please review this ticket manually before replying."
    )
    assert result.confidence == "low"
    assert result.generation_mode == "deterministic_fallback"
    assert result.error == "Knowledge agent capacity is temporarily exhausted"


def test_knowledge_agent_deadline_returns_fallback_and_holds_slot_until_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unblock = threading.Event()
    worker_started = threading.Event()
    slot_released = threading.Event()
    usage_results: list[dict[str, Any]] = []

    class TrackingSlot:
        def acquire(self, *, blocking: bool) -> bool:
            assert blocking is False
            return True

        def release(self) -> None:
            slot_released.set()

    class SlowAgent:
        def invoke(self, _inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "ticket_knowledge_agent"
            worker_started.set()
            assert unblock.wait(timeout=1)
            return {
                "structured_response": KnowledgeAgentOutput(
                    answer="Late answer.",
                    confidence="low",
                )
            }

    _patch_agent_dependencies(
        monkeypatch,
        commands=[],
        output=KnowledgeAgentOutput(answer="unused", confidence="low"),
    )
    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: SlowAgent())
    monkeypatch.setattr(issue_agent, "_KNOWLEDGE_AGENT_SLOTS", TrackingSlot())
    monkeypatch.setattr(issue_agent, "KNOWLEDGE_AGENT_DEADLINE_SECONDS", 0.01)
    monkeypatch.setattr(
        usage_module,
        "record_usage_from_result",
        lambda response, _context: usage_results.append(response),
    )

    result = _draft()

    assert worker_started.is_set()
    assert result.generation_mode == "deterministic_fallback"
    assert result.error == "Knowledge agent deadline exceeded"
    assert slot_released.is_set() is False
    unblock.set()
    assert slot_released.wait(timeout=1)
    assert len(usage_results) == 1


def test_automation_generator_capacity_exhaustion_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoCapacity:
        def acquire(self, *, blocking: bool, timeout: float) -> bool:
            assert blocking is True
            assert timeout == issue_agent.AUTOMATION_AGENT_SLOT_WAIT_SECONDS
            return False

    monkeypatch.setattr(issue_agent, "_AUTOMATION_AGENT_SLOTS", NoCapacity())

    result = issue_agent.draft_issue_automation_answer(
        issue={"id": "issue-1"},
        messages=[],
        question="Answer.",
        articles=_articles(),
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="Human review required.",
        fallback_confidence="low",
    )

    assert result.generation_mode == "deterministic_fallback"
    assert result.error == "Automatic answer capacity is temporarily exhausted"


def test_automation_generator_waits_for_capacity_within_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slot = threading.BoundedSemaphore(1)
    assert slot.acquire(blocking=False)
    release_timer = threading.Timer(0.02, slot.release)
    release_timer.start()
    monkeypatch.setattr(issue_agent, "_AUTOMATION_AGENT_SLOTS", slot)
    monkeypatch.setattr(issue_agent, "AUTOMATION_AGENT_SLOT_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(usage_module, "llm_stage", lambda _stage: nullcontext())
    monkeypatch.setattr(usage_module, "record_usage_from_result", lambda *_args, **_kwargs: None)

    class FakeAutomationAgent:
        def invoke(self, _inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_answer"
            return {
                "structured_response": AutomationAnswerOutput(
                    answer="We can help with your shipment.",
                    confidence="medium",
                )
            }

    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: FakeAutomationAgent())

    result = issue_agent.draft_issue_automation_answer(
        issue={"id": "issue-1"},
        messages=[{"direction": "customer", "body": "Please help with my shipment."}],
        question="Answer.",
        articles=[],
        prior_agent_runs=[],
        tenant_id="tenant-1",
        project_id="project-1",
        fallback_answer="Human review required.",
        fallback_confidence="low",
    )
    release_timer.join(timeout=1)

    assert result.generation_mode == "llm"
    assert result.answer == "We can help with your shipment."


def test_automation_generator_deadline_holds_slot_and_records_late_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unblock = threading.Event()
    worker_started = threading.Event()
    slot_released = threading.Event()
    late_usage_recorded = threading.Event()
    late_calls: list[dict[str, Any]] = []

    class TrackingSlot:
        def acquire(self, *, blocking: bool, timeout: float) -> bool:
            assert blocking is True
            assert timeout == issue_agent.AUTOMATION_AGENT_SLOT_WAIT_SECONDS
            return True

        def release(self) -> None:
            slot_released.set()

    class SlowAgent:
        def invoke(self, _inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
            assert config["run_name"] == "issue_automation_answer"
            worker_started.set()
            assert unblock.wait(timeout=1)
            return {
                "messages": [
                    AIMessage(
                        content="Late automatic answer.",
                        usage_metadata={
                            "input_tokens": 12,
                            "output_tokens": 5,
                            "total_tokens": 17,
                        },
                        response_metadata={"model_name": "test-automation-model"},
                    )
                ],
                "structured_response": AutomationAnswerOutput(
                    answer="Late automatic answer.",
                    confidence="low",
                ),
            }

    class FakeLlm:
        _mantly_usage_context = {
            "provider": "test",
            "model": "test-automation-model",
            "billing_mode": "byok",
        }

    monkeypatch.setattr(config_module, "read_config", lambda: {})
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda config, _tenant, _project: config,
    )
    monkeypatch.setattr(llm_module, "create_llm", lambda *_args, **_kwargs: FakeLlm())
    monkeypatch.setattr(issue_agent, "create_agent", lambda **_kwargs: SlowAgent())
    monkeypatch.setattr(issue_agent, "_AUTOMATION_AGENT_SLOTS", TrackingSlot())
    monkeypatch.setattr(issue_agent, "AUTOMATION_AGENT_DEADLINE_SECONDS", 0.01)

    def record_late_usage(calls: list[dict[str, Any]]) -> None:
        late_calls.extend(calls)
        late_usage_recorded.set()

    with usage_module.collect_llm_usage() as collector:
        result = issue_agent.draft_issue_automation_answer(
            issue={"id": "issue-1"},
            messages=[],
            question="Answer.",
            articles=_articles(),
            prior_agent_runs=[],
            tenant_id="tenant-1",
            project_id="project-1",
            fallback_answer="Human review required.",
            fallback_confidence="low",
            on_late_usage=record_late_usage,
        )

        assert worker_started.is_set()
        assert result.generation_mode == "deterministic_fallback"
        assert result.error == "Automatic answer deadline exceeded"
        assert slot_released.is_set() is False
        collector.add(
            {
                "stage": "unrelated_followup",
                "inputTokens": 100,
                "outputTokens": 50,
                "totalTokens": 150,
                "metadataAvailable": True,
            }
        )
        unblock.set()
        assert slot_released.wait(timeout=1)
        assert late_usage_recorded.wait(timeout=1)

    usage = collector.aggregate()
    assert usage["inputTokens"] == 100
    assert usage["outputTokens"] == 50
    assert usage["totalTokens"] == 150
    assert [call["stage"] for call in usage["calls"]] == ["unrelated_followup"]
    assert len(late_calls) == 1
    assert late_calls[0]["inputTokens"] == 12
    assert late_calls[0]["outputTokens"] == 5
    assert late_calls[0]["totalTokens"] == 17
    assert late_calls[0]["stage"] == "issue_automation_answer"
    assert late_calls[0]["provider"] == "test"
    assert late_calls[0]["model"] == "test-automation-model"


def test_draft_falls_back_when_bash_tool_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_agent_dependencies(
        monkeypatch,
        commands=["cat README.md"],
        output=KnowledgeAgentOutput(
            answer="Unsupported answer.",
            confidence="high",
            citation_ids=[],
        ),
    )

    def fail_run(_self: KnowledgeWorkspace, _command: str) -> str:
        raise RuntimeError("sandbox exploded")

    monkeypatch.setattr(KnowledgeWorkspace, "run", fail_run)

    result = _draft()

    assert result.answer == (
        "Knowledge research could not be completed. No grounded answer was produced. "
        "Please review this ticket manually before replying."
    )
    assert result.confidence == "low"
    assert result.generation_mode == "deterministic_fallback"
    assert "sandbox exploded" in result.error
    assert result.tool_calls == ()


def test_issue_answer_persists_only_agent_selected_citations_and_bash_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted: list[tuple[str, dict[str, Any]]] = []
    ids = iter(["run-1", "event-1"])
    issue = {
        "id": "issue-1",
        "subject": "Production API outage",
        "messages": [{"direction": "customer", "body": "The API is unavailable."}],
    }
    articles = [
        {
            "id": "lexical-match",
            "title": "API outage checklist",
            "body": "Check the incident page.",
            "status": "published",
            "tags": ["api"],
            "metadata": {"visibility": "public", "public": True},
        },
        {
            "id": "agent-selected",
            "title": "Enterprise incident communication",
            "body": "Send the next update within 30 minutes.",
            "status": "published",
            "tags": ["enterprise"],
            "metadata": {"visibility": "public", "public": True},
        },
    ]
    bash_trace = {
        "type": "knowledge_bash",
        "command": "cat knowledge/articles/0002--agent-selected.json",
        "exitCode": 0,
        "readArticleIds": ["agent-selected"],
    }

    monkeypatch.setattr(issues, "generate_id", lambda: next(ids))
    monkeypatch.setattr(issues, "get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(
        issues,
        "_list_all",
        lambda collection, *_args, **_kwargs: articles if collection == "knowledge_articles" else [],
    )
    monkeypatch.setattr(issues, "_post", lambda path, data: posted.append((path, data)) or data)
    monkeypatch.setattr(issues, "_upsert_agent_answer_knowledge_gap", lambda **_kwargs: None)
    monkeypatch.setattr(
        issues,
        "draft_issue_agent_answer",
        lambda **_kwargs: issue_agent.IssueAgentDraft(
            answer="We will send the next incident update within 30 minutes.",
            confidence="high",
            generation_mode="knowledge_agent",
            citation_ids=("agent-selected", "not-mounted"),
            missing_information=("Incident owner",),
            tool_calls=(bash_trace,),
        ),
    )

    result = issues.create_issue_agent_answer(
        "issue-1",
        tenant_id="tenant-1",
        project_id="project-1",
        author_email="agent@example.com",
        question="Prepare the incident update.",
        create_draft=False,
        use_knowledge_agent=True,
    )

    assert result is not None
    assert [article["id"] for article in result["citations"]] == ["agent-selected"]
    assert result["missingInformation"] == ["Incident owner"]
    assert result["knowledgeToolCalls"] == [bash_trace]
    ai_run = next(data for path, data in posted if path == "/api/collections/support_ai_runs/records")
    assert ai_run["metadata"]["knowledgeArticleIds"] == ["agent-selected"]
    assert ai_run["metadata"]["missingInformation"] == ["Incident owner"]
    assert ai_run["tool_calls"][0] == bash_trace
    assert ai_run["tool_calls"][1]["type"] == "knowledge_article"
    assert ai_run["tool_calls"][1]["id"] == "agent-selected"
    event = next(data for path, data in posted if path == "/api/collections/support_issue_events/records")
    assert event["metadata"]["knowledgeArticleIds"] == ["agent-selected"]


@pytest.mark.parametrize(
    (
        "generation_mode",
        "generation_error",
        "missing_information",
        "article_status",
        "knowledge_agent_requested",
        "grounding_verified",
        "expected",
    ),
    [
        ("deterministic_fallback", "provider unavailable", (), "published", True, False, "generation_failed"),
        ("knowledge_agent", "", ("Tracking number",), "published", True, False, "missing_information"),
        ("knowledge_agent", "", (), "draft", True, False, "unpublished_citations"),
        ("llm", "", (), "published", True, False, "knowledge_agent_requires_review"),
        ("knowledge_agent", "", (), "published", True, False, "knowledge_agent_requires_review"),
        ("llm", "", (), "published", False, False, "grounding_check_failed"),
        ("llm", "", (), "published", False, True, ""),
    ],
)
def test_auto_send_requires_verified_complete_published_agent_output(
    generation_mode: str,
    generation_error: str,
    missing_information: tuple[str, ...],
    article_status: str,
    knowledge_agent_requested: bool,
    grounding_verified: bool,
    expected: str,
) -> None:
    article = {
        "id": "article-1",
        "status": article_status,
        "reviewStatus": "reviewed",
        "freshnessStatus": "fresh",
        "needsReview": False,
        "visibility": "public",
        "public": True,
    }
    reason = issues._agent_auto_send_blocked_reason(
        confidence="high",
        articles=[article],
        generation_mode=generation_mode,
        generation_error=generation_error,
        missing_information=missing_information,
        knowledge_agent_requested=knowledge_agent_requested,
        grounding_verified=grounding_verified,
    )

    assert reason == expected


@pytest.mark.parametrize("review_status", ["needs_review", "stale"])
def test_auto_send_rejects_unreviewed_or_stale_citations(review_status: str) -> None:
    reason = issues._agent_auto_send_blocked_reason(
        confidence="high",
        articles=[
            {
                "id": "article-1",
                "status": "published",
                "reviewStatus": review_status,
                "freshnessStatus": "stale" if review_status == "stale" else "needs_review",
                "needsReview": True,
            }
        ],
        generation_mode="knowledge_agent",
        generation_error="",
        missing_information=(),
        knowledge_agent_requested=True,
    )

    assert reason == "unreviewed_citations"


@pytest.mark.parametrize(
    ("visibility", "is_public"),
    [("private", False), ("internal", False), ("public", False)],
)
def test_auto_send_rejects_restricted_citations(
    visibility: str,
    is_public: bool,
) -> None:
    reason = issues._agent_auto_send_static_blocked_reason(
        confidence="high",
        articles=[
            {
                "id": "article-1",
                "status": "published",
                "reviewStatus": "reviewed",
                "freshnessStatus": "fresh",
                "needsReview": False,
                "visibility": visibility,
                "public": is_public,
            }
        ],
        generation_mode="llm",
        generation_error="",
        missing_information=(),
        knowledge_agent_requested=False,
    )

    assert reason == "restricted_citations"


def test_search_validator_rejects_regex_flag_smuggling() -> None:
    workspace = _workspace(articles=[{"id": "article-1", "title": "Regex", "body": "aXF", "status": "published"}])

    result = _command_result(workspace, "grep '-ea.F' knowledge/articles/0001--article-1.json")

    assert result["exitCode"] == 2
    assert result["stderr"] == "Command rejected by limits."


def test_agent_corpus_query_mounts_only_published_project_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_list_all(collection: str, filter_value: str, **kwargs: Any) -> list[dict[str, Any]]:
        captured.update(collection=collection, filter=filter_value, kwargs=kwargs)
        return []

    monkeypatch.setattr(issues, "_list_all", fake_list_all)

    assert issues._knowledge_article_records_for_agent(tenant_id="tenant-1", project_id="project-1") == []
    assert captured["collection"] == "knowledge_articles"
    assert "tenant='tenant-1'" in captured["filter"]
    assert "project='project-1'" in captured["filter"]
    assert "status='published'" in captured["filter"]


def test_agent_corpus_enforces_human_and_automation_article_acl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        {"id": "legacy-internal", "status": "published", "metadata": {}},
        {
            "id": "internal",
            "status": "published",
            "metadata": {"visibility": "internal", "public": False},
        },
        {
            "id": "owned-private",
            "status": "published",
            "metadata": {
                "visibility": "private",
                "public": False,
                "ownerEmail": "agent@example.com",
            },
        },
        {
            "id": "other-private",
            "status": "published",
            "metadata": {
                "visibility": "private",
                "public": False,
                "ownerEmail": "other@example.com",
            },
        },
        {
            "id": "automation-private",
            "status": "published",
            "metadata": {
                "visibility": "private",
                "public": False,
                "automationAllowed": True,
            },
        },
        {
            "id": "unknown-access",
            "status": "published",
            "metadata": {"visibility": "secret"},
        },
    ]
    monkeypatch.setattr(issues, "_list_all", lambda *_args, **_kwargs: records)

    editor_ids = {
        article["id"]
        for article in issues._knowledge_article_records_for_agent(
            tenant_id="tenant-1",
            project_id="project-1",
            actor_email="agent@example.com",
            actor_role="editor",
        )
    }
    automation_ids = {
        article["id"]
        for article in issues._knowledge_article_records_for_agent(
            tenant_id="tenant-1",
            project_id="project-1",
        )
    }
    admin_ids = {
        article["id"]
        for article in issues._knowledge_article_records_for_agent(
            tenant_id="tenant-1",
            project_id="project-1",
            actor_email="admin@example.com",
            actor_role="admin",
        )
    }

    assert editor_ids == {"legacy-internal", "internal"}
    assert automation_ids == {"automation-private"}
    assert admin_ids == {
        "legacy-internal",
        "internal",
        "owned-private",
        "other-private",
        "automation-private",
    }


def test_auto_send_accepts_reviewed_internal_article_with_explicit_automation_access() -> None:
    reason = issues._agent_auto_send_static_blocked_reason(
        confidence="high",
        articles=[
            {
                "id": "internal-sop",
                "status": "published",
                "reviewStatus": "reviewed",
                "freshnessStatus": "fresh",
                "needsReview": False,
                "visibility": "internal",
                "public": False,
                "automationAllowed": True,
            }
        ],
        generation_mode="llm",
        generation_error="",
        missing_information=(),
        knowledge_agent_requested=False,
    )

    assert reason == ""


def test_issue_serialization_redacts_private_source_and_unapproved_derived_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_article = {
        "id": "private-article",
        "status": "published",
        "metadata": {
            "visibility": "private",
            "public": False,
            "automationAllowed": False,
        },
    }
    monkeypatch.setattr(issues, "_list_all", lambda *_args, **_kwargs: [private_article])
    citation = {
        "id": "private-article",
        "articleId": "private-article",
        "visibility": "private",
        "automationAllowed": False,
        "body": "PRIVATE-SOURCE",
    }
    issue = {
        "outboundMessages": [
            {
                "id": "reply-1",
                "body": "PRIVATE-DERIVED-ANSWER",
                "metadata": {
                    "knowledgeArticleIds": ["private-article"],
                    "citations": [citation],
                    "knowledgeCitationEvidence": [{"articleId": "private-article", "excerpt": "PRIVATE-SOURCE"}],
                },
            }
        ],
        "aiRuns": [
            {
                "id": "run-1",
                "summary": "PRIVATE-DERIVED-ANSWER",
                "metadata": {
                    "knowledgeArticleIds": ["private-article"],
                    "citations": [citation],
                    "answer": "PRIVATE-DERIVED-ANSWER",
                },
                "intentResult": {"knowledgeArticleIds": ["private-article"]},
                "toolCalls": [{"type": "knowledge_article", **citation}],
            }
        ],
        "agentMessages": [
            {
                "id": "message-1",
                "runId": "run-1",
                "replyId": "reply-1",
                "role": "assistant",
                "body": "PRIVATE-DERIVED-ANSWER",
            }
        ],
        "knowledgeGaps": [],
        "activityEvents": [
            {
                "id": "event-1",
                "body": "PRIVATE-DERIVED-ANSWER",
                "metadata": {"replyId": "reply-1"},
            }
        ],
    }

    redacted = issues._redact_issue_knowledge_for_principal(
        issue,
        tenant_id="tenant-1",
        project_id="project-1",
        actor_email="editor@example.com",
        actor_role="editor",
    )

    assert redacted["outboundMessages"][0]["body"] == ""
    assert redacted["outboundMessages"][0]["metadata"]["citations"] == []
    assert redacted["outboundMessages"][0]["metadata"]["knowledgeCitationEvidence"] == []
    assert redacted["aiRuns"][0]["summary"] == ""
    assert redacted["aiRuns"][0]["toolCalls"] == []
    assert redacted["agentMessages"][0]["body"] == ""
    assert redacted["activityEvents"][0]["body"] == ""


def test_issue_serialization_keeps_automation_approved_output_but_hides_private_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_article = {
        "id": "private-article",
        "status": "published",
        "metadata": {
            "visibility": "private",
            "public": False,
            "automationAllowed": True,
        },
    }
    monkeypatch.setattr(issues, "_list_all", lambda *_args, **_kwargs: [private_article])
    issue = {
        "outboundMessages": [
            {
                "id": "reply-1",
                "body": "APPROVED-DERIVED-ANSWER",
                "metadata": {
                    "knowledgeArticleIds": ["private-article"],
                    "citations": [
                        {
                            "id": "private-article",
                            "visibility": "private",
                            "automationAllowed": True,
                            "body": "PRIVATE-SOURCE",
                        }
                    ],
                },
            }
        ],
        "aiRuns": [],
        "agentMessages": [],
        "knowledgeGaps": [],
        "activityEvents": [],
    }

    redacted = issues._redact_issue_knowledge_for_principal(
        issue,
        tenant_id="tenant-1",
        project_id="project-1",
        actor_email="editor@example.com",
        actor_role="editor",
    )

    reply = redacted["outboundMessages"][0]
    assert reply["body"] == "APPROVED-DERIVED-ANSWER"
    assert reply["metadata"]["citations"] == []
    assert reply["knowledgeAccessRedacted"] is True


def test_article_history_and_suggestions_hide_prior_private_revisions() -> None:
    article = {
        "id": "article-1",
        "title": "Shipping policy",
        "body": "Current public guidance.",
        "status": "published",
        "metadata": {
            "visibility": "public",
            "public": True,
            "revisions": [
                {
                    "revision": 1,
                    "visibility": "private",
                    "public": False,
                    "automationAllowed": False,
                    "title": "SECRET-TITLE",
                    "bodyPreview": "SECRET-BODY",
                    "sourceUrl": "https://private.example/secret",
                },
                {
                    "revision": 2,
                    "visibility": "public",
                    "public": True,
                    "automationAllowed": True,
                    "title": "Shipping policy",
                    "bodyPreview": "Current public guidance.",
                },
            ],
        },
    }

    normalized = issues._normalize_article_for_principal(
        article,
        actor_email="viewer@example.com",
        actor_role="viewer",
    )
    suggestions = issues._knowledge_suggestions_for_issue(
        {"subject": "Shipping policy"},
        [],
        tenant_id="tenant-1",
        project_id="project-1",
        records=[article],
        actor_email="viewer@example.com",
        actor_role="viewer",
    )

    assert [revision["revision"] for revision in normalized["revisions"]] == [2]
    assert [revision["revision"] for revision in normalized["metadata"]["revisions"]] == [2]
    assert "SECRET" not in json.dumps(normalized)
    assert suggestions
    assert "SECRET" not in json.dumps(suggestions)


def test_policy_only_restriction_fails_closed_without_article_ids() -> None:
    clean, source_restricted, output_restricted = issues._sanitize_knowledge_metadata(
        {
            "answer": "SECRET-ANSWER",
            "question": "SECRET-QUESTION",
            "missingInformation": ["SECRET-MISSING"],
            "revisionContext": {"previousReplyBody": "SECRET-REVISION"},
            "knowledgeAccessPolicy": {
                "version": "knowledge-access-v1",
                "sourceAdminOnly": True,
                "outputAdminOnly": True,
            },
        },
        access_by_id={},
        actor_email="editor@example.com",
        actor_role="editor",
    )

    assert source_restricted is True
    assert output_restricted is True
    assert clean["answer"] == ""
    assert clean["question"] == ""
    assert clean["missingInformation"] == []
    assert clean["revisionContext"] == {}
    assert clean["knowledgeAccessRedacted"] is True
    assert clean["knowledgeOutputRestricted"] is True


def test_source_redaction_scrubs_nested_revision_lineage_but_keeps_allowed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        issues,
        "_list_all",
        lambda *_args, **_kwargs: [
            {
                "id": "private-article",
                "status": "published",
                "metadata": {
                    "visibility": "private",
                    "public": False,
                    "automationAllowed": True,
                },
            }
        ],
    )
    lineage = {
        "articleId": "private-article",
        "visibility": "private",
        "public": False,
        "automationAllowed": True,
    }
    issue = {
        "outboundMessages": [
            {
                "id": "reply-1",
                "body": "ALLOWED-DERIVED-ANSWER",
                "metadata": {
                    "knowledgeArticleIds": ["private-article"],
                    "knowledgeLineage": [lineage],
                    "revisionContext": {
                        "previousReplyBody": "ALLOWED-PRIOR-DRAFT",
                        "knowledgeArticleIds": ["private-article"],
                        "knowledgeLineage": [lineage],
                    },
                },
            }
        ],
        "aiRuns": [],
        "agentMessages": [],
        "knowledgeGaps": [],
        "activityEvents": [],
    }

    redacted = issues._redact_issue_knowledge_for_principal(
        issue,
        tenant_id="tenant-1",
        project_id="project-1",
        actor_email="editor@example.com",
        actor_role="editor",
    )

    reply = redacted["outboundMessages"][0]
    assert reply["body"] == "ALLOWED-DERIVED-ANSWER"
    assert reply["metadata"]["knowledgeArticleIds"] == []
    assert reply["metadata"]["knowledgeLineage"] == []
    assert reply["metadata"]["revisionContext"] == {
        "previousReplyBody": "ALLOWED-PRIOR-DRAFT",
        "knowledgeArticleIds": [],
        "knowledgeLineage": [],
    }


def test_current_uncited_read_precedes_inherited_lineage_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_article = {
        "id": "current-private",
        "title": "Shipping exception",
        "body": "Restricted automation guidance.",
        "status": "published",
        "metadata": {
            "visibility": "private",
            "public": False,
            "automationAllowed": True,
        },
    }
    inherited_lineage = [
        {
            "articleId": f"public-{index}",
            "visibility": "public",
            "public": True,
            "automationAllowed": True,
            "revision": "1",
        }
        for index in range(100)
    ]
    issue = {
        "id": "issue-1",
        "subject": "Shipping exception",
        "messages": [{"direction": "customer", "body": "Shipping exception"}],
        "aiRuns": [
            {
                "id": "prior-run",
                "source": "agent_answer",
                "metadata": {
                    "kind": "agent_answer",
                    "knowledgeLineage": inherited_lineage,
                },
            }
        ],
    }
    posts: list[tuple[str, dict[str, Any]]] = []
    generated = iter(f"generated-{index}" for index in range(20))
    monkeypatch.setattr(issues, "generate_id", lambda: next(generated))
    monkeypatch.setattr(issues, "get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(
        issues,
        "_list_all",
        lambda collection, *_args, **_kwargs: [current_article] if collection == "knowledge_articles" else [],
    )
    monkeypatch.setattr(issues, "_post", lambda path, data: posts.append((path, data)) or data)
    monkeypatch.setattr(issues, "_upsert_agent_answer_knowledge_gap", lambda **_kwargs: None)
    monkeypatch.setattr(
        issues,
        "draft_issue_agent_answer",
        lambda **_kwargs: issue_agent.IssueAgentDraft(
            answer="Prepared answer.",
            confidence="high",
            generation_mode="knowledge_agent",
            tool_calls=(
                {
                    "command": "cat knowledge/articles/current-private.md",
                    "readArticleIds": ["current-private"],
                },
            ),
        ),
    )

    result = issues.create_issue_agent_answer(
        "issue-1",
        tenant_id="tenant-1",
        project_id="project-1",
        author_email="agent@example.com",
        create_draft=False,
        use_knowledge_agent=True,
        knowledge_actor_role="automation",
    )

    assert result is not None
    assert result["knowledgeAccessedArticleIds"] == ["current-private"]
    assert result["knowledgeLineage"][0]["articleId"] == "current-private"
    assert len(result["knowledgeLineage"]) == 100
    assert result["knowledgeAccessPolicy"]["sourceAdminOnly"] is True
    assert result["knowledgeAccessPolicy"]["lineageOverflow"] is True
    assert result["knowledgeAccessPolicy"]["lineageCount"] == 101


def test_forbidden_private_article_never_enters_workspace_or_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        {
            "id": "allowed",
            "title": "Allowed policy",
            "body": "Approved evidence.",
            "status": "published",
            "metadata": {"visibility": "internal", "public": False},
        },
        {
            "id": "forbidden",
            "title": "Private contract",
            "body": "SECRET-CONTRACT-TERM",
            "status": "published",
            "metadata": {
                "visibility": "private",
                "public": False,
                "ownerEmail": "other@example.com",
            },
        },
    ]
    monkeypatch.setattr(issues, "_list_all", lambda *_args, **_kwargs: records)
    authorized = issues._knowledge_article_records_for_agent(
        tenant_id="tenant-1",
        project_id="project-1",
        actor_email="agent@example.com",
        actor_role="editor",
    )
    workspace = _workspace(articles=authorized)

    index = _command_result(workspace, "cat knowledge/index.jsonl")
    search = _command_result(workspace, 'rg -lF "SECRET-CONTRACT-TERM" knowledge/articles')

    assert [article["id"] for article in authorized] == ["allowed"]
    assert "forbidden" not in index["stdout"]
    assert "SECRET-CONTRACT-TERM" not in index["stdout"]
    assert search["exitCode"] != 0
    assert (
        workspace.validated_citation_ids(
            ["forbidden"],
            ["knowledge/articles/0002--forbidden.json"],
        )
        == ()
    )
    assert all("forbidden" not in str(call) for call in workspace.tool_calls)


def test_agent_corpus_ranking_keeps_older_relevant_article() -> None:
    records = [
        {
            "id": f"unrelated-{index}",
            "title": f"Unrelated policy {index}",
            "body": "General account administration guidance.",
            "status": "published",
            "updated": f"2026-07-15T12:{index % 60:02d}:00Z",
        }
        for index in range(110)
    ]
    records.append(
        {
            "id": "older-relevant",
            "title": "Temperature-sensitive Norway shipping",
            "body": "Temperature-sensitive shipments to Norway require a customs declaration.",
            "status": "published",
            "updated": "2025-01-01T00:00:00Z",
        }
    )

    ranked = issues._rank_knowledge_articles_for_issue(
        {"subject": "Can we ship temperature-sensitive goods to Norway?"},
        [],
        records=records,
        question="Which documents are required?",
    )

    assert ranked[0]["id"] == "older-relevant"
    assert any(article["id"] == "older-relevant" for article in ranked[: issues.AGENT_KNOWLEDGE_CORPUS_LIMIT])


def test_automatic_knowledge_ranking_excludes_generated_and_conversation_content() -> None:
    article = {
        "id": "billing-policy",
        "title": "Retainer billing fees",
        "body": "Retainer billing fees include a CHF 3,000 advance payment.",
        "status": "published",
        "tags": ["billing", "retainer"],
        "metadata": {"visibility": "public", "public": True},
    }
    issue = {
        "subject": "Beglaubigte Kopien für Italien – sichere Übermittlung",
        "activatedIntent": "legal-intake-qa",
        "aiSummary": "The draft quoted retainer billing fees and a CHF 3,000 advance payment.",
        "accountName": "Retainer Billing Customer",
        "contactEmail": "billing@example.test",
        "conversation": {
            "messages": [
                {
                    "direction": "agent",
                    "body": "The related ticket discussed retainer billing fees.",
                }
            ]
        },
    }
    messages = [
        {
            "direction": "customer",
            "body": "Darf ich vertrauliche PDFs per E-Mail senden?",
        },
        {
            "direction": "ai",
            "body": "The retainer billing fee is CHF 3,000.",
        },
    ]

    manual = issues._rank_knowledge_articles_for_issue(
        issue,
        messages,
        records=[article],
        question="Prepare an answer.",
    )
    automatic = issues._rank_knowledge_articles_for_automatic_answer(
        issue,
        messages,
        records=[article],
        question="Prepare an answer.",
    )

    assert manual[0]["metadata"]["knowledgeMatch"]["score"] > 0
    assert automatic == []


def test_automatic_knowledge_ranking_rejects_high_scoring_body_only_overlap() -> None:
    article = {
        "id": "fulfillment-b2b",
        "title": "Merchant operations handbook",
        "body": "Urgent escalation requires human review before the termination deadline.",
        "status": "published",
        "tags": ["fulfillment"],
        "metadata": {"visibility": "public", "public": True},
    }
    issue = {
        "subject": "Employment termination deadline",
        "activatedIntent": "employment-termination-urgent-qa",
    }
    messages = [
        {
            "direction": "customer",
            "body": "This urgent termination needs escalation and human review before the deadline.",
        }
    ]
    context = issues._automatic_knowledge_context_text(
        issue,
        messages,
        question="Prepare an answer.",
    )
    match = issues._score_knowledge_article_match(
        article,
        " ".join(context.lower().replace("_", " ").replace("-", " ").split()),
        issues._text_tokens(context),
    )

    automatic = issues._rank_knowledge_articles_for_automatic_answer(
        issue,
        messages,
        records=[article],
        question="Prepare an answer.",
    )

    assert match["score"] >= issues.AUTOMATIC_KNOWLEDGE_MIN_SCORE
    assert match["signals"] == ["body"]
    assert automatic == []


def test_automatic_knowledge_ranking_keeps_strong_activated_intent_tag_match() -> None:
    article = {
        "id": "legal-intake",
        "title": "Client onboarding checklist",
        "body": "Collect the legal name, opposing parties, and critical dates.",
        "status": "published",
        "tags": ["legal-intake"],
        "metadata": {"visibility": "public", "public": True},
    }
    issue = {
        "subject": "Beglaubigte Kopien für Italien",
        "activatedIntent": "legal-intake-qa",
    }
    messages = [
        {
            "direction": "customer",
            "body": "Welche Unterlagen benötigen Sie?",
        }
    ]

    automatic = issues._rank_knowledge_articles_for_automatic_answer(
        issue,
        messages,
        records=[article],
        question="Prepare an answer.",
    )

    assert [item["id"] for item in automatic] == ["legal-intake"]
    match = automatic[0]["metadata"]["knowledgeMatch"]
    assert match["score"] >= issues.AUTOMATIC_KNOWLEDGE_MIN_SCORE
    assert {"legal", "intake"}.issubset(set(match["tagMatches"]))
