"""Regression tests for the 2026-06-02 tick-loop freeze hardening.

Incident: at 05:57 the homeostasis tick loop stopped emitting logs for ~10.5h
(RSS stable -> not memory). Root cause chain:
  * StrategicPlanner ran a blocking qwen3:8b replan every 30 min on the tick
    path, even though STRATEGIC_PLANNER_DRIVES was OFF (its plan was discarded).
  * router.ask_as_role() had three fallbacks that called ollama._ask_once()
    with NO timeout (scheduler missing / scheduler load fail / inference fail).
  * call_with_timeout unblocks the caller but cannot cancel the Ollama call, so
    a wedged Ollama starved the 2-worker pool and pushed traffic onto the
    unbounded _ask_once paths -> one of them blocked forever -> total freeze.
  * Nothing noticed: the self-repair monitor runs on the same frozen loop.

Three hardening layers, one test class each:
  1. Gate the strategic replan behind _strategic_drives (no call when not driving).
  2. Bound every ollama fallback in ask_as_role with call_with_timeout.
  3. A liveness watchdog on a separate thread force-restarts a stalled tick loop.
"""

import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

from agent_core.planner.planner_core import PlannerCore
from agent_core.llm.router import LLMRouter
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.planner.strategic_planner import StrategicPlanner
from agent_core.tests.spec_helpers import specced


# ---------------------------------------------------------------------------
# Layer 1 -- strategic replan is gated behind the DRIVES flag
# ---------------------------------------------------------------------------
class TestStrategicReplanGate:
    def test_off_by_default_short_circuits_before_touching_strategist(self, monkeypatch):
        # Default env (DRIVES unset) -> drives is False -> we must not even
        # call should_replan() (the cheap part), let alone plan() (the blocker).
        # Strip the prod .env leak (STRATEGIC_PLANNER_DRIVES=1) so we test the
        # genuine default; load_dotenv() bleeds it into the process at import.
        monkeypatch.delenv("STRATEGIC_PLANNER_DRIVES", raising=False)
        p = PlannerCore()
        sp = specced(StrategicPlanner)
        sp.should_replan.return_value = True
        p.set_strategic_planner(sp)
        assert p._strategic_drives is False
        assert p._strategic_replan_due() is False
        sp.should_replan.assert_not_called()

    def test_explicit_off_is_a_kill_switch(self):
        p = PlannerCore()
        sp = specced(StrategicPlanner)
        sp.should_replan.return_value = True
        p.set_strategic_planner(sp)
        p.set_strategic_drives(False)
        assert p._strategic_replan_due() is False
        sp.should_replan.assert_not_called()

    def test_driving_and_due_runs_replan(self):
        p = PlannerCore()
        sp = specced(StrategicPlanner)
        sp.should_replan.return_value = True
        p.set_strategic_planner(sp)
        p.set_strategic_drives(True)
        assert p._strategic_replan_due() is True

    def test_driving_but_not_time_does_not_replan(self):
        p = PlannerCore()
        sp = specced(StrategicPlanner)
        sp.should_replan.return_value = False
        p.set_strategic_planner(sp)
        p.set_strategic_drives(True)
        assert p._strategic_replan_due() is False

    def test_driving_without_strategist_is_safe(self):
        p = PlannerCore()
        p.set_strategic_drives(True)  # no strategic planner wired
        assert p._strategic_replan_due() is False


# ---------------------------------------------------------------------------
# Layer 2 -- every ollama fallback in ask_as_role is time-bounded
# ---------------------------------------------------------------------------
def _router_with_ollama(ask_once):
    """Bare LLMRouter (no __init__) with just the ollama stub we need."""
    r = LLMRouter.__new__(LLMRouter)
    r.ollama = MagicMock()
    r.ollama._ask_once = ask_once
    return r


