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
    assert collector.events[0]["durationScope"] == "stage_wall_time"
    assert collector.events[0]["stageExecutionId"]
    assert collector.events[0]["usageRecordId"]
    assert collector.events[0]["usagePayloadIndex"] == 1
    assert collector.events[0]["usagePayloadCount"] == 1


def test_multiple_provider_usage_payloads_share_one_explicit_stage_timing(monkeypatch):
    from automail.llm import usage as usage_module

    result = {
        "messages": [
            AIMessage(
                content="tool call",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "total_tokens": 14,
                },
                response_metadata={"model_name": "gemini-3-flash-preview"},
            ),
            AIMessage(
                content="structured answer",
                usage_metadata={
                    "input_tokens": 6,
                    "output_tokens": 2,
                    "total_tokens": 8,
                },
                response_metadata={"model_name": "gemini-3-flash-preview"},
            ),
        ]
    }
    clock = iter([100.0, 100.250])
    monkeypatch.setattr(usage_module.time, "perf_counter", lambda: next(clock))

    with usage_module.collect_llm_usage() as collector:
        with usage_module.llm_stage("intent"):
            usage_module.record_usage_from_result(result)

    assert len(collector.events) == 2
    first, second = collector.events
    assert first["rawUsage"] != second["rawUsage"]
    assert first["durationMs"] == second["durationMs"] == 250
    assert first["durationScope"] == second["durationScope"] == "stage_wall_time"
    assert first["stageExecutionId"] == second["stageExecutionId"]
    assert first["usageRecordId"] == second["usageRecordId"]
    assert [first["usagePayloadIndex"], second["usagePayloadIndex"]] == [1, 2]
    assert first["usagePayloadCount"] == second["usagePayloadCount"] == 2

    usage = collector.aggregate()
    assert usage["totalTokens"] == 22
    assert usage["stageExecutions"] == [{
        "id": first["stageExecutionId"],
        "stage": "intent",
        "durationMs": 250,
        "durationScope": "stage_wall_time",
        "usageRecordCount": 1,
        "usageEventCount": 2,
    }]


def test_repeated_stage_names_get_distinct_execution_ids(monkeypatch):
    from automail.llm import usage as usage_module

    result = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
    )
    clock = iter([100.0, 100.100, 200.0, 200.200])
    monkeypatch.setattr(usage_module.time, "perf_counter", lambda: next(clock))

    with usage_module.collect_llm_usage() as collector:
        with usage_module.llm_stage("intent"):
            usage_module.record_usage_from_result(result)
        with usage_module.llm_stage("intent"):
            usage_module.record_usage_from_result(result)

    first, second = collector.events
    assert first["stage"] == second["stage"] == "intent"
    assert first["stageExecutionId"] != second["stageExecutionId"]
    assert [item["durationMs"] for item in collector.aggregate()["stageExecutions"]] == [100, 200]


def test_aggregate_usage_calls_keeps_legacy_events_without_timing_ids():
    from automail.llm.usage import aggregate_usage_calls

    legacy_call = {
        "stage": "intent",
        "durationMs": 500,
        "inputTokens": 7,
        "outputTokens": 2,
        "totalTokens": 9,
        "metadataAvailable": True,
    }

    usage = aggregate_usage_calls([legacy_call])

    assert usage["calls"] == [legacy_call]
    assert usage["totalTokens"] == 9
    assert usage["stageExecutions"] == []


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
                "durationScope": "stage_wall_time",
                "stageExecutionId": "stage-execution-1",
                "usageRecordId": "usage-record-1",
                "usagePayloadIndex": 1,
                "usagePayloadCount": 2,
                "totalTokens": 14,
            }
        ],
        project_id="project-1",
        run_id="run-1",
        background=False,
    )

    assert posted[0][0] == "/api/collections/llm_usage_events/records"
    assert posted[0][1]["duration_ms"] == 812
    assert posted[0][1]["duration_scope"] == "stage_wall_time"
    assert posted[0][1]["stage_execution_id"] == "stage-execution-1"
    assert posted[0][1]["usage_record_id"] == "usage-record-1"
    assert posted[0][1]["usage_payload_index"] == 1
    assert posted[0][1]["usage_payload_count"] == 2
