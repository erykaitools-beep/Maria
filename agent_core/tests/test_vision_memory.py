"""Tests for Super-META E1 VisionMemory (Maria remembers what she saw)."""

import json
import time

from agent_core.vision.vision_memory import VisionMemory, _ago


def _vm(tmp_path, **kw):
    return VisionMemory(path=tmp_path / "vm.json", **kw)


def test_record_and_latest(tmp_path):
    vm = _vm(tmp_path)
    assert vm.is_empty()
    vm.record("Kot na parapecie.", source="motion", timestamp=1000.0)
    latest = vm.latest()
    assert latest["description"] == "Kot na parapecie."
    assert latest["source"] == "motion"
    assert latest["timestamp"] == 1000.0
    assert latest["iso"]  # rendered
    assert not vm.is_empty()


def test_empty_description_ignored(tmp_path):
    vm = _vm(tmp_path)
    vm.record("   ")
    vm.record("")
    assert vm.is_empty()
    assert vm.latest() is None


def test_recent_is_newest_first(tmp_path):
    vm = _vm(tmp_path)
    for i in range(3):
        vm.record(f"scena {i}", timestamp=1000.0 + i)
    recent = vm.recent(2)
    assert [e["description"] for e in recent] == ["scena 2", "scena 1"]


def test_ring_buffer_caps_entries(tmp_path):
    vm = _vm(tmp_path, max_entries=3)
    for i in range(6):
        vm.record(f"s{i}", timestamp=1000.0 + i)
    recent = vm.recent(10)
    assert len(recent) == 3
    assert [e["description"] for e in recent] == ["s5", "s4", "s3"]


def test_persistence_survives_reload(tmp_path):
    vm = _vm(tmp_path)
    vm.record("Ktos wszedl.", timestamp=1000.0)
    vm.record("Pusto.", timestamp=1001.0)
    # New instance over the same file = simulates a restart.
    vm2 = _vm(tmp_path)
    assert vm2.latest()["description"] == "Pusto."
    assert len(vm2.recent(10)) == 2


def test_persisted_file_never_grows_past_cap(tmp_path):
    vm = _vm(tmp_path, max_entries=3)
    for i in range(20):
        vm.record(f"s{i}", timestamp=1000.0 + i)
    with open(tmp_path / "vm.json", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 3


def test_format_for_telegram_empty(tmp_path):
    assert "Jeszcze nic" in _vm(tmp_path).format_for_telegram()


def test_format_for_telegram_lists_recent(tmp_path):
    vm = _vm(tmp_path)
    vm.record("Kot.", timestamp=time.time() - 120)
    text = vm.format_for_telegram()
    assert "Co ostatnio widzialam" in text
    assert "Kot." in text
    assert "temu" in text


def test_ago_buckets():
    assert _ago(5) == "przed chwila"
    assert _ago(30) == "30s temu"
    assert _ago(120) == "2 min temu"
    assert _ago(7200) == "2 godz temu"
    assert _ago(3 * 86400) == "3 dni temu"


def test_corrupt_file_loads_empty(tmp_path):
    p = tmp_path / "vm.json"
    p.write_text("{ not json", encoding="utf-8")
    vm = VisionMemory(path=p)
    assert vm.is_empty()  # degraded, no crash
