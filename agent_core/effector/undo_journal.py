"""Effector undo foundation -- classify reversibility + journal an inverse.

The path to real hands (OpenClaw acting on the world beyond Maria's FS sandbox)
needs an honest safety floor BEFORE the authority rung is ever advanced. OpenClaw
is unsandboxed with no built-in undo; the K10 audit already records every action
but its `rollback_available` flag and the `Reversibility` enum are set and never
consulted (dead scaffolding).

This module is the foundation's first brick (LIBRARY / observe-only -- nothing
here invokes OpenClaw or changes execution). It provides:
  * classify_reversibility(tool, args) -- HONEST per-tool reversibility. We do NOT
    pretend the irreversible is reversible: `exec` (arbitrary shell) and `message`
    (sent, can't be unsent) are IRREVERSIBLE; read/web_* are read-only (nothing to
    undo); `write` is reversible IF the prior state was captured; `cron` is partial.
  * capture_pre_state(tool, args, read_fn) -- snapshot what's needed to reverse a
    `write` (the prior file content, or its absence), before the action runs.
  * build_inverse(tool, args, pre_state) -- the inverse OpenClaw invocation (or a
    "noop" / "irreversible" verdict). A PLAN only; this brick never executes it.
  * EffectorUndoJournal -- append-only `meta_data/effector_undo_journal.jsonl`,
    one record per intended effector action, so a later rung can offer undo and an
    irreversible action is recorded + flagged (gated harder), never faked.

Later bricks (separate, flag-gated): wire capture-before-execute into the
coordinator; a /undo_action operator command; then -- with the operator, live --
the SUGGEST authority rung.
"""

from __future__ import annotations

import json
import logging
import shlex
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent_core.action_safety.safety_model import Reversibility

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "meta_data" / "effector_undo_journal.jsonl"

# Read-only tools: invoking them changes nothing, so "undo" is a no-op.
_READ_ONLY = {"read", "web_fetch", "web_search"}
# Inherently irreversible: arbitrary shell, and a sent message.
_IRREVERSIBLE = {"exec", "message"}


def classify_reversibility(tool: str, args: Optional[Dict[str, Any]] = None) -> Reversibility:
    """Honest per-tool reversibility. Unknown tools default to IRREVERSIBLE."""
    tool = (tool or "").strip().lower()
    if tool in _READ_ONLY:
        return Reversibility.REVERSIBLE       # read-only: nothing to undo
    if tool == "write":
        return Reversibility.REVERSIBLE       # reversible IF pre-state captured
    if tool == "cron":
        return Reversibility.PARTIALLY_REVERSIBLE  # add->remove ok; remove needs prior spec
    if tool in _IRREVERSIBLE:
        return Reversibility.IRREVERSIBLE
    return Reversibility.IRREVERSIBLE          # safe default for unknown tools


