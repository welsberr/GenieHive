import json
from pathlib import Path

from fastapi.testclient import TestClient

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


class _UsagePoster:
    async def post(self, url: str, *, json: dict, headers: dict[str, str] | None = None) -> _FakeResponse:
        return _FakeResponse(
            {
                "object": "chat.completion",
                "model": json["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "done"}}],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                    "total_tokens": 10,
                },
            }
        )


def _write_audit_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "control.yaml"
    config_path.write_text(
        f"""
auth:
  client_api_keys:
    - audit-key
audit:
  enabled: true
admin_api:
  enabled: true
storage:
  sqlite_path: "{tmp_path / 'geniehive.sqlite3'}"
"""
    )
    return config_path


def _register_chat_service(app) -> None:
    app.state.registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="127.0.0.1",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/qwen",
                    host_id="atlas-01",
                    kind="chat",
                    protocol="openai",
                    endpoint="http://127.0.0.1:18091",
                    assets=[{"asset_id": "qwen-test", "loaded": True}],
                    state={"health": "healthy", "accept_requests": True},
                    observed={"p50_latency_ms": 100},
                )
            ],
        )
    )


def test_successful_chat_request_is_audited_without_prompt_content(tmp_path: Path) -> None:
    app = create_app(_write_audit_config(tmp_path), upstream_client=UpstreamClient(client=_UsagePoster()))
    _register_chat_service(app)
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"X-Api-Key": "audit-key", "X-Request-Id": "req-test-success"},
        json={
            "model": "qwen-test",
            "messages": [{"role": "user", "content": "private prompt text"}],
        },
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-test-success"

    row = app.state.registry.get_request_audit("req-test-success")
    assert row is not None
    assert row["operation"] == "chat"
    assert row["requested_model"] == "qwen-test"
    assert row["resolved_service_id"] == "atlas-01/chat/qwen"
    assert row["upstream_model"] == "qwen-test"
    assert row["provider_kind"] == "openai"
    assert row["success"] is True
    assert row["status_code"] == 200
    assert row["prompt_tokens"] == 7
    assert row["completion_tokens"] == 3
    assert row["total_tokens"] == 10
    assert "private prompt text" not in json.dumps(row)


def test_failed_chat_route_is_audited(tmp_path: Path) -> None:
    app = create_app(_write_audit_config(tmp_path), upstream_client=UpstreamClient(client=_UsagePoster()))
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"X-Api-Key": "audit-key", "X-Request-Id": "req-test-failure"},
        json={
            "model": "missing-model",
            "messages": [{"role": "user", "content": "private failure prompt"}],
        },
    )

    assert response.status_code == 404
    assert response.headers["x-request-id"] == "req-test-failure"

    row = app.state.registry.get_request_audit("req-test-failure")
    assert row is not None
    assert row["operation"] == "chat"
    assert row["requested_model"] == "missing-model"
    assert row["success"] is False
    assert row["status_code"] == 404
    assert row["error_type"] == "proxy_error"
    assert "private failure prompt" not in json.dumps(row)


def test_admin_audit_endpoints_list_and_summarize_requests(tmp_path: Path) -> None:
    app = create_app(_write_audit_config(tmp_path), upstream_client=UpstreamClient(client=_UsagePoster()))
    _register_chat_service(app)
    client = TestClient(app)
    client.post(
        "/v1/chat/completions",
        headers={"X-Api-Key": "audit-key"},
        json={"model": "qwen-test", "messages": [{"role": "user", "content": "hello"}]},
    )

    listed = client.get("/v1/admin/audit/requests", headers={"X-Api-Key": "audit-key"})
    assert listed.status_code == 200
    assert listed.json()["data"][0]["requested_model"] == "qwen-test"

    summary = client.get("/v1/admin/audit/summary", headers={"X-Api-Key": "audit-key"})
    assert summary.status_code == 200
    summary_row = summary.json()["data"][0]
    assert summary_row["requested_model"] == "qwen-test"
    assert summary_row["request_count"] == 1
    assert summary_row["success_count"] == 1
    assert summary_row["total_tokens"] == 10
