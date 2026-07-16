"""Isolated remote fixes: dispatch Codex into a throwaway git worktree.

Eryk wants to react from work -- not just diagnose (read-only /claude, /codex)
but actually get a fix WRITTEN -- without endangering the live daemon. So /fix
runs Codex (workspace-write) in a git worktree branched off the current HEAD,
OUTSIDE the live repo tree. The running daemon's code is never touched; Codex's
changes land on a fix/ branch. The diff is sent to Telegram for review. Applying
to the live branch (+ restart) stays a deliberate, operator-gated step
(in-session, or /fix_apply only when the live tree is clean) -- never automatic.

Safety model:
  * Worktree lives OUTSIDE the repo (~/maria-fix-worktrees) so the daemon never
    scans it and a session in the main tree is undisturbed.
  * Codex runs --sandbox workspace-write (writes within its cwd, no network/exec
    beyond the sandbox) and never on the main working tree.
  * One fix at a time (a module lock): the codex response file is shared, and
    serial worktrees keep the branch list legible.
  * The live branch is modified ONLY by an explicit apply, and only when the
    working tree is clean (fail-closed otherwise -> apply in-session).
  * Branch names are sanitised; worktrees are cleaned up on every exit path.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Worktrees live outside the repo so the daemon never scans them.
_WORKTREE_ROOT = Path.home() / "maria-fix-worktrees"
_BRANCH_PREFIX = "fix/"
_DEFAULT_CODEX_TIMEOUT = 900  # impl tasks can run minutes
_MAX_DIFF_INLINE = 3000       # chars; larger diffs go as a .patch file

# Only one fix may run at a time (shared codex response file + branch hygiene).
_lock = threading.Lock()


def _git(args: List[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess:
    # errors="replace": a diff over a non-UTF8 file (latin-2 Polish, binary) must
    # not crash decoding -- substitute rather than raise UnicodeDecodeError.
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )


def _slug(task: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (task or "").lower()).strip("-")
    return (s[:30].strip("-") or "fix")


def is_busy() -> bool:
    return _lock.locked()


def working_tree_clean(repo_root: Optional[Path] = None) -> bool:
    """True when the live working tree has no staged/unstaged changes."""
    repo_root = repo_root or _REPO_ROOT
    try:
        r = _git(["status", "--porcelain"], repo_root)
    except Exception:
        return False
    return r.returncode == 0 and not r.stdout.strip()


def list_fix_branches(repo_root: Optional[Path] = None) -> List[str]:
    repo_root = repo_root or _REPO_ROOT
    try:
        r = _git(["for-each-ref", "--format=%(refname:short)",
                  f"refs/heads/{_BRANCH_PREFIX}*"], repo_root)
    except Exception:
        return []
    if r.returncode != 0:
        return []
    return [b for b in r.stdout.split() if b.startswith(_BRANCH_PREFIX)]


def _remove_worktree(wt_path: Path, repo_root: Path) -> None:
    try:
        _git(["worktree", "remove", "--force", str(wt_path)], repo_root)
    except Exception as e:
        logger.warning("[remote_fix] worktree remove failed: %s", e)
    # Best-effort: prune stale admin entries.
    try:
        _git(["worktree", "prune"], repo_root)
    except Exception:
        pass


def create_fix(
    task: str,
    codex_client: Any,
    *,
    repo_root: Optional[Path] = None,
    timeout_s: int = _DEFAULT_CODEX_TIMEOUT,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Run Codex in an isolated worktree and capture its diff on a fix/ branch.

    Returns a dict: {ok, reason?, branch?, stat?, diff?, summary?}. On ok=True the
    branch holds the committed change (the worktree is removed); on ok=False any
    partial worktree/branch is cleaned up. Serialised: returns ok=False/busy if a
    fix is already running.
    """
    if not _lock.acquire(blocking=False):
        return {"ok": False, "reason": "Inny /fix wlasnie trwa - poczekaj."}
    wt_path: Optional[Path] = None
    branch: Optional[str] = None
    success = False
    pre_exists = False  # did this branch already exist (someone else's)?
    repo_root = repo_root or _REPO_ROOT  # resolve at call time (test-overridable)
    try:
        if not (task or "").strip():
            return {"ok": False, "reason": "Pusty opis zadania."}
        if codex_client is None or not getattr(codex_client, "is_available", lambda: False)():
            return {"ok": False, "reason": "Codex CLI niedostepny."}

        head = _git(["rev-parse", "HEAD"], repo_root)
        if head.returncode != 0:
            return {"ok": False, "reason": "Nie moge odczytac HEAD repo."}
        base_sha = head.stdout.strip()

        ts = int(now if now is not None else time.time())
        branch = f"{_BRANCH_PREFIX}{_slug(task)}-{ts}"
        _WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
        wt_path = _WORKTREE_ROOT / f"{_slug(task)}-{ts}"
        # A leftover dir from a crashed run makes `worktree add` fail AFTER git
        # already created the branch -> clear it first (cleanup handles the rest).
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)
        # If the branch already exists (e.g. a prior /fix the same second), the
        # add will fail -- and we must NOT delete that pre-existing branch in
        # cleanup. Record ownership so finally only removes a branch WE created.
        pre_exists = _git(["rev-parse", "--verify", "--quiet",
                           f"refs/heads/{branch}"], repo_root).returncode == 0

        add = _git(["worktree", "add", "-b", branch, str(wt_path), base_sha],
                   repo_root, timeout=120)
        if add.returncode != 0:
            # git may have created `branch` even though add failed -> finally
            # (success is False) deletes it.
            return {"ok": False,
                    "reason": f"worktree add nieudane: {add.stderr.strip()[:200]}"}

        brief = (
            f"Zadanie naprawcze w TYM repozytorium (jestes w izolowanym worktree, "
            f"smialo edytuj pliki): {task.strip()}\n\n"
            "Zasady: zrob MINIMALNA, konkretna zmiane. Jesli sensowne, dopisz/popraw "
            "test. Trzymaj sie konwencji repo (BEZ emoji w kodzie, docstrings po "
            "angielsku, type hints). Nie pushuj i nie zmieniaj historii. Na koncu "
            "krotko podsumuj co zmieniles i dlaczego."
        )
        # Per-call response file (inside the throwaway worktree) so a concurrent
        # CodexClient caller can't clobber this run's summary.
        summary = codex_client.ask(
            prompt=brief, source="telegram_fix",
            context={"task": task[:100], "branch": branch},
            cwd=wt_path, impl_mode=True, timeout_s=timeout_s,
            out_file=wt_path / ".maria_fix_codex_response.txt",
        )

        # Stage everything (incl. new files) and diff vs the base. This captures
        # changes whether Codex committed them or left them in the working tree.
        # The diff is operator-reviewed before any apply, so stray scratch files
        # Codex may leave are visible (not silently merged).
        _git(["add", "-A"], wt_path)
        d = _git(["diff", "--cached", base_sha], wt_path, timeout=120)
        diff = d.stdout if d.returncode == 0 else ""
        if not diff.strip():
            return {"ok": False,
                    "reason": "Codex nie wprowadzil zadnych zmian.",
                    "summary": (summary or "")[:1500]}

        stat = _git(["diff", "--cached", "--stat", base_sha], wt_path).stdout

        # Commit on the fix branch so it survives worktree removal. If Codex
        # already committed, there is nothing staged -> ignore that.
        _git(["commit", "-m", f"fix (remote /fix): {task.strip()[:72]}"], wt_path)
        _remove_worktree(wt_path, repo_root)  # branch keeps the commit
        success = True
        return {
            "ok": True, "branch": branch,
            "stat": stat.strip(), "diff": diff,
            "summary": (summary or "").strip()[:1500],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"Timeout (> {timeout_s}s)."}
    except Exception as e:
        logger.exception("[remote_fix] create_fix failed")
        return {"ok": False, "reason": f"Blad: {e}"}
    finally:
        # Cleanup on EVERY non-success path: worktree first (a branch checked out
        # in a worktree cannot be deleted), then the branch (git may have created
        # it even when add failed), then any leftover plain dir. Never leak into
        # the live repo (the lesson from the default-arg + timeout/exception bugs).
        if not success:
            if wt_path is not None and wt_path.exists():
                _remove_worktree(wt_path, repo_root)
            if branch is not None and not pre_exists:
                _git(["branch", "-D", branch], repo_root)
            if wt_path is not None and wt_path.exists():
                shutil.rmtree(wt_path, ignore_errors=True)
        _lock.release()


