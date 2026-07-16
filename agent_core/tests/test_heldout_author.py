"""Tests for the held-out bank author (Option C / C1, 2026-07-12).

The author freezes answer keys at ACQUISITION (fetch seam) for heldout-mode
goals only. Pinned here: row validation (the degenerate-row classes from the
red-team), idempotency on (file, source_hash), the per-fetch cap + deferral,
flag/mode gating, v3 newest-hash selection, and the B4 backfill path.
"""

import json
import time

import pytest

from maria_core.learning import exam_agent
from agent_core.teacher import heldout_author as ha


SOURCE = (
    "Cena zlota osiagnela w piatek rekordowe 2450 dolarow za uncje. "
    "Analitycy Silver Squeeze wskazuja, ze popyt na srebro rosnie. "
    "Narodowy Bank Polski zwiekszyl rezerwy o 130 ton. "
    "Kurs bitcoina wzrosl do 68 250 USD po decyzji Fed o stopach. "
) * 5  # > MIN_SOURCE_CHARS


@pytest.fixture(autouse=True)
def _clean_flag(monkeypatch):
    # .env leaks into tests via load_dotenv -- always start from a known state.
    monkeypatch.delenv("HELDOUT_BANK_AUTHOR_ENABLED", raising=False)


def _goal(mode="heldout"):
    from agent_core.goals.goal_model import create_goal, GoalType, GoalStatus
    meta = {"project_parent": "g-p", "source_kind": "market",
            "provenance_target_n": 12}
    if mode:
        meta["verification_mode"] = mode
    return create_goal(
        GoalType.USER, "projekt #3 child", 0.9, status=GoalStatus.ACTIVE,
        metadata=meta,
    )


def _write_body(tmp_path, file_id, body=SOURCE):
    (tmp_path / file_id).write_text(body, encoding="utf-8")


def _fake_author(rows):
    def author_fn(prompt):
        return json.dumps({"rows": rows})
    return author_fn


GOOD_ROWS = [
    {"q": "Ile dolarow za uncje osiagnela cena zlota?",
     "match": "numeric", "canonical": "2450", "tolerance": 10},
    {"q": "Jaki bank zwiekszyl rezerwy o 130 ton?",
     "match": "contains", "canonical": "Narodowy Bank Polski"},
    {"q": "Do jakiego poziomu wzrosl kurs bitcoina?",
     "match": "numeric", "canonical": "68250", "tolerance": 300},
]


# --- validate_row ------------------------------------------------------------


