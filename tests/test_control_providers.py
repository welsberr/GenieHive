from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geniehive_control.config import ProviderConfig
from geniehive_control.main import create_app
from geniehive_control.providers import ConfiguredProviders, ProviderConfigurationError
from geniehive_control.upstream import UpstreamClient


class _FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _RecordingPoster:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url: str, *, json: dict, headers: dict[str, str] | None = None) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        return _FakeResponse(
            {
                "object": "chat.completion",
                "model": json["model"],
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            }
        )


def _write_provider_config(tmp_path: Path) -> Path:
    path = tmp_path / "control.yaml"
    path.write_text(
        f"""
auth:
  client_api_keys: [client-key]
storage:
  sqlite_path: "{tmp_path / 'geniehive.sqlite3'}"
providers:
  - provider_id: test-cloud
    provider_kind: openai_compatible
    base_url: https://provider.example
    api_key_env: TEST_CLOUD_API_KEY
    default_headers:
      X-Provider-Tenant: foundation
    models: [cloud-test-model]
    enabled: true
"""
    )
    return path


def test_configured_provider_registers_model_and_resolves_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_CLOUD_API_KEY", "secret-key")
    poster = _RecordingPoster()
    app = create_app(
        _write_provider_config(tmp_path),
        upstream_client=UpstreamClient(client=poster),
    )
    client = TestClient(app)

    models = client.get("/v1/models", headers={"X-Api-Key": "client-key"})
    assert models.status_code == 200
    assert "cloud-test-model" in {item["id"] for item in models.json()["data"]}

    response = client.post(
        "/v1/chat/completions",
        headers={"X-Api-Key": "client-key"},
        json={
            "model": "cloud-test-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    assert poster.calls[0]["url"] == "https://provider.example/v1/chat/completions"
    assert poster.calls[0]["headers"] == {
        "Authorization": "Bearer secret-key",
        "X-Provider-Tenant": "foundation",
    }


def test_missing_provider_credential_returns_service_unavailable(tmp_path: Path) -> None:
    app = create_app(
        _write_provider_config(tmp_path),
        upstream_client=UpstreamClient(client=_RecordingPoster()),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"X-Api-Key": "client-key"},
        json={
            "model": "cloud-test-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 503
    assert "TEST_CLOUD_API_KEY" in response.json()["error"]["message"]


def test_missing_streaming_credential_fails_before_stream_starts(tmp_path: Path) -> None:
    app = create_app(
        _write_provider_config(tmp_path),
        upstream_client=UpstreamClient(client=_RecordingPoster()),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"X-Api-Key": "client-key"},
        json={
            "model": "cloud-test-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")


def test_enabled_unsupported_provider_is_rejected() -> None:
    with pytest.raises(ProviderConfigurationError, match="unsupported kind"):
        ConfiguredProviders(
            [
                ProviderConfig(
                    provider_id="anthropic",
                    provider_kind="anthropic_messages",
                    base_url="https://api.anthropic.com",
                    models=["claude-test"],
                )
            ]
        )


def test_disabling_provider_removes_persisted_external_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_CLOUD_API_KEY", "secret-key")
    config_path = _write_provider_config(tmp_path)
    enabled_app = create_app(config_path)
    assert "cloud-test-model" in {
        item["id"] for item in enabled_app.state.registry.list_client_models()
    }

    config_path.write_text(
        f"""
storage:
  sqlite_path: "{tmp_path / 'geniehive.sqlite3'}"
providers:
  - provider_id: test-cloud
    provider_kind: openai_compatible
    base_url: https://provider.example
    models: [cloud-test-model]
    enabled: false
"""
    )
    disabled_app = create_app(config_path)

    assert "cloud-test-model" not in {
        item["id"] for item in disabled_app.state.registry.list_client_models()
    }
