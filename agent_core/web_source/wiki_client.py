"""
WikiClient - fetches articles from Polish Wikipedia API.

No state. Pure HTTP client. Fail-fast, no retries.
"""

import logging
import time
import requests
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://pl.wikipedia.org/w/api.php"
USER_AGENT = "MARIA-Bot/1.0 (educational AI agent; local use only)"
DEFAULT_TIMEOUT = 30  # seconds
MAX_ARTICLE_CHARS = 15000
MIN_ARTICLE_CHARS = 200
RATE_LIMIT_SEC = 2.0  # polite crawling

# 429 backoff. The fixed 2s spacing above is "polite" only while Wikipedia is
# happy; once it answers 429 the same 2s cadence is what KEEPS us throttled.
# Measured 2026-07-26: 21 x 429 in one afternoon, in bursts of 2-3 exactly 2s
# apart -- the client asked for three candidate titles of one topic, got refused
# three times, then moved to the next topic and did it again. Three weeks before
# that: zero errors, so this path had never been exercised under refusal.
BACKOFF_BASE_SEC = 5.0
BACKOFF_MAX_SEC = 60.0
MAX_CONSECUTIVE_429 = 3


class WikiTransientError(RuntimeError):
    """Wikipedia could not be asked (network error, 429, 5xx, malformed JSON).

    Carries no information about whether an article exists. Kept distinct from
    an empty search result because callers treat "no results" as a permanent
    verdict on the topic; conflating the two lets a rate-limit erase a live
    topic forever.
    """


class WikiRateLimited(WikiTransientError):
    """Wikipedia is refusing us and asking again will not help this session.

    Raised after MAX_CONSECUTIVE_429 refusals in a row. A caller looping over
    topics must stop asking Wikipedia entirely rather than spend the rest of the
    session collecting one 429 per topic -- still a WikiTransientError, so any
    caller that does not know about it keeps the safe old behaviour (never
    mistaken for "no such article").
    """


