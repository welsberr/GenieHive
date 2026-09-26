from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from .benchmarks import BenchmarkReport, BenchmarkReportSample
from .evaluation import EvaluationCase, EvaluationWorkload, check_response


@dataclass(slots=True)
class ChatBenchmarkCase:
    name: str
    prompt: str
    max_completion_tokens: int = 120
    checks: list[dict[str, Any]] | None = None


@dataclass(slots=True)
class ChatBenchmarkWorkload:
    workload: str
    system_prompt: str
    cases: list[ChatBenchmarkCase]
    chat_template_kwargs: dict[str, Any] | None = None

    def as_evaluation_workload(self, *, role_ids: list[str], dataset_revision: str) -> EvaluationWorkload:
        return EvaluationWorkload(
            workload_id=self.workload,
            role_ids=role_ids,
            dataset_revision=dataset_revision,
            evaluator="geniehive_control.evaluation.check_response",
            system_prompt=self.system_prompt,
            chat_template_kwargs=self.chat_template_kwargs,
            cases=[
                {
                    "case_id": case.name,
                    "prompt": case.prompt,
                    "max_completion_tokens": case.max_completion_tokens,
                    "checks": case.checks if case.checks is not None else [{"kind": "nonempty"}],
                }
                for case in self.cases
            ],
        )


def built_in_chat_workloads() -> dict[str, ChatBenchmarkWorkload]:
    return {
        "chat.short_reasoning": ChatBenchmarkWorkload(
            workload="chat.short_reasoning",
            system_prompt=(
                "You are a concise and careful reasoning assistant. "
                "Return only a visible final answer. "
                "Do not spend tokens on hidden reasoning or an internal monologue."
            ),
            chat_template_kwargs={"enable_thinking": False},
            cases=[
                ChatBenchmarkCase(
                    name="short_reasoning_1",
                    prompt="In two short paragraphs, explain why a loaded healthy route should be preferred over a cold route. Return only the final answer text.",
                ),
                ChatBenchmarkCase(
                    name="short_reasoning_2",
                    prompt="Give a compact tradeoff summary for a service with lower latency but worse throughput than another. Return only the final answer text.",
                ),
            ],
        ),
        "chat.concise_support": ChatBenchmarkWorkload(
            workload="chat.concise_support",
            system_prompt="You are a concise support assistant. Return only a visible final answer.",
            cases=[
                ChatBenchmarkCase(
                    name="concise_support_1",
                    prompt="Reply with a short troubleshooting checklist for a local API endpoint returning 404. Return only the final answer text.",
                ),
                ChatBenchmarkCase(
                    name="concise_support_2",
                    prompt="Reply with a short checklist for checking a tmux-managed service that exited at startup. Return only the final answer text.",
                ),
            ],
        ),
    }


