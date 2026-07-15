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

    def fake_get_judge_llm(config_path=None, tenant_id=None):
        calls["config_path"] = config_path
        calls["tenant_id"] = tenant_id
        return fake_llm

    monkeypatch.setattr(eval_judge, "_get_judge_llm", fake_get_judge_llm)
    config_path = tmp_path / "config.json"

    result = eval_judge.run_judge({}, {}, has_response=False, config_path=config_path, tenant_id="tenant-a")

    assert result.overall == 100
    assert calls == {"config_path": config_path, "tenant_id": "tenant-a"}
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

    monkeypatch.setattr(eval_judge, "_get_judge_llm", lambda config_path=None, tenant_id=None: ListContentLLM())

    result = eval_judge.run_judge({}, {}, has_response=False, config_path=tmp_path / "config.json")

    assert result.overall == 100
