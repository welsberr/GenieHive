# Foundation Gateway Roadmap

Last updated: 2026-07-14

## Decision

Do not fork GenieHive for the Foundation AI gateway work. Implement the feature
set as an optional hardening profile on top of the existing local-first control
plane.

The core project should continue to support casual deployment:

- local model services remain first-class
- static `client_api_keys` and `node_api_keys` remain supported
- empty key lists can still disable auth for development
- audit logging, named keys, quotas, provider accounts, and admin endpoints are
  opt-in

Foundation deployments should enable stricter controls through config, role
catalogs, and operator documentation.

## Design Principle

Separate mechanism from policy.

Core GenieHive mechanisms:

- authenticate a client and attach a request identity
- route OpenAI-compatible requests through roles and services
- optionally record audit metadata without prompt or completion content
- optionally enforce model and operation scopes
- optionally route to external provider-backed services
- optionally summarize usage and enforce budgets

Foundation policy:

- who may receive a key
- what models and roles are approved
- what budgets apply
- what provider accounts are used
- how requests are reviewed before public publication
- how emergency disable and key rotation are performed

## Compatibility Contract

Every Foundation hardening change must preserve these behaviors unless a config
explicitly opts into stricter operation:

1. Existing `configs/control.example.yaml` continues to load.
2. Existing static `auth.client_api_keys` continues to authorize requests.
3. Existing node registration keys continue to work.
4. Existing role catalogs continue to route without client allowlists.
5. `GET /v1/models`, chat, embeddings, transcription, and cluster inspection
   remain available in casual deployments.
6. No provider credentials are required for local-only deployment.
7. Admin endpoints are disabled unless admin authentication is configured.

## Profiles

### Casual Profile

The casual profile is the default shape of GenieHive.

Expected traits:

- local or LAN-bound control plane
- static shared client key, or no auth during isolated development
- no audit log by default
- no budget enforcement
- no provider credential store
- no admin API exposed by default

### Foundation Gateway Profile

The Foundation gateway profile is an opt-in deployment mode for managed access
to local and paid AI services.

Expected traits:

- named, revocable client credentials
- request audit log without prompt or completion content
- model and operation allowlists per key
- Foundation-owned provider account indirection
- optional budget and quota enforcement
- migration-specific role catalogs
- operator and board-readable governance documentation

## Configuration Shape

The final config shape may evolve, but the intended compatibility model is:

```yaml
deployment_profile: "casual"

auth:
  client_api_keys:
    - "change-me-client-key"
  node_api_keys:
    - "change-me-node-key"
  enable_named_client_keys: false
  key_hash_secret_env: "GENIEHIVE_KEY_HASH_SECRET"

audit:
  enabled: false

admin_api:
  enabled: false

authorization:
  enforce_model_allowlists: false
  enforce_operation_allowlists: false
  empty_allowlist_means_no_access: true

providers: []

budgeting:
  enabled: false
```

Foundation example configs can switch these flags on. Casual example configs
should stay short and understandable.

## Status Summary

Status values are `complete`, `partial`, `ready`, `blocked`, and `deferred`.

| Milestone | Status | Evidence or remaining work |
|---|---|---|
| M0 Baseline | complete | `docs/foundation_gateway_baseline.md` and compatibility tests |
| M1 Feature flags | complete | Config models and casual/Foundation examples |
| M2 Named credentials | complete | Key hashing, storage, admin endpoints, and tests |
| M3 Audit log | complete | Request records and admin summaries; streaming final usage moves to M7-B/M8-A |
| M4 Authorization | complete | Named-key operation/model scopes and glob matching |
| M5 Archive profile | complete | Role catalog, client environment contract, smoke client, and operations note |
| M6 Provider indirection | complete | Configured OpenAI-compatible providers and request-time env credentials |
| M7 Non-OpenAI adapter | blocked | An operator must select native Python or optional `pi-ai` bridge first |
| M8 Budgets and quotas | partial | M8-A cost calculation is complete; enforcement remains |
| M9 Admin operations | ready | HTTP endpoints exist; CLI and operator documentation do not |
| M10 Security review | ready | Checklist and production exposure review do not exist |

## Instructions For Implementation Agents

These rules are part of the roadmap. Follow them for every work packet.

1. Work on one packet only. Do not include later packets in the same change.
2. Before editing, run `git status -sb` and read every file listed by the packet.
3. Preserve casual defaults. No provider key, named key, audit log, budget check,
   or admin endpoint may become mandatory for `configs/control.example.yaml`.
4. Never put a real credential, provider response, prompt, or completion in a
   fixture, log assertion, example, or committed file.
5. Unit tests must use fake upstreams, injected environment mappings, and
   temporary SQLite databases. Do not call live model providers from tests.
