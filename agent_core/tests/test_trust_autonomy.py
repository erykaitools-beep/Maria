"""
Tests for Faza 7: Trust & Autonomy Graduation.

Tests for:
- IncidentMemory: recording, querying, penalty calculation
- TrustScorer: scoring, thresholds, promotion suggestions
- AutoPromotion: proposal lifecycle, probation, rollback
"""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from agent_core.tests.spec_helpers import specced
from agent_core.goals.store import GoalStore
from agent_core.autonomy.approval_queue import ApprovalQueue
from agent_core.meta_cognition.confidence_tracker import ConfidenceTracker

from agent_core.autonomy.incident_memory import (
    IncidentMemory,
    IncidentRecord,
    PENALTY_BASE,
    PENALTY_DECAY_DAYS,
    PENALTY_MAX,
    MAX_INCIDENTS_IN_MEMORY,
)
from agent_core.autonomy.trust_scorer import (
    TrustScorer,
    TrustScore,
    PromotionProposal,
    MIN_ACTIONS_FOR_TRUST,
    PROMOTION_THRESHOLDS,
)
from agent_core.autonomy.auto_promotion import (
    AutoPromotion,
    PromotionEvent,
    PROMOTION_CHECK_INTERVAL_SEC,
    PROMOTION_COOLDOWN_SEC,
    REGRESSION_THRESHOLD,
)


def _learning_goals(achieved: int, failed: int = 0):
    """Build REAL Goal objects for trust scoring.

    These tests used to build a FakeGoal dataclass carrying a `goal_type` field.
    Goal has no such field (it declares `type`; `goal_type` is only create_goal's
    kwarg name), so the fake matched the phantom that trust_scorer.py:435 read --
    and 121 tests stayed green while _goal_matches_action returned False for
    every real goal in production, since 2026-04-12. A fake shaped like the bug
    proves nothing: build the real thing (fix 2026-07-15).
    """
    from agent_core.goals.goal_model import create_goal, GoalType, GoalStatus

    goals = []
    for _ in range(achieved):
        goals.append(create_goal(
            goal_type=GoalType.LEARNING, description="nauka", priority=0.5,
            status=GoalStatus.ACHIEVED,
        ))
    for _ in range(failed):
        goals.append(create_goal(
            goal_type=GoalType.LEARNING, description="nauka", priority=0.5,
            status=GoalStatus.FAILED,
        ))
    return goals


