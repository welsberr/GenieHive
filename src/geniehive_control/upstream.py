from __future__ import annotations

from typing import Any, Protocol

import httpx


class UpstreamError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AsyncPoster(Protocol):
    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str] | None = None) -> object:
        ...


class UpstreamClient:
    def __init__(self, client: AsyncPoster | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=60.0)
        )

    async def chat_completions(
        self,
        base_url: str,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        url = base_url.rstrip("/") + "/v1/chat/completions"
        response = await self._client.post(url, json=body, headers=headers)
        status_code = getattr(response, "status_code", 200)
        if status_code >= 400:
            text = getattr(response, "text", "")
            raise UpstreamError(
                text or f"upstream error from {url}",
                status_code=status_code,
            )
        if hasattr(response, "json"):
            return response.json()
        return response

    async def embeddings(
        self,
        base_url: str,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        url = base_url.rstrip("/") + "/v1/embeddings"
        response = await self._client.post(url, json=body, headers=headers)
        status_code = getattr(response, "status_code", 200)
        if status_code >= 400:
            text = getattr(response, "text", "")
            raise UpstreamError(
                text or f"upstream error from {url}",
                status_code=status_code,
            )
        if hasattr(response, "json"):
            return response.json()
        return response

    async def aclose(self) -> None:
        if self._owns_client and isinstance(self._client, httpx.AsyncClient):
            await self._client.aclose()
