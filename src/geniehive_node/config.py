from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


ServiceKind = Literal["chat", "embeddings", "transcription"]


class NodeConfigBlock(BaseModel):
    host_id: str = "node-1"
    display_name: str | None = None
    listen_host: str = "127.0.0.1"
    listen_port: int = 8891
    address: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class ControlPlaneConfig(BaseModel):
    base_url: str | None = None
    node_api_key: str | None = None
    heartbeat_interval_s: float = 5.0


class InventoryConfig(BaseModel):
    model_roots: list[str] = Field(default_factory=list)
    cpu_threads: int | None = None
    ram_gb: float | None = None
    capabilities: dict[str, bool] = Field(default_factory=dict)


class ManagedRuntimesConfig(BaseModel):
    enabled: bool = False
    llama_server_bin: str | None = None


class NodeServiceAssetConfig(BaseModel):
    asset_id: str
    loaded: bool = False


class NodeServiceConfig(BaseModel):
    service_id: str
    kind: ServiceKind
    protocol: str = "openai"
    endpoint: str | None = None
    runtime: dict[str, str] = Field(default_factory=dict)
    assets: list[NodeServiceAssetConfig] = Field(default_factory=list)
    state: dict[str, object] = Field(default_factory=dict)
    observed: dict[str, object] = Field(default_factory=dict)


class NodeConfig(BaseModel):
    node: NodeConfigBlock = Field(default_factory=NodeConfigBlock)
    control_plane: ControlPlaneConfig = Field(default_factory=ControlPlaneConfig)
    inventory: InventoryConfig = Field(default_factory=InventoryConfig)
    managed_runtimes: ManagedRuntimesConfig = Field(default_factory=ManagedRuntimesConfig)
    services: list[NodeServiceConfig] = Field(default_factory=list)


def load_config(path: str | Path) -> NodeConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("Node config must be a YAML mapping.")
    return NodeConfig.model_validate(raw)
