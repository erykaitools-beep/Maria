# Changelog

All notable changes to M.A.R.I.A. are documented here.

Older, session-by-session development notes from before 1.0.0 are archived in
[docs/CHANGELOG.md](docs/CHANGELOG.md) (Polish, kept as written at the time).

## [Unreleased] - 2026-10-22 public source refresh

This is a curated source update, not an export of runtime data or a claim that
optional integrations are configured on a fresh clone. Earlier entries retain
their original dates and measurements.

### Added

- Foreground local speech input through externally configured whisper.cpp,
  bounded PCM WAV uploads, explicit errors, and no silent vendor-service fallback.
- Maria/Mario wake, about four seconds of audio silence to finish an utterance,
  and a three-minute idle-listening window for follow-ups without repeating the
  name. Stop and visibility/lifecycle gates invalidate late callbacks.
- Bounded automatic speech, complete persistent chat, and explicit full readout.
  Restored history and recovered replies do not autoplay.
- Optional Codex chat with scoped tools and runtime selected-model context.
  Failures are surfaced without silently switching the turn to Ollama.
- Durable chat receipts, response correlation, and recovery without automatically
  resending an uncertain turn. SQLite complements existing JSON/JSONL stores.
- Optional Kritaqo project selection, task cards, known-job observation, artifacts,
  shared verification records, and explicit new-work requests. Registered scope
  and current host permissions are required; completed is not independently verified.
- [Voice and projects guide](docs/VOICE_AND_PROJECTS.md) covering configuration,
  evidence semantics, foreground controls, and limitations.

### Changed

- Operator-first settings can explicitly pause background reasoning and warmup
  while retaining conversation, stored memory, and perception. Lean model
  residency and reasoning admission are independent controls.
- README distinguishes local components from optional network services and removes
  undated test-count badges, installation-time promises, and the JSONL-only claim.

### Limitations

- External runtimes, model files, credentials, Kritaqo setup, and project grants
  are not bundled. Android sources/APK remain separate; physical Android voice
  acceptance is pending.
- No locked-phone listening, analysis on ordinary refresh, executor-result
  verification guarantee, or end-to-end voice latency benchmark is claimed.

## [1.1.0] - 2026-08-04

Roughly four months of continuous production running since 1.0.0. Everything
below is in the code and covered by the test suite — these are things that
survived contact with a machine that runs unattended, not plans.

### Added
- **Self-awareness loop** — tick Phase 18 records periodic self-state snapshots
  (capabilities, limitations, available tools); Phase 19 scans for systemic
  failure (model unavailable / stuck dispatcher / action-failure storm) and
  files a repair task that stays blocked behind an operator approval
  (ADR-030, amended by ADR-031: approval *closes* the alert, it does not
  dispatch an autonomous fix).
- **Conductor** — a task queue and dispatcher for delegated build work, one
  dispatcher per project, round-robin so a burn loop on one project cannot
  starve another.
- **Vision change gate** (`agent_core/vision/change_gate.py`) — decides whether
  the scene actually changed before a heavy vision model is allowed to run, and
  says *why* when it refuses.
- **NIM health probe** (`agent_core/llm/nim_health.py`) — checks the remote API
  with a real workload. The catalogue endpoint and `is_available` both report
  healthy for a model that is gone.
- **Workflow engine runs off the tick thread.** A workflow step is an ordinary
  planner action, so it can be a 70B call; the first live run froze the pulse
  for 43s. It now runs in a transient thread with an is-alive guard.

### Changed
- **Embeddings: `nomic-embed-text` → `bge-m3`** (768 → 1024 dimensions).
  Measured on this project's Polish corpus: bge-m3 reached top-5 on 100% of
  probe questions, nomic-embed-text on 43%. Cost: roughly 2.6x slower per text
  on this CPU. Override with `SEMANTIC_EMBED_MODEL`.
- **Vision model: `llava` → `gemma3:4b`.** llava reported a person in frames
  that contained no people.
- Local learning runs on `qwen3:8b` with thinking disabled, and no longer
  re-introduces itself to the model on every call — a cached prefix took the
  prefill from 117s to 0.2s on a hit.

### Fixed
- **Semantic memory was a 5-day window, not an archive.** Eviction sorted purely
  by age and was blind to namespace, so it pushed out beliefs to make room for
  bulk-indexed knowledge. It now protects namespaces whose eviction means the
  cap itself is too small.
- **Belief confidence measured survival, not truth** — a belief that merely
  persisted gained confidence, and a second writer raised it nightly without
  ever checking correctness.
- **The heavy-model mutex was stolen between threads.** `threading.Lock` has no
  owner, so a release from the wrong thread let a second heavy model load while
  the first was still resident. The invariant it was supposed to enforce had
  never actually held.
- **Tests wrote into live project data** — 23 production files, including 40% of
  the fetch-decision audit log over 46 days, which had in turn fed a false
  "fetch success rate 0.56" bulletin. Now zero.
- **The auth test wrote to `meta_data/` on a fresh clone.** Invisible locally
  because the file already existed; it would have failed CI and every first run
  after `git clone`.
- The RSS feed was silent for six days because ten blank lines preceded `<?xml>`;
  the Wikipedia client kept asking every 2s after a `429`; a log throttle carried
  a ticking counter in its own key, so it never throttled anything.

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
