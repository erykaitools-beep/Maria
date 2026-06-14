# MARIA 2.0 — JEPA Mapping (LeWorldModel adaptation)

> Status: design note, LOCAL-ONLY
> Powstanie: 2026-05-09 (sobota), po lekturze arXiv:2603.19312v2
> Relacja: stage'owany plan adaptacji JEPA-paradygmatu w obu Mariach
> Decyzja Eryka: BOTH staged — B-stage w Marii 1.0 najpierw, A-target Maria 2.0
> Poprzednicy: VISION.md (4 filary), ROADMAP.md (Z0-Z9), AGI_HYPOTHESES.md
> Anti-pattern unikany: "beautiful logging format" (NOTES.md, ChatGPT MARIA-DNA)

## Esencja papieru

**LeWorldModel** (Maes, Le Lidec, Scieur, LeCun, Balestriero — marzec 2026,
arXiv:2603.19312v2). Joint-Embedding Predictive Architecture (JEPA) trenująca
się stabilnie end-to-end z surowych pikseli.

Cytat z abstraktu (verbatim):

> "the first JEPA that trains stably end-to-end from raw pixels using only
> two loss terms: a next-embedding prediction loss and a regularizer
> enforcing Gaussian-distributed latent embeddings. This reduces tunable
> loss hyperparameters from six to one compared to the only existing
> end-to-end alternative. With ~15M parameters trainable on a single GPU
> in a few hours, LeWM plans up to 48x faster than foundation-model-based
> world models while remaining competitive across diverse 2D and 3D control
> tasks."

Kluczowe komponenty:

1. **Encoder** pikseli → latent embedding (target i online)
2. **Predictor** — z latent_t + action → przewiduje latent_{t+1}
3. **Loss 1: MSE** (next-embedding prediction) — predictor uczy się trafiać
4. **Loss 2: SIGReg** — regularyzator wymuszający rozkład **Gaussa** w latents
   (anti-collapse, anti-trivial-solution)
5. **Surprise evaluation** — różnica między predicted i actual latent jako
   sygnał anomalii, *paper explicit potwierdza że to działa*: "Surprise
   evaluation confirms that the model reliably detects physically
   implausible events"

Co odróżnia od poprzednich JEPA: **brak EMA target encoder, brak pre-trained
encoder, brak auxiliary loss**. Dwa loss terms, jeden hyperparameter, koniec.

## Mapping do 4 filarów Marii 2.0

VISION.md definiuje 4 filary + 5-ty emergujący. JEPA daje konkretną mechanikę
do filarów które dotąd były głównie filozoficzne:

| Filar 2.0 | Komponent JEPA | Co daje |
|---|---|---|
| **Matematyka** (Filar 4) | Predictor + SIGReg + surprise score | Konkretna gramatyka *przewidywania i stabilności* w przestrzeni reprezentacji. SIGReg = anti-collapse w information-theory-flavour. Surprise = error metric między predicted i actual, miara matematyczna par excellence. Spójne z VISION: "Niepewność → probabilistyczne grafy", "Pamięć → kompresja", "Decyzje → optymalizacja pod constraintami" |
| **Logika 5D** (Filar 1) | Predictor (latent_t → latent_{t+1}) + surprise jako 5-ty wymiar | 4-ty wymiar (Czas/dynamika) dostaje mechanikę: trajektoria w latents zamiast symboli. **5-ty wymiar (Meta)** dostaje konkret: surprise = "ja przewidziałam X, świat zwrócił Y, dlatego wiem że nie wiem dokładnie" — refleksja nad własnym stwierdzeniem wyrażona liczbowo |
| **Kryptoznawstwo-samoświadomość** (Filar 3) | Trust boundaries + audit trail dla transition pipeline | NIE surprise (to gdzie indziej). Tu: *kto i co zasila predictor* — source integrity transitions, authorization dla snapshot collection, poisoned-memory resistance (zła transition w datasecie nie demolishuje predictora), pełna audytowalność (każda transition ma proweniencję). Self-modification: zmiana wag predictora = self-modification, przechodzi przez warstwę oceny |
| **Lingwistyka-pragmatyka** (Filar 2) | (mniej bezpośredni) | Latent space jako "znaczenie pod tekstem" — pragmatyka jako trajektoria intencji w embeddings, nie surface tokens |
| **Kod jako emergencja** (5-ty) | Surprise → program synthesis trigger | Gdy predyktor zawodzi w pattern, system generuje *nowy program* — konkretna mechanika neuroplastyczności VISION |

