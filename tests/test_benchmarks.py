from pathlib import Path

from geniehive_control.benchmarks import load_benchmark_report, report_to_samples


def test_load_benchmark_report_and_generate_sample_ids(tmp_path: Path) -> None:
    report_path = tmp_path / "bench.json"
    report_path.write_text(
        """
{
  "report_id": "p40-short-reasoning",
  "observed_at": 1775583000.0,
  "source": "local-smoke",
  "samples": [
    {
      "service_id": "p40-box/chat/gpu1-secondary",
      "asset_id": "Qwen3.5-9B-Q5_K_M",
      "workload": "chat.short_reasoning",
      "results": {
        "ttft_ms": 900,
        "tokens_per_sec": 30,
        "quality_score": 0.9
      }
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    report = load_benchmark_report(report_path)
    samples = report_to_samples(report)

    assert report.report_id == "p40-short-reasoning"
    assert len(samples) == 1
    assert samples[0].benchmark_id.startswith("bench_")
    assert samples[0].observed_at == 1775583000.0
    assert samples[0].results["source"] == "local-smoke"


def test_report_to_samples_preserves_explicit_sample_ids(tmp_path: Path) -> None:
    report_path = tmp_path / "bench.json"
    report_path.write_text(
        """
{
  "observed_at": 1775583000.0,
  "samples": [
    {
      "benchmark_id": "bench-explicit",
      "service_id": "p40-box/chat/gpu0-primary",
      "workload": "chat.concise_support",
      "results": {
        "tokens_per_sec": 24
      }
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    report = load_benchmark_report(report_path)
    samples = report_to_samples(report)

    assert samples[0].benchmark_id == "bench-explicit"
    assert samples[0].workload == "chat.concise_support"
