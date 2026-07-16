"""Tests for the self-development board (agent_core/self_development)."""

import json

from agent_core.self_development.board import SelfDevJournal
from agent_core.self_development.title_normalizer import normalize_title


# --- title normalizer -------------------------------------------------------

def test_normalizer_collapses_numeric_and_diacritic_variants():
    """Numbers, percents, casing, word order and diacritics drop out."""
    a = normalize_title("Zwiekszenie predkosci nauki o 10%")
    b = normalize_title("Zwiększenie prędkości nauki o 0.1")
    c = normalize_title("predkosci nauki zwiekszenie")  # reordered
    assert a == b == c
    assert "10" not in a and "%" not in a


def test_normalizer_does_not_collapse_synonyms():
    """Normalization alone is NOT enough -- synonyms stay distinct (needs embed)."""
    t = normalize_title("Zwiekszaj roznorodnosc danych treningowych")
    s = normalize_title("Zwiekszaj roznorodnosc danych szkoleniowych")
    assert t != s


def test_normalizer_handles_l_stroke():
    """'l with stroke' has no NFKD decomposition; must be mapped explicitly."""
    assert normalize_title("Rozwijanie umiejetnosci") == \
        normalize_title("Rozwijanie umiejętności")


def test_normalizer_empty():
    assert normalize_title("") == ""
    assert normalize_title(None) == ""


# --- raw scan + dedup -------------------------------------------------------

def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_raw_scan_bypasses_cap_and_keeps_oldest(tmp_path):
    """600 unique ids -> all 600 read; oldest_ts is the true global min."""
    rows = []
    for i in range(600):
        rows.append({
            "goal_id": f"mg-{i:04d}",
            "title": "Ston temat",
            "created_ts": 2000.0 + i,  # ascending
            "status": "accepted",
        })
    # the OLDEST entry is the very first (created_ts=2000), would be dropped
    # by a newest-500 cap store
    _write_jsonl(tmp_path / "creative_meta_goals.jsonl", rows)
    j = SelfDevJournal(data_dir=str(tmp_path))
    goals = j.read_meta_goals_raw()
    assert len(goals) == 600
    themes = j.build_board(top_n=5, now=10000.0)
    assert themes[0].asked_count == 600
    assert themes[0].oldest_ts == 2000.0  # true min preserved


def test_dedup_goal_id_later_wins(tmp_path):
    """Same goal_id over draft->proposed->rejected counts as ONE; last status wins."""
    rows = [
        {"goal_id": "mg-1", "title": "Temat", "created_ts": 100.0, "status": "draft"},
        {"goal_id": "mg-1", "title": "Temat", "created_ts": 100.0, "status": "proposed"},
        {"goal_id": "mg-1", "title": "Temat", "created_ts": 100.0, "status": "rejected"},
    ]
    _write_jsonl(tmp_path / "creative_meta_goals.jsonl", rows)
    j = SelfDevJournal(data_dir=str(tmp_path))
    goals = j.read_meta_goals_raw()
    assert len(goals) == 1
    assert goals["mg-1"]["status"] == "rejected"
    themes = j.build_board(now=200.0)
    assert themes[0].asked_count == 1
    assert themes[0].status_breakdown == {"rejected": 1}


# --- stuck flag + rendering -------------------------------------------------

def test_stuck_flag_thresholds(tmp_path):
    """stuck requires both high count AND old age (INC-1 preliminary)."""
    now = 100 * 86400.0
    rows = []
    # theme A: 20 asks, oldest 30 days ago -> stuck
    for i in range(20):
        rows.append({"goal_id": f"a-{i}", "title": "Duzy stary temat",
                     "created_ts": 70 * 86400.0, "status": "accepted"})
    # theme B: 3 asks, oldest 30 days ago -> not stuck (below count)
    for i in range(3):
        rows.append({"goal_id": f"b-{i}", "title": "Maly temat",
                     "created_ts": 70 * 86400.0, "status": "accepted"})
    _write_jsonl(tmp_path / "creative_meta_goals.jsonl", rows)
    j = SelfDevJournal(data_dir=str(tmp_path))
    themes = {t.display_title: t for t in j.build_board(now=now)}
    assert themes["Duzy stary temat"].stuck is True
    assert themes["Maly temat"].stuck is False


