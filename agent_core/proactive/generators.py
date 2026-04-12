"""
Proactive contact content generators.

Each generator produces a message string from system data.
All generators are pure functions - no side effects, no LLM calls.
"""

import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from agent_core.homeostasis.time_awareness import TimeAwareness
from agent_core.proactive.proactive_model import ContactReason, ProactiveContact

logger = logging.getLogger(__name__)


class ContentGenerators:
    """
    Generates proactive message content from system state.

    All data is pulled via injected accessor functions (late-binding).
    This avoids circular imports and keeps generators testable.
    """

    def __init__(self):
        # Injected data accessors (set by homeostasis wiring)
        self._get_evaluation: Optional[Callable] = None
        self._get_knowledge_snapshot: Optional[Callable] = None
        self._get_goal_stats: Optional[Callable] = None
        self._get_active_goals: Optional[Callable] = None
        self._get_proposed_goals: Optional[Callable] = None
        self._get_health: Optional[Callable] = None
        self._get_user_name: Optional[Callable] = None
        self._get_user_interests: Optional[Callable] = None
        self._get_recent_achievements: Optional[Callable] = None
        self._get_planner_stats: Optional[Callable] = None
        self._get_mode: Optional[Callable] = None
        self._get_operator_context: Optional[Callable] = None
        self._get_operator_rhythm: Optional[Callable] = None
        self._get_weather: Optional[Callable] = None
        self._get_perception: Optional[Callable] = None

    # -- Accessor setters (called during wiring) --

    def set_evaluation_fn(self, fn: Callable) -> None:
        self._get_evaluation = fn

    def set_knowledge_fn(self, fn: Callable) -> None:
        self._get_knowledge_snapshot = fn

    def set_goal_stats_fn(self, fn: Callable) -> None:
        self._get_goal_stats = fn

    def set_active_goals_fn(self, fn: Callable) -> None:
        self._get_active_goals = fn

    def set_proposed_goals_fn(self, fn: Callable) -> None:
        self._get_proposed_goals = fn

    def set_health_fn(self, fn: Callable) -> None:
        self._get_health = fn

    def set_user_name_fn(self, fn: Callable) -> None:
        self._get_user_name = fn

    def set_user_interests_fn(self, fn: Callable) -> None:
        self._get_user_interests = fn

    def set_recent_achievements_fn(self, fn: Callable) -> None:
        self._get_recent_achievements = fn

    def set_planner_stats_fn(self, fn: Callable) -> None:
        self._get_planner_stats = fn

    def set_mode_fn(self, fn: Callable) -> None:
        self._get_mode = fn

    def set_operator_context_fn(self, fn: Callable) -> None:
        self._get_operator_context = fn

    def set_operator_rhythm_fn(self, fn: Callable) -> None:
        self._get_operator_rhythm = fn

    def set_weather_fn(self, fn: Callable) -> None:
        self._get_weather = fn

    def set_perception_fn(self, fn: Callable) -> None:
        self._get_perception = fn

    # -- Generators --

    def generate(self, reason: ContactReason) -> Optional[ProactiveContact]:
        """Generate a proactive contact for the given reason. Returns None if nothing to say."""
        generators = {
            ContactReason.MORNING_SUMMARY: self._morning_summary,
            ContactReason.EVENING_RECAP: self._evening_recap,
            ContactReason.WEEKLY_REVIEW: self._weekly_review,
            ContactReason.GOAL_ACHIEVED: self._goal_achieved,
            ContactReason.LEARNING_MILESTONE: self._learning_milestone,
            ContactReason.IDLE_CHECKIN: self._idle_checkin,
            ContactReason.INTEREST_MATCH: self._interest_match,
        }
        gen_fn = generators.get(reason)
        if not gen_fn:
            return None
        try:
            return gen_fn()
        except Exception as e:
            logger.debug("Generator %s failed: %s", reason.value, e)
            return None

    def _morning_summary(self) -> Optional[ProactiveContact]:
        """Daily morning briefing with overnight stats."""
        name = self._safe_call(self._get_user_name) or "Operator"
        greeting = TimeAwareness.get_greeting()

        # Check operator context - skip if "urlop" / "nie przeszkadzac"
        op_context = self._safe_call(self._get_operator_context)
        if op_context:
            skip_keywords = ("urlop", "nie przeszkadza", "vacation", "dnd")
            if any(kw in op_context.lower() for kw in skip_keywords):
                return None

        lines = [f"*{greeting}, {name}!*", ""]

        # Operator context (if set)
        if op_context:
            lines.append(f"Pamietam: {op_context}")

        # Weather (M3: filtered through SalienceFilter)
        weather_line = self._safe_call(self._get_weather)
        if weather_line:
            lines.append(weather_line)

        # Perception fusion (Faza 3: holidays, system alerts, workspace)
        perception_lines = self._safe_call(self._get_perception) or []
        for pl in perception_lines:
            lines.append(pl)

        # Health & mode
        health = self._safe_call(self._get_health)
        mode = self._safe_call(self._get_mode) or "?"
        if health is not None:
            lines.append(f"Stan: {health:.0%} health, tryb {mode}")

        # Knowledge stats
        snap = self._safe_call(self._get_knowledge_snapshot)
        if snap:
            total = snap.get("total_files", 0)
            by_status = snap.get("files_by_status", {})
            completed = len(by_status.get("completed", []))
            new_count = len(by_status.get("new", []))
            chunks = snap.get("total_chunks_learned", 0)
            avg_score = snap.get("average_exam_score", 0)
            lines.append(f"Wiedza: {completed}/{total} plikow, {chunks} chunkow")
            if new_count > 0:
                lines.append(f"Nowe do nauki: {new_count}")
            if avg_score > 0:
                lines.append(f"Sredni wynik egzaminow: {avg_score:.0%}")

        # Active goals (compact)
        goals = self._safe_call(self._get_active_goals) or []
        if goals:
            lines.append(f"Aktywne cele: {len(goals)}")
            for g in goals[:3]:
                desc = g.get("description", g.get("title", "?"))[:60]
                lines.append(f"  - {desc}")

        # Proposed goals waiting
        proposed = self._safe_call(self._get_proposed_goals) or []
        if proposed:
            lines.append(f"\nCzeka na zatwierdzenie: {len(proposed)} celow")

        # Evaluation recommendations (max 2, keep it short)
        report = self._safe_call(self._get_evaluation)
        if report and hasattr(report, "recommendations") and report.recommendations:
            lines.append("\nSugestie:")
            for r in report.recommendations[:2]:
                lines.append(f"  - {r[:80]}")

        lines.append("\nMilego dnia!")

        return ProactiveContact(
            reason=ContactReason.MORNING_SUMMARY,
            message="\n".join(lines),
        )

    def _evening_recap(self) -> Optional[ProactiveContact]:
        """Daily evening summary of what happened today."""
        name = self._safe_call(self._get_user_name) or "Operator"

        lines = [f"*Podsumowanie dnia, {name}*", ""]

        # Planner stats (cycles, actions today)
        stats = self._safe_call(self._get_planner_stats)
        if stats:
            cycles = stats.get("total_cycles", 0)
            lines.append(f"Cykli plannera: {cycles}")

        # Learning progress
        snap = self._safe_call(self._get_knowledge_snapshot)
        if snap:
            chunks_24h = snap.get("total_chunks_learned", 0)
            avg_score = snap.get("average_exam_score", 0)
            if chunks_24h > 0:
                lines.append(f"Chunki nauczone: {chunks_24h}")
            if avg_score > 0:
                lines.append(f"Sredni wynik egzaminow: {avg_score:.0%}")

        # Achievements
        achievements = self._safe_call(self._get_recent_achievements) or []
        if achievements:
            lines.append("\nOsiagniecia:")
            for a in achievements[:5]:
                lines.append(f"  - {a}")

        # Health trend
        report = self._safe_call(self._get_evaluation)
        if report and hasattr(report, "metrics"):
            stability = report.metrics.get("system_stability", 0)
            if stability > 0:
                lines.append(f"\nStabilnosc: {stability:.0%}")

        if len(lines) <= 2:
            # Nothing interesting happened
            return None

        lines.append("\nDobranoc!")

        return ProactiveContact(
            reason=ContactReason.EVENING_RECAP,
            message="\n".join(lines),
        )

    def _weekly_review(self) -> Optional[ProactiveContact]:
        """Weekly summary (Sunday evening)."""
        now = datetime.now()
        if now.weekday() != 6:  # Only on Sunday
            return None

        name = self._safe_call(self._get_user_name) or "Operator"
        lines = [f"*Przeglad tygodnia, {name}*", ""]

        # Knowledge coverage
        snap = self._safe_call(self._get_knowledge_snapshot)
        if snap:
            total = snap.get("total_files", 0)
            by_status = snap.get("files_by_status", {})
            completed = len(by_status.get("completed", []))
            coverage = (completed / total * 100) if total > 0 else 0
            lines.append(f"Pokrycie wiedzy: {coverage:.0f}% ({completed}/{total})")

        # Goal stats
        gstats = self._safe_call(self._get_goal_stats)
        if gstats:
            achieved = gstats.get("achieved", 0)
            active = gstats.get("active", 0)
            lines.append(f"Cele osiagniete: {achieved}, aktywne: {active}")

        # Evaluation
        report = self._safe_call(self._get_evaluation)
        if report and hasattr(report, "metrics"):
            retention = report.metrics.get("retention_rate", 0)
            velocity = report.metrics.get("learning_velocity", 0)
            if retention > 0:
                lines.append(f"Retencja: {retention:.0%}")
            if velocity > 0:
                lines.append(f"Predkosc nauki: {velocity:.1f} chunk/h")

        if len(lines) <= 2:
            return None

        lines.append("\nUdanego tygodnia!")
        return ProactiveContact(
            reason=ContactReason.WEEKLY_REVIEW,
            message="\n".join(lines),
        )

    def _goal_achieved(self) -> Optional[ProactiveContact]:
        """Notify about recently achieved goals."""
        achievements = self._safe_call(self._get_recent_achievements) or []
        if not achievements:
            return None

        lines = ["*Cel osiagniety!*", ""]
        for a in achievements[:3]:
            lines.append(f"  - {a}")

        return ProactiveContact(
            reason=ContactReason.GOAL_ACHIEVED,
            message="\n".join(lines),
            metadata={"count": len(achievements)},
        )

    def _learning_milestone(self) -> Optional[ProactiveContact]:
        """Notify about learning progress milestones."""
        snap = self._safe_call(self._get_knowledge_snapshot)
        if not snap:
            return None

        total = snap.get("total_files", 0)
        by_status = snap.get("files_by_status", {})
        completed = len(by_status.get("completed", []))
        if total == 0:
            return None

        coverage = completed / total
        # Milestone at every 10%
        milestone = int(coverage * 10) * 10
        if milestone == 0:
            return None

        chunks = snap.get("total_chunks_learned", 0)
        avg_score = snap.get("average_exam_score", 0)

        lines = [
            f"*Kamien milowy: {milestone}% wiedzy!*",
            "",
            f"Pliki: {completed}/{total}",
            f"Chunki: {chunks}",
        ]
        if avg_score > 0:
            lines.append(f"Sredni wynik: {avg_score:.0%}")

        return ProactiveContact(
            reason=ContactReason.LEARNING_MILESTONE,
            message="\n".join(lines),
            metadata={"milestone_pct": milestone, "coverage": coverage},
        )

    def _idle_checkin(self) -> Optional[ProactiveContact]:
        """Check in when operator hasn't been in touch for a while."""
        name = self._safe_call(self._get_user_name) or "Operator"
        greeting = TimeAwareness.get_greeting()

        lines = [
            f"*{greeting}, {name}!*",
            "",
            "Dawno sie nie slyszelismy.",
        ]

        # Add something interesting
        snap = self._safe_call(self._get_knowledge_snapshot)
        if snap:
            by_status = snap.get("files_by_status", {})
            new_count = len(by_status.get("new", []))
            if new_count > 0:
                lines.append(f"Mam {new_count} nowych plikow do nauki.")

        proposed = self._safe_call(self._get_proposed_goals) or []
        if proposed:
            lines.append(f"Czeka {len(proposed)} celow na zatwierdzenie.")

        health = self._safe_call(self._get_health)
        if health is not None:
            lines.append(f"Moj stan: {health:.0%} health.")

        lines.append("\nDaj znac jesli potrzebujesz czegos!")

        return ProactiveContact(
            reason=ContactReason.IDLE_CHECKIN,
            message="\n".join(lines),
        )

    def _interest_match(self) -> Optional[ProactiveContact]:
        """Alert about new content matching user's interests."""
        interests = self._safe_call(self._get_user_interests) or []
        if not interests:
            return None

        snap = self._safe_call(self._get_knowledge_snapshot)
        if not snap:
            return None

        new_files = snap.get("new_files_available", [])
        if not new_files:
            return None

        # Check if any new file titles match interests
        matches = []
        for f in new_files:
            title = (f.get("title", "") or f.get("file_id", "")).lower()
            for interest in interests:
                if interest.lower() in title:
                    matches.append((f, interest))
                    break

        if not matches:
            return None

        name = self._safe_call(self._get_user_name) or "Operator"
        lines = [f"*{name}, cos dla Ciebie!*", ""]
        for f, interest in matches[:3]:
            title = f.get("title", f.get("file_id", "?"))
            lines.append(f"  - {title} (temat: {interest})")

        lines.append("\nChcesz zebym sie tego nauczyla?")

        return ProactiveContact(
            reason=ContactReason.INTEREST_MATCH,
            message="\n".join(lines),
            metadata={"matches": len(matches)},
        )

    # -- Helpers --

    @staticmethod
    def _safe_call(fn: Optional[Callable], *args, **kwargs):
        """Call function safely, return None on error."""
        if fn is None:
            return None
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            logger.debug("Proactive data accessor failed: %s", e)
            return None
