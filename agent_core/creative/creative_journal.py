"""Persistent strategic diary of reflections and outcomes.

Each reflection session produces one journal entry summarizing:
- What triggered the reflection
- What tensions were found
- What insights emerged
- What meta-goals were proposed
- Later: what happened (filled retroactively)
"""

import logging
from typing import List

from agent_core.creative.creative_model import (
    CreativeJournalEntry, ReflectionSession,
)
from agent_core.creative.creative_store import CreativeStore

logger = logging.getLogger(__name__)


class CreativeJournal:
    """Manages strategic journal entries."""

    def __init__(self, store: CreativeStore):
        self._store = store

    def create_entry_from_session(self, session: ReflectionSession,
                                  summary: str = "") -> CreativeJournalEntry:
        """Create and persist a journal entry from a completed reflection session."""
        if not summary:
            summary = self._auto_summarize(session)

        entry = CreativeJournalEntry.create(
            trigger=session.trigger,
            summary=summary,
            tension_ids=[t.tension_id for t in session.detected_tensions],
            insight_ids=[i.insight_id for i in session.insights],
            meta_goal_ids=[mg.goal_id for mg in session.candidate_meta_goals],
        )
        self._store.save_journal_entry(entry)
        return entry

    def get_recent_entries(self, limit: int = 10) -> List[dict]:
        """Get most recent journal entries."""
        entries = self._store.load_journal()
        entries.sort(key=lambda e: e.get("created_ts", 0), reverse=True)
        return entries[:limit]

    def _auto_summarize(self, session: ReflectionSession) -> str:
        """Generate a brief summary from session data."""
        parts = []

        if session.detected_tensions:
            cats = [t.category.value for t in session.detected_tensions]
            parts.append(f"Wykryte napiecia: {', '.join(cats)}")

        if session.insights:
            parts.append(f"{len(session.insights)} wnioskow strategicznych")

        if session.candidate_meta_goals:
            titles = [mg.title for mg in session.candidate_meta_goals]
            parts.append(f"Zaproponowane meta-cele: {'; '.join(titles)}")

        if session.observations:
            parts.append(f"{len(session.observations)} obserwacji")

        if not parts:
            parts.append("Sesja refleksji bez nowych wnioskow")

        return ". ".join(parts) + "."
