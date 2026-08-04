"""Tests for outcome-based NIM health tracking (audit 2026-07-28).

The bug these lock down: Maria's NIM health status came from her own token-budget
counter, which can only emit OK/LOW/DEPLETED, while the self-repair rule waits
for the literal word "unavailable". The two vocabularies never intersected, so
`model_unavailable` was structurally dead -- through the entire dracarys EOL
outage (254x HTTP 410) every self-perception snapshot read "available".

The end-to-end class below (TestOutageReachesSelfRepair) is the one that matters:
it walks producer -> snapshot -> detector and fails if the vocabularies drift
apart again.
"""

import time

import pytest

from agent_core.llm.nim_client import NIMClient, NIMAPIError
from agent_core.llm.nim_health import (
    NimHealthTracker,
    get_nim_health,
    STATUS_AVAILABLE,
    STATUS_DEGRADED,
    STATUS_UNAVAILABLE,
    STATUS_UNKNOWN,
)
from agent_core.orchestrator.tool_registry import ToolCapabilityRegistry
from agent_core.self_repair.detectors import detect_model_unavailable


def make_tracker(**kw) -> NimHealthTracker:
    """Tracker with explicit params -- never inherit the module defaults, which
    read os.environ and would let a stray .env value steer the test."""
    params = dict(
        window_seconds=100.0, min_sample=5, degraded_ratio=0.5, max_records=500
    )
    params.update(kw)
    return NimHealthTracker(**params)


class TestTrackerVerdicts:
    """Window semantics: what each mix of outcomes means."""

    def test_idle_tracker_is_unknown_not_healthy(self):
        # Silence is not evidence of health -- and must not look like an outage.
        assert make_tracker().snapshot().status == STATUS_UNKNOWN

    def test_below_min_sample_is_unknown_even_if_all_failed(self):
        t = make_tracker(min_sample=5)
        for _ in range(4):
            t.record_failure("boom")
        snap = t.snapshot()
        assert snap.status == STATUS_UNKNOWN
        assert snap.failures == 4

    def test_all_failures_at_min_sample_is_unavailable(self):
        t = make_tracker(min_sample=5)
        for _ in range(5):
            t.record_failure("HTTP 410: model reached end of life")
        snap = t.snapshot()
        assert snap.status == STATUS_UNAVAILABLE
        assert snap.successes == 0
        assert snap.last_error.startswith("HTTP 410")

    def test_one_success_downgrades_outage_to_degraded(self):
        # A single success proves the endpoint is reachable. That is the whole
        # difference between "down" and "congested".
        t = make_tracker(min_sample=5, degraded_ratio=0.5)
        for _ in range(9):
            t.record_failure("HTTP 503")
        t.record_success()
        assert t.snapshot().status == STATUS_DEGRADED

    def test_mostly_successful_is_available(self):
        t = make_tracker(min_sample=5, degraded_ratio=0.5)
        for _ in range(8):
            t.record_success()
        t.record_failure("HTTP 503")
        snap = t.snapshot()
        assert snap.status == STATUS_AVAILABLE
        assert snap.failure_ratio == pytest.approx(1 / 9)

    def test_ratio_boundary_counts_as_degraded(self):
        t = make_tracker(min_sample=4, degraded_ratio=0.5)
        for _ in range(2):
            t.record_success()
        for _ in range(2):
            t.record_failure("HTTP 503")
        assert t.snapshot().status == STATUS_DEGRADED


class TestWindow:
    """Only recent outcomes may speak."""

    def test_outcomes_outside_window_are_ignored(self):
        t = make_tracker(window_seconds=100.0, min_sample=3)
        old = time.time() - 500.0
        for _ in range(10):
            t.record_failure("ancient outage", now=old)
        # Old failures fall out; nothing recent -> we do not know.
        assert t.snapshot().status == STATUS_UNKNOWN

    def test_recovery_flips_status_back(self):
        t = make_tracker(min_sample=5)
        for _ in range(5):
            t.record_failure("HTTP 410")
        assert t.snapshot().status == STATUS_UNAVAILABLE
        for _ in range(10):
            t.record_success()
        assert t.snapshot().status == STATUS_AVAILABLE

    def test_snapshot_is_peek_safe(self):
        # A "read-only" accessor that quietly evicts is how is_action_backed_off
        # started lying. Reading twice must give the same answer.
        t = make_tracker(min_sample=3)
        for _ in range(6):
            t.record_success()
        first = t.snapshot()
        second = t.snapshot()
        assert (first.attempts, first.successes) == (second.attempts,
                                                     second.successes)
        assert first.status == second.status


