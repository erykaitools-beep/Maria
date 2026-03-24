# Sesja 2026-03-24 - K12 Working + Creative Module Spec

## K12 Self-Analysis - DZIALA!

Po wielu iteracjach debugging, K12 odpalilo poprawnie o 18:47.
Maria przeanalizowala sie sama uzywajac qwen3:8b (local_planner) i zwrocila 3 rekomendacje:
1. Knowledge gap w meta-cognitive system understanding (10% confidence)
2. Knowledge gap w logice formalnej
3. Strategy change - system stability drop

### Bugi naprawione po drodze:
1. `project_root` undefined w homeostasis_module K12 wiring -> uzyj `BASE_DIR` z config
2. `_brain` variable shadowing (OllamaBrain zamiast LLMRouter) -> renamed to `_sa_brain` + default arg
3. `"planner"` string zamiast ModelRole enum w `ask_as_role()` -> router.py konwertuje string na enum
4. Planner fallthrough bug - K12 nieosiagalne gdy goal istnieje -> NOOP/K7-blocked fallthrough
5. K12 cooldown za dlugi na debugging -> zmniejszone, przywrocone na 4h

### Inne fixy tej sesji:
- `learn_next_chunk()` - nowy parametr `target_file_id`
- `teacher_module.py` - przekazuje file_id
- Chunk failure backoff - po 5 failach chunk skipowany z markerem
- 10 nowych testow (1813 total)

### Produkcyjne cooldowny (po testach):
- K12 periodic interval: 4h (SELF_ANALYSIS_INTERVAL_SEC = 14400)
- K12 min cooldown: 10min
- DEFAULT_COOLDOWN_SEC w self_analysis: 4h

### Znany problem:
- test_web_source::test_suggest_empty_topic_map failuje gdy topic_hints.jsonl ma dane
  (test czyta prawdziwy plik zamiast tmp_path - potrzebna izolacja)

## Creative Module Spec

Eryk wyslal pelna specyfikacje (10 stron PDF) w `docs/plans/MARIA_Creative_Module_Developer_Technical_Spec.pdf`.

Kluczowe decyzje:
- 19 plikow w agent_core/creative/ - pelny organ, nie MVP
- LLM: qwen3:8b (PLANNER role) - potrzebna pamiec meta-celow od poczatku
- Integracja: Phase 11 w tick loop, po planner
- K12 jest inputem do Creative (dane -> interpretacja -> kierunek)
- Testowanie w izolacji, jeden deploy na produkcji
- Eryk: "Maria jest jak organizm" - nie wszczepias polowy serca

### Overlap z istniejacym kodem:
- conversation_memory.py -> reuse istniejacy z consciousness
- identity_profile.py -> extend consciousness_identity.json
- GoalStore integration -> K3 PROPOSED flow juz istnieje
- PersonalitySignal -> mapowanie na TraitCatalog

### Plan implementacji:
1. creative_model.py (dataclasses, enums)
2. strategic_context.py + tension_detector.py
3. reflection_workspace.py + creative_journal.py + conversation_memory.py
4. novelty_filter.py + creative_evaluator.py
5. meta_goal_engine.py + reframe_engine.py + exploration_engine.py
6. goal_adapter.py + event plumbing
7. Testy
