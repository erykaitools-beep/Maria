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
        bulletin_store=None,
        llm_fn: Optional[Callable[[str], str]] = None,
    ):
        # goal_store kept for backward-compat wiring; unused since R1
        # (2026-05-29) - critic posts NEED_REVIEW advisories to the bulletin
        # instead of flooding the goal queue with un-actionable LEARNING goals.
        self._goal_store = goal_store
        self._bulletin_store = bulletin_store
        self._llm_fn = llm_fn

    def set_goal_store(self, store):
        """Deprecated (R1): retained for wiring compat; critic uses bulletin."""
        self._goal_store = store

    def set_bulletin_store(self, store):
        """Dependency injection for the bulletin board (R1)."""
        self._bulletin_store = store

    def set_llm_fn(self, fn: Callable[[str], str]):
        """Set LLM function for summary (decoration only)."""
        self._llm_fn = fn

    def apply(self, report: CritiqueReport) -> Dict[str, Any]:
        """
        Post critique findings to the bulletin as NEED_REVIEW advisories.
        Optionally generate an LLM summary.

        R1 (2026-05-29): findings used to become PROPOSED goals, but 260 critic
        goals aged to ABANDONED without ever going ACTIVE. They are quality
        observations, not actionable goals - the bulletin is their proper home.

        Returns:
            {"bulletin_posted": [...], "goals_created": [], "llm_summary_ok": bool,
             "errors": [...]}
        """
        result: Dict[str, Any] = {
            "bulletin_posted": [],
            "goals_created": [],  # retained (always empty) for caller compat
            "errors": [],
            "llm_summary_ok": False,
        }

        if not report.findings:
            return result

        posted = 0

        for finding in report.findings:
            if posted >= MAX_PROPOSED_GOALS_FROM_CRITIQUE:
                break

            try:
                if not self._should_post_advisory(finding):
                    continue

                entry_id = self._post_advisory(finding, report.report_id)
                if entry_id:
                    result["bulletin_posted"].append(entry_id)
                    posted += 1

            except Exception as e:
                logger.warning("[Critic] Error posting advisory: %s", e)
                result["errors"].append(str(e)[:100])

        # Update report (goals_created retained as empty for compat)
        report.goals_created = result["goals_created"]

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
            "[Critic] Applied: %d advisories posted from %d findings",
            posted, len(report.findings),
        )

        return result

    def _should_post_advisory(self, finding: CritiqueFinding) -> bool:
        """
        Determine if a finding should be posted as a bulletin advisory.

        Policy (R1 2026-05-29):
        - CRITICAL / WARNING: yes
        - INFO: never (report-only)

        Idempotency is handled by BulletinStore.create_and_post (dedups by
        topic+type), so the old goal-store existence check is gone.
        """
        return finding.severity in (
            FindingSeverity.CRITICAL.value,
            FindingSeverity.WARNING.value,
        )

    def _post_advisory(
        self, finding: CritiqueFinding, report_id: str,
    ) -> Optional[str]:
        """Post a critique finding to the bulletin as a NEED_REVIEW advisory.

        R1 (2026-05-29): replaces the old PROPOSED-goal flow. NEED_REVIEW is
        the bulletin entry type for exactly this case ("quality problem from
        critic/validation"). Operator and planner can read it without the goal
        queue filling with un-actionable LEARNING goals.
        """
        if self._bulletin_store is None:
            logger.debug(
                "[Critic] No bulletin_store, dropping finding %s",
                finding.finding_id,
            )
            return None

        try:
            from agent_core.bulletin.bulletin_model import EntryType
        except Exception as e:
            logger.warning("[Critic] Bulletin import failed: %s", e)
            return None

        title = finding.recommended_goal_title
        if not title:
            template = GOAL_TITLE_MAP.get(finding.category, "Sprawdz: {}")
            title = template.format(finding.topic)

        try:
            entry = self._bulletin_store.create_and_post(
                entry_type=EntryType.NEED_REVIEW,
                topic=finding.topic,
                reason_code=f"critic_{finding.category}",
                summary=title,
                requested_by="critic",
                priority=0.6 if finding.severity == "critical" else 0.4,
                metadata={
                    "report_id": report_id,
                    "finding_id": finding.finding_id,
                    "category": finding.category,
                    "severity": finding.severity,
                    "topic_normalized": finding.topic_normalized,
                    "dedupe_key": finding.dedupe_key,
                    "suggested_action": finding.suggested_action,
                },
            )
            logger.info(
                "[Critic] Posted NEED_REVIEW: %s (%s, sev=%s)",
                entry.entry_id, finding.topic[:50], finding.severity,
            )
            return entry.entry_id
        except Exception as e:
            logger.warning("[Critic] Bulletin post failed: %s", e)
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
