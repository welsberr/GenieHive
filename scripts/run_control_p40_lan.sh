#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export GENIEHIVE_BIND_HOST="${GENIEHIVE_BIND_HOST:-192.168.40.207}"
export GENIEHIVE_BIND_PORT="${GENIEHIVE_BIND_PORT:-8800}"

exec bash "$ROOT/scripts/run_control_singlebox.sh" "$ROOT/configs/control.singlebox.p40.example.yaml"
