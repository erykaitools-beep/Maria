"""
Auto-Promotion - Maria proposes authority upgrades based on earned trust.

Flow:
1. TrustScorer calculates trust per action type
2. If trust exceeds threshold -> AutoPromotion creates a PROPOSED goal
3. Operator approves via /approve (Telegram or Web UI)
4. On approval: authority level upgraded, probation starts (7 days)
5. If regression during probation: auto-rollback to previous level

Faza 7: Trust & Autonomy Graduation (Digital Human Roadmap).

Anti-pattern: Automatic granting without track record.
Trust must be EARNED, not given.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from agent_core.autonomy.authority_level import (
    AuthorityLevel,
    AuthorityManager,
    level_index,
)
from agent_core.autonomy.trust_scorer import (
    PromotionProposal,
    TrustScorer,
)

logger = logging.getLogger(__name__)

# Promotion settings
PROMOTION_CHECK_INTERVAL_SEC = 4 * 3600   # Check every 4 hours
PROMOTION_COOLDOWN_SEC = 24 * 3600         # Max 1 proposal per 24h
REGRESSION_THRESHOLD = 0.10                # Trust drop of 10% = regression
DEFAULT_PROMOTION_LOG_PATH = Path("meta_data/promotion_history.jsonl")


@dataclass
class PromotionEvent:
    """Record of a promotion-related event."""
    event_type: str        # proposed / approved / rejected / rollback / probation_passed
    timestamp: float
    from_level: str
    to_level: str
    trust_score: float
    details: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Serialize for JSONL."""
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "from_level": self.from_level,
            "to_level": self.to_level,
            "trust_score": round(self.trust_score, 3),
            "details": self.details,
        }


