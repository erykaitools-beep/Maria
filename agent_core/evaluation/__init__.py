"""
Agent Evaluation - Kontrakt K4.

READ-ONLY observer: reads JSONL logs, computes 5 metrics, generates reports.
Writes ONLY to meta_data/evaluation_reports.jsonl.
"""

from agent_core.evaluation.report import EvaluationReport
from agent_core.evaluation.observer import EvaluationObserver

__all__ = [
    "EvaluationReport",
    "EvaluationObserver",
]
