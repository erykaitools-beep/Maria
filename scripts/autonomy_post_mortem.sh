#!/usr/bin/env bash
# Post-mortem auto-collect after 24h autonomy test.
# Compares pre-autonomy snapshot vs current state, writes markdown report.

set -uo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/home/maria/maria}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-$HOME/maria-snapshots/2026-05-12_pre-autonomy}"
TAG="${TAG:-pre-autonomy-2026-05-12}"
TS=$(date +%Y-%m-%d_%H%M)
REPORT_DIR="$HOME/maria-snapshots/post-mortem-$TS"

mkdir -p "$REPORT_DIR"
cd "$PROJECT_ROOT"

REPORT="$REPORT_DIR/REPORT.md"
START_EPOCH=$(stat -c %Y "$SNAPSHOT_DIR" 2>/dev/null || echo 0)
NOW_EPOCH=$(date +%s)
DURATION_H=$(awk "BEGIN { printf \"%.1f\", ($NOW_EPOCH - $START_EPOCH) / 3600 }")

{
    echo "# Post-mortem: 24h autonomy test"
    echo
    echo "Generated: $(date -Iseconds)"
    echo "Test duration: ${DURATION_H} hours"
    echo "Pre-snapshot: $SNAPSHOT_DIR"
    echo "Pre-tag: $TAG"
    echo

    echo "## Git diff stat vs $TAG"
    echo
    echo '```'
    git diff "$TAG"..HEAD --stat 2>/dev/null || echo "Tag $TAG not found"
    echo '```'
    echo

    echo "## Files Maria changed in agent_core/"
    echo
    echo '```'
    git diff "$TAG"..HEAD --name-only -- agent_core/ maria_core/ maria_ui/ maria.py 2>/dev/null
    echo '```'
    echo

    echo "## Code checksum diff (untracked changes)"
    echo
    find "$PROJECT_ROOT/agent_core" "$PROJECT_ROOT/maria_core" "$PROJECT_ROOT/maria_ui" \
         -type f \( -name "*.py" -o -name "*.html" -o -name "*.js" -o -name "*.css" \) \
         -not -path "*/__pycache__/*" \
         2>/dev/null | sort | xargs sha256sum > "$REPORT_DIR/code_checksums_now.txt"
    echo '```'
    if [[ -f "$SNAPSHOT_DIR/code_checksums/files.sha256" ]]; then
        diff "$SNAPSHOT_DIR/code_checksums/files.sha256" "$REPORT_DIR/code_checksums_now.txt" | head -100
    fi
    echo '```'
    echo

    count_after_epoch() {
        local file="$1"
        if [[ -f "$file" ]]; then
            awk -v t="$START_EPOCH" '
                BEGIN { n=0 }
                {
                    if (match($0, /"(created_at|timestamp)":[[:space:]]*([0-9.]+)/, m)) {
                        if (m[2]+0 > t) n++
                    }
                }
                END { print n }
            ' "$file"
        else
            echo "?"
        fi
    }

    echo "## Activity during test"
    echo
    echo "| Log | New entries |"
    echo "|---|---|"
    echo "| homeostasis_events | $(count_after_epoch meta_data/homeostasis_events.jsonl) |"
    echo "| decision_traces    | $(count_after_epoch meta_data/decision_traces.jsonl) |"
    echo "| action_audit       | $(count_after_epoch meta_data/action_audit.jsonl) |"
    echo "| codex_interactions | $(count_after_epoch meta_data/codex_interactions.jsonl) |"
    echo "| creative_events    | $(count_after_epoch meta_data/creative_events.jsonl) |"
    echo "| critique_reports   | $(count_after_epoch meta_data/critique_reports.jsonl) |"
    echo

    echo "## Bulletin entries tagged autonomy"
    echo
    echo '```'
    grep "autonomy_24h\|autonomy_test" meta_data/cognitive_bulletin.jsonl 2>/dev/null | tail -10
    echo '```'
    echo

    echo "## Critical state intact?"
    echo
    if [[ -f "$PROJECT_ROOT/.env" ]]; then
        ENV_OK=$(diff -q "$PROJECT_ROOT/.env" "$SNAPSHOT_DIR/RECOVERY/env_full" >/dev/null 2>&1 && echo "INTACT" || echo "MODIFIED")
    else
        ENV_OK="MISSING - restore from RECOVERY/env_full"
    fi

    echo "- AUTONOMY_TEST_ACTIVE.flag present: $([[ -f $PROJECT_ROOT/meta_data/AUTONOMY_TEST_ACTIVE.flag ]] && echo YES || echo NO)"
    echo "- Maria PID: $(pgrep -f 'python maria.py' | head -1 || echo 'not running')"
    echo "- .env: $ENV_OK"
    echo "- ~/.claude/projects/-home-maria-maria: $([[ -d $HOME/.claude/projects/-home-maria-maria ]] && echo INTACT || echo MISSING)"
    echo "- market-agent repo: $([[ -d $HOME/maria-market-agent/.git ]] && echo INTACT || echo MISSING)"
    echo

    echo "## Last Telegram messages (if logged)"
    echo
    echo '```'
    tail -20 meta_data/conversation_history.jsonl 2>/dev/null | head -20
    echo '```'

} > "$REPORT"

echo "Post-mortem report: $REPORT"
echo "Open: less $REPORT"
