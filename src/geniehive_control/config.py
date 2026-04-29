from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8800


class AuthConfig(BaseModel):
    client_api_keys: list[str] = Field(default_factory=list)
    node_api_keys: list[str] = Field(default_factory=list)
    enable_named_client_keys: bool = False
    key_hash_secret_env: str = "GENIEHIVE_KEY_HASH_SECRET"


class AuditConfig(BaseModel):
    enabled: bool = False


class AdminApiConfig(BaseModel):
    enabled: bool = False


class AuthorizationConfig(BaseModel):
    enforce_model_allowlists: bool = False
    enforce_operation_allowlists: bool = False
    empty_allowlist_means_no_access: bool = True


class ProviderConfig(BaseModel):
    provider_id: str
    provider_kind: str
    base_url: str
    api_key_env: str | None = None
    default_headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class BudgetingConfig(BaseModel):
    enabled: bool = False
    reset_day_of_month: int = 1
    global_monthly_budget_cents: int | None = None
    provider_monthly_budget_cents: dict[str, int] = Field(default_factory=dict)
    deny_on_unknown_cost: bool = False


class StorageConfig(BaseModel):
    sqlite_path: str = "state/geniehive.sqlite3"


class RoutingConfig(BaseModel):
    health_stale_after_s: float = 30.0
    # "scored"      — pick best-scoring service per role (default)
    # "round_robin" — cycle through healthy services in order
    # "least_loaded" — prefer services with lowest queue_depth + in_flight
    default_strategy: str = "scored"
    # Set to a positive value (seconds) to enable active service health probing.
    # 0.0 (default) disables probing; the control plane relies solely on node heartbeats.
    probe_interval_s: float = 0.0
    probe_timeout_s: float = 5.0


class ControlConfig(BaseModel):
    deployment_profile: str = "casual"
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    admin_api: AdminApiConfig = Field(default_factory=AdminApiConfig)
    authorization: AuthorizationConfig = Field(default_factory=AuthorizationConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
    budgeting: BudgetingConfig = Field(default_factory=BudgetingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    roles_path: str | None = None


def load_config(path: str | Path) -> ControlConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("Control config must be a YAML mapping.")
    return ControlConfig.model_validate(raw)
