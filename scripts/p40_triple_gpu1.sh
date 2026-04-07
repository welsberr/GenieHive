#!/usr/bin/env bash
set -euo pipefail

MODEL_GPU1="${MODEL_GPU1:-/home/netuser/bin/models/llm/Qwen3.5-9B-Q5_K_M.gguf}"
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-/home/netuser/bin/llama.cpp/build/bin/llama-server}"
HOST="${GPU1_HOST:-127.0.0.1}"
PORT="${GPU1_PORT:-18092}"
CTX_SIZE="${GPU1_CTX_SIZE:-4096}"
NGL="${GPU1_NGL:-999}"
GPU_INDEX="${GPU1_INDEX:-1}"
USE_CONTAINER="${GPU1_USE_CONTAINER:-0}"
CONTAINER_IMAGE="${GPU1_CONTAINER_IMAGE:-ghcr.io/ggml-org/llama.cpp:server-cuda}"

if [[ "${USE_CONTAINER}" == "1" ]]; then
  exec docker run --rm --gpus all \
    --network host \
    -e CUDA_VISIBLE_DEVICES="${GPU_INDEX}" \
    -v "$(dirname "${MODEL_GPU1}"):/models:ro" \
    "${CONTAINER_IMAGE}" \
    -m "/models/$(basename "${MODEL_GPU1}")" \
    -ngl "${NGL}" \
    --ctx-size "${CTX_SIZE}" \
    --host "${HOST}" \
    --port "${PORT}"
fi

exec env CUDA_VISIBLE_DEVICES="${GPU_INDEX}" "$LLAMA_SERVER_BIN" \
  -m "$MODEL_GPU1" \
  -ngl "${NGL}" \
  --ctx-size "${CTX_SIZE}" \
  --host "${HOST}" \
  --port "${PORT}"
