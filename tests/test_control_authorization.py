from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geniehive_control.keys import hash_api_key
from geniehive_control.main import create_app
from geniehive_control.models import HostRegistration, RegisteredService
from geniehive_control.upstream import UpstreamClient


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakePoster:
    async def post(self, url: str, *, json: dict, headers: dict[str, str] | None = None) -> _FakeResponse:
        if url.endswith("/v1/embeddings"):
            return _FakeResponse({"object": "list", "data": [{"embedding": [0.1, 0.2]}]})
        return _FakeResponse({"object": "chat.completion", "model": json["model"], "choices": []})


def _write_config(tmp_path: Path, *, static_key: bool = False) -> Path:
    config_path = tmp_path / "control.yaml"
    static_auth = """
  client_api_keys:
    - static-key
""" if static_key else ""
    config_path.write_text(
        f"""
auth:
{static_auth}  enable_named_client_keys: true
authorization:
  enforce_model_allowlists: true
  enforce_operation_allowlists: true
  empty_allowlist_means_no_access: true
storage:
  sqlite_path: "{tmp_path / 'geniehive.sqlite3'}"
"""
    )
    return config_path


def _register_services(app) -> None:
    app.state.registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="127.0.0.1",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/qwen",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://127.0.0.1:18091",
                    assets=[{"asset_id": "archive_migrator", "loaded": True}],
                    state={"health": "healthy", "accept_requests": True},
                    observed={"p50_latency_ms": 100},
                ),
                RegisteredService(
                    service_id="atlas-01/embeddings/bge",
                    host_id="atlas-01",
                    kind="embeddings",
                    endpoint="http://127.0.0.1:18092",
                    assets=[{"asset_id": "bge-small", "loaded": True}],
                    state={"health": "healthy", "accept_requests": True},
                    observed={"p50_latency_ms": 100},
                ),
            ],
        )
    )


def _create_named_key(
    app,
    raw_key: str,
    *,
    allowed_models: list[str],
    allowed_operations: list[str],
) -> None:
    app.state.registry.create_client_key(
        key_id=f"ck_{raw_key}",
        key_hash=hash_api_key(raw_key, secret="test-secret"),
        display_name="Scoped User",
        principal_type="person",
        principal_ref="scoped-user",
        role="developer",
        allowed_models=allowed_models,
        allowed_operations=allowed_operations,
    )


def test_named_key_allows_scoped_chat_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENIEHIVE_KEY_HASH_SECRET", "test-secret")
    app = create_app(_write_config(tmp_path), upstream_client=UpstreamClient(client=_FakePoster()))
    _register_services(app)
    _create_named_key(
        app,
        "gh_allowed",
        allowed_models=["archive_migrator"],
        allowed_operations=["chat"],
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"X-Api-Key": "gh_allowed"},
        json={"model": "archive_migrator", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200


def test_named_key_denies_unlisted_operation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENIEHIVE_KEY_HASH_SECRET", "test-secret")
    app = create_app(_write_config(tmp_path), upstream_client=UpstreamClient(client=_FakePoster()))
    _register_services(app)
    _create_named_key(
        app,
        "gh_chat_only",
        allowed_models=["*"],
        allowed_operations=["chat"],
    )
    client = TestClient(app)

    response = client.post(
        "/v1/embeddings",
        headers={"X-Api-Key": "gh_chat_only"},
        json={"model": "bge-small", "input": "hello"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "authorization_error"


def test_named_key_denies_unlisted_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENIEHIVE_KEY_HASH_SECRET", "test-secret")
    app = create_app(_write_config(tmp_path), upstream_client=UpstreamClient(client=_FakePoster()))
    _register_services(app)
    _create_named_key(
        app,
        "gh_archive_only",
        allowed_models=["archive_migrator"],
        allowed_operations=["chat"],
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"X-Api-Key": "gh_archive_only"},
        json={"model": "other_role", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "authorization_error"


def test_empty_allowlist_denies_when_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENIEHIVE_KEY_HASH_SECRET", "test-secret")
    app = create_app(_write_config(tmp_path), upstream_client=UpstreamClient(client=_FakePoster()))
    _register_services(app)
    _create_named_key(
        app,
        "gh_empty",
        allowed_models=[],
        allowed_operations=[],
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"X-Api-Key": "gh_empty"},
        json={"model": "archive_migrator", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 403


def test_static_key_is_not_restricted_by_named_key_allowlists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GENIEHIVE_KEY_HASH_SECRET", "test-secret")
    app = create_app(
        _write_config(tmp_path, static_key=True),
        upstream_client=UpstreamClient(client=_FakePoster()),
    )
    _register_services(app)
    client = TestClient(app)

    response = client.post(
        "/v1/embeddings",
        headers={"X-Api-Key": "static-key"},
        json={"model": "bge-small", "input": "hello"},
    )

    assert response.status_code == 200
