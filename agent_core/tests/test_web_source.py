"""
Tests for Web Content Fetcher (agent_core/web_source/).

All HTTP calls are mocked. No real network access.
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from agent_core.web_source.fetch_registry import (
    FetchRegistry,
    DEAD_TOPIC_TTL_SEC,
    EXHAUSTED_TOPIC_TTL_SEC,
)
from agent_core.web_source.wiki_client import WikiClient, WikiTransientError
from agent_core.web_source.rss_client import RSSClient
from agent_core.web_source.content_writer import ContentWriter
from agent_core.web_source.topic_suggester import TopicSuggester
from agent_core.web_source import (
    run_fetch_session, _build_topic_keywords, _is_rss_relevant,
    _is_market_relevant, resolve_feed_profile,
)
from agent_core.web_source.rss_client import MARKET_FEEDS
from agent_core.web_source.article_fetcher import ArticleFetcher, extract_main_text
from agent_core.teacher.knowledge_analyzer import KnowledgeAnalyzer
from agent_core.goals.goal_model import Goal
from agent_core.goals.store import GoalStore
from agent_core.tests.spec_helpers import specced


# ══════════════════════════════════════════════════════
# FetchRegistry Tests
# ══════════════════════════════════════════════════════


class TestFetchRegistry:
    """FetchRegistry JSONL tests with tmp_path."""

    def test_empty_registry(self, tmp_path):
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        assert reg.is_fetched("https://example.com") is False
        assert reg.get_stats()["total_fetched"] == 0

    def test_register_and_is_fetched(self, tmp_path):
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        reg.register(
            url="https://pl.wikipedia.org/wiki/Logika",
            title="Logika",
            source_type="wikipedia",
            output_file="web_wiki_logika.txt",
            char_count=5000,
            topic="logika",
        )
        assert reg.is_fetched("https://pl.wikipedia.org/wiki/Logika") is True
        assert reg.is_fetched("https://other.com") is False

    def test_is_topic_fetched(self, tmp_path):
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        reg.register(
            url="https://example.com/1",
            title="Test",
            source_type="wikipedia",
            output_file="test.txt",
            char_count=100,
            topic="Logika",
        )
        assert reg.is_topic_fetched("logika") is True
        assert reg.is_topic_fetched("LOGIKA") is True
        assert reg.is_topic_fetched("fizyka") is False

    def test_dead_topic_marked_and_persists(self, tmp_path):
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        assert reg.is_topic_dead("analiza tekstu") is False
        reg.mark_topic_dead("Analiza Tekstu")  # case-insensitive
        assert reg.is_topic_dead("analiza tekstu") is True
        reg.mark_topic_dead("analiza tekstu")  # idempotent (no dup line)
        # Survives a fresh load (persisted to its own sibling file).
        reg2 = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        assert reg2.is_topic_dead("analiza tekstu") is True
        assert reg2.is_topic_dead("logika formalna") is False

    def test_dead_topic_verdict_expires(self, tmp_path):
        """A dead-topic verdict is provisional, not lifelong.

        Nothing in the repo ever deleted these entries, so a topic marked once
        was gone from Maria's curiosity forever. Real self-jargon just gets
        re-marked on its next miss; a mistaken mark heals itself.
        """
        path = tmp_path / "reg.jsonl"
        dead_path = path.with_name("web_dead_topics.jsonl")
        stale = time.time() - (DEAD_TOPIC_TTL_SEC + 3600)
        fresh = time.time() - 60
        dead_path.write_text(
            json.dumps({"topic": "dawno skreslony", "ts": stale}, ensure_ascii=False) + "\n"
            + json.dumps({"topic": "swiezo skreslony", "ts": fresh}, ensure_ascii=False) + "\n"
            + json.dumps({"topic": "bez znacznika"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        reg = FetchRegistry(registry_path=path)
        assert reg.is_topic_dead("swiezo skreslony") is True
        assert reg.is_topic_dead("dawno skreslony") is False
        # Brak ts = wpis sprzed TTL-a, nie wieczny.
        assert reg.is_topic_dead("bez znacznika") is False

    def test_exhausted_topic_marked_and_persists(self, tmp_path):
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        assert reg.is_topic_exhausted("fotosynteza") is False
        reg.mark_topic_exhausted("Fotosynteza")  # case-insensitive
        assert reg.is_topic_exhausted("fotosynteza") is True
        reg.mark_topic_exhausted("fotosynteza")  # idempotent (no dup line)
        # Survives a fresh load (own sibling file).
        reg2 = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        assert reg2.is_topic_exhausted("fotosynteza") is True
        assert reg2.is_topic_exhausted("biologia molekularna") is False

    def test_exhausted_and_dead_are_independent(self, tmp_path):
        """Exhausted (articles all on disk) and dead (no articles at all) are
        different verdicts in different files -- one must not leak into the other."""
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        reg.mark_topic_exhausted("zloto")
        reg.mark_topic_dead("strukturyzacja wiedzy")
        assert reg.is_topic_exhausted("zloto") is True
        assert reg.is_topic_dead("zloto") is False
        assert reg.is_topic_dead("strukturyzacja wiedzy") is True
        assert reg.is_topic_exhausted("strukturyzacja wiedzy") is False

    def test_exhausted_verdict_expires_sooner_than_dead(self, tmp_path):
        """A harvested topic comes back after EXHAUSTED_TOPIC_TTL_SEC (7d < 30d):
        Wikipedia may add an article, or it is simply worth revisiting."""
        assert EXHAUSTED_TOPIC_TTL_SEC < DEAD_TOPIC_TTL_SEC
        path = tmp_path / "reg.jsonl"
        exh_path = path.with_name("web_exhausted_topics.jsonl")
        stale = time.time() - (EXHAUSTED_TOPIC_TTL_SEC + 3600)
        fresh = time.time() - 60
        exh_path.write_text(
            json.dumps({"topic": "dawno zebrany", "ts": stale}, ensure_ascii=False) + "\n"
            + json.dumps({"topic": "swiezo zebrany", "ts": fresh}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        reg = FetchRegistry(registry_path=path)
        assert reg.is_topic_exhausted("swiezo zebrany") is True
        assert reg.is_topic_exhausted("dawno zebrany") is False

    def test_transient_wiki_failure_does_not_kill_topic(self, tmp_path):
        """The bug this whole fix exists for, pinned end-to-end.

        WikiClient.search used to swallow a 429 and return [], which
        run_fetch_session reads as "Wikipedia has no such article" -> the topic
        is struck off permanently. Uses a REAL FetchRegistry: a mocked registry
        would have happily accepted the bad call and stayed green.
        """
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")

        with patch("agent_core.web_source.wiki_client.requests.Session") as sess_cls:
            sess = MagicMock()
            sess_cls.return_value = sess
            resp = MagicMock()
            import requests as req
            resp.raise_for_status.side_effect = req.HTTPError("429 Too Many Requests")
            sess.get.return_value = resp

            client = WikiClient()
            client._last_request_ts = time.time()

            # Odwzoruj petle sesji: transient MUSI ominac mark_topic_dead.
            try:
                titles = client.search("mechanika kwantowa", limit=3)
                if not titles:
                    reg.mark_topic_dead("mechanika kwantowa")
            except WikiTransientError:
                pass  # jak `except Exception` w run_fetch_session

        assert reg.is_topic_dead("mechanika kwantowa") is False, (
            "rate-limit skreslil zywy temat -- dokladnie ten bug"
        )

    def test_merge_semantics_last_wins(self, tmp_path):
        path = tmp_path / "reg.jsonl"
        reg = FetchRegistry(registry_path=path)

        # First registration
        reg.register(
            url="https://example.com/a",
            title="Version 1",
            source_type="wikipedia",
            output_file="v1.txt",
            char_count=100,
        )

        # Second registration (same URL, different data)
        reg.register(
            url="https://example.com/a",
            title="Version 2",
            source_type="wikipedia",
            output_file="v2.txt",
            char_count=200,
        )

        # Reload and check last wins
        reg2 = FetchRegistry(registry_path=path)
        data = reg2.get_all()
        assert data["https://example.com/a"]["title"] == "Version 2"
        assert data["https://example.com/a"]["char_count"] == 200

    def test_stats(self, tmp_path):
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        reg.register("https://a.com", "A", "wikipedia", "a.txt", 1000)
        reg.register("https://b.com", "B", "rss", "b.txt", 2000)
        reg.register("https://c.com", "C", "wikipedia", "c.txt", 500)

        stats = reg.get_stats()
        assert stats["total_fetched"] == 3
        assert stats["by_source"]["wikipedia"] == 2
        assert stats["by_source"]["rss"] == 1
        assert stats["total_chars"] == 3500

    def test_corrupted_line_skipped(self, tmp_path):
        path = tmp_path / "reg.jsonl"
        path.write_text(
            '{"url":"https://a.com","title":"A","source_type":"wiki","output_file":"a.txt","char_count":100}\n'
            'THIS IS NOT JSON\n'
            '{"url":"https://b.com","title":"B","source_type":"rss","output_file":"b.txt","char_count":200}\n'
        )
        reg = FetchRegistry(registry_path=path)
        assert reg.is_fetched("https://a.com") is True
        assert reg.is_fetched("https://b.com") is True
        assert reg.get_stats()["total_fetched"] == 2

    def test_nonexistent_file(self, tmp_path):
        reg = FetchRegistry(registry_path=tmp_path / "nonexistent.jsonl")
        assert reg.get_stats()["total_fetched"] == 0
        assert reg.is_fetched("anything") is False

    def test_register_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "reg.jsonl"
        reg = FetchRegistry(registry_path=path)
        reg.register("https://x.com", "X", "wikipedia", "x.txt", 100)
        assert path.exists()


# ══════════════════════════════════════════════════════
# WikiClient Tests
# ══════════════════════════════════════════════════════


class TestWikiClient:
    """WikiClient unit tests with mocked requests."""

    def _make_client(self):
        client = WikiClient()
        client._last_request_ts = time.time()  # skip rate limit in tests
        return client

    @patch("agent_core.web_source.wiki_client.requests.Session")
    def test_search_returns_titles(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            "logika",
            ["Logika", "Logika matematyczna", "Logika modalna"],
            ["", "", ""],
            ["url1", "url2", "url3"],
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        client = WikiClient()
        client._last_request_ts = time.time()
        titles = client.search("logika")
        assert titles == ["Logika", "Logika matematyczna", "Logika modalna"]

    @patch("agent_core.web_source.wiki_client.requests.Session")
    def test_search_empty_query(self, mock_session_cls):
        client = WikiClient()
        assert client.search("") == []
        assert client.search("   ") == []

    @patch("agent_core.web_source.wiki_client.requests.Session")
    def test_search_network_error(self, mock_session_cls):
        """Transient failure must RAISE, never return [].

        [] is the permanent verdict "Wikipedia has no such article" and
        run_fetch_session acts on it via mark_topic_dead. This test used to
        assert == [], pinning the very bug that let a 429 erase live topics
        forever (15 such 429s on 2026-07-14 alone).
        """
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        import requests as req
        mock_session.get.side_effect = req.RequestException("timeout")

        client = WikiClient()
        client._last_request_ts = time.time()
        with pytest.raises(WikiTransientError):
            client.search("test")

    @patch("agent_core.web_source.wiki_client.requests.Session")
    def test_search_no_results_returns_empty(self, mock_session_cls):
        """Wikipedia answered and had nothing -> [] (the permanent verdict).

        The other half of the contract: only THIS path may feed mark_topic_dead.
        """
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = ["nieistniejace haslo", [], [], []]
        mock_session.get.return_value = resp

        client = WikiClient()
        client._last_request_ts = time.time()
        assert client.search("nieistniejace haslo") == []

    @patch("agent_core.web_source.wiki_client.requests.Session")
    def test_fetch_article_success(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        content = "A" * 500  # valid length
        mock_resp.json.return_value = {
            "query": {
                "pages": {
                    "12345": {
                        "title": "Logika",
                        "extract": content,
                        "fullurl": "https://pl.wikipedia.org/wiki/Logika",
                    }
                }
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        client = WikiClient()
        client._last_request_ts = time.time()
        result = client.fetch_article("Logika")

        assert result is not None
        assert result["title"] == "Logika"
        assert result["content"] == content
        assert "Logika" in result["url"]

    @patch("agent_core.web_source.wiki_client.requests.Session")
    def test_fetch_article_too_short(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "query": {"pages": {"1": {"title": "Stub", "extract": "Short."}}}
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        client = WikiClient()
        client._last_request_ts = time.time()
        assert client.fetch_article("Stub") is None

    @patch("agent_core.web_source.wiki_client.requests.Session")
    def test_fetch_article_not_found(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "query": {"pages": {"-1": {"title": "Missing", "missing": ""}}}
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        client = WikiClient()
        client._last_request_ts = time.time()
        assert client.fetch_article("Missing") is None

    @patch("agent_core.web_source.wiki_client.requests.Session")
    def test_fetch_article_truncates_long(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        # Content with paragraph breaks
        content = ("A" * 5000 + "\n\n" + "B" * 5000 + "\n\n" + "C" * 10000)
        mock_resp.json.return_value = {
            "query": {"pages": {"1": {"title": "Long", "extract": content}}}
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        client = WikiClient()
        client._last_request_ts = time.time()
        result = client.fetch_article("Long")

        assert result is not None
        assert len(result["content"]) <= 15000

    def test_fetch_empty_title(self):
        client = WikiClient()
        assert client.fetch_article("") is None
        assert client.fetch_article("   ") is None


# ══════════════════════════════════════════════════════
# RSSClient Tests
# ══════════════════════════════════════════════════════


RSS20_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Test Feed</title>
  <item>
    <title>Article One</title>
    <link>https://example.com/1</link>
    <description>Summary of article one.</description>
    <pubDate>Mon, 08 Mar 2026 12:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Article Two</title>
    <link>https://example.com/2</link>
    <description>Summary of article two.</description>
  </item>
</channel>
</rss>"""

ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Atom Entry</title>
    <link href="https://example.com/atom1"/>
    <summary>Atom summary text.</summary>
    <published>2026-03-08T12:00:00Z</published>
  </entry>
