"""Tests for Faza 3: Operational Perception.

Covers: HolidaySensor, SystemSensor, WorkspaceSensor, SalienceFilter, PerceptionFusion.
"""

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_core.weather.holiday_sensor import (
    HolidayInfo,
    HolidaySensor,
    _easter_date,
)
from agent_core.homeostasis.sensors.system_sensor import SystemHealth, SystemSensor
from agent_core.homeostasis.sensors.workspace_sensor import (
    WorkspaceChange,
    WorkspaceSensor,
    WorkspaceSnapshot,
)
from agent_core.perception.salience_filter import SalienceFilter
from agent_core.perception.fusion import PerceptionFusion
from agent_core.operator.operator_model import OperatorModel
from agent_core.tests.spec_helpers import specced


# =============================================================================
# HolidaySensor
# =============================================================================

class TestEasterDate:
    def test_2026(self):
        assert _easter_date(2026) == date(2026, 4, 5)

    def test_2027(self):
        assert _easter_date(2027) == date(2027, 3, 28)

    def test_2024(self):
        assert _easter_date(2024) == date(2024, 3, 31)

    def test_2025(self):
        assert _easter_date(2025) == date(2025, 4, 20)


class TestHolidaySensor:
    def test_holiday_list_not_empty(self):
        sensor = HolidaySensor()
        holidays = sensor._get_year(2026)
        assert len(holidays) >= 15  # PL + DE

    def test_new_year(self):
        sensor = HolidaySensor()
        holidays = sensor._get_year(2026)
        jan1 = [h for h in holidays if h.holiday_date == date(2026, 1, 1)]
        assert len(jan1) == 1
        assert "Nowy Rok" in jan1[0].name_pl

    def test_easter_2026(self):
        sensor = HolidaySensor()
        holidays = sensor._get_year(2026)
        easter = [h for h in holidays if h.name_pl == "Wielkanoc"]
        assert len(easter) == 1
        assert easter[0].holiday_date == date(2026, 4, 5)

    def test_easter_monday_2026(self):
        sensor = HolidaySensor()
        holidays = sensor._get_year(2026)
        monday = [h for h in holidays if "Poniedzialek Wielkanocny" in h.name_pl]
        assert len(monday) == 1
        assert monday[0].holiday_date == date(2026, 4, 6)

    def test_corpus_christi_2026(self):
        sensor = HolidaySensor()
        holidays = sensor._get_year(2026)
        bc = [h for h in holidays if "Boze Cialo" in h.name_pl]
        assert len(bc) == 1
        # Easter + 60 days
        assert bc[0].holiday_date == date(2026, 4, 5) + timedelta(days=60)

    def test_german_holidays_present(self):
        sensor = HolidaySensor()
        holidays = sensor._get_year(2026)
        de_only = [h for h in holidays if h.country == "DE"]
        assert len(de_only) >= 3  # Karfreitag, Himmelfahrt, Pfingstmontag, Einheit

    @patch("agent_core.weather.holiday_sensor.date")
    def test_get_today_on_holiday(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 1)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        sensor = HolidaySensor()
        h = sensor.get_today()
        assert h is not None
        assert "Nowy Rok" in h.name_pl

    @patch("agent_core.weather.holiday_sensor.date")
    def test_get_today_normal_day(self, mock_date):
        mock_date.today.return_value = date(2026, 3, 15)  # not a holiday
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        sensor = HolidaySensor()
        assert sensor.get_today() is None

    @patch("agent_core.weather.holiday_sensor.date")
    def test_get_upcoming(self, mock_date):
        mock_date.today.return_value = date(2026, 4, 3)  # 2 days before Easter
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        sensor = HolidaySensor()
        upcoming = sensor.get_upcoming(3)
        assert len(upcoming) >= 1
        assert upcoming[0].holiday_date == date(2026, 4, 5)

    @patch("agent_core.weather.holiday_sensor.date")
    def test_get_next(self, mock_date):
        mock_date.today.return_value = date(2026, 6, 1)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        sensor = HolidaySensor()
        nxt = sensor.get_next()
        assert nxt is not None
        assert nxt.holiday_date > date(2026, 6, 1)

    @patch("agent_core.weather.holiday_sensor.date")
    def test_format_today(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 1)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        sensor = HolidaySensor()
        text = sensor.format_today()
        assert text is not None
        assert "Nowy Rok" in text
        assert "Neujahr" in text

    @patch("agent_core.weather.holiday_sensor.date")
    def test_format_upcoming(self, mock_date):
        mock_date.today.return_value = date(2026, 4, 4)  # 1 day before Easter
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        sensor = HolidaySensor()
        text = sensor.format_upcoming(3)
        assert text is not None
        assert "Jutro" in text
        assert "Wielkanoc" in text

    def test_sorted_by_date(self):
        sensor = HolidaySensor()
        holidays = sensor._get_year(2026)
        dates = [h.holiday_date for h in holidays]
        assert dates == sorted(dates)

    def test_cache(self):
        sensor = HolidaySensor()
        h1 = sensor._get_year(2026)
        h2 = sensor._get_year(2026)
        assert h1 is h2


