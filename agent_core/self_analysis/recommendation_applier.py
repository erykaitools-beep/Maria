"""
K12 Self-Analysis: RecommendationApplier.

Converts analysis recommendations into concrete actions:
- PROPOSED LEARNING goals (human gate via K3) — for knowledge_gap / new_topic /
  retention_problem categories
- Bulletin IMPROVEMENT entries — for strategy_change category (D2, 2026-04-26):
  strategic insights about Maria's own actions/strategies should not be
  misrouted as "learn topic about Action X" learning goals (which produced
  213 ABANDONED orphans in history).
- Topic hints for WebSource fetcher
- Beliefs in K6 World Model

All goals are PROPOSED (not ACTIVE) - operator approves.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, Any, Optional

from .recommendation_model import (
    AnalysisRecommendation,
    AnalysisReport,
)

# Categories that indicate Maria-self diagnostic insights, not
# topic-learning needs. Routed to bulletin IMPROVEMENT instead of
# misrouted LEARNING goal. (D2, 2026-04-26)
STRATEGIC_CATEGORIES = frozenset({
    "strategy_change",
})

# Known internal action names that may appear in K12 strategic recs.
# Matched against rec.topic to extract structured action_hint metadata
# for downstream consumers (planner advisory, /board, telegram).
_KNOWN_ACTIONS = (
    "learn", "fetch", "exam", "review", "self_analyze",
    "ask_expert", "experiment", "noop", "maintenance",
    "effector", "creative", "critic",
)

logger = logging.getLogger(__name__)

# Topic hints file (read by TopicSuggester in Phase 2)
_DEFAULT_HINTS_PATH = "meta_data/topic_hints.jsonl"
MAX_HINTS = 200

# R2.1.1 (2026-05-05): K12 was generating recommendations on topics that
# were already in web_fetch_registry but not in knowledge_index — fetched
# files that the learn pipeline never adopted. Result: 50/50 fetch sessions
# today returned no_articles because suggester auto-consumed the hints in
# the same cycle (already-fetched check). Cycle wasted on internal gap
# the operator should see, not on retry that cannot help.
_DEFAULT_FETCH_REGISTRY_PATH = "meta_data/web_fetch_registry.jsonl"

# R2.1 (2026-04-29): K12 self-analysis sometimes emits rec topics that describe
# Maria's own architecture rather than learning subjects — e.g.
# "Obsługa błędów i fallback dla akcji 'learn'" or "Analiza tekstu (hard_topic)".
# These poison the fetcher queue: wikipedia search returns nothing, RSS keyword
# filter rejects everything, and the same hints come back every cycle. The
# heuristics below reject obvious internal-meta shapes before write.
_HINT_HAS_QUOTE = re.compile(r"['\"]")
_HINT_K12_SUFFIX = re.compile(
    r"\((?:hard|easy|learn|fetch|review|self_analyze)[\s_]?(?:topic|action)\)",
    re.IGNORECASE,
)
_HINT_JARGON = re.compile(
    r"\b(fallback|mechanizm[uoyaiw]*|pipeline|endpoint|backoff)\b",
    re.IGNORECASE,
)
_HINT_ERROR_HANDLING = re.compile(r"obsług[ai]\s+błęd", re.IGNORECASE)
_HINT_MAX_WORDS = 5
_HINT_MIN_LEN = 3


def _is_searchable_topic(topic: str) -> bool:
    """Heuristic: keep wikipedia-shaped topics, reject K12 internal-meta concepts.

    Accepts: short noun phrases like "Logika formalna", "Mechanika kwantowa".
    Rejects: quoted action names ("Akcja 'learn'"), K12 metadata suffixes
    ("(hard_topic)", "(learn action)"), engineering jargon (fallback/pipeline/
    mechanizm/endpoint/backoff), error-handling phrases ("obsługa błędów"),
    and sentence-length descriptions (>5 words).

    Liberal by design — fail-and-skip lifecycle (R2.1 part C) handles the
    residual case where filter passes but wiki has no article.
    """
    if not topic:
        return False
    text = topic.strip()
    if len(text) < _HINT_MIN_LEN:
        return False
    if _HINT_HAS_QUOTE.search(text):
        return False
    if _HINT_K12_SUFFIX.search(text):
        return False
    if _HINT_JARGON.search(text):
        return False
    if _HINT_ERROR_HANDLING.search(text):
        return False
    if len(text.split()) > _HINT_MAX_WORDS:
        return False
    return True


class RecommendationApplier:
    """Convert recommendations into goals, topic hints, and beliefs."""

    def __init__(
        self,
        goal_store=None,
        world_model=None,
        bulletin_store=None,
        project_root: str = ".",
    ):
        """
        Args:
            goal_store: K3 GoalStore instance (optional, for goal creation)
            world_model: K6 WorldModel instance (optional, for belief updates)
            bulletin_store: BulletinStore instance (optional, for strategic
                recs routed to IMPROVEMENT entries instead of learning goals)
            project_root: Project root for topic_hints.jsonl path
        """
        self._goal_store = goal_store
        self._world_model = world_model
        self._bulletin_store = bulletin_store
        self._proposal_engine = None  # Most #2: K12->K11 routing (optional DI)
        self._root = Path(project_root)
        self._hints_path = self._root / _DEFAULT_HINTS_PATH
        self._fetch_registry_path = self._root / _DEFAULT_FETCH_REGISTRY_PATH

    def set_goal_store(self, store):
        """Dependency injection from homeostasis wiring."""
        self._goal_store = store

    def set_world_model(self, wm):
        """Dependency injection from homeostasis wiring."""
        self._world_model = wm

    def set_bulletin_store(self, store):
        """Dependency injection (D2): route strategic recs to bulletin."""
        self._bulletin_store = store

    def set_proposal_engine(self, engine):
        """DI for K11 ProposalEngine (Most #2 step 1, 2026-05-08).

        When set, strategic recs with suggested_action=experiment are
        passed through k12_to_k11_router heuristics. Successful matches
        produce K11 Proposals (DRAFT or auto-approved by confidence).
        Recs that don't match any heuristic stay as bulletin entries only.
        """
        self._proposal_engine = engine

    def apply(self, report: AnalysisReport) -> Dict[str, Any]:
        """
        Apply recommendations from analysis report.

        Strategic recs (category in STRATEGIC_CATEGORIES) are routed to the
        bulletin board as IMPROVEMENT entries — they describe Maria's own
        broken/suboptimal actions, not topics to learn (D2). Other categories
        keep the existing PROPOSED-goal flow.

        Returns summary of actions taken:
            {
                "goals_created": [...],
                "bulletin_posted": [...],
                "hints_written": N,
                "beliefs_updated": N,
            }
        """
        result = {
            "goals_created": [],
            "bulletin_posted": [],
            "hints_written": 0,
            "beliefs_updated": 0,
            "errors": [],
        }

        if not report.recommendations:
            logger.info("[K12] No recommendations to apply")
            return result

        # Sort by priority (highest first)
        sorted_recs = sorted(
            report.recommendations,
            key=lambda r: r.priority,
            reverse=True,
        )

        for rec in sorted_recs:
            try:
                is_strategic = rec.category in STRATEGIC_CATEGORIES

                if is_strategic:
                    # Strategic: post to bulletin as IMPROVEMENT, skip goal.
                    entry_id = self._post_strategic_to_bulletin(
                        rec, report.report_id
                    )
                    if entry_id:
                        result["bulletin_posted"].append(entry_id)
                # R1 (2026-05-29): non-strategic recs no longer create PROPOSED
                # learning goals. 99.9% of self_analysis goals aged to ABANDONED
                # without ever going ACTIVE - the planner never worked them.
                # Learning is driven by the topic-hint -> WebSource fetch pipeline
                # below, not by per-topic goals competing in the planner queue.

                # Topic hint: only for non-strategic learn/fetch recs
                # (strategic "topics" like "Akcja 'learn'" are not real topics)
                if not is_strategic and rec.suggested_action in ("fetch", "learn"):
                    if self._write_topic_hint(rec, report.report_id):
                        result["hints_written"] += 1

                # Belief: still record observation for both paths (K6 sees it)
                # Audyt 2026-06-12: licznik rosl bezwarunkowo, a WorldModel
                # nie ma add_belief -- raport klamal "N beliefs" przy 0 zapisow.
                if self._world_model:
                    if self._update_belief(rec):
                        result["beliefs_updated"] += 1

            except Exception as e:
                logger.warning(f"[K12] Error applying rec {rec.rec_id}: {e}")
                result["errors"].append(f"{rec.rec_id}: {str(e)[:100]}")

        # Update report with created goals
        report.goals_created = result["goals_created"]
        report.beliefs_updated = result["beliefs_updated"]

        logger.info(
            f"[K12] Applied {len(sorted_recs)} recommendations: "
            f"{len(result['bulletin_posted'])} bulletin, "
            f"{result['hints_written']} hints, "
            f"{result['beliefs_updated']} beliefs"
        )

        return result

    def _write_topic_hint(
        self, rec: AnalysisRecommendation, report_id: str
    ) -> bool:
        """Write topic hint to JSONL for TopicSuggester (Phase 2 integration).

        R2.1 (2026-04-29): rejects unsearchable internal-meta topics and skips
        duplicates (same topic already pending in jsonl). Returns True if
        written, False if filtered out — caller increments hints_written
        only on True.
        """
        if not _is_searchable_topic(rec.topic):
            logger.debug(
                f"[K12] Hint filtered (unsearchable shape): {rec.topic[:60]}"
            )
            return False
        if self._is_duplicate_pending_hint(rec.topic):
            logger.debug(
                f"[K12] Hint filtered (duplicate pending): {rec.topic[:60]}"
            )
            return False
        if self._is_already_fetched(rec.topic):
            # R2.1.1: gap surfaces here on purpose. Fetched files that the
            # learn pipeline never adopted into knowledge_index keep coming
            # back as K12 recs every cycle. We refuse to re-queue them and
            # log loudly so the operator sees the real problem (broken
            # learn -> knowledge_index pipeline), not the symptom
            # (fetcher returns no_articles 100% of the time).
            logger.warning(
                f"[K12] Hint filtered (already fetched, learn pipeline gap): "
                f"{rec.topic[:60]!r}"
            )
            return False

        hint = {
            "topic": rec.topic,
            "source": "self_analysis",
            "report_id": report_id,
            "priority": rec.priority,
            "timestamp": time.time(),
            "consumed": False,
        }

        try:
            self._hints_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._hints_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(hint, ensure_ascii=False) + "\n")
            self._prune_hints_if_needed()
            return True
        except IOError as e:
            logger.warning(f"[K12] Could not write topic hint: {e}")
            return False

    def _is_duplicate_pending_hint(self, topic: str) -> bool:
        """Return True if a hint with the same topic is already pending.

        Compares lowercase-stripped topic strings against unconsumed entries
        in the hints file. Consumed hints don't block re-proposal — if K12
        re-flags a topic that was already fetched (and therefore consumed),
        we want the new entry to land so suggester can pick it up again.
        """
        if not self._hints_path.exists():
            return False
        target = (topic or "").lower().strip()
        if not target:
            return False
        try:
            with open(self._hints_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        h = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if h.get("consumed", False):
                        continue
                    existing = (h.get("topic") or "").lower().strip()
                    if existing == target:
                        return True
        except IOError:
            return False
        return False

    def _is_already_fetched(self, topic: str) -> bool:
        """Return True if topic already exists in web_fetch_registry.jsonl.

        R2.1.1 (2026-05-05): scope is the registry only, NOT knowledge_index.
        Rationale: if a topic was fetched but never indexed, there is a
        learn-pipeline gap — re-fetching does not fix it, only re-fetching
        the upstream learn handler does. So the filter says: if registry
        already saw this topic, do not queue it again, regardless of
        whether learn succeeded.

        Lowercase-stripped match, mirroring _is_duplicate_pending_hint
        and TopicSuggester._mark_hint_consumed.
        """
        if not self._fetch_registry_path.exists():
            return False
        target = (topic or "").lower().strip()
        if not target:
            return False
        try:
            with open(self._fetch_registry_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    existing = (d.get("topic") or "").lower().strip()
                    if existing == target:
                        return True
        except IOError:
            return False
        return False

    def _prune_hints_if_needed(self) -> None:
        """Rotate hints file to latest MAX_HINTS entries when over limit."""
        if not self._hints_path.exists():
            return
        try:
            with open(self._hints_path, "r", encoding="utf-8") as f:
                lines = [line for line in f if line.strip()]
        except IOError as e:
            logger.warning(f"[K12] Could not read topic hints for prune: {e}")
            return

        if len(lines) <= MAX_HINTS:
            return

        latest = lines[-MAX_HINTS:]
        tmp_path = self._hints_path.with_suffix(self._hints_path.suffix + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(latest)
            tmp_path.replace(self._hints_path)
        except IOError as e:
            logger.warning(f"[K12] Could not prune topic hints: {e}")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _update_belief(self, rec: AnalysisRecommendation) -> bool:
        """Add external observation as K6 belief. Returns True iff written.

        Audit 2026-06-12: no production WorldModel exposes add_belief -- this
        path has never written a belief (the hasattr guard always failed),
        while the caller's counter claimed otherwise. Until a real K6 minting
        API exists (and the trust regime allows unverified K12 observations),
        this honestly reports False instead of lying upward.
        """
        if not self._world_model:
            return False

        try:
            if hasattr(self._world_model, "add_belief"):
                self._world_model.add_belief(
                    entity=rec.topic,
                    entity_type="topic",
                    belief_type="observation",
                    content=f"External analysis: {rec.description[:200]}",
                    confidence=0.7,  # External observation, not yet verified
                    source="self_analysis",
                    tags=[rec.topic, "self_analysis", rec.category],
                )
                return True
        except Exception as e:
            logger.warning(f"[K12] Belief update failed: {e}")
        return False

    # --- D2: Strategic recs to bulletin -----------------------

    def _post_strategic_to_bulletin(
        self, rec: AnalysisRecommendation, report_id: str
    ) -> Optional[str]:
        """Post strategic K12 recommendation to bulletin as IMPROVEMENT entry.

        Replaces the old behaviour of creating a misrouted LEARNING goal
        (e.g. "Eksperyment: Akcja 'self_analyze'"). The bulletin gives K12
        an advisory channel that operator and planner can read without
        polluting the goal queue with un-actionable learning targets.
        """
        if self._bulletin_store is None:
            logger.debug(
                f"[K12] No bulletin_store, dropping strategic rec {rec.rec_id}"
            )
            return None

        try:
            from agent_core.bulletin.bulletin_model import EntryType
        except Exception as e:
            logger.warning(f"[K12] Bulletin import failed: {e}")
            return None

        action_hint = self._extract_action_hint(rec.topic)
        summary = rec.description[:200] if rec.description else rec.topic

        try:
            entry = self._bulletin_store.create_and_post(
                entry_type=EntryType.IMPROVEMENT,
                topic=rec.topic,
                reason_code=f"k12_{rec.category}",
                summary=summary,
                requested_by="self_analysis",
                priority=rec.priority,
                metadata={
                    "rec_id": rec.rec_id,
                    "report_id": report_id,
                    "category": rec.category,
                    "suggested_action": rec.suggested_action,
                    "action_hint": action_hint,
                },
            )
            logger.info(
                f"[K12] Posted IMPROVEMENT: {entry.entry_id} "
                f"hint={action_hint!r} pri={rec.priority:.2f} "
                f"({rec.topic[:50]})"
            )
        except Exception as e:
            logger.warning(f"[K12] Bulletin post failed: {e}")
            return None

        # Most #2 step 1: route experiment-suggested recs through K11 heuristics.
        # Bulletin entry was already posted above — router is best-effort
        # additive. Failures here must not roll back the bulletin entry.
        if (self._proposal_engine is not None
                and rec.suggested_action == "experiment"):
            try:
                from agent_core.self_analysis.k12_to_k11_router import (
                    route_recommendation,
                    AUTO_APPROVE_CONFIDENCE,
                )
                from agent_core.experiment.experiment_model import (
                    ProposalStatus,
                )

                match = route_recommendation(rec)
                if match is not None:
                    accepted = self._proposal_engine.add_proposal(match.proposal)
                    if accepted:
                        if match.confidence >= AUTO_APPROVE_CONFIDENCE:
                            self._proposal_engine.update_status(
                                match.proposal.proposal_id,
                                ProposalStatus.APPROVED,
                            )
                            logger.info(
                                f"[K12->K11] Auto-approved {match.proposal.proposal_id} "
                                f"(heuristic={match.heuristic_name}, "
                                f"conf={match.confidence:.2f})"
                            )
                        else:
                            logger.info(
                                f"[K12->K11] DRAFT {match.proposal.proposal_id} "
                                f"awaiting operator review "
                                f"(heuristic={match.heuristic_name}, "
                                f"conf={match.confidence:.2f})"
                            )
            except Exception as e:
                logger.warning(f"[K12->K11] router failed (non-fatal): {e}")

        return entry.entry_id

    def _extract_action_hint(self, topic: str) -> Optional[str]:
        """Extract Maria-internal action name from a K12 strategic rec topic.

        Strategic rec topics follow loose patterns:
            "Akcja 'self_analyze'"        -> "self_analyze"
            "proces nauki (learn action)" -> "learn"
            "effector_actions"            -> "effector"
            "trudny temat (hard_topic)"   -> None (not an action)

        Returns None if no known action name is detected. Stored as metadata
        for future planner advisory; raw topic is always preserved.
        """
        if not topic:
            return None
        text = topic.lower()

        # Quoted action: Akcja 'X' / "X"
        m = re.search(r"['\"]([a-z_]+)['\"]", text)
        if m and m.group(1) in _KNOWN_ACTIONS:
            return m.group(1)

        # Suffix form: "X_action" or "X_actions" -> X
        # Underscore is a word char in Python regex, so plain \b boundaries
        # would not catch "effector_actions"; handle the suffix explicitly.
        m2 = re.match(r"^([a-z_]+)_actions?$", text)
        if m2 and m2.group(1) in _KNOWN_ACTIONS:
            return m2.group(1)

        # Inline whole-word match: "(learn action)"
        for action in _KNOWN_ACTIONS:
            if re.search(rf"\b{re.escape(action)}\b", text):
                return action

        return None