</feed>"""


class TestRSSClient:
    """RSSClient unit tests with mocked requests."""

    @patch("agent_core.web_source.rss_client.requests.Session")
    def test_fetch_entries_rss20(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.text = RSS20_SAMPLE
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        client = RSSClient(feed_urls=["https://test.com/rss"])
        client._last_request_ts = time.time()
        entries = client.fetch_entries("https://test.com/rss")

        assert len(entries) == 2
        assert entries[0]["title"] == "Article One"
        assert entries[0]["link"] == "https://example.com/1"
        assert entries[0]["summary"] == "Summary of article one."
        assert entries[1]["title"] == "Article Two"

    @patch("agent_core.web_source.rss_client.requests.Session")
    def test_fetch_entries_atom(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.text = ATOM_SAMPLE
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        client = RSSClient(feed_urls=["https://test.com/atom"])
        client._last_request_ts = time.time()
        entries = client.fetch_entries("https://test.com/atom")

        assert len(entries) == 1
        assert entries[0]["title"] == "Atom Entry"
        assert entries[0]["link"] == "https://example.com/atom1"
        assert entries[0]["summary"] == "Atom summary text."

    @patch("agent_core.web_source.rss_client.requests.Session")
    def test_fetch_entries_network_error(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        import requests as req
        mock_session.get.side_effect = req.RequestException("timeout")

        client = RSSClient(feed_urls=["https://fail.com/rss"])
        client._last_request_ts = time.time()
        entries = client.fetch_entries("https://fail.com/rss")
        assert entries == []

    @patch("agent_core.web_source.rss_client.requests.Session")
    def test_fetch_entries_invalid_xml(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.text = "NOT VALID XML <><><>"
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        client = RSSClient(feed_urls=["https://test.com/bad"])
        client._last_request_ts = time.time()
        assert client.fetch_entries("https://test.com/bad") == []

    @patch("agent_core.web_source.rss_client.requests.Session")
    def test_fetch_all_deduplicates(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.text = RSS20_SAMPLE
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        # Two feeds returning same content
        client = RSSClient(feed_urls=["https://a.com/rss", "https://b.com/rss"])
        client._last_request_ts = time.time()
        entries = client.fetch_all()

        # Should deduplicate by link
        assert len(entries) == 2  # not 4

    def test_default_feeds_exist(self):
        client = RSSClient()
        assert len(client.feeds) >= 1

    def test_custom_feeds(self):
        feeds = ["https://custom.com/rss"]
        client = RSSClient(feed_urls=feeds)
        assert client.feeds == feeds


# ══════════════════════════════════════════════════════
# ContentWriter Tests
# ══════════════════════════════════════════════════════


class TestContentWriter:
    """ContentWriter tests with tmp_path."""

    def test_write_article_creates_file(self, tmp_path):
        writer = ContentWriter(input_dir=tmp_path)
        filename = writer.write_article(
            title="Logika",
            content="A" * 500,
            url="https://pl.wikipedia.org/wiki/Logika",
            source_type="wikipedia",
        )
        assert filename == "web_wiki_logika.txt"
        assert (tmp_path / filename).exists()

    def test_write_article_with_header(self, tmp_path):
        writer = ContentWriter(input_dir=tmp_path)
        writer.write_article(
            title="Test Article",
            content="Content here " * 50,
            url="https://example.com/test",
            source_type="wikipedia",
        )
        text = (tmp_path / "web_wiki_test_article.txt").read_text(encoding="utf-8")
        assert text.startswith("# Zrodlo: Wikipedia (pl)")
        assert "# Tytul: Test Article" in text
        assert "# URL: https://example.com/test" in text
        assert "# ---" in text
        assert "Content here" in text

    def test_write_article_registers_in_registry(self, tmp_path):
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        writer = ContentWriter(input_dir=tmp_path, fetch_registry=reg)
        writer.write_article(
            title="Test",
            content="A" * 300,
            url="https://example.com/test",
            source_type="wikipedia",
            topic="logika",
        )
        assert reg.is_fetched("https://example.com/test") is True
        assert reg.is_topic_fetched("logika") is True

    def test_write_article_skips_duplicate_url(self, tmp_path):
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        reg.register("https://dupe.com", "Dupe", "wiki", "old.txt", 100)

        writer = ContentWriter(input_dir=tmp_path, fetch_registry=reg)
        result = writer.write_article(
            title="Dupe",
            content="A" * 300,
            url="https://dupe.com",
            source_type="wikipedia",
        )
        assert result is None

    def test_write_article_skips_existing_file(self, tmp_path):
        # Create existing file
        (tmp_path / "web_wiki_existing.txt").write_text("old content")

        writer = ContentWriter(input_dir=tmp_path)
        result = writer.write_article(
            title="Existing",
            content="A" * 300,
            url="https://new-url.com",
            source_type="wikipedia",
        )
        assert result is None

    def test_write_article_skips_short_content(self, tmp_path):
        writer = ContentWriter(input_dir=tmp_path)
        result = writer.write_article(
            title="Short",
            content="Too short",
            url="https://example.com/short",
            source_type="wikipedia",
        )
        assert result is None

    def test_write_rss_naming(self, tmp_path):
        writer = ContentWriter(input_dir=tmp_path)
        filename = writer.write_article(
            title="Nauka o mozgu",
            content="A" * 300,
            url="https://feed.com/article",
            source_type="rss",
        )
        assert filename is not None
        assert filename.startswith("web_rss_")

    def test_slugify_basic(self):
        assert ContentWriter._slugify("Logika matematyczna") == "logika_matematyczna"
        assert ContentWriter._slugify("Hello World!") == "hello_world"

    def test_slugify_polish_chars(self):
        slug = ContentWriter._slugify("za\u017c\u00f3\u0142\u0107")
        assert slug == "zazolc"

    def test_slugify_max_length(self):
        long_title = "A" * 100
        slug = ContentWriter._slugify(long_title)
        assert len(slug) <= 50

    def test_slugify_special_characters(self):
        slug = ContentWriter._slugify("Test (filozofia) - cz. 1")
        assert slug == "test_filozofia_cz_1"

    def test_slugify_empty_fallback(self):
        slug = ContentWriter._slugify("!!!")
        assert slug.startswith("article_")

    def test_source_label(self):
        assert ContentWriter._source_label("wikipedia") == "Wikipedia (pl)"
        assert ContentWriter._source_label("rss") == "RSS Feed"
        assert ContentWriter._source_label("other") == "other"


# ══════════════════════════════════════════════════════
# TopicSuggester Tests
# ══════════════════════════════════════════════════════


def _make_mock_analyzer(
    topic_map=None,
    tag_freq=None,
):
    """Create mock KnowledgeAnalyzer."""
    analyzer = specced(KnowledgeAnalyzer)
    analyzer.get_topic_file_map.return_value = topic_map or {}
    analyzer.get_tag_frequency_map.return_value = tag_freq or {}
    return analyzer


def test_is_fetchable_concept_rejects_sentences_and_files():
    """2026-06-20 (review MF1): only clean 1-3 word concepts are Wikipedia-searchable."""
    from agent_core.web_source.topic_suggester import _is_fetchable_concept
    assert _is_fetchable_concept("mechanika")
    assert _is_fetchable_concept("fizyka kwantowa")
    assert _is_fetchable_concept("teoria wzglednosci ogolnej")  # 3 words ok
    assert not _is_fetchable_concept("Dla liczb nieparzystych: c_{n+1} = 3/2")  # formula
    assert not _is_fetchable_concept("a bardzo dluga zdaniowa fraza tutaj")     # >3 words
    assert not _is_fetchable_concept("web_rss_cos.txt")                          # file-id
    assert not _is_fetchable_concept("ab")                                       # too short
    assert not _is_fetchable_concept("knowledge_coverage")                       # snake_case id
    assert not _is_fetchable_concept("hard_topic")                              # snake_case id
    assert not _is_fetchable_concept("m.a.r.i.a.")                              # dotted acronym -> 0 wiki titles


class TestTopicSuggester:
    """TopicSuggester tests with mocked KnowledgeAnalyzer."""

    def test_suggest_expand_from_topic_map(self, tmp_path):
        analyzer = _make_mock_analyzer(
            topic_map={
                "logika": ["file1", "file2", "file3"],
                "fizyka": ["file4", "file5"],
                "biologia": ["file6"],
            }
        )
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggestions = suggester.suggest_topics()

        # Should pick top topics by file count
        topics = [s["topic"] for s in suggestions]
        assert "logika" in topics
        assert "fizyka" in topics

        # All should be "expand" strategy
        for s in suggestions:
            if s["strategy"] == "expand":
                assert "poglebienie" in s["reason"]

    def test_suggest_explore_from_tag_frequency(self, tmp_path):
        analyzer = _make_mock_analyzer(
            topic_map={"logika": ["f1"]},
            tag_freq={
                "myslenie": 5,
                "percepcja": 4,
                "analiza": 3,
                "rzadki": 1,
            },
        )
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggestions = suggester.suggest_topics()

        # Should include explore topics
        strategies = {s["strategy"] for s in suggestions}
        assert "explore" in strategies

        # "rzadki" (freq 1) should NOT be included
        topics = [s["topic"] for s in suggestions]
        assert "rzadki" not in topics

    def test_expand_resuggests_fetched_topic_for_deepening(self, tmp_path):
        # 2026-06-20: EXPAND no longer skips an already-fetched topic. The fetch
        # loop dedups at the article/URL level and pulls the next adjacent title,
        # so a known (fetched) topic is re-suggested to deepen it rather than going
        # dark -- this is what unblocks the supply pipeline.
        analyzer = _make_mock_analyzer(
            topic_map={"logika": ["f1", "f2"], "fizyka": ["f3"]},
        )
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        reg.register("https://x.com", "X", "wiki", "x.txt", 100, topic="logika")

        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggestions = suggester.suggest_topics(fetch_registry=reg)

        topics = [s["topic"] for s in suggestions]
        assert "logika" in topics  # re-suggested for deepening, not filtered out
        assert "fizyka" in topics

    def test_explore_slot_reserved_when_others_saturate(self, tmp_path):
        # Slot-starvation fix (2026-06-26): DREAM/PLAY/HINT/EXPAND must not consume
        # every slot. Even when they'd fill all 5, EXPLORE (the fresh-tag strategy)
        # gets its reserved slots. Without the fix EXPLORE got 0 here.
        analyzer = _make_mock_analyzer(
            tag_freq={"semantyka": 9, "logika": 8, "topologia": 7},  # fresh EXPLORE candidates
        )
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        # Saturate every pre-EXPLORE strategy.
        suggester._dream_topics = lambda: [
            {"topic": f"dream{i}", "strategy": "dream", "reason": "d"} for i in range(5)
        ]
        suggester._play_topics = lambda: [{"topic": "play1", "strategy": "play", "reason": "p"}]
        suggester._hint_topics = lambda: [
            {"topic": f"hint{i}", "strategy": "hint", "reason": "h"} for i in range(5)
        ]
        suggester._expand_topics = lambda: [
            {"topic": f"exp{i}", "strategy": "expand", "reason": "e"} for i in range(5)
        ]
        suggestions = suggester.suggest_topics()
        strategies = [s["strategy"] for s in suggestions]
        assert "explore" in strategies  # reserved slot reached EXPLORE despite saturation
        assert sum(1 for s in strategies if s == "explore") >= 1

    def test_explore_skips_already_fetched_tags(self, tmp_path):
        # EXPLORE now prefers FRESH (never-fetched) tags so the reserved slots
        # surface genuinely-new material instead of bouncing off the saturated set.
        analyzer = _make_mock_analyzer(
            tag_freq={"semantyka": 9, "logika": 8, "topologia": 7},
        )
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        reg.register("https://x", "Semantyka", "wiki", "s.txt", 100, topic="semantyka")
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggester._dream_topics = lambda: []
        suggester._play_topics = lambda: []
        suggester._hint_topics = lambda: []
        suggester._expand_topics = lambda: []
        suggestions = suggester.suggest_topics(fetch_registry=reg)
        topics = [s["topic"] for s in suggestions]
        assert "semantyka" not in topics  # already fetched -> skipped
        assert "logika" in topics         # fresh -> included

    def test_explore_skips_dead_topics(self, tmp_path):
        # Completer: a topic Wikipedia has no article for (self-jargon) is retired,
        # so the reserved EXPLORE slots reach REAL topics instead of dead jargon.
        analyzer = _make_mock_analyzer(
            tag_freq={"analiza tekstu": 9, "logika formalna": 8, "semantyka": 7},
        )
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        reg.mark_topic_dead("analiza tekstu")  # 0 Wikipedia titles
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggester._dream_topics = lambda: []
        suggester._play_topics = lambda: []
        suggester._hint_topics = lambda: []
        suggester._expand_topics = lambda: []
        suggestions = suggester.suggest_topics(fetch_registry=reg)
        topics = [s["topic"] for s in suggestions]
        assert "analiza tekstu" not in topics   # dead -> skipped
        assert "logika formalna" in topics      # real -> surfaced into the freed slot

    def test_dream_topics_seed_fetch_with_priority(self, tmp_path):
        # 2026-06-20: dreams surface curiosity concepts (sleep_processor sets
        # to_explore + topics); TopicSuggester picks them first, drops file-id
        # entities, and ignores dreams without to_explore.
        import json
        meta = tmp_path / "meta_data"
        meta.mkdir()
        (meta / "dream_log.jsonl").write_text("\n".join(json.dumps(x) for x in [
            {"type": "old", "to_explore": None, "topics": ["pomijane"]},
            {"type": "connection", "to_explore": True,
             "topics": ["mechanika kwantowa", "web_rss_smieci.txt"]},
        ]) + "\n", encoding="utf-8")

        analyzer = _make_mock_analyzer(topic_map={"logika": ["f1"]})
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggestions = suggester.suggest_topics()

        topics = [s["topic"] for s in suggestions]
        strategies = {s["topic"]: s["strategy"] for s in suggestions}
        assert "mechanika kwantowa" in topics            # dream concept fetched
        assert strategies["mechanika kwantowa"] == "dream"
        assert "web_rss_smieci.txt" not in topics         # file-id entity dropped
        assert "pomijane" not in topics                   # no to_explore -> skipped
        assert topics[0] == "mechanika kwantowa"          # DREAM has priority

    def test_play_topics_prefer_returned_thread(self, tmp_path):
        # 2026-06-20: PLAY strategy -- a waking fascination she keeps coming back
        # to (play_module stores clean TOPIC labels in `topics`) steers fresh
        # supply. Returned-to threads (continues set) win the single slot over
        # one-off musings; file-id/sentence labels are dropped.
        import json
        meta = tmp_path / "meta_data"
        meta.mkdir()
        (meta / "play_journal.jsonl").write_text("\n".join(json.dumps(x) for x in [
            {"kind": "daydream", "continues": None, "topics": ["filozofia"]},
            {"kind": "daydream", "continues": "play-001",
             "topics": ["mechanika kwantowa", "web_rss_smieci.txt"]},
            {"kind": "daydream", "continues": None, "topics": []},
        ]) + "\n", encoding="utf-8")

        analyzer = _make_mock_analyzer(topic_map={"logika": ["f1"]})
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))

        # Method ordering: returned-to fascination ranks first, file-id dropped.
        play = suggester._play_topics()
        play_topics = [p["topic"] for p in play]
        assert play_topics[0] == "mechanika kwantowa"     # continues= wins
        assert "filozofia" in play_topics                 # one-off still offered
        assert "web_rss_smieci.txt" not in play_topics    # file-id dropped
        assert play[0]["strategy"] == "play"
        assert "Wraca do tego" in play[0]["reason"]

        # Integration: the single PLAY slot is the returned-to topic.
        suggestions = suggester.suggest_topics()
        play_slot = [s for s in suggestions if s["strategy"] == "play"]
        assert len(play_slot) == 1                         # one slot only
        assert play_slot[0]["topic"] == "mechanika kwantowa"

    def test_suggest_empty_topic_map(self, tmp_path):
        analyzer = _make_mock_analyzer()
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggestions = suggester.suggest_topics()
        assert suggestions == []

    def test_suggest_respects_max_suggestions(self, tmp_path):
        analyzer = _make_mock_analyzer(
            topic_map={
                "t1": ["f1", "f2"],
                "t2": ["f3", "f4"],
                "t3": ["f5"],
                "t4": ["f6"],
            },
            tag_freq={"tag1": 5, "tag2": 4, "tag3": 3},
        )
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggestions = suggester.suggest_topics(max_suggestions=2)
        assert len(suggestions) <= 2

    def test_suggest_skips_short_tags(self, tmp_path):
        analyzer = _make_mock_analyzer(
            topic_map={"ab": ["f1"], "logika": ["f2"]},
        )
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggestions = suggester.suggest_topics()
        topics = [s["topic"] for s in suggestions]
        assert "ab" not in topics  # too short (< 3 chars)

    def test_hint_topics_from_file(self, tmp_path):
        """K12 hints are read from topic_hints.jsonl."""
        # Write hints file
        hints_path = tmp_path / "meta_data" / "topic_hints.jsonl"
        hints_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(hints_path, "w") as f:
            f.write(json.dumps({"topic": "fizyka kwantowa", "priority": 0.9,
                                "source": "self_analysis", "consumed": False}) + "\n")
            f.write(json.dumps({"topic": "chemia organiczna", "priority": 0.7,
                                "source": "self_analysis", "consumed": False}) + "\n")
            f.write(json.dumps({"topic": "already done", "priority": 0.5,
                                "source": "self_analysis", "consumed": True}) + "\n")

        analyzer = _make_mock_analyzer(topic_map={"logika": ["f1"]})
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggestions = suggester.suggest_topics()

        # Hints should come first, consumed hints skipped
        topics = [s["topic"] for s in suggestions]
        assert topics[0] == "fizyka kwantowa"  # highest priority hint
        assert "chemia organiczna" in topics
        assert "already done" not in topics

        # Strategy should be "hint"
        hint_suggestions = [s for s in suggestions if s["strategy"] == "hint"]
        assert len(hint_suggestions) == 2

    def test_hint_topics_filters_unfetchable(self, tmp_path):
        """Un-searchable self_analysis hints (snake_case ids, >3-word phrases)
        are dropped; only fetchable hints reach the suggester queue."""
        hints_path = tmp_path / "meta_data" / "topic_hints.jsonl"
        hints_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(hints_path, "w") as f:
            f.write(json.dumps({"topic": "fizyka kwantowa", "priority": 0.9,
                                "consumed": False}) + "\n")
            f.write(json.dumps({"topic": "knowledge_coverage", "priority": 0.8,
                                "consumed": False}) + "\n")
            f.write(json.dumps({"topic": "Recent Learn Success Rate", "priority": 0.7,
                                "consumed": False}) + "\n")

        analyzer = _make_mock_analyzer(topic_map={"logika": ["f1"]})
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        hint_topics = [s["topic"] for s in suggester.suggest_topics()
                       if s["strategy"] == "hint"]
        assert hint_topics == ["fizyka kwantowa"]

    def test_hint_topics_empty_file(self, tmp_path):
        """No hints file = no hint suggestions."""
        analyzer = _make_mock_analyzer(topic_map={"logika": ["f1", "f2"]})
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggestions = suggester.suggest_topics()

        hint_suggestions = [s for s in suggestions if s["strategy"] == "hint"]
        assert len(hint_suggestions) == 0

    def test_hint_topics_sorted_by_priority(self, tmp_path):
        """Hints are sorted by priority (highest first)."""
        hints_path = tmp_path / "meta_data" / "topic_hints.jsonl"
        hints_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(hints_path, "w") as f:
            f.write(json.dumps({"topic": "low prio", "priority": 0.3, "consumed": False}) + "\n")
            f.write(json.dumps({"topic": "high prio", "priority": 0.95, "consumed": False}) + "\n")

        analyzer = _make_mock_analyzer()
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggestions = suggester.suggest_topics()

        hints = [s for s in suggestions if s["strategy"] == "hint"]
        assert hints[0]["topic"] == "high prio"

    def test_mark_hint_consumed(self, tmp_path):
        """Already-fetched hints are marked consumed."""
        hints_path = tmp_path / "meta_data" / "topic_hints.jsonl"
        hints_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(hints_path, "w") as f:
            f.write(json.dumps({"topic": "fetched topic", "priority": 0.9, "consumed": False}) + "\n")

        analyzer = _make_mock_analyzer()
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))

        # Simulate: registry says this topic was already fetched
        mock_registry = specced(FetchRegistry)
        mock_registry.is_topic_fetched.return_value = True

        suggestions = suggester.suggest_topics(fetch_registry=mock_registry)
        hint_suggestions = [s for s in suggestions if s["strategy"] == "hint"]
        assert len(hint_suggestions) == 0  # skipped because already fetched

        # Verify hint was marked consumed in file
        with open(hints_path) as f:
            h = json.loads(f.readline())
        assert h["consumed"] is True

    # ─── R2.1 (2026-04-29): hint fail-and-skip lifecycle ───

    def _seed_hint(self, tmp_path, topic="logika formalna", **extra):
        """Helper: seed a single pending hint at the standard location."""
        hints_path = tmp_path / "meta_data" / "topic_hints.jsonl"
        hints_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "topic": topic,
            "source": "self_analysis",
            "priority": 0.9,
            "consumed": False,
        }
        record.update(extra)
        with open(hints_path, "w") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return hints_path

    def test_mark_hint_unsuccessful_increments_counter(self, tmp_path):
        """One unsuccessful call -> failed_attempts=1, still pending."""
        hints_path = self._seed_hint(tmp_path)
        suggester = TopicSuggester(_make_mock_analyzer(), project_root=str(tmp_path))

        suggester.mark_hint_unsuccessful("logika formalna")

        with open(hints_path) as f:
            h = json.loads(f.readline())
        assert h["failed_attempts"] == 1
        assert h["consumed"] is False

    def test_mark_hint_unsuccessful_threshold_consumes(self, tmp_path):
        """After threshold (3) unsuccessful calls -> consumed=True with reason."""
        hints_path = self._seed_hint(tmp_path)
        suggester = TopicSuggester(_make_mock_analyzer(), project_root=str(tmp_path))

        for _ in range(3):
            suggester.mark_hint_unsuccessful("logika formalna")

        with open(hints_path) as f:
            h = json.loads(f.readline())
        assert h["failed_attempts"] == 3
        assert h["consumed"] is True
        assert h["consumed_reason"] == "failed_3_attempts"

    def test_mark_hint_unsuccessful_skips_already_consumed(self, tmp_path):
        """Consumed hints stay consumed and don't increment further."""
        hints_path = self._seed_hint(
            tmp_path, consumed=True, failed_attempts=3,
            consumed_reason="failed_3_attempts",
        )
        suggester = TopicSuggester(_make_mock_analyzer(), project_root=str(tmp_path))

        suggester.mark_hint_unsuccessful("logika formalna")

        with open(hints_path) as f:
            h = json.loads(f.readline())
        # Still 3 — consumed entries are not touched
        assert h["failed_attempts"] == 3
        assert h["consumed"] is True

    def test_mark_hint_unsuccessful_case_insensitive(self, tmp_path):
        """Topic match is case-insensitive (mirrors RecommendationApplier dedup)."""
        hints_path = self._seed_hint(tmp_path, topic="Logika Formalna")
        suggester = TopicSuggester(_make_mock_analyzer(), project_root=str(tmp_path))

        suggester.mark_hint_unsuccessful("LOGIKA FORMALNA")

        with open(hints_path) as f:
            h = json.loads(f.readline())
        assert h["failed_attempts"] == 1

    def test_mark_hint_unsuccessful_custom_threshold(self, tmp_path):
        """Threshold is parameterized — useful for tests and tunable in prod."""
        hints_path = self._seed_hint(tmp_path)
        suggester = TopicSuggester(_make_mock_analyzer(), project_root=str(tmp_path))

        suggester.mark_hint_unsuccessful("logika formalna", threshold=1)

        with open(hints_path) as f:
            h = json.loads(f.readline())
        assert h["consumed"] is True
        assert h["consumed_reason"] == "failed_1_attempts"


