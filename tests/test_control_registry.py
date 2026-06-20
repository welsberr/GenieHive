import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from geniehive_control.main import create_app
from geniehive_control.models import BenchmarkSample, HostHeartbeat, HostRegistration, RegisteredService, RoleProfile, RouteMatchRequest
from geniehive_control.probe import ServiceProber
from geniehive_control.registry import Registry, _benchmark_quality_score


def test_registry_persists_registration_and_heartbeat(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path)

    host = registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            display_name="Atlas GPU Box",
            address="192.168.1.101",
            labels={"site": "home-lab"},
            capabilities={"cuda": True},
            resources={"cpu_threads": 24},
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/qwen3-8b",
                    host_id="atlas-01",
                    kind="chat",
                    protocol="openai",
                    endpoint="http://192.168.1.101:18091",
                    runtime={"engine": "llama.cpp", "launcher": "managed"},
                    assets=[{"asset_id": "qwen3-8b-q4km", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 900, "tokens_per_sec": 40},
                )
            ],
        )
    )
    assert host is not None
    assert host["host_id"] == "atlas-01"

    updated = registry.heartbeat_host(
        HostHeartbeat(
            host_id="atlas-01",
            status={"state": "online"},
            metrics={"gpu_utilization_pct": 77},
        )
    )
    assert updated is not None
    assert updated["metrics"]["gpu_utilization_pct"] == 77

    hosts = registry.list_hosts()
    services = registry.list_services()
    health = registry.cluster_health(stale_after_s=30)

    assert len(hosts) == 1
    assert len(services) == 1
    assert services[0]["service_id"] == "atlas-01/chat/qwen3-8b"
    assert services[0]["state"]["health"] == "healthy"
    assert health["host_count"] == 1
    assert health["healthy_service_count"] == 1


def test_registry_persists_roles_and_resolves_direct_and_role_routes(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path)

    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/qwen3-8b",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    assets=[{"asset_id": "qwen3-8b-q4km", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 900},
                ),
                RegisteredService(
                    service_id="atlas-01/embeddings/bge-small",
                    host_id="atlas-01",
                    kind="embeddings",
                    endpoint="http://192.168.1.101:18092",
                    assets=[{"asset_id": "bge-small-en", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 120},
                ),
            ],
        )
    )
    registry.upsert_roles(
        [
            RoleProfile(
                role_id="mentor",
                display_name="Mentor",
                operation="chat",
                modality="text",
                routing_policy={"preferred_families": ["qwen3"]},
            ),
            RoleProfile(
                role_id="embedder",
                display_name="Embedder",
                operation="embeddings",
                modality="text",
                routing_policy={"require_loaded": True},
            ),
        ]
    )

    roles = registry.list_roles()
    assert len(roles) == 2
    assert roles[0]["role_id"] == "embedder"

    direct = registry.resolve_route("qwen3-8b-q4km")
    assert direct is not None
    assert direct["match_type"] == "direct"
    assert direct["service"]["service_id"] == "atlas-01/chat/qwen3-8b"

    by_role = registry.resolve_route("mentor")
    assert by_role is not None
    assert by_role["match_type"] == "role"
    assert by_role["role"]["role_id"] == "mentor"
    assert by_role["service"]["service_id"] == "atlas-01/chat/qwen3-8b"

    embed_role = registry.resolve_route("embedder")
    assert embed_role is not None
    assert embed_role["service"]["service_id"] == "atlas-01/embeddings/bge-small"

    models = registry.list_client_models()
    ids = {item["id"] for item in models}
    assert "atlas-01/chat/qwen3-8b" in ids
    assert "qwen3-8b-q4km" in ids
    assert "mentor" in ids
    mentor = next(item for item in models if item["id"] == "mentor")
    assert mentor["geniehive"]["route_type"] == "role"
    assert mentor["geniehive"]["offload_hint"]["suitability"] == "good_for_low_complexity"
    assert mentor["geniehive"]["effective_request_policy"]["body_defaults"]["chat_template_kwargs"]["enable_thinking"] is False
    asset = next(item for item in models if item["id"] == "qwen3-8b-q4km")
    assert asset["geniehive"]["route_type"] == "asset"
    assert asset["geniehive"]["offload_hint"]["recommended_for"] == "lower-complexity offload"
    assert asset["geniehive"]["effective_request_policy"]["body_defaults"]["chat_template_kwargs"]["enable_thinking"] is False


