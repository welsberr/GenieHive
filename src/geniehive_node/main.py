from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import os
from pathlib import Path

from fastapi import FastAPI

from .config import NodeConfig, load_config
from .inventory import build_inventory, build_registration_payload
from .sync import ControlPlaneClient


def create_app(
    config_path: str | Path | None = None,
    *,
    sync_enabled: bool = True,
    control_client: ControlPlaneClient | None = None,
) -> FastAPI:
    cfg_path = config_path or os.environ.get("GENIEHIVE_NODE_CONFIG")
    cfg = load_config(cfg_path) if cfg_path else NodeConfig()
    sync_client = control_client or ControlPlaneClient(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        heartbeat_task: asyncio.Task[None] | None = None
        stop_event = asyncio.Event()
        if sync_enabled and sync_client.enabled:
            with suppress(Exception):
                await sync_client.register_once()
            heartbeat_task = asyncio.create_task(sync_client.heartbeat_loop(stop_event))
        try:
            yield
        finally:
            if heartbeat_task is not None:
                stop_event.set()
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task
            await sync_client.aclose()

    app = FastAPI(title="GenieHive Node", version="0.1.0", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.control_client = sync_client

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/node/inventory")
    async def inventory() -> dict:
        return build_inventory(cfg).model_dump()

    @app.get("/v1/node/registration")
    async def registration() -> dict:
        return build_registration_payload(cfg)

    return app


app = create_app()
