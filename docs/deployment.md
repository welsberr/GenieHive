# GenieHive Deployment

## Initial Deployment Target

V1 should be easy to deploy on a small self-hosted setup:

- 1 control plane
- 2 node agents
- private LAN or VPN
- API-key auth first

## Binding Guidance

Defaults should be conservative:

- control plane binds to localhost by default during development
- node agents bind to localhost unless remote registration is needed
- managed inference runtimes should stay node-local unless there is a specific reason to expose them

## Security Baseline

Required in v1:

- client API keys
- node registration keys
- clear separation between client-facing and node-facing credentials

Planned after v1:

- mTLS between control plane and nodes
- scoped client tokens

## Persistence

Use SQLite first for:

- host registry
- service registry
- role catalog
- recent health and benchmark samples

## Startup Order

1. Start the control plane.
2. Start node agents.
3. Confirm registration and heartbeat visibility.
4. Confirm client API readiness.
5. Exercise chat, embeddings, and transcription paths.
