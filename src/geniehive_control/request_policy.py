from __future__ import annotations

import copy
import re
from typing import Any


def deep_merge_defaults(payload: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(payload)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = copy.deepcopy(value)
            continue
        if isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge_defaults(merged[key], value)
    return merged


def deep_merge_override(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = deep_merge_override(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def apply_system_prompt(messages: list[dict[str, Any]], prompt: str, position: str) -> list[dict[str, Any]]:
    if any(message.get("role") == "system" and message.get("content") == prompt for message in messages):
        return messages

    injected = {"role": "system", "content": prompt}
    if position == "append":
        return [*messages, injected]
    if position == "replace":
        updated = list(messages)
        for index, message in enumerate(updated):
            if message.get("role") == "system":
                updated[index] = injected
                return updated
        return [injected, *updated]
    return [injected, *messages]


def apply_request_policy(body: dict[str, Any], policy: dict[str, Any] | None) -> dict[str, Any]:
    if not policy:
        return dict(body)

    shaped = deep_merge_defaults(body, policy.get("body_defaults", {}) or {})
    system_prompt = policy.get("system_prompt")
    if not system_prompt:
        return shaped

    messages = shaped.get("messages")
    if not isinstance(messages, list):
        return shaped

    normalized_messages = [message for message in messages if isinstance(message, dict)]
    shaped["messages"] = apply_system_prompt(
        normalized_messages,
        system_prompt,
        str(policy.get("system_prompt_position") or "prepend"),
    )
    return shaped


def merge_request_policies(*policies: dict[str, Any] | None) -> dict[str, Any] | None:
    combined: dict[str, Any] = {}
    for policy in policies:
        if not policy:
            continue
        body_defaults = policy.get("body_defaults") or {}
        if body_defaults:
            combined["body_defaults"] = deep_merge_override(combined.get("body_defaults", {}), body_defaults)
        if policy.get("system_prompt"):
            combined["system_prompt"] = policy["system_prompt"]
            combined["system_prompt_position"] = policy.get("system_prompt_position", "prepend")
    return combined or None


def select_target_asset(service: dict[str, Any], requested_model: str) -> dict[str, Any] | None:
    assets = service.get("assets", [])
    for asset in assets:
        if asset.get("asset_id") == requested_model:
            return asset
    for asset in assets:
        if asset.get("loaded") and asset.get("asset_id"):
            return asset
    for asset in assets:
        if asset.get("asset_id"):
            return asset
    return None


def looks_like_qwen3(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", value.lower())
    return normalized.startswith("qwen3")


def infer_chat_request_policy(requested_model: str, service: dict[str, Any], asset: dict[str, Any] | None) -> dict[str, Any] | None:
    identifiers = [requested_model, service.get("service_id", "")]
    if asset is not None:
        identifiers.append(asset.get("asset_id", ""))
    identifiers.extend(asset_item.get("asset_id", "") for asset_item in service.get("assets", []))
    if any(looks_like_qwen3(identifier) for identifier in identifiers if identifier):
        return {
            "body_defaults": {
                "chat_template_kwargs": {
                    "enable_thinking": False,
                }
            }
        }
    return None


def effective_chat_request_policy(
    *,
    requested_model: str,
    service: dict[str, Any],
    role: dict[str, Any] | None = None,
    asset: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return merge_request_policies(
        infer_chat_request_policy(requested_model, service, asset),
        (asset or {}).get("request_policy"),
        ((role or {}).get("prompt_policy") or {}).get("request_policy"),
    )
