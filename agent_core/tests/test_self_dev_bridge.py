"""Tests for the self-development bridge (proactive nudge + /approve_dev)."""

import json
from pathlib import Path

from agent_core.bulletin import BulletinStore
from agent_core.bulletin.bulletin_model import EntryType
from agent_core.self_development import SelfDevBridge, SelfDevJournal


TITLE = "Zwiekszaj roznorodnosc danych treningowych"


def _seed(tmp_path, n_goals=60, days_ago=30, with_bulletin=True):
    """Seed one big, old, stuck theme in both meta-goals and the bulletin.

    Returns (board, bulletin_store).
    """
    base = 100 * 86400.0
    created = base - days_ago * 86400.0
    rows = [
        {"goal_id": f"mg-{i}", "title": TITLE,
         "created_ts": created, "status": "accepted"}
        for i in range(n_goals)
    ]
    (tmp_path / "creative_meta_goals.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    bull = BulletinStore(path=tmp_path / "cognitive_bulletin.jsonl")
    if with_bulletin:
        # one creative advisory for the theme, linked to a meta-goal in it
        bull.create_and_post(
            entry_type=EntryType.IMPROVEMENT,
            topic=TITLE,
            reason_code="creative_capability_meta",
            summary="why",
            requested_by="creative",
            metadata={"meta_goal_id": "mg-0",
                      "meta_goal_type": "capability_meta"},
        )
    board = SelfDevJournal(data_dir=str(tmp_path))
    return board, bull


def _bridge(tmp_path, board, bull):
    return SelfDevBridge(board=board, bulletin_store=bull,
                         data_dir=str(tmp_path))


def test_find_alert_returns_stuck_high_recurrence_theme(tmp_path):
    board, bull = _seed(tmp_path)
    br = _bridge(tmp_path, board, bull)
    now = 100 * 86400.0
    t = br.find_alert(now=now)
    assert t is not None
    assert t.display_title == TITLE
    assert t.stuck is True
    assert t.asked_count == 60


def test_below_ask_floor_not_alerted(tmp_path):
    board, bull = _seed(tmp_path, n_goals=20)  # 20 < ALERT_MIN_ASKED(50)
    br = _bridge(tmp_path, board, bull)
    assert br.find_alert(now=100 * 86400.0) is None


def test_cooldown_suppresses_repeat_alert(tmp_path):
    board, bull = _seed(tmp_path)
    br = _bridge(tmp_path, board, bull)
    now = 100 * 86400.0
    t = br.find_alert(now=now)
    token = br.register_alert(t, now=now)
    assert token
    # within cooldown -> nothing to alert
    assert br.find_alert(now=now + 3600) is None
    # after cooldown window -> alertable again
    assert br.find_alert(now=now + 8 * 86400) is not None


def test_alert_text_has_title_and_token(tmp_path):
    board, bull = _seed(tmp_path)
    br = _bridge(tmp_path, board, bull)
    now = 100 * 86400.0
    t = br.find_alert(now=now)
    token = br.register_alert(t, now=now)
    text = br.build_alert_text(t, token)
    assert TITLE in text
    assert token in text
    assert "/approve_dev" in text


def test_acknowledge_resolves_and_flips_board(tmp_path):
    """The headline loop: /approve_dev -> operator_acknowledged -> board flips
    the theme from stuck to realized."""
    board, bull = _seed(tmp_path)
    br = _bridge(tmp_path, board, bull)
    now = 100 * 86400.0

    # before: stuck, not realized
    pre = board.build_board(now=now)[0]
    assert pre.stuck is True and pre.realized is False

    t = br.find_alert(now=now)
    token = br.register_alert(t, now=now)
    msg = br.acknowledge(token, now=now)
    assert "Przejete" in msg

    # after: the linked bulletin entry is resolved operator_acknowledged ->
    # board realized-join flips the theme to realized, no longer stuck
    post = board.build_board(now=now)[0]
    assert post.realized is True
    assert post.stuck is False


def test_acknowledge_unknown_token_is_friendly(tmp_path):
    board, bull = _seed(tmp_path)
    br = _bridge(tmp_path, board, bull)
    msg = br.acknowledge("zzzzzz")
    assert "Nie znam" in msg


def test_maybe_alert_sends_once_then_cooldown(tmp_path):
    """Tick path: maybe_alert sends one nudge, then stays quiet in cooldown."""
    board, bull = _seed(tmp_path)
    br = _bridge(tmp_path, board, bull)
    now = 100 * 86400.0
    sent = []
    text = br.maybe_alert(sent.append, now=now)
    assert text is not None
    assert len(sent) == 1 and TITLE in sent[0]
    # second call within cooldown -> nothing sent
    assert br.maybe_alert(sent.append, now=now + 3600) is None
    assert len(sent) == 1


def test_pace_guard_one_nudge_per_day_across_themes(tmp_path):
    """Global pace: with several stuck themes, only one nudge fires per day so
    the backlog surfaces one idea at a time, not as a burst of back-to-back
    pings. The second theme appears only after the pace window, while the first
    is still inside its own 7-day theme cooldown."""
    base = 100 * 86400.0
    created = base - 30 * 86400.0
    rows = []
    for i in range(60):  # theme A (top by ask-count)
        rows.append({"goal_id": f"a-{i}", "title": "Zwiekszaj predkosc nauki",
                     "created_ts": created, "status": "accepted"})
    for i in range(55):  # theme B (also stuck, lower count)
        rows.append({"goal_id": f"b-{i}", "title": "Rozwijaj nowe umiejetnosci",
                     "created_ts": created, "status": "accepted"})
    (tmp_path / "creative_meta_goals.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    bull = BulletinStore(path=tmp_path / "cognitive_bulletin.jsonl")
    board = SelfDevJournal(data_dir=str(tmp_path))
    br = _bridge(tmp_path, board, bull)

    now = base
    sent = []
    # day 1: one nudge fires (the top theme)
    assert br.maybe_alert(sent.append, now=now) is not None
    assert len(sent) == 1
    # same day, 12h later: pace guard keeps it silent despite a second stuck theme
    assert br.maybe_alert(sent.append, now=now + 12 * 3600) is None
    assert len(sent) == 1
    # next day: the second theme surfaces (first still in its 7-day cooldown)
    assert br.maybe_alert(sent.append, now=now + 25 * 3600) is not None
    assert len(sent) == 2
    assert sent[0] != sent[1]  # two different themes, not a repeat


def test_no_alert_when_theme_already_realized(tmp_path):
    """An already-acknowledged theme must not be re-nudged."""
    board, bull = _seed(tmp_path)
    br = _bridge(tmp_path, board, bull)
    now = 100 * 86400.0
    t = br.find_alert(now=now)
    token = br.register_alert(t, now=now)
    br.acknowledge(token, now=now)
    # realized -> not stuck -> not alertable (cooldown aside)
    assert br.find_alert(now=now + 30 * 86400) is None