def test_forge_guardrail_role_prefers_forge_proxy_service(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "geniehive.sqlite3")
    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/plain-qwen",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    runtime={"engine": "llama.cpp", "launcher": "external"},
                    assets=[{"asset_id": "qwen3-8b-q4km", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 450, "tokens_per_sec": 40},
                ),
                RegisteredService(
                    service_id="atlas-01/chat/forge-qwen",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18081",
                    runtime={"engine": "forge-proxy", "launcher": "forge"},
                    assets=[{"asset_id": "qwen3-8b-forge", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 1200, "tokens_per_sec": 28},
                ),
            ],
        )
    )
    registry.upsert_roles(
        [
            RoleProfile(
                role_id="tool_user",
                display_name="Tool User",
                description="Reliable local agentic tool-use route",
                operation="chat",
                modality="text",
                routing_policy={
                    "preferred_families": ["qwen3"],
                    "guardrail_profile": "forge_proxy",
                    "tool_mode": "auto",
                    "force_respond_tool": True,
                    "agentic_benchmark_workloads": ["agentic.tool_use"],
                },
            )
        ]
    )

    resolved = registry.resolve_route("tool_user")
    assert resolved is not None
    assert resolved["service"]["service_id"] == "atlas-01/chat/forge-qwen"
    assert resolved["role"]["routing_policy"]["guardrail_profile"] == "forge_proxy"

    matched = registry.match_routes(
        RouteMatchRequest(task="multi-step agentic tool use with required function calls", workload="agentic.tool_use")
    )
    top = matched["candidates"][0]
    assert top["candidate_id"] == "tool_user"
    assert top["signals"]["guardrail_profile_match"] == 1.0


