# M.A.R.I.A. — Public Deliverables

**Meta Analysis Recalibration Intelligence Architecture**
2026-06-14

> This document states **what M.A.R.I.A. will publish openly** in exchange for
> funding or hardware support. Everything here is intended to be public,
> reproducible and useful beyond this project. It is paired with the
> [hardware benchmark plan](./HARDWARE_BENCHMARK_PLAN.md), which defines how the
> results are produced.

---

## 1. Principle

The project is AGPL-3.0 and local-first. Support translates into **open,
reusable artifacts**: code, configuration, measurements and honest reporting —
not a private report to a single sponsor. Where results come from a specific
hardware partner, they are published as a reproducible profile that others can
verify.

---

## 2. What will be published

### Code and configuration
- **Integration code** for each hardware class / inference runtime tested
  (Ollama, llama.cpp, ROCm), upstreamed into the public repository.
- **Configuration profiles** per platform (model selection, thread/batch/context
  settings, memory tiers, the heavy-model mutex policy where it applies).
- **Benchmark harness** — the scripts used to measure throughput,
  time-to-first-token, end-to-end task latency, memory and energy.

### Results
- **Raw result files** (machine-readable), timestamped and tagged with platform,
  runtime and model versions.
- **Anonymised summaries** and comparison tables across hardware classes.
- A **cost / quality / performance comparison** — what each platform class buys,
  in plain numbers.

### Reproduction and documentation
- **Reproduction instructions** so a third party with the same hardware class can
  re-run the benchmarks and obtain comparable numbers.
- **Per-class hardware profiles** ("on this class of machine, M.A.R.I.A. behaves
  like this").
- **Failure and limitation reports** — what did not run, what regressed, what hit
  a memory or thermal wall. Negative results are published, not hidden.
- **A long-run operation write-up** — behaviour of the homeostasis loop over an
  extended window on each platform (stability, throttling, restarts).

### Reference workload
- A documented way to use M.A.R.I.A. as a **reference workload for an efficient,
  safety-governed local agent**: run the test suite plus the homeostasis loop for
  a fixed window and measure throughput, memory pressure under a combined
  plan+code task, thermals and power.

---

## 3. What will **not** be published

These boundaries are firm:

- The **operator's private data** and personal information.
- **M.A.R.I.A.'s private production memory** — the actual beliefs, knowledge,
  conversation history and decision traces from the live host. (Benchmarks use
  synthetic or clearly-consented inputs; never the operator's real memory.)
- **Secrets and credentials** — API keys, tokens, PINs (these live only in a
  git-ignored `.env`; the repo ships empty placeholders).
- **Private strategy material** — funding strategy, market work and related IP
  remain private (ADR-029).

Benchmark inputs are synthetic or explicitly public so that results are both
reproducible and safe to publish.

---

## 4. Cadence

- **Stage 1 (baseline)** can be published immediately on existing hardware — it
  needs no partner.
- Each subsequent stage in the [benchmark plan](./HARDWARE_BENCHMARK_PLAN.md)
  produces its own public profile + scripts + raw results as it completes, rather
  than one report at the end.

---

## 5. Why this is useful beyond M.A.R.I.A.

Reproducible measurements of a real, continuously-running autonomous agent across
CPU / GPU / NPU / unified-memory hardware are scarce and broadly useful: to
hardware vendors sizing edge-AI platforms, to researchers studying local agents,
and to anyone deciding what it actually costs to run a private, persistent agent
on owned hardware. Publishing the failures alongside the wins makes the data
trustworthy.

---

**Read next:** [benchmark plan](./HARDWARE_BENCHMARK_PLAN.md) ·
[funding brief](./FUNDING_BRIEF.md) · [project status](./CURRENT_PROJECT_STATUS.md)
