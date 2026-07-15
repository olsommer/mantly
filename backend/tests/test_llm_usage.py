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
