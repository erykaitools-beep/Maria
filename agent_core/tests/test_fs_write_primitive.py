"""Tests for B2 part 1: the FS_WRITE effector primitive (the governed hand).

Covers the safe write mechanism + its K7/K10 governance, WITHOUT the autonomous
plan-gen or goal closure (those are B2 part 2). Nothing here triggers in the
live daemon: no plan generates FS_WRITE yet and it is not router-registered.
"""

from agent_core.hands.sandbox_writer import (
    sandbox_write,
    default_sandbox_root,
    default_outbox_root,
    MAX_WRITE_BYTES,
)
from agent_core.planner.planner_model import ActionType, create_plan
from agent_core.planner.action_executor import ActionExecutor
from agent_core.autonomy.action_class import classify_action, ActionClassification
from agent_core.routing.capability_spec import DEFAULT_CAPABILITY_SPECS
from agent_core.action_safety.safety_classifier import get_safety_profile
from agent_core.action_safety.safety_model import (
    SafetyMode, EffectType, Reversibility, StateSnapshot, ValidationResult,
)
from agent_core.action_safety.effect_validator import EffectValidator


# --------------------------------------------------------------------------
# sandbox_writer: the safe mechanism
# --------------------------------------------------------------------------

def test_write_success(tmp_path):
    r = sandbox_write("hello", "world", sandbox_root=str(tmp_path))
    assert r["success"] is True
    assert r["action"] == "fs_write"
    assert r["path"].endswith("hello.txt")
    assert (tmp_path / "hello.txt").read_text() == "world"
    assert r["size"] == 5


def test_write_appends_txt_and_sanitizes(tmp_path):
    r = sandbox_write("my report!! v2", "x", sandbox_root=str(tmp_path))
    assert r["success"] is True
    assert r["path"].endswith(".txt")
    # unsafe chars collapsed to single underscores
    assert "!!" not in r["path"]


def test_write_size_cap(tmp_path):
    big = "a" * (MAX_WRITE_BYTES + 1)
    r = sandbox_write("big", big, sandbox_root=str(tmp_path))
    assert r["success"] is False
    assert "exceeds max" in r["error"]
    assert not (tmp_path / "big.txt").exists()  # nothing written


def test_write_traversal_is_inert(tmp_path):
    # '/' is sanitized to '_', so a traversal-looking name stays inside.
    r = sandbox_write("../../etc/passwd", "x", sandbox_root=str(tmp_path))
    assert r["success"] is True
    written = tmp_path / "etc_passwd.txt"
    # resolved path must live under the sandbox root
    assert str(tmp_path.resolve()) in r["path"]


def test_write_rejects_symlink_target(tmp_path):
    sandbox = tmp_path / "sb"
    sandbox.mkdir()
    real = tmp_path / "real.txt"
    real.write_text("x")
    (sandbox / "link.txt").symlink_to(real)
    r = sandbox_write("link", "y", sandbox_root=str(sandbox))
    assert r["success"] is False
    assert "symlink" in r["error"]
    assert real.read_text() == "x"  # untouched


def test_default_sandbox_root():
    root = default_sandbox_root("/base")
    assert root == "/base/meta_data/fs_sandbox"


# --------------------------------------------------------------------------
# Rung 2 outbox: same engine + guards, new root, no-overwrite (no undo)
# --------------------------------------------------------------------------

def test_default_outbox_root():
    assert default_outbox_root("/base") == "/base/meta_data/maria_outbox"


def test_no_overwrite_refuses_existing(tmp_path):
    sandbox_write("note", "first", sandbox_root=str(tmp_path))
    r = sandbox_write("note", "second", sandbox_root=str(tmp_path), no_overwrite=True)
    assert r["success"] is False
    assert "no_overwrite" in r["error"]
    assert (tmp_path / "note.txt").read_text() == "first"  # original untouched


def test_no_overwrite_allows_new_file(tmp_path):
    r = sandbox_write("fresh", "hi", sandbox_root=str(tmp_path), no_overwrite=True)
    assert r["success"] is True
    assert (tmp_path / "fresh.txt").read_text() == "hi"


def test_outbox_write_keeps_all_guards(tmp_path):
    # The outbox is just a different root -> every sandbox guard still applies.
    outbox = tmp_path / "maria_outbox"
    # size cap
    assert sandbox_write("big", "a" * (MAX_WRITE_BYTES + 1),
                         sandbox_root=str(outbox), no_overwrite=True)["success"] is False
    # traversal inert + contained under the outbox root
    r = sandbox_write("../../etc/passwd", "x", sandbox_root=str(outbox), no_overwrite=True)
    assert r["success"] is True
    assert str(outbox.resolve()) in r["path"]


# --------------------------------------------------------------------------
# ActionExecutor fallback: a FS_WRITE plan writes the file end-to-end
# --------------------------------------------------------------------------

def test_executor_fs_write(tmp_path):
    ex = ActionExecutor()  # no capability_router -> _ACTION_MAP fallback
    plan = create_plan(
        goal_id="goal-x",
        goal_description="first real action",
        action_type=ActionType.FS_WRITE,
        action_params={
            "filename": "maria_first_action",
            "content": "I acted on the world.",
            "sandbox_root": str(tmp_path),
        },
    )
    result = ex.execute(plan)
    assert result["success"] is True
    assert result["action"] == "fs_write"
    assert (tmp_path / "maria_first_action.txt").is_file()
    assert "duration_ms" in result  # execute() wraps timing


# --------------------------------------------------------------------------
# K7 governance: fs_write is GUARDED (not the RESTRICTED unknown default)
# --------------------------------------------------------------------------

def test_k7_fs_write_is_guarded():
    assert classify_action("fs_write") == ActionClassification.GUARDED


def test_k7_registry_agrees():
    # No new drift: action_class.py and capability_spec.py agree for fs_write.
    assert DEFAULT_CAPABILITY_SPECS["fs_write"].k7_classification == "guarded"


# --------------------------------------------------------------------------
# K10 governance: explicit profile (NOT the STAGED unknown default) + validator
# --------------------------------------------------------------------------

def test_k10_profile_explicit():
    prof = get_safety_profile("fs_write")
    # Crucial: an unknown type defaults to STAGED (won't execute). fs_write must
    # have a real profile so it actually runs + is audited.
    assert prof.safety_mode == SafetyMode.AUDIT_ONLY
    assert prof.effect_type == EffectType.FILESYSTEM
    assert prof.reversibility == Reversibility.REVERSIBLE
    assert prof.needs_before_snapshot and prof.needs_after_snapshot


def test_k10_validator_file_present_is_valid(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    v = EffectValidator()
    res, details = v.validate_effects(
        "fs_write", StateSnapshot(), StateSnapshot(),
        {"success": True, "path": str(f), "size": 1},
    )
    assert res == ValidationResult.VALID
    assert details["file_exists"] is True


def test_k10_validator_file_missing_on_success_is_unexpected(tmp_path):
    v = EffectValidator()
    res, details = v.validate_effects(
        "fs_write", StateSnapshot(), StateSnapshot(),
        {"success": True, "path": str(tmp_path / "ghost.txt"), "size": 0},
    )
    assert res == ValidationResult.UNEXPECTED
    assert details["file_missing_on_success"] is True
