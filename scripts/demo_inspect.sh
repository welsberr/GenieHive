#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${GENIEHIVE_CONTROL_BASE_URL:-http://127.0.0.1:8800}"
CLIENT_KEY="${GENIEHIVE_CLIENT_KEY:-change-me-client-key}"

curl -sS "$BASE_URL/v1/models" -H "X-Api-Key: $CLIENT_KEY"
printf '\n'
curl -sS "$BASE_URL/v1/cluster/health" -H "X-Api-Key: $CLIENT_KEY"
printf '\n'
curl -sS "$BASE_URL/v1/cluster/hosts" -H "X-Api-Key: $CLIENT_KEY"
printf '\n'
curl -sS "$BASE_URL/v1/cluster/services" -H "X-Api-Key: $CLIENT_KEY"
printf '\n'
curl -sS "$BASE_URL/v1/cluster/roles" -H "X-Api-Key: $CLIENT_KEY"
printf '\n'
curl -sS "$BASE_URL/v1/cluster/routes/resolve?model=mentor" -H "X-Api-Key: $CLIENT_KEY"
printf '\n'