# =============================================================================
# SystemSensor
# =============================================================================

class TestSystemHealth:
    def test_to_dict(self):
        h = SystemHealth(
            ollama_alive=True, ollama_latency_ms=50.5,
            service_restarts=0, service_uptime_sec=3600,
            disk_free_gb=100.5, disk_free_pct=45.2,
            storage_warning=False, timestamp=time.time(),
        )
        d = h.to_dict()
        assert d["ollama_alive"] is True
        assert d["disk_free_gb"] == 100.5

    def test_format_alerts_all_ok(self):
        h = SystemHealth(
            ollama_alive=True, ollama_latency_ms=50,
            service_restarts=0, service_uptime_sec=3600,
            disk_free_gb=100, disk_free_pct=50,
            storage_warning=False, timestamp=time.time(),
        )
        assert h.format_alerts() == []

    def test_format_alerts_problems(self):
        h = SystemHealth(
            ollama_alive=False, ollama_latency_ms=0,
            service_restarts=2, service_uptime_sec=60,
            disk_free_gb=3, disk_free_pct=5,
            storage_warning=True, timestamp=time.time(),
        )
        alerts = h.format_alerts()
        assert len(alerts) == 3
        assert any("Ollama" in a for a in alerts)
        assert any("restart" in a for a in alerts)
        assert any("miejsca" in a for a in alerts)


class TestSystemSensor:
    @patch("agent_core.homeostasis.sensors.system_sensor.shutil.disk_usage")
    @patch("agent_core.homeostasis.sensors.system_sensor.subprocess.run")
    @patch("agent_core.homeostasis.sensors.system_sensor.requests.get")
    def test_read_health(self, mock_get, mock_run, mock_disk):
        # Ollama alive
        mock_get.return_value = MagicMock(status_code=200)
        # Systemd - 0 restarts
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
        # Disk - 100GB free of 500GB
        mock_disk.return_value = MagicMock(
            free=100 * 1024**3, total=500 * 1024**3
        )

        sensor = SystemSensor(cache_ttl=0)
        health = sensor.read_health()
        assert health.ollama_alive is True
        assert health.disk_free_gb > 90
        assert health.storage_warning is False

    @patch("agent_core.homeostasis.sensors.system_sensor.requests.get")
    def test_ollama_dead(self, mock_get):
        mock_get.side_effect = Exception("connection refused")
        sensor = SystemSensor(cache_ttl=0)
        alive, latency = sensor._check_ollama()
        assert alive is False
        assert latency == 0.0

    def test_cache(self):
        sensor = SystemSensor(cache_ttl=999)
        # Prefill cache
        health = SystemHealth(
            ollama_alive=True, ollama_latency_ms=50,
            service_restarts=0, service_uptime_sec=100,
            disk_free_gb=50, disk_free_pct=30,
            storage_warning=False, timestamp=time.time(),
        )
        sensor._cached = health
        sensor._cached_at = time.time()

        result = sensor.read_health()
        assert result is health  # from cache


# =============================================================================
# WorkspaceSensor
# =============================================================================

