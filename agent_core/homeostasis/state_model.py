"""
State Model - Dataclasses for homeostasis state

Defines core data structures:
- Mode: Operating mode enum (ACTIVE, REDUCED, SLEEP, SURVIVAL)
- ResourceMetrics: Hardware resource measurements
- CognitiveMetrics: LLM and memory state measurements
- SystemState: Aggregate system state

Spec reference: homeostasis_spec.md lines 900-931
"""

import time
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


class Mode(Enum):
    """
    Operating modes for homeostasis system.

    Spec: homeostasis_spec.md section 3.1 (lines 243-290)

    ACTIVE: Full capability, all modules enabled
    REDUCED: Throttled resources, background tasks paused
    SLEEP: LLM unloaded, async consolidation only
    SURVIVAL: Emergency mode, core loop only
    """
    ACTIVE = "active"
    REDUCED = "reduced"
    SLEEP = "sleep"
    SURVIVAL = "survival"


@dataclass
class ResourceMetrics:
    """
    Hardware resource measurements.

    Spec: homeostasis_spec.md lines 907-915
    """
    timestamp: float

    # Memory
    ram_used_mb: float
    ram_total_mb: float
    ram_available_mb: float
    swap_used_pct: float

    # CPU
    cpu_percent: float
    load_avg_1m: float
    load_avg_5m: float
    load_avg_15m: float

    # Disk
    disk_used_pct: float
    disk_io_queue_depth: int

    # Process
    process_count: int

    # Temperature (from ThermalSensor)
    temp_c: float

    # LLM latency (from CognitiveSensor)
    inference_latency_ms: float

    @property
    def ram_available_pct(self) -> float:
        """Calculate available RAM percentage."""
        if self.ram_total_mb <= 0:
            return 0.0
        return (self.ram_available_mb / self.ram_total_mb) * 100

    @property
    def memory_pressure(self) -> float:
        """Calculate memory pressure (0-100, higher = more pressure)."""
        return 100 - self.ram_available_pct


@dataclass
class CognitiveMetrics:
    """
    Cognitive state measurements.

    Spec: homeostasis_spec.md lines 917-923
    """
    timestamp: float

    # LLM state
    context_coherence: float  # 0-1
    context_tokens: int
    inference_latency_ms: float
    latency_p50_ms: float
    latency_p99_ms: float

    # Error tracking
    error_count_1h: int

    # Intent stability
    goal_stack_depth: int

    # Memory state
    memory_entries: int
    contradiction_count: int
    episodic_freshness_sec: float

    # Attention
    attention_fragmentation: float  # 0-1

    # Performance
    task_completion_ratio: float  # 0-1

    @property
    def coherence_ok(self) -> bool:
        """Check if coherence is acceptable (>0.85)."""
        return self.context_coherence > 0.85

    @property
    def errors_high(self) -> bool:
        """Check if error rate is elevated (>20/hour)."""
        return self.error_count_1h > 20

    @property
    def goal_stack_runaway(self) -> bool:
        """Check if goal stack is too deep (>25)."""
        return self.goal_stack_depth > 25


@dataclass
class SystemState:
    """
    Aggregate system state.

    Spec: homeostasis_spec.md lines 925-931
    """
    mode: Mode
    health_score: float  # 0-1
    last_mode_change_time: float
    alerts: List[str] = field(default_factory=list)
    idle_seconds: float = 0

    # Detailed state (populated by interpreter)
    interpreted_state: Dict[str, Any] = field(default_factory=dict)

    @property
    def mode_duration_seconds(self) -> float:
        """Get duration in current mode."""
        return time.time() - self.last_mode_change_time

    def has_critical_alert(self) -> bool:
        """Check if any CRITICAL alerts exist."""
        return any("CRITICAL" in alert for alert in self.alerts)

    def has_warning(self) -> bool:
        """Check if any WARNING or ALERT exists."""
        return any(
            "WARNING" in alert or "ALERT" in alert
            for alert in self.alerts
        )


@dataclass
class SnapshotData:
    """
    Data structure for system snapshots.

    Spec: homeostasis_spec.md lines 468-507
    """
    timestamp: float
    uptime_seconds: float
    mode: Mode

    # Memory state hashes and metadata
    episodic_memory_version: int
    episodic_memory_size_mb: float
    episodic_memory_hash: str
    episodic_memory_entries: int
    episodic_freshness_sec: float

    semantic_model_version: int
    semantic_node_count: int
    semantic_model_hash: str
    semantic_consistency_score: float

    # Cognitive state
    active_goal_stack: List[str] = field(default_factory=list)
    current_topic_embedding: List[float] = field(default_factory=list)
    error_rate_recent: float = 0.0

    # Homeostasis state
    health_score: float = 1.0
    resource_headroom: Dict[str, float] = field(default_factory=dict)
    last_mode_transition: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp,
            "uptime_seconds": self.uptime_seconds,
            "mode": self.mode.value,
            "episodic_memory": {
                "version": self.episodic_memory_version,
                "size_mb": self.episodic_memory_size_mb,
                "hash": self.episodic_memory_hash,
                "entries": self.episodic_memory_entries,
                "freshness_seconds": self.episodic_freshness_sec,
            },
            "semantic_model": {
                "version": self.semantic_model_version,
                "node_count": self.semantic_node_count,
                "hash": self.semantic_model_hash,
                "consistency_score": self.semantic_consistency_score,
            },
            "context_snapshot": {
                "active_goal_stack": self.active_goal_stack,
                "current_topic_embedding": self.current_topic_embedding,
                "error_rate_recent": self.error_rate_recent,
            },
            "homeostasis_state": {
                "mode": self.mode.value,
                "health_score": self.health_score,
                "resource_headroom": self.resource_headroom,
                "last_mode_transition": self.last_mode_transition,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SnapshotData":
        """Create from dictionary."""
        return cls(
            timestamp=data["timestamp"],
            uptime_seconds=data["uptime_seconds"],
            mode=Mode(data["mode"]),
            episodic_memory_version=data["episodic_memory"]["version"],
            episodic_memory_size_mb=data["episodic_memory"]["size_mb"],
            episodic_memory_hash=data["episodic_memory"]["hash"],
            episodic_memory_entries=data["episodic_memory"]["entries"],
            episodic_freshness_sec=data["episodic_memory"]["freshness_seconds"],
            semantic_model_version=data["semantic_model"]["version"],
            semantic_node_count=data["semantic_model"]["node_count"],
            semantic_model_hash=data["semantic_model"]["hash"],
            semantic_consistency_score=data["semantic_model"]["consistency_score"],
            active_goal_stack=data["context_snapshot"]["active_goal_stack"],
            current_topic_embedding=data["context_snapshot"]["current_topic_embedding"],
            error_rate_recent=data["context_snapshot"]["error_rate_recent"],
            health_score=data["homeostasis_state"]["health_score"],
            resource_headroom=data["homeostasis_state"]["resource_headroom"],
            last_mode_transition=data["homeostasis_state"]["last_mode_transition"],
        )