def apply_fix(branch: str, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Merge a fix/ branch into the current (live) branch -- ONLY if the working
    tree is clean. Fail-closed otherwise (apply in-session instead). The daemon
    keeps running its loaded code until the operator restarts."""
    repo_root = repo_root or _REPO_ROOT
    branch = (branch or "").strip()
    if not branch.startswith(_BRANCH_PREFIX):
        return {"ok": False, "reason": f"To nie jest galaz fix/: {branch}"}
    if branch not in list_fix_branches(repo_root):
        return {"ok": False, "reason": f"Nie znam galezi: {branch}"}
    if not working_tree_clean(repo_root):
        return {"ok": False, "reason": (
            "Drzewo robocze jest brudne - nie scalam automatycznie. "
            "Zastosuj w sesji (we dwoje) albo gdy drzewo bedzie czyste.")}
    try:
        cur = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root).stdout.strip()
        if cur == "HEAD":  # detached -> a merge would create an orphan commit
            return {"ok": False, "reason": (
                "Repo w stanie detached HEAD - nie scalam. Przelacz na galaz docelowa.")}
        if cur.startswith(_BRANCH_PREFIX):
            return {"ok": False, "reason": (
                f"Jestes na galezi {cur} - przelacz na galaz docelowa przed scalaniem.")}
        m = _git(["merge", "--no-ff", "-m", f"merge {branch}", branch], repo_root,
                 timeout=120)
        if m.returncode != 0:
            _git(["merge", "--abort"], repo_root)
            return {"ok": False,
                    "reason": f"Merge nieudany (przerwany): {m.stderr.strip()[:200]}"}
        return {"ok": True, "branch": branch, "into": cur,
                "note": "Scalono. Zrestartuj Marie, by zmiana ozyla."}
    except Exception as e:
        logger.exception("[remote_fix] apply_fix failed")
        return {"ok": False, "reason": f"Blad: {e}"}


def drop_fix(branch: str, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Delete a fix/ branch (and any stray worktree)."""
    repo_root = repo_root or _REPO_ROOT
    branch = (branch or "").strip()
    if not branch.startswith(_BRANCH_PREFIX):
        return {"ok": False, "reason": f"To nie jest galaz fix/: {branch}"}
    try:
        r = _git(["branch", "-D", branch], repo_root)
        if r.returncode != 0:
            return {"ok": False, "reason": r.stderr.strip()[:200]}
        return {"ok": True, "branch": branch}
    except Exception as e:
        return {"ok": False, "reason": f"Blad: {e}"}