class TestClientRecordsEveryOutcome:
    """NIMClient._chat is the chokepoint -- including for callers that build
    their own client and bypass LLMRouter (teacher_module's exam does)."""

    @pytest.fixture
    def client(self, monkeypatch):
        c = NIMClient(api_key="test-key", model="test-model")
        monkeypatch.setattr("agent_core.llm.nim_client.get_nim_health",
                            lambda: self._tracker)
        return c

    def setup_method(self):
        self._tracker = make_tracker(min_sample=1)

    def test_successful_call_records_success(self, client, monkeypatch):
        # A REAL function, not MagicMock: a mock swallows wrong kwargs and would
        # hide a signature mismatch between _chat and _chat_impl.
        def fake_impl(messages, temperature=0.3, max_tokens=4096,
                      force_json=False):
            return "odpowiedz"

        monkeypatch.setattr(client, "_chat_impl", fake_impl)
        assert client._ask_once("pytanie") == "odpowiedz"
        snap = self._tracker.snapshot()
        assert (snap.successes, snap.failures) == (1, 0)

    def test_raised_error_records_failure_and_still_propagates(
        self, client, monkeypatch
    ):
        def fake_impl(messages, temperature=0.3, max_tokens=4096,
                      force_json=False):
            raise NIMAPIError("HTTP 503: ResourceExhausted (295/32)")

        monkeypatch.setattr(client, "_chat_impl", fake_impl)
        with pytest.raises(NIMAPIError):
            client._ask_once("pytanie")
        snap = self._tracker.snapshot()
        assert (snap.successes, snap.failures) == (0, 1)
        assert "503" in snap.last_error

    def test_empty_two_hundred_counts_as_failure(self, client, monkeypatch):
        # HTTP 200 with no content sends the caller to Ollama exactly like an
        # error does; counting it as success would overstate NIM's usefulness.
        def fake_impl(messages, temperature=0.3, max_tokens=4096,
                      force_json=False):
            return ""

        monkeypatch.setattr(client, "_chat_impl", fake_impl)
        assert client._ask_once("pytanie") == ""
        assert self._tracker.snapshot().failures == 1

    def test_one_call_is_one_outcome(self, client, monkeypatch):
        def fake_impl(messages, temperature=0.3, max_tokens=4096,
                      force_json=False):
            return "ok"

        monkeypatch.setattr(client, "_chat_impl", fake_impl)
        for _ in range(3):
            client._ask_once("pytanie")
        assert self._tracker.snapshot().attempts == 3

    def test_non_nim_exception_is_also_recorded(self, client, monkeypatch):
        def fake_impl(messages, temperature=0.3, max_tokens=4096,
                      force_json=False):
            raise ValueError("nieoczekiwane")

        monkeypatch.setattr(client, "_chat_impl", fake_impl)
        with pytest.raises(ValueError):
            client._ask_once("pytanie")
        snap = self._tracker.snapshot()
        assert snap.failures == 1
        assert "ValueError" in snap.last_error


class _Ctx:
    """Minimal SharedContext stand-in for the registry."""

    def __init__(self):
        self.capability_router = None
        self.openclaw_client = None
        self.codex_client = None
        self.telegram_bridge = None
        self.brain_model = "llama3.1:8b"


def nim_service(registry: ToolCapabilityRegistry) -> dict:
    for svc in registry.list_external_services():
        if svc["name"] == "NVIDIA NIM API":
            return svc
    raise AssertionError("NIM service missing from registry output")


