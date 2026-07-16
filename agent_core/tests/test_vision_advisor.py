"""Tests for VisionAdvisor -- "Maria reacts to what she sees".

Salient motion -> threaded LLaVA describe -> photo + caption to operator
(text fallback). Covers: salient-gating, cooldown, is_alive stacking guard,
non-blocking spawn, photo-preferred / text-fallback delivery, prompt+save_path
passthrough, describe=None / exception safety. Uses a fake cortex + recording
notifiers (no real LLaVA, no camera).
"""

import threading
import time
from types import SimpleNamespace

from agent_core.vision.vision_advisor import VisionAdvisor, DEFAULT_PROMPT


def _ev(event_type):
    return SimpleNamespace(event_type=event_type)


class _Cortex:
    def __init__(self, desc="Na obrazie widac osobe przy biurku.", delay=0.0,
                 writes=False):
        self.desc = desc
        self.delay = delay
        self.writes = writes
        self.calls = 0
        self.last_prompt = None
        self.last_save_path = None

    def describe_snapshot(self, prompt=None, save_path=None):
        self.calls += 1
        self.last_prompt = prompt
        self.last_save_path = save_path
        if self.delay:
            time.sleep(self.delay)
        if self.writes and save_path and self.desc:
            with open(save_path, "wb") as f:
                f.write(b"\xff\xd8\xff\xe0fake-jpeg")
        return self.desc


def _join(advisor, timeout=2):
    t = advisor._thread
    if t:
        t.join(timeout)


def _snap(tmp_path):
    return str(tmp_path / "snap.jpg")


def test_no_salient_event_no_react(tmp_path):
    pings = []
    adv = VisionAdvisor(_Cortex(), notify_fn=pings.append, snapshot_path=_snap(tmp_path))
    assert adv.maybe_react([_ev("vision_percept"), _ev("vision_health")]) is False
    assert pings == []


def test_no_delivery_channel_is_inert(tmp_path):
    cortex = _Cortex()
    adv = VisionAdvisor(cortex, notify_fn=None, photo_fn=None,
                        snapshot_path=_snap(tmp_path))
    assert adv.maybe_react([_ev("vision_motion")]) is False
    assert cortex.calls == 0


def test_motion_text_only_ping(tmp_path):
    pings = []
    cortex = _Cortex(desc="Ktos wszedl do pokoju.")
    adv = VisionAdvisor(cortex, notify_fn=pings.append, snapshot_path=_snap(tmp_path))
    assert adv.maybe_react([_ev("vision_motion")], now=1000.0) is True
    _join(adv)
    assert cortex.calls == 1
    assert len(pings) == 1
    assert pings[0].startswith("Widz")
    assert "Ktos wszedl do pokoju." in pings[0]
    # advisor passed its prompt + snapshot path through to the cortex
    assert cortex.last_prompt == DEFAULT_PROMPT
    assert cortex.last_save_path == _snap(tmp_path)


def test_translate_fn_renders_caption_to_polish(tmp_path):
    pings = []
    cortex = _Cortex(desc="A street and a house are visible.")  # LLaVA English
    adv = VisionAdvisor(
        cortex, notify_fn=pings.append, snapshot_path=_snap(tmp_path),
        translate_fn=lambda en: "Widać ulicę i dom.",
    )
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert len(pings) == 1
    assert "Widać ulicę i dom." in pings[0]              # Polish translation used
    assert "street" not in pings[0]                       # English description dropped


def test_no_translate_fn_keeps_english(tmp_path):
    pings = []
    cortex = _Cortex(desc="A car is parked outside.")
    adv = VisionAdvisor(cortex, notify_fn=pings.append, snapshot_path=_snap(tmp_path))
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    # No translator wired -> honest English beats faking Polish.
    assert "A car is parked outside." in pings[0]


def test_motion_records_into_vision_memory(tmp_path):
    """E1: the seen description (sans caption prefix) lands in VisionMemory."""
    from agent_core.vision.vision_memory import VisionMemory

    mem = VisionMemory(path=tmp_path / "vm.json")
    cortex = _Cortex(desc="Kot na parapecie.")
    adv = VisionAdvisor(
        cortex, notify_fn=[].append, snapshot_path=_snap(tmp_path), memory=mem,
    )
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    latest = mem.latest()
    assert latest is not None
    assert latest["description"] == "Kot na parapecie."  # no "Widze ruch -" prefix
    assert latest["source"] == "motion"


def test_memory_records_translated_polish(tmp_path):
    """E1: VisionMemory remembers the Polish caption, not the raw English."""
    from agent_core.vision.vision_memory import VisionMemory

    mem = VisionMemory(path=tmp_path / "vm.json")
    cortex = _Cortex(desc="A dog is in the yard.")
    adv = VisionAdvisor(
        cortex, notify_fn=[].append, snapshot_path=_snap(tmp_path),
        translate_fn=lambda en: "Pies w ogrodzie.", memory=mem,
    )
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert mem.latest()["description"] == "Pies w ogrodzie."


