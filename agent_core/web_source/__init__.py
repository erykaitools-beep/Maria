"""
Web Content Fetcher for M.A.R.I.A.

Autonomously fetches learning materials from the web:
- Polish Wikipedia articles
- RSS feed entries

Content is saved as .txt files in input/ where the existing
learning pipeline (KnowledgeAnalyzer -> TeacherAgent) picks them up.

Usage:
    from agent_core.web_source import run_fetch_session
    from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer

    result = run_fetch_session(KnowledgeAnalyzer())
    # {"articles_fetched": 3, "topics_searched": 5, "errors": 0}

Wired into planner via ActionType.FETCH + ActionExecutor._exec_fetch().
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agent_core.web_source.fetch_registry import FetchRegistry
from agent_core.web_source.wiki_client import WikiClient
from agent_core.web_source.rss_client import RSSClient
from agent_core.web_source.content_writer import ContentWriter
from agent_core.web_source.topic_suggester import TopicSuggester

logger = logging.getLogger(__name__)

# R1.1 — RSS off-topic filter tuning. Was MIN_LEN=3 / stem 75%, which
# let "syst" match "system bankowy" or "system polityczny" — Maria pulled
# unrelated PAP entries (rak watroby, sondaze polityczne) when her topic
# list was generic. We now require ≥4-char words, ≥5-char stems, drop a
# small Polish stop-list, and demand 2 keyword hits when the topic list
# is rich enough to support it.
_KEYWORD_MIN_LEN = 4

# Words that show up in nearly every Polish news article — keeping them
# in the keyword set defeats the purpose of the filter.
_STOP_WORDS = frozenset({
    "system", "praca", "praktyka", "model", "modele", "metoda", "metody",
    "teoria", "teorie", "rozwoj", "badanie", "badania", "studium",
    "polski", "polska", "polsce", "polsku", "swiat", "swiata",
    "czlowiek", "czlowieka", "rzecz", "rzeczy",
})


def _build_topic_keywords(suggestions: List[Dict[str, Any]]) -> Set[str]:
    """
    Extract lowercase keyword stems from topic suggestions for RSS filtering.

    Splits multi-word topics into individual words, keeps words >= _KEYWORD_MIN_LEN,
    drops generic Polish stop-words, and truncates to stems (first 75% of chars,
    min 5) to handle Polish declension (e.g. "fizyka" -> "fizyk" matches
    "fizyce", "fizycy", "fizyki").
    """
    keywords = set()
    for s in suggestions:
        topic = s.get("topic", "")
        for word in re.split(r"[\s,;/\-]+", topic):
            word = word.lower().strip()
            if len(word) < _KEYWORD_MIN_LEN:
                continue
            if word in _STOP_WORDS:
                continue
            # Truncate to stem: handle Polish declension
            stem_len = max(5, int(len(word) * 0.75))
            stem = word[:stem_len]
            if stem in _STOP_WORDS:
                continue
            keywords.add(stem)
    return keywords


def _is_rss_relevant(title: str, summary: str, keywords: Set[str]) -> bool:
    """
    Check if RSS entry is relevant to Maria's learning topics.

    With ≥3 keywords on file we require 2 distinct hits (cuts out single
    accidental matches like "system" appearing in unrelated news).
    With 1-2 keywords we keep the old "any hit wins" behaviour — there
    just isn't enough signal to demand more.

    Empty keyword set passes everything (backward-compatible fallback).
    """
    if not keywords:
        return True
    text = f"{title} {summary}".lower()
    required = 2 if len(keywords) >= 3 else 1
    hits = 0
    for kw in keywords:
        if kw in text:
            hits += 1
            if hits >= required:
                return True
    return False


def run_fetch_session(
    knowledge_analyzer,
    input_dir: Optional[Path] = None,
    registry_path: Optional[Path] = None,
    max_articles: int = 3,
    enable_rss: bool = True,
    semantic_memory=None,
    override_topics: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Run one web content fetch session.

    Flow:
    1. TopicSuggester picks topics from Maria's knowledge
       (or use override_topics if provided - e.g. from user conversation goals)
    2. WikiClient searches and fetches articles
    3. RSSClient fetches from configured feeds (optional)
    4. ContentWriter saves .txt files to input/

    Args:
        knowledge_analyzer: KnowledgeAnalyzer instance
        input_dir: Where to save .txt files (default: config.INPUT_DIR)
        registry_path: JSONL registry path (default: meta_data/)
        max_articles: Max articles to fetch per session
        enable_rss: Whether to also check RSS feeds
        override_topics: Explicit topics to search first (from user goals).
            These are prepended before TopicSuggester results.

    Returns:
        Stats dict with articles_fetched, topics_searched, errors.
    """
    stats = {
        "articles_fetched": 0,
        "fetched_files": [],
        "topics_searched": 0,
        "wiki_fetched": 0,
        "rss_fetched": 0,
        "rss_filtered": 0,
        "errors": 0,
        "skipped": 0,
        # R2.1: per-session count of hint topics that fetched 0 articles.
        # Used by decision_log for observability; the actual jsonl marking
        # happens at the bottom of run_fetch_session via mark_hint_unsuccessful.
        "unsuccessful_hints": 0,
    }
    # R2.1: collected for end-of-session marking. We only track topics that
    # came in with strategy="hint" (K12 self-analysis); EXPAND/EXPLORE topics
    # are derived from existing knowledge and don't need lifecycle tracking.
    unsuccessful_hint_topics: List[str] = []

    # Initialize components
    registry = FetchRegistry(registry_path=registry_path)
    wiki = WikiClient()
    writer = ContentWriter(input_dir=input_dir, fetch_registry=registry)
    # Derive project root from input_dir for topic hints (K12)
    _project_root = str(input_dir.parent) if input_dir else "."
    suggester = TopicSuggester(knowledge_analyzer, project_root=_project_root)
    if semantic_memory:
        suggester.set_semantic_memory(semantic_memory)

    # Step 1: Get topic suggestions
    # Override topics from user goals go first (highest priority)
    override_suggestions = []
    if override_topics:
        for t in override_topics:
            override_suggestions.append({
                "topic": t,
                "strategy": "user_request",
                "score": 1.0,
            })
        logger.info(
            "[WEB_SOURCE] User-requested topics: %s",
            [s["topic"] for s in override_suggestions],
        )

    suggestions = suggester.suggest_topics(
        fetch_registry=registry,
        max_suggestions=max_articles + 2,  # extra buffer for skips
    )

    # Prepend user topics before auto-suggested ones
    if override_suggestions:
        suggestions = override_suggestions + suggestions

    if not suggestions:
        logger.info("[WEB_SOURCE] No topics to fetch (empty knowledge map)")
        return stats

    logger.info(
        f"[WEB_SOURCE] Session starting: {len(suggestions)} topics suggested"
    )

    # Step 2: Fetch from Wikipedia
    for suggestion in suggestions:
        if stats["articles_fetched"] >= max_articles:
            break

        topic = suggestion["topic"]
        strategy = suggestion.get("strategy", "")
        stats["topics_searched"] += 1
        # R2.1: snapshot to detect "did this topic produce a new article"
        articles_before = stats["articles_fetched"]
        had_error = False

        try:
            # Search Wikipedia
            titles = wiki.search(topic, limit=3)
            if not titles:
                logger.debug(f"[WEB_SOURCE] No Wikipedia results for '{topic}'")
            else:
                # Try first non-fetched title
                for title in titles:
                    url = f"https://pl.wikipedia.org/wiki/{title.replace(' ', '_')}"
                    if registry.is_fetched(url):
                        stats["skipped"] += 1
                        continue

                    article = wiki.fetch_article(title)
                    if article is None:
                        continue

                    filename = writer.write_article(
                        title=article["title"],
                        content=article["content"],
                        url=article["url"],
                        source_type="wikipedia",
                        topic=topic,
                    )

                    if filename:
                        stats["articles_fetched"] += 1
                        stats["fetched_files"].append(filename)
                        stats["wiki_fetched"] += 1
                        logger.info(
                            f"[WEB_SOURCE] Wikipedia: {filename} "
                            f"({suggestion['strategy']}: {topic})"
                        )
                        break  # One article per topic
                    else:
                        stats["skipped"] += 1

        except Exception as e:
            stats["errors"] += 1
            had_error = True
            logger.warning(f"[WEB_SOURCE] Error fetching '{topic}': {e}")

        # R2.1: hint produced no new article (and didn't error transiently)
        # -> mark for end-of-session lifecycle update. Errors are excluded
        # because they're typically network-transient, not "wiki has no entry".
        if (
            strategy == "hint"
            and not had_error
            and stats["articles_fetched"] == articles_before
        ):
            unsuccessful_hint_topics.append(topic)

    # Step 3: Fetch from RSS (optional, filtered by topic relevance)
    if enable_rss and stats["articles_fetched"] < max_articles:
        topic_keywords = _build_topic_keywords(suggestions)
        logger.debug(
            f"[WEB_SOURCE] RSS topic filter keywords: {topic_keywords}"
        )

        try:
            rss = RSSClient()
            entries = rss.fetch_all()

            for entry in entries:
                if stats["articles_fetched"] >= max_articles:
                    break

                link = entry.get("link", "")
                title = entry.get("title", "")
                summary = entry.get("summary", "")

                if not link or not title or not summary:
                    continue

                if registry.is_fetched(link):
                    stats["skipped"] += 1
                    continue

                # Filter: only keep entries relevant to Maria's topics
                if not _is_rss_relevant(title, summary, topic_keywords):
                    stats["rss_filtered"] += 1
                    continue

                filename = writer.write_article(
                    title=title,
                    content=summary,
                    url=link,
                    source_type="rss",
                )

                if filename:
                    stats["articles_fetched"] += 1
                    stats["fetched_files"].append(filename)
                    stats["rss_fetched"] += 1
                    logger.info(f"[WEB_SOURCE] RSS: {filename}")
                else:
                    stats["skipped"] += 1

        except Exception as e:
            stats["errors"] += 1
            logger.warning(f"[WEB_SOURCE] RSS error: {e}")

    # R2.1: mark unsuccessful hints (post-session, after both wiki+rss tried)
    # so a hint that wiki couldn't satisfy gets one strike per session, and
    # is auto-consumed after threshold attempts. Done last so partial failure
    # earlier doesn't leak through if a later step found something.
    if unsuccessful_hint_topics:
        for topic in unsuccessful_hint_topics:
            try:
                suggester.mark_hint_unsuccessful(topic)
            except Exception as e:
                logger.warning(
                    f"[WEB_SOURCE] mark_hint_unsuccessful failed for "
                    f"'{topic}': {e}"
                )
        stats["unsuccessful_hints"] = len(unsuccessful_hint_topics)

    logger.info(
        f"[WEB_SOURCE] Session complete: "
        f"{stats['articles_fetched']} fetched "
        f"({stats['wiki_fetched']} wiki, {stats['rss_fetched']} rss), "
        f"{stats['topics_searched']} topics searched, "
        f"{stats['rss_filtered']} rss filtered out, "
        f"{stats['skipped']} skipped, "
        f"{stats['errors']} errors, "
        f"{stats['unsuccessful_hints']} unsuccessful hints"
    )

    return stats
