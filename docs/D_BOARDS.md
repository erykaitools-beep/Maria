# D-Boards Registry (Maria 1.0)

> Iteracyjne deski (statek Tezeusza) — każda to małe, mierzalne naprawianie
> konkretnej fragmentacji lub gapa. Lista rośnie. Kolejność = priorytet.
>
> Status: DONE (commit), PLANNED (decyzja tak), IDEA (do rozważenia),
> BLOCKED (czeka na coś zewnętrznego)

## Ukończone

### D1 — Learning window guard at plan creation
**DONE** 2026-04-21, commit `df28a52`
Problem: 54 outside_window fails w 72h na poziomie executora.
Fix: `LEARNING_WINDOW_ACTIONS` frozenset + `_enforce_learning_window()`
w plannerze. Redirect do NOOP zanim plan trafi do executora.
Verification post 22.3h: 0 outside_window fails (target <10% = PASS).

### D1.5 (composite — a2 + garbage filter + saturation META)
**DONE** 2026-04-21, commits `d485417` + cleanup scripts
- A2: usunięto 6 garbage plików z `input/` (polluted przez Marię ask_encyclopedia)
- `_classify_expert_response` guard — reject placeholder/repeated/short/low-variety
- Saturation META meta-goal materials check w D1.5d
Verification: unproductive strategies 791 → 1 (15× poprawa).

### D1.5d — Meta learning goals require materials
**DONE** 2026-04-21, commit `3affb0f`
GoalSelector blokuje META-learning goals gdy library saturated i brak
learning in_progress. (Później częściowo poluzowane w D1.5c.)

### D1.5b — Semantic drift cleanup (handlers vs executor)
**DONE** 2026-04-22, commit `e94b6b3`
Problem: `handlers.make_learn_handler` (active) używał strict `chunks>0`,
`action_executor._exec_learn` (dead code in prod) używał permissive
`learned OR exams OR strategies`. Fix: strict wygrywa, handlers SSoT.
Cleanup semantyczny — jedna definicja success dla learn.

### D1.5c — Saturation meta-learning goals route to FETCH
**DONE** 2026-04-22, commit `71a3025`
Problem: D1.5d zablokowało meta-learning goals gdy saturated, ale to był
właśnie warunek dla explore_new (fetch). Paradoks. Fix: saturated META
staje się feasible, planner w bypass przed K8 wybiera FETCH bezpośrednio.
Window guard nadal chroni. Helper `is_saturation_meta_goal` jako SSoT.

### D2 — K12 strategic recs route to bulletin (Phase 1: advisory)
**DONE** 2026-04-26, commit `e3ce908`
Problem (zweryfikowany na żywych danych, nie spec): K12 produkuje 5 typów
rekomendacji. `RecommendationApplier` mapował WSZYSTKIE na LEARNING goals.
Strategic recs (`category=strategy_change`, 67/207 ostatnich) np.
*"Akcja 'self_analyze' skuteczność 20%"* lądowały jako goal "Eksperyment:
Akcja 'self_analyze'" — czekał na "files" które nigdy nie powstaną.
Historia: 213 ABANDONED K12 goals. K12 miał głos taktyczny, brak
strategicznego.

Fix:
- `RecommendationApplier`: branch w `apply()` po `category`. Strategic
  recs → bulletin `IMPROVEMENT` entry zamiast goal misroute. Inne
  kategorie (knowledge_gap/new_topic/retention) bez zmian.
- `_extract_action_hint(topic)`: regex extraction "Akcja 'X'" / "X_actions"
  / inline whole-word match. Wynik w `metadata.action_hint`.
- `SelfAnalysis.set_bulletin_store()` + late-bind w
  `homeostasis_module` (bulletin tworzony po K12, więc wiring po
  `BulletinStore()`).
- `PlannerCore._apply_bulletin_advisory()`: w `_finalize_plan` czyta
  IMPROVEMENT entries, dopasowuje `action_hint` do `plan.action_type`,
  annotuje `plan.metadata["bulletin_advisory"]` + trace step
  `bulletin/advisory_match`. **Phase 1 = advisory only, NIE blokuje
  egzekucji.**
- +15 testów (8 strategic routing + hint extraction, 7 planner advisory).
  4588 passed (+15 vs 4573).

