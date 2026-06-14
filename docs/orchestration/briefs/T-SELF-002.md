# Brief: T-SELF-002 — Self-Repair detector + Conductor task creation + master gate

## Context

M.A.R.I.A. is a local autonomous AI agent. This task lands the second
"systemic self-awareness" plank: when Maria detects a systemic problem
(model unavailable, dispatcher stuck, action failure storm), she creates
a self-repair task in the Conductor queue with `assignee=codex`,
`status=pending`, and notifies operator via Telegram. The task **does
NOT auto-dispatch** — it sits PENDING until operator explicitly approves
via `/approve_repair <task_id>`, OR auto-expires after 24 hours.

This is the **STOP-AT-PENDING gate** decision from session 2026-05-28:
Maria gets full self-diagnosis + task-creation autonomy, operator
retains veto before Codex actually runs.

**Critical scope correction from initial design:** the K12
`RecommendationCategory` enum (`knowledge_gap`, `retention_problem`,
`strategy_change`, `new_topic`) is **learning-oriented only**. It does
NOT model system failures. Therefore this task creates a **new module
`agent_core/self_repair/`** that detects system problems directly from
snapshots + events + bulletin, independent of K12. K12's
`RecommendationApplier` stays unchanged.

**Dependency:** This task depends on T-SELF-001 (SelfPerception module +
snapshots). Reason: the decision-threshold gate uses
`SelfPerception.is_fresh(300)` to refuse task creation when Maria's
self-state is stale. **Do NOT start T-SELF-002 until T-SELF-001 is
merged on `refactor/homeostasis`.**

Authoritative refs (read before starting):

- `CLAUDE.md` — project conventions, ADR list.
- `docs/orchestration/WORKER_BRIEF_TEMPLATE.md` — brief format.
- `docs/orchestration/briefs/T-SELF-001.md` — predecessor (snapshot
  schema, SelfPerception API, especially `is_fresh()` contract).
- `agent_core/self_perception/` — module from T-SELF-001 (read its
  `__init__.py` for the exported API).
- `agent_core/conductor/conductor.py` — `Conductor.add_task(task)` is
  the write API.
- `agent_core/conductor/task_model.py` — `Task` dataclass,
  `Assignee.CODEX`, `TaskStatus.PENDING`, `BUILDER_ASSIGNEES`,
  `create_task()` factory.
- `agent_core/conductor/task_queue.py` — TaskQueue persistence
  (`meta_data/market_task_queue.jsonl` is the DEFAULT path; THIS task
  uses a NEW path `meta_data/maria_task_queue.jsonl` — see §Locked
  design §2).
- `agent_core/bulletin/bulletin_model.py` — `BulletinEntry`, `EntryType`
  (NOT `BulletinCategory` — that name does not exist). Used as INPUT
  signal (read existing entries via `BulletinStore.get_open()` /
  `find_open(topic=..., entry_type=...)`) and as OUTPUT signal (post
  advisory when task created via `create_and_post`).
- `agent_core/bulletin/bulletin_store.py` (NOT `store.py`) —
  `BulletinStore.create_and_post(entry_type, topic, reason_code,
  summary, requested_by, goal_id=None, priority=0.5, metadata=None)`
  has built-in dedup on (topic, entry_type).
- `agent_core/modules/homeostasis_module.py` — Telegram command
  registration around line 3754-3762. Add `/approve_repair` and
  `/list_repairs` here, mirroring existing patterns.
- `agent_core/telegram/notifier.py` — notification format. Mirror the
  `/efapprove` pattern (line 341) for `/approve_repair`.
- `meta_data/homeostasis_events.jsonl` — event log (line-oriented JSON).
- `meta_data/action_audit.jsonl` — action outcomes log.
- `meta_data/cognitive_bulletin.jsonl` — bulletin entries.

## Goal

When Maria detects a systemic failure pattern, autonomously create a
PENDING repair Task in the Conductor queue (project=maria,
assignee=codex), notify operator via Telegram, and gate the dispatch
behind `/approve_repair <task_id>` until either approved or expired
(24h).

## Scope

