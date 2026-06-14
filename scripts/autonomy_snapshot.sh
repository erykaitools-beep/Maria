#!/usr/bin/env bash
# Pre-autonomy 24h test snapshot
# Captures full state of Maria's body + meta_data + memory + process + git
# Secrets (.env) are REDACTED. ~/.claude/ is NOT included (it's Claude's, not Maria's).

set -euo pipefail

TIMESTAMP="${TIMESTAMP:-2026-05-12_pre-autonomy}"
SNAPSHOT_ROOT="${SNAPSHOT_ROOT:-$HOME/maria-snapshots}"
SNAPSHOT_DIR="$SNAPSHOT_ROOT/$TIMESTAMP"
PROJECT_ROOT="${PROJECT_ROOT:-/home/maria/maria}"

i=1
while [[ -d "$SNAPSHOT_DIR" ]]; do
    SNAPSHOT_DIR="$SNAPSHOT_ROOT/${TIMESTAMP}_${i}"
    i=$((i+1))
done

echo "=== Pre-autonomy snapshot ==="
echo "Target: $SNAPSHOT_DIR"
echo ""

mkdir -p "$SNAPSHOT_DIR"/{git,code_checksums,process,configs}

echo "[1/7] Git state..."
cd "$PROJECT_ROOT"
git rev-parse HEAD > "$SNAPSHOT_DIR/git/HEAD"
git log -20 --oneline > "$SNAPSHOT_DIR/git/log_20.txt"
git status --short > "$SNAPSHOT_DIR/git/status.txt"
git diff > "$SNAPSHOT_DIR/git/uncommitted_diff.patch" 2>/dev/null || true
git branch --show-current > "$SNAPSHOT_DIR/git/branch.txt"
TAG_NAME="pre-autonomy-$TIMESTAMP"
git tag -f "$TAG_NAME" 2>&1 | tee "$SNAPSHOT_DIR/git/tag_create.log"
echo "  HEAD: $(cat $SNAPSHOT_DIR/git/HEAD | head -c 12)  Tag: $TAG_NAME"

echo "[2/7] Code checksums..."
find "$PROJECT_ROOT/agent_core" "$PROJECT_ROOT/maria_core" "$PROJECT_ROOT/maria_ui" \
     -type f \( -name "*.py" -o -name "*.html" -o -name "*.js" -o -name "*.css" \) \
     -not -path "*/__pycache__/*" \
     2>/dev/null | sort | xargs sha256sum > "$SNAPSHOT_DIR/code_checksums/files.sha256"
for f in maria.py main.py CLAUDE.md; do
    [[ -f "$PROJECT_ROOT/$f" ]] && sha256sum "$PROJECT_ROOT/$f" >> "$SNAPSHOT_DIR/code_checksums/files.sha256"
done
FCOUNT=$(wc -l < "$SNAPSHOT_DIR/code_checksums/files.sha256")
echo "  $FCOUNT files hashed"

echo "[3/7] meta_data/ copy..."
cp -r "$PROJECT_ROOT/meta_data" "$SNAPSHOT_DIR/meta_data"
META_SIZE=$(du -sh "$SNAPSHOT_DIR/meta_data" | awk '{print $1}')
echo "  size: $META_SIZE"

echo "[4/7] memory/ copy..."
cp -r "$PROJECT_ROOT/memory" "$SNAPSHOT_DIR/memory"
MEM_SIZE=$(du -sh "$SNAPSHOT_DIR/memory" | awk '{print $1}')
echo "  size: $MEM_SIZE"

echo "[5/7] Process state..."
MARIA_PID=$(pgrep -f "python maria.py" | head -1 || true)
if [[ -n "${MARIA_PID:-}" ]]; then
    ps -p "$MARIA_PID" -o pid,ppid,etime,rss,vsz,cmd > "$SNAPSHOT_DIR/process/ps.txt"
    cat "/proc/$MARIA_PID/status" > "$SNAPSHOT_DIR/process/proc_status.txt" 2>/dev/null || true
    THREAD_COUNT=$(ls "/proc/$MARIA_PID/task" 2>/dev/null | wc -l)
    echo "$THREAD_COUNT" > "$SNAPSHOT_DIR/process/threads_count.txt"
    lsof -p "$MARIA_PID" 2>/dev/null > "$SNAPSHOT_DIR/process/open_files.txt" || true
    RSS_MB=$(grep VmRSS "/proc/$MARIA_PID/status" 2>/dev/null | awk '{printf "%.0f", $2/1024}')
    echo "  PID: $MARIA_PID  threads: $THREAD_COUNT  RSS: ${RSS_MB}MB"
else
    echo "  WARN: Maria PID not found"
    echo "MARIA_NOT_RUNNING" > "$SNAPSHOT_DIR/process/WARN.txt"
fi
systemctl show maria 2>/dev/null > "$SNAPSHOT_DIR/process/systemd_show.txt" || true
systemctl is-active maria > "$SNAPSHOT_DIR/process/systemd_state.txt" 2>&1 || true

