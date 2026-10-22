"""
Telegram Notifier for M.A.R.I.A.

Formats and sends alerts from subsystems to operator via Telegram.
Rate-limited to prevent spam. Each alert category has its own cooldown.

Sources:
- K13 Creative: tension detection, meta-goals
- K12 Self-Analysis: recommendations
- K9 Meta-Cognition: needs_human() signal
- Homeostasis: health drop, mode changes
- K7: consecutive failure blocks
"""

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent_core.telegram.bot import TelegramBot

logger = logging.getLogger(__name__)

# File-based startup dedup (survives restarts)
_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_STARTUP_NOTIFY_FILE = _META_DIR / "last_startup_notify.txt"
_STARTUP_COOLDOWN_SEC = 21600  # 6h - prevents spam on restarts

# Cooldowns per alert category (seconds)
# Prevents spamming operator with same type of alert
ALERT_COOLDOWNS: Dict[str, float] = {
    "creative_tension": 7200,     # 2h - tensions don't change fast
    "creative_meta_goal": 7200,   # 2h - batch meta-goal summaries
    "self_analysis": 14400,       # 4h - analysis is expensive
    "needs_human": 21600,         # 6h - K9 signal (LOW_CONFIDENCE stays hot under material starvation; 1h spammed)
    "health_drop": 1800,          # 30min - urgent
    "mode_change": 600,           # 10min - mode transitions
    "mode_change_survival": 600,  # 10min - SURVIVAL demotion (own counter so a
                                  # recent REDUCED alert cannot swallow it)
    "consecutive_failure": 3600,  # 1h - K7 blocks
    "stuck_planner": 7200,        # 2h - stuck loop detection
    "learning_progress": 1800,    # 30min - CDL progress updates
    "learning_complete": 0,       # always send - operator requested this
    "goal_complete": 0,           # always send - discrete goal closure (rare, event-driven)
    "feed_rot": 3600,             # 1h - deduped at source (goal.metadata["feed_rot_alerted"])
    "startup": 0,                 # always send
    # Effector approval/result/incident: no time cooldown (each is a distinct
    # operator decision), but they DO honor quiet hours -- the request survives
    # in the approval queue (/approve_ef), so a night ping only defers, never
    # drops. Not in QUIET_HOURS_CRITICAL: an approval can wait until morning.
    "effector_request": 0,
    "effector_result": 0,
    "effector_incident": 0,
}

# Default cooldown for unknown categories
DEFAULT_COOLDOWN = 3600

# Alert categories that pierce the operator's quiet hours; everything else waits
# until morning. Both are the operator's call -- he is blocked (needs_human) or
# something is actively breaking (consecutive_failure).
QUIET_HOURS_CRITICAL: frozenset = frozenset({
    "needs_human",
    "consecutive_failure",
    # A SURVIVAL demotion means real hardware trouble -- imminent OOM, full disk,
    # thermal, a hung model -- never CPU alone (that tops out at REDUCED). The CPU
    # filter in notify_mode_change still runs first, so self-inflicted load cannot
    # reach this; only a genuine failure pierces quiet hours. REDUCED stays
    # deferrable (category "mode_change").
    "mode_change_survival",
})