6. Do not change route scoring, node heartbeat behavior, or public response
   shapes unless the packet explicitly requires it.
7. Run the packet test command, then `python -m pytest -q tests`.
8. Mark a packet complete only after its acceptance checks pass. If a required
   decision is missing, stop and report the blocker instead of choosing a new
   architecture.

## Work Queue

Execute ready packets in the order shown. M7 packets remain blocked until the
decision gate is resolved. The M5, M8, and M9-A tracks are independent.

### M5-A: Archive Role Catalog

Status: complete

Goal: define stable role names for archive migration without binding clients to
provider model IDs.

Edit only:

- `configs/roles.foundation.archive.yaml` (new)
- `tests/test_foundation_archive_profile.py` (new)
- `configs/control.foundation.example.yaml` only to set `roles_path`

Requirements:

- Define `archive_migrator`, `archive_metadata_extractor`,
  `archive_link_reviewer`, `archive_copyeditor`, and
  `archive_factcheck_assistant`.
- Every role uses a supported operation and a non-empty system prompt.
- Routing policies describe capabilities or preferred families; they must not
  contain API keys, base URLs, or mandatory paid-provider model IDs.
- The test loads the YAML through `load_role_catalog()` and asserts all five role
  IDs are unique and present.

Acceptance:

- `python -m pytest -q tests/test_foundation_archive_profile.py`
- The Foundation config loads with the new role path.
- Existing local services can satisfy at least one archive role by policy.

Out of scope: client scripts, provider adapters, and prompt-quality evaluation.

### M5-B: Archive Client Contract And Smoke Client

Status: complete

Goal: prove an archive client needs only the GenieHive endpoint, client key, and
role name.

Edit only:

- `configs/clients/archive_migration.example.env` (new)
- `scripts/smoke_foundation_archive.py` (new)
- `tests/test_foundation_archive_smoke.py` (new)
- `docs/foundation_gateway_operations.md` (new) for the smoke instructions

Requirements:

- Read `GENIEHIVE_BASE_URL`, `GENIEHIVE_API_KEY`, and `GENIEHIVE_MODEL`.
- Default `GENIEHIVE_MODEL` to `archive_migrator`.
- Send one OpenAI-compatible non-streaming chat request.
- Exit nonzero and print a concise error for missing configuration, HTTP
  failure, malformed JSON, or a missing assistant message.
- Test the client with a local fake HTTP server; do not require a model server.

Acceptance:

- The script succeeds against the fake server.
- No provider-specific environment variable is read by the script.

Out of scope: batch migration logic and retries.

### M7-0: Adapter Strategy Decision

Status: blocked on operator decision

Goal: select one implementation strategy before adapter code is written.

Decision options:

- `native_python`: implement Anthropic Messages in the FastAPI process using the
  official Python SDK or HTTP API.
- `pi_bridge`: run an optional Node service using `@earendil-works/pi-ai` and
  register it with GenieHive as an ordinary external service.

Decision record:

- Update `docs/pi_ai_integration.md` with `Selected strategy`, `Reason`,
  `Operational owner`, `Review date`, `Implementation files`, and `Test files`.
- Select `pi_bridge` only when at least three non-OpenAI protocols, provider
  OAuth, or persisted cross-provider sessions are required.

Stop condition: an implementation agent must not infer the choice from package
popularity or provider count in examples.

### M7-A: Non-Streaming Adapter Contract

Status: blocked by M7-0

Goal: support one Anthropic Messages request through the selected adapter while
preserving the OpenAI-compatible GenieHive response.

Required behavior:

- Map system, user, and assistant text messages.
- Map model ID, maximum output tokens, temperature, and stop sequences.
- Map assistant text, finish reason, input tokens, and output tokens back to the
  existing OpenAI-compatible response.
- Return a specific `4xx` error for unsupported request fields and `502` for an
  upstream provider failure.
- Keep `openai_compatible` and local service behavior unchanged.

Tests:

- Add adapter-specific unit tests with recorded synthetic payloads.
- Add one control API test that routes a configured Anthropic model.
- Run `python -m pytest -q tests`.

Out of scope: streaming, images, tool calls, OAuth, and conversation persistence.

### M7-B: Streaming Adapter Contract

Status: blocked by M7-A

Goal: stream Anthropic text and final usage through the OpenAI-compatible SSE
facade.

Requirements:

- Emit valid OpenAI chat-completion chunks and exactly one `[DONE]` marker.
- Convert upstream errors before the first event into an HTTP error response.
- Convert errors after streaming starts into a terminal SSE error event and
  close the stream.
- Record final status and usage in the audit row after the stream completes.

Out of scope: tool calls and exposed reasoning content.

### M7-C: Tool And Reasoning Compatibility

Status: blocked by M7-B

