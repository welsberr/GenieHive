#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export GENIEHIVE_NODE_CONFIG="$ROOT/configs/node.example.yaml"
export PYTHONPATH="$ROOT/src"

exec python -m uvicorn geniehive_node.main:app --host 127.0.0.1 --port 8891