# ══════════════════════════════════════════════════════
# Integration: run_fetch_session
# ══════════════════════════════════════════════════════


class TestExploreSkipsExhausted:
    """The EXPLORE picker must skip topics already fully on disk, so a fresh topic
    surfaces instead of the picker re-proposing the same saturated one forever."""

    def test_explore_skips_exhausted_topic(self, tmp_path):
        analyzer = _make_mock_analyzer(tag_freq={"zloto": 10, "srebro": 10})
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        reg.mark_topic_exhausted("zloto")
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))

        explore = suggester._explore_topics(fetch_registry=reg)
        topics = [r["topic"] for r in explore]

        assert "zloto" not in topics      # exhausted -> skipped
        assert "srebro" in topics         # fresh -> offered

    def test_explore_offers_exhausted_topic_after_ttl(self, tmp_path):
        """The verdict is provisional: once the entry ages past its TTL the topic
        is offered again (Wikipedia may have grown, or it is worth revisiting)."""
        path = tmp_path / "reg.jsonl"
        exh = path.with_name("web_exhausted_topics.jsonl")
        exh.write_text(
            json.dumps({"topic": "zloto",
                        "ts": time.time() - (EXHAUSTED_TOPIC_TTL_SEC + 3600)},
                       ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        analyzer = _make_mock_analyzer(tag_freq={"zloto": 10})
        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))

        topics = [r["topic"] for r in suggester._explore_topics(
            fetch_registry=FetchRegistry(registry_path=path))]
        assert "zloto" in topics


