# Apple Silicon Nodes Behind Kong

GenieHive can act as the local compute fabric behind Kong AI Gateway. Kong remains
the enterprise ingress point for API policy, authentication, prompt controls, and
provider normalization. GenieHive exposes an OpenAI-compatible internal provider
surface and decides which local, cloud, or employee-device node should serve the
request.

## Recommended Shape

```text
company apps
  -> Kong AI Gateway
      -> managed H100/GCP providers
      -> GenieHive internal provider
           -> trusted datacenter nodes
           -> managed cloud nodes
           -> opted-in Apple Silicon employee nodes
```

Kong should not be asked to manage employee laptop lifecycle directly. It can load
balance and health check upstream targets, but the participation policy for a Mac
node belongs in GenieHive: RAM budget, AC/idle policy, trust tier, loaded models,
queue depth, pause/drain state, and workload eligibility.

## Node Metadata

Apple Silicon nodes should report a trust tier, device class, and contribution
policy:

```yaml
inventory:
  trust_tier: "employee_device"
  device_class: "apple_silicon_mac"
  ram_gb: 64
  max_contribution_ram_gb: 24
  workload_classes: ["background", "low_priority"]
  allowed_model_families: ["qwen2.5", "llama3"]
  idle_only: true
  ac_power_only: true
  capabilities:
    metal: true
```

The node agent publishes these values under `resources.contribution_policy` during
registration. The control plane uses them during route eligibility checks.

## Safe Defaults

Employee and personal devices are opt-in for role routing. A host with
`trust_tier: employee_device` or `trust_tier: personal_device` will not receive
role traffic unless the role explicitly permits it:

```yaml
routing_policy:
  allow_employee_devices: true
  allowed_device_classes: ["apple_silicon_mac"]
  allowed_workload_classes: ["background", "low_priority"]
```

Direct model/service addressing is also blocked for employee and personal devices
unless the service explicitly opts in:

```yaml
state:
  health: "healthy"
  availability: "available"
  accept_requests: true
  allow_employee_direct_requests: true
```

Use direct opt-in sparingly. Company-facing clients should usually request roles,
not laptop-local asset IDs.

## Drain And Pause

Services can decline new work without being marked unhealthy:

```yaml
state:
  health: "healthy"
  availability: "draining"
  accept_requests: true
```

Non-routable availability states are:

- `draining`
- `paused_by_user`
- `offline`
- `quarantined`

`busy` remains routable but receives a scoring penalty. Use `busy` when the node
can accept work but should be deprioritized.

## Role Gates

Roles can constrain where they run:

```yaml
routing_policy:
  preferred_families: ["Qwen2.5", "Llama3"]
  min_context: 4096
  allow_employee_devices: true
  allowed_trust_tiers: ["employee_device"]
  allowed_device_classes: ["apple_silicon_mac"]
  allowed_workload_classes: ["background"]
  denied_trust_tiers: ["personal_device"]
```

`min_context` is enforced when a service or asset reports `context_size`,
`max_context`, or `max_context_tokens`. Services with unknown context are allowed,
so deployment policy should require nodes to report context size for strict roles.

## Kong Integration

Expose GenieHive to Kong as a normal internal OpenAI-compatible upstream. Kong can
own the public route, auth, prompt guard, semantic cache, rate limits, and provider
fallbacks. GenieHive owns the local fleet resolution below that upstream.

For early pilots, create one Kong route for a conservative role such as
`mac_background_assistant`, and keep latency-sensitive or restricted-data roles on
trusted datacenter or managed cloud trust tiers.
