"""
RSSClient - reads RSS/Atom feeds.

Uses xml.etree.ElementTree (stdlib) - zero external dependencies.
Handles both RSS 2.0 and Atom formats.
"""

import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20  # seconds
MAX_ENTRIES = 10  # per feed per fetch
RATE_LIMIT_SEC = 1.0  # per request
USER_AGENT = "MARIA-Bot/1.0 (educational AI agent; local use only)"

# Atom namespace
ATOM_NS = "{http://www.w3.org/2005/Atom}"

# Default Polish educational/science feeds
DEFAULT_FEEDS = [
    "https://naukawpolsce.pl/rss.xml",            # Nauka w Polsce (PAP) - nauka PL
    # polskieradio.pl/130/rss - 404 since 2026-03 (removed)
    # kopalniawiedzy.pl/rss/feed.xml - 404 since 2026-03 (removed)
]


class RSSClient:
    """
    Reads RSS/Atom feeds. Uses stdlib XML parser.

    Handles:
    - RSS 2.0: channel/item/title, link, description
    - Atom: feed/entry/title, link[@href], summary/content
    """

    def __init__(
        self,
        feed_urls: Optional[List[str]] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        """
        Args:
            feed_urls: List of RSS/Atom feed URLs.
                       Default: curated Polish educational feeds.
            timeout: HTTP request timeout in seconds.
        """
        self._feeds = feed_urls if feed_urls is not None else list(DEFAULT_FEEDS)
        self._timeout = timeout
        self._last_request_ts = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    @property
    def feeds(self) -> List[str]:
        """Current feed URL list."""
        return list(self._feeds)

    def fetch_entries(self, feed_url: str) -> List[Dict[str, Any]]:
        """
        Fetch entries from a single RSS/Atom feed.

        Args:
            feed_url: URL of the RSS/Atom feed.

        Returns:
            List of dicts: {title, link, summary, published}.
            Empty list on error.
        """
        self._rate_limit()

        try:
            resp = self._session.get(feed_url, timeout=self._timeout)
            resp.raise_for_status()
            xml_text = resp.text
        except requests.RequestException as e:
            logger.warning(f"RSS fetch failed for {feed_url}: {e}")
            return []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.warning(f"RSS parse failed for {feed_url}: {e}")
            return []

        # Detect format and parse
        if root.tag == "rss":
            return self._parse_rss20(root)
        elif root.tag == f"{ATOM_NS}feed" or root.tag == "feed":
            return self._parse_atom(root)
        else:
            # Try RSS 2.0 first (most common)
            entries = self._parse_rss20(root)
            if entries:
                return entries
            return self._parse_atom(root)

    def fetch_all(self) -> List[Dict[str, Any]]:
        """
        Fetch entries from all configured feeds.

        Returns combined entry list (deduplicated by link).
        """
        seen_links = set()
        all_entries = []

        for feed_url in self._feeds:
            entries = self.fetch_entries(feed_url)
            for entry in entries:
                link = entry.get("link", "")
                if link and link not in seen_links:
                    seen_links.add(link)
                    all_entries.append(entry)

        return all_entries

    def _parse_rss20(self, root: ET.Element) -> List[Dict[str, Any]]:
        """Parse RSS 2.0 format."""
        entries = []
        # RSS 2.0: rss/channel/item
        for item in root.iter("item"):
            if len(entries) >= MAX_ENTRIES:
                break
            entry = {
                "title": self._get_text(item, "title"),
                "link": self._get_text(item, "link"),
                "summary": self._get_text(item, "description"),
                "published": self._get_text(item, "pubDate"),
            }
            if entry["title"]:
                entries.append(entry)
        return entries

    def _parse_atom(self, root: ET.Element) -> List[Dict[str, Any]]:
        """Parse Atom format."""
        entries = []

        # Try with namespace first, then without
        for ns in [ATOM_NS, ""]:
            for elem in root.iter(f"{ns}entry"):
                if len(entries) >= MAX_ENTRIES:
                    break

                title = self._get_text(elem, f"{ns}title")

                # Atom link is an attribute: <link href="..." />
                link = ""
                link_elem = elem.find(f"{ns}link")
                if link_elem is not None:
                    link = link_elem.get("href", "")

                summary = (
                    self._get_text(elem, f"{ns}summary")
                    or self._get_text(elem, f"{ns}content")
                )

                published = (
                    self._get_text(elem, f"{ns}published")
                    or self._get_text(elem, f"{ns}updated")
                )

                if title:
                    entries.append({
                        "title": title,
                        "link": link,
                        "summary": summary,
                        "published": published,
                    })

            if entries:
                break  # Found entries with this namespace

        return entries

    @staticmethod
    def _get_text(parent: ET.Element, tag: str) -> str:
        """Safely get text content of a child element."""
        elem = parent.find(tag)
        if elem is not None and elem.text:
            return elem.text.strip()
        return ""

    def _rate_limit(self) -> None:
        """Enforce rate limit between requests."""
        now = time.time()
        elapsed = now - self._last_request_ts
        if elapsed < RATE_LIMIT_SEC:
            time.sleep(RATE_LIMIT_SEC - elapsed)
        self._last_request_ts = time.time()