class TestBoundedAskOnce:
    def test_returns_value_on_success(self):
        r = _router_with_ollama(lambda prompt, temperature=0.3: "ok")
        assert r._bounded_ask_once("hi", 0.3, "planner") == "ok"

    def test_returns_empty_when_ollama_hangs_past_deadline(self, monkeypatch):
        # A wedged Ollama: _ask_once blocks well past the (shrunk) role timeout.
        # The caller must be released with "" instead of blocking forever -- this
        # is the exact path that froze the tick loop on 2026-06-02.
        monkeypatch.setattr(
            "agent_core.llm.router.get_timeout_for_role", lambda role: 0.1
        )

        def _hang(prompt, temperature=0.3):
            time.sleep(0.5)
            return "too late"

        r = _router_with_ollama(_hang)
        start = time.time()
        result = r._bounded_ask_once("hi", 0.3, "planner")
        elapsed = time.time() - start
        assert result == ""
        assert elapsed < 0.4  # released near the 0.1s deadline, not after 0.5s

    def test_non_timeout_errors_still_propagate(self):
        def _boom(prompt, temperature=0.3):
            raise ValueError("connection refused")

        r = _router_with_ollama(_boom)
        with pytest.raises(ValueError):
            r._bounded_ask_once("hi", 0.3, "planner")

    def test_router_ask_once_ollama_fallback_is_bounded(self, monkeypatch):
        # router._ask_once() falls back to a direct ollama call when NIM is
        # unavailable. That fallback must also be time-bounded.
        monkeypatch.setattr(
            "agent_core.llm.router.get_timeout_for_role", lambda role: 0.1
        )
        r = LLMRouter.__new__(LLMRouter)
        r.nim = None
        r._nim_fallbacks = 0
        r._ollama_calls = 0
        r.ollama = MagicMock()
        r.ollama.model = "llama3.1:8b"
        r.ollama._ask_once = lambda *a, **k: time.sleep(0.5) or "late"
        r._should_use_nim = lambda: False
        r._record_tape = lambda *a, **k: None

        start = time.time()
        result = r._ask_once("hi")
        elapsed = time.time() - start
        assert result == ""
        assert elapsed < 0.4


# ---------------------------------------------------------------------------
# Layer 3 -- out-of-loop liveness watchdog decision logic
# ---------------------------------------------------------------------------
def _bare_core(running, last_tick_monotonic, stall=300.0):
    """HomeostasisCore with only the watchdog fields the decision logic reads
    (bypasses the heavy real constructor)."""
    c = HomeostasisCore.__new__(HomeostasisCore)
    c._running = running
    c._last_tick_monotonic = last_tick_monotonic
    c._watchdog_stall_sec = stall
    c._external_op_deadline = None
    c._external_op_label = ""
    c._external_op_logged = False
    return c


class TestWatchdogDecision:
    def test_no_tick_yet_does_not_trip(self):
        c = _bare_core(True, None)
        assert c._tick_stalled_for() is None
        assert c._watchdog_should_trip() is False

    def test_fresh_tick_does_not_trip(self):
        c = _bare_core(True, time.monotonic())
        assert c._watchdog_should_trip() is False

    def test_just_under_deadline_does_not_trip(self):
        c = _bare_core(True, time.monotonic() - 100, stall=300.0)
        assert c._watchdog_should_trip() is False

    def test_stalled_tick_trips(self):
        # The 2026-06-02 freeze: tick heartbeat ages far past the deadline.
        c = _bare_core(True, time.monotonic() - 999, stall=300.0)
        assert c._tick_stalled_for() >= 998
        assert c._watchdog_should_trip() is True

    def test_not_running_never_trips(self):
        # During shutdown / between runs the heartbeat is legitimately stale;
        # the watchdog must not fire a restart then.
        c = _bare_core(False, time.monotonic() - 999, stall=300.0)
        assert c._watchdog_should_trip() is False