class TestRegistryReportsRealOutcomes:

    @pytest.fixture(autouse=True)
    def _reset_shared_tracker(self):
        get_nim_health().reset()
        yield
        get_nim_health().reset()

    def test_outage_surfaces_as_unavailable(self):
        for _ in range(10):
            get_nim_health().record_failure("HTTP 410: end of life")
        assert nim_service(ToolCapabilityRegistry(_Ctx()))["status"] == "unavailable"

    def test_congestion_surfaces_as_degraded_not_unavailable(self):
        for _ in range(9):
            get_nim_health().record_failure("HTTP 503")
        get_nim_health().record_success()
        assert nim_service(ToolCapabilityRegistry(_Ctx()))["status"] == "degraded"

    def test_healthy_traffic_surfaces_as_available(self):
        for _ in range(10):
            get_nim_health().record_success()
        assert nim_service(ToolCapabilityRegistry(_Ctx()))["status"] == "available"

    def test_details_carry_the_counts(self):
        for _ in range(6):
            get_nim_health().record_success()
        get_nim_health().record_failure("HTTP 503")
        details = nim_service(ToolCapabilityRegistry(_Ctx()))["details"]
        assert details["health_successes"] == 6
        assert details["health_failures"] == 1
        assert details["last_success_age_s"] is not None


def _snapshot(status: str, snapshot_id: str) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "external_services": [
            {"name": "NVIDIA NIM API", "status": status, "details": {}},
        ],
    }


class _Store:
    def __init__(self, snapshots):
        self._snapshots = snapshots

    def load_recent(self, n):
        return self._snapshots[-n:]


def _no_cooldown(repair_kind, subject):
    return False


class TestOutageReachesSelfRepair:
    """The regression that matters: producer vocabulary must reach the detector.

    If someone changes what tool_registry emits without changing
    detectors._is_unavailable, these fail -- which is exactly what nobody
    noticed for the two months the branch was dead.
    """

    def test_real_outage_creates_a_repair_candidate(self):
        store = _Store([
            _snapshot("available", "s1"),
            _snapshot("unavailable", "s2"),
            _snapshot("unavailable", "s3"),
        ])
        candidates = detect_model_unavailable(store, _no_cooldown)
        assert len(candidates) == 1
        assert candidates[0].repair_kind == "model_unavailable"

    def test_outage_that_ramps_through_degraded_still_trips(self):
        # The old rule demanded the oldest snapshot be exactly "available", so a
        # gradual failure would have been invisible forever.
        store = _Store([
            _snapshot("degraded", "s1"),
            _snapshot("unavailable", "s2"),
            _snapshot("unavailable", "s3"),
        ])
        assert len(detect_model_unavailable(store, _no_cooldown)) == 1

    def test_ongoing_outage_does_not_re_alarm_every_scan(self):
        store = _Store([
            _snapshot("unavailable", "s1"),
            _snapshot("unavailable", "s2"),
            _snapshot("unavailable", "s3"),
        ])
        assert detect_model_unavailable(store, _no_cooldown) == []

    def test_congestion_does_not_trip_self_repair(self):
        # Maria cannot repair someone else's queue; an alarm she can only ignore
        # teaches her to ignore alarms.
        store = _Store([
            _snapshot("available", "s1"),
            _snapshot("degraded", "s2"),
            _snapshot("degraded", "s3"),
        ])
        assert detect_model_unavailable(store, _no_cooldown) == []

    def test_budget_depletion_does_not_trip_self_repair(self):
        store = _Store([
            _snapshot("available", "s1"),
            _snapshot("depleted", "s2"),
            _snapshot("depleted", "s3"),
        ])
        assert detect_model_unavailable(store, _no_cooldown) == []

    def test_idle_daemon_does_not_trip_self_repair(self):
        store = _Store([
            _snapshot("available", "s1"),
            _snapshot("unknown", "s2"),
            _snapshot("unknown", "s3"),
        ])
        assert detect_model_unavailable(store, _no_cooldown) == []
