from __future__ import annotations

import json
from typing import Any, AsyncGenerator

from fastapi import UploadFile

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


def _strip_reasoning_from_sse_chunk(chunk: bytes) -> bytes:
    """Strip reasoning fields from SSE chunk data lines when parseable."""
    lines = chunk.split(b"\n")
    out: list[bytes] = []
    for line in lines:
        if line.startswith(b"data: ") and not line.startswith(b"data: [DONE]"):
            try:
                data = json.loads(line[6:])
                data = _strip_reasoning_fields(data)
                out.append(b"data: " + json.dumps(data, separators=(",", ":")).encode())
            except Exception:
                out.append(line)
        else:
            out.append(line)
    return b"\n".join(out)


def _prepare_chat_upstream(
    body: dict[str, Any],
    *,
    registry: Registry,
) -> tuple[dict, dict[str, Any]]:
    """Resolve chat route and build the upstream request body.

    Returns ``(service, upstream_body)``.  Raises :class:`ProxyError` if routing
    fails.  This function is synchronous — it performs only registry look-ups and
    dict manipulation, no I/O.
    """
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
    return service, upstream_body


async def proxy_chat_completion(
    body: dict[str, Any],
    *,
    registry: Registry,
    upstream: UpstreamClient,
) -> Any:
    service, upstream_body = _prepare_chat_upstream(body, registry=registry)
    response = await upstream.chat_completions(service["endpoint"], upstream_body)
    return _strip_reasoning_fields(response)


async def stream_chat_completion(
    service: dict,
    upstream_body: dict[str, Any],
    *,
    upstream: UpstreamClient,
) -> AsyncGenerator[bytes, None]:
    """Yield SSE bytes from upstream, stripping reasoning fields from each chunk."""
    async for chunk in upstream.chat_completions_stream(service["endpoint"], upstream_body):
        yield _strip_reasoning_from_sse_chunk(chunk)


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


async def proxy_transcription(
    *,
    model: str,
    file: UploadFile,
    language: str | None = None,
    prompt: str | None = None,
    response_format: str | None = None,
    temperature: float | None = None,
    registry: Registry,
    upstream: UpstreamClient,
) -> Any:
    resolved = registry.resolve_route(model, kind="transcription")
    if resolved is None:
        raise ProxyError(f"Unknown model or role '{model}'.", status_code=404)

    service = resolved.get("service")
    if service is None:
        raise ProxyError(f"No healthy transcription target available for '{model}'.", status_code=503)

    file_content = await file.read()
    form_data: dict[str, str] = {"model": choose_upstream_model_id(model, service)}
    if language is not None:
        form_data["language"] = language
    if prompt is not None:
        form_data["prompt"] = prompt
    if response_format is not None:
        form_data["response_format"] = response_format
    if temperature is not None:
        form_data["temperature"] = str(temperature)

    return await upstream.transcriptions(
        service["endpoint"],
        file_content=file_content,
        file_name=file.filename or "audio",
        file_content_type=file.content_type or "application/octet-stream",
        form_data=form_data,
    )
