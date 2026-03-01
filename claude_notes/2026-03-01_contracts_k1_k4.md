# 2026-03-01 - Kontrakty K1-K4 implementacja

## Co sie dzisiaj stalo
Implementacja wszystkich 4 kontraktow architektonicznych w jednej sesji.
Eryk powiedzial "idziemy po koleji nie ma co skakac trzymamy sie obecnego planu" -
zrobilismy K1 -> K2 -> K3 -> K4 sekwencyjnie.

## Zrealizowane

### K1: Unified Perception (Warstwa 1)
- PerceptionEvent (frozen dataclass) + PerceptionSource (7 typow)
- EVENT_TYPE_DEFAULTS: 22 typow z (priority, ttl, dedupable)
- PerceptionBuffer: deque(maxlen=200) sliding window
- 6 adapterow: sensor, user, learning, exam, consciousness, teacher
- Tick Aggregator (ADR-009): Phase 8 PERCEIVE + external queue (deque maxlen=50)
- 131 testow (event: 39, buffer: 35, adapters: 38, integration: 19)

### K2: Sandbox / Production Boundary
- SandboxSession, SandboxStatus, PromoteResult (protocol.py)
- SandboxManager: full lifecycle z transaction log (START/COMMIT/ROLLBACK)
- Startup recovery: auto-DISCARD osieroconych sesji
- SANDBOX_DIR w config.py, ensure_directories() zaktualizowane
- 44 testy

### K3: Goal System
- GoalType(4), GoalStatus(6), AuditEntry, Goal + create_goal() factory
- GoalStore: CRUD + append-only JSONL + seed goals (1 META + 3 MAINTENANCE)
- PROPOSED flow z pelna izolacja od planowania
- Limity: max 20 active, max 3 proposed, 24h timeout
- 63 testy

### K4: Agent Evaluation (READ-ONLY)
- EvaluationObserver: 5 metryk z 5 JSONL sources
- learning_velocity: chunks/hour z teacher_plans.jsonl
- retention_rate: passed/total z exam_results.jsonl
- knowledge_coverage: completed/total z knowledge_index.jsonl (merge semantics!)
- system_stability: avg health_score z homeostasis_events.jsonl
- personality_growth: event count deltas z personality_experiences.jsonl
- Threshold-based recommendations (pure logic, zero LLM)
- 35 testow

## Wiring
Wszystko w homeostasis_module.py init():
1. PerceptionBuffer -> core.set_perception_buffer() + ctx.perception_buffer
2. SandboxManager -> startup_recovery() + ctx.sandbox_manager
3. GoalStore -> load() + seed_if_empty() + expire_proposed() + save() + ctx.goal_store
4. EvaluationObserver -> ctx.evaluation_observer

SharedContext ma teraz: perception_buffer, sandbox_manager, goal_store, evaluation_observer

## Testy
668 -> 941 (+273 nowych, zero regresji)

## Co dalej
Wg DEVELOPMENT_PLAN nastepna jest Warstwa 2: Planner (ReAct loop).
Ale to wymaga specyfikacji - moze warto dac Grokowi/ChatGPT kontekst K1-K4 i poprosic o review?

## Uwagi techniczne
- knowledge_index.jsonl uzywa MERGE semantics (nie pure append!) - ostatni rekord per id wygrywa
- homeostasis_events.jsonl ma dwa formaty timestamp: "ts" (float) i "timestamp" (ISO string)
- Adaptery w testach uzywaja Mock dataclasses (nie importuja psutil)
- External queue (deque maxlen=50) jest thread-safe dzieki CPython GIL
