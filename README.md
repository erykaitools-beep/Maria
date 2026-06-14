<p align="center">
  <h1 align="center">M.A.R.I.A.</h1>
  <p align="center"><b>Meta Analysis Recalibration Intelligence Architecture</b></p>
  <p align="center">
    A local, autonomous AI agent that lives on your machine.<br>
    She learns, plans, reflects, and communicates — all offline.
  </p>
  <p align="center">
    <a href="https://github.com/erykaitools-beep/Maria/actions/workflows/test.yml"><img src="https://github.com/erykaitools-beep/Maria/actions/workflows/test.yml/badge.svg" alt="Tests"></a>
    <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
    <img src="https://img.shields.io/badge/tests-5700%2B-brightgreen" alt="5700+ tests">
    <img src="https://img.shields.io/badge/license-AGPL--3.0-purple" alt="License">
    <img src="https://img.shields.io/badge/LLM-Ollama%20(local)-orange" alt="Ollama">
  </p>
</p>

---

## Screenshots

<p align="center">
  <img src="https://github.com/user-attachments/assets/bfca558d-33df-4abc-ba71-1d373ed1022e" width="700" alt="Status Dashboard">
  <br><em>Status Dashboard — system health, mode, goals, knowledge stats</em>
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/f3840380-0830-4624-8aae-d97175fce977" width="700" alt="Status Dashboard (extended)">
  <br><em>Status Dashboard — planner, experiments, model registry</em>
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/75afda18-9c92-4488-a108-a13687d18ecc" width="700" alt="Decision Traces">
  <br><em>Decision Traces — episode-based cognitive traceability</em>
</p>

---

## What is Maria?

Maria is a **personal digital companion**, not a chatbot. She runs continuously as a daemon on your machine, learning autonomously from files you provide, building knowledge over time, and reaching out when she has something to say.

She remembers who you are, what you care about, and adapts to your preferences.

**Core idea:** Clone, run, and she works forever. No cloud dependencies required.

### Key Features

| Feature | Description |
|---------|-------------|
| **Autonomous Learning** | Drop `.txt` files in `input/` — Maria chunks, extracts knowledge, runs spaced repetition exams |
| **Cognitive Core** | 13 architectural contracts (K1-K13): perception, goals, planning, world model, meta-cognition |
| **Self-Reflection** | Self-analysis, creative tension detection, experiment system for parameter tuning |
| **Proactive Communication** | Morning summaries, learning milestones, idle check-ins via Telegram |
| **Operator Memory** | Remembers your name, interests, schedule, preferences across sessions |
| **Web UI** | Chat, status dashboard, knowledge browser, experiment viewer |
| **Telegram Bot** | Two-way communication, approve/reject goals, remote control |
| **Vision** | Optional camera integration for scene understanding (LLaVA) |

### Architecture Overview

```
                    ┌─────────────────────────────────────┐
                    │          Homeostasis Loop (1Hz)       │
                    │  sense → interpret → validate → act   │
                    └──────────────┬──────────────────────┘
                                   │
        ┌──────────┬───────────┬───┴────┬──────────┬──────────┐
        │          │           │        │          │          │
   ┌────┴────┐ ┌───┴───┐ ┌────┴───┐ ┌──┴──┐ ┌────┴────┐ ┌───┴────┐
   │ Percept.│ │ Goals │ │Planner │ │World│ │Creative │ │Teacher │
   │  (K1)   │ │ (K3)  │ │ (K5)   │ │Model│ │ (K13)   │ │ Agent  │
   └─────────┘ └───────┘ └────────┘ │(K6) │ └─────────┘ └────────┘
                                     └─────┘
        ┌──────────┬───────────┬───────────┬──────────┐
        │          │           │           │          │
   ┌────┴────┐ ┌───┴───┐ ┌────┴────┐ ┌────┴───┐ ┌───┴────┐
   │Autonomy │ │Safety │ │  Meta-  │ │ Self-  │ │Experim.│
   │  (K7)   │ │(K10)  │ │Cognit.  │ │Analysis│ │ (K11)  │
   └─────────┘ └───────┘ │  (K9)   │ │ (K12)  │ └────────┘
                          └─────────┘ └────────┘

   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
   │Telegram │ │ Web UI  │ │ Vision  │ │Semantic │
   │  Bot    │ │ (Flask) │ │(camera) │ │ Memory  │
   └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

### Cognitive Contracts (K1-K13)

| Layer | Contracts | Purpose |
|-------|-----------|---------|
| **Perception** | K1 Unified Perception | Event aggregation from all sources |
| **Boundary** | K2 Sandbox | Isolated learning, promote-to-production gate |
| **Planning** | K3 Goals, K5 Planner, K8 Deliberation | Goal system, ReAct loop, multi-step strategies |
| **Knowledge** | K6 World Model, K9 Meta-Cognition | Belief system, confidence tracking, assumptions |
| **Safety** | K7 Autonomy, K10 Action Safety | Action classification, rate limiting, audit log |
| **Growth** | K11 Experiments, K12 Self-Analysis, K13 Creative | Parameter tuning, reflection, tension detection |

## Quick Start

### Requirements

- **OS:** Linux (Ubuntu 22.04+), macOS
- **Python:** 3.10+
- **RAM:** 16 GB+ (8 GB minimum)
- **Disk:** 10 GB free (for LLM model)

### Install

```bash
git clone https://github.com/erykaitools-beep/Maria.git
cd Maria
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
# Maria picks it up on the next planner cycle (~60s)
```

## Configuration

All config is in `.env` (created by `install.sh`). Nothing is required for basic operation.

| Variable | Default | Description |
|----------|---------|-------------|
| `MARIA_PIN` | *(random)* | Web UI login PIN |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `TELEGRAM_BOT_TOKEN` | *(empty)* | Telegram bot token (optional) |
| `TELEGRAM_CHAT_ID` | *(empty)* | Your Telegram chat ID (optional) |
| `NIM_API_KEY` | *(empty)* | NVIDIA NIM API key (optional, for stronger analysis) |

### Optional: Telegram Bot

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Get your chat ID via [@userinfobot](https://t.me/userinfobot)
3. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```
4. Restart Maria

