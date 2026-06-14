from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from agent_core.self_perception import SelfPerception, SnapshotStore


class FakeSelfModel:
    def __init__(self, ctx):
        self._ctx = ctx

    def get_identity(self):
        return {
            "name": "Maria",
            "session_count": 2087,
            "total_uptime_hours": 845.3,
            "age_string": "6 miesiecy",
        }

    def get_current_mode(self):
        return self._ctx.mode

    def get_awareness(self):
        return {
            "files_total": 425,
            "files_by_status": {"completed": 423, "pending": 2},
            "input_files_count": 0,
        }


class FakeLimitationReporter:
    def __init__(self, ctx):
        self._ctx = ctx

    def get_report(self):
        return {
            "total_limitations": len(self._ctx.limitations),
            "by_severity": dict(self._ctx.by_severity),
            "limitations": list(self._ctx.limitations),
            "blocked_actions": [{}] * self._ctx.blocked_count,
            "blocked_count": self._ctx.blocked_count,
            "mode": self._ctx.mode,
        }


class FakeToolCapabilityRegistry:
    def __init__(self, ctx):
        self._ctx = ctx

    def get_summary(self):
        return {
            "total_capabilities": self._ctx.total_capabilities,
            "free": 7,
            "guarded": 3,
            "restricted": 2,
            "external_services": len(self._ctx.services),
            "available_services": sum(
                1 for service in self._ctx.services
                if service["status"] == "available"
            ),
            "categories": ["Nauka", "Samoanaliza", "System", "Efektory"],
        }

    def list_external_services(self):
        return list(self._ctx.services)


class FakeBulletinStore:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def create_and_post(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(entry_id=f"fake-{len(self.calls)}")


@pytest.fixture
def fake_ctx():
    ctx = SimpleNamespace()
    ctx.mode = "ACTIVE"
    ctx.total_capabilities = 12
    ctx.services = [
        {"name": "NVIDIA NIM API", "status": "available"},
        {"name": "Ollama (local LLM)", "status": "available"},
        {"name": "OpenClaw Effector", "status": "disconnected"},
        {"name": "Codex (ChatGPT Plus)", "status": "available"},
        {"name": "Telegram (ClawBot)", "status": "available"},
    ]
    ctx.limitations = [
        {
            "category": "budget",
            "severity": "info",
            "description": "Budzet NIM niski (450 tokenow)",
        },
        {
            "category": "hardware",
            "severity": "warning",
            "description": "OpenClaw efektor niedostepny",
        },
    ]
    ctx.by_severity = {"critical": 0, "warning": 1, "info": 1}
    ctx.blocked_count = 2
    ctx.homeostasis_core = SimpleNamespace(_tick_count=75600)
    ctx.user_facing_self_model = FakeSelfModel(ctx)
    return ctx


@pytest.fixture(autouse=True)
def fake_readers(monkeypatch):
    monkeypatch.setattr(
        "agent_core.self_perception.perception.LimitationReporter",
        FakeLimitationReporter,
    )
    monkeypatch.setattr(
        "agent_core.self_perception.perception.ToolCapabilityRegistry",
        FakeToolCapabilityRegistry,
    )


def make_perception(tmp_path: Path, ctx, bulletin_store=None) -> SelfPerception:
    return SelfPerception(
        ctx=ctx,
        snapshot_store=SnapshotStore(tmp_path / "self_state_snapshots.jsonl"),
        bulletin_store=bulletin_store,
    )


def test_snapshot_schema_complete(tmp_path, fake_ctx):
    snapshot = make_perception(tmp_path, fake_ctx).take_snapshot()

    assert set(snapshot) == {
        "snapshot_id",
        "timestamp",
        "iso_timestamp",
        "tick_count",
        "mode",
        "mode_label",
        "identity",
        "capabilities",
        "external_services",
        "limitations",
        "knowledge",
    }
    assert snapshot["snapshot_id"].startswith("sps-")
    assert isinstance(snapshot["timestamp"], float)
    assert isinstance(snapshot["iso_timestamp"], str)
    assert isinstance(snapshot["tick_count"], int)
    assert isinstance(snapshot["mode"], str)
    assert isinstance(snapshot["mode_label"], str)
    assert isinstance(snapshot["identity"], dict)
    assert isinstance(snapshot["capabilities"], dict)
    assert isinstance(snapshot["external_services"], list)
    assert isinstance(snapshot["limitations"], dict)
    assert isinstance(snapshot["knowledge"], dict)


def test_snapshot_persisted(tmp_path, fake_ctx):
    store = SnapshotStore(tmp_path / "self_state_snapshots.jsonl")
    sp = SelfPerception(fake_ctx, snapshot_store=store)

    before = store.path.read_text(encoding="utf-8").splitlines() if store.path.exists() else []
    snapshot = sp.take_snapshot()
    after = store.path.read_text(encoding="utf-8").splitlines()

    assert len(after) == len(before) + 1
    assert store.load_latest() == snapshot


def test_no_diff_no_bulletin(tmp_path, fake_ctx):
    bulletin = FakeBulletinStore()
    sp = make_perception(tmp_path, fake_ctx, bulletin)

    sp.take_snapshot()
    sp.take_snapshot()

    assert len(bulletin.calls) == 1


def test_diff_triggers_bulletin(tmp_path, fake_ctx):
    bulletin = FakeBulletinStore()
    sp = make_perception(tmp_path, fake_ctx, bulletin)

    sp.take_snapshot()
    fake_ctx.mode = "REDUCED"
    sp.take_snapshot()

    assert len(bulletin.calls) == 2
    assert "mode" in bulletin.calls[-1]["metadata"]["diff_fields"]


def test_is_fresh_threshold(tmp_path, fake_ctx, monkeypatch):
    current_time = 1000.0
    monkeypatch.setattr("agent_core.self_perception.perception.time.time", lambda: current_time)
    sp = make_perception(tmp_path, fake_ctx)

    assert make_perception(tmp_path / "empty", fake_ctx).is_fresh(300) is False
    sp.take_snapshot()
    assert sp.is_fresh(300) is True

    current_time = 1401.0
    assert sp.is_fresh(300) is False


def test_telegram_format_cold_start(tmp_path, fake_ctx):
    sp = make_perception(tmp_path, fake_ctx)

    assert (
        sp.format_status_for_telegram()
        == "Brak snapshotu. Pierwszy zapisze sie w ciagu 30 min."
    )


def test_telegram_format_with_snapshot(tmp_path, fake_ctx):
    sp = make_perception(tmp_path, fake_ctx)
    sp.take_snapshot()

    text = sp.format_status_for_telegram()

    assert "Stan Marii" in text
    assert "Tryb:" in text
    assert "Zdolnosci:" in text
    assert "Serwisy:" in text
    assert "Ograniczenia" in text
    assert all(ord(ch) < 0x1F300 for ch in text)