def test_format_plain_text_no_emoji_no_markdown(tmp_path):
    rows = [{"goal_id": "mg-1", "title": "Jakis temat",
             "created_ts": 100.0, "status": "accepted"}]
    _write_jsonl(tmp_path / "creative_meta_goals.jsonl", rows)
    j = SelfDevJournal(data_dir=str(tmp_path))
    out = j.format_for_telegram(j.build_board(now=200.0))
    assert "Jakis temat" in out
    assert "1x" in out
    # no Markdown emphasis chars that break underscores; no bold stars
    assert "**" not in out
    # ASCII-only (no emoji) -- ADR-005
    out.encode("ascii")


def test_empty_board(tmp_path):
    j = SelfDevJournal(data_dir=str(tmp_path))  # no file
    assert j.read_meta_goals_raw() == {}
    assert "Brak" in j.format_for_telegram(j.build_board())


# --- INC-2: realized join + stuck -------------------------------------------

def _seed_one_theme(tmp_path, goal_id="mg-1", n=20, days_ago=30):
    """Write a single stuck-eligible theme (n asks, old) and return its path."""
    base = 100 * 86400.0
    rows = [{"goal_id": f"{goal_id}-{i}", "title": "Wazny temat",
             "created_ts": base - days_ago * 86400.0, "status": "accepted"}
            for i in range(n)]
    _write_jsonl(tmp_path / "creative_meta_goals.jsonl", rows)
    return base


def _write_bulletin(tmp_path, entries):
    _write_jsonl(tmp_path / "cognitive_bulletin.jsonl", entries)


def test_realized_join_positive_whitelist_reason(tmp_path):
    """Resolved bulletin with a whitelisted reason + matching meta_goal_id
    flips the theme to realized (and off stuck)."""
    now = _seed_one_theme(tmp_path)
    _write_bulletin(tmp_path, [{
        "entry_id": "e1", "status": "resolved",
        "metadata": {"meta_goal_id": "mg-1-0",
                     "last_status_reason": "material_fetched"},
    }])
    j = SelfDevJournal(data_dir=str(tmp_path))
    t = j.build_board(now=now)[0]
    assert t.realized is True
    assert "e1" in t.realized_evidence
    assert t.stuck is False
    assert t.realized_join_status == "live"


def test_realized_join_rejects_non_whitelist_reasons(tmp_path):
    """skip/expire/None reasons do NOT count as realized (anti false-comfort)."""
    now = _seed_one_theme(tmp_path)
    for bad in ("skip_measurement_artifact", "task_expired", None):
        _write_bulletin(tmp_path, [{
            "entry_id": "e1", "status": "resolved",
            "metadata": {"meta_goal_id": "mg-1-0", "last_status_reason": bad},
        }])
        j = SelfDevJournal(data_dir=str(tmp_path))
        t = j.build_board(now=now)[0]
        assert t.realized is False, bad
        assert t.stuck is True
        assert t.realized_join_status == "bridge_broken"


def test_realized_join_sees_resolved_entries(tmp_path):
    """Raw scan must see RESOLVED entries (the public get_open API hides them)."""
    now = _seed_one_theme(tmp_path)
    _write_bulletin(tmp_path, [{
        "entry_id": "e1", "status": "resolved",
        "metadata": {"meta_goal_id": "mg-1-5",
                     "last_status_reason": "operator_acknowledged"},
    }])
    j = SelfDevJournal(data_dir=str(tmp_path))
    realized = j._load_realized_meta_goal_ids()
    assert realized.get("mg-1-5") == ["e1"]


