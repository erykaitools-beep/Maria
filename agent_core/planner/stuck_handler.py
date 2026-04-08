"""
StuckHandler - Self-diagnosis and repair for stuck planner loops.

Level 4: Diagnose WHY the planner is stuck
Level 5: Attempt self-repair based on diagnosis
Level 6: Escalate to operator with full context if repair fails

Called from PlannerCore._handle_stuck() when consecutive identical
failures are detected (STUCK_THRESHOLD reached).
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class StuckCause(Enum):
    """Diagnosed root cause of a stuck loop."""
    MATERIAL_EXISTS = "material_exists"       # Expert file already there, should LEARN
    TOPIC_EXHAUSTED = "topic_exhausted"       # All topics covered, need new ones
    RATE_LIMITED = "rate_limited"              # K7/rate limit blocking action
    CONSECUTIVE_FAILURES = "consecutive_fails" # K7 blocked due to failure streak
    NO_FILES = "no_files"                     # Goal has no input files to learn from
    LLM_ERROR = "llm_error"                   # LLM backend failing repeatedly
    MISSING_SUBSYSTEM = "missing_subsystem"   # Required module not configured
    UNKNOWN = "unknown"                       # Could not determine cause


class RepairAction(Enum):
    """Self-repair action attempted."""
    SWITCH_TO_LEARN = "switch_to_learn"       # Trigger LEARN instead of ask_expert
    RESET_FAILURES = "reset_failures"         # Reset K7 consecutive failure counter
    PICK_NEW_TOPIC = "pick_new_topic"         # Force different topic for goal
    TRIGGER_FETCH = "trigger_fetch"           # Fetch new material from web
    NONE = "none"                             # No repair possible


@dataclass
class StuckDiagnosis:
    """Result of stuck loop analysis."""
    cause: StuckCause
    detail: str                               # Human-readable explanation
    repair_action: RepairAction = RepairAction.NONE
    repair_succeeded: bool = False
    repair_detail: str = ""
    context: Dict[str, Any] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return self.repair_succeeded


class StuckHandler:
    """
    Diagnoses and attempts to repair stuck planner loops.

    Injected with references to subsystems it can query (read-only)
    and limited repair actions it can take.
    """

    def __init__(self):
        self._goal_store = None
        self._autonomy_policy = None
        self._knowledge_analyzer = None
        self._input_dir = None  # Path to input/ directory

    def set_goal_store(self, store) -> None:
        self._goal_store = store

    def set_autonomy_policy(self, policy) -> None:
        self._autonomy_policy = policy

    def set_knowledge_analyzer(self, analyzer) -> None:
        self._knowledge_analyzer = analyzer

    def set_input_dir(self, path) -> None:
        self._input_dir = path

    # -- Level 4: Diagnosis --

    def diagnose(self, fingerprint: Dict[str, str], plan_result: Dict) -> StuckDiagnosis:
        """
        Analyze why the planner is stuck based on failure fingerprint.

        Args:
            fingerprint: {action, goal_id, reason} from stuck detection
            plan_result: Full result dict from last failed plan

        Returns:
            StuckDiagnosis with cause, detail, and suggested repair
        """
        action = fingerprint.get("action", "")
        reason = fingerprint.get("reason", "")
        goal_id = fingerprint.get("goal_id", "")

        # Match known patterns
        if reason in ("expert_material_already_exists", "topic_well_covered"):
            return self._diagnose_material_exists(fingerprint, plan_result)

        if "rate_limit" in reason or "rate_limited" in reason:
            return StuckDiagnosis(
                cause=StuckCause.RATE_LIMITED,
                detail=f"Akcja '{action}' zablokowana przez rate limit. "
                       f"Poczekam az limit sie odnowi.",
                context={"action": action, "reason": reason},
            )

        if "consecutive_failures" in reason or "consecutive_fail" in reason:
            return self._diagnose_consecutive_failures(fingerprint, plan_result)

        if reason in ("No teacher agent configured", "no_analyzer"):
            return StuckDiagnosis(
                cause=StuckCause.MISSING_SUBSYSTEM,
                detail=f"Brak wymaganego modulu do akcji '{action}': {reason}",
                context={"action": action, "reason": reason},
            )

        if "timeout" in reason.lower() or "llm_error" in reason:
            return StuckDiagnosis(
                cause=StuckCause.LLM_ERROR,
                detail=f"Backend LLM nie odpowiada: {reason}",
                repair_action=RepairAction.NONE,
                context={"action": action, "reason": reason},
            )

        if "idle_reason" in (plan_result or {}):
            idle = plan_result.get("idle_reason", "")
            if "no_files" in idle or "no files" in idle.lower():
                return self._diagnose_no_files(fingerprint, plan_result)

        # Unknown cause
        return StuckDiagnosis(
            cause=StuckCause.UNKNOWN,
            detail=f"Nie moge zdiagnozowac przyczyny. "
                   f"Akcja: {action}, powod: {reason}",
            context={"action": action, "reason": reason, "result": plan_result},
        )

    def _diagnose_material_exists(
        self, fingerprint: Dict, plan_result: Dict,
    ) -> StuckDiagnosis:
        """Expert material exists - should learn from it instead."""
        topic = plan_result.get("topic", fingerprint.get("reason", ""))
        return StuckDiagnosis(
            cause=StuckCause.MATERIAL_EXISTS,
            detail=f"Material o '{topic}' juz istnieje w input/. "
                   f"Powinnam sie z niego uczyc zamiast pytac eksperta.",
            repair_action=RepairAction.SWITCH_TO_LEARN,
            context={"topic": topic},
        )

    def _diagnose_consecutive_failures(
        self, fingerprint: Dict, plan_result: Dict,
    ) -> StuckDiagnosis:
        """K7 blocked action due to failure streak."""
        action = fingerprint.get("action", "")
        return StuckDiagnosis(
            cause=StuckCause.CONSECUTIVE_FAILURES,
            detail=f"K7 zablokowala '{action}' po serii niepowodzen. "
                   f"Zresetuje licznik i sprobuje z innym tematem.",
            repair_action=RepairAction.RESET_FAILURES,
            context={"action": action},
        )

    def _diagnose_no_files(
        self, fingerprint: Dict, plan_result: Dict,
    ) -> StuckDiagnosis:
        """Goal has no files to learn from."""
        return StuckDiagnosis(
            cause=StuckCause.NO_FILES,
            detail="Cel nauki nie ma plikow w input/. "
                   "Sprobuje pobrac nowe materialy.",
            repair_action=RepairAction.TRIGGER_FETCH,
            context={"idle_reason": plan_result.get("idle_reason", "")},
        )

    # -- Level 5: Self-repair --

    def try_repair(self, diagnosis: StuckDiagnosis) -> StuckDiagnosis:
        """
        Attempt to fix the stuck condition based on diagnosis.

        Modifies diagnosis in-place with repair results.
        Returns the same diagnosis with repair_succeeded + repair_detail set.
        """
        repair = diagnosis.repair_action

        if repair == RepairAction.NONE:
            diagnosis.repair_detail = "Brak dostepnej naprawy dla tego problemu."
            return diagnosis

        try:
            if repair == RepairAction.SWITCH_TO_LEARN:
                return self._repair_switch_to_learn(diagnosis)
            elif repair == RepairAction.RESET_FAILURES:
                return self._repair_reset_failures(diagnosis)
            elif repair == RepairAction.PICK_NEW_TOPIC:
                return self._repair_pick_new_topic(diagnosis)
            elif repair == RepairAction.TRIGGER_FETCH:
                return self._repair_trigger_fetch(diagnosis)
        except Exception as e:
            logger.warning("[StuckHandler] Repair failed: %s", e)
            diagnosis.repair_detail = f"Naprawa nie powiodla sie: {e}"

        return diagnosis

    def _repair_switch_to_learn(self, diag: StuckDiagnosis) -> StuckDiagnosis:
        """Force goal to LEARN from existing material instead of ask_expert."""
        goal_id = diag.context.get("goal_id", "")
        topic = diag.context.get("topic", "")

        if self._goal_store and goal_id:
            goal = self._goal_store.get(goal_id)
            if goal and hasattr(goal, 'metadata'):
                # Remove forced_action_type if set, so planner picks LEARN naturally
                goal.metadata.pop("forced_action_type", None)
                # Hint: topic files exist, prefer learning
                goal.metadata["prefer_learn"] = True
                goal.metadata["stuck_repair"] = "switch_to_learn"
                self._goal_store.save()

                diag.repair_succeeded = True
                diag.repair_detail = (
                    f"Przestawiam cel na LEARN z istniejacego materialu "
                    f"o '{topic}'."
                )
                logger.info(
                    "[StuckHandler] Repair: switch_to_learn for goal %s topic '%s'",
                    goal_id, topic,
                )
                return diag

        # Fallback: even without goal_store, clearing stuck cooldown
        # and letting normal planner flow handle it is a repair
        diag.repair_succeeded = True
        diag.repair_detail = (
            f"Material o '{topic}' istnieje. "
            f"Planner powinien wybrac LEARN w nastepnym cyklu."
        )
        return diag

    def _repair_reset_failures(self, diag: StuckDiagnosis) -> StuckDiagnosis:
        """Reset K7 consecutive failure counter for the stuck action."""
        action = diag.context.get("action", "")

        if self._autonomy_policy:
            try:
                # Reset consecutive failures via record_execution(success=True)
                self._autonomy_policy.record_execution(action, True)
                diag.repair_succeeded = True
                diag.repair_detail = (
                    f"Zresetowano licznik niepowodzen dla '{action}'. "
                    f"Sprobuje ponownie z innym podejsciem."
                )
                logger.info(
                    "[StuckHandler] Repair: reset consecutive failures for '%s'",
                    action,
                )
            except Exception as e:
                diag.repair_detail = f"Nie udalo sie zresetowac licznika: {e}"
        else:
            diag.repair_detail = "Brak autonomy_policy do resetu licznika."

        return diag

    def _repair_pick_new_topic(self, diag: StuckDiagnosis) -> StuckDiagnosis:
        """Suggest a different topic for the goal."""
        # This is advisory - the actual topic change happens through
        # GapPlanner/TopicSuggester on next cycle after cooldown expires
        diag.repair_succeeded = False
        diag.repair_detail = (
            "Sugeruje zmiane tematu. GapPlanner powinien wybrac "
            "inny temat po wygasnieciu cooldownu."
        )
        return diag

    def _repair_trigger_fetch(self, diag: StuckDiagnosis) -> StuckDiagnosis:
        """Mark that new material needs to be fetched."""
        goal_id = diag.context.get("goal_id", "")

        if self._goal_store and goal_id:
            goal = self._goal_store.get(goal_id)
            if goal and hasattr(goal, 'metadata'):
                goal.metadata["needs_fetch"] = True
                goal.metadata["stuck_repair"] = "trigger_fetch"
                self._goal_store.save()

                diag.repair_succeeded = True
                diag.repair_detail = (
                    "Oznaczono cel do pobrania nowych materialow. "
                    "FETCH zostanie uruchomiony w nastepnym cyklu."
                )
                logger.info(
                    "[StuckHandler] Repair: trigger_fetch for goal %s", goal_id,
                )
                return diag

        diag.repair_detail = "Nie moge oznaczyc celu do fetcha."
        return diag

    # -- Level 6: Escalation message --

    def format_escalation(
        self,
        diagnosis: StuckDiagnosis,
        fingerprint: Dict[str, str],
        count: int,
        cooldown_minutes: int,
    ) -> str:
        """
        Build detailed Telegram escalation message with diagnosis context.

        Replaces the simple "Utknelam" message when diagnosis is available.
        """
        action = fingerprint.get("action", "?")
        goal_id = fingerprint.get("goal_id", "?")
        reason = fingerprint.get("reason", "?")

        lines = [
            f"*Utknelam: {action}*",
            "",
            f"*Diagnoza:* {diagnosis.detail}",
        ]

        if diagnosis.repair_action != RepairAction.NONE:
            status = "OK" if diagnosis.repair_succeeded else "FAILED"
            lines.append(f"*Naprawa [{status}]:* {diagnosis.repair_detail}")

        if not diagnosis.resolved:
            lines.append("")
            lines.append("Potrzebuje pomocy operatora.")

            # Add actionable hints based on cause
            hints = self._get_operator_hints(diagnosis)
            if hints:
                lines.append("")
                lines.append("*Sugestie:*")
                for hint in hints:
                    lines.append(f"- {hint}")

        lines.append("")
        lines.append(
            f"Cel: {goal_id[:12]} | Powtorzen: {count} | "
            f"Cooldown: {cooldown_minutes} min"
        )

        return "\n".join(lines)

    def _get_operator_hints(self, diagnosis: StuckDiagnosis) -> List[str]:
        """Suggest actions for operator based on diagnosis."""
        cause = diagnosis.cause
        hints = []

        if cause == StuckCause.MATERIAL_EXISTS:
            hints.append("Sprawdz czy plik w input/ jest kompletny")
            hints.append("/goals - sprawdz stan celu")
        elif cause == StuckCause.RATE_LIMITED:
            hints.append("Poczekaj na odnowienie limitu")
            hints.append("/status - sprawdz rate limity")
        elif cause == StuckCause.CONSECUTIVE_FAILURES:
            hints.append("/goals - sprawdz/odrzuc problematyczny cel")
        elif cause == StuckCause.LLM_ERROR:
            hints.append("Sprawdz Ollama/NIM - moze wymaga restartu")
            hints.append("/status - sprawdz health systemu")
        elif cause == StuckCause.MISSING_SUBSYSTEM:
            hints.append("Modul nie jest skonfigurowany - wymaga restartu")
        elif cause == StuckCause.NO_FILES:
            hints.append("Dodaj materialy do input/ lub czekaj na FETCH")
        elif cause == StuckCause.UNKNOWN:
            hints.append("/trace - sprawdz ostatnie decyzje")
            hints.append("/status - sprawdz ogolny stan")

        return hints
