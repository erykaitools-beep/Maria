"""Tests for warm crash recovery (Klocek 9, TIER 1 roof).

All file I/O uses tmp_path (the live maria.service races meta_data/*.jsonl);
the _maybe_warm_recover glue tests monkeypatch recovery I/O so they touch no
files at all. Run as a targeted suite.
"""

import json
import time
from types import SimpleNamespace

from agent_core.homeostasis import recovery
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.planner.strategic_plan import PlannedAction, StrategicPlan
from agent_core.planner.strategic_planner import StrategicPlanner


# ── recovery.py: feature flag (parallel-run, OFF by default) ───────────────

def test_is_enabled_off_by_default(monkeypatch):
    monkeypatch.delenv("WARM_RECOVERY_ENABLED", raising=False)
    assert recovery.is_enabled() is False


def test_is_enabled_on(monkeypatch):
    monkeypatch.setenv("WARM_RECOVERY_ENABLED", "1")
    assert recovery.is_enabled() is True


# ── recovery.py: write/read round-trip + atomicity + safety ────────────────

def _snap(plan_dict=None, goal_ids=None):
    return recovery.build_snapshot(
        mode="ACTIVE",
        last_mode_change_time=123.0,
        active_goal_ids=goal_ids if goal_ids is not None else ["g1", "g2"],
        plan_dict=plan_dict,
    )


def test_write_then_read_round_trip(tmp_path):
    path = tmp_path / "warm_recovery.json"
    assert recovery.write_snapshot(_snap(goal_ids=["g1"]), path) is True

    loaded = recovery.read_snapshot(path)
    assert loaded is not None
    assert loaded["mode"] == "ACTIVE"
    assert loaded["active_goal_ids"] == ["g1"]
    assert loaded["schema_version"] == recovery.SCHEMA_VERSION


def test_write_is_atomic_no_tmp_left(tmp_path):
    path = tmp_path / "warm_recovery.json"
    recovery.write_snapshot(_snap(), path)

    # os.replace consumed the tmp; final file is valid JSON (never torn).
    assert not (tmp_path / "warm_recovery.json.tmp").exists()
    json.loads(path.read_text(encoding="utf-8"))


def test_read_missing_file_returns_none(tmp_path):
    assert recovery.read_snapshot(tmp_path / "nope.json") is None


def test_read_corrupt_returns_none(tmp_path):
    # A torn last write (exactly the failure mode atomic-write prevents on our
    # own file, but a reader must still survive any corruption) -> cold boot.
    path = tmp_path / "warm_recovery.json"
    path.write_text('{"schema_version": 1, "written_at":', encoding="utf-8")
    assert recovery.read_snapshot(path) is None


def test_read_stale_returns_none(tmp_path):
    path = tmp_path / "warm_recovery.json"
    snap = _snap()
    snap["written_at"] = time.time() - 3600  # 1h old
    recovery.write_snapshot(snap, path)
    assert recovery.read_snapshot(path, max_age_seconds=900) is None


def test_read_schema_mismatch_returns_none(tmp_path):
    path = tmp_path / "warm_recovery.json"
    snap = _snap()
    snap["schema_version"] = 999
    recovery.write_snapshot(snap, path)
    assert recovery.read_snapshot(path) is None


# ── StrategicPlan.from_dict (the deserializer that was missing) ─────────────

def test_plan_from_dict_round_trip():
    plan = StrategicPlan(
        valid_until=9e9,
        action_queue=[
            PlannedAction(action_type="learn", goal_id="g1", reason="r", attempts=2),
        ],
        idle_strategy="evaluate", notes="n", model_used="qwen3",
    )
    back = StrategicPlan.from_dict(plan.to_dict())
    assert back.valid_until == 9e9
    assert back.idle_strategy == "evaluate"
    assert back.model_used == "qwen3"
    assert back.action_queue[0].action_type == "learn"
    assert back.action_queue[0].goal_id == "g1"
    assert back.action_queue[0].attempts == 2


