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


def _write_cost_budget_config(
    tmp_path: Path,
    *,
    key_budget: int | None = None,
    provider_budget: int | None = None,
    global_budget: int | None = None,
    deny_unknown: bool = False,
    priced: bool = True,
    static: bool = False,
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    auth = "  client_api_keys:\n    - static-key\n" if static else "  enable_named_client_keys: true\n"
    prices = (
        "  model_prices:\n    test-model:\n"
        "      input_microdollars_per_million: 1000000000\n"
        "      output_microdollars_per_million: 1000000000\n"
        if priced
        else ""
    )
    path = tmp_path / "cost-control.yaml"
    path.write_text(
        f"""
auth:
{auth}audit:
  enabled: true
budgeting:
  enabled: true
  deny_on_unknown_cost: {str(deny_unknown).lower()}
  provider_monthly_budget_cents:
    openai: {provider_budget if provider_budget is not None else 0}
  global_monthly_budget_cents: {global_budget if global_budget is not None else 'null'}
{prices}storage:
  sqlite_path: "{tmp_path / 'cost-geniehive.sqlite3'}"
"""
    )
    if provider_budget is None:
        text = path.read_text().replace("  provider_monthly_budget_cents:\n    openai: 0\n", "  provider_monthly_budget_cents: {}\n")
        path.write_text(text)
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


def _create_budget_key(
    app,
    raw_key: str,
    limit: int | None,
    *,
    monthly_budget_cents: int | None = None,
) -> None:
    app.state.registry.create_client_key(
        key_id=f"ck_{raw_key}",
        key_hash=hash_api_key(raw_key, secret="budget-secret"),
        display_name=raw_key,
        principal_type="person",
        principal_ref=raw_key,
        monthly_token_limit=limit,
        monthly_budget_cents=monthly_budget_cents,
    )


def _seed_cost(app, *, key_id: str | None, cents: float, provider_kind: str = "openai") -> None:
    app.state.registry.record_request_audit(
        request_id=f"seed-{key_id or provider_kind}-{cents}",
        key_id=key_id,
        principal_type="person" if key_id else None,
        principal_ref=key_id,
        operation="chat",
        requested_model="test-model",
        resolved_service_id="budget-host/chat/test-model",
        resolved_host_id="budget-host",
        upstream_model="test-model",
        provider_kind=provider_kind,
        started_at=datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp(),
        finished_at=datetime(2026, 7, 1, 0, 0, 1, tzinfo=timezone.utc).timestamp(),
        status_code=200,
        success=True,
        total_tokens=1,
        estimated_cost_cents=cents,
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


def test_key_cost_budget_allows_below_limit_then_denies_at_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENIEHIVE_KEY_HASH_SECRET", "budget-secret")
    poster = _BudgetPoster()
    app = create_app(
        _write_cost_budget_config(tmp_path, key_budget=1),
        upstream_client=UpstreamClient(client=poster),
        clock=lambda: datetime(2026, 7, 14, 12, tzinfo=timezone.utc).timestamp(),
    )
    _register_budget_service(app)
    _create_budget_key(app, "cost-key", limit=None, monthly_budget_cents=1)
    _seed_cost(app, key_id="ck_cost-key", cents=0.5)
    client = TestClient(app)
    payload = {"model": "test-model", "messages": [{"role": "user", "content": "hello"}]}

    assert client.post("/v1/chat/completions", headers={"X-Api-Key": "cost-key"}, json=payload).status_code == 200
    denied = client.post("/v1/chat/completions", headers={"X-Api-Key": "cost-key"}, json=payload)

    assert denied.status_code == 429
    assert denied.json()["error"]["code"] == "budget_exceeded"
    assert poster.calls == 1


def test_provider_and_global_cost_limits_apply_to_static_keys(tmp_path: Path) -> None:
    poster = _BudgetPoster()
    app = create_app(
        _write_cost_budget_config(tmp_path, provider_budget=1, static=True),
        upstream_client=UpstreamClient(client=poster),
        clock=lambda: datetime(2026, 7, 14, 12, tzinfo=timezone.utc).timestamp(),
    )
    _register_budget_service(app)
    _seed_cost(app, key_id=None, cents=1.0, provider_kind="openai")
    client = TestClient(app)
    payload = {"model": "test-model", "messages": [{"role": "user", "content": "hello"}]}

    denied = client.post("/v1/chat/completions", headers={"X-Api-Key": "static-key"}, json=payload)

    assert denied.status_code == 429
    assert denied.json()["error"]["code"] == "budget_exceeded"
    assert poster.calls == 0


def test_global_cost_limit_and_unknown_price_policy(tmp_path: Path) -> None:
    poster = _BudgetPoster()
    app = create_app(
        _write_cost_budget_config(tmp_path, provider_budget=2, global_budget=1, static=True),
        upstream_client=UpstreamClient(client=poster),
        clock=lambda: datetime(2026, 7, 14, 12, tzinfo=timezone.utc).timestamp(),
    )
    _register_budget_service(app)
    _seed_cost(app, key_id=None, cents=1.0)
    client = TestClient(app)
    payload = {"model": "test-model", "messages": [{"role": "user", "content": "hello"}]}
    denied = client.post("/v1/chat/completions", headers={"X-Api-Key": "static-key"}, json=payload)

    assert denied.status_code == 429
    assert poster.calls == 0

    unknown_app = create_app(
        _write_cost_budget_config(tmp_path / "unknown", global_budget=1, deny_unknown=True, priced=False, static=True),
        upstream_client=UpstreamClient(client=_BudgetPoster()),
        clock=lambda: datetime(2026, 7, 14, 12, tzinfo=timezone.utc).timestamp(),
    )
    _register_budget_service(unknown_app)
    unknown = TestClient(unknown_app).post(
        "/v1/chat/completions", headers={"X-Api-Key": "static-key"}, json=payload
    )

    assert unknown.status_code == 503
    assert unknown.json()["error"]["code"] == "unknown_cost"


def test_missing_cost_limits_do_not_behave_as_zero(tmp_path: Path) -> None:
    poster = _BudgetPoster()
    app = create_app(
        _write_cost_budget_config(tmp_path, static=True),
        upstream_client=UpstreamClient(client=poster),
        clock=lambda: datetime(2026, 7, 14, 12, tzinfo=timezone.utc).timestamp(),
    )
    _register_budget_service(app)
    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"X-Api-Key": "static-key"},
        json={"model": "test-model", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200
    assert poster.calls == 1
