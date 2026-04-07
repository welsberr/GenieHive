from geniehive_control.benchmark_runner import ChatBenchmarkCase, ChatBenchmarkWorkload, built_in_chat_workloads, run_chat_benchmark


def test_built_in_chat_workloads_exist() -> None:
    workloads = built_in_chat_workloads()

    assert "chat.short_reasoning" in workloads
    assert workloads["chat.short_reasoning"].cases
    assert workloads["chat.short_reasoning"].chat_template_kwargs == {"enable_thinking": False}


def test_run_chat_benchmark_generates_report() -> None:
    workload = ChatBenchmarkWorkload(
        workload="chat.short_reasoning",
        system_prompt="You are concise.",
        cases=[
            ChatBenchmarkCase(name="case1", prompt="Explain route selection briefly."),
            ChatBenchmarkCase(name="case2", prompt="Explain latency versus throughput briefly."),
        ],
    )

    def fake_request(url: str, headers: dict[str, str], payload: dict) -> dict:
        assert url.endswith("/v1/chat/completions")
        assert payload["model"] == "general_assistant"
        assert "chat_template_kwargs" not in payload
        return {
            "choices": [{"message": {"role": "assistant", "content": "Benchmark response."}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            "timings": {"prompt_ms": 120.0, "predicted_per_second": 25.0},
        }

    report = run_chat_benchmark(
        base_url="http://127.0.0.1:8800",
        api_key="change-me-client-key",
        model="general_assistant",
        workload=workload,
        request_fn=fake_request,
        observed_at=1775584000.0,
    )

    sample = report.samples[0]
    assert report.source == "geniehive-benchmark-runner"
    assert sample.workload == "chat.short_reasoning"
    assert sample.results["case_count"] == 2
    assert sample.results["pass_rate"] == 1.0
    assert sample.results["response_rate"] == 1.0
    assert sample.results["empty_visible_response_rate"] == 0.0
    assert sample.results["tokens_per_sec"] == 25.0
    assert sample.observed_at == 1775584000.0


def test_run_chat_benchmark_treats_reasoning_content_as_a_pass() -> None:
    workload = ChatBenchmarkWorkload(
        workload="chat.short_reasoning",
        system_prompt="You are concise.",
        cases=[ChatBenchmarkCase(name="case1", prompt="Explain route selection briefly.")],
    )

    def fake_request(url: str, headers: dict[str, str], payload: dict) -> dict:
        return {
            "choices": [{"message": {"role": "assistant", "content": "", "reasoning_content": "Reasoning only."}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            "timings": {"prompt_ms": 120.0, "predicted_per_second": 25.0},
        }

    report = run_chat_benchmark(
        base_url="http://127.0.0.1:8800",
        api_key="change-me-client-key",
        model="general_assistant",
        workload=workload,
        request_fn=fake_request,
        observed_at=1775584000.0,
    )

    assert report.samples[0].results["pass_rate"] == 1.0
    assert report.samples[0].results["empty_visible_response_rate"] == 0.0


def test_run_chat_benchmark_includes_chat_template_kwargs_when_configured() -> None:
    workload = ChatBenchmarkWorkload(
        workload="chat.short_reasoning",
        system_prompt="You are concise.",
        chat_template_kwargs={"enable_thinking": False},
        cases=[ChatBenchmarkCase(name="case1", prompt="Explain route selection briefly.")],
    )

    def fake_request(url: str, headers: dict[str, str], payload: dict) -> dict:
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        return {
            "choices": [{"message": {"role": "assistant", "content": "Visible response."}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            "timings": {"prompt_ms": 120.0, "predicted_per_second": 25.0},
        }

    report = run_chat_benchmark(
        base_url="http://127.0.0.1:8800",
        api_key="change-me-client-key",
        model="general_assistant",
        workload=workload,
        request_fn=fake_request,
        observed_at=1775584000.0,
    )

    assert report.samples[0].results["pass_rate"] == 1.0