Zostawione na Phase 2 (osobna deska): penalty/skip semantics z operator
override, K12-Codex pipeline (gated), retention-problem osobny channel.

### D3 — Loop detection dla creative meta-goals
**DONE** 2026-04-26, commit `1bd2676`
Problem: K13 Creative regeneruje meta-goals każdego cyklu reflection bez
pamięci historycznej. NoveltyFilter sprawdza title-similarity, NIE history.
Goal store: **41 abandoned `capability_meta` + 11 `architectural_meta`** —
unikalne tytuły (LLM warianty) ale ten sam pattern semantyczny.

Fix:
- Nowy `agent_core/creative/loop_detector.py` — `LoopDetector` skanuje
  goal_store i liczy abandoned creative meta-goals po fingerprint
  `metadata.meta_goal_type` w sliding window 7d. Próg ≥3 abandons →
  type w `suppressed_types`.
- `LoopReport` jako frozen dataclass (suppressed_types, counts, window,
  threshold) + `filter_candidates(cands)` dzielący na (kept, suppressed).
- `CreativeModule.reflect()`: krok **5.7** między candidates a novelty
  filter — odrzuca suppressed kandydatów zanim trafią do goal_store.
- `_handle_suppressed_loop`: persist jako `REJECTED` w creative store,
  emit `creative.goal_suppressed_loop` event per kandydat, post jeden
  bulletin `IMPROVEMENT` entry per type per cykl (nie spam).
- `set_bulletin_store()` w facade + late-bind w homeostasis init
  (bulletin tworzony po creative).
- Self-decaying: po 7d bez nowych abandonów licznik spada poniżej
  progu → suppression sama się zdejmuje. Operator może ręcznie
  rozproszyć przez resolve bulletin entry.
- +16 testów (10 detector core/window/decay, 2 filter, 4 facade integ).
  4604 passed (+16 vs 4588).

Coarse fingerprint (tylko `meta_goal_type`) wybrany świadomie — brak
migracji modelu, używa istniejących metadanych. Phase 2 może dodać
`source_tension_category` dla finer-grained pattern.

### D4 — Mode-aware learning (W1 + W2 + W3)
**DONE** 2026-04-26
Problem (Eryk 2026-04-22): Maria spędza ~19.7% czasu w REDUCED (CPU
spike podczas LLM inference, nie RAM pressure). Mode regulator pure
reactive — patrzy tylko na current state. K12 nie analizuje mode
patterns, bulletin 0 wpisów. Maria nie uczyła się z własnych stanów.

Fix (cała pętla observe → diagnose → adapt):

**W1 — `agent_core/self_analysis/mode_postmortem.py`**
- `ModePostmortemRecorder.note_entry/note_exit/discard_pending` —
  pamięta wejście do REDUCED, na REDUCED→ACTIVE zapisuje structured
  record do `meta_data/mode_postmortems.jsonl`.
- `alerts_signature(alerts)` kanonizuje listę alertów (CPU/RAM/
  THERMAL/LLM/COHERENCE/IDLE/GOAL_STACK) — stabilna fingerprint pomimo
  zmieniających się wartości numerycznych.
- Hook w `HomeostasisCore._transition_mode` (setter
  `set_mode_postmortem_recorder`). REDUCED→SLEEP/SURVIVAL → discard
  (te recovery mają inną przyczynę).

**W2 — `agent_core/self_analysis/mode_analyzer.py`**
- `ModeAnalyzer` klastruje recent post-mortems po
  `(alerts_signature, hour_bucket, active_action_type)` w 7d window.
  Próg ≥2 → `ModePattern` + bulletin `IMPROVEMENT` post.
- Bulletin entry dostaje `metadata.mode_aware=True`,
  `action_hint`, `hour_bucket`, `abandon_count`, sample IDs —
  wszystko czego planner potrzebuje do W3.
- Cooldown 30 min między pełnymi `analyze()`. Recorder łańcuchuje
  analyzer przez `set_analyzer()` — po każdym post-mortem wywołuje
  analyze() (cooldown-aware) dla szybkiego feedbacku.
- Dedup: powtórny analyze() z tym samym fingerprintem nie spamuje
  bulletin — `find_open(topic=...)` short-circuit.

