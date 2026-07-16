"""Regressions on the AUTONOMOUS synthesis path (_maybe_autonomous_synthesis),
from the 2026-06-15 cast-nets audit:

  #1 (4 lenses): the path must RELEASE the shared _synthesis_lock if the worker
     thread fails to spawn after acquire -- else the lock leaks for the whole
     process lifetime and ALL synthesis (autonomous + operator /synthesize)
     dies silently until a daemon restart. The manual /synthesize path was
     already hardened with a `spawned` flag; this locks the same guard on.

  #3: the path must feed the picker the FULL eligible set (topics(limit=None)),
     not the operator's top-10 menu, or 990+ eligible topics starve forever and
     the loop re-synthesizes the same ~10 richest tags every day.

  #5: a FAILED autonomous run (crash / judge-stall / unfaithful) must always
     write its event AND fire a same-day Telegram alert -- otherwise the failure
     is invisible until the twice-daily cron, with the day's budget already gone.
"""

from types import SimpleNamespace
from unittest import mock

import pytest

from agent_core.modules import homeostasis_telegram_commands as htc
from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands as _register,
)


class _Bot:
    def __init__(self):
        self.messages = []

    def send_message(self, text, parse_mode=None):
        self.messages.append(text)
        return True


class _Bridge:
    def __init__(self):
        self.handlers = {}
        self.bot = _Bot()

    def register_command(self, command, handler):
        self.handlers[command] = handler


def _capture_trigger(meta_dir):
    """Register the real command table; return the captured autonomous
    synthesis trigger (the callback handed to set_synthesis_trigger)."""
    holder = {}
    core = SimpleNamespace(
        event_logger=SimpleNamespace(
            log_path=str(meta_dir / "homeostasis_events.jsonl")),
        set_synthesis_trigger=lambda cb: holder.__setitem__("cb", cb),
    )
    ctx = SimpleNamespace(
        maria_conductor=None, self_perception=None, homeostasis_core=core,
        planner_core=None, knowledge_analyzer=None, goal_store=None,
        bulletin_store=None, model_scheduler=None, sandbox_manager=None,
    )
    _register(_Bridge(), ctx)
    return holder["cb"]


class _ThreadStartFails:
    """Stand-in for threading.Thread whose .start() raises -- simulates
    RuntimeError('can't start new thread') under thread/FD exhaustion on a
    long-running daemon."""

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        raise RuntimeError("can't start new thread")


def test_autonomous_synthesis_releases_lock_when_thread_spawn_fails(tmp_path):
    trigger = _capture_trigger(tmp_path)

    eligible = [{"topic": "fizyka", "sources": 3}]
    fresh_state = {"last_run_ts": 0.0, "history": {}}  # cooldown elapsed
    fake_agent = mock.Mock()
    fake_agent.topics.return_value = eligible
    save_state = mock.Mock()

    with mock.patch(
        "agent_core.environment.environment_model.is_learning_window",
        return_value=True,
    ), mock.patch(
        "agent_core.synthesis.SynthesisAgent", return_value=fake_agent,
    ), mock.patch(
        "agent_core.synthesis.picker.load_state", return_value=fresh_state,
    ), mock.patch(
        "agent_core.synthesis.picker.save_state", save_state,
    ), mock.patch.object(htc.threading, "Thread", _ThreadStartFails):
        # Run 1: lock acquired, budget stamped, then Thread.start() raises.
        # The RuntimeError propagates (the tick loop swallows it in prod), but
        # the finally must have released the lock first.
        with pytest.raises(RuntimeError):
            trigger()
        # Run 2: if the lock had leaked, this bails at the non-blocking
        # acquire BEFORE stamping the budget again -> no RuntimeError, and
        # save_state would have been called only once. A released lock lets
        # run 2 reach Thread.start() again -> raises again, stamps again.
        with pytest.raises(RuntimeError):
            trigger()

    # Budget stamped on BOTH attempts => the lock was free at the start of
    # run 2 => it was released after run 1's failed spawn.
    assert save_state.call_count == 2