def test_round_robin_role_routes_only_highest_preferred_family(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path, routing_strategy="round_robin")

    registry.register_host(
        HostRegistration(
            host_id="translation-cluster",
            address="127.0.0.1",
            services=[
                RegisteredService(
                    service_id="gorlim/chat/qwen35-gpu0",
                    host_id="translation-cluster",
                    kind="chat",
                    endpoint="http://127.0.0.1:19101",
                    assets=[{"asset_id": "Qwen3.5-9B-Q5_K_M", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 1050, "tokens_per_sec": 41},
                ),
                RegisteredService(
                    service_id="gorlim/chat/qwen35-gpu1",
                    host_id="translation-cluster",
                    kind="chat",
                    endpoint="http://127.0.0.1:19102",
                    assets=[{"asset_id": "Qwen3.5-9B-Q5_K_M", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 1050, "tokens_per_sec": 41},
                ),
                RegisteredService(
                    service_id="p40-box/chat/qwen35-gpu0",
                    host_id="translation-cluster",
                    kind="chat",
                    endpoint="http://127.0.0.1:19191",
                    assets=[{"asset_id": "Qwen3.5-9B-Q5_K_S", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 1000, "tokens_per_sec": 30},
                ),
                RegisteredService(
                    service_id="p40-box/chat/qwen35-gpu1",
                    host_id="translation-cluster",
                    kind="chat",
                    endpoint="http://127.0.0.1:19192",
                    assets=[{"asset_id": "Qwen3.5-9B-Q5_K_S", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 1000, "tokens_per_sec": 30},
                ),
                RegisteredService(
                    service_id="gorlim/chat/qwen3-8b",
                    host_id="translation-cluster",
                    kind="chat",
                    endpoint="http://127.0.0.1:19091",
                    assets=[{"asset_id": "Qwen3-8B-Q5_K_M", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 900, "tokens_per_sec": 33},
                ),
            ],
        )
    )
    registry.upsert_roles(
        [
            RoleProfile(
                role_id="scientific_translator",
                display_name="Scientific Translator",
                operation="chat",
                modality="text",
                routing_policy={
                    "preferred_families": ["qwen3.5-9b", "qwen3.5", "qwen3-8b", "qwen3"],
                    "require_loaded": True,
                },
            )
        ]
    )

    service_ids = [
        registry.resolve_route("scientific_translator")["service"]["service_id"]
        for _ in range(8)
    ]

    assert service_ids == [
        "gorlim/chat/qwen35-gpu0",
        "gorlim/chat/qwen35-gpu1",
        "p40-box/chat/qwen35-gpu0",
        "p40-box/chat/qwen35-gpu1",
        "gorlim/chat/qwen35-gpu0",
        "gorlim/chat/qwen35-gpu1",
        "p40-box/chat/qwen35-gpu0",
        "p40-box/chat/qwen35-gpu1",
    ]
    assert "gorlim/chat/qwen3-8b" not in service_ids


def test_employee_device_nodes_are_role_opt_in_and_not_direct_by_default(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "geniehive.sqlite3")
    registry.register_host(
        HostRegistration(
            host_id="macbook-ada",
            display_name="Ada MacBook Pro",
            address="100.64.10.42",
            labels={"trust_tier": "employee_device", "device_class": "apple_silicon_mac"},
            capabilities={"metal": True},
            resources={
                "ram_gb": 64,
                "trust_tier": "employee_device",
                "device_class": "apple_silicon_mac",
                "contribution_policy": {
                    "max_ram_gb": 24,
                    "idle_only": True,
                    "ac_power_only": True,
                    "workload_classes": ["background", "low_priority"],
                    "allowed_model_families": ["qwen2.5", "llama3"],
                },
            },
            services=[
                RegisteredService(
                    service_id="macbook-ada/chat/qwen-small",
                    host_id="macbook-ada",
                    kind="chat",
                    endpoint="http://100.64.10.42:11434/v1",
                    runtime={"engine": "ollama", "launcher": "user-agent", "context_size": 8192},
                    assets=[{"asset_id": "qwen2.5-7b-instruct-q4", "loaded": True, "context_size": 8192}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 1800, "tokens_per_sec": 18},
                )
            ],
        )
    )
    registry.upsert_roles(
        [
            RoleProfile(
                role_id="standard_assistant",
                display_name="Standard Assistant",
                operation="chat",
                modality="text",
                routing_policy={"preferred_families": ["qwen2.5"]},
            ),
            RoleProfile(
                role_id="mac_background_assistant",
                display_name="Mac Background Assistant",
                operation="chat",
                modality="text",
                routing_policy={
                    "preferred_families": ["qwen2.5"],
                    "allow_employee_devices": True,
                    "allowed_device_classes": ["apple_silicon_mac"],
                    "allowed_workload_classes": ["background"],
                    "min_context": 4096,
                },
            ),
        ]
    )

    standard = registry.resolve_route("standard_assistant")
    assert standard is not None
    assert standard["service"] is None

    opted_in = registry.resolve_route("mac_background_assistant")
    assert opted_in is not None
    assert opted_in["service"]["service_id"] == "macbook-ada/chat/qwen-small"

    direct = registry.resolve_route("qwen2.5-7b-instruct-q4")
    assert direct is None

    model_ids = {item["id"] for item in registry.list_client_models()}
    assert "qwen2.5-7b-instruct-q4" not in model_ids
    assert "mac_background_assistant" in model_ids


def test_employee_device_direct_addressing_requires_explicit_service_opt_in(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "geniehive.sqlite3")
    registry.register_host(
        HostRegistration(
            host_id="macbook-ada",
            address="100.64.10.42",
            labels={"trust_tier": "employee_device", "device_class": "apple_silicon_mac"},
            services=[
                RegisteredService(
                    service_id="macbook-ada/chat/qwen-small",
                    host_id="macbook-ada",
                    kind="chat",
                    endpoint="http://100.64.10.42:11434/v1",
                    assets=[{"asset_id": "qwen2.5-7b-instruct-q4", "loaded": True}],
                    state={
                        "health": "healthy",
                        "load_state": "loaded",
                        "accept_requests": True,
                        "allow_employee_direct_requests": True,
                    },
                    observed={"p50_latency_ms": 1800},
                )
            ],
        )
    )

    direct = registry.resolve_route("qwen2.5-7b-instruct-q4")
    assert direct is not None
    assert direct["service"]["service_id"] == "macbook-ada/chat/qwen-small"


def test_node_allowed_model_families_constrain_routing(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "geniehive.sqlite3")
    registry.register_host(
        HostRegistration(
            host_id="macbook-ada",
            address="100.64.10.42",
            labels={"trust_tier": "employee_device", "device_class": "apple_silicon_mac"},
            resources={"contribution_policy": {"allowed_model_families": ["qwen2.5"], "workload_classes": ["background"]}},
            services=[
                RegisteredService(
                    service_id="macbook-ada/chat/llama",
                    host_id="macbook-ada",
                    kind="chat",
                    endpoint="http://100.64.10.42:11434/v1",
                    assets=[{"asset_id": "llama3.2-3b-instruct", "loaded": True}],
                    state={"health": "healthy", "accept_requests": True},
                    observed={"p50_latency_ms": 1300},
                )
            ],
        )
    )
    registry.upsert_roles(
        [
            RoleProfile(
                role_id="mac_background_assistant",
                display_name="Mac Background Assistant",
                operation="chat",
                modality="text",
                routing_policy={
                    "preferred_families": ["llama3"],
                    "allow_employee_devices": True,
                    "allowed_device_classes": ["apple_silicon_mac"],
                    "allowed_workload_classes": ["background"],
                },
            )
        ]
    )

    resolved = registry.resolve_route("mac_background_assistant")
    assert resolved is not None
    assert resolved["service"] is None


def test_draining_services_do_not_receive_new_routes(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "geniehive.sqlite3")
    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/draining",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    assets=[{"asset_id": "qwen3-draining", "loaded": True}],
                    state={"health": "healthy", "availability": "draining", "accept_requests": True},
                    observed={"p50_latency_ms": 700},
                ),
                RegisteredService(
                    service_id="atlas-01/chat/available",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18092",
                    assets=[{"asset_id": "qwen3-available", "loaded": True}],
                    state={"health": "healthy", "availability": "available", "accept_requests": True},
                    observed={"p50_latency_ms": 1200},
                ),
            ],
        )
    )
    registry.upsert_roles(
        [
            RoleProfile(
                role_id="assistant",
                display_name="Assistant",
                operation="chat",
                modality="text",
                routing_policy={"preferred_families": ["qwen3"]},
            )
        ]
    )

    resolved = registry.resolve_route("assistant")
    assert resolved is not None
    assert resolved["service"]["service_id"] == "atlas-01/chat/available"

    direct = registry.resolve_route("qwen3-draining")
    assert direct is None


def test_min_context_filters_underpowered_services(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "geniehive.sqlite3")
    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/small-context",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    assets=[{"asset_id": "qwen3-small-context", "loaded": True, "context_size": 4096}],
                    state={"health": "healthy", "accept_requests": True},
                    observed={"p50_latency_ms": 600},
                ),
                RegisteredService(
                    service_id="atlas-01/chat/large-context",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18092",
                    assets=[{"asset_id": "qwen3-large-context", "loaded": True, "context_size": 32768}],
                    state={"health": "healthy", "accept_requests": True},
                    observed={"p50_latency_ms": 1200},
                ),
            ],
        )
    )
    registry.upsert_roles(
        [
            RoleProfile(
                role_id="long_context_assistant",
                display_name="Long Context Assistant",
                operation="chat",
                modality="text",
                routing_policy={"preferred_families": ["qwen3"], "min_context": 8192},
            )
        ]
    )

    resolved = registry.resolve_route("long_context_assistant")
    assert resolved is not None
    assert resolved["service"]["service_id"] == "atlas-01/chat/large-context"