**W3 — `PlannerCore._apply_mode_aware_defer`**
- W `_finalize_plan` po D2 advisory: jeśli `bulletin_advisory`
  carries `mode_aware=True` AND current `_current_hour_bucket()` ==
  entry's `hour_bucket` → plan.action_type → NOOP, zachowując
  oryginalny action w `action_params["deferred_action"]`. Trace
  step `mode_aware/defer/applied` dla widoczności.
- Klucz: D2 (advisory) tylko logował; D4 (mode-aware) faktycznie
  blokuje, ALE tylko gdy 3 warunki spełnione (mode_aware match +
  bucket match + nie NOOP już). Conservative.
- Wired przez homeostasis_module: ctx.mode_postmortem_recorder +
  ctx.mode_analyzer, recorder hookowany do core.

+38 testów (alerts_signature, recorder W1, analyzer W2, planner W3,
core hook integration). 4642 passed (+38 vs 4604).

Kryterium sukcesu (do weryfikacji ~7d): REDUCED fraction spada z
19.7% do <10%, ALBO ≥3 wpisy w bulletin z root cause który planner
zaczął honorować przez deferral.

**Wczesny 7d-soak check (2026-04-28, +2d od deploy)** — PASS-A:
- REDUCED fraction: **0.13%** (target <10%, baseline 19.7%) — primary
  criterion z ogromnym zapasem (~150x spadek)
- Mode post-mortems: 3 records (W1 recorder OK)
- Bulletin mode_aware IMPROVEMENT: 1 entry (target ≥3, słaby — ale
  artefakt sukcesu: za mało REDUCED do clusterowania)
- Verdict via `scripts/verify_d4.py`
- Domniemana współprzyczyna ogromnego spadku: splot D4 deferral + C1
  NIM-first planner z 04-23 (CPU spike usunięty z planera). Pełny
  7d recheck wskazany ~05-03 dla potwierdzenia stabilności.

---

## Planowane

(brak — D1..D4 wszystkie ukończone 2026-04-26, D4 PASS-A potwierdzone
2026-04-28. Następna weryfikacja D4 po pełnym 7d window ~05-03. Dalsze
pomysły patrz "Side tasks" i `MEMORY.md` directions.)

---

## Side tasks (nie D-deski, osobne sesje)

### R1 — Cross-source knowledge consolidation
**FLAGGED** 2026-04-22, **przepisane** 2026-05-06

Wizja: Maria czyta temat z Wikipedii **i** woła Codex/ChatGPT o ten sam
temat. Comparator wyłapuje fakty zgodne (consensus → boost confidence
w BeliefStore) vs rozbieżne (disagreement → reasoning lub flag do
operatora). Pattern: Maria uczy się jak naukowiec — triangulacja źródeł,
krytyczne myślenie. **NIE Codex jako primary source** (anti-crutch w
`project_llm_strategy`), **ale Codex jako second opinion**.

