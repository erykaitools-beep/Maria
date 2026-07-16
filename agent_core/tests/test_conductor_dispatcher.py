"""Tests for ConductorDispatcher — autonomous Codex dispatch.

Covers:
- Throttling (interval gate)
- Skip when no PENDING task
- Workspace resolution + blocked-on-missing
- Codex returns None → BLOCKED, or RATE_LIMITED + requeue when window full
- Git HEAD unchanged → BLOCKED with "no commits"
- Git HEAD moved → DONE with commit SHAs in artifacts
- Notification fired at start and at result
- task.description passed verbatim as Codex prompt
- cwd= passed correctly to CodexClient.ask
"""

from __future__ import annotations

import subprocess
from collections import deque
from pathlib import Path
from typing import List, Optional

import pytest

from agent_core.conductor import (
    Assignee,
    BuildStatusStore,
    Conductor,
    TaskQueue,
    TaskStatus,
    create_task,
)
from agent_core.conductor.dispatcher import (
    ConductorDispatcher,
    DispatchOutcome,
    DispatchResult,
    auto_commit_codex_work,
    get_commits_between,
    get_workspace_dirty,
    get_workspace_head,
)


# ============================================================
# Fixtures
# ============================================================


class FakeCodex:
    """Test double for CodexClient. Records calls, returns scripted responses."""

    def __init__(
        self,
        response: Optional[str] = "ok",
        calls_this_hour: int = 0,
    ):
        self._response = response
        # Mirror CodexClient internals the dispatcher peeks at for
        # rate-limit detection.
        self._call_timestamps: deque = deque([0.0] * calls_this_hour)
        self.calls: List[dict] = []

    def ask(
        self, prompt, source="unknown", context=None,
        cwd=None, timeout_s=None, impl_mode=False,
    ):
        self.calls.append({
            "prompt": prompt,
            "source": source,
            "context": context,
            "cwd": cwd,
            "timeout_s": timeout_s,
            "impl_mode": impl_mode,
        })
        return self._response


@pytest.fixture
def conductor(tmp_path: Path) -> Conductor:
    queue = TaskQueue(path=tmp_path / "queue.jsonl")
    status = BuildStatusStore(path=tmp_path / "status.json")
    return Conductor(queue=queue, status_store=status)


@pytest.fixture
def git_workspace(tmp_path: Path) -> Path:
    """Real git repo at tmp_path/work with an initial commit."""
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.email", "t@test"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=work, check=True)
    (work / "README.md").write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=work, check=True
    )
    return work


