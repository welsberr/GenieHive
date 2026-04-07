#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export GENIEHIVE_CONTROL_CONFIG="$ROOT/configs/control.example.yaml"
export GENIEHIVE_ROLES_CONFIG="$ROOT/configs/roles.example.yaml"
export PYTHONPATH="$ROOT/src"

exec python -m uvicorn geniehive_control.main:app --host 127.0.0.1 --port 8800
