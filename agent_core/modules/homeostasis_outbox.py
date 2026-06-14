"""Outbox helpers: Telegram outbox-note proposal + ping.

Extracted from homeostasis_module (2026-06-13 god-file split). Shared by the
boot wiring (init proposes a status note) and the Telegram command layer, so it
lives in its own module to avoid a homeostasis_module <-> telegram_commands
import cycle.
"""

import logging
import time

logger = logging.getLogger(__name__)


def _notify_outbox(ctx, rec):
    """Best-effort Telegram ping that Maria proposed an outbox note.

    Sent as PLAIN TEXT (parse_mode=None): the body carries slash-commands
    (/approve_note, /reject_note) and a filename, all with underscores.
    Telegram Markdown treats '_' as italic; when the underscores balance it
    silently EATS them, so '/approve_note' arrives as '/approvenote' and the
    command no longer works (observed 2026-06-09: the operator saw a command
    without its underscore). No API error is raised, so the markdown->plain
    fallback never fires -- hence we must force plain here.
    """
    msg = (
        f"[Outbox] Maria proponuje notatke {rec['id']} ({rec['filename']}.txt).\n"
        f"--- podglad ---\n{rec['content'][:300]}\n---\n"
        f"Zatwierdz: /approve_note {rec['id']} | odrzuc: /reject_note {rec['id']}"
    )
    try:
        notifier = getattr(ctx, "telegram_notifier", None)
        if notifier is not None and hasattr(notifier, "send_raw"):
            notifier.send_raw(msg, parse_mode=None)
        else:
            bridge = getattr(ctx, "telegram_bridge", None)
            bot = getattr(bridge, "bot", None) if bridge else None
            if bot is not None and hasattr(bot, "send_message"):
                bot.send_message(msg, parse_mode=None)
    except Exception:
        # Warning (not debug): a swallowed notify failure would otherwise strand
        # an unannounced PENDING proposal that the operator never sees.
        logger.warning("[Outbox] notify failed", exc_info=True)


