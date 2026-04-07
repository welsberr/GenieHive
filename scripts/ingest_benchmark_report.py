#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os

import httpx

from geniehive_control.benchmarks import load_benchmark_report, report_to_samples


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load a benchmark report JSON file and ingest its samples into GenieHive.")
    parser.add_argument("input", help="Path to benchmark report JSON")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("GENIEHIVE_CONTROL_BASE_URL", "http://127.0.0.1:8800"),
        help="GenieHive control base URL",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("GENIEHIVE_CLIENT_API_KEY", "change-me-client-key"),
        help="GenieHive client API key",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = load_benchmark_report(args.input)
    samples = report_to_samples(report)
    payload = {"samples": [sample.model_dump() for sample in samples]}
    response = httpx.post(
        args.base_url.rstrip("/") + "/v1/cluster/benchmarks",
        json=payload,
        headers={"X-Api-Key": args.api_key},
        timeout=30.0,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
