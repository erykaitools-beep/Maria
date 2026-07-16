"""/drill_undo: proves the undo EXECUTION path end to end against the FS sandbox
(no live OpenClaw), through register_telegram_commands. tmp_path-jailed.

Mirrors /drill_fs_write: a self-contained on-demand proof the operator can run to
see the inverse machinery actually restore and remove files before the live rung.
"""

from types import SimpleNamespace

from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands as _register,
)


class FakeBridge:
    def __init__(self):
        self.handlers = {}

    def register_command(self, command, handler):
        self.handlers[command] = handler


def _harness(tmp_path, monkeypatch):
    sandbox = tmp_path / "fs_sandbox"
    # Jail the drill to tmp so it never writes the real meta_data/fs_sandbox/.
    monkeypatch.setattr(
        "agent_core.hands.sandbox_writer.default_sandbox_root",
        lambda base: str(sandbox),
    )
    bridge = FakeBridge()
    _register(bridge, SimpleNamespace())  # drill is self-contained; ctx unused
    return bridge, sandbox


def test_drill_undo_registered(tmp_path, monkeypatch):
    bridge, _ = _harness(tmp_path, monkeypatch)
    assert "drill_undo" in bridge.handlers


def test_drill_undo_proves_restore_and_remove(tmp_path, monkeypatch):
    bridge, sandbox = _harness(tmp_path, monkeypatch)
    out = bridge.handlers["drill_undo"]("")
    assert "RESTORE: OK" in out
    assert "REMOVE:  OK" in out
    assert "UNDONE=True" in out
    # the drill cleans up after itself (no standing artifacts)
    assert not (sandbox / "drill_restore.txt").exists()
    assert not (sandbox / "drill_new file.txt").exists()


def test_drill_undo_does_not_leak_execute_flag(tmp_path, monkeypatch):
    import os
    monkeypatch.delenv("EFFECTOR_UNDO_EXECUTE_ENABLED", raising=False)
    bridge, _ = _harness(tmp_path, monkeypatch)
    bridge.handlers["drill_undo"]("")
    # the run flips the execute flag ON then restores it -> must be gone after.
    assert os.environ.get("EFFECTOR_UNDO_EXECUTE_ENABLED") is None
