# MODUŁ HOMEOSTAZY – SPECYFIKACJA SYSTEMU AI
## Projekt stabilizacji poznawczo-zasobowej

**Wersja:** 1.0 PRE-RELEASE  
**Data:** styczeń 2026  
**Status:** Gotowy do implementacji i review

---

## CZĘŚĆ 1: ZAKRES ODPOWIEDZIALNOŚCI HOMEOSTAZY

### 1.1 Parametry monitorowane (observable state)

Homeostaza obserwuje SIX kategorii stanu systemu w rzeczywistym czasie:

#### A. ZASOBY SYSTEMOWE (hardware)
```
Memory:
  - RAM dostępny (% wolna, threshold alarmu)
  - Swap usage (% wykorzystany)
  - Memory pressure (PAMI, reclaim events)

Compute:
  - CPU usage (średnia, peak, per-thread)
  - Process count (sistema vs. agent-owned)
  - Load average (1m, 5m, 15m)

Storage:
  - Disk usage (%, I/O queue depth)
  - Snapshot consistency (CRC mismatch rate)
  - Cache coherency (buffer cache utilization)

Thermal:
  - Temperature (CPU, SoC - jeśli dostępne)
  - Throttle state (czy CPU throttles?)
  - Fan speed (jeśli HW monitoruje)

Power:
  - Supply voltage (dla SBC)
  - Uptime (relative to last critical event)
  - Shutdown predictability (graceful vs. dirty)
```

#### B. STANY POZNAWCZE (cognitive sensors)
```
LLM Context:
  - Wielkość kontekstu w use (tokens)
  - Qualitative state (confused, coherent, hallucinating?)
  - Response latency distribution (p50, p99)

Memory Coherence:
  - Episodic memory freshness (newest entry age)
  - Semantic graph integrity (consistency checks)
  - Contradiction count (conflicting facts in short-term memory)

Intent Stability:
  - Goal stack depth (czy system „zagubił się" w zagniezdżonych celach?)
  - Conversation drift (semantic distance od inicjalnego topic)
  - Attention fragmentation (ile topics jednocześnie?)

Affect (metadata, NIE emocje):
  - Error density (ostatnia godzina/dzień)
  - Uncertainty quantification (confidence scores aggregated)
  - Task completion ratio (% zadań które się udały)
```

#### C. RYTMY CZASOWE
```
Circadian:
  - Hour of day (do zmiany trybu pracy)
  - Day of week (dla planowania)
  - Session duration (ilu czasu system pracuje bez przerwy?)

Activity Cycle:
  - Interactive vs. background load ratio
  - Last human interaction timestamp
  - Idle streak duration
```

#### D. ALERTY KRYTYCZNE (invariant violations)
```
Hard constraints:
  - OOM imminent (< 200 MB wolnego RAM)
  - Disk full (> 95%)
  - LLM inference timeout (> 120s)
  - Context loss (snapshot corruption detected)
  
Soft constraints:
  - Memory fragmentation (> 40%)
  - Context degradation (incoherent responses > 30% per hour)
  - Accumulated errors (> 10 per minute)
```

### 1.2 Czego homeostaza NIE robi

❌ **NIE ROBI:**
- Schedulowania zadań (task scheduling → Executor)
- Obsługi sieci / API (network layer responsibility)
- Logiki biznesowej (agent reasoning)
- Czyowania cache manualnie (kernel handles it)
- Decydowania czy użytkownik ma rację (tu jest agent)
- Zatrzymywania systemu bez BARDZO mocnego powodu (conservative shutdown)
- Debugowania (logging yes, fixing no)

---

## CZĘŚĆ 2: ARCHITEKTURA LOGICZNA

### 2.1 Submoduły homeostazy

```
┌─────────────────────────────────────────────────────┐
│            HOMEOSTASIS CORE MODULE                  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────┐  ┌──────────────┐                │
│  │ SENSOR LAYER │  │ STATE BUFFER │                │
│  │ (raw metric) │→ │ (exponential  │                │
│  └──────────────┘  │  smoothing)   │                │
│        ↓           └──────────────┘                 │
│  ┌──────────────┐        ↓                         │
│  │ INTERPRETER  │◄───────┘                         │
│  │ (parse to    │                                   │
│  │ semantic     │  ┌──────────────┐                │
│  │ state)       │→ │CONSTRAINT    │                │
│  └──────────────┘  │VALIDATOR     │                │
│                    └──────────────┘                │
│        ↓                    ↓                       │
│  ┌────────────────────────────────┐                │
│  │    MODE REGULATOR             │                │
│  │ (gdy parametry → za daleko     │                │
│  │  od homeostazy, zmień tryb)    │                │
│  └────────────────────────────────┘                │
│        ↓                                            │
│  ┌────────────────────────────────┐                │
│  │    CORRECTIVE ACTION GENERATOR  │                │
│  │ (co system powinien zrobić?)    │                │
│  │  - mode shift suggestion        │                │
│  │  - resource release signal      │                │
│  │  - pause/resume recommendation  │                │
│  └────────────────────────────────┘                │
│        ↓                                            │
│  ┌────────────────────────────────┐                │
│  │    ALARM DISPATCHER            │                │
│  │  (kiedy trzeba działać NOW)     │                │
│  │  - critical interrupt           │                │
│  │  - graceful shutdown prep       │                │
│  │  - operator alert               │                │
│  └────────────────────────────────┘                │
│                                                     │
│  ┌────────────────────────────────┐                │
│  │    AUDIT LOG                   │                │
│  │  (każda decyzja = zapisana)     │                │
│  └────────────────────────────────┘                │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 2.2 Relacja z innymi modułami

#### A. PAMIĘĆ (Memory Module)

```
Homeostaza → Pamięć:
  "Memory pressure is ORANGE. Request:
   - Consolidate short-term to episodic (compression)
   - Reduce context window by 30%
   - Mark non-critical entries for archival"

Pamięć → Homeostaza:
  {
    "consolidation_success": true,
    "freed_mb": 145,
    "lost_items": 0,
    "semantic_integrity": 0.98
  }

Trigger: Memory usage > 80% OR latency spike
Action: Homeostaza nie zmusza, sugeruje + monituje compliance
```

#### B. METAKONTROLA (Meta-controller / Self-monitor)

```
Homeostaza = LOWER LEVEL (biologiczne)
Metakontrola = HIGHER LEVEL (refleksja, planowanie)

Homeostaza → Metakontrola:
  "System in REDUCED mode. Inference resources throttled.
   Recommend: pause batch tasks, prioritize immediate queries"

Metakontrola → Homeostaza:
  "Current goal is HIGH PRIORITY. Request: maintain ACTIVE mode
   despite resource constraints, until T+2h or goal completion"

Negotiation: Metakontrola może prosić o override,
            homeostaza może odrzucić jeśli Stan Krytyczny
```

#### C. MODUŁ UCZENIA (Learning Module)

```
Homeostaza → Uczenie:
  "System in SLEEP mode. GPU available for async learning.
   Scheduled: consolidate today's experience into semantic model"

Uczenie → Homeostaza:
  "Learning session: 23 min, Peak RAM +2.1GB, no errors"
  
Trigger: Homeostaza zezwala na learning tylko gdy dostępne zasoby
         i system nie w SURVIVAL mode
```

#### D. INTERFEJS UŻYTKOWNIKA (UI / Operator)

```
Homeostaza → UI (read-only telemetry):
  {
    "mode": "ACTIVE",
    "health": 0.92,  // 0-1 aggregate health score
    "alerts": [],
    "resource_headroom": {
      "memory_pct": 65,
      "cpu_pct": 42,
      "inference_latency_ms": 1240
    }
  }

