"""Tests for meta-goal priority escalation (2026-03-27).

Covers:
1. Tension streak tracking in CreativeStore
2. Priority boost from streak in ReflectionWorkspace
3. PROPOSED goal displacement in GoalStore
4. Telegram /priority command
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from agent_core.creative.creative_model import (
    CreativeInsight,
    DetectedTension,
    MetaGoal,
    MetaGoalStatus,
    MetaGoalType,
    ReflectionSession,
    RiskLevel,
    TensionCategory,
)
from agent_core.creative.creative_store import CreativeStore
from agent_core.creative.reflection_workspace import ReflectionWorkspaceManager
from agent_core.goals.goal_model import (
    Goal, GoalType, GoalStatus, AuditEntry,
    create_goal, MAX_PROPOSED_GOALS,
)
from agent_core.goals.store import GoalStore
from agent_core.telegram import TelegramBridge


# =========================================================================
# 1. Tension streak tracking
# =========================================================================

class TestTensionStreaks:
    def test_record_and_get_streak(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        store.record_tensions(["repetition", "stagnation"])
        store.record_tensions(["repetition"])
        store.record_tensions(["repetition", "misalignment"])

        assert store.get_tension_streak("repetition") == 3
        assert store.get_tension_streak("misalignment") == 1
        assert store.get_tension_streak("stagnation") == 0  # broken streak

    def test_empty_streak(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        assert store.get_tension_streak("repetition") == 0

    def test_streak_breaks_on_absence(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        store.record_tensions(["repetition"])
        store.record_tensions(["repetition"])
        store.record_tensions([])  # no tensions -> breaks streak
        store.record_tensions(["repetition"])

        assert store.get_tension_streak("repetition") == 1

    def test_streak_with_no_file(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        # File does not exist yet
        assert store.get_tension_streak("anything") == 0

    def test_multiple_categories_independent(self, tmp_path):
        store = CreativeStore(str(tmp_path))
        store.record_tensions(["repetition", "over_restriction"])
        store.record_tensions(["repetition", "over_restriction"])
        store.record_tensions(["repetition"])  # over_restriction stops

        assert store.get_tension_streak("repetition") == 3
        assert store.get_tension_streak("over_restriction") == 0

    def test_streak_persists_across_store_instances(self, tmp_path):
        store1 = CreativeStore(str(tmp_path))
        store1.record_tensions(["repetition"])
        store1.record_tensions(["repetition"])

        store2 = CreativeStore(str(tmp_path))
        assert store2.get_tension_streak("repetition") == 2


# =========================================================================
# 2. Priority boost from streak
# =========================================================================

class TestPriorityBoost:
    def _make_session_with_tension(self, category=TensionCategory.REPETITION, severity=0.9):
        session = ReflectionSession(trigger="test")
        tension = DetectedTension.create(
            category=category,
            description="Test tension",
            severity=severity,
            evidence_refs=["e1"],
            pattern_window="24h",
        )
        session.add_tension(tension)

        # Add insight that qualifies for meta-goal
        insight = CreativeInsight.create(
            derived_from=[tension.tension_id],
            statement=f"Test insight for {category.value}",
            confidence=severity * 0.8,
            meta_goal_candidate=True,
        )
        session.add_insight(insight)
        return session

    def test_no_streak_no_boost(self):
        mgr = ReflectionWorkspaceManager()
        session = self._make_session_with_tension(severity=0.9)
        context = {"learning_state": {"coverage": 0.8}}

        candidates = mgr.generate_candidates(session, context, tension_streak_fn=lambda c: 0)
        assert len(candidates) == 1
        # Base priority = 0.9 * 0.8 = 0.72, no boost
        assert abs(candidates[0].priority - 0.72) < 0.01

    def test_streak_boosts_priority(self):
        mgr = ReflectionWorkspaceManager()
        session = self._make_session_with_tension(severity=0.9)
        context = {"learning_state": {"coverage": 0.8}}

        # Streak of 3 = +0.15
        candidates = mgr.generate_candidates(
            session, context, tension_streak_fn=lambda c: 3
        )
        assert len(candidates) == 1
        expected = 0.72 + 0.15  # 0.87
        assert abs(candidates[0].priority - expected) < 0.01

    def test_streak_boost_capped_at_0_2(self):
        mgr = ReflectionWorkspaceManager()
        session = self._make_session_with_tension(severity=0.9)
        context = {"learning_state": {"coverage": 0.8}}

        # Streak of 10 = capped at +0.2
        candidates = mgr.generate_candidates(
            session, context, tension_streak_fn=lambda c: 10
        )
        assert len(candidates) == 1
        expected = 0.72 + 0.2  # 0.92
        assert abs(candidates[0].priority - expected) < 0.01

    def test_priority_capped_at_1_0(self):
        mgr = ReflectionWorkspaceManager()
        # severity 1.0 -> confidence 0.8 -> base priority 0.8
        session = self._make_session_with_tension(severity=1.0)
        context = {"learning_state": {"coverage": 0.8}}

        candidates = mgr.generate_candidates(
            session, context, tension_streak_fn=lambda c: 10
        )
        assert len(candidates) == 1
        assert candidates[0].priority <= 1.0

    def test_no_streak_fn_means_no_boost(self):
        mgr = ReflectionWorkspaceManager()
        session = self._make_session_with_tension(severity=0.9)
        context = {"learning_state": {"coverage": 0.8}}

        # No tension_streak_fn passed (backward compat)
        candidates = mgr.generate_candidates(session, context)
        assert len(candidates) == 1
        assert abs(candidates[0].priority - 0.72) < 0.01

    def test_streak_per_category(self):
        """Different categories get different streak values."""
        mgr = ReflectionWorkspaceManager()
        session = self._make_session_with_tension(
            category=TensionCategory.STAGNATION, severity=0.8
        )
        context = {"learning_state": {"coverage": 0.5}}

        def streak_fn(cat):
            if cat == "stagnation":
                return 4
            return 0

        candidates = mgr.generate_candidates(session, context, tension_streak_fn=streak_fn)
        assert len(candidates) == 1
        # Base: 0.8 * 0.8 = 0.64, boost: min(4*0.05, 0.2) = 0.2
        expected = 0.64 + 0.2
        assert abs(candidates[0].priority - expected) < 0.01


# =========================================================================
# 3. PROPOSED goal displacement
# =========================================================================

class TestProposedDisplacement:
    def test_higher_priority_displaces_lowest(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        # Fill with 3 proposed goals at priority 0.3, 0.5, 0.6
        for pri in [0.3, 0.5, 0.6]:
            g = create_goal(GoalType.META, f"Goal pri={pri}", pri)
            store.propose(g)
        assert len(store.get_proposed()) == MAX_PROPOSED_GOALS

        # New goal with priority 0.8 should displace the 0.3 one
        high = create_goal(GoalType.META, "High priority", 0.8)
        result = store.propose(high)
        assert result is not None

        proposed = store.get_proposed()
        priorities = sorted([g.priority for g in proposed])
        assert 0.3 not in priorities  # displaced
        assert 0.8 in priorities

    def test_equal_priority_does_not_displace(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        for i in range(MAX_PROPOSED_GOALS):
            g = create_goal(GoalType.META, f"Goal {i}", 0.5)
            store.propose(g)

        same = create_goal(GoalType.META, "Same priority", 0.5)
        result = store.propose(same)
        assert result is None  # Cannot displace equal priority

    def test_lower_priority_does_not_displace(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        for i in range(MAX_PROPOSED_GOALS):
            g = create_goal(GoalType.META, f"Goal {i}", 0.7)
            store.propose(g)

        low = create_goal(GoalType.META, "Low priority", 0.3)
        result = store.propose(low)
        assert result is None

    def test_displaced_goal_is_abandoned(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        victims = []
        for pri in [0.3, 0.5, 0.6]:
            g = create_goal(GoalType.META, f"Goal pri={pri}", pri)
            store.propose(g)
            victims.append(g)

        high = create_goal(GoalType.META, "High priority", 0.9)
        store.propose(high)

        # The 0.3 goal should be ABANDONED
        displaced = store.get(victims[0].id)
        assert displaced.status == GoalStatus.ABANDONED
        assert "displaced" in displaced.audit_trail[-1].reason

    def test_displacement_preserves_total_proposed_count(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        for pri in [0.3, 0.5, 0.6]:
            g = create_goal(GoalType.META, f"Goal pri={pri}", pri)
            store.propose(g)

        high = create_goal(GoalType.META, "High priority", 0.9)
        store.propose(high)

        assert len(store.get_proposed()) == MAX_PROPOSED_GOALS

    def test_under_limit_no_displacement_needed(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g1 = create_goal(GoalType.META, "First", 0.5)
        store.propose(g1)

        g2 = create_goal(GoalType.META, "Second", 0.3)
        result = store.propose(g2)
        assert result is not None  # No displacement needed
        assert len(store.get_proposed()) == 2


# =========================================================================
# 4. Telegram /priority command
# =========================================================================

class TestTelegramPriorityCommand:
    def _make_goal_store(self, tmp_path):
        store = GoalStore(tmp_path / "goals.jsonl")
        g = create_goal(GoalType.META, "Test goal", 0.5, goal_id="goal-test1234")
        store.propose(g)
        return store

    def test_priority_changes_value(self, tmp_path):
        store = self._make_goal_store(tmp_path)

        # Simulate the command handler logic
        from agent_core.goals.goal_model import AuditEntry
        goal = store.get_proposed()[0]
        old_pri = goal.priority
        goal.priority = 0.9
        goal.updated_at = time.time()
        goal.audit_trail.append(AuditEntry(
            timestamp=time.time(),
            old_status=goal.status.value,
            new_status=goal.status.value,
            reason=f"priority {old_pri:.2f} -> 0.90 (operator)",
            actor="operator",
        ))
        store._mark_dirty(goal.id)
        store.save()

        # Verify
        reloaded = GoalStore(tmp_path / "goals.jsonl")
        reloaded.load()
        g = reloaded.get("goal-test1234")
        assert g.priority == 0.9
        assert "operator" in g.audit_trail[-1].reason

    def test_priority_command_via_bridge(self, tmp_path):
        """Integration test: /priority command through TelegramBridge."""
        store = self._make_goal_store(tmp_path)

        bot = MagicMock()
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "/priority goal-test 0.9", "from": "Eryk", "chat_id": 123,
             "date": 0, "message_id": 1}
        ])
        bot.send_message = MagicMock(return_value=True)

        bridge = TelegramBridge(bot=bot)

        # Build handler like homeostasis_module does
        from agent_core.goals.goal_model import AuditEntry as AE

        def _cmd_priority(args):
            if not args:
                return "Uzycie: /priority <id-prefix> <0.0-1.0>"
            parts = args.strip().split(None, 1)
            if len(parts) < 2:
                return "Uzycie: /priority <id-prefix> <0.0-1.0>"
            prefix = parts[0]
            try:
                new_pri = float(parts[1])
            except ValueError:
                return f"Nieprawidlowy priorytet: {parts[1]}"
            if not (0.0 <= new_pri <= 1.0):
                return "Priorytet musi byc 0.0-1.0"
            candidates = store.get_proposed() + store.get_active()
            match = [g for g in candidates if g.id.startswith(prefix)]
            if not match:
                return f"Nie znaleziono celu: {prefix}"
            goal = match[0]
            old_pri = goal.priority
            goal.priority = new_pri
            goal.updated_at = time.time()
            goal.audit_trail.append(AE(
                timestamp=time.time(), old_status=goal.status.value,
                new_status=goal.status.value,
                reason=f"priority {old_pri:.2f} -> {new_pri:.2f} (operator)",
                actor="operator",
            ))
            store._mark_dirty(goal.id)
            store.save()
            return f"Priorytet {goal.description[:60]}: {old_pri:.2f} -> {new_pri:.2f}"

        bridge.register_command("priority", _cmd_priority)
        bridge.poll_and_respond()

        # Verify message sent
        sent = bot.send_message.call_args[0][0]
        assert "0.50" in sent
        assert "0.90" in sent

        # Verify goal changed
        assert store.get("goal-test1234").priority == 0.9

    def test_priority_invalid_value(self):
        bot = MagicMock()
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "/priority goal-x abc", "from": "Eryk", "chat_id": 123,
             "date": 0, "message_id": 1}
        ])
        bot.send_message = MagicMock(return_value=True)

        bridge = TelegramBridge(bot=bot)

        def _cmd_priority(args):
            parts = args.strip().split(None, 1)
            if len(parts) < 2:
                return "Uzycie: /priority <id-prefix> <0.0-1.0>"
            try:
                float(parts[1])
            except ValueError:
                return f"Nieprawidlowy priorytet: {parts[1]}"
            return "OK"

        bridge.register_command("priority", _cmd_priority)
        bridge.poll_and_respond()

        sent = bot.send_message.call_args[0][0]
        assert "Nieprawidlowy" in sent

    def test_priority_out_of_range(self):
        bot = MagicMock()
        bot.configured = True
        bot.get_updates = MagicMock(return_value=[
            {"text": "/priority goal-x 1.5", "from": "Eryk", "chat_id": 123,
             "date": 0, "message_id": 1}
        ])
        bot.send_message = MagicMock(return_value=True)

        bridge = TelegramBridge(bot=bot)

        def _cmd_priority(args):
            parts = args.strip().split(None, 1)
            if len(parts) < 2:
                return "Uzycie"
            new_pri = float(parts[1])
            if not (0.0 <= new_pri <= 1.0):
                return "Priorytet musi byc 0.0-1.0"
            return "OK"

        bridge.register_command("priority", _cmd_priority)
        bridge.poll_and_respond()

        sent = bot.send_message.call_args[0][0]
        assert "0.0-1.0" in sent


# =========================================================================
# 5. Integration: streak -> boost -> displacement
# =========================================================================

class TestEscalationE2E:
    def test_streak_boost_enables_displacement(self, tmp_path):
        """High streak boost pushes priority above existing PROPOSED goals."""
        store = GoalStore(tmp_path / "goals.jsonl")

        # Fill proposed slots with priority 0.72 (typical for severity=0.9)
        for i in range(MAX_PROPOSED_GOALS):
            g = create_goal(GoalType.META, f"Existing {i}", 0.72)
            store.propose(g)

        # Without streak: priority=0.72, same as existing -> cannot displace
        no_boost = create_goal(GoalType.META, "No boost", 0.72)
        assert store.propose(no_boost) is None

        # With streak of 4: priority=0.72 + 0.2 = 0.92 -> displaces 0.72
        boosted = create_goal(GoalType.META, "Boosted by streak", 0.92)
        result = store.propose(boosted)
        assert result is not None
        assert store.get(result).priority == 0.92