def run_chat_benchmark(
    *,
    base_url: str,
    api_key: str,
    model: str,
    workload: ChatBenchmarkWorkload | EvaluationWorkload,
    request_fn: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] | None = None,
    observed_at: float | None = None,
) -> BenchmarkReport:
    contract = workload if isinstance(workload, EvaluationWorkload) else None
    if contract is not None:
        if contract.evaluator != "geniehive_control.evaluation.check_response":
            raise ValueError("chat runner supports only the deterministic check_response evaluator")
        workload = ChatBenchmarkWorkload(
            workload=contract.workload_id,
            system_prompt=contract.system_prompt,
            cases=[ChatBenchmarkCase(name=c.case_id, prompt=c.prompt,
                                     max_completion_tokens=c.max_completion_tokens, checks=c.checks)
                   for c in contract.cases],
            chat_template_kwargs=contract.chat_template_kwargs,
        )
    if not workload.cases or len({c.name for c in workload.cases}) != len(workload.cases):
        raise ValueError("benchmark requires nonempty cases with unique names")
    for case in workload.cases:
        EvaluationCase(case_id=case.name, prompt=case.prompt,
                       max_completion_tokens=case.max_completion_tokens,
                       checks=case.checks if case.checks is not None else [{"kind": "nonempty"}])
    request = request_fn or _default_chat_request
    latencies_ms: list[float] = []
    ttfts_ms: list[float] = []
    tokens_per_sec_values: list[float] = []
    completion_tokens: list[int] = []
    prompt_tokens: list[int] = []
    case_results: list[dict[str, Any]] = []
    passed = 0
    responses_received = 0
    empty_visible_responses = 0

    for case in workload.cases:
        start = time.perf_counter()
        request_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": workload.system_prompt},
                {"role": "user", "content": case.prompt},
            ],
            "max_tokens": case.max_completion_tokens,
        }
        if workload.chat_template_kwargs:
            request_payload["chat_template_kwargs"] = dict(workload.chat_template_kwargs)

        payload = request(
            base_url.rstrip("/") + "/v1/chat/completions",
            {
                "X-Api-Key": api_key,
                "Content-Type": "application/json",
            },
            request_payload,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies_ms.append(elapsed_ms)

        usage = payload.get("usage", {})
        timings = payload.get("timings", {})
        prompt_tokens.append(int(usage.get("prompt_tokens", 0) or 0))
        completion_tokens.append(int(usage.get("completion_tokens", 0) or 0))
        responses_received += 1
        if isinstance(timings.get("prompt_ms"), (int, float)):
            ttfts_ms.append(float(timings["prompt_ms"]))
        if isinstance(timings.get("predicted_per_second"), (int, float)):
            tokens_per_sec_values.append(float(timings["predicted_per_second"]))
        elif isinstance(timings.get("predicted_ms"), (int, float)) and completion_tokens[-1] > 0 and float(timings["predicted_ms"]) > 0:
            tokens_per_sec_values.append((completion_tokens[-1] * 1000.0) / float(timings["predicted_ms"]))
        content = _visible_content(payload)
        checks_passed, check_failures = check_response(content, case.checks or [{"kind": "nonempty"}])
        case_results.append({
            "case_id": case.name,
            "passed": checks_passed,
            "check_failures": check_failures,
            "latency_ms": elapsed_ms,
            "prompt_tokens": prompt_tokens[-1],
            "completion_tokens": completion_tokens[-1],
        })
        if checks_passed:
            passed += 1
        if not content.strip():
            empty_visible_responses += 1

    contract_results: dict[str, Any] = {}
    if contract is not None:
        hard_failures = sorted({failure for result in case_results
                                for failure in result["check_failures"]
                                if failure in contract.hard_failures})
        contract_results = {
            "dataset_revision": contract.dataset_revision,
            "evaluator": contract.evaluator,
            "role_ids": contract.role_ids,
            "risk_class": contract.risk_class,
            "minimum_pass_rate": contract.minimum_pass_rate,
            "hard_failure_codes": hard_failures,
            "contract_passed": passed / len(workload.cases) >= contract.minimum_pass_rate and not hard_failures,
        }

    sample = BenchmarkReportSample(
        service_id=model,
        workload=workload.workload,
        observed_at=observed_at if observed_at is not None else time.time(),
        results={
            "case_count": len(workload.cases),
            "pass_rate": passed / max(1, len(workload.cases)),
            "response_rate": responses_received / max(1, len(workload.cases)),
            "empty_visible_response_rate": empty_visible_responses / max(1, len(workload.cases)),
            "p50_latency_ms": _median(latencies_ms),
            "ttft_ms": _median(ttfts_ms) if ttfts_ms else None,
            "tokens_per_sec": _median(tokens_per_sec_values) if tokens_per_sec_values else None,
            "prompt_tokens": int(sum(prompt_tokens) / max(1, len(prompt_tokens))),
            "completion_tokens": int(sum(completion_tokens) / max(1, len(completion_tokens))),
            "case_results": case_results,
            **contract_results,
        },
    )
    return BenchmarkReport(
        report_id=f"{model}-{workload.workload}",
        observed_at=sample.observed_at,
        source="geniehive-benchmark-runner",
        samples=[sample],
    )


def _default_chat_request(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _has_nonempty_content(payload: dict[str, Any]) -> bool:
    choices = payload.get("choices", [])
    if not choices:
        return False
    message = choices[0].get("message", {})
    if str(message.get("content", "")).strip():
        return True
    return bool(str(message.get("reasoning_content", "")).strip())


def _visible_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = str(message.get("content", "") or "")
    if content.strip():
        return content
    return str(message.get("reasoning_content", "") or "")
