import asyncio
from pathlib import Path

from geniehive_node.config import load_config
from geniehive_node.inventory import build_heartbeat_payload, build_inventory, build_registration_payload
from geniehive_node.main import create_app
from geniehive_node.sync import ControlPlaneClient


def _write_node_config(tmp_path: Path) -> Path:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "demo.gguf").write_bytes(b"gguf-demo")

    cfg_path = tmp_path / "node.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "node:",
                '  host_id: "atlas-01"',
                '  display_name: "Atlas GPU Box"',
                '  listen_host: "127.0.0.1"',
                "  listen_port: 8891",
                '  address: "192.168.1.101"',
                "  labels:",
                '    site: "home-lab"',
                "inventory:",
                f'  model_roots:\n    - "{models_dir}"',
                "  cpu_threads: 24",
                "  ram_gb: 128",
                "  capabilities:",
                "    cuda: true",
                "services:",
                '  - service_id: "atlas-01/chat/qwen3-8b"',
                '    kind: "chat"',
                '    endpoint: "http://127.0.0.1:18091"',
                "    runtime:",
                '      engine: "llama.cpp"',
                '      launcher: "managed"',
                "    assets:",
                '      - asset_id: "qwen3-8b-q4km"',
                "        loaded: true",
                "    state:",
                '      health: "healthy"',
                '      load_state: "loaded"',
                "      accept_requests: true",
            ]
        )
    )
    return cfg_path


def test_build_inventory_and_registration_payload(tmp_path: Path) -> None:
    cfg = load_config(_write_node_config(tmp_path))
    inventory = build_inventory(cfg)
    payload = build_registration_payload(cfg)
    heartbeat = build_heartbeat_payload(cfg)

    assert inventory.host_id == "atlas-01"
    assert inventory.address == "192.168.1.101"
    assert inventory.capabilities["cuda"] is True
    assert inventory.resources["cpu_threads"] == 24
    assert len(inventory.resources["discovered_models"]) == 1
    assert inventory.services[0]["host_id"] == "atlas-01"
    assert inventory.services[0]["service_id"] == "atlas-01/chat/qwen3-8b"
    assert payload["services"][0]["kind"] == "chat"
    assert heartbeat["host_id"] == "atlas-01"
    assert heartbeat["metrics"]["service_count"] == 1
    assert heartbeat["metrics"]["healthy_service_count"] == 1


def test_node_app_exposes_inventory_routes(tmp_path: Path) -> None:
    app = create_app(_write_node_config(tmp_path), sync_enabled=False)
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/v1/node/inventory" in paths
    assert "/v1/node/registration" in paths


class _FakePoster:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url: str, *, json: dict, headers: dict[str, str] | None = None) -> object:
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        return object()


def test_control_plane_client_posts_register_and_heartbeat(tmp_path: Path) -> None:
    cfg_path = _write_node_config(tmp_path)
    cfg = load_config(cfg_path)
    cfg.control_plane.base_url = "http://127.0.0.1:8800"
    cfg.control_plane.node_api_key = "node-key"
    fake = _FakePoster()
    client = ControlPlaneClient(cfg, http_client=fake)

    async def run() -> None:
        await client.register_once()
        await client.heartbeat_once()

    asyncio.run(run())

    assert len(fake.calls) == 2
    assert fake.calls[0]["url"] == "http://127.0.0.1:8800/v1/nodes/register"
    assert fake.calls[0]["headers"]["X-GenieHive-Node-Key"] == "node-key"
    assert fake.calls[0]["json"]["host_id"] == "atlas-01"
    assert fake.calls[1]["url"] == "http://127.0.0.1:8800/v1/nodes/heartbeat"
    assert fake.calls[1]["json"]["metrics"]["service_count"] == 1
