from __future__ import annotations

import httpx


async def discover_ollama_assets(
    endpoint: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 5.0,
) -> list[dict]:
    """Query Ollama's GET /api/tags and return available (not necessarily loaded) model assets.

    Sets ``"loaded": False`` for all entries — callers should follow up with
    :func:`query_ollama_ps` to determine which models are currently in VRAM.
    Returns an empty list on any error.
    """
    url = endpoint.rstrip("/") + "/api/tags"
    _owns_client = client is None
    _client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(connect=timeout, read=timeout, write=timeout, pool=timeout)
    )
    try:
        response = await _client.get(url)
        if response.status_code != 200:
            return []
        data = response.json()
        return [
            {"asset_id": model["name"], "loaded": False}
            for model in data.get("models", [])
            if model.get("name")
        ]
    except Exception:
        return []
    finally:
        if _owns_client:
            await _client.aclose()


async def _get_ollama_ps_models(
    endpoint: str,
    *,
    client: httpx.AsyncClient,
    timeout: float = 5.0,
) -> list[dict]:
    """Query Ollama's GET /api/ps and return the raw model list.

    Returns an empty list on any error.  Caller owns the httpx client lifetime.
    """
    url = endpoint.rstrip("/") + "/api/ps"
    try:
        response = await client.get(url)
        if response.status_code != 200:
            return []
        data = response.json()
        return [m for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


async def query_ollama_ps(
    endpoint: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 5.0,
) -> frozenset[str]:
    """Query Ollama's GET /api/ps and return names of currently VRAM-loaded models.

    Returns an empty frozenset on any error so callers can treat this as a
    best-effort enrichment.
    """
    _owns_client = client is None
    _client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(connect=timeout, read=timeout, write=timeout, pool=timeout)
    )
    try:
        models = await _get_ollama_ps_models(endpoint, client=_client, timeout=timeout)
        return frozenset(m["name"] for m in models)
    finally:
        if _owns_client:
            await _client.aclose()


async def discover_openai_models(
    endpoint: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 5.0,
) -> list[dict]:
    """Query an OpenAI-compatible GET /v1/models endpoint and return discovered assets.

    Works with vLLM, llama.cpp server (with --api-key or open), and any other
    runtime that implements the standard models list format.  Returns an empty
    list on any error.
    """
    url = endpoint.rstrip("/") + "/v1/models"
    _owns_client = client is None
    _client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(connect=timeout, read=timeout, write=timeout, pool=timeout)
    )
    try:
        response = await _client.get(url)
        if response.status_code != 200:
            return []
        data = response.json()
        return [
            {"asset_id": model["id"], "loaded": True}
            for model in data.get("data", [])
            if model.get("id")
        ]
    except Exception:
        return []
    finally:
        if _owns_client:
            await _client.aclose()


async def enrich_service_assets(
    service: dict,
    *,
    protocol: str | None,
    client: httpx.AsyncClient | None = None,
    timeout: float = 5.0,
) -> dict:
    """Return a copy of *service* with assets enriched from upstream discovery.

    For ``"ollama"`` protocol:
    - Queries ``/api/tags`` for the full available-model list
    - Queries ``/api/ps`` for currently VRAM-loaded models
    - Marks each asset ``loaded: True`` only if its name appears in ``/api/ps``
    - Updates the ``loaded`` state of existing (statically configured) assets too
    - Adds newly discovered assets that were absent from the static config

    For ``"openai"`` protocol:
    - Queries ``/v1/models`` and marks all returned models as ``loaded: True``
    - Adds newly discovered models; does not modify existing static assets

    Any value other than ``"ollama"`` or ``"openai"`` (including ``None``) skips
    discovery and returns *service* unchanged.  If discovery returns nothing the
    original service dict is returned unchanged.
    """
    if not protocol:
        return service

    endpoint = service.get("endpoint", "")
    if not endpoint:
        return service

    if protocol == "ollama":
        available = await discover_ollama_assets(endpoint, client=client, timeout=timeout)
        if not available:
            return service
        _owns_ps_client = client is None
        _ps_client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=timeout, read=timeout, write=timeout, pool=timeout)
        )
        try:
            ps_models = await _get_ollama_ps_models(endpoint, client=_ps_client, timeout=timeout)
        finally:
            if _owns_ps_client:
                await _ps_client.aclose()
        loaded_names = frozenset(m["name"] for m in ps_models)
        discovered = [
            {**asset, "loaded": asset["asset_id"] in loaded_names}
            for asset in available
        ]
        ollama_observed: dict = {
            "loaded_model_count": len(ps_models),
            "vram_used_bytes": sum(m.get("size_in_vram", 0) for m in ps_models),
        }
    elif protocol == "openai":
        discovered = await discover_openai_models(endpoint, client=client, timeout=timeout)
        ollama_observed = None
    else:
        return service

    if not discovered:
        return service

    # Build merged asset list:
    # 1. Start with statically configured assets, updating loaded state if discovered.
    # 2. Append any newly discovered assets not in the static config.
    existing_by_id = {a["asset_id"]: a for a in service.get("assets", [])}
    merged: list[dict] = []
    for existing in service.get("assets", []):
        disc = next((d for d in discovered if d["asset_id"] == existing["asset_id"]), None)
        if disc is not None:
            # Update loaded state from discovery; preserve all other static fields.
            merged.append({**existing, "loaded": disc["loaded"]})
        else:
            merged.append(existing)
    for asset in discovered:
        if asset["asset_id"] not in existing_by_id:
            merged.append(asset)

    result = {**service, "assets": merged}
    if ollama_observed:
        existing_observed = service.get("observed") or {}
        result["observed"] = {**existing_observed, **ollama_observed}
    return result