def test_plan_from_dict_tolerates_missing_keys():
    back = StrategicPlan.from_dict({"action_queue": [{}]})
    assert back.idle_strategy == "wait"
    assert back.action_queue[0].action_type == ""


# ── StrategicPlanner.restore_plan ──────────────────────────────────────────

def test_restore_plan_sets_current():
    sp = StrategicPlanner()
    plan = StrategicPlan(valid_until=9e9, action_queue=[PlannedAction(action_type="learn")])
    sp.restore_plan(plan)
    assert sp.current_plan is plan


def test_restore_plan_resets_replan_clock():
    # Without seeding _last_plan_ts, should_replan()'s time branch (now - 0 >>
    # interval) fires on the first tick and discards the just-restored plan.
    sp = StrategicPlanner()
    sp.set_llm_fn(lambda *a, **k: "")  # should_replan only engages with an llm_fn
    plan = StrategicPlan(valid_until=9e9, action_queue=[PlannedAction(action_type="learn")])
    sp.restore_plan(plan)
    assert sp._last_plan_ts > 0
    assert sp.should_replan() is False  # resumed plan survives the first tick


def test_plan_from_dict_tolerates_wrong_types():
    # A torn/edited snapshot with wrong-typed fields must degrade, not raise.
    back = StrategicPlan.from_dict({"action_queue": 123, "blocked_goals": "nope"})
    assert back.action_queue == []
    assert back.blocked_goals == {}
    back2 = StrategicPlan.from_dict({"action_queue": None, "blocked_goals": ["x"]})
    assert back2.action_queue == []
    assert back2.blocked_goals == {}


# ── _maybe_warm_recover glue (maria.py boot hook, Klocek 9b) ────────────────

def _ctx_with_planner():
    sp = StrategicPlanner()
    ctx = SimpleNamespace(strategic_planner=sp, goal_store=None, homeostasis_core=None)
    return ctx, sp


def test_warm_recover_flag_off_short_circuits(monkeypatch):
    import maria
    seen = {"read": 0}
    monkeypatch.setattr(recovery, "is_enabled", lambda: False)
    monkeypatch.setattr(
        recovery, "read_snapshot",
        lambda *a, **k: seen.__setitem__("read", seen["read"] + 1) or None,
    )
    ctx, sp = _ctx_with_planner()

    maria._maybe_warm_recover(ctx)

    assert sp.current_plan is None
    assert seen["read"] == 0  # flag gate runs before any read => cold boot


def test_warm_recover_resumes_valid_plan(monkeypatch):
    import maria
    plan = StrategicPlan(
        valid_until=9e9,
        action_queue=[PlannedAction(action_type="learn", goal_id="g1")],
    )
    snap = recovery.build_snapshot("REDUCED", 1.0, ["g1"], plan.to_dict())
    monkeypatch.setattr(recovery, "is_enabled", lambda: True)
    monkeypatch.setattr(recovery, "read_snapshot", lambda *a, **k: snap)
    ctx, sp = _ctx_with_planner()

    maria._maybe_warm_recover(ctx)

    assert sp.current_plan is not None
    assert sp.current_plan.action_queue[0].goal_id == "g1"


def test_warm_recover_skips_expired_plan(monkeypatch):
    import maria
    plan = StrategicPlan(valid_until=1.0, action_queue=[PlannedAction(action_type="learn")])
    snap = recovery.build_snapshot("ACTIVE", 1.0, [], plan.to_dict())
    monkeypatch.setattr(recovery, "is_enabled", lambda: True)
    monkeypatch.setattr(recovery, "read_snapshot", lambda *a, **k: snap)
    ctx, sp = _ctx_with_planner()

    maria._maybe_warm_recover(ctx)

    assert sp.current_plan is None  # expired plan is not resumed


def test_warm_recover_no_snapshot_is_cold(monkeypatch):
    import maria
    monkeypatch.setattr(recovery, "is_enabled", lambda: True)
    monkeypatch.setattr(recovery, "read_snapshot", lambda *a, **k: None)
    ctx, sp = _ctx_with_planner()

    maria._maybe_warm_recover(ctx)  # must not raise

    assert sp.current_plan is None