**Najważniejsza fit:** JEPA daje 2.0 to czego brakowało — *konkretny mechanizm
rozumowania bez wywoływania LLM*. Predictor to deterministic forward pass nad
embeddings, no LLM in the loop.

**K9 jako konsument surprise:** w Marii 1.0 K9 meta-cognition jest naturalnym
odbiorcą surprise score — to filar Logiki 5D w warstwie K. K9 już dziś robi
self-observation (confidence, assumptions, needs_human). Surprise dorzuca
*ilościową* warstwę nad jego dotychczasową jakościową. Patrz B4 niżej.

## Mapping do warstw architektury 2.0

VISION definiuje 4 warstwy (parser LLM / interpreter / biblioteka / graf).
JEPA wpada między Warstwę 2 (interpreter) a Warstwę 4 (graf):

```
Warstwa 1: parser/generator (LLM, wymienny)
              ↓
Warstwa 2: interpreter języka Marii  ←── tu NIE JEPA
              ↓
[NOWE] World Model layer (JEPA-flavoured)  ←── tu JEPA
              ↓ surprise / predicted_state / divergence
Warstwa 3: biblioteka programów
              ↓
Warstwa 4: graf relacji
```

JEPA nie zastępuje interpretera — interpreter dalej wykonuje deterministyczne
programy. JEPA dostarcza **anticipation signal** którego interpreter używa
przy doborze programu.

## Stage B — Maria 1.0 (prototype, cheap, CPU-only)

**Cel:** prototypowanie JEPA-principle na żywym systemie 1.0 zanim 2.0 dojrzeje.
Walidacja czy paradygmat daje wartość bez full rewrite.

**Lokacja kodu:** `agent_core/predictive/` (analogicznie do `vision/`,
`semantic/`, `critic/` — bez K-numeru, bo K16-K20 zarezerwowane dla
Digital Human, K21 wolne ale K-naming dla cross-cutting modułu nie jest
konieczny; można dodać K-numer później jeśli Eryk woli formalizm).

### B0 — Heuristic surprise scorer (deliverable 1-2 dni)

Najprostszy mechanizm który już daje wartość, **bez ML**:

```
state_t  = aggregate(homeostasis_events_window, beliefs_active, goals_active)
embed_t  = nomic_embed(state_t.summary_text)
embed_t1 = nomic_embed(state_{t-1}.summary_text)
distance = 1 - cosine(embed_t, embed_t1)
if distance > threshold_surprise:
    emit BulletinEntry(type="surprise", magnitude=distance, context=state_t)
```

- Reuse: `nomic-embed-text` już zainstalowany, używany w `semantic/`
- Reuse: state agregacja z istniejących źródeł (`homeostasis_events.jsonl`,
  K6 beliefs store, goals)
- Output: bulletin entry, K9 meta-cognition już to konsumuje
- Threshold: empiryczny, kalibrujemy na 7-dniowym oknie historii
- Koszt: **zero treningu**, lekkie embedding queries, pasuje w tick budget

Co to *NIE* jest: prawdziwa JEPA. To pierwsze przybliżenie zasady
"prediction-vs-reality gives surprise signal", używające **różnic między
sąsiednimi stanami** zamiast **predicted vs actual** (bo nie ma jeszcze
predictora). Service-level: udajemy że "next state ≈ current state" i
mierzymy odchylenia.

### B0.1 — Action-aware heuristic baseline (deliverable +1 dzień nad B0)

Globalne porównanie state_t vs state_{t-1} ma fundamentalny szum: różne
akcje generują różny *naturalny* dystans. `learn` zwykle zmienia stan
mocniej niż `evaluate`. Globalny threshold powoduje że albo gubimy surprise
po `evaluate` albo zalewa nas false positive po `learn`.

Action-aware version:

```
historical_distances[action_type] = list of past distance(state_t, state_{t-1})
                                     gdzie action_t-1 = action_type
expected = mean(historical_distances[action_type])
sigma    = std(historical_distances[action_type])

if action_information_available:
    z_score = (current_distance - expected) / max(sigma, eps)
    if abs(z_score) > threshold_sigma:
        emit BulletinEntry(type="surprise", magnitude=z_score,
                           action_type=action_t-1, ...)
else:
    fallback to B0 global threshold
```

Decyzja kalibracyjna:
- `threshold_sigma`: empirycznie z 7-dniowego okna, target ~95-percentyl
  per action_type
