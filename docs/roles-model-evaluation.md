# Roles × models evaluation framework

This is the operating plan for qualifying local models for GenieHive roles.
The unit of evidence is a model, serving profile, role, workload, dataset
revision, and evaluator together. A model is not promoted because it wins a
general leaderboard.

## Current implementation

`docs/evaluation_catalog_v1.json` is a public example catalog of candidate model
profiles and synthetic workload contracts. It does not assert that those models
are installed, licensed for a particular use, or qualified. Keep deployment-specific
paths, exact weight hashes, private replay cases, and raw responses in a separate
private catalog; do not commit those records as public examples.

The `geniehive_control.evaluation` module provides model-profile and workload
contracts, dataset revisions, risk classes, minimum pass rates, hard-failure
declarations, and deterministic checks for nonempty output, JSON validity,
required text, and regular-expression matches.

The chat benchmark runner now records case-level results inside each benchmark
sample. Existing aggregate fields remain for routing compatibility.

Pass an `EvaluationWorkload` from a loaded catalog directly to
`run_chat_benchmark`. The report retains its role IDs, dataset revision,
evaluator, risk class, threshold, hard-failure codes and `contract_passed` result.
The runner executes only `geniehive_control.evaluation.check_response`; it rejects
other evaluator names instead of mislabeling a deterministic run as judge review.
Declared hard-failure codes produced by these checks override the pass-rate
threshold. `contract_passed` is a deterministic contract result, not a model
qualification or a routing promotion. Semantic hard failures that require human
or judge review are outside these checks.

Nonempty responses that fail a JSON, substring or regex check count as failed
cases, not as empty responses. For compatibility, the chat runner falls back to
`reasoning_content` when normal content is empty; a passing nonempty check is
therefore not proof that an end-user final answer was delivered. The public
example JSON checks verify syntax and text presence, not JSON-schema conformance,
factual accuracy or correct tool execution.

Run the offline regression suite with `python -m pytest -q` after installing
`.[dev]` in a virtual environment. It uses synthetic responses and temporary
registries; no model server, GPU, provider key or live routing change is required.

## Role catalog

| Role | Representative work | Hard failures |
|---|---|---|
| `general_assistant` | concise Q&A and support | empty or unusable answer |
| `reasoning` | multi-step technical analysis | unsupported conclusion |
| `coding_agent` | repository edits, tests, tool use | broken patch or unsafe action |
| `tool_user` | function calls and recovery | invalid or invented arguments |
| `structured_extractor` | metadata, claims, citations, JSON | invalid schema or invented field |
| `evidence_analyst` | claim/span/evidence mapping | missing source span or fabricated citation |
| `archive_migrator` | preserve HTML, links, citations, structure | silent content loss |
| `translation_editor` | faithful multilingual conversion | altered meaning or broken markup |
| `critic_reviewer` | adversarial review and defect discovery | missed high-risk defect |
| `embedder` | retrieval and clustering | retrieval-quality threshold failure |
| `transcriber` | transcription and diarization | unacceptable WER or speaker error |

## Model pools

The proposed comparison pool includes Qwen3.5-9B, Qwen3-8B, Qwen2.5-14B,
Qwen2.5-Coder-14B/32B, Devstral Small 2, DeepSeek-R1-Distill-Qwen-32B,
Tongyi DeepResearch, Mixtral, Nail, Dagger, and Jina Embeddings v4.

The first comparisons should be Qwen3.5-9B as the fast baseline;
Qwen2.5-Coder-14B and Devstral for coding; Nail and Dagger for high-capability
reasoning and research; Qwen2.5-Coder-32B and DeepSeek-R1-Distill-Qwen-32B for
offline deep work; and Jina v4 against BGE-M3 for retrieval.

Every profile must include the exact file, hash, quantization, runtime,
context, GPU-layer/offload configuration, and prompt/template settings.

## Dataset design

The planned full suite starts each role with 30 cases: 20 representative, 5 adversarial, and 5
boundary/failure cases. Cases are versioned and classified as deterministic
contract cases, human- or judge-reviewed quality cases, redacted replay cases
from archive/bibliography/evidence/translation/repository work, or privacy-
reviewed production shadow cases.

The checked-in starter catalog currently contains two workloads with two cases
each; the larger suite described here remains a roadmap.

High-risk roles must have hard failures for fabricated citations, missing
evidence spans, unsafe tool actions, invalid output contracts, and silent loss
of source qualifications.

## Scoring and qualification

Use role-specific scorecards rather than a universal ranking:

```text
45% correctness
20% contract compliance
15% robustness
10% latency
5% throughput
5% resource efficiency
```

Hard failures override the aggregate. For high-risk research and publication
roles, evidence fidelity and hallucination rate replace most of the latency
weight. For coding, tests passed and patch correctness dominate.

Report p50/p95 TTFT, generation rate, context size, VRAM, CPU offload,
concurrency, error rate, case-level failures, and evaluator revision.

## Operational roadmap

### Phase 0 — inventory and safety

Hash local weights and record licenses; inventory hosts, GPU memory, runtimes,
and active services; use isolated benchmark ports; define rollback and private
log retention.

### Phase 1 — contracts and harness

Expand the catalog to all Tier 1 roles; add structured-output, tool-use,
coding, archive, and evidence workloads; add embeddings, transcription, and
vision runners; retain raw case results separately from routing hints.

### Phase 2 — controlled matrix

Run candidates at 4K, 16K, and 32K where supported; full-GPU and CPU-offloaded
profiles; one and two concurrent requests; and deterministic and robustness
settings. Repeat nondeterministic cases at least three times.

### Phase 3 — qualification

Select a winner and runner-up per role, document hard failures, set latency and
resource ceilings, and ingest only reviewed benchmark summaries into routing.

### Phase 4 — canary and production

Shadow or low-risk route selected workloads. Monitor human corrections,
contract violations, latency, queueing, and model-specific failure modes.
Promote only after role gates pass, with explicit fallbacks and rollback.

### Phase 5 — continuous evaluation

Add representative production failures to the regression set, rerun smoke
tests after runtime changes, rerun full role suites after model or prompt
changes, and expire stale results without deleting history.

## Promotion boundary

Deployment catalogs, private prompts, raw responses, and unreviewed benchmark
cases remain private/draft; the checked-in synthetic examples are public.
Only reviewed aggregate benchmark records may influence routing;
no benchmark command should silently alter production role preferences.
