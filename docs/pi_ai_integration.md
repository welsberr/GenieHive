# pi-ai Integration Boundary

Last updated: 2026-07-14

## Decision

GenieHive retains ownership of cluster registration, health, role routing,
authorization, auditing, and budget enforcement. It does not take a mandatory
dependency on `@earendil-works/pi-ai`.

GenieHive adopts the provider/API separation, capability metadata, normalized
usage, explicit stop reasons, credential locking, compatibility profiles, and
scripted-provider testing concepts used by `pi-ai`.

An optional Node provider bridge may use `pi-ai` for non-OpenAI provider
protocols and cross-provider conversation handoffs. The bridge must appear to
GenieHive as an ordinary registered service; it does not participate in route
selection or governance decisions.

## Implemented Baseline

Enabled `openai_compatible` entries under `providers` now:

- register an external provider host and service at control-plane startup
- advertise explicitly configured model IDs through `GET /v1/models`
- resolve API keys from the configured environment variable at request time
- merge provider default headers without placing credentials in YAML
- fail with `503` when required provider credentials are unavailable
- remain outside node heartbeat and local runtime probing

Disabled providers and configurations without a `providers` section retain the
existing local-only behavior.

## pi-ai Bridge Spike

The bridge spike should cover OpenAI and Anthropic chat models with:

1. streaming and non-streaming responses
2. tool calls and argument validation
3. cancellation and partial failure results
4. reasoning-content policy
5. normalized usage and cost fields
6. one role that can route between a local service and a bridge service

Adopt the bridge in production when GenieHive needs at least three non-OpenAI
provider protocols, provider OAuth, or persisted cross-provider sessions. If
Anthropic is the only additional protocol, compare the bridge against a native
Python adapter before accepting the Node operational dependency.

## Ownership Contract

The bridge may own provider wire conversion, provider authentication, OAuth
refresh, and provider-reported usage normalization. GenieHive continues to own
client identity, model and operation scopes, role selection, audit records,
quota decisions, and provider budget enforcement.
