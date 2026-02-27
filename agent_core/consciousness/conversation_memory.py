"""
ConversationMemory - Persistent conversation history with condensation.

Handles:
- Saving conversation turns to JSONL (append-only, ADR-001)
- Restoring last N messages on startup
- Condensing full session into structured summary at checkpoint
- Loading past session summaries for context injection

Thread-safe, non-blocking for the REPL loop.
"""

import json
import time
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_HISTORY_PATH = Path("meta_data/conversation_history.jsonl")
DEFAULT_SUMMARIES_PATH = Path("meta_data/conversation_summaries.jsonl")


class ConversationMemory:
    """
    Persistent conversation memory with session condensation.

    Usage:
        mem = ConversationMemory(session_id=9)
        mem.save_turn("user", "Jak sie masz?")
        mem.save_turn("assistant", "Dobrze!")

        # At shutdown:
        condensed = mem.condense_session(brain)
        mem.save_summary(condensed)

        # Next startup:
        restored = mem.restore_history()
        context = mem.get_conversation_context()
    """

    MAX_RESTORE_MESSAGES = 20
    MAX_CONTENT_LENGTH = 2000

    def __init__(
        self,
        history_path: Optional[Path] = None,
        summaries_path: Optional[Path] = None,
        session_id: int = 0,
        source: str = "repl",
    ):
        """
        Initialize conversation memory.

        Args:
            history_path: Path to conversation JSONL file
            summaries_path: Path to summaries JSONL file
            session_id: Current session number
            source: Message source identifier ("repl" or "web")
        """
        self.history_path = Path(history_path or DEFAULT_HISTORY_PATH)
        self.summaries_path = Path(summaries_path or DEFAULT_SUMMARIES_PATH)
        self.session_id = session_id
        self.source = source
        self._lock = threading.Lock()
        self._session_turn_count = 0
        self._session_start_ts = None

    # --- Persistence ---

    def save_turn(self, role: str, content: str) -> None:
        """
        Append a single conversation turn to JSONL.

        Thread-safe. Called after each user/assistant message.

        Args:
            role: "user" or "assistant"
            content: Message text
        """
        if role not in ("user", "assistant"):
            return

        # Truncate long content
        if len(content) > self.MAX_CONTENT_LENGTH:
            content = content[:self.MAX_CONTENT_LENGTH] + "..."

        entry = {
            "ts": time.time(),
            "session": self.session_id,
            "role": role,
            "content": content,
            "source": self.source,
        }

        with self._lock:
            if self._session_start_ts is None:
                self._session_start_ts = entry["ts"]
            self._session_turn_count += 1

            try:
                self.history_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.history_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.warning(f"Failed to save turn: {e}")

    def restore_history(self) -> List[Dict[str, str]]:
        """
        Load the last N messages from the most recent session.

        Returns list in OllamaBrain format:
        [{"role": "user", "content": "..."}, ...]
        Skips system messages.
        """
        if not self.history_path.exists():
            return []

        # Read all entries, filter by most recent session that has data
        all_entries = []
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        all_entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Failed to read history: {e}")
            return []

        if not all_entries:
            return []

        # Find the most recent session with messages (might be previous session)
        # We want to restore from the session right before current one
        prev_session_entries = [
            e for e in all_entries
            if e.get("session", 0) == self.session_id - 1
            and e.get("role") in ("user", "assistant")
        ]

        # If no previous session, try current session (e.g. crash recovery)
        if not prev_session_entries:
            prev_session_entries = [
                e for e in all_entries
                if e.get("role") in ("user", "assistant")
            ]

        if not prev_session_entries:
            return []

        # Take last N messages
        recent = prev_session_entries[-self.MAX_RESTORE_MESSAGES:]

        # Convert to OllamaBrain format
        messages = []
        for entry in recent:
            messages.append({
                "role": entry["role"],
                "content": entry["content"],
            })

        logger.info(f"Restored {len(messages)} messages from history")
        return messages

    # --- Condensation ---

    def condense_session(self, brain) -> Optional[Dict[str, Any]]:
        """
        Condense current session conversation into structured summary.

        Uses brain._ask_once() for LLM-based extraction. Falls back to
        rule-based summary if LLM fails.

        Args:
            brain: OllamaBrain or LLMRouter instance

        Returns:
            Summary dict or None if no conversation
        """
        # Get current session messages from JSONL
        session_messages = self._get_session_messages()
        if not session_messages:
            return None

        turn_count = len(session_messages)
        date_str = time.strftime("%Y-%m-%d")

        # Build conversation text for LLM
        conversation_text = self._build_conversation_text(session_messages)

        # Try LLM condensation
        condensed = self._llm_condense(brain, conversation_text)

        if condensed:
            condensed.update({
                "session": self.session_id,
                "date": date_str,
                "turn_count": turn_count,
            })
            return condensed

        # Fallback: rule-based summary
        return {
            "session": self.session_id,
            "date": date_str,
            "turn_count": turn_count,
            "summary": f"Sesja {self.session_id} ({turn_count} wiadomosci)",
            "facts": [],
            "user_facts": [],
            "sentiment": "neutral",
            "condensed_by": "rule",
        }

    def _get_session_messages(self) -> List[Dict]:
        """Read messages from current session."""
        if not self.history_path.exists():
            return []

        messages = []
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("session") == self.session_id:
                            messages.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Failed to read session messages: {e}")

        return messages

    def _build_conversation_text(self, messages: List[Dict], max_chars: int = 3000) -> str:
        """Build conversation text for LLM prompt, respecting char limit."""
        lines = []
        total = 0
        # Take last 30 exchanges
        recent = messages[-60:]  # 30 pairs

        for msg in recent:
            role = msg.get("role", "?")
            content = msg.get("content", "")[:200]
            line = f"{role}: {content}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)

        return "\n".join(lines)

    def _llm_condense(self, brain, conversation_text: str) -> Optional[Dict[str, Any]]:
        """Use LLM to condense conversation into structured summary."""
        prompt = (
            "Przeanalizuj te fragmenty rozmowy i wyodrebnij z nich informacje.\n\n"
            "ROZMOWA:\n"
            f"{conversation_text}\n\n"
            "Zwroc TYLKO JSON w tym formacie (bez dodatkowego tekstu):\n"
            '{"summary": "1-2 zdania podsumowujace o czym rozmawialismy (pisz w 1os l.mn.)", '
            '"facts": ["fakt1", "fakt2"], '
            '"user_facts": ["fakt o uzytkowniku"], '
            '"sentiment": "positive|neutral|negative|mixed"}\n\n'
            "Zasady:\n"
            "- summary: max 2 zdania, zwiezle\n"
            "- facts: kluczowe fakty z rozmowy (max 5)\n"
            "- user_facts: fakty o uzytkowniku - preferencje, plany (max 3)\n"
            "- sentiment: ogolny ton rozmowy\n"
            "- Nie dodawaj nic poza JSON"
        )

        try:
            # Use _ask_once to avoid polluting conversation history
            ask_fn = getattr(brain, "_ask_once", None)
            if ask_fn is None:
                # LLMRouter wraps _ask_once differently
                ask_fn = getattr(brain, "analyze_task", None)

            if ask_fn is None:
                logger.warning("No _ask_once or analyze_task on brain")
                return None

            raw = ask_fn(prompt, temperature=0.1)
            if not raw:
                return None

            # Extract JSON from response
            result = self._extract_json(raw)
            if result and "summary" in result:
                # Determine which LLM was used
                condensed_by = "nim" if hasattr(brain, "nim") else "ollama"
                result["condensed_by"] = condensed_by
                return result

            logger.warning(f"LLM condensation returned invalid JSON: {raw[:200]}")
            return None

        except Exception as e:
            logger.warning(f"LLM condensation failed: {e}")
            return None

    def _extract_json(self, text: str) -> Optional[Dict]:
        """Extract JSON from LLM response text."""
        # Try direct parse
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON block in text
        import re
        # Look for {...} block
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Try stripping markdown code fences
        cleaned = re.sub(r'```(?:json)?\s*', '', text)
        cleaned = re.sub(r'```\s*$', '', cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        return None

    def save_summary(self, summary: Dict[str, Any]) -> None:
        """
        Append condensed session summary to summaries JSONL.

        Args:
            summary: Summary dict from condense_session()
        """
        try:
            self.summaries_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.summaries_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(summary, ensure_ascii=False) + "\n")
            logger.info(f"Saved session {summary.get('session')} summary")
        except Exception as e:
            logger.warning(f"Failed to save summary: {e}")

    # --- Context Retrieval ---

    def get_recent_summaries(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Load last N session summaries from JSONL.

        Args:
            limit: Maximum number of summaries to return

        Returns:
            List of summary dicts, newest last
        """
        if not self.summaries_path.exists():
            return []

        summaries = []
        try:
            with open(self.summaries_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        summaries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Failed to read summaries: {e}")
            return []

        return summaries[-limit:]

    def get_conversation_context(self, limit: int = 3) -> str:
        """
        Build human-readable context string from recent session summaries.

        Included in system prompt so Maria remembers past conversations.

        Args:
            limit: Number of recent sessions to include

        Returns:
            Context string or empty string if no summaries
        """
        summaries = self.get_recent_summaries(limit)
        if not summaries:
            return ""

        lines = ["[Pamiec rozmow]"]
        for s in summaries:
            session = s.get("session", "?")
            date = s.get("date", "?")
            summary = s.get("summary", "")
            if summary:
                lines.append(f"  Sesja {session} ({date}): {summary}")

        # Add user facts (never forgotten)
        user_facts = self.get_all_user_facts()
        if user_facts:
            lines.append(f"  Fakty o uzytkowniku: {', '.join(user_facts[:5])}")

        return "\n".join(lines)

    def get_all_user_facts(self) -> List[str]:
        """
        Collect all user_facts from all session summaries.

        User facts are highest priority - never forgotten (CONSCIOUSNESS_SPEC).

        Returns:
            Deduplicated list of user facts
        """
        all_summaries = self.get_recent_summaries(limit=100)
        seen = set()
        facts = []
        for s in all_summaries:
            for fact in s.get("user_facts", []):
                fact_lower = fact.lower().strip()
                if fact_lower and fact_lower not in seen:
                    seen.add(fact_lower)
                    facts.append(fact.strip())
        return facts

    # --- Session Info ---

    def get_session_turn_count(self) -> int:
        """Count turns saved in current session."""
        return self._session_turn_count

    def get_session_start_ts(self) -> Optional[float]:
        """Get timestamp of first turn in current session."""
        return self._session_start_ts
