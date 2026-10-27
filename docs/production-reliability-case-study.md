# Production reliability case study

[Portfolio README](../README.md) · [Evidence audit](evidence/portfolio-audit-2026-10-26.md)
· [German summary](portfolio-summary-de.md) · [Documentation map](README.md)

M.A.R.I.A. runs a stateful Python agent on a resource-constrained operator host.
The incidents below illustrate the work between a successful model call and a
maintainable service: bounding waits, keeping the control loop responsive,
preventing maintenance churn, and correcting feedback signals.

**Evidence boundary, 26 October 2026:** incident descriptions are supported by
comments, implementation and regression tests in public revision `47eaec0`.
The original development history is not all part of the curated public Git
history, so the references below point to shipped code and tests rather than
unavailable fix commits. Historical symptoms are not fresh uptime measurements.
No private conversations or raw operational logs are reproduced.

## 1. An Ollama request outlived the control loop's deadline

**Context.** Background planning called a local model from a long-running
control loop. The incident commentary in
[execution_budget.py](../agent_core/llm/execution_budget.py), above
`get_ollama_client()`, records a June 2026 freeze of approximately 10.5 hours.
That duration is a historical source annotation; the raw event timeline was not
reconstructed during this review.

**Observable symptom.** The process remained present while the tick stopped
advancing. A caller deadline could return, yet the underlying HTTP call and its
worker remained blocked. A monitor executing on that same tick could not report
its own stalled execution.

**Root cause.** A caller timeout and a socket timeout solve different problems.
Some Ollama paths used a module-level client without the latter. Strategic
replanning also performed expensive work when its output was disabled.

**Diagnostic evidence.** The public source explains the failure and the intended
timeout ordering. `get_ollama_client()` constructs a shared client with an HTTP
timeout; `call_with_timeout()` bounds the caller. The
[planner](../agent_core/planner/planner_core.py) gates strategic work through
`_strategic_replan_due()`. The
[control loop](../agent_core/homeostasis/core.py) has a separate watchdog thread,
`_tick_stalled_for()` and `_trip_watchdog()`.

**Implemented fix.** Gate disabled strategic work, bound caller waits, route
participating Ollama requests through the timeout-aware client, and keep stall
detection outside the tick thread. On a confirmed stall, the watchdog dumps
thread stacks and terminates the process. The configured systemd service can
then restart it.

**Test or verification.**
[test_freeze_hardening_20260602.py](../agent_core/tests/test_freeze_hardening_20260602.py)
exercises model-call deadlines, stall detection and watchdog exit;
[test_ollama_http_timeout_20260602.py](../agent_core/tests/test_ollama_http_timeout_20260602.py)
checks scheduler degradation and guards against unbounded module calls.
The local review reran these tests and independently verified the watchdog
subprocess's exact diagnostic and exit status, with the public source explicitly
on its import path.

**Result.** Layered timeout and process-recovery mechanisms are implemented and
the regression checks pass. This establishes the tested failure behavior, not
months of uninterrupted service after the fix.

**Remaining limitation.** Caller deadlines cannot forcibly cancel arbitrary
worker code. If timeout-aware Ollama client construction fails, a compatibility
fallback still returns the bare module without its HTTP timeout. Watchdog
recovery is configurable and relies on a process supervisor to restart; a hard
exit can interrupt buffered writes.

## 2. Workflow advancement blocked the heartbeat

**Context.** The daemon advanced a workflow from its Phase 14 tick handler.
An individual step could wait for a remote analysis response.

**Observable symptom.** While a workflow step waited, the same tick could not
advance sensing, planning or Telegram polling. A slow step could also consume
the watchdog's stall allowance.

**Root cause.** `advance_next_active()` executed inline in the control loop.
The latency of an external operation became the latency of the entire heartbeat.

**Diagnostic evidence.** The comment and implementation of
`_advance_workflow_async()` in
[core.py](../agent_core/homeostasis/core.py) describe the blocking path.
[TestWorkflowPhaseOffTick](../agent_core/tests/test_core.py) includes a test of
the actual `_execute_tick()` Phase 14 call, not just the worker helper.

**Implemented fix.** Advance the workflow in a transient worker thread. Check
whether that worker is still alive before starting another advance, preserving
one-at-a-time access to the workflow engine. Catch worker failures so they do
not propagate through the heartbeat.

**Test or verification.** `TestWorkflowPhaseOffTick` verifies that scheduling
returns promptly, work is not duplicated while a worker is active, a later
advance is possible after completion, exceptions are contained, and the actual
tick remains non-blocking. This class passed in the local review and is included
in the public CI suite.

