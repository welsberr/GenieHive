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
  routing_policy:
    preferred_families: ["Qwen3", "Mistral"]
    preferred_labels: ["instruction", "stable"]
    min_context: 8192
    require_loaded: false
    fallback_roles: ["general_assistant"]
```

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