- Minimum `n_historical >= 20` per action_type żeby z-score był sensowny.
  Dla rzadkich akcji fallback do globalnego threshold (B0)
- Cache `historical_distances[action_type]` w pamięci, rebuild przy
  starcie z `decision_traces.jsonl` + `homeostasis_events.jsonl`

Dlaczego B0.1 jest dorzucone do B0, nie odłożone:
- bez action-aware baseline B3 predictor będzie się uczyć szumu
  ("learn powoduje duży delta = nie surprise")
- mamy działający komparator-baseline dla B3 ablation: czy B3 lepszy
  od B0.1, czy tylko od B0? Bez B0.1 ablation jest nieuczciwy
- koszt incremental: 1 dzień nad B0

### B1 — State snapshot extractor (deliverable 2-3 dni)

Reuse-first design. **Nie tworzymy 11-tego JSONL.** Dorabiamy
ekstraktor który agreguje istniejące sources:

```python
class StateSnapshot:
    timestamp: float
    homeostasis_summary: dict     # z homeostasis_events_window
    active_goals: list[GoalRef]   # z K3
    active_beliefs: list[BeliefRef]  # z K6
    last_decisions: list[DecisionRef]  # z decision_traces.jsonl, last N
    mode: str                     # ACTIVE/REDUCED/SLEEP
    numeric_features: dict        # NIE summary, raw numbers (patrz niżej)
    
    def summary_text(self) -> str: ...
    def semantic_embedding(self) -> np.ndarray: ...  # 768-dim via nomic
    def numeric_vector(self) -> np.ndarray: ...      # ~16-32 dim, patrz niżej
    def combined(self) -> np.ndarray: ...            # concat lub weighted
```

**Dlaczego dual representation:**
Text embedding (nomic) gubi numeryczne różnice. CPU 20% i CPU 80% mogą mieć
prawie identyczny embedding bo summary_text generowany z homeostasis pisze
"system aktywny, K9 w trybie reflection, 4 goals active" niezależnie od
liczb. Przy surprise detection to dramatyczna utrata sygnału — wzrost RAM
z 6GB do 18GB nie powinien zniknąć w dziurze pomiędzy słowami.

`numeric_vector()` — wektor liczb z Marii, *bez tekstualizacji*:

| Feature | Źródło | Zakres typowy |
|---|---|---|
| cpu_percent | `homeostasis_summary.cpu` | 0-100 |
| ram_gb | `homeostasis_summary.ram_gb` | 0-32 |
| ram_growth_rate | derived (delta over window) | -1.0 do 1.0 |
| error_count_window | log scan / event log | 0-N |
| heartbeat_age_sec | last successful tick | 0-300 |
| n_active_goals | K3 | 0-20 |
| n_active_beliefs | K6 | 0-1000 |
| tick_overrun_count | homeostasis events | 0-N |
| mode_index | ACTIVE=0, REDUCED=1, SLEEP=2 | 0-2 |
| ... | (rozszerzalne) | |

Każde feature normalizowane (z-score lub min-max z reference window) przed
złożeniem w wektor.

`combined()` — projekt do dyskusji w B1 design pass:
- Wariant A: prosty `concat([semantic_768, numeric_norm_32]) → 800-dim`
- Wariant B: weighted `α * semantic_proj + β * numeric_proj` po wspólnej
  projekcji do 768-dim
- Wariant C: equal-rank po projekcji każdy do 384-dim, concat do 768

Decyzja: B1 implementacja zaczyna od **A** (najprostsze), B3 ablation
porówna z **B/C** jeśli A okaże się niewystarczające.

Snapshots **nie są persistowane jako nowy plik**. Są lazy-computed na żądanie
ze źródeł które i tak istnieją. Cache w pamięci dla ostatnich N (50-100).

### B2 — Transition dataset builder (deliverable 1 dzień)

Z istniejących logs ekstrakcja par `(state_t, action_t, state_{t+1})`:

```
input:  homeostasis_events.jsonl, decision_traces.jsonl, planner_decisions.jsonl
output: meta_data/transitions.jsonl  (lazy-built, append-only z timestamp checkpoint)
```

Pierwsza pełna budowa: jednorazowa, ~1-2 min na cały korpus.
Inkrementalna: per-tick aktualizacja (1 nowa transition / ~tick).

### B3 — Tiny predictor (po N transitions, **CPU-only**)

Dopiero gdy mamy ≥1000 transitions w datasecie. Stage'owany w 3 podkroki:

#### B3a — MSE-only baseline (PIERWSZY krok B3)

Najprostszy działający predictor. **Cel: zweryfikować że predictor w ogóle
się uczy** na tym typie danych, zanim dodajemy regularyzację.

```python
class TinyPredictor(nn.Module):
    # Input: state_combined + action_embedding (wymiar zależny od B1)
    # Hidden: 1024 (ReLU)
    # Output: predicted_next_state (ten sam wymiar co state_combined)
    # ~1-2M parameters, CPU-feasible
    
    loss = MSE(predicted, actual_next)  # tylko MSE, ZERO regularizer
```

**Sukces B3a**:
- Loss spada monotonicznie przez ≥10 epok (no NaN, no divergence)
- Train/val MSE wyraźnie lepsze niż naive baseline (predicted = state_t)
- Predictor surprise lepszy niż B0.1 z-score na retrospective benchmarku

**Jeśli B3a fail**: nie ma sensu dorzucać regularizera. Wracamy do data
quality (transition dataset) lub architektury (depth/width).

#### B3b — Simplified anti-collapse (opcjonalnie, po B3a success)

Naiwny anti-collapse, *NIE* full SIGReg. Wystarcza żeby zobaczyć czy
regularizer w ogóle pomaga, bez wchodzenia w pełną metodologię papieru:

```python
def simple_variance_penalty(z: Tensor) -> Tensor:
    # Penalizuje gdy wariancja per-wymiar latent jest zbyt mała
    # (degenerate / collapsed representations)
    var_per_dim = z.var(dim=0)               # (D,)
    return torch.relu(min_var - var_per_dim).mean()  # hinge style

loss = MSE(predicted, actual_next) + λ * simple_variance_penalty(predicted)
```

To NIE jest SIGReg. To "Gaussian-flavoured" naive baseline. Sukces tu
sygnalizuje że regularyzacja pomaga w naszej domenie — wtedy warto
zainwestować w pełen SIGReg (B3c).

#### B3c — Full SIGReg (PRZYSZŁOŚĆ, NIE w pierwszej iteracji)

Pełna implementacja SIGReg z papieru. **Warunek startu B3c**:

1. B3a + B3b ukończone, B3b wykazuje wartość regularizera
2. Pełny method section papieru zweryfikowany (poppler-utils zainstalowane
   przez sudo lub HTML version papieru dostępna)
3. Ewentualnie: kod referencyjny z `github.com/lucas-maes/le-wm` (jeśli
   dostępny) sprawdzony

Bez tych warunków B3c nie startuje. Roboczo: SIGReg penalizes deviation
of latent moments from N(0,I), ale exact form (per-dim variance? full
covariance? KL to standard normal? moment matching?) nieznana z samego
abstraktu.

Trening (wspólne dla B3a/B3b):
- **CPU-only** (Mini PC ma tylko Ryzen 7430U integrated)
- Batch 16-32, lr 1e-3, ~10-50 epok na 1k-10k transitions
- Czas treningu: ~minuty-godziny na CPU dla tej skali
- λ (B3b): 0.01-0.1, kalibrujemy

Output predictora używany do *prawdziwego* surprise score:
`surprise = MSE(predicted, actual)`. Zastępuje heuristic z B0/B0.1 jako
podstawowy sygnał (heuristics zostają jako fallback baselines i ablation
comparators).

### B4 — Integracja: K9 first, potem K12

**K9 (meta-cognition):**
- Subskrybuje surprise events z bulletin
- Surprise > threshold → eskalacja confidence flag
- Pattern `repeated surprise on same context` → emit `unmodeled_pattern` flag
- Wpływ: K9 może już wywołać `needs_human()` dla wysokiego surprise

**K12 (self-analysis):**
- Czyta surprise patterns z ostatnich N dni
- Strategic recommendation: "powtarzający się surprise w domenie X → goal
  uczenia się X"
