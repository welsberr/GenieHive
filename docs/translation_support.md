# GenieHive Translation Support

This note describes the control-plane and node configuration needed to support
translation clients such as SciSiteForge.

GenieHive already exposes the core transport needed for translation:

- `POST /v1/chat/completions`
- client API keys
- role-based routing
- OpenAI-compatible upstream services

Translation support is mostly a matter of configuration discipline.

## Control Plane

The control plane should provide a translation-oriented role or directly
addressable model that the client can target.

Recommended control-plane changes:

1. Add a dedicated role, for example `scientific_translator`.
2. Keep it as `operation: "chat"`.
3. Use a conservative prompt policy that returns translation only.
4. Prefer a stable, instruction-following model family.
5. Keep the role in the loaded role catalog so it appears in `/v1/models`
   and route-resolution output.

Example role entry:

```yaml
- role_id: "scientific_translator"
  display_name: "Scientific Translator"
  description: "Translation-oriented chat route for site localization"
  operation: "chat"
  modality: "text"
  prompt_policy:
    system_prompt: "Translate faithfully. Preserve meaning, structure, citations, and technical terms. Return only the translation."
    request_policy:
      body_defaults:
        temperature: 0.1
  routing_policy:
    preferred_families: ["Qwen3", "Mistral", "Llama"]
    min_context: 8192
    require_loaded: true
```

What matters operationally:

- the role must resolve to a healthy chat service
- the role should stay loaded on a model with enough context for page-sized
  paragraph batches
- the control plane should not silently route translation requests to a
  low-context or partially loaded fallback unless that is explicitly intended

## Auth and Exposure

Keep the same separation used for other GenieHive clients:

- `X-Api-Key` for client requests
- `X-GenieHive-Node-Key` for node registration and heartbeats

If the control plane is exposed beyond localhost, prefer a reverse proxy and
keep the upstream control port private.

## Node Requirements

A node that is meant to serve translation traffic should expose one or more
healthy chat services that can accept small, repeated requests.

Recommended node configuration:

- chat service kind: `chat`
- runtime: any OpenAI-compatible upstream that GenieHive can route to
- assets: a loaded instruction-following model
- observed latency and throughput: populated so scoring can prefer the right
  node
- `accept_requests: true`

Example service snippet:

```yaml
services:
  - service_id: "atlas-01/chat/qwen3-8b"
    kind: "chat"
    endpoint: "http://127.0.0.1:18091"
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
      p50_latency_ms: 900
      tokens_per_sec: 40
```

For translation, loaded state matters more than raw capacity. A node that is
nominally available but not loaded is a poor default target for a localization
job that will touch many pages.

## Node-Side Practices

Use the node agent to keep the registry current:

- heartbeat frequently enough that the control plane sees the service as fresh
- publish loaded assets honestly
- keep queue and latency metrics current when possible
- separate translation services from other high-latency or experimental routes

If a translation model is available through multiple runtimes, prefer the one
that keeps response shape stable and context handling predictable.

## Routing Advice

For translation clients, the most useful route behavior is usually:

- a translation role with a stable model family preference
- `require_loaded: true`
- enough context to keep paragraph-level requests coherent
- predictable prompt policy, not aggressive prompt rewriting

That keeps the client config simple. The client can point to a role alias and
let GenieHive pick the actual service.

## What Not to Do

- Do not rely on a transient model alias unless you are willing to update the
  client config when the alias changes.
- Do not expose raw upstream model endpoints directly to the translation client
  if GenieHive is already in the path.
- Do not route translation through a node that cannot maintain enough context
  for the content size you expect.

## Minimal Support Checklist

- translation role present in the role catalog
- client API key enabled
- node API key enabled
- at least one healthy chat service with a loaded model
- route resolution confirms the translation role resolves to that service
- client can reach the control plane or reverse proxy