class TestValidateRow:
    def test_grounded_contains_ok(self):
        ok, why = ha.validate_row(GOOD_ROWS[1], SOURCE, "web_rss_x.txt")
        assert ok, why

    def test_ungrounded_canonical_rejected(self):
        row = {"q": "Kto wygral wybory w Peru w tym roku?", "match": "contains",
               "canonical": "Jan Kowalski"}
        ok, why = ha.validate_row(row, SOURCE, "web_rss_x.txt")
        assert not ok and "not grounded" in why

    def test_answer_leak_in_question_rejected(self):
        row = {"q": "Czy Narodowy Bank Polski zwiekszyl rezerwy?",
               "match": "contains", "canonical": "Narodowy Bank Polski"}
        ok, why = ha.validate_row(row, SOURCE, "web_rss_x.txt")
        assert not ok and "leaked" in why

    def test_short_canonical_rejected(self):
        row = {"q": "Jaki jest symbol zlota w ukladzie?", "match": "contains",
               "canonical": "za"}  # trivially matchable
        ok, why = ha.validate_row(row, SOURCE, "web_rss_x.txt")
        assert not ok and "too short" in why

    def test_file_stem_token_rejected(self):
        row = {"q": "O jakim kruszcu jest artykul?", "match": "contains",
               "canonical": "zloto"}
        ok, why = ha.validate_row(
            row, SOURCE + " zloto ", "web_rss_zloto_rekord.txt")
        assert not ok and "stem" in why

    def test_numeric_without_tolerance_rejected(self):
        row = {"q": "Ile ton rezerw dokupil NBP?", "match": "numeric",
               "canonical": "130"}
        ok, why = ha.validate_row(row, SOURCE, "web_rss_x.txt")
        assert not ok and "tolerance" in why

    def test_numeric_grounded_with_space_thousands(self):
        """The source spells '68 250' -- grounding must parse Polish formats
        (C10 matcher), not stop at the group separator."""
        row = {"q": "Do jakiego poziomu wzrosl kurs bitcoina w USD?",
               "match": "numeric", "canonical": "68250", "tolerance": 5}
        ok, why = ha.validate_row(row, SOURCE, "web_rss_x.txt")
        assert ok, why

    def test_numeric_ungrounded_rejected(self):
        row = {"q": "Ile wynosi kurs ethereum w USD?", "match": "numeric",
               "canonical": "999999", "tolerance": 10}
        ok, why = ha.validate_row(row, SOURCE, "web_rss_x.txt")
        assert not ok and "not grounded" in why

    def test_regex_rows_not_authorable(self):
        row = {"q": "Jaki wzorzec pasuje do tekstu artykulu?", "match": "regex",
               "pattern": ".*", "canonical": "cokolwiek"}
        ok, why = ha.validate_row(row, SOURCE, "web_rss_x.txt")
        assert not ok and "not allowed" in why


def test_min_rows_mirrors_exam_agent():
    assert ha.MIN_ROWS_PER_FILE == exam_agent.HELDOUT_MIN_BANK_ROWS


# --- author_rows_for_file ------------------------------------------------------


class TestAuthorRowsForFile:
    def test_happy_path_writes_validated_rows(self, tmp_path):
        _write_body(tmp_path, "web_rss_x.txt")
        bank = tmp_path / "bank.jsonl"
        bad = {"q": "Kto jest krolem Marsa?", "match": "contains",
               "canonical": "Elon Musk"}  # ungrounded -> dropped
        out = ha.author_rows_for_file(
            "web_rss_x.txt", author_fn=_fake_author(GOOD_ROWS + [bad]),
            author_model="nim:test-70b", input_dir=tmp_path, bank_path=bank,
        )
        assert out["written"] == 3
        rows = exam_agent.load_heldout_bank(bank)
        assert len(rows) == 3
        assert all(r["bank_version"] == "v3" for r in rows)
        assert all(r["author_model"] == "nim:test-70b" for r in rows)
        assert all(r["source_hash"] for r in rows)
        assert all("topic" not in r for r in rows)  # forbidden on v3

    def test_idempotent_on_same_source(self, tmp_path):
        _write_body(tmp_path, "web_rss_x.txt")
        bank = tmp_path / "bank.jsonl"
        ha.author_rows_for_file(
            "web_rss_x.txt", author_fn=_fake_author(GOOD_ROWS),
            input_dir=tmp_path, bank_path=bank,
        )
        out2 = ha.author_rows_for_file(
            "web_rss_x.txt", author_fn=_fake_author(GOOD_ROWS),
            input_dir=tmp_path, bank_path=bank,
        )
        assert out2["written"] == 0
        assert out2["skipped"] == "already covered"
        assert len(exam_agent.load_heldout_bank(bank)) == 3

    def test_refetched_body_authors_new_key_and_select_uses_newest(
            self, tmp_path):
        bank = tmp_path / "bank.jsonl"
        _write_body(tmp_path, "web_rss_x.txt", SOURCE)
        ha.author_rows_for_file(
            "web_rss_x.txt", author_fn=_fake_author(GOOD_ROWS),
            input_dir=tmp_path, bank_path=bank,
        )
        # Feed-rot / re-fetch: body changes -> new hash -> re-authored.
        new_source = SOURCE.replace("2450", "2500")
        new_rows = [dict(GOOD_ROWS[0], canonical="2500"),
                    GOOD_ROWS[1],
                    dict(GOOD_ROWS[2])]
        _write_body(tmp_path, "web_rss_x.txt", new_source)
        time_gap_rows = ha.author_rows_for_file(
            "web_rss_x.txt", author_fn=_fake_author(new_rows),
            input_dir=tmp_path, bank_path=bank,
        )
        assert time_gap_rows["written"] == 3
        all_rows = exam_agent.load_heldout_bank(bank)
        assert len(all_rows) == 6
        selected = exam_agent.select_heldout_rows("web_rss_x.txt", all_rows)
        assert len(selected) == 3
        new_hash = ha.compute_source_hash(new_source)
        assert all(r["source_hash"] == new_hash for r in selected)

    def test_unreadable_source_skips(self, tmp_path):
        out = ha.author_rows_for_file(
            "missing.txt", author_fn=_fake_author(GOOD_ROWS),
            input_dir=tmp_path, bank_path=tmp_path / "bank.jsonl",
        )
        assert out["written"] == 0
        assert "unreadable" in out["skipped"]

    def test_author_call_failure_is_soft(self, tmp_path):
        _write_body(tmp_path, "web_rss_x.txt")

        def broken(prompt):
            raise RuntimeError("NIM down")

        out = ha.author_rows_for_file(
            "web_rss_x.txt", author_fn=broken,
            input_dir=tmp_path, bank_path=tmp_path / "bank.jsonl",
        )
        assert out["written"] == 0
        assert "author failed" in out["skipped"]


