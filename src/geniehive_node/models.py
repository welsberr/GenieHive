from __future__ import annotations

from pydantic import BaseModel, Field


class NodeInventory(BaseModel):
    host_id: str
    display_name: str | None = None
    address: str
    labels: dict[str, str] = Field(default_factory=dict)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    resources: dict[str, object] = Field(default_factory=dict)
    services: list[dict] = Field(default_factory=list)