def test_autonomous_picker_is_fed_full_corpus_not_top_10(tmp_path):
    trigger = _capture_trigger(tmp_path)

    fake_agent = mock.Mock()
    fake_agent.topics.return_value = [{"topic": "fizyka", "sources": 3}]

    with mock.patch(
        "agent_core.environment.environment_model.is_learning_window",
        return_value=True,
    ), mock.patch(
        "agent_core.synthesis.SynthesisAgent", return_value=fake_agent,
    ), mock.patch(
        "agent_core.synthesis.picker.load_state",
        return_value={"last_run_ts": 0.0, "history": {}},
    ), mock.patch(
        "agent_core.synthesis.picker.save_state", mock.Mock(),
    ), mock.patch.object(htc.threading, "Thread", _ThreadStartFails):
        with pytest.raises(RuntimeError):  # thread spawn stubbed to fail
            trigger()

    # The picker's least-recently-synthesized rotation only works if it sees
    # the WHOLE corpus, so the autonomous caller must ask for limit=None, NOT
    # the operator-menu top-10.
    fake_agent.topics.assert_called_once_with(limit=None)


class _ThreadRunsInline:
    """Stand-in for threading.Thread that runs the target synchronously on
    .start(), so the worker body executes within the test."""

    def __init__(self, target=None, **kwargs):
        self._target = target

    def start(self):
        if self._target:
            self._target()


def _capture_full(meta_dir):
    """Like _capture_trigger but also exposes the bot (captured messages) and a
    list recording every event_logger._write_event call."""
    events = []
    holder = {}
    core = SimpleNamespace(
        event_logger=SimpleNamespace(
            log_path=str(meta_dir / "homeostasis_events.jsonl"),
            _write_event=lambda ev: events.append(ev),
        ),
        set_synthesis_trigger=lambda cb: holder.__setitem__("cb", cb),
    )
    ctx = SimpleNamespace(
        maria_conductor=None, self_perception=None, homeostasis_core=core,
        planner_core=None, knowledge_analyzer=None, goal_store=None,
        bulletin_store=None, model_scheduler=None, sandbox_manager=None,
    )
    bridge = _Bridge()
    _register(bridge, ctx)
    return holder["cb"], bridge.bot, events


def test_autonomous_synthesis_failure_writes_event_and_alerts(tmp_path):
    trigger, bot, events = _capture_full(tmp_path)

    fake_agent = mock.Mock()
    fake_agent.topics.return_value = [{"topic": "fizyka", "sources": 3}]

    with mock.patch(
        "agent_core.environment.environment_model.is_learning_window",
        return_value=True,
    ), mock.patch(
        "agent_core.synthesis.SynthesisAgent", return_value=fake_agent,
    ), mock.patch(
        "agent_core.synthesis.picker.load_state",
        return_value={"last_run_ts": 0.0, "history": {}},
    ), mock.patch(
        "agent_core.synthesis.picker.save_state", mock.Mock(),
    ), mock.patch(
        # Fail the cycle deterministically BEFORE any real LLM call: the cycle
        # builds a SandboxManager before run_cycle, so this raises cleanly and
        # exercises the failure path.
        "agent_core.sandbox.manager.SandboxManager",
        side_effect=RuntimeError("boom"),
    ), mock.patch.object(htc.threading, "Thread", _ThreadRunsInline):
        trigger()  # runs the worker inline; the cycle raises -> failure path

    # (a) event written even though the cycle crashed (cron + log scan visibility)
    synth_events = [e for e in events if e.get("event") == "autonomous_synthesis"]
    assert len(synth_events) == 1
    assert synth_events[0]["success"] is False
    assert synth_events[0]["reason"] == "cycle_error"
    # (b) same-day Telegram alert fired (operator does not wait for the cron)
    assert any("[Auto]" in m for m in bot.messages)
