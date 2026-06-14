# Planner v2 - Adaptive Planning with Strategic LLM

> Design doc. Status: DRAFT. Wymaga review Eryka przed implementacja.

## Problem

Planner v1 (ADR-013) jest rule-based i deterministyczny - dobry na start, ale:

1. **Retry spam** - prubuje review co minute poza learning window (zablokowany, prubuje znowu)
2. **Brak backoff na failed goals** - ten sam cel wybierany po kazdym NOOP
3. **Brak time-awareness** - nie wie ze wieczorem lepiej robic creative niz learn
4. **Brak priorytyzacji dynamicznej** - aging factor to za malo
5. **Brak "swiadomego idle"** - NOOP to petla, nie decyzja

## Architektura: Dual-Loop Planner

```
                    +--------------------------+
                    |   STRATEGIC LOOP (LLM)   |
                    |   qwen3:8b / co 30 min   |
                    |                          |
                    |   "Co robic nastepne?"   |
                    |   -> Plan dnia/godziny   |
                    |   -> Priorytety celow    |
                    |   -> Backoff decisions   |
                    +-----------+--------------+
                                |
                       strategic_plan.json
                                |
                    +-----------v--------------+
                    |   TACTICAL LOOP (rules)  |
                    |   per-tick / 60s          |
                    |                          |
                    |   Wykonuje plan LLM      |
                    |   Quick checks + guards  |
                    |   Fallback na reguly     |
                    +--------------------------+
```

### Strategic Loop (nowy, LLM-powered)

**Model:** qwen3:8b (MODEL-01, local, cold-start ~3s, 5.5GB)
**Czestotliwosc:** Co 30 min w ACTIVE, na event (nowy material, failure pattern), przy wake-up
**Fallback:** NIM API jesli local fail, rule-based jesli oba fail

**Input (prompt context):**
```json
{
  "current_time": "2026-04-16 10:30 Berlin (Wed)",
  "mode": "ACTIVE",
  "health": 0.92,
  "learning_window": true,
  "next_window_change": "11:00 (closes in 30min)",
  "active_goals": [
    {"id": "g-abc", "type": "learning", "topic": "logika", "progress": 0.4, "age_hours": 12},
    {"id": "g-def", "type": "learning", "topic": "python", "progress": 0.0, "age_hours": 48}
  ],
  "recent_actions": [
    {"action": "learn", "goal": "g-abc", "result": "success", "ago_min": 15},
    {"action": "exam", "goal": "g-abc", "result": "failed", "ago_min": 5}
  ],
  "knowledge_gaps": ["fizyka", "matematyka"],
  "retention_rate": 0.72,
  "available_materials": 3,
  "beliefs_weak": 12,
  "last_creative_ago_min": 90,
  "last_evaluate_ago_min": 45
}
```

**Output (structured JSON):**
```json
{
  "plan": [
    {"action": "review", "goal": "g-abc", "reason": "exam failed, review before retry"},
    {"action": "learn", "goal": "g-def", "reason": "new topic, start while window open"},
    {"action": "exam", "goal": "g-abc", "reason": "retry after review"}
  ],
  "blocked_until": {
    "g-def_exam": "wait until 2 chunks learned"
  },
  "idle_strategy": "creative",
  "notes": "Window closes at 11:00 - prioritize learning. After window: creative + evaluate."
}
```

### Tactical Loop (ulepszony v1)

Per-tick, rule-based, zero LLM. Zmiany vs v1:

1. **Czyta strategic_plan** zamiast samodzielnie wybierac cele
2. **Backoff z pamiecia** - jesli akcja failowala 3x, skip do zmiany warunkow (nie timer)
3. **Time-slot awareness** - wie ze 10:45 to "ostatnie 15min window, nie zaczynaj dlugiego learn"
4. **Swiadomy idle** - "strategic plan mowi: idle, czekaj na window" zamiast NOOP spam
5. **Event-driven re-plan** - nowy material / goal achieved -> trigger strategic loop

## Przeplywy

### Flow 1: Normalna praca (learning window)

