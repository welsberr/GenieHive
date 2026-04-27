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

    # No stacking: pass_rate=1.0 alone should not score above 1.0 when speed is added.
    perfect_correct = _benchmark_quality_score({"pass_rate": 1.0})
    with_speed = _benchmark_quality_score({"pass_rate": 1.0, "tokens_per_sec": 100, "ttft_ms": 100})
    assert with_speed <= 1.0
    assert with_speed >= perfect_correct  # speed can only help, not hurt
