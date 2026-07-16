"""ReasoningJournal - Maria "thinks out loud" into an append-only notebook.

Direction (2026-07-05, operator): capture the PROSE an LLM produced while
solving a problem - not just the structured decision that survived parsing -
keyed by episode_id, so a future synthesis pass can mine reasoning patterns
across models (model-independence; fuel for a long-horizon own model).

Contract:
  - capture-only: hooks record text the organs ALREADY had in hand; the
    journal never triggers an LLM call of its own;
  - never raises into a caller (a journaling bug must not break thinking);
  - append-only JSONL (ADR-001), one entry per LLM reasoning moment;
  - episode_id comes from the thread-local tracing context (ADR-022), so
    entries join decision_traces.jsonl records without extra plumbing.

Kill-switch: REASONING_JOURNAL_ENABLED=false (read live, no restart needed
for the hooks themselves - they just start no-oping).
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.tracing.episode import current_episode_id

logger = logging.getLogger(__name__)

# Caps keep single entries bounded; reasoning is prose, not a dump site.
MAX_REASONING_CHARS = 4000
MAX_CONCLUSION_CHARS = 400
MAX_PROMPT_HINT_CHARS = 300


def _enabled() -> bool:
    return os.environ.get(
        "REASONING_JOURNAL_ENABLED", "true"
    ).strip().lower() not in ("0", "false", "off")


class ReasoningJournal:
    """Append-only writer/reader for reasoning entries."""

    def __init__(self, path: Path):
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        source: str,
        reasoning: str,
        conclusion: str = "",
        model: str = "",
        goal_id: Optional[str] = None,
        prompt_hint: str = "",
    ) -> Optional[str]:
        """Append one reasoning moment. Returns entry_id or None (skipped/failed)."""
        if not _enabled():
            return None
        text = (reasoning or "").strip()
        if not text:
            return None
        entry = {
            "entry_id": f"rj-{uuid.uuid4().hex[:12]}",
            "ts": time.time(),
            "episode_id": current_episode_id() or None,
            "source": source,
            "model": model or "",
            "goal_id": goal_id,
            "prompt_hint": (prompt_hint or "")[:MAX_PROMPT_HINT_CHARS],
            "reasoning": text[:MAX_REASONING_CHARS],
            "conclusion": (conclusion or "")[:MAX_CONCLUSION_CHARS],
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry["entry_id"]
        except Exception as e:  # journaling must never break the thinker
            logger.debug("[REASONING] record failed: %s", e)
            return None

    def recent(
        self, n: int = 5, source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Last n entries, newest first (optionally filtered by source prefix)."""
        entries: List[Dict[str, Any]] = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if source and not str(e.get("source", "")).startswith(source):
                        continue
                    entries.append(e)
        except FileNotFoundError:
            return []
        except Exception as e:
            logger.debug("[REASONING] recent failed: %s", e)
            return []
        return list(reversed(entries[-max(n, 0):]))

    def for_episode(self, episode_id: str) -> List[Dict[str, Any]]:
        """All entries recorded under one episode, oldest first."""
        out = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if e.get("episode_id") == episode_id:
                        out.append(e)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.debug("[REASONING] for_episode failed: %s", e)
        return out


_journal: Optional[ReasoningJournal] = None


def _default_path() -> Path:
    try:
        from maria_core.sys.config import BASE_DIR
        return Path(BASE_DIR) / "meta_data" / "reasoning_journal.jsonl"
    except Exception:
        return Path("meta_data") / "reasoning_journal.jsonl"


def get_reasoning_journal() -> ReasoningJournal:
    """Shared journal singleton (hooks import this - zero wiring needed)."""
    global _journal
    if _journal is None:
        _journal = ReasoningJournal(_default_path())
    return _journal


def set_reasoning_journal(journal: Optional[ReasoningJournal]) -> None:
    """Override the singleton (tests / custom wiring)."""
    global _journal
    _journal = journal