**Result.** External workflow latency is removed from the heartbeat's critical
path. The real tick wiring is covered by regression tests.

**Remaining limitation.** A blocked worker can still prevent that workflow from
making progress. The overlap guard deliberately refuses another advance while
the previous one lives. Responsiveness and task completion require separate
checks; a moving tick alone cannot demonstrate a completed workflow.

## 3. Belief rebuilding recreated data that pruning had just removed

**Context.** Periodic maintenance derived beliefs from knowledge records while
[BeliefStore](../agent_core/world_model/belief_store.py) enforced a cap of
2,000 current beliefs.

**Observable symptom.** Repeated builds on unchanged sources recreated candidates
that had just been pruned. This produced unnecessary add/prune/compact work;
beliefs near the retention boundary could receive new identities and lose
continuity.

**Root cause.** Deduplicating against currently retained beliefs cannot recognize
candidates removed by an earlier pruning pass. Enumerating the entire unchanged
source set restarted that cycle.

**Diagnostic evidence.** The `build_all()` docstring and implementation in
[belief_builder.py](../agent_core/world_model/belief_builder.py) describe this
recreation/pruning problem and compare source-file `(mtime_ns, size)` watermarks.
`BeliefStore.bulk_mode()` separately defers cap enforcement across batch inserts.

**Implemented fix.** Skip `build_all()` when source watermarks have not changed.
Record watermarks only after a successful build, and retain `force=True` for an
explicit rebuild. Bulk insertion avoids enforcing the cap after every item.

**Test or verification.**
[test_world_model.py](../agent_core/tests/test_world_model.py) contains
`test_build_all_skips_when_sources_unchanged`, source-change coverage, and
`test_build_all_force_overrides_watermark`. The local review reran the builder
and store tests; public CI covers the same code.

**Result.** Repeating an unchanged-source build takes the no-op path while
changed sources and explicit rebuilds remain supported. No unsupported speedup
factor or production latency estimate is attached to this result.

**Remaining limitation.** Watermarks are process-local and are not content
hashes. A cold start or changed source still triggers a build and possible
pruning. The retention cap deliberately discards information; it is not a claim
of unlimited learning capacity.

## 4. Maintenance feedback inflated confidence without new correctness evidence

**Context.** Examination results and scheduled sleep maintenance both updated
belief confidence. Confidence affected later decisions, so bias in the update
rule could accumulate across a long run.

**Observable symptom.** Beliefs accumulated confidence toward a ceiling, including
beliefs with unsuccessful examinations. Repeated corroboration maintenance
could reward the same sources again.

**Root cause.** Fixed pass/fail increments encouraged upward drift, while each
sleep cycle could add another corroboration reward. A deduplicated provenance
set was also unsuitable as a count of examination events.

**Diagnostic evidence.**
`_confidence_after_exam()` and `update_from_exam()` in
[belief_builder.py](../agent_core/world_model/belief_builder.py) implement the
current examination arithmetic. `_phase_nrem2()` in
[sleep_processor.py](../agent_core/consciousness/sleep_processor.py) documents
repeated-boost inflation and excludes beliefs carrying examination evidence.
The old fixed-increment wording in `update_from_exam()`'s docstring is stale;
the implementation and tests define current behavior.

**Implemented fix.** Move examination confidence toward the observed pass/fail
outcome using an exponential update. Corroboration maintenance aims for a
source-count-dependent target rather than adding a reward indefinitely, and
leaves examination-evaluated beliefs to the examination path.

**Test or verification.**
[test_world_model.py](../agent_core/tests/test_world_model.py) checks that
repeated passes do not ratchet to the ceiling and that never-passing beliefs
stay low; those regressions passed locally. Sleep tests cover basic boosts and
caps. This audit did not identify a dedicated repeated-cycle plus examination-
exclusion regression for the full sleep interaction; that is a remaining test gap.

**Result.** The shipped arithmetic corrects the identified update mechanisms.
Passing tests establish the examined cases. A historical simulation does not
establish a measured post-deployment confidence distribution.

**Remaining limitation.** Existing inflated values are not migrated immediately;
future examinations are needed to correct them. Confidence remains a heuristic,
not a calibrated probability or evidence that the underlying belief is true.

## What these incidents demonstrate

A long-running agent needs independent progress checks, bounded external work,
maintenance that converges, and feedback signals tied to the right outcome.
These cases provide inspectable engineering decisions and regression evidence.
A repeatable endurance test with fault injection and a public measurement
protocol remains a useful next step.

The proposed DNS incident was excluded: this audit did not establish a complete,
publicly supportable cause/fix/verification chain. The old large-JSONL outage
sizes and duration were also left out of measured claims because their original
runtime records were not independently reconstructed.