- **Repository:** `~/maria/` (Maria main, branch `refactor/homeostasis`).
- **Dispatch mode:** inline on `refactor/homeostasis`.
- **In-scope new files:**
  - `agent_core/self_repair/__init__.py` — exports public API.
  - `agent_core/self_repair/detectors.py` — three detection rules,
    each a pure function over evidence sources.
  - `agent_core/self_repair/monitor.py` — `SystemFailureMonitor` class
    (orchestrates detectors, dedupe, threshold gate).
  - `agent_core/self_repair/task_creator.py` — `RepairTaskCreator`
    class (creates Conductor Task + bulletin advisory + TASK_BOARD echo).
  - `agent_core/self_repair/task_board_writer.py` — `TaskBoardWriter`
    class (atomic markdown append to `docs/orchestration/TASK_BOARD.md`).
  - `agent_core/self_repair/expiry.py` — `expire_stale_repair_tasks()`
    helper called from Conductor tick.
  - `agent_core/tests/test_self_repair_monitor.py` — detection tests.
  - `agent_core/tests/test_self_repair_task_creator.py` — task creation
    + TASK_BOARD echo tests.
  - `agent_core/tests/test_self_repair_expiry.py` — expiry tests.
  - `agent_core/tests/test_self_repair_telegram.py` —
    `/approve_repair` + `/list_repairs` command tests.
- **In-scope edits:**
  - `agent_core/homeostasis/core.py` — add Phase 19 tick (every 600
    ticks = 10 min) that runs `SystemFailureMonitor.scan_and_create()`;
    wire SystemFailureMonitor + RepairTaskCreator into init; add
    expiry sweep on every 120th tick (= 2 min) of the existing tick.
  - `agent_core/registry/shared_context.py` (NOT homeostasis/) — add
    `system_failure_monitor: Optional[Any] = None` and
    `repair_task_creator: Optional[Any] = None` fields.
  - `agent_core/modules/homeostasis_module.py` — register two new
    Telegram commands: `/approve_repair <task_id>` and
    `/list_repairs`. Insert near line 3762 with other commands.
  - `agent_core/conductor/conductor.py` — add new method
    `get_pending_repair_tasks(self) -> List[Task]` that lists tasks
    with `project="maria"` and `phase="self_repair"` and
    `status=PENDING`. (Method only, no behavioral change to existing
    methods.)
- **Out-of-scope (do NOT touch):**
  - `agent_core/self_analysis/recommendation_applier.py` — leave K12
    alone. K12 stays learning-only.
  - `agent_core/conductor/dispatcher.py` — that's T-SELF-003.
  - `agent_core/self_perception/` — already done in T-SELF-001.
  - Web UI.

## Locked design decisions (do NOT relitigate)

1. **Detection rules: exactly THREE, hardcoded, whitelist-only.**
   Adding new rules requires a new task; this brief covers exactly
   these three. The whitelist guarantees that K12 false positives or
   noisy bulletin signals cannot trigger arbitrary self-repair tasks.

   **Rule 1: MODEL_UNAVAILABLE**
   - Evidence source: last 3 self-state snapshots
     (`meta_data/self_state_snapshots.jsonl` tail).
   - Trigger condition: a named external service (NIM, Ollama, OpenClaw)
     was `available` in snapshot[-3] AND is `unavailable` (or `depleted`
     for NIM) in BOTH snapshot[-2] AND snapshot[-1].
   - Cooldown: do NOT re-trigger for the same service within 4 hours
     (look back through existing repair tasks with matching `repair_kind`
     in their artifacts). 4h matches the K11 ADOPT cooldown convention.

   **Rule 2: DISPATCHER_STUCK**
   - Evidence source: Conductor task queue
     (`Conductor.list_tasks(status=TaskStatus.IN_PROGRESS)`).
   - Trigger condition: at least one task has been IN_PROGRESS
     (`updated_at` not refreshed) for more than 60 minutes AND the
     task's project is not "maria" (only dispatcher for OTHER projects
     can be stuck; a maria-project task being slow is normal — this
     would be self-referential).
   - Cooldown: 4 hours per project.

   **Rule 3: ACTION_FAILURE_STORM**
   - Evidence source: `meta_data/action_audit.jsonl` last hour.
   - Trigger condition: at least 10 actions in last hour AND
     `failures / total >= 0.30` (≥30% failure rate).
   - Cooldown: 4 hours.