class TestWatchdogExternalOpLease:
    """2026-06-30 incident: Phase 17 dispatched a Codex implementation brief
    (30 min subprocess budget) and the watchdog force-restarted the process at
    +300s, killing Codex mid-build and stranding the task IN_PROGRESS. A
    declared external-op lease must hold the watchdog's fire for exactly the
    leased window -- and no longer."""

    def test_active_lease_holds_fire_on_a_stalled_tick(self):
        c = _bare_core(True, time.monotonic() - 999, stall=300.0)
        with c.external_op_lease(1800.0, label="codex-dispatch:market_agent"):
            assert c._watchdog_should_trip() is False

    def test_expired_lease_trips_again(self):
        # A wedge INSIDE the leased call (the 2026-06-02 class) must still be
        # bounded: once the allowance is spent the watchdog fires normally.
        c = _bare_core(True, time.monotonic() - 999, stall=300.0)
        with c.external_op_lease(0.0, label="codex-dispatch:market_agent"):
            assert c._watchdog_should_trip() is True

    def test_lease_release_restamps_heartbeat_then_trips_on_a_new_stall(self):
        # After a legitimate long lease the tick TAIL (phases after the leased
        # op) still has work to do. The release must give it a fresh window
        # instead of tripping instantly on the now-minutes-old stall clock
        # (the 2026-07-07 residual). Normal tripping returns only if the tail
        # itself then stalls past the deadline.
        c = _bare_core(True, time.monotonic() - 999, stall=300.0)
        with c.external_op_lease(1800.0):
            pass
        assert c._external_op_deadline is None
        # Heartbeat restamped on release -> the tail is not treated as wedged.
        assert c._watchdog_should_trip() is False
        # A genuine wedge in the tail (clock ages past the deadline) still trips.
        c._last_tick_monotonic = time.monotonic() - 999
        assert c._watchdog_should_trip() is True

    def test_lease_released_even_when_the_op_raises(self):
        c = _bare_core(True, time.monotonic() - 999, stall=300.0)
        with pytest.raises(RuntimeError):
            with c.external_op_lease(1800.0):
                raise RuntimeError("dispatch crashed")
        # finally still runs: lease cleared AND heartbeat restamped, so a crash
        # mid-dispatch does not leave the tail exposed to an instant trip.
        assert c._external_op_deadline is None
        assert c._watchdog_should_trip() is False

    def test_lease_does_not_mask_a_fresh_tick(self):
        # Lease active but the loop is beating fine -- nothing to suppress.
        c = _bare_core(True, time.monotonic(), stall=300.0)
        with c.external_op_lease(1800.0):
            assert c._watchdog_should_trip() is False

    def test_suppression_logs_once_per_lease(self, caplog):
        import logging as _logging
        c = _bare_core(True, time.monotonic() - 999, stall=300.0)
        c._watchdog_stop = threading.Event()
        c._watchdog_check_sec = 0.01
        with caplog.at_level(_logging.INFO, logger="agent_core.homeostasis.core"):
            with c.external_op_lease(1800.0, label="codex-dispatch:maria"):
                t = threading.Thread(target=c._watchdog_loop, daemon=True)
                t.start()
                time.sleep(0.15)
                c._watchdog_stop.set()
                t.join(timeout=2.0)
        held = [r for r in caplog.records if "holding fire" in r.getMessage()]
        assert len(held) == 1
        assert "codex-dispatch:maria" in held[0].getMessage()


class TestWatchdogArming:
    def test_disabled_via_env_does_not_spawn_thread(self, monkeypatch):
        monkeypatch.setenv("MARIA_WATCHDOG", "0")
        c = HomeostasisCore.__new__(HomeostasisCore)
        c._watchdog_thread = None
        c._watchdog_stop = threading.Event()
        c._watchdog_stall_sec = 300.0
        c._watchdog_check_sec = 30.0
        c._last_tick_monotonic = None
        c.start_watchdog()
        assert c._watchdog_thread is None

    def test_arms_a_daemon_thread_and_is_idempotent(self, monkeypatch):
        monkeypatch.setenv("MARIA_WATCHDOG", "1")
        c = HomeostasisCore.__new__(HomeostasisCore)
        c._watchdog_thread = None
        c._watchdog_stop = threading.Event()
        c._watchdog_stall_sec = 300.0
        c._watchdog_check_sec = 30.0
        c._last_tick_monotonic = None
        c._running = True
        try:
            c.start_watchdog()
            assert c._watchdog_thread is not None
            assert c._watchdog_thread.is_alive()
            assert c._watchdog_thread.daemon is True
            first = c._watchdog_thread
            c.start_watchdog()  # idempotent: no second thread
            assert c._watchdog_thread is first
        finally:
            c._watchdog_stop.set()
            if c._watchdog_thread is not None:
                c._watchdog_thread.join(timeout=1.0)


