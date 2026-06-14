# M.A.R.I.A. — Funding & Hardware-Partnership Brief

**Meta Analysis Recalibration Intelligence Architecture**
One-page brief · 2026-06-14 · AGPL-3.0 · <https://github.com/erykaitools-beep/Maria>

---

### What it is

M.A.R.I.A. is an **open-source, local-first autonomous agent runtime**: persistent
structured memory, safety-governed actions, a continuous homeostasis loop and
multi-model orchestration. It is not a chatbot and not a concept — it is a daemon
that has run in production on a single mini PC since **2026-02-22**, learning,
planning, reflecting and contacting its operator on its own initiative, fully
offline if needed.

### The problem it addresses

Capable agents today are tied to the cloud: data leaves the machine, behaviour is
opaque, and continuity depends on a vendor. M.A.R.I.A. explores the opposite
point in the design space — an agent that **runs on hardware you own**, keeps a
**persistent, auditable memory**, and treats **safety and autonomy as one design
problem** (every action is classified, rate-limited, logged, and gated to the
level the operator has granted).

### Current state (verifiable)

- **~109k lines** of application Python and **~77k lines** of test code;
  **5,799 tests passing** in a clean checkout, with CI green across
  Python 3.10/3.11/3.12.
- **K1–K13 cognitive contracts** plus a 19-phase, 1 Hz homeostasis loop, observed
  in live logs.
- Sandbox-first learning, append-only action audit trails, operator-gated
  effectors, alert-based (not autonomous) self-repair.
- Full numbers, with sources, in [`CURRENT_PROJECT_STATUS.md`](./CURRENT_PROJECT_STATUS.md).

### Evidence of maturity

Nearly four months of continuous production operation; a public history of
**real incidents with root-cause analysis, fixes and regression tests** (memory leaks,
deadlocks, OOM loops, an OS-level suspend masquerading as a freeze). This is an
operated system, not a demo.

### The constraint: hardware

The production host is an **AMD Ryzen 5 7430U, 32 GB RAM, CPU-only** — no NPU, no
discrete GPU. Concrete consequences:

- The production baseline is limited to 8B-class models; larger models are not
  operationally safe under the current memory, latency and concurrency budgets.
- A **heavy-model mutex** serialises cognition — the planner and the coder cannot
  run at the same time.
- Embeddings, vision and knowledge synthesis all compete for the same CPU.
- The "Maria 2.0" research tracks (symbolic world model + predictive/JEPA layer)
  are **frozen**, partly for lack of headroom to run them next to the 1.0 loop.

This is a specific, measured bottleneck — not a wish for "a faster computer".

### What the project needs

Access to **stronger and more varied compute** to run a defined, reproducible
benchmark and integration program — see
[`HARDWARE_BENCHMARK_PLAN.md`](./HARDWARE_BENCHMARK_PLAN.md). Useful forms, by
distinct role:

- **more RAM / memory bandwidth** → larger local models;
- **unified-memory systems and discrete GPUs** → larger models and concurrent
  multi-model operation;
- **ROCm** → GPU acceleration on AMD hardware;
- **NPU-class platforms** (e.g. Ryzen AI / XDNA) → experiments with smaller
  models, embeddings, classification or perception — *contingent on the
  inference tool stack actually supporting the NPU* (we do not assume Ollama uses
  a Ryzen AI NPU automatically today).

### What stronger hardware would enable

- Evaluation of **20B+ planner-class models** and **concurrent multi-model
  operation** instead of serialised single-model steps.
- Accelerated embeddings and vision workloads, freeing the CPU for reasoning.
- A path to **re-evaluating the frozen 2.0 research tracks** on real data.
- A published reference for "an efficient, safety-governed local agent across CPU
  / GPU / NPU hardware classes" — each claim measured, not assumed.

### What we publish in return

Integration code, configs, benchmark scripts, raw/anonymised results, hardware
profiles, reproduction instructions, and honest failure reports — see
[`PUBLIC_DELIVERABLES.md`](./PUBLIC_DELIVERABLES.md). The operator's private data
and M.A.R.I.A.'s private production memory are never part of any deliverable.

### Why local-first matters

Data sovereignty, auditability and continuity are not features bolted on later —
they are the architecture. A local-first agent that an individual or institution
can own, inspect and keep running is a different category of system from a
cloud-tethered assistant, and a useful reference workload for efficient,
privacy-preserving edge AI.

---

**Read next:** [project status](./CURRENT_PROJECT_STATUS.md) ·
[benchmark plan](./HARDWARE_BENCHMARK_PLAN.md) ·
[public deliverables](./PUBLIC_DELIVERABLES.md) ·
[architecture](../ARCHITECTURE.md) · [security](../SECURITY.md)

*Maintainer: Eryk (@DonCames).*
