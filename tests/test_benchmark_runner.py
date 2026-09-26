from geniehive_control.benchmark_runner import ChatBenchmarkCase, ChatBenchmarkWorkload, built_in_chat_workloads, run_chat_benchmark
from geniehive_control.evaluation import EvaluationWorkload
import pytest


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


def test_run_chat_benchmark_records_case_level_contract_results() -> None:
    workload = ChatBenchmarkWorkload(
        workload="chat.structured_json",
        system_prompt="Return JSON.",
        cases=[
            ChatBenchmarkCase(
                name="json_case",
                prompt="Return a JSON object with key title.",
                checks=[{"kind": "json"}, {"kind": "contains", "value": "title"}],
            )
        ],
    )

    def fake_request(url: str, headers: dict[str, str], payload: dict) -> dict:
        return {
            "choices": [{"message": {"role": "assistant", "content": '{"title":"Example"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            "timings": {"prompt_ms": 50.0, "predicted_per_second": 20.0},
        }

    report = run_chat_benchmark(
        base_url="http://127.0.0.1:8800",
        api_key="key",
        model="structured_extractor",
        workload=workload,
        request_fn=fake_request,
        observed_at=1775584000.0,
    )
    assert report.samples[0].results["case_results"] == [
        {
            "case_id": "json_case",
            "passed": True,
            "check_failures": [],
            "latency_ms": report.samples[0].results["case_results"][0]["latency_ms"],
            "prompt_tokens": 10,
            "completion_tokens": 4,
        }
    ]


def test_contract_hard_failure_overrides_rate_without_counting_nonempty_as_empty():
    contract=EvaluationWorkload(
        workload_id="test.contract", role_ids=["structured_extractor"], dataset_revision="test-v1",
        evaluator="geniehive_control.evaluation.check_response", minimum_pass_rate=0.5,
        hard_failures=["invalid_json"], cases=[
            {"case_id":"good","prompt":"valid","checks":[{"kind":"json"}]},
            {"case_id":"bad","prompt":"invalid","checks":[{"kind":"json"}]},
        ],
    )
    def request(url,headers,payload):
        content='{}' if payload["messages"][-1]["content"] == "valid" else 'not JSON'
        return {"choices":[{"message":{"content":content}}]}
    r=run_chat_benchmark(base_url="http://example.invalid",api_key="test",model="model",workload=contract,request_fn=request,observed_at=0).samples[0]
    assert r.observed_at == 0
    assert r.results["pass_rate"] == 0.5
    assert r.results["empty_visible_response_rate"] == 0
    assert r.results["hard_failure_codes"] == ["invalid_json"]
    assert r.results["contract_passed"] is False
    assert r.results["dataset_revision"] == "test-v1"
    assert r.results["evaluator"] == contract.evaluator
    contract.hard_failures=[]
    r=run_chat_benchmark(base_url="http://example.invalid",api_key="test",model="model",workload=contract,request_fn=request).samples[0]
    assert r.results["contract_passed"] is True


@pytest.mark.parametrize("cases", [[], [ChatBenchmarkCase(name="bad",prompt="anything",checks=[])]])
def test_invalid_workload_is_rejected_before_sending_requests(cases):
    def request(*args):
        pytest.fail("invalid contracts must not call a provider")
    with pytest.raises(ValueError):
        run_chat_benchmark(base_url="http://example.invalid",api_key="test",model="model",
                           workload=ChatBenchmarkWorkload(workload="invalid",system_prompt="test",cases=cases),request_fn=request)


def test_runner_does_not_claim_to_execute_an_unimplemented_evaluator():
    contract=EvaluationWorkload(workload_id="test",role_ids=["reviewer"],dataset_revision="test-v1",
                                evaluator="human_review",cases=[{"case_id":"one","prompt":"review"}])
    def request(*args):
        pytest.fail("unsupported evaluator must not send a request")
    with pytest.raises(ValueError,match="supports only"):
        run_chat_benchmark(base_url="http://example.invalid",api_key="test",model="model",workload=contract,request_fn=request)