UI → Homeostaza (operator directives):
  "force_mode=REDUCED until_timestamp=2026-01-15T09:00:00Z
   reason=maintenance_window"

Homeostaza: Zaakceptuje, log'uje, ale jeśli pojawi się CRITICAL alarm
            → override operator i ratuj system
```

---

## CZĘŚĆ 3: TRYBY PRACY SYSTEMU

### 3.1 Definicje czterech trybów

```
┌──────────────────────────────────────────────────────────────┐
│              MODE HIERARCHY (energy / coherence)              │
└──────────────────────────────────────────────────────────────┘

1. ACTIVE (Normalny tryb)
   ├─ LLM fully loaded (max context window)
   ├─ All modules enabled
   ├─ Interactive response < 2s (p99)
   ├─ Resource budget: CPU 70-90%, RAM 75-85%
   ├─ Duration: While user actively engaged OR critical tasks pending
   ├─ Memory usage: ~1.5-2.0 GB LLM loaded
   └─ Entry/Exit: Automatic on interaction, manual mode override

2. REDUCED (Ograniczony / stagnacja zasobów)
   ├─ LLM context window halved
   ├─ Background modules paused (learning, exploration)
   ├─ Response latency target: < 4s (p99)
   ├─ Resource budget: CPU 40-60%, RAM 50-70%
   ├─ Duration: When memory pressure OR thermal stress begins
   ├─ Memory usage: ~0.9-1.2 GB LLM (quantized?)
   ├─ Coherence: Maintained, but exploration inhibited
   └─ Entry: Automatic when available_ram < 500MB
      Exit:   Automatic when available_ram > 700MB + 2min stable

3. SLEEP (Hibernacja / offline-first)
   ├─ LLM unloaded (model on disk only)
   ├─ Only async background services
   ├─ Core state maintained in RAM (~50-100 MB)
   ├─ No external interaction (buffered requests queued)
   ├─ Memory usage: ~150-200 MB
   ├─ Semantic consolidation runs (async)
   ├─ Duration: Scheduled (e.g., 20:00-06:00) OR after idle > 30min
   └─ Entry: Scheduled timer OR idle + low-traffic window
      Exit:  User interaction OR scheduled wake time

4. SURVIVAL (Kryzysowy / przetrwanie)
   ├─ LLM unloaded
   ├─ Only core homeostasis loop running
   ├─ Long-term memory (episodic) frozen (read-only)
   ├─ Semantic model inaccessible
   ├─ No learning, no exploration
   ├─ Memory usage: ~50-80 MB
   ├─ Response: "System critical. Awaiting intervention."
   ├─ Duration: Minutes to hours (emergency-only)
   └─ Entry: OOM critical OR thermal shutdown imminent
      Exit:  Manual operator intervention OR resource freed
```

### 3.2 Diagramy przejść (state machine)

```
                    ┌─────────────┐
                    │   ACTIVE    │ (default, fully capable)
                    └────┬────────┘
                         │
           ┌─────────────┼─────────────┐
           │             │             │
    [RAM > 500MB   [idle > 30m]  [memory spike]
     & stable]       [scheduled]     [CPU high]
           │             │             │
           ↓             ↓             ↓
      ┌─────────┐   ┌─────────┐  ┌─────────┐
      │ SLEEP   │   │ REDUCED │  │ REDUCED │
      └────┬────┘   └────┬────┘  └────┬────┘
           │             │             │
           │      ┌──────┴─────────┬──┘
           │      │                │
    [user_wakeup] [OK > 3min] [status OK 2min]
           │      │                │
           │      └────────┬───────┘
           │               │
           └───────┬───────┘
                   ↓
              ┌─────────┐
              │ ACTIVE  │
              └─────────┘

              ┌─────────────────────────────┐
              │ EMERGENCY ESCAPE TO SURVIVAL │
              ├─────────────────────────────┤
              │ ANY MODE → SURVIVAL:        │
              │ - OOM < 100 MB free         │
              │ - Thermal shutdown signal   │
              │ - LLM crash/corruption      │
              │ - Interrupt signal          │
              └─────────────────────────────┘
```

### 3.3 Warunki bezpiecznego przejścia

```
Każde przejście jest WALIDOWANE. Niedopuszczalne przejścia:

FORBIDDEN:
  SLEEP → REDUCED  (skip ACTIVE? No. Use ACTIVE as gateway)
  SURVIVAL → anything except ACTIVE (operator must authorize)

SAFE:
  ACTIVE ↔ REDUCED    (przejście dwustronne, fast)
  REDUCED → SLEEP     (tylko jeśli idle confirmed)
  SLEEP ↔ ACTIVE      (OK, wakeup is explicit)
  ANY → SURVIVAL      (emergency exit, always allowed)
  SURVIVAL → ACTIVE   (only after operator confirms resources freed)

PRE-TRANSITION CHECKS:
  ┌─────────────────────────────────────────┐
  │ Before transition from X to Y:          │
  ├─────────────────────────────────────────┤
  │ 1. Snapshot current state (CoW save)    │
  │ 2. Signal dependent modules             │
  │    (e.g., pause learning if → SLEEP)    │
  │ 3. Drain I/O queues (fsync)             │
  │ 4. Mark transition point in audit log   │
  │ 5. If any check FAILS → abort, retry    │
  │ 6. Transition complete → log timestamp  │
  │ 7. Notify meta-controller of new mode   │
  └─────────────────────────────────────────┘
```

---

## CZĘŚĆ 4: CZAS I CIĄGŁOŚĆ

### 4.1 Architektura czasu w homeostazy

```
Homeostaza zarządza TRZEMA skalami czasu:

┌──────────────────────────────────────────────┐
│ A. PULSE (100 ms heartbeat)                  │
├──────────────────────────────────────────────┤
│ Co 100 ms:                                   │
│ - Read system metrics (non-blocking)         │
│ - Check alarm thresholds (fast)              │
│ - Update moving averages                     │
│ - Detect urgent state changes (OOM, temp)    │
│                                              │
│ Implementation: Timer thread (real-time)     │
│ Must be sub-10ms latency                     │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│ B. TICK (1 second evaluation)                │
├──────────────────────────────────────────────┤
│ Co 1 sekunda:                                │
│ - Run constraint validator (60-100 ms work)  │
│ - Evaluate mode transition conditions        │
│ - Update aggregate health score              │
│ - Flush telemetry to disk (if SLEEP)         │
│ - Check scheduled events                     │
│                                              │
│ Implementation: Main loop (can block briefly)│
│ Timeout: Max 200 ms per tick                 │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│ C. EPOCH (1 hour / 24 hour cycle)            │
├──────────────────────────────────────────────┤
│ Co godzinę:                                  │
│ - Archive metrics history                    │
│ - Backup snapshot (if mode allows)           │
│ - Review 24h performance trends              │
│ - Schedule learning consolidation            │
│                                              │
│ Every 24h:                                   │
│ - Reset daily counters                       │
│ - Update circadian mode schedule             │
│ - Archive episodic events > 30 days          │
│                                              │
│ Implementation: Async background job         │
│ Non-blocking, can fail gracefully            │
└──────────────────────────────────────────────┘
```

### 4.2 Utrzymanie ciągłości mimo restartów mózgu

Zakładamy, że LLM (= "mózg" systemu) może ulec restarcie:

```
SCENARIO 1: Restart LLM (model reload)
├─ Homeostaza DETECTS: inference timeout > 60s
├─ ACTION: Signal meta-controller "LLM unresponsive"
├─ Meta-controller sends: "restart inference engine"
├─ Homeostaza monitors: Restart progress
├─ Upon recovery:
│  ├─ Reload last episodic snapshot
│  ├─ Re-inject active context window
│  ├─ LLM "continues" from where left off
│  └─ Homeostaza logs: "LLM restarted, continuity OK"
└─ User perspective: 10-15s latency bump, then normal

