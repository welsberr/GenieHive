# GenieHive Roadmap

Last updated: 2026-07-14

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

**Client-facing proxy:**
- `POST /v1/audio/transcriptions` — proxies multipart audio to upstream; uses a
  real httpx client for multipart form-data (not the injectable `AsyncPoster` Protocol)

**Route matching and scoring:**
- `POST /v1/cluster/routes/match` — scored candidate list for role and service targets
- Signals: text overlap, preferred family, runtime (loaded state, latency, throughput,
  queue depth), benchmark (workload overlap, quality score)
- `GET /v1/cluster/routes/resolve` — quick single-model resolution
- `fallback_roles` chain in `resolve_route()` — walks role fallbacks with cycle
  protection; each fallback resolves using its own operation (not the primary's kind)

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

**Active health probing (control plane):**
- `ServiceProber` in `probe.py` probes each service's `GET /health` endpoint
- Health divergences update the registry's `state_json` without touching other fields
- Background `probe_loop` task launched at app startup when
  `routing.probe_interval_s > 0` (default 0 = disabled, relies on node heartbeats)
- Configurable via `routing.probe_interval_s` and `routing.probe_timeout_s`

**Routing strategies — all three implemented:**
- `routing.default_strategy` in config; `Registry(routing_strategy=...)` dispatches
- `scored` (default): picks best-scoring service per role
- `round_robin`: cycles through healthy candidates; in-memory counter, resets on restart
- `least_loaded`: picks service with lowest `queue_depth + in_flight` from observed
  metrics; falls back to latency as a secondary signal when load metrics are equal

**Streaming chat completions:**
- `UpstreamClient.chat_completions_stream()` — async generator, yields raw SSE bytes
  using `httpx.AsyncClient.stream()`; raises `UpstreamError` before first yield on
  non-2xx status
- `_prepare_chat_upstream()` extracted from `proxy_chat_completion` — synchronous
  routing/policy step so `ProxyError` can be caught before `StreamingResponse` is created
- `stream_chat_completion()` — async generator wrapping `chat_completions_stream`,
  applies `_strip_reasoning_from_sse_chunk()` to each SSE data line
- Route handler detects `body.get("stream")`, resolves route eagerly, returns
  `StreamingResponse` with `Cache-Control: no-cache, X-Accel-Buffering: no`

**Upstream model discovery (node agent):**
- `discover_ollama_assets()` — queries `/api/tags`; marks all as `loaded: False`
  (available, not necessarily in VRAM)
- `_get_ollama_ps_models()` — internal helper; queries `/api/ps`; returns raw model
  list (with `size_in_vram` etc.) for reuse without extra HTTP requests
- `query_ollama_ps()` — public wrapper; returns frozenset of VRAM-loaded model names
- `discover_openai_models()` — queries `/v1/models`; marks all as `loaded: True`
- `enrich_service_assets(service, *, protocol)` — for `"ollama"`: two-phase query
  (tags + ps); updates `loaded` state of existing static assets as well as adding
  new ones; stale `loaded: True` in config gets corrected to `False` if the model
  isn't in `/api/ps`; populates `observed.loaded_model_count` and
  `observed.vram_used_bytes` from `/api/ps` response
- Per-service `discover_protocol: "ollama" | "openai" | null` config field
- Heartbeat zips service dicts with config objects to pass protocol correctly
- Separate httpx discovery client allocated only when any service opts in

**`ServiceObserved` extended:**
- `loaded_model_count: int | None` — number of models currently in VRAM (from Ollama `/api/ps`)
- `vram_used_bytes: int | None` — total VRAM used across loaded models
- Both exposed in `_runtime_signals` signals dict for route scoring visibility

**Tests:**
- Registry, chat proxy, node inventory, benchmark runner, full demo flow
- ServiceProber probe_once, update_service_health, discover_ollama_assets,
  enrich_service_assets, observed metrics population, configured external
  providers, credential failures, and provider lifecycle cleanup
- Current full-suite baseline: 89 passing tests

---

## Known Gaps And Issues

The v1 local control plane is operational. The following confirmed gaps remain:

### 1. Discovery covers Ollama and OpenAI-compatible; faster-whisper not covered

Transcription services (faster-whisper, WhisperX) don't expose `/api/tags` or
`/v1/models`.  A `discover_protocol: "whisper"` variant could query
`GET /inference/v1/models` or read a static manifest.

### 2. Foundation profile is incomplete

The archive role catalog and smoke client are now implemented. Cost calculation
is implemented behind the disabled-by-default budgeting profile; budget
enforcement, the admin CLI, and the production security checklist remain
unimplemented. Use the atomic work packets in
`docs/foundation_gateway_roadmap.md`; do not implement these from this summary.

### 3. Non-OpenAI provider strategy is not selected

Configured OpenAI-compatible providers are implemented. Anthropic and other
native protocols are blocked on the adapter decision in Foundation packet M7-0.
Do not add a mandatory Node or `pi-ai` dependency without that decision record.

### 4. `architecture.md` could be tightened further

Minor: some sections inherited from earlier drafts could be simplified now that
the implementation is stable.

---

## Next Work

For changes suitable for lower-cost implementation models, assign exactly one
ready packet from `docs/foundation_gateway_roadmap.md`. That document defines
allowed files, acceptance checks, dependencies, and stop conditions.

1. **Live end-to-end demo** — run control + node against a real upstream (Ollama
   or llama.cpp) and validate: chat via role, direct asset addressing, Ollama
   dynamic discovery with correct load state, `least_loaded` routing with real
   VRAM metrics, and streaming.

2. **Validate Codex-friendly `/v1/models` offload** — test `GET /v1/models` as
   a programmatic service catalog for a Claude Code or Codex client selecting
   a GenieHive-hosted model for lower-complexity subtasks.

3. **`queue_depth` / `in_flight` from Ollama** — populate from `/api/ps` model
   count or from a sidecar queue tracker; currently only set from static config.

---

## V1.5 Scope

- mTLS between control plane and node agents
- Scoped client tokens (read-only vs. operator vs. admin)
- Active load-aware model swapping (trigger unload/load on a node based on demand)
- Image and TTS generation adapter stubs
- Provider-neutral streaming audit completion and final usage capture

---

## Non-Goals (Unchanged from Original Spec)

- Peer-to-peer consensus
- Autonomous global model swapping across many nodes
- Full WAN zero-trust platform
- Distributed vector database management
- Customer billing, metered invoicing, or a general-purpose multi-tenant billing
  platform. Foundation spend guardrails remain in scope.
