from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .auth import require_client_auth, require_node_auth
from .chat import ProxyError, proxy_chat_completion, proxy_embeddings
from .config import ControlConfig, load_config
from .models import BenchmarkIngestRequest, HostHeartbeat, HostRegistration, RouteMatchRequest, RouteMatchResponse
from .roles import load_role_catalog
from .registry import Registry
from .upstream import UpstreamClient, UpstreamError


def create_app(
    config_path: str | Path | None = None,
    *,
    upstream_client: UpstreamClient | None = None,
) -> FastAPI:
    cfg_path = config_path or os.environ.get("GENIEHIVE_CONTROL_CONFIG")
    cfg = load_config(cfg_path) if cfg_path else ControlConfig()
    registry = Registry(cfg.storage.sqlite_path)
    roles_path = cfg.roles_path or os.environ.get("GENIEHIVE_ROLES_CONFIG")
    if roles_path:
        registry.upsert_roles(load_role_catalog(roles_path).roles)
    upstream = upstream_client or UpstreamClient()

    app = FastAPI(title="GenieHive Control", version="0.1.0")
    app.state.cfg = cfg
    app.state.registry = registry
    app.state.upstream = upstream

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/nodes/register")
    async def register_node(request: Request, _=Depends(require_node_auth)) -> dict:
        payload = await request.json()
        reg = HostRegistration.model_validate(payload)
        host = request.app.state.registry.register_host(reg)
        return {"status": "ok", "host": host}

    @app.post("/v1/nodes/heartbeat")
    async def heartbeat_node(request: Request, _=Depends(require_node_auth)):
        payload = await request.json()
        hb = HostHeartbeat.model_validate(payload)
        host = request.app.state.registry.heartbeat_host(hb)
        if host is None:
            return JSONResponse(status_code=404, content={"error": "unknown_host", "host_id": hb.host_id})
        return {"status": "ok", "host": host}

    @app.get("/v1/cluster/hosts")
    async def list_hosts(request: Request, _=Depends(require_client_auth)) -> dict:
        return {"object": "list", "data": request.app.state.registry.list_hosts()}

    @app.get("/v1/models")
    async def list_models(request: Request, _=Depends(require_client_auth)) -> dict:
        return {"object": "list", "data": request.app.state.registry.list_client_models()}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request, _=Depends(require_client_auth)):
        body = await request.json()
        try:
            return await proxy_chat_completion(
                body,
                registry=request.app.state.registry,
                upstream=request.app.state.upstream,
            )
        except ProxyError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"message": str(exc), "type": "geniehive_error", "code": "chat_proxy_error"}},
            )
        except UpstreamError as exc:
            return JSONResponse(
                status_code=exc.status_code or 502,
                content={"error": {"message": str(exc), "type": "geniehive_error", "code": "upstream_error"}},
            )

    @app.post("/v1/embeddings")
    async def embeddings(request: Request, _=Depends(require_client_auth)):
        body = await request.json()
        try:
            return await proxy_embeddings(
                body,
                registry=request.app.state.registry,
                upstream=request.app.state.upstream,
            )
        except ProxyError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"message": str(exc), "type": "geniehive_error", "code": "embeddings_proxy_error"}},
            )
        except UpstreamError as exc:
            return JSONResponse(
                status_code=exc.status_code or 502,
                content={"error": {"message": str(exc), "type": "geniehive_error", "code": "upstream_error"}},
            )

    @app.get("/v1/cluster/services")
    async def list_services(request: Request, _=Depends(require_client_auth)) -> dict:
        return {"object": "list", "data": request.app.state.registry.list_services()}

    @app.get("/v1/cluster/benchmarks")
    async def list_benchmarks(
        request: Request,
        service_id: str | None = None,
        workload: str | None = None,
        _=Depends(require_client_auth),
    ) -> dict:
        return {
            "object": "list",
            "data": request.app.state.registry.list_benchmark_samples(service_id=service_id, workload=workload),
        }

    @app.post("/v1/cluster/benchmarks")
    async def ingest_benchmarks(payload: BenchmarkIngestRequest, request: Request, _=Depends(require_client_auth)) -> dict:
        samples = request.app.state.registry.upsert_benchmark_samples(payload.samples)
        return {"status": "ok", "count": len(payload.samples), "data": samples}

    @app.get("/v1/cluster/roles")
    async def list_roles(request: Request, _=Depends(require_client_auth)) -> dict:
        return {"object": "list", "data": request.app.state.registry.list_roles()}

    @app.get("/v1/cluster/health")
    async def cluster_health(request: Request, _=Depends(require_client_auth)) -> dict:
        cfg: ControlConfig = request.app.state.cfg
        return request.app.state.registry.cluster_health(cfg.routing.health_stale_after_s)

    @app.get("/v1/cluster/routes/resolve")
    async def resolve_route(model: str, request: Request, kind: str | None = None, _=Depends(require_client_auth)) -> dict:
        resolved = request.app.state.registry.resolve_route(model, kind=kind)
        if resolved is None:
            return JSONResponse(status_code=404, content={"error": "no_route", "model": model, "kind": kind})
        return {"status": "ok", "resolution": resolved}

    @app.post("/v1/cluster/routes/match")
    async def match_routes(payload: RouteMatchRequest, request: Request, _=Depends(require_client_auth)) -> dict:
        response = request.app.state.registry.match_routes(payload)
        return RouteMatchResponse.model_validate(response).model_dump()

    return app


app = create_app()
