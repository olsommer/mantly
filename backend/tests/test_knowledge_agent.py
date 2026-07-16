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


@pytest.mark.parametrize("failure", ["missing_unit", "wrong_hash", "unused_citation"])
def test_grounding_gate_rejects_incomplete_unit_protocol(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
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
    if failure == "missing_unit":
        assessments.pop()
    elif failure == "wrong_hash":
        assessments[0].unit_sha256 = "0" * 64
    else:
        assessments[0].evidence_ids = ["ticket"]
        assessments[1].evidence_ids = ["ticket"]
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
        def acquire(self, *, blocking: bool) -> bool:
            assert blocking is False
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


def test_grounding_gate_deadline_holds_slot_and_records_late_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = "Candidate answer."
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
        def acquire(self, *, blocking: bool) -> bool:
            assert blocking is False
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


def test_automation_generator_deadline_holds_slot_and_records_late_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unblock = threading.Event()
    worker_started = threading.Event()
    slot_released = threading.Event()
    late_usage_recorded = threading.Event()
    late_calls: list[dict[str, Any]] = []

    class TrackingSlot:
        def acquire(self, *, blocking: bool) -> bool:
            assert blocking is False
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