class TestWatchdogThreadLoop:
    """Exercise the real watchdog thread loop -- _trip_watchdog is stubbed so we
    observe the decision without os._exit killing the test process."""

    def _core(self, stall, check, last_tick):
        c = _bare_core(True, last_tick, stall=stall)
        c._watchdog_stop = threading.Event()
        c._watchdog_check_sec = check
        return c

    def test_loop_trips_on_a_stalled_tick(self):
        c = self._core(stall=0.2, check=0.05, last_tick=time.monotonic() - 10.0)
        tripped = []
        c._trip_watchdog = lambda stalled: tripped.append(stalled)
        t = threading.Thread(target=c._watchdog_loop, daemon=True)
        t.start()
        time.sleep(0.25)
        c._watchdog_stop.set()
        t.join(timeout=1.0)
        assert tripped, "watchdog must trip on a stalled tick"
        assert tripped[0] >= 9.0

    def test_loop_stays_quiet_while_ticks_keep_beating(self):
        c = self._core(stall=5.0, check=0.05, last_tick=time.monotonic())
        tripped = []
        c._trip_watchdog = lambda stalled: tripped.append(stalled)

        def beat():
            for _ in range(6):
                c._last_tick_monotonic = time.monotonic()
                time.sleep(0.05)

        t = threading.Thread(target=c._watchdog_loop, daemon=True)
        b = threading.Thread(target=beat, daemon=True)
        t.start()
        b.start()
        b.join(timeout=1.0)
        c._watchdog_stop.set()
        t.join(timeout=1.0)
        assert not tripped, "watchdog must not trip while ticks keep beating"

    def test_trip_watchdog_hard_exits_with_code_1(self):
        # _trip_watchdog must terminate the process (os._exit(1)) so systemd
        # relaunches us -- proven in a subprocess so it cannot kill the test run.
        code = (
            "from agent_core.homeostasis.core import HomeostasisCore\n"
            "c = HomeostasisCore.__new__(HomeostasisCore)\n"
            "c._watchdog_stall_sec = 300.0\n"
            "c._tick_count = 42\n"
            "c._trip_watchdog(999.0)\n"
            "print('UNREACHABLE')\n"
        )
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 1
        assert "UNREACHABLE" not in r.stdout


class TestWatchdogThread:
    def test_loop_trips_on_stall(self):
        # End-to-end: the watchdog THREAD must call _trip_watchdog on a stall.
        # _trip_watchdog is stubbed so the test process survives (the real one
        # would os._exit(1)).
        c = _bare_core(True, time.monotonic() - 1.0, stall=0.05)  # stalled
        c._watchdog_stop = threading.Event()
        c._watchdog_check_sec = 0.01
        tripped = {"stalled": None}

        def _fake_trip(stalled):
            tripped["stalled"] = stalled
            c._watchdog_stop.set()  # let the loop exit

        c._trip_watchdog = _fake_trip
        t = threading.Thread(target=c._watchdog_loop, daemon=True)
        t.start()
        t.join(timeout=2.0)
        assert tripped["stalled"] is not None
        assert tripped["stalled"] >= 0.05

    def test_loop_quiet_while_healthy(self):
        c = _bare_core(True, time.monotonic(), stall=5.0)  # fresh
        c._watchdog_stop = threading.Event()
        c._watchdog_check_sec = 0.01
        tripped = {"called": False}
        c._trip_watchdog = lambda s: tripped.__setitem__("called", True)
        t = threading.Thread(target=c._watchdog_loop, daemon=True)
        t.start()
        time.sleep(0.1)  # several check cycles
        c._watchdog_stop.set()
        t.join(timeout=2.0)
        assert tripped["called"] is False