# --- author_bank_for_goal (fetch seam) ------------------------------------------


class TestAuthorBankForGoal:
    def test_flag_off_is_noop(self, tmp_path):
        out = ha.author_bank_for_goal(_goal(), ["web_rss_x.txt"])
        assert out == {"skipped": "flag_off"}

    def test_non_heldout_goal_never_banked(self, tmp_path, monkeypatch):
        """Kronika-shaped goal (market, NO verification_mode): even with the
        author flag ON its pantry must never enter the bank (belt-and-suspenders
        with C8's per-exam scoping)."""
        monkeypatch.setenv("HELDOUT_BANK_AUTHOR_ENABLED", "1")
        out = ha.author_bank_for_goal(_goal(mode=None), ["web_rss_x.txt"])
        assert out == {"skipped": "not_heldout_goal"}

    def test_batch_cap_and_deferral(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HELDOUT_BANK_AUTHOR_ENABLED", "1")
        bank = tmp_path / "bank.jsonl"
        files = [f"web_rss_{i}.txt" for i in range(5)]
        for f in files:
            _write_body(tmp_path, f)
        out = ha.author_bank_for_goal(
            _goal(), files, input_dir=tmp_path, bank_path=bank,
            author_fn=_fake_author(GOOD_ROWS), author_model="nim:test",
        )
        assert len(out["authored"]) == ha.MAX_FILES_PER_BATCH
        assert out["deferred"] == files[ha.MAX_FILES_PER_BATCH:]

    def test_lease_taken_when_core_given(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HELDOUT_BANK_AUTHOR_ENABLED", "1")
        _write_body(tmp_path, "web_rss_x.txt")
        seen = {}

        class FakeLease:
            def __enter__(self):
                seen["entered"] = True

            def __exit__(self, *a):
                seen["exited"] = True

        class FakeCore:
            def external_op_lease(self, seconds, label=""):
                seen["seconds"] = seconds
                seen["label"] = label
                return FakeLease()

        ha.author_bank_for_goal(
            _goal(), ["web_rss_x.txt"], core=FakeCore(),
            input_dir=tmp_path, bank_path=tmp_path / "bank.jsonl",
            author_fn=_fake_author(GOOD_ROWS),
        )
        assert seen["entered"] and seen["exited"]
        assert seen["label"] == "heldout_bank_author"
        assert seen["seconds"] >= ha.NIM_AUTHOR_TIMEOUT


# --- B4 backfill ------------------------------------------------------------------


def test_b4_backfill_authors_missing_file(tmp_path, monkeypatch):
    """B4 peek with no coverage + author flag ON: author THIS file, re-peek,
    emit the drill in the SAME cycle (no coverage hole for files beyond the
    fetch-seam cap)."""
    from agent_core.planner.planner_core import PlannerCore
    from agent_core.goals.store import GoalStore
    from agent_core.goals.goal_model import create_goal, GoalType, GoalStatus
    import maria_core.learning.exam_agent as ea

    monkeypatch.setenv("HELDOUT_BANK_AUTHOR_ENABLED", "1")
    for flag in ("STRATEGIC_PLANNER_DRIVES", "FS_WRITE_ENABLED",
                 "HELDOUT_GRADER_ENABLED"):
        monkeypatch.delenv(flag, raising=False)

    bank_state = {"rows": []}
    monkeypatch.setattr(
        ea, "load_heldout_bank", lambda *a, **k: list(bank_state["rows"]))

    def fake_author(file_id, **kwargs):
        bank_state["rows"] = [
            {"file": file_id, "q": f"q{i}", "match": "contains",
             "canonical": f"odp{i}", "bank_version": "v3",
             "source_hash": "abc", "created_at": time.time()}
            for i in range(3)
        ]
        return {"file": file_id, "written": 3, "total": 3}

    monkeypatch.setattr(
        "agent_core.teacher.heldout_author.author_rows_for_file", fake_author)

    results = tmp_path / "exam_results.jsonl"
    store = GoalStore(tmp_path / "goals.jsonl")
    g = create_goal(
        GoalType.USER, "projekt child", 0.9, status=GoalStatus.ACTIVE,
        success_criteria=[{
            "type": "exam_independent", "file": "web_rss_x.txt",
            "grader": "heldout", "min_score": 0.6,
            "results_path": str(results),
        }],
    )
    store.create(g)
    p = PlannerCore(
        state_path=tmp_path / "state.json",
        decisions_path=tmp_path / "decisions.jsonl",
    )
    p.set_goal_store(store)
    p.set_heldout_enabled(True)

    plan = p._maybe_run_heldout_exam({})
    assert plan is not None
    assert plan.action_params["grader"] == "heldout"
    # Post-emission cooldown bounds the re-drill rate (covered-but-failing
    # files); the global selection filter stays untouched.
    assert p._b4_cooldowns.get(g.id, 0) > 0
    assert not p._state.stuck_cooldowns


class TestValidateRowDiffReviewGuards:
    """Diff-review 2026-07-12 (MEDIUM): year-shaped canonicals and zero-tolerance
    prices are degenerate rows -- reject at authoring."""

    def test_year_shaped_canonical_rejected(self):
        row = {"q": "W ktorym roku bitcoin ma osiagnac 500 tys. USD?",
               "match": "numeric", "canonical": "2029", "tolerance": 0}
        ok, why = ha.validate_row(row, SOURCE + " prognoza na 2029 rok ",
                                  "web_rss_x.txt")
        assert not ok and "year-shaped" in why

    def test_price_shaped_zero_tolerance_rejected(self):
        row = {"q": "Do jakiego poziomu wzrosl kurs bitcoina w USD?",
               "match": "numeric", "canonical": "68250", "tolerance": 0}
        ok, why = ha.validate_row(row, SOURCE, "web_rss_x.txt")
        assert not ok and "tolerance > 0" in why

    def test_small_integer_zero_tolerance_ok(self):
        row = {"q": "Ile ton rezerw dokupil bank centralny?",
               "match": "numeric", "canonical": "130", "tolerance": 0}
        ok, why = ha.validate_row(row, SOURCE, "web_rss_x.txt")
        assert ok, why
