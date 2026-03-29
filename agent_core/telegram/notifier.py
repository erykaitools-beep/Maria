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
from typing import Any, Dict, List, Optional

from agent_core.telegram.bot import TelegramBot

logger = logging.getLogger(__name__)

# Cooldowns per alert category (seconds)
# Prevents spamming operator with same type of alert
ALERT_COOLDOWNS: Dict[str, float] = {
    "creative_tension": 7200,     # 2h - tensions don't change fast
    "creative_meta_goal": 7200,   # 2h - batch meta-goal summaries
    "self_analysis": 14400,       # 4h - analysis is expensive
    "needs_human": 3600,          # 1h - K9 signal
    "health_drop": 1800,          # 30min - urgent
    "mode_change": 600,           # 10min - mode transitions
    "consecutive_failure": 3600,  # 1h - K7 blocks
    "startup": 0,                 # always send
}

# Default cooldown for unknown categories
DEFAULT_COOLDOWN = 3600


class TelegramNotifier:
    """
    High-level notification layer.

    Formats alerts from Maria's subsystems into readable Telegram messages.
    Tracks cooldowns to avoid spamming operator.
    """

    def __init__(self, bot: Optional[TelegramBot] = None):
        self._bot = bot or TelegramBot()
        self._last_sent: Dict[str, float] = {}  # category -> timestamp

    @property
    def configured(self) -> bool:
        return self._bot.configured

    def _can_send(self, category: str) -> bool:
        """Check if cooldown for this category has expired."""
        cooldown = ALERT_COOLDOWNS.get(category, DEFAULT_COOLDOWN)
        if cooldown == 0:
            return True
        last = self._last_sent.get(category, 0)
        return (time.time() - last) >= cooldown

    def _mark_sent(self, category: str) -> None:
        self._last_sent[category] = time.time()

    # -- Public notification methods (called by subsystems) --

    def notify_startup(self) -> bool:
        """Send startup notification."""
        text = (
            "*M.A.R.I.A. uruchomiona*\n\n"
            "Homeostasis aktywna. Czekam na polecenia."
        )
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("startup")
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
    ) -> bool:
        """Send K12 self-analysis report."""
        if not self._can_send("self_analysis"):
            return False

        lines = ["*Raport K12 Self-Analysis:*\n"]
        if summary:
            lines.append(summary[:500])
            lines.append("")
        if recommendations:
            lines.append("*Rekomendacje:*")
            for r in recommendations[:5]:
                lines.append(f"- {r[:150]}")

        text = "\n".join(lines)
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("self_analysis")
        return ok

    def notify_needs_human(self, reason: str = "") -> bool:
        """Send K9 needs_human signal."""
        if not self._can_send("needs_human"):
            return False

        text = (
            "*K9 Meta-Cognition: potrzebuje pomocy*\n\n"
            f"{reason[:300]}" if reason else
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
        """Send health drop alert."""
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
        return ok

    def notify_mode_change(
        self, from_mode: str, to_mode: str, trigger: str = ""
    ) -> bool:
        """Send mode transition alert (only for degraded modes)."""
        # Only notify on degradation (not recovery back to ACTIVE)
        if to_mode == "active":
            return False
        if not self._can_send("mode_change"):
            return False

        text = (
            f"*Zmiana trybu: {from_mode} -> {to_mode}*"
        )
        if trigger:
            text += f"\nPrzyczyna: {trigger}"
        ok = self._bot.send_message(text)
        if ok:
            self._mark_sent("mode_change")
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

    def notify_effector_request(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        goal_description: str = "",
        authority_level: str = "",
        request_id: str = "",
    ) -> bool:
        """
        Send effector approval request to operator (Phase 5).

        Always sent (no cooldown) - operator needs to see every request.
        """
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
        status = "OK" if success else "BLAD"
        lines = [
            f"*Efektor wynik: {tool_name} [{status}]*",
        ]
        if summary:
            lines.append(summary[:300])

        text = "\n".join(lines)
        return self._bot.send_message(text)

    def send_raw(self, text: str) -> bool:
        """Send arbitrary message (no cooldown)."""
        return self._bot.send_message(text)

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
