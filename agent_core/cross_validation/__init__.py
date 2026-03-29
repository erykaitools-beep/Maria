"""
Multi-Source Learning: Cross-LLM Validation (Faza F).

Maria learns from one LLM at a time, then validates knowledge
by asking a different LLM to independently summarize the same material.
Disagreements are logged as disputes for analysis.

Components:
- CrossValidator: compares learning results from multiple LLMs
- ConfidenceScorer: scores reliability of learned knowledge
- DisputeLog: persists contradictions between sources

Integration: Planner ActionType.VALIDATE triggers post-learning check.

ADR-027: Multi-Source Learning via post-learning cross-validation.
"""

from agent_core.cross_validation.cross_validator import CrossValidator
from agent_core.cross_validation.confidence_scorer import ConfidenceScorer
from agent_core.cross_validation.dispute_log import DisputeLog

__all__ = ["CrossValidator", "ConfidenceScorer", "DisputeLog"]
