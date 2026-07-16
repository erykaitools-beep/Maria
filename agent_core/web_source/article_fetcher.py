"""
ArticleFetcher -- fetches an article page and extracts its main text body.

Market RSS feeds (Kronika) carry thin or empty summaries, so the real
BTC / gold / silver content lives on the article page, not the feed. This
pulls the page and extracts the densest block of <p> text (readability-style),
using only requests + lxml (both already vendored -- no readability /
trafilatura / newspaper dependency, keeping web_source offline-first-friendly).

Best-effort by design: returns None on any network or parse failure so the
caller falls back to the RSS summary. Rate-limited (1 req/s) and size-capped.
"""

import logging
import time
from typing import Optional

import requests
from lxml import html as lxml_html

logger = logging.getLogger(__name__)

USER_AGENT = "MARIA-Bot/1.0 (educational AI agent; local use only)"
DEFAULT_TIMEOUT = 15  # seconds
RATE_LIMIT_SEC = 1.0
MAX_BODY_CHARS = 8000  # cap stored article body
_MIN_PARA_LEN = 40     # drop nav/menu/teaser <p> shorter than this

# Tags whose text is never article body.
_DROP_TAGS = (
    "script", "style", "nav", "header", "footer", "aside", "form",
    "figure", "figcaption", "noscript", "iframe", "button", "svg",
)
# Candidate content containers, scored by total <p> text length.
_CONTAINER_XPATH = "//article | //main | //div | //section | //body"


def extract_main_text(html_text: str) -> Optional[str]:
    """
    Extract the densest block of <p> text from an HTML page.

    Module-level (not a method) so it can be unit-tested on static HTML with
    no network round-trip. Strips boilerplate tags, then picks the container
    whose de-duplicated >=40-char paragraphs sum to the most text. Returns the
    cleaned text, or None if nothing substantial was found.
    """
    if not html_text or not html_text.strip():
        return None

    doc = lxml_html.fromstring(html_text)
    for el in doc.xpath("|".join(f"//{t}" for t in _DROP_TAGS)):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)

    best_text = ""
    for container in doc.xpath(_CONTAINER_XPATH):
        seen = set()
        paras = []
        for p in container.findall(".//p"):
            txt = " ".join(p.text_content().split())
            if len(txt) >= _MIN_PARA_LEN and txt not in seen:
                seen.add(txt)
                paras.append(txt)
        text = "\n\n".join(paras)
        if len(text) > len(best_text):
            best_text = text

    best_text = best_text.strip()
    if len(best_text) > MAX_BODY_CHARS:
        best_text = best_text[:MAX_BODY_CHARS].rsplit("\n", 1)[0].strip()
    return best_text or None


class ArticleFetcher:
    """Fetches and extracts the main text body of article pages (best-effort)."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self._timeout = timeout
        self._last_ts = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _rate_limit(self) -> None:
        dt = time.time() - self._last_ts
        if dt < RATE_LIMIT_SEC:
            time.sleep(RATE_LIMIT_SEC - dt)
        self._last_ts = time.time()

    def fetch_body(self, url: str) -> Optional[str]:
        """Return the cleaned main text of the article at url, or None."""
        if not url:
            return None
        self._rate_limit()
        try:
            resp = self._session.get(url, timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.debug("[ARTICLE] fetch failed %s: %s", url, e)
            return None
        try:
            # requests defaults to latin-1 when the Content-Type header omits
            # charset (RFC 2616 legacy), which mangles UTF-8 pages into
            # mojibake ("przełamał" -> "przeÅ‚amaÅ‚") -- the first 18 Kronika
            # pantry files shipped broken this way. Trust the body sniffer
            # (charset_normalizer via apparent_encoding) instead.
            ctype = resp.headers.get("content-type", "")
            if "charset" not in ctype.lower():
                resp.encoding = resp.apparent_encoding or "utf-8"
            return extract_main_text(resp.text)
        except Exception as e:  # lxml can raise on malformed markup
            logger.debug("[ARTICLE] extract failed %s: %s", url, e)
            return None
