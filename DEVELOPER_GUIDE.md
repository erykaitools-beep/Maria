# M.A.R.I.A. Developer Guide

> Technical reference for developers working on or extending M.A.R.I.A.

## What is M.A.R.I.A.?

**M.A.R.I.A.** (Meta Analysis Recalibration Intelligence Architecture) - a local, autonomous cognitive agent that learns from text files, plans its own work, and communicates proactively.

- **Backend LLM:** Ollama (llama3.1:8b default)
- **Runtime:** Python 3.10+, threading (not asyncio)
- **Mode:** Offline-first, all state in JSONL files

## Entry Points

| Command | Purpose |
|---------|---------|
| `python maria.py` | **Primary** - daemon + Web UI (unified launcher) |
| `python maria.py --daemon` | Daemon only (headless) |
| `python maria.py --ui` | Web UI only |
| `python maria.py --check` | Verify environment |
| `python main.py` | REPL interface (development) |

## Project Structure

```
maria/
├── maria.py              # Unified launcher (daemon + Web UI)
├── main.py               # REPL interface (development)
├── agent_core/           # Core cognitive modules
│   ├── homeostasis/      # 1Hz tick loop, sensors, mode regulation
│   ├── planner/          # K5 ReAct planning loop
│   ├── goals/            # K3 Goal system (lifecycle, audit)
│   ├── teacher/          # Autonomous learning agent
│   ├── consciousness/    # Personality, identity, operator memory
│   ├── creative/         # K13 Tension detection, meta-goals
│   ├── proactive/        # Maria initiates contact
│   ├── telegram/         # Telegram bot integration
│   ├── vision/           # Camera/vision (optional hardware)
│   ├── llm/              # LLM routing, model registry, master prompt
│   ├── perception/       # K1 Unified event aggregation
│   ├── autonomy/         # K7 Authority levels, rate limiting
│   ├── action_safety/    # K10 Audit, effect validation
│   ├── world_model/      # K6 Belief system
│   ├── meta_cognition/   # K9 Confidence, assumptions
│   ├── deliberation/     # K8 Strategic planning
│   ├── experiment/       # K11 Parameter tuning
│   ├── self_analysis/    # K12 Self-reflection
│   ├── semantic/         # Embedding-based similarity search
│   ├── critic/           # Knowledge quality gate
│   ├── reminders/        # Time-triggered notifications
│   ├── orchestrator/     # V3 Task orchestration
│   └── tests/            # 7,100+ tests
├── maria_core/           # Legacy modules (migration in progress)
├── models/               # OllamaBrain LLM interface
├── maria_ui/             # Flask Web UI
├── docs/                 # Specs, contracts, architecture
├── scripts/              # Deployment, backup, systemd
├── input/                # Learning materials (.txt files)
├── memory/               # Knowledge index (runtime, gitignored)
└── meta_data/            # Runtime state (runtime, gitignored)
```

## Cognitive Contracts (K1-K13)

The system is built on 13 formal contracts documented in `docs/CONTRACTS.md`:

| Contract | Module | Purpose |
|----------|--------|---------|
| K1 | `perception/` | Unified event aggregation (PerceptionEvent, PerceptionBuffer) |
| K2 | `sandbox/` | Sandbox isolation for learning (promote as only bridge) |
| K3 | `goals/` | Goal system (4 types, 6 statuses, audit trail) |
| K4 | `evaluation/` | READ-ONLY metrics (5 key metrics, zero LLM) |
| K5 | `planner/` | ReAct loop (OBSERVE->THINK->ACT->EVALUATE) |
| K6 | `world_model/` | Belief system (JSONL, cap 2000, MERGE) |
| K7 | `autonomy/` | Action classification (FREE/GUARDED/RESTRICTED/FORBIDDEN) |
| K8 | `deliberation/` | Multi-step strategies, templates |
| K9 | `meta_cognition/` | Reflection, confidence tracking, assumptions |
| K10 | `action_safety/` | Audit log, effect validation, safe-by-default |
| K11 | `experiment/` | Autonomous parameter tuning, proposal/report pipeline |
| K12 | `self_analysis/` | Self-reflection via external LLM analysis |
| K13 | `creative/` | Tension detection, meta-goals, NIM-powered engines |

## Homeostasis Tick Loop

The core runtime is a 1Hz loop in `agent_core/homeostasis/core.py` with 13 phases:

