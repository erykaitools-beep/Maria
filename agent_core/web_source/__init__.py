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
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agent_core.web_source.fetch_registry import FetchRegistry
from agent_core.web_source.wiki_client import WikiClient
from agent_core.web_source.rss_client import RSSClient, MARKET_FEEDS
from agent_core.web_source.article_fetcher import ArticleFetcher
from agent_core.web_source.content_writer import ContentWriter
from agent_core.web_source.topic_suggester import TopicSuggester

logger = logging.getLogger(__name__)

# RSS off-topic filter. Two ideas: (1) short/generic words are noise, so we
# keep only ≥4-char words, truncate each to a ~75%-length stem (Polish
# declension; floor 5, but a 4-char word stays 4), and drop a stop-list;
# (2) an entry is relevant when it hits ANY ONE topic stem.
#
# 2026-07-16 (RSS martwy): the old rule demanded 2 hits once the keyword set
# was rich (≥3). But `keywords` is a FLAT UNION of stems from up to 5 UNRELATED
# topics ("planner" + "sprzezenie zwrotne" + "rynki finansowe" ...), so "2 hits"
# meant an article had to be about two unrelated things at once -- structurally
# unsatisfiable. Live probe: 1/50 real entries passed, RSS saved 0/session for
# days. Fixed to required=1 (one topic hit is enough) + WORD-PREFIX matching
# (was substring `kw in text`, which let a stem hit mid-word: "wiedz" matched
# "odwiedza", "astro" matched "katastrofa"). See _is_rss_relevant.
_KEYWORD_MIN_LEN = 4

# Words that show up in nearly every Polish (science) article — keeping them
# in the keyword set defeats the purpose of the filter. "nauka"/"nauki" and the
# stem "wiedz" (covers the whole wiedza/wiedzy/wiedzą declension via the stem
# check) are added 2026-07-16: as topic stems they match essentially every entry
# on a general-science feed, so they carry no discriminating signal.
_STOP_WORDS = frozenset({
    "system", "praca", "praktyka", "model", "modele", "metoda", "metody",
    "teoria", "teorie", "rozwoj", "badanie", "badania", "studium",
    "polski", "polska", "polsce", "polsku", "swiat", "swiata",
    "czlowiek", "czlowieka", "rzecz", "rzeczy",
    "nauka", "nauki", "wiedz",
})


def _build_topic_keywords(suggestions: List[Dict[str, Any]]) -> Set[str]:
    """
    Extract lowercase keyword stems from topic suggestions for RSS filtering.

    Splits multi-word topics into individual words, keeps words >= _KEYWORD_MIN_LEN,
    drops generic Polish stop-words, and truncates to stems (first 75% of chars,
    min 5) to handle Polish declension (e.g. "fizyka" -> "fizyk" matches
    "fizyce", "fizycy", "fizyki").

    Topics are NFC-normalized so a stem built here is byte-comparable with the
    NFC-normalized entry text in _is_rss_relevant (a decomposed "ą" = a + U+0328
    is not a \\w char and would silently split the word otherwise).
    """
    keywords = set()
    for s in suggestions:
        topic = unicodedata.normalize("NFC", s.get("topic", ""))
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


# Word tokens for prefix matching (Unicode letters/digits, incl. Polish).
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _is_rss_relevant(title: str, summary: str, keywords: Set[str]) -> bool:
    """
    Check if RSS entry is relevant to Maria's learning topics.

    Relevant = at least ONE keyword stem is a PREFIX of some word in the
    title/summary. required=1 because `keywords` is a flat union of stems from
    several UNRELATED topics; demanding 2 hits would require one article to be
    about two unrelated things at once (the 2026-07-16 RSS-dead bug).

    Matching is WORD-PREFIX, not substring: the stem must begin a word token,
    so "wiedz" matches "wiedza"/"wiedzy" but NOT "odwiedza", and "fizyk" matches
    "fizyka"/"fizyce" but not a mid-word coincidence. This handles Polish
    declension (stems are truncated) without the substring false positives.

    Empty keyword set passes everything (backward-compatible fallback).
    """
    if not keywords:
        return True
    prefixes = tuple(keywords)  # str.startswith accepts a tuple of options
    # NFC first: a decomposed diacritic (a + U+0328) is not a \w char and would
    # split the word mid-stem, so the stems (also NFC) would never prefix-match.
    text = unicodedata.normalize("NFC", f"{title} {summary}").lower()
    for token in _WORD_RE.findall(text):
        if token.startswith(prefixes):
            return True
    return False


