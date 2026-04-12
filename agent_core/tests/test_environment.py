"""
Tests for Faza 6: Environment Adaptation.

Covers: model, mode_detector, environment_manager.
"""

import json
import os
import tempfile
import time
from datetime import datetime
import pytest

from agent_core.environment.environment_model import (
    EnvironmentMode,
    EnvironmentProfile,
    EnvironmentState,
    ENVIRONMENT_PROFILES,
    PROFILE_DEFAULT,
    PROFILE_LEARNING,
    PROFILE_MONITORING,
    PROFILE_QUIET,
)
from agent_core.environment.mode_detector import ModeDetector, MIN_SWITCH_INTERVAL_SEC
from agent_core.environment.environment_manager import EnvironmentManager


# ========== MODEL TESTS ==========

class TestEnvironmentModel:

    def test_environment_modes(self):
        assert EnvironmentMode.DEFAULT.value == "default"
        assert EnvironmentMode.LEARNING.value == "learning"
        assert EnvironmentMode.MONITORING.value == "monitoring"
        assert EnvironmentMode.QUIET.value == "quiet"
        assert len(EnvironmentMode) == 4

    def test_profile_frozen(self):
        with pytest.raises(AttributeError):
            PROFILE_DEFAULT.mode = EnvironmentMode.LEARNING

    def test_profile_to_dict_roundtrip(self):
        d = PROFILE_LEARNING.to_dict()
        restored = EnvironmentProfile.from_dict(d)
        assert restored.mode == EnvironmentMode.LEARNING
        assert "learn" in restored.priority_actions
        assert restored.llm_budget_multiplier == 1.5
        assert restored.planner_interval_multiplier == 0.5
        assert len(restored.auto_trigger_hours) > 0

    def test_all_profiles_exist(self):
        assert len(ENVIRONMENT_PROFILES) == 4
        for mode in EnvironmentMode:
            assert mode in ENVIRONMENT_PROFILES

    def test_default_profile_is_neutral(self):
        p = PROFILE_DEFAULT
        assert p.priority_actions == ()
        assert p.blocked_actions == ()
        assert p.llm_budget_multiplier == 1.0
        assert p.planner_interval_multiplier == 1.0
        assert p.notification_level == "normal"

    def test_learning_profile_priorities(self):
        p = PROFILE_LEARNING
        assert "learn" in p.priority_actions
        assert "exam" in p.priority_actions
        assert "fetch" in p.priority_actions
        assert p.llm_budget_multiplier > 1.0

    def test_monitoring_profile(self):
        p = PROFILE_MONITORING
        assert "evaluate" in p.priority_actions
        assert "maintenance" in p.priority_actions
        assert "experiment" in p.blocked_actions
        assert p.llm_budget_multiplier < 1.0

    def test_quiet_profile(self):
        p = PROFILE_QUIET
        assert "effector" in p.blocked_actions
        assert p.notification_level == "critical"
        assert p.llm_budget_multiplier < 0.5
        assert len(p.auto_trigger_hours) > 0

    def test_learning_auto_trigger_weekdays(self):
        p = PROFILE_LEARNING
        # Mon-Fri
        assert 0 in p.auto_trigger_days
        assert 4 in p.auto_trigger_days
        assert 5 not in p.auto_trigger_days  # No Saturday
        assert 6 not in p.auto_trigger_days  # No Sunday

    def test_quiet_auto_trigger_night_hours(self):
        p = PROFILE_QUIET
        assert 22 in p.auto_trigger_hours
        assert 23 in p.auto_trigger_hours
        assert 0 in p.auto_trigger_hours
        assert 3 in p.auto_trigger_hours

    def test_state_to_dict_roundtrip(self):
        state = EnvironmentState(
            active_mode=EnvironmentMode.LEARNING,
            switched_at=12345.0,
            switched_by="operator",
            auto_detect_enabled=False,
            override_until=99999.0,
        )
        d = state.to_dict()
        restored = EnvironmentState.from_dict(d)
        assert restored.active_mode == EnvironmentMode.LEARNING
        assert restored.switched_by == "operator"
        assert restored.auto_detect_enabled is False
        assert restored.override_until == 99999.0

    def test_state_defaults(self):
        state = EnvironmentState()
        assert state.active_mode == EnvironmentMode.DEFAULT
        assert state.auto_detect_enabled is True
        assert state.override_until is None

    def test_profile_prompt_additions_are_strings(self):
        for mode, profile in ENVIRONMENT_PROFILES.items():
            assert isinstance(profile.prompt_addition, str)
            if mode != EnvironmentMode.DEFAULT:
                assert len(profile.prompt_addition) > 0


