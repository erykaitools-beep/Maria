"""
Tests for Web Content Fetcher (agent_core/web_source/).

All HTTP calls are mocked. No real network access.
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, Mock

import pytest

from agent_core.web_source.fetch_registry import FetchRegistry, MAX_ENTRIES
from agent_core.web_source.wiki_client import WikiClient
from agent_core.web_source.rss_client import RSSClient
from agent_core.web_source.content_writer import ContentWriter
from agent_core.web_source.topic_suggester import TopicSuggester
from agent_core.web_source import run_fetch_session, _build_topic_keywords, _is_rss_relevant


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

    def test_prunes_registry_to_max_entries(self, tmp_path):
        path = tmp_path / "reg.jsonl"
        reg = FetchRegistry(registry_path=path)

        for i in range(MAX_ENTRIES + 10):
            reg.register(
                url=f"https://example.com/{i}",
                title=f"Title {i}",
                source_type="wikipedia",
                output_file=f"{i}.txt",
                char_count=100 + i,
                topic=f"topic-{i}",
            )

        all_records = reg.get_all()
        assert len(all_records) == MAX_ENTRIES
        assert "https://example.com/0" not in all_records
        assert f"https://example.com/{MAX_ENTRIES + 9}" in all_records


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
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        import requests as req
        mock_session.get.side_effect = req.RequestException("timeout")

        client = WikiClient()
        client._last_request_ts = time.time()
        assert client.search("test") == []

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
    analyzer = MagicMock()
    analyzer.get_topic_file_map.return_value = topic_map or {}
    analyzer.get_tag_frequency_map.return_value = tag_freq or {}
    return analyzer


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

    def test_suggest_filters_already_fetched(self, tmp_path):
        analyzer = _make_mock_analyzer(
            topic_map={"logika": ["f1", "f2"], "fizyka": ["f3"]},
        )
        reg = FetchRegistry(registry_path=tmp_path / "reg.jsonl")
        reg.register("https://x.com", "X", "wiki", "x.txt", 100, topic="logika")

        suggester = TopicSuggester(analyzer, project_root=str(tmp_path))
        suggestions = suggester.suggest_topics(fetch_registry=reg)

        topics = [s["topic"] for s in suggestions]
        assert "logika" not in topics
        assert "fizyka" in topics

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
        mock_registry = MagicMock()
        mock_registry.is_topic_fetched = MagicMock(return_value=True)

        suggestions = suggester.suggest_topics(fetch_registry=mock_registry)
        hint_suggestions = [s for s in suggestions if s["strategy"] == "hint"]
        assert len(hint_suggestions) == 0  # skipped because already fetched

        # Verify hint was marked consumed in file
        with open(hints_path) as f:
            h = json.loads(f.readline())
        assert h["consumed"] is True


# ══════════════════════════════════════════════════════
# Integration: run_fetch_session
# ══════════════════════════════════════════════════════


class TestRunFetchSession:
    """Integration tests for run_fetch_session with all mocks."""

    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_full_session(self, mock_wiki_cls, mock_rss_cls, tmp_path):
        # Setup mock WikiClient
        mock_wiki = MagicMock()
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = ["Logika"]
        mock_wiki.fetch_article.return_value = {
            "title": "Logika",
            "content": "X" * 500,
            "url": "https://pl.wikipedia.org/wiki/Logika",
        }

        # Setup mock RSSClient
        mock_rss = MagicMock()
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
        mock_wiki = MagicMock()
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
        mock_wiki = MagicMock()
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

        mock_rss = MagicMock()
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
        mock_wiki = MagicMock()
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
        mock_wiki = MagicMock()
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = []

        mock_rss = MagicMock()
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
            {"fizy"},
        ) is True

    @patch("agent_core.web_source.RSSClient")
    @patch("agent_core.web_source.WikiClient")
    def test_session_filters_irrelevant_rss(self, mock_wiki_cls, mock_rss_cls, tmp_path):
        """Full session: irrelevant RSS entries get filtered out."""
        mock_wiki = MagicMock()
        mock_wiki_cls.return_value = mock_wiki
        mock_wiki.search.return_value = []

        mock_rss = MagicMock()
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