Commands: `/status`, `/goals`, `/approve`, `/reject`, `/learn`, `/remind`, `/help`

### Optional: Systemd service

```bash
sudo cp scripts/maria.service /etc/systemd/system/
sudo systemctl enable maria
sudo systemctl start maria
```

## How Maria Works

### The Tick Loop

Maria runs a 1Hz homeostasis loop:

```
SENSE → INTERPRET → VALIDATE → DECIDE → ACT → HEALTH → PERCEIVE → PLANNER → TELEGRAM → REMINDERS → PROACTIVE
```

The **mode regulator** manages four states: `ACTIVE` → `REDUCED` → `SLEEP` → `SURVIVAL`, based on system resources and health.

### Learning Pipeline

```
input/*.txt → chunk → LLM extract → knowledge_index.jsonl → exam → spaced repetition
```

Maria decides **what** to learn based on knowledge gaps, spaced repetition schedule, semantic novelty, and operator hints.

### Proactive Contact

Maria reaches out via Telegram when she has something meaningful to say:
- **Morning summary** (7-9am) — health, goals, learning stats
- **Evening recap** (8-9pm) — what happened today
- **Goal achieved** — celebration when a goal is completed
- **Learning milestone** — every 10% knowledge coverage
- **Idle check-in** — after 48h without operator contact

Quiet hours (23:00-6:00), daily limits, per-reason cooldowns.

## Running in Production

Maria has been running continuously on a single mini PC since 2026-02-22. This isn't a demo — it's the same process, same logs, same beliefs carried across every tick.

| | |
|---|---|
| **Hardware** | AMD Ryzen 5 7430U · 32 GB RAM · 1 TB SSD · Ubuntu 22.04 |
| **Deployment** | `maria.service` under systemd, auto-restart on failure |
| **Resource ceiling** | `MemoryHigh=16G`, `MemoryMax=20G`, `OOMPolicy=kill` (systemd drop-in, hard-capped after an incident — see below) |
| **Archival storage** | 6 TB ext4 disk for rotated logs and daily summaries |

Live counters as of 2026-04-18 (~8 weeks in):

| Signal | Count |
|---|---|
| Knowledge entries | 286 |
| Beliefs (post-compaction) | 1,961 |
| Semantic vectors (nomic-embed-text, 768-dim) | 10,030 |
| Decision traces (episode-correlated) | 4,589 |
| Test suite | 4,490 passing · 1 xfail · 104s runtime |

Observed modes: `ACTIVE` most of the day, `REDUCED` briefly during LLM inference spikes, `SLEEP` during low-activity hours, `SURVIVAL` never triggered in production.

## Incidents & Lessons Learned

Real issues from production, and what we did about them. Every fix below is in the commit history.

### 2026-04-17 — The 1.5M-line JSONL

**Symptom.** Nine-hour freeze. Swap exhausted. The watchdog kept restarting the process; every restart hung in the same place.

**Cause.** `beliefs.jsonl` is an append-only log. Confidence decay, revisions, and dedup had accumulated **~1.5 million tombstone rows (1.1 GB)**. On startup, `BeliefStore` replayed the whole file into memory. Compaction had a cadence rule that required a "quiet period" to kick in — but the system was never quiet, because the log was what made it un-quiet. A deadlock in slow motion.