class TestRunFetchSession:
    """Integration tests for run_fetch_session with all mocks."""

    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_full_session(self, mock_wiki_cls, mock_rss_cls, tmp_path):
        # Setup mock WikiClient
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = ["Logika"]
        mock_wiki.fetch_article.return_value = {
            "title": "Logika",
            "content": "X" * 500,
            "url": "https://pl.wikipedia.org/wiki/Logika",
        }

        # Setup mock RSSClient
        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        mock_rss.fetch_all.return_value = []

        # Setup mock analyzer
        analyzer = _make_mock_analyzer(
            topic_map={"logika": ["f1", "f2"]},
        )

        result = run_fetch_session(
            knowledge_analyzer=analyzer,
            input_dir=tmp_path,
            registry_path=tmp_path / "reg.jsonl",
            max_articles=3,
        )

        assert result["articles_fetched"] >= 1
        assert result["wiki_fetched"] >= 1
        assert result["errors"] == 0

        # File should exist
        files = list(tmp_path.glob("web_wiki_*.txt"))
        assert len(files) >= 1

    @patch("agent_core.web_source.WikiClient")
    def test_session_empty_knowledge(self, mock_wiki_cls, tmp_path):
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki

        analyzer = _make_mock_analyzer()  # empty topic map

        result = run_fetch_session(
            knowledge_analyzer=analyzer,
            input_dir=tmp_path,
            registry_path=tmp_path / "reg.jsonl",
            enable_rss=False,
        )

        assert result["articles_fetched"] == 0
        assert result["topics_searched"] == 0

    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_session_respects_max_articles(self, mock_wiki_cls, mock_rss_cls, tmp_path):
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki

        # Return different articles for different searches
        call_count = [0]
        def search_side_effect(query, limit=3):
            call_count[0] += 1
            return [f"Article_{call_count[0]}"]

        mock_wiki.search.side_effect = search_side_effect
        mock_wiki.fetch_article.side_effect = lambda title: {
            "title": title,
            "content": "Y" * 500,
            "url": f"https://pl.wikipedia.org/wiki/{title}",
        }

        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        mock_rss.fetch_all.return_value = []

        analyzer = _make_mock_analyzer(
            topic_map={
                "t1": ["f1", "f2"],
                "t2": ["f3"],
                "t3": ["f4"],
                "t4": ["f5"],
            },
        )

        result = run_fetch_session(
            knowledge_analyzer=analyzer,
            input_dir=tmp_path,
            registry_path=tmp_path / "reg.jsonl",
            max_articles=2,
            enable_rss=False,
        )

        assert result["articles_fetched"] <= 2

    @patch("agent_core.web_source.WikiClient")
    def test_session_handles_wiki_errors(self, mock_wiki_cls, tmp_path):
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.side_effect = Exception("network error")

        analyzer = _make_mock_analyzer(
            topic_map={"logika": ["f1"]},
        )

        result = run_fetch_session(
            knowledge_analyzer=analyzer,
            input_dir=tmp_path,
            registry_path=tmp_path / "reg.jsonl",
            enable_rss=False,
        )

        assert result["errors"] >= 1
        assert result["articles_fetched"] == 0

    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_session_returns_stats(self, mock_wiki_cls, mock_rss_cls, tmp_path):
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = []

        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        mock_rss.fetch_all.return_value = []

        analyzer = _make_mock_analyzer(
            topic_map={"logika": ["f1"]},
        )

        result = run_fetch_session(
            knowledge_analyzer=analyzer,
            input_dir=tmp_path,
            registry_path=tmp_path / "reg.jsonl",
        )

        # All stat keys should be present
        assert "articles_fetched" in result
        assert "topics_searched" in result
        assert "wiki_fetched" in result
        assert "rss_fetched" in result
        assert "rss_filtered" in result
        assert "errors" in result
        assert "skipped" in result
        assert "unsuccessful_hints" in result  # R2.1

    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_session_marks_unsuccessful_hint(
        self, mock_wiki_cls, mock_rss_cls, tmp_path,
    ):
        """R2.1: hint with no wiki results gets failed_attempts incremented
        post-session, so it auto-consumes after threshold."""
        # Seed a pending hint in tmp_path/meta_data/
        meta = tmp_path / "meta_data"
        meta.mkdir()
        hints_path = meta / "topic_hints.jsonl"
        with open(hints_path, "w") as f:
            f.write(json.dumps({
                "topic": "Meta-nauka",
                "source": "self_analysis",
                "priority": 1.0,
                "consumed": False,
            }, ensure_ascii=False) + "\n")

        # Wiki returns nothing for any topic
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = []

        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        mock_rss.fetch_all.return_value = []

        # input_dir under tmp_path so suggester finds tmp_path/meta_data/
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        analyzer = _make_mock_analyzer()  # empty topic_map -> hint dominates

        result = run_fetch_session(
            knowledge_analyzer=analyzer,
            input_dir=input_dir,
            registry_path=tmp_path / "reg.jsonl",
        )

        assert result["articles_fetched"] == 0
        assert result["unsuccessful_hints"] == 1

        # Hint counter incremented
        with open(hints_path) as f:
            h = json.loads(f.readline())
        assert h["failed_attempts"] == 1
        assert h["consumed"] is False

    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_session_does_not_mark_expand_strategy(
        self, mock_wiki_cls, mock_rss_cls, tmp_path,
    ):
        """R2.1: only hint-strategy suggestions trigger fail-and-skip.
        EXPAND/EXPLORE topics derive from existing knowledge; the lifecycle
        machinery is hint-only."""
        meta = tmp_path / "meta_data"
        meta.mkdir()

        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = []  # No results for anything

        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        mock_rss.fetch_all.return_value = []

        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # No hints file — only EXPAND topics from analyzer
        analyzer = _make_mock_analyzer(topic_map={"logika": ["f1", "f2"]})

        result = run_fetch_session(
            knowledge_analyzer=analyzer,
            input_dir=input_dir,
            registry_path=tmp_path / "reg.jsonl",
        )

        # EXPAND tried wiki, got nothing — but unsuccessful_hints stays 0
        # because expand isn't tracked by the hint lifecycle.
        assert result["articles_fetched"] == 0
        assert result["unsuccessful_hints"] == 0


