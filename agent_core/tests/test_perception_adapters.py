"""
Tests for Perception Adapters.

Contract reference: docs/CONTRACTS.md - Kontrakt 1, sekcja "Adaptery"
"""

import time
from dataclasses import dataclass
from typing import Optional

import pytest

from agent_core.perception.event import PerceptionEvent, PerceptionSource
from agent_core.perception.adapters.sensor_adapter import SensorAdapter
from agent_core.perception.adapters.user_adapter import UserAdapter
from agent_core.perception.adapters.learning_adapter import LearningAdapter
from agent_core.perception.adapters.exam_adapter import ExamAdapter
from agent_core.perception.adapters.consciousness_adapter import ConsciousnessAdapter
from agent_core.perception.adapters.teacher_adapter import TeacherAdapter


# --- Mock dataclasses for sensors (avoid importing real ones with psutil deps) ---

@dataclass
class MockResourceMetrics:
    timestamp: float = 1000.0
    ram_used_mb: float = 6000.0
    ram_total_mb: float = 32000.0
    ram_available_mb: float = 26000.0
    swap_used_pct: float = 5.0
    cpu_percent: float = 15.3
    load_avg_1m: float = 0.5
    load_avg_5m: float = 0.4
    load_avg_15m: float = 0.3
    disk_used_pct: float = 45.0
    disk_io_queue_depth: int = 0
    process_count: int = 120
    temp_c: float = 52.0
    inference_latency_ms: float = 450.0

    @property
    def ram_available_pct(self) -> float:
        return (self.ram_available_mb / self.ram_total_mb) * 100


@dataclass
class MockCognitiveMetrics:
    timestamp: float = 1000.0
    context_coherence: float = 0.92
    context_tokens: int = 1024
    inference_latency_ms: float = 300.0
    latency_p50_ms: float = 280.0
    latency_p99_ms: float = 500.0
    error_count_1h: int = 2
    goal_stack_depth: int = 3
    memory_entries: int = 150
    contradiction_count: int = 0
    episodic_freshness_sec: float = 60.0
    attention_fragmentation: float = 0.15
    task_completion_ratio: float = 0.85


@dataclass
class MockThermalMetrics:
    timestamp: float = 1000.0
    cpu_temp_c: float = 55.0
    is_throttling: bool = False
    fan_speed_rpm: Optional[int] = None


@dataclass
class MockPowerMetrics:
    timestamp: float = 1000.0
    uptime_seconds: float = 3600.0
    voltage_v: Optional[float] = None
    is_on_battery: bool = False
    last_shutdown_clean: bool = True


@dataclass
class MockTimeMetrics:
    timestamp: float = 1000.0
    hour_of_day: int = 14
    day_of_week: int = 1  # Tuesday
    session_duration_sec: float = 1800.0
    last_interaction_sec: float = 30.0
    idle_streak_sec: float = 30.0


# --- SensorAdapter Tests ---