| Phase | Name | Purpose |
|-------|------|---------|
| 1-5 | SENSE->ACT | Sensor reading, interpretation, mode regulation |
| 7 | HEALTH | Compute health score, alert if <0.7 |
| 8 | PERCEIVE | Aggregate events into PerceptionBuffer |
| 9.5 | MODEL SCHEDULER | LLM model load/unload (RAM management) |
| 9.7 | LOG ARCHIVAL | Daily log rotation |
| 10 | PLANNER | Run ReAct decision cycle (background thread) |
| 11 | TELEGRAM | Poll operator messages |
| 12 | REMINDERS | Check due reminders/todos |
| 13 | PROACTIVE | Check if Maria should initiate contact |

## Key Architectural Decisions (ADRs)

| ADR | Decision | Rationale |
|-----|----------|-----------|
| 001 | JSONL as source of truth | No database dependency, human-readable, append-only |
| 002 | Threading (not asyncio) | Simpler, matches spec requirements |
| 005 | No emoji in code | Terminal compatibility |
| 006 | Introspection is READ-ONLY | Maria never modifies her own code |
| 008 | NIM for learning, Ollama for chat | Hybrid routing with auto-fallback |
| 009 | Tick Aggregator (not Event Bus) | KISS, deterministic ordering |
| 013 | Planner v1 is rule-based | Zero LLM, deterministic, testable |
| 015 | Multi-organ model stack | 5 roles, heavy mutex, RAM tiers |
| 021 | Embeddings replace keyword retrieval | nomic-embed-text via Ollama |

## Model Registry

Maria uses multiple LLM models for different roles:

| Role | Model | Purpose |
|------|-------|---------|
| Executor (MODEL-02) | llama3.1:8b | Core brain, chat, warm by default |
| Planner (MODEL-01) | qwen3:8b | Strategic planning, cold start |
| Coder (MODEL-03) | qwen2.5-coder:7b | Code tasks, cold start |
| Triage (MODEL-04) | Rule-based | Request classification (no LLM) |
| Memory (MODEL-05) | nomic-embed-text | Embeddings, cold start |
| External (MODEL-06) | NIM API | Optional cloud LLM for analysis |

Golden rule: MODEL-02 stays warm, others load on-demand. Heavy model mutex prevents MODEL-01 and MODEL-03 from running simultaneously.

## Code Conventions

- **Docstrings:** English
- **Comments:** Polish or English
- **Type hints:** Preferred
- **No emoji in code** (ADR-005)
- **Frozen dataclasses** for data models where possible
- **JSONL** for all persistent state (MERGE semantics for indexed files)

## Configuration

All runtime config via `.env` (see `.env.example`). Key variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MARIA_OPERATOR_NAME` | `Operator` | Default operator name (used in greetings, prompts) |
| `MARIA_PIN` | (required) | Web UI login PIN |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API |
| `TELEGRAM_BOT_TOKEN` | (empty) | Optional Telegram integration |
| `NVIDIA_NIM_API_KEY` | (empty) | Optional NVIDIA NIM API (stronger analysis) |

## Testing

```bash
source venv/bin/activate
python -m pytest agent_core/tests/ -q           # all tests
python -m pytest agent_core/tests/ -k "planner"  # specific module
```

All tests are mocked - no external dependencies, no LLM calls, no network.

## Common Tasks

### Add a new module

1. Create `agent_core/your_module/` with `__init__.py`
2. Add tests in `agent_core/tests/test_your_module.py`
3. Wire into `agent_core/modules/homeostasis_module.py` if tick-integrated
4. Register in `SharedContext` (`agent_core/registry/shared_context.py`)
5. Add REPL command if interactive (`agent_core/modules/`)
6. Add Telegram command if operator-facing

### Add learning material

Drop `.txt` files into `input/`. Maria auto-discovers and learns from them during planner cycles.

### Add a Telegram command

1. Add a handler in `agent_core/modules/homeostasis_telegram_commands.py` (inside `register_telegram_commands(bridge, ctx)`)
2. Register it with `bridge.register_command("name", handler)`, where `handler(args: str) -> str`
3. Add it to the `/help` output

## Experimental Features

These modules work but depend on optional hardware or external services:

| Module | Dependency | Status |
|--------|------------|--------|
| `vision/` | USB camera | Functional, requires hardware |
| `effector/` | OpenClaw | Functional, requires separate service |
| `telegram/` | Telegram Bot API | Functional, requires bot token |
| `llm/nim_client.py` | NVIDIA NIM API | Functional, requires API key |

Specs without implementation (planned):
- `docs/SMART_HOME_SPEC.md` - IoT integration
- `docs/VOICE_SPEC.md` - Speech I/O