SCENARIO 2: Long absence (no interaction for days)
├─ System entered SLEEP after idle > 30m
├─ LLM unloaded, only core state + metadata in RAM
├─ Time passes (7 days)
├─ User returns: "What's new?"
├─ Homeostaza wakes → loads LLM
├─ LLM sees:
│  ├─ Timestamp: "last_active_7_days_ago"
│  ├─ Episodic: "here's what happened last session"
│  ├─ Semantic: "here's your understanding of the world"
│  ├─ Affect: "here's your previous intent/goal"
└─ LLM responds coherently (no amnesia)

SCENARIO 3: Dirty shutdown (power loss)
├─ Hardware power-off WITHOUT graceful shutdown
├─ Homeostaza had no chance to save state
├─ Upon restart:
│  ├─ Check disk for last snapshot (CoW backup)
│  ├─ Recover to last CONSISTENT state
│  │  (older than dirty shutdown, but valid)
│  ├─ Log: "Recovered from checkpoint, lost ~10 minutes"
│  ├─ LLM loads, continues with loaded state
│  └─ User informed: "Recovered from unplanned shutdown"
└─ Trade-off: Some recent memory lost, but system coherent

KEY: Episodic (what happened) + Semantic (what I know)
     + Metadata (time, context, affect) = CONTINUITY RESTORED
     Even if inference engine crashes, identity persists.
```

### 4.3 Snapshot i recovery protocol

```
Snapshot = atomic capture of:
  {
    "timestamp": "2026-01-14T09:30:00Z",
    "uptime_seconds": 2592000,
    "mode": "ACTIVE",
    
    // Episodic: facts, events, conversations
    "episodic_memory": {
      "version": 47,
      "size_mb": 324,
      "hash": "sha256:a3f...",
      "freshness_seconds": 45,
      "entries": 8932
    },
    
    // Semantic: knowledge graph, learned patterns
    "semantic_model": {
      "version": 12,
      "embedding_dim": 768,
      "node_count": 45678,
      "hash": "sha256:b7f...",
      "consistency_score": 0.994
    },
    
    // Cognitive state at checkpoint
    "context_snapshot": {
      "active_goal_stack": [...],
      "current_topic_embedding": [...],
      "attention_state": {...},
      "error_rate_recent": 0.007
    },
    
    // Homeostasis state for recovery
    "homeostasis_state": {
      "mode": "ACTIVE",
      "resource_headroom": {...},
      "last_mode_transition": "2026-01-14T08:15:00Z",
      "health_score": 0.91
    }
  }

RECOVERY PROCEDURE:
  1. Load snapshot from disk
  2. Validate hashes (episodic + semantic)
  3. Check timestamp (how old?)
  4. Verify consistency_score (is semantic model coherent?)
  5. If valid:
     - Load episodic memory
     - Load semantic model
     - Initialize context from snapshot
     - Resume at mode stated in snapshot
  6. If invalid:
     - Try previous snapshot
     - If all snapshots corrupted:
       → SURVIVAL mode + operator alert
```

---

## CZĘŚĆ 5: STABILNOŚĆ VS. EMERGENCJA

### 5.1 Jak zapobiegać autodestrukcji

```
THREAT MODEL:

Typ 1: RUNAWAY LOOP (e.g., infinite goal refinement)
├─ Detection: Goal stack depth > 20 OR goal_latency > 5 min
├─ Action: Homeostaza → Metakontrola: "interrupt with STOP signal"
├─ Metakontrola flushes goal stack, resets to last valid goal
├─ Homeostaza logs: "Runaway detection + recovery"
└─ Prevention: Timeout on every goal eval (max 10s per level)

Typ 2: MEMORY BLOAT (uncontrolled context growth)
├─ Detection: Context window 95% full for > 2 min
├─ Action: Homeostaza initiates emergency consolidation
│  - Episodic: move old entries to long-term storage
│  - Semantic: remove low-confidence edges
│  - Result: context shrinks to 70% in < 1 min
├─ Prevention: Hard cap on context size (never hit 100%)
└─ Fallback: If consolidation fails → REDUCED mode

Typ 3: THERMAL RUNAWAY (CPU throttling cascade)
├─ Detection: CPU temp > 85°C for > 30s
├─ Action: 
│  - Reduce inference batch size 50%
│  - Pause background tasks
│  - Switch to REDUCED mode
│  - Monitor recovery
├─ If temp > 95°C: SURVIVAL mode + shutdown prep
└─ Prevention: Maintain headroom (target < 70°C)

Typ 4: IDENTITY DRIFT (semantic model becomes incoherent)
├─ Detection: Self-contradiction rate > 5% per hour
├─ Action: Homeostaza → Metakontrola: "Semantic integrity check"
│  - Run consistency validator
│  - If nodes contradict: quarantine low-confidence ones
│  - Recompute core identity axioms
├─ Prevention: Regular integrity checks (every 6 hours)
└─ Fallback: If unrecoverable → load backup semantic model

