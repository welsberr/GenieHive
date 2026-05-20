# GenieHive Schemas

These are canonical logical schemas for v1. They are documentation first, not final implementation code.

## Host

```yaml
host:
  host_id: "atlas-01"
  display_name: "Atlas GPU Box"
  address: "192.168.1.101"
  labels:
    site: "home-lab"
    class: "gpu"
  capabilities:
    cuda: true
    rocm: false
    metal: false
  resources:
    cpu_threads: 24
    ram_gb: 128
    gpus:
      - gpu_id: "cuda:0"
        name: "RTX 4090"
        vram_gb: 24
  auth:
    node_key_id: "nk_atlas_01"
  status:
    state: "online"
    last_seen: "2026-04-05T15:30:00Z"
```

## Service

```yaml
service:
  service_id: "atlas-01/chat/qwen3-8b"
  host_id: "atlas-01"
  kind: "chat"
  protocol: "openai"
  endpoint: "http://192.168.1.101:18091"
  runtime:
    engine: "llama.cpp"
    launcher: "managed"
  assets:
    - asset_id: "qwen3-8b-q4km"
      loaded: true
      request_policy:
        body_defaults:
          chat_template_kwargs:
            enable_thinking: false
  state:
    health: "healthy"
    load_state: "loaded"
    accept_requests: true
  observed:
    p50_latency_ms: 920
    p95_latency_ms: 1900
    tokens_per_sec: 42
```

## Asset

```yaml
asset:
  asset_id: "qwen3-8b-q4km"
  family: "Qwen3-8B"
  modality: "text"
  operation: "chat"
  format: "gguf"
  locator:
    kind: "path"
    value: "/models/qwen3-8b/qwen3-8b-q4_k_m.gguf"
  metadata:
    quant: "Q4_K_M"
    ctx_train: 32768
```

## Role Profile

```yaml
role:
  role_id: "mentor"
  display_name: "Mentor"
  description: "Guidance-oriented instructional reasoning"
  modality: "text"
  operation: "chat"
  prompt_policy:
    system_prompt: "You guide without doing the user's work for them."
    user_template: "{{ user_input }}"
    request_policy:
      body_defaults:
        temperature: 0.2
  routing_policy:
    preferred_families: ["Qwen3", "Mistral"]
    preferred_labels: ["instruction", "stable"]
    min_context: 8192
    require_loaded: false
    fallback_roles: ["general_assistant"]
    guardrail_profile: "none"         # none | forge_proxy | forge_middleware | native_light
    tool_mode: "auto"                 # auto | native | prompt | none
    force_respond_tool: false
    context_budget_mode: "auto"       # auto | upstream | conservative
    agentic_benchmark_workloads: []
```

Forge-backed agentic roles can set `guardrail_profile: "forge_proxy"` to prefer
services whose runtime metadata identifies a Forge proxy. See
`docs/forge_integration.md`.

## Request Shape Policy

This is a general representation for model- or route-specific request shaping.

```yaml
request_shape_policy:
  body_defaults:
    chat_template_kwargs:
      enable_thinking: false
    temperature: 0.2
  system_prompt: "Return only visible final answer text."
  system_prompt_position: "prepend"
```

Use it for:

- model-specific request flags such as `chat_template_kwargs.enable_thinking`
- default OpenAI-compatible body fields that should be applied unless the caller already set them
- model-specific prompt instructions that should be prepended, appended, or replace an existing system message

GenieHive currently supports this policy on:

- `service.assets[].request_policy`
- `role.prompt_policy.request_policy`

The control plane may also infer built-in request policies from model family metadata. For example, Qwen3/Qwen3.5 chat routes default to `chat_template_kwargs.enable_thinking: false` unless the caller explicitly sets a different value.

`GET /v1/models` exposes the merged result as `geniehive.effective_request_policy` on service, asset, and role-backed model entries so clients can discover what GenieHive will apply by default.

## Health Sample

```yaml
health_sample:
  sample_id: "hs_01"
  target_type: "service"
  target_id: "atlas-01/chat/qwen3-8b"
  observed_at: "2026-04-05T15:30:00Z"
  status: "healthy"
  checks:
    http_ok: true
    models_ok: true
    auth_ok: true
  metrics:
    queue_depth: 1
    in_flight: 1
    mem_used_gb: 18.4
```

## Benchmark Sample

```yaml
benchmark_sample:
  benchmark_id: "bench_01"
  service_id: "atlas-01/chat/qwen3-8b"
  asset_id: "qwen3-8b-q4km"
  observed_at: "2026-04-05T15:25:00Z"
  workload: "chat.short_reasoning"
  results:
    prompt_tokens: 512
    completion_tokens: 256
    ttft_ms: 780
    tokens_per_sec: 44
```

## Route Match Request

```yaml
route_match_request:
  task: "fast technical reasoning for an interactive assistant"
  tasks:
    - "interactive debugging help"
    - "concise technical explanations"
  workload: "chat.short_reasoning"
  workloads:
    - "chat.short_reasoning"
    - "chat.concise_support"
  kind: "chat"
  modality: "text"
  include_direct_services: true
  limit: 5
```

This request is meant to answer:

- which role-backed route is the best current fit for this task or task suite
- which direct services also look suitable right now

V1 matching is metadata- and runtime-driven. It uses:

- role text and routing policy overlap
- service asset and runtime metadata overlap
- loaded state
- observed latency
- observed throughput
- current queue depth when available
- recent benchmark sample workload overlap and empirical quality/performance hints

If benchmark samples exist for a candidate service, workload hints such as `chat.short_reasoning` can boost routes with recent empirical fit.

## Route Match Candidate

```yaml
route_match_candidate:
  candidate_type: "role"
  candidate_id: "general_assistant"
  operation: "chat"
  score: 0.86
  reasons:
    - "task text overlaps role description or policy"
    - "resolved service matches role preferred model family"
    - "service already has a loaded asset"
    - "low observed latency"
    - "good observed throughput"
  signals:
    task_overlap: 0.33
    preferred_family_match: 1.0
    loaded: true
    p50_latency_ms: 1100
    tokens_per_sec: 28
    queue_depth: 0
    benchmark_match_count: 2
    best_workload_overlap: 1.0
    benchmark_quality_score: 0.9
  role:
    role_id: "general_assistant"
  service:
    service_id: "p40-box/chat/gpu1-secondary"
```

## Benchmark Ingest Request

```yaml
benchmark_ingest_request:
  samples:
    - benchmark_id: "bench-qwen-1"
      service_id: "p40-box/chat/gpu1-secondary"
      asset_id: "Qwen3.5-9B-Q5_K_M"
      workload: "chat.short_reasoning"
      observed_at: 1775582000.0
      results:
        ttft_ms: 900
        tokens_per_sec: 30
        quality_score: 0.9
```

## Benchmark Report File

This is a file-oriented format meant for repeatable benchmark runs before ingestion into GenieHive.

```yaml
benchmark_report:
  report_id: "p40-short-reasoning"
  observed_at: 1775583000.0
  source: "local-smoke"
  samples:
    - service_id: "p40-box/chat/gpu1-secondary"
      asset_id: "Qwen3.5-9B-Q5_K_M"
      workload: "chat.short_reasoning"
      results:
        ttft_ms: 900
        tokens_per_sec: 30
        quality_score: 0.9
```

Notes:

- `observed_at` may be set once at the report level or per sample
- `benchmark_id` is optional in the file format; GenieHive tooling can generate a stable ID during conversion
- the helper script `scripts/ingest_benchmark_report.py` loads this format and posts the expanded samples to `POST /v1/cluster/benchmarks`
