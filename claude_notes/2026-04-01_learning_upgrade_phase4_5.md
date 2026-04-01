# 2026-04-01: Learning Upgrade Phase 4-5 (Expert Bridge + Full Wiring)

## Co zrobione
1. **Phase 4: ExpertBridge** (`agent_core/bulletin/expert_bridge.py`)
   - Full pipeline: topic -> audit -> gap plan -> enhanced prompt -> LLM -> response
   - Uses context_prompt from GapPlanner ("Maria wie X, potrzebuje Y")
   - Three prompt modes: enhanced (from gap planner), from-scratch, generic fallback
   - Graceful degradation: works without auditor/gap_planner (just uses generic prompt)
   - 27 tests

2. **Phase 5: Full Wiring**
   - `make_ask_expert_handler` accepts `expert_bridge` + `bulletin_store`
   - `_exec_ask_expert` in ActionExecutor also uses ExpertBridge (dual path)
   - Bulletin NEED_MATERIAL entries resolved after successful expert call
   - Homeostasis init: ExpertBridge wired with auditor + gap_planner + ask_encyclopedia
   - CapabilityRouter registration updated
   - 11 new integration tests

## Kluczowe pliki
- `agent_core/bulletin/expert_bridge.py` - ExpertBridge, ExpertResponse
- `agent_core/bulletin/__init__.py` - updated exports
- `agent_core/routing/handlers.py` - make_ask_expert_handler + _resolve_bulletin_need
- `agent_core/planner/action_executor.py` - _exec_ask_expert, set_expert_bridge, _resolve_bulletin_need
- `agent_core/modules/homeostasis_module.py` - ExpertBridge creation + LLM wiring
- `agent_core/tests/test_expert_bridge.py` - 27 tests
- `agent_core/tests/test_ask_expert.py` - 11 new tests (total 25)

## Pipeline flow (complete)
```
topic -> KnowledgeAuditor.audit_topic() -> AuditReport
  -> GapPlanner.plan_for_topic() -> GapPlan (context_prompt)
    -> ExpertBridge.ask_about_topic() -> ExpertResponse
      -> save_expert_response() -> input/expert_{slug}.txt
        -> _resolve_bulletin_need() -> bulletin entry RESOLVED
          -> standard learn pipeline picks up new file
```

## Kluczowa zmiana
Przed: ASK_EXPERT -> "Wyjasnij w 3-5 zdaniach: {topic}" (generic)
Po: ASK_EXPERT -> "Maria wie o mechanice (3 pliki, confidence 60%). Problemy: niski confidence. Potrzebuje poglebionego materialu o optyce." (targeted)

## Learning Upgrade COMPLETE
All 5 phases from ChatGPT plan (plan_upgrade_nauki_maria.pdf) are now done:
- Phase 1: Bulletin Board (visibility)
- Phase 2: Knowledge Auditor (audit)
- Phase 3: Gap Planner (decisions)
- Phase 4: Expert Bridge (targeted LLM queries)
- Phase 5: Full wiring (save to input/, bulletin update)

## Stan
- 2730 testow passing (was 2635)
- 95 nowych testow w tej i poprzedniej sesji
- 0 failures
