from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field

from .models import BenchmarkSample


class BenchmarkReportSample(BaseModel):
    service_id: str
    asset_id: str | None = None
    workload: str
    observed_at: float | None = None
    benchmark_id: str | None = None
    results: dict[str, object] = Field(default_factory=dict)


class BenchmarkReport(BaseModel):
    report_id: str | None = None
    observed_at: float | None = None
    source: str | None = None
    samples: list[BenchmarkReportSample] = Field(default_factory=list)


def load_benchmark_report(path: str | Path) -> BenchmarkReport:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return BenchmarkReport.model_validate(raw)


def report_to_samples(report: BenchmarkReport) -> list[BenchmarkSample]:
    samples: list[BenchmarkSample] = []
    for index, sample in enumerate(report.samples):
        observed_at = sample.observed_at if sample.observed_at is not None else report.observed_at
        if observed_at is None:
            raise ValueError("Benchmark report sample is missing observed_at and report has no default observed_at.")
        benchmark_id = sample.benchmark_id or _make_benchmark_id(report.report_id, sample, index, observed_at)
        payload = dict(sample.results)
        if report.source and "source" not in payload:
            payload["source"] = report.source
        samples.append(
            BenchmarkSample(
                benchmark_id=benchmark_id,
                service_id=sample.service_id,
                asset_id=sample.asset_id,
                workload=sample.workload,
                observed_at=observed_at,
                results=payload,
            )
        )
    return samples


def _make_benchmark_id(report_id: str | None, sample: BenchmarkReportSample, index: int, observed_at: float) -> str:
    digest = hashlib.sha1(
        "|".join(
            [
                report_id or "report",
                sample.service_id,
                sample.asset_id or "",
                sample.workload,
                str(observed_at),
                str(index),
            ]
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"bench_{digest}"
