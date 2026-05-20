from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

from .models import BenchmarkSample, HostHeartbeat, HostRegistration, RegisteredService, RoleProfile, RouteMatchRequest
from .request_policy import effective_chat_request_policy, select_target_asset


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _service_matches_guardrail_profile(service: dict | None, guardrail_profile: str | None) -> bool:
    if service is None or not guardrail_profile or guardrail_profile == "none":
        return False
    if guardrail_profile == "native_light":
        return service.get("protocol") == "openai"
    service_text = " ".join(
        str(part)
        for part in (
            service.get("service_id", ""),
            service.get("protocol", ""),
            (service.get("runtime") or {}).get("engine", ""),
            (service.get("runtime") or {}).get("launcher", ""),
            service.get("endpoint", ""),
        )
        if part
    ).lower()
    if guardrail_profile == "forge_proxy":
        return "forge" in service_text
    if guardrail_profile == "forge_middleware":
        return "forge" in service_text or "guardrail" in service_text
    return False


class Registry:
    def __init__(self, db_path: str | Path, *, routing_strategy: str = "scored") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._routing_strategy = routing_strategy
        # Per-role round-robin counters (in-memory; reset on restart is intentional).
        self._rr_counters: dict[str, int] = {}
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

                CREATE TABLE IF NOT EXISTS benchmark_samples (
                    benchmark_id TEXT PRIMARY KEY,
                    service_id TEXT NOT NULL,
                    asset_id TEXT,
                    workload TEXT NOT NULL,
                    observed_at REAL NOT NULL,
                    results_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS client_keys (
                    key_id TEXT PRIMARY KEY,
                    key_hash TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    principal_type TEXT NOT NULL,
                    principal_ref TEXT NOT NULL,
                    role TEXT,
                    allowed_models_json TEXT NOT NULL DEFAULT '[]',
                    allowed_operations_json TEXT NOT NULL DEFAULT '[]',
                    monthly_budget_cents INTEGER,
                    monthly_token_limit INTEGER,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_used_at REAL,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS request_audit_log (
                    request_id TEXT PRIMARY KEY,
                    key_id TEXT,
                    principal_type TEXT,
                    principal_ref TEXT,
                    operation TEXT NOT NULL,
                    requested_model TEXT,
                    resolved_service_id TEXT,
                    resolved_host_id TEXT,
                    upstream_model TEXT,
                    provider_kind TEXT,
                    started_at REAL NOT NULL,
                    finished_at REAL NOT NULL,
                    duration_ms REAL NOT NULL,
                    status_code INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    error_type TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    estimated_cost_cents REAL,
                    input_bytes INTEGER,
                    output_bytes INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
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

    def update_service_health(self, service_id: str, health: str) -> None:
        """Overwrite the health field in a service's state_json without touching other fields."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM services WHERE service_id = ?", (service_id,)
            ).fetchone()
            if row is None:
                return
            state = json.loads(row["state_json"])
            state["health"] = health
            conn.execute(
                "UPDATE services SET state_json = ? WHERE service_id = ?",
                (_json_dumps(state), service_id),
            )

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

    def upsert_benchmark_samples(self, samples: list[BenchmarkSample]) -> list[dict]:
        with self._connect() as conn:
            for sample in samples:
                conn.execute(
                    """
                    INSERT INTO benchmark_samples (
                        benchmark_id, service_id, asset_id, workload, observed_at, results_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(benchmark_id) DO UPDATE SET
                        service_id=excluded.service_id,
                        asset_id=excluded.asset_id,
                        workload=excluded.workload,
                        observed_at=excluded.observed_at,
                        results_json=excluded.results_json
                    """,
                    (
                        sample.benchmark_id,
                        sample.service_id,
                        sample.asset_id,
                        sample.workload,
                        sample.observed_at,
                        _json_dumps(sample.results),
                    ),
                )
        return self.list_benchmark_samples()

    def list_benchmark_samples(self, *, service_id: str | None = None, workload: str | None = None) -> list[dict]:
        query = "SELECT * FROM benchmark_samples"
        clauses = []
        params: list[object] = []
        if service_id:
            clauses.append("service_id = ?")
            params.append(service_id)
        if workload:
            clauses.append("workload = ?")
            params.append(workload)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY observed_at DESC, benchmark_id"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._benchmark_row_to_dict(row) for row in rows]

    def create_client_key(
        self,
        *,
        key_id: str,
        key_hash: str,
        display_name: str,
        principal_type: str,
        principal_ref: str,
        role: str | None = None,
        allowed_models: list[str] | None = None,
        allowed_operations: list[str] | None = None,
        monthly_budget_cents: int | None = None,
        monthly_token_limit: int | None = None,
        enabled: bool = True,
        notes: str | None = None,
    ) -> dict:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO client_keys (
                    key_id, key_hash, display_name, principal_type, principal_ref,
                    role, allowed_models_json, allowed_operations_json,
                    monthly_budget_cents, monthly_token_limit, enabled,
                    created_at, updated_at, last_used_at, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    key_id,
                    key_hash,
                    display_name,
                    principal_type,
                    principal_ref,
                    role,
                    _json_dumps(allowed_models or []),
                    _json_dumps(allowed_operations or []),
                    monthly_budget_cents,
                    monthly_token_limit,
                    1 if enabled else 0,
                    now,
                    now,
                    notes,
                ),
            )
        created = self.get_client_key(key_id)
        if created is None:
            raise RuntimeError(f"created client key {key_id!r} could not be loaded")
        return created

    def get_client_key(self, key_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM client_keys WHERE key_id = ?", (key_id,)).fetchone()
        return self._client_key_row_to_dict(row) if row is not None else None

    def get_client_key_by_hash(self, key_hash: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM client_keys WHERE key_hash = ?", (key_hash,)).fetchone()
        return self._client_key_row_to_dict(row) if row is not None else None

    def list_client_keys(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM client_keys ORDER BY created_at, key_id").fetchall()
        return [self._client_key_row_to_dict(row) for row in rows]

    def set_client_key_enabled(self, key_id: str, enabled: bool) -> dict | None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE client_keys SET enabled = ?, updated_at = ? WHERE key_id = ?",
                (1 if enabled else 0, now, key_id),
            )
        return self.get_client_key(key_id)

    def touch_client_key(self, key_id: str) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE client_keys SET last_used_at = ?, updated_at = ? WHERE key_id = ?",
                (now, now, key_id),
            )

    def record_request_audit(
        self,
        *,
        request_id: str,
        key_id: str | None,
        principal_type: str | None,
        principal_ref: str | None,
        operation: str,
        requested_model: str | None,
        resolved_service_id: str | None,
        resolved_host_id: str | None,
        upstream_model: str | None,
        provider_kind: str | None,
        started_at: float,
        finished_at: float,
        status_code: int,
        success: bool,
        error_type: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        estimated_cost_cents: float | None = None,
        input_bytes: int | None = None,
        output_bytes: int | None = None,
        metadata: dict | None = None,
    ) -> dict:
        duration_ms = max(0.0, (finished_at - started_at) * 1000.0)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO request_audit_log (
                    request_id, key_id, principal_type, principal_ref,
                    operation, requested_model, resolved_service_id,
                    resolved_host_id, upstream_model, provider_kind,
                    started_at, finished_at, duration_ms, status_code, success,
                    error_type, prompt_tokens, completion_tokens, total_tokens,
                    estimated_cost_cents, input_bytes, output_bytes,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    key_id,
                    principal_type,
                    principal_ref,
                    operation,
                    requested_model,
                    resolved_service_id,
                    resolved_host_id,
                    upstream_model,
                    provider_kind,
                    started_at,
                    finished_at,
                    duration_ms,
                    status_code,
                    1 if success else 0,
                    error_type,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    estimated_cost_cents,
                    input_bytes,
                    output_bytes,
                    _json_dumps(metadata or {}),
                ),
            )
        row = self.get_request_audit(request_id)
        if row is None:
            raise RuntimeError(f"created audit row {request_id!r} could not be loaded")
        return row

    def get_request_audit(self, request_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM request_audit_log WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return self._request_audit_row_to_dict(row) if row is not None else None

    def list_request_audit(
        self,
        *,
        key_id: str | None = None,
        principal_ref: str | None = None,
        operation: str | None = None,
        model: str | None = None,
        success: bool | None = None,
        limit: int = 100,
    ) -> list[dict]:
        query = "SELECT * FROM request_audit_log"
        clauses = []
        params: list[object] = []
        if key_id:
            clauses.append("key_id = ?")
            params.append(key_id)
        if principal_ref:
            clauses.append("principal_ref = ?")
            params.append(principal_ref)
        if operation:
            clauses.append("operation = ?")
            params.append(operation)
        if model:
            clauses.append("requested_model = ?")
            params.append(model)
        if success is not None:
            clauses.append("success = ?")
            params.append(1 if success else 0)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._request_audit_row_to_dict(row) for row in rows]

    def request_audit_summary(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    key_id,
                    principal_ref,
                    operation,
                    requested_model,
                    COUNT(*) AS request_count,
                    SUM(success) AS success_count,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failure_count,
                    SUM(COALESCE(prompt_tokens, 0)) AS prompt_tokens,
                    SUM(COALESCE(completion_tokens, 0)) AS completion_tokens,
                    SUM(COALESCE(total_tokens, 0)) AS total_tokens,
                    SUM(COALESCE(estimated_cost_cents, 0)) AS estimated_cost_cents
                FROM request_audit_log
                GROUP BY key_id, principal_ref, operation, requested_model
                ORDER BY request_count DESC, requested_model
                """
            ).fetchall()
        return [dict(row) for row in rows]

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
                        "geniehive": self._service_metadata(service, requested_model=asset_id) | {"route_type": "asset", "asset_id": asset_id},
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
                        "effective_request_policy": self._effective_request_policy(
                            requested_model=role["role_id"],
                            role=role,
                            service=self.resolve_route(role["role_id"], kind=role["operation"]).get("service") if matching_services else None,
                        ),
                    },
                }
            )

        deduped: dict[str, dict] = {}
        for item in items:
            deduped[item["id"]] = item
        return [deduped[key] for key in sorted(deduped)]

    def resolve_route(self, requested_model: str, *, kind: str | None = None, _visited: set[str] | None = None) -> dict | None:
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
            visited: set[str] = _visited if _visited is not None else {requested_model}
            for fb_role_id in role["routing_policy"].get("fallback_roles", []):
                if fb_role_id in visited:
                    continue
                visited.add(fb_role_id)
                # Let each fallback role resolve using its own operation — don't
                # inherit matched_kind, so a fallback with a different kind can
                # provide a service when the primary kind has none available.
                fb_result = self.resolve_route(fb_role_id, _visited=visited)
                if fb_result is not None and fb_result.get("service") is not None:
                    return {"match_type": "role", "role": role, "service": fb_result["service"], "fallback_via": fb_role_id}
            return {"match_type": "role", "role": role, "service": None}

        preferred_families = [family.lower() for family in role["routing_policy"].get("preferred_families", [])]

        guardrail_profile = role["routing_policy"].get("guardrail_profile", "none")

        def score(service: dict) -> tuple[int, int, int, float, str]:
            guardrail_match = 1 if _service_matches_guardrail_profile(service, guardrail_profile) else 0
            loaded = 1 if any(asset.get("loaded") for asset in service["assets"]) else 0
            family_match = 0
            if preferred_families:
                asset_names = " ".join(asset.get("asset_id", "") for asset in service["assets"]).lower()
                family_match = 1 if any(family in asset_names for family in preferred_families) else 0
            latency = service["observed"].get("p50_latency_ms")
            latency_score = float(latency) if latency is not None else float("inf")
            return (guardrail_match, family_match, loaded, -latency_score, service["service_id"])

        if role["routing_policy"].get("require_loaded"):
            loaded_candidates = [service for service in candidates if any(asset.get("loaded") for asset in service["assets"])]
            if loaded_candidates:
                candidates = loaded_candidates

        if self._routing_strategy == "round_robin":
            rr_key = requested_model
            idx = self._rr_counters.get(rr_key, 0) % len(candidates)
            self._rr_counters[rr_key] = idx + 1
            service = candidates[idx]
        elif self._routing_strategy == "least_loaded":
            def load_key(svc: dict) -> tuple:
                obs = svc.get("observed", {})
                queue = obs.get("queue_depth") or 0
                in_flight = obs.get("in_flight") or 0
                # Prefer low load; use latency as secondary signal, then id for stability.
                latency = obs.get("p50_latency_ms") or float("inf")
                return (queue + in_flight, latency, svc["service_id"])
            service = min(candidates, key=load_key)
        else:
            service = max(candidates, key=score)
        return {"match_type": "role", "role": role, "service": service}

    def match_routes(self, request: RouteMatchRequest) -> dict:
        tasks = [task.strip() for task in ([request.task] if request.task else []) + request.tasks if task and task.strip()]
        workloads = [value.strip() for value in ([request.workload] if request.workload else []) + request.workloads if value and value.strip()]
        kind = request.kind
        modality = request.modality
        services = [
            service
            for service in self.list_services()
            if (kind is None or service["kind"] == kind)
            and service["state"].get("accept_requests", True)
            and service["state"].get("health") == "healthy"
        ]
        roles = [
            role
            for role in self.list_roles()
            if (kind is None or role["operation"] == kind)
            and (modality is None or role["modality"] == modality)
        ]

        candidates: list[dict] = []
        for role in roles:
            resolved = self.resolve_route(role["role_id"], kind=role["operation"])
            service = resolved["service"] if resolved is not None else None
            candidate = self._score_role_candidate(role, service, tasks, workloads)
            candidates.append(candidate)

        if request.include_direct_services:
            for service in services:
                candidates.append(self._score_service_candidate(service, tasks, workloads))

        candidates.sort(
            key=lambda item: (
                -item["score"],
                item["candidate_type"] != "role",
                item["candidate_id"],
            )
        )
        limit = max(1, request.limit)
        return {
            "status": "ok",
            "task_count": len(tasks),
            "tasks": tasks,
            "workloads": workloads,
            "kind": kind,
            "modality": modality,
            "candidates": candidates[:limit],
        }

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

    def _score_role_candidate(self, role: dict, service: dict | None, tasks: list[str], workloads: list[str]) -> dict:
        task_tokens = _tokenize_tasks(tasks)
        text_parts = [
            role.get("role_id", ""),
            role.get("display_name", "") or "",
            role.get("description", "") or "",
            (role.get("prompt_policy") or {}).get("system_prompt", "") or "",
            " ".join((role.get("routing_policy") or {}).get("preferred_families", [])),
            " ".join((role.get("routing_policy") or {}).get("preferred_labels", [])),
            str((role.get("routing_policy") or {}).get("guardrail_profile", "")),
            str((role.get("routing_policy") or {}).get("tool_mode", "")),
            " ".join((role.get("routing_policy") or {}).get("agentic_benchmark_workloads", [])),
        ]
        text_score = _overlap_score(task_tokens, _tokenize_text(" ".join(text_parts)))
        preferred_families = [family.lower() for family in (role.get("routing_policy") or {}).get("preferred_families", [])]
        family_score = 0.0
        if service is not None and preferred_families:
            asset_names = " ".join(asset.get("asset_id", "") for asset in service["assets"]).lower()
            if any(family in asset_names for family in preferred_families):
                family_score = 1.0
        guardrail_profile = (role.get("routing_policy") or {}).get("guardrail_profile", "none")
        guardrail_score = 1.0 if _service_matches_guardrail_profile(service, guardrail_profile) else 0.0
        runtime_score, runtime_reasons, runtime_signals = self._runtime_signals(service)
        benchmark_score, benchmark_reasons, benchmark_signals = self._benchmark_signals(service, tasks, workloads)

        score = min(1.0, 0.25 * text_score + 0.12 * family_score + 0.13 * guardrail_score + 0.25 * runtime_score + 0.25 * benchmark_score)
        reasons = []
        if text_score > 0:
            reasons.append("task text overlaps role description or policy")
        if family_score > 0:
            reasons.append("resolved service matches role preferred model family")
        if guardrail_score > 0:
            reasons.append("resolved service matches role guardrail profile")
        reasons.extend(runtime_reasons)
        reasons.extend(benchmark_reasons)
        if service is None:
            reasons.append("no healthy service currently resolves for this role")
        return {
            "candidate_type": "role",
            "candidate_id": role["role_id"],
            "operation": role["operation"],
            "score": round(score, 4),
            "reasons": reasons,
            "signals": {
                "task_overlap": round(text_score, 4),
                "preferred_family_match": family_score,
                "guardrail_profile_match": guardrail_score,
                **runtime_signals,
                **benchmark_signals,
            },
            "role": role,
            "service": service,
        }

    def _score_service_candidate(self, service: dict, tasks: list[str], workloads: list[str]) -> dict:
        task_tokens = _tokenize_tasks(tasks)
        service_text = " ".join(
            [
                service.get("service_id", ""),
                service.get("host_id", ""),
                " ".join(asset.get("asset_id", "") for asset in service.get("assets", [])),
                " ".join(f"{key} {value}" for key, value in (service.get("runtime") or {}).items() if value),
            ]
        )
        text_score = _overlap_score(task_tokens, _tokenize_text(service_text))
        runtime_score, runtime_reasons, runtime_signals = self._runtime_signals(service)
        benchmark_score, benchmark_reasons, benchmark_signals = self._benchmark_signals(service, tasks, workloads)
        score = min(1.0, 0.20 * text_score + 0.45 * runtime_score + 0.35 * benchmark_score)
        reasons = []
        if text_score > 0:
            reasons.append("task text overlaps service or asset metadata")
        reasons.extend(runtime_reasons)
        reasons.extend(benchmark_reasons)
        return {
            "candidate_type": "service",
            "candidate_id": service["service_id"],
            "operation": service["kind"],
            "score": round(score, 4),
            "reasons": reasons,
            "signals": {
                "task_overlap": round(text_score, 4),
                **runtime_signals,
                **benchmark_signals,
            },
            "role": None,
            "service": service,
        }

    @staticmethod
    def _runtime_signals(service: dict | None) -> tuple[float, list[str], dict[str, object]]:
        if service is None:
            return 0.0, [], {"loaded": False, "p50_latency_ms": None, "tokens_per_sec": None}
        loaded = any(asset.get("loaded") for asset in service.get("assets", []))
        latency = service["observed"].get("p50_latency_ms")
        tokens_per_sec = service["observed"].get("tokens_per_sec")
        queue_depth = service["observed"].get("queue_depth")
        loaded_model_count = service["observed"].get("loaded_model_count")

        score = 0.0
        reasons: list[str] = []
        if loaded:
            score += 0.35
            reasons.append("service already has a loaded asset")
        if latency is not None:
            if latency <= 1500:
                score += 0.30
                reasons.append("low observed latency")
            elif latency <= 4000:
                score += 0.18
                reasons.append("moderate observed latency")
            else:
                score += 0.05
                reasons.append("high but usable latency")
        if tokens_per_sec is not None:
            if tokens_per_sec >= 20:
                score += 0.20
                reasons.append("good observed throughput")
            elif tokens_per_sec >= 8:
                score += 0.10
                reasons.append("usable observed throughput")
        if queue_depth is not None and queue_depth > 0:
            score -= min(0.15, 0.03 * queue_depth)
            reasons.append("current queue depth reduces suitability")
        return max(0.0, min(1.0, score)), reasons, {
            "loaded": loaded,
            "p50_latency_ms": latency,
            "tokens_per_sec": tokens_per_sec,
            "queue_depth": queue_depth,
            "loaded_model_count": loaded_model_count,
        }

    def _benchmark_signals(self, service: dict | None, tasks: list[str], workloads: list[str]) -> tuple[float, list[str], dict[str, object]]:
        if service is None:
            return 0.0, [], {"benchmark_match_count": 0, "best_workload_overlap": 0.0, "benchmark_quality_score": None}
        samples = self.list_benchmark_samples(service_id=service["service_id"])
        if not samples:
            return 0.0, [], {"benchmark_match_count": 0, "best_workload_overlap": 0.0, "benchmark_quality_score": None}

        query_tokens = _tokenize_tasks(tasks + workloads)
        best_overlap = 0.0
        best_quality = 0.0
        matched_count = 0
        for sample in samples:
            workload_tokens = _tokenize_text(sample["workload"])
            overlap = _overlap_score(query_tokens, workload_tokens) if query_tokens else 0.0
            if workloads and sample["workload"] in workloads:
                overlap = max(overlap, 1.0)
            quality = _benchmark_quality_score(sample["results"])
            if overlap > 0 or not query_tokens:
                matched_count += 1
                best_overlap = max(best_overlap, overlap)
                best_quality = max(best_quality, quality)

        score = 0.55 * best_overlap + 0.45 * best_quality if matched_count else 0.0
        reasons: list[str] = []
        if matched_count:
            reasons.append("recent benchmark sample matches requested workload or task shape")
        if best_quality >= 0.6:
            reasons.append("benchmark results indicate strong empirical fit")
        elif matched_count:
            reasons.append("benchmark results indicate limited but relevant empirical fit")
        return min(1.0, score), reasons, {
            "benchmark_match_count": matched_count,
            "best_workload_overlap": round(best_overlap, 4),
            "benchmark_quality_score": round(best_quality, 4) if matched_count else None,
        }

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

    def _service_metadata(self, service: dict, *, requested_model: str | None = None) -> dict:
        lat = service["observed"].get("p50_latency_ms")
        loaded_count = 1 if any(asset.get("loaded") for asset in service["assets"]) else 0
        effective_requested_model = requested_model or service["service_id"]
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
            "effective_request_policy": self._effective_request_policy(
                requested_model=effective_requested_model,
                service=service,
            ),
            "offload_hint": self._offload_hint(
                operation=service["kind"],
                loaded_count=loaded_count,
                best_latency_ms=lat,
            ),
        }

    @staticmethod
    def _effective_request_policy(
        *,
        requested_model: str,
        service: dict | None,
        role: dict | None = None,
    ) -> dict | None:
        if service is None or service.get("kind") != "chat":
            return None
        asset = select_target_asset(service, requested_model)
        return effective_chat_request_policy(
            requested_model=requested_model,
            service=service,
            role=role,
            asset=asset,
        )

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

    @staticmethod
    def _benchmark_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "benchmark_id": row["benchmark_id"],
            "service_id": row["service_id"],
            "asset_id": row["asset_id"],
            "workload": row["workload"],
            "observed_at": row["observed_at"],
            "results": json.loads(row["results_json"]),
        }

    @staticmethod
    def _client_key_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "key_id": row["key_id"],
            "key_hash": row["key_hash"],
            "display_name": row["display_name"],
            "principal_type": row["principal_type"],
            "principal_ref": row["principal_ref"],
            "role": row["role"],
            "allowed_models": json.loads(row["allowed_models_json"]),
            "allowed_operations": json.loads(row["allowed_operations_json"]),
            "monthly_budget_cents": row["monthly_budget_cents"],
            "monthly_token_limit": row["monthly_token_limit"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_used_at": row["last_used_at"],
            "notes": row["notes"],
        }

    @staticmethod
    def _request_audit_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "request_id": row["request_id"],
            "key_id": row["key_id"],
            "principal_type": row["principal_type"],
            "principal_ref": row["principal_ref"],
            "operation": row["operation"],
            "requested_model": row["requested_model"],
            "resolved_service_id": row["resolved_service_id"],
            "resolved_host_id": row["resolved_host_id"],
            "upstream_model": row["upstream_model"],
            "provider_kind": row["provider_kind"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_ms": row["duration_ms"],
            "status_code": row["status_code"],
            "success": bool(row["success"]),
            "error_type": row["error_type"],
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "total_tokens": row["total_tokens"],
            "estimated_cost_cents": row["estimated_cost_cents"],
            "input_bytes": row["input_bytes"],
            "output_bytes": row["output_bytes"],
            "metadata": json.loads(row["metadata_json"]),
        }