2. **Conductor queue path: `meta_data/maria_task_queue.jsonl`** (new,
   separate from `market_task_queue.jsonl`). Reason: `TaskQueue` uses
   one file per project per the comment in its `_DEFAULT_PATH` docs.
   The RepairTaskCreator constructs a TaskQueue with `path=Path(
   "meta_data/maria_task_queue.jsonl")` and a Conductor wrapping it.
   The HomeostasisCore wires this as `self._maria_conductor`,
   separate from the existing market_agent conductor (which keeps
   its own queue file).

3. **Task shape** when RepairTaskCreator creates a repair Task:
   ```python
   Task(
       task_id=f"cdt-{uuid.uuid4().hex[:12]}",  # from create_task() factory
       project="maria",
       phase="self_repair",
       title=f"Self-repair: {detector_summary}",  # ≤80 chars
       description=<full brief generated, ~50-100 lines, see §6>,
       status=TaskStatus.PENDING,
       priority=0.8,  # higher than typical 0.5 to signal urgency
       assignee=Assignee.CODEX,
       dependencies=[],
       artifacts={
           "repair_kind": "model_unavailable" | "dispatcher_stuck" | "action_failure_storm",
           "evidence_summary": <dict from detector>,
           "created_by": "maria_self_diagnosis",
           "snapshot_id": <id of fresh snapshot>,
           "workspace_path": "/home/maria/maria",  # for T-SELF-003 dispatcher
           "approval_required": True,  # gate flag — dispatcher refuses to pick this up
           "expires_at": <unix epoch, created_at + 86400>,
       },
   )
   ```

4. **Decision threshold gate** (RepairTaskCreator refuses to create a
   task unless ALL are true):
   - `SelfPerception.is_fresh(max_age_seconds=300)` returns True (fresh
     snapshot ≤5 min old).
   - Latest snapshot has `mode in ("ACTIVE", "REDUCED")` — not SLEEP,
     not SURVIVAL. (System is healthy enough to self-repair; SLEEP/SURVIVAL
     mean focus elsewhere.)
   - Latest snapshot has `external_services["NVIDIA NIM API"].status ==
     "available"` (Codex dispatch will need NIM/local LLM; if NIM is
     down AND we're trying to schedule a NIM-related repair, that's a
     deadlock — refuse).
   - No existing PENDING repair task with the same `repair_kind` and
     created within the last 4 hours.

   On refusal, log to `agent_core.self_repair` logger at INFO level:
   `"[SelfRepair] refused task creation: reason={...}"`. Do NOT create
   a task and do NOT notify operator.

