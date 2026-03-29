# 2026-03-29 - Faza F Multi-Source Learning COMPLETE + Roadmap v1.0

## Co zrobione

### Roadmap v1.0 (docs/ROADMAP.md)
- Aktualizacja z v0.6 (2026-03-01) do v1.0
- Dodane brakujace fazy: C.6 (K5-K13), C.7 (Infrastructure), C.8 (Stabilization)
- Milestones M5-M10, ryzyka zaktualizowane, ADR-001 do ADR-026

### Faza F: Multi-Source Learning - uzupelnienie triggera
Juz bylo (z poprzedniej sesji):
- CrossValidator, ConfidenceScorer, DisputeLog (38 testow)
- Homeostasis wiring (NIM secondary LLM)
- ActionExecutor._exec_validate() + _pick_validation_candidate()

Dodane dzis:
- **_maybe_validate()** w PlannerCore - 6h cooldown
- **last_validation_ts** w PlannerState (backward-compatible)
- **Belief confidence update** - OBSERVATION->FACT (>0.7), demotion HYPOTHESIS (<0.3)
- **VALIDATE w degradation check** - blokowane w REDUCED mode
- **World model wiring** - planner -> executor -> belief store
- **Web UI /validation** - 3 taby (stats, disputes, history) + 4 API endpoints
- **Telegram /validate** [disputes|unresolved] command
- **18 nowych testow** (trigger, cooldown, belief update, telegram)

### Testy: 2448 passing (zero regresji)

## Kluczowe decyzje
- Validation cooldown 6h (nie za czesto, nie za rzadko)
- Confidence blend: 60% existing + 40% validation score
- VALIDATE = heavy action (degradation check, jak LEARN/FETCH)
- K7: GUARDED, rate 5/h (juz bylo skonfigurowane)
- K10: SafetyProfile (juz bylo skonfigurowane)

## Stan Fazy F
COMPLETE. Wszystkie moduly:
- CrossValidator -> NIM secondary LLM
- ConfidenceScorer -> rule-based (Jaccard similarity)
- DisputeLog -> JSONL persistence
- Planner trigger -> _maybe_validate() z cooldownem
- Belief update -> BeliefStore.revise() po walidacji
- Web UI -> /validation page
- Telegram -> /validate command

## Belief Store v2 (ta sama sesja, po Faza F)

Zaimplementowane:
- **belief_model.py** - evidence field: `Tuple[Tuple[str, str, float], ...]` (backward-compatible)
- **belief_maintenance.py** (NOWY, ~310 lines):
  - `compact_jsonl()` - rewrite JSONL without superseded
  - `compute_belief_score()` - 4-factor: confidence + freshness + revision + references
  - `smart_prune()` - replaces naive confidence-only pruning
  - `compute_decayed_confidence()` - exponential decay (FACT 90d, OBS 30d, HYP 14d)
  - `apply_decay()` - batch, idempotent, min_delta=0.05
  - `find_exact_duplicates()` + `merge_duplicate_pair()` + `deduplicate()`
  - `run_maintenance()` - decay -> dedup -> prune -> compact
- **belief_store.py** - revise() merges evidence, _enforce_cap() uses smart_prune, compact()
- **belief_builder.py** - evidence populated in all build methods + update_from_exam
- **__init__.py** - compact(), apply_decay(), deduplicate(), maintain() facade methods
- **Planner** - maintain() po EVALUATE (~1/h)
- **Telegram** - /beliefs [gaps|maintain]
- **Web UI** - /api/beliefs/{stats,gaps,recent}

97 testow world_model (69 + 28 nowych), 2476 total.

## Co dalej
- CDL dopracowanie (Etap 1 roadmapy)
- Capability/Task Router (Etap 2)
- Vision/Smart Home czeka na sprzet