class TestSensorAdapter:
    """Tests for SensorAdapter - all 5 sensor types."""

    def test_resource_reading(self):
        """ResourceMetrics -> resource_reading event."""
        metrics = MockResourceMetrics()
        event = SensorAdapter.from_resource_metrics(metrics)

        assert isinstance(event, PerceptionEvent)
        assert event.source == PerceptionSource.SENSOR
        assert event.event_type == "resource_reading"
        assert event.priority == 0.3
        assert event.ttl == 5.0
        assert event.timestamp == 1000.0
        assert event.payload["ram_available_mb"] == 26000.0
        assert event.payload["cpu_percent"] == 15.3
        assert event.payload["temp_c"] == 52.0
        assert event.payload["disk_used_pct"] == 45.0
        assert event.payload["inference_latency_ms"] == 450.0
        assert event.payload["swap_used_pct"] == 5.0
        assert event.payload["load_avg_1m"] == 0.5
        assert "ram_available_pct" in event.payload

    def test_cognitive_reading(self):
        """CognitiveMetrics -> cognitive_reading event."""
        metrics = MockCognitiveMetrics()
        event = SensorAdapter.from_cognitive_metrics(metrics)

        assert event.source == PerceptionSource.SENSOR
        assert event.event_type == "cognitive_reading"
        assert event.priority == 0.3
        assert event.payload["context_coherence"] == 0.92
        assert event.payload["inference_latency_ms"] == 300.0
        assert event.payload["error_count_1h"] == 2
        assert event.payload["goal_stack_depth"] == 3
        assert event.payload["memory_entries"] == 150
        assert event.payload["contradiction_count"] == 0
        assert event.payload["attention_fragmentation"] == 0.15

    def test_thermal_reading(self):
        """ThermalMetrics -> thermal_reading event."""
        metrics = MockThermalMetrics(cpu_temp_c=65.0, is_throttling=True)
        event = SensorAdapter.from_thermal_metrics(metrics)

        assert event.event_type == "thermal_reading"
        assert event.payload["cpu_temp_c"] == 65.0
        assert event.payload["is_throttling"] is True
        assert "fan_speed_rpm" not in event.payload  # None -> not included

    def test_thermal_reading_with_fan(self):
        """ThermalMetrics with fan speed."""
        metrics = MockThermalMetrics(fan_speed_rpm=2400)
        event = SensorAdapter.from_thermal_metrics(metrics)

        assert event.payload["fan_speed_rpm"] == 2400

    def test_power_reading(self):
        """PowerMetrics -> power_reading event."""
        metrics = MockPowerMetrics(uptime_seconds=7200.0, is_on_battery=True)
        event = SensorAdapter.from_power_metrics(metrics)

        assert event.event_type == "power_reading"
        assert event.payload["uptime_seconds"] == 7200.0
        assert event.payload["is_on_battery"] is True
        assert "voltage_v" not in event.payload

    def test_power_reading_with_voltage(self):
        """PowerMetrics with voltage."""
        metrics = MockPowerMetrics(voltage_v=12.1)
        event = SensorAdapter.from_power_metrics(metrics)

        assert event.payload["voltage_v"] == 12.1

    def test_time_reading(self):
        """TimeMetrics -> time_reading event."""
        metrics = MockTimeMetrics()
        event = SensorAdapter.from_time_metrics(metrics)

        assert event.event_type == "time_reading"
        assert event.payload["idle_streak_sec"] == 30.0
        assert event.payload["hour_of_day"] == 14
        assert event.payload["session_duration_sec"] == 1800.0
        assert event.payload["day_of_week"] == 1

    def test_parent_event_id_passed(self):
        """All sensor adapters should pass parent_event_id."""
        parent_id = "parent-123"
        metrics = MockResourceMetrics()
        event = SensorAdapter.from_resource_metrics(metrics, parent_event_id=parent_id)
        assert event.parent_event_id == parent_id

    def test_timestamp_from_metrics(self):
        """Adapter should use timestamp from metrics, not current time."""
        metrics = MockResourceMetrics(timestamp=42.0)
        event = SensorAdapter.from_resource_metrics(metrics)
        assert event.timestamp == 42.0


# --- UserAdapter Tests ---

class TestUserAdapter:
    """Tests for UserAdapter."""

    def test_user_message(self):
        """Text message -> user_message event."""
        event = UserAdapter.from_message("Co wiesz o fizyce?")

        assert event.source == PerceptionSource.USER
        assert event.event_type == "user_message"
        assert event.priority == 0.9
        assert event.ttl == 0.0
        assert event.payload["text"] == "Co wiesz o fizyce?"
        assert event.payload["channel"] == "repl"

    def test_user_message_webui(self):
        """WebUI message with custom channel."""
        event = UserAdapter.from_message("hello", channel="webui", user_id="user1")

        assert event.payload["channel"] == "webui"
        assert event.payload["user_id"] == "user1"

    def test_user_message_no_user_id(self):
        """user_id should not be in payload when not provided."""
        event = UserAdapter.from_message("test")
        assert "user_id" not in event.payload

    def test_user_command(self):
        """REPL command -> user_command event."""
        event = UserAdapter.from_command("/learn", args="physics.txt")

        assert event.source == PerceptionSource.USER
        assert event.event_type == "user_command"
        assert event.priority == 0.9
        assert event.payload["command"] == "/learn"
        assert event.payload["args"] == "physics.txt"

    def test_user_command_default_channel(self):
        """Default channel 'repl' should not be in payload for commands."""
        event = UserAdapter.from_command("/homeostasis")
        assert "channel" not in event.payload

    def test_user_command_webui_channel(self):
        """Non-default channel should be included."""
        event = UserAdapter.from_command("/learn", channel="webui")
        assert event.payload["channel"] == "webui"


