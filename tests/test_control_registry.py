from pathlib import Path

from geniehive_control.main import create_app
from geniehive_control.models import BenchmarkSample, HostHeartbeat, HostRegistration, RegisteredService, RoleProfile, RouteMatchRequest
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

    # No stacking: pass_rate=1.0 alone should not score above 1.0 when speed is added.
    perfect_correct = _benchmark_quality_score({"pass_rate": 1.0})
    with_speed = _benchmark_quality_score({"pass_rate": 1.0, "tokens_per_sec": 100, "ttft_ms": 100})
    assert with_speed <= 1.0
    assert with_speed >= perfect_correct  # speed can only help, not hurt
