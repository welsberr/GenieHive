# GenieHive Roadmap

Last updated: 2026-04-27

## What Is Complete

The v1 core is implemented and tested.

**Registry and cluster control:**
- SQLite-backed registry with hosts, services, roles, and benchmark samples
- Node registration and heartbeat protocol with auto-re-registration on 404
- Role catalog loading from YAML
- Route resolution: direct asset/service match → role resolution → clear failure

**Client-facing API:**
- `GET /v1/models` — OpenAI-compatible model list with rich metadata (loaded state,
  latency hints, offload classification, role aliases)
- `POST /v1/chat/completions` — proxies to upstream with request policy application
- `POST /v1/embeddings` — proxies to upstream

**Request policy system:**
- Body defaults and overrides via deep merge
- System prompt injection (prepend / append / replace)
- Per-asset and per-role policies, merged with role winning on prompts
- Qwen3 / Qwen3.5 auto-detection with `enable_thinking: false` applied automatically

**Route matching and scoring:**
- `POST /v1/cluster/routes/match` — scored candidate list for role and service targets
- Signals: text overlap, preferred family, runtime (loaded state, latency, throughput,
  queue depth), benchmark (workload overlap, quality score)
- `GET /v1/cluster/routes/resolve` — quick single-model resolution

**Benchmark infrastructure:**
- Built-in workloads: `chat.short_reasoning`, `chat.concise_support`
- `run_benchmark_workload.py` executes workloads and emits a JSON report
- `ingest_benchmark_report.py` posts results to the control plane
- Benchmark samples feed the route scoring pipeline

**Operator inspection:**
- `GET /v1/cluster/hosts`, `/services`, `/roles`, `/benchmarks`, `/health`

**Auth:**
- Client API key (`X-Api-Key`) and node registration key (`X-GenieHive-Node-Key`)
- Empty key lists disable auth for development

**Tests:**
- Registry, chat proxy, node inventory, benchmark runner, full demo flow
- All passing

---

## Known Gaps and Issues

These are confirmed gaps in the current implementation, not aspirational items.

### 1. Transcription endpoint not implemented

`POST /v1/audio/transcriptions` is listed in the architecture and wired into
`main.py`, but there is no upstream proxy handler for it. `upstream.py` has no
`transcriptions()` method. The endpoint currently returns nothing useful.

### 2. Routing strategy field is ignored

`RoutingConfig.default_strategy` exists in `config.py` (default: `"loaded_first"`),
but `resolve_route()` in `registry.py` does not read it. There is effectively only
one strategy. The field is misleading.

### 3. Role fallback chain is not implemented

`RoutingPolicy.fallback_roles` is defined in `models.py` and appears in the schema
docs, but `resolve_route()` never consults it. A role that fails to match any service
fails outright rather than trying its fallbacks.

### 4. `_benchmark_quality_score` can exceed 1.0 before clamping

`pass_rate` and `quality_score` are taken as `max()`, then `tokens_per_sec` and
`ttft_ms` are *added* on top. A service with `pass_rate=1.0`, fast tokens, and low
TTFT accumulates a score of up to 1.6 before the final `min(1.0, quality)` clamp.
This means the additive bonuses have no effect once pass_rate or quality_score is
already high, which is probably not the intended behavior.

### 5. Health is self-reported only

Service health (`healthy` / `unhealthy`) comes entirely from node-reported state.
The control plane does not probe upstream endpoints. A service can appear healthy
while its endpoint is unreachable.

### 6. No active model discovery from upstream services

The node agent scans for `.gguf` files on disk and reads static service config.
It does not query running Ollama or vLLM instances for their loaded model list.
A freshly-pulled Ollama model will not appear until the node config is updated
and the agent restarted.

### 7. `docs/architecture.md` duplicates `GENIEWARREN_SPEC.md`

`architecture.md` contains the repo-naming rationale, name alternatives, and
implementation sequence list that are only meaningful in a design/proposal context.
These are noise in a reference architecture document.

---

## Immediate Next Work (Priority Order)

### P0 — Fix confirmed bugs

1. **Remove the misleading `default_strategy` field** or implement a dispatch table
   so the config field actually selects behavior. Simplest fix: delete the field and
   the dead config surface until a second strategy is implemented.

2. **Fix `_benchmark_quality_score`** so additive bonuses apply only when no
   `pass_rate` / `quality_score` is available, or restructure as a weighted average
   so the components don't stack additively.

### P1 — Complete stated v1 scope

3. **Implement transcription proxy** — add `upstream.transcriptions()` and wire
   the handler in `chat.py` and `main.py`.

4. **Implement role fallback chain** — when `resolve_route()` finds no matching
   service for a role, walk `fallback_roles` in order before failing.

### P2 — Close the most important self-reported-only gaps

5. **Add active health probing** — the control plane should periodically probe
   registered service endpoints (a lightweight `GET /health` or `GET /v1/models`
   is sufficient) and update health state independently of node heartbeats.

6. **Add upstream model discovery for Ollama** — query `GET /api/tags` (Ollama)
   or `GET /v1/models` (OpenAI-compatible) from the node agent and merge loaded
   model names into the service's asset list. This enables dynamic model tracking
   without config restarts.

### P3 — Documentation cleanup

7. **Revise `architecture.md`** — remove the design-phase repo-naming rationale
   and first-implementation-sequence list; replace with a description of the actual
   running system (the four layers as implemented, data flow diagram if possible).

8. **Update `roadmap.md`** — this file (done).

---

## Near-Term Milestones (After P0–P3)

- **Live LLM demo** — run control + node against a real upstream (Ollama or
  llama.cpp) and document the end-to-end flow, including chat via role and
  direct asset addressing
- **Validate Codex-friendly `/v1/models` offload** — test `GET /v1/models` as
  a programmatic service catalog for a Claude Code or Codex client selecting
  a GenieHive-hosted model for lower-complexity subtasks
- **Richer node metrics** — queue depth, in-flight count, and rolling performance
  averages reported from node to control on every heartbeat
- **Second routing strategy** — implement `round_robin` or `least_loaded` as a
  second selectable strategy, then make `default_strategy` actually dispatch

---

## V1.5 Scope (Not Yet Started)

- mTLS between control plane and node agents
- Scoped client tokens (read-only vs. operator vs. admin)
- Active load-aware model swapping (trigger unload/load on a node based on demand)
- Image and TTS generation adapter stubs
- Streaming response passthrough for chat completions

---

## Non-Goals (Unchanged from Original Spec)

- Peer-to-peer consensus
- Autonomous global model swapping across many nodes
- Full WAN zero-trust platform
- Distributed vector database management
- Billing or multi-tenant quota accounting
