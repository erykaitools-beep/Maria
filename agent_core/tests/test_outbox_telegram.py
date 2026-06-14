"""Telegram wiring for the Rung 2 outbox (TIER 2 hands): drill -> list ->
approve, end to end through _register_telegram_commands. tmp_path isolated.

Proves the operator-gated chain: /drill_outbox PROPOSES (no write), /approve_note
performs the one guarded write. Nothing reaches the world without approval.
"""

from pathlib import Path
from types import SimpleNamespace

from agent_core.hands import outbox as outbox_mod
from agent_core.hands.outbox import OutboxProposalStore
from agent_core.hands.sandbox_writer import default_outbox_root
from agent_core.homeostasis.core import HomeostasisCore
from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands as _register_telegram_commands,
)
from agent_core.modules.homeostasis_outbox import (
    _notify_outbox,
    _propose_outbox_status_note,
)


class FakeBot:
    def __init__(self):
        self.messages = []

    def send_message(self, text, parse_mode=None):
        self.messages.append(text)
        return True


class FakeBridge:
    def __init__(self):
        self.handlers = {}
        self.bot = FakeBot()

    def register_command(self, command, handler):
        self.handlers[command] = handler


def _ctx(tmp_path):
    store = OutboxProposalStore(path=tmp_path / "proposals.jsonl", base_dir=str(tmp_path))
    state = SimpleNamespace(mode=SimpleNamespace(value="ACTIVE"), health_score=0.91)
    notifier_msgs = []

    def _send_raw(text, parse_mode="Markdown"):
        notifier_msgs.append(text)
        return True

    ctx = SimpleNamespace(
        outbox_store=store,
        homeostasis_core=SimpleNamespace(state=state),
        goal_store=SimpleNamespace(get_active=lambda: [SimpleNamespace(id="g1")]),
        telegram_notifier=SimpleNamespace(send_raw=_send_raw),
        # attrs other registered handlers may read at call time
        planner_core=None, knowledge_analyzer=None, bulletin_store=None,
        maria_conductor=None, self_perception=None, repair_task_creator=None,
    )
    return ctx, store, notifier_msgs


def _bridge(ctx):
    b = FakeBridge()
    _register_telegram_commands(b, ctx)
    return b


def _outbox_dir(tmp_path):
    return Path(default_outbox_root(str(tmp_path)))


def test_drill_outbox_proposes_without_writing(tmp_path):
    ctx, store, notifier_msgs = _ctx(tmp_path)
    bridge = _bridge(ctx)

    resp = bridge.handlers["drill_outbox"]("")

    assert "Outbox drill OK" in resp
    assert len(store.list_pending()) == 1
    # crucial: proposing writes nothing to the world
    assert not _outbox_dir(tmp_path).exists() or not any(_outbox_dir(tmp_path).iterdir())
    assert notifier_msgs and "proponuje" in notifier_msgs[0]


def test_list_notes_shows_pending(tmp_path):
    ctx, store, _ = _ctx(tmp_path)
    bridge = _bridge(ctx)
    bridge.handlers["drill_outbox"]("")

    resp = bridge.handlers["list_notes"]("")

    assert "Oczekujace notatki outbox (1)" in resp
    assert store.list_pending()[0]["id"] in resp


def test_approve_note_performs_the_one_write(tmp_path):
    ctx, store, _ = _ctx(tmp_path)
    bridge = _bridge(ctx)
    bridge.handlers["drill_outbox"]("")
    pid = store.list_pending()[0]["id"]

    resp = bridge.handlers["approve_note"](pid)

    assert "Zapisano" in resp
    files = list(_outbox_dir(tmp_path).glob("*.txt"))
    assert len(files) == 1
    assert "Maria -- status note" in files[0].read_text()
    assert store.list_pending() == []  # consumed


def test_approve_note_unknown_id(tmp_path):
    ctx, _, _ = _ctx(tmp_path)
    bridge = _bridge(ctx)
    resp = bridge.handlers["approve_note"]("obx-nope")
    assert "nieudane" in resp


def test_drill_outbox_dedups_when_pending(tmp_path):
    ctx, store, _ = _ctx(tmp_path)
    bridge = _bridge(ctx)
    bridge.handlers["drill_outbox"]("")
    resp2 = bridge.handlers["drill_outbox"]("")  # one already pending
    assert "brak propozycji" in resp2
    assert len(store.list_pending()) == 1


# -- core tick hook (the SOLE flag gate) + full wire --