def _git_init(path: Path) -> Path:
    """Initialize ``path`` as a git repo with one commit (a readable HEAD).

    Post-audit the dispatcher refuses to run Codex when it cannot read a HEAD
    baseline pre-dispatch (audit 2026-06-16 #19), so dispatch tests need real
    repos, not bare mkdir dirs."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)
    (path / "README.md").write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def _seed_codex_task(
    conductor: Conductor,
    *,
    workspace: Optional[Path] = None,
    description: str = "Read brief X and implement",
    project: str = "market_agent",
    approval_required: bool = False,
):
    task = create_task(
        project=project,
        phase="p9.1",
        title="Test dispatch",
        description=description,
        assignee=Assignee.CODEX,
        priority=0.9,
    )
    # Default approved/dispatchable: post-audit the maria dispatcher is
    # fail-closed on a MISSING flag (a forgotten flag must not auto-dispatch on
    # the live repo), so seeded maria tasks must opt in explicitly to dispatch.
    task.artifacts["approval_required"] = approval_required
    if workspace is not None:
        task.artifacts["workspace_path"] = str(workspace)
    conductor.add_task(task)
    return task


# ============================================================
# Throttling
# ============================================================


def test_should_dispatch_true_when_never_dispatched(conductor):
    d = ConductorDispatcher(conductor, FakeCodex(), "market_agent",
                            interval_sec=600.0, clock_fn=lambda: 1000.0)
    assert d.should_dispatch() is True


def test_should_dispatch_false_within_interval(conductor):
    d = ConductorDispatcher(conductor, FakeCodex(), "market_agent",
                            interval_sec=600.0, clock_fn=lambda: 1000.0)
    d.dispatch_next()  # sets _last_dispatch_ts=1000
    # Advance clock by 599s — under threshold
    d._clock = lambda: 1599.0
    assert d.should_dispatch() is False


def test_should_dispatch_true_after_interval(conductor):
    d = ConductorDispatcher(conductor, FakeCodex(), "market_agent",
                            interval_sec=600.0, clock_fn=lambda: 1000.0)
    d.dispatch_next()
    d._clock = lambda: 1600.0
    assert d.should_dispatch() is True


def test_two_dispatchers_independent_throttling(tmp_path):
    market_conductor = Conductor(
        queue=TaskQueue(path=tmp_path / "market_queue.jsonl"),
        status_store=BuildStatusStore(path=tmp_path / "market_status.json"),
    )
    maria_conductor = Conductor(
        queue=TaskQueue(path=tmp_path / "maria_queue.jsonl"),
        status_store=BuildStatusStore(path=tmp_path / "maria_status.json"),
    )
    market_workspace = _git_init(tmp_path / "market_workspace")
    maria_workspace = _git_init(tmp_path / "maria_workspace")
    market_codex = FakeCodex(response="ok")
    maria_codex = FakeCodex(response="ok")
    market_dispatcher = ConductorDispatcher(
        market_conductor, market_codex, "market_agent", interval_sec=60.0,
    )
    maria_dispatcher = ConductorDispatcher(
        maria_conductor, maria_codex, "maria", interval_sec=60.0,
    )

    _seed_codex_task(market_conductor, workspace=market_workspace)
    _seed_codex_task(maria_conductor, workspace=maria_workspace, project="maria")

    market_dispatcher.dispatch_next(now=0.0)
    maria_dispatcher.dispatch_next(now=0.0)
    assert len(market_codex.calls) == 1
    assert len(maria_codex.calls) == 1

    assert market_dispatcher.should_dispatch(now=30.0) is False
    assert maria_dispatcher.should_dispatch(now=30.0) is False

    _seed_codex_task(market_conductor, workspace=market_workspace)
    _seed_codex_task(maria_conductor, workspace=maria_workspace, project="maria")
    assert market_dispatcher.should_dispatch(now=70.0) is True
    assert maria_dispatcher.should_dispatch(now=70.0) is True
    market_dispatcher.dispatch_next(now=70.0)
    maria_dispatcher.dispatch_next(now=70.0)
    assert len(market_codex.calls) == 2
    assert len(maria_codex.calls) == 2


# ============================================================
# Skip / blocked paths (no Codex call)
# ============================================================


def test_skipped_when_no_pending_task(conductor):
    d = ConductorDispatcher(conductor, FakeCodex(), "market_agent")
    result = d.dispatch_next()
    assert result.outcome is DispatchOutcome.SKIPPED
    assert result.task_id is None


def test_blocked_when_missing_workspace_path(conductor):
    _seed_codex_task(conductor, workspace=None)
    codex = FakeCodex()
    d = ConductorDispatcher(conductor, codex, "market_agent")

    result = d.dispatch_next()
    assert result.outcome is DispatchOutcome.BLOCKED
    assert "workspace_path" in (result.error or "")
    assert codex.calls == []  # Codex was never invoked


def test_blocked_when_workspace_does_not_exist(conductor, tmp_path):
    _seed_codex_task(conductor, workspace=tmp_path / "does_not_exist")
    codex = FakeCodex()
    d = ConductorDispatcher(conductor, codex, "market_agent")

    result = d.dispatch_next()
    assert result.outcome is DispatchOutcome.BLOCKED
    assert codex.calls == []


# ============================================================
# Codex returns None
# ============================================================


def test_codex_none_marks_blocked(conductor, git_workspace):
    _seed_codex_task(conductor, workspace=git_workspace)
    codex = FakeCodex(response=None)
    d = ConductorDispatcher(conductor, codex, "market_agent")

    result = d.dispatch_next()
    assert result.outcome is DispatchOutcome.BLOCKED
    assert "codex returned None" in (result.error or "")
    # Task state should be BLOCKED
    refreshed = conductor.get_next_task("market_agent")
    # get_next_task returns next PENDING; if blocked, this returns None
    assert refreshed is None


def test_codex_none_with_full_rate_window_requeues(conductor, git_workspace):
    task = _seed_codex_task(conductor, workspace=git_workspace)
    # Rate window full → CodexClient would return None for rate-limit reason
    codex = FakeCodex(response=None, calls_this_hour=10)
    d = ConductorDispatcher(conductor, codex, "market_agent")

    result = d.dispatch_next()
    assert result.outcome is DispatchOutcome.RATE_LIMITED
    assert result.task_id == task.task_id
    # Task should be PENDING again (re-queued)
    refreshed = conductor.get_next_task("market_agent")
    assert refreshed is not None
    assert refreshed.task_id == task.task_id
    assert refreshed.status is TaskStatus.PENDING


# ============================================================
# Git HEAD diff = done detection
# ============================================================


def test_done_when_head_advances(conductor, git_workspace):
    """Simulate Codex committing during the ask() call."""
    _seed_codex_task(conductor, workspace=git_workspace)

    class CommittingCodex:
        _call_timestamps: deque = deque()
        def ask(self, prompt, source="unknown", context=None,
                cwd=None, timeout_s=None, impl_mode=False):
            # Simulate Codex making a commit
            (cwd / "new.py").write_text("# new")
            subprocess.run(["git", "add", "-A"], cwd=cwd, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "from codex"],
                cwd=cwd, check=True,
            )
            return "implemented and committed"

    d = ConductorDispatcher(conductor, CommittingCodex(), "market_agent")
    result = d.dispatch_next()

    assert result.outcome is DispatchOutcome.DONE
    assert len(result.commits) == 1
    assert "implemented" in result.response_summary


def test_done_artifacts_persist(conductor, git_workspace):
    _seed_codex_task(conductor, workspace=git_workspace)

    class CommittingCodex:
        _call_timestamps: deque = deque()
        def ask(self, prompt, source="unknown", context=None,
                cwd=None, timeout_s=None, impl_mode=False):
            (cwd / "f.py").write_text("# f")
            subprocess.run(["git", "add", "-A"], cwd=cwd, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=cwd, check=True)
            return "x"

    d = ConductorDispatcher(conductor, CommittingCodex(), "market_agent")
    result = d.dispatch_next()
    assert result.outcome is DispatchOutcome.DONE

    # Now task should be DONE and artifacts should include commits + head_before/after
    all_done = conductor.list_tasks(
        project="market_agent", status=TaskStatus.DONE
    )
    assert len(all_done) == 1
    art = all_done[0].artifacts
    assert "commits" in art and len(art["commits"]) == 1
    assert "head_before" in art and "head_after" in art
    assert art["head_before"] != art["head_after"]


def test_blocked_when_head_unchanged(conductor, git_workspace):
    """Codex responded but never committed — work was partial."""
    _seed_codex_task(conductor, workspace=git_workspace)
    codex = FakeCodex(response="i thought about it but didn't commit")
    d = ConductorDispatcher(conductor, codex, "market_agent")

    result = d.dispatch_next()
    assert result.outcome is DispatchOutcome.BLOCKED
    assert "no commits" in (result.error or "")
    assert "thought about it" in result.response_summary


# ============================================================
# Codex call parameters
# ============================================================


def test_codex_receives_task_description_as_prompt(conductor, git_workspace):
    _seed_codex_task(
        conductor, workspace=git_workspace, description="DO THE THING"
    )
    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(conductor, codex, "market_agent")
    d.dispatch_next()

    assert len(codex.calls) == 1
    assert codex.calls[0]["prompt"] == "DO THE THING"


def test_codex_receives_workspace_cwd(conductor, git_workspace):
    _seed_codex_task(conductor, workspace=git_workspace)
    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(conductor, codex, "market_agent")
    d.dispatch_next()

    assert codex.calls[0]["cwd"] == git_workspace


def test_dispatcher_with_maria_project(conductor, tmp_path):
    workspace = _git_init(tmp_path / "fake_maria_workspace")
    _seed_codex_task(conductor, workspace=workspace, project="maria")
    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(conductor, codex, "maria")

    d.dispatch_next()

    assert len(codex.calls) == 1
    assert codex.calls[0]["cwd"] == workspace


def test_codex_receives_source_and_context(conductor, git_workspace):
    task = _seed_codex_task(conductor, workspace=git_workspace)
    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(conductor, codex, "market_agent")
    d.dispatch_next()

    assert codex.calls[0]["source"] == "conductor_dispatcher"
    ctx = codex.calls[0]["context"]
    assert ctx["task_id"] == task.task_id
    assert ctx["project"] == "market_agent"


def test_codex_receives_extended_timeout(conductor, git_workspace):
    """Default 3600s for implementation briefs (not the 120s Q&A default)."""
    _seed_codex_task(conductor, workspace=git_workspace)
    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(conductor, codex, "market_agent")
    d.dispatch_next()
    assert codex.calls[0]["timeout_s"] == 3600.0


def test_codex_timeout_override(conductor, git_workspace):
    """Per-dispatcher override propagates to ask()."""
    _seed_codex_task(conductor, workspace=git_workspace)
    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(
        conductor, codex, "market_agent", codex_timeout_sec=300.0,
    )
    d.dispatch_next()
    assert codex.calls[0]["timeout_s"] == 300.0


def test_dispatcher_runs_codex_in_impl_mode(conductor, git_workspace):
    """Dispatcher must enable workspace-write + ask-for-approval=never.
    Without impl_mode=True the read-only default blocks all edits and
    the first in-vivo dispatch on 2026-05-25 17:01 ended with sandbox
    "filesystem read-only" + no commits + BLOCKED.
    """
    _seed_codex_task(conductor, workspace=git_workspace)
    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(conductor, codex, "market_agent")
    d.dispatch_next()
    assert codex.calls[0]["impl_mode"] is True


# ============================================================
# Notification
# ============================================================


def test_notify_called_on_dispatch_start_and_result(conductor, git_workspace):
    """Two notifications: one when dispatch starts, one with outcome."""
    _seed_codex_task(conductor, workspace=git_workspace)
    msgs: List[str] = []
    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(
        conductor, codex, "market_agent",
        notify_fn=msgs.append,
    )
    d.dispatch_next()

    assert len(msgs) == 2
    assert "Dispatching" in msgs[0]
    # outcome is BLOCKED (no commits since codex didn't actually commit)
    # but the notification still fires
    assert any(kw in msgs[1] for kw in ("DONE", "BLOCKED", "rate-limited"))


def test_notify_skip_path_when_blocked_pre_codex(conductor):
    """No workspace_path → BLOCKED before Codex; still notifies."""
    _seed_codex_task(conductor, workspace=None)
    msgs: List[str] = []
    codex = FakeCodex()
    d = ConductorDispatcher(
        conductor, codex, "market_agent",
        notify_fn=msgs.append,
    )
    d.dispatch_next()
    # Only one notification (BLOCKED), no "Dispatching" because we skip
    # the Codex call entirely.
    assert any("BLOCKED" in m for m in msgs)


# ============================================================
# Helper functions
# ============================================================


def test_get_workspace_head_returns_sha(git_workspace):
    sha = get_workspace_head(git_workspace)
    assert sha is not None
    assert len(sha) == 40  # SHA-1 hex


def test_get_workspace_head_returns_none_for_non_repo(tmp_path):
    sha = get_workspace_head(tmp_path)
    assert sha is None


def test_get_commits_between_empty_when_same_sha(git_workspace):
    sha = get_workspace_head(git_workspace)
    assert get_commits_between(git_workspace, sha, sha) == []


def test_get_commits_between_returns_new_commits(git_workspace):
    base = get_workspace_head(git_workspace)
    # Make two new commits
    for n in range(2):
        (git_workspace / f"f{n}.txt").write_text(str(n))
        subprocess.run(["git", "add", "-A"], cwd=git_workspace, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", f"c{n}"],
            cwd=git_workspace, check=True,
        )
    head = get_workspace_head(git_workspace)
    commits = get_commits_between(git_workspace, base, head)
    assert len(commits) == 2


# ============================================================
# Dispatch interval is updated unconditionally
# ============================================================


def test_dispatch_updates_last_ts_even_on_skipped(conductor):
    d = ConductorDispatcher(
        conductor, FakeCodex(), "market_agent",
        clock_fn=lambda: 5000.0,
    )
    result = d.dispatch_next()
    assert result.outcome is DispatchOutcome.SKIPPED
    assert d._last_dispatch_ts == 5000.0


def test_dispatch_updates_last_ts_on_blocked(conductor):
    _seed_codex_task(conductor, workspace=None)
    d = ConductorDispatcher(
        conductor, FakeCodex(), "market_agent",
        clock_fn=lambda: 7000.0,
    )
    d.dispatch_next()
    assert d._last_dispatch_ts == 7000.0


# ============================================================
# A' safeguard — workspace cleanliness pre-check + auto-commit
# ============================================================


def test_get_workspace_dirty_clean_repo(git_workspace):
    assert get_workspace_dirty(git_workspace) is False


def test_get_workspace_dirty_with_untracked_file(git_workspace):
    (git_workspace / "untracked.txt").write_text("x")
    assert get_workspace_dirty(git_workspace) is True


def test_get_workspace_dirty_with_modified_file(git_workspace):
    (git_workspace / "README.md").write_text("modified")
    assert get_workspace_dirty(git_workspace) is True


def test_get_workspace_dirty_returns_false_for_non_repo(tmp_path):
    assert get_workspace_dirty(tmp_path) is False


def test_blocked_when_workspace_dirty_pre_dispatch(conductor, git_workspace):
    """Operator left work-in-progress → refuse dispatch, never call Codex.

    Without this guard, auto-commit would sweep operator's unrelated files
    into a "from codex:" commit.
    """
    _seed_codex_task(conductor, workspace=git_workspace)
    (git_workspace / "operator_wip.txt").write_text("operator was here")

    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(conductor, codex, "market_agent")
    result = d.dispatch_next()

    assert result.outcome is DispatchOutcome.BLOCKED
    assert "dirty" in (result.error or "").lower()
    assert codex.calls == []  # Codex never invoked


def test_auto_commit_when_codex_leaves_dirty_tree(conductor, git_workspace):
    """Codex's "Implemented in the working tree" pattern — dispatcher
    auto-commits dirty tree on success and marks DONE.
    """
    _seed_codex_task(conductor, workspace=git_workspace)

    class NonCommittingCodex:
        _call_timestamps: deque = deque()
        def ask(self, prompt, source="unknown", context=None,
                cwd=None, timeout_s=None, impl_mode=False):
            (cwd / "feature.py").write_text("# implemented")
            return "Implemented in the working tree."

    d = ConductorDispatcher(conductor, NonCommittingCodex(), "market_agent")
    result = d.dispatch_next()

    assert result.outcome is DispatchOutcome.DONE
    assert len(result.commits) == 1
    # Verify the commit landed in the workspace
    final_head = get_workspace_head(git_workspace)
    assert final_head == result.commits[0]


def test_auto_commit_persists_auto_committed_artifact(conductor, git_workspace):
    """DONE artifacts include ``auto_committed=True`` so post-hoc audits
    can distinguish Codex's own commits from dispatcher-side commits.
    """
    _seed_codex_task(conductor, workspace=git_workspace)

    class NonCommittingCodex:
        _call_timestamps: deque = deque()
        def ask(self, prompt, source="unknown", context=None,
                cwd=None, timeout_s=None, impl_mode=False):
            (cwd / "f.py").write_text("x")
            return "done in tree"

    d = ConductorDispatcher(conductor, NonCommittingCodex(), "market_agent")
    d.dispatch_next()

    all_done = conductor.list_tasks(
        project="market_agent", status=TaskStatus.DONE,
    )
    assert len(all_done) == 1
    assert all_done[0].artifacts.get("auto_committed") is True


def test_auto_commit_message_format(conductor, git_workspace):
    """Commit message must match ``from codex: {task_id} - {title}``
    so log scanners and ledger tooling can attribute autonomous commits.
    """
    task = _seed_codex_task(conductor, workspace=git_workspace)

    class NonCommittingCodex:
        _call_timestamps: deque = deque()
        def ask(self, prompt, source="unknown", context=None,
                cwd=None, timeout_s=None, impl_mode=False):
            (cwd / "f.py").write_text("x")
            return "done"

    d = ConductorDispatcher(conductor, NonCommittingCodex(), "market_agent")
    d.dispatch_next()

    last_msg = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=git_workspace, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert last_msg == f"from codex: {task.task_id} - {task.title}"


def test_codex_self_commit_no_double_commit(conductor, git_workspace):
    """When Codex commits itself, dispatcher must NOT auto-commit again.
    The head_before != head_after branch takes the DONE path directly.
    """
    _seed_codex_task(conductor, workspace=git_workspace)

    class SelfCommittingCodex:
        _call_timestamps: deque = deque()
        def ask(self, prompt, source="unknown", context=None,
                cwd=None, timeout_s=None, impl_mode=False):
            (cwd / "self.py").write_text("x")
            subprocess.run(["git", "add", "-A"], cwd=cwd, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "codex self-commit"],
                cwd=cwd, check=True,
            )
            return "self-committed"

    d = ConductorDispatcher(conductor, SelfCommittingCodex(), "market_agent")
    d.dispatch_next()

    all_done = conductor.list_tasks(
        project="market_agent", status=TaskStatus.DONE,
    )
    assert len(all_done) == 1
    # auto_committed must be absent or False — this was Codex's own commit
    assert all_done[0].artifacts.get("auto_committed") is not True
    # Exactly one new commit, with Codex's message (not "from codex:")
    last_msg = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=git_workspace, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert last_msg == "codex self-commit"


def test_auto_commit_codex_work_helper_returns_new_sha(git_workspace):
    """Direct helper test: dirty tree → commit → new SHA returned."""
    base = get_workspace_head(git_workspace)
    (git_workspace / "x.py").write_text("x")

    new_sha = auto_commit_codex_work(git_workspace, "t-123", "Title here")

    assert new_sha is not None
    assert new_sha != base
    assert len(new_sha) == 40


def test_auto_commit_codex_work_helper_returns_none_on_clean_tree(git_workspace):
    """Nothing to commit → git commit exits non-zero → None.
    Safety net: the caller already pre-checks dirty, but the helper must
    not silently report success on a no-op.
    """
    new_sha = auto_commit_codex_work(git_workspace, "t-123", "Title")
    assert new_sha is None


def test_codex_clean_tree_response_still_blocks(conductor, git_workspace):
    """Codex responded but neither committed nor modified files → BLOCKED.
    Distinct from auto-commit path: dirty=False, head unchanged.
    """
    _seed_codex_task(conductor, workspace=git_workspace)
    codex = FakeCodex(response="I would do X but did nothing")
    d = ConductorDispatcher(conductor, codex, "market_agent")
    result = d.dispatch_next()

    assert result.outcome is DispatchOutcome.BLOCKED
    assert "no commits" in (result.error or "")


# ============================================================
# Audit 2026-06-16 -- workspace allowlist + crash/HEAD hardening
# ============================================================


def test_dispatch_blocks_workspace_outside_allowlist(
    conductor, git_workspace, tmp_path
):
    """A1: a task whose resolved workspace is outside the allowlist is BLOCKED
    and Codex is NEVER fired (the hard wall against Codex-on-prod escape)."""
    allowed = tmp_path / "allowed_root"
    allowed.mkdir()
    _seed_codex_task(conductor, workspace=git_workspace)  # NOT under allowed
    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(
        conductor, codex, "market_agent",
        allowed_workspace_roots=[allowed],
    )

    result = d.dispatch_next()

    assert result.outcome is DispatchOutcome.BLOCKED
    assert codex.calls == []  # Codex must not run outside the allowlist
    assert conductor.list_tasks()[0].status is TaskStatus.BLOCKED


def test_dispatch_allows_workspace_inside_allowlist(conductor, git_workspace):
    """A1 counterpart: an allowlisted workspace dispatches normally."""
    _seed_codex_task(conductor, workspace=git_workspace)
    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(
        conductor, codex, "market_agent",
        allowed_workspace_roots=[git_workspace.parent],
    )

    result = d.dispatch_next()

    # Codex ran -> the allowlist permitted dispatch (outcome is BLOCKED only
    # because FakeCodex makes no commit, which is the no-commits path).
    assert len(codex.calls) == 1
    assert result.outcome is DispatchOutcome.BLOCKED


def test_dispatch_exception_marks_blocked_not_stuck_in_progress(
    conductor, git_workspace
):
    """D1 (#5): a crash mid-dispatch must drop the task to BLOCKED, never leave
    it wedged IN_PROGRESS forever."""
    class RaisingCodex(FakeCodex):
        def ask(self, *a, **k):
            raise RuntimeError("boom")

    _seed_codex_task(conductor, workspace=git_workspace)
    d = ConductorDispatcher(conductor, RaisingCodex(), "market_agent")

    result = d.dispatch_next()

    assert result.outcome is DispatchOutcome.BLOCKED
    task = conductor.list_tasks()[0]
    assert task.status is TaskStatus.BLOCKED  # NOT stuck IN_PROGRESS


def test_dispatch_blocks_when_head_unreadable_predispatch(
    conductor, git_workspace, monkeypatch
):
    """D2 (#19): if HEAD can't be read pre-dispatch there's no commit baseline,
    so refuse rather than dispatch Codex blind (and risk a wrong auto-commit)."""
    import agent_core.conductor.dispatcher as disp
    monkeypatch.setattr(disp, "get_workspace_head", lambda ws: None)
    _seed_codex_task(conductor, workspace=git_workspace)
    codex = FakeCodex(response="ok")
    d = ConductorDispatcher(conductor, codex, "market_agent")

    result = d.dispatch_next()

    assert result.outcome is DispatchOutcome.BLOCKED
    assert codex.calls == []  # never dispatched without a baseline


# ---------------------------------------------------------------------------
# Watchdog lease wiring (2026-06-30: watchdog killed the process mid-dispatch)
# ---------------------------------------------------------------------------

def test_codex_timeout_sec_property_exposes_hard_timeout(conductor):
    d = ConductorDispatcher(
        conductor, FakeCodex(response="ok"), "market_agent",
        codex_timeout_sec=1234.0,
    )
    assert d.codex_timeout_sec == 1234.0


def test_phase17_runs_dispatch_under_an_active_watchdog_lease():
    """The tick phase must lease the watchdog allowance BEFORE calling
    dispatch_next and release it after -- otherwise a >300s Codex build gets
    force-restarted mid-flight (the 2026-06-30 Brick-0 kill)."""
    import time as _time
    from agent_core.homeostasis.core import HomeostasisCore

    core = HomeostasisCore.__new__(HomeostasisCore)
    core._running = True
    core._watchdog_stall_sec = 300.0
    core._external_op_deadline = None
    core._external_op_label = ""
    core._external_op_logged = False
    # Simulate the exact incident geometry: the tick heartbeat is already
    # stale past the 300s deadline while the dispatch is still running.
    core._last_tick_monotonic = _time.monotonic() - 999

    seen = {}

    class RecordingDispatcher:
        project = "market_agent"
        codex_timeout_sec = 1800.0

        def should_dispatch(self):
            return True

        def dispatch_next(self):
            seen["deadline_during"] = core._external_op_deadline
            seen["would_trip_during"] = core._watchdog_should_trip()
            return DispatchResult(
                outcome=DispatchOutcome.SKIPPED, project=self.project,
            )

    core._conductor_dispatchers = [RecordingDispatcher()]
    core._dispatch_conductor_tasks()

    assert seen["deadline_during"] is not None  # lease was live during the call
    assert seen["would_trip_during"] is False   # watchdog held fire
    assert core._external_op_deadline is None   # and released afterwards
    # Release restamps the heartbeat, so the tick TAIL after dispatch is NOT
    # instantly tripped on the now-stale clock (2026-07-07 residual). Normal
    # tripping returns only if the tail itself then stalls past the deadline.
    assert core._watchdog_should_trip() is False
    core._last_tick_monotonic = _time.monotonic() - 999
    assert core._watchdog_should_trip() is True


def test_first_dispatch_sweeps_orphaned_in_progress_and_dispatches_it(
    conductor, git_workspace
):
    """Crash mid-dispatch (2026-06-30 watchdog os._exit) strands the task
    IN_PROGRESS. The first dispatch attempt of a fresh process must requeue
    the orphan and may then dispatch it immediately in the same call."""
    task = _seed_codex_task(conductor, workspace=git_workspace)
    conductor.mark_in_progress(task.task_id, Assignee.CODEX)

    class CommittingCodex:
        _call_timestamps: deque = deque()

        def ask(self, prompt, source="unknown", context=None,
                cwd=None, timeout_s=None, impl_mode=False):
            (cwd / "new.py").write_text("# new")
            subprocess.run(["git", "add", "-A"], cwd=cwd, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "from codex"],
                cwd=cwd, check=True,
            )
            return "implemented and committed"

    d = ConductorDispatcher(conductor, CommittingCodex(), "market_agent")
    result = d.dispatch_next()

    assert result.outcome is DispatchOutcome.DONE
    assert result.task_id == task.task_id
    refreshed = conductor.list_tasks(project="market_agent")[0]
    assert refreshed.artifacts["stale_requeue_count"] == 1


def test_sweep_runs_once_per_dispatcher_lifetime(conductor, git_workspace):
    task = _seed_codex_task(conductor, workspace=git_workspace)
    conductor.mark_in_progress(task.task_id, Assignee.CODEX)

    d = ConductorDispatcher(conductor, FakeCodex(response=None), "market_agent")
    d.dispatch_next()  # sweep + dispatch attempt (codex None -> blocked)
    conductor.mark_in_progress(task.task_id, Assignee.CODEX)
    result = d.dispatch_next()

    # Second call must NOT sweep again: the task we just put IN_PROGRESS
    # stays untouched and there is nothing PENDING to dispatch.
    assert result.outcome is DispatchOutcome.SKIPPED
    refreshed = conductor.list_tasks(project="market_agent")[0]
    assert refreshed.status is TaskStatus.IN_PROGRESS
    assert refreshed.artifacts["stale_requeue_count"] == 1