def test_control_app_exposes_expected_routes() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/v1/models" in paths
    assert "/v1/nodes/register" in paths
    assert "/v1/nodes/heartbeat" in paths
    assert "/v1/cluster/hosts" in paths
    assert "/v1/cluster/services" in paths
    assert "/v1/cluster/benchmarks" in paths
    assert "/v1/cluster/roles" in paths
    assert "/v1/cluster/health" in paths
    assert "/v1/cluster/routes/resolve" in paths
    assert "/v1/cluster/routes/match" in paths
    assert "/v1/audio/transcriptions" in paths


def test_registry_can_rank_routes_for_task_statements(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path)

    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/qwen-reasoner",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    assets=[{"asset_id": "qwen3.5-9b", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 1100, "tokens_per_sec": 28},
                ),
                RegisteredService(
                    service_id="atlas-01/chat/rocket-background",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18093",
                    assets=[{"asset_id": "rocket-3b", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 4200, "tokens_per_sec": 7},
                ),
            ],
        )
    )
    registry.upsert_roles(
        [
            RoleProfile(
                role_id="general_assistant",
                display_name="General Assistant",
                description="Fast general technical assistant for reasoning and question answering.",
                operation="chat",
                modality="text",
                routing_policy={"preferred_families": ["qwen3.5", "qwen"]},
            ),
            RoleProfile(
                role_id="background_summarizer",
                display_name="Background Summarizer",
                description="Slow fallback summarizer for lower-priority background work.",
                operation="chat",
                modality="text",
                routing_policy={"preferred_families": ["rocket"]},
            ),
        ]
    )

    result = registry.match_routes(
        RouteMatchRequest(
            task="fast technical reasoning for an interactive assistant",
            kind="chat",
            modality="text",
            limit=4,
        )
    )

    assert result["task_count"] == 1
    assert result["candidates"]
    top = result["candidates"][0]
    assert top["candidate_type"] == "role"
    assert top["candidate_id"] == "general_assistant"
    assert top["service"]["service_id"] == "atlas-01/chat/qwen-reasoner"
    assert top["signals"]["preferred_family_match"] == 1.0


