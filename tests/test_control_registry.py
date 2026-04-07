from pathlib import Path

from geniehive_control.main import create_app
from geniehive_control.models import HostHeartbeat, HostRegistration, RegisteredService, RoleProfile
from geniehive_control.registry import Registry


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
    asset = next(item for item in models if item["id"] == "qwen3-8b-q4km")
    assert asset["geniehive"]["route_type"] == "asset"
    assert asset["geniehive"]["offload_hint"]["recommended_for"] == "lower-complexity offload"


def test_control_app_exposes_expected_routes() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/v1/models" in paths
    assert "/v1/nodes/register" in paths
    assert "/v1/nodes/heartbeat" in paths
    assert "/v1/cluster/hosts" in paths
    assert "/v1/cluster/services" in paths
    assert "/v1/cluster/roles" in paths
    assert "/v1/cluster/health" in paths
    assert "/v1/cluster/routes/resolve" in paths
