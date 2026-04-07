from __future__ import annotations

from pathlib import Path
import time

from .config import NodeConfig
from .models import NodeInventory


def discover_model_files(roots: list[str]) -> list[dict[str, object]]:
    discovered: list[dict[str, object]] = []
    for root in roots:
        path = Path(root)
        if not path.exists():
            continue
        for model_path in sorted(path.rglob("*.gguf")):
            discovered.append(
                {
                    "path": str(model_path),
                    "name": model_path.name,
                    "size_bytes": model_path.stat().st_size,
                }
            )
    return discovered


def build_inventory(cfg: NodeConfig) -> NodeInventory:
    address = cfg.node.address or cfg.node.listen_host
    resources: dict[str, object] = {}
    if cfg.inventory.cpu_threads is not None:
        resources["cpu_threads"] = cfg.inventory.cpu_threads
    if cfg.inventory.ram_gb is not None:
        resources["ram_gb"] = cfg.inventory.ram_gb
    resources["discovered_models"] = discover_model_files(cfg.inventory.model_roots)

    services: list[dict] = []
    for service in cfg.services:
        endpoint = service.endpoint or f"http://{cfg.node.listen_host}:{cfg.node.listen_port}"
        services.append(
            {
                "service_id": service.service_id,
                "host_id": cfg.node.host_id,
                "kind": service.kind,
                "protocol": service.protocol,
                "endpoint": endpoint,
                "runtime": service.runtime,
                "assets": [asset.model_dump() for asset in service.assets],
                "state": service.state,
                "observed": service.observed,
            }
        )

    return NodeInventory(
        host_id=cfg.node.host_id,
        display_name=cfg.node.display_name,
        address=address,
        labels=cfg.node.labels,
        capabilities=cfg.inventory.capabilities,
        resources=resources,
        services=services,
    )


def build_registration_payload(cfg: NodeConfig) -> dict:
    inventory = build_inventory(cfg)
    return inventory.model_dump()


def build_heartbeat_payload(cfg: NodeConfig) -> dict:
    inventory = build_inventory(cfg)
    healthy_service_count = sum(
        1 for service in inventory.services if service.get("state", {}).get("health") == "healthy"
    )
    return {
        "host_id": inventory.host_id,
        "status": {
            "state": "online",
            "last_seen": time.time(),
        },
        "metrics": {
            "service_count": len(inventory.services),
            "healthy_service_count": healthy_service_count,
            "discovered_model_count": len(inventory.resources.get("discovered_models", [])),
        },
    }