**Fix.**
- Forced compaction on startup when the file exceeds a size threshold
- systemd drop-in: `MemoryHigh=16G`, `MemoryMax=20G`, `OOMPolicy=kill` — a hard ceiling so a runaway replay gets killed fast instead of thrashing swap for hours
- Audit cron every 4 days that surfaces anomalies before they freeze the loop

**Lesson.** An append-only log needs a compaction trigger that **doesn't depend on the system being healthy**. If the hang caused by the log is what prevents compaction, you have a deadlock.

### 2026-04-16 — Confidence feedback loop

**Symptom.** `ConfidenceTracker` reported 0.01 on every action type. Maria effectively stopped trying — every `LEARN` was gated out by low confidence.

**Cause.** The scoring function used `outcome_match` directly: `mismatch → 0.0`. That conflated two distinct signals — *"did we predict right?"* and *"did the action succeed?"*. Learn actions on small/empty topics produced `outcome_match=mismatch` with `actual_success=True` (the action ran fine; we just underestimated). Each such reflection pushed confidence down. Once floored, every subsequent learn was also a "mismatch" relative to the (now-zero) expectation. Floor sealed shut.

**Fix.** Separated the signals. `actual_success` is the primary score. `outcome_match='partial'` halves it. Pending reflections fall back to neutral. (Commit `e1f753d`.)

**Lesson.** When a signal drives a control loop, make sure it measures the thing the loop is reacting to — not a proxy. Proxies are fine until they drift, and control loops amplify drift.

### 2026-04-18 — BeliefBuilder cold-build hang

**Symptom.** After a month-long silent bug in `BeliefBuilder` was fixed, a rebuild unlocked ~7,766 queued topic concepts. The first cold rebuild hung for several minutes and pegged a core.

**Cause.** `BeliefStore.add()` enforces a 2,000-entry cap per call. On a cold rebuild of ~22 k concepts, cap enforcement ran 22 k times — each pass scanning the store.

**Fix.** Wrapped the three build passes in `store.bulk_mode()` — cap enforcement runs once at the end instead of per-add. Multi-minute hang became seconds. (Commit `3a3925e`.)

**Lesson.** Per-item invariants are cheap per call and pathological in bulk. If a path can be called with a large batch, offer a bulk mode that defers the invariant.

## Project Structure

```
maria/
├── maria.py              # Entry point (daemon + Web UI)
├── main.py               # REPL interface (interactive)
├── install.sh            # Quick install script
├── agent_core/           # Core cognitive modules
│   ├── homeostasis/      # 1Hz tick loop, sensors, mode regulation
│   ├── planner/          # ReAct planning loop (K5)
│   ├── goals/            # Goal system with audit trail (K3)
│   ├── teacher/          # Autonomous learning agent
│   ├── consciousness/    # Personality, dreams, user profile
│   ├── creative/         # Tension detection, meta-goals (K13)
│   ├── world_model/      # Belief system (K6)
│   ├── meta_cognition/   # Reflection, confidence (K9)
│   ├── autonomy/         # Action classification, rate limits (K7)
│   ├── action_safety/    # Audit log, effect validation (K10)
│   ├── experiment/       # Parameter tuning system (K11)
│   ├── self_analysis/    # Self-reflection via LLM (K12)
│   ├── semantic/         # Embedding-based memory (nomic-embed-text)
│   ├── telegram/         # Telegram bot integration
│   ├── vision/           # Camera/vision (optional)
│   ├── llm/              # LLM routing, model registry
│   ├── reminders/        # Time-triggered notifications
│   ├── web_source/       # Wikipedia + RSS content fetcher
│   └── tests/            # 5700+ tests
├── maria_ui/             # Flask Web UI
│   ├── templates/        # HTML (Jinja2)
│   └── static/           # CSS + JS
├── docs/                 # Architecture, contracts, specs
└── scripts/              # Install, backup, systemd
```

## Development

```bash
# Run all tests
source venv/bin/activate
python -m pytest agent_core/tests/ -q

# Run specific module tests
python -m pytest agent_core/tests/test_planner.py -v

# Interactive REPL
python main.py
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Runtime** | Python 3.10+, threading |
| **LLM** | Ollama (llama3.1:8b), optional NVIDIA NIM API |
| **Web UI** | Flask + Flask-SocketIO, vanilla JS |
| **Storage** | JSONL files (no database) |
| **Embeddings** | nomic-embed-text (768-dim, via Ollama) |
| **Communication** | Telegram Bot API |
| **Tests** | pytest, all mocked, zero external deps |

## License

[AGPL-3.0](LICENSE) — Copyright (C) 2025-2026 Eryk (@DonCames)

## Credits

M.A.R.I.A. has been running continuously since **February 22, 2026**.

Built by Eryk with help from Claude, ChatGPT, and Grok.
