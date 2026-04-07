from __future__ import annotations

from typing import Any

from .request_policy import apply_request_policy, effective_chat_request_policy, select_target_asset
from .registry import Registry
from .routing import choose_upstream_model_id
from .upstream import UpstreamClient


class ProxyError(RuntimeError):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def _strip_reasoning_fields(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_strip_reasoning_fields(item) for item in payload]
    if not isinstance(payload, dict):
        return payload

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"reasoning_content", "reasoning"}:
            continue
        cleaned[key] = _strip_reasoning_fields(value)
    return cleaned

async def proxy_chat_completion(
    body: dict[str, Any],
    *,
    registry: Registry,
    upstream: UpstreamClient,
) -> Any:
    requested_model = body.get("model")
    if not requested_model:
        raise ProxyError("Missing 'model' in request body.", status_code=400)

    resolved = registry.resolve_route(requested_model, kind="chat")
    if resolved is None:
        raise ProxyError(f"Unknown model or role '{requested_model}'.", status_code=404)

    service = resolved.get("service")
    if service is None:
        raise ProxyError(f"No healthy chat target available for '{requested_model}'.", status_code=503)

    asset = select_target_asset(service, requested_model)
    role = resolved.get("role")
    combined_policy = effective_chat_request_policy(
        requested_model=requested_model,
        service=service,
        role=role,
        asset=asset,
    )

    upstream_body = apply_request_policy(dict(body), combined_policy)
    upstream_body["model"] = choose_upstream_model_id(requested_model, service)
    response = await upstream.chat_completions(service["endpoint"], upstream_body)
    return _strip_reasoning_fields(response)


async def proxy_embeddings(
    body: dict[str, Any],
    *,
    registry: Registry,
    upstream: UpstreamClient,
) -> Any:
    requested_model = body.get("model")
    if not requested_model:
        raise ProxyError("Missing 'model' in request body.", status_code=400)

    resolved = registry.resolve_route(requested_model, kind="embeddings")
    if resolved is None:
        raise ProxyError(f"Unknown model or role '{requested_model}'.", status_code=404)

    service = resolved.get("service")
    if service is None:
        raise ProxyError(f"No healthy embeddings target available for '{requested_model}'.", status_code=503)

    upstream_body = dict(body)
    upstream_body["model"] = choose_upstream_model_id(requested_model, service)
    return await upstream.embeddings(service["endpoint"], upstream_body)
