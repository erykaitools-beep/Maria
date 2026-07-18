# M.A.R.I.A. - Architectural Contracts

> Version: 1.6 | Created: 2026-03-01 | Revisions: v1.1 (event_id, registry, promote tx, auto-goals), v1.2 (dedup/priority/ttl per type, trace_id trade-off, ROLLBACK reason, PROPOSED isolation), v1.3 (Contract K5: Planner), v1.4 (Contract K6: World Model), v1.5 (Contract K7: Autonomy Policy), v1.6 (Contract K8: Deliberation)
> Approved by: M.A.R.I.A. Project
>
> This document defines the formal contracts ("constitutions") for the system's new layers.
> Every implementation MUST comply with these contracts.

---

## Table of Contents

1. [Unified Perception - PerceptionEvent](#contract-1-unified-perception)
2. [Sandbox / Production Boundary](#contract-2-sandbox--production-boundary)
3. [Goal System](#contract-3-goal-system)
4. [Agent Evaluation](#contract-4-agent-evaluation)
5. [Planner - ReAct Loop](#contract-5-planner)
6. [World Model / Belief System](#contract-6-world-model--belief-system)
7. [Autonomy Policy / Governance](#contract-7-autonomy-policy--governance)
8. [Deliberation / Strategic Planning](#contract-8-deliberation--strategic-planning)
9. [Decision: Tick Aggregator](#decision-5-tick-aggregator-adr-009)
10. [File Structure](#file-structure)
11. [Integration with existing code](#integration)

---

## Contract 1: Unified Perception

### Problem

The system has 5+ parallel, inconsistent data streams:
- Homeostasis sensors (5x dataclasses)
- User REPL (string commands)
- Learning results (JSONL)
- Consciousness events (JSONL)
- Teacher decisions (JSONL)

There is no common format. Modules don't know what is happening in other modules.

### Solution: PerceptionEvent

One format for ALL stimuli.

```python
class PerceptionSource(Enum):
    """Source of a perception event."""
    SENSOR = "sensor"                # Homeostasis sensors (5x)
    USER = "user"                    # REPL input, Web UI chat
    LEARNING = "learning"            # learn_next_chunk results, file scan
    EXAM = "exam"                    # run_exam_if_ready results
    CONSCIOUSNESS = "consciousness"  # trait evolution, sleep, dreams
    TEACHER = "teacher"              # TeacherAgent decisions
    PLANNER = "planner"              # Planner decisions (K5)
    SYSTEM = "system"                # Mode changes, alerts, startup/shutdown


@dataclass(frozen=True)
class PerceptionEvent:
    """Universal perception-event format."""
    event_id: str                # UUID4 - unique identifier of this event
    source: PerceptionSource     # Who generated the event
    event_type: str              # e.g. "resource_reading", "user_message", "exam_result"
    priority: float              # 0.0 (ignore) to 1.0 (react immediately)
    timestamp: float             # time.time()
    payload: Dict[str, Any]      # Source data (structure per the Event Type Registry)
    ttl: float                   # Seconds until expiry (0 = no limit)
    parent_event_id: Optional[str]  # event_id of the causing event (causal chain)
```

### Identifier semantics

- **`event_id`** - unique UUID4 per event. Every event has EXACTLY one.
- **`parent_event_id`** - references the `event_id` of the event that DIRECTLY caused this event.
  - Example chain: teacher_decision(id=A) → learn_chunk(id=B, parent=A) → exam_result(id=C, parent=B)
  - Tracing the whole chain: follow `parent_event_id` recursively until `None`.
- **No separate `correlation_id` / `trace_id`** - a deliberate trade-off:
  - `parent_event_id` gives a causality tree (sufficient at the scale of 5-6 sources)
  - `trace_id` / `correlation_id` would allow grouping parallel events into a single "case" (e.g. an entire user flow)
  - For now: not needed. If needed in the future: add 1 optional field, zero breaking changes.
  - **When to add:** once the Planner (Layer 2) appears and needs to track many concurrent actions.

### Priority table

| Priority | Event type | Example |
|----------|--------------|---------|
| **1.0** | CRITICAL alerts | RAM OOM, thermal shutdown, SURVIVAL |
| **0.9** | User input | REPL command, chat message |
| **0.8** | Mode transitions, exam results | ACTIVE->REDUCED, score=0.85 |
| **0.7** | Learning completion | Chunk learned successfully |
| **0.5** | Teacher decisions, consciousness | Strategy chosen, trait emerged |
| **0.3** | Periodic sensor readings | 1Hz tick data (resource, cognitive) |
| **0.1** | State snapshots, audit | Periodic logging |

### Default TTLs

| Event type | TTL | Rationale |
|---------------|-----|-------------|
| Sensor readings | 5s | Stale data is useless |
| User input | 0 (none) | Always relevant |
| Learning/exam results | 300s (5 min) | Context of the current session |
| Mode changes | 0 (none) | Historically important |

### Event Type Registry

A registry mapping `event_type` → required `payload` fields.
NOT validated at runtime - this is a specification, not enforcement.
Purpose: to keep the payload from descending into anarchy after 3 sprints.

| event_type | source | priority | ttl | dedup | Required payload fields | Optional |
|-----------|--------|----------|-----|-------|----------------------|------------|
| `resource_reading` | SENSOR | 0.3 | 5s | yes | `ram_available_mb`, `ram_available_pct`, `cpu_percent`, `temp_c`, `disk_used_pct` | `inference_latency_ms`, `swap_used_pct`, `load_avg_1m` |
| `cognitive_reading` | SENSOR | 0.3 | 5s | yes | `context_coherence`, `inference_latency_ms`, `error_count_1h`, `goal_stack_depth` | `memory_entries`, `contradiction_count`, `attention_fragmentation` |
| `thermal_reading` | SENSOR | 0.3 | 5s | yes | `cpu_temp_c`, `is_throttling` | `fan_speed_rpm` |
| `power_reading` | SENSOR | 0.3 | 5s | yes | `uptime_seconds`, `is_on_battery` | `voltage_v` |
| `time_reading` | SENSOR | 0.3 | 5s | yes | `idle_streak_sec`, `hour_of_day`, `session_duration_sec` | `day_of_week` |
| `user_message` | USER | 0.9 | 0 | no | `text`, `channel` | `user_id` |
| `user_command` | USER | 0.9 | 0 | no | `command`, `args` | `channel` |
| `chunk_learned` | LEARNING | 0.7 | 300s | no | `file_id`, `chunk_index`, `chunks_total` | `summary_preview` |
| `file_scan_result` | LEARNING | 0.5 | 300s | yes | `new_files`, `changed_files`, `total_files` | |
| `exam_result` | EXAM | 0.8 | 300s | no | `file_id`, `score`, `passed`, `attempt` | `num_questions` |
| `teacher_decision` | TEACHER | 0.5 | 300s | no | `strategy_type`, `target_file_id` | `reason`, `iteration` |
| `teacher_session_complete` | TEACHER | 0.5 | 300s | no | `chunks_learned`, `exams_run`, `exams_passed` | `errors` |
| `trait_emerged` | CONSCIOUSNESS | 0.5 | 300s | no | `trait`, `score` | `previous_score` |
| `trait_faded` | CONSCIOUSNESS | 0.5 | 300s | no | `trait`, `score` | `previous_score` |
| `dream_generated` | CONSCIOUSNESS | 0.5 | 300s | no | `dream_count`, `session_id` | `themes` |
| `sleep_cycle` | CONSCIOUSNESS | 0.5 | 300s | no | `phases_completed` | `dream_count` |
| `mode_change` | SYSTEM | 0.8 | 0 | no | `from_mode`, `to_mode` | `trigger`, `health_score` |
| `alert` | SYSTEM | 1.0 | 0 | no | `alert_type`, `severity`, `message` | `value`, `threshold` |
| `sandbox_promoted` | LEARNING | 0.7 | 300s | no | `session_id`, `files_promoted`, `chunks_promoted` | |
| `sandbox_discarded` | LEARNING | 0.3 | 300s | no | `session_id`, `reason` | |
| `goal_created` | SYSTEM | 0.5 | 0 | no | `goal_id`, `goal_type`, `description` | `priority` |
| `goal_achieved` | SYSTEM | 0.5 | 0 | no | `goal_id`, `goal_type` | `duration_sec` |

**Columns:**
- **priority** - default priority (an adapter can override it, e.g. CRITICAL alert = 1.0, WARNING = 0.5)
- **ttl** - default time-to-live (0 = no limit)
- **dedup** - whether it can be deduplicated (yes = if an identical payload is in the buffer, the new event replaces the old one)

**Adding new event_types:** Add to this table BEFORE implementing the adapter.
If the payload does not fit any existing type, that is a sign a new type is needed.

### Adapters (mapping existing streams)

6 adapters, each with a `to_perception_event()` method:

| Adapter | Source | Event types |
|---------|--------|-------------|
| `sensor_adapter.py` | ResourceMetrics, CognitiveMetrics, ThermalMetrics, PowerMetrics, TimeMetrics | `resource_reading`, `cognitive_reading`, `thermal_reading`, `power_reading`, `time_reading` |
| `user_adapter.py` | REPL input, WebUI messages | `user_message`, `user_command` |
| `learning_adapter.py` | `learn_next_chunk()` return | `chunk_learned`, `file_scan_result` |
| `exam_adapter.py` | `run_exam_if_ready()` return | `exam_result`, `exam_failed` |
| `consciousness_adapter.py` | ExperienceTracker, SleepProcessor | `trait_emerged`, `trait_faded`, `dream_generated`, `sleep_cycle` |
| `teacher_adapter.py` | TeacherAgent decisions | `teacher_decision`, `teacher_session_complete` |

### Example: Sensor reading → PerceptionEvent

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

### Example: User message → PerceptionEvent

```python
PerceptionEvent(
    event_id="e5f6g7h8-...",
    source=PerceptionSource.USER,
    event_type="user_message",
    priority=0.9,
    timestamp=1709312405.0,
    payload={
        "text": "What do you know about quantum physics?",
        "channel": "repl",
    },
    ttl=0,
    parent_event_id=None,
)
```

### Example: Exam result (downstream of teacher decision)

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
    parent_event_id="m3n4o5p6-...",  # event_id of the teacher_decision that triggered this exam
)
```

### PerceptionBuffer

```python
class PerceptionBuffer:
    """Sliding window of the most recent perception events."""

    def __init__(self, maxlen: int = 200):
        self._buffer: deque = deque(maxlen=maxlen)

    def push(self, event: PerceptionEvent) -> None:
        """Add an event to the buffer."""
        self._buffer.append(event)

    def get_recent(self, n: int = 10, source: Optional[PerceptionSource] = None) -> List[PerceptionEvent]:
        """Get the N most recent events, optionally filtered by source."""
        ...

    def get_by_priority(self, min_priority: float = 0.5) -> List[PerceptionEvent]:
        """Get events with priority >= min_priority."""
        ...

    def drain_expired(self) -> int:
        """Remove expired events (ttl). Returns the number removed."""
        ...
```

### What it does NOT cover

- No async/threading in PerceptionEvent (adapters are synchronous)
- No runtime schema validation (the payload is trusted, the registry is documentation)
- No persistence in the perception layer (each subsystem has its own JSONL)
- No Vision/Smart Home adapters (added when Layer 4/6 is built)
- No deduplication (at 1Hz from 5-6 sources, duplicates are not a problem)

---

## Contract 2: Sandbox / Production Boundary

### Problem

Learning writes directly to production JSONL. No validation before writing.
One bad LLM result = garbage in the knowledge base forever.

### Guiding principle

**EVERY learning operation goes through the sandbox. promote() is the ONLY bridge to production.**

### Schema

```python
class SandboxStatus(Enum):
    ACTIVE = "active"            # Sandbox is active, learning in progress
    READY_TO_PROMOTE = "ready"   # Criteria met, awaiting promote
    PROMOTED = "promoted"        # Content moved to production
    DISCARDED = "discarded"      # Content discarded


@dataclass
class SandboxSession:
    """A single isolated learning session."""
    session_id: str              # UUID
    created_at: float            # time.time()
    status: SandboxStatus

    # Paths
    sandbox_dir: Path            # meta_data/sandbox/sess_<id>/
    sandbox_index: Path          # sandbox_dir / "knowledge_index.jsonl"
    sandbox_memory: Path         # sandbox_dir / "maria_longterm_memory.jsonl"
    sandbox_exams: Path          # sandbox_dir / "exam_results.jsonl"

    # Metrics (updated after each operation)
    files_learned: int = 0
    chunks_learned: int = 0
    exams_passed: int = 0
    exams_total: int = 0
    avg_score: float = 0.0
    validation_errors: List[str] = field(default_factory=list)

    def meets_promote_criteria(self) -> bool:
        """Check whether the sandbox is ready for promotion."""
        return (
            len(self.validation_errors) == 0
            and self.exams_total > 0
            and self.avg_score >= 0.6  # = EXAM_PASS_THRESHOLD
            and self.chunks_learned > 0
        )


@dataclass
class PromoteResult:
    """Result of a promote() operation."""
    success: bool
    files_promoted: int
    chunks_promoted: int
    errors: List[str] = field(default_factory=list)
```

### Operations allowed in the sandbox

| Operation | Allowed? | Notes |
|----------|-----------|-------|
| `learn_next_chunk()` | YES | With `index_path=sandbox_index, memory_path=sandbox_memory` |
| `run_exam_if_ready()` | YES | With `index_path=sandbox_index, exam_path=sandbox_exams` |
| Re-learn (retry) | YES | Re-learning with different prompts |
| Modifying semantic_graph | NO | Only after promote |
| Modifying personality traits | NO | Learning does not change personality |

**Key:** No changes to `learning_agent.py` / `exam_agent.py` - they already accept path parameters.

### promote() rules

**Mandatory conditions (all must be met):**

1. `chunks_learned > 0` - something was learned
2. `exams_total > 0` - at least one exam
3. `avg_score >= 0.6` - average score >= pass threshold (EXAM_PASS_THRESHOLD)
4. All JSONL in the sandbox parse correctly
5. No entries in `validation_errors`

**Mechanism:**
- Promote = APPEND records from sandbox JSONL to production JSONL
- Uses the existing file locking from `memory_store.py`
- Index records merged by `file_id` (newer `updated_at` wins)
- Promote is **atomic per session**: all or nothing
- After a successful promote: the sandbox session directory is deleted

**Transaction log (`meta_data/promote_log.jsonl`):**

Each promote writes START/COMMIT (or ROLLBACK) markers to detect interrupted operations:

```json
{"ts": 1709312500.0, "marker": "START", "session_id": "sess_abc123", "files": 2, "chunks": 8}
{"ts": 1709312500.5, "marker": "COMMIT", "session_id": "sess_abc123", "result": "ok"}
```

If, at system startup, we find a START without a COMMIT:
1. Sandbox dir still exists → data was not moved, status OK (sandbox intact)
2. Sandbox dir does not exist → a partial append may have occurred → WARNING in logs, manual review

```json
{"ts": 1709312500.0, "marker": "ROLLBACK", "session_id": "sess_abc123", "reason": "validation_error", "exception": "JSONDecodeError at line 42"}
```

Rules:
- START always BEFORE the first append to production
- COMMIT after ALL appends complete + sandbox dir removed
- ROLLBACK if any append fails (sandbox dir remains)
  - ROLLBACK MUST include `reason` (short description) and `exception` (error string or null)
- **At system startup:** scan promote_log.jsonl; if the last entry is a START without a COMMIT:
  1. If sandbox dir exists → **auto-DISCARD** the session (not a zombie, clean closure)
  2. If sandbox dir does NOT exist → WARNING in logs + manual review (partial append)
  3. In both cases: append a ROLLBACK marker with `reason: "startup_recovery"`

### discard() rules

| Trigger | Action |
|---------|-------|
| User explicitly runs `/sandbox discard` | Delete the sandbox session directory |
| Sandbox older than 24h without promote | Auto-discard |
| System enters SURVIVAL | Auto-discard ALL active sessions |
| Discard | = deletes the entire `sandbox_dir` directory |

### Flow

```
Teacher/User requests learning
  |
  v
SandboxManager.create_session()
  → meta_data/sandbox/sess_abc123/
  |
  v
seed_from_production(file_ids)
  ← copies records from memory/knowledge_index.jsonl
  |
  v
learn_next_chunk(path=sandbox)
  ← writes to sandbox JSONL
  |
  v
run_exam_if_ready(path=sandbox)
  |
  v
meets_promote_criteria()?
  |
  ├── YES → promote()
  |         ├── append to memory/*.jsonl
  |         ├── delete sandbox dir
  |         └── emit PerceptionEvent(source=LEARNING, type="sandbox_promoted")
  |
  └── NO  → retry (re-learn) or discard()
            └── emit PerceptionEvent(source=LEARNING, type="sandbox_discarded")
```

### Constraints

- Max 1 active sandbox session (Maria learns ~10 files, not millions)
- No sandbox for chat/conversation (learning only)
- No partial promote (cherry-picking individual files)
- No production versioning/rollback (that is what backup.sh is for)

---

## Contract 3: Goal System

### Problem

Goals are implicit - hardcoded thresholds in mode_regulator, an if/elif chain in teacher P1-P6.
They cannot be changed at runtime, have no history, and cannot be observed.

### Solution: Minimal goal model

```python
class GoalType(Enum):
    META = "meta"                # System mission (1 goal, always active)
    USER = "user"                # Goals from the user (via /goal create)
    LEARNING = "learning"        # Learning goals (generated from Teacher P1-P6)
    MAINTENANCE = "maintenance"  # Maintenance goals (from homeostasis thresholds)


class GoalStatus(Enum):
    PROPOSED = "proposed"        # Auto-suggested, awaiting user confirmation
    PENDING = "pending"          # Approved, not started
    ACTIVE = "active"            # In progress
    ACHIEVED = "achieved"        # Achieved
    FAILED = "failed"            # Failed
    ABANDONED = "abandoned"      # Deliberately abandoned


@dataclass
class AuditEntry:
    """Record of a goal status change."""
    timestamp: float
    old_status: str
    new_status: str
    reason: str
    actor: str                   # "teacher" / "user" / "homeostasis" / "planner" / "system"


@dataclass
class Goal:
    """A single goal in Maria's goal system."""
    id: str                      # UUID
    type: GoalType
    description: str             # Human-readable (Polish is fine)
    priority: float              # 0.0 to 1.0
    status: GoalStatus
    progress: float              # 0.0 to 1.0
    parent_goal_id: Optional[str]  # Hierarchy (Stage B: rollup, max depth 3)
    created_by: str              # "system" / "user" / "teacher" / "homeostasis"
    created_at: float            # time.time()
    updated_at: float            # time.time()
    deadline: Optional[float]    # Epoch (Stage B: urgency in selection + reaper, flag-gated)
    audit_trail: List[AuditEntry] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### Mapping of current implicit goals

#### META (seed goal, created on first run)

```
Goal(
    id="goal-meta-learn",
    type=META,
    description="Autonomous learning and structuring of knowledge from text files",
    priority=1.0,
    status=ACTIVE,
    progress=<computed from knowledge_coverage>,
    parent_goal_id=None,
    created_by="system",
)
```

#### LEARNING (generated from Teacher P1-P6)

| Teacher Priority | Goal description | Priority | Metadata |
|-----------------|------------------|----------|----------|
| P1 | "Continue learning: {file} ({n}/{m} chunks)" | 0.9 | `teacher_priority: 1, file_id, chunks_done, chunks_total` |
| P2 | "Exam on: {file}" | 0.85 | `teacher_priority: 2, file_id` |
| P3 | "Start a new file: {file}" | 0.7 | `teacher_priority: 3, file_id` |
| P4 | "Review: {file} (score: {score}%)" | 0.6 | `teacher_priority: 4, file_id, last_score` |
| P5 | "Retry a hard topic: {file}" | 0.5 | `teacher_priority: 5, file_id` |
| P6 | "NIM knowledge-gap analysis" | 0.4 | `teacher_priority: 6` |

#### MAINTENANCE (always active)

```
Goal(id="goal-maint-health", type=MAINTENANCE,
     description="Maintain health_score >= 0.7",
     priority=1.0, status=ACTIVE,
     progress=<current health / threshold>,
     metadata={"metric": "health_score", "threshold": 0.7})

Goal(id="goal-maint-ram", type=MAINTENANCE,
     description="RAM available > 20%",
     priority=0.95, status=ACTIVE,
     parent_goal_id="goal-maint-health",
     metadata={"metric": "ram_available_pct", "threshold": 20})

Goal(id="goal-maint-cpu", type=MAINTENANCE,
     description="CPU < 75%",
     priority=0.95, status=ACTIVE,
     parent_goal_id="goal-maint-health",
     metadata={"metric": "cpu_load", "threshold": 75})
```

#### USER (two creation modes)

**Mode 1: Explicit** - the user creates a goal with a REPL command:
```
# /goal create "Learn everything about physics"
Goal(id="goal-user-physics", type=USER,
     description="Learn everything about physics",
     priority=0.8, status=PENDING,       # Immediately PENDING (approved)
     created_by="user")
```

**Mode 2: Auto-suggested** - Maria detects an intent in conversation and PROPOSES a goal:
```
# User writes: "I'd like to know more about astronomy"
# Maria detects the intent and creates a PROPOSED goal:
Goal(id="goal-user-astronomy", type=USER,
     description="Deepen knowledge of astronomy",
     priority=0.7, status=PROPOSED,      # PROPOSED - awaiting confirmation
     created_by="consciousness",          # Maria proposed it herself
     metadata={"source_message": "I'd like to know more about astronomy",
               "confidence": 0.8})

# Maria asks: "Do you want me to set myself the goal: 'Deepen knowledge of astronomy'?"
# User: yes → status PROPOSED → PENDING (audit: "user confirmed")
# User: no  → status PROPOSED → ABANDONED (audit: "user rejected")
```

**Auto-suggestion rules:**
- Maria NEVER activates an auto-goal without user confirmation
- **PROPOSED does not affect the system** (isolation from planning):
  - Does not change teacher priorities (P1-P6 ignore PROPOSED)
  - Does not generate learning tasks
  - Does not change the day's plan
  - Does not affect the mode regulator or homeostasis
  - Only after CONFIRM (PROPOSED → PENDING) does the goal enter the system
- PROPOSED goals older than 24h without a response → auto-ABANDONED
- Max 3 PROPOSED goals at once (do not flood the user with questions)
- Intent detection: pure logic (keyword matching on Polish cues like "chce", "naucz", "pokaz", etc.) - zero LLM in v1

### Rules

| Rule | Value | Rationale |
|--------|---------|-------------|
| Max active goals | 20 | Maria learns ~10 files; 20 gives headroom |
| Max PROPOSED goals | 3 | Do not flood the user with questions |
| Max hierarchy depth | 3 | META → LEARNING/MAINTENANCE → sub-goal |
| Audit trail | Mandatory | Every status change = AuditEntry with reason and actor |
| Auto-ACHIEVED | progress >= 1.0 when ACTIVE | The system automatically closes achieved goals |
| PROPOSED timeout | 24h | PROPOSED without a response → auto-ABANDONED |
| MAINTENANCE reset | Every session | MAINTENANCE goals are never ACHIEVED, reset at startup |
| ABANDON overflow | Lowest PENDING | When 20 active is exceeded |
| Persistence | `meta_data/goals.jsonl` | Append-only, last record per id wins |
| Runtime modification | Yes | Any module with `SharedContext.goal_store` can CRUD |
| Auto-suggestion | Human-in-the-loop | Maria NEVER activates a goal without user confirmation |
| PROPOSED isolation | Zero impact | PROPOSED does not change priorities, generate tasks, or change the plan |

### GoalStore API

```python
class GoalStore:
    """CRUD + goal persistence."""

    def create(self, goal: Goal) -> str:
        """Create a goal (status PENDING or ACTIVE), return id."""

    def propose(self, goal: Goal) -> str:
        """Create a goal with status PROPOSED (awaiting user confirmation). Return id."""

    def confirm(self, goal_id: str) -> bool:
        """User confirms a PROPOSED goal → PENDING. Returns False if the goal is not PROPOSED."""

    def reject(self, goal_id: str) -> bool:
        """User rejects a PROPOSED goal → ABANDONED. Returns False if the goal is not PROPOSED."""

    def get(self, goal_id: str) -> Optional[Goal]:
        """Get a goal by id."""

    def get_active(self, goal_type: Optional[GoalType] = None) -> List[Goal]:
        """Get active goals (PENDING + ACTIVE), optionally filtered by type."""

    def get_proposed(self) -> List[Goal]:
        """Get goals awaiting user confirmation (status PROPOSED)."""

    def update_status(self, goal_id: str, status: GoalStatus, reason: str, actor: str) -> bool:
        """Change status with an audit trail entry."""

    def update_progress(self, goal_id: str, progress: float) -> bool:
        """Update progress (auto-ACHIEVED at 1.0)."""

    def abandon_lowest(self) -> Optional[str]:
        """Abandon the lowest-priority PENDING goal. Returns id or None."""

    def expire_proposed(self) -> int:
        """Auto-ABANDON PROPOSED goals older than 24h. Returns the number abandoned."""

    def load(self) -> None:
        """Load from meta_data/goals.jsonl."""

    def save(self) -> None:
        """Save to meta_data/goals.jsonl (append-only)."""
```

### What it does NOT cover

- No LLM goal generation in v1 (pure logic / keyword matching)
- No dependency graph between goals (parent-child only)
- No goal templates
- No AUTONOMOUS sub-goal creation (trees are created by the operator via /project)
- Auto-suggestion NEVER activates a goal without user confirmation (human-in-the-loop)

### Digital Human Stage B: sub-goal trees + deadlines (2026-06-22)

Two dead fields (`parent_goal_id`, `deadline`, 0 readers) brought to life. Everything
behind `.env` flags, OFF BY DEFAULT (flag -> observe -> cutover); code unchanged when OFF.

- **Schema-guard (always-on, no flag):** `store.create/propose` reject a bad
  parent link (parent does not exist / self-parent / cycle / depth >
  `MAX_HIERARCHY_DEPTH=3`) by orphaning the goal (flat) + logging ERROR. Fail-SAFE:
  `create()` returns an id as before. No-op for the existing (flat) population.
- **Rollup (`GOAL_ROLLUP_ENABLED`):** planner phase STEP 2.35. A terminal child
  -> the parent's `progress = terminal/total`; all ACHIEVED ->
  parent ACHIEVED; any FAILED/ABANDONED/CANCELLED (rest terminal) ->
  parent FAILED (`ANY_FAIL_FAILS_PARENT`). **MAINTENANCE skipped** (the seed-tree
  health<-ram/cpu does not auto-close). Aggregates ONLY the status of terminal children
  -- NEVER re-evaluates a leaf's `success_criteria`/exam (does not collide with the
  2026-05-31 closure). `agent_core/goals/rollup.py`.
- **Deadline urgency (`GOAL_DEADLINE_ENABLED`):** `goal_selector._compute_effective_priority`
  multiplies the effective priority by a deadline multiplier (overdue x3.0; <=24h ramp
  1.0->2.0; far/None x1.0), multiplicatively after aging, clamp 3.0. Only
  RE-ORDERS the feasible set; does not change feasibility gates. `deadline` = absolute
  epoch (TZ-safe).
- **Deadline reaper (`GOAL_DEADLINE_REAP_ENABLED`, SEPARATE flag):** overdue
  still-active non-MAINTENANCE/non-META -> FAILED (`deadline_overdue`). A separate track
  from the age-reaper. OFF even when urgency=cutover.
- **Operator tap:** `/project <name> | <deadline> | <subgoal1> ; <subgoal2>` creates
  a USER parent + USER children (deadline inherited). `/projects` = tree view.

---

## Contract 4: Agent Evaluation

### Problem

Evaluation is scattered: exam scores in one JSONL, health_score in another,
teacher stats in memory. There is no single coherent picture of "how Maria is doing".

### Guiding principle

**Strictly READ-ONLY** (an extension of ADR-006, like introspection).
The observer reads logs and metrics, NEVER modifies them.

### 5 key metrics

| # | Metric | Definition | Data source | Window |
|---|---------|-----------|---------------|------|
| 1 | `learning_velocity` | chunks / hour | `teacher_plans.jsonl` | Rolling 1h |
| 2 | `retention_rate` | exams_passed / exams_total | `exam_results.jsonl` | All-time |
| 3 | `knowledge_coverage` | completed_files / total_files | `knowledge_index.jsonl` | Current |
| 4 | `system_stability` | avg health_score | `homeostasis_events.jsonl` | Rolling 1h |
| 5 | `personality_growth` | sum \|trait_delta\| | `personality_experiences.jsonl` | Last N sessions |

### Report format (JSON)

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
      "traits_emerged": ["persistent"],
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
    "Retention rate < 80% - consider more reviews (P4)",
    "2 hard topics - consider a retry after finishing 1 more file"
  ]
}
```

### Rules

| Rule | Value |
|--------|---------|
| Mode | READ-ONLY (ADR-006 extended) |
| Writes to | ONLY `meta_data/evaluation_reports.jsonl` (its own reports) |
| Frequency | On-demand (`/evaluate`) + every 300 ticks (5 min) in ACTIVE |
| LLM | ZERO (pure logic, thresholds) |
| Implementation pattern | Like `knowledge_analyzer.py` (reads JSONL, zero side effects) |

### Recommendations (thresholds)

| Condition | Recommendation |
|---------|-------------|
| `retention_rate < 0.8` | "Consider more reviews (P4)" |
| `retention_rate < 0.6` | "Retention critically low - simplify prompts" |
| `learning_velocity == 0` for 2h | "No learning for 2h" |
| `knowledge_coverage > 0.9` | "Almost everything learned - look for new materials" |
| `system_stability < 0.7` | "System unstable - check resources" |
| `personality_growth == 0` for 3 sessions | "No personality evolution" |

### Feed into Goal System (future)

The observer **SUGGESTS**, the GoalStore **DECIDES**:

```
retention_rate < 0.7
  → suggestion: boost the priority of P4 goals (reviews) by +0.1

learning_velocity == 0 for 2h
  → suggestion: new LEARNING goal "resume learning"

knowledge_coverage > 0.9
  → suggestion: META goal "look for new materials"
```

The observer never modifies goals directly.
Suggestions are a `List[GoalAdjustment]` that the GoalStore may accept or ignore.

### What it does NOT cover

- No LLM calls (pure math + thresholds)
- No modification of source JSONL
- No alerts (that is homeostasis's domain)
- No trends/charts (that is the Web UI's domain)
- No cross-session comparison (future feature)

---

## Contract 5: Planner

### Problem

K1-K4 gave Maria perception, sandbox, goals, and evaluation - but there is no "agent" that ties it together.
The Teacher (P1-P6) runs on an if/elif chain with hardcoded priorities; the Phase 10 tick loop
fires it every 10min of idle. There is no central decision loop.

### Solution: Rule-based ReAct Loop (ADR-013)

Planner v1 = deterministic, rule-based, zero LLM. Testable and predictable.

```
OBSERVE -> THINK -> ACT -> EVALUATE
   |                          |
   +-------- REPEAT ----------+
```

- **OBSERVE:** Read the PerceptionBuffer (K1), GoalStore (K3), EvaluationObserver (K4)
- **THINK:** GoalSelector picks a goal, PlannerGuard checks the gating rules
- **ACT:** ActionExecutor delegates to Teacher/Sandbox (K2)
- **EVALUATE:** Emit PerceptionEvent(PLANNER), log the decision

### Planner replaces Phase 10

The Phase 10 tick loop (teacher auto-trigger) is replaced by PlannerCore:
- If PlannerCore is connected: `planner.run_cycle(tick)` in Phase 10
- If not: fall back to the old `_check_teacher_trigger()` (backward-compatible)

### Data model

```python
class PlanStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ActionType(Enum):
    LEARN = "learn"          # Delegate learning to Teacher
    EXAM = "exam"            # Delegate an exam to Teacher
    REVIEW = "review"        # Delegate a review to Teacher
    EVALUATE = "evaluate"    # Generate a K4 report
    MAINTENANCE = "maintenance"  # Check health metrics
    NOOP = "noop"            # Nothing to do


@dataclass
class Plan:
    """A single planning step (not a tree/graph)."""
    plan_id: str             # UUID
    timestamp: float
    goal_id: Optional[str]   # The goal it serves
    goal_description: str
    action_type: ActionType
    action_params: Dict[str, Any]
    status: PlanStatus
    result: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None  # Optional (per ChatGPT review)
    duration_ms: float = 0.0


@dataclass
class PlannerState:
    """Persistent Planner state (planner_state.json)."""
    total_cycles: int = 0
    total_plans: int = 0
    last_plan_id: Optional[str] = None
    last_evaluation_ts: float = 0.0
    last_cycle_ts: float = 0.0
```

### Planner Guard (gating rules)

The Planner does NOT plan if the conditions are not met:

| Rule | Blocking condition | Rationale |
|--------|-------------------|-------------|
| Health | `health_score < 0.7` | System not healthy - do not load it |
| Mode | `mode != ACTIVE` | In REDUCED/SLEEP/SURVIVAL, do not plan learning |
| Sandbox | Active sandbox session | Wait for promote/discard |
| Retention | `retention_rate < 0.5` | Too many failures - do not add new learning |
| Teacher | Teacher thread active | Do not interfere with the current session |

```python
class PlannerGuard:
    def can_plan(self, health, mode, sandbox_active,
                 retention, teacher_running) -> Tuple[bool, List[str]]:
        """Returns (can_plan, list_of_block_reasons)."""
```

### Goal Selector (aging factor)

Prevents starvation (a long-waiting goal is promoted):

```python
effective_priority = priority * (1.0 + min(hours_pending * 0.1, 4.0))
```

- After 1h pending: x1.1
- After 10h pending: x2.0
- After 24h pending: x3.4
- Max: x5.0 (clamp)

Feasibility check per goal type:
- MAINTENANCE / META / USER: always feasible
- LEARNING: requires files available to learn

### Action Executor

The Planner decides WHAT, the Executor does HOW:

| ActionType | Delegation |
|-----------|-----------|
| LEARN / EXAM / REVIEW | `TeacherAgent.run_session(max_iterations=1)` |
| EVALUATE | `EvaluationObserver.generate_report()` |
| MAINTENANCE | Update goal progress from system metrics |
| NOOP | Do nothing |

### Hybrid Frequency

| Trigger | Condition | Description |
|---------|---------|------|
| Routine | Every 60 ticks (~1min) | Regular planning cycle |
| Event-driven | `exam_result` | Immediately after an exam |
| Event-driven | `alert` | Immediately on an alert |
| Event-driven | `user_command` | Immediately on a user command |
| Event-driven | `sandbox_promoted` | Immediately after a promote |

### Perception (new types)

PerceptionSource += `PLANNER`

| event_type | source | priority | ttl | dedup | Payload |
|-----------|--------|----------|-----|-------|---------|
| `planner_decision` | PLANNER | 0.5 | 300s | no | `plan_id`, `goal_id`, `action_type`, `goal_description` |
| `planner_cycle_complete` | PLANNER | 0.3 | 60s | yes | `tick`, `planned`, `guard_blocked`, `no_goals` |

### Persistence

| File | Format | Description |
|------|--------|------|
| `meta_data/planner_state.json` | JSON | Current state (cycles, last plan) |
| `meta_data/planner_decisions.jsonl` | JSONL (append) | Decision history |

### Cooldown

- Evaluation every 1h (no more often) - anti-oscillation on recommendations
- Planner Guard blocks planning learning when retention < 0.5

### REPL commands

| Command | Description |
|---------|------|
| `/plan` | The planner's last decision |
| `/plan status` | Cycles, plans, last eval |
| `/plan history [N]` | Decision history (default 10) |
| `/plan goals` | Ranking of goals by effective priority |

### File structure

```
agent_core/planner/
  __init__.py
  planner_model.py     # Plan, PlanStatus, ActionType, PlannerState
  planner_guard.py     # PlannerGuard.can_plan() - 5 gating rules
  goal_selector.py     # GoalSelector.select_goal() - aging + feasibility
  action_executor.py   # ActionExecutor.execute() - delegation
  planner_core.py      # PlannerCore - central ReAct loop

agent_core/modules/
  planner_module.py    # REPL /plan commands
```

### Modifications to existing files

| File | Change |
|------|--------|
| `agent_core/perception/event.py` | +PLANNER source, +2 event types |
| `agent_core/registry/shared_context.py` | +planner_core field |
| `agent_core/homeostasis/core.py` | Phase 10: planner with fallback to teacher |
| `agent_core/modules/homeostasis_module.py` | Wire PlannerCore |
| `main.py` | `registry.try_register(make_planner, "planner")` |

### New ADRs

| ADR | Decision |
|-----|---------|
| **ADR-013** | Planner v1 rule-based (zero LLM, deterministic, testable) |

### What it does NOT cover (v1)

- No LLM in the decision loop (rule-based only)
- No multi-step plans (Plan = single step)
- No planning trees/graphs
- No prioritization among parallel goals (sequential)
- No plan rollback (failed = log + next cycle)
- No auto-generation of goals (that is the GoalStore's domain)

---

## Decision 5: Tick Aggregator (ADR-009)

### Question

How should events be coordinated between modules?
- Option A: A full pub/sub event bus
- Option B: A lightweight tick aggregator (extension of the existing tick loop)

### Decision: Option B - Tick Aggregator

### Rationale

1. **The tick loop IS ALREADY an aggregator** - roughly 20 phases run sequentially, and all data passes through a single point in `HomeostasisCore._execute_tick()`
2. **Deterministic ordering** - the phases guarantee that a sensor reading is processed BEFORE the mode regulator. An event bus does not guarantee this.
3. **Threading simplicity** - ADR-002 says "threading, not asyncio". Pub/sub with threading = locks, race conditions. The tick loop = 1 thread + 1 deque for external events.
4. **5-6 sources, not hundreds** - an event bus pays off with dozens of producers. Maria has 6.
5. **1s latency is OK** - Maria learns from text files; it does not need sub-second reaction to events.
6. **HomeostasisEventBus already exists and is NOT used** - `agent_core/homeostasis/api.py` has pub/sub, but the tick loop does everything inline. The system naturally gravitates toward synchronous aggregation.

### Mechanism

Extend Phase 8 of the tick loop with aggregation:

```python
# In HomeostasisCore._execute_tick(), after Phase 7:

# PHASE 8: AGGREGATE
tick_summary = TickSummary(
    tick=self._tick_count,
    timestamp=time.time(),
    sensor_events=sensor_events,         # From Phase 1
    interpreted_state=interpreted_state,  # From Phase 2
    alerts=alerts,                        # From Phase 3
    mode=self.state.mode,                 # From Phase 4
    actions=actions,                      # From Phase 5-6
    health=self.state.health_score,       # From Phase 7
    external_events=self._drain_external_queue(),
)
self._perception_buffer.ingest_tick(tick_summary)
```

External events (from the REPL thread, teacher, etc.) are pushed via a thread-safe deque:

```python
# Thread-safe queue for events outside the tick loop
self._external_queue: deque = deque(maxlen=50)

def push_external_event(self, event: PerceptionEvent) -> None:
    """Called from the REPL thread, teacher thread, etc. Thread-safe (deque is thread-safe)."""
    self._external_queue.append(event)

def _drain_external_queue(self) -> List[PerceptionEvent]:
    """Called ONLY from the tick loop thread. Drains the queue."""
    events = []
    while self._external_queue:
        try:
            events.append(self._external_queue.popleft())
        except IndexError:
            break
    return events
```

### Comparison

| Aspect | Event Bus (A) | Tick Aggregator (B) |
|--------|---------------|---------------------|
| Ordering | Undefined (callback order) | Deterministic (phases) |
| Thread safety | Complex (locks on emit/subscribe) | Simple (1 deque) |
| Latency | ~0ms | Max 1s (next tick) |
| Code changes | New class + subscriber registration | 10-15 lines in `_execute_tick()` |
| Testing | Subscriber lifecycle | Existing tick-loop tests |
| Debugging | Every emit/callback to log | Print tick summary |

### HomeostasisEventBus - what about it?

It stays as-is (it has tests, it does not get in the way). If a future module needs push-style notifications (e.g. Web UI real-time alerts), it can subscribe. But the core perception flow goes through the tick aggregator, not the event bus.

---

## File Structure

### New files (to be created during implementation)

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
    action_executor.py          # ActionExecutor (delegation)
    planner_core.py             # PlannerCore (ReAct loop)
  world_model/
    __init__.py                 # WorldModel facade (K6)
    belief_model.py             # Belief (frozen), EntityType, BeliefType, BeliefSource
    belief_store.py             # BeliefStore (JSONL, MERGE, cap 2000)
    belief_builder.py           # Builds beliefs from JSONL (zero LLM)
    query.py                    # WorldModelQuery (topic confidence, gaps)
  autonomy/
    __init__.py                 # AutonomyPolicy facade + CheckResult (K7)
    action_class.py             # ActionClassification (FREE/GUARDED/RESTRICTED/FORBIDDEN)
    rate_limiter.py             # ActionRateLimiter (sliding window)
    policy_rules.py             # PolicyEngine + 3 built-in rules
    escalation.py               # EscalationHandler (JSONL log)
  deliberation/
    __init__.py                 # Deliberation facade (K8)
    strategy.py                 # Strategy + Step dataclasses
    strategy_templates.py       # 3 templates + TEMPLATE_REGISTRY
    deliberator.py              # Strategy selection and execution
    intent_tracker.py           # IntentTracker (JSONL intents)
  modules/
    evaluation_module.py        # REPL /evaluate command
    planner_module.py           # REPL /plan commands
```

### Data (new JSONL files)

```
meta_data/
  goals.jsonl                   # Goal records (append-only)
  evaluation_reports.jsonl      # Evaluation reports (append-only)
  planner_state.json            # Planner current state (K5)
  planner_decisions.jsonl       # Planner decision history (K5, append-only)
  beliefs.jsonl                 # Beliefs store (K6, MERGE semantics)
  autonomy_decisions.jsonl      # Autonomy escalation log (K7, append-only)
  deliberation_intents.jsonl    # Intent log (K8, append-only, bounded 500)
  sandbox/                      # Sandbox sessions directory
    sess_<uuid>/                # One session
      knowledge_index.jsonl
      maria_longterm_memory.jsonl
      exam_results.jsonl
```

---

## Integration

### Existing files to modify

| File | Change |
|------|--------|
| `agent_core/registry/shared_context.py` | New fields: `perception_buffer`, `goal_store`, `evaluation_observer`, `sandbox_manager`, `knowledge_analyzer`, `world_model`, `autonomy_policy`, `deliberation` |
| `agent_core/homeostasis/core.py` | Phase 8: tick aggregation + external queue. Periodic evaluation trigger. |
| `agent_core/modules/homeostasis_module.py` | Wiring new components in `init()` |
| `agent_core/modules/teacher_module.py` | Sandbox paths instead of production paths |
| `maria_core/sys/config.py` | `SANDBOX_DIR = BASE_DIR / "meta_data" / "sandbox"` |

### New ADRs

| ADR | Decision |
|-----|---------|
| **ADR-009** | Tick Aggregator instead of Event Bus (KISS, deterministic ordering) |
| **ADR-010** | Sandbox-first learning (all learning through the sandbox, promote as the only bridge) |
| **ADR-011** | Goals as data (goals are data objects with an audit trail, not hardcoded logic) |
| **ADR-012** | Evaluation READ-ONLY (extension of ADR-006 to agent evaluation) |
| **ADR-013** | Planner v1 rule-based (zero LLM, deterministic, testable) |

---

*Created: 2026-03-01*
*Approved by: M.A.R.I.A. Project*

Implementation milestones (test counts below are historical — the cumulative suite size at the time each layer was completed):
*Layer 1 (K1-K4): Implemented (~941 tests)*
*Layer 2 (K5 Planner): Implemented (~1023 tests)*
*Layer 3 (K6 World Model): Implemented (~1194 tests)*
*Layer 4 (K7 Autonomy Policy): Implemented (~1239 tests)*
*Layer 5 (K8 Deliberation): Implemented (~1288 tests)*

*Current test suite: 7,145 collected (`pytest agent_core/tests/ --collect-only -q`), CI green on `main`.*

---

## Contract 6: World Model / Belief System

### Problem

The system learns files and passes exams, but has no representation of "what it knows" or "how well it knows it".
There is no center of gravity for knowledge: the planner does not know which topics are weak and which are strong.
There is no feedback loop: a passed exam does not strengthen a topic's "confidence".

### Solution

A belief system as frozen dataclasses with JSONL persistence (MERGE semantics):

1. **Belief** - a unit of knowledge: entity + confidence + source
2. **BeliefStore** - a JSONL store with indexes (cap 2000, MERGE)
3. **BeliefBuilder** - builds beliefs from existing JSONL (READ-ONLY, zero LLM)
4. **WorldModelQuery** - query API (topic confidence, knowledge gaps)
5. **WorldModel** - facade

### Structure

```
agent_core/world_model/
    __init__.py          # WorldModel facade
    belief_model.py      # Belief (frozen), EntityType, BeliefType, BeliefSource
    belief_store.py      # BeliefStore (JSONL, MERGE, cap 2000)
    belief_builder.py    # Builds beliefs from knowledge_index + longterm_memory
    query.py             # WorldModelQuery - topic confidence, gaps, summaries
```

### Belief Model

```python
class EntityType(Enum):
    TOPIC, FILE, CONCEPT, MODULE, PERSON, PLACE

class BeliefType(Enum):
    FACT          # Confirmed (exam score >= 0.7)
    OBSERVATION   # Learned but unverified
    HYPOTHESIS    # Inferred

class BeliefSource(Enum):
    LEARNING, EXAM, MEMORY_FACT, SYSTEM, USER

@dataclass(frozen=True)
class Belief:
    belief_id: str
    entity: str               # What it's about (e.g. "quantum physics")
    entity_type: EntityType
    belief_type: BeliefType
    content: str              # Content
    confidence: float         # 0.0-1.0
    source: BeliefSource
    source_id: str            # Where from (e.g. file_id)
    tags: Tuple[str, ...]
    revision: int             # Version (incremented on revise)
    superseded_by: Optional[str]  # If superseded by a newer one
```

### BeliefStore

- JSONL persistence with MERGE semantics (last record per belief_id wins)
- Cap: **2000 beliefs** (weakest confidence pruned)
- Indexes: by_entity, by_entity_type, by_tag
- `revise()`: creates a new record, marks the old one as superseded

### BeliefBuilder (zero LLM)

- `build_topic_beliefs()` - from tags in `maria_longterm_memory.jsonl`, confidence = min(1.0, file_count/5)
- `build_file_beliefs()` - from `knowledge_index.jsonl`, type/confidence based on status + exam score
- `build_concept_beliefs()` - from key_points in longterm memory
- `update_from_exam()` - pass: +0.1 conf, OBSERVATION->FACT; fail: -0.15 conf
- Idempotent (safe to run repeatedly)

### Integration with PlannerCore

- `_gather_context()` -> `wm.query.get_world_summary()` + `get_knowledge_gaps()`
- `_auto_create_learning_goal()` -> prefers the topic with the lowest confidence
- `_finalize_plan()` -> after an exam `wm.process_exam_result()` + `wm.save()`
- `homeostasis_module.py` -> lazy build on init

### Limits

- Max 2000 beliefs (weakest pruned)
- JSONL bounded read (MERGE, last wins)
- Zero LLM, zero side effects (READ-ONLY sources)

---

## Contract 7: Autonomy Policy / Governance

### Problem

The Planner (K5) has no constraints: it can run fetch endlessly (1430 attempts),
execute actions in SLEEP mode, and does not react to repeated errors.
There is no autonomy policy: what is allowed, what requires approval, what is forbidden.

### Solution

A layer between PlannerGuard and ActionExecutor:

1. **ActionClassification** - 4 action classes (FREE/GUARDED/RESTRICTED/FORBIDDEN)
2. **ActionRateLimiter** - sliding-window rate limiting per ActionType
3. **PolicyEngine** - a chain of rules (first match wins)
4. **EscalationHandler** - decision logging + HITL placeholder
5. **AutonomyPolicy** - facade

### Structure

```
agent_core/autonomy/
    __init__.py          # AutonomyPolicy facade + CheckResult
    action_class.py      # ActionClassification enum + DEFAULT_ACTION_CLASSIFICATIONS
    rate_limiter.py      # ActionRateLimiter (sliding window, per action type)
    policy_rules.py      # PolicyEngine + 3 built-in rules + PolicyContext/PolicyResult
    escalation.py        # EscalationHandler (JSONL log, HITL placeholder)
```

### Action Classification

| Class | Actions | Constraints |
|-------|-------|-------------|
| **FREE** | learn, exam, review, evaluate, noop | No constraints |
| **GUARDED** | maintenance, fetch | Rate limit + logging |
| **RESTRICTED** | (future) | Requires conditions or HITL |
| **FORBIDDEN** | (future) | Never autonomously |

Unknown actions -> RESTRICTED (safe-by-default).

### Rate Limiter

- Sliding window: **3600s (1h)**
- `fetch`: max **5/h**
- `maintenance`: max **10/h**
- FREE actions: no limit

### Policy Rules (3 built-in)

| Rule | Condition | Decision |
|--------|---------|---------|
| `rule_consecutive_failure_breaker` | >= 3 consecutive failures of the same action | BLOCK |
| `rule_degraded_mode_restrict` | mode != ACTIVE + GUARDED+ action | BLOCK |
| `rule_restricted_actions_block` | FORBIDDEN action | BLOCK |
|                                  | RESTRICTED action | ESCALATE |

PolicyEngine: a chain of rules, first non-None result wins. If all None -> ALLOW.

### Integration with PlannerCore

```
PlannerCore._finalize_plan(plan):
    |
    +-> AutonomyPolicy.check(action_type, health, mode, ...)
    |       |
    |       +-> rate_limiter.check() (for GUARDED)
    |       +-> engine.evaluate(PolicyContext) -> PolicyResult
    |       +-> if blocked: escalation_handler.handle() -> log + blocked_result
    |       |
    |       +-> return CheckResult(allowed, decision, reasons)
    |
    +-> if not allowed: plan.status = FAILED, return
    +-> else: executor.execute(plan)
    +-> AutonomyPolicy.record_execution(action_type, success)
```

### Persistence

- `meta_data/autonomy_decisions.jsonl` - escalation and block log
- Rate limiter: in-memory (sliding window, resets on restart)
- Consecutive failures: in-memory (resets on restart)

### Limits

- fetch: 5/h, maintenance: 10/h
- 3 consecutive failures -> block
- GUARDED blocked in non-ACTIVE mode
- RESTRICTED/FORBIDDEN always blocked (until HITL v2)

### Effector Authority Levels (Phase 5, ADR-026)

A SECOND, independent axis of autonomy. The action class (above, FREE/GUARDED/RESTRICTED/FORBIDDEN)
says WHAT kind of action it is; the authority level says HOW FAR Maria may reach with the EFFECTOR
(OpenClaw). It applies ONLY to `action_type == "effector"` -- not to learning, exams,
FS_WRITE/outbox, or any other action. These two axes are often confused; the drift between
them allowed a silent divergence (live=BOUNDED vs docs=OBSERVE) -- hence this section.

| Level | Effector behavior (`rule_effector_authority`) |
|--------|--------------------------------------------------|
| **OBSERVE** (default) | sees tools, never calls -> BLOCK |
| **SUGGEST** | proposes, the operator gets a notification, no execution -> ESCALATE |
| **CONFIRM** | proposes, the operator approves (Telegram), then execution -> ESCALATE + queue |
| **BOUNDED** | autonomous for non-dangerous tools, confirm for dangerous ones |
| **UNRESTRICTED** | full autonomy -- BLOCKED (gated behind an explicit Phase 5 unlock) |

Changing the level: ONLY the operator, via `/authority <level>`. `MAX_ALLOWED_LEVEL = BOUNDED`
(clamped on load). State: `meta_data/authority_config.json` (runtime, gitignored).

**K7 reconciliation (2026-06-07):** the resting level = **OBSERVE** (consistent with the default
code and this document). The invariants that make OBSERVE sufficient:
- The autonomous planner **NEVER** emits an EFFECTOR action (lock:
  `TestAutonomousNeverEmitsEffector` in `test_planner.py`). The only effector plans are created by
  `_execute_approved_effector` -- the operator path `/do` -> `/efapprove`, which carries
  `already_approved=True` and bypasses the authority rule. Conclusion: dropping to OBSERVE does not
  break `/do`.
- Level promotion is only possible by the operator. `auto_promotion` PROPOSES (a PROPOSED goal,
  awaiting `/approve`), never applies on its own (`created_by="auto_promotion"` outside
  `AUTO_CONFIRM_SOURCES`); additionally it is **gated OFF** by the `AUTO_PROMOTION_ENABLED` flag
  (disabled by default) -- to be enabled deliberately only once autonomous effector rungs exist.
- Raising authority above OBSERVE is a **deliberate precondition** before
  connecting any autonomous effector path -- not a silent default.

(Historically the level was set manually to BOUNDED on 2026-05-14 during a 24h test and was not
touched for 24 days -- dormant, because there was no autonomous effector trigger.)

---

## Contract 8: Deliberation / Strategic Planning

### Problem

The Planner (K5) makes one-off decisions (single-step plans) every 60 ticks.
There is no multi-step planning: it cannot, for example, "first LEARN, then EXAM, and if it fails - REVIEW and EXAM again".
Each cycle is an independent decision with no strategy continuation.

### Solution

Multi-step strategies as data (ADR-011), rule-based (ADR-013):

1. **Strategy + Step** - a multi-step plan with fallbacks
2. **Strategy Templates** - ready-made templates for common flows
3. **Deliberator** - selects and runs strategies
4. **IntentTracker** - remembers why a strategy was chosen (JSONL)
5. **Deliberation** - facade tying it all together

### Structure

```
agent_core/deliberation/
    __init__.py              # Deliberation facade
    strategy.py              # Strategy + Step dataclasses
    strategy_templates.py    # 3 templates + TEMPLATE_REGISTRY
    deliberator.py           # Strategy selection and execution
    intent_tracker.py        # JSONL intent log
```

### Strategy Model

```python
@dataclass
class Step:
    step_id: str
    order: int                    # 0-based position
    action_type: str              # "learn", "exam", "review", "fetch", "evaluate"
    action_params: Dict
    status: StepStatus            # PENDING -> ACTIVE -> COMPLETED/FAILED/SKIPPED
    max_retries: int              # How many times to retry on fail (default 1)
    fallback_step_order: Optional[int]  # On fail, jump here (v1)

@dataclass
class Strategy:
    strategy_id: str
    goal_id: str
    template_name: str
    status: StrategyStatus        # ACTIVE -> COMPLETED/ABANDONED/PAUSED
    steps: List[Step]
    current_step_order: int       # Which step we're on
    intent: str                   # Why this strategy
```

### Templates (v1)

| Template | Flow | Trigger |
|----------|------|---------|
| `learn_topic` | LEARN -> EXAM -> (fail?) REVIEW -> EXAM | topic specified or default |
| `explore_new` | FETCH -> LEARN -> EXAM | new_files_available |
| `consolidate` | REVIEW -> EXAM -> EVALUATE | weak_topics detected |

### Integration with PlannerCore

```
PlannerCore._create_plan_for_goal(goal, context)
    |
    +-> _consult_deliberation(goal, context)
    |       |
    |       +-> Deliberation.get_next_action(goal_id, context)
    |       |       |
    |       |       +-> active strategy? -> return current step
    |       |       +-> no strategy? -> _select_strategy() from templates
    |       |       +-> no match? -> return None
    |       |
    |       +-> return action dict (action_type, params, strategy_id)
    |
    +-> if None -> fallback to _decide_learning_action() (old behavior)

PlannerCore._finalize_plan(plan)
    |
    +-> after execute -> Deliberation.report_step_outcome(strategy_id, "pass"/"fail")
```

### Backward compatible

- `deliberation=None` -> PlannerCore uses the old logic (_decide_learning_action)
- Deliberation is **advisory**: if there is no strategy, the planner works as before

### Persistence

- `meta_data/deliberation_intents.jsonl` - intent log (bounded 500 records)
- Strategies in-memory only (v1), created on-demand from templates

### Extensibility (v2 path)

| Element | v1 | v2 path |
|---------|-----|---------|
| Steps | Sequential list | DAG (step.next_on_success/fail) |
| Templates | Registry of functions | LLM-generated strategies |
| Conditions | Enum (PASS/FAIL/TIMEOUT) | Expressions ("confidence > 0.7") |
| Selection | Rule-based matching | LLM select_strategy() |
| Persistence | In-memory + intents JSONL | Full JSONL strategies |
| Integration | Advisory (optional) | Primary -> replacement |

### Limits

- Max 10 active strategies
- Max 5 strategies per goal (oldest trimmed)
- Max 3 abandoned attempts per template per goal (exhaust detection)
- IntentTracker: 500 records max (bounded read)

---

## Contract 9: Meta-Cognition (K9)

**Status:** IMPLEMENTED (2026-03-20)
**ADR:** ADR-013 (rule-based, zero LLM), ADR-011 (reflections as data)
**Tests:** 73 at implementation (test_meta_cognition.py)

### Purpose

A meta-cognitive system: it tracks assumptions before executing an action, compares the result with expectations, builds confidence per action/topic, and signals "I need a human".

"The system should know what it does not know."

### Structure

```
agent_core/meta_cognition/
    __init__.py              # MetaCognition facade (6 public methods)
    reflection_model.py      # Dataclasses: Reflection, Assumption, Lesson + 5 enums
    reflection_store.py      # JSONL persistence (meta_data/reflections.jsonl)
    confidence_tracker.py    # Confidence per action_type and per topic (exponential decay)
    reflector.py             # Builds assumptions, compares the result, detects patterns
```

### Enums

| Enum | Values |
|------|----------|
| AssumptionType | TOPIC_LEARNABLE, EXAM_WILL_PASS, FETCH_RELEVANT, RETENTION_STABLE, STRATEGY_EFFECTIVE |
| OutcomeMatch | MATCH (delta<=0.15), PARTIAL (0.15-0.4), MISMATCH (>0.4), UNKNOWN (fallback bool) |
| LessonType | WRONG_ASSUMPTION, UNEXPECTED_SUCCESS, SLOW_EXECUTION, PARTIAL_RESULT |
| Severity | LOW, MEDIUM, HIGH |
| NeedHumanReason | LOW_CONFIDENCE, REPEATED_FAILURES, ASSUMPTION_DRIFT |

### Dataclasses

**Assumption**: assumption_type, description, basis
**Lesson**: lesson_type, assumption_type (optional), message, severity
**Reflection**: a 2-phase record (mutable):
- Phase 1 (before exec): reflection_id, plan_id, step_id, action_type, goal_id, topic, assumptions[], expected_success, confidence_before, timestamp_started
- Phase 2 (after exec): actual_success, outcome_match, confidence_after, lessons[], timestamp_finished
- Properties: duration_ms, is_reflected

### Facade API (MetaCognition)

| Method | When | What it does |
|--------|-------|---------|
| `record_decision(plan_id, action_type, goal_id, topic, context)` | Before exec | Builds assumptions, records the expected outcome |
| `reflect(plan_id, success, result)` | After exec | Compares the result with expectations, extracts lessons |
| `get_decision_confidence(action_type, topic)` | Before a decision | 0.6*action + 0.4*topic (exponential decay) |
| `analyze_patterns()` | Periodically | Detects error patterns |
| `need_human()` | When needed | True when confidence is too low |
| `get_status()` | REPL/WebUI | Full status for display |

### Confidence Tracker

- Per action_type: success rate with exponential decay (DECAY=0.85)
- Per topic: success rate with exponential decay
- Combined: `0.6 * action_conf + 0.4 * topic_conf`
- DEFAULT_CONFIDENCE = 0.5 (when there is no history)
- LOW_CONFIDENCE_THRESHOLD = 0.3
- MIN_SAMPLES = 3 (min reflections for meaningful confidence)

### "Need Human" Signal

True when any of:
- Consecutive failures >= 3 for any action_type
- The same assumption_type wrong >= 3x in the last 20 reflections
- A topic with confidence < 0.3 and >= 3 attempts

V1: advisory (logged, visible in get_status), NOT blocking.

### Integration with PlannerCore

```
PlannerCore._finalize_plan(plan)
    |
    +-> BEFORE execute:  meta_cognition.record_decision(plan_id, action, topic, context)
    |                     -> builds assumptions from context (rule-based)
    |                     -> records a Reflection with expected_success + confidence_before
    |
    +-> executor.execute(plan)
    |
    +-> AFTER execute:   meta_cognition.reflect(plan_id, success, result)
    |                     -> outcome_match (MATCH/PARTIAL/MISMATCH)
    |                     -> lessons: [Lesson(WRONG_ASSUMPTION, ..., HIGH), ...]
    |                     -> updates confidence_after

PlannerCore._gather_context()
    |
    +-> meta_cognition.get_status() -> context["meta_confidence"]
```

### Wiring (homeostasis_module.py)

```python
from agent_core.meta_cognition import MetaCognition
meta_cognition = MetaCognition()
planner.set_meta_cognition(meta_cognition)
ctx.meta_cognition = meta_cognition
```

### Backward compatible

- `meta_cognition=None` -> PlannerCore works as before (zero impact)
- MetaCognition is **advisory**: it does not block planning

### Persistence

- `meta_data/reflections.jsonl` - append-only, rewrite on update
- MAX_RECORDS = 1000 (oldest trimmed)

### Limits

- Max 1000 reflections in memory
- Pattern analysis window: 20 most recent reflected records
- Consecutive failure threshold: 3
- Wrong assumption threshold: 3x in window

---

## Contract 10: Action Safety (K10)

**Status:** IMPLEMENTED (2026-03-20)
**ADR:** ADR-013 (rule-based, zero LLM), ADR-011 (data as structure)
**Tests:** 52 at implementation (test_action_safety.py)

### Purpose

Unified audit and effect validation for ALL action types. A generalization of K2 Sandbox to the whole system. Safe-by-default for new action types.

K7=WHETHER it is allowed, K9=WHETHER the assumption was correct, K10=WHETHER the state changed as expected.

### Structure

```
agent_core/action_safety/
    __init__.py              # ActionSafety facade
    safety_model.py          # ActionRecord, StateSnapshot, SafetyProfile + 4 enums
    safety_classifier.py     # ActionType -> SafetyProfile mapping
    audit_log.py             # JSONL persistence (meta_data/action_audit.jsonl)
    effect_validator.py      # Before/after state capture + comparison
```

### Enums

| Enum | Values |
|------|----------|
| SafetyMode | AUTO_COMMIT, AUDIT_ONLY, STAGED (future HITL) |
| Reversibility | REVERSIBLE, PARTIALLY_REVERSIBLE, IRREVERSIBLE |
| EffectType | NONE, KNOWLEDGE, FILESYSTEM, GOAL_STATE, EXTERNAL_API, DEVICE |
| ValidationResult | VALID, UNEXPECTED, SKIPPED |

### Safety Classification

| ActionType | SafetyMode | Reversibility | EffectType | Snapshots |
|-----------|------------|---------------|------------|-----------|
| learn/exam/review | AUTO_COMMIT | REVERSIBLE | KNOWLEDGE | No (K2) |
| evaluate/noop | AUTO_COMMIT | REVERSIBLE | NONE | No |
| maintenance | AUDIT_ONLY | REVERSIBLE | GOAL_STATE | Yes |
| fetch | AUDIT_ONLY | PARTIAL | FILESYSTEM | Yes |
| **unknown** | **STAGED** | **IRREVERSIBLE** | EXTERNAL_API | **Yes** |

### Facade API (ActionSafety)

| Method | When | What it does |
|--------|-------|---------|
| `before_action(plan_id, action_type, params, goal_id)` | Before exec | Classification + snapshot before. Returns SafetyMode |
| `after_action(plan_id, success, result, duration_ms)` | After exec | Snapshot after + validation + audit record |
| `is_staged(action_type)` | Quick check | True for unknown actions (v2 HITL) |
| `get_status()` | REPL/WebUI | Full status |

### Effect Validation (v1)

- **fetch:** input_file_count should not drop
- **maintenance:** goal_count should not explode (> +5)
- **any audited:** health_score drop > 0.3 = UNEXPECTED
- **learn/exam/noop:** SKIPPED (K2/K4 cover it)

### Integration with PlannerCore

```
PlannerCore._finalize_plan(plan)
    |
    +-> K7 check -> blocked? return
    +-> K9 record_decision
    +-> K10 before_action -> SafetyMode + snapshot before
    +-> executor.execute(plan)
    +-> K10 after_action -> snapshot after + validate
    +-> K7 record_execution
    +-> K8 report_step_outcome
    +-> K9 reflect
    +-> K6 update beliefs
```

### Wiring (homeostasis_module.py)

```python
from agent_core.action_safety import ActionSafety
action_safety = ActionSafety()
action_safety.set_homeostasis_core(core)
planner.set_action_safety(action_safety)
ctx.action_safety = action_safety
```

### Backward compatible

- `action_safety=None` -> PlannerCore works as before
- v1: STAGED logged but not blocking (placeholder for Smart Home/Code Agent)

### Persistence

- `meta_data/action_audit.jsonl` - append-only
- MAX_RECENT = 200 in-memory cache

### Limits

- Max 200 records in memory (bounded)
- Health drop threshold: 0.3
- Max goal increase per action: 5