def test_realized_join_ignores_reason_code_creation_field(tmp_path):
    """reason_code is the CREATION reason, never the close reason -- ignored."""
    now = _seed_one_theme(tmp_path)
    _write_bulletin(tmp_path, [{
        "entry_id": "e1", "status": "resolved",
        "reason_code": "creative_architectural_meta",  # creation, not close
        "metadata": {"meta_goal_id": "mg-1-0"},  # no last_status_reason
    }])
    j = SelfDevJournal(data_dir=str(tmp_path))
    assert j.build_board(now=now)[0].realized is False


def test_bridge_broken_header_in_output(tmp_path):
    now = _seed_one_theme(tmp_path)
    j = SelfDevJournal(data_dir=str(tmp_path))
    out = j.format_for_telegram(j.build_board(now=now))
    assert "nikt nie domyka" in out
    out.encode("ascii")


# --- INC-3: cache + command entry point -------------------------------------

def test_get_cached_board_lazy_builds_then_caches(tmp_path):
    now = _seed_one_theme(tmp_path)
    j = SelfDevJournal(data_dir=str(tmp_path))
    first = j.get_cached_board()
    assert first  # built on demand
    # mutate the source -> cached result must stay stable (read from cache)
    _write_jsonl(tmp_path / "creative_meta_goals.jsonl", [])
    second = j.get_cached_board()
    assert second is first  # same cached object, not rebuilt


def test_render_board_returns_text(tmp_path):
    _seed_one_theme(tmp_path)
    j = SelfDevJournal(data_dir=str(tmp_path))
    out = j.render_board()
    assert "Samorozwoj" in out
    out.encode("ascii")


def test_no_goal_creation_invariant(tmp_path, monkeypatch):
    """R1: building the board must never create goals or post bulletins."""
    import agent_core.self_development.board as board_mod
    now = _seed_one_theme(tmp_path)
    j = SelfDevJournal(data_dir=str(tmp_path))
    # board imports nothing that writes; assert no write to the source files
    before = (tmp_path / "creative_meta_goals.jsonl").read_bytes()
    j.build_board(now=now)
    after = (tmp_path / "creative_meta_goals.jsonl").read_bytes()
    assert before == after  # read-only over the source of truth


# --- INC-5: artifact write + tick orchestration -----------------------------

def test_write_artifact_atomic_snapshot_and_audit_append(tmp_path):
    """The .md keeps only the latest snapshot; the audit .jsonl appends."""
    _seed_one_theme(tmp_path)
    j = SelfDevJournal(data_dir=str(tmp_path))
    j.refresh_and_write()
    j.refresh_and_write()
    md = (tmp_path / "self_dev_board.md").read_text(encoding="utf-8")
    assert md.count("# Tablica samorozwoju Marii") == 1  # single snapshot
    md.encode("ascii")  # no emoji (ADR-005)
    audit = [l for l in (tmp_path / "self_dev_journal.jsonl")
             .read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(audit) == 2  # append-only history
    rec = json.loads(audit[-1])
    assert rec["stuck_count"] >= 1 and "themes" in rec


def test_refresh_and_write_updates_command_cache(tmp_path):
    """Phase 21 refresh feeds the same cache the /samorozwoj command reads."""
    _seed_one_theme(tmp_path)
    j = SelfDevJournal(data_dir=str(tmp_path))
    written = j.refresh_and_write()
    assert j.get_cached_board() is written  # command reads the refreshed cache


def test_no_artifact_files_when_only_reading(tmp_path):
    """The read command path must not write artifacts (only Phase 21 writes)."""
    _seed_one_theme(tmp_path)
    j = SelfDevJournal(data_dir=str(tmp_path))
    j.render_board()
    assert not (tmp_path / "self_dev_board.md").exists()
    assert not (tmp_path / "self_dev_journal.jsonl").exists()
