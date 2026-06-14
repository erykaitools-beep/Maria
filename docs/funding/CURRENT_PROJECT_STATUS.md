# M.A.R.I.A. — Current Project Status

**Meta Analysis Recalibration Intelligence Architecture**
Status report — **2026-06-14**

> This is a factual snapshot intended for funding, hardware-partnership and
> research evaluation. Every number below is either present in the public
> repository or can be reproduced with the command shown. Figures that depend
> on the live production host (uptime, hardware, log volumes) are marked as
> such and cannot be derived from the repository alone.
>
> Source of truth: the public `main` branch of
> <https://github.com/erykaitools-beep/Maria>. Where a figure is older but
> still useful, it is labelled with its date — do not read a dated snapshot as
> current.

---

## 1. One-line summary

M.A.R.I.A. is an open-source, **local-first autonomous agent runtime** with
persistent structured memory, safety-governed actions, a continuous homeostasis
loop and multi-model orchestration. It has run as a production daemon on a
single mini PC since **2026-02-22**.

---

## 2. Codebase and tests

| Metric | Value | How to verify |
|---|---|---|
| Application Python | **~109,000 lines** | `find . -name '*.py' -not -path '*/venv/*' -not -path '*/__pycache__/*' -not -path '*/tests/*' \| xargs wc -l` |
| `agent_core/` application Python | ~95,000 lines | same, scoped to `agent_core/` |
| Test Python | **~77,000 lines** | `find agent_core/tests -name '*.py' \| xargs wc -l` |
| Test files | **184** | `find agent_core/tests -name 'test_*.py' \| wc -l` |
| Automated tests passing | **5,799** | clean checkout, commit `59b1ce2`; latest CI run on `main` green |
| Continuous integration | **green on Python 3.10, 3.11, 3.12** | [`.github/workflows/test.yml`](../../.github/workflows/test.yml) |

The CI workflow runs `pytest agent_core/tests/ -q --tb=short -x --timeout=60`
across a three-version Python matrix. The `-x` flag stops on the first failure,
so a green run means the **entire** collected suite passed on every supported
Python version. The latest run on `main` (for commit `59b1ce2`) is green on all
three versions. All tests are mocked — no network, no live LLM calls — so the
suite is reproducible by anyone who clones the repository.

The README badge reads `tests-5700+` as a conservative public figure; the exact
count reported from the last clean checkout was 5,799.

---

## 3. Architecture maturity

M.A.R.I.A. classifies every subsystem with a five-level vocabulary defined in
[`docs/SYSTEM_STATUS.md`](../SYSTEM_STATUS.md). This is the project's honesty
mechanism — a module is only called "working" once there is evidence for it.

| Level | Meaning | Evidence required |
|---|---|---|
| **LIBRARY** | Code + tests exist | passing tests |
| **WIRED** | Reachable from the daemon / UI / REPL | import graph |
| **OBSERVED** | Seen running in live or archived logs | JSONL log entries |
| **OPERATOR_READY** | Flow + operator documentation complete | docs + flow |
| **RESEARCH_ONLY** | Deliberately frozen / experimental | explicit decision |

**Production core (OBSERVED in live logs):** the K1–K13 cognitive contracts
(perception, sandbox, goals, evaluation, planner, world model, autonomy,
deliberation, meta-cognition, action safety, experiments, self-analysis,
creative), plus the homeostasis tick loop, LLM routing, knowledge critic,
learning bulletin board, self-perception and semantic memory. Full per-contract
detail is in [`docs/CONTRACTS.md`](../CONTRACTS.md) and
[`docs/ARCHITECTURE.md`](../ARCHITECTURE.md).

**Wired but not yet routinely exercised:** capability/intent routing
(flag-gated), the multi-project conductor, vision (LLaVA on demand; camera
hardware pending), the V3 orchestrator, and operator-gated self-repair (verified
via a controlled drill, not yet observed firing in normal operation).

**RESEARCH_ONLY (frozen, not wired into the daemon):** the "Maria 2.0" tracks —
a symbolic property-graph world model and a predictive (JEPA-style) layer. These
are preserved with tests but explicitly deferred until the 1.0 system produces
enough data to train them — and, in practice, until there is hardware headroom
to run them alongside the 1.0 loop. They are **not** presented as working
features.