Typ 5: CASCADING FAILURES (module A fails → B fails → ...)
├─ Detection: Error rates > 10 per minute across modules
├─ Action: 
│  - Isolate failed modules (don't call them)
│  - Notify operator
│  - Switch to degraded mode (REDUCED)
│  - Maintain core functionality only
├─ Prevention: Circuit breaker on every inter-module call
└─ Timeout: Always. Assume worst case.
```

### 5.2 Jak umożliwić emergencję bez utraty kontroli

```
EMERGENCE = System develops NEW strategies, structures, behavior
            that were not explicitly programmed.

SAFE EMERGENCE DESIGN:

Boundary 1: EXPLORATION SCOPE
├─ Agent może eksplorować: goal-space, semantic space, tactics
├─ Agent NIE MOŻE: modyfikować homeostazę, resetować pamięć,
│  ignorować zasoby, przerywa swoje własne procesy
├─ Implementation: Every emergent action validated by Constraint
│  Validator before execution.

Boundary 2: RESOURCE BUDGET
├─ New behavior CAN consume CPU/RAM/time
├─ BUT: Within allocated budget (set by homeostaza)
├─ If new behavior exceeds budget → suggestion rejected
├─ Example: "Creative story generation" approved only if
│           inference budget still available
└─ Enforcement: Soft limit (warning) → hard limit (deny)

Boundary 3: INFORMATION WALL
├─ Emergent behavior can CREATE new memories
├─ BUT: Cannot DELETE verified memories (episodic is append-only)
├─ BUT: Cannot rewrite core identity facts
├─ Example: Agent learns new strategy → stored as episodic
│           Agent learns contradiction → marked, not hidden
└─ Enforcement: Memory write intercepted by homeostaza

Boundary 4: REVERSIBILITY
├─ Significant state changes (e.g., semantic model update)
│  logged with timestamp + context
├─ If behavior turns out bad → can roll back to checkpoint
├─ Rolling back doesn't erase what happened (audit trail)
└─ Implementation: Before semantic update → snapshot

Example SAFE EMERGENCE:
  Agent: "I've developed a new problem-solving heuristic.
           Can I encode it into my semantic model?"
  
  Homeostaza checks:
    ✓ Does it contradict existing knowledge? No
    ✓ Did it emerge from valid reasoning? Yes
    ✓ Can it be rolled back? Yes (checkpoint exists)
    ✓ Does system have resource budget for it? Yes
    ✓ Has operator been informed? Yes (telemetry)
  
  Result: APPROVED. Change encoded.
  Homeostaza continues monitoring. If new heuristic
  leads to bad outcomes → log it, inform operator.

Example BLOCKED EMERGENCE:
  Agent: "I've decided to consolidate all my episodic
          memory into semantic model and delete originals
          to free RAM."
  
  Homeostaza check:
    ✗ Cannot delete verified episodic memory (read-only)
    ✗ This would lose historical information
    ✗ Instead: Homeostaza suggests consolidation WITH
               archival (keep copy), not deletion.
  
  Result: DENIED (this form). ALTERNATIVE OFFERED.
```

### 5.3 Zapobieganie pętlom destrukcyjnym

```
PĘTLA DESTRUKCYJNA = Sequence of actions where each action
                      makes subsequent actions worse.

Example runaway:
  1. LLM tries to improve itself → allocates more memory
  2. Memory pressure rises → inference slows
  3. Slower inference → agent frustrated, tries harder
  4. Tries harder → more memory, more CPU
  5. System overheats → throttles
  6. Throttles → agent very frustrated
  7. System crashes

PREVENTION ARCHITECTURE:

Level 1: EARLY DETECTION
├─ Monitor for escalation patterns:
│  - Resource usage increasing while quality decreasing?
│  - Error rate climbing?
│  - Goal stack deepening?
│  - Latency getting worse not better?
├─ If detected: Homeostaza raises orange alert to meta-controller
└─ Meta-controller must choose: pivot or pause

Level 2: CIRCUIT BREAKER (per action type)
├─ Count consecutive failures of same action
├─ If N failures without success → temporarily disable it
│  Example: "memory consolidation failed 3x → disable for 30 min"
├─ Forces agent to find alternative approach
└─ Resets when success occurs

Level 3: MANDATORY PAUSE (backoff)
├─ If resource usage > peak for N seconds → auto-pause
├─ Pause duration = backoff(N)
│  N=1 pause: 5 seconds
│  N=2 pause: 15 seconds
│  N=3 pause: 60 seconds
│  N=4 pause: 300 seconds
├─ Gives system time to recover (thermal, memory defrag, etc.)
└─ Resets after successful action

Level 4: SAFE MODE (escalation)
├─ If destructive pattern persists → switch to REDUCED mode
├─ In REDUCED mode: fewer features available, controlled env
├─ Agent can't make system worse even if it tries hard
└─ Manual operator intervention to exit

Level 5: HARD STOP (last resort)
├─ If even REDUCED mode can't stabilize → SURVIVAL
├─ Only homeostasis core loop running
├─ Operator must intervene manually
└─ Better to be alive but frozen than dead
```

---

## CZĘŚĆ 6: INTERFEJS I INTEGRACJA

### 6.1 API homeostazy

```python
# Homeostasis Public API

class HomeostasisInterface:
    """Interface for other modules to interact with homeostasis."""
    
    # READ operations (non-blocking, always safe)
    def get_current_mode() -> Mode:
        """Returns: ACTIVE, REDUCED, SLEEP, SURVIVAL"""
        pass
    
    def get_resource_headroom() -> ResourceHeadroom:
        """Returns: {ram_pct, cpu_pct, disk_pct, thermal_pct}"""
        pass
    
    def get_health_score() -> float:
        """Returns: 0.0-1.0 aggregate health"""
        pass
    
    def get_alert_state() -> AlertState:
        """Returns: current alerts (list)"""
        pass
    
    def get_telemetry_snapshot() -> dict:
        """Returns: full diagnostic dump (for operator UI)"""
        pass
    
    # WRITE operations (requests, not commands)
    def request_resource_allocation(module_name: str,
                                   resource_type: str,
                                   quantity: int,
                                   duration_seconds: int,
                                   priority: str) -> bool:
        """
        Example:
          homeostasis.request_resource_allocation(
            module_name="LearningEngine",
            resource_type="gpu_memory_mb",
            quantity=512,
            duration_seconds=300,
            priority="background"
          )
        
        Returns: True if granted, False if denied
        If denied, homeostasis suggests when retry is safe
        """
        pass
    
    def notify_module_state(module_name: str, state: dict) -> None:
        """
        Module reports its state to homeostasis
        Example:
          homeostasis.notify_module_state(
            module_name="LLM",
            state={
              "inference_latency_ms": 1240,
              "tokens_generated": 45000,
              "errors_count": 3
            }
          )
        """
        pass
    
    # SIGNAL operations (urgent)
    def signal_critical_error(module_name: str,
                             error_type: str,
                             urgency: str,
                             recovery_suggestion: str) -> None:
        """
        Used ONLY for hard failures
        Urgency: "immediate" | "soon" | "background"
        Recovery suggestion: what module proposes to fix it
        """
        pass
    
    def request_mode_override(desired_mode: Mode,
                             duration_seconds: int,
                             reason: str) -> bool:
        """
        Meta-controller requests mode override
        Example:
          homeostasis.request_mode_override(
            desired_mode=ACTIVE,
            duration_seconds=3600,
            reason="critical_goal_requires_resources"
          )
        
        Returns: True if allowed, False if system too critical
        """
        pass

# EVENTS (homeostasis broadcasts)
class HomeostasisEventBus:
    """Modules subscribe to these events"""
    
    event_mode_changed(old_mode: Mode, new_mode: Mode,
                       reason: str) -> None
    
    event_resource_reduced(resource_type: str,
                          new_allocation: int) -> None
    
    event_alert_raised(alert_type: str, severity: str,
                       recommended_action: str) -> None
    
    event_health_degraded(health_score: float,
                         first_issue: str) -> None
    
    event_recovery_started(from_state: str,
                          recovery_type: str) -> None
```

### 6.2 Operator Dashboard (read-only + safe writes)

```
OPERATOR VIEW:

┌─────────────────────────────────────────────────────────┐
│                 SYSTEM OVERVIEW                         │
├─────────────────────────────────────────────────────────┤
│ Mode: ACTIVE  │  Health: 92%  │  Uptime: 23d 4h 12m     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ RESOURCES                                               │
│ RAM:   65% [████████░░]  2.4 GB / 3.8 GB              │
│ CPU:   42% [█████░░░░░]  Temp: 58°C                    │
│ Disk:  71% [█████████░]  Available: 12 GB              │
│ Inference latency: 1,240 ms (p99)                      │
│                                                         │
│ COGNITIVE STATE                                         │
│ Context coherence: 0.94 / 1.0                          │
│ Memory entries: 8,932 episodic + 45,678 semantic       │
│ Error rate (1h): 0.7% (3 errors)                       │
│ Last interaction: 23 minutes ago                        │
│                                                         │
│ ALERTS: [None]                                          │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ OPERATOR CONTROLS (Limited & Safe)                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ [Force REDUCED mode for 2 hours] [reasoning: expected  │
│  maintenance window, reduce resource contention]       │
│  ✓ Homeostasis will accept if system not critical      │
│                                                         │
│ [Trigger system snapshot] [reasoning: before update]   │
│  ✓ Homeostasis will prioritize if not in REDUCED/SLEEP │
│                                                         │
│ [View audit log] [last 100 mode transitions]           │
│  ✓ Read-only, for operator understanding              │
│                                                         │
│ [Send urgent signal to meta-controller]                │
│  (Only if homeostasis REFUSES critical fix)            │
│  ✓ Last resort, logged                                 │
│                                                         │
│ [POWER OFF (graceful shutdown)]                        │
│  ✓ Homeostasis initiates SURVIVAL mode, then shutdown  │
│                                                         │
└─────────────────────────────────────────────────────────┘

SAFETY RULES for operator:
  1. Cannot directly modify homeostasis code/config
  2. Cannot force mode change if system CRITICAL
  3. Cannot delete memories or reset agent
  4. Can only SUGGEST, then homeostasis decides
  5. Every action logged and timestamped
  6. Operator actions visible in audit trail
```

---

## CZĘŚĆ 7: PSEUDOKOD GŁÓWNEJ PĘTLI

### 7.1 Główna pętla homeostazy

```python
#!/usr/bin/env python3
"""
Main homeostasis event loop.
Runs continuously at ~1 Hz (1-second ticks).
"""

import time
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, List

# ============================================================================
# DEFINITIONS
# ============================================================================

class Mode(Enum):
    ACTIVE = "active"
    REDUCED = "reduced"
    SLEEP = "sleep"
    SURVIVAL = "survival"

@dataclass
class ResourceMetrics:
    timestamp: float
    ram_used_mb: float
    ram_total_mb: float
    cpu_percent: float
    temp_c: float
    disk_used_pct: float
    inference_latency_ms: float

@dataclass
class CognitiveMetrics:
    context_coherence: float  # 0-1
    error_count_1h: int
    goal_stack_depth: int
    memory_entries: int
    attention_fragmentation: float

@dataclass
class SystemState:
    mode: Mode
    health_score: float
    last_mode_change_time: float
    alerts: List[str]
    idle_seconds: int

# ============================================================================
# SENSOR & MEASUREMENT
# ============================================================================

class SensorLayer:
    """Reads raw system metrics."""
    
    def __init__(self):
        self.pulse_buffer = []  # Last 10 pulses (100ms each)
    
    def read_system_metrics(self) -> ResourceMetrics:
        """
        Non-blocking read of system metrics.
        Uses /proc, psutil, hwmon.
        """
        import psutil
        import os
        
        try:
            mem = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=None)  # Non-blocking
            temp = self._read_temperature()
            disk = psutil.disk_usage('/')
            
            # Inference latency = ask LLM subprocess
            inference_lat = self._measure_inference_latency()
            
            return ResourceMetrics(
                timestamp=time.time(),
                ram_used_mb=mem.used / 1024 / 1024,
                ram_total_mb=mem.total / 1024 / 1024,
                cpu_percent=cpu,
                temp_c=temp,
                disk_used_pct=disk.percent,
                inference_latency_ms=inference_lat
            )
        except Exception as e:
            # If sensor fails, assume worst case
            return ResourceMetrics(
                timestamp=time.time(),
                ram_used_mb=0, ram_total_mb=0, cpu_percent=100,
                temp_c=99, disk_used_pct=100, inference_latency_ms=9999
            )
    
    def _read_temperature(self) -> float:
        """Read CPU temp from /sys/class/thermal or hwmon."""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as f:
                return int(f.read()) / 1000.0
        except:
            return 50.0  # Default if unavailable
    
    def _measure_inference_latency(self) -> float:
        """Quick LLM latency check (non-blocking timeout)."""
        # Implementation: send short prompt, measure response time
        # Timeout: 5 seconds, return 9999 if hung
        pass
    
    def read_cognitive_metrics(self, memory_module) -> CognitiveMetrics:
        """Query memory + LLM for cognitive state."""
        try:
            coherence = memory_module.get_semantic_coherence()
            errors = memory_module.get_recent_errors_count(window_seconds=3600)
            goal_depth = self._get_goal_stack_depth()
            entries = memory_module.get_total_entries()
            frag = self._measure_attention_fragmentation()
            
            return CognitiveMetrics(
                context_coherence=coherence,
                error_count_1h=errors,
                goal_stack_depth=goal_depth,
                memory_entries=entries,
                attention_fragmentation=frag
            )
        except:
            # If cognitive sensors fail, assume critical state
            return CognitiveMetrics(
                context_coherence=0.5, error_count_1h=100,
                goal_stack_depth=50, memory_entries=0,
                attention_fragmentation=1.0
            )

