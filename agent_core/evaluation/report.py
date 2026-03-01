"""
Evaluation Report - schema for evaluation results.

Kontrakt: docs/CONTRACTS.md - Kontrakt 4: Agent Evaluation
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class EvaluationReport:
    """Single evaluation report with 5 metrics + details + recommendations."""
    timestamp: float
    report_id: str
    period_start: float
    period_end: float

    # 5 key metrics
    metrics: Dict[str, float] = field(default_factory=dict)

    # Detailed breakdowns per metric
    details: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Source file paths (for traceability)
    data_sources: Dict[str, str] = field(default_factory=dict)

    # Threshold-based recommendations (pure logic, no LLM)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "report_id": self.report_id,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "metrics": self.metrics,
            "details": self.details,
            "data_sources": self.data_sources,
            "recommendations": self.recommendations,
        }

    @staticmethod
    def from_dict(d: dict) -> "EvaluationReport":
        return EvaluationReport(
            timestamp=d["timestamp"],
            report_id=d["report_id"],
            period_start=d["period_start"],
            period_end=d["period_end"],
            metrics=d.get("metrics", {}),
            details=d.get("details", {}),
            data_sources=d.get("data_sources", {}),
            recommendations=d.get("recommendations", []),
        )


def create_report(
    period_start: float,
    period_end: float,
) -> EvaluationReport:
    """Factory for empty report shell."""
    now = time.time()
    return EvaluationReport(
        timestamp=now,
        report_id=f"eval-{uuid.uuid4().hex[:12]}",
        period_start=period_start,
        period_end=period_end,
    )
