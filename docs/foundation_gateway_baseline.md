# Foundation Gateway Baseline

Last updated: 2026-04-29

## Repository State

- Repository: `/home/netuser/bin/geniehive`
- Baseline commit: `2355cf8114db5a1ac4630ca22aba63c703553f70`
- Branch: `main`

## Current Capability Snapshot

GenieHive is currently a local-first control plane for heterogeneous generative
AI services. It already supports:

- OpenAI-compatible `GET /v1/models`
- OpenAI-compatible `POST /v1/chat/completions`
- OpenAI-compatible `POST /v1/embeddings`
- `POST /v1/audio/transcriptions` multipart proxying
- node registration and heartbeat
- SQLite-backed hosts, services, roles, and benchmark samples
- role-based route resolution
- request policy shaping
- benchmark-informed route scoring
- optional active service health probing
- static client and node API keys

## Casual Deployment Behavior To Preserve

- `configs/control.example.yaml` loads without Foundation-specific sections.
- Static `auth.client_api_keys` authorize client requests with `X-Api-Key`.
- Static `auth.node_api_keys` authorize node requests with
  `X-GenieHive-Node-Key`.
- Empty client or node key lists disable that auth check for development.
- Local model servers do not require provider credential config.
- Admin endpoints, audit logging, named keys, and budget checks are not required
  for a local-only deployment.

## Current Example Ports

- Control plane default: `127.0.0.1:8800`
- Node examples commonly use localhost service endpoints for Ollama,
  llama.cpp, llamafile, or vLLM.
- Recent ZeroTier test deployment used control plane binding
  `172.24.50.65:8800`, node `127.0.0.1:8891`, and llama.cpp
  `127.0.0.1:18091`.

## Baseline Verification

Run from the repository root:

```bash
python -m pytest -q tests
```

Expected current result at baseline: all tests pass.

Current verification result after adding the Foundation roadmap, config profile
scaffold, named client key storage, opt-in named auth, admin key endpoints, and
request audit logging:

```text
61 passed
```

## Known Constraints

- Client authentication is static-key based, not named or revocable per user.
- Request attribution is not currently persisted.
- Provider credentials are not modeled as first-class control-plane objects.
- No budget or quota enforcement exists.
- Anthropic Messages API is not natively adapted behind the OpenAI-compatible
  facade.
