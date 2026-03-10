"""
TopicSuggester - picks web search topics based on Maria's knowledge.

Zero LLM. Deterministic. Uses KnowledgeAnalyzer's topic and tag maps.

Two strategies:
- EXPAND: Topics Maria knows well -> search for related Wikipedia articles
- EXPLORE: Frequent tags across files -> discover new cross-topic content
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 5
EXPAND_TOP_N = 3        # top N topics by file count
EXPLORE_MIN_FREQ = 3    # minimum tag frequency for EXPLORE
TAG_MIN_LEN = 3         # skip very short tags


class TopicSuggester:
    """
    Suggests web search topics based on Maria's existing knowledge.

    Uses KnowledgeAnalyzer's topic_file_map and tag_frequency_map
    to find topics worth fetching from Wikipedia/RSS.
    """

    def __init__(self, knowledge_analyzer):
        """
        Args:
            knowledge_analyzer: KnowledgeAnalyzer instance with
                get_topic_file_map() and get_tag_frequency_map().
        """
        self._analyzer = knowledge_analyzer

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