def _latest_exam_summary():
    """Last exam result as a one-line summary (e.g. '83% (closed-book,
    independent)'), or None. Tails exam_results.jsonl from the END so the large
    history file (thousands of rows) stays cheap to read each propose; fully
    best-effort -- any error returns None rather than breaking the note."""
    try:
        import json as _json
        from maria_core.sys.config import EXAM_RESULTS
        if not EXAM_RESULTS.exists():
            return None
        with open(EXAM_RESULTS, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            data = b""
            while size > 0 and data.count(b"\n") < 2:
                step = min(4096, size)
                size -= step
                f.seek(size)
                data = f.read(step) + data
        rec = None
        for line in reversed(data.splitlines()):
            if line.strip():
                rec = _json.loads(line)
                break
        if not rec or rec.get("score") is None:
            return None
        pct = round(float(rec["score"]) * 100)
        book = "closed-book" if rec.get("closed_book") else "open-book"
        indep = ", independent" if rec.get("grader_independent") else ""
        return f"{pct}% ({book}{indep})"
    except Exception:
        return None


def _propose_outbox_status_note(ctx, reason="autonomous"):
    """Gather live status -> compose a deterministic note -> PROPOSE it (pending
    row + Telegram ping). NEVER writes -- the write is operator-gated via
    /approve_note. Returns the proposal record or None.

    Dedup: never piles up (skips if a proposal is already pending); autonomous
    calls also respect a min wall-clock gap so the tick cannot spam proposals."""
    store = getattr(ctx, "outbox_store", None)
    if store is None:
        return None
    try:
        from agent_core.hands import outbox as _outbox

        # Wall-clock throttle for the autonomous tick (cheap pre-check; the hard
        # one-at-a-time invariant is enforced atomically by propose_if_none_pending).
        if reason == "autonomous":
            gap = store.seconds_since_last()
            if gap is not None and gap < _outbox.AUTONOMOUS_PROPOSE_MIN_GAP_SECONDS:
                return None

        core = getattr(ctx, "homeostasis_core", None)
        gs = getattr(ctx, "goal_store", None)

        # -- vitals (always shown; '?' when a source is missing) --
        mode, health, alerts, tick = "?", "?", None, None
        state = getattr(core, "state", None) if core is not None else None
        if state is not None:
            mode = state.mode.value
            health = round(state.health_score, 2)
            try:
                alerts = len(state.alerts)
            except Exception:
                alerts = None
        if core is not None:
            tick = getattr(core, "_tick_count", None)

        # -- goals: authoritative active set (NOT a hand-rolled status filter --
        #    the 'active' taxonomy lives in GoalStore) + per-type breakdown +
        #    proposed count --
        active_goals, proposed_goals, goals_breakdown = "?", None, None
        if gs is not None:
            try:
                act = list(gs.get_active()) if hasattr(gs, "get_active") else []
                active_goals = len(act)
                bt = {}
                for g in act:
                    t = getattr(getattr(g, "type", None), "value", "?")
                    bt[t] = bt.get(t, 0) + 1
                if bt:
                    goals_breakdown = ", ".join(
                        f"{n} {t}"
                        for t, n in sorted(bt.items(), key=lambda kv: (-kv[1], kv[0]))
                    )
            except Exception:
                pass
            try:
                proposed_goals = gs.stats().get("proposed")
            except Exception:
                pass

        # -- age in days (identity) --
        uptime_days = None
        try:
            import datetime as _dt
            from agent_core.consciousness.identity_store import MARIA_BIRTH_DATE
            birth = _dt.datetime.strptime(MARIA_BIRTH_DATE, "%Y-%m-%d")
            uptime_days = (_dt.datetime.now() - birth).days
        except Exception:
            pass

        # -- learning: knowledge progress + last exam score --
        knowledge = None
        ka = getattr(ctx, "knowledge_analyzer", None)
        if ka is not None:
            try:
                snap = ka.get_knowledge_snapshot()
                if snap:
                    done = len(snap.get("files_by_status", {}).get("completed", []))
                    total = snap.get("total_files", 0)
                    knowledge = f"{done}/{total} complete"
            except Exception:
                pass
        last_exam = _latest_exam_summary()

        # -- cognition: planner activity + self-model capability count --
        planner = None
        pc = getattr(ctx, "planner_core", None)
        if pc is not None:
            try:
                st = pc.get_status()
                planner = (
                    f"{st.get('total_cycles', 0)} cycles, "
                    f"{st.get('total_plans_executed', 0)} plans"
                )
            except Exception:
                pass
        capabilities = None
        sp = getattr(ctx, "self_perception", None)
        if sp is not None:
            try:
                cap_snap = sp.get_latest() if hasattr(sp, "get_latest") else None
                caps = (cap_snap or {}).get("capabilities", {}) or {}
                if caps.get("total") is not None:
                    restricted = caps.get("restricted") or 0
                    rstr = f", {restricted} restricted" if restricted else ""
                    capabilities = (
                        f"{caps.get('total', 0)} ({caps.get('free', 0)} free, "
                        f"{caps.get('guarded', 0)} guarded{rstr})"
                    )
            except Exception:
                pass

        fields = {
            "ts_label": time.strftime("%Y-%m-%d %H:%M"),
            "mode": mode,
            "health": health,
            "alerts": alerts,
            "tick": tick,
            "active_goals": active_goals,
            "proposed_goals": proposed_goals,
            "goals_breakdown": goals_breakdown,
            "uptime_days": uptime_days,
            "knowledge": knowledge,
            "last_exam": last_exam,
            "planner": planner,
            "capabilities": capabilities,
            "note": reason,
        }
        content = _outbox.compose_status_note(fields)
        filename = f"maria_status_{int(time.time())}"
        rec = store.propose_if_none_pending(filename, content, reason=reason)
        if rec is None:
            return None  # one already pending (atomic dedup)
        _notify_outbox(ctx, rec)
        return rec
    except Exception:
        logger.warning("[Outbox] propose failed", exc_info=True)
        return None
