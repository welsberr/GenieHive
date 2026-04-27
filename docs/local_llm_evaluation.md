# Local LLM Evaluation for GenieHive Agent Roles

Last updated: 2026-04-27

## Purpose

This document describes a framework for evaluating locally-hosted LLMs against the
roles that GenieHive needs to fulfill in a multi-agent or tool-use pipeline. The goal
is to determine which models are fit for which roles given available hardware, and
to produce benchmark data that GenieHive's own routing layer can consume.

---

## Role Taxonomy

GenieHive routes by role. Before evaluating models, the roles likely needed in an
agent pipeline must be defined. The following taxonomy covers the most common cases.

### Tier 1: Core Inference Roles

| Role ID              | Description                                              | Key requirements                                  |
|----------------------|----------------------------------------------------------|---------------------------------------------------|
| `general_assistant`  | General-purpose instruction following, Q&A, summarization| Good instruction following, ≥8k context           |
| `reasoning`          | Multi-step problem solving, chain-of-thought tasks       | Extended thinking, ≥16k context, slow OK          |
| `code_assistant`     | Code generation, explanation, debugging                  | Strong code benchmarks, fill-in-middle optional   |
| `structured_output`  | JSON/schema-constrained generation                       | Grammar sampling or reliable JSON mode            |
| `tool_use`           | Tool/function call formatting and parsing                | Function call format compliance, low hallucination|

### Tier 2: Supporting Roles

| Role ID              | Description                                              | Key requirements                                  |
|----------------------|----------------------------------------------------------|---------------------------------------------------|
| `embedder`           | Semantic embedding for RAG, search, clustering           | High MTEB scores, must be loaded (not lazy)       |
| `classifier`         | Short-text classification, intent detection              | Fast TTFT, low token budget, reliable format      |
| `summarizer`         | Condensing long documents                                | Long context (≥32k), extractive reliability       |
| `critic`             | Reviewing, scoring, or evaluating model outputs          | Self-consistency, instruction precision            |
| `transcriber`        | Audio-to-text (Whisper-family)                           | WER on domain-specific content                    |

### Tier 3: Specialized Roles (project-specific)

