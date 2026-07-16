"""Smoke + behaviour: the conscious-unlearn Telegram commands (PR5 operator
surface for rollback/quarantine).

Registers the real command table with a fake bridge (the god-files split smoke
pattern) and drives /quarantine, /unquarantine, /retract (two-step confirm),
/forget_source, /retractions against a LIVE WorldModel with tmp-backed soul
files -- so the operator path is wired end to end, not just unit-tested.
"""

from types import SimpleNamespace

from agent_core.modules.homeostasis_telegram_commands import (
    register_telegram_commands as _register,
)
from agent_core.world_model import WorldModel
from agent_core.world_model import retraction_log
from agent_core.world_model.belief_model import (
    create_belief, EntityType, BeliefType, BeliefSource,
)


class _Bot:
    def __init__(self):
        self.messages = []

    def send_message(self, text, parse_mode=None):
        self.messages.append(text)
        return True


class _Bridge:
    def __init__(self):
        self.handlers = {}
        self.bot = _Bot()

    def register_command(self, command, handler):
        self.handlers[command] = handler


def _wm(tmp_path):
    return WorldModel(
        beliefs_path=tmp_path / "beliefs.jsonl",
        knowledge_index_path=tmp_path / "ki.jsonl",
        longterm_memory_path=tmp_path / "lt.jsonl",
        exam_results_path=tmp_path / "ex.jsonl",
        retractions_path=tmp_path / "retractions.jsonl",
        denylist_path=tmp_path / "denylist.jsonl",
    )


def _ctx(tmp_path, wm):
    core = SimpleNamespace(
        event_logger=SimpleNamespace(
            log_path=str(tmp_path / "homeostasis_events.jsonl")),
        set_synthesis_trigger=lambda cb: None,
    )
    return SimpleNamespace(
        world_model=wm, maria_conductor=None, self_perception=None,
        homeostasis_core=core, planner_core=None, knowledge_analyzer=None,
        goal_store=None, bulletin_store=None, model_scheduler=None,
        sandbox_manager=None,
    )


def _bridge(tmp_path, wm):
    b = _Bridge()
    _register(b, _ctx(tmp_path, wm))
    return b


def _add(wm, entity, belief_id, source_id=None):
    wm.store.add(create_belief(
        entity=entity, entity_type=EntityType.TOPIC,
        belief_type=BeliefType.OBSERVATION, content=f"about {entity}",
        confidence=0.8, source=BeliefSource.LEARNING,
        source_id=source_id or f"topic:{entity}", belief_id=belief_id,
    ))


def test_commands_registered(tmp_path):
    bridge = _bridge(tmp_path, _wm(tmp_path))
    for cmd in ("quarantine", "unquarantine", "retract", "forget_source", "retractions"):
        assert cmd in bridge.handlers


def test_quarantine_then_unquarantine(tmp_path):
    wm = _wm(tmp_path)
    _add(wm, "fizyka", "belief-1")
    bridge = _bridge(tmp_path, wm)

    out = bridge.handlers["quarantine"]("belief-1")
    assert "Kwarantanna" in out
    assert wm.store.get_current() == []

    out2 = bridge.handlers["unquarantine"]("belief-1")
    assert "Przywrocono" in out2
    assert {b.entity for b in wm.store.get_current()} == {"fizyka"}


def test_retract_requires_confirm(tmp_path):
    wm = _wm(tmp_path)
    _add(wm, "fizyka", "belief-1")
    bridge = _bridge(tmp_path, wm)

    # First call (no confirm) = preview, no mutation.
    preview = bridge.handlers["retract"]("belief-1 zle zrodlo")
    assert "NIEODWRACALNE" in preview
    assert "confirm" in preview
    assert wm.store.get("belief-1").status == "active"  # untouched

    # Second call with confirm = executes.
    done = bridge.handlers["retract"]("belief-1 zle zrodlo confirm")
    assert "Wycofano" in done
    assert wm.store.get("belief-1").status == "retracted"
    # Entity denylisted.
    assert "fizyka" in retraction_log.load_denylist(tmp_path / "denylist.jsonl")["entity"]


def test_retract_missing_target(tmp_path):
    bridge = _bridge(tmp_path, _wm(tmp_path))
    out = bridge.handlers["retract"]("ghost powod confirm")
    assert "Brak aktywnego" in out


def test_forget_source_confirm_and_denylist(tmp_path):
    wm = _wm(tmp_path)
    wm.store.add(create_belief(
        entity="synthesis_x", entity_type=EntityType.FILE,
        belief_type=BeliefType.OBSERVATION, content="c", confidence=0.5,
        source=BeliefSource.LEARNING, source_id="file:synthesis_x",
        belief_id="bf"))
    bridge = _bridge(tmp_path, wm)

    preview = bridge.handlers["forget_source"]("synthesis_x halucynacja")
    assert "wytnie" in preview and "confirm" in preview
    assert wm.store.get("bf").status == "active"

    done = bridge.handlers["forget_source"]("synthesis_x halucynacja confirm")
    assert "Wyciecie zrodla" in done
    assert wm.store.get("bf").status == "retracted"
    assert "synthesis_x" in retraction_log.load_denylist(tmp_path / "denylist.jsonl")["source"]


def test_forget_source_denylist_only_when_no_live_beliefs(tmp_path):
    wm = _wm(tmp_path)
    bridge = _bridge(tmp_path, wm)
    done = bridge.handlers["forget_source"]("ghost_source bo tak confirm")
    assert "denylescie" in done
    assert "ghost_source" in retraction_log.load_denylist(tmp_path / "denylist.jsonl")["source"]


def test_retractions_ledger_listing(tmp_path):
    wm = _wm(tmp_path)
    _add(wm, "fizyka", "belief-1")
    bridge = _bridge(tmp_path, wm)
    assert "pusta" in bridge.handlers["retractions"]("")
    bridge.handlers["quarantine"]("belief-1")
    out = bridge.handlers["retractions"]("5")
    assert "quarantine" in out
    assert "fizyka" in out
