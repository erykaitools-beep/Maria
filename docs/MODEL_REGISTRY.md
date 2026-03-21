# MODEL_REGISTRY.md
# M.A.R.I.A. Local Model Registry
# Hardware: NiPoGi Mini PC | Ryzen 5 7430U | 32 GB RAM | Ubuntu 22.04
# Runtime: Ollama (primary) | llama.cpp (debug/fallback)
# Status: HARDENED v1.1 | 2026-03-21
# Author: Eryk Wyrebek (METAOPERATOR)
# Purpose: production-oriented registry for local model orchestration
---
## OPERATING PRINCIPLE
M.A.R.I.A. is **not** a one-model system.
This registry defines a **multi-organ local model stack** optimized for:
- stability first,
- predictable RAM behavior,
- explicit routing,
- safe escalation,
- strong separation of roles.
The full stack may exist **logically** as five organs, but it must **not** exist physically in RAM all at once.
---
## HARD LIMITS (32 GB RAM)
| Tier | RAM budget | Meaning | Policy |
|------|-----------:|---------|--------|
| SAFE | < 10 GB | always fits | parallel light tasks allowed |
| NORMAL | 10-16 GB | comfortable | one active main task, limited coexistence |
| WATCH | 16-18 GB | acceptable but monitored | no additional heavy loads |
| RISK | 18-22 GB | only for controlled tests | no background memory jobs |
| DANGER | 22-26 GB | unstable zone | temporary only, no production loops |
| FORBIDDEN | > 26 GB | OOM likely on this machine | do not load |
### Real machine assumptions
- Ubuntu + background services + M.A.R.I.A. runtime: **4-6 GB**
- Safe free margin to preserve: **at least 6 GB**
- Practical production ceiling for active models: **16-18 GB total**
- Anything above **18 GB** must be treated as **benchmark-only** or temporary maintenance mode
### Core rule
**Do not optimize for "it fits once". Optimize for repeated daily operation without OOM, swap thrash, or routing instability.**
---
## LOADING POLICY
### Warm models
These may remain loaded during active work sessions:
- **MODEL-04 (TRIAGE)**
- **MODEL-02 (EXECUTOR)**
### Cold / on-demand models
These must load only when needed:
- **MODEL-01 (PLANNER)**
- **MODEL-03 (CODER)**
### Conditional model
- **MODEL-05 (MEMORY)**
  - default mode: **shared persona on MODEL-02**
  - dedicated model only if benchmark proves strong quality gain and RAM stays within budget
