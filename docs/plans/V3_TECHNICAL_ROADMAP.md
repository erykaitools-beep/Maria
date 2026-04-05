# M.A.R.I.A. V3 Technical Roadmap (V2 -> V3)

> Source: ChatGPT analysis, reviewed by Claude Code (2026-04-05)
> Status: APPROVED - no architectural conflicts with V2 codebase

## Core Principle

V3 = productization + orchestration layer ON TOP of V2-core.
Rule: **wrap, adapt, expose, orchestrate** - NOT rewrite/replace.

## V3 in one sentence

V3 is achieved when a new user can launch Maria through one entry point,
understand what Maria is, give a real task, receive a structured plan with
constraints and cost/time options, approve execution, and observe a coherent
end-to-end result.

## Phase A - Foundation (P0)

| # | Module | Status | Bazuje na |
|---|--------|--------|-----------|
| 1 | UnifiedLauncher | DONE | run_maria.py + run_ui.py |
| 2 | OnboardingFlow | DONE | UserFacingSelfModel + IdentityStore |
| 3 | UserFacingSelfModel | DONE | SelfModelBuilder + CapabilityRouter + ContextBuilder |

**Outcome:** Maria becomes understandable and launchable as one system.
**Status:** COMPLETE (2026-04-05) - 65 tests, all 3 modules done.

## Phase B - Task Pipeline (P1)

| # | Module | Status | Bazuje na |
|---|--------|--------|-----------|
| 4 | TaskOrchestrator | ~30% | PlannerCore + K5 |
| 5 | TaskDecomposer | ~20% | K8 Deliberation |
| 6 | ExecutionPlanBuilder | ~20% | Planner + ActionExecutor |

**Outcome:** Maria can turn user intent into structured work.

## Phase C - Practical Intelligence (P2)

| # | Module | Status | Bazuje na |
|---|--------|--------|-----------|
| 7 | CostEstimator | NEW | - |
| 8 | TimeEstimator | NEW | - |
| 9 | FreeVsPaidPlanner | NEW | - |

**Outcome:** Maria becomes useful for real decision-making.

## Phase D - Execution Bridge (P3)

| # | Module | Status | Bazuje na |
|---|--------|--------|-----------|
| 10 | ExecutionRouter | ~80% | CapabilityRouter (14 caps) |
| 11 | ToolCapabilityRegistry (user-facing) | ~60% | /api/capabilities + OpenClaw + Claude/Codex |
| 12 | TaskProgressTracker | ~40% | Traces + planner_state + Telegram |
| 13 | LimitationReporter | ~30% | K7 + K9 + K10 |

**Outcome:** Maria can move from plan to action with visibility.

## Phase E - Product Hardening (P4)

| # | Module | Status | Bazuje na |
|---|--------|--------|-----------|
| 14 | ProductShell | NEW | Web UI v2 |
| 15 | V3 UX Integration | NEW | - |

**Outcome:** Maria feels like a product, not a lab.

## V3 Release Gates

| Gate | Requirement | V2 Coverage |
|------|-------------|-------------|
| 1 | Unified startup | DONE |
| 2 | First-run guidance | DONE |
| 3 | Stable self-model | DONE |
| 4 | Real task execution | ~60% |
| 5 | Tool orchestration | ~70% |
| 6 | Cost/time planning | ~10% |
| 7 | Limitation handling | ~80% |
| 8 | Operator visibility | ~90% |
| 9 | Memory continuity | ~85% |
| 10 | Product coherence | ~40% |

## Milestone Definitions

### V3-alpha
- One-command startup
- Onboarding
- Self-model
- Task intake + decomposition
- Basic execution plan

### V3-beta
- Estimation engine (cost/time)
- Execution routing
- Progress tracking
- Limitation reporting

### V3-release
- Product shell
- Stable UX
- Clean operator/user flow
- Coherent end-to-end task execution

## Suggested Location

New modules: `agent_core/orchestrator/`
- launcher.py
- onboarding.py
- self_model.py
- task_orchestrator.py
- task_decomposer.py
- execution_plan.py
- cost_estimator.py
- time_estimator.py
- free_vs_paid.py
- execution_router.py (wraps CapabilityRouter)
- progress_tracker.py
- limitation_reporter.py

Product shell: `maria_ui/` extensions

Entry point: `maria.py` (new, replaces run_maria.py + run_ui.py)