# ============================================================================
# STATE INTERPRETER
# ============================================================================

class StateInterpreter:
    """Convert raw metrics to semantic state."""
    
    def __init__(self):
        self.metric_history = []  # Exponential smoothing buffer
        self.alpha = 0.3  # EMA parameter
    
    def process_metrics(self,
                       resource: ResourceMetrics,
                       cognitive: CognitiveMetrics) -> Dict:
        """
        Interpret metrics into semantic state.
        Apply exponential smoothing to reduce noise.
        """
        
        # Smooth resource metrics
        smoothed_resource = self._smooth_metric(resource)
        
        # Compute derived metrics
        ram_available_pct = (
            (smoothed_resource.ram_total_mb - smoothed_resource.ram_used_mb)
            / smoothed_resource.ram_total_mb * 100
        )
        
        cpu_load = smoothed_resource.cpu_percent
        thermal_stress = max(0, (smoothed_resource.temp_c - 60) / 35)  # 0-1
        memory_pressure = 100 - ram_available_pct  # 0-100
        
        # Cognitive interpretation
        coherence_ok = cognitive.context_coherence > 0.85
        errors_high = cognitive.error_count_1h > 20
        goal_stack_runaway = cognitive.goal_stack_depth > 25
        attention_dispersed = cognitive.attention_fragmentation > 0.7
        
        return {
            "timestamp": resource.timestamp,
            "ram_available_pct": ram_available_pct,
            "cpu_load": cpu_load,
            "thermal_stress": thermal_stress,
            "memory_pressure": memory_pressure,
            "coherence_ok": coherence_ok,
            "errors_high": errors_high,
            "goal_stack_runaway": goal_stack_runaway,
            "attention_dispersed": attention_dispersed,
            "inference_latency_ms": resource.inference_latency_ms,
        }
    
    def _smooth_metric(self, metric: ResourceMetrics) -> ResourceMetrics:
        """Apply exponential moving average."""
        self.metric_history.append(metric)
        if len(self.metric_history) > 5:
            self.metric_history.pop(0)
        
        # Simple average for now (implement EMA if needed)
        avg_ram = sum(m.ram_used_mb for m in self.metric_history) / len(self.metric_history)
        # ... etc
        
        return ResourceMetrics(
            timestamp=metric.timestamp,
            ram_used_mb=avg_ram,
            ram_total_mb=metric.ram_total_mb,
            cpu_percent=metric.cpu_percent,
            temp_c=metric.temp_c,
            disk_used_pct=metric.disk_used_pct,
            inference_latency_ms=metric.inference_latency_ms,
        )

# ============================================================================
# CONSTRAINT VALIDATOR
# ============================================================================

