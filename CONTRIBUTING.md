# Contributing

GenieHive is still early-stage infrastructure code. Keep changes small, explicit, and easy to verify.

## Setup

```bash
cd /home/netuser/bin/geniehive
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

## Common Checks

```bash
make test
make smoke
```

## Guidelines

- Prefer narrowly scoped patches over broad rewrites.
- Keep the control-plane and node-agent contracts in sync.
- Add or update tests with behavior changes.
- Do not commit local runtime state from `state/`.
- Do not commit benchmark artifacts or cache directories.

## Runtime Notes

- Example configs under `configs/` are meant to stay runnable.
- Scripts under `scripts/` should remain usable as operator entrypoints, not just test helpers.
- If a startup dependency can race in practice, prefer self-healing behavior over one-shot initialization.
