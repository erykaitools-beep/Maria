"""Self-development bridge: proactive nudge for stuck recurring ideas.

The board (SelfDevJournal) shows what Maria keeps asking for. This bridge is
the missing link to ACTION for operator-territory ideas (~95% of meta-goals,
which Maria cannot and must not execute herself): instead of re-proposing the
same idea thousands of times into the void, Maria pings the operator ONCE per
recurring theme and waits.

It creates NO goals and takes NO autonomous action (the safest possible bridge,
even safer than the PROPOSED-goal escalator). It only:
  1. finds a stuck, high-recurrence board theme not recently alerted,
  2. asks the operator (Telegram) whether to take it on, with a token,
  3. on /approve_dev <token>, resolves the linked creative bulletin entries
     with reason "operator_acknowledged".

That close-reason is whitelisted by the board's realized-join, so an
acknowledged theme flips from "UTKNAL" to "zrealizowane" on /samorozwoj -- the
loop closes visibly. Mirrors /approve_repair (ADR-031): approve = operator
takes over + closure, NOT autonomous execution.
"""

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from agent_core.self_development.title_normalizer import normalize_title

logger = logging.getLogger(__name__)

# Only nudge about themes Maria has raised at least this many times -- so the
# ping is reserved for the genuinely persistent ideas, not every stuck theme.
ALERT_MIN_ASKED = 50
# Do not re-ping the same theme more often than this.
ALERT_COOLDOWN_DAYS = 7.0
# Global pace across ALL themes: at most one nudge per this many days. A backlog
# of stuck themes then surfaces one idea at a time over days, instead of a burst
# of pings in a single evening (each theme keeps its own ALERT_COOLDOWN_DAYS on
# top of this). Without it, the 30-min Phase 21 cadence would fire one ping per
# stuck theme back-to-back -- the very "wall of pings" this bridge exists to end.
NUDGE_PACE_DAYS = 1.0

_SUPPRESSION_REASON_CODE = "creative_loop_suppression"
_ACK_REASON = "operator_acknowledged"