# ── Market feed profile (Kronika rynku: BTC / zloto / srebro) ──────────────
# The default _is_rss_relevant filter starves market content: it needs 2 hits
# on rich keyword sets, does no PL transliteration ("zloto" never matches the
# real headline "złota"), and its stem floor kills 5-letter declensions. On a
# live probe of 24 real market entries it passed 0/24. So the market profile
# gets its OWN matcher: required=1, PL+ASCII bilingual, transliterated so
# "złota" -> "zlota" matches the "zlota" stem, short tickers on word boundaries.
FEED_PROFILES = {"market": MARKET_FEEDS}

# Max articles for a market session (bumped above the default 3 so gold/silver
# from the PL feeds still land after the crypto feeds fill early slots).
MARKET_MAX_ARTICLES = 6

# Substring stems (transliterated, lowercased). Gold uses "zloto"/"zlota"
# (nominative/genitive — "cena złota") on purpose and NOT bare "zlot", so the
# PLN currency "złotego"/"złotych" does not false-match a gold Kronika.
_MARKET_STEMS = (
    "bitcoin", "ethereum", "krypto", "crypto",
    "gold", "silver", "srebr", "zloto", "zlota",
)
# Short tickers matched on token boundaries (avoid substring noise).
_MARKET_TICKERS = frozenset({"btc", "eth", "xau", "xag"})


def _is_market_relevant(title: str, summary: str) -> bool:
    """
    Relevance filter for the market feed profile (BTC / gold / silver).

    required=1 (one asset mention is enough — a headline names one asset).
    Transliterates PL diacritics before matching so ASCII stems catch the
    real declined Polish forms. Generic words ("kurs", "rynek") are excluded
    on purpose — they leak ("konkurs", "rynek pracy") without an asset.
    """
    from agent_core.web_source.content_writer import _PL_TRANS

    text = f"{title} {summary}".translate(_PL_TRANS).lower()
    for stem in _MARKET_STEMS:
        if stem in text:
            return True
    tokens = set(re.findall(r"[a-z0-9]+", text))
    return bool(tokens & _MARKET_TICKERS)


def resolve_feed_profile(goal_store, goal_id) -> Optional[str]:
    """
    Resolve the RSS feed profile for a fetch from the goal's source_kind.

    Single source of truth for the B1 choke-point: BOTH the CapabilityRouter
    path (make_fetch_handler) and the no-router fallback
    (ActionExecutor._exec_fetch) call this, so a market goal never silently
    drifts onto the science feed pipeline. None-safe by design: a missing
    goal_store or goal_id (default handler args, Optional plan.goal_id) yields
    None -> the science default, never an exception that would fail EVERY fetch.
    """
    if not goal_store or not goal_id:
        return None
    try:
        goal = goal_store.get(goal_id)
    except Exception:
        return None
    if goal and (getattr(goal, "metadata", None) or {}).get("source_kind") == "market":
        return "market"
    return None


