"""Unified 'awaiting your decision' inbox -- read-only aggregation.

Three queues that today only surface as Telegram commands are collapsed into
one operator-facing list for the mobile app:

  - note    Maria proposes an outbox status-note      (/approve_note)
  - repair  PENDING maria self-repair task            (/approve_repair)
  - review  bulletin WAITING_HUMAN entry needing a call

Everything is read FRESH from the same jsonl files the daemon writes
(mirrors /api/projects), so no live SharedContext reference is required and
there is NO write path here. This is layer 1 (the glass): the action buttons
land in a later pass behind their own verify loop, because approval has real
side effects (file writes, task closure).
"""

from pathlib import Path
from typing import Any, Dict


def _preview(text: Any, limit: int = 240) -> str:
    """Trim a body to a single-screen preview; defensive against non-strings."""
    text = (str(text) if text is not None else "").strip().replace("\r", "")
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def build_approval_inbox(meta_dir: Path) -> Dict[str, Any]:
    """Aggregate pending operator approvals from ``meta_dir`` jsonl stores.

    Each read is isolated: a failure in one queue logs and degrades to empty
    rather than blanking the whole inbox. Returns a JSON-ready dict::

        {"items": [ {kind,id,title,detail,created_at,extra}, ... ],
         "counts": {"note": n, "repair": n, "review": n, "total": N}}

    Items are sorted newest-first; any item missing a timestamp sinks to the
    bottom.
    """
    meta_dir = Path(meta_dir)
    items = []
    counts = {"note": 0, "repair": 0, "review": 0}

    # 1) Outbox notes (PENDING). Explicit path -- the store default is
    #    CWD-relative, so we never rely on the process working directory.
    try:
        from agent_core.hands.outbox import OutboxProposalStore
        outbox = OutboxProposalStore(path=meta_dir / "outbox_proposals.jsonl")
        for rec in outbox.list_pending():
            content = rec.get("content")
            content = str(content) if content is not None else ""
            items.append({
                "kind": "note",
                "id": rec.get("id", ""),
                "title": rec.get("filename") or "(notatka)",
                # Prefer the note BODY for the preview (what Maria actually wants
                # to post), falling back to the one-word reason. The FULL body
                # rides in extra["content"] so the app can show the whole note on
                # tap instead of only "autonomous".
                "detail": _preview(content or rec.get("reason")),
                "created_at": rec.get("created_at"),
                "extra": {"reason": rec.get("reason", ""), "content": content},
            })
            counts["note"] += 1
    except Exception as e:  # pragma: no cover - defensive
        print(f"[UI] [WARN] approval inbox: outbox read failed: {e}")

    # 2) Self-repair tasks (PENDING, phase=self_repair) -- read via TaskQueue
    #    just like /api/projects, so no live conductor reference is needed.
    try:
        from agent_core.conductor.task_queue import TaskQueue
        from agent_core.conductor.task_model import TaskStatus
        q_path = meta_dir / "maria_task_queue.jsonl"
        if q_path.exists():
            for t in TaskQueue(path=q_path).list(
                project="maria", status=TaskStatus.PENDING
            ):
                if t.phase != "self_repair":
                    continue
                art = t.artifacts or {}
                evidence = art.get("evidence_summary")
                full = (
                    t.notes
                    or (str(evidence) if evidence else "")
                    or t.description
                    or ""
                )
                items.append({
                    "kind": "repair",
                    "id": t.task_id,
                    "title": t.title or "(naprawa)",
                    "detail": _preview(full),
                    "created_at": t.created_at,
                    "extra": {
                        "repair_kind": art.get("repair_kind"),
                        "expires_at": art.get("expires_at"),
                        "content": full,
                    },
                })
                counts["repair"] += 1
    except Exception as e:  # pragma: no cover - defensive
        print(f"[UI] [WARN] approval inbox: repair read failed: {e}")

    # 3) Bulletin WAITING_HUMAN (needs an operator decision). BulletinStore's
    #    default path is already absolute and correct in production.
    try:
        from agent_core.bulletin import BulletinStore, EntryType
        store = BulletinStore(path=meta_dir / "cognitive_bulletin.jsonl")
        for entry in store.get_by_type(EntryType.WAITING_HUMAN):
            items.append({
                "kind": "review",
                "id": entry.entry_id,
                "title": entry.topic or "(zgloszenie)",
                "detail": _preview(entry.summary),
                "created_at": entry.created_at,
                "extra": {
                    "priority": entry.priority,
                    "requested_by": entry.requested_by,
                    "reason_code": entry.reason_code,
                    "content": entry.summary or "",
                },
            })
            counts["review"] += 1
    except Exception as e:  # pragma: no cover - defensive
        print(f"[UI] [WARN] approval inbox: bulletin read failed: {e}")

    items.sort(key=lambda it: it.get("created_at") or 0.0, reverse=True)
    counts["total"] = len(items)
    return {"items": items, "counts": counts}
