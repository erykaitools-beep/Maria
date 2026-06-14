# Brief: T-SELF-001 — Self-Perception module + Phase 18 tick + /selfstatus

## Context

M.A.R.I.A. is a local autonomous AI agent (Mini PC, IP <MINI_PC_LAN_IP>). This
task lands the first "systemic self-awareness" plank: periodic snapshots of
Maria's own capabilities, limitations, and tool inventory, exposed via Telegram
`/selfstatus`. Foundation for T-SELF-002 (K12 → self-repair bridge) which
needs a snapshot freshness check as a decision threshold.

Three reader modules already exist and are wired into `SharedContext` — this
task only orchestrates them; it does **not** rewrite or replace them. The
core insight: Maria has the introspection primitives but no loop that
periodically asks "what do I have right now?" Without that loop, the
self-model is queried only on `/v3 self` operator command — never on Maria's
own initiative.

Authoritative refs (read before starting):

- `CLAUDE.md` — project conventions, ADR list, file map.
- `docs/orchestration/WORKER_BRIEF_TEMPLATE.md` — brief format conventions.
- `agent_core/orchestrator/self_model_facade.py` — `UserFacingSelfModel`
  class. Exposes `get_status()`, `get_identity()`, `get_capabilities()`,
  `get_current_mode()`, `get_limitations()`. **Already wired in
  SharedContext as `ctx.user_facing_self_model`** if present — read
  defensively via `getattr`.
- `agent_core/orchestrator/limitation_reporter.py` — `LimitationReporter`
  class. `get_report()` returns dict with `limitations` list (each entry
  has `category`/`severity`/`description`/`suggestion`), `blocked_actions`,
  `mode`. **Construct fresh per snapshot**: `LimitationReporter(ctx)`.
- `agent_core/orchestrator/tool_registry.py` — `ToolCapabilityRegistry`.
  `get_summary()` returns dict with capability counts + external services
  list (NIM, Ollama, OpenClaw, Codex, Telegram). **Construct fresh per
  snapshot**: `ToolCapabilityRegistry(ctx)`.
- `agent_core/homeostasis/core.py` — primary tick loop. Phase 17 conductor
  (line ~617) is the pattern to mirror for Phase 18. **Tick interval is
  1 second**; existing Phase 17 fires at `_tick_count % 180 == 0` (every
  3 minutes).
- `agent_core/telegram/__init__.py` — defines the `TelegramBridge` class
  (NOT `telegram_bridge.py` — there is no such file). The class is
  imported as `from agent_core.telegram import TelegramBridge`.
- `agent_core/modules/homeostasis_module.py` line 1994 onward —
  `_register_telegram_commands(bridge, ctx)` function. All Telegram cmds
  are added here, NOT in the bridge file. **Verify before adding** that
  `selfstatus` is not already taken (grep in this function).
- `agent_core/bulletin/bulletin_store.py` — `BulletinStore.create_and_post(
  entry_type, topic, reason_code, summary, requested_by, goal_id=None,
  priority=0.5, metadata=None)` for posting bulletin entries. Use
  `entry_type=EntryType.IMPROVEMENT` (from
  `agent_core/bulletin/bulletin_model.py`). Note: BulletinStore has
  built-in dedup — if an open entry for the same `topic` + `entry_type`
  already exists, `create_and_post` returns the existing entry instead
  of creating a duplicate. This means cold-start bulletin (§6) is safe
  to call on every Phase 18 tick if no diff exists — dedup handles it.

## Goal

Periodically capture and persist Maria's current self-state (identity, mode,
capabilities, limitations, external services), surface changes as bulletin
entries, and expose the latest snapshot via Telegram `/selfstatus`.

## Scope

- **Repository:** `~/maria/` (Maria main, branch `refactor/homeostasis`).
- **Dispatch mode:** inline on `refactor/homeostasis` (per TASK_BOARD note
  2026-05-16); no agent-branch worktree needed.
