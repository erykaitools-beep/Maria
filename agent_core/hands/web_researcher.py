"""
WebResearcher - Search and summarize information from the web.

First "digital hand" - Maria can look things up autonomously.
Uses existing WikiClient + RSSClient, wrapped with TaskExecutor tracking.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_INPUT_DIR = Path("input")


class WebResearcher:
    """Search the web and produce structured results."""

    def __init__(self):
        self._wiki_client = None
        self._rss_client = None
        self._content_writer = None
        self._fetch_registry = None

    # -- DI setters --

    def set_wiki_client(self, client) -> None:
        self._wiki_client = client

    def set_rss_client(self, client) -> None:
        self._rss_client = client

    def set_content_writer(self, writer) -> None:
        self._content_writer = writer

    def set_fetch_registry(self, registry) -> None:
        self._fetch_registry = registry

    # -- Core API (these are tool handlers for TaskExecutor) --

    def search_wikipedia(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search Polish Wikipedia for a topic.

        Args: {"query": str, "max_results": int (default 3), "save": bool (default True)}
        Returns: {"success": bool, "results": list, "saved_files": list}
        """
        query = args.get("query", "")
        max_results = args.get("max_results", 3)
        save = args.get("save", True)

        if not query:
            return {"success": False, "error": "brak zapytania (query)"}
        if not self._wiki_client:
            return {"success": False, "error": "WikiClient niedostepny"}

        try:
            # Search
            search_results = self._wiki_client.search(query, limit=max_results)
            if not search_results:
                return {"success": True, "results": [], "saved_files": [], "ok": True}

            results = []
            saved = []
            for title in search_results:
                article = self._wiki_client.fetch(title)
                if article:
                    results.append({
                        "title": article.get("title", title),
                        "extract": article.get("extract", "")[:500],
                        "url": article.get("url", ""),
                    })

                    # Save to input/ if requested
                    if save and self._content_writer:
                        path = self._content_writer.write(
                            content=article.get("extract", ""),
                            title=article.get("title", title),
                            source="wikipedia",
                            url=article.get("url", ""),
                        )
                        if path:
                            saved.append(str(path))

            return {
                "success": True,
                "ok": True,
                "results": results,
                "saved_files": saved,
                "count": len(results),
            }

        except Exception as e:
            logger.warning("WebResearcher.search_wikipedia failed: %s", e)
            return {"success": False, "error": str(e)}

    def fetch_url(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch content from a URL (via OpenClaw web_fetch if available).

        Args: {"url": str}
        Returns: {"success": bool, "content": str, "length": int}
        """
        url = args.get("url", "")
        if not url:
            return {"success": False, "error": "brak URL"}

        try:
            import requests
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "MARIA/1.0 (personal digital human)"
            })
            resp.raise_for_status()
            content = resp.text[:10000]  # limit to 10k chars
            return {
                "success": True,
                "ok": True,
                "content": content,
                "length": len(content),
                "url": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_and_save(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Convenience: search Wikipedia and save results to input/.

        Args: {"topic": str, "max_articles": int}
        """
        topic = args.get("topic", "")
        max_articles = args.get("max_articles", 3)
        return self.search_wikipedia({
            "query": topic,
            "max_results": max_articles,
            "save": True,
        })