```
09:00 Wake-up (auto-wake z ModeRegulator)
09:00 Strategic Loop: "Window otwarte. Plan: learn logika -> exam -> review python"
09:01 Tactical: learn logika (chunk 1)
09:02 Tactical: learn logika (chunk 2)
09:05 Tactical: exam logika -> FAIL
09:05 Tactical: (strategic plan says review after fail) -> review logika
09:10 Tactical: exam logika -> PASS
09:15 Tactical: learn python (new topic)
...
10:55 Tactical: "5 min do zamkniecia window, skip heavy learn"
10:55 Tactical: evaluate (quick)
11:00 Window zamkniete
11:00 Strategic Loop: "Window zamkniete. Plan: creative -> evaluate -> idle"
11:01 Tactical: creative reflection
11:10 Tactical: idle (swiadomy, nie NOOP spam)
```

### Flow 2: Wieczor (poza window)

```
18:00 Strategic Loop: "Wieczor. Plan: creative, evaluate, light review only"
18:01 Tactical: creative (NIM-powered)
18:10 Tactical: evaluate
18:20 Tactical: idle (poczekaj 30 min)
18:50 Strategic Loop: "Nic nowego. Plan: idle until sleep"
19:30 ModeRegulator: SLEEP (idle > 30min)
19:30 SleepProcessor: NREM1-3 + REM
```

### Flow 3: Failure recovery

```
14:00 Strategic Loop: "learn fizyka" 
14:01 Tactical: learn fizyka -> FAIL (LLM timeout)
14:02 Tactical: learn fizyka -> FAIL (LLM timeout again)
14:03 Tactical: (2 failures) strategic plan says: "skip fizyka, try python"
14:03 Tactical: learn python -> OK
14:30 Strategic Loop: "fizyka failed 2x, possible LLM issue. Plan: skip fizyka today, retry tomorrow"
```

## Implementacja

### Nowe pliki

```
agent_core/planner/
  strategic_planner.py    # StrategicPlanner - LLM-powered planning
  strategic_plan.py       # StrategicPlan model (dataclass)
  time_context.py         # TimeContext - pora dnia, window status, time-to-close
```

### Zmiany w istniejacych

```
planner_core.py           # Tactical loop czyta strategic_plan zamiast samodzielnego goal selection
planner_model.py          # PlannerState += last_strategic_ts, strategic_plan reference
goal_selector.py          # Respektuje strategic_plan ordering (jesli dostepny)
```

### StrategicPlanner - glowna klasa

```python
class StrategicPlanner:
    """LLM-powered strategic planning layer.
    
    Runs every 30min (or on event), produces StrategicPlan
    that tactical loop follows.
    """
    
    INTERVAL_SEC = 1800  # 30 min
    
    def __init__(self, llm_fn, goal_store, knowledge_analyzer, ...):
        self._llm_fn = llm_fn  # ask_as_role(PLANNER, prompt)
        self._goal_store = goal_store
        self._last_plan = None
        self._last_plan_ts = 0
    
    def should_replan(self, event=None) -> bool:
        """Check if strategic replanning needed."""
        elapsed = time.time() - self._last_plan_ts
        if elapsed > self.INTERVAL_SEC:
            return True
        if event in ("goal_achieved", "new_material", "failure_pattern", "mode_change"):
            return True
        return False
    
    def plan(self, context: dict) -> StrategicPlan:
        """Ask qwen3:8b for strategic plan."""
        prompt = self._build_prompt(context)
        response = self._llm_fn("planner", prompt)
        return self._parse_response(response)
    
    def _build_prompt(self, ctx) -> str:
        """Build structured prompt with system context."""
        # ... time, goals, recent actions, gaps, retention ...
```

### StrategicPlan - model

```python
@dataclass
class StrategicPlan:
    """Output of strategic planning session."""
    created_at: float
    valid_until: float              # Plan expiry (next strategic session)
    action_queue: List[PlannedAction]  # Ordered actions to execute
    blocked_goals: Dict[str, str]   # goal_id -> reason (skip until condition)
    idle_strategy: str              # What to do when queue empty
    notes: str                      # LLM reasoning (for traces)

@dataclass  
class PlannedAction:
    action_type: str
    goal_id: Optional[str]
    reason: str
    max_attempts: int = 3
    skip_if_blocked: bool = True
```

