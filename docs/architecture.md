# GenieHive Architecture

Status: proposed v1 architecture
Drafted: 2026-04-05

## Repo Name

Chosen name: `GenieHive`

Why this name:

- suggestive: "genie" implies generative AI services, "hive" implies a cooperating cluster
- accessible: easy to say, remember, and explain
- whimsical enough to feel like a project name rather than a dry infrastructure label

Tradeoff:

- `GenieHive` is less search-distinct than `Geniewarren` because `hive` is a common product metaphor

## Mission

GenieHive is a local-first control plane for heterogeneous generative AI services running across one or more hosts.

It should:

- register hosts and their available services
- expose a stable client-facing API
- track health, capacity, and observed performance
- support direct model addressing and higher-level role addressing
- route requests to healthy loaded services first
- optionally coordinate loading or swapping when policy allows
- remain practical for a small self-hosted deployment with two hosts

## Non-Goals For V1

Out of scope initially:

- peer-to-peer consensus
- autonomous global model swapping across many nodes
- full WAN zero-trust platform engineering
- image and TTS generation orchestration
- distributed vector database management
- billing or multi-tenant quota accounting

## Architectural Position

GenieHive is not just an OpenAI-compatible gateway.

It is a control plane with these layers:

1. Control API
   - authoritative registry
   - routing and scheduling
   - role catalog
   - operator inspection

2. Node Agent
   - host discovery
   - service discovery
   - telemetry reporting
   - optional local process management

3. Provider Adapters
   - OpenAI-compatible chat backends
   - OpenAI-compatible embedding backends
   - transcription backends
   - future adapters for image and speech synthesis

4. Client Facades
   - OpenAI-compatible facade for completions and embeddings
   - operator API for topology, health, and inventory

## Core Concepts

### Host

A physical or virtual machine participating in the cluster.

### Service

A concrete callable capability on a host. Examples:

- chat completion endpoint
- embedding endpoint
- transcription endpoint

### Asset

A model weight, model name, application, or runtime target that a service can serve.

### Role

A reusable task profile that describes how requests should be fulfilled. A role is policy, not a concrete model.

### Route Resolution

Request handling order:

1. If the requested `model` matches a currently loaded and healthy concrete asset or service alias, route directly.
2. Otherwise, if the requested `model` matches a known role, resolve the role to the best eligible service.
3. Otherwise, fail clearly.

## V1 Capability Scope

V1 supports only:

- chat completions
- embeddings
- transcription

## Topology

Recommended initial topology:

- 1 control plane
- 2 node agents
- 1 or more clients
- LAN-first deployment
- API key auth in v1
- VPN or mTLS in v1.5

## API Families

### Client API

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `POST /v1/audio/transcriptions`

`GET /v1/models` should expose enough metadata for programmatic clients to make routing decisions about what GenieHive can handle cheaply, especially for lower-complexity offloaded work. That metadata should include direct assets, service-backed aliases, role aliases, operation kind, health, loaded status, and observed performance hints.

### Operator API

- `GET /v1/cluster/hosts`
- `GET /v1/cluster/services`
- `GET /v1/cluster/roles`
- `GET /v1/cluster/health`
- `GET /v1/cluster/routes/resolve?model=...`

### Node API

- `POST /v1/nodes/register`
- `POST /v1/nodes/heartbeat`
- `GET /v1/node/inventory`
- `POST /v1/node/services/refresh`

## Data Store

V1 should use SQLite for durable state.

## Routing Rules

### Direct Model Resolution

If a request names a concrete asset alias or service alias:

- prefer loaded and healthy services
- choose the lowest-cost healthy target if multiple matches exist
- fail clearly if all matches are unhealthy

### Role Resolution

If direct resolution fails, treat the requested name as a role.

Role resolution should filter by:

- operation kind
- modality
- health
- auth and exposure compatibility
- minimum context or memory requirements
- preferred model families

Then rank by:

- already loaded
- recent health
- expected latency
- queue pressure
- operator priority

## First Implementation Sequence

1. Create the repo skeleton and docs.
2. Implement SQLite-backed registry models.
3. Implement node registration and heartbeat.
4. Implement operator inspection endpoints.
5. Implement client-facing chat routing.
6. Add embeddings routing.
7. Add transcription routing.
8. Add truthful readiness and health reporting.
9. Add role catalog and role-based resolution.
10. Add optional managed local runtime support.