class TestRSSRelevanceFilter:
    """Tests for RSS topic-based filtering."""

    def test_build_keywords_from_suggestions(self):
        suggestions = [
            {"topic": "fizyka kwantowa", "strategy": "expand"},
            {"topic": "biologia", "strategy": "explore"},
        ]
        kw = _build_topic_keywords(suggestions)
        # Stems: fizyka->fizy, kwantowa->kwanto, biologia->biolog
        assert any(k.startswith("fizy") for k in kw)
        assert any(k.startswith("kwant") for k in kw)
        assert any(k.startswith("biolog") for k in kw)

    def test_build_keywords_skips_short_words(self):
        suggestions = [{"topic": "AI w IT", "strategy": "expand"}]
        kw = _build_topic_keywords(suggestions)
        assert "ai" not in kw
        assert "it" not in kw

    def test_build_keywords_empty(self):
        assert _build_topic_keywords([]) == set()

    def test_relevant_title_match(self):
        # "fizy" stem matches "fizyce" (Polish locative)
        assert _is_rss_relevant(
            "Nowe odkrycie w fizyce jadrowej",
            "krotki opis",
            {"fizy", "kwanto"},
        ) is True

    def test_relevant_summary_match(self):
        # "biolog" stem matches "biologii" (Polish genitive)
        assert _is_rss_relevant(
            "Tytul ogolny",
            "Badania dotycza biologii morskiej",
            {"biolog"},
        ) is True

    def test_irrelevant_entry_filtered(self):
        assert _is_rss_relevant(
            "Beauty trendy 2026",
            "Kosmetyczny swiat ewoluuje",
            {"fizy", "biolog", "nauka"},
        ) is False

    def test_empty_keywords_passes_all(self):
        """Backward compatibility: no keywords = no filtering."""
        assert _is_rss_relevant(
            "Beauty trendy",
            "Cokolwiek",
            set(),
        ) is True

    def test_case_insensitive(self):
        assert _is_rss_relevant(
            "FIZYKA Jadrowa",
            "",
            {"fizyk"},
        ) is True

    def test_single_hit_from_rich_set_passes(self):
        # 2026-07-16 (RSS martwy): keywords are a FLAT UNION of stems from
        # UNRELATED topics, so the old "≥2 hits when ≥3 keywords" rule required
        # an article to be about two unrelated things at once -- unsatisfiable
        # (live probe: 1/50 passed, 0 saved/session). ONE topic hit is enough.
        # Teeth: revert required->2 and this asserts False.
        assert _is_rss_relevant(
            "Fizyka jadrowa: przelomowe odkrycie",
            "Opis bez zadnych innych slow kluczowych",
            {"fizyk", "biolog", "kwant", "astrono", "plann"},
        ) is True
        # Zero hits still fails -- off-topic noise is rejected.
        assert _is_rss_relevant(
            "Sondaz poparcia dla partii",
            "Politycy komentuja wyniki",
            {"fizyk", "biolog", "kwant", "astrono", "plann"},
        ) is False

    def test_word_prefix_not_substring(self):
        # 2026-07-16: matching was substring (`kw in text`), so a stem matched
        # mid-word -- "wiedz" hit "odwiedza", "astro" hit "katastrofa". Now the
        # stem must begin a WORD token. Teeth: revert to substring and the two
        # `is False` asserts flip to True.
        assert _is_rss_relevant("Prezydent odwiedza szpital", "", {"wiedz"}) is False
        assert _is_rss_relevant("Nowa wiedza o mozgu", "", {"wiedz"}) is True
        assert _is_rss_relevant("Katastrofa kolejowa pod miastem", "", {"astro"}) is False
        assert _is_rss_relevant("Astronomia obserwacyjna", "", {"astro"}) is True

    def test_generic_learning_words_are_stopped(self):
        # "nauka"/"nauki"/"wiedz*" match essentially every general-science entry,
        # so as topic stems they carry no signal -> dropped. One topic word per
        # added stop-entry so dropping ANY ONE flips an assert (real teeth):
        #   "nauka" (word), "nauki" (word), "wiedz" (stem -> wiedza/wiedzy/...).
        kw = _build_topic_keywords([
            {"topic": "nauka"},          # pins stop-word "nauka"
            {"topic": "nauki fizyczne"}, # pins stop-word "nauki" (keeps "fizycz")
            {"topic": "wiedza"},         # pins stem "wiedz"
            {"topic": "wiedzy"},         # pins stem "wiedz"
            {"topic": "astronomia"},     # specific -> kept
        ])
        assert not any(k.startswith("nauk") for k in kw)    # nauka + nauki dropped
        assert not any(k.startswith("wiedz") for k in kw)   # wiedza + wiedzy dropped
        assert any(k.startswith("astrono") for k in kw)     # specific -> kept
        assert any(k.startswith("fizy") for k in kw)        # non-generic survives

    def test_nfd_diacritics_still_match(self):
        # 2026-07-16 hardening (review finding): a feed may emit NFD-decomposed
        # text ("jądrowa" = j,a,U+0328,d,r,o,w,a). The combining ogonek is not a
        # \\w char, so without NFC normalization the word splits mid-stem and the
        # (NFC) keyword never prefix-matches. Teeth: drop the unicodedata.normalize
        # calls in _is_rss_relevant/_build_topic_keywords and the NFD case is False.
        import unicodedata
        kw = _build_topic_keywords([{"topic": unicodedata.normalize("NFD", "jądrowa")}])
        assert any(k.startswith("jądro") for k in kw)  # stem stored NFC
        nfd_entry = unicodedata.normalize("NFD", "Fizyka jądrowa")
        nfc_entry = unicodedata.normalize("NFC", "Fizyka jądrowa")
        assert _is_rss_relevant(nfd_entry, "", kw) is True
        assert _is_rss_relevant(nfc_entry, "", kw) is True  # both forms agree

    def test_stop_words_dropped(self):
        from agent_core.web_source import _STOP_WORDS
        suggestions = [
            {"topic": "system poznawczy"},
            {"topic": "model jezykowy"},
        ]
        kw = _build_topic_keywords(suggestions)
        # "system" and "model" should not survive — they were tripping
        # the filter on unrelated news (R1.1 audit).
        assert all(stem not in _STOP_WORDS for stem in kw)
        # The non-stop counterparts do survive
        assert any(k.startswith("pozna") for k in kw)
        assert any(k.startswith("jezyk") for k in kw)

    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_session_filters_irrelevant_rss(self, mock_wiki_cls, mock_rss_cls, tmp_path):
        """Full session: irrelevant RSS entries get filtered out."""
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = []

        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        mock_rss.fetch_all.return_value = [
            {"title": "Fizyka jadrowa nowe odkrycie", "link": "http://a.pl/1", "summary": "N" * 300},
            {"title": "Beauty trendy 2026", "link": "http://a.pl/2", "summary": "K" * 300},
            {"title": "Test hulajnogi elektrycznej", "link": "http://a.pl/3", "summary": "R" * 300},
        ]

        analyzer = _make_mock_analyzer(
            topic_map={"fizyka": ["f1", "f2"]},
        )

        result = run_fetch_session(
            knowledge_analyzer=analyzer,
            input_dir=tmp_path,
            registry_path=tmp_path / "reg.jsonl",
            max_articles=5,
        )

        # Only physics article should pass filter (stem "fizy" matches "Fizyka")
        assert result["rss_fetched"] == 1
        assert result["rss_filtered"] == 2

        files = list(tmp_path.glob("web_rss_*.txt"))
        assert len(files) == 1