class TestWorkspaceSensor:
    @pytest.fixture
    def workspace(self, tmp_path):
        # Create fake input/ dir
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "test1.txt").write_text("hello")
        (input_dir / "test2.txt").write_text("world")
        state = tmp_path / "state.json"
        return WorkspaceSensor(
            watch_dirs=[str(input_dir)],
            state_path=state,
            cache_ttl=0,
        )

    def test_first_scan_populates(self, workspace):
        snap = workspace.scan()
        # First scan: all files are "new" but no prior state = everything is new
        assert snap.total_files >= 2

    def test_second_scan_no_changes(self, workspace):
        workspace.scan()  # populate state
        snap = workspace.scan()
        assert len(snap.changes) == 0

    def test_detects_new_file(self, workspace, tmp_path):
        workspace.scan()  # populate state
        # Add new file
        input_dir = tmp_path / "input"
        (input_dir / "test3.txt").write_text("new file")
        snap = workspace.scan()
        new = [c for c in snap.changes if c.change_type == "new"]
        assert len(new) == 1
        assert "test3" in new[0].path

    def test_detects_modified_file(self, workspace, tmp_path):
        workspace.scan()
        # Modify existing file (need to change mtime)
        input_dir = tmp_path / "input"
        f = input_dir / "test1.txt"
        time.sleep(0.05)  # ensure different mtime
        f.write_text("modified content")
        snap = workspace.scan()
        modified = [c for c in snap.changes if c.change_type == "modified"]
        assert len(modified) == 1

    def test_ignores_pyc(self, workspace, tmp_path):
        workspace.scan()
        input_dir = tmp_path / "input"
        (input_dir / "test.pyc").write_bytes(b"bytecode")
        snap = workspace.scan()
        pyc = [c for c in snap.changes if ".pyc" in c.path]
        assert len(pyc) == 0

    def test_persistence(self, workspace, tmp_path):
        workspace.scan()
        # Create new sensor pointing to same state file
        input_dir = tmp_path / "input"
        ws2 = WorkspaceSensor(
            watch_dirs=[str(input_dir)],
            state_path=workspace._state_path,
            cache_ttl=0,
        )
        snap = ws2.scan()
        assert len(snap.changes) == 0  # state loaded, no changes

    def test_new_input_files_count(self, workspace, tmp_path):
        workspace.scan()
        input_dir = tmp_path / "input"
        (input_dir / "new1.txt").write_text("a")
        (input_dir / "new2.txt").write_text("b")
        snap = workspace.scan()
        assert snap.new_input_files == 2


# =============================================================================
# SalienceFilter
# =============================================================================

