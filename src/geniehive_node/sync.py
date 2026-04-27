from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Protocol

import httpx

from .config import NodeConfig
from .discovery import enrich_service_assets
from .inventory import build_heartbeat_payload, build_registration_payload


class AsyncPoster(Protocol):
    async def post(self, url: str, *, json: dict, headers: dict[str, str] | None = None) -> object:
        ...


class ControlPlaneClient:
    def __init__(self, cfg: NodeConfig, http_client: AsyncPoster | None = None) -> None:
        self.cfg = cfg
        self._owns_client = http_client is None
        self._registered = False
        self._http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=30.0)
        )
        # Separate client used exclusively for upstream model discovery GETs.
        # Only allocated when at least one service has discover_protocol set.
        _needs_discovery = any(s.discover_protocol for s in cfg.services)
        self._discovery_client: httpx.AsyncClient | None = (
            httpx.AsyncClient(timeout=httpx.Timeout(5.0)) if _needs_discovery else None
        )

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.control_plane.base_url)

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.cfg.control_plane.node_api_key:
            headers["X-GenieHive-Node-Key"] = self.cfg.control_plane.node_api_key
        return headers

    async def register_once(self) -> None:
        if not self.enabled:
            return
        url = str(self.cfg.control_plane.base_url).rstrip("/") + "/v1/nodes/register"
        response = await self._http.post(
            url,
            json=build_registration_payload(self.cfg),
            headers=self._headers(),
        )
        if isinstance(response, httpx.Response):
            response.raise_for_status()
        self._registered = True

    async def heartbeat_once(self) -> None:
        if not self.enabled:
            return
        if not self._registered:
            await self.register_once()
        url = str(self.cfg.control_plane.base_url).rstrip("/") + "/v1/nodes/heartbeat"
        payload = build_heartbeat_payload(self.cfg)
        if self._discovery_client is not None:
            reg_services = build_registration_payload(self.cfg).get("services", [])
            enriched = [
                await enrich_service_assets(
                    svc_dict,
                    protocol=svc_cfg.discover_protocol,
                    client=self._discovery_client,
                )
                for svc_dict, svc_cfg in zip(reg_services, self.cfg.services)
            ]
            payload["services"] = enriched
        response = await self._http.post(url, json=payload, headers=self._headers())
        if isinstance(response, httpx.Response):
            if response.status_code == 404:
                self._registered = False
                await self.register_once()
                response = await self._http.post(url, json=payload, headers=self._headers())
            response.raise_for_status()

    async def heartbeat_loop(self, stop_event: asyncio.Event) -> None:
        interval = max(self.cfg.control_plane.heartbeat_interval_s, 0.1)
        while not stop_event.is_set():
            with suppress(Exception):
                await self.heartbeat_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

    async def aclose(self) -> None:
        if self._owns_client and isinstance(self._http, httpx.AsyncClient):
            await self._http.aclose()
        if self._discovery_client is not None:
            await self._discovery_client.aclose()
