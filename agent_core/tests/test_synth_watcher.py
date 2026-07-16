"""Tests for the autonomous-synthesis watcher message builder.

The Monday-legibility guarantee: a JUDGE STALL (timeout/parse error) must never
read like a content verdict. A stalled judge surfaces as 0/N supported, which
is indistinguishable from a fabricated synthesis unless the message says so.
"""
import importlib.util
from pathlib import Path

_WATCHER = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_autonomous_synthesis.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("synth_watcher", _WATCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_judge_stall_is_not_shown_as_content_verdict():
    mod = _load()
    latest = {
        "topic": "uczenie maszynowe",
        "file_id": "synthesis_um_20260615",
        "success": False,
        "reason": "unfaithful_to_sources",
        "exam": {"passed": False, "score": None},
    }
    fz = {"reason": "judge_failed", "supported": 0, "total": 6, "contradicted": 0}
    msg = mod.build_message(latest, fz, 1, 5)
    assert "judge_failed" in msg
    assert "NIE ZADZIALAL" in msg
    assert "INFRY" in msg
    # The operator must NOT be able to read "0/6" as a faithfulness verdict.
    assert "0/6" not in msg


def test_contradicted_shows_real_verdict():
    mod = _load()
    latest = {
        "topic": "m.a.r.i.a.",
        "file_id": "synthesis_maria_20260615",
        "success": False,
        "reason": "unfaithful_to_sources",
        "exam": {"passed": False, "score": None},
    }
    fz = {"reason": "contradicted", "supported": 3, "total": 6, "contradicted": 1}
    msg = mod.build_message(latest, fz, 1, 5)
    assert "wiernosc 3/6" in msg
    assert "sprzeczne 1" in msg
    assert "/retract" in msg
    assert "INFRY" not in msg


def test_ok_promoted_standard_message():
    mod = _load()
    latest = {
        "topic": "uczenie maszynowe",
        "file_id": "fid",
        "success": True,
        "promoted": True,
        "reason": None,
        "exam": {"passed": True, "score": 0.8},
    }
    fz = {"reason": "ok", "supported": 5, "total": 8, "contradicted": 0}
    msg = mod.build_message(latest, fz, 1, 5)
    assert "wiernosc 5/8" in msg
    assert "POPLYNELA SAMA" in msg
    assert "score=0.8" in msg


def test_no_judge_wired_omits_faith_line():
    mod = _load()
    latest = {"topic": "x", "file_id": "y", "exam": {}}
    msg = mod.build_message(latest, None, 1, 1)
    assert "wiernosc" not in msg
    assert "NIE ZADZIALAL" not in msg


def test_match_review_prefers_file_id_over_last_row():
    mod = _load()
    reviews = [
        {"file_id": "auto", "faithfulness": {"reason": "ok", "supported": 6, "total": 6}},
        {"file_id": "later_manual", "faithfulness": {"reason": "contradicted"}},
    ]
    # The autonomous run's row wins even though a manual run logged afterwards.
    assert mod._match_review(reviews, "auto")["file_id"] == "auto"
    # Missing id -> newest row (best-effort).
    assert mod._match_review(reviews, None)["file_id"] == "later_manual"
    # Empty log -> None (caller degrades to no faith line).
    assert mod._match_review([], "x") is None
