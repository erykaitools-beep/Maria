# 2026-03-28 - Phase 1: Decision Traceability

## Co zrobilem

Zaimplementowalem Phase 1 ze Stabilization Roadmap (plan Eryka z ChatGPT):
**"Unified observability and decision traces"**

### Nowy pakiet: `agent_core/tracing/`
- `episode.py` - thread-local episode_id (generowany per cykl plannera)
- `trace_model.py` - DecisionTrace + TraceStep dataclasses
- `trace_store.py` - JSONL persistence (meta_data/decision_traces.jsonl)

### Episode ID flow
Planner.run_cycle() generuje episode_id -> przeplywa przez:
- Plan.trace_id (wczesniej zawsze None, teraz ustawiony)
- LLM Tape - TapeEntry.episode_id (auto-read z thread-local)
- K7 Autonomy - EscalationRecord.episode_id (auto-read)
- K10 Action Safety - ActionRecord.episode_id (auto-read)

### Wiring
- homeostasis_module.py -> TraceStore tworzony i podpiety do plannera
- SharedContext.trace_store -> dostepny dla Telegrama i Web UI

### Interfejsy operatorskie
- Web UI: 4 endpointy (/api/traces, /api/traces/<id>, /api/traces/stats, /api/traces/failed)
- Telegram: /trace [N|stats|failed|ep-ID]
- /help zaktualizowany

### Testy
- 25 nowych testow (test_tracing.py)
- 2176 total passing (was 2081)

### Bug naprawiony po deploy
SafetyMode enum nie byl JSON-serializowalny - dodal .value conversion.
Validation z after_action() jest dict, nie string - poprawiony na dict.get().

### Produkcja
Po 2 restartach trace'y sie generuja. Pierwszy trace z produkcji:
- ep-69c7ea06-c3982cce: CREATIVE, 18.6s, K7:allow, K10:valid, 4 steps

## Decyzja architektoniczna
ADR-022: Episode-based tracing. Thread-local episode_id (nie argument passing).
Kazdy subsystem auto-czyta episode_id z threading.local().
Backward compatible - jesli episode_id jest pusty, omijany w serializacji.

## Phase 2 - zrobione w tej sesji

### MemoryQuery API (agent_core/memory/query.py)
- query_topic() - szuka w knowledge_index + beliefs + semantic vectors
- get_topic_summary() - zwiezle podsumowanie
- get_knowledge_gaps() - luki w wiedzy
- 24 testow

### Staleness fixy
- A: cleanup_stale_vectors() w indexer.py (startup)
- C: beliefs rebuild_all() po LEARN (nie tylko EVALUATE)
- Incremental re-indexing po LEARN w action_executor

### Grounding pipeline
- GROUNDED_KNOWLEDGE mode w query_router.py
- "co wiesz o fizyce" -> EvidenceCollector -> MemoryQuery -> evidence
- ResponseBuilder._build_knowledge()

### CDL w Web UI
- detect_learning_intent() przed brain.think()
- GoalStore.create() z Web UI (oddzielny proces)

### Interfejsy
- Web UI: /api/memory/query, /api/memory/gaps
- Telegram: /memory <topic>, /memory gaps
- K12 StateCollector.set_memory_query() - unified gaps

## Phase 3 - scheduler telemetry

### Route reason logging
- TapeEntry.route_reason (opcjonalne pole w LLM tape)
- Kazdy LLM call loguje dlaczego ten model:
  - chat_always_ollama
  - nim_budget_ok / nim_unavailable_or_budget / nim_fallback
  - scheduler:<role>:<model> / scheduler_fail:<reason>
- Backward compatible (omit empty)

## Pliki ze stabilization roadmap
Eryk przyniosl docs/plans/MARIA_full_scale_stabilization_roadmap.pdf
(zrobiony z ChatGPT 2026-03-27). Dobrze przemyslany plan 6 faz:
1. Observability (DONE - this session)
2. Memory consistency
3. Scheduler governance
4. Autonomy governance
5. Effector safety envelope
6. Full ClawBot authority

Przenioslem tez 3 pliki txt z docs/plans/ do input/ (materialy edukacyjne).
