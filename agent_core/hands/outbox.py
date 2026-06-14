"""Operator-visible outbox -- Rung 2 of TIER 2 hands.

Maria's first REAL action on the world (outside the sandbox): she PROPOSES a
small, useful text artifact; the operator APPROVES it; only then is it written,
through the same guarded ``sandbox_write`` engine (size cap, .txt, sanitize,
symlink reject, path jail) PLUS ``no_overwrite`` (there is no undo, so a write
never clobbers an existing file). Proposals live in
``meta_data/outbox_proposals.jsonl``; files land in ``meta_data/maria_outbox/``.

SAFETY MODEL: nothing is ever written without an explicit operator approval.
The autonomous side can only PROPOSE (append a pending row + ping Telegram); the
write happens solely in ``approve()``, which the operator triggers. Content is
deterministic (composed from live state, no LLM), so it is never attacker- or
model-controlled.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.hands.sandbox_writer import default_outbox_root, sandbox_write

logger = logging.getLogger(__name__)

DEFAULT_PROPOSALS_PATH = Path("meta_data/outbox_proposals.jsonl")

# How long after the last status-note proposal before the autonomous tick makes
# another one. Wall-clock on purpose: it reads the proposal ledger, so the gap
# survives daemon restarts (tick_count does not). NB: ticks advance +1/s in
# every mode -- the old "SLEEP fast-forwards ticks" claim was comment folklore.
AUTONOMOUS_PROPOSE_MIN_GAP_SECONDS = 20 * 3600


def is_enabled() -> bool:
    """OUTBOX_WRITE_ENABLED flag (parallel-run, OFF by default). Gates ONLY the
    autonomous proposer; operator drill/approve always work, and the write is
    gated by approval regardless of this flag."""
    return os.environ.get("OUTBOX_WRITE_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on",
    }

STATUS_PENDING = "pending"
STATUS_WRITTEN = "written"
STATUS_FAILED = "failed"
STATUS_REJECTED = "rejected"


def compose_status_note(fields: Dict[str, Any]) -> str:
    """Build a deterministic, human-readable status snapshot (no LLM).

    ``fields`` is a plain dict gathered from live state by the caller -- keeping
    this pure makes it trivially testable and free of side effects. Beyond the
    header + ``when``/``mode``/``health`` core, every field is optional: a
    missing source simply drops its line, so the note degrades gracefully and a
    gap in one subsystem never breaks the tick or the artifact. Labels align to
    a 14-char column for readability."""
    lines = [
        "Maria -- status note",
        f"when:         {fields.get('ts_label', '?')}",
    ]
    # identity / heartbeat
    if fields.get("uptime_days") is not None:
        lines.append(f"age (days):   {fields.get('uptime_days')}")
    if fields.get("tick") is not None:
        lines.append(f"tick:         {fields.get('tick')}")
    # vitals
    lines.append(f"mode:         {fields.get('mode', '?')}")
    lines.append(f"health:       {fields.get('health', '?')}")
    if fields.get("alerts") is not None:
        lines.append(f"alerts:       {fields.get('alerts')}")
    # goals (what she is working on)
    goals_line = f"active goals: {fields.get('active_goals', '?')}"
    if fields.get("goals_breakdown"):
        goals_line += f" ({fields['goals_breakdown']})"
    lines.append(goals_line)
    if fields.get("proposed_goals") is not None:
        lines.append(f"proposed:     {fields['proposed_goals']}")
    # learning (what she has been taking in)
    if fields.get("knowledge") is not None:
        lines.append(f"knowledge:    {fields['knowledge']}")
    if fields.get("last_exam") is not None:
        lines.append(f"last exam:    {fields['last_exam']}")
    # cognition (her own activity + self-model)
    if fields.get("planner") is not None:
        lines.append(f"planner:      {fields['planner']}")
    if fields.get("capabilities") is not None:
        lines.append(f"capabilities: {fields['capabilities']}")
    note = fields.get("note")
    if note:
        lines.append(f"note:         {note}")
    return "\n".join(lines) + "\n"


class OutboxProposalStore:
    """Pending-proposal ledger + the gated write. JSONL, append-per-transition
    (latest record per id wins), mirroring the conductor/bulletin convention."""

    def __init__(
        self,
        path: Any = DEFAULT_PROPOSALS_PATH,
        base_dir: str = ".",
    ):
        self._path = Path(path)
        self._base_dir = base_dir
        # Serializes the read-modify-append sections (approve/reject + the
        # atomic dedup) so the tick thread and the TelegramPoll thread cannot
        # race a double-write or two coexisting PENDING rows.
        self._lock = threading.Lock()

    # -- write side (append-only transitions) --
    def _append(self, record: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _load(self) -> Dict[str, Dict[str, Any]]:
        """Collapse the ledger to the latest record per proposal id."""
        latest: Dict[str, Dict[str, Any]] = {}
        if not self._path.exists():
            return latest
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    pid = rec.get("id")
                    if pid:
                        latest[pid] = rec
        except OSError:
            logger.warning("[outbox] proposals read failed", exc_info=True)
        return latest

    def propose(
        self,
        filename: str,
        content: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Record a PENDING proposal. Does NOT write anything to the outbox.
        Returns the proposal record (caller is responsible for notifying)."""
        pid = f"obx-{uuid.uuid4().hex[:8]}"
        record = {
            "id": pid,
            "created_at": time.time(),
            "filename": filename,
            "content": content,
            "reason": reason,
            "status": STATUS_PENDING,
        }
        self._append(record)
        logger.info("[outbox] proposed %s (%s)", pid, filename)
        return record

    def propose_if_none_pending(
        self,
        filename: str,
        content: str,
        reason: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Atomic 'one at a time': under the lock, propose ONLY if no proposal is
        already pending. Returns the new record, or None if one was pending.
        This makes the dedup race-free across the tick + Telegram threads."""
        with self._lock:
            if any(r.get("status") == STATUS_PENDING for r in self._load().values()):
                return None
            return self.propose(filename, content, reason)

    def list_pending(self) -> List[Dict[str, Any]]:
        return [
            r for r in self._load().values() if r.get("status") == STATUS_PENDING
        ]

    def seconds_since_last(self) -> Optional[float]:
        """Wall-clock age of the most recent proposal (any status), or None if
        the ledger is empty. Used by the autonomous proposer to self-throttle."""
        recs = self._load()
        newest = max((r.get("created_at", 0.0) for r in recs.values()), default=0.0)
        return (time.time() - newest) if newest else None

    def get(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """Resolve a proposal by id. Exact match, else a UNIQUE suffix match
        (>=4 chars -- the operator may paste the 8-hex tail). Refuses ambiguous
        or too-short tokens (returns None) so a typo / the constant 'obx-'
        prefix can never silently resolve to the wrong proposal."""
        proposal_id = (proposal_id or "").strip()
        if not proposal_id:
            return None
        latest = self._load()
        if proposal_id in latest:
            return latest[proposal_id]
        if len(proposal_id) >= 4:
            matches = [r for pid, r in latest.items() if pid.endswith(proposal_id)]
            if len(matches) == 1:
                return matches[0]
        return None

    def approve(self, proposal_id: str) -> Dict[str, Any]:
        """Operator approval -> the ONLY place an outbox file is written.
        Guarded write (no_overwrite) into the outbox root; records the outcome.
        Locked so two approvals of the same id cannot both write."""
        with self._lock:
            rec = self.get(proposal_id)
            if rec is None:
                return {"ok": False, "error": f"no proposal: {proposal_id}"}
            if rec.get("status") != STATUS_PENDING:
                return {"ok": False, "error": f"not pending (status={rec.get('status')})"}

            result = sandbox_write(
                rec["filename"],
                rec["content"],
                sandbox_root=default_outbox_root(self._base_dir),
                no_overwrite=True,
            )
            ok = bool(result.get("success"))
            self._append({
                **rec,
                "status": STATUS_WRITTEN if ok else STATUS_FAILED,
                "result": result,
                "updated_at": time.time(),
            })
            logger.info("[outbox] approve %s -> %s", rec["id"],
                        STATUS_WRITTEN if ok else STATUS_FAILED)
            return {"ok": ok, "result": result, "proposal": rec}

    def reject(self, proposal_id: str) -> Dict[str, Any]:
        with self._lock:
            rec = self.get(proposal_id)
            if rec is None:
                return {"ok": False, "error": f"no proposal: {proposal_id}"}
            if rec.get("status") != STATUS_PENDING:
                return {"ok": False, "error": f"not pending (status={rec.get('status')})"}
            self._append({**rec, "status": STATUS_REJECTED, "updated_at": time.time()})
            return {"ok": True, "proposal": rec}
