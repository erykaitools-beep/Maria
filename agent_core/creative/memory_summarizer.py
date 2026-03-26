"""Compress conversation memories into concise summary for LLM context.

Rule-based fallback: sort by importance, truncate, concatenate.
LLM-enhanced: ask NIM to condense fragments.
"""

import logging
from typing import Callable, Dict, List, Optional

from agent_core.creative.llm_utils import safe_llm_call

logger = logging.getLogger(__name__)


class MemorySummarizer:
    """Compresses conversation memory entries into a concise summary."""

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        self._llm_fn = llm_fn

    def set_llm_fn(self, fn: Optional[Callable[[str], str]]) -> None:
        """Set or update LLM function (late wiring)."""
        self._llm_fn = fn

    def summarize(
        self,
        memories: List[dict],
        max_chars: int = 1500,
    ) -> str:
        """
        Summarize conversation memories for LLM prompt context.

        Args:
            memories: List of conversation memory dicts
            max_chars: Maximum summary length in characters

        Returns:
            Condensed summary string
        """
        if not memories:
            return ""

        # Try LLM-enhanced path
        if self._llm_fn is not None:
            result = self._summarize_with_llm(memories, max_chars)
            if result:
                return result

        # Rule-based fallback
        return self._summarize_rule_based(memories, max_chars)

    def _summarize_rule_based(
        self,
        memories: List[dict],
        max_chars: int,
    ) -> str:
        """Rule-based: sort by importance, truncate, concatenate."""
        sorted_mems = sorted(
            memories,
            key=lambda m: m.get("importance", 0),
            reverse=True,
        )

        parts = ["Kontekst z pamieci operatora:"]
        total_len = len(parts[0])

        for mem in sorted_mems:
            # Prefer summary over full content
            text = mem.get("summary", "") or mem.get("content", "")
            if not text:
                continue

            # Truncate individual entry
            if len(text) > 200:
                text = text[:197] + "..."

            line = f"- {text}"
            if total_len + len(line) + 1 > max_chars:
                break
            parts.append(line)
            total_len += len(line) + 1

        if len(parts) <= 1:
            return ""
        return "\n".join(parts)

    def _summarize_with_llm(
        self,
        memories: List[dict],
        max_chars: int,
    ) -> Optional[str]:
        """LLM-enhanced: condense memories via NIM."""
        # Build input text from memories
        fragments = []
        for mem in memories[:10]:  # Cap input
            speaker = mem.get("speaker", "unknown")
            content = mem.get("content", "")[:300]
            mem_type = mem.get("memory_type", "")
            fragments.append(f"[{speaker}/{mem_type}] {content}")

        if not fragments:
            return None

        input_text = "\n".join(fragments)
        prompt = (
            "Skondensuj ponizsze fragmenty rozmow z operatorem do krotkich, "
            "kluczowych informacji (max 3-5 punktow). "
            "Zachowaj decyzje, preferencje i odrzucenia. "
            "Odpowiedz po polsku, w formie listy punktowej.\n\n"
            f"{input_text}"
        )

        response = safe_llm_call(self._llm_fn, prompt, "memory_summarizer")
        if response and len(response) <= max_chars:
            return response
        if response:
            return response[:max_chars]
        return None
