#!/usr/bin/env bash
# =============================================================================
# M.A.R.I.A. - Quick Install Script
# =============================================================================
# Usage:  bash install.sh
#
# Requirements:
#   - Linux (Ubuntu 22.04+ / Debian 12+ recommended)
#   - Python 3.10+
#   - 16 GB+ RAM (8 GB minimum, slower)
#   - 10 GB free disk space
#
# What this script does:
#   1. Checks system requirements
#   2. Installs Ollama (if not present)
#   3. Pulls llama3.1:8b + nomic-embed-text models
#   4. Creates Python virtual environment
#   5. Installs dependencies
#   6. Creates .env from template
#   7. Runs a quick test
#   8. Shows next steps
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

MARIA_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}  M.A.R.I.A. - Installation${NC}"
echo -e "${BLUE}  Meta Analysis Recalibration Intelligence Architecture${NC}"
echo -e "${BLUE}=================================================${NC}"
echo ""

# ── Step 1: Check system requirements ──

echo -e "${YELLOW}[1/7] Checking system requirements...${NC}"

# Python
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
    PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
    if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
        echo -e "${RED}[ERROR] Python 3.10+ required (found $PY_VERSION)${NC}"
        echo "Install: sudo apt install python3.10 python3.10-venv"
        exit 1
    fi
    echo -e "  Python: ${GREEN}$PY_VERSION${NC}"
else
    echo -e "${RED}[ERROR] Python3 not found${NC}"
    echo "Install: sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

# python3-venv
if ! python3 -m venv --help &>/dev/null; then
    echo -e "${RED}[ERROR] python3-venv not installed${NC}"
    echo "Install: sudo apt install python3-venv"
    exit 1
fi

# RAM check
TOTAL_RAM_MB=$(free -m | awk '/Mem:/{print $2}')
if [ "$TOTAL_RAM_MB" -lt 8000 ]; then
    echo -e "${RED}[WARNING] Only ${TOTAL_RAM_MB}MB RAM. Maria needs 16GB+ (8GB minimum).${NC}"
fi
echo -e "  RAM: ${GREEN}${TOTAL_RAM_MB}MB${NC}"

# Disk check
FREE_DISK_MB=$(df -m "$MARIA_DIR" | awk 'NR==2{print $4}')
if [ "$FREE_DISK_MB" -lt 10000 ]; then
    echo -e "${YELLOW}[WARNING] Only ${FREE_DISK_MB}MB free disk. Maria + model need ~10GB.${NC}"
fi
echo -e "  Disk free: ${GREEN}${FREE_DISK_MB}MB${NC}"

echo ""

# ── Step 2: Install Ollama ──

echo -e "${YELLOW}[2/7] Checking Ollama...${NC}"

if command -v ollama &>/dev/null; then
    OLLAMA_VERSION=$(ollama --version 2>/dev/null || echo "unknown")
    echo -e "  Ollama: ${GREEN}already installed ($OLLAMA_VERSION)${NC}"
else
    echo "  Ollama not found. Installing..."
    OLLAMA_INSTALLER=$(mktemp)
    curl -fsSL https://ollama.com/install.sh -o "$OLLAMA_INSTALLER"
    echo "  Downloaded installer to $OLLAMA_INSTALLER"
    sh "$OLLAMA_INSTALLER"
    rm -f "$OLLAMA_INSTALLER"
    echo -e "  Ollama: ${GREEN}installed${NC}"
fi

# Start Ollama if not running
if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
    echo "  Starting Ollama service..."
    if command -v systemctl &>/dev/null; then
        sudo systemctl start ollama 2>/dev/null || ollama serve &>/dev/null &
    else
        ollama serve &>/dev/null &
    fi
    sleep 3
fi

echo ""

# ── Step 3: Pull model ──

echo -e "${YELLOW}[3/7] Pulling models (llama3.1:8b ~5GB + nomic-embed-text ~275MB)...${NC}"

if ollama list 2>/dev/null | grep -q "llama3.1:8b"; then
    echo -e "  llama3.1:8b: ${GREEN}already downloaded${NC}"
else
    echo "  Downloading llama3.1:8b (this may take a while)..."
    ollama pull llama3.1:8b
    echo -e "  llama3.1:8b: ${GREEN}downloaded${NC}"
fi

# Embedding model - powers semantic memory (without it, embedding calls 404)
if ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
    echo -e "  nomic-embed-text: ${GREEN}already downloaded${NC}"
else
    echo "  Downloading nomic-embed-text (embeddings, ~275MB)..."
    ollama pull nomic-embed-text
    echo -e "  nomic-embed-text: ${GREEN}downloaded${NC}"
fi

echo ""

# ── Step 4: Python virtual environment ──

echo -e "${YELLOW}[4/7] Setting up Python environment...${NC}"

cd "$MARIA_DIR"

if [ -d "venv" ]; then
    echo -e "  Virtual environment: ${GREEN}already exists${NC}"
else
    python3 -m venv venv
    echo -e "  Virtual environment: ${GREEN}created${NC}"
fi

source venv/bin/activate

echo ""

# ── Step 5: Install dependencies ──

echo -e "${YELLOW}[5/7] Installing Python dependencies...${NC}"

pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "  Dependencies: ${GREEN}installed${NC}"

echo ""

# ── Step 6: Configuration ──

echo -e "${YELLOW}[6/7] Configuration...${NC}"

if [ -f ".env" ]; then
    echo -e "  .env: ${GREEN}already exists (keeping your config)${NC}"
else
    cp .env.example .env
    # Generate a random PIN
    RANDOM_PIN=$(python3 -c "import secrets; print(secrets.token_hex(4))")
    sed -i "s/MARIA_PIN=change-me-123/MARIA_PIN=$RANDOM_PIN/" .env
    echo -e "  .env: ${GREEN}created from template${NC}"
    echo -e "  Web UI PIN: ${YELLOW}$RANDOM_PIN${NC} (change in .env if needed)"
fi

# Create required directories
mkdir -p input memory meta_data docs/incoming logs
echo -e "  Directories: ${GREEN}OK${NC}"

echo ""

# ── Step 7: Quick test ──

echo -e "${YELLOW}[7/7] Quick verification...${NC}"

# Test Ollama connectivity
if curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; json.load(sys.stdin)" &>/dev/null; then
    echo -e "  Ollama API: ${GREEN}OK${NC}"
else
    echo -e "  Ollama API: ${YELLOW}not responding (start with: ollama serve)${NC}"
fi

# Test Python imports
if python3 -c "from agent_core.proactive import ProactiveScheduler; print('OK')" 2>/dev/null | grep -q OK; then
    echo -e "  Maria imports: ${GREEN}OK${NC}"
else
    echo -e "  Maria imports: ${YELLOW}some modules may be missing${NC}"
fi

echo ""
echo -e "${GREEN}=================================================${NC}"
echo -e "${GREEN}  Installation complete!${NC}"
echo -e "${GREEN}=================================================${NC}"
echo ""
echo "  Start Maria:"
echo -e "    ${BLUE}cd $MARIA_DIR${NC}"
echo -e "    ${BLUE}source venv/bin/activate${NC}"
echo -e "    ${BLUE}python maria.py${NC}"
echo ""
echo "  Then open: http://localhost:5000"
echo "  PIN: check your .env file"
echo ""
echo "  Optional:"
echo "    - Edit .env for Telegram bot, NIM API, etc."
echo "    - Add .txt files to input/ for Maria to learn"
echo "    - Run tests: python -m pytest agent_core/tests/ -q"
echo ""
echo "  Documentation: docs/ARCHITECTURE.md, docs/ROADMAP.md"
echo ""
