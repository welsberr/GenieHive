from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RequestShapePolicy(BaseModel):
    body_defaults: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str | None = None
    system_prompt_position: Literal["prepend", "append", "replace"] = "prepend"


class ServiceAsset(BaseModel):
    asset_id: str
    loaded: bool = False
    request_policy: RequestShapePolicy = Field(default_factory=RequestShapePolicy)


class ServiceRuntime(BaseModel):
    engine: str | None = None
    launcher: str | None = None


class ServiceState(BaseModel):
    health: str | None = None
    load_state: str | None = None
    accept_requests: bool = True


class ServiceObserved(BaseModel):
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    tokens_per_sec: float | None = None
    queue_depth: int | None = None
    in_flight: int | None = None


class RegisteredService(BaseModel):
    service_id: str
    host_id: str
    kind: Literal["chat", "embeddings", "transcription"]
    protocol: str = "openai"
    endpoint: str
    runtime: ServiceRuntime = Field(default_factory=ServiceRuntime)
    assets: list[ServiceAsset] = Field(default_factory=list)
    state: ServiceState = Field(default_factory=ServiceState)
    observed: ServiceObserved = Field(default_factory=ServiceObserved)


class HostStatus(BaseModel):
    state: str = "online"
    last_seen: float | None = None


class HostRegistration(BaseModel):
    host_id: str
    display_name: str | None = None
    address: str
    labels: dict[str, str] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    services: list[RegisteredService] = Field(default_factory=list)


class HostHeartbeat(BaseModel):
    host_id: str
    status: HostStatus = Field(default_factory=HostStatus)
    metrics: dict[str, Any] = Field(default_factory=dict)
    services: list[RegisteredService] = Field(default_factory=list)


class PromptPolicy(BaseModel):
    system_prompt: str | None = None
    user_template: str | None = None
    request_policy: RequestShapePolicy = Field(default_factory=RequestShapePolicy)


class RoutingPolicy(BaseModel):
    preferred_families: list[str] = Field(default_factory=list)
    preferred_labels: list[str] = Field(default_factory=list)
    min_context: int | None = None
    require_loaded: bool = False
    fallback_roles: list[str] = Field(default_factory=list)


class RoleProfile(BaseModel):
    role_id: str
    display_name: str | None = None
    description: str | None = None
    operation: Literal["chat", "embeddings", "transcription"]
    modality: str
    prompt_policy: PromptPolicy = Field(default_factory=PromptPolicy)
    routing_policy: RoutingPolicy = Field(default_factory=RoutingPolicy)


class RoleCatalog(BaseModel):
    roles: list[RoleProfile] = Field(default_factory=list)


class BenchmarkSample(BaseModel):
    benchmark_id: str
    service_id: str
    asset_id: str | None = None
    workload: str
    observed_at: float
    results: dict[str, Any] = Field(default_factory=dict)


class BenchmarkIngestRequest(BaseModel):
    samples: list[BenchmarkSample] = Field(default_factory=list)


class RouteMatchRequest(BaseModel):
    task: str | None = None
    tasks: list[str] = Field(default_factory=list)
    workload: str | None = None
    workloads: list[str] = Field(default_factory=list)
    kind: Literal["chat", "embeddings", "transcription"] | None = None
    modality: str | None = None
    include_direct_services: bool = True
    limit: int = 10


class RouteMatchCandidate(BaseModel):
    candidate_type: Literal["role", "service"]
    candidate_id: str
    operation: Literal["chat", "embeddings", "transcription"]
    score: float
    reasons: list[str] = Field(default_factory=list)
    signals: dict[str, Any] = Field(default_factory=dict)
    role: dict[str, Any] | None = None
    service: dict[str, Any] | None = None


class RouteMatchResponse(BaseModel):
    status: str = "ok"
    task_count: int
    tasks: list[str]
    workloads: list[str] = Field(default_factory=list)
    kind: Literal["chat", "embeddings", "transcription"] | None = None
    modality: str | None = None
    candidates: list[RouteMatchCandidate] = Field(default_factory=list)