# --- LearningAdapter Tests ---

class TestLearningAdapter:
    """Tests for LearningAdapter."""

    def test_chunk_learned(self):
        """learn_next_chunk result -> chunk_learned event."""
        event = LearningAdapter.from_chunk_learned(
            file_id="physics.txt",
            chunk_index=3,
            chunks_total=8,
        )

        assert event.source == PerceptionSource.LEARNING
        assert event.event_type == "chunk_learned"
        assert event.priority == 0.7
        assert event.ttl == 300.0
        assert event.payload["file_id"] == "physics.txt"
        assert event.payload["chunk_index"] == 3
        assert event.payload["chunks_total"] == 8
        assert "summary_preview" not in event.payload

    def test_chunk_learned_with_preview(self):
        """Chunk learned with summary preview."""
        event = LearningAdapter.from_chunk_learned(
            file_id="quantum.txt",
            chunk_index=0,
            chunks_total=5,
            summary_preview="Fizyka kwantowa opisuje...",
        )
        assert event.payload["summary_preview"] == "Fizyka kwantowa opisuje..."

    def test_chunk_learned_with_parent(self):
        """Chunk learned caused by teacher decision."""
        event = LearningAdapter.from_chunk_learned(
            file_id="bio.txt",
            chunk_index=1,
            chunks_total=4,
            parent_event_id="teacher-decision-xyz",
        )
        assert event.parent_event_id == "teacher-decision-xyz"

    def test_file_scan_result(self):
        """File scan -> file_scan_result event."""
        event = LearningAdapter.from_file_scan(
            new_files=2,
            changed_files=1,
            total_files=15,
        )

        assert event.event_type == "file_scan_result"
        assert event.priority == 0.5
        assert event.payload["new_files"] == 2
        assert event.payload["changed_files"] == 1
        assert event.payload["total_files"] == 15

    def test_sandbox_promoted(self):
        """Sandbox promoted event."""
        event = LearningAdapter.from_sandbox_promoted(
            session_id="sess_abc123",
            files_promoted=2,
            chunks_promoted=8,
        )

        assert event.event_type == "sandbox_promoted"
        assert event.priority == 0.7
        assert event.payload["session_id"] == "sess_abc123"
        assert event.payload["files_promoted"] == 2

    def test_sandbox_discarded(self):
        """Sandbox discarded event."""
        event = LearningAdapter.from_sandbox_discarded(
            session_id="sess_xyz",
            reason="timeout_24h",
        )

        assert event.event_type == "sandbox_discarded"
        assert event.priority == 0.3
        assert event.payload["reason"] == "timeout_24h"


# --- ExamAdapter Tests ---

class TestExamAdapter:
    """Tests for ExamAdapter."""

    def test_exam_result_passed(self):
        """Passed exam -> exam_result event."""
        event = ExamAdapter.from_exam_result(
            file_id="quantum.txt",
            score=0.85,
            passed=True,
            attempt=1,
        )

        assert event.source == PerceptionSource.EXAM
        assert event.event_type == "exam_result"
        assert event.priority == 0.8
        assert event.ttl == 300.0
        assert event.payload["file_id"] == "quantum.txt"
        assert event.payload["score"] == 0.85
        assert event.payload["passed"] is True
        assert event.payload["attempt"] == 1
        assert "num_questions" not in event.payload

    def test_exam_result_failed(self):
        """Failed exam."""
        event = ExamAdapter.from_exam_result(
            file_id="math.txt",
            score=0.4,
            passed=False,
            attempt=2,
            num_questions=6,
        )

        assert event.payload["passed"] is False
        assert event.payload["score"] == 0.4
        assert event.payload["attempt"] == 2
        assert event.payload["num_questions"] == 6

    def test_exam_with_parent(self):
        """Exam triggered by teacher decision."""
        event = ExamAdapter.from_exam_result(
            file_id="test.txt",
            score=0.9,
            passed=True,
            attempt=1,
            parent_event_id="teacher-review-abc",
        )
        assert event.parent_event_id == "teacher-review-abc"


