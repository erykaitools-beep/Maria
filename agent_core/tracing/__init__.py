"""
Tracing - Unified decision traceability for M.A.R.I.A.

Phase 1 of Stabilization Roadmap: every critical decision gets an episode_id
that flows through planner, K7, K10, LLM tape, and effector.

ADR-022: Episode-based tracing (correlation IDs across cognitive episodes).
"""

from agent_core.tracing.episode import generate_episode_id, current_episode_id, set_episode_id, clear_episode_id, set_current_trace, get_current_trace
from agent_core.tracing.trace_model import DecisionTrace, TraceStep
from agent_core.tracing.trace_store import TraceStore

__all__ = [
    "generate_episode_id",
    "current_episode_id",
    "set_episode_id",
    "clear_episode_id",
    "DecisionTrace",
    "TraceStep",
    "TraceStore",
]
