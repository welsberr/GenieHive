import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from geniehive_node.config import load_config
from geniehive_node.discovery import discover_ollama_assets, discover_openai_models, enrich_service_assets, query_ollama_ps
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


def test_discover_ollama_assets_parses_api_tags_response() -> None:
    ollama_response = {
        "models": [
            {"name": "qwen3:8b", "size": 12345678},
            {"name": "nomic-embed-text", "size": 987654},
        ]
    }

    async def run() -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ollama_response
        mock_client.get = AsyncMock(return_value=mock_response)

        assets = await discover_ollama_assets("http://127.0.0.1:11434", client=mock_client)
        assert len(assets) == 2
        # /api/tags → available, NOT necessarily loaded
        assert assets[0] == {"asset_id": "qwen3:8b", "loaded": False}
        assert assets[1] == {"asset_id": "nomic-embed-text", "loaded": False}
        mock_client.get.assert_called_once_with("http://127.0.0.1:11434/api/tags")

    asyncio.run(run())


def test_query_ollama_ps_returns_loaded_model_names() -> None:
    ps_response = {
        "models": [
            {"name": "qwen3:8b", "size_in_vram": 5000000000},
        ]
    }

    async def run() -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ps_response
        mock_client.get = AsyncMock(return_value=mock_response)

        loaded = await query_ollama_ps("http://127.0.0.1:11434", client=mock_client)
        assert loaded == frozenset({"qwen3:8b"})
        mock_client.get.assert_called_once_with("http://127.0.0.1:11434/api/ps")

    asyncio.run(run())


def test_discover_ollama_assets_returns_empty_on_error() -> None:
    async def run() -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        assets = await discover_ollama_assets("http://127.0.0.1:11434", client=mock_client)
        assert assets == []

    asyncio.run(run())


def test_enrich_service_assets_skips_when_protocol_none() -> None:
    service = {"service_id": "svc-1", "endpoint": "http://127.0.0.1:11434", "assets": []}

    async def run() -> None:
        result = await enrich_service_assets(service, protocol=None)
        assert result is service  # unchanged, no HTTP queries made

    asyncio.run(run())


def test_enrich_ollama_marks_loaded_state_via_api_ps_and_adds_new_assets() -> None:
    """Ollama enrichment: tags gives available, ps gives loaded; static assets updated."""
    tags_response = {"models": [{"name": "qwen3:8b"}, {"name": "nomic-embed"}]}
    ps_response = {"models": [{"name": "qwen3:8b"}]}  # only qwen3 is in VRAM

    service = {
        "service_id": "svc-1",
        "endpoint": "http://127.0.0.1:11434",
        # Static config has qwen3:8b as loaded (stale info) and rocket-3b not listed at all.
        "assets": [
            {"asset_id": "qwen3:8b", "loaded": True},
        ],
    }

    call_log: list[str] = []

    async def run() -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        async def fake_get(url: str):
            call_log.append(url)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            if url.endswith("/api/tags"):
                mock_resp.json.return_value = tags_response
            else:
                mock_resp.json.return_value = ps_response
            return mock_resp

        mock_client.get = AsyncMock(side_effect=fake_get)

        enriched = await enrich_service_assets(service, protocol="ollama", client=mock_client)

        assets_by_id = {a["asset_id"]: a for a in enriched["assets"]}
        # qwen3:8b is in /api/ps → loaded: True (preserved)
        assert assets_by_id["qwen3:8b"]["loaded"] is True
        # nomic-embed is in /api/tags but NOT in /api/ps → loaded: False, added as new asset
        assert assets_by_id["nomic-embed"]["loaded"] is False
        # Both endpoints were queried.
        assert any("/api/tags" in u for u in call_log)
        assert any("/api/ps" in u for u in call_log)

    asyncio.run(run())


def test_enrich_ollama_populates_observed_metrics_from_ps() -> None:
    """Ollama enrichment populates observed.loaded_model_count and vram_used_bytes."""
    tags_response = {"models": [{"name": "qwen3:8b"}, {"name": "nomic-embed"}]}
    ps_response = {
        "models": [
            {"name": "qwen3:8b", "size_in_vram": 5_000_000_000},
        ]
    }

    service = {
        "service_id": "svc-1",
        "endpoint": "http://127.0.0.1:11434",
        "assets": [],
    }

    async def run() -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        async def fake_get(url: str):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = tags_response if "/api/tags" in url else ps_response
            return mock_resp

        mock_client.get = AsyncMock(side_effect=fake_get)
        enriched = await enrich_service_assets(service, protocol="ollama", client=mock_client)
        assert enriched["observed"]["loaded_model_count"] == 1
        assert enriched["observed"]["vram_used_bytes"] == 5_000_000_000

    asyncio.run(run())


def test_enrich_ollama_updates_stale_loaded_state_to_false() -> None:
    """Static config says loaded=True but /api/ps reports it is not; should be corrected."""
    tags_response = {"models": [{"name": "big-model"}]}
    ps_response = {"models": []}  # nothing loaded

    service = {
        "service_id": "svc-1",
        "endpoint": "http://127.0.0.1:11434",
        "assets": [{"asset_id": "big-model", "loaded": True}],
    }

    async def run() -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        async def fake_get(url: str):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = tags_response if "/api/tags" in url else ps_response
            return mock_resp

        mock_client.get = AsyncMock(side_effect=fake_get)
        enriched = await enrich_service_assets(service, protocol="ollama", client=mock_client)
        assert enriched["assets"][0]["loaded"] is False  # stale state corrected

    asyncio.run(run())


def test_discover_openai_models_parses_v1_models_response() -> None:
    openai_response = {
        "object": "list",
        "data": [
            {"id": "mistral-7b-instruct", "object": "model"},
            {"id": "nomic-embed-text-v1", "object": "model"},
        ],
    }

    async def run() -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = openai_response
        mock_client.get = AsyncMock(return_value=mock_response)

        assets = await discover_openai_models("http://127.0.0.1:8000", client=mock_client)
        assert len(assets) == 2
        assert assets[0] == {"asset_id": "mistral-7b-instruct", "loaded": True}
        assert assets[1] == {"asset_id": "nomic-embed-text-v1", "loaded": True}
        mock_client.get.assert_called_once_with("http://127.0.0.1:8000/v1/models")

    asyncio.run(run())


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