# ── identity_store._save atomicity (Klocek 9c-L1) ──────────────────────────

def test_identity_save_is_atomic(tmp_path):
    from agent_core.consciousness.identity_store import IdentityStore
    store = IdentityStore(data_dir=str(tmp_path))

    store._save()

    target = store._file_path
    assert target.exists()
    json.loads(target.read_text(encoding="utf-8"))  # valid, never torn
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


# ── core.py producer glue (_write_recovery_snapshot / _active_goal_ids) ─────
# Driven via the unbound method on a duck-typed self (the staticmethod is bound
# explicitly) so no heavy HomeostasisCore construction / meta_data touch.

def _fake_core_self(ctx, mode="ACTIVE", last_change=42.0):
    return SimpleNamespace(
        _shared_context=ctx,
        state=SimpleNamespace(
            mode=SimpleNamespace(value=mode), last_mode_change_time=last_change,
        ),
        _active_goal_ids=HomeostasisCore._active_goal_ids,  # staticmethod -> fn
    )


def test_write_recovery_snapshot_producer_flag_on(monkeypatch):
    captured = {}
    monkeypatch.setattr(recovery, "is_enabled", lambda: True)
    monkeypatch.setattr(
        recovery, "write_snapshot",
        lambda snap, *a, **k: (captured.update(snap), True)[1],
    )
    sp = StrategicPlanner()
    sp.restore_plan(StrategicPlan(
        valid_until=9e9, action_queue=[PlannedAction(action_type="learn", goal_id="g1")],
    ))
    ctx = SimpleNamespace(
        strategic_planner=sp,
        goal_store=SimpleNamespace(get_active=lambda: [SimpleNamespace(id="g1")]),
    )

    HomeostasisCore._write_recovery_snapshot(_fake_core_self(ctx))

    assert captured["mode"] == "ACTIVE"
    assert captured["last_mode_change_time"] == 42.0
    assert captured["active_goal_ids"] == ["g1"]
    assert captured["strategic_plan"]["action_queue"][0]["goal_id"] == "g1"


def test_write_recovery_snapshot_flag_off_is_noop(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(recovery, "is_enabled", lambda: False)
    monkeypatch.setattr(
        recovery, "write_snapshot",
        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1),
    )

    HomeostasisCore._write_recovery_snapshot(_fake_core_self(None))

    assert calls["n"] == 0  # flag OFF => no write at all


def test_trigger_snapshot_calls_recovery_writer():
    calls = {"n": 0}
    fake = SimpleNamespace(
        executor=None,
        _write_recovery_snapshot=lambda: calls.__setitem__("n", calls["n"] + 1),
    )

    HomeostasisCore._trigger_snapshot(fake)

    assert calls["n"] == 1  # _trigger_snapshot drives the recovery write


def test_active_goal_ids_branches():
    f = HomeostasisCore._active_goal_ids
    assert f(None) == []  # no store

    class _Boom:
        def get_active(self):
            raise RuntimeError("x")

    assert f(_Boom()) == []  # get_active raising -> [] (not propagated)

    goals = [SimpleNamespace(id="a"), SimpleNamespace(id=""), SimpleNamespace(id="b")]
    assert f(SimpleNamespace(get_active=lambda: goals)) == ["a", "b"]  # empty id dropped


def test_write_snapshot_failure_returns_false(tmp_path):
    # Parent is a file -> mkdir/open fails -> return False, never raise.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    assert recovery.write_snapshot(_snap(), blocker / "warm_recovery.json") is False


def test_write_snapshot_cleans_tmp_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "warm_recovery.json"

    def boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(recovery.os, "replace", boom)  # fail after tmp written
    assert recovery.write_snapshot(_snap(), path) is False
    assert not (tmp_path / "warm_recovery.json.tmp").exists()  # tmp cleaned up
