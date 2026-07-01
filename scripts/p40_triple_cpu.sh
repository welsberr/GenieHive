#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-/opt/models/llm}"
MODEL_CPU="${MODEL_CPU:-${MODEL_DIR}/rocket-3b.Q5_K_M.gguf}"
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-llama-server}"

exec "$LLAMA_SERVER_BIN" -m "$MODEL_CPU" --host 127.0.0.1 --port 18093 -ngl 0 -t 12
