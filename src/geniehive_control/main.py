from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import require_admin_auth, require_client_auth, require_node_auth
from .chat import ProxyError, _prepare_chat_upstream, proxy_chat_completion, proxy_embeddings, proxy_transcription, stream_chat_completion
from .config import ControlConfig, load_config
from .keys import generate_api_key, hash_api_key
from .models import BenchmarkIngestRequest, HostHeartbeat, HostRegistration, RouteMatchRequest, RouteMatchResponse
from .probe import ServiceProber
from .roles import load_role_catalog
from .registry import Registry
from .routing import choose_upstream_model_id
from .upstream import UpstreamClient, UpstreamError


def create_app(
    config_path: str | Path | None = None,
    *,
    upstream_client: UpstreamClient | None = None,
) -> FastAPI:
    cfg_path = config_path or os.environ.get("GENIEHIVE_CONTROL_CONFIG")
    cfg = load_config(cfg_path) if cfg_path else ControlConfig()
    registry = Registry(cfg.storage.sqlite_path, routing_strategy=cfg.routing.default_strategy)
    roles_path = cfg.roles_path or os.environ.get("GENIEHIVE_ROLES_CONFIG")
    if roles_path:
        registry.upsert_roles(load_role_catalog(roles_path).roles)
    upstream = upstream_client or UpstreamClient()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        probe_task: asyncio.Task | None = None
        prober: ServiceProber | None = None
        stop_event = asyncio.Event()
        if cfg.routing.probe_interval_s > 0:
            prober = ServiceProber(registry, timeout_s=cfg.routing.probe_timeout_s)
            probe_task = asyncio.create_task(
                prober.probe_loop(stop_event, cfg.routing.probe_interval_s)
            )
        try:
            yield
        finally:
            if probe_task is not None:
                stop_event.set()
                probe_task.cancel()
                with suppress(asyncio.CancelledError):
                    await probe_task
            if prober is not None:
                await prober.aclose()

    app = FastAPI(title="GenieHive Control", version="0.1.0", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.registry = registry
    app.state.upstream = upstream

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    def _public_client_key(row: dict) -> dict:
        return {
            key: value
            for key, value in row.items()
            if key != "key_hash"
        }

    def _request_id(request: Request) -> str:
        return request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex}"

    def _client_context(request: Request):
        return getattr(request.state, "client_context", None)

    def _route_audit_metadata(reg: Registry, requested_model: str | None, *, kind: str) -> dict:
        if not requested_model:
            return {
                "requested_model": None,
                "resolved_service_id": None,
                "resolved_host_id": None,
                "upstream_model": None,
                "provider_kind": None,
            }
        resolved = reg.resolve_route(requested_model, kind=kind)
        service = resolved.get("service") if resolved else None
        if not service:
            return {
                "requested_model": requested_model,
                "resolved_service_id": None,
                "resolved_host_id": None,
                "upstream_model": None,
                "provider_kind": None,
            }
        return {
            "requested_model": requested_model,
            "resolved_service_id": service.get("service_id"),
            "resolved_host_id": service.get("host_id"),
            "upstream_model": choose_upstream_model_id(requested_model, service),
            "provider_kind": service.get("protocol"),
        }

    def _usage_from_response(response: object) -> dict[str, int | None]:
        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        return {
            "prompt_tokens": usage.get("prompt_tokens") if isinstance(usage, dict) else None,
            "completion_tokens": usage.get("completion_tokens") if isinstance(usage, dict) else None,
            "total_tokens": usage.get("total_tokens") if isinstance(usage, dict) else None,
        }

    def _audit_request(
        request: Request,
        *,
        request_id: str,
        operation: str,
        route_metadata: dict,
        started_at: float,
        status_code: int,
        success: bool,
        response: object | None = None,
        error_type: str | None = None,
        input_bytes: int | None = None,
        output_bytes: int | None = None,
    ) -> None:
        if not cfg.audit.enabled:
            return
        context = _client_context(request)
        usage = _usage_from_response(response)
        request.app.state.registry.record_request_audit(
            request_id=request_id,
            key_id=getattr(context, "key_id", None),
            principal_type=getattr(context, "principal_type", None),
            principal_ref=getattr(context, "principal_ref", None),
            operation=operation,
            requested_model=route_metadata.get("requested_model"),
            resolved_service_id=route_metadata.get("resolved_service_id"),
            resolved_host_id=route_metadata.get("resolved_host_id"),
            upstream_model=route_metadata.get("upstream_model"),
            provider_kind=route_metadata.get("provider_kind"),
            started_at=started_at,
            finished_at=time.time(),
            status_code=status_code,
            success=success,
            error_type=error_type,
            input_bytes=input_bytes,
            output_bytes=output_bytes,
            **usage,
        )

    if cfg.admin_api.enabled:
        @app.post("/v1/admin/client-keys")
        async def create_client_key(request: Request, _=Depends(require_admin_auth)) -> dict:
            if not cfg.auth.enable_named_client_keys:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="named client keys are not enabled",
                )
            secret = os.environ.get(cfg.auth.key_hash_secret_env)
            if not secret:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"{cfg.auth.key_hash_secret_env} is required for named client keys",
                )
            payload = await request.json()
            raw_key = generate_api_key()
            key_id = payload.get("key_id") or f"ck_{uuid.uuid4().hex}"
            created = request.app.state.registry.create_client_key(
                key_id=key_id,
                key_hash=hash_api_key(raw_key, secret=secret),
                display_name=payload["display_name"],
                principal_type=payload["principal_type"],
                principal_ref=payload["principal_ref"],
                role=payload.get("role"),
                allowed_models=payload.get("allowed_models") or [],
                allowed_operations=payload.get("allowed_operations") or [],
                monthly_budget_cents=payload.get("monthly_budget_cents"),
                monthly_token_limit=payload.get("monthly_token_limit"),
                enabled=payload.get("enabled", True),
                notes=payload.get("notes"),
            )
            return {
                "status": "ok",
                "api_key": raw_key,
                "client_key": _public_client_key(created),
            }

        @app.get("/v1/admin/client-keys")
        async def list_client_keys(request: Request, _=Depends(require_admin_auth)) -> dict:
            rows = request.app.state.registry.list_client_keys()
            return {"object": "list", "data": [_public_client_key(row) for row in rows]}

        @app.post("/v1/admin/client-keys/{key_id}/disable")
        async def disable_client_key(key_id: str, request: Request, _=Depends(require_admin_auth)) -> dict:
            updated = request.app.state.registry.set_client_key_enabled(key_id, False)
            if updated is None:
                return JSONResponse(status_code=404, content={"error": "unknown_client_key", "key_id": key_id})
            return {"status": "ok", "client_key": _public_client_key(updated)}

        @app.post("/v1/admin/client-keys/{key_id}/enable")
        async def enable_client_key(key_id: str, request: Request, _=Depends(require_admin_auth)) -> dict:
            updated = request.app.state.registry.set_client_key_enabled(key_id, True)
            if updated is None:
                return JSONResponse(status_code=404, content={"error": "unknown_client_key", "key_id": key_id})
            return {"status": "ok", "client_key": _public_client_key(updated)}

        @app.get("/v1/admin/audit/requests")
        async def list_audit_requests(
            request: Request,
            key_id: str | None = None,
            principal_ref: str | None = None,
            operation: str | None = None,
            model: str | None = None,
            success: bool | None = None,
            limit: int = 100,
            _=Depends(require_admin_auth),
        ) -> dict:
            if not cfg.audit.enabled:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="audit logging is not enabled",
                )
            rows = request.app.state.registry.list_request_audit(
                key_id=key_id,
                principal_ref=principal_ref,
                operation=operation,
                model=model,
                success=success,
                limit=limit,
            )
            return {"object": "list", "data": rows}

        @app.get("/v1/admin/audit/summary")
        async def audit_summary(request: Request, _=Depends(require_admin_auth)) -> dict:
            if not cfg.audit.enabled:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="audit logging is not enabled",
                )
            return {"object": "list", "data": request.app.state.registry.request_audit_summary()}

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
        reg: Registry = request.app.state.registry
        up: UpstreamClient = request.app.state.upstream
        request_id = _request_id(request)
        started_at = time.time()
        route_metadata = _route_audit_metadata(reg, body.get("model"), kind="chat")
        input_bytes = len(json.dumps(body, separators=(",", ":")).encode("utf-8"))
        try:
            if body.get("stream"):
                # Resolve route eagerly so ProxyError is raised before streaming starts.
                service, upstream_body = _prepare_chat_upstream(body, registry=reg)
                _audit_request(
                    request,
                    request_id=request_id,
                    operation="chat",
                    route_metadata=route_metadata,
                    started_at=started_at,
                    status_code=200,
                    success=True,
                    input_bytes=input_bytes,
                )
                return StreamingResponse(
                    stream_chat_completion(service, upstream_body, upstream=up),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-Id": request_id},
                )
            response = await proxy_chat_completion(body, registry=reg, upstream=up)
            output_bytes = len(json.dumps(response, separators=(",", ":")).encode("utf-8")) if isinstance(response, dict) else None
            _audit_request(
                request,
                request_id=request_id,
                operation="chat",
                route_metadata=route_metadata,
                started_at=started_at,
                status_code=200,
                success=True,
                response=response,
                input_bytes=input_bytes,
                output_bytes=output_bytes,
            )
            return JSONResponse(content=response, headers={"X-Request-Id": request_id})
        except ProxyError as exc:
            _audit_request(
                request,
                request_id=request_id,
                operation="chat",
                route_metadata=route_metadata,
                started_at=started_at,
                status_code=exc.status_code,
                success=False,
                error_type="proxy_error",
                input_bytes=input_bytes,
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"message": str(exc), "type": "geniehive_error", "code": "chat_proxy_error"}},
                headers={"X-Request-Id": request_id},
            )
        except UpstreamError as exc:
            status_code = exc.status_code or 502
            _audit_request(
                request,
                request_id=request_id,
                operation="chat",
                route_metadata=route_metadata,
                started_at=started_at,
                status_code=status_code,
                success=False,
                error_type="upstream_error",
                input_bytes=input_bytes,
            )
            return JSONResponse(
                status_code=status_code,
                content={"error": {"message": str(exc), "type": "geniehive_error", "code": "upstream_error"}},
                headers={"X-Request-Id": request_id},
            )

    @app.post("/v1/embeddings")
    async def embeddings(request: Request, _=Depends(require_client_auth)):
        body = await request.json()
        reg: Registry = request.app.state.registry
        request_id = _request_id(request)
        started_at = time.time()
        route_metadata = _route_audit_metadata(reg, body.get("model"), kind="embeddings")
        input_bytes = len(json.dumps(body, separators=(",", ":")).encode("utf-8"))
        try:
            response = await proxy_embeddings(
                body,
                registry=reg,
                upstream=request.app.state.upstream,
            )
            output_bytes = len(json.dumps(response, separators=(",", ":")).encode("utf-8")) if isinstance(response, dict) else None
            _audit_request(
                request,
                request_id=request_id,
                operation="embeddings",
                route_metadata=route_metadata,
                started_at=started_at,
                status_code=200,
                success=True,
                response=response,
                input_bytes=input_bytes,
                output_bytes=output_bytes,
            )
            return JSONResponse(content=response, headers={"X-Request-Id": request_id})
        except ProxyError as exc:
            _audit_request(
                request,
                request_id=request_id,
                operation="embeddings",
                route_metadata=route_metadata,
                started_at=started_at,
                status_code=exc.status_code,
                success=False,
                error_type="proxy_error",
                input_bytes=input_bytes,
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"message": str(exc), "type": "geniehive_error", "code": "embeddings_proxy_error"}},
                headers={"X-Request-Id": request_id},
            )
        except UpstreamError as exc:
            status_code = exc.status_code or 502
            _audit_request(
                request,
                request_id=request_id,
                operation="embeddings",
                route_metadata=route_metadata,
                started_at=started_at,
                status_code=status_code,
                success=False,
                error_type="upstream_error",
                input_bytes=input_bytes,
            )
            return JSONResponse(
                status_code=status_code,
                content={"error": {"message": str(exc), "type": "geniehive_error", "code": "upstream_error"}},
                headers={"X-Request-Id": request_id},
            )

    @app.post("/v1/audio/transcriptions")
    async def audio_transcriptions(
        request: Request,
        file: UploadFile = File(...),
        model: str = Form(...),
        language: str | None = Form(None),
        prompt: str | None = Form(None),
        response_format: str | None = Form(None),
        temperature: float | None = Form(None),
        _=Depends(require_client_auth),
    ):
        request_id = _request_id(request)
        started_at = time.time()
        route_metadata = _route_audit_metadata(request.app.state.registry, model, kind="transcription")
        try:
            response = await proxy_transcription(
                model=model,
                file=file,
                language=language,
                prompt=prompt,
                response_format=response_format,
                temperature=temperature,
                registry=request.app.state.registry,
                upstream=request.app.state.upstream,
            )
            output_bytes = len(json.dumps(response, separators=(",", ":")).encode("utf-8")) if isinstance(response, dict) else None
            _audit_request(
                request,
                request_id=request_id,
                operation="transcription",
                route_metadata=route_metadata,
                started_at=started_at,
                status_code=200,
                success=True,
                response=response,
                output_bytes=output_bytes,
            )
            return JSONResponse(content=response, headers={"X-Request-Id": request_id})
        except ProxyError as exc:
            _audit_request(
                request,
                request_id=request_id,
                operation="transcription",
                route_metadata=route_metadata,
                started_at=started_at,
                status_code=exc.status_code,
                success=False,
                error_type="proxy_error",
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"message": str(exc), "type": "geniehive_error", "code": "transcription_proxy_error"}},
                headers={"X-Request-Id": request_id},
            )
        except UpstreamError as exc:
            status_code = exc.status_code or 502
            _audit_request(
                request,
                request_id=request_id,
                operation="transcription",
                route_metadata=route_metadata,
                started_at=started_at,
                status_code=status_code,
                success=False,
                error_type="upstream_error",
            )
            return JSONResponse(
                status_code=status_code,
                content={"error": {"message": str(exc), "type": "geniehive_error", "code": "upstream_error"}},
                headers={"X-Request-Id": request_id},
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
