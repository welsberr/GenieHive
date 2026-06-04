# GenieHive Architecture

Last updated: 2026-06-04

## Mission

GenieHive is a local-first control plane for heterogeneous generative AI services
running across one or more hosts. It provides:

- Registration and health tracking for distributed AI services
- A stable, OpenAI-compatible client-facing API
- Role-based routing and scheduling over multiple services
- Integrated benchmarking and performance-informed route scoring

It is not a plain OpenAI-compatible gateway. The control plane layer adds topology
awareness, role abstraction, and signal-driven routing that a dumb proxy does not
provide.

---

## Four Layers

```
┌─────────────────────────────────────────────┐
│  Client Facades                              │
│  OpenAI-compatible completions + embeddings  │
│  Operator inspection API                     │
├─────────────────────────────────────────────┤
│  Control API                                 │
│  Registry · Role catalog · Route resolution  │
│  Scheduling · Benchmark store                │
├─────────────────────────────────────────────┤
│  Node Agent(s)                               │
│  Host discovery · Service enumeration        │
│  Telemetry reporting · Heartbeat             │
├─────────────────────────────────────────────┤
│  Provider Adapters                           │
│  OpenAI-compatible chat / embeddings         │
│  Transcription (partial)                     │
└─────────────────────────────────────────────┘
```

---

## Core Concepts

### Host

A physical or virtual machine participating in the cluster.

### Service

A concrete callable capability on a host: a chat endpoint, an embeddings endpoint,
or a transcription endpoint. A host typically exposes multiple services.

### Asset

A model weight, model name, or runtime target that a service can serve. Assets carry
optional `request_policy` fields that adjust how requests are shaped before forwarding.

### Role

A reusable task profile that describes *how* requests should be fulfilled, not *which*
model fills them. A role has a prompt policy (system prompt injection, body defaults)
and a routing policy (preferred model families, minimum context size, loaded-first
preference). The same role can route to different services as cluster state changes.

### Route Resolution

1. If `model` matches a loaded, healthy asset or service alias → route directly.
2. If `model` matches a known role → filter by role policy and route by strategy.
3. Otherwise → fail with a clear 404.

Role routing applies these gates before a scheduling strategy is used:

- operation/kind match
- healthy service state and `accept_requests`
- `require_loaded`, if set
- `min_context`, if set
- ordered `preferred_families`, if set

`preferred_families` is ordered by priority. When at least one healthy eligible
service matches a preferred family, GenieHive restricts the candidate set to the
highest-priority matching family before applying `scored`, `round_robin`, or
`least_loaded`. Lower-priority families remain fallbacks, not co-equal members
of the active pool.

---

## Data Flow: Chat Completion

```
Client POST /v1/chat/completions
  │
  ▼
resolve_route(model, kind="chat")
  ├─ direct: asset_id or service alias match
  └─ role: filter by kind/health/policy → schedule among eligible services
  │
  ▼
apply_request_policy(request, asset, role)
  ├─ deep-merge body_defaults
  ├─ apply system prompt (prepend / append / replace)
  └─ auto-infer Qwen3 template kwargs if needed
  │
  ▼
UpstreamClient.chat_completions(endpoint, modified_request)
  │
  ▼
_strip_reasoning_fields(response)  ← removes reasoning_content / reasoning
  │
  ▼
Response to client
```

---

## Scoring

Route scoring combines three signal families:

| Signal family  | Weight (role) | Weight (service) |
|----------------|---------------|-----------------|
| Text overlap   | 30%           | 20%             |
| Runtime        | 30%           | 45%             |
| Benchmark      | 25%           | 35%             |
| Family pref.   | 15%           | —               |

**Runtime signals** (from last heartbeat):
- Loaded state: +0.35
- Latency bands: p50 <500 ms +0.30, <1500 ms +0.20, <3000 ms +0.10, else +0.05
- Throughput: ≥40 tok/s +0.20, ≥20 +0.10
- Queue depth: penalty −0.20 if ≥5, −0.10 if ≥2

**Benchmark signals** (from ingested workload runs):
- Workload overlap score (Jaccard-style token overlap)
- Quality score from results: `0.45 * overlap + 0.55 * quality`

## Scheduling Strategies

`routing.default_strategy` controls selection after eligibility filtering:

- `scored`: pick the highest scoring service using runtime, benchmark, text, and
  role-family signals.
- `round_robin`: cycle across the filtered candidate set. This is appropriate
  for homogeneous worker pools such as multiple instances of the same model
  family serving one batch role.
- `least_loaded`: pick the service with the lowest `queue_depth + in_flight`.

In June 2026, the `scientific_translator` role was used by the TalkOrigins
Archive translation queue as a live four-worker capability test. The role
advertised Qwen3.5 as its first preferred family and lower-priority model
families as fallbacks. With `round_robin`, GenieHive cycled across four healthy
Qwen3.5 9B services on `gorlim` and `p40-box`, while excluding healthy Qwen3
fallback services from the active schedule until they were actually needed.

---

## Topology

**Minimum viable (single machine):**
```
control plane + node agent + model server
all on 127.0.0.1, different ports
```

**Recommended (small cluster):**
```
1 control plane host
2+ node-agent hosts, each with 1+ model servers
1+ clients on LAN
```

**Auth:**
- Client requests: `X-Api-Key` header
- Node registration/heartbeat: `X-GenieHive-Node-Key` header
- Empty key lists disable auth (development only)
- mTLS between control and nodes planned for v1.5

---

## State Store

SQLite. Schema:

| Table               | Content                                   |
|---------------------|-------------------------------------------|
| `hosts`             | Host registration, resources, labels      |
| `services`          | Service config, runtime, assets, observed |
| `roles`             | Role catalog                              |
| `benchmark_samples` | Workload results per service              |

Default path: `state/geniehive.sqlite3`

---

## API Reference Summary

### Client API
| Endpoint                        | Status        |
|---------------------------------|---------------|
| `GET /v1/models`                | Implemented   |
| `POST /v1/chat/completions`     | Implemented   |
| `POST /v1/embeddings`           | Implemented   |
| `POST /v1/audio/transcriptions` | Stub only     |

### Operator API
| Endpoint                           | Status      |
|------------------------------------|-------------|
| `GET /v1/cluster/hosts`            | Implemented |
| `GET /v1/cluster/services`         | Implemented |
| `GET /v1/cluster/roles`            | Implemented |
| `GET /v1/cluster/benchmarks`       | Implemented |
| `GET /v1/cluster/health`           | Implemented |
| `GET /v1/cluster/routes/resolve`   | Implemented |
| `POST /v1/cluster/routes/match`    | Implemented |

### Node API
| Endpoint                     | Status      |
|------------------------------|-------------|
| `POST /v1/nodes/register`    | Implemented |
| `POST /v1/nodes/heartbeat`   | Implemented |
| `GET /v1/node/inventory`     | Implemented |
| `GET /v1/node/registration`  | Implemented |

---

## Supported Upstream Backends

Any OpenAI-compatible HTTP server. Tested configurations:

- **Ollama** — chat and embeddings
- **llama.cpp** (server mode) — chat and embeddings
- **llamafile** — chat
- **vLLM** — chat and embeddings

---

## Non-Goals for V1

- Peer-to-peer consensus
- Autonomous global model swapping
- WAN zero-trust networking
- Image and TTS generation
- Distributed vector databases
- Billing or multi-tenant quotas