class TestSalienceFilter:
    def test_weather_salient(self):
        sf = SalienceFilter()
        assert sf.is_worth_telling("weather", {"salient": True}) is True

    def test_weather_not_salient(self):
        sf = SalienceFilter()
        assert sf.is_worth_telling("weather", {"salient": False}) is False

    def test_holiday_today(self):
        sf = SalienceFilter()
        assert sf.is_worth_telling("holiday", {"is_today": True, "days_until": 0}) is True

    def test_holiday_tomorrow(self):
        sf = SalienceFilter()
        assert sf.is_worth_telling("holiday", {"is_today": False, "days_until": 1}) is True

    def test_holiday_too_far(self):
        sf = SalienceFilter()
        assert sf.is_worth_telling("holiday", {"is_today": False, "days_until": 5}) is False

    def test_system_all_ok(self):
        sf = SalienceFilter()
        payload = {"ollama_alive": True, "service_restarts": 0, "storage_warning": False}
        assert sf.is_worth_telling("system", payload) is False

    def test_system_ollama_dead(self):
        sf = SalienceFilter()
        payload = {"ollama_alive": False, "service_restarts": 0, "storage_warning": False}
        assert sf.is_worth_telling("system", payload) is True

    def test_system_storage_warning(self):
        sf = SalienceFilter()
        payload = {"ollama_alive": True, "service_restarts": 0, "storage_warning": True}
        assert sf.is_worth_telling("system", payload) is True

    def test_workspace_new_files(self):
        sf = SalienceFilter()
        assert sf.is_worth_telling("workspace", {"new_input_files": 3}) is True

    def test_workspace_no_new(self):
        sf = SalienceFilter()
        assert sf.is_worth_telling("workspace", {"new_input_files": 0}) is False

    def test_unknown_channel_suppressed(self):
        sf = SalienceFilter()
        assert sf.is_worth_telling("unknown", {}) is False

    def test_dnd_suppresses(self):
        om = specced(OperatorModel)
        om.get_context.return_value = "jestem na urlopie"
        sf = SalienceFilter(operator_model=om)
        assert sf.is_worth_telling("holiday", {"is_today": True}) is False

    def test_dnd_allows_critical(self):
        om = specced(OperatorModel)
        om.get_context.return_value = "urlop"
        sf = SalienceFilter(operator_model=om)
        # Priority 0.9+ passes even in DND
        assert sf.is_worth_telling("system", {"priority": 0.95, "ollama_alive": False}) is True

    def test_quiet_hours_suppresses(self):
        om = specced(OperatorModel)
        om.get_context.return_value = None
        om.get_preference.return_value = [23, 6]  # quiet 23:00-06:00
        sf = SalienceFilter(operator_model=om)
        with patch("agent_core.perception.salience_filter.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=2)
            assert sf.is_worth_telling("holiday", {"is_today": True}) is False

    def test_no_operator_model(self):
        sf = SalienceFilter()
        # Should work fine without operator model
        assert sf.is_worth_telling("holiday", {"is_today": True}) is True


# =============================================================================
# PerceptionFusion
# =============================================================================

class TestPerceptionFusion:
    @pytest.fixture
    def fusion(self):
        f = PerceptionFusion()
        return f

    def test_empty_snapshot(self, fusion):
        data = fusion.snapshot_for_brief()
        assert data == {}

    def test_with_holiday(self, fusion):
        holiday_sensor = specced(HolidaySensor)
        holiday_sensor.get_today.return_value = HolidayInfo(
            name_pl="Nowy Rok", name_de="Neujahr",
            country="PL+DE", holiday_date=date(2026, 1, 1),
        )
        holiday_sensor.format_today.return_value = "Dzis swieto: Nowy Rok (Neujahr)"
        fusion.set_holiday_sensor(holiday_sensor)

        data = fusion.snapshot_for_brief()
        assert "holiday_today" in data
        assert "Nowy Rok" in data["holiday_today"]

    def test_with_system_alert(self, fusion):
        sys_sensor = specced(SystemSensor)
        health = SystemHealth(
            ollama_alive=False, ollama_latency_ms=0,
            service_restarts=0, service_uptime_sec=100,
            disk_free_gb=50, disk_free_pct=30,
            storage_warning=False, timestamp=time.time(),
        )
        sys_sensor.read_health.return_value = health
        fusion.set_system_sensor(sys_sensor)

        data = fusion.snapshot_for_brief()
        assert "system_alerts" in data
        assert any("Ollama" in a for a in data["system_alerts"])

    def test_with_workspace_changes(self, fusion):
        ws = specced(WorkspaceSensor)
        ws.scan.return_value = WorkspaceSnapshot(
            changes=(), total_files=10, new_input_files=3, timestamp=time.time(),
        )
        fusion.set_workspace_sensor(ws)

        data = fusion.snapshot_for_brief()
        assert data["new_input_files"] == 3

    def test_format_for_brief(self, fusion):
        holiday_sensor = specced(HolidaySensor)
        holiday_sensor.get_today.return_value = HolidayInfo(
            name_pl="Wielkanoc", name_de="Ostersonntag",
            country="PL+DE", holiday_date=date(2026, 4, 5),
        )
        holiday_sensor.format_today.return_value = "Dzis swieto: Wielkanoc"
        fusion.set_holiday_sensor(holiday_sensor)

        ws = specced(WorkspaceSensor)
        ws.scan.return_value = WorkspaceSnapshot(
            changes=(), total_files=10, new_input_files=2, timestamp=time.time(),
        )
        fusion.set_workspace_sensor(ws)

        lines = fusion.format_for_brief()
        assert any("Wielkanoc" in l for l in lines)
        assert any("plikow" in l for l in lines)

    def test_salience_filter_applied(self, fusion):
        ws = specced(WorkspaceSensor)
        ws.scan.return_value = WorkspaceSnapshot(
            changes=(), total_files=10, new_input_files=0, timestamp=time.time(),
        )
        fusion.set_workspace_sensor(ws)

        sf = specced(SalienceFilter)
        sf.is_worth_telling.return_value = False
        fusion.set_salience_filter(sf)

        data = fusion.snapshot_for_brief()
        assert "new_input_files" not in data

    def test_morning_brief_integration(self):
        """Verify perception lines appear in morning brief."""
        from agent_core.proactive.generators import ContentGenerators
        gen = ContentGenerators()
        gen.set_user_name_fn(lambda: "Eryk")
        gen.set_perception_fn(lambda: ["Dzis swieto: Wielkanoc", "2 nowych plikow w input/"])

        contact = gen._morning_summary()
        assert "Wielkanoc" in contact.message
        assert "plikow" in contact.message

    def test_morning_brief_no_perception(self):
        from agent_core.proactive.generators import ContentGenerators
        gen = ContentGenerators()
        gen.set_user_name_fn(lambda: "Eryk")

        contact = gen._morning_summary()
        assert contact is not None
        # Should still work without perception