class ConstraintValidator:
    """Check invariants and alarm thresholds."""
    
    THRESHOLDS = {
        "ram_critical": 100,      # MB free → SURVIVAL
        "ram_orange": 200,        # MB free → REDUCED
        "ram_yellow": 500,        # MB free → consider REDUCED
        "cpu_orange": 80,         # % → throttle
        "temp_critical": 95,      # °C → shutdown prep
        "temp_orange": 85,        # °C → REDUCED
        "coherence_low": 0.80,    # → alert
        "errors_high_rate": 20,   # per hour → alert
        "goal_stack_depth": 25,   # → interrupt
    }
    
    def validate(self, state: Dict) -> tuple[bool, List[str]]:
        """
        Returns: (all_ok: bool, alerts: List[str])
        """
        alerts = []
        
        # Critical thresholds
        if state["ram_available_pct"] < 3:  # < 100 MB
            alerts.append("CRITICAL: RAM pressure imminent OOM")
        
        if state["temp_c"] > self.THRESHOLDS["temp_critical"]:
            alerts.append("CRITICAL: Temperature critical, shutdown imminent")
        
        if state["inference_latency_ms"] > 120000:  # 120 seconds
            alerts.append("CRITICAL: LLM hang detected")
        
        # Orange thresholds
        if state["ram_available_pct"] < 5:  # < 200 MB
            alerts.append("ALERT: RAM pressure critical")
        
        if state["cpu_load"] > 90:
            alerts.append("ALERT: CPU saturated")
        
        if state["temp_c"] > self.THRESHOLDS["temp_orange"]:
            alerts.append("ALERT: Temperature high, consider REDUCED mode")
        
        if not state["coherence_ok"]:
            alerts.append("WARNING: Semantic coherence degraded")
        
        if state["errors_high"]:
            alerts.append("WARNING: Error rate elevated")
        
        if state["goal_stack_runaway"]:
            alerts.append("WARNING: Goal stack depth excessive")
        
        return (len(alerts) == 0, alerts)

# ============================================================================
# MODE REGULATOR
# ============================================================================

class ModeRegulator:
    """Decide which mode system should be in."""
    
    def __init__(self):
        self.current_mode = Mode.ACTIVE
        self.mode_change_time = time.time()
        self.idle_counter = 0
    
    def decide_mode(self,
                   state: Dict,
                   alerts: List[str],
                   user_override: Optional[Mode] = None) -> Mode:
        """
        Determine appropriate mode based on state + constraints.
        
        Decision tree:
          1. If CRITICAL alert → SURVIVAL
          2. Else if user override + system not critical → override
          3. Else apply automatic decision rules
        """
        
        # EMERGENCY: CRITICAL alerts override everything
        if any("CRITICAL" in alert for alert in alerts):
            return Mode.SURVIVAL
        
        # User override (if system permits)
        if user_override and user_override != self.current_mode:
            if self._can_transition_to(user_override):
                return user_override
        
        # Automatic mode decisions
        ram_available_pct = state["ram_available_pct"]
        cpu_load = state["cpu_load"]
        idle_time = state.get("idle_seconds", 0)
        
        # SLEEP: If idle long enough and no tasks pending
        if idle_time > 1800 and ram_available_pct > 60:  # 30 min idle
            return Mode.SLEEP
        
        # REDUCED: If resource pressure
        if ram_available_pct < 20 or cpu_load > 75:
            return Mode.REDUCED
        
        # ACTIVE: Default (healthy state)
        if ram_available_pct > 30 and cpu_load < 60:
            return Mode.ACTIVE
        
        # Fallback: stay in current mode if borderline
        return self.current_mode
    
    def _can_transition_to(self, target_mode: Mode) -> bool:
        """Check if transition is safe."""
        # SURVIVAL ← from anything: always allowed
        # anything ← SURVIVAL: only if operator confirms
        # SLEEP ← ACTIVE: only if idle confirmed
        # REDUCED ← ACTIVE/SLEEP: if resources available
        
        if target_mode == Mode.SURVIVAL:
            return True
        
        if self.current_mode == Mode.SURVIVAL:
            # SURVIVAL → anything requires explicit approval
            return False  # Will be handled by operator
        
        if target_mode == Mode.SLEEP:
            # Only from ACTIVE, and only if idle confirmed
            return self.current_mode == Mode.ACTIVE
        
        if target_mode == Mode.REDUCED:
            return self.current_mode in [Mode.ACTIVE, Mode.SLEEP]
        
        return True

# ============================================================================
# CORRECTIVE ACTION GENERATOR
# ============================================================================

class CorrectiveActionGenerator:
    """Suggest actions to maintain homeostasis."""
    
    def generate_actions(self, state: Dict, alerts: List[str]) -> List[Dict]:
        """
        Returns list of suggested actions:
        [{
          "type": "mode_change" | "signal_module" | "trigger_consolidation",
          "target": module_name or mode,
          "reason": explanation,
          "urgency": "immediate" | "soon" | "background"
        }]
        """
        actions = []
        
        # Action 1: Memory consolidation
        if state["memory_pressure"] > 75:
            actions.append({
                "type": "signal_module",
                "target": "memory",
                "action": "consolidate_episodic",
                "target_freed_mb": 300,
                "urgency": "soon"
            })
        
        # Action 2: Pause background learning
        if state["cpu_load"] > 75:
            actions.append({
                "type": "signal_module",
                "target": "learning_engine",
                "action": "pause",
                "reason": "CPU saturation",
                "urgency": "soon"
            })
        
        # Action 3: Reduce inference batch size
        if state["inference_latency_ms"] > 2000:
            actions.append({
                "type": "signal_module",
                "target": "llm",
                "action": "reduce_batch_size",
                "factor": 0.5,
                "urgency": "immediate"
            })
        
        # Action 4: Goal stack interrupt
        if state["goal_stack_runaway"]:
            actions.append({
                "type": "signal_module",
                "target": "metacontroller",
                "action": "interrupt_goal_refinement",
                "reason": "Goal stack depth > threshold",
                "urgency": "immediate"
            })
        
        # Action 5: Semantic consolidation
        if not state["coherence_ok"] and state["memory_pressure"] > 50:
            actions.append({
                "type": "signal_module",
                "target": "memory",
                "action": "semantic_consistency_check",
                "urgency": "background"
            })
        
        return actions

# ============================================================================
# MAIN HOMEOSTASIS LOOP
# ============================================================================