### Idle unload policy
- TRIAGE: keep warm
- EXECUTOR: keep warm during active sessions; unload after **20 min idle** if needed
- PLANNER: unload after **5 min idle**
- CODER: unload after **5 min idle**
- MEMORY dedicated instance: unload immediately after compression job completes
---
## REGISTERED MODELS
### MODEL-01 -- Strategic Planner (Primary Brain)
```yaml
id: qwen2.5-14b-instruct
file_format: GGUF / Q4_K_M
ram_estimate_gb: 9
warm_state: cold
priority: high
ollama_tag: qwen2.5:14b
role: PLANNER
latency_budget_max_s: 45
concurrency_class: heavy
use_when:
  - planning
  - architecture decisions
  - multi-step reasoning
  - proposal generation
  - synthesis of multiple sources
  - experiment design
  - evaluation of system changes
avoid_when:
  - task is classification only
  - short answer expected under 80 tokens
  - routing decision only
  - memory compression
  - code-only patch generation
fallback_to: MODEL-02
load_guard:
  min_free_ram_gb_before_load: 12
  block_if_any_heavy_model_active: true
```
### MODEL-02 -- Executor / Worker (Fallback Brain)
```yaml
id: llama-3.1-8b-instruct
file_format: GGUF / Q4_K_M
ram_estimate_gb: 5
warm_state: warm
priority: highest
ollama_tag: llama3.1:8b
role: EXECUTOR
latency_budget_max_s: 20
concurrency_class: light_main
use_when:
  - short procedural tasks
  - text transformation
  - draft generation
  - quick iterations
  - general question answering
  - fallback when MODEL-01 times out
  - shared memory-compression mode
avoid_when:
  - architectural reasoning required
  - deep multi-step planning required
  - code-specialized generation preferred
fallback_to: MODEL-04
load_guard:
  min_free_ram_gb_before_load: 8
  block_if_any_heavy_model_active: false
```
### MODEL-03 -- Coding Organ
```yaml
id: qwen2.5-coder-7b-instruct
file_format: GGUF / Q4_K_M
ram_estimate_gb: 5
warm_state: cold
priority: high
ollama_tag: qwen2.5-coder:7b
role: CODER
latency_budget_max_s: 30
concurrency_class: heavy
use_when:
  - code generation
  - patch analysis
  - diff review
  - test writing
  - refactoring
  - log analysis when code dominates
  - script generation for experiments
avoid_when:
  - natural language only task
  - planning without code
  - generic summaries
fallback_to: MODEL-02
load_guard:
  min_free_ram_gb_before_load: 10
  block_if_any_heavy_model_active: true
```
### MODEL-04 -- Semantic Gate / Triage (Cheap Layer)
```yaml
id: TBD_AFTER_BENCHMARK
candidate_pool:
  - phi3:mini
  - qwen2.5:3b
  - gemma2:2b
file_format: GGUF / Q4_K_M
ram_estimate_gb: 2-3
warm_state: warm
priority: highest
ollama_tag: TBD_AFTER_BENCHMARK
role: TRIAGE
latency_budget_max_s: 3
concurrency_class: light_gate
use_when:
  - intent classification
  - routing decision
  - tagging
  - field extraction
  - initial risk detection
  - cheap escalation decision
  - pre-memory cleanup tags
avoid_when:
  - reasoning required
  - output longer than 200 tokens expected
fallback_to: MODEL-02_HEURISTIC
confidence_policy:
  if_confidence_below: 0.75
  escalate_to: MODEL-02
```
### MODEL-05 -- Memory Compressor / Summarizer
```yaml
id: SHARED_BY_DEFAULT
default_mode: reuse_MODEL-02_with_memory_prompt
optional_dedicated_model: qwen2.5:7b
file_format: GGUF / Q4_K_M
ram_estimate_gb_if_dedicated: 5
warm_state: batch_only
priority: medium
role: MEMORY
latency_budget_max_s: 15
concurrency_class: background_light
use_when:
  - session summarization
  - fact extraction for long-term memory
  - context compression before episodic save
  - building belief entries
  - daily summary generation
avoid_when:
  - code task
  - planning task
  - any period of RAM pressure
hard_rule:
  dedicated_instance_allowed_only_if:
    - stage_4_peak_ram_gb <= 16
    - no_heavy_model_needed_during_memory_job
    - benchmark_summary_quality_gain >= 1.0_point_on_5_scale
  otherwise: reuse MODEL-02
```
### MODEL-06 -- External API (NIM)
```yaml
id: z-ai/glm5
endpoint: integrate.api.nvidia.com/v1
ram_estimate_gb: 0
warm_state: external
priority: medium
role: EXTERNAL_LEARNING
latency_budget_max_s: 30
concurrency_class: none
token_budget:
  daily: 100000
  monthly: 2000000
expiry: 2026-08-xx
use_when:
  - learning analysis (current primary use)
  - fallback for MODEL-01 when RAM pressure
  - heavy reasoning when local models overloaded
avoid_when:
  - offline mode required
  - token budget depleted
  - chat (use local Ollama instead)
fallback_to: MODEL-02
notes: >
  Free NVIDIA NIM key from build.nvidia, valid until August 2026.
  Currently the primary model for learning tasks via LLMRouter.
  After expiry, MODEL-01 or MODEL-02 takes over learning.
```
---
## MODEL-05 DECISION POLICY (HARDENED)
### Default decision
**MODEL-05 must reuse MODEL-02 by default.**
### Dedicated MODEL-05 is allowed only if all conditions are true
1. Stage 4 measured peak RAM is **16 GB or lower**
2. Dedicated memory model improves summary/extraction quality by **at least +1.0 point on a 5-point scale**
3. Memory jobs are scheduled outside planner/coder windows
4. No OOM, swap spike, or latency regression appeared during test run
### Otherwise
Use:
- same MODEL-02 instance,
- different system prompt,
- smaller batch window,
- delayed compression cycle.
**Reason:** memory compression is important, but not more important than stability.
---
## COEXISTENCE MATRIX (PRODUCTION-SAFE)
| Combination | Estimated total RAM | Status | Notes |
|-------------|--------------------:|--------|-------|
| MODEL-04 | ~3 GB | SAFE | keep warm |
| MODEL-02 + MODEL-04 | ~8 GB | SAFE | default operating base |
| MODEL-01 + MODEL-04 | ~12 GB | SAFE | planning without executor kept warm if needed |
| MODEL-03 + MODEL-04 | ~8 GB | SAFE | coding path |
| MODEL-01 + MODEL-02 + MODEL-04 | ~17 GB | WATCH | allowed, but no other jobs |
| MODEL-02 + MODEL-03 + MODEL-04 | ~13 GB | SAFE | common coding configuration |
| MODEL-01 + MODEL-03 + MODEL-04 | ~17 GB | WATCH | not preferred; do sequentially if possible |
| MODEL-01 + MODEL-02 + MODEL-03 | ~19 GB | BENCHMARK ONLY | not for continuous production |
| MODEL-01 + MODEL-02 + MODEL-03 + MODEL-04 | ~22 GB | DANGER | temporary test only |
| all 5 logical organs as separate instances | ~26 GB | FORBIDDEN | violates stability target |
### Golden rule
**The production baseline is MODEL-02 + MODEL-04. Everything else is an escalation.**
---
## CONCURRENCY POLICY
### Heavy models
Heavy = MODEL-01 or MODEL-03
### Allowed concurrency
- MODEL-04 may run alongside anything
- MODEL-02 may run alongside MODEL-04 and may remain warm during a heavy task
- MODEL-05 shared mode may run on MODEL-02 only when no heavy task is active
### Forbidden concurrency
- MODEL-01 and MODEL-03 must **never** execute simultaneously
- Dedicated MODEL-05 must **never** run while MODEL-01 or MODEL-03 is active
- Two heavy tasks must **never** be scheduled in parallel
### Scheduler rules
1. Max heavy jobs at once: **1**
2. Max memory jobs at once: **1**
3. If heavy job starts, background memory compression is paused
4. If planner job is queued while coder is active, planner waits
5. If coder job is queued while planner is active, coder waits unless task severity is marked `critical_patch`
### Emergency degradation
If free RAM drops below **7 GB**:
- reject planner load,
- reject coder load,
- force routing to MODEL-02 or queue,
- postpone memory compression,
- log `ram_pressure_event=true`.
---
## ROUTING CONFIDENCE POLICY
### Triage result handling
- confidence >= 0.85 -> accept route
- confidence 0.75-0.84 -> accept only if heuristic agrees
- confidence < 0.75 -> escalate to MODEL-02 for secondary routing judgment
- confidence < 0.60 + high-risk keywords -> hold and log manual-review-needed
### Heuristic agreement examples
- contains `.py`, `pytest`, `diff`, `patch` -> code bias
- contains `plan`, `design`, `architecture`, `proposal` -> planner bias
- contains `summarize`, `compress`, `extract facts` -> memory bias
- very short command / rewrite / transform -> executor bias
---
## LATENCY BUDGETS
| Role | Max acceptable latency | Action if exceeded |
|------|-----------------------:|-------------------|
| TRIAGE (MODEL-04) | 3s | fallback to MODEL-02 heuristic |
| EXECUTOR (MODEL-02) | 20s | return partial + log warning |
| MEMORY (MODEL-05) | 15s | skip compression this cycle |
| CODER (MODEL-03) | 30s | timeout + retry once |
| PLANNER (MODEL-01) | 45s | timeout + fallback to MODEL-02 summary plan |
### Repeated latency fault rule
If the same model exceeds latency budget **3 times in one session**:
- mark `model_unhealthy=true`
- stop non-essential use of that model
- fall back according to role
- record incident for homeostasis review
---
## QUALITY RUBRIC
Score each tested output from **1 to 5**.
### 1. Planning quality
- 1 = confused, missing structure
- 2 = partial plan, weak logic
- 3 = usable but shallow
- 4 = strong, coherent, actionable
- 5 = excellent, precise, robust, low ambiguity
### 2. Code quality
- 1 = broken / unsafe / irrelevant
- 2 = partial or syntactically weak
- 3 = usable with edits
- 4 = strong, mostly correct
- 5 = production-ready or near-production-ready
### 3. Classification quality
- 1 = mostly wrong
- 2 = unreliable
- 3 = acceptable baseline
- 4 = accurate and stable
- 5 = highly accurate with consistent confidence
### 4. Summary quality
- 1 = loses core meaning
- 2 = misses key facts
- 3 = okay but incomplete
- 4 = preserves essentials well
- 5 = compact, faithful, highly useful for memory
### 5. Extraction quality
- 1 = wrong fields / noise
- 2 = weak precision
- 3 = mostly correct
- 4 = high precision and recall
- 5 = precise, stable, ready for storage
### Pass thresholds by role
| Role | Minimum average score |
|------|----------------------:|
| TRIAGE | 4.0 classification |
| EXECUTOR | 3.5 general utility |
| MEMORY | 4.0 summary/extraction |
| CODER | 4.0 code |
| PLANNER | 4.0 planning |
---
## BENCHMARK CHECKLIST (HARDENED)
For each model candidate, measure:
- [ ] RAM usage at load (MB)
- [ ] RAM usage during inference peak (MB)
- [ ] Time to first token (TTFT) -- short prompt
- [ ] Time to first token (TTFT) -- long prompt
- [ ] Total inference time -- 200 token output
- [ ] 3 repeated requests without OOM
- [ ] Quality score on planning / code / classification / summary / extraction
- [ ] Confidence reliability for routing model
- [ ] Behavior under low free RAM simulation
Update this registry after benchmark. Replace all TBD fields.
---
## FORBIDDEN MODELS (ON THIS HARDWARE)
| Model | Reason |
|-------|--------|
| Mistral Small 3.1 (24B) | too large for comfortable daily local use on 32 GB RAM |
| Qwen3-30B-A3B (MoE) | CPU latency and scheduling unpredictability too high for agent loop |
| Any dense 32B+ model | violates practical RAM budget |
| Any model with measured load > 26 GB | forbidden by hard limit |
| Any model that OOMs on 3 consecutive requests | operationally disqualified |
---
## CHANGE CONTROL
Update this registry when one of the following changes:
- MODEL-04 winner selected
- Stage 4 peak RAM measured
- MODEL-05 dedicated/shared decision finalized
- latency budgets revised after real benchmark
- fallback routing changed
- a model becomes unhealthy in production
---
## VERSION HISTORY
| Date | Change |
|------|--------|
| 2026-03-21 | v1.0 initial draft |
| 2026-03-21 | v1.1 hardened: concurrency, loading policy, MODEL-05 decision, routing confidence, quality rubric |
| 2026-03-21 | v1.1+ added MODEL-06 (NIM external API) for completeness |
