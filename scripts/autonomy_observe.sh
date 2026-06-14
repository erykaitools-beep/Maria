#!/usr/bin/env bash
# Observability dashboard for 24h autonomy test
# tmux session with 4 panes: 3 log tails + filesystem watcher

set -uo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/home/maria/maria}"
SESSION="${SESSION:-maria-observe}"

if ! command -v tmux >/dev/null; then
    echo "ERROR: tmux not installed (apt install tmux)"
    exit 1
fi
if ! command -v inotifywait >/dev/null; then
    echo "WARN: inotifywait not installed (apt install inotify-tools) — filesystem pane skipped"
    NO_INOTIFY=1
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Session '$SESSION' exists. Attach: tmux attach -t $SESSION"
    exit 0
fi

cd "$PROJECT_ROOT"

tmux new-session -d -s "$SESSION" -n "observe" \
    "echo '=== homeostasis_events ==='; tail -F meta_data/homeostasis_events.jsonl"

tmux split-window -t "$SESSION":0 -h \
    "echo '=== decision_traces ==='; tail -F meta_data/decision_traces.jsonl"

tmux select-pane -t "$SESSION":0.0
tmux split-window -t "$SESSION":0 -v \
    "echo '=== action_audit ==='; tail -F meta_data/action_audit.jsonl"

tmux select-pane -t "$SESSION":0.1
if [[ -z "${NO_INOTIFY:-}" ]]; then
    tmux split-window -t "$SESSION":0 -v \
        "echo '=== fs changes ==='; inotifywait -m -r -e modify,create,delete --format '%T %w%f %e' --timefmt '%H:%M:%S' agent_core/ maria.py maria_core/ 2>&1"
else
    tmux split-window -t "$SESSION":0 -v \
        "echo 'inotifywait not available'; sleep infinity"
fi

tmux select-layout -t "$SESSION":0 tiled

echo "tmux '$SESSION' started — 4 panes:"
echo "  TL: homeostasis_events  TR: decision_traces"
echo "  BL: action_audit         BR: fs changes (inotify)"
echo ""
echo "Attach:  tmux attach -t $SESSION"
echo "Detach:  Ctrl-b d"
echo "Stop:    tmux kill-session -t $SESSION"