class WikiClient:
    """
    Fetches article content from Polish Wikipedia API.

    Uses two endpoints:
    - opensearch: search for article titles
    - query+extracts: fetch plain text of an article
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self._base_url = base_url
        self._timeout = timeout
        self._last_request_ts = 0.0
        # 429 state. The class docstring says "no state"; that was already only
        # aspirational (_last_request_ts), and honouring a refusal is not
        # possible without remembering it.
        self._consecutive_429 = 0
        self._cooldown_until = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def search(self, query: str, limit: int = 5) -> List[str]:
        """
        Search Wikipedia for article titles matching query.

        Args:
            query: Search string (e.g. "logika")
            limit: Max results (1-10)

        Returns:
            List of article titles. EMPTY MEANS "Wikipedia has no such article"
            and nothing else -- callers act on that permanently (see
            FetchRegistry.mark_topic_dead), so a transient failure must never
            be flattened into it.

        Raises:
            WikiTransientError: the request failed or Wikipedia refused it
                (429/5xx/timeout/bad JSON). Says nothing about whether the
                article exists; retry later.
        """
        if not query or not query.strip():
            return []

        self._rate_limit()

        params = {
            "action": "opensearch",
            "search": query.strip(),
            "limit": min(limit, 10),
            "namespace": 0,
            "format": "json",
        }

        try:
            resp = self._session.get(
                self._base_url, params=params, timeout=self._timeout,
            )
            self._note_response(resp)
            resp.raise_for_status()
            data = resp.json()

            # opensearch returns: [query, [titles], [descriptions], [urls]]
            if isinstance(data, list) and len(data) >= 2:
                return list(data[1])
            return []

        except (requests.RequestException, ValueError) as e:
            # NIE zwracaj [] -- run_fetch_session czyta puste wyniki jako
            # "Wikipedia nie ma takiego hasla" i kasuje temat NA ZAWSZE
            # (mark_topic_dead, one-strike). Przy 429 od pl.wikipedia.org
            # (15x samego 2026-07-14) kasowalo to zywe tematy przez chwilowy
            # rate-limit. Wyjatek ląduje w `except Exception` sesji, ktory juz
            # ustawia had_error i pomija mark_topic_dead -- czyli robi to, co
            # jego komentarz obiecywal od poczatku.
            logger.warning(f"Wikipedia search failed for '{query}': {e}")
            raise WikiTransientError(f"Wikipedia search failed for '{query}': {e}") from e

    def fetch_article(self, title: str) -> Optional[Dict[str, Any]]:
        """
        Fetch plain text extract of a Wikipedia article.

        Args:
            title: Exact article title (e.g. "Logika")

        Returns:
            {"title": str, "content": str, "url": str} or None.
            None if article not found, too short, or error.
        """
        if not title or not title.strip():
            return None

        self._rate_limit()

        params = {
            "action": "query",
            "titles": title.strip(),
            "prop": "extracts|info",
            "explaintext": "true",
            "exsectionformat": "plain",
            "inprop": "url",
            "format": "json",
        }

        try:
            resp = self._session.get(
                self._base_url, params=params, timeout=self._timeout,
            )
            self._note_response(resp)
            resp.raise_for_status()
            data = resp.json()

            pages = data.get("query", {}).get("pages", {})
            if not pages:
                return None

            # Pages dict has dynamic page IDs as keys
            for page_id, page in pages.items():
                # -1 means not found
                if page_id == "-1" or "missing" in page:
                    logger.debug(f"Wikipedia article not found: '{title}'")
                    return None

                content = page.get("extract", "")
                if not content or len(content) < MIN_ARTICLE_CHARS:
                    logger.debug(
                        f"Wikipedia article too short: '{title}' "
                        f"({len(content)} chars)"
                    )
                    return None

                # Truncate if too long
                if len(content) > MAX_ARTICLE_CHARS:
                    # Cut at last paragraph break before limit
                    cut_pos = content.rfind("\n\n", 0, MAX_ARTICLE_CHARS)
                    if cut_pos > MIN_ARTICLE_CHARS:
                        content = content[:cut_pos]
                    else:
                        content = content[:MAX_ARTICLE_CHARS]

                url = page.get("fullurl", f"https://pl.wikipedia.org/wiki/{title}")

                return {
                    "title": page.get("title", title),
                    "content": content,
                    "url": url,
                }

            return None

        except (requests.RequestException, ValueError) as e:
            logger.warning(f"Wikipedia fetch failed for '{title}': {e}")
            return None

    def _rate_limit(self) -> None:
        """Enforce polite crawling rate limit, plus any 429 cooldown owed."""
        now = time.time()
        owed = self._cooldown_until - now
        if owed > 0:
            time.sleep(owed)
            now = time.time()
        elapsed = now - self._last_request_ts
        if elapsed < RATE_LIMIT_SEC:
            time.sleep(RATE_LIMIT_SEC - elapsed)
        self._last_request_ts = time.time()

    def _note_response(self, resp) -> None:
        """Record whether Wikipedia accepted or refused us, and arm the backoff.

        Called before raise_for_status() so a 429 is seen as a rate-limit rather
        than as one more anonymous HTTPError. Honours Retry-After when the server
        sends it; otherwise backs off exponentially from BACKOFF_BASE_SEC.

        Raises:
            WikiRateLimited: after MAX_CONSECUTIVE_429 refusals in a row.
        """
        if getattr(resp, "status_code", None) != 429:
            self._consecutive_429 = 0
            return

        self._consecutive_429 += 1
        retry_after = None
        try:
            raw = (getattr(resp, "headers", None) or {}).get("Retry-After")
            if raw is not None:
                retry_after = float(str(raw).strip())
        except (TypeError, ValueError):
            retry_after = None

        if retry_after is None or retry_after <= 0:
            retry_after = BACKOFF_BASE_SEC * (2 ** (self._consecutive_429 - 1))
        wait = min(retry_after, BACKOFF_MAX_SEC)
        self._cooldown_until = time.time() + wait
        logger.warning(
            "Wikipedia rate-limited (429 #%d), backing off %.0fs",
            self._consecutive_429, wait,
        )

        if self._consecutive_429 >= MAX_CONSECUTIVE_429:
            raise WikiRateLimited(
                "Wikipedia refused %d requests in a row; stopping for this session"
                % self._consecutive_429
            )