The homeostasis loop runs **19 phases at 1 Hz**; the loop is described in
[`docs/ARCHITECTURE.md`](../ARCHITECTURE.md).

---

## 4. Deployment

| Aspect | Value | Note |
|---|---|---|
| Process model | single `maria.py` daemon (cognitive loop + Flask/SocketIO Web UI) | one systemd service |
| Service | `maria.service` under systemd, `Restart=on-failure` | [`scripts/maria.service`](../../scripts/maria.service) |
| Running since | **2026-02-22** | production host; systemd journal |
| Continuity | nearly four months of operation with automatic restart on failure; beliefs, logs and knowledge carried across restarts | *live host, not repo-derivable* |
| Memory governance | `MemoryHigh=16G`, `MemoryMax=20G`, `OOMPolicy=kill` | systemd drop-in (added after the 2026-04-17 incident) |

"Continuity" here means continuous **operation of the service**, not zero
downtime. Restarts happen (and are expected); the system is designed to recover
from them. Real incidents and their fixes are documented in the repository — see
§9.

---

## 5. Hardware (production host)

These figures describe the single mini PC the system runs on. They are the basis
for the hardware-research program in
[`HARDWARE_BENCHMARK_PLAN.md`](./HARDWARE_BENCHMARK_PLAN.md).

| Component | Value | How verified (on host) |
|---|---|---|
| CPU | **AMD Ryzen 5 7430U** — 6 cores / 12 threads (Zen 3) | `lscpu` |
| AI acceleration | **none in use** — no on-die NPU; integrated Radeon (Vega) iGPU not used for inference | `lscpu`, `lspci`; 7430U has no XDNA/NPU |
| Inference | **CPU-only** | all local models run as Ollama GGUF on CPU |
| RAM | **32 GB** (≈30 GiB usable) | `free -h` |
| System disk | **1 TB SSD**, ~100 GB provisioned to the live root volume (`/`) | `lsblk` + `df -h /` |
| Archival volume | **6 TB external USB** (5.5 TB usable, `/mnt/storage`) | `lsblk` + `df -h /mnt/storage` |
| OS | Ubuntu 22.04 LTS | — |

This is the single most important fact for hardware partners: **M.A.R.I.A. does
all of its inference on CPU.** There is no NPU and no discrete GPU on the
current host.

---

## 6. Local and external models