class TestSkippedCountersSplit:
    """BUG 3 (2026-07-16): stats['skipped'] conflated 'already in the fetch
    registry' with 'the write was rejected'. The report lied that RSS tried to
    fetch something new. The two reasons are now counted separately, and their
    sum still equals the grand total."""

    @patch("agent_core.web_source.WikiClient")
    def test_registry_skip_counts_in_registry(self, mock_wiki_cls, tmp_path):
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = ["Logika"]
        mock_wiki.fetch_article.return_value = {
            "title": "Logika", "content": "X" * 500,
            "url": "https://pl.wikipedia.org/wiki/Logika",
        }
        reg_path = tmp_path / "reg.jsonl"
        # URL already fetched -> is_fetched True -> IN-REGISTRY skip (not a write skip).
        FetchRegistry(registry_path=reg_path).register(
            url="https://pl.wikipedia.org/wiki/Logika", title="Logika",
            source_type="wikipedia", output_file="web_wiki_logika.txt",
            char_count=500, topic="logika",
        )
        result = run_fetch_session(
            knowledge_analyzer=_make_mock_analyzer(), input_dir=tmp_path,
            registry_path=reg_path, enable_rss=False, override_topics=["logika"],
        )
        assert result["skipped_in_registry"] >= 1
        assert result["skipped_write_none"] == 0
        assert result["skipped"] == (
            result["skipped_in_registry"] + result["skipped_write_none"]
        )

    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_write_none_counts_as_write_skip(self, mock_wiki_cls, mock_rss_cls, tmp_path):
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = []  # isolate the RSS write-none path
        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        mock_rss.fetch_all.return_value = [
            {"title": "Fizyka jadrowa nowe odkrycie", "link": "http://a.pl/1",
             "summary": "N" * 300},
        ]
        # Pre-create the exact target file so write_article returns None (file on
        # disk) AFTER the entry passes the matcher -> a WRITE skip, not registry.
        slug = ContentWriter._slugify("Fizyka jadrowa nowe odkrycie")
        (tmp_path / f"web_rss_{slug}.txt").write_text("existing", encoding="utf-8")
        result = run_fetch_session(
            knowledge_analyzer=_make_mock_analyzer(topic_map={"fizyka": ["f1", "f2"]}),
            input_dir=tmp_path, registry_path=tmp_path / "reg.jsonl", max_articles=5,
        )
        assert result["rss_fetched"] == 0
        assert result["skipped_write_none"] >= 1
        assert result["skipped_in_registry"] == 0

    # The two off-diagonal sites (a bucket-swap would otherwise pass green):

    @patch("agent_core.web_source.WikiClient")
    def test_wiki_write_none_counts_as_write_skip(self, mock_wiki_cls, tmp_path):
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = ["Logika"]
        mock_wiki.fetch_article.return_value = {
            "title": "Logika", "content": "X" * 500,
            "url": "https://pl.wikipedia.org/wiki/Logika",
        }
        # Pre-create the wiki target file: URL is NOT in the registry, so the
        # fetch happens and write_article returns None -> a WIKI write skip.
        (tmp_path / "web_wiki_logika.txt").write_text("existing", encoding="utf-8")
        result = run_fetch_session(
            knowledge_analyzer=_make_mock_analyzer(), input_dir=tmp_path,
            registry_path=tmp_path / "reg.jsonl", enable_rss=False,
            override_topics=["logika"],
        )
        assert result["articles_fetched"] == 0
        assert result["skipped_write_none"] >= 1
        assert result["skipped_in_registry"] == 0

    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_rss_registry_skip_counts_in_registry(self, mock_wiki_cls, mock_rss_cls, tmp_path):
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = []  # isolate the RSS registry path
        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        mock_rss.fetch_all.return_value = [
            {"title": "Fizyka jadrowa", "link": "http://a.pl/1", "summary": "N" * 300},
        ]
        reg_path = tmp_path / "reg.jsonl"
        # Pre-register the RSS link -> is_fetched True -> RSS IN-REGISTRY skip
        # (fires before the matcher, so it is never a write skip).
        FetchRegistry(registry_path=reg_path).register(
            url="http://a.pl/1", title="Fizyka jadrowa", source_type="rss",
            output_file="web_rss_fizyka_jadrowa.txt", char_count=300, topic="fizyka",
        )
        result = run_fetch_session(
            knowledge_analyzer=_make_mock_analyzer(topic_map={"fizyka": ["f1", "f2"]}),
            input_dir=tmp_path, registry_path=reg_path, max_articles=5,
        )
        assert result["rss_fetched"] == 0
        assert result["skipped_in_registry"] >= 1
        assert result["skipped_write_none"] == 0


