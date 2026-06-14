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

# R2.1 (2026-04-29): hint fail-and-skip threshold. After this many fetch
# sessions returned 0 articles for a hint topic, mark it consumed so it
# stops re-appearing at top of the suggester queue.
DEFAULT_FAIL_THRESHOLD = 3


class TopicSuggester:
    """
    Suggests web search topics based on Maria's existing knowledge.

    Uses KnowledgeAnalyzer's topic_file_map and tag_frequency_map
    to find topics worth fetching from Wikipedia/RSS.

    When semantic_memory is set, uses embedding similarity to rank
    suggestions by relevance to Maria's learning gaps.
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
        self._semantic_memory = None  # Late-wired SemanticMemory

    def set_semantic_memory(self, semantic_memory) -> None:
        """Wire SemanticMemory for semantic ranking of suggestions."""
        self._semantic_memory = semantic_memory

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

        # Semantic re-ranking: boost suggestions similar to known knowledge gaps
        if self._semantic_memory and len(suggestions) > 1:
            suggestions = self._semantic_rerank(suggestions)

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

    def mark_hint_unsuccessful(
        self, topic: str, threshold: int = DEFAULT_FAIL_THRESHOLD,
    ) -> None:
        """Increment failed_attempts for a hint; consume it after threshold.

        R2.1 (2026-04-29): wikipedia search returns 0 titles for many K12
        hints even after the searchable-shape filter. Without this lifecycle
        the same top-priority hints came back every cycle wasting 17s each.

        After `threshold` unsuccessful sessions, the hint is marked consumed
        with reason `failed_<N>_attempts` and stops appearing in suggestions.
        Topic match is case-insensitive lowercase-stripped, mirroring
        deduplication in RecommendationApplier.
        """
        if not self._hints_path.exists():
            return
        target = (topic or "").lower().strip()
        if not target:
            return

        try:
            lines: List[str] = []
            with open(self._hints_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        h = json.loads(line)
                    except json.JSONDecodeError:
                        lines.append(line)
                        continue

                    ht = (h.get("topic") or "").lower().strip()
                    if ht == target and not h.get("consumed", False):
                        fa = int(h.get("failed_attempts", 0)) + 1
                        h["failed_attempts"] = fa
                        if fa >= threshold:
                            h["consumed"] = True
                            h["consumed_reason"] = f"failed_{threshold}_attempts"
                            logger.info(
                                f"[TOPIC_SUGGEST] Hint exhausted after {fa} "
                                f"unsuccessful attempts: {topic[:50]}"
                            )
                    lines.append(json.dumps(h, ensure_ascii=False))

            with open(self._hints_path, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
        except IOError as e:
            logger.warning(f"Could not mark hint unsuccessful: {e}")

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

    def _semantic_rerank(self, suggestions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Re-rank suggestions using semantic similarity to indexed knowledge.

        Topics similar to what Maria already knows get a diversity penalty,
        topics dissimilar (novel) get boosted. Hints keep priority.
        """
        try:
            sm = self._semantic_memory
            reranked = []
            for s in suggestions:
                topic = s["topic"]
                # Search existing knowledge for similar topics
                results = sm.search(topic, namespace="knowledge", top_k=3, threshold=0.5)

                if results:
                    # High similarity = Maria already knows this area
                    # -> lower novelty score (but still useful for EXPAND)
                    avg_sim = sum(r.score for r in results) / len(results)
                    novelty = 1.0 - avg_sim  # 0 = exact match, 1 = totally new
                else:
                    novelty = 1.0  # Unknown territory

                # Hints keep their priority regardless of novelty
                if s["strategy"] == "hint":
                    rank_score = 2.0  # Always first
                else:
                    # Blend: 60% novelty + 40% original order
                    original_order_score = 1.0 - (suggestions.index(s) / len(suggestions))
                    rank_score = 0.6 * novelty + 0.4 * original_order_score

                s["novelty"] = round(novelty, 3)
                s["rank_score"] = round(rank_score, 3)
                reranked.append(s)

            reranked.sort(key=lambda x: x.get("rank_score", 0), reverse=True)
            return reranked

        except Exception as e:
            logger.warning(f"[TOPIC_SUGGEST] Semantic rerank failed: {e}")
            return suggestions  # Fallback: original order

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
