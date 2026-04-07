#!/usr/bin/env bash
set -euo pipefail

MODEL_GPU0="${MODEL_GPU0:-/home/netuser/bin/models/llm/Qwen2.5-14B-Instruct-1M-Q5_K_M.gguf}"
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-/home/netuser/bin/llama.cpp/build/bin/llama-server}"

exec env CUDA_VISIBLE_DEVICES=0 "$LLAMA_SERVER_BIN" -m "$MODEL_GPU0" --host 127.0.0.1 --port 18091
