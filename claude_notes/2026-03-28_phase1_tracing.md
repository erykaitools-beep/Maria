# 2026-03-28 - Mega sesja: Phase 1-4 Stabilization Roadmap

## Co zrobilem (cala sesja)

### Phase 1: Decision Traceability (ADR-022)
- `agent_core/tracing/` - episode_id (thread-local), DecisionTrace, TraceStore
- Episode ID flows: planner -> LLM tape -> K7 -> K10 (auto-read z threading.local)
- LLM call counting: total_llm_calls, models_used, latency via thread-local trace ref
- DecisionTrace: goal, K7 decision, K10 safety, steps, duration
- TraceStore: JSONL persistence (meta_data/decision_traces.jsonl)
- Web UI: /traces page (tabela, statystyki, bledy, click-to-detail overlay)
- Telegram: /trace [N|stats|failed|ep-ID]
- 25 testow

### Phase 2: Memory Consistency (ADR-023)
- `agent_core/memory/query.py` - MemoryQuery API (unified query with provenance)
  - query_topic() - knowledge_index + beliefs + semantic vectors
  - get_topic_summary() - summary z confidence + freshness
  - get_knowledge_gaps() - low confidence beliefs + exam_failed files
- Grounding: GROUNDED_KNOWLEDGE mode ("co wiesz o X" -> EvidenceCollector -> MemoryQuery)
- Staleness fixy:
  - cleanup_stale_vectors() w indexer.py (startup)
  - beliefs rebuild_all() po LEARN (nie tylko EVALUATE)
  - incremental re-indexing po LEARN
- CDL w Web UI (learning intent detection, GoalStore direct write)
- Web UI: /api/memory/query, /api/memory/gaps
- Telegram: /memory <topic>, /memory gaps
- K12 StateCollector wired z MemoryQuery
- Memory hierarchy analysis: 34 zrodla danych zmapowane
- 24 testow

### Phase 3: Scheduler Hardening
- `agent_core/llm/execution_budget.py` - call_with_timeout() (ThreadPoolExecutor)
  - Ollama calls mialy ZERO timeout, teraz 120-180s per role
  - EpisodeBudget: max 10 LLM calls, 5min total latency per episode
- route_reason w LLM tape (dlaczego ten model wybrany)
- Degradation routing: REDUCED mode dopuszcza lekkie akcje (evaluate, maintenance)
  ale blokuje ciezkie LLM (learn, exam, creative, fetch)
- PlannerGuard: MIN_HEALTH_SCORE 0.7->0.5, heavy actions nadal wymagaja 0.7

### Phase 4: Autonomy Governance
- Cross-metric validation: ADOPT blocked jesli guard metric degraduje > 3%
  (retention_rate, system_stability, knowledge_coverage, learning_velocity)
- Promotion audit metadata: guard_metrics_checked, guard_degraded, promotion_requires
- Zapobiega metric gaming: poprawa jednej metryki kosztem innych = REJECT

### Inne
- 3 pliki edukacyjne przeniesione z docs/plans/ do input/
- Web UI /traces page - 3 taby, overlay detail, auto-refresh 30s
- Stabilization Roadmap PDF (docs/plans/) - plan Eryka z ChatGPT

## Stan testow
- Start sesji: 2081
- Koniec sesji: 2202
- Nowe testy: +121 (tracing: 25, memory: 24, planner guard: 2, reszta z istniejacych)

## 3 commity
1. `382105c` - Phase 1 Tracing + Phase 3 telemetry
2. `8f8da32` - Phase 2 Memory + CDL + Traces page
3. `81534ba` - Phase 3 budgets + Phase 4 cross-metric

## Nastepna sesja
- Phase 5: Effector safety envelope (staged authority levels for ClawBot)
- Phase 6: Full authority readiness review
- Restart Marii zeby nowe zmiany weszly (Phase 3 budgets, Phase 4 validation, degradation routing)
- Eryk moze przetestowac: /memory fizyka, /trace stats, /traces w Web UI

## Decyzje architektoniczne
- ADR-022: Episode-based tracing (thread-local correlation IDs)
- ADR-023: Unified memory query with provenance metadata
- Execution budgets: ThreadPoolExecutor + future.result(timeout=N)
- Degradation: REDUCED dozwala planner ale blokuje heavy LLM
- Cross-metric: GUARD_METRICS lista, MAX_DEGRADATION_PCT = -3%

## Uwagi
- Web UI traces page jest SUPER wedlug Eryka
- Maria caly czas dziala na produkcji (creative + learn traces potwierdzaja)
- LLM counting dziala: creative trace pokazal 3 calls do z-ai/glm5
- MemoryQuery wired ale wymaga restart (nowy PID) zeby wrocyc w syslog
