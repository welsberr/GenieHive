# Forge Integration

Forge is best treated as an agentic reliability layer that GenieHive can route to, not as a replacement for GenieHive's control plane. GenieHive should continue to own service discovery, role routing, health, load, request policy, and benchmark storage. Forge can own the fragile tool-use loop for roles where that matters.

## Recommended Topology

Run Forge proxy as an OpenAI-compatible upstream:

```bash
forge-proxy --backend-url http://127.0.0.1:8080 --port 18081
```

Then register that proxy as a GenieHive chat service. See:

- `configs/node.singlebox.forge.example.yaml`
- `configs/roles.agentic.example.yaml`

The important service metadata is:

```yaml
runtime:
  engine: "forge-proxy"
  launcher: "external"
```

Roles that should prefer the Forge route set:

```yaml
routing_policy:
  guardrail_profile: "forge_proxy"
  tool_mode: "auto"
  force_respond_tool: true
  context_budget_mode: "upstream"
  agentic_benchmark_workloads:
    - "agentic.tool_use"
```

## Policy Fields

`guardrail_profile` describes the reliability layer expected by a role:

- `none`: no special guardrail preference.
- `forge_proxy`: prefer services whose runtime metadata identifies Forge proxy.
- `forge_middleware`: reserve for services embedding Forge guardrails inside another loop.
- `native_light`: ordinary OpenAI-compatible service with light GenieHive-side policy.

`tool_mode` records whether a route expects native tool calling, prompt-injected tool calling, no tools, or automatic handling.

`force_respond_tool` records the Forge principle that small local models behave better when final text is represented as a structured `respond` tool during tool-capable requests.

`context_budget_mode` records whether context sizing should be inferred automatically, delegated to the upstream, or kept conservative.

`agentic_benchmark_workloads` lists the benchmark families that should count when matching routes for agentic work.

## Benchmark Import

Forge-style results can be ingested into GenieHive as benchmark samples. Useful result keys include:

- `pass_rate`
- `quality_score`
- `completion_rate`
- `terminal_tool_completion_rate`
- `terminal_accuracy`
- `tool_success_rate`
- `tokens_per_sec`
- `ttft_ms`

GenieHive's benchmark quality score treats those correctness fields as route-selection evidence.

## Boundary

GenieHive should not execute arbitrary user tools inside the control-plane process. Central tool execution, if needed, should live in a sandboxed worker service. GenieHive can still route to Forge-backed services, score them, and expose their suitability through `/v1/models` and route-matching metadata.
