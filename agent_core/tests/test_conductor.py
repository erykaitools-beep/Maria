"""Tests for the Conductor delegation layer (Phase 0.5 of market_agent build).

Coverage:
- Task model serialization round-trip (dataclass + Enums)
- TaskQueue MERGE semantics (last write wins on task_id)
- TaskQueue dependency-aware get_next
- BuildStatusStore JSON read/write
- Conductor lifecycle methods (mark_in_progress / done / blocked)
- Conductor.tick() refreshes BuildStatus correctly
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_core.conductor import (
    Assignee,
    BUILDER_ASSIGNEES,
    BuildStatus,
    BuildStatusStore,
    Conductor,
    Task,
    TaskQueue,
    TaskStatus,
    create_task,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def tmp_queue(tmp_path: Path) -> TaskQueue:
    return TaskQueue(path=tmp_path / "queue.jsonl")


@pytest.fixture
def tmp_status_store(tmp_path: Path) -> BuildStatusStore:
    return BuildStatusStore(path=tmp_path / "status.json")


@pytest.fixture
def tmp_conductor(
    tmp_queue: TaskQueue, tmp_status_store: BuildStatusStore
) -> Conductor:
    return Conductor(queue=tmp_queue, status_store=tmp_status_store)


def _seed_task(queue: TaskQueue, title: str = "t", phase: str = "p", **kwargs) -> Task:
    task = create_task(
        project=kwargs.get("project", "market_agent"),
        phase=phase,
        title=title,
        description=kwargs.get("description", "desc"),
        priority=kwargs.get("priority", 0.5),
        assignee=kwargs.get("assignee", Assignee.UNASSIGNED),
        dependencies=kwargs.get("dependencies"),
        estimated_minutes=kwargs.get("estimated_minutes"),
    )
    return queue.post(task)


# ============================================================
# Task model
# ============================================================

class TestTaskModel:
    def test_create_task_defaults_to_pending(self):
        task = create_task(project="market_agent", phase="p", title="x", description="d")
        assert task.status == TaskStatus.PENDING
        assert task.assignee == Assignee.UNASSIGNED
        assert task.task_id.startswith("cdt-")
        assert task.dependencies == []

    def test_to_dict_from_dict_roundtrip(self):
        task = create_task(
            project="market_agent",
            phase="p1",
            title="title",
            description="desc",
            priority=0.7,
            assignee=Assignee.CLAUDE_CLI,
            dependencies=["cdt-aaa"],
            estimated_minutes=120,
        )
        d = task.to_dict()
        # Enum fields must be primitive in dict for JSON safety
        assert isinstance(d["status"], str)
        assert isinstance(d["assignee"], str)
        rt = Task.from_dict(d)
        assert rt == task

    def test_terminal_property(self):
        t = create_task(project="m", phase="p", title="t", description="d")
        assert t.is_terminal is False
        d = t.to_dict()
        d["status"] = "done"
        assert Task.from_dict(d).is_terminal is True


# ============================================================
# TaskQueue
# ============================================================

class TestTaskQueue:
    def test_post_and_get(self, tmp_queue: TaskQueue):
        task = _seed_task(tmp_queue, title="x")
        assert tmp_queue.get(task.task_id) == task

    def test_persistence_roundtrip(self, tmp_path: Path):
        path = tmp_path / "q.jsonl"
        q1 = TaskQueue(path=path)
        a = _seed_task(q1, title="a")
        b = _seed_task(q1, title="b")
        # Fresh queue rebuilds from JSONL
        q2 = TaskQueue(path=path)
        assert q2.get(a.task_id).title == "a"
        assert q2.get(b.task_id).title == "b"

    def test_merge_semantics_last_write_wins(self, tmp_path: Path):
        path = tmp_path / "q.jsonl"
        q1 = TaskQueue(path=path)
        t = _seed_task(q1, title="x")
        q1.update(t.task_id, notes="first")
        q1.update(t.task_id, notes="second")
        q2 = TaskQueue(path=path)
        assert q2.get(t.task_id).notes == "second"

    def test_update_unknown_returns_none(self, tmp_queue: TaskQueue):
        assert tmp_queue.update("does-not-exist", status=TaskStatus.DONE) is None

    def test_list_filters(self, tmp_queue: TaskQueue):
        a = _seed_task(tmp_queue, title="a", project="market_agent")
        b = _seed_task(tmp_queue, title="b", project="market_agent")
        c = _seed_task(tmp_queue, title="c", project="other_project")
        tmp_queue.update(b.task_id, status=TaskStatus.DONE)

        all_market = tmp_queue.list(project="market_agent")
        assert {t.task_id for t in all_market} == {a.task_id, b.task_id}

        pending_market = tmp_queue.list(
            project="market_agent", status=TaskStatus.PENDING
        )
        assert {t.task_id for t in pending_market} == {a.task_id}

        no_terminal = tmp_queue.list(project="market_agent", include_terminal=False)
        assert {t.task_id for t in no_terminal} == {a.task_id}

        all_projects = tmp_queue.list()
        assert {t.task_id for t in all_projects} == {a.task_id, b.task_id, c.task_id}

    def test_get_next_picks_highest_priority(self, tmp_queue: TaskQueue):
        _seed_task(tmp_queue, title="lo", priority=0.3)
        hi = _seed_task(tmp_queue, title="hi", priority=0.9)
        _seed_task(tmp_queue, title="mid", priority=0.6)
        nxt = tmp_queue.get_next("market_agent")
        assert nxt is not None
        assert nxt.task_id == hi.task_id

    def test_get_next_respects_dependencies(self, tmp_queue: TaskQueue):
        a = _seed_task(tmp_queue, title="a", priority=0.9)
        b = _seed_task(
            tmp_queue, title="b", priority=0.95, dependencies=[a.task_id]
        )
        # b has higher prio but depends on a
        nxt = tmp_queue.get_next("market_agent")
        assert nxt.task_id == a.task_id
        # finish a
        tmp_queue.update(a.task_id, status=TaskStatus.DONE)
        nxt = tmp_queue.get_next("market_agent")
        assert nxt.task_id == b.task_id

    def test_get_next_skips_in_progress(self, tmp_queue: TaskQueue):
        a = _seed_task(tmp_queue, title="a", priority=0.9)
        tmp_queue.update(a.task_id, status=TaskStatus.IN_PROGRESS)
        # Only IN_PROGRESS -> nothing PENDING ready
        assert tmp_queue.get_next("market_agent") is None

    def test_external_writer_visible_after_mtime_bump(
        self, tmp_path: Path
    ) -> None:
        """Maria's running TaskQueue must pick up tasks written by a
        separate process (e.g. ``scripts/seed_task_*.py``). Without
        mtime-aware reload, ``_ensure_loaded`` is a one-shot no-op and
        external appends stay invisible until Maria restarts.
        """
        path = tmp_path / "q.jsonl"
        # Two independent instances pointing at the same file — simulates
        # Maria's daemon + a separate seed script.
        runtime = TaskQueue(path=path)
        external = TaskQueue(path=path)

        # Daemon-side: warm cache (file empty so far).
        assert runtime.get_next("market_agent") is None

        # External writer appends a task.
        external.post(create_task(
            project="market_agent", phase="p", title="from external",
            description="d", priority=0.9, assignee=Assignee.CODEX,
        ))

        # Force mtime bump so the daemon's reload trigger is unambiguous
        # even on filesystems with low-resolution mtime (e.g. older ext).
        new_mtime = path.stat().st_mtime + 2.0
        import os
        os.utime(path, (new_mtime, new_mtime))

        # Daemon-side: must now see the externally-posted task.
        nxt = runtime.get_next("market_agent")
        assert nxt is not None
        assert nxt.title == "from external"

    def test_stats(self, tmp_queue: TaskQueue):
        a = _seed_task(tmp_queue, title="a")
        b = _seed_task(tmp_queue, title="b")
        _seed_task(tmp_queue, title="c")
        tmp_queue.update(a.task_id, status=TaskStatus.DONE)
        tmp_queue.update(b.task_id, status=TaskStatus.IN_PROGRESS)
        s = tmp_queue.stats(project="market_agent")
        assert s["total"] == 3
        assert s["done"] == 1
        assert s["in_progress"] == 1
        assert s["pending"] == 1

    def test_corrupted_lines_skipped(self, tmp_path: Path, caplog):
        path = tmp_path / "q.jsonl"
        q = TaskQueue(path=path)
        good = _seed_task(q, title="good")
        # Append a corrupted line
        with open(path, "a", encoding="utf-8") as f:
            f.write("not-json{}\n")
        # Re-load — should not crash, good task survives
        q2 = TaskQueue(path=path)
        assert q2.get(good.task_id) is not None
        assert q2.get(good.task_id).title == "good"


# ============================================================
# BuildStatusStore
# ============================================================

class TestBuildStatusStore:
    def test_save_and_load(self, tmp_status_store: BuildStatusStore):
        s = BuildStatus(
            project="market_agent",
            current_phase="phase_1",
            progress_pct=0.25,
            blockers=["awaiting exchange decision"],
            pending_count=5,
            done_count=2,
            total_count=8,
        )
        tmp_status_store.save(s)
        loaded = tmp_status_store.load("market_agent")
        assert loaded is not None
        assert loaded.project == "market_agent"
        assert loaded.current_phase == "phase_1"
        assert loaded.progress_pct == 0.25
        assert loaded.blockers == ["awaiting exchange decision"]
        assert loaded.updated_at >= s.updated_at  # save() refreshes

    def test_multiple_projects(self, tmp_status_store: BuildStatusStore):
        s1 = BuildStatus(project="p1", current_phase="x")
        s2 = BuildStatus(project="p2", current_phase="y")
        tmp_status_store.save(s1)
        tmp_status_store.save(s2)
        assert tmp_status_store.list_projects() == ["p1", "p2"]

    def test_atomic_write_uses_tmp_then_rename(
        self, tmp_status_store: BuildStatusStore
    ):
        # tmp_status_store path lives in a tmp dir; a save should leave
        # only the final file, not the .tmp sibling.
        s = BuildStatus(project="m", current_phase="p")
        tmp_status_store.save(s)
        path = tmp_status_store._path
        assert path.exists()
        assert not path.with_suffix(".json.tmp").exists()
        # Sanity check JSON shape
        d = json.loads(path.read_text())
        assert "m" in d
        assert d["m"]["current_phase"] == "p"


# ============================================================
# Conductor
# ============================================================

class TestConductor:
    def test_lifecycle_in_progress_done(self, tmp_conductor: Conductor):
        task = create_task(
            project="market_agent", phase="p", title="x", description="d"
        )
        tmp_conductor.add_task(task)

        ip = tmp_conductor.mark_in_progress(task.task_id, Assignee.CLAUDE_CLI)
        assert ip is not None
        assert ip.status == TaskStatus.IN_PROGRESS
        assert ip.started_at is not None

        done = tmp_conductor.mark_done(
            task.task_id, artifacts={"file": "foo.py"}, notes="shipped"
        )
        assert done is not None
        assert done.status == TaskStatus.DONE
        assert done.artifacts == {"file": "foo.py"}
        assert done.notes == "shipped"
        assert done.completed_at is not None

    def test_mark_blocked_accumulates_reasons(self, tmp_conductor: Conductor):
        t = tmp_conductor.add_task(
            create_task(
                project="m", phase="p", title="x", description="d"
            )
        )
        tmp_conductor.mark_blocked(t.task_id, "missing dep")
        tmp_conductor.mark_blocked(t.task_id, "rate limit")
        # Re-blocking with the same reason should not duplicate
        b = tmp_conductor.mark_blocked(t.task_id, "missing dep")
        assert b is not None
        assert b.status == TaskStatus.BLOCKED
        assert b.blockers == ["missing dep", "rate limit"]

    def test_mark_pending_clears_blockers(self, tmp_conductor: Conductor):
        t = tmp_conductor.add_task(
            create_task(project="m", phase="p", title="x", description="d")
        )
        tmp_conductor.mark_blocked(t.task_id, "x")
        revived = tmp_conductor.mark_pending(t.task_id)
        assert revived is not None
        assert revived.status == TaskStatus.PENDING
        assert revived.blockers == []

    def test_lifecycle_unknown_id_returns_none(self, tmp_conductor: Conductor):
        assert tmp_conductor.mark_in_progress("nope", Assignee.OPERATOR) is None
        assert tmp_conductor.mark_done("nope") is None
        assert tmp_conductor.mark_blocked("nope", "r") is None
        assert tmp_conductor.mark_pending("nope") is None

    def test_tick_refreshes_status(self, tmp_conductor: Conductor):
        for i in range(4):
            tmp_conductor.add_task(
                create_task(
                    project="market_agent",
                    phase=f"phase_{i}",
                    title=f"t{i}",
                    description="d",
                    priority=0.5 + i * 0.05,
                )
            )
        tasks = tmp_conductor.list_tasks(project="market_agent")
        # Mark one in progress and one done
        tmp_conductor.mark_in_progress(tasks[0].task_id, Assignee.CLAUDE_CLI)
        tmp_conductor.mark_done(tasks[1].task_id)

        tmp_conductor.tick()
        status = tmp_conductor.get_status("market_agent")
        assert status is not None
        assert status.total_count == 4
        assert status.done_count == 1
        assert status.in_progress_count == 1
        assert status.pending_count == 2
        assert 0.0 < status.progress_pct < 1.0
        # current_phase comes from in-progress task
        assert status.current_phase == tasks[0].phase
        # next_task is the highest-prio remaining pending
        assert status.next_task_id is not None

    def test_tick_no_projects_is_noop(self, tmp_conductor: Conductor):
        # Nothing in queue — tick must not raise and not write status
        tmp_conductor.tick()
        assert tmp_conductor.get_status("market_agent") is None

    def test_get_next_task_proxy(self, tmp_conductor: Conductor):
        tmp_conductor.add_task(
            create_task(
                project="market_agent", phase="p", title="lo", description="d",
                priority=0.3,
            )
        )
        hi = tmp_conductor.add_task(
            create_task(
                project="market_agent", phase="p", title="hi", description="d",
                priority=0.9,
            )
        )
        nxt = tmp_conductor.get_next_task("market_agent")
        assert nxt is not None
        assert nxt.task_id == hi.task_id

    def test_persisted_state_visible_to_fresh_conductor(self, tmp_path: Path):
        q1 = TaskQueue(path=tmp_path / "q.jsonl")
        s1 = BuildStatusStore(path=tmp_path / "s.json")
        c1 = Conductor(queue=q1, status_store=s1)
        c1.add_task(
            create_task(project="m", phase="p", title="t", description="d")
        )
        c1.tick()

        q2 = TaskQueue(path=tmp_path / "q.jsonl")
        s2 = BuildStatusStore(path=tmp_path / "s.json")
        c2 = Conductor(queue=q2, status_store=s2)
        assert c2.get_status("m") is not None
        assert c2.list_tasks(project="m")


# ============================================================
# BUILDER_ASSIGNEES policy — Maria never autonomously routes to
# Claude CLI. Subscription account ban risk on autonomous CLI usage.
# ============================================================

class TestBuilderAssigneesPolicy:
    def test_policy_contents(self):
        # The exact set matters — adding CLAUDE_CLI here would silently
        # re-enable autonomous routing to a subscription account.
        assert BUILDER_ASSIGNEES == frozenset(
            {Assignee.CODEX, Assignee.AGENT_SELF}
        )

    def test_claude_cli_not_in_autonomous_set(self):
        # Explicit guardrail: this assertion is the regression alarm.
        assert Assignee.CLAUDE_CLI not in BUILDER_ASSIGNEES
        assert Assignee.OPERATOR not in BUILDER_ASSIGNEES
        assert Assignee.UNASSIGNED not in BUILDER_ASSIGNEES

    def test_get_autonomous_next_skips_claude_cli(
        self, tmp_conductor: Conductor
    ):
        # Higher-priority CLAUDE_CLI task must NOT win autonomous routing.
        tmp_conductor.add_task(
            create_task(
                project="market_agent",
                phase="p",
                title="claude_high",
                description="d",
                priority=0.99,
                assignee=Assignee.CLAUDE_CLI,
            )
        )
        codex = tmp_conductor.add_task(
            create_task(
                project="market_agent",
                phase="p",
                title="codex_low",
                description="d",
                priority=0.5,
                assignee=Assignee.CODEX,
            )
        )
        nxt = tmp_conductor.get_autonomous_next("market_agent")
        assert nxt is not None
        assert nxt.task_id == codex.task_id
        # Sanity: get_next_task (operator-facing) WOULD pick the CLAUDE_CLI
        # task because it does not filter by assignee. That's intentional —
        # operator can still see it and decide.
        op_view = tmp_conductor.get_next_task("market_agent")
        assert op_view.assignee == Assignee.CLAUDE_CLI

    def test_get_autonomous_next_skips_operator(
        self, tmp_conductor: Conductor
    ):
        tmp_conductor.add_task(
            create_task(
                project="market_agent", phase="p", title="op",
                description="d", priority=0.9, assignee=Assignee.OPERATOR,
            )
        )
        agent = tmp_conductor.add_task(
            create_task(
                project="market_agent", phase="p", title="agent",
                description="d", priority=0.4, assignee=Assignee.AGENT_SELF,
            )
        )
        nxt = tmp_conductor.get_autonomous_next("market_agent")
        assert nxt is not None
        assert nxt.task_id == agent.task_id

    def test_get_autonomous_next_respects_dependencies(
        self, tmp_conductor: Conductor
    ):
        a = tmp_conductor.add_task(
            create_task(
                project="market_agent", phase="p", title="a",
                description="d", priority=0.5, assignee=Assignee.CODEX,
            )
        )
        b = tmp_conductor.add_task(
            create_task(
                project="market_agent", phase="p", title="b",
                description="d", priority=0.95, assignee=Assignee.CODEX,
                dependencies=[a.task_id],
            )
        )
        # b has higher prio but waits on a
        nxt = tmp_conductor.get_autonomous_next("market_agent")
        assert nxt.task_id == a.task_id
        tmp_conductor.mark_done(a.task_id)
        nxt = tmp_conductor.get_autonomous_next("market_agent")
        assert nxt.task_id == b.task_id

    def test_get_autonomous_next_skips_approval_required(
        self, tmp_conductor: Conductor
    ):
        held = create_task(
            project="maria",
            phase="self_repair",
            title="needs approval",
            description="d",
            priority=0.99,
            assignee=Assignee.CODEX,
        )
        held.artifacts["approval_required"] = True
        tmp_conductor.add_task(held)
        approved = create_task(
            project="maria",
            phase="self_repair",
            title="approved",
            description="d",
            priority=0.5,
            assignee=Assignee.CODEX,
        )
        tmp_conductor.add_task(approved)

        nxt = tmp_conductor.get_autonomous_next("maria")
        assert nxt is not None
        assert nxt.task_id == approved.task_id

    def test_get_autonomous_next_approval_flipped_becomes_eligible(
        self, tmp_conductor: Conductor
    ):
        task = create_task(
            project="maria",
            phase="self_repair",
            title="repair",
            description="d",
            priority=0.9,
            assignee=Assignee.CODEX,
        )
        task.artifacts["approval_required"] = True
        tmp_conductor.add_task(task)
        assert tmp_conductor.get_autonomous_next("maria") is None

        task.artifacts["approval_required"] = False
        tmp_conductor.add_task(task)

        nxt = tmp_conductor.get_autonomous_next("maria")
        assert nxt is not None
        assert nxt.task_id == task.task_id

    def test_get_autonomous_next_missing_flag_treated_as_false(
        self, tmp_conductor: Conductor
    ):
        task = tmp_conductor.add_task(
            create_task(
                project="maria",
                phase="p",
                title="legacy",
                description="d",
                priority=0.5,
                assignee=Assignee.CODEX,
            )
        )

        nxt = tmp_conductor.get_autonomous_next("maria")
        assert nxt is not None
        assert nxt.task_id == task.task_id

    def test_get_autonomous_next_returns_none_when_only_claude(
        self, tmp_conductor: Conductor
    ):
        tmp_conductor.add_task(
            create_task(
                project="market_agent", phase="p", title="only_claude",
                description="d", priority=0.9, assignee=Assignee.CLAUDE_CLI,
            )
        )
        # No CODEX/AGENT_SELF candidate -> autonomous queue is empty
        assert tmp_conductor.get_autonomous_next("market_agent") is None
        # But operator preview still has it
        assert tmp_conductor.get_next_task("market_agent") is not None

    def test_two_conductors_isolated(self, tmp_path: Path):
        market = Conductor(
            queue=TaskQueue(path=tmp_path / "market.jsonl"),
            status_store=BuildStatusStore(path=tmp_path / "market_status.json"),
        )
        maria = Conductor(
            queue=TaskQueue(path=tmp_path / "maria.jsonl"),
            status_store=BuildStatusStore(path=tmp_path / "maria_status.json"),
        )

        market_task = market.add_task(
            create_task(
                project="market_agent",
                phase="p",
                title="market",
                description="d",
                assignee=Assignee.CODEX,
            )
        )
        assert maria.list_tasks(project="market_agent") == []

        maria_task = maria.add_task(
            create_task(
                project="maria",
                phase="p",
                title="maria",
                description="d",
                assignee=Assignee.CODEX,
            )
        )

        assert [t.task_id for t in market.list_tasks(project="market_agent")] == [
            market_task.task_id
        ]
        assert [t.task_id for t in maria.list_tasks(project="maria")] == [
            maria_task.task_id
        ]
        assert market.list_tasks(project="maria") == []
        assert maria.list_tasks(project="market_agent") == []
