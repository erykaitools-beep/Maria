# 2026-03-30 - Faza G: Agent Krytyk (Knowledge Quality Gate)

## Co zrobilem

### Nowy modul: agent_core/critic/ (4 pliki)

**critique_model.py** - modele danych:
- 7 kategorii FindingCategory: CONTRADICTION, OVERCONFIDENT, UNDERCONFIDENT, SHALLOW_KNOWLEDGE, UNRESOLVED_DISPUTE, COVERAGE_GAP, STALE_KNOWLEDGE
- 3 severity levels: CRITICAL, WARNING, INFO
- CritiqueFinding (frozen): dedupe_key, topic_normalized, evidence_sources, volatility_hint
- CritiqueReport (mutable): findings_total, findings_by_category/severity, suppressed_duplicates
- GOAL_TITLE_MAP: pol tytuly goali per category

**knowledge_critic.py** - silnik analizy (READ-ONLY, zero LLM, zero side effects):
1. CONTRADICTION - negation patterns (PL+EN), numeric conflicts, type/confidence gap
2. OVERCONFIDENT - confidence > 0.7 + no exam / weighted exam < 0.5
3. UNDERCONFIDENT - confidence < 0.4 + weighted exam >= 0.7
4. SHALLOW_KNOWLEDGE - brak facts, single source, brak exam + dispute resolution
5. UNRESOLVED_DISPUTE - >= 2 high-severity unresolved z DisputeLog
6. COVERAGE_GAP - partially learned / completed bez exam (3-day grace period)
7. STALE_KNOWLEDGE - decayed confidence < 0.15 (mirrored decay formula)

Top 5 findings, sorted severity -> evidence count, deduped po dedupe_key.

**critique_applier.py** - PROPOSED goals + LLM summary:
- Polityka: CRITICAL -> goal always, WARNING -> only if no existing similar, INFO -> never
- Idempotencja: sprawdza dedupe_key + topic_normalized w existing goals
- LLM summary = dekoracja (nie wplywa na decyzje, failure nie blokuje)
- Max 3 goals per report

**__init__.py** - CriticAgent facade:
- run_critique() -> KnowledgeCritic.analyze() -> CritiqueApplier.apply() -> persist JSONL
- should_critique(): 8h periodic, post_validation, post_maintenance (min 1h)
- Persistence: meta_data/critique_reports.jsonl

### Integracja (8 plikow zmodyfikowanych)
- planner_model.py: ActionType.CRITIQUE + PlannerState.last_critique_ts
- capability_spec.py: CapabilitySpec "critique" (guarded, 14 total)
- handlers.py: make_critique_handler() + Telegram notify (CRITICAL only)
- planner_core.py: set_critic_agent() + _maybe_critique() + CRITIQUE_INTERVAL_SEC=28800
- action_executor.py: set_critic_agent() + _exec_critique() legacy fallback
- homeostasis_module.py: wiring (belief_store, dispute_log, goal_store, NIM llm_fn)
- telegram/notifier.py: notify_critique() z cooldownem
- 3 test files: count fixes 13->14

### Kolejnosc w cyklu planner:
evaluate -> validate -> **critique** -> self_analyze -> creative -> noop

## Kluczowe decyzje (z feedbacku Eryka)
- ADR-028: Coherence/calibration critic, NOT truth engine
- 7 wymiarow (nie 6 jak w pierwszym planie)
- KnowledgeCritic jest czysto READ-ONLY, CritiqueApplier jedyne miejsce z side effects
- Model kontradykcji: same entity + comparable predicate + conflicting value (nie kazda roznica)
- Per-topic kalibracja (weighted recent exam, nie globalny prog)
- Coverage gap z 3-dniowym grace period (nie flaguj swiezych plikow)
- Stale knowledge z volatility_hint w metadata
- dedupe_key na CritiqueFinding przeciw spamowi
- WARNING -> goal tylko warunkowo (nie kazdy warning tworzy goal)
- LLM summary = dekoracja, nie wplywa na severity/action/goal

## Testy
- Start sesji: 2566
- Koniec: 2635 (+69)
- Nowe: 11 model, 6 contradiction, 5 overconfident, 3 underconfident, 4 shallow,
  4 disputes, 5 coverage, 4 stale, 4 integration, 8 applier, 10 facade, 5 integration

## Dodatkowe fixy w tej sesji

### Priority fix (b90c466)
- Conversation goals mialy priority=0.8, seed goal-meta-learn ma 1.0
- Z aging cap 4.0: user max = 0.8*5 = 4.0 vs meta 1.0*5 = 5.0 -> user NIGDY nie wygrywa
- Fix: conversation_learning.py priority 0.8 -> 1.1
- Reczna naprawa celu Eryka: goal-cbcb2f0d5a47 (system kognitywny, AGI) pri=1.1, status=active

### FETCH topics fix (8a28e75)
- Gdy conversation goal triggeruje FETCH (brak plikow), tematy usera byly ignorowane
- TopicSuggester bral wlasne tematy z istniejacvej wiedzy zamiast szukac tego co user poprosil
- Fix: run_fetch_session() dostaje override_topics z plan.action_params["topics"]
- Tematy usera prepended przed auto-sugestiami

## Nastepna sesja - Upgrade pipelinu nauki

**Problem:** Wikipedia to slabe zrodlo. Maria ma ASK_EXPERT (NIM/Codex) ale nie uzywa go
w kontekscie celow nauki od usera.

**Nowy flow:**
```
user topic -> sprawdz co Maria juz wie (MemoryQuery/beliefs)
           -> opcjonalnie test z istniejacej wiedzy
           -> zaplanuj luki (co brakuje)
           -> ASK_EXPERT (NIM/Codex - najsilniejszy model)
              z precyzyjnym promptem: "Maria wie X, potrzebuje Y"
           -> material do input/ -> standardowy learn pipeline
```

**Kluczowe:**
- Wikipedia zastapiona przez encyklopedie (ASK_EXPERT) z kontekstem
- Najsilniejszy model generuje material celowany w luki
- Maria wie co juz umie i czego nie wie -> prompt jest precyzyjny
- Reszta (chunking, learning, exam) zostaje bez zmian
