# B0 / B0.1 Implementation Shortlist

> Status: starting-point shortlist, rev 4 (all open decisions closed by Eryk)
> Powstanie: 2026-05-09 (sobota), po commit `defabbf` (JEPA_MAPPING.md rev 3)
> Cel: złapać następny krok po JEPA_MAPPING — bez zamykania *wszystkich*
> decyzji implementacyjnych, bez kodu
> Poprzednik: `docs/MARIA_2.0/JEPA_MAPPING.md`
> Rev historia:
> - rev 1 (initial) — 10 punktów + 7 open decisions
> - rev 2 — 3 decisions closed (separate distances, decision_traces only,
>   throttled N-tick), 6 open (z 2 nowymi sub-questions)
> - rev 3 — 2 sub-questions closed (combined `max()`, throttling 60s),
>   4 open zostają (threshold calibration, cache strategy, numeric
>   features set, cosine reuse)
> - rev 4 — wszystkie 4 open decisions closed (threshold method/window/
>   cadence + warm-up, cache strategy, numeric features set, cosine
>   reuse). 0 open. Design pass complete

## 1. Proposed location

`agent_core/predictive/` — nowy moduł, nie istnieje. Cross-cutting,
analogicznie do `vision/`, `semantic/`, `critic/`. Bez K-numeru
(K16-K20 zarezerwowane dla Digital Human, K21 wolne ale nie obowiązkowe).

## 2. Minimal files for B0/B0.1

```
agent_core/predictive/
├── __init__.py
├── state_snapshot.py      # StateSnapshot dataclass + agregator
├── surprise_scorer.py     # B0 global cosine + threshold
├── action_baseline.py     # B0.1 action-aware z-score
├── bulletin_adapter.py    # emit BulletinEntry przez BulletinStore.post()
└── threshold_calibrator.py  # 7-dniowy okno → percentyle threshold

agent_core/tests/predictive/
├── __init__.py
├── test_state_snapshot.py
├── test_surprise_scorer.py
├── test_action_baseline.py
├── test_bulletin_adapter.py
└── test_threshold_calibrator.py
```

`threshold_calibrator.py` dorzucone bo kalibracja to osobna troska — nie
chcemy hard-coded magic numbers w surprise_scorer. Decyzja czy oddzielny
plik czy method na scorerze: do design pass.

## 3. Existing sources to read (READ-ONLY)

| Źródło | Path | Co dostajemy |
|---|---|---|
| Homeostasis events | `meta_data/homeostasis_events.jsonl` | tick events, mode, cpu, ram, health_score |
| Decision traces | `meta_data/decision_traces.jsonl` | `action_type`, `goal_id`, `mode`, `success`, `duration_ms`, `health_score`, `tick_count` |
| Planner decisions | `meta_data/planner_decisions.jsonl` | pre-execution decisions, classification (READ for context) |
| K6 beliefs store | `agent_core/world_model/belief_store.py` (API: `query`, `get_active`) | active beliefs snapshot |
| K3 goals store | `agent_core/goals/...` (verify exact module w design pass) | active goals |
| Embedding model | `agent_core/semantic/embedding_model.py` (`EmbeddingModel.embed`, `cosine_similarity`) | nomic-embed-text 768-dim, cache built-in |

**Nie czytamy:** Telegram chat history, Web UI state, OpenClaw subprocess.
Domena predictive ogranicza się do core homeostasis state.

## 4. B0 — global heuristic surprise

