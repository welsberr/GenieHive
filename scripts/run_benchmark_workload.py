#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from geniehive_control.benchmark_runner import built_in_chat_workloads, run_chat_benchmark


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a built-in chat benchmark workload against a GenieHive route or model.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8800", help="GenieHive control base URL")
    parser.add_argument("--api-key", default="change-me-client-key", help="GenieHive client API key")
    parser.add_argument("--model", required=True, help="Role, service, or direct asset/model id to benchmark")
    parser.add_argument(
        "--workload",
        required=True,
        choices=sorted(built_in_chat_workloads().keys()),
        help="Built-in benchmark workload to run",
    )
    parser.add_argument("--output", help="Optional path to write the benchmark report JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    workload = built_in_chat_workloads()[args.workload]
    report = run_chat_benchmark(
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        workload=workload,
    )
    rendered = json.dumps(report.model_dump(), indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