def capture_pre_state(
    tool: str,
    args: Optional[Dict[str, Any]] = None,
    *,
    read_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> Dict[str, Any]:
    """Snapshot the state needed to reverse the action, BEFORE it runs.

    Only `write` needs a snapshot: the prior file content (to restore) or its
    absence (so the inverse is a remove). `read_fn(path)` returns the current
    content or None if the file does not exist; without it, existence is unknown.
    """
    tool = (tool or "").strip().lower()
    args = args or {}
    if tool != "write":
        return {}
    path = args.get("path", "")
    if not path or read_fn is None:
        return {"path": path, "captured": False}
    try:
        content = read_fn(path)
    except Exception as e:  # a failed read must not crash the journal
        logger.warning("[undo_journal] pre-state read failed for %s: %s", path, e)
        return {"path": path, "captured": False, "error": str(e)[:200]}
    return {"path": path, "captured": True,
            "existed": content is not None, "content": content}


def build_inverse(
    tool: str,
    args: Optional[Dict[str, Any]] = None,
    pre_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The inverse OpenClaw invocation, as a PLAN (never executed here).

    Returns one of:
      {"kind": "noop", ...}                       -- read-only, nothing to undo
      {"kind": "invoke", "tool", "args", ...}     -- run this to reverse
      {"kind": "partial"|"unknown"|"irreversible", "reason"} -- cannot auto-undo
    """
    tool = (tool or "").strip().lower()
    args = args or {}
    pre_state = pre_state or {}

    if tool in _READ_ONLY:
        return {"kind": "noop", "reason": "read-only action, nothing to undo"}

    if tool == "write":
        path = args.get("path", "")
        if not pre_state.get("captured"):
            return {"kind": "unknown",
                    "reason": "no pre-state captured -- cannot build a safe inverse"}
        if pre_state.get("existed"):
            return {"kind": "invoke", "tool": "write",
                    "args": {"path": path, "content": pre_state.get("content", "")},
                    "dangerous": True, "note": "restore prior file content"}
        # File did not exist before -> the inverse removes the new file. Removal
        # requires `exec` (no delete tool), which is itself dangerous. Carry the
        # removal as an `argv` list (path as ONE element) so the executor never
        # re-splits it on whitespace -- a `command` string is re-split by the
        # OpenClaw exec node (command.split()), which would destroy shlex.quote
        # protection and delete the wrong path. `command` is kept for display only.
        return {"kind": "invoke", "tool": "exec",
                "args": {"argv": ["rm", "--", path],
                         "command": f"rm -- {shlex.quote(path)}"},
                "dangerous": True, "note": "remove newly-created file"}

    if tool == "cron":
        action = str(args.get("action", "")).lower()
        if action in ("add", "create", "schedule"):
            return {"kind": "partial",
                    "reason": "scheduled job -- inverse is an unschedule once the job id is known"}
        return {"kind": "partial",
                "reason": "cron mutation -- needs the prior schedule to reverse"}

    if tool in _IRREVERSIBLE:
        why = ("arbitrary shell command cannot be generically reversed"
               if tool == "exec" else "a sent message cannot be unsent")
        return {"kind": "irreversible", "reason": why}

    return {"kind": "irreversible", "reason": f"unknown tool '{tool}'"}


# --- journal ---------------------------------------------------------------

# Status of an undo record.
STATUS_RECORDED = "recorded"        # reversible action journaled with an executable inverse
STATUS_IRREVERSIBLE = "irreversible"  # logged but cannot be auto-undone (gated harder)
STATUS_UNDONE = "undone"            # the inverse was executed successfully
STATUS_UNDO_FAILED = "undo_failed"  # the inverse was attempted and failed
STATUS_ACTION_FAILED = "action_failed"  # the original action did NOT complete -> nothing to undo


@dataclass
class UndoRecord:
    record_id: str
    tool: str
    args: Dict[str, Any]
    reversibility: str            # Reversibility.value
    inverse: Dict[str, Any]
    pre_state: Dict[str, Any]
    status: str
    reason: str = ""
    action_record_id: str = ""    # link to K10 action_audit (arec-...) when known
    created_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EffectorUndoJournal:
    """Append-only journal of intended effector actions + their inverse plan.

    One record per action (status RECORDED / IRREVERSIBLE); status updates
    (UNDONE / UNDO_FAILED) are appended as new lines, reconciled last-write-wins
    by record_id on read (same discipline as GoalStore / action_audit).
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else _DEFAULT_PATH
        # Reentrant so a mutator can hold the lock across the whole
        # read-modify-append (get -> mutate -> append) and still call the
        # lock-free internals -- otherwise two concurrent mark_* on the same
        # record could interleave their appends and lose a status transition.
        self._lock = threading.RLock()

    def record_action(
        self,
        *,
        tool: str,
        args: Optional[Dict[str, Any]] = None,
        action_record_id: str = "",
        read_fn: Optional[Callable[[str], Optional[str]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> UndoRecord:
        """Classify, capture pre-state, build the inverse plan, and journal it.

        ``metadata`` carries provenance the autonomous SUGGEST side needs to
        decide whether to later propose undoing this action (e.g. the owning
        ``goal_id`` + ``source``). Observability only -- never consulted here.
        """
        args = args or {}
        pre = capture_pre_state(tool, args, read_fn=read_fn)
        inv = build_inverse(tool, args, pre)
        # FIX-3 (honesty): the record's reversibility/status must reflect whether a
        # SAFE, EXECUTABLE inverse was actually built -- not the tool class alone. A
        # `write` whose pre-state could not be captured (read failed) yields
        # kind='unknown' and MUST NOT be advertised as auto-reversible: a later
        # executor would otherwise refuse it, but /undo_list/preview would mislead.
        kind = inv.get("kind")
        if kind == "invoke":
            rev = classify_reversibility(tool, args)  # REVERSIBLE for read/write
            status = STATUS_RECORDED
        elif kind == "noop":
            rev = Reversibility.REVERSIBLE             # read-only, nothing to undo
            status = STATUS_RECORDED
        elif kind == "partial":
            rev = Reversibility.PARTIALLY_REVERSIBLE
            status = STATUS_IRREVERSIBLE              # cannot auto-undo -> gated harder
        else:  # 'unknown' (no pre-state) / 'irreversible'
            rev = Reversibility.IRREVERSIBLE
            status = STATUS_IRREVERSIBLE
        rec = UndoRecord(
            record_id=f"eundo-{uuid.uuid4().hex[:8]}",
            tool=(tool or "").strip().lower(),
            args=args,
            reversibility=rev.value,
            inverse=inv,
            pre_state=pre,
            status=status,
            reason=inv.get("reason", ""),
            action_record_id=action_record_id,
            created_at=float(now if now is not None else time.time()),
            metadata=dict(metadata or {}),
        )
        self._append(rec)
        return rec

    def mark_undone(self, record_id: str, *, ok: bool, detail: str = "",
                    now: Optional[float] = None) -> None:
        """Append a status update after an inverse was attempted.

        The read-modify-append runs under one lock acquisition so a concurrent
        mark_* on the same record cannot interleave and drop a transition."""
        with self._lock:
            base = self._get_locked(record_id)
            if base is None:
                return
            base.status = STATUS_UNDONE if ok else STATUS_UNDO_FAILED
            base.metadata = {**(base.metadata or {}), "undo_detail": detail[:300],
                             "undo_at": float(now if now is not None else time.time())}
            self._append_locked(base)

    def mark_action_failed(self, record_id: str, *, detail: str = "",
                           now: Optional[float] = None) -> None:
        """Append a status update when the ORIGINAL action did not complete.

        The inverse is journaled before the action runs (pre-state must be
        captured first), so a failed action leaves a stale 'recorded' inverse for
        something that never happened -- undoing it would act on a state that does
        not exist. Reconcile it to ACTION_FAILED so a later executor / operator
        view never offers undo for a non-action. No-op if the record is unknown."""
        with self._lock:
            base = self._get_locked(record_id)
            if base is None:
                return
            base.status = STATUS_ACTION_FAILED
            base.metadata = {**(base.metadata or {}), "action_failed_detail": detail[:300],
                             "action_failed_at": float(now if now is not None else time.time())}
            self._append_locked(base)

    def get(self, record_id: str) -> Optional[UndoRecord]:
        with self._lock:
            return self._get_locked(record_id)

    def _get_locked(self, record_id: str) -> Optional[UndoRecord]:
        for rec in reversed(self._load()):  # last-write-wins
            if rec.record_id == record_id:
                return rec
        return None

    def list_recent(self, n: int = 20) -> List[UndoRecord]:
        with self._lock:
            seen: Dict[str, UndoRecord] = {}
            for rec in self._load():
                seen[rec.record_id] = rec  # last write wins
            return list(seen.values())[-n:]

    # --- io ---
    def _append(self, rec: UndoRecord) -> None:
        with self._lock:
            self._append_locked(rec)

    def _append_locked(self, rec: UndoRecord) -> None:
        """Append one record. Caller MUST hold self._lock."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("[undo_journal] append failed: %s", e)

    def _load(self) -> List[UndoRecord]:
        if not self._path.exists():
            return []
        out: List[UndoRecord] = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(UndoRecord(**json.loads(line)))
                    except (json.JSONDecodeError, TypeError):
                        continue  # tolerate a partial/old line
        except OSError as e:
            logger.warning("[undo_journal] load failed: %s", e)
        return out


# --- operator-facing formatting (read-only; used by /undo_list, /undo_preview) -

def format_undo_list(records: List[UndoRecord]) -> str:
    if not records:
        return "Dziennik cofania pusty (brak zapisanych akcji efektora)."
    lines = [f"{r.record_id} | {r.tool} | {r.reversibility} | {r.status}"
             for r in records]
    return ("Dziennik cofania (ostatnie):\n" + "\n".join(lines)
            + "\n\nPodglad cofniecia: /undo_preview <id>")


def format_undo_preview(record: Optional[UndoRecord]) -> str:
    if record is None:
        return "Nie znam takiego wpisu (zobacz /undo_list)."
    inv = record.inverse or {}
    kind = inv.get("kind")
    head = (f"Wpis {record.record_id} ({record.tool}, {record.reversibility}, "
            f"status={record.status}).")
    if kind == "noop":
        return head + "\nAkcja read-only - nie ma czego cofac."
    if kind == "invoke":
        note = f"\nUwaga: {inv.get('note')}" if inv.get("note") else ""
        return (head + f"\nCofniecie wykonaloby: narzedzie={inv.get('tool')}, "
                f"args={inv.get('args')}." + note
                + "\nSamo wykonanie cofniecia uruchomimy RAZEM przy podniesieniu "
                "szczebla (to juz akcja na zywym OpenClaw).")
    return head + f"\nNIE da sie automatycznie cofnac. Powod: {inv.get('reason', '-')}"
