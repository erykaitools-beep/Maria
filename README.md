# M.A.R.I.A.

**Meta Analysis Recalibration Intelligence Architecture**

A local, autonomous AI agent that lives on your machine. Maria learns from text files, remembers you, plans her own work, and communicates proactively - all running offline with a local LLM.

## What is Maria?

Maria is a personal digital companion, not a chatbot. She runs continuously as a daemon, learning autonomously from files you provide, building knowledge over time, and reaching out when she has something to say. She remembers who you are, what you care about, and adapts to your preferences.

**Core idea:** Clone, run, and she works forever. No cloud dependencies required.

### What she does

- **Learns autonomously** from `.txt` files in `input/` (chunking, LLM extraction, spaced repetition exams)
- **Remembers you** - name, interests, schedule, preferences (UserProfile)
- **Plans her own work** - goal system, planner with ReAct loop, experiment tuning
- **Communicates proactively** - morning summaries, learning milestones, idle check-ins via Telegram
- **Reflects on herself** - self-analysis, creative tensions, meta-cognition
- **Web UI** - chat, status dashboard, knowledge browser, experiment viewer
- **Telegram bot** - two-way communication, approve/reject goals, remote control

### Architecture

Maria has 13 cognitive contracts (K1-K13) forming a complete cognitive core:

| Layer | Modules | Purpose |
|-------|---------|---------|
| Perception | K1 Unified Perception | Event aggregation from all sources |
| Safety | K2 Sandbox, K7 Autonomy, K10 Action Safety | Isolation, classification, audit |
| Planning | K3 Goals, K5 Planner, K8 Deliberation | Goal system, ReAct loop, strategies |
| Knowledge | K6 World Model, K9 Meta-Cognition | Beliefs, confidence, assumptions |
| Growth | K11 Experiments, K12 Self-Analysis, K13 Creative | Parameter tuning, reflection, innovation |
| Learning | Teacher Agent, Spaced Repetition, Exam System | Autonomous learning pipeline |

## Quick Start

### Requirements

- **OS:** Linux (Ubuntu 22.04+ recommended), macOS
- **Python:** 3.10+
- **RAM:** 16 GB+ (8 GB minimum)
- **Disk:** 10 GB free (for LLM model)

### Install

```bash
git clone https://github.com/YOUR_USER/maria.git
cd maria
bash install.sh
```

The install script will:
1. Check system requirements
2. Install [Ollama](https://ollama.com) (local LLM runtime)
3. Pull the `llama3.1:8b` model (~5 GB)
4. Create Python virtual environment
5. Install dependencies
6. Generate `.env` config with random PIN

### Run

```bash
source venv/bin/activate
python maria.py
```

Open `http://localhost:5000` in your browser. Enter the PIN from `.env`.

On first run, Maria will introduce herself and ask your name.

### Give her something to learn

Drop `.txt` files into `input/`. Maria will find them and start learning automatically.

```bash
cp my_notes.txt input/
# Maria picks it up on next planner cycle
```

## Configuration

All config is in `.env` (created by `install.sh`). Nothing is required for basic operation.

| Variable | Default | Description |
|----------|---------|-------------|
| `MARIA_PIN` | (random) | Web UI login PIN |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `TELEGRAM_BOT_TOKEN` | (empty) | Telegram bot token (optional) |
| `TELEGRAM_CHAT_ID` | (empty) | Your Telegram chat ID (optional) |
| `NIM_API_KEY` | (empty) | NVIDIA NIM API key (optional, stronger LLM for analysis) |

### Optional: Telegram Bot

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Get your chat ID via [@userinfobot](https://t.me/userinfobot)
3. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```
4. Restart Maria

Commands: `/status`, `/goals`, `/approve`, `/reject`, `/learn`, `/remind`, `/proactive`, `/help`

### Optional: Run as systemd service

```bash
sudo cp scripts/maria.service /etc/systemd/system/
sudo systemctl enable maria
sudo systemctl start maria
```

## Project Structure

```
maria/
├── maria.py              # Main entry point (daemon + Web UI)
├── main.py               # REPL interface
├── install.sh            # Quick install script
├── agent_core/           # Core modules
│   ├── homeostasis/      # 1Hz tick loop, sensors, mode regulation
│   ├── planner/          # ReAct planning loop (K5)
│   ├── goals/            # Goal system (K3)
│   ├── teacher/          # Autonomous learning agent
│   ├── consciousness/    # Personality, memory, user profile
│   ├── creative/         # Tension detection, meta-goals (K13)
│   ├── proactive/        # Maria initiates contact
│   ├── telegram/         # Telegram bot integration
│   ├── vision/           # Camera/vision (optional hardware)
│   ├── llm/              # LLM routing, model registry
│   └── tests/            # ~3800 tests
├── maria_ui/             # Flask Web UI
│   ├── templates/        # HTML (Jinja2)
│   └── static/           # CSS + JS
├── input/                # Learning materials (.txt files)
├── memory/               # Knowledge index (JSONL)
├── meta_data/            # Runtime state (JSON/JSONL)
└── docs/                 # Architecture, contracts, specs
```

## How Maria Works

### The Tick Loop

Maria runs a 1Hz homeostasis loop with 13 phases:

1. **Sense** - Read system resources, CPU, RAM, temperature
2. **Interpret** - Map sensor data to cognitive state
3. **Validate** - Check constraints and thresholds
4. **Decide** - Mode regulation (ACTIVE/REDUCED/SLEEP/SURVIVAL)
5. **Act** - Execute mode transitions
6. **Health** - Compute overall health score
7. **Perceive** - Aggregate events from all subsystems
8. **Planner** - Run autonomous decision cycle (learn, review, analyze...)
9. **Telegram** - Poll for operator messages
10. **Reminders** - Check due reminders and todos
11. **Proactive** - Check if Maria should initiate contact

### Learning Pipeline

```
input/*.txt → chunk → LLM extract → knowledge_index.jsonl → exam → spaced repetition
```

Maria decides what to learn based on:
- Knowledge gaps (what she doesn't know)
- Spaced repetition schedule (what needs review)
- Topic suggestions (semantic novelty)
- Operator hints (Telegram `/learn <topic>`)

### Proactive Contact

Maria reaches out via Telegram when she has something to say:
- **Morning summary** (7:00-9:00) - health, goals, learning stats
- **Evening recap** (20:00-21:00) - what happened today
- **Goal achieved** - celebration when a goal is completed
- **Learning milestone** - every 10% knowledge coverage
- **Idle check-in** - after 48h without operator contact

Quiet hours (23:00-6:00), daily limit (8 messages), per-reason cooldowns.

## Development

```bash
# Run tests
source venv/bin/activate
python -m pytest agent_core/tests/ -q

# Run specific module tests
python -m pytest agent_core/tests/test_proactive.py -v

# REPL mode (interactive)
python main.py
```

## Tech Stack

- **Runtime:** Python 3.10+, threading (not asyncio)
- **LLM:** Ollama (llama3.1:8b default), optional NVIDIA NIM API
- **Web UI:** Flask + Flask-SocketIO, vanilla JS
- **Storage:** JSONL files (no database)
- **Communication:** Telegram Bot API (optional)
- **Tests:** pytest (~3800 tests, all mocked, zero external deps)

## License

AGPL-3.0 - see [LICENSE](LICENSE)

## Credits

M.A.R.I.A. has been running continuously since February 2026.

Built with help from Claude, ChatGPT, and Grok.