def test_no_memory_still_pings(tmp_path):
    """Advisor with no memory wired still works (backward compatible)."""
    pings = []
    cortex = _Cortex(desc="Cos sie rusza.")
    adv = VisionAdvisor(cortex, notify_fn=pings.append, snapshot_path=_snap(tmp_path))
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert len(pings) == 1


def test_translate_failure_falls_back_to_english(tmp_path):
    pings = []
    cortex = _Cortex(desc="Two people near a tree.")

    def boom(_en):
        raise RuntimeError("nim down")

    adv = VisionAdvisor(cortex, notify_fn=pings.append, snapshot_path=_snap(tmp_path),
                        translate_fn=boom)
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert len(pings) == 1
    assert "Two people near a tree." in pings[0]          # never blocks the ping


def test_translate_empty_result_keeps_english(tmp_path):
    pings = []
    cortex = _Cortex(desc="An empty room.")
    adv = VisionAdvisor(cortex, notify_fn=pings.append, snapshot_path=_snap(tmp_path),
                        translate_fn=lambda en: "   ")  # blank -> ignored
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert "An empty room." in pings[0]


def test_photo_preferred_over_text(tmp_path):
    photos = []
    pings = []
    cortex = _Cortex(desc="Osoba przy oknie.", writes=True)
    adv = VisionAdvisor(
        cortex,
        notify_fn=pings.append,
        photo_fn=lambda p, c: photos.append((p, c)) or True,
        snapshot_path=_snap(tmp_path),
    )
    assert adv.maybe_react([_ev("vision_motion")], now=1000.0) is True
    _join(adv)
    assert len(photos) == 1                          # photo sent
    assert photos[0][0] == _snap(tmp_path)           # the saved frame
    assert "Osoba przy oknie." in photos[0][1]       # caption carries desc
    assert pings == []                               # text NOT used when photo ok


def test_text_fallback_when_photo_fails(tmp_path):
    pings = []
    cortex = _Cortex(desc="Cos sie rusza.", writes=True)
    adv = VisionAdvisor(
        cortex,
        notify_fn=pings.append,
        photo_fn=lambda p, c: False,  # photo send fails
        snapshot_path=_snap(tmp_path),
    )
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert len(pings) == 1                            # fell back to text
    assert "Cos sie rusza." in pings[0]


def test_text_fallback_when_no_snapshot_file(tmp_path):
    pings = []
    photos = []
    cortex = _Cortex(desc="Ruch.", writes=False)  # describe runs but saves no file
    adv = VisionAdvisor(
        cortex,
        notify_fn=pings.append,
        photo_fn=lambda p, c: photos.append((p, c)) or True,
        snapshot_path=_snap(tmp_path),
    )
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert photos == []          # no file -> photo skipped
    assert len(pings) == 1       # text used instead


def test_alert_event_also_triggers(tmp_path):
    pings = []
    adv = VisionAdvisor(_Cortex(), notify_fn=pings.append, snapshot_path=_snap(tmp_path))
    assert adv.maybe_react([_ev("vision_alert")], now=1000.0) is True
    _join(adv)
    assert len(pings) == 1


def test_cooldown_blocks_then_allows(tmp_path):
    pings = []
    adv = VisionAdvisor(_Cortex(), notify_fn=pings.append, cooldown_sec=300.0,
                        snapshot_path=_snap(tmp_path))
    assert adv.maybe_react([_ev("vision_motion")], now=1000.0) is True
    _join(adv)
    assert adv.maybe_react([_ev("vision_motion")], now=1100.0) is False  # cooldown
    assert adv.maybe_react([_ev("vision_motion")], now=1400.0) is True   # past it
    _join(adv)
    assert len(pings) == 2


def test_describe_none_no_ping(tmp_path):
    pings = []
    adv = VisionAdvisor(_Cortex(desc=None), notify_fn=pings.append,
                        snapshot_path=_snap(tmp_path))
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert pings == []


def test_describe_exception_swallowed(tmp_path):
    pings = []

    class _Boom:
        def describe_snapshot(self, prompt=None, save_path=None):
            raise RuntimeError("llava down")

    adv = VisionAdvisor(_Boom(), notify_fn=pings.append, snapshot_path=_snap(tmp_path))
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert pings == []  # no crash, no ping


def test_maybe_react_is_non_blocking(tmp_path):
    """The slow LLaVA work must run off the caller's (tick) thread."""
    started = threading.Event()
    release = threading.Event()
    pings = []

    class _Slow:
        def describe_snapshot(self, prompt=None, save_path=None):
            started.set()
            release.wait(2)
            return "opis"

    adv = VisionAdvisor(_Slow(), notify_fn=pings.append, snapshot_path=_snap(tmp_path))
    t0 = time.perf_counter()
    assert adv.maybe_react([_ev("vision_motion")], now=1000.0) is True
    elapsed = time.perf_counter() - t0

    assert started.wait(2)   # describe started in the thread
    assert elapsed < 1.0     # but maybe_react returned without waiting for it
    release.set()
    _join(adv)
    assert len(pings) == 1
    assert pings[0].endswith("opis")


