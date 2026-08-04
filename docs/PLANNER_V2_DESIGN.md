# Planner v2 - Adaptive Planning with Strategic LLM

> Design doc, written before implementation. **It has since been built**:
> `agent_core/planner/strategic_planner.py` and `strategic_plan.py` exist and are
> wired from `agent_core/modules/homeostasis_module.py`. Read this as the original
> reasoning, not as a description of the shipped code — the implementation differs
> in places (constant names, the replan interval, and how the time context is
> derived). The code is the truth.

## Problem

Planner v1 (ADR-013) is rule-based and deterministic - a good starting point, but:

1. **Retry spam** - tries review every minute outside the learning window (blocked, tries again)
2. **No backoff on failed goals** - the same goal is picked after every NOOP
3. **No time-awareness** - does not know that creative work fits the evening better than learn
4. **No dynamic prioritization** - the aging factor alone is not enough
5. **No "deliberate idle"** - NOOP is a loop, not a decision

## Architecture: Dual-Loop Planner

```
                    +--------------------------+
                    |   STRATEGIC LOOP (LLM)   |
                    |  qwen3:8b / every 30 min |
                    |                          |
                    |   "What to do next?"     |
                    |   -> Day/hour plan       |
                    |   -> Goal priorities     |
                    |   -> Backoff decisions   |
                    +-----------+--------------+
                                |
                       strategic_plan.json
                                |
                    +-----------v--------------+
                    |   TACTICAL LOOP (rules)  |
                    |   per-tick / 60s         |
                    |                          |
                    |   Executes the LLM plan  |
                    |   Quick checks + guards  |
                    |   Fallback to rules      |
                    +--------------------------+
```

### Strategic Loop (new, LLM-powered)

**Model:** qwen3:8b (MODEL-01, local, cold-start ~3s, 5.5GB)
**Frequency:** Every 30 min in ACTIVE, on event (new material, failure pattern), on wake-up
**Fallback:** NIM API if the local model fails, rule-based if both fail

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

### Tactical Loop (improved v1)

Per-tick, rule-based, zero LLM. Changes vs v1:

1. **Reads strategic_plan** instead of selecting goals on its own
2. **Backoff with memory** - if an action failed 3x, skip it until conditions change (not on a timer)
3. **Time-slot awareness** - knows that 10:45 means "last 15 min of the window, do not start a long learn"
4. **Deliberate idle** - "the strategic plan says: idle, wait for the window" instead of NOOP spam
5. **Event-driven re-plan** - new material / goal achieved -> trigger the strategic loop

## Flows

### Flow 1: Normal operation (learning window)

```
09:00 Wake-up (auto-wake from ModeRegulator)
09:00 Strategic Loop: "Window open. Plan: learn logika -> exam -> review python"
09:01 Tactical: learn logika (chunk 1)
09:02 Tactical: learn logika (chunk 2)
09:05 Tactical: exam logika -> FAIL
09:05 Tactical: (strategic plan says review after fail) -> review logika
09:10 Tactical: exam logika -> PASS
09:15 Tactical: learn python (new topic)
...
10:55 Tactical: "5 min to window close, skip heavy learn"
10:55 Tactical: evaluate (quick)
11:00 Window closed
11:00 Strategic Loop: "Window closed. Plan: creative -> evaluate -> idle"
11:01 Tactical: creative reflection
11:10 Tactical: idle (deliberate, not NOOP spam)
```

### Flow 2: Evening (outside the window)

```
18:00 Strategic Loop: "Evening. Plan: creative, evaluate, light review only"
18:01 Tactical: creative (NIM-powered)
18:10 Tactical: evaluate
18:20 Tactical: idle (wait 30 min)
18:50 Strategic Loop: "Nothing new. Plan: idle until sleep"
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

## Implementation

### New files

```
agent_core/planner/
  strategic_planner.py    # StrategicPlanner - LLM-powered planning
  strategic_plan.py       # StrategicPlan model (dataclass)
  time_context.py         # TimeContext - time of day, window status, time-to-close
```

### Changes to existing files

```
planner_core.py           # Tactical loop reads strategic_plan instead of selecting goals itself
planner_model.py          # PlannerState += last_strategic_ts, strategic_plan reference
goal_selector.py          # Respects strategic_plan ordering (when available)
```

### StrategicPlanner - main class

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

### TimeContext - time awareness

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

## Rollout - phases

### Phase A: TimeContext + Backoff (no LLM)
1. `time_context.py` - time of day, window status
2. Backoff in the tactical loop - memory of failed actions (a condition, not a timer)
3. Deliberate idle - not NOOP spam, but "waiting for X"
4. **Tests:** 20-30

### Phase B: StrategicPlanner (with LLM)
1. `strategic_planner.py` - prompt, parse, plan model
2. `strategic_plan.py` - dataclass
3. Wiring: homeostasis tick -> should_replan() -> plan()
4. Tactical loop reads the plan (falls back to rules when no plan is available)
5. **Tests:** 30-40

### Phase C: Integration + Tuning
1. Trace integration (strategic decisions in episode traces)
2. Telegram /plan command (show the current strategic plan)
3. Web UI strategic plan view
4. Prompt tuning on real data
5. **Tests:** 10-15

## Risks

| Risk | Mitigation |
|--------|-----------|
| qwen3:8b returns bad JSON | Robust parser + fallback to rules |
| LLM hallucinates a goal_id | Validation: the goal must exist in the store |
| Strategic plan goes stale | 30min expiry + event-driven replan |
| 3s cold start blocks the tick | Strategic loop in a separate thread (not in the tick) |
| RAM: qwen3:8b + llama3.1:8b | Heavy mutex (already exists in ModelScheduler) |

## Success metrics

1. **Zero NOOP spam** in the logs (currently: ~6 NOOP/h in SLEEP)
2. **100% learning window utilization** (currently: a whole day was missed)
3. **Failure recovery < 3 attempts** (currently: retries indefinitely)
4. **Strategic plan readable by the operator** (Telegram /plan)
