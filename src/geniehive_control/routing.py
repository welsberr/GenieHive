from __future__ import annotations

from typing import Any


def choose_upstream_model_id(requested_model: str, service: dict[str, Any]) -> str:
    assets = service.get("assets", [])
    asset_ids = [asset.get("asset_id") for asset in assets if asset.get("asset_id")]
    if requested_model in asset_ids:
        return requested_model

    loaded_assets = [asset.get("asset_id") for asset in assets if asset.get("loaded") and asset.get("asset_id")]
    if loaded_assets:
        return loaded_assets[0]
    if asset_ids:
        return asset_ids[0]
    return requested_model
