#!/usr/bin/env bash
set -euo pipefail

check() {
  local name="$1"
  local url="$2"
  if curl -fsS "$url" >/dev/null 2>&1; then
    printf '[ok]   %s -> %s\n' "$name" "$url"
  else
    printf '[fail] %s -> %s\n' "$name" "$url"
  fi
}

echo "GenieHive single-box health check"
echo

check "gpu0 upstream" "http://127.0.0.1:18091/health"
check "gpu1 upstream" "http://127.0.0.1:18092/health"
check "cpu upstream" "http://127.0.0.1:18093/health"
check "control plane" "http://127.0.0.1:8800/health"
check "node agent" "http://127.0.0.1:8891/health"

echo
echo "Authenticated GenieHive checks"
echo

if curl -fsS http://127.0.0.1:8800/v1/cluster/health -H 'X-Api-Key: change-me-client-key' >/dev/null 2>&1; then
  echo "[ok]   cluster health endpoint"
else
  echo "[fail] cluster health endpoint"
fi

if curl -fsS http://127.0.0.1:8800/v1/models -H 'X-Api-Key: change-me-client-key' >/dev/null 2>&1; then
  echo "[ok]   model catalog endpoint"
else
  echo "[fail] model catalog endpoint"
fi
