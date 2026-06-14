"""Operator approval actions (Skrzynka layer 2 -- the write path).

These mutate real state, so unlike the read-only inbox they MUST run against
the daemon's LIVE store instances (shared into the Web UI via
``set_approval_stores`` in maria_ui/app.py). Sharing the live instances -- not
fresh ones -- means the UI thread, the tick thread, and the TelegramPoll thread
all serialize on the SAME per-store lock; a fresh instance would have its own
lock and could race a double-write.

Each branch mirrors its Telegram command exactly so an in-app tap and the
``/approve_*`` command are the identical action:
  - note   approve -> OutboxProposalStore.approve (the gated file write)
           reject  -> OutboxProposalStore.reject
  - repair approve -> close (mark_done + resolve linked bulletin). Per ADR-031
           this is an ACKNOWLEDGE-AND-CLOSE, never a Codex dispatch.
  - review approve/reject -> BulletinStore.resolve (reason records which)
"""

from typing import Any, Dict, Optional


def apply_approval_action(
    *,
    outbox: Any,
    conductor: Any,
    bulletin: Any,
    kind: str,
    item_id: str,
    action: str,
) -> Dict[str, Any]:
    """Apply ``action`` to the item ``item_id`` of the given ``kind``.

    Returns ``{"ok": bool, "message": str}``. Any store may be None (daemon not
    wired); the relevant branch reports that rather than raising.
    """
    kind = (kind or "").strip()
    action = (action or "").strip()
    item_id = (item_id or "").strip()
    if not item_id:
        return {"ok": False, "message": "Brak id."}

    if kind == "note":
        return _act_note(outbox, item_id, action)
    if kind == "repair":
        return _act_repair(conductor, bulletin, item_id, action)
    if kind == "review":
        return _act_review(bulletin, item_id, action)
    return {"ok": False, "message": f"Nieznany rodzaj: {kind}"}


def _act_note(outbox: Any, item_id: str, action: str) -> Dict[str, Any]:
    if outbox is None:
        return {"ok": False, "message": "Outbox niedostepny (daemon nie wired)."}
    if action == "approve":
        res = outbox.approve(item_id)
        if res.get("ok"):
            path = (res.get("result") or {}).get("path", "?")
            return {"ok": True, "message": f"Zapisano notatke -> {path}"}
        err = res.get("error") or (res.get("result") or {}).get("error") or "?"
        return {"ok": False, "message": f"Approve nieudane: {err}"}
    if action == "reject":
        res = outbox.reject(item_id)
        if res.get("ok"):
            return {"ok": True, "message": "Notatka odrzucona."}
        return {"ok": False, "message": f"Reject nieudane: {res.get('error', '?')}"}
    return {"ok": False, "message": f"Akcja '{action}' nie dotyczy notatki."}


def _act_repair(
    conductor: Any, bulletin: Any, item_id: str, action: str
) -> Dict[str, Any]:
    if conductor is None:
        return {"ok": False, "message": "Conductor niedostepny (daemon nie wired)."}
    if action != "approve":
        return {"ok": False, "message": "Naprawe mozna tylko zatwierdzic (zamknac)."}
    # ADR-031: approve == acknowledge + close, NEVER dispatch. Only close an id
    # that is genuinely a PENDING self-repair (never an arbitrary task id).
    pending = {t.task_id for t in conductor.get_pending_repair_tasks()}
    if item_id not in pending:
        return {"ok": False,
                "message": f"Nie znaleziono PENDING self-repair: {item_id}"}
    conductor.mark_done(
        item_id, notes="acknowledged + closed by operator (web Skrzynka)")
    _close_linked_bulletin(bulletin, item_id, reason="operator_acknowledged")
    return {"ok": True, "message": f"Zamknieto {item_id}. Bulletin rozwiazany."}


def _act_review(bulletin: Any, item_id: str, action: str) -> Dict[str, Any]:
    if bulletin is None:
        return {"ok": False, "message": "Bulletin niedostepny (daemon nie wired)."}
    # Both approve and reject close the entry; the reason records the decision.
    reason = "operator_approved" if action == "approve" else "operator_dismissed"
    ok = bool(bulletin.resolve(item_id, reason=reason))
    if ok:
        return {"ok": True, "message": "Zgloszenie zamkniete."}
    return {"ok": False, "message": f"Nie znaleziono zgloszenia: {item_id}"}


def _close_linked_bulletin(
    bulletin: Any, task_id: str, reason: str = "operator_acknowledged"
) -> None:
    """Resolve the bulletin entry linked to a repair task. Reuses the canonical
    self-repair closer so web and Telegram paths behave identically."""
    if bulletin is None:
        return
    try:
        from agent_core.self_repair.expiry import _close_linked_bulletin as closer
        closer(bulletin, task_id, reason=reason)
    except Exception:  # pragma: no cover - defensive
        pass
