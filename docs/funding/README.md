# M.A.R.I.A. — Funding & Hardware Research

**Meta Analysis Recalibration Intelligence Architecture**

This directory describes M.A.R.I.A.'s **research needs, hardware constraints,
benchmark plan and the public results** that funding or hardware partnership
would produce. It is written for grant officers, hardware vendors, academic and
technical partners, and any engineer evaluating the project for the first time.

M.A.R.I.A. is an open-source, **local-first autonomous agent runtime** running in
production on a single CPU-only mini PC since 2026-02-22. Its further experiments
are now limited primarily by hardware. These documents explain that constraint as
a concrete, reproducible program of work — not as a request for "a better
computer".

> All documents here are public and factual. Every figure is sourced to the
> repository or to a stated measurement method. Private material (operator data,
> funding strategy, secrets, M.A.R.I.A.'s production memory) is deliberately kept
> out of this directory and out of the public repository.

---

## Contents

| Document | What it covers |
|---|---|
| [`FUNDING_BRIEF.md`](./FUNDING_BRIEF.md) | One-page brief: what M.A.R.I.A. is, the problem, current state, the hardware bottleneck, what is needed, what gets published. |
| [`CURRENT_PROJECT_STATUS.md`](./CURRENT_PROJECT_STATUS.md) | Dated, fully-sourced status report: code, tests, architecture maturity, deployment, hardware, models, safety, limitations. |
| [`HARDWARE_BENCHMARK_PLAN.md`](./HARDWARE_BENCHMARK_PLAN.md) | Reproducible, staged benchmark program across CPU / GPU / NPU / unified-memory classes. A plan, not results. |
| [`PUBLIC_DELIVERABLES.md`](./PUBLIC_DELIVERABLES.md) | Exactly what is published in return: code, configs, scripts, raw/anonymised results, reproduction instructions, failure reports. |

---

## Background documents in the repository

These are the deeper technical references the documents above draw on:

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — layers and data flow
- [`../CONTRACTS.md`](../CONTRACTS.md) — the K1–K13 cognitive contracts
- [`../SYSTEM_STATUS.md`](../SYSTEM_STATUS.md) — per-subsystem maturity (source of truth)
- [`../SECURITY.md`](../SECURITY.md) — security posture
- [`../MODEL_REGISTRY.md`](../MODEL_REGISTRY.md) — local/external model stack and RAM tiers
- [`../../README.md`](../../README.md) — project overview and production history