**Separate distances, not concat** (decyzja Eryka 2026-05-09 #1):

```
state_t   = StateSnapshot.from_current_context()
state_t1  = StateSnapshot.last_cached() or None
if state_t1 is None:
    return  # cold start, no surprise yet

semantic_distance = 1 - EmbeddingModel.cosine_similarity(
    state_t.semantic_embedding(), state_t1.semantic_embedding())

numeric_distance  = normalized_numeric_distance(
    state_t.numeric_vector(), state_t1.numeric_vector())
    # np. euclidean over per-feature z-scored vectors

if semantic_distance > semantic_threshold or numeric_distance > numeric_threshold:
    bulletin_adapter.emit_surprise(
        semantic_distance=semantic_distance,
        numeric_distance=numeric_distance,
        source="b0_global", ...)
```

`semantic_threshold`, `numeric_threshold` osobne z `threshold_calibrator`.
**Method dla B0 global: 95-percentyl** (decyzja Eryka 2026-05-09 #7a) —
bez Gaussian assumption (raw cosine distance ma długi ogon w SLEEP/mode
transitions). **Window: rolling 7d** (#7b), no floor at start — drift
protection = future enhancement. **Recalibration: per-day** (#7c), batch
raz dziennie. Scoring nadal throttled 60s (#6).

**Warm-up mode** (decyzja #7d) gdy global calibration ma N<200 samples
(semantic LUB numeric distribution): scorer loguje diagnostykę ale NIE
emituje high-confidence surprise. Domyślnie no emit do zakończenia warm-up;
diagnostyka idzie do logu (nie bulletin) dla audit.

Trigger condition (po wyjściu z warm-up): `semantic_distance >
semantic_threshold` LUB `numeric_distance > numeric_threshold`. Combined
surprise formula `max(z_semantic, z_numeric)` (decyzja #5b) dotyczy ścieżki
B0.1 — w B0 global nie ma z-score, są raw distance vs percentile threshold.
**Raw sub-scores zawsze visible** w bulletin payload.

**Frequency: NIE per-tick** (decyzja Eryka 2026-05-09 #2):
- Throttled time-window. **Default initial: 60 sekund** (decyzja Eryka
  2026-05-09 #6) — predictive scoring nie naciska homeostasis ani nie
  woła nomic za często. Future tuning po 7-day observation
- Predictive scoring **MUSI** never block/overload homeostasis (anti-pattern:
  dorzucenie tick budget overruns)
- **Skip conditions** (gdy łatwo dostępne):
  - mode == SLEEP → skip
  - mode == REDUCED → skip lub bardzo rzadko (np. co N×2)
  - cpu_percent > 80% (z `homeostasis_summary`) → skip
  - ram_gb > 26GB (4GB safety margin) → skip
  - tick overrun w ostatnich 3 tickach → skip
- Implementacja skip: cheap pre-check przed nomic call, nie po. Embedding
  call to dominujący koszt

## 5. B0.1 — action-aware baseline

**Source: `decision_traces.jsonl` only** (decyzja Eryka 2026-05-09 #3 —
ma `action_type`, `success`, `duration_ms`, `tick_count`. Planner_decisions
NIE w B0.1, oznaczone jako future enrichment).

**Separate distance distributions per (action_type, distance_type)**:

```
action_type = last_decision.action_type   # z decision_traces.jsonl
historical_semantic = action_baseline.get_distribution(action_type, "semantic")
historical_numeric  = action_baseline.get_distribution(action_type, "numeric")

if historical_semantic.n < 20 or historical_numeric.n < 20:
    fallback to B0 (global, oba distances)
else:
    z_semantic = (current_semantic - historical_semantic.mean) / max(historical_semantic.std, eps)
    z_numeric  = (current_numeric  - historical_numeric.mean)  / max(historical_numeric.std, eps)
    
    if abs(z_semantic) > sigma_threshold or abs(z_numeric) > sigma_threshold:
        bulletin_adapter.emit_surprise(
            z_semantic=z_semantic, z_numeric=z_numeric,
            semantic_distance=current_semantic, numeric_distance=current_numeric,
            source="b0_1_action", action_type=action_type, ...)
```

Distribution per `(action_type, distance_type)` budowana z
`decision_traces.jsonl` przy starcie (rebuild on init, no persist) +
maintenance N-tick (rolling buffer, in-memory).

`sigma_threshold`: empirycznie z 7-dniowego okna, target ~2-3 sigma.

**Frequency**: dziedziczone z B0 throttling + skip conditions (punkt 4).
B0 i B0.1 dzielą tę samą execution policy — predictive layer odpala raz
na N-tick i wykonuje obie ścieżki ze wspólnymi state_t/state_t-1.

**Warm-up cascade** (decyzja #7d): B0.1 fallback do B0 gdy action_type
N<20. Jeśli B0 też w warm-up (global N<200), całość scorera jest w
warm-up — emisja high-confidence surprise zablokowana, diagnostyka
logowana. Cold-start safe.

## 6. Output

**Tylko bulletin emit. Zero direct action execution.**

Bulletin payload **musi** zawierać raw sub-scores (decyzja Eryka 2026-05-09
#1 — combined nie zastępuje sub-score visibility):

```python
bulletin_adapter.emit_surprise(
    # Raw sub-scores (zawsze obecne):
    semantic_distance=...,    # cosine-based, 0..1
    numeric_distance=...,     # euclidean over z-scored numeric features
    
    # Action-aware z-scores (tylko gdy source="b0_1_action"):
    z_semantic=...,           # None dla b0_global
    z_numeric=...,            # None dla b0_global
    
    # Combined surprise — default max(z_semantic, z_numeric):
    combined_surprise=...,
    
    # Numeric features faktycznie użyte (decyzja Eryka 2026-05-09 #9):
    numeric_features_used=[...],  # subset z {cpu_percent, ram_gb,
                                  # error_count_window, n_active_goals,
                                  # mode_index} dostępnych w tym round
    
    # Optional diagnostic (NIE wchodzi do distance computation):
    health_score=...,         # z decision_traces dla audit;
                              # None gdy niedostępny
    
    # Context:
    source="b0_global" | "b0_1_action",
    action_type=...,          # None dla b0_global
    state_t_summary=...,      # short text, dla audit
    state_t1_summary=...,
    timestamp=...,
    episode_id=...,           # z thread-local tracing (ADR-022)
)
```

→ `BulletinStore.post(BulletinEntry(type="surprise", payload={...}))`.

Combined surprise: **`max(z_semantic, z_numeric)` jako default** (decyzja
Eryka 2026-05-09 #5) — konserwatywny: alarm gdy KTÓRYKOLWIEK kanał
przekracza próg, sygnał z silniejszego kanału przechodzi w całości.
Weighted formula (`α*z_semantic + β*z_numeric`) = future tuning po
calibration data. **Constraint**: combined NIGDY nie zastępuje sub-scores
w payloadzie — audit musi widzieć z czego się składa.

K9 consumer w przyszłości (B4 stage), NIE w B0/B0.1. K9 dziś może
zignorować surprise events bezboleśnie.

K7/K10/K12 integration — NONE w B0/B0.1.

## 7. Tests

| Test | Co weryfikuje |
|---|---|
| `test_state_snapshot_from_fake_context` | StateSnapshot agreguje z dict-mocków poprawnie, dual repr działa |
| `test_normal_transition_no_surprise` | Małe delta → no bulletin emit |
| `test_large_unexpected_jump_emits` | Duże delta global → surprise event |
| `test_action_aware_expected_jump_no_emit` | High distance ale matchuje action_type historical → no emit |
| `test_action_aware_unexpected_jump_emits` | High distance + odbiegające od action_type historical → emit |
| `test_rare_action_falls_back_to_global` | n_action<20 → fallback B0 path |
| `test_no_data_graceful_degradation` | brak `decision_traces.jsonl` / pusty plik → no crash, log warning |
| `test_cold_start_skip` | Pierwszy tick (no state_t-1) → silent skip |
| `test_sleep_mode_skip` | Mode=SLEEP → no embedding calls (perf) |
| `test_threshold_calibrator_window` | Calibrator daje sensowny percentyl na fixed dataset |

Cel: ≥10 testów, full happy-path coverage + 4 edge cases. Pasują do
istniejącej pytest infra (`agent_core/tests/`).

## 8. Decisions

### Closed by Eryk 2026-05-09 (przed kodem)

| # | Decyzja | Rezolucja |
|---|---|---|
| 1 | Semantic + numeric representation | **Separate distances** (NIE concat). Cosine na semantic + normalized euclidean/z-score na numeric. Bulletin payload zawiera raw sub-scores zawsze visible. Combined `max()` (zob. #5), ale sub-scores zostają |
| 3 | Action_type source | **`decision_traces.jsonl` only** dla B0.1 (ma action_type, success, duration_ms, tick_count). `planner_decisions.jsonl` jako future enrichment, NIE w B0/B0.1 |
| 5 | Frequency | **Throttled time-window**, NIE per-tick. Skip conditions: SLEEP, REDUCED, cpu>80%, ram>26GB, recent tick overruns. Predictive layer NIGDY nie blokuje homeostasis |
| 5b | Combined surprise formula | **`max(z_semantic, z_numeric)` jako default** dla B0/B0.1. Reason: konserwatywne wykrywanie — jeśli KTÓRYKOLWIEK kanał wykryje silne surprise, combined zachowuje sygnał. Weighted formula = future tuning po calibration data exists |
| 6 | Throttling initial value | **60 sekund interval** jako first default. Reason: predictive scoring nie naciska homeostasis ani nie woła nomic za często. Future tuning po 7-day observation |
| 7a | Threshold method | **Hybryda**: B0 global percentile-based (95-percentyl), B0.1 sigma z-score per `(action_type, distance_type)`. Raw cosine distance ma długi ogon → no Gaussian assumption dla globalnego. B0.1 z definicji liczy z-score więc sigma threshold natural fit |
| 7b | Threshold window | **Rolling 7d**, no floor at start. Floor/drift protection (np. minimum threshold = initial calibration) = future enhancement po obserwacji 30+ dni |
| 7c | Recalibration cadence | **Per-day** (raz dziennie batch recompute). Per-tick overkill, per-restart stale przy długim uptime. Scoring nadal throttled 60s (#6). Ad-hoc trigger przy false-positive burst = future enhancement |
| 7d | Warm-up mode | Gdy global calibration N<200 samples LUB action_type N<20 (B0.1): scorer loguje diagnostykę, NIE emituje high-confidence surprise. B0.1 N<20 fallback do B0; jeśli B0 też w warm-up, cała ścieżka warm-up. Zapobiega false-positive flood przy cold start |
| 8 | Cache strategy | **In-memory only**, rebuild z bounded 7-day window logs przy starcie. No `predictive_cache.json`, no new SSoT. Spójne z JEPA_MAPPING ("snapshots NIE persistowane"). Jeśli rebuild za drogi → predictive startuje w warm-up mode i nie blokuje homeostasis. Background rebuild thread = future enhancement |
| 9 | Numeric features set | **5 features na start**: `cpu_percent, ram_gb, error_count_window, n_active_goals, mode_index`. Per-feature z-score przed numeric distance. Missing feature → skip (no crash), oznaczone jako unavailable. Event payload zawiera `numeric_features_used=[...]` listę faktycznie użytych. `health_score` = optional diagnostic field, NIE feature do distance computation. Pozostałe 4 features z JEPA_MAPPING (`ram_growth_rate`, `heartbeat_age_sec`, `n_active_beliefs`, `tick_overrun_count`) odłożone — redundant lub low-signal |
| 10 | Cosine similarity reuse | **Direct import** z `agent_core/semantic/embedding_model.py` (`EmbeddingModel.cosine_similarity` static, line 154). Lokalna konwersja `distance = 1 - cosine_similarity(a, b)` inline w surprise_scorer. No wrapper file unless circular import surfaces |

### Open

(none — wszystkie 4 decisions closed w rev 4, 2026-05-09. Patrz #7a-7d, #8, #9, #10)

## 9. Explicit constraints (z JEPA_MAPPING.md, hard limits)

- ❌ Brak neural predictora (B3 odłożony)
- ❌ Brak SIGReg (czeka na method-section verify)
- ❌ Brak K10/K4 integration (poza scope B0/B0.1)
- ❌ Brak nowego SSoT (`transitions.jsonl` derived/lazy gdyby się pojawił,
  cache in-memory only, snapshots NIE persistowane)
- ❌ Brak GPU dependency (CPU-only, embedding via Ollama)
- ❌ Brak zmian w istniejących modułach (predictive jest cross-cutting,
  read-only consumer; emit tylko przez istniejące BulletinStore API).
  **Doprecyzowanie (2026-05-09):** "no behavior change". Additive
  rozszerzenia konieczne dla output contract z punktu 6 są dozwolone —
  w szczególności `EntryType.SURPRISE` w `bulletin/bulletin_model.py`
  (1-line enum value, no semantic change for existing types). Adapter
  emituje SURPRISE; istniejące paths nie są dotknięte
- ❌ Brak kodu do następnej explicit approval Eryka

## 10. Status

Ready for implementation. Wszystkie open decisions closed w rev 4
(2026-05-09).

Następny krok (po explicit Eryk approval):
- Start kodu w `agent_core/predictive/`, commit-by-commit
- Tests równolegle z każdym modułem
- Pierwszy commit kandydat: `state_snapshot.py` + jego test (foundation,
  zero zależności od reszty modułów predictive)
