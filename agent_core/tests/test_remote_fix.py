"""Remote /fix: Codex in an isolated git worktree, change captured on a fix/ branch.

Eryk's 2026-06-22 ask -- react from work, actually get a fix WRITTEN -- without
endangering the live daemon. These tests run REAL git worktree mechanics against
a throwaway repo (the value is the git lifecycle), with a fake Codex that writes
into the worktree. Pins: isolation (live tree untouched), diff capture, branch
lifecycle, clean-tree-only apply, busy/no-op/unavailable guards.
"""

import subprocess
from pathlib import Path

import pytest

from agent_core.telegram import remote_fix


def _g(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _g(root, "init", "-q")
    _g(root, "config", "user.email", "t@example.com")
    _g(root, "config", "user.name", "Tester")
    _g(root, "config", "commit.gpgsign", "false")
    (root / "a.txt").write_text("hello\n")
    _g(root, "add", "-A")
    _g(root, "commit", "-q", "-m", "init")
    monkeypatch.setattr(remote_fix, "_REPO_ROOT", root)
    monkeypatch.setattr(remote_fix, "_WORKTREE_ROOT", tmp_path / "wts")
    return root


class FakeCodex:
    """Stands in for CodexClient: writes into the worktree (cwd) like impl_mode."""

    def __init__(self, write=True, summary="poprawione"):
        self._write = write
        self._summary = summary
        self.seen = {}

    def is_available(self):
        return True

    def ask(self, prompt, source=None, context=None, cwd=None,
            impl_mode=False, timeout_s=None, out_file=None):
        self.seen = {"cwd": cwd, "impl_mode": impl_mode, "source": source,
                     "out_file": out_file}
        if self._write:
            (Path(cwd) / "a.txt").write_text("hello\nfixed\n")
            (Path(cwd) / "new.txt").write_text("brand new\n")
        return self._summary


# --- create_fix -------------------------------------------------------------

def test_create_fix_captures_diff_on_branch(repo):
    codex = FakeCodex()
    res = remote_fix.create_fix("popraw a", codex, now=1000)
    assert res["ok"], res
    assert res["branch"].startswith("fix/")
    # Codex was dispatched workspace-write into a worktree (not the live tree).
    assert codex.seen["impl_mode"] is True
    assert Path(codex.seen["cwd"]) != repo
    # diff captured (modified + new file)
    assert "fixed" in res["diff"] and "new.txt" in res["diff"]
    # branch preserved, worktree removed
    assert res["branch"] in remote_fix.list_fix_branches(repo)
    assert not (repo.parent / "wts").exists() or not any((repo.parent / "wts").iterdir())


def test_live_working_tree_untouched_by_create(repo):
    remote_fix.create_fix("popraw a", FakeCodex(), now=1001)
    # The live repo's file is unchanged; change lives only on the fix/ branch.
    assert (repo / "a.txt").read_text() == "hello\n"
    assert remote_fix.working_tree_clean(repo)


def test_create_fix_no_changes_cleans_up(repo):
    res = remote_fix.create_fix("nic nie rob", FakeCodex(write=False), now=2)
    assert not res["ok"]
    assert "zmian" in res["reason"].lower()
    assert remote_fix.list_fix_branches(repo) == []  # branch deleted


def test_create_fix_codex_unavailable(repo):
    class Unavail(FakeCodex):
        def is_available(self):
            return False
    res = remote_fix.create_fix("x", Unavail(), now=3)
    assert not res["ok"] and "niedostepny" in res["reason"].lower()


def test_create_fix_empty_task(repo):
    assert not remote_fix.create_fix("   ", FakeCodex(), now=4)["ok"]


def test_busy_is_serialized(repo):
    assert remote_fix._lock.acquire(blocking=False)
    try:
        res = remote_fix.create_fix("x", FakeCodex(), now=5)
        assert not res["ok"] and "trwa" in res["reason"].lower()
    finally:
        remote_fix._lock.release()


# --- error-path cleanup: NEVER leak a branch into the live repo (review r3) -

class _RaisingCodex(FakeCodex):
    def __init__(self, exc):
        super().__init__()
        self._exc = exc

    def ask(self, *a, **k):
        raise self._exc


def test_codex_exception_cleans_branch(repo):
    res = remote_fix.create_fix("x", _RaisingCodex(RuntimeError("boom")), now=100)
    assert not res["ok"]
    assert remote_fix.list_fix_branches(repo) == []      # no leaked branch


def test_codex_timeout_cleans_branch(repo):
    exc = subprocess.TimeoutExpired(cmd="codex", timeout=900)
    res = remote_fix.create_fix("x", _RaisingCodex(exc), now=101)
    assert not res["ok"] and "timeout" in res["reason"].lower()
    assert remote_fix.list_fix_branches(repo) == []      # no leaked branch
    assert remote_fix._lock.acquire(blocking=False)       # lock was released
    remote_fix._lock.release()


def test_leftover_worktree_dir_collision_handled(repo, tmp_path):
    # A crashed prior run left the worktree dir behind -> create_fix clears it
    # and still succeeds, with no leaked branch/dir.
    wt_root = tmp_path / "wts"
    (wt_root / "popraw-200").mkdir(parents=True)
    (wt_root / "popraw-200" / "junk").write_text("stale")
    res = remote_fix.create_fix("popraw", FakeCodex(), now=200)
    assert res["ok"], res


def test_same_second_collision_preserves_first_branch(repo):
    first = remote_fix.create_fix("popraw", FakeCodex(), now=300)
    assert first["ok"]
    # Second call, same second -> same branch name -> worktree add fails, but the
    # FIRST run's branch must NOT be deleted by cleanup.
    second = remote_fix.create_fix("popraw", FakeCodex(), now=300)
    assert not second["ok"]
    assert first["branch"] in remote_fix.list_fix_branches(repo)


def test_nonutf8_diff_does_not_crash(repo):
    class NonUtf8Codex(FakeCodex):
        def ask(self, *a, **k):
            (Path(k["cwd"]) / "note.txt").write_bytes(b"zazo\xf3lc gesla jazn\n")
            return "dodalem note"
    res = remote_fix.create_fix("dodaj note", NonUtf8Codex(), now=400)
    assert res["ok"], res                                 # decoded with replace, no crash


def test_apply_detached_head_blocked(repo):
    res = remote_fix.create_fix("popraw", FakeCodex(), now=500)
    _g(repo, "checkout", "--detach")
    ap = remote_fix.apply_fix(res["branch"], repo)
    assert not ap["ok"] and "detached" in ap["reason"].lower()


# --- apply_fix --------------------------------------------------------------

def test_apply_fix_clean_tree_merges(repo):
    res = remote_fix.create_fix("popraw", FakeCodex(), now=6)
    ap = remote_fix.apply_fix(res["branch"], repo)
    assert ap["ok"], ap
    assert "fixed" in (repo / "a.txt").read_text()      # merged into live tree
    assert (repo / "new.txt").exists()


def test_apply_fix_dirty_tree_blocked(repo):
    res = remote_fix.create_fix("popraw", FakeCodex(), now=7)
    (repo / "dirty.txt").write_text("uncommitted")       # make live tree dirty
    ap = remote_fix.apply_fix(res["branch"], repo)
    assert not ap["ok"] and "brudne" in ap["reason"].lower()
    assert (repo / "a.txt").read_text() == "hello\n"     # nothing merged


def test_apply_rejects_non_fix_branch(repo):
    assert not remote_fix.apply_fix("main", repo)["ok"]
    assert not remote_fix.apply_fix("fix/does-not-exist-999", repo)["ok"]


# --- drop_fix ---------------------------------------------------------------

def test_drop_fix_removes_branch(repo):
    res = remote_fix.create_fix("popraw", FakeCodex(), now=8)
    d = remote_fix.drop_fix(res["branch"], repo)
    assert d["ok"]
    assert res["branch"] not in remote_fix.list_fix_branches(repo)


def test_drop_rejects_non_fix_branch(repo):
    assert not remote_fix.drop_fix("main", repo)["ok"]


# --- helpers ----------------------------------------------------------------

def test_slug_is_safe():
    s = remote_fix._slug("Popraw BŁĄD w pliku!!! /etc/passwd")
    assert s and all(c.isalnum() or c == "-" for c in s)
    assert "/" not in s and " " not in s