def test_registry_match_can_include_direct_services(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path)
    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/qwen3-8b",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    assets=[{"asset_id": "qwen3-8b-q4km", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 900, "tokens_per_sec": 40},
                )
            ],
        )
    )

    result = registry.match_routes(
        RouteMatchRequest(
            task="qwen model for quick chat",
            kind="chat",
            include_direct_services=True,
            limit=4,
        )
    )

    direct = next(candidate for candidate in result["candidates"] if candidate["candidate_type"] == "service")
    assert direct["candidate_id"] == "atlas-01/chat/qwen3-8b"
    assert direct["service"]["assets"][0]["asset_id"] == "qwen3-8b-q4km"


def test_registry_persists_benchmark_samples_and_uses_them_for_matching(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path)
    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/qwen-fast",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    assets=[{"asset_id": "qwen3.5-9b", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 1500, "tokens_per_sec": 22},
                ),
                RegisteredService(
                    service_id="atlas-01/chat/rocket-slow",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18093",
                    assets=[{"asset_id": "rocket-3b", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 1200, "tokens_per_sec": 10},
                ),
            ],
        )
    )
    registry.upsert_benchmark_samples(
        [
            BenchmarkSample(
                benchmark_id="bench-qwen-1",
                service_id="atlas-01/chat/qwen-fast",
                asset_id="qwen3.5-9b",
                workload="chat.short_reasoning",
                observed_at=1000.0,
                results={"tokens_per_sec": 30, "ttft_ms": 900, "quality_score": 0.9},
            ),
            BenchmarkSample(
                benchmark_id="bench-rocket-1",
                service_id="atlas-01/chat/rocket-slow",
                asset_id="rocket-3b",
                workload="chat.short_reasoning",
                observed_at=1000.0,
                results={"tokens_per_sec": 9, "ttft_ms": 1900, "quality_score": 0.4},
            ),
        ]
    )

    samples = registry.list_benchmark_samples(service_id="atlas-01/chat/qwen-fast")
    assert len(samples) == 1
    assert samples[0]["benchmark_id"] == "bench-qwen-1"

    result = registry.match_routes(
        RouteMatchRequest(
            task="fast short reasoning for chat responses",
            workloads=["chat.short_reasoning"],
            kind="chat",
            include_direct_services=True,
            limit=4,
        )
    )

    top_service = next(candidate for candidate in result["candidates"] if candidate["candidate_type"] == "service")
    assert top_service["candidate_id"] == "atlas-01/chat/qwen-fast"
    assert top_service["signals"]["benchmark_match_count"] == 1
    assert top_service["signals"]["best_workload_overlap"] == 1.0