# ---------------------------------------------------------------------------
# E3: suppress the ping (record-only) when the operator is already present
# ---------------------------------------------------------------------------

class _Mem:
    def __init__(self):
        self.records = []

    def record(self, desc, source=None):
        self.records.append((desc, source))


def test_suppress_when_present_skips_describe_light_record_no_ping(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_SUPPRESS_WHEN_PRESENT", "true")
    pings, mem = [], _Mem()
    cortex = _Cortex(desc="Ktos przy biurku.")
    adv = VisionAdvisor(
        cortex, notify_fn=pings.append,
        snapshot_path=_snap(tmp_path), memory=mem,
        operator_present_fn=lambda: True,
    )
    assert adv.maybe_react([_ev("vision_motion")], now=1000.0) is True
    _join(adv)
    assert pings == []                                  # ping suppressed
    assert cortex.calls == 0                            # E3: LLaVA skipped (no CPU burn)
    assert mem.records and mem.records[0][1] == "motion_suppressed"  # light trace only
    assert "operator obecny" in mem.records[0][0]


def test_no_suppress_when_operator_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_SUPPRESS_WHEN_PRESENT", "true")
    pings = []
    adv = VisionAdvisor(
        _Cortex(desc="Ruch."), notify_fn=pings.append,
        snapshot_path=_snap(tmp_path), operator_present_fn=lambda: False,
    )
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert len(pings) == 1                              # absent -> normal ping


def test_flag_off_always_pings_even_if_present(tmp_path, monkeypatch):
    # .env can leak the flag into tests -> explicitly clear it (code-fact).
    monkeypatch.delenv("VISION_SUPPRESS_WHEN_PRESENT", raising=False)
    pings = []
    adv = VisionAdvisor(
        _Cortex(desc="Ruch."), notify_fn=pings.append,
        snapshot_path=_snap(tmp_path), operator_present_fn=lambda: True,
    )
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert len(pings) == 1                              # flag off -> presence ignored


def test_presence_fn_error_fails_open_to_ping(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_SUPPRESS_WHEN_PRESENT", "true")
    pings = []

    def boom():
        raise RuntimeError("presence boom")

    adv = VisionAdvisor(
        _Cortex(desc="Ruch."), notify_fn=pings.append,
        snapshot_path=_snap(tmp_path), operator_present_fn=boom,
    )
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert len(pings) == 1                              # error -> fail-open -> ping


# ── Quiet hours ────────────────────────────────────────────

class _Memory:
    def __init__(self):
        self.records = []

    def record(self, text, source=None):
        self.records.append((text, source))


def test_quiet_hours_records_silently_no_llava_no_ping(tmp_path):
    """At night: motion leaves a trace, but no LLaVA describe and no ping."""
    from agent_core.vision.vision_advisor import QUIET_PLACEHOLDER

    pings = []
    cortex = _Cortex(desc="Ktos wszedl.")
    mem = _Memory()
    adv = VisionAdvisor(
        cortex, notify_fn=pings.append, snapshot_path=_snap(tmp_path),
        memory=mem, quiet_hours_fn=lambda: True,
    )
    assert adv.maybe_react([_ev("vision_motion")], now=1000.0) is True
    _join(adv)
    assert cortex.calls == 0, "LLaVA must not run at night"
    assert pings == [], "no ping at night"
    assert mem.records == [(QUIET_PLACEHOLDER, "motion_suppressed")]


def test_not_quiet_pings_normally(tmp_path):
    pings = []
    cortex = _Cortex(desc="Ktos wszedl.")
    adv = VisionAdvisor(
        cortex, notify_fn=pings.append, snapshot_path=_snap(tmp_path),
        quiet_hours_fn=lambda: False,
    )
    assert adv.maybe_react([_ev("vision_motion")], now=1000.0) is True
    _join(adv)
    assert cortex.calls == 1
    assert len(pings) == 1


def test_quiet_hours_fail_open_on_error(tmp_path):
    """A throwing quiet-hours predicate must not silence vision by accident."""
    pings = []
    cortex = _Cortex(desc="Ktos wszedl.")

    def _boom():
        raise RuntimeError("clock gone")

    adv = VisionAdvisor(
        cortex, notify_fn=pings.append, snapshot_path=_snap(tmp_path),
        quiet_hours_fn=_boom,
    )
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert cortex.calls == 1
    assert len(pings) == 1


def test_quiet_placeholder_distinct_from_present(tmp_path):
    """Night trace is labelled quiet-hours, not 'operator present'."""
    from agent_core.vision.vision_advisor import QUIET_PLACEHOLDER, SILENT_PLACEHOLDER

    assert QUIET_PLACEHOLDER != SILENT_PLACEHOLDER
    mem = _Memory()
    adv = VisionAdvisor(
        _Cortex(), notify_fn=[].append, snapshot_path=_snap(tmp_path),
        memory=mem, quiet_hours_fn=lambda: True,
    )
    adv.maybe_react([_ev("vision_motion")], now=1000.0)
    _join(adv)
    assert mem.records[0][0] == QUIET_PLACEHOLDER
