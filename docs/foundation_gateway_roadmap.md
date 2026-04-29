# Foundation Gateway Roadmap

Last updated: 2026-04-29

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

## Revised Milestones

### M0: Baseline and Compatibility Guard

Goal: record the current behavior and make compatibility explicit before adding
governance features.

Tasks:

- Add `docs/foundation_gateway_baseline.md`.
- Record current commit, test command, existing exposed ports, and supported
  casual deployment behavior.
- Add or preserve tests proving `configs/control.example.yaml` still loads and
  static `X-Api-Key` auth still works.

Acceptance:

- Baseline document exists.
- Current test suite passes or failures are documented.
- Compatibility contract is visible in docs.

### M1: Config Profiles and Feature Flags

Goal: introduce opt-in switches without changing runtime behavior.

Tasks:

- Add config models for `deployment_profile`, `audit`, `admin_api`,
  `authorization`, `providers`, and `budgeting`.
- Keep default values equivalent to current casual behavior.
- Add a Foundation example config skeleton.
- Add tests for default values and legacy config loading.

Acceptance:

- Existing configs load unchanged.
- New config sections are accepted.
- No governance feature activates by default.

### M2: Named Client Credentials

Goal: support named, revocable API keys while keeping static keys working.

Tasks:

- Add `ClientContext` with principal metadata.
- Add API key generation, hashing, verification, and redaction helpers.
- Add a `client_keys` SQLite table.
- Add registry methods to create, list, disable, enable, and touch keys.
- Support named keys only when `auth.enable_named_client_keys` is true.
- Preserve static `auth.client_api_keys`.

Acceptance:

- Static keys still work.
- Named keys work through `X-Api-Key` when enabled.
- Disabled named keys fail.
- Raw keys are never stored.
- Request handlers can read authenticated client context.

### M3: Request Audit Log

Goal: make production requests attributable without storing prompt or completion
content.

Status: implemented for chat, embeddings, and transcription request wrappers.
Audit logging is disabled by default and enabled by `audit.enabled`. Admin audit
read endpoints are only mounted when `admin_api.enabled` is true.

Tasks:

- Add request ID generation from `X-Request-Id` or UUID.
- Add `request_audit_log` SQLite table.
- Record identity, operation, requested model, resolved service, upstream model,
  provider kind, status, duration, token usage when available, estimated cost
  when available, and error category.
- Add admin-only query and summary endpoints, disabled unless admin API is
  enabled.

Acceptance:

- Chat, embeddings, and transcription requests create audit rows when enabled.
- Prompt and completion content are not logged.
- Failed routing and upstream errors are logged.
- Casual deployments have no audit behavior unless enabled.

### M4: Model and Operation Authorization

Goal: let Foundation keys be limited to approved roles, models, and operations.

Tasks:

- Add allowed models and allowed operations to named keys.
- Enforce operation scopes only when authorization enforcement is enabled.
- Support exact model IDs and conservative glob patterns such as `local/*`,
  `openai/*`, `anthropic/*`, and `role/*`.
- Prefer role IDs for migration workflows.

Acceptance:

- A chat-only key cannot call embeddings when enforcement is enabled.
- A key restricted to `archive_migrator` cannot call unrelated roles.
- Legacy static keys are unaffected unless explicitly mapped into stricter mode.

### M5: Archive Migration Profile

Goal: support TalkOrigins/SciSiteForge-style migration without direct provider
keys in migration scripts.

Tasks:

- Add `configs/roles.foundation.archive.yaml`.
- Add roles such as `archive_migrator`, `archive_metadata_extractor`,
  `archive_link_reviewer`, `archive_copyeditor`, and
  `archive_factcheck_assistant`.
- Add `configs/control.foundation.example.yaml`.
- Add `configs/clients/archive_migration.example.env`.
- Add a smoke script that calls `archive_migrator` through the OpenAI-compatible
  facade.

Acceptance:

- A migration client only needs `GENIEHIVE_BASE_URL`, `GENIEHIVE_API_KEY`, and
  `GENIEHIVE_MODEL`.
- The requested model is a role, not a provider-specific model.
- Local-only provider routing remains possible.

### M6: Provider Credential Indirection

Goal: keep paid provider credentials out of role configs, node configs, and
client scripts.

Tasks:

- Add provider config entries using environment variables first.
- Add external/provider-backed service registration without requiring node
  heartbeat.
- Resolve provider headers centrally in the upstream layer.
- Keep provider credential storage optional; encrypted-at-rest credentials can
  be deferred.

Acceptance:

- Provider keys are loaded from environment variables, not committed YAML.
- Provider-backed services can be routed like local services.
- Local-only deployments do not need provider sections.

### M7: Anthropic Messages Adapter

Goal: expose Anthropic models through the existing OpenAI-compatible chat facade.

Tasks:

- Add provider protocol dispatch in `UpstreamClient`.
- Transform OpenAI-shaped messages into Anthropic Messages requests.
- Transform Anthropic responses back to OpenAI-compatible chat completions.
- Reject Anthropic streaming clearly until implemented.

Acceptance:

- A chat request can route to an Anthropic-backed service.
- System messages and usage fields are mapped correctly.
- Unsupported streaming fails with a specific error.

### M8: Budget and Quota Enforcement

Goal: prevent accidental provider overspend.

Tasks:

- Add budget config with disabled default.
- Use audit summaries to calculate monthly usage.
- Add request, token, and estimated-cost limits per key, provider, and globally.
- Add configurable price maps.

Acceptance:

- Requests over configured limits are denied before upstream calls.
- Unknown-cost behavior is configurable.
- Casual deployments do not perform budget checks.

### M9: Admin CLI and Operations Docs

Goal: make managed operation scriptable and understandable.

Tasks:

- Add `geniehive-admin` CLI for create/list/disable/enable keys and usage
  summaries.
- Add Foundation docs for gateway operation, provider accounts, key management,
  archive migration workflow, and emergency disable.
- Document when provider-native seats are needed instead of GenieHive routing.

Acceptance:

- A new operator can provision and revoke a user key without editing SQLite.
- A board-facing control summary explains ownership, auditability, and budget
  control.

### M10: Security Review

Goal: make the Foundation profile safe to expose beyond localhost.

Tasks:

- Add a security checklist covering provider keys, admin auth, content logging,
  CORS, TLS/reverse proxy, backup/restore, rate limits, and emergency disable.
- Implement critical checklist items or explicitly defer with issue references.
- Keep WAN and zero-trust networking as deployment concerns unless a concrete
  need appears.

Acceptance:

- Security checklist exists.
- Critical production risks have implementation or documented mitigations.

## Initial Implementation Order

1. M0: Baseline and compatibility guard.
2. M1: Config profiles and feature flags.
3. M2: Named client credentials.
4. M3: Request audit log.
5. M4: Model and operation authorization.
6. M5: Archive migration profile.
7. M6: Provider credential indirection.
8. M7: Anthropic Messages adapter.
9. M8: Budget and quota enforcement.
10. M9: Admin CLI and operations docs.
11. M10: Security review.

This order lets local-only and TalkOrigins migration pilots start before paid
provider routing and budget controls are complete.
