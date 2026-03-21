# deployment_order.md
# M.A.R.I.A. Local Model Deployment -- Step-by-Step
# Version: 1.1 HARDENED | 2026-03-21
# Read alongside: MODEL_REGISTRY.md + routing_rules.yaml
# Purpose: production-safe rollout sequence for 32 GB RAM Ubuntu node
---
## PHILOSOPHY
Do not deploy everything at once.
Each stage must pass its own health check before the next one starts.
M.A.R.I.A. must remain stable at every intermediate stage.
### Production principle
The objective is **not** maximum model count.
The objective is:
- predictable routing,
- no OOM,
- no hidden RAM pressure,
- clear rollback,
- benchmark-backed decisions.
### Golden operating state
Default live configuration should be:
- **MODEL-04 warm**
- **MODEL-02 warm**
- everything else on demand
---
## STAGE 0 -- Prerequisites and Safety Rails
Before any model is deployed:
- [ ] Ollama installed and running: `ollama serve`
- [ ] Ollama API accessible: `curl http://localhost:11434/api/tags`
- [ ] Free RAM confirmed: `free -h` -> should show **> 20 GB available** before first benchmark
- [ ] Swap status checked: `swapon --show` and `free -h`
- [ ] M.A.R.I.A. runtime stable (homeostasis healthy)
- [ ] Storage Manager active (logs will capture benchmark data)
- [ ] 6 TB disk mounted and writable (model files go here, not system SSD)
- [ ] routing_rules.yaml includes `oom_kill_protection: true`
- [ ] routing_rules.yaml includes heavy-model mutex / queue behavior
- [ ] benchmark directory exists for logs: `benchmarks/local_models/`
### Stage 0 output
Create these artifacts before Stage 1:
- `benchmark_log.md`
- `routing_decisions.jsonl`
- `incident_log.jsonl`
- `model_health.json`
### Pass criteria
- [ ] All safety rails verified
- [ ] No stale Ollama processes
- [ ] At least 6 GB RAM headroom reserved after baseline services
Stage 0 complete -> proceed to Stage 1
---
## STAGE 1 -- Single Model Baseline (MODEL-02)
Goal: prove one useful model works end-to-end before adding routing complexity.
### 1.1 Install MODEL-02
```bash
ollama pull llama3.1:8b
```
### 1.2 Verify load
```bash
ollama run llama3.1:8b "Say exactly: MODEL-02 ONLINE"
```
### 1.3 Benchmark MODEL-02
Run and log:
- RAM at load: `free -h`
- TTFT short prompt -- 3 runs average
- TTFT long prompt -- 3 runs average
- 200-token generation time
- 10 consecutive requests without OOM
- quality on 5 executor-style prompts
Suggested prompts:
1. Rewrite short operational note
2. Summarize a short log chunk
3. Transform bullet list into YAML
4. Answer a general question about system state
5. Produce a concise user-facing draft
### 1.4 Pass criteria
- [ ] RAM under **8 GB** when loaded
- [ ] TTFT under **5s** on short prompt
- [ ] No OOM in **10 consecutive requests**
- [ ] Average executor quality score **>= 3.5/5**
- [ ] No latency spikes beyond budget in more than 1 of 10 runs
### 1.5 If failed
- reduce context length
- confirm no hidden background jobs
- retest before advancing
Stage 1 complete -> proceed to Stage 2
---
## STAGE 2 -- Add Triage Layer (MODEL-04)
Goal: routing works before adding expensive models.
### 2.1 Benchmark 3B-4B candidates
Test candidates and pick the winner:
```bash
ollama pull phi3:mini
ollama pull qwen2.5:3b
# optional
ollama pull gemma2:2b
```
For each candidate, measure:
- RAM at load
- TTFT on classification prompt
- accuracy on 20 routing cases
- confidence stability
- false escalation rate
### 2.2 Use this routing benchmark set
At least 20 tasks:
- 5 planning
- 5 code
- 4 summary/memory
- 3 classification-only
- 3 general executor
### 2.3 Register winner as MODEL-04
Update registry:
- replace TBD model id
- add measured RAM
- add measured TTFT
- add measured confidence behavior
### 2.4 Verify routing confidence policy
Test:
- high-confidence correct route
- low-confidence escalation to MODEL-02
- heuristic agreement case
- heuristic disagreement case
### 2.5 Pass criteria
- [ ] MODEL-04 RAM under **3 GB**
- [ ] TTFT under **3s**
- [ ] Classification accuracy **>= 85% on 20 cases**
- [ ] Low-confidence escalation works
- [ ] MODEL-02 + MODEL-04 coexist under **10 GB** total RAM
### 2.6 Implementation note
At the end of Stage 2, routing must support:
- `route_target`
- `triage_confidence`
- `heuristic_match`
- `escalated_to_model_02`
Stage 2 complete -> proceed to Stage 3
---
## STAGE 3 -- Add Strategic Planner (MODEL-01)
Goal: heavy reasoning available for planning and architecture tasks.
### 3.1 Install MODEL-01
```bash
ollama pull qwen2.5:14b
```
### 3.2 RAM safety check before loading
```bash
free -h
# Must show > 12 GB free before loading MODEL-01
```
### 3.3 Verify heavy-model mutex
Before planner goes live, confirm:
- planner cannot start if coder already active
- planner blocks memory job if dedicated memory model exists
- queue behavior is visible in logs
### 3.4 Benchmark MODEL-01
Measure:
- RAM at load
- TTFT on planning prompt
- total time for structured answer
- quality score vs MODEL-02 on same 5 planning tasks
Suggested planning prompt:
```text
Design a 3-step experiment plan for testing whether increasing exam frequency
improves M.A.R.I.A.'s belief accuracy. Include hypothesis, method, success
criteria, failure modes, and rollback.
```
### 3.5 Verify health guard
Confirm routing guard:
- If free RAM < 12 GB -> MODEL-01 must not load
- If MODEL-03 active -> MODEL-01 must queue
- If memory compression active -> memory job pauses or exits before planner starts
### 3.6 Pass criteria
- [ ] RAM under **11 GB** when loaded alone
- [ ] MODEL-01 + MODEL-02 + MODEL-04 coexist under **17 GB**
- [ ] Latency under **45s** on planning prompt
- [ ] Planner average quality score **>= 4.0/5**
- [ ] Health guard blocks unsafe load
- [ ] Heavy-model mutex verified
Stage 3 complete -> proceed to Stage 4
---
## STAGE 4 -- Add Coding Organ (MODEL-03)
Goal: code tasks have a dedicated model, not a general model.
### 4.1 Install MODEL-03
```bash
ollama pull qwen2.5-coder:7b
```
### 4.2 Verify heavy-model mutex again
Confirm:
- MODEL-03 cannot start if MODEL-01 active
- MODEL-03 can coexist with MODEL-02 + MODEL-04
- dedicated MODEL-05 cannot run during coder session
### 4.3 Benchmark MODEL-03
Measure:
- RAM at load
- TTFT on code prompt
- 5 coding tasks vs MODEL-02
- syntax validity rate
- test usefulness
Suggested prompt:
```text
Write a pytest for this function: def rebuild_beliefs(self): ...
```
### 4.4 Verify routing for code tasks
Cases:
- `.py` reference -> MODEL-04 -> MODEL-03
- `patch`, `diff`, `refactor`, `pytest` -> MODEL-04 -> MODEL-03
- mixed planning+code task -> first MODEL-02 routing check; if architecture dominates, planner first; if patch dominates, coder first
### 4.5 Pass criteria
- [ ] MODEL-02 + MODEL-03 + MODEL-04 coexist under **13 GB**
- [ ] Code quality better than MODEL-02 on **5/5** selected code benchmarks or at least average **+1.0 point** higher
- [ ] Routing correctly sends code tasks to MODEL-03
- [ ] Heavy-model mutex verified for coder
### 4.6 Stage 4 decision artifact
At end of this stage record:
- measured peak RAM with MODEL-02 + MODEL-03 + MODEL-04
- measured peak RAM with MODEL-01 + MODEL-02 + MODEL-04
- final basis for MODEL-05 decision
Stage 4 complete -> proceed to Stage 5
---
## STAGE 5 -- Memory Compressor (MODEL-05) + Full Routing Loop
Goal: complete the organ set without destabilizing the machine.
### 5.1 Default policy
Default to **shared MODEL-02 memory mode**.
Do **not** introduce a dedicated memory model unless the criteria below are met.
### 5.2 Dedicated MODEL-05 allowed only if all true
- [ ] Stage 4 peak RAM <= **16 GB**
- [ ] dedicated memory model improves summary/extraction score by **>= 1.0/5**
- [ ] no OOM or severe latency regression during test
- [ ] memory jobs can be scheduled outside heavy-model windows
### 5.3 If any condition fails
Use shared mode:
- MODEL-02 with memory compression prompt
- smaller memory batches
- delayed compression at low-load times
### 5.4 Benchmark shared vs dedicated memory mode
Use 10 memory tasks:
- 4 session summaries
- 3 fact extraction tasks
- 3 belief-entry compression tasks
Score:
- summary faithfulness
- extraction precision
- storage usefulness
- latency
- RAM stability
### 5.5 Full routing loop test
Run 20 mixed tasks through complete pipeline:
- 5 planning -> MODEL-01
- 5 code -> MODEL-03
- 5 classification -> MODEL-04 only
- 5 general -> MODEL-02
For low-confidence tasks, verify MODEL-04 escalation behavior.
### 5.6 Pass criteria
- [ ] All 20 routing decisions correct
- [ ] No OOM during 20-task run
- [ ] Logs flowing to Storage Manager
- [ ] Homeostasis reads model usage metrics
- [ ] Memory mode decision documented and justified
Stage 5 complete -- local model stack operational
---
## STAGE 6 -- Integration with M.A.R.I.A. Organs
This stage connects local models to existing M.A.R.I.A. modules.
### 6.1 Connect to Planner
- Planner calls MODEL-01 for complex decisions
- Planner may use MODEL-04 for cheap pre-routing
- Planner must never bypass heavy-model mutex
### 6.2 Connect to Teacher / Memory
- Teacher uses MODEL-05 shared mode by default
- Dedicated memory mode only if approved by Stage 5 decision artifact
### 6.3 Connect to K11 Experiment System
- Proposal Engine uses MODEL-01
- Experiment Runner uses MODEL-03 for code patches
- Report Generator uses MODEL-02 for summaries
- Triage may preclassify experiment requests
### 6.4 Homeostasis monitoring
Add to homeostasis metrics:
- current model loaded
- peak RAM per request
- latency per role
- queue time for heavy models
- memory compression skipped count
- ram_pressure_event count
- unhealthy_model count
### 6.5 Pass criteria
- [ ] All organs can call through router
- [ ] Metrics visible to homeostasis
- [ ] Queue behavior visible in logs
- [ ] No direct bypass around routing layer
Stage 6 complete -> proceed to Stage 7
---
## STAGE 7 -- Fault Tolerance and Recovery Drill
Goal: prove the stack can fail safely.
### 7.1 Simulate failures
Run controlled tests:
- planner timeout
- coder timeout
- triage low confidence
- forced RAM pressure event
- storage manager unavailable for one request
### 7.2 Expected behavior
- fallback route chosen
- queued heavy task waits cleanly
- memory compression postponed
- incident logged
- system returns to stable baseline: MODEL-02 + MODEL-04
### 7.3 Pass criteria
- [ ] All failure paths logged
- [ ] No crash cascade
- [ ] System returns to baseline within one cycle
Stage 7 complete -- rollout hardened
---
## ROLLBACK PROCEDURE (HARDENED)
If any stage fails or causes OOM:
```bash
# Show loaded models
ollama list
# Stop active heavy jobs first (app-level queue pause recommended)
# Then remove or unload offending model if needed
ollama rm <model_name>
# Emergency restart
pkill ollama
sleep 5
ollama serve &
```
### Mandatory recovery actions after rollback
1. Record incident in `incident_log.jsonl`
2. Capture:
   - free RAM after recovery
   - swap state
   - model that triggered failure
   - active stage