def _tokenize_text(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def _tokenize_tasks(tasks: list[str]) -> set[str]:
    return _tokenize_text(" ".join(tasks))


def _overlap_score(task_tokens: set[str], candidate_tokens: set[str]) -> float:
    if not task_tokens or not candidate_tokens:
        return 0.0
    overlap = len(task_tokens & candidate_tokens) / max(1, len(task_tokens))
    return min(1.0, overlap)


def _benchmark_quality_score(results: dict) -> float:
    """
    Combine correctness and speed signals into a [0, 1] quality score.

    Correctness (weight 0.65): pass_rate, quality_score, or Forge-style
    agentic workflow metrics from the workload run.
    Speed (weight 0.35): tokens_per_sec and TTFT, each contributing up to 0.5 of
    the speed component.

    When a correctness signal is absent the speed component carries the full weight
    so that services with runtime data but no workload results still rank above
    those with no data at all.
    """
    if not results:
        return 0.0

    tokens_per_sec = results.get("tokens_per_sec")
    ttft_ms = results.get("ttft_ms")
    pass_rate = results.get("pass_rate")
    quality_score = results.get("quality_score")
    terminal_accuracy = results.get("terminal_accuracy")
    completion_rate = results.get("completion_rate")
    terminal_tool_completion_rate = results.get("terminal_tool_completion_rate")
    tool_success_rate = results.get("tool_success_rate")

    # Correctness component: best available signal in [0, 1].
    correctness: float | None = None
    correctness_values = [
        value
        for value in (
            quality_score,
            pass_rate,
            terminal_accuracy,
            completion_rate,
            terminal_tool_completion_rate,
            tool_success_rate,
        )
        if isinstance(value, (int, float))
    ]
    if correctness_values:
        correctness = max(max(0.0, min(1.0, float(value))) for value in correctness_values)

    # Speed component: tokens/sec (up to 0.5) + TTFT bands (up to 0.5), in [0, 1].
    speed = 0.0
    if isinstance(tokens_per_sec, (int, float)):
        speed += min(0.5, float(tokens_per_sec) / 80.0)
    if isinstance(ttft_ms, (int, float)):
        if float(ttft_ms) <= 500:
            speed += 0.50
        elif float(ttft_ms) <= 1000:
            speed += 0.40
        elif float(ttft_ms) <= 2500:
            speed += 0.25
        else:
            speed += 0.10
    speed = min(1.0, speed)

    if correctness is None:
        # No correctness data — speed signal carries everything.
        return speed
    return 0.65 * correctness + 0.35 * speed