class SelfDevBridge:
    """Turns recurring stuck self-dev themes into one operator nudge."""

    def __init__(
        self,
        board,                      # SelfDevJournal
        bulletin_store,
        data_dir: str,
        alert_min_asked: int = ALERT_MIN_ASKED,
        cooldown_days: float = ALERT_COOLDOWN_DAYS,
        pace_days: float = NUDGE_PACE_DAYS,
    ):
        self._board = board
        self._bulletin = bulletin_store
        self._alerts_path = os.path.join(data_dir, "self_dev_alerts.json")
        self._alert_min_asked = alert_min_asked
        self._cooldown_sec = cooldown_days * 86400.0
        self._pace_sec = pace_days * 86400.0
        self._lock = threading.Lock()

    # --- pending-alert state (token -> record) ----------------------------

    def _load_pending(self) -> Dict[str, dict]:
        if not os.path.exists(self._alerts_path):
            return {}
        try:
            with open(self._alerts_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            return {}

    def _save_pending(self, data: Dict[str, dict]) -> None:
        tmp = self._alerts_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self._alerts_path)

    @staticmethod
    def _token_for(norm: str) -> str:
        return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:6]

    # --- reading creative bulletin entries --------------------------------

    def _creative_entries(self) -> List[Any]:
        """Open creative IMPROVEMENT advisories (excluding suppression posts)."""
        try:
            from agent_core.bulletin.bulletin_model import EntryType
            entries = self._bulletin.get_by_type(EntryType.IMPROVEMENT)
        except Exception as e:
            logger.debug(f"[SelfDevBridge] bulletin read failed: {e}")
            return []
        out = []
        for e in entries:
            rc = getattr(e, "reason_code", "") or ""
            if rc.startswith("creative_") and rc != _SUPPRESSION_REASON_CODE:
                out.append(e)
        return out

    def _entry_ids_for_norm(self, norm: str) -> List[str]:
        """Entry ids of creative advisories whose title maps to this theme."""
        ids = []
        for e in self._creative_entries():
            if normalize_title(getattr(e, "topic", "")) == norm:
                ids.append(e.entry_id)
        return ids

    # --- alert selection --------------------------------------------------

    def find_alert(self, now: Optional[float] = None):
        """Return the top stuck theme worth nudging about, or None.

        Picks the highest-recurrence stuck theme that clears the ask floor and
        is not within cooldown. Returns at most one theme per call so Maria
        nudges gently (one idea at a time), not a wall of pings.

        Honours the global pace: if any theme was nudged within the pace window,
        returns None without even scanning the board, so a backlog surfaces one
        idea per day rather than one-per-theme back-to-back on the 30-min tick.
        """
        if now is None:
            now = time.time()
        pending = self._load_pending()
        # Global daily pace gate (cheap, runs before the multi-MB board scan).
        last_nudge = max(
            (r.get("ts", 0.0) for r in pending.values()), default=0.0
        )
        if last_nudge and (now - last_nudge) < self._pace_sec:
            return None
        themes = self._board.build_board(top_n=10, now=now)
        for t in themes:  # already sorted by asked_count desc
            if not t.stuck:
                continue
            if t.asked_count < self._alert_min_asked:
                continue
            norm = t.norm_aliases[0] if t.norm_aliases else ""
            if not norm:
                continue
            rec = pending.get(self._token_for(norm))
            if rec and (now - rec.get("ts", 0.0)) < self._cooldown_sec:
                continue  # still in cooldown
            return t
        return None

    def register_alert(self, theme, now: Optional[float] = None) -> str:
        """Persist a pending alert for the theme; return its token."""
        if now is None:
            now = time.time()
        norm = theme.norm_aliases[0] if theme.norm_aliases else ""
        token = self._token_for(norm)
        with self._lock:
            pending = self._load_pending()
            pending[token] = {
                "norm": norm,
                "title": theme.display_title,
                "asked": theme.asked_count,
                "entry_ids": self._entry_ids_for_norm(norm),
                "ts": now,
                "acknowledged": False,
            }
            self._save_pending(pending)
        return token

    def build_alert_text(self, theme, token: str) -> str:
        """Maria's first-person nudge (plain text, no emoji -- ADR-005)."""
        return (
            f"Wracam do pomyslu na samorozwoj: \"{theme.display_title}\".\n"
            f"Podsuwam go {theme.asked_count}x od {theme.days_old:.0f} dni "
            f"i nic sie z tym nie dzieje. Chcesz to przejac?\n"
            f"/approve_dev {token} - oznacze jako przejete przez Ciebie."
        )

    def maybe_alert(self, notify_fn, now: Optional[float] = None) -> Optional[str]:
        """Find one alertable theme, register it, and send the nudge.

        Returns the sent text, or None if nothing was alertable / send failed.
        Called off-tick (Phase 21) so the board read never stalls the heartbeat.
        """
        if now is None:
            now = time.time()
        theme = self.find_alert(now=now)
        if theme is None:
            return None
        token = self.register_alert(theme, now=now)
        text = self.build_alert_text(theme, token)
        try:
            notify_fn(text)
        except Exception as e:
            logger.warning(f"[SelfDevBridge] notify failed: {e}")
            return None
        logger.info("[SelfDevBridge] nudged operator about '%s' (token=%s)",
                    theme.display_title, token)
        return text

    # --- operator acknowledgement (/approve_dev) --------------------------

    def acknowledge(self, token: str, now: Optional[float] = None) -> str:
        """Resolve the theme's creative advisories as operator-acknowledged.

        This is closure, not execution (mirrors /approve_repair): the operator
        takes the idea on; Maria stops re-proposing it and the board flips it to
        'zrealizowane'. Returns a human confirmation string.
        """
        if now is None:
            now = time.time()
        with self._lock:
            pending = self._load_pending()
            rec = pending.get(token)
            if rec is None:
                return f"Nie znam zgloszenia '{token}'. Sprawdz /samorozwoj."
            # Re-resolve live (entry_ids cached at alert time may have grown).
            norm = rec.get("norm", "")
            entry_ids = set(rec.get("entry_ids", [])) | set(
                self._entry_ids_for_norm(norm)
            )
            resolved = 0
            for eid in entry_ids:
                try:
                    if self._bulletin.resolve(eid, reason=_ACK_REASON):
                        resolved += 1
                except Exception as e:
                    logger.debug(f"[SelfDevBridge] resolve {eid} failed: {e}")
            rec["acknowledged"] = True
            rec["ack_ts"] = now
            rec["resolved_count"] = resolved
            pending[token] = rec
            self._save_pending(pending)
        # Let the board reflect the change on next read.
        try:
            self._board.invalidate_cache()
        except Exception:
            pass
        title = rec.get("title", token)
        return (
            f"Przejete: \"{title}\". Zamknelam {resolved} powiazanych wpisow "
            f"(operator_acknowledged). Temat zniknie z 'UTKNAL' na /samorozwoj."
        )
