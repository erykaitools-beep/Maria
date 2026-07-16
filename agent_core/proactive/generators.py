"""
Proactive contact content generators.

Each generator produces a message string from system data.
All generators are pure functions - no side effects, no LLM calls.
"""

import logging
import os
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
        self._get_recent_achievements: Optional[Callable] = None
        self._get_recent_milestones: Optional[Callable] = None
        self._get_chunks_learned: Optional[Callable] = None
        self._get_mode: Optional[Callable] = None
        self._get_operator_context: Optional[Callable] = None
        self._get_operator_rhythm: Optional[Callable] = None
        self._get_weather: Optional[Callable] = None
        self._get_weather_data: Optional[Callable] = None  # raw WeatherData (hydration nudge)
        self._get_perception: Optional[Callable] = None
        self._get_operator_question: Optional[Callable] = None
        self._get_self_context: Optional[Callable] = None  # E4: full situational picture

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

    def set_recent_achievements_fn(self, fn: Callable) -> None:
        self._get_recent_achievements = fn

    def set_recent_milestones_fn(self, fn: Callable) -> None:
        self._get_recent_milestones = fn

    def set_chunks_learned_fn(self, fn: Callable) -> None:
        """Inject the 24h chunk count (KnowledgeAnalyzer.count_chunks_learned).

        Separate from the knowledge snapshot on purpose: the snapshot is read on
        the planner tick path, this reads the much larger memory file and is only
        wanted by the daily frame.
        """
        self._get_chunks_learned = fn

    def set_mode_fn(self, fn: Callable) -> None:
        self._get_mode = fn

    def set_operator_context_fn(self, fn: Callable) -> None:
        self._get_operator_context = fn

    def set_operator_rhythm_fn(self, fn: Callable) -> None:
        self._get_operator_rhythm = fn

    def set_weather_fn(self, fn: Callable) -> None:
        self._get_weather = fn

    def set_weather_data_fn(self, fn: Callable) -> None:
        """Inject raw WeatherData accessor (used by the hydration nudge, which
        needs the temperature itself, not just the formatted morning line)."""
        self._get_weather_data = fn

    def set_perception_fn(self, fn: Callable) -> None:
        self._get_perception = fn

    def set_operator_question_fn(self, fn: Callable) -> None:
        """Inject ActiveLearner's 'what to ask next' decision (K14.1)."""
        self._get_operator_question = fn

    def set_self_context_fn(self, fn: Callable) -> None:
        """Inject SelfContext.build() (E4): the merged situational picture so a
        proactive message can speak from the whole situation (last seen + current
        focus), not just isolated stats."""
        self._get_self_context = fn

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
            ContactReason.OPERATOR_QUESTION: self._operator_question,
            ContactReason.HYDRATION_NUDGE: self._hydration_nudge,
        }
        gen_fn = generators.get(reason)
        if not gen_fn:
            return None
        try:
            return gen_fn()
        except Exception as e:
            logger.debug("Generator %s failed: %s", reason.value, e)
            return None

    def _operator_question(self) -> Optional[ProactiveContact]:
        """ActiveLearner (K14.1): ask ONE low-pressure question to fill a gap.
        The injected fn returns the question text (marking it pending) or None
        when there is nothing worth asking / a question is already open."""
        if not self._get_operator_question:
            return None
        text = self._get_operator_question()
        if not text:
            return None
        return ProactiveContact(
            reason=ContactReason.OPERATOR_QUESTION,
            message=text,
        )

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

        # E4: situational awareness -- what I last saw + what I'm working on now.
        for sl in self._situational_lines():
            lines.append(sl)

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
            # "Wiedza" is deliberately the lifetime total -- it is a claim about
            # accumulated knowledge, not about a day, so the sum is the answer.
            lines.append(f"Wiedza: {completed}/{total} plikow, {chunks} chunkow")
            if new_count > 0:
                lines.append(f"Nowe do nauki: {new_count}")
            # The exam figure is a claim about how she is doing lately, so it is
            # windowed: the lifetime mean sits on 1347 exams and cannot move.
            exams_24h = snap.get("exam_count_24h", 0)
            if exams_24h > 0:
                avg_24h = snap.get("average_exam_score_24h", 0)
                lines.append(
                    f"Egzaminy (24h): {exams_24h}, sredni wynik {avg_24h:.0%}"
                )

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
        """Daily evening summary of what happened today.

        Every figure here is windowed to the last 24h. Lifetime aggregates were
        tried and they lied: on 07-12..07-15 this frame printed "5379 chunks /
        83%" plus the same five achievements four evenings running, because a
        single day cannot move an all-time sum -- and one of those achievements
        was ten days old. A quiet day must be allowed to read as a quiet day.
        """
        name = self._safe_call(self._get_user_name) or "Operator"

        lines = [f"*Podsumowanie dnia, {name}*", ""]

        # Chunks counted from long-term memory, not from successful learn actions:
        # a learn action that finds every chunk already known still reports
        # success, so the action count runs ahead of what was really learned
        # (101 vs 83 on 2026-07-16).
        chunks_24h = self._safe_call(self._get_chunks_learned) or 0
        if chunks_24h > 0:
            lines.append(f"Chunki nauczone (24h): {chunks_24h}")

        snap = self._safe_call(self._get_knowledge_snapshot)
        if snap:
            exams_24h = snap.get("exam_count_24h", 0)
            if exams_24h > 0:
                avg_24h = snap.get("average_exam_score_24h", 0)
                lines.append(
                    f"Egzaminy (24h): {exams_24h}, sredni wynik {avg_24h:.0%}"
                )

        # Achievements: the injected fn returns only goals achieved inside the
        # window, newest first. An empty list is a real answer -- print nothing
        # rather than reaching further back for something to show.
        achievements = self._safe_call(self._get_recent_achievements) or []
        if achievements:
            lines.append("\nOsiagniecia (24h):")
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
        """Notify when Maria has passed exam(s) / finished file(s).

        Twin of _goal_achieved: pulls the freshly-passed milestones (the
        scheduler drains its buffer here) and batches them into one ping.
        """
        items = self._safe_call(self._get_recent_milestones) or []
        if not items:
            return None

        lines = ["*Nauczylam sie czegos nowego!*", ""]
        for it in items[:5]:
            topic = self._format_topic(it.get("topic", "?"))
            pct = self._score_pct(it.get("score"))
            if pct is not None:
                lines.append(f"  - {topic} (egzamin zdany {pct}%)")
            else:
                lines.append(f"  - {topic}")
        extra = len(items) - 5
        if extra > 0:
            lines.append(f"  ... i {extra} wiecej")

        return ProactiveContact(
            reason=ContactReason.LEARNING_MILESTONE,
            message="\n".join(lines),
            metadata={"count": len(items)},
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

    def _hydration_nudge(self) -> Optional[ProactiveContact]:
        """Hot-weather care: gently remind the operator to drink water.

        Fires only when it is genuinely hot (needs_hydration_reminder over the
        raw WeatherData). Returns None on mild days, when weather is
        unavailable, or when the operator is on a do-not-disturb context.
        Wording is warm and rotated by hour so two nudges on the same day read
        differently rather than as a repeated canned line.
        """
        get_data = self._get_weather_data
        if get_data is None:
            return None
        data = self._safe_call(get_data)
        if data is None:
            return None

        # Heat gate (lazy import keeps generators free of a hard weather dep).
        from agent_core.weather.salience import needs_hydration_reminder
        if not needs_hydration_reminder(data):
            return None

        # Respect "urlop" / "nie przeszkadzac", same skip as the morning brief.
        op_context = self._safe_call(self._get_operator_context)
        if op_context:
            skip_keywords = ("urlop", "nie przeszkadza", "vacation", "dnd")
            if any(kw in op_context.lower() for kw in skip_keywords):
                return None

        name = self._safe_call(self._get_user_name) or "Operator"
        temp = f"{data.temp_c:.0f}"
        feels = f"{data.feels_like_c:.0f}"

        # City stays in metadata only -- folding it into "w {city}" breaks Polish
        # declension for arbitrary OWM names ("w Berlin"), so keep the wording
        # city-agnostic.
        variants = [
            f"{name}, dzis {temp}C i ostro przygrzewa. "
            "Zrob sobie przerwe i wypij szklanke wody.",
            f"Upal nie odpuszcza ({temp}C, odczuwalne {feels}C). "
            f"{name}, pamietaj o nawodnieniu!",
            f"Goraco dzis ({temp}C). {name}, dawno piles wode? "
            "To dobry moment na szklanke.",
            f"{temp}C na dworze - zadbaj o siebie. "
            f"Szklanka wody teraz sie przyda, {name}.",
        ]
        idx = datetime.now().hour % len(variants)

        return ProactiveContact(
            reason=ContactReason.HYDRATION_NUDGE,
            message=variants[idx],
            metadata={"temp_c": data.temp_c, "feels_like_c": data.feels_like_c},
        )

    def proposed_goal_alert(
        self, new_goals: List[Dict[str, Any]]
    ) -> Optional[ProactiveContact]:
        """Alert about freshly created PROPOSED goal(s) awaiting approval.

        Called directly by ProactiveScheduler with the diff against
        seen_proposed_goal_ids — not part of generate() dispatch since it
        needs the new-goals list as input. Single-vs-batch format keeps the
        message readable when escalator creates several goals in one scan.
        """
        if not new_goals:
            return None

        if len(new_goals) == 1:
            g = new_goals[0]
            desc = (g.get("description") or g.get("title") or "?")[:200]
            message = (
                "*Nowy PROPOSED cel*\n\n"
                f"{desc}\n\n"
                "Approve via /goals."
            )
        else:
            lines = [f"*{len(new_goals)} nowych PROPOSED celow*", ""]
            for g in new_goals[:5]:
                desc = (g.get("description") or g.get("title") or "?")[:80]
                lines.append(f"  - {desc}")
            if len(new_goals) > 5:
                lines.append(f"  ... i {len(new_goals) - 5} wiecej")
            lines.append("\nApprove via /goals.")
            message = "\n".join(lines)

        return ProactiveContact(
            reason=ContactReason.GOAL_PROPOSED,
            message=message,
            metadata={
                "count": len(new_goals),
                "goal_ids": [g.get("id") for g in new_goals if g.get("id")],
            },
        )

    # -- Helpers --

    def _situational_lines(self) -> List[str]:
        """E4: a compact 'what I'm working on right now' from SelfContext, so a
        proactive message speaks from the live situation ("teraz robie Y").

        Deliberately does NOT restate the last vision sighting: that already rides
        the interactive chat tail (E2) where it is contextual and not a re-broadcast
        -- echoing it in a proactive message would duplicate the VisionAdvisor ping
        (or leak the 'operator present' silent placeholder). Proactive's unique
        situational bit is the planner's REAL current focus (E3 rung2), which is
        not surfaced anywhere else.

        Flag-gated (PROACTIVE_SITUATIONAL, default OFF -> observe->cutover). Returns
        [] when off / no picture / nothing worth adding. Pure read: SelfContext.
        build() is read-only and cache-backed.
        """
        if os.environ.get("PROACTIVE_SITUATIONAL", "").strip().lower() not in (
            "1", "true", "yes", "on"
        ):
            return []
        pic = self._safe_call(self._get_self_context)
        if not isinstance(pic, dict):
            return []

        # Fully defensive: called inline by _morning_summary (NOT via _safe_call),
        # so a malformed picture must degrade to no situational line, never kill
        # the whole briefing.
        try:
            mission = pic.get("mission") or {}
            # Only the planner's REAL focus (E3 rung2), never the priority-guess.
            if (
                isinstance(mission, dict)
                and mission.get("focus_source") == "planner"
                and mission.get("top_goal")
            ):
                return [f"Teraz pracuje nad: {mission['top_goal']}"]
            return []
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("Proactive _situational_lines failed: %s", e)
            return []

    @staticmethod
    def _format_topic(file_id: Any) -> str:
        """Turn a file id / path into a readable topic name."""
        name = str(file_id or "").strip()
        name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]  # drop directory
        if "." in name:
            name = name.rsplit(".", 1)[0]  # drop extension
        name = name.replace("_", " ").replace("-", " ").strip()
        return name or str(file_id)

    @staticmethod
    def _score_pct(score: Any) -> Optional[int]:
        """Normalise an exam score (0.0-1.0 fraction, or already a percent) to %."""
        if not isinstance(score, (int, float)):
            return None
        if score <= 0:
            return None
        return round(score * 100) if score <= 1.0 else round(score)

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
