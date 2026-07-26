from automail.evals import judge as eval_judge


class _FakeLLM:
    messages = None

    def invoke(self, messages):
        self.messages = messages

        class Response:
            content = (
                '{"identity":{"score":100,"reasoning":"ok"},'
                '"intent":{"score":100,"reasoning":"ok"},'
                '"actions":{"score":100,"reasoning":"ok"}}'
            )

        return Response()


def test_run_judge_uses_shared_llm_factory(monkeypatch, tmp_path):
    calls = {}
    fake_llm = _FakeLLM()

    def fake_get_judge_llm(config_path=None, tenant_id=None, **kwargs):
        calls["config_path"] = config_path
        calls["tenant_id"] = tenant_id
        calls.update(kwargs)
        return fake_llm

    monkeypatch.setattr(eval_judge, "_get_judge_llm", fake_get_judge_llm)
    config_path = tmp_path / "config.json"

    result = eval_judge.run_judge({}, {}, has_response=False, config_path=config_path, tenant_id="tenant-a")

    assert result.overall == 100
    assert calls == {
        "config_path": config_path,
        "tenant_id": "tenant-a",
        "timeout": 300,
        "max_retries": 5,
    }
    assert fake_llm.messages is not None
    assert len(fake_llm.messages) == 2


def test_run_judge_accepts_list_message_content(monkeypatch, tmp_path):
    class ListContentLLM:
        def invoke(self, messages):
            class Response:
                content = [
                    {
                        "type": "text",
                        "text": (
                            '{"identity":{"score":100,"reasoning":"ok"},'
                            '"intent":{"score":100,"reasoning":"ok"},'
                            '"actions":{"score":100,"reasoning":"ok"}}'
                        ),
                    }
                ]

            return Response()

    monkeypatch.setattr(
        eval_judge,
        "_get_judge_llm",
        lambda config_path=None, tenant_id=None, **kwargs: ListContentLLM(),
    )

    result = eval_judge.run_judge({}, {}, has_response=False, config_path=tmp_path / "config.json")

    assert result.overall == 100


def test_run_judge_forwards_per_call_timeout_and_retry_overrides(monkeypatch) -> None:
    calls = {}

    def fake_get_judge_llm(**kwargs):
        calls.update(kwargs)
        return _FakeLLM()

    monkeypatch.setattr(eval_judge, "_get_judge_llm", fake_get_judge_llm)

    result = eval_judge.run_judge(
        {},
        {},
        has_response=False,
        timeout=60,
        max_retries=0,
    )

    assert result.overall == 100
    assert calls["timeout"] == 60
    assert calls["max_retries"] == 0


def test_get_judge_llm_forwards_bounds_to_shared_factory(monkeypatch) -> None:
    from automail import llm as llm_module

    config = object()
    sentinel_llm = object()
    calls = {}
    monkeypatch.setattr(eval_judge, "read_config", lambda **_kwargs: config)
    monkeypatch.setattr(
        llm_module,
        "resolve_effective_config",
        lambda resolved, *_args: resolved,
    )

    def fake_create_llm(resolved, **kwargs):
        calls["config"] = resolved
        calls.update(kwargs)
        return sentinel_llm

    monkeypatch.setattr(llm_module, "create_llm", fake_create_llm)

    result = eval_judge._get_judge_llm(timeout=60, max_retries=0)

    assert result is sentinel_llm
    assert calls == {
        "config": config,
        "timeout": 60,
        "max_retries": 0,
        "temperature": 0.1,
    }
