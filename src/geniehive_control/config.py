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


class StorageConfig(BaseModel):
    sqlite_path: str = "state/geniehive.sqlite3"


class RoutingConfig(BaseModel):
    health_stale_after_s: float = 30.0


class ControlConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    roles_path: str | None = None


def load_config(path: str | Path) -> ControlConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("Control config must be a YAML mapping.")
    return ControlConfig.model_validate(raw)
