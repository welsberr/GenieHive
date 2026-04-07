#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONTROL_CONFIG="${1:-$ROOT/configs/control.singlebox.example.yaml}"

export GENIEHIVE_CONTROL_CONFIG="$CONTROL_CONFIG"
if [[ -z "${GENIEHIVE_ROLES_CONFIG:-}" ]]; then
  export GENIEHIVE_ROLES_CONFIG="$ROOT/configs/roles.example.yaml"
fi
export PYTHONPATH="$ROOT/src"

HOST="${GENIEHIVE_BIND_HOST:-127.0.0.1}"
PORT="${GENIEHIVE_BIND_PORT:-8800}"

exec python -m uvicorn geniehive_control.main:app --host "$HOST" --port "$PORT"