Goal: normalize tool calls without exposing hidden reasoning by default.

Requirements:

- Validate tool arguments against the submitted JSON Schema.
- Preserve tool call IDs and tool result association.
- Make reasoning exposure an explicit policy; the default remains hidden.
- Add tests for malformed arguments, interleaved text/tool deltas, and tool
  results returned to a different eligible model.

### M8-A: Price Map And Cost Calculation

Status: complete

Goal: calculate deterministic request cost without enforcing a limit.

Edit:

- `src/geniehive_control/config.py`
- `src/geniehive_control/budgeting.py` (new)
- `src/geniehive_control/main.py`
- `tests/test_control_budgeting.py` (new)
- `configs/control.foundation.example.yaml`

Requirements:

- Add per-model input/output price entries in integer microdollars per million
  tokens. Do not use binary floating point for policy decisions.
- Calculate cost only from normalized usage and an exact model price match.
- Store the resulting `estimated_cost_cents` in the existing audit field.
- When a price is unknown, return `None`; do not guess or silently use another
  model's price.
- Budgeting remains disabled by default.

Acceptance:

- Tests cover known price, unknown price, zero-token usage, and rounding.
- Casual-profile responses and audit behavior remain unchanged.

Out of scope: denying requests and fetching prices from the network.

### M8-B: Named-Key Token Enforcement

Status: ready

Goal: reject a named key whose monthly token allowance is exhausted.

Requirements:

- Add a registry query for usage since the current configured reset boundary.
- Check `monthly_token_limit` before calling the upstream.
- Return `429` with a stable GenieHive error code when exhausted.
- Static and development keys remain unaffected.
- Use an injected or explicitly passed clock in tests; do not depend on the
  machine's current month.

Acceptance:

- Tests cover below limit, exactly at limit, over limit, disabled enforcement,
  reset boundary, and two different keys.

Out of scope: predicting the token count of the pending request.

### M8-C: Cost Budget Enforcement

Status: ready after M8-B

Goal: enforce named-key, provider, and global monthly cost ceilings.

Requirements:

- Use audited integer or exact-decimal cost totals.
- Apply the most restrictive configured limit before the upstream call.
- Implement `deny_on_unknown_cost`: deny when true, allow and audit unknown cost
  when false.
- Return `429` for an exhausted budget and `503` when policy requires a price but
  no price exists.
- Never treat a missing limit as zero.

Acceptance:

- Tests isolate key, provider, and global limits and verify casual defaults.

### M9-A: Admin CLI

Status: ready

Goal: manage keys and inspect usage through the admin HTTP API rather than direct
SQLite access.

Edit:

- `src/geniehive_control/admin_cli.py` (new)
- `pyproject.toml` for the `geniehive-admin` entry point
- `tests/test_admin_cli.py` (new)

Commands:

- `client-key create`
- `client-key list`
- `client-key enable`
- `client-key disable`
- `audit list`
- `audit summary`

Requirements:

- Read base URL and admin key from flags or environment variables.
- Never print a stored key hash. Print a newly created raw key only once.
- Provide nonzero exits for authentication, validation, transport, and server
  errors.

### M9-B: Operations Documentation

Status: ready after M9-A and M8-C

Goal: make routine and emergency operation reproducible.

Create or complete `docs/foundation_gateway_operations.md` with:

- initial configuration
- provider environment variables
- key provisioning and revocation
- usage and budget inspection
- archive smoke workflow
- emergency provider disable
- SQLite backup and restore
- when to use provider-native seats instead of GenieHive

Acceptance: every command names its working directory and required environment;
no example contains a plausible real secret.

### M10-A: Security Checklist

Status: ready after M9-B

Goal: classify production exposure risks without expanding GenieHive into a WAN
security platform.

Create `docs/foundation_gateway_security.md` covering:

- TLS and reverse proxy ownership
- admin endpoint exposure
- provider and client secret storage
- prompt/completion logging prohibition
- CORS and browser access
- request size and rate limits
- backup protection and restoration tests
- dependency and container update policy
- emergency key and provider disable

For every item record `implemented`, `deployment control`, or `deferred`, plus an
owner and verification method. Do not mark the Foundation profile production
ready while any critical item has no owner or mitigation.

## Completion Order

1. Archive track: M5-A, then M5-B.
2. Budget track: M8-A, then M8-B, then M8-C.
3. Adapter track: M7 begins only after M7-0 is resolved; then run M7-A,
   M7-B, and M7-C.
4. Operations track: M9-A may start immediately. M9-B requires M9-A and M8-C.
5. Security track: M10-A follows M9-B.

Do not combine tracks merely to reduce the number of commits. Small independent
changes are intentional so lower-cost models can be assigned one packet with a
clear verification boundary.
