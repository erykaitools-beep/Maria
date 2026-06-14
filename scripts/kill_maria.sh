#!/usr/bin/env bash
# Kill switch for 24h autonomy test
# Three escalation levels: soft -> hard -> systemd

set -uo pipefail

LEVEL="${1:-soft}"

MARIA_PID=$(pgrep -f "python maria.py" | head -1 || true)

if [[ -z "$MARIA_PID" ]]; then
    echo "Maria not running."
    exit 0
fi

echo "Maria PID: $MARIA_PID  uptime: $(ps -p $MARIA_PID -o etime= | tr -d ' ')"
echo "Kill level: $LEVEL"

case "$LEVEL" in
    soft)
        echo "Sending SIGTERM (Maria saves state, then exits)..."
        kill -TERM "$MARIA_PID"
        echo "Waiting up to 30s for graceful shutdown..."
        for i in {1..30}; do
            if ! kill -0 "$MARIA_PID" 2>/dev/null; then
                echo "Maria stopped gracefully after ${i}s."
                # Check if systemd auto-restarted (Restart=on-failure only triggers on non-zero exit)
                sleep 2
                NEW_PID=$(pgrep -f "python maria.py" | head -1 || true)
                if [[ -n "$NEW_PID" ]]; then
                    echo "WARN: New Maria PID $NEW_PID started (systemd restart?). Use: $0 systemd"
                fi
                exit 0
            fi
            sleep 1
        done
        echo "Maria still alive after 30s. Try: $0 hard"
        exit 1
        ;;
    hard)
        echo "Sending SIGKILL (instant, no save)..."
        kill -KILL "$MARIA_PID"
        sleep 1
        if kill -0 "$MARIA_PID" 2>/dev/null; then
            echo "ERROR: Maria still alive after SIGKILL. Try: $0 systemd (needs sudo)"
            exit 1
        fi
        echo "Maria killed."
        sleep 3
        NEW_PID=$(pgrep -f "python maria.py" | head -1 || true)
        if [[ -n "$NEW_PID" ]]; then
            echo "WARN: systemd auto-restarted Maria (new PID: $NEW_PID). Use: $0 systemd"
            exit 1
        fi
        echo "Confirmed stopped."
        ;;
    systemd)
        echo "Stopping via systemctl (requires sudo as deployadmin)..."
        sudo systemctl stop maria
        sleep 2
        if pgrep -f "python maria.py" > /dev/null; then
            echo "ERROR: Maria still running after systemctl stop. Check: sudo systemctl status maria"
            exit 1
        fi
        echo "Maria stopped by systemd. Auto-restart blocked until manual start."
        ;;
    *)
        echo "Usage: $0 [soft|hard|systemd]"
        echo "  soft    SIGTERM, graceful (saves state) [default]"
        echo "  hard    SIGKILL, instant (no save)"
        echo "  systemd systemctl stop (needs sudo deployadmin, blocks auto-restart)"
        exit 2
        ;;
esac
