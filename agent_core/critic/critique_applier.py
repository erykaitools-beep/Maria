"""
Faza G: CritiqueApplier - convert findings into PROPOSED goals.

The ONLY place that creates side effects from critique analysis.
KnowledgeCritic is READ-ONLY; this module writes goals.

Goal creation policy:
- CRITICAL: always create PROPOSED goal
- WARNING: only if high confidence + no existing similar goal + topic active
- INFO: report only, never create goal

Idempotency: checks for existing goals with same dedupe_key.
LLM summary: decoration only, does not affect decisions.
"""

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from agent_core.critic.critique_model import (
    CritiqueReport,
    CritiqueFinding,
    FindingSeverity,
    GOAL_TITLE_MAP,
    MAX_PROPOSED_GOALS_FROM_CRITIQUE,
)

logger = logging.getLogger(__name__)


class CritiqueApplier:
    """Convert critique findings into PROPOSED goals + optional LLM summary."""

    def __init__(
        self,
        goal_store=None,
        llm_fn: Optional[Callable[[str], str]] = None,
    ):
        self._goal_store = goal_store
        self._llm_fn = llm_fn

    def set_goal_store(self, store):
        """Dependency injection."""
        self._goal_store = store

    def set_llm_fn(self, fn: Callable[[str], str]):
        """Set LLM function for summary (decoration only)."""
        self._llm_fn = fn

    def apply(self, report: CritiqueReport) -> Dict[str, Any]:
        """
        Create PROPOSED goals from findings. Optionally generate LLM summary.

        Returns:
            {"goals_created": [...], "llm_summary_ok": bool, "errors": [...]}
        """
        result: Dict[str, Any] = {
            "goals_created": [],
            "errors": [],
            "llm_summary_ok": False,
        }

        if not report.findings:
            return result

        goals_created = 0

        for finding in report.findings:
            if goals_created >= MAX_PROPOSED_GOALS_FROM_CRITIQUE:
                break

            try:
                should_create = self._should_create_goal(finding)
                if not should_create:
                    continue

                goal_id = self._create_proposed_goal(finding, report.report_id)
                if goal_id:
                    result["goals_created"].append(goal_id)
                    goals_created += 1

            except Exception as e:
                logger.warning("[Critic] Error creating goal: %s", e)
                result["errors"].append(str(e)[:100])

        # Update report
        report.goals_created = result["goals_created"]

        # Persist goals to JSONL
        if goals_created > 0 and self._goal_store is not None:
            try:
                self._goal_store.save()
            except Exception as e:
                logger.warning("[Critic] Failed to persist goals: %s", e)

        # LLM summary (decoration only, failure does not break apply)
        try:
            if self._llm_fn and report.findings:
                summary = self._generate_summary(report.findings)
                if summary:
                    report.llm_summary = summary
                    result["llm_summary_ok"] = True
        except Exception as e:
            logger.debug("[Critic] LLM summary failed (non-critical): %s", e)

        logger.info(
            "[Critic] Applied: %d goals created from %d findings",
            goals_created, len(report.findings),
        )

        return result

    def _should_create_goal(self, finding: CritiqueFinding) -> bool:
        """
        Determine if finding should create a PROPOSED goal.

        Policy:
        - CRITICAL: yes (always)
        - WARNING: yes if no existing similar goal
        - INFO: never
        """
        if finding.severity == FindingSeverity.INFO.value:
            return False

        if finding.severity == FindingSeverity.CRITICAL.value:
            # Always, but still check idempotency
            return not self._has_existing_goal(finding)

        if finding.severity == FindingSeverity.WARNING.value:
            return not self._has_existing_goal(finding)

        return False

    def _has_existing_goal(self, finding: CritiqueFinding) -> bool:
        """Check if a similar goal already exists (idempotency)."""
        if self._goal_store is None:
            return False

        try:
            # Check active goals
            active = []
            if hasattr(self._goal_store, "get_active"):
                active = self._goal_store.get_active()
            proposed = []
            if hasattr(self._goal_store, "get_proposed"):
                proposed = self._goal_store.get_proposed()

            all_goals = active + proposed
            dedupe_key = finding.dedupe_key
            topic_norm = finding.topic_normalized

            for goal in all_goals:
                meta = getattr(goal, "metadata", {}) or {}
                # Check by dedupe_key
                if meta.get("dedupe_key") == dedupe_key:
                    return True
                # Check by topic similarity (source=critic + similar topic)
                if (
                    meta.get("source") == "critic"
                    and meta.get("topic_normalized") == topic_norm
                    and meta.get("category") == finding.category
                ):
                    return True

        except Exception as e:
            logger.debug("[Critic] Goal check failed: %s", e)

        return False

    def _create_proposed_goal(
        self, finding: CritiqueFinding, report_id: str,
    ) -> Optional[str]:
        """Create a PROPOSED LEARNING goal from finding."""
        if self._goal_store is None:
            return None

        try:
            from agent_core.goals.goal_model import (
                Goal, GoalType, GoalStatus, AuditEntry,
            )

            # Get goal title from map or finding
            title = finding.recommended_goal_title
            if not title:
                template = GOAL_TITLE_MAP.get(finding.category, "Sprawdz: {}")
                title = template.format(finding.topic)

            goal_id_str = f"goal-crit-{uuid.uuid4().hex[:8]}"
            now = time.time()

            goal = Goal(
                id=goal_id_str,
                type=GoalType.LEARNING,
                description=title,
                priority=0.6 if finding.severity == "critical" else 0.4,
                status=GoalStatus.PROPOSED,
                progress=0.0,
                parent_goal_id=None,
                created_by="critic",
                created_at=now,
                updated_at=now,
                audit_trail=[
                    AuditEntry(
                        timestamp=now,
                        old_status=None,
                        new_status="proposed",
                        reason=f"Critic: {finding.category} - {finding.topic}",
                        actor="critic",
                    )
                ],
                metadata={
                    "source": "critic",
                    "report_id": report_id,
                    "finding_id": finding.finding_id,
                    "category": finding.category,
                    "severity": finding.severity,
                    "topic": finding.topic,
                    "topic_normalized": finding.topic_normalized,
                    "dedupe_key": finding.dedupe_key,
                    "suggested_action": finding.suggested_action,
                },
            )

            goal_id = None
            if hasattr(self._goal_store, "propose"):
                goal_id = self._goal_store.propose(goal)
            elif hasattr(self._goal_store, "create"):
                self._goal_store.create(goal)
                goal_id = goal.id

            if goal_id:
                logger.info(
                    "[Critic] Created PROPOSED goal: %s (%s)",
                    goal_id, finding.topic,
                )

            return goal_id

        except Exception as e:
            logger.warning("[Critic] Goal creation failed: %s", e)
            return None

    def _generate_summary(self, findings: List[CritiqueFinding]) -> Optional[str]:
        """
        Generate LLM summary of findings (decoration only).

        Does NOT affect severity, suggested_action, or goal creation.
        """
        if not self._llm_fn:
            return None

        findings_text = []
        for f in findings:
            findings_text.append(
                f"- [{f.severity}] {f.category}: {f.description}"
            )

        prompt = (
            "Jestes krytycznym recenzentem wiedzy systemu M.A.R.I.A. "
            "Napisz krotkie podsumowanie (2-3 zdania po polsku) "
            "nastepujacych problemow z wiedza:\n\n"
            + "\n".join(findings_text)
            + "\n\nPodsumuj najwazniejsze problemy i co nalezy zrobic."
        )

        try:
            response = self._llm_fn(prompt)
            if response and len(response.strip()) > 10:
                return response.strip()[:500]
        except Exception as e:
            logger.debug("[Critic] LLM summary call failed: %s", e)

        return None