# ══════════════════════════════════════════════════════
# Kronika: market feed profile (BTC / gold / silver)
# ══════════════════════════════════════════════════════


class TestMarketMatcher:
    """Unit tests for _is_market_relevant (Kronika B4)."""

    def test_gold_pl_headline_passes(self):
        # The real Polish headline the default filter dropped (no transliteration).
        assert _is_market_relevant("Cena zlota bije rekordy", "Rynek surowcow rosnie")
        # With actual diacritics (transliterated internally).
        assert _is_market_relevant("Cena złota bije rekordy", "")

    def test_pln_currency_excluded(self):
        # "zlotego"/"zlotych" (PLN currency) must NOT match a gold kronika.
        assert not _is_market_relevant("Kurs złotego słabnie wobec euro", "")
        assert not _is_market_relevant("Notowania złotych obligacji", "")

    def test_crypto_english_passes(self):
        assert _is_market_relevant("Bitcoin surges past resistance", "")
        assert _is_market_relevant("Ethereum ETF approved by regulator", "")

    def test_silver_passes(self):
        assert _is_market_relevant("Notowania srebra w gore", "")

    def test_ticker_word_boundary(self):
        assert _is_market_relevant("BTC/USD analiza techniczna", "")
        # Substring-only match must not trigger (no bare ticker token).
        assert not _is_market_relevant("Firma XAGO otwiera biuro", "")

    def test_generic_leak_rejected(self):
        # "kurs"/"rynek" are deliberately NOT keywords (leak into konkurs etc.).
        assert not _is_market_relevant("Konkurs na rynku pracy w Warszawie", "")
        assert not _is_market_relevant("Rynek nieruchomosci rosnie", "")


class TestMarketProfile:
    """Integration: run_fetch_session(feed_profile='market')."""

    @patch("agent_core.web_source.ArticleFetcher")
    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_market_session_fetches_and_filters(self, mock_wiki_cls, mock_rss_cls, mock_fetcher_cls, tmp_path):
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki

        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        mock_rss.fetch_all.return_value = [
            {"title": "Cena złota bije rekordy", "link": "http://m/1", "summary": "Z" * 300},
            {"title": "Bitcoin surges past resistance", "link": "http://m/2", "summary": "B" * 300},
            {"title": "Srebro drożeje na rynkach", "link": "http://m/3", "summary": "S" * 300},
            {"title": "Konkurs na rynku pracy", "link": "http://m/4", "summary": "K" * 300},
            {"title": "Kurs złotego słabnie", "link": "http://m/5", "summary": "E" * 300},
        ]

        # Body-fetch returns full article text (avoids network in the test).
        mock_fetcher = specced(ArticleFetcher)
        mock_fetcher_cls.return_value = mock_fetcher
        mock_fetcher.fetch_body.return_value = "Tresc artykulu " * 30

        analyzer = _make_mock_analyzer()  # market bypasses the suggester

        result = run_fetch_session(
            knowledge_analyzer=analyzer,
            input_dir=tmp_path,
            registry_path=tmp_path / "reg.jsonl",
            max_articles=3,
            feed_profile="market",
        )

        # feed_profile echoed for observability (B1 PASS grep)
        assert result["feed_profile"] == "market"
        # 3 assets pass, 2 noise entries filtered
        assert result["rss_fetched"] == 3
        assert result["rss_filtered"] == 2
        # Wikipedia is skipped entirely for the market profile
        mock_wiki.search.assert_not_called()
        # RSSClient built from the market feed list, not the default science feeds
        mock_rss_cls.assert_called_once_with(feed_urls=MARKET_FEEDS)
        # Files are date-stamped (web_rss_YYYYMMDD_slug.txt) so repeatable titles
        # across the 14-day kronika do not collide.
        files = sorted(p.name for p in tmp_path.glob("web_rss_*.txt"))
        assert len(files) == 3
        # web_rss_YYYYMMDD_slug.txt -> chars 8:16 are the 8-digit date
        assert all(name.startswith("web_rss_") and name[8:16].isdigit() for name in files)

    @patch("agent_core.web_source.ArticleFetcher")
    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_market_session_survives_empty_suggester(self, mock_wiki_cls, mock_rss_cls, mock_fetcher_cls, tmp_path):
        # Regression: the "if not suggestions: return stats" gate must NOT
        # short-circuit the market profile before RSS runs.
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        mock_rss.fetch_all.return_value = [
            {"title": "Bitcoin rally continues", "link": "http://m/1", "summary": "B" * 300},
        ]
        # Body-fetch fails -> falls back to the RSS summary.
        mock_fetcher = specced(ArticleFetcher)
        mock_fetcher_cls.return_value = mock_fetcher
        mock_fetcher.fetch_body.return_value = None
        analyzer = _make_mock_analyzer()  # empty topic map -> no suggestions

        result = run_fetch_session(
            knowledge_analyzer=analyzer,
            input_dir=tmp_path,
            registry_path=tmp_path / "reg.jsonl",
            feed_profile="market",
        )
        assert result["rss_fetched"] == 1


