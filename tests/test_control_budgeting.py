from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geniehive_control.budgeting import calculate_estimated_cost_cents, monthly_period_start
from geniehive_control.config import ModelPrice
from geniehive_control.keys import hash_api_key
from geniehive_control.main import create_app
from geniehive_control.models import HostRegistration, RegisteredService
from geniehive_control.registry import Registry
from geniehive_control.upstream import UpstreamClient


PRICES = {
    "test-model": ModelPrice(
        input_microdollars_per_million=1_000_000,
        output_microdollars_per_million=2_000_000,
    )
}


def test_cost_uses_exact_model_and_rounds_to_cents() -> None:
    result = calculate_estimated_cost_cents(
        "test-model",
        {"prompt_tokens": 1_000, "completion_tokens": 500},
        PRICES,
    )

    assert result == Decimal("0.20")


def test_unknown_model_does_not_fall_back_to_another_price() -> None:
    assert calculate_estimated_cost_cents(
        "test-model-alias",
        {"prompt_tokens": 1, "completion_tokens": 1},
        PRICES,
    ) is None


def test_zero_usage_is_a_known_zero_cost() -> None:
    assert calculate_estimated_cost_cents(
        "test-model",
        {"prompt_tokens": 0, "completion_tokens": 0},
        PRICES,
    ) == Decimal("0.00")


def test_missing_usage_is_unknown_cost() -> None:
    assert calculate_estimated_cost_cents("test-model", {}, PRICES) is None


def test_monthly_period_start_uses_configured_reset_day() -> None:
    july_14 = datetime(2026, 7, 14, 12, tzinfo=timezone.utc).timestamp()
    july_15 = datetime(2026, 7, 15, 12, tzinfo=timezone.utc).timestamp()

    assert monthly_period_start(july_14, 15) == datetime(2026, 6, 15, tzinfo=timezone.utc).timestamp()
    assert monthly_period_start(july_15, 15) == datetime(2026, 7, 15, tzinfo=timezone.utc).timestamp()


class _BudgetResponse:
    status_code = 200

    def __init__(self, model: str) -> None:
        self._payload = {
            "object": "chat.completion",
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
        self.text = str(self._payload)

    def json(self) -> dict:
        return self._payload


class _BudgetPoster:
    def __init__(self) -> None:
        self.calls = 0

    async def post(self, url: str, *, json: dict, headers: dict[str, str] | None = None):
        self.calls += 1
        return _BudgetResponse(json["model"])


def _write_token_budget_config(tmp_path: Path, *, enabled: bool = True) -> Path:
    path = tmp_path / "control.yaml"
    path.write_text(
        f"""
auth:
  enable_named_client_keys: true
audit:
  enabled: true
budgeting:
  enabled: {str(enabled).lower()}
  reset_day_of_month: 1
storage:
  sqlite_path: "{tmp_path / 'geniehive.sqlite3'}"
"""
    )
    return path


def _register_budget_service(app) -> None:
    app.state.registry.register_host(
        HostRegistration(
            host_id="budget-host",
            address="127.0.0.1",
            services=[
                RegisteredService(
                    service_id="budget-host/chat/test-model",
                    host_id="budget-host",
                    kind="chat",
                    endpoint="http://127.0.0.1:18091",
                    assets=[{"asset_id": "test-model", "loaded": True}],
                    state={"health": "healthy", "accept_requests": True},
                )
            ],
        )
    )


def _create_budget_key(app, raw_key: str, limit: int) -> None:
    app.state.registry.create_client_key(
        key_id=f"ck_{raw_key}",
        key_hash=hash_api_key(raw_key, secret="budget-secret"),
        display_name=raw_key,
        principal_type="person",
        principal_ref=raw_key,
        monthly_token_limit=limit,
    )


def test_named_key_is_rejected_at_monthly_token_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENIEHIVE_KEY_HASH_SECRET", "budget-secret")
    poster = _BudgetPoster()
    app = create_app(
        _write_token_budget_config(tmp_path),
        upstream_client=UpstreamClient(client=poster),
        clock=lambda: datetime(2026, 7, 14, 12, tzinfo=timezone.utc).timestamp(),
    )
    _register_budget_service(app)
    _create_budget_key(app, "budget-one", limit=10)
    client = TestClient(app)
    payload = {"model": "test-model", "messages": [{"role": "user", "content": "hello"}]}

    assert client.post("/v1/chat/completions", headers={"X-Api-Key": "budget-one"}, json=payload).status_code == 200
    assert client.post("/v1/chat/completions", headers={"X-Api-Key": "budget-one"}, json=payload).status_code == 200
    denied = client.post("/v1/chat/completions", headers={"X-Api-Key": "budget-one"}, json=payload)

    assert denied.status_code == 429
    assert denied.json()["error"]["code"] == "budget_exceeded"
    assert poster.calls == 2


def test_budget_is_independent_per_named_key_and_can_be_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENIEHIVE_KEY_HASH_SECRET", "budget-secret")
    poster = _BudgetPoster()
    app = create_app(
        _write_token_budget_config(tmp_path, enabled=False),
        upstream_client=UpstreamClient(client=poster),
        clock=lambda: datetime(2026, 7, 14, 12, tzinfo=timezone.utc).timestamp(),
    )
    _register_budget_service(app)
    _create_budget_key(app, "budget-one", limit=0)
    _create_budget_key(app, "budget-two", limit=5)
    client = TestClient(app)
    payload = {"model": "test-model", "messages": [{"role": "user", "content": "hello"}]}

    assert client.post("/v1/chat/completions", headers={"X-Api-Key": "budget-one"}, json=payload).status_code == 200
    assert client.post("/v1/chat/completions", headers={"X-Api-Key": "budget-two"}, json=payload).status_code == 200
    assert poster.calls == 2


def test_cost_usage_query_scopes_key_and_provider(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "usage.sqlite3")
    common = {
        "principal_type": "person",
        "principal_ref": "test",
        "operation": "chat",
        "requested_model": "test-model",
        "resolved_service_id": "svc",
        "resolved_host_id": "host",
        "upstream_model": "test-model",
        "started_at": 100.0,
        "finished_at": 101.0,
        "status_code": 200,
        "success": True,
    }
    registry.record_request_audit(request_id="one", key_id="key-one", provider_kind="openai", estimated_cost_cents=1.25, **common)
    registry.record_request_audit(request_id="two", key_id="key-two", provider_kind="openai", estimated_cost_cents=2.50, **common)
    registry.record_request_audit(request_id="three", key_id="key-one", provider_kind="other", estimated_cost_cents=4.00, **common)

    assert registry.request_cost_cents_since(started_at=100.0, key_id="key-one") == [1.25, 4.0]
    assert registry.request_cost_cents_since(started_at=100.0, provider_kind="openai") == [1.25, 2.5]
