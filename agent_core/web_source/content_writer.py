"""
ContentWriter - saves fetched web content as .txt files in input/.

Handles naming (slugify), metadata headers, deduplication,
and content validation.
"""

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent_core.web_source.fetch_registry import FetchRegistry

logger = logging.getLogger(__name__)

# Import INPUT_DIR from config
try:
    from maria_core.sys.config import INPUT_DIR as _DEFAULT_INPUT_DIR
except ImportError:
    _DEFAULT_INPUT_DIR = Path(__file__).resolve().parents[2] / "input"

MIN_CONTENT_CHARS = 200
MAX_SLUG_LEN = 50
HEADER_SEPARATOR = "# ---\n\n"

# Polish character transliteration map
_PL_TRANS = str.maketrans({
    "a": "a", "c": "c", "e": "e", "l": "l",
    "n": "n", "o": "o", "s": "s", "z": "z", "z": "z",
    "A": "A", "C": "C", "E": "E", "L": "L",
    "N": "N", "O": "O", "S": "S", "Z": "Z", "Z": "Z",
    # Additional common chars
    "\u0105": "a", "\u0107": "c", "\u0119": "e", "\u0142": "l",
    "\u0144": "n", "\u00f3": "o", "\u015b": "s", "\u017a": "z",
    "\u017c": "z",
    "\u0104": "A", "\u0106": "C", "\u0118": "E", "\u0141": "L",
    "\u0143": "N", "\u00d3": "O", "\u015a": "S", "\u0179": "Z",
    "\u017b": "Z",
})


class ContentWriter:
    """
    Writes fetched web content to input/ as .txt files.

    Naming: web_{source}_{slug}.txt
    Adds metadata header for human inspection.
    """

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        fetch_registry: Optional[FetchRegistry] = None,
    ):
        self._input_dir = Path(input_dir or _DEFAULT_INPUT_DIR)
        self._registry = fetch_registry

    def write_article(
        self,
        title: str,
        content: str,
        url: str,
        source_type: str,
        topic: Optional[str] = None,
    ) -> Optional[str]:
        """
        Write content to input/ and register in FetchRegistry.

        Args:
            title: Article title
            content: Plain text content
            url: Source URL
            source_type: "wikipedia" or "rss"
            topic: Topic that led to this fetch (for registry)

        Returns:
            Filename (e.g. "web_wiki_logika.txt") or None if skipped.
        """
        # Validate content
        if not content or len(content.strip()) < MIN_CONTENT_CHARS:
            logger.debug(
                f"Content too short for '{title}': "
                f"{len(content.strip()) if content else 0} chars"
            )
            return None

        # Check registry dedup
        if self._registry and self._registry.is_fetched(url):
            logger.debug(f"Already fetched: {url}")
            return None

        # Generate filename. R1.3 added "codex" as a third writer source
        # for ChatGPT-authored educational articles; the "web_" prefix
        # remains for fetched web content (wiki/rss).
        slug = self._slugify(title)
        st = source_type.lower()
        if "codex" in st:
            filename = f"codex_{slug}.txt"
        elif "wiki" in st:
            filename = f"web_wiki_{slug}.txt"
        else:
            filename = f"web_rss_{slug}.txt"

        # Check file exists on disk
        filepath = self._input_dir / filename
        if filepath.exists():
            logger.debug(f"File already exists: {filename}")
            return None

        # Build file content with header
        source_label = self._source_label(source_type)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        header = (
            f"# Zrodlo: {source_label}\n"
            f"# Tytul: {title}\n"
            f"# URL: {url}\n"
            f"# Pobrano: {date_str}\n"
            + HEADER_SEPARATOR
        )
        full_content = header + content.strip() + "\n"

        # Write file
        try:
            self._input_dir.mkdir(parents=True, exist_ok=True)
            filepath.write_text(full_content, encoding="utf-8")
            logger.info(f"Saved: {filename} ({len(content)} chars)")
        except IOError as e:
            logger.warning(f"Could not write {filename}: {e}")
            return None

        # Register in fetch registry
        if self._registry:
            self._registry.register(
                url=url,
                title=title,
                source_type=source_type,
                output_file=filename,
                char_count=len(content),
                topic=topic,
            )

        return filename

    @staticmethod
    def _slugify(text: str) -> str:
        """
        Convert title to filesystem-safe slug.

        "Logika matematyczna" -> "logika_matematyczna"
        "Metoda naukowa (filozofia)" -> "metoda_naukowa_filozofia"
        """
        # Transliterate Polish characters
        slug = text.translate(_PL_TRANS)
        # Lowercase
        slug = slug.lower()
        # Replace non-alphanumeric with underscore
        slug = re.sub(r"[^a-z0-9]+", "_", slug)
        # Strip leading/trailing underscores
        slug = slug.strip("_")
        # Truncate
        if len(slug) > MAX_SLUG_LEN:
            slug = slug[:MAX_SLUG_LEN].rstrip("_")
        # Fallback for empty slug
        if not slug:
            slug = f"article_{int(time.time())}"
        return slug

    @staticmethod
    def _source_label(source_type: str) -> str:
        """Human-readable source label for file header."""
        labels = {
            "wikipedia": "Wikipedia (pl)",
            "rss": "RSS Feed",
            "codex": "Codex (ChatGPT) — operator-approved",
        }
        return labels.get(source_type.lower(), source_type)
