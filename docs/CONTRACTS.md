# M.A.R.I.A. - Kontrakty Architektoniczne

> Version: 1.3 | Utworzono: 2026-03-01 | Korekty: v1.1 (event_id, registry, promote tx, auto-goals), v1.2 (dedup/priority/ttl per type, trace_id trade-off, ROLLBACK reason, PROPOSED izolacja), v1.3 (Kontrakt K5: Planner)
> Zatwierdzone przez: Eryk + Claude
>
> Ten dokument definiuje formalne kontrakty ("konstytucje") dla nowych warstw systemu.
> Kazda implementacja MUSI byc zgodna z tymi kontraktami.

---

## Spis tresci

1. [Unified Perception - PerceptionEvent](#kontrakt-1-unified-perception)
2. [Sandbox / Production Boundary](#kontrakt-2-sandbox--production-boundary)
3. [Goal System](#kontrakt-3-goal-system)
4. [Agent Evaluation](#kontrakt-4-agent-evaluation)
5. [Planner - ReAct Loop](#kontrakt-5-planner)
6. [Decyzja: Tick Aggregator](#decyzja-5-tick-aggregator)
7. [Struktura plikow](#struktura-plikow)
8. [Integracja z istniejacym kodem](#integracja)

---

## Kontrakt 1: Unified Perception

### Problem

System ma 5+ rownolegych, niespojnych strumieni danych:
- Homeostasis sensors (5x dataclasses)
- User REPL (string commands)
- Learning results (JSONL)
- Consciousness events (JSONL)
- Teacher decisions (JSONL)

Brak wspolnego formatu. Moduly nie wiedza co sie dzieje w innych modulach.

### Rozwiazanie: PerceptionEvent

Jeden format dla WSZYSTKICH bodzcow.

```python
class PerceptionSource(Enum):
    """Zrodlo zdarzenia percepcji."""
    SENSOR = "sensor"                # Homeostasis sensors (5x)
    USER = "user"                    # REPL input, Web UI chat
    LEARNING = "learning"            # learn_next_chunk results, file scan
    EXAM = "exam"                    # run_exam_if_ready results
    CONSCIOUSNESS = "consciousness"  # trait evolution, sleep, dreams
    TEACHER = "teacher"              # TeacherAgent decisions
    SYSTEM = "system"                # Mode changes, alerts, startup/shutdown


@dataclass(frozen=True)
class PerceptionEvent:
    """Uniwersalny format zdarzenia percepcji."""
    event_id: str                # UUID4 - unikalny identyfikator tego zdarzenia
    source: PerceptionSource     # Kto wygenerowel zdarzenie
    event_type: str              # np. "resource_reading", "user_message", "exam_result"
    priority: float              # 0.0 (ignoruj) do 1.0 (reaguj natychmiast)
    timestamp: float             # time.time()
    payload: Dict[str, Any]      # Dane zrodlowe (struktura wg Event Type Registry)
    ttl: float                   # Sekundy do wygasniecia (0 = bez limitu)
    parent_event_id: Optional[str]  # event_id zdarzenia-przyczyny (lancuch kauzalny)
```

### Semantyka identyfikatorow

- **`event_id`** - unikalny UUID4 per zdarzenie. Kazde zdarzenie ma DOKLADNIE jeden.
- **`parent_event_id`** - referuje `event_id` zdarzenia ktore BEZPOSREDNIO spowodowalo to zdarzenie.
  - Przyklad lancucha: teacher_decision(id=A) → learn_chunk(id=B, parent=A) → exam_result(id=C, parent=B)
  - Sledzenie calego lancucha: podazaj `parent_event_id` rekurencyjnie do `None`.
- **Brak osobnego `correlation_id` / `trace_id`** - swiadomy trade-off:
  - `parent_event_id` daje drzewo przyczynowosci (wystarczajace na skali 5-6 zrodel)
  - `trace_id` / `correlation_id` daloby grupowanie rownoleglych eventow w jedna "sprawe" (np. caly user flow)
  - Na dzis: nie potrzebne. Jesli w przyszlosci bedzie potrzebne: dodanie 1 opcjonalnego pola, zero breaking changes.
  - **Kiedy dodac:** gdy pojawi sie Planner (Warstwa 2) i bedzie potrzebowal sledzic wiele rownoczesnych akcji.

### Tabela priorytetow

| Priority | Typ zdarzenia | Przyklad |
|----------|--------------|---------|
| **1.0** | CRITICAL alerts | RAM OOM, thermal shutdown, SURVIVAL |
| **0.9** | User input | REPL command, chat message |
| **0.8** | Mode transitions, exam results | ACTIVE->REDUCED, score=0.85 |
| **0.7** | Learning completion | Chunk learned successfully |
| **0.5** | Teacher decisions, consciousness | Strategy chosen, trait emerged |
| **0.3** | Periodic sensor readings | 1Hz tick data (resource, cognitive) |
| **0.1** | State snapshots, audit | Periodic logging |

### TTL domyslne

| Typ zdarzenia | TTL | Uzasadnienie |
|---------------|-----|-------------|
| Sensor readings | 5s | Stale data jest bezuzyteczna |
| User input | 0 (brak) | Zawsze relevantne |
| Learning/exam results | 300s (5 min) | Kontekst biezacej sesji |
| Mode changes | 0 (brak) | Historycznie wazne |

### Event Type Registry

Rejestr mapujacy `event_type` → wymagane pola `payload`.
NIE walidowany w runtime - to specyfikacja, nie enforcement.
Cel: zeby payload nie zrobil anarchii po 3 sprintach.

| event_type | source | priority | ttl | dedup | Wymagane pola payload | Opcjonalne |
|-----------|--------|----------|-----|-------|----------------------|------------|
| `resource_reading` | SENSOR | 0.3 | 5s | tak | `ram_available_mb`, `ram_available_pct`, `cpu_percent`, `temp_c`, `disk_used_pct` | `inference_latency_ms`, `swap_used_pct`, `load_avg_1m` |
| `cognitive_reading` | SENSOR | 0.3 | 5s | tak | `context_coherence`, `inference_latency_ms`, `error_count_1h`, `goal_stack_depth` | `memory_entries`, `contradiction_count`, `attention_fragmentation` |
| `thermal_reading` | SENSOR | 0.3 | 5s | tak | `cpu_temp_c`, `is_throttling` | `fan_speed_rpm` |
| `power_reading` | SENSOR | 0.3 | 5s | tak | `uptime_seconds`, `is_on_battery` | `voltage_v` |
| `time_reading` | SENSOR | 0.3 | 5s | tak | `idle_streak_sec`, `hour_of_day`, `session_duration_sec` | `day_of_week` |
| `user_message` | USER | 0.9 | 0 | nie | `text`, `channel` | `user_id` |
| `user_command` | USER | 0.9 | 0 | nie | `command`, `args` | `channel` |
| `chunk_learned` | LEARNING | 0.7 | 300s | nie | `file_id`, `chunk_index`, `chunks_total` | `summary_preview` |
| `file_scan_result` | LEARNING | 0.5 | 300s | tak | `new_files`, `changed_files`, `total_files` | |
| `exam_result` | EXAM | 0.8 | 300s | nie | `file_id`, `score`, `passed`, `attempt` | `num_questions` |
| `teacher_decision` | TEACHER | 0.5 | 300s | nie | `strategy_type`, `target_file_id` | `reason`, `iteration` |
| `teacher_session_complete` | TEACHER | 0.5 | 300s | nie | `chunks_learned`, `exams_run`, `exams_passed` | `errors` |
| `trait_emerged` | CONSCIOUSNESS | 0.5 | 300s | nie | `trait`, `score` | `previous_score` |
| `trait_faded` | CONSCIOUSNESS | 0.5 | 300s | nie | `trait`, `score` | `previous_score` |
| `dream_generated` | CONSCIOUSNESS | 0.5 | 300s | nie | `dream_count`, `session_id` | `themes` |
| `sleep_cycle` | CONSCIOUSNESS | 0.5 | 300s | nie | `phases_completed` | `dream_count` |
| `mode_change` | SYSTEM | 0.8 | 0 | nie | `from_mode`, `to_mode` | `trigger`, `health_score` |
| `alert` | SYSTEM | 1.0 | 0 | nie | `alert_type`, `severity`, `message` | `value`, `threshold` |
| `sandbox_promoted` | LEARNING | 0.7 | 300s | nie | `session_id`, `files_promoted`, `chunks_promoted` | |
| `sandbox_discarded` | LEARNING | 0.3 | 300s | nie | `session_id`, `reason` | |
| `goal_created` | SYSTEM | 0.5 | 0 | nie | `goal_id`, `goal_type`, `description` | `priority` |
| `goal_achieved` | SYSTEM | 0.5 | 0 | nie | `goal_id`, `goal_type` | `duration_sec` |

**Kolumny:**
- **priority** - domyslny priorytet (adapter moze nadpisac, np. alert CRITICAL = 1.0, WARNING = 0.5)
- **ttl** - domyslny czas zycia (0 = bez limitu)
- **dedup** - czy mozna dedupowac (tak = jesli identyczny payload w buforze, nowy event zastepuje stary)

**Dodawanie nowych event_type:** Dopisz do tej tabeli PRZED implementacja adaptera.
Jesli payload nie pasuje do zadnego istniejacego typu, to znak ze potrzebny nowy typ.

### Adaptery (mapowanie istniejacych strumieni)

6 adapterow, kazdy z metoda `to_perception_event()`:

| Adapter | Zrodlo | Event types |
|---------|--------|-------------|
| `sensor_adapter.py` | ResourceMetrics, CognitiveMetrics, ThermalMetrics, PowerMetrics, TimeMetrics | `resource_reading`, `cognitive_reading`, `thermal_reading`, `power_reading`, `time_reading` |
| `user_adapter.py` | REPL input, WebUI messages | `user_message`, `user_command` |
| `learning_adapter.py` | `learn_next_chunk()` return | `chunk_learned`, `file_scan_result` |
| `exam_adapter.py` | `run_exam_if_ready()` return | `exam_result`, `exam_failed` |
| `consciousness_adapter.py` | ExperienceTracker, SleepProcessor | `trait_emerged`, `trait_faded`, `dream_generated`, `sleep_cycle` |
| `teacher_adapter.py` | TeacherAgent decisions | `teacher_decision`, `teacher_session_complete` |

### Przyklad: Sensor reading → PerceptionEvent

```python
PerceptionEvent(
    event_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    source=PerceptionSource.SENSOR,
    event_type="resource_reading",
    priority=0.3,
    timestamp=1709312400.0,
    payload={
        "ram_available_mb": 18200.0,
        "ram_available_pct": 56.8,
        "cpu_percent": 12.3,
        "temp_c": 52.0,
        "disk_used_pct": 34.2,
        "inference_latency_ms": 450.0,
    },
    ttl=5.0,
    parent_event_id=None,
)
```

### Przyklad: User message → PerceptionEvent

```python
PerceptionEvent(
    event_id="e5f6g7h8-...",
    source=PerceptionSource.USER,
    event_type="user_message",
    priority=0.9,
    timestamp=1709312405.0,
    payload={
        "text": "Co wiesz o fizyce kwantowej?",
        "channel": "repl",
    },
    ttl=0,
    parent_event_id=None,
)
```

### Przyklad: Exam result (downstream of teacher decision)

```python
PerceptionEvent(
    event_id="i9j0k1l2-...",
    source=PerceptionSource.EXAM,
    event_type="exam_result",
    priority=0.8,
    timestamp=1709312500.0,
    payload={
        "file_id": "quantum_basics.txt",
        "score": 0.75,
        "passed": True,
        "num_questions": 6,
        "attempt": 1,
    },
    ttl=300.0,
    parent_event_id="m3n4o5p6-...",  # event_id teacher_decision ktory wywoial ten egzamin
)
```

### PerceptionBuffer

```python
class PerceptionBuffer:
    """Sliding window ostatnich zdarzen percepcji."""

    def __init__(self, maxlen: int = 200):
        self._buffer: deque = deque(maxlen=maxlen)

    def push(self, event: PerceptionEvent) -> None:
        """Dodaj zdarzenie do bufora."""
        self._buffer.append(event)

    def get_recent(self, n: int = 10, source: Optional[PerceptionSource] = None) -> List[PerceptionEvent]:
        """Pobierz N ostatnich zdarzen, opcjonalnie filtruj po zrodle."""
        ...

    def get_by_priority(self, min_priority: float = 0.5) -> List[PerceptionEvent]:
        """Pobierz zdarzenia o priorytecie >= min_priority."""
        ...

    def drain_expired(self) -> int:
        """Usun wygasle zdarzenia (ttl). Zwraca liczbe usunietych."""
        ...
```

### Czego NIE obejmuje

- Brak async/threading w PerceptionEvent (adaptery sa synchroniczne)
- Brak walidacji schema w runtime (payload jest trusted, rejestr to dokumentacja)
- Brak persystencji w warstwie percepcji (kazdy subsystem ma wlasny JSONL)
- Brak adapterow Vision/Smart Home (dodane gdy Warstwa 4/6 bedzie budowana)
- Brak deduplikacji (przy 1Hz z 5-6 zrodel duplikaty nie sa problemem)

---

## Kontrakt 2: Sandbox / Production Boundary

### Problem

Nauka pisze bezposrednio do produkcyjnych JSONL. Brak walidacji przed zapisem.
Jeden zly wynik LLM = smieci w bazie wiedzy na zawsze.

### Zasada naczelna

**KAZDA operacja nauki idzie przez sandbox. Promote() to JEDYNY most do produkcji.**

### Schema

```python
class SandboxStatus(Enum):
    ACTIVE = "active"            # Sandbox jest aktywny, trwa nauka
    READY_TO_PROMOTE = "ready"   # Kryteria spelnione, czeka na promote
    PROMOTED = "promoted"        # Zawartosc przeniesiona do produkcji
    DISCARDED = "discarded"      # Zawartosc odrzucona


@dataclass
class SandboxSession:
    """Jedna izolowana sesja nauki."""
    session_id: str              # UUID
    created_at: float            # time.time()
    status: SandboxStatus

    # Sciezki
    sandbox_dir: Path            # meta_data/sandbox/sess_<id>/
    sandbox_index: Path          # sandbox_dir / "knowledge_index.jsonl"
    sandbox_memory: Path         # sandbox_dir / "maria_longterm_memory.jsonl"
    sandbox_exams: Path          # sandbox_dir / "exam_results.jsonl"

    # Metryki (aktualizowane po kazdej operacji)
    files_learned: int = 0
    chunks_learned: int = 0
    exams_passed: int = 0
    exams_total: int = 0
    avg_score: float = 0.0
    validation_errors: List[str] = field(default_factory=list)

    def meets_promote_criteria(self) -> bool:
        """Sprawdz czy sandbox jest gotowy do promocji."""
        return (
            len(self.validation_errors) == 0
            and self.exams_total > 0
            and self.avg_score >= 0.6  # = EXAM_PASS_THRESHOLD
            and self.chunks_learned > 0
        )


@dataclass
class PromoteResult:
    """Wynik operacji promote()."""
    success: bool
    files_promoted: int
    chunks_promoted: int
    errors: List[str] = field(default_factory=list)
```

### Operacje dozwolone w sandboxie

| Operacja | Dozwolona? | Uwagi |
|----------|-----------|-------|
| `learn_next_chunk()` | TAK | Z `index_path=sandbox_index, memory_path=sandbox_memory` |
| `run_exam_if_ready()` | TAK | Z `index_path=sandbox_index, exam_path=sandbox_exams` |
| Re-learn (retry) | TAK | Ponowna nauka z innymi promptami |
| Modyfikacja semantic_graph | NIE | Dopiero po promote |
| Modyfikacja personality traits | NIE | Nauka nie zmienia osobowosci |

**Kluczowe:** Bez zmian w `learning_agent.py` / `exam_agent.py` - juz przyjmuja parametry sciezek.

### Reguly promote()

**Warunki obowiazkowe (wszystkie musza byc spelnione):**

1. `chunks_learned > 0` - cos zostalo nauczone
2. `exams_total > 0` - przynajmniej jeden egzamin
3. `avg_score >= 0.6` - sredni wynik >= prog zdania (EXAM_PASS_THRESHOLD)
4. Wszystkie JSONL w sandboxie parsuja sie poprawnie
5. Brak wpisow w `validation_errors`

**Mechanizm:**
- Promote = APPEND rekordow z sandbox JSONL do production JSONL
- Uzywa istniejacego file locking z `memory_store.py`
- Index records mergowane po `file_id` (nowszy `updated_at` wygrywa)
- Promote jest **atomowy per sesja**: wszystko albo nic
- Po udanym promote: katalog sandbox sesji jest kasowany

**Transaction log (`meta_data/promote_log.jsonl`):**

Kazdy promote zapisuje markery START/COMMIT (lub ROLLBACK) zeby wykryc przerwane operacje:

```json
{"ts": 1709312500.0, "marker": "START", "session_id": "sess_abc123", "files": 2, "chunks": 8}
{"ts": 1709312500.5, "marker": "COMMIT", "session_id": "sess_abc123", "result": "ok"}
```

Jesli na starcie systemu znajdziemy START bez COMMIT:
1. Sandbox dir jeszcze istnieje → dane nie zostaly przeniesione, status OK (sandbox intact)
2. Sandbox dir nie istnieje → partial append moglo wystapic → WARNING w logach, manual review

```json
{"ts": 1709312500.0, "marker": "ROLLBACK", "session_id": "sess_abc123", "reason": "validation_error", "exception": "JSONDecodeError at line 42"}
```

Reguly:
- START zawsze PRZED pierwszym appendem do produkcji
- COMMIT po WSZYSTKICH appendach zakonczonych + sandbox dir usuniety
- ROLLBACK jesli jakikolwiek append sie nie powiodl (sandbox dir pozostaje)
  - ROLLBACK MUSI zawierac `reason` (krotki opis) i `exception` (string bledu lub null)
- **Na starcie systemu:** scan promote_log.jsonl, jesli ostatni wpis to START bez COMMIT:
  1. Jesli sandbox dir istnieje → **auto-DISCARD** sesji (nie zombie, czyste zamkniecie)
  2. Jesli sandbox dir NIE istnieje → WARNING w logach + manual review (partial append)
  3. W obu przypadkach: dopisz ROLLBACK marker z `reason: "startup_recovery"`

### Reguly discard()

| Trigger | Akcja |
|---------|-------|
| User jawnie wywola `/sandbox discard` | Kasuj katalog sandbox sesji |
| Sandbox starszy niz 24h bez promote | Auto-discard |
| System wchodzi w SURVIVAL | Auto-discard WSZYSTKICH aktywnych |
| Discard | = kasuje caly katalog `sandbox_dir` |

### Flow

```
Teacher/User zleca nauke
  |
  v
SandboxManager.create_session()
  → meta_data/sandbox/sess_abc123/
  |
  v
seed_from_production(file_ids)
  ← kopiuje rekordy z memory/knowledge_index.jsonl
  |
  v
learn_next_chunk(path=sandbox)
  ← pisze do sandbox JSONL
  |
  v
run_exam_if_ready(path=sandbox)
  |
  v
meets_promote_criteria()?
  |
  ├── YES → promote()
  |         ├── append do memory/*.jsonl
  |         ├── kasuj sandbox dir
  |         └── emit PerceptionEvent(source=LEARNING, type="sandbox_promoted")
  |
  └── NO  → retry (re-learn) lub discard()
            └── emit PerceptionEvent(source=LEARNING, type="sandbox_discarded")
```

### Ograniczenia

- Max 1 aktywna sandbox sesja (Maria uczy sie ~10 plikow, nie milionow)
- Brak sandbox dla chat/conversation (tylko nauka)
- Brak partial promote (cherry-picking pojedynczych plikow)
- Brak versioning/rollback produkcji (od tego jest backup.sh)

---

## Kontrakt 3: Goal System

### Problem

Cele sa implicit - hardcoded thresholdy w mode_regulator, if/elif chain w teacher P1-P6.
Nie mozna ich zmieniac w runtime, nie maja historii, nie mozna ich obserwowac.

### Rozwiazanie: Minimalny model celow

```python
class GoalType(Enum):
    META = "meta"                # Misja systemu (1 cel, zawsze aktywny)
    USER = "user"                # Cele od uzytkownika (przez /goal create)
    LEARNING = "learning"        # Cele nauki (generowane z Teacher P1-P6)
    MAINTENANCE = "maintenance"  # Cele utrzymania (z homeostasis thresholds)


class GoalStatus(Enum):
    PROPOSED = "proposed"        # Auto-sugerowany, czeka na potwierdzenie usera
    PENDING = "pending"          # Zatwierdzony, nie rozpoczety
    ACTIVE = "active"            # W trakcie realizacji
    ACHIEVED = "achieved"        # Zrealizowany
    FAILED = "failed"            # Nie udalo sie
    ABANDONED = "abandoned"      # Swiadomie porzucony


@dataclass
class AuditEntry:
    """Zapis zmiany statusu celu."""
    timestamp: float
    old_status: str
    new_status: str
    reason: str
    actor: str                   # "teacher" / "user" / "homeostasis" / "planner" / "system"


@dataclass
class Goal:
    """Pojedynczy cel w systemie celow Marii."""
    id: str                      # UUID
    type: GoalType
    description: str             # Human-readable (po polsku OK)
    priority: float              # 0.0 do 1.0
    status: GoalStatus
    progress: float              # 0.0 do 1.0
    parent_goal_id: Optional[str]  # Hierarchia celow
    created_by: str              # "system" / "user" / "teacher" / "homeostasis"
    created_at: float            # time.time()
    updated_at: float            # time.time()
    deadline: Optional[float]    # Opcjonalny (informacyjny, Planner moze uzyc)
    audit_trail: List[AuditEntry] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### Mapowanie obecnych implicit goals

#### META (seed goal, tworzony na pierwszym uruchomieniu)

```
Goal(
    id="goal-meta-learn",
    type=META,
    description="Autonomiczna nauka i strukturyzacja wiedzy z plikow tekstowych",
    priority=1.0,
    status=ACTIVE,
    progress=<obliczany z knowledge_coverage>,
    parent_goal_id=None,
    created_by="system",
)
```

#### LEARNING (generowane z Teacher P1-P6)

| Teacher Priority | Goal description | Priority | Metadata |
|-----------------|------------------|----------|----------|
| P1 | "Kontynuuj nauke: {file} ({n}/{m} chunkow)" | 0.9 | `teacher_priority: 1, file_id, chunks_done, chunks_total` |
| P2 | "Egzamin z: {file}" | 0.85 | `teacher_priority: 2, file_id` |
| P3 | "Zacznij nowy plik: {file}" | 0.7 | `teacher_priority: 3, file_id` |
| P4 | "Powtorka: {file} (wynik: {score}%)" | 0.6 | `teacher_priority: 4, file_id, last_score` |
| P5 | "Ponow trudny temat: {file}" | 0.5 | `teacher_priority: 5, file_id` |
| P6 | "NIM analiza luk wiedzy" | 0.4 | `teacher_priority: 6` |

#### MAINTENANCE (zawsze aktywne)

```
Goal(id="goal-maint-health", type=MAINTENANCE,
     description="Utrzymaj health_score >= 0.7",
     priority=1.0, status=ACTIVE,
     progress=<current health / threshold>,
     metadata={"metric": "health_score", "threshold": 0.7})

Goal(id="goal-maint-ram", type=MAINTENANCE,
     description="RAM dostepny > 20%",
     priority=0.95, status=ACTIVE,
     parent_goal_id="goal-maint-health",
     metadata={"metric": "ram_available_pct", "threshold": 20})

Goal(id="goal-maint-cpu", type=MAINTENANCE,
     description="CPU < 75%",
     priority=0.95, status=ACTIVE,
     parent_goal_id="goal-maint-health",
     metadata={"metric": "cpu_load", "threshold": 75})
```

#### USER (dwa tryby tworzenia)

**Tryb 1: Jawny** - uzytkownik tworzy cel komenda REPL:
```
# /goal create "Naucz sie wszystkiego o fizyce"
Goal(id="goal-user-physics", type=USER,
     description="Naucz sie wszystkiego o fizyce",
     priority=0.8, status=PENDING,       # Od razu PENDING (zatwierdzony)
     created_by="user")
```

**Tryb 2: Auto-sugerowany** - Maria wykrywa intencje w rozmowie i PROPONUJE cel:
```
# User pisze: "Chcialbym wiedziec wiecej o astronomii"
# Maria wykrywa intencje i tworzy PROPOSED goal:
Goal(id="goal-user-astronomy", type=USER,
     description="Poglebic wiedze o astronomii",
     priority=0.7, status=PROPOSED,      # PROPOSED - czeka na potwierdzenie
     created_by="consciousness",          # Maria sama zaproponowala
     metadata={"source_message": "Chcialbym wiedziec wiecej o astronomii",
               "confidence": 0.8})

# Maria pyta: "Czy chcesz zebym postawila sobie cel: 'Poglebic wiedze o astronomii'?"
# User: tak → status PROPOSED → PENDING (audit: "user confirmed")
# User: nie → status PROPOSED → ABANDONED (audit: "user rejected")
```

**Reguly auto-sugestii:**
- Maria NIGDY nie aktywuje auto-celu bez potwierdzenia usera
- **PROPOSED nie wplywa na system** (izolacja od planowania):
  - Nie zmienia teacher priorities (P1-P6 ignoruja PROPOSED)
  - Nie generuje zadan nauki
  - Nie zmienia planu dnia
  - Nie wplywa na mode regulator ani homeostasis
  - Dopiero po CONFIRM (PROPOSED → PENDING) cel wchodzi do systemu
- PROPOSED goals starsze niz 24h bez odpowiedzi → auto-ABANDONED
- Max 3 PROPOSED goals jednoczesnie (nie zalewaj usera pytaniami)
- Wykrywanie intencji: czysta logika (keyword matching na "chce", "naucz", "pokaz", itp.) - zero LLM w v1

### Reguly

| Regula | Wartosc | Uzasadnienie |
|--------|---------|-------------|
| Max aktywnych celow | 20 | Maria uczy sie ~10 plikow; 20 daje zapas |
| Max PROPOSED celow | 3 | Nie zalewaj usera pytaniami |
| Max glebokosc hierarchii | 3 | META → LEARNING/MAINTENANCE → sub-goal |
| Audit trail | Obowiazkowy | Kazda zmiana statusu = AuditEntry z reason i actor |
| Auto-ACHIEVED | progress >= 1.0 przy ACTIVE | System automatycznie zamyka zrealizowane cele |
| PROPOSED timeout | 24h | PROPOSED bez odpowiedzi → auto-ABANDONED |
| MAINTENANCE reset | Co sesje | MAINTENANCE goals nigdy ACHIEVED, resetowane na starcie |
| ABANDON overflow | Najnizszy PENDING | Przy przekroczeniu 20 aktywnych |
| Persystencja | `meta_data/goals.jsonl` | Append-only, ostatni rekord per id wygrywa |
| Runtime modyfikacja | Tak | Kazdy modul z `SharedContext.goal_store` moze CRUD |
| Auto-sugestia | Human-in-the-loop | Maria NIGDY nie aktywuje celu bez potwierdzenia usera |
| PROPOSED izolacja | Zero wplywu | PROPOSED nie zmienia priorities, nie generuje zadan, nie zmienia planu |

### GoalStore API

```python
class GoalStore:
    """CRUD + persystencja celow."""

    def create(self, goal: Goal) -> str:
        """Utworz cel (status PENDING lub ACTIVE), zwroc id."""

    def propose(self, goal: Goal) -> str:
        """Utworz cel ze statusem PROPOSED (czeka na potwierdzenie usera). Zwroc id."""

    def confirm(self, goal_id: str) -> bool:
        """User potwierdza PROPOSED goal → PENDING. Zwraca False jesli goal nie jest PROPOSED."""

    def reject(self, goal_id: str) -> bool:
        """User odrzuca PROPOSED goal → ABANDONED. Zwraca False jesli goal nie jest PROPOSED."""

    def get(self, goal_id: str) -> Optional[Goal]:
        """Pobierz cel po id."""

    def get_active(self, goal_type: Optional[GoalType] = None) -> List[Goal]:
        """Pobierz aktywne cele (PENDING + ACTIVE), opcjonalnie filtruj po typie."""

    def get_proposed(self) -> List[Goal]:
        """Pobierz cele czekajace na potwierdzenie usera (status PROPOSED)."""

    def update_status(self, goal_id: str, status: GoalStatus, reason: str, actor: str) -> bool:
        """Zmien status z audit trail."""

    def update_progress(self, goal_id: str, progress: float) -> bool:
        """Aktualizuj postep (auto-ACHIEVED przy 1.0)."""

    def abandon_lowest(self) -> Optional[str]:
        """Porzuc najnizszy priorytet PENDING goal. Zwraca id lub None."""

    def expire_proposed(self) -> int:
        """Auto-ABANDON PROPOSED goals starszych niz 24h. Zwraca liczbe porzuconych."""

    def load(self) -> None:
        """Zaladuj z meta_data/goals.jsonl."""

    def save(self) -> None:
        """Zapisz do meta_data/goals.jsonl (append-only)."""
```

### Czego NIE obejmuje

- Brak generowania celow przez LLM w v1 (czysta logika / keyword matching)
- Brak grafu zaleznosci miedzy celami (tylko parent-child)
- Brak enforcement deadline (informacyjny, Planner moze uzyc w przyszlosci)
- Brak szablonow celow
- Brak automatycznego tworzenia sub-celow
- Auto-sugestia NIGDY nie aktywuje celu bez potwierdzenia usera (human-in-the-loop)

---

## Kontrakt 4: Agent Evaluation

### Problem

Ewaluacja jest rozproszona: exam scores w jednym JSONL, health_score w innym,
teacher stats w pamieci. Brak jednego spojnego obrazu "jak Maria sobie radzi".

### Zasada naczelna

**Scisle READ-ONLY** (rozszerzenie ADR-006, jak introspection).
Observer czyta logi i metryki, NIGDY ich nie modyfikuje.

### 5 kluczowych metryk

| # | Metryka | Definicja | Zrodlo danych | Okno |
|---|---------|-----------|---------------|------|
| 1 | `learning_velocity` | chunks / hour | `teacher_plans.jsonl` | Rolling 1h |
| 2 | `retention_rate` | exams_passed / exams_total | `exam_results.jsonl` | All-time |
| 3 | `knowledge_coverage` | completed_files / total_files | `knowledge_index.jsonl` | Current |
| 4 | `system_stability` | avg health_score | `homeostasis_events.jsonl` | Rolling 1h |
| 5 | `personality_growth` | sum \|trait_delta\| | `personality_experiences.jsonl` | Last N sessions |

### Format raportu (JSON)

```json
{
  "timestamp": 1709312400.0,
  "report_id": "eval-abc123",
  "period_start": 1709308800.0,
  "period_end": 1709312400.0,

  "metrics": {
    "learning_velocity": 2.4,
    "retention_rate": 0.78,
    "knowledge_coverage": 0.45,
    "system_stability": 0.92,
    "personality_growth": 0.12
  },

  "details": {
    "learning_velocity": {
      "chunks_last_1h": 2,
      "chunks_last_24h": 18,
      "trend": "stable"
    },
    "retention_rate": {
      "exams_passed": 7,
      "exams_total": 9,
      "last_5_scores": [0.85, 0.70, 0.90, 0.60, 0.75]
    },
    "knowledge_coverage": {
      "completed_files": 5,
      "total_files": 11,
      "hard_topics": 2,
      "new_files": 3
    },
    "system_stability": {
      "avg_health_1h": 0.92,
      "avg_health_24h": 0.88,
      "mode_changes_24h": 3,
      "critical_alerts_24h": 0
    },
    "personality_growth": {
      "traits_emerged": ["wytrwala"],
      "traits_faded": [],
      "total_trait_delta": 0.12,
      "sessions_analyzed": 5
    }
  },

  "data_sources": {
    "homeostasis_events": "meta_data/homeostasis_events.jsonl",
    "exam_results": "memory/exam_results.jsonl",
    "knowledge_index": "memory/knowledge_index.jsonl",
    "personality_experiences": "meta_data/personality_experiences.jsonl",
    "teacher_plans": "meta_data/teacher_plans.jsonl"
  },

  "recommendations": [
    "Retention rate < 80% - rozwazyc wiecej powtórek (P4)",
    "2 hard topics - rozwazyc retry po ukonczeniu jeszcze 1 pliku"
  ]
}
```

### Reguly

| Regula | Wartosc |
|--------|---------|
| Tryb | READ-ONLY (ADR-006 rozszerzony) |
| Pisze do | TYLKO `meta_data/evaluation_reports.jsonl` (wlasne raporty) |
| Czestotliwosc | On-demand (`/evaluate`) + co 300 tickow (5 min) w ACTIVE |
| LLM | ZERO (czysta logika, thresholdy) |
| Wzorzec implementacji | Jak `knowledge_analyzer.py` (czyta JSONL, zero side effects) |

### Rekomendacje (thresholdy)

| Warunek | Rekomendacja |
|---------|-------------|
| `retention_rate < 0.8` | "Rozwazyc wiecej powtórek (P4)" |
| `retention_rate < 0.6` | "Retention krytycznie niska - uproszic prompty" |
| `learning_velocity == 0` przez 2h | "Brak nauki od 2h" |
| `knowledge_coverage > 0.9` | "Prawie wszystko nauczone - szukac nowych materialow" |
| `system_stability < 0.7` | "System niestabilny - sprawdzic zasoby" |
| `personality_growth == 0` przez 3 sesje | "Brak ewolucji osobowosci" |

### Feed do Goal System (przyszlosc)

Observer **SUGERUJE**, GoalStore **DECYDUJE**:

```
retention_rate < 0.7
  → sugestia: boost priority celow P4 (powtorki) o +0.1

learning_velocity == 0 przez 2h
  → sugestia: nowy cel LEARNING "wznow nauke"

knowledge_coverage > 0.9
  → sugestia: cel META "szukaj nowych materialow"
```

Observer nigdy nie modyfikuje celow bezposrednio.
Sugestie to `List[GoalAdjustment]` ktore GoalStore moze przyjac lub zignorowac.

### Czego NIE obejmuje

- Brak wywolan LLM (czysta matematyka + thresholdy)
- Brak modyfikacji zrodlowych JSONL
- Brak alertow (to domena homeostasis)
- Brak trendow/wykresow (to domena Web UI)
- Brak porownania miedzy sesjami (future feature)

---

## Kontrakt 5: Planner

### Problem

K1-K4 daly Marii percepcje, sandbox, cele i ewaluacje - ale nie ma "sprawcy" ktory to laczy.
Teacher (P1-P6) dziala na if/elif chain z hardcoded priorytetami, Phase 10 tick loop
odpala go co 10min idle. Brak centralnej petli decyzyjnej.

### Rozwiazanie: Rule-based ReAct Loop (ADR-013)

Planner v1 = deterministyczny, rule-based, zero LLM. Testable i przewidywalny.

```
OBSERVE -> THINK -> ACT -> EVALUATE
   |                          |
   +-------- REPEAT ----------+
```

- **OBSERVE:** Odczytaj PerceptionBuffer (K1), GoalStore (K3), EvaluationObserver (K4)
- **THINK:** GoalSelector wybiera cel, PlannerGuard sprawdza gating rules
- **ACT:** ActionExecutor deleguje do Teacher/Sandbox (K2)
- **EVALUATE:** Emit PerceptionEvent(PLANNER), log decision

### Planner zastepuje Phase 10

Phase 10 tick loop (teacher auto-trigger) zostaje zastapiona PlannerCore:
- Jesli PlannerCore podlaczony: `planner.run_cycle(tick)` w Phase 10
- Jesli nie: fallback na stary `_check_teacher_trigger()` (backward-compatible)

### Model danych

```python
class PlanStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ActionType(Enum):
    LEARN = "learn"          # Deleguj nauke do Teacher
    EXAM = "exam"            # Deleguj egzamin do Teacher
    REVIEW = "review"        # Deleguj powtorke do Teacher
    EVALUATE = "evaluate"    # Wygeneruj raport K4
    MAINTENANCE = "maintenance"  # Sprawdz metryki zdrowia
    NOOP = "noop"            # Nic do zrobienia


@dataclass
class Plan:
    """Pojedynczy krok planowania (nie drzewo/graf)."""
    plan_id: str             # UUID
    timestamp: float
    goal_id: Optional[str]   # Cel ktory realizuje
    goal_description: str
    action_type: ActionType
    action_params: Dict[str, Any]
    status: PlanStatus
    result: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None  # Opcjonalny (per ChatGPT review)
    duration_ms: float = 0.0


@dataclass
class PlannerState:
    """Stan persystentny Plannera (planner_state.json)."""
    total_cycles: int = 0
    total_plans: int = 0
    last_plan_id: Optional[str] = None
    last_evaluation_ts: float = 0.0
    last_cycle_ts: float = 0.0
```

### Planner Guard (gating rules)

Planner NIE planuje jesli warunki nie sa spelnione:

| Regula | Warunek blokujacy | Uzasadnienie |
|--------|-------------------|-------------|
| Health | `health_score < 0.7` | System nie zdrowy - nie obciazaj |
| Mode | `mode != ACTIVE` | W REDUCED/SLEEP/SURVIVAL nie planuj nauki |
| Sandbox | Aktywna sesja sandbox | Poczekaj na promote/discard |
| Retention | `retention_rate < 0.5` | Za duzo oblanych - nie dodawaj nowej nauki |
| Teacher | Teacher thread aktywny | Nie interferuj z biezaca sesja |

```python
class PlannerGuard:
    def can_plan(self, health, mode, sandbox_active,
                 retention, teacher_running) -> Tuple[bool, List[str]]:
        """Zwraca (can_plan, list_of_block_reasons)."""
```

### Goal Selector (aging factor)

Zapobiega starvation (dlugo czekajacy cel jest promowany):

```python
effective_priority = priority * (1.0 + min(hours_pending * 0.1, 4.0))
```

- Po 1h pending: x1.1
- Po 10h pending: x2.0
- Po 24h pending: x3.4
- Max: x5.0 (clamp)

Feasibility check per goal type:
- MAINTENANCE / META / USER: zawsze feasible
- LEARNING: wymaga dostepnych plikow do nauki

### Action Executor

Planner decyduje CO, Executor robi JAK:

| ActionType | Delegacja |
|-----------|-----------|
| LEARN / EXAM / REVIEW | `TeacherAgent.run_session(max_iterations=1)` |
| EVALUATE | `EvaluationObserver.generate_report()` |
| MAINTENANCE | Update goal progress z system metrics |
| NOOP | Nic nie rob |

### Hybrid Frequency

| Trigger | Warunek | Opis |
|---------|---------|------|
| Routine | Co 60 tickow (~1min) | Regularny cykl planowania |
| Event-driven | `exam_result` | Natychmiast po egzaminie |
| Event-driven | `alert` | Natychmiast na alert |
| Event-driven | `user_command` | Natychmiast na komende usera |
| Event-driven | `sandbox_promoted` | Natychmiast po promote |

### Percepcja (nowe typy)

PerceptionSource += `PLANNER`

| event_type | source | priority | ttl | dedup | Payload |
|-----------|--------|----------|-----|-------|---------|
| `planner_decision` | PLANNER | 0.5 | 300s | nie | `plan_id`, `goal_id`, `action_type`, `goal_description` |
| `planner_cycle_complete` | PLANNER | 0.3 | 60s | tak | `tick`, `planned`, `guard_blocked`, `no_goals` |

### Persystencja

| Plik | Format | Opis |
|------|--------|------|
| `meta_data/planner_state.json` | JSON | Biezacy stan (cykle, ostatni plan) |
| `meta_data/planner_decisions.jsonl` | JSONL (append) | Historia decyzji |

### Cooldown

- Evaluation co 1h (nie czesciej) - anty-oscylacja na recommendations
- Planner Guard blokuje planowanie nauki gdy retention < 0.5

### REPL commands

| Komenda | Opis |
|---------|------|
| `/plan` | Ostatnia decyzja plannera |
| `/plan status` | Cykle, plany, ostatni eval |
| `/plan history [N]` | Historia decyzji (domyslnie 10) |
| `/plan goals` | Ranking celow wg effective priority |

### Struktura plikow

```
agent_core/planner/
  __init__.py
  planner_model.py     # Plan, PlanStatus, ActionType, PlannerState
  planner_guard.py     # PlannerGuard.can_plan() - 5 gating rules
  goal_selector.py     # GoalSelector.select_goal() - aging + feasibility
  action_executor.py   # ActionExecutor.execute() - delegacja
  planner_core.py      # PlannerCore - centralny ReAct loop

agent_core/modules/
  planner_module.py    # REPL /plan commands
```

### Modyfikacje istniejacych plikow

| Plik | Zmiana |
|------|--------|
| `agent_core/perception/event.py` | +PLANNER source, +2 event types |
| `agent_core/registry/shared_context.py` | +planner_core field |
| `agent_core/homeostasis/core.py` | Phase 10: planner z fallbackiem na teacher |
| `agent_core/modules/homeostasis_module.py` | Wire PlannerCore |
| `main.py` | `registry.try_register(make_planner, "planner")` |

### Nowe ADR

| ADR | Decyzja |
|-----|---------|
| **ADR-013** | Planner v1 rule-based (zero LLM, deterministic, testable) |

### Czego NIE obejmuje (v1)

- Brak LLM w petli decyzyjnej (rule-based only)
- Brak multi-step planow (Plan = single step)
- Brak drzew/grafow planowania
- Brak priorytyzacji miedzy rownoleglymi celami (sekwencyjny)
- Brak rollback planow (failed = log + next cycle)
- Brak auto-generowania celow (to domena GoalStore)

---

## Decyzja 5: Tick Aggregator (ADR-009)

### Pytanie

Jak koordynowac zdarzenia miedzy modulami?
- Opcja A: Pelny pub/sub event bus
- Opcja B: Lightweight tick aggregator (rozszerzenie istniejacego tick loop)

### Decyzja: Opcja B - Tick Aggregator

### Uzasadnienie

1. **Tick loop JUZ jest agregatorem** - 9 faz sekwencyjnie, wszystkie dane przechodza przez jeden punkt w `HomeostasisCore._execute_tick()`
2. **Deterministyczna kolejnosc** - fazy gwarantuja ze sensor reading jest przetworzony PRZED mode regulator. Event bus tego nie gwarantuje.
3. **Prostota threading** - ADR-002 mowi "threading nie asyncio". Pub/sub z threading = locki, race conditions. Tick loop = 1 watek + 1 deque dla external events.
4. **5-6 zrodel, nie setki** - event bus sie oplaca przy dziesieciach producentow. Maria ma 6.
5. **1s latency jest OK** - Maria uczy sie z plikow tekstowych, nie potrzebuje sub-sekundowej reakcji na zdarzenia.
6. **HomeostasisEventBus juz istnieje i NIE jest uzywany** - `agent_core/homeostasis/api.py` ma pub/sub ale tick loop robi wszystko inline. System naturalnie ciagy ku synchronicznej agregacji.

### Mechanizm

Rozszerzenie Phase 8 tick loop o agregacje:

```python
# W HomeostasisCore._execute_tick(), po Phase 7:

# PHASE 8: AGGREGATE
tick_summary = TickSummary(
    tick=self._tick_count,
    timestamp=time.time(),
    sensor_events=sensor_events,         # Z Phase 1
    interpreted_state=interpreted_state,  # Z Phase 2
    alerts=alerts,                        # Z Phase 3
    mode=self.state.mode,                 # Z Phase 4
    actions=actions,                      # Z Phase 5-6
    health=self.state.health_score,       # Z Phase 7
    external_events=self._drain_external_queue(),
)
self._perception_buffer.ingest_tick(tick_summary)
```

External events (z watku REPL, teacher, etc.) wrzucane przez thread-safe deque:

```python
# Thread-safe kolejka dla zdarzen spoza tick loop
self._external_queue: deque = deque(maxlen=50)

def push_external_event(self, event: PerceptionEvent) -> None:
    """Wolane z watku REPL, teacher thread, etc. Thread-safe (deque jest thread-safe)."""
    self._external_queue.append(event)

def _drain_external_queue(self) -> List[PerceptionEvent]:
    """Wolane TYLKO z watku tick loop. Oproznia kolejke."""
    events = []
    while self._external_queue:
        try:
            events.append(self._external_queue.popleft())
        except IndexError:
            break
    return events
```

### Porownanie

| Aspekt | Event Bus (A) | Tick Aggregator (B) |
|--------|---------------|---------------------|
| Kolejnosc | Nieokreslona (callback order) | Deterministyczna (fazy) |
| Thread safety | Zlozony (locki na emit/subscribe) | Prosty (1 deque) |
| Latency | ~0ms | Max 1s (nastepny tick) |
| Zmiany w kodzie | Nowa klasa + rejestracja subscribentow | 10-15 linii w `_execute_tick()` |
| Testowanie | Lifecycle subscribentow | Istniejace testy tick loop |
| Debuggowanie | Kazdy emit/callback do logowania | Print tick summary |

### HomeostasisEventBus - co z nim?

Zostaje jak jest (ma testy, nie przeszkadza). Jesli przyszly modul potrzebuje push-style notifications (np. Web UI real-time alerts), moze subskrybowac. Ale core perception flow idzie przez tick aggregator, nie przez event bus.

---

## Struktura plikow

### Nowe pliki (do utworzenia przy implementacji)

```
agent_core/
  perception/
    __init__.py
    event.py                    # PerceptionEvent, PerceptionSource
    buffer.py                   # PerceptionBuffer (deque)
    adapters/
      __init__.py
      sensor_adapter.py         # ResourceMetrics -> PerceptionEvent
      user_adapter.py           # REPL/WebUI -> PerceptionEvent
      learning_adapter.py       # learn results -> PerceptionEvent
      exam_adapter.py           # exam results -> PerceptionEvent
      consciousness_adapter.py  # traits/sleep -> PerceptionEvent
      teacher_adapter.py        # decisions -> PerceptionEvent
  sandbox/
    __init__.py
    manager.py                  # SandboxManager (create/promote/discard)
    protocol.py                 # SandboxSession, PromoteResult, SandboxStatus
  goals/
    __init__.py
    goal_model.py               # Goal, GoalType, GoalStatus, AuditEntry
    store.py                    # GoalStore (CRUD + persistence)
  evaluation/
    __init__.py
    observer.py                 # EvaluationObserver (READ-ONLY)
    report.py                   # EvaluationReport schema
  planner/
    __init__.py
    planner_model.py            # Plan, PlanStatus, ActionType, PlannerState
    planner_guard.py            # PlannerGuard (5 gating rules)
    goal_selector.py            # GoalSelector (aging + feasibility)
    action_executor.py          # ActionExecutor (delegacja)
    planner_core.py             # PlannerCore (ReAct loop)
  modules/
    evaluation_module.py        # REPL /evaluate command
    planner_module.py           # REPL /plan commands
```

### Dane (nowe pliki JSONL)

```
meta_data/
  goals.jsonl                   # Goal records (append-only)
  evaluation_reports.jsonl      # Evaluation reports (append-only)
  planner_state.json            # Planner current state (K5)
  planner_decisions.jsonl       # Planner decision history (K5, append-only)
  sandbox/                      # Katalog sandbox sesji
    sess_<uuid>/                # Jedna sesja
      knowledge_index.jsonl
      maria_longterm_memory.jsonl
      exam_results.jsonl
```

---

## Integracja

### Istniejace pliki do modyfikacji

| Plik | Zmiana |
|------|--------|
| `agent_core/registry/shared_context.py` | Nowe pola: `perception_buffer`, `goal_store`, `evaluation_observer`, `sandbox_manager` |
| `agent_core/homeostasis/core.py` | Phase 8: tick aggregation + external queue. Periodic evaluation trigger. |
| `agent_core/modules/homeostasis_module.py` | Wiring nowych komponentow w `init()` |
| `agent_core/modules/teacher_module.py` | Sandbox paths zamiast production paths |
| `maria_core/sys/config.py` | `SANDBOX_DIR = BASE_DIR / "meta_data" / "sandbox"` |

### Nowe ADR

| ADR | Decyzja |
|-----|---------|
| **ADR-009** | Tick Aggregator zamiast Event Bus (KISS, deterministyczna kolejnosc) |
| **ADR-010** | Sandbox-first learning (kazda nauka przez sandbox, promote jako jedyny most) |
| **ADR-011** | Goals as data (cele sa obiektami danych z audit trail, nie hardcoded logika) |
| **ADR-012** | Evaluation READ-ONLY (rozszerzenie ADR-006 na ewaluacje agenta) |
| **ADR-013** | Planner v1 rule-based (zero LLM, deterministyczny, testowalny) |

---

*Utworzono: 2026-03-01*
*Zatwierdzone przez: Eryk + Claude*
*Warstwa 1 (K1-K4): Zaimplementowana (941 testow)*
*Warstwa 2 (K5 Planner): Zaimplementowana (1023 testow)*