class AutoPromotion:
    """
    Manages earned authority upgrades.

    Integrated with:
    - TrustScorer: calculates when promotion is earned
    - GoalStore: creates PROPOSED goals for operator approval
    - AuthorityManager: applies approved promotions
    - Telegram: notifies operator about proposals

    Thread-safe for tick loop integration.
    """

    def __init__(
        self,
        trust_scorer: Optional[TrustScorer] = None,
        authority_manager: Optional[AuthorityManager] = None,
        goal_store=None,
        notify_fn: Optional[Callable[[str, str], None]] = None,
        log_path: Optional[Path] = None,
    ):
        self._scorer = trust_scorer
        self._authority = authority_manager
        self._goal_store = goal_store
        self._notify_fn = notify_fn  # Telegram notification
        self._log_path = log_path or DEFAULT_PROMOTION_LOG_PATH

        # State
        self._last_check_at: float = 0.0
        self._last_proposal_at: float = 0.0
        self._pending_proposal: Optional[PromotionProposal] = None
        self._pending_goal_id: Optional[str] = None
        self._pre_promotion_level: Optional[AuthorityLevel] = None
        self._pre_promotion_trust: float = 0.0
        self._history: List[PromotionEvent] = []

        self._load_history()

    # -- Setters for late wiring --

    def set_trust_scorer(self, scorer: TrustScorer) -> None:
        """Set trust scorer (late wiring)."""
        self._scorer = scorer

    def set_authority_manager(self, manager: AuthorityManager) -> None:
        """Set authority manager (late wiring)."""
        self._authority = manager

    def set_goal_store(self, store) -> None:
        """Set goal store (late wiring)."""
        self._goal_store = store

    def set_notify_fn(self, fn: Callable[[str, str], None]) -> None:
        """Set notification function (late wiring)."""
        self._notify_fn = fn

    # -- Main tick entry point --

    def tick(self) -> Optional[Dict]:
        """
        Called from homeostasis tick loop.

        Checks:
        1. Is it time to check? (every PROMOTION_CHECK_INTERVAL_SEC)
        2. Is there a pending proposal that got approved?
        3. Is probation still clean?
        4. Should we propose a new promotion?

        Returns action dict if something happened, None otherwise.
        """
        now = time.time()

        # Rate limit checks
        if now - self._last_check_at < PROMOTION_CHECK_INTERVAL_SEC:
            return None
        self._last_check_at = now

        if not self._scorer or not self._authority:
            return None

        # Step 1: Check if pending proposal was approved/rejected
        result = self._check_pending_proposal()
        if result:
            return result

        # Step 2: Check probation (if in probation)
        result = self._check_probation()
        if result:
            return result

        # Step 3: Maybe propose new promotion
        result = self._maybe_propose()
        if result:
            return result

        return None

    # -- Internal logic --

    def _check_pending_proposal(self) -> Optional[Dict]:
        """Check if a pending promotion goal was approved/rejected."""
        if not self._pending_goal_id or not self._goal_store:
            return None

        try:
            goal = self._goal_store.get(self._pending_goal_id)
            if not goal:
                self._pending_goal_id = None
                self._pending_proposal = None
                return None

            status = goal.status.value if hasattr(goal.status, 'value') else str(goal.status)

            if status == "active" or status == "pending":
                # Approved! Apply promotion.
                return self._apply_promotion()

            elif status in ("failed", "abandoned"):
                # Rejected by operator
                self._log_event("rejected",
                    from_level=self._pending_proposal.current_level.value if self._pending_proposal else "?",
                    to_level=self._pending_proposal.proposed_level.value if self._pending_proposal else "?",
                    trust_score=self._pending_proposal.trust_score if self._pending_proposal else 0.0,
                    details={"reason": "operator_rejected"},
                )
                if self._notify_fn:
                    self._notify_fn(
                        "promotion_rejected",
                        "Operator odrzucil propozycje awansu autonomii.",
                    )
                self._pending_goal_id = None
                self._pending_proposal = None
                return {"action": "promotion_rejected"}

        except Exception as e:
            logger.debug("Pending proposal check failed: %s", e)

        return None

    def _apply_promotion(self) -> Optional[Dict]:
        """Apply an approved promotion."""
        if not self._pending_proposal or not self._authority:
            return None

        proposal = self._pending_proposal
        old_level = proposal.current_level
        new_level = proposal.proposed_level

        # Apply the level change
        success = self._authority.set_level(new_level)
        if not success:
            logger.warning("Failed to apply promotion to %s", new_level.value)
            self._pending_goal_id = None
            self._pending_proposal = None
            return None

        # Start probation tracking
        self._pre_promotion_level = old_level
        self._pre_promotion_trust = proposal.trust_score
        self._scorer.record_promotion()

        # Log event
        self._log_event("approved",
            from_level=old_level.value,
            to_level=new_level.value,
            trust_score=proposal.trust_score,
            details={"action_types": proposal.action_types},
        )

        # Complete the goal
        if self._goal_store and self._pending_goal_id:
            try:
                self._goal_store.update_status(
                    self._pending_goal_id, "achieved",
                    reason="Promotion applied", actor="auto_promotion",
                )
            except Exception:
                pass

        # Notify operator
        if self._notify_fn:
            self._notify_fn(
                "promotion_approved",
                f"Autonomia awansowana: {old_level.value} -> {new_level.value} "
                f"(trust: {proposal.trust_score:.2f}). "
                f"Probacja: 7 dni.",
            )

        logger.info(
            "Authority promoted: %s -> %s (trust: %.2f)",
            old_level.value, new_level.value, proposal.trust_score,
        )

        self._pending_goal_id = None
        self._pending_proposal = None

        return {
            "action": "promotion_applied",
            "from": old_level.value,
            "to": new_level.value,
            "trust": proposal.trust_score,
        }

    def _check_probation(self) -> Optional[Dict]:
        """Check if probation period is still clean (no regression)."""
        if not self._scorer.is_in_probation():
            return None

        if self._pre_promotion_level is None:
            return None

        # Check for regression
        current_trust = self._scorer.get_average_trust()
        trust_drop = self._pre_promotion_trust - current_trust

        if trust_drop >= REGRESSION_THRESHOLD:
            # Regression detected! Rollback.
            return self._rollback(
                reason=f"Trust regression during probation: "
                       f"{self._pre_promotion_trust:.2f} -> {current_trust:.2f} "
                       f"(drop: {trust_drop:.2f})",
            )

        # Check if probation completed
        remaining = self._scorer.get_probation_remaining_days()
        if remaining <= 0:
            self._log_event("probation_passed",
                from_level=self._pre_promotion_level.value,
                to_level=self._authority.get_level().value if self._authority else "?",
                trust_score=current_trust,
            )
            if self._notify_fn:
                self._notify_fn(
                    "probation_passed",
                    f"Probacja zakonczona pomyslnie! "
                    f"Trust: {current_trust:.2f}. "
                    f"Nowy poziom autonomii jest trwaly.",
                )
            self._pre_promotion_level = None
            self._pre_promotion_trust = 0.0
            return {"action": "probation_passed"}

        return None

    def _rollback(self, reason: str) -> Dict:
        """Rollback to previous authority level."""
        old_level = self._authority.get_level() if self._authority else AuthorityLevel.OBSERVE
        target_level = self._pre_promotion_level or AuthorityLevel.OBSERVE

        if self._authority:
            self._authority.set_level(target_level)

        self._log_event("rollback",
            from_level=old_level.value,
            to_level=target_level.value,
            trust_score=self._scorer.get_average_trust() if self._scorer else 0.0,
            details={"reason": reason},
        )

        if self._notify_fn:
            self._notify_fn(
                "promotion_rollback",
                f"Autonomia cofnieta: {old_level.value} -> {target_level.value}. "
                f"Powod: {reason}",
            )

        logger.warning(
            "Authority rolled back: %s -> %s. Reason: %s",
            old_level.value, target_level.value, reason,
        )

        self._pre_promotion_level = None
        self._pre_promotion_trust = 0.0

        return {
            "action": "promotion_rollback",
            "from": old_level.value,
            "to": target_level.value,
            "reason": reason,
        }

    def _maybe_propose(self) -> Optional[Dict]:
        """Propose a promotion if trust supports it."""
        now = time.time()

        # Cooldown between proposals
        if now - self._last_proposal_at < PROMOTION_COOLDOWN_SEC:
            return None

        # Don't propose during probation
        if self._scorer.is_in_probation():
            return None

        # Already have a pending proposal
        if self._pending_goal_id:
            return None

        # Ask TrustScorer
        proposal = self._scorer.suggest_promotion()
        if not proposal:
            return None

        # Create a PROPOSED goal for operator approval
        goal_id = None
        if self._goal_store:
            try:
                goal_id = self._goal_store.propose(
                    description=(
                        f"Awans autonomii: {proposal.current_level.value} -> "
                        f"{proposal.proposed_level.value} "
                        f"(trust: {proposal.trust_score:.2f})"
                    ),
                    goal_type="user",
                    source="auto_promotion",
                    metadata={
                        "promotion": proposal.to_dict(),
                        "type": "authority_promotion",
                    },
                )
            except Exception as e:
                logger.warning("Failed to create promotion goal: %s", e)
                return None

        self._pending_proposal = proposal
        self._pending_goal_id = goal_id
        self._last_proposal_at = now

        self._log_event("proposed",
            from_level=proposal.current_level.value,
            to_level=proposal.proposed_level.value,
            trust_score=proposal.trust_score,
            details={"action_types": proposal.action_types},
        )

        # Notify operator
        if self._notify_fn:
            self._notify_fn(
                "promotion_proposed",
                f"Maria proponuje awans autonomii:\n"
                f"{proposal.current_level.value} -> {proposal.proposed_level.value}\n"
                f"Trust: {proposal.trust_score:.2f} (prog: {proposal.threshold:.2f})\n"
                f"Na podstawie {len(proposal.action_types)} typow akcji.\n"
                f"Uzyj /approve lub /reject.",
            )

        logger.info(
            "Promotion proposed: %s -> %s (trust: %.2f)",
            proposal.current_level.value,
            proposal.proposed_level.value,
            proposal.trust_score,
        )

        return {
            "action": "promotion_proposed",
            "proposal": proposal.to_dict(),
            "goal_id": goal_id,
        }

    # -- Persistence --

    def _log_event(
        self,
        event_type: str,
        from_level: str,
        to_level: str,
        trust_score: float,
        details: Optional[Dict] = None,
    ) -> None:
        """Log a promotion event to JSONL."""
        event = PromotionEvent(
            event_type=event_type,
            timestamp=time.time(),
            from_level=from_level,
            to_level=to_level,
            trust_score=trust_score,
            details=details or {},
        )
        self._history.append(event)

        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to persist promotion event: %s", e)

    def _load_history(self) -> None:
        """Load promotion history from JSONL."""
        if not self._log_path.exists():
            return
        try:
            lines = self._log_path.read_text(encoding="utf-8").strip().split("\n")
            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    self._history.append(PromotionEvent(
                        event_type=data.get("event_type", ""),
                        timestamp=data.get("timestamp", 0.0),
                        from_level=data.get("from_level", ""),
                        to_level=data.get("to_level", ""),
                        trust_score=data.get("trust_score", 0.0),
                        details=data.get("details", {}),
                    ))
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception as e:
            logger.warning("Failed to load promotion history: %s", e)

    # -- Query API --

    def get_history(self, limit: int = 20) -> List[Dict]:
        """Get recent promotion history."""
        return [e.to_dict() for e in self._history[-limit:]]

    def get_status(self) -> Dict:
        """Get auto-promotion status for UI/Telegram."""
        return {
            "pending_proposal": self._pending_proposal.to_dict() if self._pending_proposal else None,
            "pending_goal_id": self._pending_goal_id,
            "in_probation": self._scorer.is_in_probation() if self._scorer else False,
            "probation_remaining_days": round(
                self._scorer.get_probation_remaining_days(), 1
            ) if self._scorer else 0.0,
            "last_proposal_at": self._last_proposal_at,
            "history_count": len(self._history),
        }
