"""
Trust Scorer - Calculates earned trust per action type.

Trust is NOT granted - it's earned from track record:
- Goal success/failure rates
- Approval rejection rates
- Incident penalty (decays over 7 days)
- Confidence from meta-cognition

Each action type has its own trust score. Trust determines whether
Maria can propose a promotion to a higher authority level.

Faza 7: Trust & Autonomy Graduation (Digital Human Roadmap).
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from agent_core.autonomy.authority_level import AuthorityLevel, level_index

logger = logging.getLogger(__name__)

# Trust thresholds for authority promotion
# Higher level = higher trust required
PROMOTION_THRESHOLDS = {
    # current_level -> required trust_score to propose next level
    AuthorityLevel.OBSERVE: 0.75,    # OBSERVE -> SUGGEST
    AuthorityLevel.SUGGEST: 0.82,    # SUGGEST -> CONFIRM
    AuthorityLevel.CONFIRM: 0.90,    # CONFIRM -> BOUNDED
    AuthorityLevel.BOUNDED: 0.95,    # BOUNDED -> UNRESTRICTED (not available in Phase 5)
}

# Minimum successful actions before trust is meaningful
MIN_ACTIONS_FOR_TRUST = 10

# Actor stamped by the planner's non-productive loop detector
# (planner_core.py:4850). Among all abandon actors this is the ONLY one that
# means "Maria worked the goal and got stuck" -- every other one means nobody
# ever touched it (planner_stale_cleanup: 922 goals), the architecture moved
# (r1_cleanup: 64), the operator let a proposal lapse (system: 33), or a better
# proposal displaced it (creative: 13). Keyed on the actor, not on the reason
# text, so rewording the message cannot silently reclassify failures.
ACTOR_NONPRODUCTIVE_LOOP = "planner_nonproductive_detector"

# How many days of clean operation needed after promotion
PROBATION_DAYS = 7.0

# Weights for trust score components
WEIGHT_GOAL_SUCCESS = 0.40    # Goal completion rate
WEIGHT_REJECTION = 0.20       # Low rejection rate = good
WEIGHT_INCIDENT = 0.25        # Low incidents = good
WEIGHT_CONFIDENCE = 0.15      # Meta-cognitive confidence


@dataclass
class TrustScore:
    """Trust score for a specific action type."""
    action_type: str
    score: float                  # 0.0 to 1.0
    goal_success_rate: float      # From goal store
    rejection_rate: float         # From approval queue
    incident_penalty: float       # From incident memory
    confidence: float             # From meta-cognition
    total_actions: int            # How many actions of this type
    successful_actions: int
    failed_actions: int
    rejected_actions: int
    computed_at: float = field(default_factory=time.time)

    def has_enough_data(self) -> bool:
        """Whether we have enough history for meaningful trust."""
        return self.total_actions >= MIN_ACTIONS_FOR_TRUST

    def to_dict(self) -> Dict:
        """Serialize for API/UI."""
        return {
            "action_type": self.action_type,
            "score": round(self.score, 3),
            "goal_success_rate": round(self.goal_success_rate, 3),
            "rejection_rate": round(self.rejection_rate, 3),
            "incident_penalty": round(self.incident_penalty, 3),
            "confidence": round(self.confidence, 3),
            "total_actions": self.total_actions,
            "successful_actions": self.successful_actions,
            "failed_actions": self.failed_actions,
            "rejected_actions": self.rejected_actions,
            "has_enough_data": self.has_enough_data(),
            "computed_at": self.computed_at,
        }


@dataclass
class PromotionProposal:
    """A proposed authority level upgrade."""
    current_level: AuthorityLevel
    proposed_level: AuthorityLevel
    trust_score: float
    threshold: float
    action_types: List[str]       # Which action types support this
    reason: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        """Serialize for API/UI."""
        return {
            "current_level": self.current_level.value,
            "proposed_level": self.proposed_level.value,
            "trust_score": round(self.trust_score, 3),
            "threshold": round(self.threshold, 3),
            "action_types": self.action_types,
            "reason": self.reason,
            "created_at": self.created_at,
        }


class TrustScorer:
    """
    Computes trust scores from multiple data sources.

    Data sources (all optional, graceful degradation):
    - goal_store: Goal success/failure counts
    - approval_queue: Rejection rate
    - incident_memory: Failure penalties
    - confidence_tracker: Meta-cognitive confidence

    Thread-safe (reads only, no mutation).
    """

    def __init__(
        self,
        goal_store=None,
        approval_queue=None,
        incident_memory=None,
        confidence_tracker=None,
        authority_manager=None,
    ):
        self._goal_store = goal_store
        self._approval_queue = approval_queue
        self._incident_memory = incident_memory
        self._confidence_tracker = confidence_tracker
        self._authority_manager = authority_manager
        # Track promotion history (thread-safe)
        self._lock = threading.Lock()
        self._last_promotion_at: float = 0.0
        self._promotion_action_types: Set[str] = set()

    # -- Setters for late wiring --

    def set_goal_store(self, store) -> None:
        """Set goal store (late wiring)."""
        self._goal_store = store

    def set_approval_queue(self, queue) -> None:
        """Set approval queue (late wiring)."""
        self._approval_queue = queue

    def set_incident_memory(self, memory) -> None:
        """Set incident memory (late wiring)."""
        self._incident_memory = memory

    def set_confidence_tracker(self, tracker) -> None:
        """Set confidence tracker (late wiring)."""
        self._confidence_tracker = tracker

    def set_authority_manager(self, manager) -> None:
        """Set authority manager (late wiring)."""
        self._authority_manager = manager

    # -- Core scoring --

    def calculate_trust(self, action_type: str) -> TrustScore:
        """
        Calculate trust score for a specific action type.

        Aggregates from all available data sources.
        Returns DEFAULT (0.5) if insufficient data.
        """
        # Component 1: Goal success rate
        success_count = 0
        fail_count = 0
        goal_success_rate = 0.5  # default

        if self._goal_store:
            try:
                goals = self._goal_store.get_all()
                for g in goals:
                    # Match goals to action types through audit trail
                    if self._goal_matches_action(g, action_type):
                        outcome = self._goal_outcome(g)
                        if outcome is True:
                            success_count += 1
                        elif outcome is False:
                            fail_count += 1
                total = success_count + fail_count
                if total >= 3:
                    goal_success_rate = success_count / total
            except Exception as e:
                logger.debug("Goal store read failed: %s", e)

        # Component 2: Rejection rate
        rejected_count = 0
        rejection_rate = 0.0  # default (no rejections = good)

        if self._approval_queue:
            try:
                stats = self._approval_queue.get_stats()
                approved = stats.get("approved", 0)
                rejected = stats.get("rejected", 0)
                rejected_count = rejected
                total_decisions = approved + rejected
                if total_decisions >= 3:
                    rejection_rate = rejected / total_decisions
            except Exception as e:
                logger.debug("Approval queue read failed: %s", e)

        # Component 3: Incident penalty
        incident_penalty = 0.0
        if self._incident_memory:
            try:
                incident_penalty = self._incident_memory.get_incident_penalty(
                    action_type
                )
            except Exception as e:
                logger.debug("Incident memory read failed: %s", e)

        # Component 4: Meta-cognitive confidence
        confidence = 0.5  # default
        if self._confidence_tracker:
            try:
                confidence = self._confidence_tracker.get_action_confidence(
                    action_type
                )
            except Exception as e:
                logger.debug("Confidence tracker read failed: %s", e)

        # Combine components into final score
        total_actions = success_count + fail_count
        score = self._compute_score(
            goal_success_rate=goal_success_rate,
            rejection_rate=rejection_rate,
            incident_penalty=incident_penalty,
            confidence=confidence,
        )

        return TrustScore(
            action_type=action_type,
            score=score,
            goal_success_rate=goal_success_rate,
            rejection_rate=rejection_rate,
            incident_penalty=incident_penalty,
            confidence=confidence,
            total_actions=total_actions,
            successful_actions=success_count,
            failed_actions=fail_count,
            rejected_actions=rejected_count,
        )

    def calculate_all(self) -> Dict[str, TrustScore]:
        """
        Calculate trust scores for all known action types.

        Returns dict of {action_type: TrustScore}.
        """
        action_types = self._get_known_action_types()
        return {
            at: self.calculate_trust(at) for at in sorted(action_types)
        }

    def get_average_trust(self) -> float:
        """Get average trust across all action types."""
        scores = self.calculate_all()
        if not scores:
            return 0.5
        return sum(s.score for s in scores.values()) / len(scores)

    # -- Promotion logic --

    def suggest_promotion(self) -> Optional[PromotionProposal]:
        """
        Check if Maria's track record supports an authority promotion.

        Returns a PromotionProposal if conditions are met, None otherwise.

        Conditions:
        1. Average trust exceeds threshold for current level
        2. Enough total actions (MIN_ACTIONS_FOR_TRUST)
        3. Not in probation period from recent promotion
        4. Current level < BOUNDED (max in Phase 5)
        """
        if not self._authority_manager:
            return None

        current_level = self._authority_manager.get_level()

        # Can't promote beyond BOUNDED (Phase 5 limit)
        if level_index(current_level) >= level_index(AuthorityLevel.BOUNDED):
            return None

        # Check probation period
        if self._last_promotion_at > 0:
            days_since = (time.time() - self._last_promotion_at) / 86400.0
            if days_since < PROBATION_DAYS:
                return None

        # Get threshold for current level
        threshold = PROMOTION_THRESHOLDS.get(current_level)
        if threshold is None:
            return None

        # Calculate trust for all action types
        scores = self.calculate_all()
        if not scores:
            return None

        # Need at least some action types with enough data
        qualified = {
            at: s for at, s in scores.items() if s.has_enough_data()
        }
        if not qualified:
            return None

        # Average trust of qualified action types
        avg_trust = sum(s.score for s in qualified.values()) / len(qualified)

        if avg_trust < threshold:
            return None

        # Determine next level
        current_idx = level_index(current_level)
        next_level_candidates = [
            l for l in AuthorityLevel
            if level_index(l) == current_idx + 1
            and l != AuthorityLevel.UNRESTRICTED
        ]
        if not next_level_candidates:
            return None

        next_level = next_level_candidates[0]

        return PromotionProposal(
            current_level=current_level,
            proposed_level=next_level,
            trust_score=avg_trust,
            threshold=threshold,
            action_types=list(qualified.keys()),
            reason=(
                f"Trust score {avg_trust:.2f} exceeds threshold {threshold:.2f} "
                f"based on {sum(s.total_actions for s in qualified.values())} actions "
                f"across {len(qualified)} action types."
            ),
        )

    def record_promotion(self) -> None:
        """Record that a promotion was approved (starts probation)."""
        with self._lock:
            self._last_promotion_at = time.time()

    def is_in_probation(self) -> bool:
        """Check if Maria is in probation period after promotion."""
        with self._lock:
            if self._last_promotion_at <= 0:
                return False
            days_since = (time.time() - self._last_promotion_at) / 86400.0
            return days_since < PROBATION_DAYS

    def get_probation_remaining_days(self) -> float:
        """Days remaining in probation (0.0 if not in probation)."""
        with self._lock:
            if self._last_promotion_at <= 0:
                return 0.0
            days_since = (time.time() - self._last_promotion_at) / 86400.0
            remaining = PROBATION_DAYS - days_since
            return max(0.0, remaining)

    # -- Dashboard data --

    def get_dashboard(self) -> Dict:
        """
        Get full trust dashboard data for Web UI / Telegram.

        Returns:
            Dict with trust scores, promotion status, probation info.
        """
        scores = self.calculate_all()
        promotion = self.suggest_promotion()

        current_level = "observe"
        if self._authority_manager:
            current_level = self._authority_manager.get_level().value

        return {
            "current_authority": current_level,
            "trust_scores": {
                at: ts.to_dict() for at, ts in scores.items()
            },
            "average_trust": round(self.get_average_trust(), 3),
            "promotion_available": promotion is not None,
            "promotion": promotion.to_dict() if promotion else None,
            "in_probation": self.is_in_probation(),
            "probation_remaining_days": round(
                self.get_probation_remaining_days(), 1
            ),
            "min_actions_required": MIN_ACTIONS_FOR_TRUST,
        }

    # -- Internal helpers --

    @staticmethod
    def _compute_score(
        goal_success_rate: float,
        rejection_rate: float,
        incident_penalty: float,
        confidence: float,
    ) -> float:
        """
        Weighted combination of trust components.

        Score formula:
          S = w1*goal_success + w2*(1-rejection) + w3*(1-penalty) + w4*confidence

        All components normalized to 0.0-1.0.
        """
        score = (
            WEIGHT_GOAL_SUCCESS * goal_success_rate
            + WEIGHT_REJECTION * (1.0 - rejection_rate)
            + WEIGHT_INCIDENT * (1.0 - min(incident_penalty, 1.0))
            + WEIGHT_CONFIDENCE * confidence
        )
        return max(0.0, min(1.0, score))

    @staticmethod
    def _goal_outcome(goal) -> Optional[bool]:
        """Did Maria succeed, fail, or never actually get to try?

        Returns True (success), False (failure) or None (no evidence -- excluded
        from the rate entirely, rather than counted against her).

        ABANDONED IS NOT A FAILURE. It was counted as one until 2026-07-15, and
        on live data 95.6% of goals (1140/1192) are abandoned -- so the "goal
        success rate" was mostly measuring goal EXPIRY. Of those, 922 were
        dropped by planner_stale_cleanup as "stale: pending 72h with no
        progress": nobody ever started them (0/926 had progress > 0). Scoring
        Maria's trustworthiness down for goals no one ever ran conflates a
        backlog problem with an ability problem.

        A failure needs evidence she TRIED: either measurable progress that did
        not reach the finish, or the planner's own non-productive-loop verdict
        (20 consecutive actions without progress -- trying hard and getting
        nowhere is the realest failure there is, even at progress 0).
        """
        try:
            status = (goal.status.value if hasattr(goal.status, 'value')
                      else str(goal.status))
        except Exception:
            return None

        if status == "achieved":
            return True
        if status == "failed":
            return False
        if status != "abandoned":
            # active / pending / proposed / cancelled -- verdict not in yet.
            return None

        if (getattr(goal, "progress", 0) or 0) > 0:
            return False  # moved the needle, never finished

        for entry in reversed(getattr(goal, "audit_trail", None) or []):
            if str(getattr(entry, "new_status", "")) != "abandoned":
                continue
            if getattr(entry, "actor", "") == ACTOR_NONPRODUCTIVE_LOOP:
                return False  # tried hard, went nowhere -- a real failure
            return None  # any other actor: nobody ever ran it -- no evidence

        return None  # abandoned with no audit trail -- no evidence either way

    @staticmethod
    def _goal_matches_action(goal, action_type: str) -> bool:
        """
        Check if a goal is related to an action type.

        Uses goal type as proxy:
        - LEARNING goals -> learn, exam, review, fetch
        - MAINTENANCE goals -> maintenance, evaluate, critique
        - USER goals -> effector, ask_expert
        """
        # Goal declares `type` (goal_model.py:84); `goal_type` is only the
        # create_goal() KWARG name. Reading goal.goal_type raised inside the
        # hasattr() ARGUMENT -- evaluated before hasattr could guard it -- so
        # this returned False for every goal since 2026-04-12: no goal ever
        # matched an action, total_actions stayed 0, has_enough_data() (min 10)
        # was never true, and propose_promotion() bailed at `if not qualified`
        # before reaching any threshold. Zero promotion proposals in history.
        try:
            gtype = goal.type.value if hasattr(goal.type, 'value') else str(goal.type)
        except Exception:
            return False

        mapping = {
            "learning": {"learn", "exam", "review", "fetch", "ask_expert"},
            "maintenance": {"maintenance", "evaluate", "critique", "self_analyze"},
            "user": {"effector", "ask_expert", "fetch"},
            "meta": {"learn", "fetch", "evaluate"},
        }

        return action_type in mapping.get(gtype, set())

    def _get_known_action_types(self) -> Set[str]:
        """Collect all known action types from data sources."""
        types: Set[str] = set()

        # From goal store
        if self._goal_store:
            try:
                for g in self._goal_store.get_all():
                    gtype = g.type.value if hasattr(g.type, 'value') else str(g.type)
                    mapping = {
                        "learning": ["learn", "exam", "fetch"],
                        "maintenance": ["maintenance", "evaluate"],
                        "user": ["effector"],
                        "meta": ["learn", "fetch"],
                    }
                    types.update(mapping.get(gtype, []))
            except Exception:
                pass

        # From incident memory
        if self._incident_memory:
            try:
                for inc in self._incident_memory.get_recent(limit=100):
                    types.add(inc.action_type)
            except Exception:
                pass

        # From confidence tracker
        if self._confidence_tracker:
            try:
                cmap = self._confidence_tracker.get_confidence_map()
                types.update(cmap.keys())
            except Exception:
                pass

        # Fallback: at least these standard types. Includes "effector" -- it was
        # the one action with a real track record (16/17 achieved) yet the only
        # one missing here, so whenever the goal store contributed nothing (which
        # was ALWAYS, while _goal_matches_action was reading a phantom field) the
        # sharpest action was also the one never scored.
        if not types:
            types = {"learn", "exam", "fetch", "evaluate", "maintenance",
                     "effector"}

        return types