These are informed by the current project context (TalkOrigins bibliography pipeline,
Panda's Thumb archive, multi-site search).

| Role ID                | Description                                                | Key requirements                               |
|------------------------|------------------------------------------------------------|------------------------------------------------|
| `bibliographic_analyst`| Extract, verify, and enrich bibliographic metadata         | Precise instruction following, structured JSON |
| `science_explainer`    | Explain scientific concepts for a general audience         | Factual accuracy, good prose, ≥8k context      |
| `search_query_writer`  | Generate search queries from topic descriptions            | Concise, varied output; fast                   |
| `html_cleaner`         | Identify and convert markup patterns (MT tags, etc.)       | Reliable format compliance                     |

---

## Hardware Context

Evaluation should be scoped to what is actually available. Document hardware before
running benchmarks.

Recommended inventory fields per host:

```yaml
host_id: atlas-01
gpu:
  - name: NVIDIA Tesla P40
    vram_gb: 24
    cuda: "8.0"
cpu:
  threads: 24
  model: "Intel Xeon"
ram_gb: 128
fast_storage: true   # NVMe vs. spinning rust matters for model load time
```

Models that do not fit in VRAM will run on CPU or split across GPU+CPU. Note
GPU-only, GPU+CPU, and CPU-only fit status explicitly for each candidate.

---

## Candidate Model Selection

For each role tier, select 2–4 candidate models. Selection criteria:

1. **Fits hardware** — VRAM budget for the target host
2. **GGUF available** — for llama.cpp / llamafile deployment
3. **License** — permissive enough for intended use
4. **Recency** — prefer models released in the last 12 months unless a classic
   substantially outperforms

### Suggested Starting Candidates (as of 2026-04)

**General assistant / reasoning:**
- Qwen3-8B-Q4_K_M (fits P40 at 24 GB, extended thinking available)
- Qwen3-14B-Q4_K_M (fits P40 at ~10 GB VRAM + offload, better reasoning)
- Mistral-7B-Instruct-v0.3 (fast, reliable baseline)

**Code assistant:**
- Qwen2.5-Coder-7B-Instruct
- DeepSeek-Coder-V2-Lite-Instruct (16B MoE, may fit on CPU+GPU split)

**Structured output / tool use:**
- Qwen3-8B (native tool call support)
- functionary-small-v3.2 (purpose-built for tool use)
- Hermes-3-Llama-3.1-8B (strong JSON reliability)

**Embeddings:**
- nomic-embed-text-v1.5 (fast, high MTEB, 137M params)
- mxbai-embed-large-v1 (larger, higher MTEB)
- bge-small-en-v1.5 (smallest, acceptable quality for retrieval)

**Transcription:**
- faster-whisper large-v3 (best WER, GPU accelerated)
- faster-whisper medium.en (faster, smaller, English-only)

---

## Evaluation Protocol

### Phase 1: Deployment fit check

For each candidate:

1. Load the model via llama.cpp or Ollama.
2. Send a minimal completion request to confirm the endpoint is responding.
3. Record:
   - Actual VRAM used (from `nvidia-smi`)
   - Time to first token on a short prompt (~50 tokens)
   - Tokens/sec on a medium completion (~200 tokens)

Pass criterion: TTFT < 5 s, tokens/sec > 5.

### Phase 2: Role fitness benchmarks

Use GenieHive's built-in benchmark runner for chat roles. Extend with custom
workloads for each role. Each workload should have 3–5 cases with known expected
outputs or pass criteria.

**Workload design principles:**
- Cases should be representative of real workload (not toy examples)
- Pass criteria should be checkable without a judge model where possible
  (exact match, JSON parse, regex, non-empty, length bounds)
- Include at least one adversarial case per role (ambiguous prompt, edge input)
- Record `chat_template_kwargs` for models that need them (e.g., Qwen3 thinking)

**Suggested workloads to add to `benchmark_runner.py`:**

```
chat.structured_json      — produce valid JSON matching a schema
chat.tool_call_format     — emit a well-formed function call
chat.code_python          — generate a short working Python function
chat.long_context_recall  — answer from a 16k-token context document
chat.concise_classification — classify text into one of N labels
```

**Embeddings workloads** (separate evaluation script needed):
- Cosine similarity ranking on semantically close/distant pairs
- Retrieval recall@5 on a small fixed corpus

### Phase 3: Comparative scoring

For each role, rank candidates by:

1. Pass rate (primary)
2. Tokens/sec (secondary, for latency-sensitive roles)
3. TTFT (secondary, for interactive roles)
4. VRAM cost (tie-breaker)

Document the winner and runner-up. Load both into GenieHive's benchmark store
so the routing layer can score them in live operation.

---

## Integrating Results into GenieHive

After running benchmarks:

1. Emit a JSON benchmark report (use `run_benchmark_workload.py`).
2. Ingest into the control plane: `python scripts/ingest_benchmark_report.py`.
3. Define a role in `roles.yaml` with `preferred_families` aligned to the
   winning candidate's model family.
4. Verify routing: `GET /v1/cluster/routes/resolve?model=<role_id>` should
   return the winning service.
5. Run a live request through the role to confirm end-to-end.

---

## Evaluation Checklist

```
[ ] Hardware inventory documented for each candidate host
[ ] Candidate models selected per role tier
[ ] Each candidate loaded and Phase 1 deployment check passed
[ ] Custom workloads written for at least Tier 1 roles
[ ] Phase 2 benchmarks run and results recorded
[ ] Results ingested into GenieHive benchmark store
[ ] Roles defined in roles.yaml matching Phase 3 winners
[ ] End-to-end routing verified for each role
[ ] Results documented in a summary (see template below)
```

---

## Results Summary Template

```markdown
## Evaluation Results — <date>

### Hardware
- Host: <host_id>
- GPU: <name>, <vram_gb> GB VRAM
- RAM: <ram_gb> GB

### Role: general_assistant
| Model              | Pass rate | tok/s | TTFT ms | VRAM GB | Result  |
|--------------------|-----------|-------|---------|---------|---------|
| Qwen3-8B-Q4_K_M    | 0.92      | 38    | 420     | 6.1     | WINNER  |
| Mistral-7B-v0.3    | 0.85      | 52    | 310     | 4.9     | runner-up |

### Role: embedder
| Model                  | Recall@5 | Latency ms | VRAM GB | Result  |
|------------------------|----------|------------|---------|---------|
| nomic-embed-text-v1.5  | 0.88     | 12         | 0.3     | WINNER  |
| bge-small-en-v1.5      | 0.79     | 8          | 0.1     | runner-up |

... (repeat for each role)
```

---

## Notes on Model Families and Known Behaviors

**Qwen3 / Qwen3.5:**
GenieHive auto-detects these and sets `enable_thinking: false` unless a role or
asset explicitly overrides. For the `reasoning` role, set `enable_thinking: true`
in the role's `body_defaults` to engage extended chain-of-thought.

**Mistral / Mixtral:**
Standard instruction format. No special handling needed.

**DeepSeek models:**
Some versions use a `<think>` block in their output. GenieHive strips
`reasoning_content` from responses but not inline `<think>` blocks. If the
model emits inline thinking that should be hidden from clients, add a
response-cleaning step or configure the model server to suppress it.

**Embedding models via Ollama:**
Ollama's embedding endpoint is `/api/embeddings`, not `/v1/embeddings`. The
current `UpstreamClient` uses the OpenAI-compatible path. When registering
an Ollama embedding service, confirm the node config points to the correct
endpoint or that the Ollama version supports `/v1/embeddings`.

**llamafile:**
Does not support the embeddings endpoint. Only suitable for chat roles.
