#!/usr/bin/env bash
set -euo pipefail

MODEL_CPU="${MODEL_CPU:-/home/netuser/bin/models/llm/rocket-3b.Q5_K_M.gguf}"
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-/home/netuser/bin/llama.cpp/build/bin/llama-server}"

exec "$LLAMA_SERVER_BIN" -m "$MODEL_CPU" --host 127.0.0.1 --port 18093 -ngl 0 -t 12
