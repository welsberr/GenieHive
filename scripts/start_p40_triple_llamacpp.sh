#!/usr/bin/env bash
set -euo pipefail

# Example launcher pattern for:
# - GPU0 chat model on :18091
# - GPU1 chat model on :18092
# - CPU fallback chat model on :18093
#
# Defaults are based on models already present under /home/netuser/bin/models/llm.
# Override them via env vars if you want different weights.

MODEL_GPU0="${MODEL_GPU0:-/home/netuser/bin/models/llm/Qwen2.5-14B-Instruct-1M-Q5_K_M.gguf}"
MODEL_GPU1="${MODEL_GPU1:-/home/netuser/bin/models/llm/Qwen3.5-9B-Q5_K_M.gguf}"
MODEL_CPU="${MODEL_CPU:-/home/netuser/bin/models/llm/rocket-3b.Q5_K_M.gguf}"
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-/home/netuser/bin/llama.cpp/build/bin/llama-server}"

echo "Start these in separate shells or tmux panes."
echo "Helper scripts are available too:"
echo
echo "bash /home/netuser/bin/geniehive/scripts/p40_triple_gpu0.sh"
echo
echo "bash /home/netuser/bin/geniehive/scripts/p40_triple_gpu1.sh"
echo
echo "bash /home/netuser/bin/geniehive/scripts/p40_triple_cpu.sh"
echo
echo "Or try the combined launcher:"
echo "bash /home/netuser/bin/geniehive/scripts/launch_p40_triple.sh"
echo
echo "Equivalent raw commands:"
echo
echo "CUDA_VISIBLE_DEVICES=0 \"$LLAMA_SERVER_BIN\" -m \"$MODEL_GPU0\" --host 127.0.0.1 --port 18091"
echo
echo "CUDA_VISIBLE_DEVICES=1 \"$LLAMA_SERVER_BIN\" -m \"$MODEL_GPU1\" --host 127.0.0.1 --port 18092"
echo
echo "\"$LLAMA_SERVER_BIN\" -m \"$MODEL_CPU\" --host 127.0.0.1 --port 18093 -ngl 0 -t 12"