# --- ConsciousnessAdapter Tests ---

class TestConsciousnessAdapter:
    """Tests for ConsciousnessAdapter."""

    def test_trait_emerged(self):
        """Trait emergence -> trait_emerged event."""
        event = ConsciousnessAdapter.from_trait_emerged(
            trait="wytrwala",
            score=0.45,
            previous_score=0.38,
        )

        assert event.source == PerceptionSource.CONSCIOUSNESS
        assert event.event_type == "trait_emerged"
        assert event.priority == 0.5
        assert event.ttl == 300.0
        assert event.payload["trait"] == "wytrwala"
        assert event.payload["score"] == 0.45
        assert event.payload["previous_score"] == 0.38

    def test_trait_emerged_no_previous(self):
        """Trait emerged without previous score."""
        event = ConsciousnessAdapter.from_trait_emerged(trait="refleksyjna", score=0.42)
        assert "previous_score" not in event.payload

    def test_trait_faded(self):
        """Trait fading -> trait_faded event."""
        event = ConsciousnessAdapter.from_trait_faded(
            trait="spoleczna",
            score=0.35,
            previous_score=0.42,
        )

        assert event.event_type == "trait_faded"
        assert event.payload["trait"] == "spoleczna"
        assert event.payload["score"] == 0.35

    def test_dream_generated(self):
        """Dreams generated -> dream_generated event."""
        event = ConsciousnessAdapter.from_dream_generated(
            dream_count=3,
            session_id="sleep-sess-42",
            themes=["fizyka", "historia", "matematyka"],
        )

        assert event.event_type == "dream_generated"
        assert event.payload["dream_count"] == 3
        assert event.payload["session_id"] == "sleep-sess-42"
        assert event.payload["themes"] == ["fizyka", "historia", "matematyka"]

    def test_dream_generated_no_themes(self):
        """Dreams without themes."""
        event = ConsciousnessAdapter.from_dream_generated(dream_count=1, session_id="s1")
        assert "themes" not in event.payload

    def test_sleep_cycle(self):
        """Sleep cycle complete -> sleep_cycle event."""
        event = ConsciousnessAdapter.from_sleep_cycle(
            phases_completed=4,
            dream_count=2,
        )

        assert event.event_type == "sleep_cycle"
        assert event.payload["phases_completed"] == 4
        assert event.payload["dream_count"] == 2

    def test_sleep_cycle_no_dreams(self):
        """Sleep cycle without dream count."""
        event = ConsciousnessAdapter.from_sleep_cycle(phases_completed=3)
        assert "dream_count" not in event.payload


# --- TeacherAdapter Tests ---

class TestTeacherAdapter:
    """Tests for TeacherAdapter."""

    def test_teacher_decision(self):
        """Strategy decision -> teacher_decision event."""
        event = TeacherAdapter.from_decision(
            strategy_type="continue",
            target_file_id="physics.txt",
            reason="3/8 chunks done",
            iteration=2,
        )

        assert event.source == PerceptionSource.TEACHER
        assert event.event_type == "teacher_decision"
        assert event.priority == 0.5
        assert event.ttl == 300.0
        assert event.payload["strategy_type"] == "continue"
        assert event.payload["target_file_id"] == "physics.txt"
        assert event.payload["reason"] == "3/8 chunks done"
        assert event.payload["iteration"] == 2

    def test_teacher_decision_minimal(self):
        """Decision with only required fields."""
        event = TeacherAdapter.from_decision(
            strategy_type="new_file",
            target_file_id="biology.txt",
        )

        assert event.payload["strategy_type"] == "new_file"
        assert "reason" not in event.payload
        assert "iteration" not in event.payload

    def test_session_complete(self):
        """Session complete -> teacher_session_complete event."""
        event = TeacherAdapter.from_session_complete(
            chunks_learned=5,
            exams_run=2,
            exams_passed=2,
        )

        assert event.event_type == "teacher_session_complete"
        assert event.payload["chunks_learned"] == 5
        assert event.payload["exams_run"] == 2
        assert event.payload["exams_passed"] == 2
        assert "errors" not in event.payload

    def test_session_complete_with_errors(self):
        """Session complete with errors."""
        event = TeacherAdapter.from_session_complete(
            chunks_learned=3,
            exams_run=1,
            exams_passed=0,
            errors=["LLM timeout", "JSONL parse error"],
        )

        assert event.payload["errors"] == ["LLM timeout", "JSONL parse error"]


