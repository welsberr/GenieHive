from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .models import HostHeartbeat, HostRegistration, RegisteredService, RoleProfile


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True)


class Registry:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS hosts (
                    host_id TEXT PRIMARY KEY,
                    display_name TEXT,
                    address TEXT NOT NULL,
                    labels_json TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    resources_json TEXT NOT NULL,
                    status_state TEXT NOT NULL DEFAULT 'online',
                    last_seen REAL NOT NULL,
                    metrics_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS services (
                    service_id TEXT PRIMARY KEY,
                    host_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    runtime_json TEXT NOT NULL,
                    assets_json TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    observed_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(host_id) REFERENCES hosts(host_id)
                );

                CREATE TABLE IF NOT EXISTS roles (
                    role_id TEXT PRIMARY KEY,
                    display_name TEXT,
                    description TEXT,
                    operation TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    prompt_policy_json TEXT NOT NULL,
                    routing_policy_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def register_host(self, reg: HostRegistration) -> dict:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO hosts (
                    host_id, display_name, address, labels_json, capabilities_json,
                    resources_json, status_state, last_seen, metrics_json
                )
                VALUES (?, ?, ?, ?, ?, ?, 'online', ?, '{}')
                ON CONFLICT(host_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    address=excluded.address,
                    labels_json=excluded.labels_json,
                    capabilities_json=excluded.capabilities_json,
                    resources_json=excluded.resources_json,
                    status_state='online',
                    last_seen=excluded.last_seen
                """,
                (
                    reg.host_id,
                    reg.display_name,
                    reg.address,
                    _json_dumps(reg.labels),
                    _json_dumps(reg.capabilities),
                    _json_dumps(reg.resources),
                    now,
                ),
            )
            self._replace_services(conn, reg.host_id, reg.services, now)
        return self.get_host(reg.host_id)

    def heartbeat_host(self, hb: HostHeartbeat) -> dict | None:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT host_id FROM hosts WHERE host_id = ?",
                (hb.host_id,),
            )
            if cur.fetchone() is None:
                return None
            conn.execute(
                """
                UPDATE hosts
                SET status_state = ?, last_seen = ?, metrics_json = ?
                WHERE host_id = ?
                """,
                (
                    hb.status.state,
                    now,
                    _json_dumps(hb.metrics),
                    hb.host_id,
                ),
            )
            if hb.services:
                self._replace_services(conn, hb.host_id, hb.services, now)
        return self.get_host(hb.host_id)

    def _replace_services(
        self,
        conn: sqlite3.Connection,
        host_id: str,
        services: list[RegisteredService],
        now: float,
    ) -> None:
        conn.execute("DELETE FROM services WHERE host_id = ?", (host_id,))
        for service in services:
            conn.execute(
                """
                INSERT INTO services (
                    service_id, host_id, kind, protocol, endpoint,
                    runtime_json, assets_json, state_json, observed_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    service.service_id,
                    host_id,
                    service.kind,
                    service.protocol,
                    service.endpoint,
                    _json_dumps(service.runtime.model_dump()),
                    _json_dumps([asset.model_dump() for asset in service.assets]),
                    _json_dumps(service.state.model_dump()),
                    _json_dumps(service.observed.model_dump()),
                    now,
                ),
            )

    def get_host(self, host_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM hosts WHERE host_id = ?", (host_id,)).fetchone()
            if row is None:
                return None
        return self._host_row_to_dict(row)

    def upsert_roles(self, roles: list[RoleProfile]) -> list[dict]:
        now = time.time()
        with self._connect() as conn:
            for role in roles:
                conn.execute(
                    """
                    INSERT INTO roles (
                        role_id, display_name, description, operation, modality,
                        prompt_policy_json, routing_policy_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(role_id) DO UPDATE SET
                        display_name=excluded.display_name,
                        description=excluded.description,
                        operation=excluded.operation,
                        modality=excluded.modality,
                        prompt_policy_json=excluded.prompt_policy_json,
                        routing_policy_json=excluded.routing_policy_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        role.role_id,
                        role.display_name,
                        role.description,
                        role.operation,
                        role.modality,
                        _json_dumps(role.prompt_policy.model_dump()),
                        _json_dumps(role.routing_policy.model_dump()),
                        now,
                    ),
                )
        return self.list_roles()

    def get_role(self, role_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM roles WHERE role_id = ?", (role_id,)).fetchone()
            if row is None:
                return None
        return self._role_row_to_dict(row)

    def list_roles(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM roles ORDER BY role_id").fetchall()
        return [self._role_row_to_dict(row) for row in rows]

    def list_hosts(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM hosts ORDER BY host_id").fetchall()
        return [self._host_row_to_dict(row) for row in rows]

    def list_services(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM services ORDER BY host_id, service_id").fetchall()
        return [self._service_row_to_dict(row) for row in rows]

    def list_client_models(self) -> list[dict]:
        services = self.list_services()
        roles = self.list_roles()
        items: list[dict] = []

        for service in services:
            if not service["state"].get("accept_requests", True):
                continue
            if service["state"].get("health") != "healthy":
                continue
            item = {
                "id": service["service_id"],
                "object": "model",
                "owned_by": service["host_id"],
                "geniehive": self._service_metadata(service),
            }
            items.append(item)
            for asset in service["assets"]:
                asset_id = asset.get("asset_id")
                if not asset_id:
                    continue
                items.append(
                    {
                        "id": asset_id,
                        "object": "model",
                        "owned_by": service["host_id"],
                        "geniehive": self._service_metadata(service) | {"route_type": "asset", "asset_id": asset_id},
                    }
                )

        for role in roles:
            matching_services = [
                service
                for service in services
                if service["kind"] == role["operation"]
                and service["state"].get("accept_requests", True)
                and service["state"].get("health") == "healthy"
            ]
            loaded_count = sum(1 for service in matching_services if any(asset.get("loaded") for asset in service["assets"]))
            latencies = [
                service["observed"].get("p50_latency_ms")
                for service in matching_services
                if service["observed"].get("p50_latency_ms") is not None
            ]
            best_latency_ms = min(latencies) if latencies else None
            items.append(
                {
                    "id": role["role_id"],
                    "object": "model",
                    "owned_by": "geniehive-role",
                    "geniehive": {
                        "route_type": "role",
                        "role_id": role["role_id"],
                        "display_name": role["display_name"],
                        "operation": role["operation"],
                        "modality": role["modality"],
                        "healthy_target_count": len(matching_services),
                        "loaded_target_count": loaded_count,
                        "best_p50_latency_ms": best_latency_ms,
                        "offload_hint": self._offload_hint(
                            operation=role["operation"],
                            loaded_count=loaded_count,
                            best_latency_ms=best_latency_ms,
                        ),
                        "routing_policy": role["routing_policy"],
                    },
                }
            )

        deduped: dict[str, dict] = {}
        for item in items:
            deduped[item["id"]] = item
        return [deduped[key] for key in sorted(deduped)]

    def resolve_route(self, requested_model: str, *, kind: str | None = None) -> dict | None:
        direct = self._resolve_direct(requested_model, kind=kind)
        if direct is not None:
            return {"match_type": "direct", **direct}

        role = self.get_role(requested_model)
        if role is None:
            return None

        matched_kind = kind or role["operation"]
        candidates = [
            service
            for service in self.list_services()
            if service["kind"] == matched_kind
            and service["state"].get("accept_requests", True)
            and service["state"].get("health") == "healthy"
        ]
        if not candidates:
            return {"match_type": "role", "role": role, "service": None}

        preferred_families = [family.lower() for family in role["routing_policy"].get("preferred_families", [])]

        def score(service: dict) -> tuple[int, int, float, str]:
            loaded = 1 if any(asset.get("loaded") for asset in service["assets"]) else 0
            family_match = 0
            if preferred_families:
                asset_names = " ".join(asset.get("asset_id", "") for asset in service["assets"]).lower()
                family_match = 1 if any(family in asset_names for family in preferred_families) else 0
            latency = service["observed"].get("p50_latency_ms")
            latency_score = float(latency) if latency is not None else float("inf")
            return (family_match, loaded, -latency_score, service["service_id"])

        if role["routing_policy"].get("require_loaded"):
            loaded_candidates = [service for service in candidates if any(asset.get("loaded") for asset in service["assets"])]
            if loaded_candidates:
                candidates = loaded_candidates

        service = max(candidates, key=score)
        return {"match_type": "role", "role": role, "service": service}

    def _resolve_direct(self, requested_model: str, *, kind: str | None = None) -> dict | None:
        candidates = []
        for service in self.list_services():
            if kind is not None and service["kind"] != kind:
                continue
            if not service["state"].get("accept_requests", True):
                continue
            if service["state"].get("health") != "healthy":
                continue
            asset_ids = {asset.get("asset_id") for asset in service["assets"]}
            if service["service_id"] == requested_model or requested_model in asset_ids:
                candidates.append(service)
        if not candidates:
            return None

        def score(service: dict) -> tuple[int, float, str]:
            loaded = 1 if any(asset.get("loaded") for asset in service["assets"]) else 0
            latency = service["observed"].get("p50_latency_ms")
            latency_score = float(latency) if latency is not None else float("inf")
            return (loaded, -latency_score, service["service_id"])

        service = max(candidates, key=score)
        return {"service": service}

    def cluster_health(self, stale_after_s: float) -> dict:
        hosts = self.list_hosts()
        services = self.list_services()
        now = time.time()
        online = 0
        stale = 0
        for host in hosts:
            is_stale = (now - host["status"]["last_seen"]) > stale_after_s
            if is_stale:
                stale += 1
            elif host["status"]["state"] == "online":
                online += 1
        healthy_services = sum(1 for service in services if service["state"].get("health") == "healthy")
        return {
            "status": "ok",
            "host_count": len(hosts),
            "online_host_count": online,
            "stale_host_count": stale,
            "service_count": len(services),
            "healthy_service_count": healthy_services,
        }

    @staticmethod
    def _offload_hint(*, operation: str, loaded_count: int, best_latency_ms: float | None) -> dict:
        if loaded_count <= 0:
            suitability = "cold_only"
        elif best_latency_ms is not None and best_latency_ms <= 1500:
            suitability = "good_for_low_complexity"
        elif best_latency_ms is not None and best_latency_ms <= 4000:
            suitability = "usable_for_background_tasks"
        else:
            suitability = "available_but_slow"
        return {
            "operation": operation,
            "suitability": suitability,
            "recommended_for": "lower-complexity offload" if operation == "chat" else f"{operation} offload",
            "inference_basis": {
                "loaded_target_count": loaded_count,
                "best_p50_latency_ms": best_latency_ms,
            },
        }

    def _service_metadata(self, service: dict) -> dict:
        lat = service["observed"].get("p50_latency_ms")
        loaded_count = 1 if any(asset.get("loaded") for asset in service["assets"]) else 0
        return {
            "route_type": "service",
            "service_id": service["service_id"],
            "host_id": service["host_id"],
            "operation": service["kind"],
            "protocol": service["protocol"],
            "endpoint": service["endpoint"],
            "health": service["state"].get("health"),
            "loaded_asset_count": loaded_count,
            "assets": service["assets"],
            "runtime": service["runtime"],
            "observed": service["observed"],
            "offload_hint": self._offload_hint(
                operation=service["kind"],
                loaded_count=loaded_count,
                best_latency_ms=lat,
            ),
        }

    @staticmethod
    def _host_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "host_id": row["host_id"],
            "display_name": row["display_name"],
            "address": row["address"],
            "labels": json.loads(row["labels_json"]),
            "capabilities": json.loads(row["capabilities_json"]),
            "resources": json.loads(row["resources_json"]),
            "status": {
                "state": row["status_state"],
                "last_seen": row["last_seen"],
            },
            "metrics": json.loads(row["metrics_json"]),
        }

    @staticmethod
    def _service_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "service_id": row["service_id"],
            "host_id": row["host_id"],
            "kind": row["kind"],
            "protocol": row["protocol"],
            "endpoint": row["endpoint"],
            "runtime": json.loads(row["runtime_json"]),
            "assets": json.loads(row["assets_json"]),
            "state": json.loads(row["state_json"]),
            "observed": json.loads(row["observed_json"]),
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _role_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "role_id": row["role_id"],
            "display_name": row["display_name"],
            "description": row["description"],
            "operation": row["operation"],
            "modality": row["modality"],
            "prompt_policy": json.loads(row["prompt_policy_json"]),
            "routing_policy": json.loads(row["routing_policy_json"]),
            "updated_at": row["updated_at"],
        }
