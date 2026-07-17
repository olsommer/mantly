from langchain.messages import AIMessage


def test_create_llm_does_not_pass_invalid_callback_list():
    from automail.core.config import AdminConfig
    from automail.llm.factory import create_llm

    llm = create_llm(
        AdminConfig(
            llm_api_key="dummy",
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
        )
    )

    assert getattr(llm, "_mantly_usage_context")["provider"] == "gemini"


def test_record_usage_from_agent_result_metadata():
    from automail.llm.usage import collect_llm_usage, llm_stage, record_usage_from_result

    result = {
        "messages": [
            AIMessage(
                content="ok",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "total_tokens": 14,
                },
                response_metadata={"model_name": "gemini-3-flash-preview"},
            )
        ]
    }

    with collect_llm_usage() as collector:
        with llm_stage("response"):
            record_usage_from_result(
                result,
                {
                    "provider": "gemini",
                    "model": "gemini-3-flash-preview",
                    "billing_mode": "byok",
                },
            )

    usage = collector.aggregate()
    assert usage["inputTokens"] == 10
    assert usage["outputTokens"] == 4
    assert usage["totalTokens"] == 14
    assert usage["metadataAvailable"] is True
    assert usage["calls"][0]["stage"] == "response"


def test_record_usage_includes_enclosing_stage_duration(monkeypatch):
    from automail.llm import usage as usage_module

    result = {
        "messages": [
            AIMessage(
                content="ok",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "total_tokens": 14,
                },
                response_metadata={"model_name": "gemini-3-flash-preview"},
            )
        ]
    }
    clock = iter([100.0, 100.125])
    monkeypatch.setattr(usage_module.time, "perf_counter", lambda: next(clock))

    with usage_module.collect_llm_usage() as collector:
        with usage_module.llm_stage("issue_automation_grounding"):
            usage_module.record_usage_from_result(result)

    assert collector.events[0]["stage"] == "issue_automation_grounding"
    assert collector.events[0]["durationMs"] == 125


def test_store_llm_usage_events_persists_stage_duration(monkeypatch):
    from automail.db.pocketbase import chats

    posted: list[tuple[str, dict]] = []
    monkeypatch.setattr(chats, "generate_id", lambda: "usage-event-1")
    monkeypatch.setattr(
        chats,
        "_post",
        lambda path, data: posted.append((path, data)) or data,
    )

    chats.store_llm_usage_events(
        [
            {
                "stage": "response",
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "durationMs": 812,
                "totalTokens": 14,
            }
        ],
        project_id="project-1",
        run_id="run-1",
        background=False,
    )

    assert posted[0][0] == "/api/collections/llm_usage_events/records"
    assert posted[0][1]["duration_ms"] == 812