def run_fetch_session(
    knowledge_analyzer,
    input_dir: Optional[Path] = None,
    registry_path: Optional[Path] = None,
    max_articles: int = 3,
    enable_rss: bool = True,
    semantic_memory=None,
    override_topics: Optional[List[str]] = None,
    feed_profile: Optional[str] = None,
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
        # "skipped" is the grand total; the two below split WHY an entry was
        # skipped so the session report stops conflating "we already have this"
        # (in the fetch registry) with "the write was rejected" (slug file on
        # disk / content too short). Both wiki and rss feed these counters.
        "skipped": 0,
        "skipped_in_registry": 0,   # is_fetched(url) -> already fetched before
        "skipped_write_none": 0,    # write_article returned None (exists/short)
        # R2.1: per-session count of hint topics that fetched 0 articles.
        # Used by decision_log for observability; the actual jsonl marking
        # happens at the bottom of run_fetch_session via mark_hint_unsuccessful.
        "unsuccessful_hints": 0,
    }
    # R2.1: collected for end-of-session marking. We only track topics that
    # came in with strategy="hint" (K12 self-analysis); EXPAND/EXPLORE topics
    # are derived from existing knowledge and don't need lifecycle tracking.
    unsuccessful_hint_topics: List[str] = []

    # Kronika: the "market" profile fetches straight from MARKET_FEEDS with its
    # own bilingual matcher, ignoring topic suggestions and Wikipedia entirely.
    # feed_profile is echoed into stats so fetch_decisions.jsonl can tell a real
    # market fetch from the science default (B1 PASS criterion is grep-able).
    market = feed_profile == "market"
    stats["feed_profile"] = feed_profile or "default"
    if market:
        # Bump the cap so gold/silver (PL feeds, iterated after crypto) still land.
        max_articles = max(max_articles, MARKET_MAX_ARTICLES)

    # Initialize components
    registry = FetchRegistry(registry_path=registry_path)
    wiki = WikiClient()
    writer = ContentWriter(input_dir=input_dir, fetch_registry=registry)
    # Derive project root from input_dir for topic hints (K12)
    _project_root = str(input_dir.parent) if input_dir else "."
    suggester = TopicSuggester(knowledge_analyzer, project_root=_project_root)
    if semantic_memory:
        suggester.set_semantic_memory(semantic_memory)

    # Step 1: Get topic suggestions (science profile only). The market profile
    # bypasses the suggester AND the "no topics -> return" gate: it has fixed
    # feeds and a matcher that ignores topics, so an empty suggester must not
    # short-circuit it before Step 3 (Kronika review: early-return before RSS).
    suggestions: List[Dict[str, Any]] = []
    if not market:
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
        had_titles = False

        try:
            # Search Wikipedia
            titles = wiki.search(topic, limit=3)
            had_titles = bool(titles)
            if not titles:
                logger.debug(f"[WEB_SOURCE] No Wikipedia results for '{topic}'")
                # Dead topic: Wikipedia has no article for this query (deterministic,
                # not a transient error -- those raise and land in the except below).
                # Record it so the suggester stops re-handing EXPLORE slots to Maria's
                # un-searchable self-jargon and reaches real topics instead.
                registry.mark_topic_dead(topic)
            else:
                # Try first non-fetched title
                for title in titles:
                    url = f"https://pl.wikipedia.org/wiki/{title.replace(' ', '_')}"
                    if registry.is_fetched(url):
                        stats["skipped"] += 1
                        stats["skipped_in_registry"] += 1
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
                        stats["skipped_write_none"] += 1

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

        # Topic HAD Wikipedia articles but produced 0 new files: every title was
        # one we already have on disk -> the topic is exhausted, not dead. Mark it
        # so the suggester frees its EXPLORE slot for a fresh topic instead of
        # re-proposing this saturated one every ~60s. Errors excluded (transient,
        # not "fully harvested"); the 0-titles case is already handled as dead.
        if (
            had_titles
            and not had_error
            and stats["articles_fetched"] == articles_before
        ):
            registry.mark_topic_exhausted(topic)

    # Step 3: Fetch from RSS. Science profile filters by topic relevance;
    # market profile uses fixed MARKET_FEEDS + its own bilingual matcher.
    if enable_rss and stats["articles_fetched"] < max_articles:
        try:
            article_fetcher = None
            if market:
                rss = RSSClient(feed_urls=FEED_PROFILES["market"])
                topic_keywords = set()  # unused for market (matcher ignores topics)
                article_fetcher = ArticleFetcher()
                logger.debug(
                    "[WEB_SOURCE] RSS market profile: %s", FEED_PROFILES["market"]
                )
            else:
                rss = RSSClient()
                topic_keywords = _build_topic_keywords(suggestions)
                logger.debug(
                    f"[WEB_SOURCE] RSS topic filter keywords: {topic_keywords}"
                )

            entries = rss.fetch_all(interleave=market)

            for entry in entries:
                if stats["articles_fetched"] >= max_articles:
                    break

                link = entry.get("link", "")
                title = entry.get("title", "")
                summary = entry.get("summary", "")

                # Market entries may be title-only (thin/empty summary) -- the
                # body is fetched from the page below -- so only link+title are
                # mandatory for the market profile.
                if not link or not title or (not market and not summary):
                    continue

                if registry.is_fetched(link):
                    stats["skipped"] += 1
                    stats["skipped_in_registry"] += 1
                    continue

                # Filter: market matcher for the market profile, else topic filter
                relevant = (
                    _is_market_relevant(title, summary)
                    if market
                    else _is_rss_relevant(title, summary, topic_keywords)
                )
                if not relevant:
                    stats["rss_filtered"] += 1
                    continue

                # Market: fetch the full article body (feeds carry thin summaries);
                # fall back to the summary if the body fetch/extract fails.
                if market:
                    body = article_fetcher.fetch_body(link)
                    content = body if body else summary
                else:
                    content = summary

                filename = writer.write_article(
                    title=title,
                    content=content,
                    url=link,
                    source_type="rss",
                    # Date-stamp market files: a 14-day kronika has repeatable
                    # titles ("Cena zlota rosnie") that would otherwise collide
                    # on slug and be silently dropped (write_article -> None).
                    dated_slug=market,
                )

                if filename:
                    stats["articles_fetched"] += 1
                    stats["fetched_files"].append(filename)
                    stats["rss_fetched"] += 1
                    logger.info(f"[WEB_SOURCE] RSS: {filename}")
                else:
                    stats["skipped"] += 1
                    stats["skipped_write_none"] += 1

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
        f"{stats['skipped']} skipped "
        f"({stats['skipped_in_registry']} in-registry, "
        f"{stats['skipped_write_none']} write-none), "
        f"{stats['errors']} errors, "
        f"{stats['unsuccessful_hints']} unsuccessful hints"
    )

    return stats
