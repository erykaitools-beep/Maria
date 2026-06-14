"""
Conductor — autonomous Codex dispatcher.

Pops next PENDING task with assignee=codex via Conductor.get_autonomous_next,
fires CodexClient against the workspace specified in task.artifacts, and
marks DONE/BLOCKED based on whether new commits landed.

Done detection model: git HEAD diff. Pre-dispatch the dispatcher records the
workspace's current HEAD SHA. Post-dispatch it re-reads HEAD. If HEAD moved,
the dispatched task is marked DONE with the new commit SHAs in artifacts.
If HEAD did not move, the task is marked BLOCKED — Codex returned a response
but never committed (so either it proposed work without executing, hit a
sandbox restriction, or the work was incomplete).

Rate-limit handling: when CodexClient returns None and the rate-limit window
is full, the task is bumped back to PENDING (not BLOCKED) — the dispatcher
will retry on a future tick. Other None returns (CLI missing, subprocess
error, parse failure) → BLOCKED so the operator can investigate.

This module is the only autonomous code path that invokes CodexClient.ask
for the purpose of "execute this brief". Q&A uses (creative, web_source,
code_agent) all stay one-shot, no task-queue interaction.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

from agent_core.conductor.conductor import Conductor
from agent_core.conductor.task_model import Assignee, Task

logger = logging.getLogger(__name__)


# Minimum seconds between dispatch attempts. Set high enough that one Codex
# call (60-300s typical) plus its commit settling time has elapsed before
# the next dispatch fires. Operator can tighten via constructor if needed.
DEFAULT_DISPATCH_INTERVAL_SEC = 600.0

# Truncate Codex's full response when persisting to task.artifacts so we
# don't bloat the queue JSONL. The full text still lives in
# meta_data/codex_interactions.jsonl (written by CodexClient).
RESPONSE_ARTIFACT_LIMIT = 5000

# Subprocess timeout for the Codex ``exec`` call. Implementation briefs
# (T-MA-001/002/003 references) ran 6 minutes typical, up to 30 minutes
# tail. CodexClient's default of 120 s is suitable for Q&A but kills any
# real implementation work mid-run. 1800 s = 30 min ceiling.
DEFAULT_CODEX_TIMEOUT_SEC = 1800.0


class DispatchOutcome(Enum):
    """Result of a single dispatch attempt."""

    DONE = "done"                # Codex committed; task moved to DONE
    BLOCKED = "blocked"          # Codex responded but no commits, or errored
    SKIPPED = "skipped"          # No PENDING task to dispatch
    RATE_LIMITED = "rate_limited"  # Hit codex_client rate window; task re-queued
    THROTTLED = "throttled"      # Dispatch interval not yet elapsed


@dataclass(frozen=True)
class DispatchResult:
    outcome: DispatchOutcome
    task_id: Optional[str] = None
    project: Optional[str] = None
    commits: List[str] = field(default_factory=list)
    response_summary: str = ""
    duration_sec: float = 0.0
    error: Optional[str] = None


def get_workspace_head(workspace: Path) -> Optional[str]:
    """Current HEAD SHA of the workspace's git repo, or None on any failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("[Dispatcher] git HEAD read failed: %s", exc)
    return None


def get_commits_between(
    workspace: Path, base_sha: str, head_sha: str
) -> List[str]:
    """List of commit SHAs from base..head (exclusive base, inclusive head).

    Returns [] when bases match, or on git failure. Order is newest first
    (git log default).
    """
    if base_sha == head_sha:
        return []
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H", f"{base_sha}..{head_sha}"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return [s for s in result.stdout.strip().split("\n") if s]
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("[Dispatcher] git log read failed: %s", exc)
    return []