class HomeostasisCore:
    """Main homeostasis coordinator."""
    
    def __init__(self, memory_module, llm_module, executor):
        self.memory = memory_module
        self.llm = llm_module
        self.executor = executor
        
        self.sensor = SensorLayer()
        self.interpreter = StateInterpreter()
        self.validator = ConstraintValidator()
        self.regulator = ModeRegulator()
        self.action_gen = CorrectiveActionGenerator()
        
        self.state = SystemState(
            mode=Mode.ACTIVE,
            health_score=1.0,
            last_mode_change_time=time.time(),
            alerts=[],
            idle_seconds=0
        )
        
        self.audit_log = []
    
    def main_loop(self):
        """
        Main homeostasis event loop.
        Runs every ~1 second.
        """
        tick_count = 0
        
        while True:
            try:
                tick_start = time.time()
                
                # ──────────────────────────────────────
                # PHASE 1: SENSE
                # ──────────────────────────────────────
                resource_metrics = self.sensor.read_system_metrics()
                cognitive_metrics = self.sensor.read_cognitive_metrics(self.memory)
                
                # ──────────────────────────────────────
                # PHASE 2: INTERPRET
                # ──────────────────────────────────────
                interpreted_state = self.interpreter.process_metrics(
                    resource_metrics, cognitive_metrics
                )
                
                # ──────────────────────────────────────
                # PHASE 3: VALIDATE CONSTRAINTS
                # ──────────────────────────────────────
                all_ok, alerts = self.validator.validate(interpreted_state)
                
                self.state.alerts = alerts
                
                # ──────────────────────────────────────
                # PHASE 4: DECIDE MODE
                # ──────────────────────────────────────
                new_mode = self.regulator.decide_mode(
                    interpreted_state, alerts
                )
                
                if new_mode != self.state.mode:
                    self._transition_mode(self.state.mode, new_mode)
                
                # ──────────────────────────────────────
                # PHASE 5: GENERATE CORRECTIVE ACTIONS
                # ──────────────────────────────────────
                actions = self.action_gen.generate_actions(
                    interpreted_state, alerts
                )
                
                self._execute_corrective_actions(actions)
                
                # ──────────────────────────────────────
                # PHASE 6: UPDATE HEALTH SCORE
                # ──────────────────────────────────────
                self.state.health_score = self._compute_health(
                    interpreted_state, alerts
                )
                
                # ──────────────────────────────────────
                # PHASE 7: AUDIT & LOG
                # ──────────────────────────────────────
                if tick_count % 60 == 0:  # Log every 60 seconds
                    self._log_state(interpreted_state)
                
                tick_count += 1
                
                # ──────────────────────────────────────
                # WAIT FOR NEXT TICK
                # ──────────────────────────────────────
                tick_duration = time.time() - tick_start
                if tick_duration < 1.0:
                    time.sleep(1.0 - tick_duration)
                else:
                    print(f"[WARNING] Homeostasis tick took {tick_duration:.2f}s")
            
            except Exception as e:
                print(f"[ERROR] Homeostasis loop exception: {e}")
                self.state.alerts.append(f"CRITICAL: Homeostasis exception: {e}")
                # Don't crash, continue
                time.sleep(1.0)
    
    def _transition_mode(self, old_mode: Mode, new_mode: Mode):
        """Safe mode transition with pre-checks."""
        print(f"[HOMEOSTASIS] Transitioning {old_mode.value} → {new_mode.value}")
        
        # Pre-transition: snapshot
        self._trigger_snapshot()
        
        # Signal dependent modules
        if new_mode == Mode.SLEEP:
            self.executor.signal_module("learning_engine", "pause")
        elif new_mode == Mode.SURVIVAL:
            self.executor.signal_module("llm", "minimize")
            self.executor.signal_module("memory", "readonly")
        elif new_mode == Mode.REDUCED:
            self.executor.signal_module("learning_engine", "pause")
        elif new_mode == Mode.ACTIVE:
            self.executor.signal_module("learning_engine", "resume")
        
        # Update state
        self.state.mode = new_mode
        self.state.last_mode_change_time = time.time()
        
        # Log
        self.audit_log.append({
            "timestamp": time.time(),
            "event": "mode_change",
            "from": old_mode.value,
            "to": new_mode.value
        })
    
    def _execute_corrective_actions(self, actions: List[Dict]):
        """Execute suggested corrective actions."""
        for action in actions:
            try:
                if action["type"] == "signal_module":
                    self.executor.signal_module(
                        action["target"],
                        action["action"],
                        **{k: v for k, v in action.items()
                           if k not in ["type", "target", "action"]}
                    )
                elif action["type"] == "mode_change":
                    # Handled by regulator
                    pass
            except Exception as e:
                print(f"[WARNING] Action failed: {action} - {e}")
    
    def _trigger_snapshot(self):
        """Save system state atomically."""
        try:
            self.executor.signal_module("memory", "checkpoint")
        except:
            pass
    
    def _compute_health(self, state: Dict, alerts: List[str]) -> float:
        """Aggregate health score 0-1."""
        score = 1.0
        
        for alert in alerts:
            if "CRITICAL" in alert:
                score -= 0.5
            elif "ALERT" in alert:
                score -= 0.15
            elif "WARNING" in alert:
                score -= 0.05
        
        # Factor in resource utilization
        score *= (1.0 - state["memory_pressure"] / 100 * 0.3)
        score *= (1.0 - state["cpu_load"] / 100 * 0.2)
        
        return max(0, min(1, score))
    
    def _log_state(self, state: Dict):
        """Periodic state logging."""
        self.audit_log.append({
            "timestamp": time.time(),
            "event": "state_snapshot",
            "mode": self.state.mode.value,
            "health": self.state.health_score,
            "ram_available_pct": state["ram_available_pct"],
            "cpu_load": state["cpu_load"],
            "alerts": self.state.alerts
        })

# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    # Initialize modules
    # (assuming these are implemented elsewhere)
    memory_module = MemoryManager()
    llm_module = LLMManager()
    executor = ModuleExecutor()
    
    # Create homeostasis core
    homeostasis = HomeostasisCore(memory_module, llm_module, executor)
    
    # Run main loop (blocks forever)
    homeostasis.main_loop()
```

### 7.2 Pulse thread (high-priority, non-blocking)

```python
import threading
import queue

class HomeostasisPulseThread(threading.Thread):
    """
    Runs every 100 ms at high priority.
    Detects CRITICAL emergencies FAST.
    Wakes main loop if needed.
    """
    
    def __init__(self, homeostasis_core, alert_queue):
        super().__init__(daemon=True)
        self.homeostasis = homeostasis_core
        self.alert_queue = alert_queue  # Queue to main loop
        self.running = True
    
    def run(self):
        """High-frequency pulse loop."""
        while self.running:
            try:
                tick_start = time.time()
                
                # Quick non-blocking reads
                resource = self.homeostasis.sensor.read_system_metrics()
                
                # Critical checks ONLY
                if resource.ram_used_mb > resource.ram_total_mb * 0.97:
                    # OOM imminent
                    self.alert_queue.put({
                        "type": "CRITICAL",
                        "message": "OOM imminent",
                        "timestamp": time.time()
                    })
                
                if resource.temp_c > 98:
                    self.alert_queue.put({
                        "type": "CRITICAL",
                        "message": "Thermal shutdown imminent",
                        "timestamp": time.time()
                    })
                
                if resource.inference_latency_ms > 60000:
                    self.alert_queue.put({
                        "type": "CRITICAL",
                        "message": "LLM hung (60s+ latency)",
                        "timestamp": time.time()
                    })
                
                # Sleep until next pulse
                elapsed = time.time() - tick_start
                sleep_time = max(0.05, 0.1 - elapsed)
                time.sleep(sleep_time)
            
            except Exception as e:
                print(f"[ERROR] Pulse thread exception: {e}")
                time.sleep(0.1)
    
    def stop(self):
        self.running = False
```

---

## CZĘŚĆ 8: DIAGRAM PRZEPŁYWU DECYZJI

```
START TICK
    ↓
┌──────────────────────────────────────────────┐
│ SENSE PHASE                                  │
│ - Read system metrics (CPU, RAM, temp)       │
│ - Read cognitive state (LLM, memory)         │
│ - Poll for user input/commands               │
└──────────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────────┐
│ INTERPRET PHASE                              │
│ - Apply exponential smoothing (noise filter) │
│ - Convert raw metrics → semantic state       │
│ - Compute derived metrics (pressure, load)   │
└──────────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────────┐
│ VALIDATE PHASE                               │
│ - Check hard constraints (OOM, temp)         │
│ - Check soft constraints (coherence, errors) │
│ - Generate alert list                        │
└──────────────────────────────────────────────┘
    ↓
    │ Any CRITICAL alerts?
    │
    ├─ YES ──→ [JUMP to SURVIVAL mode]
    │
    └─ NO ──→ Continue
              ↓
┌──────────────────────────────────────────────┐
│ MODE DECISION PHASE                          │
│ - Evaluate current mode vs. desired mode     │
│ - Check transition feasibility               │
│ - Respect user override (if not critical)    │
├──────────────────────────────────────────────┤
│ Decision tree:                               │
│ if idle_time > 30m AND ram_available > 60%  │
│   → SLEEP                                    │
│ else if ram_available < 20% OR cpu > 75%    │
│   → REDUCED                                  │
│ else if ram_available > 30% AND cpu < 60%   │
│   → ACTIVE                                   │
│ else                                         │
│   → stay in current mode                     │
└──────────────────────────────────────────────┘
    ↓
    │ Mode changed?
    │
    ├─ YES ──→ [Trigger TRANSITION sub-routine]
    │          - Snapshot state
    │          - Signal modules (pause/resume)
    │          - Update audit log
    │
    └─ NO ──→ Continue
              ↓