class TestResolveFeedProfile:
    """Unit tests for resolve_feed_profile (B1 choke-point, None-safe)."""

    def _goal(self, metadata):
        return specced(Goal, metadata=metadata)

    def test_none_store_returns_none(self):
        assert resolve_feed_profile(None, "goal-1") is None

    def test_none_goal_id_returns_none(self):
        store = specced(GoalStore)
        assert resolve_feed_profile(store, None) is None
        store.get.assert_not_called()

    def test_market_goal_resolves_market(self):
        store = specced(GoalStore)
        store.get.return_value = self._goal({"source_kind": "market"})
        assert resolve_feed_profile(store, "goal-1") == "market"

    def test_non_market_goal_resolves_none(self):
        store = specced(GoalStore)
        store.get.return_value = self._goal({"project_parent": "p1"})
        assert resolve_feed_profile(store, "goal-1") is None

    def test_missing_goal_resolves_none(self):
        store = specced(GoalStore)
        store.get.return_value = None
        assert resolve_feed_profile(store, "goal-1") is None

    def test_store_raises_is_swallowed(self):
        store = specced(GoalStore)
        store.get.side_effect = RuntimeError("boom")
        assert resolve_feed_profile(store, "goal-1") is None


class TestExhaustedMarkedInSession:
    """End-to-end: a topic whose every Wikipedia title is already on disk gets
    marked exhausted by run_fetch_session -- the fix for the deterministic
    0-fetched loop (same 5 topics re-proposed every ~60s, 2456 fresh ones stuck
    behind them)."""

    @patch("agent_core.web_source.WikiClient")
    def test_topic_with_all_titles_fetched_is_marked_exhausted(self, mock_wiki_cls, tmp_path):
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = ["Fotosynteza"]
        mock_wiki.fetch_article.return_value = {
            "title": "Fotosynteza", "content": "X" * 500,
            "url": "https://pl.wikipedia.org/wiki/Fotosynteza",
        }

        reg_path = tmp_path / "reg.jsonl"
        # Pre-register the URL so is_fetched()=True -> the title is skipped ->
        # the topic produces 0 new articles despite having a Wikipedia result.
        FetchRegistry(registry_path=reg_path).register(
            url="https://pl.wikipedia.org/wiki/Fotosynteza", title="Fotosynteza",
            source_type="wikipedia", output_file="web_wiki_fotosynteza.txt",
            char_count=500, topic="fotosynteza",
        )

        result = run_fetch_session(
            knowledge_analyzer=_make_mock_analyzer(), input_dir=tmp_path,
            registry_path=reg_path, enable_rss=False,
            override_topics=["fotosynteza"],
        )

        assert result["articles_fetched"] == 0
        assert FetchRegistry(registry_path=reg_path).is_topic_exhausted("fotosynteza") is True
        # ...and NOT marked dead: Wikipedia did have an article for it.
        assert FetchRegistry(registry_path=reg_path).is_topic_dead("fotosynteza") is False

    @patch("agent_core.web_source.WikiClient")
    def test_fresh_fetch_is_not_marked_exhausted(self, mock_wiki_cls, tmp_path):
        """A topic that DID produce a new article must not be marked exhausted."""
        mock_wiki = specced(WikiClient)
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = ["Fotosynteza"]
        mock_wiki.fetch_article.return_value = {
            "title": "Fotosynteza", "content": "X" * 500,
            "url": "https://pl.wikipedia.org/wiki/Fotosynteza",
        }

        reg_path = tmp_path / "reg.jsonl"
        result = run_fetch_session(
            knowledge_analyzer=_make_mock_analyzer(), input_dir=tmp_path,
            registry_path=reg_path, enable_rss=False,
            override_topics=["fotosynteza"],
        )

        assert result["articles_fetched"] == 1
        assert FetchRegistry(registry_path=reg_path).is_topic_exhausted("fotosynteza") is False


class TestMarketBodyFetch:
    """Market profile fetches the article body (feeds carry thin summaries)."""

    @patch("agent_core.web_source.ArticleFetcher")
    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_title_only_entry_uses_fetched_body(self, mock_wiki_cls, mock_rss_cls, mock_fetcher_cls, tmp_path):
        mock_wiki_cls.return_value = specced(WikiClient)
        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        # A metals headline with NO summary (title-only feed) still gets in via
        # the article body -- the relaxed summary gate + body fetch.
        mock_rss.fetch_all.return_value = [
            {"title": "Cena złota bije rekordy", "link": "http://m/gold", "summary": ""},
        ]
        mock_fetcher = specced(ArticleFetcher)
        mock_fetcher_cls.return_value = mock_fetcher
        mock_fetcher.fetch_body.return_value = (
            "Zloto zdrozalo dzis o dwa procent na fali popytu inwestycyjnego. " * 6
        )

        result = run_fetch_session(
            knowledge_analyzer=_make_mock_analyzer(),
            input_dir=tmp_path,
            registry_path=tmp_path / "reg.jsonl",
            feed_profile="market",
        )
        assert result["rss_fetched"] == 1
        # The stored file holds the fetched body, not the (empty) summary.
        files = list(tmp_path.glob("web_rss_*.txt"))
        assert len(files) == 1
        assert "Zloto zdrozalo" in files[0].read_text(encoding="utf-8")

    @patch("agent_core.web_source.ArticleFetcher")
    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_body_fetch_failure_falls_back_to_summary(self, mock_wiki_cls, mock_rss_cls, mock_fetcher_cls, tmp_path):
        mock_wiki_cls.return_value = specced(WikiClient)
        mock_rss = specced(RSSClient)
        mock_rss_cls.return_value = mock_rss
        mock_rss.fetch_all.return_value = [
            {"title": "Bitcoin news", "link": "http://m/btc", "summary": "Bitcoin " * 40},
        ]
        mock_fetcher = specced(ArticleFetcher)
        mock_fetcher_cls.return_value = mock_fetcher
        mock_fetcher.fetch_body.return_value = None  # extract failed

        result = run_fetch_session(
            knowledge_analyzer=_make_mock_analyzer(),
            input_dir=tmp_path,
            registry_path=tmp_path / "reg.jsonl",
            feed_profile="market",
        )
        assert result["rss_fetched"] == 1  # summary fallback still wrote the file


class TestArticleExtractor:
    """Unit tests for extract_main_text (dependency-light body extraction)."""

    def test_extracts_densest_paragraph_block(self):
        html = """
        <html><body>
          <nav><p>Menu Home About Contact Login Register Subscribe now</p></nav>
          <div class="sidebar"><p>Short teaser</p></div>
          <article>
            <p>To jest pierwszy akapit artykulu o cenach zlota na rynku swiatowym.</p>
            <p>Drugi akapit rozwija watek podazy i popytu na kruszec w tym tygodniu.</p>
          </article>
          <footer><p>Copyright 2026 all rights reserved terms privacy policy</p></footer>
        </body></html>
        """
        out = extract_main_text(html)
        assert "pierwszy akapit artykulu o cenach zlota" in out
        assert "Drugi akapit" in out
        # boilerplate dropped
        assert "Copyright" not in out
        assert "Menu Home" not in out

    def test_drops_script_and_style(self):
        html = (
            "<html><body><article>"
            "<script>var x = 'ignore this long javascript blob of text here';</script>"
            "<p>Prawdziwa tresc artykulu ktora ma wystarczajaca dlugosc do przejscia.</p>"
            "</article></body></html>"
        )
        out = extract_main_text(html)
        assert "Prawdziwa tresc" in out
        assert "javascript" not in out

    def test_empty_or_garbage_returns_none(self):
        assert extract_main_text("") is None
        assert extract_main_text("   ") is None
        assert extract_main_text("<html><body><p>hi</p></body></html>") is None  # too short

    @patch("agent_core.web_source.article_fetcher.requests.Session")
    def test_fetch_body_success(self, mock_session_cls):
        resp = MagicMock()
        resp.text = (
            "<html><body><article><p>"
            + "Pelna tresc artykulu rynkowego o zlocie i srebrze dzisiaj. " * 3
            + "</p></article></body></html>"
        )
        resp.raise_for_status.return_value = None
        mock_session = MagicMock()
        mock_session.get.return_value = resp
        mock_session_cls.return_value = mock_session

        body = ArticleFetcher().fetch_body("http://x/article")
        assert body is not None
        assert "Pelna tresc artykulu" in body

    @patch("agent_core.web_source.article_fetcher.requests.Session")
    def test_fetch_body_network_error_returns_none(self, mock_session_cls):
        import requests as _req
        mock_session = MagicMock()
        mock_session.get.side_effect = _req.RequestException("boom")
        mock_session_cls.return_value = mock_session
        assert ArticleFetcher().fetch_body("http://x/article") is None

    def test_fetch_body_empty_url_returns_none(self):
        assert ArticleFetcher().fetch_body("") is None
