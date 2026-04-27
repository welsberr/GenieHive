from __future__ import annotations

from typing import Any, AsyncGenerator, Protocol

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

    async def chat_completions_stream(
        self,
        base_url: str,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> AsyncGenerator[bytes, None]:
        """Yield raw SSE bytes from an upstream chat completions endpoint.

        Raises ``UpstreamError`` before the first yield if the upstream returns a
        non-2xx status.  Requires a real ``httpx.AsyncClient`` — raises immediately
        if an injected mock was provided instead.
        """
        if not isinstance(self._client, httpx.AsyncClient):
            raise UpstreamError(
                "streaming requires a real httpx client; not supported by the injected mock",
                status_code=500,
            )
        url = base_url.rstrip("/") + "/v1/chat/completions"
        async with self._client.stream("POST", url, json=body, headers=headers or {}) as response:
            if response.status_code >= 400:
                content = await response.aread()
                raise UpstreamError(
                    content.decode(errors="replace") or f"upstream error from {url}",
                    status_code=response.status_code,
                )
            async for chunk in response.aiter_bytes():
                yield chunk

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

    async def transcriptions(
        self,
        base_url: str,
        *,
        file_content: bytes,
        file_name: str,
        file_content_type: str,
        form_data: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> Any:
        if not isinstance(self._client, httpx.AsyncClient):
            raise UpstreamError(
                "transcription requires a real httpx client; multipart is not supported by the injected mock",
                status_code=500,
            )
        url = base_url.rstrip("/") + "/v1/audio/transcriptions"
        response = await self._client.post(
            url,
            data=form_data,
            files={"file": (file_name, file_content, file_content_type)},
            headers=headers or {},
        )
        if response.status_code >= 400:
            raise UpstreamError(
                response.text or f"upstream error from {url}",
                status_code=response.status_code,
            )
        return response.json()

    async def aclose(self) -> None:
        if self._owns_client and isinstance(self._client, httpx.AsyncClient):
            await self._client.aclose()