def test_registry_exposes_asset_request_policy_in_model_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path)
    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/custom-model",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    assets=[
                        {
                            "asset_id": "custom-model-v1",
                            "loaded": True,
                            "request_policy": {
                                "body_defaults": {
                                    "temperature": 0.2,
                                    "chat_template_kwargs": {"custom_flag": "yes"},
                                }
                            },
                        }
                    ],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 900},
                )
            ],
        )
    )

    models = registry.list_client_models()
    asset = next(item for item in models if item["id"] == "custom-model-v1")
    assert asset["geniehive"]["effective_request_policy"]["body_defaults"]["temperature"] == 0.2
    assert asset["geniehive"]["effective_request_policy"]["body_defaults"]["chat_template_kwargs"]["custom_flag"] == "yes"


def test_registry_fallback_roles_resolve_when_primary_has_no_service(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path)

    # Only a chat service exists — no transcription service.
    # The primary role wants transcription (no candidates), so it falls back to
    # the secondary role which routes to the available chat service.
    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/rocket",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18093",
                    assets=[{"asset_id": "rocket-3b", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 2000},
                )
            ],
        )
    )
    registry.upsert_roles(
        [
            RoleProfile(
                role_id="primary_transcriber",
                display_name="Primary Transcriber",
                operation="transcription",
                modality="text",
                routing_policy={"fallback_roles": ["chat_fallback"]},
            ),
            RoleProfile(
                role_id="chat_fallback",
                display_name="Chat Fallback",
                operation="chat",
                modality="text",
                routing_policy={"preferred_families": ["rocket"]},
            ),
        ]
    )

    result = registry.resolve_route("primary_transcriber")
    assert result is not None
    assert result["match_type"] == "role"
    assert result["role"]["role_id"] == "primary_transcriber"
    assert result["service"] is not None
    assert result["service"]["service_id"] == "atlas-01/chat/rocket"
    assert result["fallback_via"] == "chat_fallback"


def test_registry_fallback_roles_cycle_protection(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path)

    # No services — both roles have empty candidate lists.
    registry.upsert_roles(
        [
            RoleProfile(
                role_id="role_a",
                display_name="A",
                operation="chat",
                modality="text",
                routing_policy={"fallback_roles": ["role_b"]},
            ),
            RoleProfile(
                role_id="role_b",
                display_name="B",
                operation="chat",
                modality="text",
                routing_policy={"fallback_roles": ["role_a"]},
            ),
        ]
    )

    # Must not loop forever; must return service=None gracefully.
    result = registry.resolve_route("role_a")
    assert result is not None
    assert result["match_type"] == "role"
    assert result["service"] is None


def test_registry_update_service_health_changes_only_health_field(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path)
    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/qwen3-8b",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    assets=[{"asset_id": "qwen3-8b", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 900},
                )
            ],
        )
    )

    registry.update_service_health("atlas-01/chat/qwen3-8b", "unhealthy")
    services = registry.list_services()
    assert services[0]["state"]["health"] == "unhealthy"
    # Other state fields must be preserved.
    assert services[0]["state"]["load_state"] == "loaded"
    assert services[0]["state"]["accept_requests"] is True

    # Unknown service_id is a no-op (does not raise).
    registry.update_service_health("nonexistent", "healthy")