# --- Integration Tests ---

class TestAdapterIntegration:
    """Cross-adapter integration tests."""

    def test_causal_chain_teacher_to_learning_to_exam(self):
        """Full causal chain: teacher -> learning -> exam."""
        # Teacher decides to continue learning
        teacher_event = TeacherAdapter.from_decision(
            strategy_type="continue",
            target_file_id="physics.txt",
        )

        # Learning executes
        learn_event = LearningAdapter.from_chunk_learned(
            file_id="physics.txt",
            chunk_index=4,
            chunks_total=8,
            parent_event_id=teacher_event.event_id,
        )

        # Exam triggered
        exam_event = ExamAdapter.from_exam_result(
            file_id="physics.txt",
            score=0.85,
            passed=True,
            attempt=1,
            parent_event_id=learn_event.event_id,
        )

        # Verify chain
        assert teacher_event.parent_event_id is None
        assert learn_event.parent_event_id == teacher_event.event_id
        assert exam_event.parent_event_id == learn_event.event_id

        # Verify sources
        assert teacher_event.source == PerceptionSource.TEACHER
        assert learn_event.source == PerceptionSource.LEARNING
        assert exam_event.source == PerceptionSource.EXAM

    def test_all_adapters_produce_valid_events(self):
        """Every adapter method should produce a valid PerceptionEvent."""
        events = [
            SensorAdapter.from_resource_metrics(MockResourceMetrics()),
            SensorAdapter.from_cognitive_metrics(MockCognitiveMetrics()),
            SensorAdapter.from_thermal_metrics(MockThermalMetrics()),
            SensorAdapter.from_power_metrics(MockPowerMetrics()),
            SensorAdapter.from_time_metrics(MockTimeMetrics()),
            UserAdapter.from_message("test"),
            UserAdapter.from_command("/test"),
            LearningAdapter.from_chunk_learned("f.txt", 0, 1),
            LearningAdapter.from_file_scan(1, 0, 5),
            LearningAdapter.from_sandbox_promoted("s1", 1, 3),
            LearningAdapter.from_sandbox_discarded("s2", "timeout"),
            ExamAdapter.from_exam_result("f.txt", 0.8, True, 1),
            ConsciousnessAdapter.from_trait_emerged("ciekawska", 0.5),
            ConsciousnessAdapter.from_trait_faded("spoleczna", 0.3),
            ConsciousnessAdapter.from_dream_generated(2, "s1"),
            ConsciousnessAdapter.from_sleep_cycle(4),
            TeacherAdapter.from_decision("continue", "f.txt"),
            TeacherAdapter.from_session_complete(3, 1, 1),
        ]

        for event in events:
            assert isinstance(event, PerceptionEvent), f"Not a PerceptionEvent: {event}"
            assert event.event_id is not None
            assert isinstance(event.source, PerceptionSource)
            assert isinstance(event.event_type, str)
            assert 0.0 <= event.priority <= 1.0
            assert event.timestamp > 0
            assert isinstance(event.payload, dict)

    def test_all_event_ids_unique(self):
        """All generated events should have unique event_ids."""
        events = [
            SensorAdapter.from_resource_metrics(MockResourceMetrics()),
            SensorAdapter.from_resource_metrics(MockResourceMetrics()),
            UserAdapter.from_message("a"),
            UserAdapter.from_message("b"),
        ]
        ids = [e.event_id for e in events]
        assert len(set(ids)) == len(ids)
