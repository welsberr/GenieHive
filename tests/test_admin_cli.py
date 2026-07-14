import json

from geniehive_control import admin_cli


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise admin_cli.httpx.HTTPStatusError(
                "request failed", request=admin_cli.httpx.Request("GET", "http://test"), response=admin_cli.httpx.Response(self.status_code)
            )

    def json(self) -> dict:
        return self.payload


class _Client:
    instances: list["_Client"] = []

    def __init__(self, **kwargs) -> None:
        self.calls: list[tuple] = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return _Response({"object": "list", "data": [{"key_id": "ck_1", "key_hash": "secret"}]})

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return _Response({"status": "ok", "api_key": "raw-once", "client_key": {"key_hash": "secret"}})


def test_client_key_create_uses_env_and_never_prints_hash(monkeypatch, capsys) -> None:
    _Client.instances.clear()
    monkeypatch.setenv("GENIEHIVE_ADMIN_KEY", "admin-secret")
    monkeypatch.setattr(admin_cli.httpx, "Client", _Client)

    result = admin_cli.main(
        [
            "--base-url",
            "http://gateway",
            "client-key",
            "create",
            "--display-name",
            "Archive",
            "--principal-type",
            "person",
            "--principal-ref",
            "alice",
            "--allowed-model",
            "archive_migrator",
        ]
    )

    assert result == 0
    call = _Client.instances[0].calls[0]
    assert call[0] == "POST"
    assert call[1] == "http://gateway/v1/admin/client-keys"
    assert call[2]["headers"] == {"X-Api-Key": "admin-secret"}
    assert call[2]["json"]["allowed_models"] == ["archive_migrator"]
    output = capsys.readouterr().out
    assert "raw-once" in output
    assert "secret" not in output


def test_audit_list_serializes_filters_and_missing_key_fails(monkeypatch, capsys) -> None:
    _Client.instances.clear()
    monkeypatch.setattr(admin_cli.httpx, "Client", _Client)

    result = admin_cli.main(
        [
            "--admin-key",
            "admin-secret",
            "audit",
            "list",
            "--operation",
            "chat",
            "--success",
            "false",
            "--limit",
            "5",
        ]
    )
    assert result == 0
    params = _Client.instances[0].calls[0][2]["params"]
    assert params == {"operation": "chat", "success": "false", "limit": 5}

    assert admin_cli.main(["audit", "summary"]) == 2
    assert "required" in capsys.readouterr().err
