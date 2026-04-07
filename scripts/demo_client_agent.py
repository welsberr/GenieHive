#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

import httpx


def fetch_models(client: httpx.Client, base_url: str, api_key: str) -> list[dict[str, Any]]:
    response = client.get(
        f"{base_url.rstrip('/')}/v1/models",
        headers={"X-Api-Key": api_key},
    )
    response.raise_for_status()
    return response.json().get("data", [])


def choose_chat_model(models: list[dict[str, Any]]) -> str:
    candidates = []
    for item in models:
        meta = item.get("geniehive", {})
        if meta.get("operation") != "chat":
            continue
        offload = meta.get("offload_hint", {})
        route_type = meta.get("route_type")
        suitability = offload.get("suitability", "")
        latency = meta.get("best_p50_latency_ms")
        if latency is None:
            latency = meta.get("observed", {}).get("p50_latency_ms")
        latency_score = float(latency) if latency is not None else float("inf")
        role_preference = 1 if route_type == "role" else 0
        suitability_rank = {
            "good_for_low_complexity": 3,
            "usable_for_background_tasks": 2,
            "available_but_slow": 1,
            "cold_only": 0,
        }.get(suitability, 0)
        candidates.append((suitability_rank, role_preference, -latency_score, item["id"]))
    if not candidates:
        raise SystemExit("No chat-capable models were advertised by GenieHive.")
    return max(candidates)[3]


def run_task(base_url: str, api_key: str, model: str, task: str) -> dict[str, Any]:
    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            headers={
                "X-Api-Key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a concise demo client agent."},
                    {"role": "user", "content": task},
                ],
            },
        )
        response.raise_for_status()
        return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise GenieHive as a small client agent.")
    parser.add_argument("--base-url", required=True, help="GenieHive control-plane base URL")
    parser.add_argument("--api-key", required=True, help="GenieHive client API key")
    parser.add_argument("--model", help="Explicit chat model or role alias to use")
    parser.add_argument("--task", help="Task text to send")
    parser.add_argument("--list-models", action="store_true", help="List advertised models and exit")
    args = parser.parse_args()

    with httpx.Client(timeout=30.0) as client:
        models = fetch_models(client, args.base_url, args.api_key)

    if args.list_models:
        print(json.dumps(models, indent=2))
        return

    if not args.task:
        raise SystemExit("--task is required unless --list-models is used.")

    model = args.model or choose_chat_model(models)
    print(f"Using model: {model}")
    result = run_task(args.base_url, args.api_key, model, args.task)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