def get_workspace_dirty(workspace: Path) -> bool:
    """True when workspace has uncommitted changes (tracked or untracked).

    Used both pre-dispatch (refuse if operator left work-in-progress that
    the auto-commit safeguard could otherwise sweep into a "from codex:"
    commit) and post-dispatch (detect that Codex implemented changes but
    did not commit them — happens when Codex's response is "Implemented
    in the working tree" without `git commit`).

    On git failure we return False, mirroring get_workspace_head: better
    to proceed with the dispatch than block on a transient git error.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return bool(result.stdout.strip())
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("[Dispatcher] git status read failed: %s", exc)
    return False


def auto_commit_codex_work(
    workspace: Path, task_id: str, title: str
) -> Optional[str]:
    """Stage all changes and commit with ``from codex: {task_id} - {title}``.

    Returns the new HEAD SHA on success, None on any git failure. The
    pre-dispatch cleanliness check guarantees everything being committed
    here came from this Codex run, so a blanket ``git add -A`` is safe.
    """
    message = f"from codex: {task_id} - {title}"
    try:
        add = subprocess.run(
            ["git", "add", "-A"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if add.returncode != 0:
            logger.warning(
                "[Dispatcher] auto-commit git add failed: %s",
                add.stderr.strip(),
            )
            return None
        commit = subprocess.run(
            ["git", "commit", "-q", "-m", message],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if commit.returncode != 0:
            logger.warning(
                "[Dispatcher] auto-commit git commit failed: %s",
                commit.stderr.strip(),
            )
            return None
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("[Dispatcher] auto-commit subprocess error: %s", exc)
        return None
    return get_workspace_head(workspace)


class ConductorDispatcher:
    """Pops next autonomous task and dispatches it to Codex CLI.

    One dispatcher per project. Use ``dispatch_next`` to run one attempt;
    callers (homeostasis tick) gate via ``should_dispatch`` to throttle.
    """

    def __init__(
        self,
        conductor: Conductor,
        codex_client: object,  # CodexClient — duck-typed for test isolation
        project: str,
        notify_fn: Optional[Callable[[str], None]] = None,
        interval_sec: float = DEFAULT_DISPATCH_INTERVAL_SEC,
        codex_timeout_sec: float = DEFAULT_CODEX_TIMEOUT_SEC,
        clock_fn: Callable[[], float] = time.time,
    ):
        self._conductor = conductor
        self._codex = codex_client
        self._project = project
        self._notify = notify_fn or (lambda _msg: None)
        self._interval = interval_sec
        self._codex_timeout = codex_timeout_sec
        self._clock = clock_fn
        self._last_dispatch_ts: float = 0.0

    @property
    def project(self) -> str:
        return self._project

    def should_dispatch(self, now: Optional[float] = None) -> bool:
        """True when at least ``interval_sec`` has elapsed since last attempt."""
        now = self._clock() if now is None else now
        return (now - self._last_dispatch_ts) >= self._interval

    def dispatch_next(self, now: Optional[float] = None) -> DispatchResult:
        """Single dispatch attempt. Updates ``_last_dispatch_ts`` unconditionally."""
        now = self._clock() if now is None else now
        self._last_dispatch_ts = now

        task = self._conductor.get_autonomous_next(self._project)
        if task is None:
            return DispatchResult(
                outcome=DispatchOutcome.SKIPPED,
                project=self._project,
                response_summary="no pending task",
            )

        workspace_path = self._resolve_workspace(task)
        if workspace_path is None:
            # Already marked BLOCKED inside _resolve_workspace
            return DispatchResult(
                outcome=DispatchOutcome.BLOCKED,
                task_id=task.task_id,
                project=task.project,
                error="workspace_path missing or invalid",
                response_summary="workspace_path missing or invalid",
            )

        # Pre-dispatch cleanliness check. Auto-commit safeguard requires
        # an empty diff baseline so that "git add -A" after Codex cannot
        # sweep operator's in-progress files into a "from codex:" commit.
        if get_workspace_dirty(workspace_path):
            return self._handle_workspace_dirty(task)

        head_before = get_workspace_head(workspace_path)
        self._conductor.mark_in_progress(task.task_id, Assignee.CODEX)

        self._notify(
            f"[Conductor] Dispatching {task.task_id} -> Codex\n"
            f"Project: {task.project}\n"
            f"Title: {task.title}\n"
            f"Workspace: {workspace_path}"
        )

        start = time.time()
        response = self._codex.ask(
            task.description,
            source="conductor_dispatcher",
            context={"task_id": task.task_id, "project": task.project},
            cwd=workspace_path,
            timeout_s=self._codex_timeout,
            impl_mode=True,
        )
        duration = time.time() - start

        if response is None:
            return self._handle_codex_none(task, duration)

        head_after = get_workspace_head(workspace_path)
        commits: List[str] = []
        if head_before and head_after and head_before != head_after:
            commits = get_commits_between(workspace_path, head_before, head_after)

        if commits:
            return self._handle_done(task, response, commits, head_before,
                                     head_after, duration)
        # No HEAD movement. Either Codex implemented + left dirty tree
        # ("Implemented in the working tree" pattern) → auto-commit, or
        # nothing actually happened → BLOCKED.
        if get_workspace_dirty(workspace_path):
            return self._handle_auto_commit(
                task, response, head_before, workspace_path, duration,
            )
        return self._handle_no_commits(task, response, duration)

    # ── internals ───────────────────────────────────────────────────

    def _resolve_workspace(self, task: Task) -> Optional[Path]:
        raw = task.artifacts.get("workspace_path") if task.artifacts else None
        if not raw:
            self._conductor.mark_blocked(
                task.task_id, "missing workspace_path in artifacts"
            )
            self._notify(
                f"[Conductor] {task.task_id} BLOCKED (no workspace_path)"
            )
            return None
        try:
            path = Path(str(raw)).expanduser().resolve()
        except (TypeError, OSError) as exc:
            self._conductor.mark_blocked(
                task.task_id, f"invalid workspace_path: {exc}"
            )
            self._notify(
                f"[Conductor] {task.task_id} BLOCKED (invalid workspace_path)"
            )
            return None
        if not path.exists():
            self._conductor.mark_blocked(
                task.task_id, f"workspace {path} not found"
            )
            self._notify(
                f"[Conductor] {task.task_id} BLOCKED (workspace not found)"
            )
            return None
        return path

    def _handle_codex_none(
        self, task: Task, duration: float
    ) -> DispatchResult:
        if self._is_rate_limited():
            # Re-queue so we try again on the next tick after the window clears.
            self._conductor.mark_pending(task.task_id)
            self._notify(
                f"[Conductor] {task.task_id} rate-limited, re-queued"
            )
            return DispatchResult(
                outcome=DispatchOutcome.RATE_LIMITED,
                task_id=task.task_id,
                project=task.project,
                duration_sec=duration,
                response_summary="rate limited, requeued",
            )
        self._conductor.mark_blocked(task.task_id, "codex returned None")
        self._notify(
            f"[Conductor] {task.task_id} BLOCKED (Codex returned None)"
        )
        return DispatchResult(
            outcome=DispatchOutcome.BLOCKED,
            task_id=task.task_id,
            project=task.project,
            duration_sec=duration,
            response_summary="codex returned None",
            error="codex returned None",
        )

    def _is_rate_limited(self) -> bool:
        # CodexClient stores ``_call_timestamps`` (deque) and
        # ``MAX_CALLS_PER_HOUR`` is a module constant on the import. Use
        # getattr for resilience if internals shift.
        from agent_core.llm.codex_client import MAX_CALLS_PER_HOUR
        stamps = getattr(self._codex, "_call_timestamps", None)
        if stamps is None:
            return False
        return len(stamps) >= MAX_CALLS_PER_HOUR

    def _handle_done(
        self,
        task: Task,
        response: str,
        commits: List[str],
        head_before: Optional[str],
        head_after: Optional[str],
        duration: float,
    ) -> DispatchResult:
        artifacts = {
            "codex_response": response[:RESPONSE_ARTIFACT_LIMIT],
            "commits": commits,
            "head_before": head_before,
            "head_after": head_after,
            "duration_sec": round(duration, 1),
        }
        self._conductor.mark_done(
            task.task_id,
            artifacts=artifacts,
            notes=f"Codex dispatched, {len(commits)} commit(s)",
        )
        self._notify(
            f"[Conductor] {task.task_id} DONE\n"
            f"Commits: {len(commits)}\n"
            f"First SHA: {commits[0][:12] if commits else 'n/a'}\n"
            f"Duration: {duration:.0f}s"
        )
        return DispatchResult(
            outcome=DispatchOutcome.DONE,
            task_id=task.task_id,
            project=task.project,
            commits=commits,
            response_summary=response[:300],
            duration_sec=duration,
        )

    def _handle_no_commits(
        self, task: Task, response: str, duration: float
    ) -> DispatchResult:
        reason = (
            "Codex returned response but no commits and clean tree — "
            "work may be partial, proposed-only, or sandbox-blocked"
        )
        self._conductor.mark_blocked(task.task_id, reason)
        self._notify(
            f"[Conductor] {task.task_id} BLOCKED (no commits)\n"
            f"Codex response head: {response[:200]}"
        )
        return DispatchResult(
            outcome=DispatchOutcome.BLOCKED,
            task_id=task.task_id,
            project=task.project,
            duration_sec=duration,
            response_summary=response[:300],
            error="no commits",
        )

    def _handle_workspace_dirty(self, task: Task) -> DispatchResult:
        """Pre-dispatch refusal when workspace already has uncommitted work."""
        reason = (
            "workspace not clean — operator must commit or stash "
            "before autonomous dispatch (auto-commit safeguard)"
        )
        self._conductor.mark_blocked(task.task_id, reason)
        self._notify(
            f"[Conductor] {task.task_id} BLOCKED (workspace dirty)\n"
            f"Reason: {reason}"
        )
        return DispatchResult(
            outcome=DispatchOutcome.BLOCKED,
            task_id=task.task_id,
            project=task.project,
            error="workspace dirty pre-dispatch",
            response_summary=reason,
        )

    def _handle_auto_commit(
        self,
        task: Task,
        response: str,
        head_before: Optional[str],
        workspace: Path,
        duration: float,
    ) -> DispatchResult:
        """Codex left a dirty tree on success — commit it on Codex's behalf.

        Pre-dispatch cleanliness guarantees everything in this commit was
        produced by this dispatch, so a blanket ``git add -A`` is safe.
        """
        new_sha = auto_commit_codex_work(workspace, task.task_id, task.title)
        if new_sha is None:
            reason = "codex left dirty tree, auto-commit failed"
            self._conductor.mark_blocked(task.task_id, reason)
            self._notify(
                f"[Conductor] {task.task_id} BLOCKED ({reason})"
            )
            return DispatchResult(
                outcome=DispatchOutcome.BLOCKED,
                task_id=task.task_id,
                project=task.project,
                duration_sec=duration,
                response_summary=response[:300],
                error="auto-commit failed",
            )
        artifacts = {
            "codex_response": response[:RESPONSE_ARTIFACT_LIMIT],
            "commits": [new_sha],
            "head_before": head_before,
            "head_after": new_sha,
            "duration_sec": round(duration, 1),
            "auto_committed": True,
        }
        self._conductor.mark_done(
            task.task_id,
            artifacts=artifacts,
            notes="Codex dispatched, dirty tree auto-committed",
        )
        self._notify(
            f"[Conductor] {task.task_id} DONE (auto-committed)\n"
            f"Commit: {new_sha[:12]}\n"
            f"Duration: {duration:.0f}s"
        )
        return DispatchResult(
            outcome=DispatchOutcome.DONE,
            task_id=task.task_id,
            project=task.project,
            commits=[new_sha],
            response_summary=response[:300],
            duration_sec=duration,
        )


__all__ = [
    "ConductorDispatcher",
    "DispatchOutcome",
    "DispatchResult",
    "DEFAULT_DISPATCH_INTERVAL_SEC",
    "auto_commit_codex_work",
    "get_commits_between",
    "get_workspace_dirty",
    "get_workspace_head",
]
