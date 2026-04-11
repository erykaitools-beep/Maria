# Changelog

All notable changes to M.A.R.I.A. are documented here.

## [1.0.0] - 2026-04-11

First public release. M.A.R.I.A. has been running in production since February 2026.

### Core Architecture
- **13 Cognitive Contracts (K1-K13)** - complete cognitive core
  - K1 Unified Perception, K2 Sandbox, K3 Goals, K4 Evaluation
  - K5 Planner (ReAct loop), K6 World Model, K7 Autonomy Policy
  - K8 Deliberation, K9 Meta-Cognition, K10 Action Safety
  - K11 Experiment System, K12 Self-Analysis, K13 Creative Module
- **Homeostasis** - 1Hz tick loop with 13 phases, mode regulation (ACTIVE/REDUCED/SLEEP/SURVIVAL)
- **Semantic Memory** - nomic-embed-text embeddings, vector similarity search
- **Belief Store v2** - evidence tracking, confidence decay, smart pruning

### Learning System
- **Autonomous learning** from .txt files in input/
- **Spaced repetition** exam system
- **Knowledge auditor** + gap planner
- **Expert bridge** - targeted LLM queries based on knowledge gaps
- **Multi-source validation** (cross-validation with confidence scoring)
- **Knowledge critic** (7-dimension analysis)

### Communication
- **Proactive Contact** - Maria initiates Telegram messages (morning summary, milestones, idle check-in)
- **Telegram Bot (ClawBot)** - 25+ commands, file upload, PDF export
- **Reminders & Todos** - time-triggered notifications with PL/EN parser
- **Web UI** - chat, status dashboard, experiments, traces, profile, architecture map

### Intelligence
- **Creative Module** - tension detection, meta-goals, NIM-powered reframing
- **Self-Analysis** - K12 cognitive reports via external LLM cascade
- **Decision Tracing** - episode-based correlation IDs across cognitive episodes
- **Experiment System** - autonomous parameter tuning with proposals and reports

### Infrastructure
- **Unified Launcher** (maria.py) - single entry point for daemon + Web UI
- **Model Registry v2** - multi-organ LLM stack (5 roles, heavy mutex, RAM tiers)
- **Effector Safety Envelope** - 5-level authority, approval queue, anti-cascade
- **Storage Manager** - log archival, daily summaries
- **Vision System** - camera sensor, preprocessing, scene analysis (optional hardware)

### V3 Orchestrator
- **15 modules** across 5 phases (Foundation, Task Pipeline, Practical Intelligence, Execution Bridge, Product Hardening)
- **Onboarding Flow** - first-run guidance with operator name collection
- **User Profile** - persistent operator memory (interests, schedule, facts)

### Developer Experience
- **~3800 tests** (all mocked, zero external dependencies)
- **install.sh** - one-command setup
- **Zero-config operation** - works with just Ollama, everything else optional
- **AGPL-3.0 license**