def test_service_prober_updates_health_on_probe(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path)
    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/qwen3-8b",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    assets=[{"asset_id": "qwen3-8b", "loaded": True}],
                    state={"health": "healthy"},
                    observed={},
                )
            ],
        )
    )

    prober = ServiceProber(registry, timeout_s=5.0)

    # Simulate a failed probe (connection error → unhealthy).
    import httpx
    async def run() -> None:
        with patch.object(prober._client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.ConnectError("refused")
            results = await prober.probe_once()
        assert results["atlas-01/chat/qwen3-8b"] == "unhealthy"
        services = registry.list_services()
        assert services[0]["state"]["health"] == "unhealthy"

        # Simulate a successful probe → health restored.
        with patch.object(prober._client, "get", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            results2 = await prober.probe_once()
        assert results2["atlas-01/chat/qwen3-8b"] == "healthy"
        services2 = registry.list_services()
        assert services2[0]["state"]["health"] == "healthy"

    asyncio.run(run())


def test_service_prober_falls_back_to_v1_models_when_health_endpoint_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "geniehive.sqlite3"
    registry = Registry(db_path)
    registry.register_host(
        HostRegistration(
            host_id="vllm-01",
            address="192.168.1.200",
            services=[
                RegisteredService(
                    service_id="vllm-01/chat/mistral",
                    host_id="vllm-01",
                    kind="chat",
                    endpoint="http://192.168.1.200:8000",
                    assets=[],
                    state={"health": "unhealthy"},
                    observed={},
                )
            ],
        )
    )

    prober = ServiceProber(registry, timeout_s=5.0)

    async def run() -> None:
        import httpx
        call_log: list[str] = []

        async def fake_get(url: str) -> MagicMock:
            call_log.append(url)
            mock_response = MagicMock()
            if url.endswith("/health"):
                mock_response.status_code = 404
            else:
                mock_response.status_code = 200
            return mock_response

        with patch.object(prober._client, "get", side_effect=fake_get):
            results = await prober.probe_once()

        assert results["vllm-01/chat/mistral"] == "healthy"
        # Both paths were tried.
        assert any("/health" in u for u in call_log)
        assert any("/v1/models" in u for u in call_log)
        services = registry.list_services()
        assert services[0]["state"]["health"] == "healthy"

    asyncio.run(run())


def test_benchmark_quality_score_stays_bounded_and_weighted() -> None:
    # High correctness + fast speed must not exceed 1.0.
    score = _benchmark_quality_score({"pass_rate": 1.0, "tokens_per_sec": 80, "ttft_ms": 400})
    assert score <= 1.0
    assert score > 0.9  # should be near 1.0

    # Correctness dominates: high pass_rate with slow speed should still score well.
    high_correct_slow = _benchmark_quality_score({"pass_rate": 0.95, "tokens_per_sec": 5, "ttft_ms": 4000})
    low_correct_fast = _benchmark_quality_score({"pass_rate": 0.3, "tokens_per_sec": 80, "ttft_ms": 400})
    assert high_correct_slow > low_correct_fast

    # Speed-only (no correctness signal) returns a non-zero score.
    speed_only = _benchmark_quality_score({"tokens_per_sec": 40, "ttft_ms": 800})
    assert 0.0 < speed_only < 1.0

    # Empty results return 0.
    assert _benchmark_quality_score({}) == 0.0

    # Forge-style agentic workflow metrics count as correctness signals.
    agentic = _benchmark_quality_score({"terminal_accuracy": 0.9, "completion_rate": 0.8})
    assert agentic > 0.5

    # No stacking: pass_rate=1.0 alone should not score above 1.0 when speed is added.
    perfect_correct = _benchmark_quality_score({"pass_rate": 1.0})
    with_speed = _benchmark_quality_score({"pass_rate": 1.0, "tokens_per_sec": 100, "ttft_ms": 100})
    assert with_speed <= 1.0
    assert with_speed >= perfect_correct  # speed can only help, not hurt