4 komponenty (draft 04-22 robił tylko #1):

1. **Content fetch** — `CodexKnowledgeSource` woła Codex CLI, pisze do
   `input/codex_*.txt` z headerem `# Zrodlo: ChatGPT (Codex CLI)`.
   Strict gating: PROPOSED→ACTIVE per-topic, 10/h limit, garbage guard
   (≥500 chars, variety check, no placeholders).
2. **Side-by-side comparator** — gdy `expert_X.txt` (Wikipedia) i
   `codex_X.txt` istnieją na ten sam topic, semantic comparison
   (embeddings + LLM diff) ekstraktuje fakty zgodne i rozbieżne.
3. **Disagreement detector** — flaguje pary `(fakt_wiki, fakt_codex)`
   gdzie te same encje mają różne wartości/relacje. Bulletin entry
   `IMPROVEMENT category=knowledge_consolidation` per disagreement.
4. **Confidence reconciler** — BeliefStore rozróżnia confidence per
   source: Wikipedia consensus = high, Codex consensus = mid,
   disagreement = low (do dalszej resolution lub manual review).

**Anti-crutch test:** Maria z wyłączonym Codex'em musi nadal uczyć się
poprawnie z Wikipedii samej. R1 to enhancement, nie dependency.

**Drafty 04-22** (zarchiwizowane do `/mnt/storage/zombie_patches_2026-04-22/`):
- `codex_source.py` + `test_codex_source.py` — częściowy fundament #1
- `brave-mirzakhani-modified.patch` — modyfikacje `rss_client`,
  `handlers`, `recommendation_applier` (niewykorzystane,
  supersedowane przez R2/R2.1)

Pierwotne side-cele R1 (RSS filtering by weak topics, 2-3 więcej feedów)
**wydzielone** — osobny chip jeśli kiedyś wraca, niezależny od
consolidation engine.

### R2 — Fetch observability
**DONE** 2026-04-22 (commit `b6286cd`, weryfikacja 2026-04-28)
Spec: brak logów fetch w journalu, nieznany caller fetch 15:21:57.
Fix: `agent_core/web_source/decision_log.py` z `[FETCH_DECISION]`
strukturalnym (origin, outcome, topics, fetched, rss_filtered,
dur_ms) + `meta_data/fetch_decisions.jsonl` ślad dla każdej fetch
session. Plus `[WEB_SOURCE] Session starting/complete` per session.
Dziennik 2026-04-28 ma 51 strukturalnych decisions — observability
gap zamknięty. Atrybucja origin (`saturation_meta_fetch`,
`teacher`, `manual`) odpowiada na pytanie "kto wywołał fetch".

### R2.1 — Fetch effectiveness (saturation loop)
**FLAGGED** 2026-04-28 (chip spawned)
Po zamknięciu R2 widać że Maria spamia FETCH co ~60s w
`saturation_meta_fetch` path: 50/51 dzisiejszych decisions =
`outcome=no_articles`. Library 99.7% saturated, topic_suggester
proponuje 5 topics które wszystkie kończą się `40/40 rss_filtered`
→ 0 articles fetched. Symptomy: marnowanie 16-21s/cycle, 0 nowej
wiedzy, jedynie `expert_*.txt` (Codex/manual) zasilają input/.
Diagnoza wymagana: topic_suggester (proponuje już-zindeksowane?),
`_is_rss_relevant` filter (over-aggressive?), brak rate-limit
cooldown gdy session zwraca 0 articles.

---

## Konwencja numerowania

- D1, D2, D3... — główne deski
- D1.5, D1.5b, D1.5c... — sub-deski ujawnione podczas głównej
- R1, R2... — side tasks (poza kolejnością D-desek)

## Ostatnia aktualizacja

2026-05-06 — **R1 przepisane** z "Codex jako writer-source" na
"Cross-source knowledge consolidation" (4 komponenty: content fetch,
comparator, disagreement detector, confidence reconciler). Pivot
napędzony tym że pierwotny draft 04-22 robił 1/4 wizji — sam content
fetch bez triangulacji = single-source pattern przebrany za
fundament. Drafty 04-22 (`codex_source.py`, 2× `*-modified.patch`)
zarchiwizowane do `/mnt/storage/zombie_patches_2026-04-22/`. Przy
okazji cleanup 3 zombie git worktrees (sharp-cannon-18243a,
brave-mirzakhani-712123, compassionate-wescoff-3d6c1c).

2026-04-26 — **D2 + D3 + D4 ukończone tego samego dnia**.
D2: K12 strategic recs → bulletin IMPROVEMENT (213 ABANDONED
zaadresowane). D3: LoopDetector w creative/ (fingerprint po
meta_goal_type, sliding 7d, próg ≥3). D4: mode-aware learning
trzy warstwy — ModePostmortemRecorder (W1), ModeAnalyzer (W2),
planner mode-aware defer (W3). Test counter 4573 → 4642
(+69 testów dziś). Wszystkie deski D1..D4 done. Backlog
operacyjny pusty — następne kroki wynikną z runtime weryfikacji
(7-dniowe okno po D4 deploy).

2026-04-22 — Eryk zatwierdził D4 (mode-aware learning) po diagnostyce
"Maria wpada w REDUCED 20% czasu, nie wyciąga wniosków". Intuicja
Eryka "to zasoby nie błąd" okazała się trafna, ale konkret to CPU
spike podczas LLM inference, nie RAM pressure / ładowanie modeli.
