#!/usr/bin/env bash
set -euo pipefail

SESSION="${1:-${GENIEHIVE_TMUX_SESSION:-geniehive-p40}}"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux not found"
  exit 127
fi

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session not found: $SESSION"
  exit 1
fi

printf 'tmux session: %s\n' "$SESSION"
printf '%-6s %-8s %-10s %-8s %s\n' "pane" "title" "state" "status" "command"

live_count=0
while IFS=$'\t' read -r pane_id pane_title pane_pid pane_dead pane_dead_status pane_start_command; do
  state="exited"
  status="$pane_dead_status"
  if [[ "$pane_dead" == "0" ]] && kill -0 "$pane_pid" 2>/dev/null; then
    state="running"
    status="-"
    live_count=$((live_count + 1))
  fi

  printf '%-6s %-8s %-10s %-8s %s\n' "$pane_id" "${pane_title:--}" "$state" "${status:--}" "$pane_start_command"
done < <(
  tmux list-panes -t "$SESSION" -F "#{pane_index}\t#{pane_title}\t#{pane_pid}\t#{pane_dead}\t#{pane_dead_status}\t#{pane_start_command}"
)

if [[ "$live_count" -eq 0 ]]; then
  echo
  echo "No pane processes are still running."
  exit 2
fi
