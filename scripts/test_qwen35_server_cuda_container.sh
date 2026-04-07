#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/ggml-org/llama.cpp:server-cuda}"
MODEL_PATH="${MODEL_PATH:-/home/netuser/bin/models/llm/Qwen3.5-9B-Q5_K_M.gguf}"
GPU_INDEX="${GPU_INDEX:-0}"
CTX_SIZE="${CTX_SIZE:-512}"
PORT="${PORT:-19091}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-90}"

if [[ ! -f "${MODEL_PATH}" ]]; then
  echo "Model not found: ${MODEL_PATH}" >&2
  exit 1
fi

echo "Image: ${IMAGE}"
echo "Model: ${MODEL_PATH}"
echo "GPU: ${GPU_INDEX}"
echo "Port: ${PORT}"
echo "Timeout: ${TIMEOUT_SECONDS}s"
echo
echo "This probe is successful if llama-server loads the model and begins serving."
echo "A timeout exit after successful startup is acceptable for this test."
echo

timeout "${TIMEOUT_SECONDS}"s docker run --rm --gpus all \
  -e CUDA_VISIBLE_DEVICES="${GPU_INDEX}" \
  -v "$(dirname "${MODEL_PATH}"):/models:ro" \
  "${IMAGE}" \
  -m "/models/$(basename "${MODEL_PATH}")" \
  -ngl 999 \
  --ctx-size "${CTX_SIZE}" \
  --host 127.0.0.1 \
  --port "${PORT}"