# ========== MODE DETECTOR TESTS ==========

class TestModeDetector:

    def test_detect_no_change(self):
        detector = ModeDetector()
        # Reset anti-flap timer
        detector._last_switch_ts = 0
        # At a time that doesn't trigger any auto mode
        now = datetime(2026, 4, 12, 12, 0)  # Saturday noon
        result = detector.detect(EnvironmentMode.DEFAULT, now)
        # QUIET doesn't trigger on Saturdays (no auto_trigger_days set)
        # LEARNING doesn't trigger on weekends
        # So should be None (no change) or QUIET (night hours don't match)
        # At noon, no triggers match -> None
        assert result is None or result == EnvironmentMode.DEFAULT

    def test_detect_learning_weekday_morning(self):
        detector = ModeDetector()
        detector._last_switch_ts = 0
        # Monday at 10:00 -> LEARNING should trigger
        now = datetime(2026, 4, 13, 10, 0)  # Monday
        result = detector.detect(EnvironmentMode.DEFAULT, now)
        assert result == EnvironmentMode.LEARNING

    def test_detect_quiet_at_night(self):
        detector = ModeDetector()
        detector._last_switch_ts = 0
        # Any day at 23:00 -> QUIET should trigger
        now = datetime(2026, 4, 12, 23, 0)  # Saturday night
        result = detector.detect(EnvironmentMode.DEFAULT, now)
        assert result == EnvironmentMode.QUIET

    def test_detect_quiet_early_morning(self):
        detector = ModeDetector()
        detector._last_switch_ts = 0
        # 3 AM -> QUIET
        now = datetime(2026, 4, 13, 3, 0)  # Monday 3AM
        result = detector.detect(EnvironmentMode.DEFAULT, now)
        assert result == EnvironmentMode.QUIET

    def test_anti_flap_guard(self):
        detector = ModeDetector()
        detector._last_switch_ts = time.time()  # Just switched
        now = datetime(2026, 4, 13, 10, 0)
        result = detector.detect(EnvironmentMode.DEFAULT, now)
        assert result is None  # Anti-flap blocks

    def test_homeostasis_degradation_to_quiet(self):
        detector = ModeDetector()
        detector._last_switch_ts = 0

        class FakeCore:
            _current_mode = "REDUCED"

        detector.set_homeostasis_core(FakeCore())
        now = datetime(2026, 4, 13, 14, 0)  # Afternoon (would be LEARNING)
        result = detector.detect(EnvironmentMode.DEFAULT, now)
        # Homeostasis degradation should override to QUIET
        assert result == EnvironmentMode.QUIET

    def test_homeostasis_active_no_override(self):
        detector = ModeDetector()
        detector._last_switch_ts = 0

        class FakeCore:
            _current_mode = "ACTIVE"

        detector.set_homeostasis_core(FakeCore())
        now = datetime(2026, 4, 13, 10, 0)  # Monday morning
        result = detector.detect(EnvironmentMode.DEFAULT, now)
        # Should detect LEARNING, not QUIET
        assert result == EnvironmentMode.LEARNING

    def test_already_in_detected_mode(self):
        detector = ModeDetector()
        detector._last_switch_ts = 0
        now = datetime(2026, 4, 13, 10, 0)
        # Already in LEARNING -> no switch needed
        result = detector.detect(EnvironmentMode.LEARNING, now)
        # Should suggest QUIET (night-hours profile has 3AM trigger)
        # or None if no other profile triggers
        # At 10AM Monday, LEARNING triggers but we're already there -> None
        assert result is None

    def test_record_switch(self):
        detector = ModeDetector()
        assert detector._last_switch_ts == 0.0
        detector.record_switch()
        assert detector._last_switch_ts > 0

    def test_operator_quiet_hours(self):
        detector = ModeDetector()
        detector._last_switch_ts = 0

        class FakeOperatorModel:
            def get_preferences(self):
                return {"quiet_hours_start": 22, "quiet_hours_end": 7}

        detector.set_operator_model(FakeOperatorModel())
        now = datetime(2026, 4, 13, 23, 0)  # 11 PM
        result = detector.detect(EnvironmentMode.DEFAULT, now)
        assert result == EnvironmentMode.QUIET

    def test_operator_quiet_hours_daytime_no_trigger(self):
        detector = ModeDetector()
        detector._last_switch_ts = 0

        class FakeOperatorModel:
            def get_preferences(self):
                return {"quiet_hours_start": 22, "quiet_hours_end": 7}

        detector.set_operator_model(FakeOperatorModel())
        now = datetime(2026, 4, 12, 12, 0)  # Saturday noon
        # No quiet hours at noon, no other triggers for Saturday
        result = detector.detect(EnvironmentMode.DEFAULT, now)
        # Saturday noon - no triggers match
        assert result is None