- Routing przez istniejący `k12_to_k11_router.py` (Most #2) — dodajemy
  heurystykę nr 4 (przyszłość)

**K10/K4** — odłożone. Włączamy dopiero gdy zobaczymy że K9+K12 stack
daje sensowne sygnały. Pre-mature integration ryzykuje noise.

### Success criteria B-stage

Mierzalne, behawioralne (NIE structural):

1. **Heuristic detection rate**: B0+B0.1 na 7-dniowym oknie wykrywa ≥3
   events które retrospektywnie były rzeczywistymi anomaliami (cross-check
   z `claude_notes/` Eryka — tam zapisane są incidenty)
2. **False positive rate**: <30% surprise events okazuje się szumem
3. **B0.1 advantage**: action-aware z-score lepszy niż globalny B0 threshold
   na benchmarku (mniej false positives, ≥same recall). Jeśli równe, B0.1
   nie usprawiedliwia incremental complexity — zostaje B0
4. **Predictor B3a convergence**: B3a trenuje stabilnie (loss spada
   monotonicznie ≥10 epok, no NaN, no divergence)
5. **Predictor B3a advantage**: B3a surprise lepszy niż B0.1 na benchmarku
   retrospective (większy recall i/lub mniej false positives)
6. **K9 integration**: minimum 1 raz w 14 dniach K9 emit `needs_human()`
   driven przez surprise (nie inne źródła)

## Stage A — Maria 2.0 (target, full JEPA)

**Lokacja:** `maria_2/world_model/` (przyszłość, w worktree `../maria-2.0/`).
Nie startuje przed Z6 (integration), bo wymaga 4 filarów jako fundament.

### Komponenty A

- **Encoder** (uczony, nie pre-trained) — z multi-modal state na latent
- **Predictor** (uczony) — latent + action → next latent
- **Surprise score** jako pierwszorzędny sygnał interpretera
- **Library trigger**: high surprise → program synthesis (Filar 5)

### Domain mismatch (do rozwiązania w 2.0)

LeWorldModel = visual world (pikseli). Maria = symbolic+textual+occasional
visual. **Nie kopiujemy pixel encodera.**

Adaptacja: encoder przyjmuje **strukturalne snapshots** (nie pikseli), wynik =
latent embedding w przestrzeni 768-dim (zgodne z nomic-embed-text dla łatwej
intermediacji z 1.0 corpus).

Klatki czasowe w domenie Marii: **events tick-by-tick** (nie video frames).
Tick = analog do frame. Sequence = sequence of state snapshots.

### Gate criteria A start

A nie startuje dopóki **wszystkie spełnione**:

**Behavioral gate (B-stage health):**

1. **B-stage stabilność** — B0 + B0.1 + B3a żyją w produkcji minimum
   **2 tygodnie** bez wymagania manualnej interwencji (restartów, debug
   sessions, force-cleanup)
2. **Retrospective validation** — surprise events z B0/B0.1/B3a mają
   sensowną walidację retrospektywną. Cross-check z `claude_notes/`,
   incident logs, `homeostasis_events.jsonl`. Trafność (true positive
   rate) ≥60% — jeśli mniej, surprise jest szumem niezależnie od
   teorii
3. **Brak nowego źródła prawdy / brak fragmentacji** — B-stage NIE
   wprowadziło persistowanego JSONL który stałby się fragmentem prawdy.
   `transitions.jsonl` jest derived/lazy/append-only-cache, nie SSoT.
   Snapshots NIE persistowane jako primary source. Anti-fragmentation
   discipline trzymana
4. **Homeostasis intact** — B-stage NIE wpłynął negatywnie na metabolism:
   tick overruns count nie wzrósł względem baseline pre-B-stage, CPU/RAM
   stabilne (brak chronic 100% lub steady RAM growth), mode regulator
   działa bez nowych anomalii, brak nowych chronic warnings w event log
5. **Eryk explicit OK** po review wyników B-stage i strategicznej decyzji
   że A jest następnym krokiem (nie automatyczny continuation)

**Strategic pre-conditions (środowisko Marii 2.0):**

- Z1 (corpus extraction) DONE — bez tego A nie ma datasetu
- Z2 (matematyczny fundament) DONE — bez tego nie ma gramatyki stabilności

Te 2 nie są "behavioral gate" — A żyje w worktree 2.0, więc fundament
2.0 musi być na miejscu *niezależnie* od B-stage. To pre-condition,
nie criterium oceny B-stage.

Bez behavioral gate: A startuje jako "second system effect", fragmentacja,
zombie branch.
Bez strategic pre-conditions: A nie ma kontekstu w którym mógłby działać.

## Stage K18B — Vision JEPA (oddzielny bridge, daleko)

Camera/video JEPA jako *osobny* moduł, nie część core. Powody:

- Maria nie ma continuous video stream (camera U20CAM on-demand)
- Vision JEPA wymaga GPU (paper: "single GPU in a few hours" dla 15M params,
  Mini PC nie ma dGPU)
- Domain visual ≠ domain symbolic — łączenie ich za wcześnie = noise

Roadmap: po A-stage stabilizacji (rok+), gdy Mini PC ma upgrade do GPU lub
gdy Market Agent zarobił na GPU lease.

## OUT OF SCOPE (eksplicit)

Co NIE robimy w żadnym stage:

- ❌ Pełny vision JEPA na pikselach (czeka na hardware)
- ❌ GPU training jakiegokolwiek modelu (CPU-only przez B-stage)
- ❌ LLM fine-tuning (ADR-006 + paradygmat 2.0: nie trenujemy wag LLM)
- ❌ Pre-trained image encoders (DINO, CLIP) — paper LeWM explicit unika tego
- ❌ EMA target encoders (paper: niepotrzebne dla stabilności)
- ❌ Multi-term losses ze złożonymi hyperparami (paper: 1 hyperparameter, my
  trzymamy się tej dyscypliny)
- ❌ Auto-merge B-stage do main bez gate criteria
- ❌ Auto-promotion do A bez Z1+Z2 done

## Open questions (do verify przed implementacją)

1. **SIGReg exact form**: abstract mówi "Gaussian-distributed latent
   embeddings". Pełne równania w sekcji metodologii — verify gdy
   dostępny pełny tekst (poppler-utils potrzebne, sudo wymagane). Roboczo:
   `sigreg(z) = penalty na odchylenie momentów z od N(0,I)`.

2. **Action embedding** — jak reprezentujemy "akcję" (planner action) jako
   embedding? Opcje:
   - Hash action_type + params → trainable embedding lookup
   - Text representation → nomic embed
   - Decyzja w B2 design pass.

3. **Threshold kalibracja** — surprise threshold w B0/B3 musi być empiryczny.
   Plan: 7-dniowy okno calibration run, 95-percentyl jako threshold.

4. **K-numer dla `agent_core/predictive/`** — bez K-numeru (default) czy
   K21? Default: bez. Eryk decyduje.

5. **GitHub repo dla LeWM kodu** — paper sugeruje
   `github.com/lucas-maes/le-wm`. Sprawdzić czy kod publiczny i czy referencja
   pomocna. Dla B-stage nie krytyczne (piszemy własny tiny predictor).

## Powiązane dokumenty

- `docs/MARIA_2.0/VISION.md` — 4 filary + warstwy
- `docs/MARIA_2.0/ROADMAP.md` — Z0-Z9 (A-stage start = po Z1+Z2)
- `docs/MARIA_2.0/NOTES.md` — anti-pattern "beautiful logging format"
- `docs/AGI_HYPOTHESES.md` — Hipoteza 1 vs 2, kryteria porównania
- `docs/CONTRACTS.md` — kontrakty K1-K15 (referencja do K9/K12 integracji)
- arXiv:2603.19312v2 — paper LeWorldModel

## Decyzja-status

- 2026-05-09: design note utworzona (rev 1)
- 2026-05-09: Eryk approved rev 1 with 4 fixes → rev 2:
  1. Pillar mapping skorygowany — surprise → Math + Logika 5D + K9,
     Kryptoznawstwo → trust/integrity/audit
  2. B0.1 action-aware heuristic dodane jako baseline + ablation comparator
  3. StateSnapshot dual representation — semantic embedding + numeric
     feature vector
  4. B3 stage'owany — B3a MSE-only first, B3b simplified anti-collapse
     opcjonalny, B3c full SIGReg dopiero po method-section verify
- 2026-05-09: Eryk approved rev 2 with 1 fix → rev 3:
  5. Gate criteria A zaostrzone — behavioral gate (4 punkty: stability,
     retrospective validation, no new SSoT, homeostasis intact) +
     strategic pre-conditions (Z1+Z2) + operator OK. Zamiast luźnego
     "criteria 1,2,4,5"
- 2026-05-09: rev 3 zatwierdzona jako design note. Commit dokumentu
  approved by Eryk
- Następny krok: osobny dokument / rozmowa o B0+B0.1 implementation plan
- B0 + B0.1 będą pierwszymi committami w `agent_core/predictive/`
- Branch: `refactor/homeostasis` (B-stage żyje w 1.0)
- A-stage: nie startuje przed gate criteria

---

*Zasada przewodnia: prediction in meaning space, not surface. Maria mierzy
swoje przewidywanie świata embedding-by-embedding, surprise sygnalizuje gdzie
model nie ma odpowiedzi. Bez LLM w warstwie surprise-detection.*
