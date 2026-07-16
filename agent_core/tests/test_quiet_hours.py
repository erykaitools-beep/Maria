"""Operator quiet hours: one definition, actually reachable (fix 2026-07-15).

mode_detector.py:129 read prefs["quiet_hours_start"] / ["quiet_hours_end"].
Nobody writes those: OperatorModel stores the preference as the LIST
quiet_hours=[23, 6] (operator_model.py:186). So get() returned None, the guard
`if quiet_start is not None and quiet_end is not None` was never true, and
operator quiet hours NEVER APPLIED -- same phantom-field class as
goal.goal_type (trust_scorer) and TelegramNotifier.notify(), all found the
same day.

Second bug in the same function: the same-day branch used
`quiet_start <= hour or hour < quiet_end`, so a 1-5 window called 10:00 quiet.
Unreachable behind the phantom, live the moment it was fixed.

Three hardcoded definitions existed (proactive 23-6, planner 22-7,
environment_model comment 22-06). These helpers are the operator-preference
SSoT; do not re-parse the preference elsewhere.
"""

from agent_core.operator.operator_model import in_quiet_hours, quiet_hours_window


class TestWindowParsing:
    def test_reads_the_shape_operator_model_actually_writes(self):
        assert quiet_hours_window({"quiet_hours": [23, 6]}) == (23, 6)

    def test_the_phantom_fields_are_not_consulted(self):
        """A prefs dict carrying ONLY the old field names yields nothing --
        proving the list is the real source, not those names."""
        assert quiet_hours_window({"quiet_hours_start": 23, "quiet_hours_end": 6}) is None

    def test_missing_preference_is_none(self):
        assert quiet_hours_window({}) is None

    def test_garbage_is_rejected_not_crashed(self):
        for bad in ([], [1], [1, 2, 3], "23-6", None, {"a": 1}, ["a", "b"]):
            assert quiet_hours_window({"quiet_hours": bad}) is None

    def test_out_of_range_hours_rejected(self):
        assert quiet_hours_window({"quiet_hours": [25, 6]}) is None
        assert quiet_hours_window({"quiet_hours": [23, -1]}) is None

    def test_numeric_strings_accepted(self):
        assert quiet_hours_window({"quiet_hours": ["23", "6"]}) == (23, 6)


class TestWindowMembership:
    def test_live_operator_window_23_to_6(self):
        w = (23, 6)
        for quiet_hour in (23, 0, 3, 5):
            assert in_quiet_hours(quiet_hour, w) is True, quiet_hour
        for loud_hour in (6, 7, 12, 20, 22):
            assert in_quiet_hours(loud_hour, w) is False, loud_hour

    def test_same_day_window_does_not_swallow_the_day(self):
        """Pre-fix `start <= hour or hour < end` called 10:00 quiet on a 1-5 window."""
        w = (1, 5)
        assert in_quiet_hours(3, w) is True
        assert in_quiet_hours(10, w) is False
        assert in_quiet_hours(0, w) is False

    def test_boundaries_start_inclusive_end_exclusive(self):
        assert in_quiet_hours(23, (23, 6)) is True, "start hour is quiet"
        assert in_quiet_hours(6, (23, 6)) is False, "end hour is awake"

    def test_zero_length_window_is_never_quiet(self):
        """start == end must not mute the agent forever -- the worse failure."""
        for h in range(24):
            assert in_quiet_hours(h, (3, 3)) is False

    def test_no_window_means_never_quiet(self):
        assert in_quiet_hours(3, None) is False


class TestLivePreferences:
    def test_the_real_operator_model_yields_a_usable_window(self):
        """The whole point: end-to-end on the REAL singleton, not a fixture."""
        from agent_core.operator.operator_model import get_operator_model

        prefs = get_operator_model().get_preferences()
        window = quiet_hours_window(prefs)
        assert window is not None, (
            "operator quiet hours must be reachable from live preferences "
            f"(got prefs={prefs})"
        )
        start, end = window
        assert 0 <= start <= 23 and 0 <= end <= 23


class TestNotifierWiring:
    """_operator_quiet_now: the predicate the notifier is wired with.

    The helper is what actually connects the tested window logic to a clock;
    the bug it guards against is a wiring that reads the wrong field or forgets
    the current hour -- neither of which a unit test of in_quiet_hours can see.
    """

    def test_composes_current_hour_with_the_preference(self, monkeypatch):
        from datetime import datetime
        from types import SimpleNamespace
        import agent_core.operator.operator_model as om
        from agent_core.modules.homeostasis_module import _operator_quiet_now

        monkeypatch.setattr(
            om, "get_operator_model",
            lambda: SimpleNamespace(get_preferences=lambda: {"quiet_hours": [23, 6]}),
        )

        # Independent of what hour it happens to be: the helper must agree with
        # in_quiet_hours applied to the same hour and the same window.
        expected = in_quiet_hours(datetime.now().hour, (23, 6))
        assert _operator_quiet_now() is expected

    def test_fail_open_when_operator_model_unavailable(self, monkeypatch):
        import agent_core.operator.operator_model as om
        from agent_core.modules.homeostasis_module import _operator_quiet_now

        def _boom():
            raise RuntimeError("no operator model")

        monkeypatch.setattr(om, "get_operator_model", _boom)
        assert _operator_quiet_now() is False

    def test_no_preference_means_not_quiet(self, monkeypatch):
        from types import SimpleNamespace
        import agent_core.operator.operator_model as om
        from agent_core.modules.homeostasis_module import _operator_quiet_now

        monkeypatch.setattr(
            om, "get_operator_model",
            lambda: SimpleNamespace(get_preferences=lambda: {}),
        )
        assert _operator_quiet_now() is False
