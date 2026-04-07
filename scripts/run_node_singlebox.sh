#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

NODE_CONFIG="${1:-$ROOT/configs/node.singlebox.ollama.example.yaml}"

export GENIEHIVE_NODE_CONFIG="$NODE_CONFIG"
export PYTHONPATH="$ROOT/src"

HOST="${GENIEHIVE_NODE_BIND_HOST:-127.0.0.1}"
PORT="${GENIEHIVE_NODE_BIND_PORT:-8891}"

exec python -m uvicorn geniehive_node.main:app --host "$HOST" --port "$PORT"