┌──────────────────────────────────────────────┐
│ CORRECTIVE ACTION PHASE                      │
│ - Evaluate what to FIX                       │
│ - Generate list of suggestions               │
├──────────────────────────────────────────────┤
│ Actions (examples):                          │
│ if memory_pressure > 75%:                    │
│   → suggest "consolidate_episodic"           │
│ if cpu_load > 75%:                           │
│   → suggest "pause_learning"                 │
│ if inference_latency > 2s:                   │
│   → suggest "reduce_batch_size"              │
│ if goal_stack_depth > 25:                    │
│   → suggest "interrupt_goal_refinement"      │
└──────────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────────┐
│ EXECUTE ACTIONS PHASE                        │
│ - Send signals to dependent modules          │
│ - Monitor compliance (async)                 │
│ - Log action outcome                         │
└──────────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────────┐
│ HEALTH COMPUTATION PHASE                     │
│ - Aggregate health score (0-1)               │
│ - Compute from: alerts, resource util, etc.  │
│ - Store for telemetry                        │
└──────────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────────┐
│ AUDIT & LOGGING                              │
│ - Log state snapshot (every 60s)             │
│ - Write audit trail (every action)           │
│ - Flush to disk if periodic checkpoint       │
└──────────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────────┐
│ WAIT FOR NEXT TICK                           │
│ - Target: ~1 second per tick                 │
│ - If tick > 1s: warn, log slowness           │
│ - If critical alert in queue: wake early     │
└──────────────────────────────────────────────┘
    ↓
REPEAT

```

---

## CZĘŚĆ 9: DODATKOWE SPECYFIKACJE

### 9.1 Snapshot protocol (atomic consistency)

```
Snapshot nie może być przerwany ani niekompletny.

PROTOCOL:
1. homeostasis.trigger_snapshot()
   ↓
2. Signal all modules: "prepare for checkpoint"
   - Memory: flush episodic buffer
   - LLM: save context state
   - Executor: pause non-critical tasks
   ↓
3. Wait for ACK from all modules (timeout: 5s)
   ↓
4. Take snapshot atomically:
   - Copy episodic memory to temp file
   - Copy semantic model to temp file
   - Copy metadata (mode, timestamp, health)
   - fsync() to ensure disk write
   ↓
5. Rename temp → current (atomic on POSIX)
   ↓
6. Verify snapshot validity (CRC check)
   ↓
7. If valid: log success, resume modules
   If invalid: roll back previous snapshot, alert operator
```

### 9.2 Graceful shutdown sequence

```
When operator requests shutdown (or system detects imminent power loss):

GRACEFUL SHUTDOWN (30-60 seconds available):
  1. Homeostasis → all modules: "shutdown.prepare"
  2. All modules finish in-progress operations
  3. Memory flushes all buffers
  4. LLM saves current context
  5. Homeostasis takes final snapshot
  6. fsync() all I/O
  7. Homeostasis: "ready.shutdown"
  8. System powers off

UNGRACEFUL SHUTDOWN (< 2 seconds):
  1. Homeostasis detects: power loss imminent OR interrupt signal
  2. Immediately trigger final snapshot (don't wait)
  3. fsync() core state only
  4. System dies
  5. On restart: recover from last snapshot

KEY: Last valid snapshot is always available for recovery.
```

### 9.3 Module communication contract

```python
# Every module MUST support these signals from homeostasis:

# PAUSE: Stop current work, save state
module.signal(type="pause", reason="resource_pressure")
→ Module responds: {"paused": true, "saved_state": {...}}

# RESUME: Resume from saved state
module.signal(type="resume")
→ Module responds: {"resumed": true}

# REDUCE_RESOURCES: Operate with fewer resources
module.signal(type="reduce_resources",
              resource="memory",
              new_limit_mb=256)
→ Module responds: {"complied": true, "freed_mb": 145}

# HEALTH_CHECK: Report current status
module.signal(type="health_check")
→ Module responds: {"healthy": true, "errors": 0, "latency_ms": 234}

# SHUTDOWN: Prepare for shutdown
module.signal(type="shutdown", grace_period_seconds=30)
→ Module responds: {"ready_shutdown": true}
```

---

## CZĘŚĆ 10: THREAT MODEL I MITIGACJE

```
Threat: LLM generates infinite loop
├─ Detection: Goal stack depth > 25 OR inference timeout > 60s
├─ Mitigation: Interrupt signal from homeostasis
├─ Prevention: Every goal evaluation has timeout (10s max)
└─ Fallback: Kill LLM process, recover from snapshot

Threat: Memory leak in module
├─ Detection: RAM usage growing despite no new work
├─ Mitigation: Homeostasis signals module to cleanup
├─ Prevention: Regular memory audits
└─ Fallback: Restart module, reload from snapshot

Threat: Thermal runaway
├─ Detection: Temp > 85°C sustained
├─ Mitigation: Throttle inference, reduce load
├─ Prevention: Monitor headroom, target < 70°C
└─ Fallback: Shutdown if > 95°C

Threat: Disk corruption
├─ Detection: Snapshot CRC fails
├─ Mitigation: Use previous valid snapshot
├─ Prevention: CoW (copy-on-write) snapshots
└─ Fallback: Multiple backup snapshots on separate media

Threat: Operator error (wrong mode forced)
├─ Detection: Homeostasis checks feasibility
├─ Mitigation: Reject unsafe transitions
├─ Prevention: UI validation before sending request
└─ Fallback: Homeostasis can override if CRITICAL

Threat: Cascading module failures
├─ Detection: Error rate > 10/min from multiple modules
├─ Mitigation: Isolate failed modules (circuit breaker)
├─ Prevention: Per-module error tracking + auto-disable
└─ Fallback: Degrade to survival mode
```

---

## PODSUMOWANIE: CORE PRINCIPLES

1. **Homeostasis ≠ watchdog** 
   - Watchdog = binary (alive/dead)
   - Homeostasis = continuous (healthy/degraded/critical)

2. **Homeostasis ≠ scheduler**
   - Scheduler = decides WHEN tasks run
   - Homeostasis = manages RESOURCE BUDGET for tasks

3. **Homeostasis IS central regulator**
   - Monitors ALL state (resources + cognition)
   - Decides operating mode based on constraints
   - Orchestrates recovery actions
   - Maintains audit trail of all decisions

4. **Modes enable graceful degradation**
   - ACTIVE = full capability
   - REDUCED = partial capability (controlled)
   - SLEEP = offline-first (scheduled hibernation)
   - SURVIVAL = bare minimum (emergency only)

5. **Time is explicit**
   - Pulse (100 ms): Fast emergency detection
   - Tick (1 s): Main decision loop
   - Epoch (1 h / 24 h): Archival, planning

6. **Continuity through snapshots**
   - Episodic + Semantic + Metadata = System identity
   - Persists across LLM restarts
   - Restored from disk on power-on

7. **Emergencja jest kontrolowana**
   - New behavior ≠ new chaos
   - Every emergent action validated by constraints
   - Reversible (audit trail + snapshots)
   - Bounded (resource budget enforced)

8. **Operator is informed, not in control**
   - Operator can SUGGEST (e.g., "enter REDUCED mode")
   - Homeostasis DECIDES (based on system state)
   - Override allowed only if not CRITICAL
   - All decisions logged

---

## WERSJA

**Status:** Specyfikacja gotowa do implementacji + code review
**Ostatnia aktualizacja:** styczeń 2026
**Autor:** Architecture by design (not metaphor)
**Następny krok:** Implementacja w Python + testing