### TimeContext - swiadomosc czasu

```python
class TimeContext:
    """Time-of-day awareness for planner decisions."""
    
    def __init__(self):
        self._berlin_offset = timedelta(hours=2)
    
    @property
    def berlin_now(self) -> datetime: ...
    
    @property  
    def is_learning_window(self) -> bool: ...
    
    @property
    def minutes_to_window_close(self) -> Optional[int]:
        """Minutes until current learning window closes. None if not in window."""
        ...
    
    @property
    def next_window_start(self) -> Optional[datetime]:
        """When does next learning window open?"""
        ...
    
    @property
    def time_slot(self) -> str:
        """Current time slot: 'morning_learn', 'afternoon_learn', 'evening', 'night', 'quiet'"""
        ...
    
    @property
    def is_good_for_heavy_llm(self) -> bool:
        """Is this a good time for heavy LLM work (not quiet hours, not near sleep)?"""
        ...
```

## Prompt Design

### System prompt (qwen3:8b)

```
Jestes strategicznym planistą dla Maria - autonomicznego agenta AI.
Twoje zadanie: zdecyduj co Maria powinna robic w nastepnych 30 minutach.

Zasady:
- W learning window (9-11, 14-16): priorytet LEARN/EXAM/REVIEW
- Poza window: priorytet CREATIVE/EVALUATE/IDLE
- Po failed exam: zawsze REVIEW przed retry
- Max 3 proby na jedna akcje, potem skip
- Jesli 5 min do zamkniecia window: nie zaczynaj nowego LEARN
- Wieczor (18+): lekkie akcje, przygotuj sie do SLEEP
- Noc (22-7): tylko IDLE

Odpowiedz WYLACZNIE w JSON:
{
  "plan": [{"action": "...", "goal_id": "...", "reason": "..."}],
  "blocked_until": {"goal_id": "reason"},
  "idle_strategy": "creative|evaluate|sleep_prep|wait",
  "notes": "krotkie wyjasnienie"
}
```

## Wdrozenie - fazy

### Faza A: TimeContext + Backoff (bez LLM)
1. `time_context.py` - pora dnia, window status
2. Backoff w tactical loop - pamiec failed actions (nie timer, warunek)
3. Swiadomy idle - nie NOOP spam, "czekam na X"
4. **Testy:** 20-30

### Faza B: StrategicPlanner (z LLM)
1. `strategic_planner.py` - prompt, parse, plan model
2. `strategic_plan.py` - dataclass
3. Wiring: homeostasis tick -> should_replan() -> plan()
4. Tactical loop czyta plan (z fallback na reguly jesli brak planu)
5. **Testy:** 30-40

### Faza C: Integration + Tuning
1. Trace integration (strategic decisions w episode traces)
2. Telegram /plan command (pokaz aktualny strategic plan)
3. Web UI strategic plan view
4. Prompt tuning na prawdziwych danych
5. **Testy:** 10-15

## Ryzyka

| Ryzyko | Mitygacja |
|--------|-----------|
| qwen3:8b daje zly JSON | Robust parser + fallback na reguly |
| LLM halucynuje goal_id | Walidacja: goal musi istniec w store |
| Strategic plan nieaktualny | 30min expiry + event-driven replan |
| Cold start 3s blokuje tick | Strategic loop w osobnym uatku (nie w tick) |
| RAM: qwen3:8b + llama3.1:8b | Heavy mutex (juz istnieje w ModelScheduler) |

## Metryki sukcesu

1. **Zero NOOP spam** w logach (teraz: ~6 NOOP/h w SLEEP)
2. **100% wykorzystanie learning window** (teraz: przegapila caly dzien)
3. **Failure recovery < 3 proby** (teraz: retry w nieskonczonosc)
4. **Strategic plan czytelny dla operatora** (Telegram /plan)
