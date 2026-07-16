"""
TopicSuggester - picks web search topics based on Maria's knowledge.

Zero LLM. Deterministic. Uses KnowledgeAnalyzer's topic and tag maps.

Four strategies (priority order):
- DREAM: Concepts surfaced by recent dreams (curiosity -> sleep directs supply)
- HINT: Topics from K12 Self-Analysis recommendations (topic_hints.jsonl)
- EXPAND: Topics Maria knows well -> search for related Wikipedia articles
- EXPLORE: Frequent tags across files -> discover new cross-topic content
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.world_model.belief_builder import _source_group

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 5
EXPAND_TOP_N = 3        # top N topics by file count
EXPLORE_MIN_FREQ = 3    # minimum tag frequency for EXPLORE
TAG_MIN_LEN = 3         # skip very short tags
HINTS_FILENAME = "meta_data/topic_hints.jsonl"
DREAM_LOG_FILENAME = "meta_data/dream_log.jsonl"
DREAM_LOOKBACK = 40     # how many recent dreams to scan for curiosity topics
PLAY_LOG_FILENAME = "meta_data/play_journal.jsonl"
PLAY_LOOKBACK = 30      # how many recent musings to scan for a returned-to topic

# Belief entities are a mix of clean concepts ("mechanika", "dedukcja") and
# file-ids ("web_rss_...txt", "expert_x.txt"). Only the concepts are fetchable
# Wikipedia queries -- file-ids are already-downloaded material.
_FILE_ID_PREFIXES = ("web_wiki_", "web_rss_", "web_", "expert_", "input_", "edu_")


def _is_fetchable_concept(topic: str) -> bool:
    """True if a belief entity looks like a real Wikipedia-searchable concept
    (not a file-id, a sentence, or a formula fragment)."""
    tl = (topic or "").lower().strip()
    if len(tl) < TAG_MIN_LEN:
        return False
    if tl.endswith(".txt") or tl.startswith(_FILE_ID_PREFIXES):
        return False
    # Sentence / formula fragments aren't searchable titles (opensearch returns
    # nothing): reject long phrases and math/code punctuation. (review MF1)
    # The underscore also catches snake_case internal identifiers like
    # "knowledge_coverage" / "hard_topic" that self_analysis emits as hints --
    # real PL/EN Wikipedia titles use spaces, never underscores. (2026-06-21)
    if len(tl.split()) > 3:
        return False
    if any(ch in tl for ch in ":={}()<>/_"):
        return False
    if tl.count(".") >= 2:
        return False  # dotted acronyms / self-labels (m.a.r.i.a.) -> 0 wiki titles
    return True

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
        self._dream_log_path = Path(project_root) / DREAM_LOG_FILENAME
        self._play_log_path = Path(project_root) / PLAY_LOG_FILENAME
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

        # Slot-starvation fix (2026-06-26): DREAM/PLAY/HINT/EXPAND all lean on
        # Maria's MOST-fetched topics, so on a saturated corpus they filled every
        # MAX_SUGGESTIONS slot and EXPLORE -- the ONLY strategy that surfaces FRESH
        # never-fetched tags (thousands available) -- got starved to 0 slots, so the
        # fetch loop re-asked the same exhausted set every ~60s. Reserve slots for
        # EXPLORE up front so genuinely-new material keeps flowing.
        explore_reserved = min(max_suggestions, 2 if max_suggestions >= 4 else 1)
        pre_explore_cap = max(1, max_suggestions - explore_reserved)

        # Strategy -1: DREAM curiosity topics (highest priority). Concepts surfaced
        # by recent dreams (sleep_processor sets to_explore + topics) -- "what she
        # was wondering about" steers fresh supply, closing the sleep -> curiosity
        # -> fetch -> learn loop. Capped so it seeds variety without dominating;
        # like EXPAND it does NOT skip is_topic_fetched (article-level dedup deepens).
        dream_cap = max(1, max_suggestions // 3)
        dream_used = 0
        for item in self._dream_topics():
            if dream_used >= dream_cap or len(suggestions) >= pre_explore_cap:
                break
            suggestions.append(item)
            dream_used += 1

        # Strategy -0.5: PLAY curiosity (her own idle musings she returns to).
        # Twin of DREAM, from the waking side: a fascination she keeps coming
        # back to in play_journal steers fresh supply. ONE slot only -- "one
        # thing she keeps returning to" -- and like DREAM it does NOT create a
        # goal (R1 intact); it only steers what she reads next.
        play_items = self._play_topics()
        if play_items and len(suggestions) < pre_explore_cap:
            suggestions.append(play_items[0])

        # Strategy 0: HINT topics from K12 Self-Analysis (highest priority).
        # 2026-06-20: cap HINT to at most half the slots. The hint queue is
        # dominated by low-value strategic labels ("knowledge_coverage",
        # "hard_topic") that Wikipedia can't search; left uncapped they fill every
        # slot and starve EXPAND/EXPLORE, which draw real fetchable topics from
        # Maria's own tags -- so fetch found nothing to pull. Reserving slots for
        # the real-topic strategies keeps material flowing even when hints are junk.
        hint_slot_cap = max(1, max_suggestions // 2)
        hint_used = 0
        hints = self._hint_topics()
        for item in hints:
            if hint_used >= hint_slot_cap or len(suggestions) >= pre_explore_cap:
                break
            topic = item["topic"]
            if fetch_registry and fetch_registry.is_topic_fetched(topic):
                self._mark_hint_consumed(topic)
                continue
            suggestions.append(item)
            hint_used += 1

        # Strategy 1: EXPAND known topics.
        # 2026-06-20 (review): do NOT skip on is_topic_fetched here. A topic
        # "fetched once" is NOT exhausted -- run_fetch_session dedups at the
        # ARTICLE/URL level (registry.is_fetched(url)) and pulls the next adjacent
        # Wikipedia title, so EXPAND deepens a known topic. Skipping the topic made
        # EXPAND contribute zero (its top tags are Maria's most-fetched), leaving
        # the freed HINT slots dry.
        for item in self._expand_topics():
            if len(suggestions) >= pre_explore_cap:
                break
            suggestions.append(item)

        # Strategy 2: EXPLORE via tag frequency -- the FRESH-material strategy.
        # Now skips already-fetched + un-searchable tags (see _explore_topics) so
        # the reserved slots surface genuinely-new material.
        explore = self._explore_topics(
            exclude=[s["topic"] for s in suggestions],
            fetch_registry=fetch_registry,
        )
        for item in explore:
            if len(suggestions) >= max_suggestions:
                break
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
            # Gate hints through the same fetchability filter as every other
            # strategy: self_analysis emits un-searchable meta-labels
            # ("knowledge_coverage", "System stability analysis", file-ids) that
            # otherwise reach wiki.search() and return nothing. (2026-06-21)
            if not _is_fetchable_concept(topic):
                continue
            results.append({
                "topic": topic,
                "strategy": "hint",
                "reason": f"K12 Self-Analysis: {h.get('source', 'self_analysis')} (priority {h.get('priority', 0):.1f})",
            })

        return results

    def _dream_topics(self) -> List[Dict[str, Any]]:
        """Curiosity topics from recent dreams (sleep_processor `to_explore` + `topics`).

        Scans the last DREAM_LOOKBACK dream-log entries, keeps the fetchable
        concept entities (drops file-id-shaped ones), newest-first, deduped.
        """
        path = self._dream_log_path
        if not path or not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-DREAM_LOOKBACK:]
        except OSError:
            return []

        seen = set()
        out: List[Dict[str, Any]] = []
        for line in reversed(lines):  # newest dream first
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not d.get("to_explore"):
                continue
            for topic in (d.get("topics") or []):
                tl = (topic or "").strip()
                key = tl.lower()
                if not tl or key in seen or not _is_fetchable_concept(tl):
                    continue
                seen.add(key)
                out.append({
                    "topic": tl,
                    "strategy": "dream",
                    "reason": f"Ciekawosc ze snu ({d.get('type', 'dream')})",
                })
        return out

    def _play_topics(self) -> List[Dict[str, Any]]:
        """Curiosity topics from her own play journal (idle musings she returns to).

        Twin of _dream_topics, from the waking side. Scans recent play-journal
        entries and prefers ones that CONTINUE a prior thread -- that is the
        genuine "I keep coming back to this" signal play has that dreams don't.
        Keeps the clean, fetchable TOPIC labels play_module stores in `topics`,
        newest-first, deduped. Routes a waking fascination into fresh supply
        WITHOUT creating a goal (R1 intact) -- it only steers what she reads.
        """
        path = self._play_log_path
        if not path or not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-PLAY_LOOKBACK:]
        except OSError:
            return []

        entries: List[Dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        # Two passes, newest-first: returned-to threads (continues set) win the
        # single play slot over one-off musings.
        seen = set()
        out: List[Dict[str, Any]] = []
        for prefer_continued in (True, False):
            for d in reversed(entries):
                if bool(d.get("continues")) != prefer_continued:
                    continue
                for topic in (d.get("topics") or []):
                    tl = (topic or "").strip()
                    key = tl.lower()
                    if not tl or key in seen or not _is_fetchable_concept(tl):
                        continue
                    seen.add(key)
                    reason = ("Wraca do tego w mysleniu (play)"
                              if prefer_continued
                              else "Ciekawosc z wlasnego myslenia (play)")
                    out.append({
                        "topic": tl,
                        "strategy": "play",
                        "reason": reason,
                    })
        return out

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

        # Sort by INDEPENDENT sources (descending), not raw file count: a tag in
        # 100 expert_*.txt files is one LLM voice, not 100 (cross-source
        # WYDMUSZKA, audit 2026-06-16), so an expert monoculture must not win the
        # deepen slots on volume alone. See belief_builder._source_group.
        sorted_topics = sorted(
            topic_map.items(),
            key=lambda x: len({_source_group(f) for f in x[1]}),
            reverse=True,
        )

        results = []
        for topic, files in sorted_topics[:EXPAND_TOP_N]:
            if len(topic) < TAG_MIN_LEN:
                continue
            n_src = len({_source_group(f) for f in files})
            results.append({
                "topic": topic,
                "strategy": "expand",
                "reason": (
                    f"Maria zna {len(files)} plikow ({n_src} zrodel) o "
                    f"'{topic}' - poglebienie"
                ),
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
        fetch_registry=None,
    ) -> List[Dict[str, Any]]:
        """
        Find frequent tags for cross-topic exploration.

        Strategy: tags appearing in >= EXPLORE_MIN_FREQ chunks that aren't in the
        EXPAND list. Prefers tags NOT already fetched (fetch_registry) and that are
        actually Wikipedia-searchable (_is_fetchable_concept), so the reserved
        EXPLORE slots surface genuinely-new material instead of the saturated set
        or un-searchable self-jargon.
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
            if not _is_fetchable_concept(tag):
                continue  # skip un-searchable self-jargon (0 Wikipedia titles)
            if fetch_registry and fetch_registry.is_topic_dead(tag):
                continue  # Wikipedia has no article (learned at fetch time)
            if fetch_registry and fetch_registry.is_topic_exhausted(tag):
                continue  # every article for it is already on disk (fetch-time)
            if fetch_registry and fetch_registry.is_topic_fetched(tag):
                continue  # already fetched -> not fresh material

            results.append({
                "topic": tag,
                "strategy": "explore",
                "reason": f"Tag '{tag}' pojawia sie {freq}x - eksploracja nowego",
            })

        return results
