# M.A.R.I.A. — Hardware Benchmark & Integration Plan

**Meta Analysis Recalibration Intelligence Architecture**
2026-06-14

> This document defines a **reproducible benchmark program** for running
> M.A.R.I.A. on stronger and more varied hardware. It is a *plan*, not a results
> report. No throughput numbers are claimed here; establishing them is the first
> stage. The point of access to better hardware is to **execute this program and
> publish the results**, not simply to "run faster".

---

## 1. Why this plan exists

M.A.R.I.A. runs today entirely on CPU on a single 32 GB mini PC
(see [`CURRENT_PROJECT_STATUS.md`](./CURRENT_PROJECT_STATUS.md) §5). That host
imposes hard limits:

- local models capped at ~8B; models ≥24B excluded;
- a heavy-model mutex that serialises planning and coding;
- embeddings, vision and synthesis competing for the same cores;
- no NPU and no discrete GPU, so no on-device acceleration path.

The questions a hardware partnership lets us answer are concrete and measurable:
*How much faster, how much larger, how much more concurrent, and at what energy
cost* does M.A.R.I.A. become on each class of hardware — and which of its
currently-frozen research tracks become feasible.

---

## 2. Baseline: the current machine

The baseline is the reference every other platform is compared against.

| Property | Value |
|---|---|
| CPU | AMD Ryzen 5 7430U (6c / 12t, Zen 3) |
| Acceleration | none (no NPU; integrated Radeon iGPU unused for inference) |
| RAM | 32 GB |
| Inference runtime | Ollama (llama.cpp), GGUF Q4_K_M, CPU |
| Models | `llama3.1:8b` (executor, warm), `qwen3:8b` (planner), `qwen2.5-coder:7b`, `nomic-embed-text` (768-dim), rule-based triage |
| Known limits | heavy-model mutex; ~17 GB safe coexistence ceiling; ≥24B excluded |

The baseline measurement (Stage 1) captures, on this exact machine, the metrics
in §4 — so that "improvement" is always stated relative to a published number,
not an impression.

---

## 3. Platform classes to test

We propose evaluating across hardware **classes**, not a random list of devices.
Not every model is expected to run on every platform; that is itself a result.

1. **Modern CPU, more RAM/bandwidth** — a current x86 or ARM CPU with 64–128 GB.
   Tests whether larger local models (e.g. 14B–32B) become usable and whether the
   heavy-model mutex can be relaxed.
2. **Unified-memory systems** — large shared CPU/GPU memory (e.g. Ryzen AI / APU
   or comparable). Tests larger models and concurrent roles without a discrete
   VRAM boundary.
3. **Discrete GPU** — CUDA and/or **ROCm**. Tests inference acceleration,
   time-to-first-token, and running planner + coder concurrently.
4. **NPU-class edge platforms** — e.g. Ryzen AI (XDNA) or comparable NPUs. Tests
   on-device acceleration for embeddings and vision specifically, where an NPU is
   well-matched, at low power.

For each class we record what *did not* run (and why) as carefully as what did.

---

## 4. What we measure

Per model, per role, per platform, under both a single-task and a multi-role
workload:

- **Throughput** — tokens/second (generation), measured, not estimated.
- **Time-to-first-token (TTFT)** — prompt/prefill latency, which dominates the
  interactive chat path on CPU today.
- **End-to-end task latency** — full agent tasks (a planner cycle, a learning +
  exam cycle, a synthesis cycle), not just raw generation.
- **Memory** — peak RAM and, where applicable, VRAM.
- **Energy** — package power / energy-per-task where the platform exposes it
  (e.g. RAPL, GPU power telemetry); reported as "not measurable" where it is not.
- **Long-run stability** — sustained operation of the homeostasis loop for an
  extended window (thermal behaviour, throttling, memory drift, restart count).
- **Concurrency behaviour** — what happens when multiple model roles are active
  at once (does the heavy-model mutex still need to hold?).
- **Quality / task success** — does answer quality and real agent-task success
  hold or improve with larger models, measured with the existing exam and
  evaluation machinery, not vibes.

All measurements are timestamped, tagged with platform + runtime + model
versions, and stored in a comparable, machine-readable format.

---

## 5. Inference runtimes in scope

- **Ollama** — current runtime; the comparison anchor.
- **llama.cpp** — direct, for finer control of threads, batch and context, and
  for CPU/GPU build comparisons.
- **ROCm** — where AMD GPU/accelerator hardware is available.

CUDA may be included opportunistically if NVIDIA hardware is part of an
evaluation, but the project's centre of gravity is open, local runtimes.

---

## 6. Staged program

The program is sequential so that each stage produces a clean, comparable result
before the next variable is introduced.

**Stage 1 — Baseline (current machine).**
Run §4 on the Ryzen 5 7430U for the current model set. Publish the baseline.
*Deliverable: baseline profile + scripts.* This can begin immediately, on
existing hardware, and does not require a partner.

**Stage 2 — More CPU / more RAM.**
Re-run Stage 1 on a stronger CPU platform with 64–128 GB. Add larger local
models (14B–32B) where they fit. Measure whether the heavy-model mutex can be
relaxed. *Deliverable: CPU-scaling profile + larger-model feasibility report.*

**Stage 3 — Acceleration (GPU / unified memory / ROCm).**
Re-run on GPU and/or unified-memory hardware. Focus on TTFT, generation
throughput, and **concurrent planner + coder**. *Deliverable: acceleration
profile + concurrency report.*

**Stage 4 — Edge / NPU.**
Run targeted workloads (embeddings, vision) on NPU-class hardware at low power.
*Deliverable: edge profile + energy-per-task report.*

**Stage 5 — Unlock research tracks.**
On whichever platform provides headroom, attempt to **un-freeze the Maria 2.0
tracks** (symbolic world model, predictive/JEPA layer) and report whether they
become feasible to run alongside the 1.0 loop. *Deliverable: feasibility report.*

---

## 7. Reproducibility

Every stage ships with:

- the exact commit of M.A.R.I.A. used (the public `main` snapshot is designed to
  be easy to isolate for benchmarking);
- pinned runtime and model versions;
- the benchmark scripts and configuration;
- raw result files plus a short written analysis;
- a documented list of what failed and why.

A third party with the same hardware class should be able to reproduce the
numbers. Reproducibility is the deliverable, not a nice-to-have.

---

## 8. Out of scope / honest caveats

- We do **not** promise that any specific model will run on any specific
  platform. Feasibility is an outcome of the tests.
- We do **not** publish a tokens/s figure before it is measured (Stage 1).
- Energy measurement depends on platform telemetry and will be reported as
  unavailable where it cannot be measured reliably.
- The operator's private data and M.A.R.I.A.'s private production memory are
  never used as benchmark inputs; see [`PUBLIC_DELIVERABLES.md`](./PUBLIC_DELIVERABLES.md).

---

**Read next:** [public deliverables](./PUBLIC_DELIVERABLES.md) ·
[project status](./CURRENT_PROJECT_STATUS.md) ·
[model registry](../MODEL_REGISTRY.md)
