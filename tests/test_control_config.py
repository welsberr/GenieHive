from pathlib import Path

from geniehive_control.config import ControlConfig, load_config


def test_default_control_config_is_casual_and_non_governed() -> None:
    cfg = ControlConfig()

    assert cfg.deployment_profile == "casual"
    assert cfg.auth.client_api_keys == []
    assert cfg.auth.node_api_keys == []
    assert cfg.auth.enable_named_client_keys is False
    assert cfg.audit.enabled is False
    assert cfg.admin_api.enabled is False
    assert cfg.authorization.enforce_model_allowlists is False
    assert cfg.authorization.enforce_operation_allowlists is False
    assert cfg.providers == []
    assert cfg.budgeting.enabled is False


def test_legacy_control_example_loads_without_foundation_sections() -> None:
    cfg = load_config(Path("configs/control.example.yaml"))

    assert cfg.deployment_profile == "casual"
    assert cfg.auth.client_api_keys == ["change-me-client-key"]
    assert cfg.auth.node_api_keys == ["change-me-node-key"]
    assert cfg.auth.enable_named_client_keys is False
    assert cfg.audit.enabled is False
    assert cfg.admin_api.enabled is False
    assert cfg.providers == []


def test_foundation_control_example_loads_as_opt_in_profile() -> None:
    cfg = load_config(Path("configs/control.foundation.example.yaml"))

    assert cfg.deployment_profile == "foundation_gateway"
    assert cfg.auth.enable_named_client_keys is True
    assert cfg.audit.enabled is True
    assert cfg.admin_api.enabled is True
    assert cfg.authorization.enforce_model_allowlists is True
    assert cfg.authorization.enforce_operation_allowlists is True
    assert cfg.providers[0].provider_id == "openai-foundation"
    assert cfg.providers[0].api_key_env == "OPENAI_API_KEY"
    assert cfg.providers[0].models == ["gpt-4o-mini"]
    assert cfg.providers[1].provider_kind == "anthropic_messages"
    assert cfg.budgeting.global_monthly_budget_cents == 5000
