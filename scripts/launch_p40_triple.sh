#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${GENIEHIVE_TMUX_SESSION:-geniehive-p40}"
STATUS_CMD="$ROOT/scripts/tmux_session_status.sh"

GPU0_CMD="$ROOT/scripts/p40_triple_gpu0.sh"
GPU1_CMD="$ROOT/scripts/p40_triple_gpu1.sh"
CPU_CMD="$ROOT/scripts/p40_triple_cpu.sh"

if command -v tmux >/dev/null 2>&1; then
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session already exists: $SESSION"
    echo "Inspect panes with: bash '$STATUS_CMD' '$SESSION'"
    exit 1
  fi

  tmux new-session -d -s "$SESSION" "cd '$ROOT' && bash '$GPU0_CMD'"
  tmux split-window -h -t "$SESSION:0" "cd '$ROOT' && bash '$GPU1_CMD'"
  tmux split-window -v -t "$SESSION:0" "cd '$ROOT' && bash '$CPU_CMD'"
  tmux set-option -t "$SESSION:0" remain-on-exit on >/dev/null
  tmux select-pane -t "$SESSION:0.0" -T gpu0 >/dev/null
  tmux select-pane -t "$SESSION:0.1" -T gpu1 >/dev/null
  tmux select-pane -t "$SESSION:0.2" -T cpu >/dev/null
  tmux select-layout -t "$SESSION" tiled >/dev/null
  echo "Started tmux session: $SESSION"
  echo "Inspect panes with: bash '$STATUS_CMD' '$SESSION'"
  echo "Attach manually only if needed: tmux attach -t $SESSION"
  exit 0
fi

echo "tmux not found. Run these in three shells:"
echo
echo "bash '$GPU0_CMD'"
echo "bash '$GPU1_CMD'"
echo "bash '$CPU_CMD'"
