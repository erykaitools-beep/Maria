"""
TopicSuggester - picks web search topics based on Maria's knowledge.

Zero LLM. Deterministic. Uses KnowledgeAnalyzer's topic and tag maps.

Three strategies (priority order):
- HINT: Topics from K12 Self-Analysis recommendations (topic_hints.jsonl)
- EXPAND: Topics Maria knows well -> search for related Wikipedia articles
- EXPLORE: Frequent tags across files -> discover new cross-topic content
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 5
EXPAND_TOP_N = 3        # top N topics by file count
EXPLORE_MIN_FREQ = 3    # minimum tag frequency for EXPLORE
TAG_MIN_LEN = 3         # skip very short tags
HINTS_FILENAME = "meta_data/topic_hints.jsonl"


class TopicSuggester:
    """
    Suggests web search topics based on Maria's existing knowledge.

    Uses KnowledgeAnalyzer's topic_file_map and tag_frequency_map
    to find topics worth fetching from Wikipedia/RSS.
    """

    def __init__(self, knowledge_analyzer, project_root: str = "."):
        """
        Args:
            knowledge_analyzer: KnowledgeAnalyzer instance with
                get_topic_file_map() and get_tag_frequency_map().
            project_root: Project root for reading topic_hints.jsonl.
        """
        self._analyzer = knowledge_analyzer
        self._hints_path = Path(project_root) / HINTS_FILENAME

    def suggest_topics(
        self,
        fetch_registry=None,
        max_suggestions: int = MAX_SUGGESTIONS,
    ) -> List[Dict[str, Any]]:
        """
        Generate topic suggestions for web fetching.

        Args:
            fetch_registry: FetchRegistry to check already-fetched topics.
            max_suggestions: Maximum number of suggestions.

        Returns:
            List of dicts:
            {
                "topic": str,          # Search query for Wikipedia
                "strategy": str,       # "expand" or "explore"
                "reason": str,         # Human-readable explanation
            }
        """
        suggestions = []

        # Strategy 0: HINT topics from K12 Self-Analysis (highest priority)
        hints = self._hint_topics()
        for item in hints:
            if len(suggestions) >= max_suggestions:
                break
            topic = item["topic"]
            if fetch_registry and fetch_registry.is_topic_fetched(topic):
                self._mark_hint_consumed(topic)
                continue
            suggestions.append(item)

        # Strategy 1: EXPAND known topics
        expand = self._expand_topics()
        for item in expand:
            if len(suggestions) >= max_suggestions:
                break
            topic = item["topic"]
            # Skip already fetched
            if fetch_registry and fetch_registry.is_topic_fetched(topic):
                continue
            suggestions.append(item)

        # Strategy 2: EXPLORE via tag frequency
        explore = self._explore_topics(
            exclude=[s["topic"] for s in suggestions]
        )
        for item in explore:
            if len(suggestions) >= max_suggestions:
                break
            topic = item["topic"]
            if fetch_registry and fetch_registry.is_topic_fetched(topic):
                continue
            suggestions.append(item)

        return suggestions

    def _hint_topics(self) -> List[Dict[str, Any]]:
        """
        Read topic hints from K12 Self-Analysis (topic_hints.jsonl).

        Strategy: highest priority hints that haven't been consumed yet.
        These are recommendations from external AI analysis of Maria's logs.
        """
        if not self._hints_path.exists():
            return []

        hints = []
        try:
            with open(self._hints_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        h = json.loads(line)
                        if not h.get("consumed", False):
                            hints.append(h)
                    except json.JSONDecodeError:
                        continue
        except IOError:
            return []

        # Sort by priority descending
        hints.sort(key=lambda h: h.get("priority", 0), reverse=True)

        results = []
        for h in hints:
            topic = h.get("topic", "")
            if not topic or len(topic) < TAG_MIN_LEN:
                continue
            results.append({
                "topic": topic,
                "strategy": "hint",
                "reason": f"K12 Self-Analysis: {h.get('source', 'self_analysis')} (priority {h.get('priority', 0):.1f})",
            })

        return results

    def _mark_hint_consumed(self, topic: str):
        """Mark a hint topic as consumed (already fetched)."""
        if not self._hints_path.exists():
            return

        try:
            lines = []
            with open(self._hints_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        h = json.loads(line)
                        if h.get("topic") == topic:
                            h["consumed"] = True
                        lines.append(json.dumps(h, ensure_ascii=False))
                    except json.JSONDecodeError:
                        lines.append(line)

            with open(self._hints_path, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
        except IOError as e:
            logger.warning(f"Could not mark hint consumed: {e}")

    def _expand_topics(self) -> List[Dict[str, Any]]:
        """
        Pick known topics worth expanding.

        Strategy: top N topics by file count. Maria knows these best,
        so she can learn deeper by reading related Wikipedia articles.
        """
        try:
            topic_map = self._analyzer.get_topic_file_map()
        except Exception as e:
            logger.warning(f"Could not get topic map: {e}")
            return []

        if not topic_map:
            return []

        # Sort by file count (descending)
        sorted_topics = sorted(
            topic_map.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        )

        results = []
        for topic, files in sorted_topics[:EXPAND_TOP_N]:
            if len(topic) < TAG_MIN_LEN:
                continue
            results.append({
                "topic": topic,
                "strategy": "expand",
                "reason": f"Maria zna {len(files)} plikow o '{topic}' - poglebienie",
            })

        return results

    def _explore_topics(
        self, exclude: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find frequent tags for cross-topic exploration.

        Strategy: tags appearing in >= EXPLORE_MIN_FREQ chunks
        that aren't in the EXPAND list. These are recurring themes
        worth exploring independently.
        """
        exclude_set = set(t.lower() for t in (exclude or []))

        try:
            tag_freq = self._analyzer.get_tag_frequency_map()
        except Exception as e:
            logger.warning(f"Could not get tag frequency map: {e}")
            return []

        if not tag_freq:
            return []

        results = []
        for tag, freq in tag_freq.items():
            if freq < EXPLORE_MIN_FREQ:
                break  # Sorted by freq desc, no more candidates
            if tag.lower() in exclude_set:
                continue
            if len(tag) < TAG_MIN_LEN:
                continue

            results.append({
                "topic": tag,
                "strategy": "explore",
                "reason": f"Tag '{tag}' pojawia sie {freq}x - eksploracja nowego",
            })

        return results
