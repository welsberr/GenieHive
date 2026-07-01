# GenieHive

GenieHive is a local-first control plane for heterogeneous generative AI services running across one or more hosts.

V1 scope:

- chat completions
- embeddings
- transcription

Core goals:

- register hosts and services
- track health, inventory, and observed performance
- expose a stable client-facing API
- support direct model addressing and higher-level role addressing
- route requests to healthy loaded services first

Repository layout:

- `docs/architecture.md`: system overview and v1 scope
- `docs/roadmap.md`: current milestones and near-term priorities
- `docs/schemas.md`: canonical data models
- `docs/deployment.md`: intended deployment approach
- `docs/translation_support.md`: translation-oriented control-plane and node notes
- `docs/demo.md`: first end-to-end control-plus-node demo flow
- `docs/llm_demo.md`: detailed master/peer/client LLM demo runbook
- `docs/reverse_proxy.md`: safer external exposure patterns
- `docs/forge_integration.md`: Forge proxy routing for agentic tool-use roles
- `docs/apple_silicon_kong_fabric.md`: using GenieHive as a local compute fabric behind Kong AI Gateway
- `configs/`: example control-plane, node, and role configs
- `scripts/`: small launch and inspection helpers
- `src/geniehive_control/`: control-plane package
- `src/geniehive_node/`: node-agent package

There is now a documented single-machine path as well as the cluster-oriented path, so GenieHive can be exercised as a useful local router even without multiple hosts.

This repository is intended as the clean successor to narrower local gateway experiments. OpenAI-compatible routing remains important, but it is treated as one client facade within a broader cluster control-plane design.

## Development

Local development setup:

```bash
cd /path/to/geniehive
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Common commands:

```bash
make test
make smoke
make health
```

Benchmark workflow:

```bash
PYTHONPATH=src python scripts/run_benchmark_workload.py \
  --base-url http://127.0.0.1:8800 \
  --api-key change-me-client-key \
  --model general_assistant \
  --workload chat.short_reasoning \
  --output /tmp/geniehive-bench.json

PYTHONPATH=src python scripts/ingest_benchmark_report.py /tmp/geniehive-bench.json \
  --base-url http://127.0.0.1:8800 \
  --api-key change-me-client-key
```

Repository conventions:

- local runtime state lives under `state/` and should not be committed
- example configs under `configs/` should remain runnable
- operator scripts under `scripts/` are part of the supported workflow