class TelegramNotifier:
    """
    High-level notification layer.

    Formats alerts from Maria's subsystems into readable Telegram messages.
    Tracks cooldowns to avoid spamming operator.
    """

    def __init__(self, bot: Optional[TelegramBot] = None):
        self._bot = bot or TelegramBot()
        self._last_sent: Dict[str, float] = {}  # category -> timestamp
        # Returns True when the local clock is inside the operator's quiet
        # window. Injected during wiring; None means quiet hours are not enforced
        # (fail-open -- an un-wired notifier still sends).
        self._quiet_hours_check: Optional[Callable[[], bool]] = None
        # Health-drop edge state: True once an ongoing (non-CPU) drop has been
        # announced, so it is announced ONCE per episode instead of re-firing
        # every cooldown while the same condition sits stuck. The tick calls
        # reset_health_drop_edge() on recovery (health >= 0.7) to re-arm it.
        self._health_drop_active = False

    @property
    def configured(self) -> bool:
        return self._bot.configured

    def set_quiet_hours_check(self, fn: Optional[Callable[[], bool]]) -> None:
        """Inject the quiet-hours predicate (fn() -> True when it is quiet now).

        The window itself lives in OperatorModel (the SSoT); resolving it is the
        wiring's job, so the notifier stays free of that dependency and a test
        can drive quiet hours with a plain lambda.
        """
        self._quiet_hours_check = fn

    def in_quiet_hours(self) -> bool:
        """Is it the operator's quiet window right now? Fail-open on any error.

        Public so a caller that delivers via send_raw (which bypasses _can_send
        -- the outbox note proposal, a self-repair alert, a vision advisory) can
        defer its own night ping. Safe to defer only when the underlying item
        survives the drop: the note stays PENDING (/list_notes), the repair task
        stays queued (/pending_repairs), a vision sighting is advisory. Silencing
        the operator forever on a bad read is worse than one late ping, so an
        unset or throwing predicate resolves to 'not quiet'.
        """
        if self._quiet_hours_check is None:
            return False
        try:
            return bool(self._quiet_hours_check())
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("[Telegram] quiet-hours check failed: %s", e)
            return False

    def _can_send(self, category: str) -> bool:
        """Gate a category on quiet hours first, then its cooldown.

        Quiet hours suppress everything except QUIET_HOURS_CRITICAL. Suppression
        is a plain drop -- there is no queue -- which is why a category that
        cannot afford to be dropped must be critical, not merely cheap to
        re-send.
        """
        if category not in QUIET_HOURS_CRITICAL and self.in_quiet_hours():
            return False
        cooldown = ALERT_COOLDOWNS.get(category, DEFAULT_COOLDOWN)
        if cooldown == 0:
            return True
        last = self._last_sent.get(category, 0)
        return (time.time() - last) >= cooldown

    def _mark_sent(self, category: str) -> None:
        self._last_sent[category] = time.time()

    def notify(self, category: str, text: str,
               parse_mode: Optional[str] = "Markdown") -> bool:
        """Generic categorized alert: gate on _can_send(category), then send.

        The typed notify_* methods are the preferred API; this facade serves
        call-sites that already hold their own formatted text and only need a
        category's quiet-hours + cooldown gating (learning_complete /
        learning_progress / goal_complete / feed_rot). Routing through
        _can_send -- NOT send_raw -- is the whole point: send_raw bypasses quiet
        hours by design (it is the /restart reply channel), so a naive facade
        would ping the operator at night. Categories absent from
        QUIET_HOURS_CRITICAL (all four above) are dropped overnight, not queued.

        Historical: five call-sites (handlers close/progress, planner harvest +
        feed_rot) called this method before it existed. The AttributeError was
        swallowed by their `except`, so every one of those alerts was silently
        dead. Restored 2026-07-17.
        """
        if not text:
            return False
        if not self._can_send(category):
            return False
        ok = self._bot.send_message(text, parse_mode=parse_mode)
        if ok:
            self._mark_sent(category)
        return ok

    # -- Public notification methods (called by subsystems) --

    def notify_startup(self) -> bool:
        """Send startup notification (file-based dedup survives restarts)."""
        # Check file-based cooldown to prevent spam on rapid restarts
        try:
            if _STARTUP_NOTIFY_FILE.exists():
                last_ts = float(_STARTUP_NOTIFY_FILE.read_text().strip())
                if (time.time() - last_ts) < _STARTUP_COOLDOWN_SEC:
                    logger.info(
                        "[Telegram] Startup notification suppressed "
                        "(last sent %.0fs ago, cooldown %ds)",
                        time.time() - last_ts, _STARTUP_COOLDOWN_SEC,
                    )
                    return False
        except (ValueError, OSError):
            pass  # corrupted file or read error - proceed with send

        text = (
            "*M.A.R.I.A. uruchomiona*\n\n"
            "Homeostasis aktywna. Czekam na polecenia."
        )
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("startup")
            # Persist to file for cross-restart dedup
            try:
                _STARTUP_NOTIFY_FILE.parent.mkdir(parents=True, exist_ok=True)
                _STARTUP_NOTIFY_FILE.write_text(str(time.time()))
            except OSError:
                pass
        return ok

    def notify_creative_tensions(
        self, tensions: List[Dict[str, Any]]
    ) -> bool:
        """
        Send creative module tension report.

        Args:
            tensions: List of tension dicts from CreativeModule
        """
        if not tensions:
            return False
        if not self._can_send("creative_tension"):
            return False

        lines = ["*Wykryte napieica (K13 Creative):*\n"]
        for t in tensions[:5]:  # Max 5
            category = t.get("category", "?")
            severity = t.get("severity", 0)
            evidence = t.get("evidence", "")
            bar = _severity_bar(severity)
            lines.append(f"{bar} *{category}* ({severity:.0%})")
            if evidence:
                lines.append(f"   {evidence[:120]}")
            lines.append("")

        text = "\n".join(lines)
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("creative_tension")
        return ok

    def notify_creative_meta_goals(
        self, meta_goals: List[Dict[str, Any]]
    ) -> bool:
        """Send creative module meta-goal proposals."""
        if not meta_goals:
            return False
        if not self._can_send("creative_meta_goal"):
            return False

        lines = ["*Propozycje celow (K13 Creative):*\n"]
        for g in meta_goals[:5]:
            desc = g.get("description", "?")
            risk = g.get("risk_level", "?")
            lines.append(f"- {desc} (ryzyko: {risk})")

        lines.append("\nOdpisz 'status' aby sprawdzic stan.")
        text = "\n".join(lines)
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("creative_meta_goal")
        return ok

    def notify_self_analysis(
        self,
        summary: str,
        recommendations: List[str],
        systemic_issues: Optional[List[str]] = None,
    ) -> bool:
        """Send K12 self-analysis report."""
        if not self._can_send("self_analysis"):
            return False

        lines = ["*Raport K12 Self-Analysis:*\n"]
        if summary:
            lines.append(summary[:500])
            lines.append("")
        # Above the recommendations on purpose: a cross-cutting finding ("the
        # recommendation loop itself is broken") outranks the individual topics
        # it explains, and the operator reads top-down on a phone.
        if systemic_issues:
            lines.append("*Problemy ukladowe:*")
            for issue in systemic_issues[:4]:
                lines.append(f"- {issue[:280]}")
            lines.append("")
        if recommendations:
            lines.append("*Rekomendacje:*")
            for r in recommendations[:5]:
                # 280 > REC_LINE_MAX (240): the formatter already trims each line
                # to a whole finding, so this is just a backstop, not a mid-reason
                # cut. The old 150 sliced the description off exactly where the
                # number lived.
                lines.append(f"- {r[:280]}")

        text = "\n".join(lines)
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("self_analysis")
        return ok

    def notify_critique(self, findings: List[Dict]) -> bool:
        """Send Faza G critique findings (CRITICAL only)."""
        if not self._can_send("critique"):
            return False

        lines = ["*Faza G - Krytyk wiedzy:*\n"]
        for f in findings[:3]:
            cat = f.get("category", "?")
            topic = f.get("topic", "?")
            desc = f.get("description", "")[:120]
            action = f.get("suggested_action", "?")
            lines.append(f"[!] {cat}: {topic}")
            lines.append(f"    {desc}")
            lines.append(f"    -> {action}")
            lines.append("")

        text = "\n".join(lines)
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("critique")
        return ok

    def notify_needs_human(self, reason: str = "") -> bool:
        """Send K9 needs_human signal."""
        if not self._can_send("needs_human"):
            return False

        text = (
            f"*K9 Meta-Cognition: potrzebuje pomocy*\n\n{reason[:300]}"
            if reason else
            "*K9 Meta-Cognition: potrzebuje pomocy*\n\n"
            "Spadek pewnosci ponizej progu. Sprawdz stan systemu."
        )
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("needs_human")
        return ok

    def notify_health_drop(
        self, health_score: float, mode: str, alerts: List[str]
    ) -> bool:
        """Send health drop alert -- once per episode, and never for self-load.

        Two guards keep a chronically-loaded mini-PC from spamming the operator
        (a 07-18 audit found 21 of a day's gated alerts were this -- all CPU):

        1. CPU-only drops are self-inflicted. Maria's own local inference
           (ollama / LLaVA / exams) pegs this CPU-only box, dragging health below
           0.7 with nothing for the operator to act on. Mirror the identical
           filter in notify_mode_change and skip. A drop carrying ANY non-CPU
           alert (RAM, temp, disk, coherence) still goes out.
        2. Edge-trigger: announce a (non-CPU) drop ONCE on entry, then stay quiet
           while it persists. reset_health_drop_edge() re-arms it when the tick
           sees health recover to >= 0.7, so the next genuine drop alarms again
           instead of re-firing every cooldown on a stuck condition.
        """
        # 1. Self-inflicted CPU load -> nothing to act on (see notify_mode_change).
        if alerts and all("CPU" in a for a in alerts):
            return False
        # 2. Already announced this ongoing drop -- wait for recovery to re-arm.
        if self._health_drop_active:
            return False
        if not self._can_send("health_drop"):
            return False

        lines = [
            f"*Health drop: {health_score:.0%}*",
            f"Mode: {mode}",
        ]
        if alerts:
            lines.append("\nAlerty:")
            for a in alerts[:5]:
                lines.append(f"- {a[:100]}")

        text = "\n".join(lines)
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("health_drop")
            self._health_drop_active = True
        return ok

    def reset_health_drop_edge(self) -> None:
        """Re-arm the health-drop edge once the system recovers (health >= 0.7).

        Called by the homeostasis tick when health climbs back above the alert
        threshold. Without it, edge-triggering would announce the first drop and
        then never again. Idempotent -- safe to call every recovered tick.
        """
        self._health_drop_active = False

    def notify_mode_change(
        self,
        from_mode: str,
        to_mode: str,
        trigger: str = "",
        alerts: Optional[List[str]] = None,
    ) -> bool:
        """Send mode transition alert (only for degraded modes).

        Self-inflicted CPU demotions are dropped. Maria's own local inference
        (ollama / LLaVA / exams) saturates the CPU on this mini-PC, which trips a
        REDUCED demotion, which fired a Telegram alert -- 31/31 mode-change alerts
        in the 07-15 audit came from her own load and told the operator nothing
        to act on. When EVERY alert behind the transition is a CPU alert, skip
        it; a non-CPU alert (RAM, temp, disk, coherence) means something else and
        still goes out. `alerts` is the structured trigger list; `trigger` stays
        the human-readable string for the message body.
        """
        # Only notify on degradation (not recovery back to ACTIVE)
        if to_mode == "active":
            return False
        if alerts and all("CPU" in a for a in alerts):
            return False
        # SURVIVAL is a genuine-failure mode and pierces quiet hours; REDUCED is
        # deferrable. The CPU filter above already ran, so a survival demotion
        # here is never self-inflicted CPU.
        category = "mode_change_survival" if to_mode == "survival" else "mode_change"
        if not self._can_send(category):
            return False

        text = (
            f"*Zmiana trybu: {from_mode} -> {to_mode}*"
        )
        if trigger:
            text += f"\nPrzyczyna: {trigger}"
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent(category)
        return ok

    def notify_consecutive_failures(
        self, action_type: str, count: int
    ) -> bool:
        """Send K7 consecutive failure block alert."""
        if not self._can_send("consecutive_failure"):
            return False

        text = (
            f"*K7: Zablokowano '{action_type}'*\n\n"
            f"{count} kolejnych niepowodzen. "
            f"Akcja zablokowana do auto-resetu (30 min)."
        )
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("consecutive_failure")
        return ok

    def notify_stuck_planner(
        self,
        action: str,
        goal_id: str,
        goal_description: str = "",
        count: int = 0,
        reason: str = "",
        cooldown_minutes: int = 30,
    ) -> bool:
        """Send stuck planner loop alert to operator."""
        if not self._can_send("stuck_planner"):
            return False

        desc = goal_description[:80] if goal_description else goal_id
        text = (
            f"*Utknelam: {action} na '{desc}'*\n\n"
            f"Failuje {count}x z rzedu.\n"
            f"Powod: {reason[:200]}\n"
            f"Pomijam cel na {cooldown_minutes} min."
        )
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("stuck_planner")
        return ok

    def notify_stuck(self, message: str) -> bool:
        """Send pre-formatted stuck diagnosis message (Level 6)."""
        if not self._can_send("stuck_planner"):
            return False
        ok = self._bot.send_message(message)
        if ok:
            self._mark_sent("stuck_planner")
        return ok

    # Quiet-hours coverage note. The effector methods below go through _can_send
    # (categories with cooldown 0, so quiet hours are their only gate) -- safe
    # because the request survives in the approval queue. send_raw() still
    # bypasses _can_send by design (it is the delivery channel for the /restart
    # reply, the proactive scheduler's own windowed contacts, and code-task
    # results the operator asked for); the send_raw callers that SHOULD honor
    # quiet hours (outbox note, self-repair alert, vision advisory) call
    # in_quiet_hours() themselves before sending. notify_startup keeps its own
    # file cooldown and must arrive after a restart.
    def notify_effector_request(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        goal_description: str = "",
        authority_level: str = "",
        request_id: str = "",
    ) -> bool:
        """Send effector approval request to operator (Phase 5).

        Honors quiet hours: the request is already persisted in the approval
        queue (/approve_ef) before this is called, so a deferred night ping only
        delays the notice, never the request.
        """
        if not self._can_send("effector_request"):
            return False
        args_str = ", ".join(
            f"{k}={str(v)[:60]}" for k, v in list(tool_args.items())[:5]
        )
        lines = [
            f"*Efektor: {tool_name}*",
            f"Cel: {goal_description[:120]}" if goal_description else "",
            f"Args: {args_str}" if args_str else "",
            f"Level: {authority_level}" if authority_level else "",
        ]
        if request_id:
            prefix = request_id[:12] if len(request_id) > 12 else request_id
            lines.append(f"\n/efapprove {prefix}")
            lines.append(f"/efreject {prefix}")

        text = "\n".join(line for line in lines if line)
        return self._bot.send_message(text)

    def notify_effector_result(
        self,
        tool_name: str,
        success: bool,
        summary: str = "",
    ) -> bool:
        """Send effector execution result to operator (Phase 5)."""
        if not self._can_send("effector_result"):
            return False
        status = "OK" if success else "BLAD"
        lines = [
            f"*Efektor wynik: {tool_name} [{status}]*",
        ]
        if summary:
            lines.append(summary[:300])

        text = "\n".join(lines)
        return self._bot.send_message(text)

    def notify_effector_incident(self, task, outcome) -> bool:
        """Report persistent effector failure (coordinator: 3× retry exhausted).

        Honors quiet hours: the failure is also posted to the bulletin, so a
        deferred night ping is not the only record.
        """
        if not self._can_send("effector_incident"):
            return False
        n = len(outcome.attempts)
        last_err = outcome.attempts[-1].error if outcome.attempts else "-"
        lines = [
            f"*Efektor INCIDENT: {task.tool_name}*",
            f"Status: {outcome.status.value} po {n}× probach",
            f"Czas laczny: {outcome.total_duration_s:.1f}s",
            f"Ostatni blad: {last_err[:120]}",
        ]
        if task.tool_args:
            args_s = str(task.tool_args)[:120]
            lines.append(f"Argumenty: {args_s}")
        return self._bot.send_message("\n".join(lines))

    def send_raw(self, text: str, parse_mode: Optional[str] = "Markdown") -> bool:
        """Send arbitrary message (no cooldown).

        parse_mode defaults to Markdown (legacy behavior). Pass parse_mode=None
        for operational pings that carry slash-commands or filenames with
        underscores: Telegram Markdown treats '_' as italic and, when the
        underscores happen to balance, silently EATS them (e.g. '/approve_note'
        renders as '/approvenote' -> the command no longer works). Such a
        message raises no API error, so the bot's markdown->plain fallback never
        triggers.
        """
        return self._bot.send_message(text, parse_mode=parse_mode)

    def get_status(self) -> Dict[str, Any]:
        """Get notifier status for diagnostics."""
        now = time.time()
        cooldown_status = {}
        for cat, cooldown in ALERT_COOLDOWNS.items():
            last = self._last_sent.get(cat, 0)
            remaining = max(0, cooldown - (now - last)) if last > 0 else 0
            cooldown_status[cat] = {
                "cooldown_sec": cooldown,
                "remaining_sec": round(remaining),
                "last_sent": last,
            }
        return {
            "configured": self.configured,
            "cooldowns": cooldown_status,
        }


def _severity_bar(severity: float) -> str:
    """Visual severity indicator."""
    if severity >= 0.8:
        return "[!!!]"
    elif severity >= 0.5:
        return "[!! ]"
    elif severity >= 0.3:
        return "[!  ]"
    return "[   ]"