def test_core_maybe_propose_outbox_flag_on(monkeypatch):
    monkeypatch.setattr(outbox_mod, "is_enabled", lambda: True)
    calls = []
    fake = SimpleNamespace(_outbox_proposer=lambda reason: calls.append(reason))
    HomeostasisCore._maybe_propose_outbox(fake)
    assert calls == ["autonomous"]


def test_core_maybe_propose_outbox_flag_off(monkeypatch):
    monkeypatch.setattr(outbox_mod, "is_enabled", lambda: False)
    calls = []
    fake = SimpleNamespace(_outbox_proposer=lambda reason: calls.append(reason))
    HomeostasisCore._maybe_propose_outbox(fake)
    assert calls == []  # flag OFF => no autonomous propose


def test_core_maybe_propose_outbox_no_proposer(monkeypatch):
    monkeypatch.setattr(outbox_mod, "is_enabled", lambda: True)
    HomeostasisCore._maybe_propose_outbox(SimpleNamespace(_outbox_proposer=None))  # no crash


def test_full_wire_tick_to_pending_proposal(tmp_path, monkeypatch):
    # tick -> _maybe_propose_outbox -> proposer("autonomous") -> helper -> propose
    monkeypatch.setattr(outbox_mod, "is_enabled", lambda: True)
    ctx, store, _ = _ctx(tmp_path)
    fake = SimpleNamespace(
        _outbox_proposer=lambda reason: _propose_outbox_status_note(ctx, reason),
    )
    HomeostasisCore._maybe_propose_outbox(fake)
    assert len(store.list_pending()) == 1
    assert store.list_pending()[0]["reason"] == "autonomous"


# -- notify resilience: a failed ping must not strand/raise --

def test_proposal_recorded_even_if_notify_raises(tmp_path):
    ctx, store, _ = _ctx(tmp_path)

    def _boom(_msg, parse_mode="Markdown"):
        raise RuntimeError("telegram down")

    ctx.telegram_notifier = SimpleNamespace(send_raw=_boom)
    rec = _propose_outbox_status_note(ctx, reason="drill")
    assert rec is not None                      # helper still returns
    assert len(store.list_pending()) == 1       # proposal persisted despite notify fail


def test_notify_outbox_is_plain_text():
    # REGRESSION (2026-06-09): the ping carries /approve_note + a status filename,
    # both with underscores. It MUST be sent as PLAIN TEXT -- Telegram Markdown
    # treats '_' as italic and, when underscores balance, silently eats them,
    # so '/approve_note' arrives as '/approvenote' and the command fails.
    rec = {"id": "obx-1", "filename": "maria_status_1", "content": "c"}
    calls = []
    notifier = SimpleNamespace(
        send_raw=lambda text, parse_mode="Markdown": calls.append((text, parse_mode))
    )
    _notify_outbox(SimpleNamespace(telegram_notifier=notifier), rec)
    assert len(calls) == 1
    text, parse_mode = calls[0]
    assert parse_mode is None                       # plain text, NOT Markdown
    assert "/approve_note obx-1" in text            # underscore must survive
    assert "maria_status_1" in text


def test_notify_bot_fallback_is_plain_text():
    # No notifier -> bridge.bot fallback must also force plain text.
    rec = {"id": "obx-1", "filename": "f", "content": "c"}
    calls = []
    ctx = SimpleNamespace(
        telegram_notifier=None,
        telegram_bridge=SimpleNamespace(
            bot=SimpleNamespace(
                send_message=lambda text, parse_mode="Markdown": calls.append((text, parse_mode))
            )
        ),
    )
    _notify_outbox(ctx, rec)
    assert len(calls) == 1 and calls[0][1] is None and "obx-1" in calls[0][0]


def test_autonomous_respects_min_gap(tmp_path):
    # Autonomous proposer must self-throttle: after a recent proposal (even one
    # already approved, so not pending), a fresh autonomous call is skipped.
    ctx, store, _ = _ctx(tmp_path)
    first = _propose_outbox_status_note(ctx, reason="autonomous")
    assert first is not None
    store.approve(first["id"])  # clear pending so only the gap guard remains
    second = _propose_outbox_status_note(ctx, reason="autonomous")
    assert second is None  # within the 20h gap -> throttled


def test_reject_note_drops_without_writing(tmp_path):
    ctx, store, _ = _ctx(tmp_path)
    bridge = _bridge(ctx)
    bridge.handlers["drill_outbox"]("")
    pid = store.list_pending()[0]["id"]

    resp = bridge.handlers["reject_note"](pid)

    assert "Odrzucono" in resp
    assert store.list_pending() == []
    assert not _outbox_dir(tmp_path).exists() or not any(_outbox_dir(tmp_path).iterdir())
