"""
Episode ID - thread-local correlation ID for cognitive episodes.

One episode = one planner cycle (OBSERVE -> THINK -> ACT -> EVALUATE).
All subsystems (K7, K10, LLM tape, effector) read the current episode_id
from thread-local storage to tag their log entries.

Thread-safe: each thread gets its own episode_id via threading.local().
"""

import threading
import time
import uuid

_local = threading.local()


def generate_episode_id() -> str:
    """
    Generate a new episode ID and set it as current.

    Format: ep-{timestamp_hex}-{random_hex}
    Example: ep-66e5a1f0-3b7c9a1d

    The timestamp prefix enables chronological sorting without parsing.
    """
    ts_hex = format(int(time.time()), "x")
    rand_hex = uuid.uuid4().hex[:8]
    eid = f"ep-{ts_hex}-{rand_hex}"
    _local.episode_id = eid
    return eid


def current_episode_id() -> str:
    """
    Get the current episode ID for this thread.

    Returns empty string if no episode is active (safe for logging).
    """
    return getattr(_local, "episode_id", "")


def set_episode_id(episode_id: str) -> None:
    """Set episode ID explicitly (for testing or cross-thread propagation)."""
    _local.episode_id = episode_id


def set_current_trace(trace) -> None:
    """Set current DecisionTrace reference for LLM call counting."""
    _local.current_trace = trace


def get_current_trace():
    """Get current DecisionTrace reference (or None)."""
    return getattr(_local, "current_trace", None)


def clear_episode_id() -> None:
    """Clear the current episode ID (end of cycle cleanup)."""
    _local.episode_id = ""
    _local.current_trace = None
