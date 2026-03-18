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
from pathlib import Path
from typing import Any, Dict, Optional

from agent_core.web_source.fetch_registry import FetchRegistry
from agent_core.web_source.wiki_client import WikiClient
from agent_core.web_source.rss_client import RSSClient
from agent_core.web_source.content_writer import ContentWriter
from agent_core.web_source.topic_suggester import TopicSuggester

logger = logging.getLogger(__name__)


def run_fetch_session(
    knowledge_analyzer,
    input_dir: Optional[Path] = None,
    registry_path: Optional[Path] = None,
    max_articles: int = 3,
    enable_rss: bool = True,
) -> Dict[str, Any]:
    """
    Run one web content fetch session.

    Flow:
    1. TopicSuggester picks topics from Maria's knowledge
    2. WikiClient searches and fetches articles
    3. RSSClient fetches from configured feeds (optional)
    4. ContentWriter saves .txt files to input/

    Args:
        knowledge_analyzer: KnowledgeAnalyzer instance
        input_dir: Where to save .txt files (default: config.INPUT_DIR)
        registry_path: JSONL registry path (default: meta_data/)
        max_articles: Max articles to fetch per session
        enable_rss: Whether to also check RSS feeds

    Returns:
        Stats dict with articles_fetched, topics_searched, errors.
    """
    stats = {
        "articles_fetched": 0,
        "topics_searched": 0,
        "wiki_fetched": 0,
        "rss_fetched": 0,
        "errors": 0,
        "skipped": 0,
    }

    # Initialize components
    registry = FetchRegistry(registry_path=registry_path)
    wiki = WikiClient()
    writer = ContentWriter(input_dir=input_dir, fetch_registry=registry)
    suggester = TopicSuggester(knowledge_analyzer)

    # Step 1: Get topic suggestions
    suggestions = suggester.suggest_topics(
        fetch_registry=registry,
        max_suggestions=max_articles + 2,  # extra buffer for skips
    )

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
        stats["topics_searched"] += 1

        try:
            # Search Wikipedia
            titles = wiki.search(topic, limit=3)
            if not titles:
                logger.debug(f"[WEB_SOURCE] No Wikipedia results for '{topic}'")
                continue

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
            logger.warning(f"[WEB_SOURCE] Error fetching '{topic}': {e}")

    # Step 3: Fetch from RSS (optional)
    if enable_rss and stats["articles_fetched"] < max_articles:
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

                filename = writer.write_article(
                    title=title,
                    content=summary,
                    url=link,
                    source_type="rss",
                )

                if filename:
                    stats["articles_fetched"] += 1
                    stats["rss_fetched"] += 1
                    logger.info(f"[WEB_SOURCE] RSS: {filename}")
                else:
                    stats["skipped"] += 1

        except Exception as e:
            stats["errors"] += 1
            logger.warning(f"[WEB_SOURCE] RSS error: {e}")

    logger.info(
        f"[WEB_SOURCE] Session complete: "
        f"{stats['articles_fetched']} fetched "
        f"({stats['wiki_fetched']} wiki, {stats['rss_fetched']} rss), "
        f"{stats['topics_searched']} topics searched, "
        f"{stats['skipped']} skipped, "
        f"{stats['errors']} errors"
    )

    return stats