- **In-scope new files:**
  - `agent_core/self_perception/__init__.py` — exports `SelfPerception` and
    `SnapshotStore`.
  - `agent_core/self_perception/perception.py` — `SelfPerception` class.
  - `agent_core/self_perception/snapshot_store.py` — JSONL persistence +
    last-snapshot retrieval.
  - `agent_core/tests/test_self_perception.py` — full test suite.
- **In-scope edits:**
  - `agent_core/homeostasis/core.py` — add Phase 18 tick (snapshot every
    1800 ticks = 30 min); wire `SelfPerception` into init.
  - `agent_core/registry/shared_context.py` — add
    `self_perception: Optional[Any] = None` field; ensure optional
    fields for `user_facing_self_model`, `limitation_reporter`,
    `tool_capability_registry` if not already present (read the file
    first — V3 may have wired some/all; if present, do not duplicate).
    The actual SharedContext is in **registry/**, not homeostasis/.
  - `agent_core/modules/homeostasis_module.py` inside
    `_register_telegram_commands(bridge, ctx)` (~line 1994) — register
    `/selfstatus` command returning the formatted Polish summary. See §8
    Locked decisions for the exact pattern.
- **Out-of-scope (do NOT touch):**
  - `agent_core/orchestrator/self_model_facade.py` — read only.
  - `agent_core/orchestrator/limitation_reporter.py` — read only.
  - `agent_core/orchestrator/tool_registry.py` — read only.
  - K12 self_analysis modules — that's T-SELF-002 territory.
  - Conductor / dispatcher code — that's T-SELF-003 territory.
  - Web UI (`maria_ui/`) — out of scope for this task.

## Locked design decisions (do NOT relitigate)

1. **Snapshot cadence: every 1800 ticks (30 minutes).** Constant
   `SELF_PERCEPTION_TICK_INTERVAL = 1800` at module top of `core.py`.
   Phase 18 fires on `_tick_count % SELF_PERCEPTION_TICK_INTERVAL == 0`.
   Reason: snapshot is cheap (no LLM), but bulletin spam would be worse
   than no snapshot. Half-hour grain gives 48 datapoints/day, enough for
   T-SELF-002's 5-minute-freshness threshold.

2. **Snapshot file: `meta_data/self_state_snapshots.jsonl`.** Append-only,
   one JSON per line. Schema below (§Snapshot schema). No rotation/pruning
   in this task — file grows unbounded for now; T-SELF-001b future task
   can add daily rotation if needed.

3. **SnapshotStore is a thin file-backed class** — NOT a database, NOT a
   queue, NOT a cache. Methods:
   - `save(snapshot: dict) -> None` — atomic append.
   - `load_latest() -> Optional[dict]` — read last line, parse, return.
   - `load_recent(n: int) -> List[dict]` — last n lines.
   - Path injectable via constructor for tests.

4. **SelfPerception constructs reader classes fresh per snapshot.**
   `UserFacingSelfModel(ctx)`, `LimitationReporter(ctx)`,
   `ToolCapabilityRegistry(ctx)` are cheap (no I/O in `__init__`); fresh
   construction guarantees the snapshot reflects the live ctx, not a stale
   reader bound at SelfPerception init. **Exception:** if
   `ctx.user_facing_self_model` already exists (V3 may wire it), use that
   instance — do not double-instantiate.

5. **Bulletin entry on diff only.** SelfPerception compares the new
   snapshot against `SnapshotStore.load_latest()`. Diff signal = any of:
   - `mode` changed (e.g. ACTIVE → REDUCED)
   - `total_capabilities` changed
   - `external_services` status changed for any service (e.g. NIM
     `available` → `depleted`)
   - `limitations.by_severity.critical` count changed
   If any of these flipped, write a bulletin entry. **No diff = no
   bulletin** (snapshot still saved to JSONL — only the bulletin is
   gated). This keeps the bulletin signal-to-noise clean.

6. **Bulletin entry posting** (when diff detected). Call:
   ```python
   bulletin_store.create_and_post(
       entry_type=EntryType.IMPROVEMENT,
       topic=f"self_state_change",  # stable topic — dedup will collapse multiple same-cycle entries
       reason_code="self_perception_diff",
       summary=f"Self-state change: {field}={old}->{new}",  # max 200 chars, "; "-joined for multi-field
       requested_by="self_perception",
       priority=0.4,
       metadata={
           "snapshot_id": <id from new snapshot>,
           "diff_fields": [list of fields that changed],
           "previous_snapshot_id": <id from previous snapshot or null>,
       },
   )
   ```
   Imports: `from agent_core.bulletin.bulletin_store import BulletinStore`
   and `from agent_core.bulletin.bulletin_model import EntryType`.

7. **`/selfstatus` command output format** (Polish, ASCII, no emoji per
   ADR-005). Two-section layout:
   ```
   [Stan Marii] {timestamp}
   Tryb: {mode_label}  Sesja: #{session_count}  Wiek: {age_string}
   Zdolnosci: {total} ({free} swobodnych, {guarded} nadzorowanych)
   Serwisy: {available_services}/{total_services} aktywnych
     NIM API: {status}    Ollama: {status}    OpenClaw: {status}
     Codex: {status}      Telegram: {status}

   Ograniczenia ({critical} critical, {warning} warning, {info} info):
     [CRITICAL] {description}
     [WARNING] {description}
     ... (max 5 listed, "+ N more" suffix if more)
   ```
   If no snapshot exists yet (cold-start before first Phase 18 tick),
   return: `"Brak snapshotu. Pierwszy zapisze sie w ciagu 30 min."`

8. **Telegram command registration pattern.** In
   `agent_core/modules/homeostasis_module.py` inside the existing
   `_register_telegram_commands(bridge, ctx)` function (line 1994+),
   define a nested handler and register it. Mirror the existing
   `_cmd_status(args)` / `_cmd_goals(args)` pattern in that same
   function:
   ```python
   def _cmd_selfstatus(args):
       """Show current Self-Perception snapshot."""
       sp = getattr(ctx, "self_perception", None)
       if sp is None:
           return "Brak SelfPerception (modul nie wired)."
       return sp.format_status_for_telegram()

   bridge.register_command("selfstatus", _cmd_selfstatus)
   ```
   The handler signature is `(args: str) -> str` — `args` is the rest of
   the message after `/selfstatus`, the return value is the response
   text that the bridge sends back. There is no `update`/`context`/
   `reply_text` — the bridge handles transport.

## Snapshot schema

One JSON object per line in `meta_data/self_state_snapshots.jsonl`:

```json
{
  "snapshot_id": "sps-{uuid12}",
  "timestamp": 1779980000.0,
  "iso_timestamp": "2026-05-28T17:00:00",
  "tick_count": 75600,
  "mode": "ACTIVE",
  "mode_label": "aktywna",
  "identity": {
    "name": "Maria",
    "session_count": 2087,
    "total_uptime_hours": 845.3,
    "age_string": "6 miesiecy"
  },
  "capabilities": {
    "total": 12,
    "free": 7,
    "guarded": 3,
    "restricted": 2,
    "categories": ["Nauka", "Samoanaliza", "System", "Efektory"]
  },
  "external_services": [
    {"name": "NVIDIA NIM API", "status": "available"},
    {"name": "Ollama (local LLM)", "status": "available"},
    {"name": "OpenClaw Effector", "status": "disconnected"},
    {"name": "Codex (ChatGPT Plus)", "status": "available"},
    {"name": "Telegram (ClawBot)", "status": "available"}
  ],
  "limitations": {
    "total": 4,
    "by_severity": {"critical": 0, "warning": 1, "info": 3},
    "blocked_actions_count": 2,
    "items": [
      {"category": "budget", "severity": "info",
       "description": "Budzet NIM niski (450 tokenow)"},
      {"category": "hardware", "severity": "info",
       "description": "Lokalne LLM: llama3.1:8b (32GB RAM, brak GPU)"}
    ]
  },
  "knowledge": {
    "files_total": 425,
    "files_by_status": {"completed": 423, "pending": 2},
    "input_files_count": 0
  }
}
```

**ID format:** `sps-` prefix + 12-char hex from `uuid.uuid4().hex[:12]`.
**Field stability:** all top-level fields always present. List/dict values
may be empty but must exist. Snapshot is JSON-serializable end-to-end.

## SelfPerception public API

```python
class SelfPerception:
    def __init__(self, ctx, snapshot_store: Optional[SnapshotStore] = None,
                 bulletin_store: Optional[BulletinStore] = None):
        ...

    def take_snapshot(self) -> Dict[str, Any]:
        """Build a fresh snapshot. Side effects: persists to SnapshotStore,
        posts bulletin entry on diff. Returns the snapshot dict."""
        ...

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """Latest persisted snapshot, or None if no snapshot exists yet."""
        ...

    def is_fresh(self, max_age_seconds: float = 300.0) -> bool:
        """True iff latest snapshot exists AND is younger than max_age_seconds.
        Used by T-SELF-002 as a decision-threshold check."""
        ...

    def format_status_for_telegram(self) -> str:
        """Polish-formatted status text per §7. Falls back to cold-start
        message if no snapshot exists."""
        ...
```

## Phase 18 tick integration

In `agent_core/homeostasis/core.py`, **after** the existing Phase 17
conductor block (around line 617-641), add:

```python
# Phase 18: Self-Perception snapshot (every SELF_PERCEPTION_TICK_INTERVAL ticks)
if self._self_perception and self._tick_count % SELF_PERCEPTION_TICK_INTERVAL == 0:
    try:
        self._self_perception.take_snapshot()
    except Exception as e:
        logger.warning(f"[Phase18] self-perception snapshot error: {e}")
```

Add at module top (with other phase constants):
```python
SELF_PERCEPTION_TICK_INTERVAL = 1800  # ticks (≈30 min at 1 tick/sec)
```

**Init wiring** in `HomeostasisCore.__init__` (or wherever Phase 17 conductor
is wired — mirror that exact pattern):
```python
self._self_perception: Optional[Any] = None  # SelfPerception instance
# ... later, after BulletinStore + SharedContext are ready:
from agent_core.self_perception import SelfPerception, SnapshotStore
self._self_perception = SelfPerception(
    ctx=self._shared_context,
    snapshot_store=SnapshotStore(),  # default path
    bulletin_store=self._bulletin_store,
)
self._shared_context.self_perception = self._self_perception
```

**Cold start consideration:** at first Phase 18 tick after restart, there
is no previous snapshot to diff against → SelfPerception treats this as
diff=True for ALL fields (intentional — produces a single "boot snapshot"
bulletin entry per restart). Subsequent ticks compare against
`load_latest()`.

## SharedContext changes

The actual SharedContext lives at `agent_core/registry/shared_context.py`
(NOT in `agent_core/homeostasis/`). Edit that file to ensure these
attributes exist (add only the ones missing):

```python
self_perception: Optional[Any] = None  # SelfPerception (T-SELF-001)
```

**Check first** — read the file; V3 may have already wired some of:
- `user_facing_self_model`
- `limitation_reporter`
- `tool_capability_registry`

If they exist, leave them alone (no duplication). If they don't, add
them as `Optional[Any] = None` fields (do not import the classes —
keep SharedContext free of import cycles). SelfPerception then reads
`getattr(ctx, 'user_facing_self_model', None)` defensively and
instantiates a fresh one if absent.

## Definition of Done

- `agent_core/self_perception/__init__.py` exports `SelfPerception` and
  `SnapshotStore`.
- `SelfPerception.take_snapshot()` returns a dict matching the §Snapshot
  schema (all top-level keys present, types correct).
- `SnapshotStore.save()` writes one valid JSON line to
  `meta_data/self_state_snapshots.jsonl`; `load_latest()` parses it back
  identically.
- Phase 18 tick in `homeostasis/core.py` fires on
  `_tick_count % 1800 == 0` and only when `self._self_perception` is not
  None.
- Bulletin entry posted only when diff vs. latest snapshot is detected
  (mode, total_capabilities, service status, or critical-count change).
- `/selfstatus` Telegram command registered and returns formatted Polish
  output per §7, including cold-start fallback.
- `SelfPerception.is_fresh(max_age_seconds=300)` returns True iff latest
  snapshot is younger than 300s. False otherwise (including when no
  snapshot exists).
- All new tests pass (see §Tests).
- Full `agent_core/tests/` suite still passes (no regressions in 5192
  baseline; allow `+N pass` for new tests).
- `ruff check agent_core/self_perception agent_core/tests/test_self_perception.py`
  clean.
- `mypy agent_core/self_perception` clean (mypy config already in repo).

## Tests

Required new file: `agent_core/tests/test_self_perception.py`.

Minimum tests (≥7):

1. **test_snapshot_schema_complete** — `take_snapshot()` returns dict with
   all top-level keys from §Snapshot schema; each is the correct type.
2. **test_snapshot_persisted** — after `take_snapshot()`, the JSONL file
   has exactly one more line; `load_latest()` returns the same dict
   (modulo float precision tolerance on timestamp).
3. **test_no_diff_no_bulletin** — two consecutive `take_snapshot()` calls
   with unchanged ctx produce one bulletin entry on the FIRST (cold
   start), zero on the second.
4. **test_diff_triggers_bulletin** — mock ctx so `get_current_mode()`
   returns ACTIVE then REDUCED between snapshots; second snapshot must
   write a bulletin entry with diff_fields containing "mode".
5. **test_is_fresh_threshold** — snapshot just taken → `is_fresh(300)` is
   True; snapshot from 400s ago (mock time) → `is_fresh(300)` is False;
   no snapshot ever taken → False.
6. **test_telegram_format_cold_start** — no snapshot exists →
   `format_status_for_telegram()` returns the cold-start fallback string.
7. **test_telegram_format_with_snapshot** — after one snapshot,
   `format_status_for_telegram()` returns a string containing
   "Stan Marii", "Tryb:", "Zdolnosci:", "Serwisy:", "Ograniczenia"; no
   non-ASCII chars except Polish letters (no emoji per ADR-005).

Tests must use:
- A temp-dir SnapshotStore path (`tmp_path` pytest fixture).
- A fake ctx object (dict-like or namespace with the attributes
  `SelfPerception` reads). **Do not** spin up a real SharedContext — keep
  tests fast and isolated.
- A fake BulletinStore (record `create_and_post` calls in a list, or
  use a real `BulletinStore(path=tmp_path / "bulletin.jsonl")` for
  integration-style verification).

Test command:
```bash
cd /home/maria/maria && python -m pytest agent_core/tests/test_self_perception.py -v
```

Full suite check:
```bash
cd /home/maria/maria && python -m pytest agent_core/tests/ -q
```

## Non-goals

- Do NOT add daily rotation / pruning of the JSONL file (T-SELF-001b
  future task).
- Do NOT call any LLM during snapshot — this must stay zero-LLM
  (UserFacingSelfModel's NIM availability check is the ONE network call
  acceptable, and it's already gated by env-var presence).
- Do NOT refactor `LimitationReporter` / `UserFacingSelfModel` /
  `ToolCapabilityRegistry`. Read-only consumers only.
- Do NOT add a Web UI panel — Telegram + JSONL is enough for this plank.
- Do NOT add config-file knobs (`SELF_PERCEPTION_TICK_INTERVAL`). The
  constant lives in code; a future task can move to env if needed.
- Do NOT extend SnapshotStore to query/filter beyond `load_latest` /
  `load_recent`. Future T-SELF-001b can add it.
- Do NOT add backwards-compatibility shims; this is a new module.

## Conventions

- Python 3.10+ (project standard).
- Type hints required (mypy must pass).
- English docstrings; comments may be Polish if matching existing file
  style (CLAUDE.md §Konwencje).
- No emojis (ADR-005).
- No comments explaining WHAT the code does; only WHY for non-obvious
  decisions.
- Do not add backwards-compatibility shims.
- Do not push to GitHub (ADR-029 — operator pushes manually).

## Constraints from this task in particular

- **Performance budget:** `take_snapshot()` must complete in under 200ms
  on the production Mini PC (Ryzen 5 7430U). Most of the time will be
  the NIM availability check (~50-100ms typical). If the snapshot would
  exceed 200ms, the NIM check must be moved to async/background — but
  start with the simple synchronous version; only optimize if pytest
  timing tests fail. **No premature optimization.**
- **Memory:** snapshots are small (~2KB JSON). 48/day × 365/year = ~35MB
  per year. Acceptable; no rotation needed in this task.
- **Tick budget:** Phase 18 tick must add no more than 5ms to the tick
  cycle when it does NOT fire (skip-fast check). When it fires, the
  200ms snapshot is acceptable — homeostasis already tolerates 3s
  overruns (see existing "Tick overrun" warnings in journalctl).
- **Thread safety:** SnapshotStore methods may be called from the
  homeostasis tick thread and from the Telegram thread (when
  `/selfstatus` fires). Use a `threading.Lock` around file I/O.
  SelfPerception's `take_snapshot` is only called from tick thread —
  no lock needed there, but `is_fresh` / `get_latest` / `format_status_for_telegram`
  are called from Telegram → those must use SnapshotStore's locked methods.

## If you encounter ambiguity

- Stop. Output a numbered list of the ambiguities you found.
- Do NOT guess. Master will rewrite the brief.
- Especially: if `SharedContext` already has fields wired in unexpected
  ways, if existing telegram command names conflict, or if the existing
  bulletin store API differs from what's described here — surface it
  before guessing.

## Output

- Inline commits on `refactor/homeostasis` (per TASK_BOARD §Dispatch mode
  2026-05-16). Do NOT create a new branch.
- One commit per logical change preferred:
  1. `feat(self-perception): add SelfPerception + SnapshotStore modules`
  2. `feat(self-perception): wire Phase 18 tick + SharedContext`
  3. `feat(telegram): /selfstatus command`
  4. `test(self-perception): test suite (7 tests)`
  Squashing into 1-2 commits is fine if all changes are tightly related.
- Commit message style: see `git log --oneline -10` for examples; lowercase
  type prefix (`feat`, `fix`, `test`, `docs`), short subject.
- When done, output a short summary: which files changed, test count,
  any surprises. Do not summarize what the code does.

## Authoritative references (must read before starting)

- `CLAUDE.md` (project conventions, ADR-005)
- `docs/orchestration/WORKER_BRIEF_TEMPLATE.md` (brief format conventions)
- `agent_core/orchestrator/self_model_facade.py` (`UserFacingSelfModel`)
- `agent_core/orchestrator/limitation_reporter.py` (`LimitationReporter`)
- `agent_core/orchestrator/tool_registry.py` (`ToolCapabilityRegistry`)
- `agent_core/homeostasis/core.py` Phase 17 block (mirror for Phase 18)
- `agent_core/registry/shared_context.py` (THE SharedContext file — NOT
  in homeostasis/)
- `agent_core/telegram/__init__.py` (`TelegramBridge.register_command(
  command, handler)` where `handler(args: str) -> str`)
- `agent_core/modules/homeostasis_module.py:1994`
  (`_register_telegram_commands(bridge, ctx)` — where all cmd handlers
  are defined and registered)
- `agent_core/bulletin/bulletin_store.py` (`BulletinStore.create_and_post`
  signature)
- `agent_core/bulletin/bulletin_model.py` (`EntryType.IMPROVEMENT`)