3. Re-run API health check:
   ```bash
   curl http://localhost:11434/api/tags
   ```
4. Confirm baseline availability:
   - MODEL-04 route health
   - MODEL-02 basic response health
5. Mark current stage as `FAILED`
6. Return to previous stable stage only after root-cause note is written
### Root-cause categories
Use one of:
- `oom_load`
- `oom_inference`
- `latency_spike`
- `routing_error`
- `mutex_violation`
- `memory_job_collision`
- `storage_log_failure`
---
## BENCHMARK LOG TEMPLATE (HARDENED)
Copy and fill after each stage:
```text
Stage: ___
Date: ___
Status: PASS / FAIL
Models warm: ___
Models loaded on-demand: ___
MODEL-04 (TRIAGE):
  ram_load_mb: ___
  ttft_short_s: ___
  classification_accuracy_20: ___/20
  avg_confidence: ___
  low_confidence_escalations: ___
MODEL-02 (EXECUTOR):
  ram_load_mb: ___
  ttft_short_s: ___
  ttft_long_s: ___
  executor_quality_avg_5: ___
MODEL-01 (PLANNER):
  ram_load_mb: ___
  ttft_planning_prompt_s: ___
  planner_quality_avg_5: ___
  blocked_by_guard_count: ___
MODEL-03 (CODER):
  ram_load_mb: ___
  ttft_code_prompt_s: ___
  coder_quality_avg_5: ___
  syntax_valid_outputs: ___/5
MODEL-05 (MEMORY):
  mode: shared / dedicated
  ram_load_mb: ___
  summary_quality_avg_5: ___
  extraction_quality_avg_5: ___
  skipped_due_to_ram_pressure: ___
System:
  peak_total_ram_gb: ___
  free_ram_after_peak_gb: ___
  swap_used_mb: ___
  oom_events: ___
  latency_budget_violations: ___
  mutex_violations: ___
  ram_pressure_events: ___
  incident_ids: ___
Decision:
  proceed_to_next_stage: yes / no
  reason: ___
  notes: ___
```
---
## VERSION HISTORY
| Date | Change |
|------|--------|
| 2026-03-21 | v1.0 initial draft |
| 2026-03-21 | v1.1 hardened: safety rails, heavy-model mutex, MODEL-05 policy, fault drill, stronger benchmark logging |