# ========== ENVIRONMENT MANAGER TESTS ==========

class TestEnvironmentManager:

    def _make_manager(self, tmp_path=None):
        if tmp_path is None:
            tmp_path = tempfile.mkdtemp()
        path = os.path.join(str(tmp_path), "environment_state.json")
        detector = ModeDetector()
        detector._last_switch_ts = 0  # Allow switches
        return EnvironmentManager(detector=detector, state_path=path)

    def test_default_mode(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        assert mgr.get_active_mode() == EnvironmentMode.DEFAULT

    def test_switch_mode(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        assert mgr.switch(EnvironmentMode.LEARNING) is True
        assert mgr.get_active_mode() == EnvironmentMode.LEARNING

    def test_switch_same_mode(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        assert mgr.switch(EnvironmentMode.DEFAULT) is False

    def test_switch_persistence(self, tmp_path):
        path = os.path.join(str(tmp_path), "env.json")
        mgr1 = EnvironmentManager(state_path=path)
        mgr1.switch(EnvironmentMode.MONITORING)

        mgr2 = EnvironmentManager(state_path=path)
        assert mgr2.get_active_mode() == EnvironmentMode.MONITORING

    def test_switch_listener(self, tmp_path):
        events = []
        mgr = self._make_manager(tmp_path)
        mgr.add_switch_listener(lambda old, new, by: events.append((old, new, by)))

        mgr.switch(EnvironmentMode.QUIET, by="operator")
        assert len(events) == 1
        assert events[0] == (EnvironmentMode.DEFAULT, EnvironmentMode.QUIET, "operator")

    def test_manual_override_disables_auto(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.switch(EnvironmentMode.LEARNING, by="operator")
        assert mgr._state.auto_detect_enabled is False

    def test_switch_to_default_re_enables_auto(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.switch(EnvironmentMode.LEARNING, by="operator")
        assert mgr._state.auto_detect_enabled is False

        mgr.switch(EnvironmentMode.DEFAULT, by="operator")
        assert mgr._state.auto_detect_enabled is True

    def test_duration_override(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.switch(EnvironmentMode.QUIET, by="operator", duration_hours=2.0)
        assert mgr._state.override_until is not None
        assert mgr._state.override_until > time.time()

    def test_get_active_profile(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        profile = mgr.get_active_profile()
        assert profile.mode == EnvironmentMode.DEFAULT

        mgr.switch(EnvironmentMode.LEARNING)
        profile = mgr.get_active_profile()
        assert profile.mode == EnvironmentMode.LEARNING
        assert "learn" in profile.priority_actions

    def test_get_context(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        ctx = mgr.get_context()
        assert ctx["mode"] == "default"
        assert "prompt_addition" in ctx
        assert "notification_level" in ctx

    def test_get_status(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.switch(EnvironmentMode.MONITORING, by="auto")
        status = mgr.get_status()
        assert status["mode"] == "monitoring"
        assert status["switched_by"] == "auto"
        assert "evaluate" in status["priority_actions"]

    def test_is_action_blocked(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        assert mgr.is_action_blocked("learn") is False

        mgr.switch(EnvironmentMode.MONITORING)
        assert mgr.is_action_blocked("experiment") is True
        assert mgr.is_action_blocked("learn") is False

        mgr.switch(EnvironmentMode.QUIET)
        assert mgr.is_action_blocked("effector") is True

    def test_action_priority_boost(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.switch(EnvironmentMode.LEARNING)

        # Priority actions get positive boost
        assert mgr.get_action_priority_boost("learn") > 0
        assert mgr.get_action_priority_boost("exam") > 0

        # Deprioritized actions get negative boost
        assert mgr.get_action_priority_boost("creative") < 0

        # Neutral actions get 0
        assert mgr.get_action_priority_boost("maintenance") == 0

    def test_list_modes(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        modes = mgr.list_modes()
        assert len(modes) == 4
        active = [m for m in modes if m["active"]]
        assert len(active) == 1
        assert active[0]["mode"] == "default"

    def test_maybe_auto_switch_disabled(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr._state.auto_detect_enabled = False
        result = mgr.maybe_auto_switch()
        assert result is None

    def test_maybe_auto_switch_override_expiry(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.switch(EnvironmentMode.QUIET, by="operator", duration_hours=0.001)
        # Fast-forward: override should have expired
        mgr._state.override_until = time.time() - 10
        mgr._state.auto_detect_enabled = True

        result = mgr.maybe_auto_switch()
        assert result == EnvironmentMode.DEFAULT

    def test_load_corrupted_state(self, tmp_path):
        path = os.path.join(str(tmp_path), "env.json")
        with open(path, "w") as f:
            f.write("not json")

        mgr = EnvironmentManager(state_path=path)
        assert mgr.get_active_mode() == EnvironmentMode.DEFAULT

    def test_load_nonexistent_state(self, tmp_path):
        path = os.path.join(str(tmp_path), "nonexistent", "env.json")
        mgr = EnvironmentManager(state_path=path)
        assert mgr.get_active_mode() == EnvironmentMode.DEFAULT


# ========== INTEGRATION TESTS ==========

class TestEnvironmentIntegration:

    def test_full_lifecycle(self, tmp_path):
        """Default -> Learning -> Monitoring -> Default."""
        path = os.path.join(str(tmp_path), "env.json")
        mgr = EnvironmentManager(state_path=path)
        switches = []
        mgr.add_switch_listener(lambda o, n, b: switches.append(n.value))

        mgr.switch(EnvironmentMode.LEARNING, by="operator")
        assert mgr.is_action_blocked("learn") is False
        assert mgr.get_action_priority_boost("learn") > 0

        mgr.switch(EnvironmentMode.MONITORING, by="auto")
        assert mgr.is_action_blocked("experiment") is True
        assert mgr.get_action_priority_boost("evaluate") > 0

        mgr.switch(EnvironmentMode.DEFAULT, by="operator")
        assert mgr.get_action_priority_boost("learn") == 0
        assert mgr.is_action_blocked("experiment") is False

        assert switches == ["learning", "monitoring", "default"]

    def test_persistence_across_restart(self, tmp_path):
        """State survives process restart."""
        path = os.path.join(str(tmp_path), "env.json")
        mgr1 = EnvironmentManager(state_path=path)
        mgr1.switch(EnvironmentMode.QUIET, by="operator")

        mgr2 = EnvironmentManager(state_path=path)
        assert mgr2.get_active_mode() == EnvironmentMode.QUIET
        assert mgr2._state.switched_by == "operator"

    def test_mode_affects_context(self, tmp_path):
        """Context changes with mode."""
        path = os.path.join(str(tmp_path), "env.json")
        mgr = EnvironmentManager(state_path=path)

        ctx1 = mgr.get_context()
        assert ctx1["prompt_addition"] == ""

        mgr.switch(EnvironmentMode.LEARNING)
        ctx2 = mgr.get_context()
        assert "nauki" in ctx2["prompt_addition"].lower() or "nauk" in ctx2["prompt_addition"].lower()

    def test_detector_integration(self, tmp_path):
        """Detector + manager work together."""
        path = os.path.join(str(tmp_path), "env.json")
        detector = ModeDetector()
        detector._last_switch_ts = 0

        class FakeCore:
            _current_mode = "REDUCED"

        detector.set_homeostasis_core(FakeCore())

        mgr = EnvironmentManager(detector=detector, state_path=path)
        result = mgr.maybe_auto_switch()
        assert result == EnvironmentMode.QUIET
        assert mgr.get_active_mode() == EnvironmentMode.QUIET