from agent_core.autonomy.authority_level import (
    AuthorityLevel,
    AuthorityManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_incidents(tmp_path):
    """IncidentMemory with temp path."""
    return IncidentMemory(path=tmp_path / "incidents.jsonl")


@pytest.fixture
def mock_goal_store():
    """Mock GoalStore with configurable goals."""
    store = specced(GoalStore)
    store.get_all.return_value = []
    store.get.return_value = None
    store.propose.return_value = "goal-promo-1"
    return store


@pytest.fixture
def mock_approval_queue():
    """Mock ApprovalQueue."""
    queue = specced(ApprovalQueue)
    queue.get_stats.return_value = {"approved": 0, "rejected": 0, "pending": 0}
    return queue


@pytest.fixture
def mock_confidence_tracker():
    """Mock ConfidenceTracker."""
    tracker = specced(ConfidenceTracker)
    tracker.get_action_confidence.return_value = 0.5
    tracker.get_confidence_map.return_value = {}
    return tracker


@pytest.fixture
def mock_authority(tmp_path):
    """AuthorityManager with temp config."""
    return AuthorityManager(config_path=tmp_path / "auth.json")


# ---------------------------------------------------------------------------
# IncidentMemory Tests
# ---------------------------------------------------------------------------

class TestIncidentMemory:
    """Tests for incident recording and querying."""

    def test_record_incident(self, tmp_incidents):
        """Basic incident recording."""
        inc = tmp_incidents.record_incident(
            action_type="fetch",
            error_type="timeout",
            description="Wikipedia fetch timed out after 30s",
        )
        assert inc.incident_id.startswith("inc-")
        assert inc.action_type == "fetch"
        assert inc.error_type == "timeout"
        assert inc.severity == "minor"
        assert not inc.resolved

    def test_record_with_all_fields(self, tmp_incidents):
        """Record with all optional fields."""
        inc = tmp_incidents.record_incident(
            action_type="effector",
            error_type="permission",
            description="exec tool blocked",
            tool_name="exec",
            context={"command": "ls /root"},
            goal_id="goal-123",
            severity="major",
        )
        assert inc.tool_name == "exec"
        assert inc.goal_id == "goal-123"
        assert inc.severity == "major"
        assert inc.context["command"] == "ls /root"

    def test_get_recent(self, tmp_incidents):
        """Query recent incidents."""
        tmp_incidents.record_incident(action_type="learn", error_type="parse")
        tmp_incidents.record_incident(action_type="fetch", error_type="timeout")
        tmp_incidents.record_incident(action_type="learn", error_type="llm_error")

        all_recent = tmp_incidents.get_recent()
        assert len(all_recent) == 3

        learn_only = tmp_incidents.get_recent(action_type="learn")
        assert len(learn_only) == 2

    def test_get_recent_limit(self, tmp_incidents):
        """Limit parameter works."""
        for i in range(10):
            tmp_incidents.record_incident(action_type="fetch", error_type=f"err_{i}")

        limited = tmp_incidents.get_recent(limit=3)
        assert len(limited) == 3

    def test_resolve_incident(self, tmp_incidents):
        """Resolve an incident with lessons learned."""
        inc = tmp_incidents.record_incident(
            action_type="fetch",
            error_type="timeout",
        )
        assert not inc.resolved

        result = tmp_incidents.resolve_incident(
            inc.incident_id,
            resolution="Increased timeout to 60s",
            prevention="Add retry with exponential backoff",
        )
        assert result is True

        resolved = tmp_incidents.get_recent(action_type="fetch")
        assert resolved[-1].resolved
        assert resolved[-1].resolution == "Increased timeout to 60s"

    def test_resolve_nonexistent(self, tmp_incidents):
        """Resolving non-existent incident returns False."""
        assert tmp_incidents.resolve_incident("inc-nonexistent") is False

    def test_get_unresolved(self, tmp_incidents):
        """Query unresolved incidents."""
        inc1 = tmp_incidents.record_incident(action_type="fetch", error_type="a")
        inc2 = tmp_incidents.record_incident(action_type="fetch", error_type="b")
        tmp_incidents.resolve_incident(inc1.incident_id)

        unresolved = tmp_incidents.get_unresolved()
        assert len(unresolved) == 1
        assert unresolved[0].incident_id == inc2.incident_id

    def test_incident_penalty_fresh(self, tmp_incidents):
        """Fresh incident gives full penalty."""
        tmp_incidents.record_incident(action_type="fetch", error_type="timeout")
        penalty = tmp_incidents.get_incident_penalty("fetch")
        assert penalty > 0
        assert penalty <= PENALTY_BASE * 1.1  # ~PENALTY_BASE

    def test_incident_penalty_no_incidents(self, tmp_incidents):
        """No incidents = no penalty."""
        assert tmp_incidents.get_incident_penalty("fetch") == 0.0

    def test_incident_penalty_severity(self, tmp_incidents):
        """Major incidents have higher penalty."""
        tmp_incidents.record_incident(
            action_type="a", severity="minor"
        )
        minor_penalty = tmp_incidents.get_incident_penalty("a")

        tmp_incidents.record_incident(
            action_type="b", severity="critical"
        )
        critical_penalty = tmp_incidents.get_incident_penalty("b")

        assert critical_penalty > minor_penalty

    def test_incident_penalty_capped(self, tmp_incidents):
        """Penalty is capped at PENALTY_MAX."""
        for i in range(20):
            tmp_incidents.record_incident(
                action_type="fetch", error_type=f"err_{i}", severity="critical"
            )
        penalty = tmp_incidents.get_incident_penalty("fetch")
        assert penalty <= PENALTY_MAX

    def test_incident_penalty_decays(self, tmp_incidents):
        """Old incidents have less penalty."""
        inc = tmp_incidents.record_incident(action_type="fetch", error_type="timeout")

        fresh_penalty = tmp_incidents.get_incident_penalty("fetch")

        # Simulate aging by patching timestamp
        inc.timestamp = time.time() - (PENALTY_DECAY_DAYS * 86400 * 0.9)
        aged_penalty = tmp_incidents.get_incident_penalty("fetch")

        assert aged_penalty < fresh_penalty

    def test_should_avoid_empty(self, tmp_incidents):
        """No incidents = don't avoid."""
        assert tmp_incidents.should_avoid("fetch") is False

    def test_should_avoid_recent_unresolved(self, tmp_incidents):
        """Multiple unresolved incidents = avoid."""
        tmp_incidents.record_incident(action_type="fetch", error_type="a")
        tmp_incidents.record_incident(action_type="fetch", error_type="b")

        assert tmp_incidents.should_avoid("fetch") is True

    def test_should_avoid_tool_match(self, tmp_incidents):
        """Should avoid specific tool that failed."""
        tmp_incidents.record_incident(
            action_type="effector", tool_name="exec", error_type="perm"
        )

        assert tmp_incidents.should_avoid(
            "effector", context={"tool_name": "exec"}
        ) is True
        assert tmp_incidents.should_avoid(
            "effector", context={"tool_name": "read"}
        ) is False

    def test_persistence(self, tmp_path):
        """Incidents persist across instances."""
        path = tmp_path / "incidents.jsonl"
        mem1 = IncidentMemory(path=path)
        mem1.record_incident(action_type="fetch", error_type="timeout")
        mem1.record_incident(action_type="learn", error_type="parse")

        mem2 = IncidentMemory(path=path)
        assert mem2.count() == 2
        assert mem2.count("fetch") == 1

    def test_stats(self, tmp_incidents):
        """Stats computation."""
        tmp_incidents.record_incident(action_type="fetch", severity="minor")
        tmp_incidents.record_incident(action_type="fetch", severity="major")
        tmp_incidents.record_incident(action_type="learn", severity="minor")

        stats = tmp_incidents.get_stats()
        assert stats["total"] == 3
        assert stats["unresolved"] == 3
        assert stats["by_action_type"]["fetch"] == 2
        assert stats["by_severity"]["minor"] == 2

    def test_stats_empty(self, tmp_incidents):
        """Stats on empty memory."""
        stats = tmp_incidents.get_stats()
        assert stats["total"] == 0

    def test_memory_cap(self, tmp_path):
        """In-memory cap is enforced."""
        path = tmp_path / "incidents.jsonl"
        mem = IncidentMemory(path=path)
        for i in range(MAX_INCIDENTS_IN_MEMORY + 50):
            mem.record_incident(action_type="test", error_type=f"e{i}")
        assert mem.count() == MAX_INCIDENTS_IN_MEMORY

    def test_age_days(self):
        """IncidentRecord.age_days() works."""
        rec = IncidentRecord(
            incident_id="test",
            timestamp=time.time() - 86400 * 3,  # 3 days ago
            action_type="test",
        )
        assert 2.9 < rec.age_days() < 3.1


# ---------------------------------------------------------------------------
# TrustScorer Tests
# ---------------------------------------------------------------------------

class TestTrustScorer:
    """Tests for trust score calculation."""

    def test_default_trust(self):
        """No data sources = baseline score (no negative signals)."""
        scorer = TrustScorer()
        score = scorer.calculate_trust("learn")
        # With defaults: success=0.5, rejection=0.0, penalty=0.0, confidence=0.5
        # Score = 0.4*0.5 + 0.2*1.0 + 0.25*1.0 + 0.15*0.5 = 0.725
        assert 0.7 <= score.score <= 0.75
        assert score.total_actions == 0

    def test_trust_with_good_goals(self, mock_goal_store):
        """High goal success rate = high trust."""
        goals = _learning_goals(achieved=15, failed=2)

        mock_goal_store.get_all.return_value = goals

        scorer = TrustScorer(goal_store=mock_goal_store)
        score = scorer.calculate_trust("learn")
        assert score.goal_success_rate > 0.8
        assert score.successful_actions == 15
        assert score.failed_actions == 2

    def test_trust_with_rejections(self, mock_approval_queue):
        """High rejection rate lowers trust."""
        mock_approval_queue.get_stats.return_value = {
            "approved": 5, "rejected": 5,
        }
        scorer = TrustScorer(approval_queue=mock_approval_queue)
        score = scorer.calculate_trust("effector")
        assert score.rejection_rate == 0.5

        # Compare with zero rejections
        mock_approval_queue.get_stats.return_value = {
            "approved": 10, "rejected": 0,
        }
        score_good = scorer.calculate_trust("effector")
        assert score_good.score > score.score

    def test_trust_with_incidents(self, tmp_path):
        """Incidents lower trust."""
        mem = IncidentMemory(path=tmp_path / "inc.jsonl")
        scorer_clean = TrustScorer(incident_memory=IncidentMemory(
            path=tmp_path / "clean.jsonl"
        ))
        scorer_dirty = TrustScorer(incident_memory=mem)

        # Add incidents
        for i in range(5):
            mem.record_incident(action_type="fetch", severity="major")

        clean_score = scorer_clean.calculate_trust("fetch")
        dirty_score = scorer_dirty.calculate_trust("fetch")

        assert dirty_score.incident_penalty > 0
        assert dirty_score.score < clean_score.score

    def test_trust_with_confidence(self, mock_confidence_tracker):
        """High meta-cognitive confidence boosts trust."""
        mock_confidence_tracker.get_action_confidence.return_value = 0.95

        scorer = TrustScorer(confidence_tracker=mock_confidence_tracker)
        score = scorer.calculate_trust("learn")
        assert score.confidence == 0.95

    def test_has_enough_data(self):
        """TrustScore.has_enough_data() threshold."""
        score = TrustScore(
            action_type="test", score=0.8,
            goal_success_rate=0.9, rejection_rate=0.0,
            incident_penalty=0.0, confidence=0.8,
            total_actions=MIN_ACTIONS_FOR_TRUST - 1,
            successful_actions=8, failed_actions=1, rejected_actions=0,
        )
        assert not score.has_enough_data()

        score.total_actions = MIN_ACTIONS_FOR_TRUST
        assert score.has_enough_data()

    def test_suggest_promotion_not_enough_data(self, mock_authority):
        """No promotion if not enough data."""
        scorer = TrustScorer(authority_manager=mock_authority)
        assert scorer.suggest_promotion() is None

    def test_suggest_promotion_threshold_met(
        self, mock_authority, mock_goal_store, mock_confidence_tracker
    ):
        """Promotion suggested when trust exceeds threshold."""
        # Create enough successful goals
        goals = _learning_goals(achieved=20)

        mock_goal_store.get_all.return_value = goals
        mock_confidence_tracker.get_action_confidence.return_value = 0.9
        mock_confidence_tracker.get_confidence_map.return_value = {"learn": 0.9}

        scorer = TrustScorer(
            goal_store=mock_goal_store,
            confidence_tracker=mock_confidence_tracker,
            authority_manager=mock_authority,
        )
        proposal = scorer.suggest_promotion()
        assert proposal is not None
        assert proposal.current_level == AuthorityLevel.OBSERVE
        assert proposal.proposed_level == AuthorityLevel.SUGGEST

    def test_suggest_promotion_during_probation(self, mock_authority):
        """No promotion during probation."""
        scorer = TrustScorer(authority_manager=mock_authority)
        scorer.record_promotion()  # Start probation
        assert scorer.is_in_probation()
        assert scorer.suggest_promotion() is None

    def test_suggest_promotion_at_max_level(self, mock_authority):
        """No promotion if already at BOUNDED."""
        mock_authority.set_level(AuthorityLevel.BOUNDED)
        scorer = TrustScorer(authority_manager=mock_authority)
        assert scorer.suggest_promotion() is None

    def test_calculate_all(self, mock_confidence_tracker):
        """calculate_all returns scores for all known types."""
        mock_confidence_tracker.get_confidence_map.return_value = {
            "learn": 0.8, "fetch": 0.7,
        }
        scorer = TrustScorer(confidence_tracker=mock_confidence_tracker)
        scores = scorer.calculate_all()
        assert len(scores) >= 2
        assert "learn" in scores
        assert "fetch" in scores

    def test_average_trust(self, mock_confidence_tracker):
        """Average trust across all types."""
        mock_confidence_tracker.get_confidence_map.return_value = {
            "learn": 0.8,
        }
        mock_confidence_tracker.get_action_confidence.return_value = 0.8
        scorer = TrustScorer(confidence_tracker=mock_confidence_tracker)
        avg = scorer.get_average_trust()
        assert 0.0 <= avg <= 1.0

    def test_dashboard(self, mock_authority):
        """Dashboard returns all expected fields."""
        scorer = TrustScorer(authority_manager=mock_authority)
        dash = scorer.get_dashboard()
        assert "current_authority" in dash
        assert "trust_scores" in dash
        assert "average_trust" in dash
        assert "promotion_available" in dash
        assert "in_probation" in dash
        assert "min_actions_required" in dash

    def test_probation_tracking(self):
        """Probation tracking works."""
        scorer = TrustScorer()
        assert not scorer.is_in_probation()
        assert scorer.get_probation_remaining_days() == 0.0

        scorer.record_promotion()
        assert scorer.is_in_probation()
        assert scorer.get_probation_remaining_days() > 6.9

    def test_score_to_dict(self):
        """TrustScore serialization."""
        score = TrustScore(
            action_type="learn", score=0.85,
            goal_success_rate=0.9, rejection_rate=0.05,
            incident_penalty=0.1, confidence=0.8,
            total_actions=20, successful_actions=18,
            failed_actions=2, rejected_actions=1,
        )
        d = score.to_dict()
        assert d["action_type"] == "learn"
        assert d["score"] == 0.85
        assert d["has_enough_data"] is True


# ---------------------------------------------------------------------------
# AutoPromotion Tests
# ---------------------------------------------------------------------------

class TestAutoPromotion:
    """Tests for auto-promotion lifecycle."""

    @pytest.fixture(autouse=True)
    def _enable_auto_promotion(self, monkeypatch):
        """Auto-promotion is gated OFF by default (K7 reconciliation 2026-06-07).
        These lifecycle tests exercise the promotion logic, so enable the gate for
        the whole class. Hermetic -- monkeypatch reverts after each test. The
        default-OFF behavior itself is locked by test_disabled_by_default."""
        monkeypatch.setenv("AUTO_PROMOTION_ENABLED", "1")

    def test_tick_too_early(self, mock_authority):
        """Tick returns None if check interval not reached."""
        scorer = TrustScorer(authority_manager=mock_authority)
        promo = AutoPromotion(
            trust_scorer=scorer,
            authority_manager=mock_authority,
        )
        # First tick sets last_check_at
        promo._last_check_at = time.time()
        result = promo.tick()
        assert result is None

    def test_tick_proposes_promotion(
        self, mock_authority, mock_goal_store, mock_confidence_tracker, tmp_path
    ):
        """Tick creates promotion proposal when trust is high."""
        goals = _learning_goals(achieved=20)

        mock_goal_store.get_all.return_value = goals
        mock_confidence_tracker.get_action_confidence.return_value = 0.95
        mock_confidence_tracker.get_confidence_map.return_value = {"learn": 0.95}

        scorer = TrustScorer(
            goal_store=mock_goal_store,
            confidence_tracker=mock_confidence_tracker,
            authority_manager=mock_authority,
        )

        promo = AutoPromotion(
            trust_scorer=scorer,
            authority_manager=mock_authority,
            goal_store=mock_goal_store,
            log_path=tmp_path / "promo.jsonl",
        )
        promo._last_check_at = 0  # Force check

        result = promo.tick()
        assert result is not None
        assert result["action"] == "promotion_proposed"
        assert mock_goal_store.propose.called

    def test_tick_applies_approved_promotion(
        self, mock_authority, mock_goal_store, tmp_path
    ):
        """When pending goal is approved, promotion is applied."""
        scorer = TrustScorer(authority_manager=mock_authority)

        # Simulate pending proposal
        proposal = PromotionProposal(
            current_level=AuthorityLevel.OBSERVE,
            proposed_level=AuthorityLevel.SUGGEST,
            trust_score=0.85,
            threshold=0.75,
            action_types=["learn"],
            reason="test",
        )

        # Goal status = active (approved)
        goal_mock = MagicMock()
        goal_mock.status = MagicMock(value="active")
        mock_goal_store.get.return_value = goal_mock
        mock_goal_store.update_status = MagicMock()

        promo = AutoPromotion(
            trust_scorer=scorer,
            authority_manager=mock_authority,
            goal_store=mock_goal_store,
            log_path=tmp_path / "promo.jsonl",
        )
        promo._pending_proposal = proposal
        promo._pending_goal_id = "goal-promo-1"
        promo._last_check_at = 0

        result = promo.tick()
        assert result is not None
        assert result["action"] == "promotion_applied"
        assert mock_authority.get_level() == AuthorityLevel.SUGGEST
        # Regression (audit 2026-06-01 #5): the tracking goal must be closed with
        # the GoalStatus.ACHIEVED enum, not the raw string "achieved". The string
        # raised AttributeError in update_status (status.value) and the old bare
        # `except: pass` hid it, so the goal was never actually closed.
        from agent_core.goals.goal_model import GoalStatus
        mock_goal_store.update_status.assert_called_once_with(
            "goal-promo-1", GoalStatus.ACHIEVED,
            reason="Promotion applied", actor="auto_promotion",
        )

    def test_tick_handles_rejected_proposal(
        self, mock_authority, mock_goal_store, tmp_path
    ):
        """When pending goal is rejected, proposal is cleared."""
        scorer = TrustScorer(authority_manager=mock_authority)

        proposal = PromotionProposal(
            current_level=AuthorityLevel.OBSERVE,
            proposed_level=AuthorityLevel.SUGGEST,
            trust_score=0.85,
            threshold=0.75,
            action_types=["learn"],
            reason="test",
        )

        goal_mock = MagicMock()
        goal_mock.status = MagicMock(value="abandoned")
        mock_goal_store.get.return_value = goal_mock

        promo = AutoPromotion(
            trust_scorer=scorer,
            authority_manager=mock_authority,
            goal_store=mock_goal_store,
            log_path=tmp_path / "promo.jsonl",
        )
        promo._pending_proposal = proposal
        promo._pending_goal_id = "goal-promo-1"
        promo._last_check_at = 0

        result = promo.tick()
        assert result is not None
        assert result["action"] == "promotion_rejected"
        assert promo._pending_proposal is None

    def test_rollback_on_regression(self, mock_authority, tmp_path):
        """Trust regression during probation triggers rollback."""
        mock_authority.set_level(AuthorityLevel.SUGGEST)

        scorer = TrustScorer(authority_manager=mock_authority)
        scorer.record_promotion()
        scorer._last_promotion_at = time.time()  # In probation

        promo = AutoPromotion(
            trust_scorer=scorer,
            authority_manager=mock_authority,
            log_path=tmp_path / "promo.jsonl",
        )
        promo._pre_promotion_level = AuthorityLevel.OBSERVE
        promo._pre_promotion_trust = 0.85
        promo._last_check_at = 0

        # Mock low trust (regression)
        with patch.object(scorer, 'get_average_trust', return_value=0.70):
            result = promo.tick()

        assert result is not None
        assert result["action"] == "promotion_rollback"
        assert mock_authority.get_level() == AuthorityLevel.OBSERVE

    def test_no_proposal_during_cooldown(self, mock_authority, tmp_path):
        """No new proposal during cooldown period."""
        scorer = TrustScorer(authority_manager=mock_authority)

        promo = AutoPromotion(
            trust_scorer=scorer,
            authority_manager=mock_authority,
            log_path=tmp_path / "promo.jsonl",
        )
        promo._last_check_at = 0
        promo._last_proposal_at = time.time()  # Just proposed

        result = promo.tick()
        assert result is None

    def test_notification_on_propose(
        self, mock_authority, mock_goal_store, mock_confidence_tracker, tmp_path
    ):
        """Notification function called on proposal."""
        goals = _learning_goals(achieved=20)

        mock_goal_store.get_all.return_value = goals
        mock_confidence_tracker.get_action_confidence.return_value = 0.95
        mock_confidence_tracker.get_confidence_map.return_value = {"learn": 0.95}

        notify_calls = []
        def mock_notify(category, msg):
            notify_calls.append((category, msg))

        scorer = TrustScorer(
            goal_store=mock_goal_store,
            confidence_tracker=mock_confidence_tracker,
            authority_manager=mock_authority,
        )

        promo = AutoPromotion(
            trust_scorer=scorer,
            authority_manager=mock_authority,
            goal_store=mock_goal_store,
            notify_fn=mock_notify,
            log_path=tmp_path / "promo.jsonl",
        )
        promo._last_check_at = 0

        promo.tick()
        assert len(notify_calls) == 1
        assert notify_calls[0][0] == "promotion_proposed"

    def test_history_persistence(self, tmp_path):
        """Promotion history persists to JSONL."""
        path = tmp_path / "promo.jsonl"
        scorer = TrustScorer()

        promo = AutoPromotion(
            trust_scorer=scorer,
            log_path=path,
        )
        promo._log_event(
            "proposed", "observe", "suggest", 0.85,
            details={"test": True},
        )
        assert path.exists()

        # Reload
        promo2 = AutoPromotion(trust_scorer=scorer, log_path=path)
        history = promo2.get_history()
        assert len(history) == 1
        assert history[0]["event_type"] == "proposed"

    def test_get_status(self, mock_authority, tmp_path):
        """Status returns expected fields."""
        scorer = TrustScorer(authority_manager=mock_authority)
        promo = AutoPromotion(
            trust_scorer=scorer,
            authority_manager=mock_authority,
            log_path=tmp_path / "promo.jsonl",
        )
        status = promo.get_status()
        assert "pending_proposal" in status
        assert "in_probation" in status
        assert "history_count" in status

    def test_late_wiring(self, mock_authority, mock_goal_store, tmp_path):
        """Late wiring setters work."""
        scorer = TrustScorer()
        promo = AutoPromotion(log_path=tmp_path / "promo.jsonl")

        promo.set_trust_scorer(scorer)
        promo.set_authority_manager(mock_authority)
        promo.set_goal_store(mock_goal_store)

        notify_calls = []
        promo.set_notify_fn(lambda cat, msg: notify_calls.append(cat))

        assert promo._scorer is scorer
        assert promo._authority is mock_authority

    # -- K7 reconciliation 2026-06-07: gate + signature-fix locks ----------

    def test_disabled_by_default(self, mock_authority, monkeypatch):
        """With the env flag absent, the promoter is OFF and tick() is a no-op
        even when trust would otherwise warrant a proposal. Locks the safe
        default: authority stays operator-only until deliberately enabled."""
        monkeypatch.delenv("AUTO_PROMOTION_ENABLED", raising=False)
        scorer = TrustScorer(authority_manager=mock_authority)
        promo = AutoPromotion(
            trust_scorer=scorer,
            authority_manager=mock_authority,
        )
        assert promo._enabled is False
        promo._last_check_at = 0  # would force a check if enabled
        assert promo.tick() is None

    def test_tick_noop_when_disabled(
        self, mock_authority, mock_goal_store, mock_confidence_tracker, tmp_path
    ):
        """Explicit enabled=False short-circuits before any work -- no proposal
        even with a high-trust track record."""
        goals = _learning_goals(achieved=20)
        mock_goal_store.get_all.return_value = goals
        mock_confidence_tracker.get_action_confidence.return_value = 0.95
        mock_confidence_tracker.get_confidence_map.return_value = {"learn": 0.95}

        scorer = TrustScorer(
            goal_store=mock_goal_store,
            confidence_tracker=mock_confidence_tracker,
            authority_manager=mock_authority,
        )
        promo = AutoPromotion(
            trust_scorer=scorer,
            authority_manager=mock_authority,
            goal_store=mock_goal_store,
            log_path=tmp_path / "promo.jsonl",
            enabled=False,
        )
        promo._last_check_at = 0
        assert promo.tick() is None
        assert not mock_goal_store.propose.called

    def test_propose_builds_real_goal_and_stays_proposed(
        self, mock_authority, mock_goal_store, mock_confidence_tracker, tmp_path
    ):
        """Regression: the promotion proposal must build a real Goal via
        create_goal() and persist as PROPOSED -- never auto-confirmed to PENDING
        (authority cannot self-apply). The old kwargs propose(description=...)
        call raised TypeError, which the mocked goal_store in sibling tests hid,
        so auto-promotion silently never proposed (no promotion_history.jsonl)."""
        from agent_core.goals.store import GoalStore
        from agent_core.goals.goal_model import GoalStatus

        goals = _learning_goals(achieved=20)
        mock_goal_store.get_all.return_value = goals
        mock_confidence_tracker.get_action_confidence.return_value = 0.95
        mock_confidence_tracker.get_confidence_map.return_value = {"learn": 0.95}

        scorer = TrustScorer(
            goal_store=mock_goal_store,
            confidence_tracker=mock_confidence_tracker,
            authority_manager=mock_authority,
        )
        # A REAL GoalStore as the propose target is what catches the signature bug.
        real_store = GoalStore(tmp_path / "goals.jsonl")

        promo = AutoPromotion(
            trust_scorer=scorer,
            authority_manager=mock_authority,
            goal_store=real_store,
            log_path=tmp_path / "promo.jsonl",
            enabled=True,
        )
        promo._last_check_at = 0

        result = promo.tick()
        assert result is not None
        assert result["action"] == "promotion_proposed"

        goal_id = result["goal_id"]
        assert goal_id is not None
        goal = real_store.get(goal_id)
        assert goal is not None
        assert goal.status == GoalStatus.PROPOSED   # operator-gated, NOT pending
        assert goal.created_by == "auto_promotion"


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------

class TestTrustIntegration:
    """Tests that combine multiple components."""

    def test_incident_affects_trust(self, tmp_path, mock_goal_store):
        """Recording incidents lowers trust score."""
        mem_clean = IncidentMemory(path=tmp_path / "clean.jsonl")
        mem_dirty = IncidentMemory(path=tmp_path / "dirty.jsonl")

        for i in range(5):
            mem_dirty.record_incident(
                action_type="fetch", severity="major"
            )

        scorer_clean = TrustScorer(
            incident_memory=mem_clean,
            goal_store=mock_goal_store,
        )
        scorer_dirty = TrustScorer(
            incident_memory=mem_dirty,
            goal_store=mock_goal_store,
        )

        clean = scorer_clean.calculate_trust("fetch")
        dirty = scorer_dirty.calculate_trust("fetch")

        assert dirty.score < clean.score
        assert dirty.incident_penalty > 0

    def test_full_promotion_lifecycle(self, tmp_path, mock_goal_store, mock_confidence_tracker):
        """Full lifecycle: score -> propose -> approve -> probation -> pass."""
        auth = AuthorityManager(config_path=tmp_path / "auth.json")

        # Build good track record
        goals = _learning_goals(achieved=20)
        mock_goal_store.get_all.return_value = goals
        mock_confidence_tracker.get_action_confidence.return_value = 0.95
        mock_confidence_tracker.get_confidence_map.return_value = {"learn": 0.95}

        scorer = TrustScorer(
            goal_store=mock_goal_store,
            confidence_tracker=mock_confidence_tracker,
            authority_manager=auth,
        )

        # 1. Check trust
        score = scorer.calculate_trust("learn")
        assert score.score > PROMOTION_THRESHOLDS[AuthorityLevel.OBSERVE]

        # 2. Get proposal
        proposal = scorer.suggest_promotion()
        assert proposal is not None
        assert proposal.proposed_level == AuthorityLevel.SUGGEST

        # 3. Apply promotion
        auth.set_level(proposal.proposed_level)
        scorer.record_promotion()
        assert auth.get_level() == AuthorityLevel.SUGGEST
        assert scorer.is_in_probation()

        # 4. Probation ends (simulate)
        scorer._last_promotion_at = time.time() - (8 * 86400)  # 8 days ago
        assert not scorer.is_in_probation()

    def test_promotion_proposal_to_dict(self):
        """PromotionProposal serializes correctly."""
        p = PromotionProposal(
            current_level=AuthorityLevel.OBSERVE,
            proposed_level=AuthorityLevel.SUGGEST,
            trust_score=0.85,
            threshold=0.75,
            action_types=["learn", "fetch"],
            reason="test reason",
        )
        d = p.to_dict()
        assert d["current_level"] == "observe"
        assert d["proposed_level"] == "suggest"
        assert len(d["action_types"]) == 2

    def test_promotion_event_to_dict(self):
        """PromotionEvent serializes correctly."""
        e = PromotionEvent(
            event_type="approved",
            timestamp=time.time(),
            from_level="observe",
            to_level="suggest",
            trust_score=0.85,
        )
        d = e.to_dict()
        assert d["event_type"] == "approved"
        assert d["trust_score"] == 0.85


class TestGoalOutcome:
    """abandoned != failure (fix 2026-07-15).

    On live data 1140/1192 goals (95.6%) are abandoned, and 922 of those were
    dropped by planner_stale_cleanup as "stale: pending 72h with no progress" --
    nobody ever started them (0/926 had progress > 0). Counting those as
    failures made goal_success_rate measure goal EXPIRY, not ability: `learn`
    read 0.021 (24/1133). Excluding no-evidence goals it reads 0.209 (24/115).

    A failure requires evidence she TRIED: progress > 0, or the planner's own
    non-productive-loop verdict (20 consecutive actions going nowhere).
    """

    @staticmethod
    def _goal(status, progress=0.0, abandon_actor=None):
        from agent_core.goals.goal_model import (
            create_goal, GoalType, GoalStatus, AuditEntry,
        )
        g = create_goal(goal_type=GoalType.LEARNING, description="nauka",
                        priority=0.5, status=GoalStatus.PENDING)
        g.status = status
        g.progress = progress
        if abandon_actor is not None:
            g.audit_trail.append(AuditEntry(
                timestamp=time.time(), old_status="pending",
                new_status="abandoned", reason="x", actor=abandon_actor,
            ))
        return g

    def test_achieved_is_success(self):
        from agent_core.goals.goal_model import GoalStatus
        assert TrustScorer._goal_outcome(self._goal(GoalStatus.ACHIEVED)) is True

    def test_failed_is_failure(self):
        from agent_core.goals.goal_model import GoalStatus
        assert TrustScorer._goal_outcome(self._goal(GoalStatus.FAILED)) is False

    def test_stale_abandoned_goal_is_not_counted_at_all(self):
        """THE bug: 922 goals nobody ever ran, scored against her ability."""
        from agent_core.goals.goal_model import GoalStatus
        g = self._goal(GoalStatus.ABANDONED, progress=0.0,
                       abandon_actor="planner_stale_cleanup")
        assert TrustScorer._goal_outcome(g) is None, \
            "a goal that never started is no evidence -- not a failure"

    def test_nonproductive_loop_is_a_real_failure(self):
        """Trying 20 times and going nowhere is the realest failure there is."""
        from agent_core.goals.goal_model import GoalStatus
        g = self._goal(GoalStatus.ABANDONED, progress=0.0,
                       abandon_actor="planner_nonproductive_detector")
        assert TrustScorer._goal_outcome(g) is False

    def test_abandoned_with_progress_is_a_failure(self):
        """Moved the needle, never finished -- she tried."""
        from agent_core.goals.goal_model import GoalStatus
        g = self._goal(GoalStatus.ABANDONED, progress=0.4,
                       abandon_actor="planner_stale_cleanup")
        assert TrustScorer._goal_outcome(g) is False

    def test_proposal_lapsed_by_operator_is_not_her_failure(self):
        from agent_core.goals.goal_model import GoalStatus
        g = self._goal(GoalStatus.ABANDONED, progress=0.0, abandon_actor="system")
        assert TrustScorer._goal_outcome(g) is None

    def test_displaced_by_better_proposal_is_not_a_failure(self):
        from agent_core.goals.goal_model import GoalStatus
        g = self._goal(GoalStatus.ABANDONED, progress=0.0, abandon_actor="creative")
        assert TrustScorer._goal_outcome(g) is None

    def test_in_flight_goals_have_no_verdict_yet(self):
        from agent_core.goals.goal_model import GoalStatus
        for st in (GoalStatus.ACTIVE, GoalStatus.PENDING, GoalStatus.PROPOSED):
            assert TrustScorer._goal_outcome(self._goal(st)) is None

    def test_cancelled_is_not_a_failure(self):
        from agent_core.goals.goal_model import GoalStatus
        assert TrustScorer._goal_outcome(self._goal(GoalStatus.CANCELLED)) is None

    def test_rate_excludes_no_evidence_goals(self, mock_goal_store):
        """End-to-end: 2 achieved + 1 real loop failure + 50 never-started
        must read 0.667 (2/3), not 0.038 (2/53)."""
        from agent_core.goals.goal_model import GoalStatus
        goals = [self._goal(GoalStatus.ACHIEVED) for _ in range(2)]
        goals.append(self._goal(GoalStatus.ABANDONED, 0.0,
                                "planner_nonproductive_detector"))
        goals += [self._goal(GoalStatus.ABANDONED, 0.0, "planner_stale_cleanup")
                  for _ in range(50)]
        mock_goal_store.get_all.return_value = goals

        score = TrustScorer(goal_store=mock_goal_store).calculate_trust("learn")

        assert score.successful_actions == 2
        assert score.failed_actions == 1
        assert score.total_actions == 3, "50 never-started goals must not count"
        assert round(score.goal_success_rate, 3) == 0.667
