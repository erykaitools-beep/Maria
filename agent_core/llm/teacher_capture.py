"""
Full-fidelity capture of teacher LLM calls, for training a local replacement.

llm_tape.py deliberately truncates: prompts to 200 chars, responses to 2000.
That is right for its consumers -- EvidenceCollector and K12 feed recent tape
entries straight into prompts, and an untruncated tape would bloat every
context window on a CPU-bound box. But it also means the tape cannot serve as
a training corpus: the prompt is a stub and the answer is clipped mid-sentence.

This module writes the untruncated pair to a separate file that nothing in the
running system reads back. Scope is narrow on purpose -- only roles that
represent a task we want a local model to take over.

Off switch: TEACHER_CAPTURE_ENABLED=0 in .env (requires a restart).
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Only roles whose work a local student is meant to inherit. "learning" is the
# chunk -> {summary, key_points, tags, questions} task currently served by NIM.
CAPTURE_ROLES = frozenset({"learning"})

DEFAULT_PATH = Path("meta_data/datasets/teacher_capture.jsonl")

# Hard ceiling so a runaway loop cannot fill the disk. Unlike llm_tape this
# file does NOT rotate: rotation there renames onto a single .bak and drops
# whatever the previous rotation left, which is acceptable for an audit log
# and not acceptable for a corpus. Above the ceiling we stop writing and say so.
MAX_FILE_BYTES = 512 * 1024 * 1024

_lock = threading.Lock()
_ceiling_warned = False


def is_enabled() -> bool:
    """Capture is on unless explicitly disabled."""
    return os.environ.get("TEACHER_CAPTURE_ENABLED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def capture(
    model: str,
    role: str,
    prompt: str,
    response: str,
    success: bool,
    latency_ms: float = 0.0,
    episode_id: str = "",
    route_reason: str = "",
    path: Optional[Path] = None,
) -> bool:
    """Append one untruncated call. Returns True when a row was written.

    Never raises: this sits on the hot path of every LLM call.
    """
    global _ceiling_warned

    if role not in CAPTURE_ROLES or not is_enabled():
        return False
    if not success or not prompt or not (response or "").strip():
        # A failed or empty call is a fine audit record but a useless training
        # pair; the tape already keeps it.
        return False

    target = Path(path) if path else DEFAULT_PATH
    row = {
        "ts": time.time(),
        "model": model or "unknown",
        "role": role,
        "prompt": prompt,
        "response": response,
        "latency_ms": round(latency_ms, 1),
        "episode_id": episode_id or "",
        "route_reason": route_reason or "",
    }

    try:
        with _lock:
            if target.exists() and target.stat().st_size >= MAX_FILE_BYTES:
                if not _ceiling_warned:
                    logger.warning(
                        "[TeacherCapture] %s reached %d MB ceiling, capture stopped",
                        target,
                        MAX_FILE_BYTES // (1024 * 1024),
                    )
                    _ceiling_warned = True
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:
        logger.debug("[TeacherCapture] write failed: %s", exc)
        return False
