# 2026-03-19 - K8 Deliberation / Strategic Planning

## Kontekst
Sesja z Erykiem. Po K7 (Autonomy Policy) przeszlismy do K8.
Eryk zatwierdzil plan v1 pod warunkiem latwe rozszerzalnosci.

## Kluczowe decyzje rozszerzalnosci
- Strategy.steps: v1 lista -> v2 DAG (step.next_on_success/fail)
- Templates: v1 rejestr funkcji -> v2 LLM-generated
- Warunki: v1 Enum (PASS/FAIL/TIMEOUT) -> v2 expressions (confidence > 0.7)
- Deliberator: v1 rule-based -> v2 LLM select_strategy()
- Integracja: v1 advisory (optional) -> v2 primary -> v3 replacement

## Plan K8

### Struktura
```
agent_core/deliberation/
    __init__.py              # Deliberation facade
    strategy.py              # Strategy + Step dataclasses
    strategy_templates.py    # Gotowe szablony (learn_topic, explore, consolidate)
    deliberator.py           # Tworzy/aktualizuje strategie z kontekstu
    intent_tracker.py        # Sledzi intencje (dlaczego robimy X)
```

### Strategy Templates (v1)
- learn_topic: LEARN -> EXAM -> (pass? complete : REVIEW -> EXAM)
- explore_new: FETCH -> LEARN -> EXAM
- consolidate: REVIEW weak topics -> EXAM -> update beliefs

### Integracja
- PlannerCore._create_plan_for_goal() pyta deliberator o nastepny krok
- Jesli jest aktywna strategia -> uzyj next step
- Jesli nie -> fallback na _decide_learning_action()
- deliberator=None = stare zachowanie (backward compatible)

### Zasady
- Zero LLM (ADR-013)
- Strategie jako data (ADR-011)
- Backward compatible
- JSONL persistence (deliberation_intents.jsonl)

## Implementacja
- strategy.py: Step, StepStatus, StepOutcome, Strategy, StrategyStatus + fabryki
- strategy_templates.py: 3 szablony + TEMPLATE_REGISTRY + get_template/list_templates
- intent_tracker.py: IntentRecord + IntentTracker (JSONL, bounded 500)
- deliberator.py: Deliberator (select/advance/abandon, rule-based matching)
- __init__.py: Deliberation facade
- Wiring: PlannerCore.set_deliberation(), _consult_deliberation(), report_step_outcome
- Plan.metadata field added for strategy_id tracking
- SharedContext.deliberation field
- homeostasis_module.py K8 wiring block

## Testy
- 49 nowych testow (test_deliberation.py)
- 1288 total (1239 + 49)
- Zero regresji

## Obserwacje
- K8 jest "advisory" - jesli Deliberator nie ma strategii, planner uzywa starego kodu
- IntentTracker pozwala unikac powtarzania tych samych podejsc (3x abandoned = skip)
- Template matching: new_files -> explore_new, weak_topics -> consolidate, topic -> learn_topic
- Max 10 active strategies, max 5 per goal (trimming oldest terminal)

## Nastepne kroki
- K9: Meta-Cognition (uncertainty, self-reflection)
- K10: Action Safety Layer
- Potem: Vision, Smart Home
