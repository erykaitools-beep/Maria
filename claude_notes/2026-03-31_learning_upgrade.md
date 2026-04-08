# 2026-03-31: Learning Upgrade Phase 1-3 + NOOP fix

## Co zrobione
1. **Goal pivot fix** - planner nie zapetla sie w NOOP gdy top goal jest rate-limited (4 testy)
2. **Daemon via systemd** - restart z Telegram dziala poprawnie
3. **Phase 1: Cognitive Bulletin Board** - agent_core/bulletin/ (model, store, wiring, /board, /api/bulletin) - 32 testy
4. **Phase 2: Knowledge Auditor** - audit_topic() sprawdza MemoryQuery, beliefs, critic, exams -> AuditReport z 7 typami luk - 11 testow
5. **Phase 3: Gap Planner** - czyta audit, decyduje: ASK_EXPERT (z context prompt), REVIEW, RUN_EXAM, DECOMPOSE, WAIT_HUMAN - 14 testow

## Kluczowe pliki
- agent_core/bulletin/bulletin_model.py - BulletinEntry, 5 EntryTypes
- agent_core/bulletin/bulletin_store.py - JSONL store, dedup, queries
- agent_core/bulletin/knowledge_auditor.py - 7 gap types, zero LLM
- agent_core/bulletin/gap_planner.py - GapAction(7), context_prompt builder
- meta_data/cognitive_bulletin.jsonl - persistence

## Pipeline flow (Phase 3)
```
topic -> KnowledgeAuditor.audit_topic() -> AuditReport
  -> GapPlanner.plan_for_topic() -> GapPlan(action, context_prompt)
    -> BulletinStore.create_and_post() -> bulletin entry
```

## Co dalej (Phase 4+5)
- Phase 4: Expert Bridge - NIM/Codex z context_prompt ("Maria wie X, potrzebuje Y")
- Phase 5: Material zapisuje sie do input/, standard learn pipeline
- Kluczowe: context_prompt juz jest generowany przez GapPlanner, Phase 4 tylko go uzywa

## Obserwacje
- Plan od ChatGPT (plan_upgrade_nauki_maria.pdf) byl dobry, 5 faz realistycznych
- Eryk planuje z ChatGPT/Grok, egzekucja tutaj - efektywny workflow
- Bulletin board jest pusta na produkcji (0 entries) bo Maria ma materialy - aktywuje sie dopiero przy wyczerpaniu zrodel
- 2650 testow passing, 4 commity w sesji
