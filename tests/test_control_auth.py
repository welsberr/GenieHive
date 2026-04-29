from pathlib import Path

import pytest
from fastapi import Depends, Request
from fastapi.testclient import TestClient

from geniehive_control.auth import require_client_auth
from geniehive_control.keys import hash_api_key
from geniehive_control.main import create_app


def _write_config(tmp_path: Path, body: str) -> Path:
    config_path = tmp_path / "control.yaml"
    config_path.write_text(body)
    return config_path


def test_static_client_key_auth_still_works(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        f"""
auth:
  client_api_keys:
    - static-key
storage:
  sqlite_path: "{tmp_path / 'geniehive.sqlite3'}"
""",
    )
    app = create_app(config_path)
    client = TestClient(app)

    assert client.get("/v1/models").status_code == 401
    ok = client.get("/v1/models", headers={"X-Api-Key": "static-key"})
    assert ok.status_code == 200


def test_empty_static_keys_still_allow_development_access(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        f"""
storage:
  sqlite_path: "{tmp_path / 'geniehive.sqlite3'}"
""",
    )
    app = create_app(config_path)
    client = TestClient(app)

    response = client.get("/v1/models")
    assert response.status_code == 200


def test_named_client_key_auth_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENIEHIVE_KEY_HASH_SECRET", "test-secret")
    db_path = tmp_path / "geniehive.sqlite3"
    config_path = _write_config(
        tmp_path,
        f"""
auth:
  enable_named_client_keys: true
storage:
  sqlite_path: "{db_path}"
""",
    )
    app = create_app(config_path)
    raw_key = "gh_test_named"
    app.state.registry.create_client_key(
        key_id="ck_named",
        key_hash=hash_api_key(raw_key, secret="test-secret"),
        display_name="Named User",
        principal_type="person",
        principal_ref="named-user",
        role="developer",
        allowed_models=["archive_migrator"],
        allowed_operations=["chat"],
    )

    @app.get("/_test/client-context")
    async def client_context(request: Request, _=Depends(require_client_auth)) -> dict:
        context = request.state.client_context
        return {
            "auth_kind": context.auth_kind,
            "key_id": context.key_id,
            "principal_ref": context.principal_ref,
            "allowed_models": list(context.allowed_models),
            "allowed_operations": list(context.allowed_operations),
        }

    client = TestClient(app)

    missing = client.get("/_test/client-context")
    assert missing.status_code == 401

    bad = client.get("/_test/client-context", headers={"X-Api-Key": "wrong"})
    assert bad.status_code == 401

    ok = client.get("/_test/client-context", headers={"X-Api-Key": raw_key})
    assert ok.status_code == 200
    assert ok.json() == {
        "auth_kind": "named",
        "key_id": "ck_named",
        "principal_ref": "named-user",
        "allowed_models": ["archive_migrator"],
        "allowed_operations": ["chat"],
    }
    touched = app.state.registry.get_client_key("ck_named")
    assert touched is not None
    assert touched["last_used_at"] is not None


def test_disabled_named_client_key_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENIEHIVE_KEY_HASH_SECRET", "test-secret")
    db_path = tmp_path / "geniehive.sqlite3"
    config_path = _write_config(
        tmp_path,
        f"""
auth:
  enable_named_client_keys: true
storage:
  sqlite_path: "{db_path}"
""",
    )
    app = create_app(config_path)
    raw_key = "gh_test_disabled"
    app.state.registry.create_client_key(
        key_id="ck_disabled",
        key_hash=hash_api_key(raw_key, secret="test-secret"),
        display_name="Disabled User",
        principal_type="person",
        principal_ref="disabled-user",
        enabled=False,
    )
    client = TestClient(app)

    response = client.get("/v1/models", headers={"X-Api-Key": raw_key})
    assert response.status_code == 401


def test_admin_client_key_endpoints_are_hidden_by_default() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/v1/admin/client-keys" not in paths


def test_admin_can_create_list_disable_and_enable_named_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GENIEHIVE_KEY_HASH_SECRET", "test-secret")
    db_path = tmp_path / "geniehive.sqlite3"
    config_path = _write_config(
        tmp_path,
        f"""
auth:
  client_api_keys:
    - admin-static-key
  enable_named_client_keys: true
admin_api:
  enabled: true
storage:
  sqlite_path: "{db_path}"
""",
    )
    app = create_app(config_path)
    client = TestClient(app)

    denied = client.get("/v1/admin/client-keys")
    assert denied.status_code == 401

    created = client.post(
        "/v1/admin/client-keys",
        headers={"X-Api-Key": "admin-static-key"},
        json={
            "key_id": "ck_created",
            "display_name": "Archive Migration",
            "principal_type": "person",
            "principal_ref": "wesley",
            "role": "developer",
            "allowed_models": ["archive_migrator"],
            "allowed_operations": ["chat"],
        },
    )
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["api_key"].startswith("gh_")
    assert created_body["client_key"]["key_id"] == "ck_created"
    assert "key_hash" not in created_body["client_key"]

    listed = client.get(
        "/v1/admin/client-keys",
        headers={"X-Api-Key": "admin-static-key"},
    )
    assert listed.status_code == 200
    assert listed.json()["data"][0]["key_id"] == "ck_created"
    assert "key_hash" not in listed.json()["data"][0]

    disabled = client.post(
        "/v1/admin/client-keys/ck_created/disable",
        headers={"X-Api-Key": "admin-static-key"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["client_key"]["enabled"] is False

    named_denied = client.get(
        "/v1/models",
        headers={"X-Api-Key": created_body["api_key"]},
    )
    assert named_denied.status_code == 401

    enabled = client.post(
        "/v1/admin/client-keys/ck_created/enable",
        headers={"X-Api-Key": "admin-static-key"},
    )
    assert enabled.status_code == 200
    assert enabled.json()["client_key"]["enabled"] is True

    named_ok = client.get(
        "/v1/models",
        headers={"X-Api-Key": created_body["api_key"]},
    )
    assert named_ok.status_code == 200