5. **TASK_BOARD.md atomic echo.** When a repair task is created, also
   append an entry to `docs/orchestration/TASK_BOARD.md`. Goal:
   operator visibility in the file they already check. Format:

   ```
   ### T-REPAIR-<short-id> — Self-repair: <title> [PENDING — operator gate]
   - **Status:** pending (created by maria_self_diagnosis 2026-XX-XX HH:MM Berlin)
   - **Owner:** codex (autonomous after /approve_repair)
   - **Repair kind:** <repair_kind>
   - **Conductor task_id:** <cdt-...>
   - **Evidence:** <one-line summary from detector>
   - **Expires:** <ISO timestamp 24h from now>
   - **Approve:** `/approve_repair <cdt-...>` (Telegram)
   ```

   **Insertion point:** find the literal line `## Open tasks` in the
   file; insert the new entry as a new section IMMEDIATELY after that
   header and before the next `###` heading. If `## Open tasks` is not
   found, log a warning and skip the TASK_BOARD echo (do NOT fail task
   creation — Conductor queue is the source of truth, TASK_BOARD is
   sekundary).

   **Atomic write:** read file, prepare new content, write to
   `TASK_BOARD.md.tmp`, `os.replace()` to final path. Use
   `threading.Lock()` shared across TaskBoardWriter instances (class-
   level lock since there's only one writer per process).

   `T-REPAIR-<short-id>` uses the LAST 4 chars of the Conductor task_id
   uuid — short enough to type, long enough to disambiguate. (Full
   task_id is on the next line for unambiguous reference.)

6. **Task description generation** (the ~50-100 line "brief" that
   becomes Codex's instruction body when dispatched). Template:

   ```
   # Self-repair: <title>

   ## Context
   This task was created autonomously by Maria's SystemFailureMonitor
   after detecting a systemic problem in the running system. Maria is
   the local autonomous AI agent project at /home/maria/maria. You
   are running on Maria's behalf via the Conductor dispatcher.

   ## Detection evidence
   <pretty-printed JSON of detector's evidence_summary>

   ## Repair kind: <repair_kind>

   ### If repair_kind == "model_unavailable":
   The named service has been unavailable for at least 2 consecutive
   30-min snapshots. Determine root cause: is it network, configuration,
   credentials, or the upstream service itself? Files to investigate:
   - For NIM: `agent_core/llm/nim_client.py`, `.env` NVIDIA_NIM_*
     variables, last 100 lines of `meta_data/llm_tape.jsonl`.
   - For Ollama: `systemctl status ollama` (read-only diagnostic),
     `agent_core/llm/llm_manager.py`.
   - For OpenClaw: `agent_core/effector/openclaw_client.py`,
     `pgrep openclaw_gateway`.
   Output: a markdown diagnostic to stdout AND a code fix if possible.
   If no fix possible (e.g. upstream API outage), produce diagnostic
   + recommended operator action only — do NOT make speculative changes.

   ### If repair_kind == "dispatcher_stuck":
   A Conductor task has been IN_PROGRESS for >60 minutes. Diagnose:
   inspect `meta_data/<project>_task_queue.jsonl` for the stuck task;
   check logs for the assignee; determine whether to mark BLOCKED,
   re-PENDING, or extend the timeout. Files:
   - `agent_core/conductor/dispatcher.py` (dispatch logic)
   - `agent_core/conductor/conductor.py` (lifecycle methods)
   Output: code change OR mark the task appropriately via conductor
   lifecycle methods + commit.

   ### If repair_kind == "action_failure_storm":
   ≥30% of actions in the last hour have failed. Read
   `meta_data/action_audit.jsonl` (last hour), group failures by
   `action_type` + `goal_id`, identify the dominant failure pattern.
   Files to investigate (depend on dominant action_type — let evidence
   guide):
   - learn → `agent_core/teacher/learning_agent.py`
   - fetch → `agent_core/web_source/`
   - exam → `agent_core/teacher/exam_agent.py`
   Output: diagnostic + targeted fix.

   ## Constraints
   - Branch: `refactor/homeostasis` inline.
   - Conventions: see `CLAUDE.md` and `docs/orchestration/WORKER_BRIEF_TEMPLATE.md`.
   - Tests: full `agent_core/tests/` must still pass.
   - Auto-commit safeguard: do NOT commit unrelated work. Pre-dispatch
     workspace was verified clean.

   ## Done criteria
   - Diagnostic written to stdout in the Codex response.
   - If code change made: tests still pass, commit on
     `refactor/homeostasis`.
   - If no fix possible: explain why + recommend operator action.
   ```

7. **Bulletin advisory** posted when a task is created. Call:
   ```python
   from agent_core.bulletin.bulletin_store import BulletinStore
   from agent_core.bulletin.bulletin_model import EntryType

   bulletin_store.create_and_post(
       entry_type=EntryType.IMPROVEMENT,  # closest semantic fit; no "advisory" enum value exists
       topic=f"self_repair_{repair_kind}",
       reason_code=f"self_repair_{repair_kind}",
       summary=f"Self-repair created: {short_description}",
       requested_by="self_repair_monitor",
       priority=0.7,
       metadata={
           "task_id": <cdt-...>,
           "repair_kind": <repair_kind>,
           "evidence_summary": <evidence dict>,
       },
   )
   ```
   The entry's lifecycle status starts as `EntryStatus.OPEN` (default
   from BulletinStore); it transitions to `RESOLVED` when the linked
   task transitions to DONE/CANCELLED via the expiry hook (§8). Note:
   `create_and_post` has built-in dedup on (topic, entry_type) so a
   second repair of the same kind within the same scan returns the
   existing entry instead of creating a duplicate.

8. **Auto-expiry: 24 hours.** `expire_stale_repair_tasks()` is called
   from `Conductor.tick()` (master will wire — actually,
   `HomeostasisCore.tick()` Phase 17 already calls
   `self._conductor.tick()`, but `Conductor.tick()` is read-only by
   contract. So add the expiry call as a SEPARATE call in
   `HomeostasisCore.tick()`, after the existing conductor block, every
   120 ticks = 2 min cadence).

   The expiry function:
   - Lists all PENDING tasks with `project="maria"`, `phase="self_repair"`.
   - For each, checks `artifacts["expires_at"]` against `time.time()`.
   - If expired, marks the task CANCELLED with notes
     `"expired_no_response after 24h"`.
   - Closes the linked bulletin advisory (`metadata.task_id` match) by
     setting `status="closed"` + `metadata.close_reason="task_expired"`.
   - Sends ONE Telegram notification per expiry batch (combine multiple
     expirations into one message if they fire in the same sweep).

9. **Telegram commands** added inside the existing
   `_register_telegram_commands(bridge, ctx)` function at line 1994.
   That function defines all `_cmd_*` nested handlers and ends with a
   block of `bridge.register_command("name", _cmd_name)` calls around
   line 3754-3771. Add the new handlers and register them in that
   same function. **Handler signature is `(args: str) -> str`** —
   `args` is the rest of the message after the command word, the
   return value is the response text. Example existing pattern from
   `_cmd_status(args)` in that function:

   - **`/list_repairs`** — list all PENDING repair tasks. Format:
     ```
     Otwarte self-repair tasks (N):
       cdt-abcd1234 | model_unavailable | NIM API | 2h temu | wygasnie 22:00
       cdt-efgh5678 | dispatcher_stuck | market_agent | 30min temu | wygasnie 02:00
     Zatwierdz: /approve_repair <task_id>
     ```
     If N=0: `"Brak otwartych self-repair tasks."`.

   - **`/approve_repair <task_id>`** — flip the gate flag on a single
     task. Implementation:
     1. Look up task via `self._maria_conductor.list_tasks(...)`,
        match by `task_id` (full or last-4-prefix).
     2. If not found OR not PENDING OR not project="maria"+phase="self_repair":
        reply `"Nie znaleziono PENDING self-repair task: <id>"`.
     3. Otherwise, update task `artifacts["approval_required"] = False`
        via `Conductor.add_task(updated_task)` (queue uses MERGE
        semantics on task_id — last write wins).
     4. Reply: `"Zatwierdzono <task_id>. Dispatcher podejmie task na
        nastepnym ticku (do 3 min)."`
     5. Send notification to the chat: `"[Self-repair] Task <task_id>
        approved by operator → eligible for dispatch."`.

10. **The dispatcher (T-SELF-003) will check `approval_required`
    before dispatching** — that's a T-SELF-003 obligation, not this
    task's. But this task's RepairTaskCreator MUST set
    `artifacts["approval_required"] = True` so the future dispatcher
    has the flag to honor. Document this clearly in the
    `RepairTaskCreator` docstring.

## Public API

```python
# agent_core/self_repair/__init__.py
from .monitor import SystemFailureMonitor
from .task_creator import RepairTaskCreator
from .task_board_writer import TaskBoardWriter
from .expiry import expire_stale_repair_tasks
from .detectors import RepairCandidate

__all__ = [
    "SystemFailureMonitor",
    "RepairTaskCreator",
    "TaskBoardWriter",
    "expire_stale_repair_tasks",
    "RepairCandidate",
]


# detectors.py
@dataclass(frozen=True)
class RepairCandidate:
    repair_kind: str  # "model_unavailable" | "dispatcher_stuck" | "action_failure_storm"
    summary: str  # short, for title
    evidence_summary: Dict[str, Any]  # detector-specific
    detected_at: float

def detect_model_unavailable(snapshot_store, cooldown_lookup) -> List[RepairCandidate]:
    ...

def detect_dispatcher_stuck(conductor, cooldown_lookup) -> List[RepairCandidate]:
    ...

def detect_action_failure_storm(audit_path: Path, cooldown_lookup) -> List[RepairCandidate]:
    ...


# monitor.py
class SystemFailureMonitor:
    def __init__(self, self_perception, conductor, audit_path, repair_task_creator):
        ...

    def scan_and_create(self) -> List[str]:
        """Run detectors, gate, create tasks. Returns list of task_ids
        created. Empty list = no candidates or gate refused."""
        ...


# task_creator.py
class RepairTaskCreator:
    def __init__(self, conductor, bulletin_store, task_board_writer, notifier):
        ...

    def create(self, candidate: RepairCandidate, snapshot_id: str) -> Optional[str]:
        """Create task + bulletin + TASK_BOARD echo + notification.
        Returns task_id on success, None on failure or gate-refused."""
        ...


# task_board_writer.py
class TaskBoardWriter:
    _lock = threading.Lock()  # class-level

    def __init__(self, board_path: Path = Path("docs/orchestration/TASK_BOARD.md")):
        ...

    def append_repair_entry(self, task_id: str, title: str,
                            repair_kind: str, evidence_summary: dict,
                            expires_at: float) -> bool:
        """Atomic append. Returns True on success, False on missing
        marker."""
        ...


# expiry.py
def expire_stale_repair_tasks(conductor, bulletin_store, notifier, now=None) -> List[str]:
    """Cancel any PENDING self-repair tasks past expires_at. Closes
    bulletin advisories. Sends one combined Telegram notification.
    Returns list of expired task_ids."""
    ...
```

## Phase 19 tick + Conductor expiry integration

In `agent_core/homeostasis/core.py`:

```python
# Module top:
SELF_REPAIR_SCAN_INTERVAL = 600   # ticks (~10 min)
SELF_REPAIR_EXPIRY_INTERVAL = 120  # ticks (~2 min)

# Inside tick(), after Phase 18 (self-perception) block:

# Phase 19: System failure detection + repair task creation
if self._system_failure_monitor and self._tick_count % SELF_REPAIR_SCAN_INTERVAL == 0:
    try:
        created = self._system_failure_monitor.scan_and_create()
        if created:
            logger.info(f"[Phase19] self-repair tasks created: {created}")
    except Exception as e:
        logger.warning(f"[Phase19] self-repair scan error: {e}")

# Expiry sweep (cheaper, more frequent)
if self._maria_conductor and self._tick_count % SELF_REPAIR_EXPIRY_INTERVAL == 0:
    try:
        from agent_core.self_repair import expire_stale_repair_tasks
        expired = expire_stale_repair_tasks(
            self._maria_conductor,
            self._bulletin_store,
            self._telegram_notifier,
        )
        if expired:
            logger.info(f"[Phase19] expired self-repair tasks: {expired}")
    except Exception as e:
        logger.warning(f"[Phase19] expiry sweep error: {e}")
```

## Definition of Done

- `agent_core/self_repair/` module exists with 6 files exporting public
  API per §Public API.
- `SystemFailureMonitor.scan_and_create()` runs all 3 detectors,
  applies threshold gate, creates tasks for surviving candidates.
- All 3 detection rules work per §1 spec (testable with synthetic
  evidence in tests).
- 4-hour cooldown per (repair_kind, optional_subject) is honored —
  re-running scan within cooldown does NOT create duplicates.
- Threshold gate refuses task creation when ANY of §4 conditions fail;
  logs INFO-level reason.
- Repair Task lands in `meta_data/maria_task_queue.jsonl` with
  `assignee=codex`, `status=pending`, `artifacts["approval_required"]=True`,
  `artifacts["expires_at"]` set to created+86400.
- TASK_BOARD.md gets the new entry inserted right after `## Open tasks`
  header. Atomic write — no partial writes possible.
- Bulletin advisory posted with `requested_by="self_repair_monitor"`,
  metadata linking to task_id.
- `/list_repairs` Telegram cmd lists all PENDING self_repair tasks in
  the format from §9.
- `/approve_repair <task_id>` flips `artifacts["approval_required"]`
  to False; partial-prefix match (last 4 chars) works.
- Phase 19 tick fires every 600 ticks; expiry sweep every 120 ticks.
- `expire_stale_repair_tasks` cancels expired tasks (>24h PENDING),
  closes their bulletin advisories, sends one combined Telegram notif.
- All new tests pass (see §Tests).
- Full `agent_core/tests/` suite still passes (baseline 5192 + T-SELF-001
  additions — should be ~5199 after T-SELF-001 lands).
- `ruff check agent_core/self_repair agent_core/tests/test_self_repair_*.py`
  clean.
- `mypy agent_core/self_repair` clean.

## Tests

Required new files (≥4 test modules):

### `test_self_repair_monitor.py` — Detection rules (≥6 tests)
1. **test_detect_model_unavailable_positive** — 3 mock snapshots,
   service flips available→unavailable across last 2. Detector
   returns one candidate.
2. **test_detect_model_unavailable_cooldown** — same evidence, but a
   matching PENDING repair task already exists with `repair_kind=
   "model_unavailable"` created <4h ago. Detector returns empty.
3. **test_detect_dispatcher_stuck_positive** — Conductor stub returns
   one IN_PROGRESS task with `updated_at` 65 min ago and
   `project="market_agent"`. Detector returns one candidate.
4. **test_detect_dispatcher_stuck_skips_maria** — same as above but
   `project="maria"`. Detector returns empty (self-referential
   guard).
5. **test_detect_action_failure_storm_positive** — mock audit file
   with 12 actions in last hour, 5 failures. 5/12=41% ≥30% threshold.
   Detector returns one candidate.
6. **test_detect_action_failure_storm_insufficient_sample** — mock
   audit with 8 actions, 6 failures (75% failure rate but only 8
   actions, below 10-action minimum). Detector returns empty.

### `test_self_repair_task_creator.py` — Task creation + threshold gate (≥7 tests)
1. **test_create_task_happy_path** — fresh snapshot, mode=ACTIVE,
   NIM available, no existing same-kind task in cooldown. Creates
   task, posts bulletin, calls TaskBoardWriter, notifies.
2. **test_gate_refuses_stale_snapshot** — `is_fresh(300)` returns
   False. RepairTaskCreator returns None, no task in queue, no
   bulletin entry, no notification.
3. **test_gate_refuses_survival_mode** — snapshot has mode=SURVIVAL.
   No task created.
4. **test_gate_refuses_nim_down_for_nim_repair** — candidate is
   `model_unavailable: NIM`, snapshot says NIM unavailable (deadlock
   case). No task created.
5. **test_gate_refuses_cooldown** — existing PENDING task with
   matching repair_kind exists. No new task.
6. **test_task_artifacts_complete** — created task has
   `repair_kind`, `evidence_summary`, `created_by="maria_self_diagnosis"`,
   `snapshot_id`, `workspace_path="/home/maria/maria"`,
   `approval_required=True`, `expires_at` set to created+86400.
7. **test_task_board_echo** — TaskBoardWriter.append called with
   matching fields.

### `test_self_repair_expiry.py` — Expiry sweep (≥4 tests)
1. **test_expiry_cancels_old_tasks** — task with expires_at 1h ago is
   marked CANCELLED with notes containing "expired_no_response".
2. **test_expiry_skips_fresh_tasks** — task created 1h ago (23h until
   expiry) is untouched.
3. **test_expiry_closes_bulletin** — when task expires, the linked
   bulletin advisory's status becomes "closed".
4. **test_expiry_combined_notification** — when 3 tasks expire in
   one sweep, exactly ONE Telegram message is sent listing all 3.

### `test_self_repair_telegram.py` — Commands (≥4 tests)
1. **test_list_repairs_empty** — no PENDING tasks → "Brak otwartych
   self-repair tasks."
2. **test_list_repairs_shows_pending** — 2 PENDING tasks → formatted
   output containing both task_ids.
3. **test_approve_repair_flips_flag** — `/approve_repair cdt-abc123`
   for an existing PENDING task → task's
   `artifacts["approval_required"]` becomes False.
4. **test_approve_repair_unknown_id** — `/approve_repair cdt-xxx` for
   non-existent task → "Nie znaleziono PENDING self-repair task".

Test command:
```bash
cd /home/maria/maria && python -m pytest agent_core/tests/test_self_repair_*.py -v
```

Full suite:
```bash
cd /home/maria/maria && python -m pytest agent_core/tests/ -q
```

## Non-goals

- Do NOT modify K12 (`recommendation_applier.py`, `recommendation_model.py`,
  `state_collector.py`, `external_analyzer.py`). K12 stays
  learning-oriented.
- Do NOT change `Conductor.tick()` behavior — it stays read-only;
  expiry sweep is called separately from HomeostasisCore.tick().
- Do NOT add a "self-repair-dispatcher" — the existing
  `ConductorDispatcher` handles dispatch in T-SELF-003.
- Do NOT add Web UI panel.
- Do NOT add config-file knobs — all thresholds are constants in code.
- Do NOT add more detection rules. Three is the spec.
- Do NOT add auto-approve logic. Even if Maria is highly confident,
  operator gate is the spec.

## Conventions

- Python 3.10+.
- Type hints required.
- English docstrings; comments may be Polish.
- No emojis (ADR-005).
- No backwards-compatibility shims.
- Do not push to GitHub.

## Constraints from this task in particular

- **Performance:** Phase 19 scan must complete in <500ms typical. The
  bulk is the action_audit.jsonl read (last hour ≈ ~100-500 lines).
  If it ever exceeds 500ms, log a warning — but do NOT add async
  machinery; the slow path is acceptable as long as it's known.
- **File locking:** TaskBoardWriter MUST use a `threading.Lock`
  (class-level singleton) to prevent corrupted writes when Phase 19
  tick and another future code path both write to TASK_BOARD.md.
- **No silent failures:** every refusal (cooldown, threshold gate,
  marker not found) logs at INFO; every exception logs at WARNING
  with full traceback (`logger.warning(..., exc_info=True)`).
- **Telegram notifier is OPTIONAL**: if `notifier is None`, skip
  notifications, do NOT fail task creation. (Real prod has notifier
  wired; tests may pass None.)

## If you encounter ambiguity

- Stop. Output a numbered list of the ambiguities.
- Do NOT guess. Master will rewrite the brief.
- Especially: if T-SELF-001's `SelfPerception.is_fresh()` API differs
  from `is_fresh(max_age_seconds=300) -> bool`, or if the snapshot
  schema differs from §Snapshot schema in T-SELF-001 — surface it.

## Output

- Inline commits on `refactor/homeostasis`.
- Preferred 1 commit per file or 2-3 logical commits:
  1. `feat(self-repair): detectors + monitor module`
  2. `feat(self-repair): task creator + TASK_BOARD echo + expiry`
  3. `feat(telegram): /approve_repair + /list_repairs commands`
  4. `feat(homeostasis): Phase 19 tick wiring`
  5. `test(self-repair): full test suite (≥21 tests across 4 files)`
- When done, output short summary: files changed, test count, any
  surprises.

## Authoritative references (must read before starting)

- `CLAUDE.md`
- `docs/orchestration/WORKER_BRIEF_TEMPLATE.md`
- `docs/orchestration/briefs/T-SELF-001.md` (snapshot schema +
  SelfPerception API)
- `agent_core/conductor/conductor.py` (`add_task`, `list_tasks`,
  `get_pending_repair_tasks` new)
- `agent_core/conductor/task_model.py` (`Task`, `Assignee.CODEX`,
  `TaskStatus.PENDING`)
- `agent_core/conductor/task_queue.py` (path conventions)
- `agent_core/bulletin/bulletin_model.py` (`BulletinEntry`, `EntryType`,
  `EntryStatus`)
- `agent_core/bulletin/bulletin_store.py` (`create_and_post` signature,
  `update_status`, `find_open`, `get_open`)
- `agent_core/modules/homeostasis_module.py:1994`
  (`_register_telegram_commands(bridge, ctx)` — define handlers as
  nested functions `def _cmd_X(args): return "..."`; signature
  `(args: str) -> str`, no update/context/reply_text)
- `agent_core/telegram/notifier.py` (notification format, especially
  the `/efapprove` echo at line 341)
- `agent_core/telegram/__init__.py` (`TelegramBridge` class — NOT
  `telegram_bridge.py`)