echo "[6/7] Configs (redacting secrets)..."
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    sed 's/=.*/=<REDACTED>/' "$PROJECT_ROOT/.env" > "$SNAPSHOT_DIR/configs/env.redacted"
fi
ls "$PROJECT_ROOT/agent_core/llm/" 2>/dev/null > "$SNAPSHOT_DIR/configs/llm_modules.txt" || true
ollama list 2>/dev/null > "$SNAPSHOT_DIR/configs/ollama_models.txt" || true
python3 --version > "$SNAPSHOT_DIR/configs/python_version.txt" 2>&1 || true

echo "[7/8] Recovery items (LOCAL ONLY, excluded from tar)..."
mkdir -p "$SNAPSHOT_DIR/RECOVERY"
chmod 700 "$SNAPSHOT_DIR/RECOVERY"

# Full .env with secrets (chmod 600, LOCAL ONLY)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    cp "$PROJECT_ROOT/.env" "$SNAPSHOT_DIR/RECOVERY/env_full"
    chmod 600 "$SNAPSHOT_DIR/RECOVERY/env_full"
    echo "  env_full backed up (chmod 600)"
fi

# Claude project state (MY memory)
# Note: directory name starts with '-' so it needs ./ prefix or tar treats as flag
if [[ -d "$HOME/.claude/projects/-home-maria-maria" ]]; then
    tar -czf "$SNAPSHOT_DIR/RECOVERY/claude_project_state.tar.gz" \
        -C "$HOME/.claude/projects" "./-home-maria-maria"
    CL_SIZE=$(du -sh "$SNAPSHOT_DIR/RECOVERY/claude_project_state.tar.gz" | awk '{print $1}')
    echo "  claude_project_state.tar.gz ($CL_SIZE)"
fi

# market-agent state (separate repo)
MARKET_DIR="$HOME/maria-market-agent"
if [[ -d "$MARKET_DIR" ]]; then
    {
        echo "# Market-agent state at snapshot time"
        echo
        echo "## Branch"
        cd "$MARKET_DIR" && git branch --show-current
        echo
        echo "## Recent commits (top 10)"
        git log --oneline -10
        echo
        echo "## Status"
        git status --short
        echo
        echo "## Uncommitted diff"
        git diff
        cd - > /dev/null
    } > "$SNAPSHOT_DIR/RECOVERY/market_agent_state.txt" 2>/dev/null
    echo "  market_agent_state.txt written"
fi

# Recovery instructions
cat > "$SNAPSHOT_DIR/RECOVERY/RESTORE.md" <<'RESTORE_EOF'
# Recovery procedure

## To restore Maria's body after autonomy test:

```bash
cd /home/maria/maria

# 1. Code rollback (kill running Maria first)
sudo systemctl stop maria
git reset --hard pre-autonomy-2026-05-12

# 2. meta_data + memory restore
rm -rf meta_data memory
cp -r <SNAPSHOT_DIR>/meta_data ./
cp -r <SNAPSHOT_DIR>/memory ./

# 3. .env restore (if needed)
cp <SNAPSHOT_DIR>/RECOVERY/env_full .env

# 4. authority_config.json — already in meta_data/, restored above

# 5. Restart
sudo systemctl start maria
```

## Claude memory restore (if Maria touched it):

```bash
cd ~/.claude/projects
rm -rf -home-maria-maria
tar -xzf <SNAPSHOT_DIR>/RECOVERY/claude_project_state.tar.gz
```

## Market-agent (separate repo, NOT auto-restored):

See `market_agent_state.txt` for last-known state. Manual restore in `~/maria-market-agent/`.
RESTORE_EOF
echo "  RESTORE.md written"

RECOVERY_SIZE=$(du -sh "$SNAPSHOT_DIR/RECOVERY" | awk '{print $1}')
echo "  RECOVERY/ total: $RECOVERY_SIZE"

echo "[8/8] Tar archive (RECOVERY/ excluded — stays local)..."
TAR_PATH="$SNAPSHOT_ROOT/${TIMESTAMP}.tar.gz"
i=1
while [[ -f "$TAR_PATH" ]]; do
    TAR_PATH="$SNAPSHOT_ROOT/${TIMESTAMP}_${i}.tar.gz"
    i=$((i+1))
done
tar -czf "$TAR_PATH" --exclude="RECOVERY" -C "$SNAPSHOT_ROOT" "$(basename "$SNAPSHOT_DIR")"
TAR_SIZE=$(du -sh "$TAR_PATH" | awk '{print $1}')
echo "  Archive: $TAR_PATH ($TAR_SIZE)"

echo ""
echo "=== SNAPSHOT COMPLETE ==="
echo "Directory: $SNAPSHOT_DIR"
echo "Archive:   $TAR_PATH"
echo ""
echo "From your laptop (replace USER/IP):"
echo "  scp maria@<MINI_PC_LAN_IP>:$TAR_PATH ~/maria-backups/"
echo "Or rsync:"
echo "  rsync -avz --progress maria@<MINI_PC_LAN_IP>:$TAR_PATH ~/maria-backups/"