Local models run through [Ollama](https://ollama.com); roles and RAM tiers are
defined in code ([`agent_core/llm/model_registry.py`](../../agent_core/llm/model_registry.py))
and documented in [`docs/MODEL_REGISTRY.md`](../MODEL_REGISTRY.md).

| Role | Model | Approx. RAM | Notes |
|---|---|---|---|
| Executor (main) | `llama3.1:8b` (Q4_K_M) | ~5.0 GB | kept warm |
| Planner | `qwen3:8b` (Q4_K_M) | ~5.5 GB | loaded on demand |
| Coder | `qwen2.5-coder:7b` (Q4_K_M) | ~5.0 GB | loaded on demand |
| Embeddings | `nomic-embed-text` (768-dim, 274 MB) | ~0.5 GB | semantic memory |
| Triage | rule-based classifier | 0 GB | no LLM |

A **heavy-model mutex** guarantees the two heaviest models never run
concurrently; the documented safe coexistence ceiling is ~17 GB, and the model
registry marks 24B-class models as "too large for comfortable daily use on
32 GB". In practice the production baseline stays at 8B-class models — larger
models are not operationally safe under the current memory, latency and
concurrency budgets. Latency budgets (CPU): planner 60 s, executor 20 s, coder
30 s, triage <1 s.

**External (optional):** an NVIDIA NIM endpoint is used for heavier learning and
analysis, with automatic fallback to the local stack if it is unavailable. The
routing policy is "external for learning, local for chat" (ADR-008). No external
service is required to run the system. API keys live only in a git-ignored
`.env`; the public repository ships `.env.example` with empty placeholders.

---

## 7. Integrations

| Integration | Status |
|---|---|
| Web UI (Flask + SocketIO) | production |
| Telegram bridge (commands, notifications, approvals) | production |
| Semantic memory (nomic-embed-text, 768-dim) | production |
| Web sources (Wikipedia + RSS fetcher, no API keys) | production |
| OpenClaw effector (subprocess tool invocation, rate-limited) | production, RESTRICTED |
| Vision (LLaVA on demand) | wired; camera hardware pending |
| Smart home (local-only API, ADR-007) | planned; hardware pending |

---

## 8. Safety and autonomy

Safety and autonomy are designed together. Detail is in
[`docs/SECURITY.md`](../SECURITY.md) and the K7/K10 contracts in
[`docs/CONTRACTS.md`](../CONTRACTS.md).

- **Sandbox-first learning.** All learning happens in isolated sessions and only
  reaches production knowledge through a single `promote()` gate, after an exam
  threshold (≥0.6) and zero validation errors.
- **Action classification (K7).** Every action is FREE, GUARDED, RESTRICTED or
  FORBIDDEN; unknown actions default to RESTRICTED (safe-by-default). A separate
  effector authority level defaults to **OBSERVE** (can see tools, never invoke)
  and is capped at BOUNDED in code.
- **Off by default.** Filesystem writes, autonomous outbox writes and
  auto-promotion are disabled by default. Each capability is gated behind an
  explicit flag and/or operator approval. Filesystem writes, when enabled, are
  sandboxed and limited to <1 KB.
- **Action safety (K10).** Every action is recorded to an append-only audit
  trail with before/after state and effect validation.
- **Self-repair is an alert, not an autonomous fix.** The failure monitor
  detects problems and creates a task that an operator must approve; approval
  closes the task rather than dispatching a fix (ADR-031).
- **Rate limiting and escalation** apply to all guarded actions, with a
  human-in-the-loop approval queue for effector tools.

This is defense-in-depth with continuous operator oversight — not "fully
autonomous", and the project does not claim to be.

---

## 9. Observability and operational maturity

The system writes append-only JSONL logs for homeostasis events, episode-
correlated decision traces, autonomy decisions, action-safety audits, critic
reports, evaluations and more. Older records are archived nightly to the 6 TB
data volume (~285 MB of archived logs spanning Feb–Jun 2026 on the host).

The repository preserves a history of **real production incidents with root
cause, fix and regression tests** — a maturity signal, not something to hide.
Examples (all in the commit history):

- A belief-store tombstone leak that grew an append-only log to ~1.1 GB and
  drove tick time from ~2 s to tens of minutes (fix: forced compaction +
  cgroup memory ceiling).
- A recursive-lock deadlock that hung CI for 6+ hours (fix: re-entrant lock +
  pytest timeouts).
- An infinite chunking loop that caused repeated OOM restarts (fix: progress
  guard + hard chunk cap).
- An exam-timeout "storm" (fix: shorter exams + correct skip/failure accounting).
- A mini-PC S3-suspend that masqueraded as a software freeze (fix: disable
  phantom suspend at the OS level) — an environmental bug, found by disciplined
  investigation.

Three of these are summarised in the public
[README](../../README.md#incidents--lessons-learned).

---

## 10. Known limitations and unfinished work

- **Hardware is the binding constraint.** CPU-only + 32 GB RAM caps local models
  at ~8B and forces the heavy-model mutex (no parallel planning + coding). This
  is the central motivation for the
  [hardware benchmark program](./HARDWARE_BENCHMARK_PLAN.md).
- **No published throughput baseline yet.** Tokens/s and time-to-first-token are
  not yet measured and published; establishing that baseline is the first
  deliverable of the benchmark plan. We deliberately do not quote a tok/s number
  we cannot reproduce.
- **Maria 2.0 (symbolic + predictive) is frozen**, pending both data and
  hardware headroom.
- **Vision and smart home** are wired/planned but awaiting hardware.
- **Self-repair** has been drill-verified but not yet observed firing in normal
  operation.

---

## 11. Licensing and access

- **License:** AGPL-3.0.
- **Public repository:** the `main` branch is a curated, sanitised snapshot.
  Active development happens on a private branch; private material (operator
  data, market/funding strategy, secrets) is never published. See ADR-029 in the
  repository.

---

*Numbers in §2 were measured on the public `main` branch (commit `59b1ce2`).
Hardware and runtime figures in §4–§5, §9 come from the production host and are
labelled as such.*
