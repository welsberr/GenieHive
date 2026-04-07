# GenieHive Demo

This is the first end-to-end demo path for GenieHive using the example configs already in the repo.

## Goal

Bring up:

- one control plane
- one node agent
- one route-resolution check

The node should auto-register with the control plane on startup and then send periodic heartbeats.

## 1. Start the control plane

From the repo root:

```bash
bash scripts/run_control.sh
```

This uses:

- `configs/control.example.yaml`
- `configs/roles.example.yaml`

## 2. Start the node agent

In another shell:

```bash
bash scripts/run_node.sh
```

This uses:

- `configs/node.example.yaml`

## 3. Inspect the cluster

In another shell:

```bash
bash scripts/demo_inspect.sh
```

That script checks:

- client-facing model metadata
- cluster health
- registered hosts
- registered services
- loaded roles
- route resolution for `mentor`

## Notes

- The example configs use API keys; the inspection script sends the example client key.
- The example node config assumes the underlying model-serving endpoints already exist. The current demo proves control-plane registration and routing metadata, not full inference proxying yet.
- The control plane stores state in `state/geniehive.sqlite3` by default.
