from __future__ import annotations

import asyncio
from contextlib import suppress

import httpx

from .registry import Registry


class ServiceProber:
    """Periodically probes registered service endpoints and updates health state."""

    def __init__(self, registry: Registry, *, timeout_s: float = 5.0) -> None:
        self._registry = registry
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=timeout_s, read=timeout_s, write=timeout_s, pool=timeout_s)
        )

    async def probe_once(self) -> dict[str, str]:
        """Probe all registered services. Returns mapping of service_id → observed health."""
        services = self._registry.list_services()
        results: dict[str, str] = {}
        for service in services:
            health = await self._probe_service(service)
            current = service["state"].get("health")
            if health != current:
                self._registry.update_service_health(service["service_id"], health)
            results[service["service_id"]] = health
        return results

    async def _probe_service(self, service: dict) -> str:
        endpoint = service.get("endpoint", "")
        if not endpoint:
            return service["state"].get("health") or "unknown"
        try:
            response = await self._client.get(endpoint.rstrip("/") + "/health")
            if response.status_code < 400:
                return "healthy"
            if response.status_code in (404, 405):
                # Runtime doesn't implement GET /health; fall back to the
                # standard OpenAI-compatible models list (works for vLLM etc.).
                response2 = await self._client.get(endpoint.rstrip("/") + "/v1/models")
                return "healthy" if response2.status_code < 400 else "unhealthy"
            return "unhealthy"
        except Exception:
            return "unhealthy"

    async def probe_loop(self, stop_event: asyncio.Event, interval_s: float) -> None:
        while not stop_event.is_set():
            with suppress(Exception):
                await self.probe_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            except asyncio.TimeoutError:
                continue

    async def aclose(self) -> None:
        await self._client.aclose()
