"""
KronikaReport -- renders a market chronicle document from a /project tree.

Turns a project parent (e.g. Kronika rynku BTC/zloto/srebro) and its
market-stamped children into a chronological, human-readable report: one
entry per pantry file (metadata['market_file_ids']), with title, source,
fetch date, verification status and a short lead. The report text feeds the
existing Telegram PDF pipe (pdf_export.generate_task_pdf), so a project can
end as a DOCUMENT in the operator's hands instead of a progress counter.

READ-ONLY by design: reads goals via GoalStore accessors and article files
from the input dir; never mutates goals, the knowledge index or soul files.
Provenance-honest: only stamped market_file_ids enter the report -- the same
set the provenance gate credits -- so a false-matched file can never appear.
"""

import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Article files are written by the FETCH pipe into the learning inbox.
DEFAULT_INPUT_DIR = Path(__file__).resolve().parents[2] / "input"

_HEADER_KEYS = {
    "zrodlo": "source",
    "tytul": "title",
    "url": "url",
    "pobrano": "fetched",
}
_LEAD_MAX_CHARS = 420
# A UTF-8 sequence mis-decoded as latin-1 becomes: lead char U+00C2-U+00F4
# followed by 1-3 continuation chars U+0080-U+00BF ("ł" C5 82 -> "Å"+ctrl,
# "ó" C3 B3 -> "Ã³", curly quote E2 80 99 -> "â"+2 ctrls). Matching the exact
# byte structure lets us repair each sequence independently, so MIXED text
# (mojibake Polish next to genuine curly quotes) still comes out clean.
_MOJIBAKE_SEQ = re.compile(
    "[\u00f0-\u00f4][\u0080-\u00bf]{3}"
    "|[\u00e0-\u00ef][\u0080-\u00bf]{2}"
    "|[\u00c2-\u00df][\u0080-\u00bf]"
)


def _fix_mojibake(text: str) -> str:
    """Repair UTF-8-read-as-latin-1 mojibake (display-time only).

    The first 18 Kronika pantry files were fetched before the
    article_fetcher charset fix and store "przeÅ\x82amaÅ\x82" instead of
    "przełamał". Each matched sequence is re-encoded via latin-1 and decoded
    as UTF-8 on its own; anything that does not round-trip stays untouched,
    and clean Polish text has no such sequences at all (its diacritics are
    outside latin-1), so it passes through unchanged.
    """
    if not text:
        return text

    def _repair(m: "re.Match") -> str:
        s = m.group(0)
        try:
            return s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s

    return _MOJIBAKE_SEQ.sub(_repair, text)


def _parse_article_file(path: Path) -> Optional[Dict[str, str]]:
    """Parse the '# Klucz: wartosc' header block + body lead from a fetched
    article file. Returns None when the file is unreadable/absent."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    info: Dict[str, str] = {}
    body_lines: List[str] = []
    in_header = True
    for line in raw.splitlines():
        stripped = line.strip()
        if in_header:
            if stripped.startswith("#"):
                content = stripped.lstrip("#").strip()
                if content == "---":
                    in_header = False
                    continue
                if ":" in content:
                    key, _, value = content.partition(":")
                    mapped = _HEADER_KEYS.get(
                        key.strip().lower().replace("ź", "z").replace("ó", "o"))
                    if mapped:
                        info[mapped] = value.strip()
                continue
            in_header = False
        if stripped:
            body_lines.append(stripped)
    lead = " ".join(body_lines)[:_LEAD_MAX_CHARS].strip()
    if lead and len(" ".join(body_lines)) > _LEAD_MAX_CHARS:
        lead = lead.rsplit(" ", 1)[0] + " (...)"
    info["lead"] = _fix_mojibake(lead)
    if "title" in info:
        info["title"] = _fix_mojibake(info["title"])
    return info


def _domain(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else ""


def _date_from_file_id(file_id: str) -> str:
    """Fallback date from ids like web_rss_20260711_slug.txt -> 2026-07-11."""
    m = re.search(r"_(\d{4})(\d{2})(\d{2})_", file_id or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def build_kronika_report(
    goal_store,
    parent_id: str,
    input_dir: Optional[Path] = None,
    verified_ids: Optional[set] = None,
) -> Optional[str]:
    """Build the chronicle text for a project tree, or None when the parent
    does not exist. Markdown-ish output tuned for pdf_export._render_result
    (## headings, - bullets, plain paragraphs)."""
    parent = goal_store.get(parent_id)
    if parent is None:
        return None
    if verified_ids is None:
        try:
            from agent_core.goals.success_criteria import (
                independently_verified_file_ids,
            )
            verified_ids = independently_verified_file_ids()
        except Exception as e:
            logger.debug("[KRONIKA] verified-ids lookup failed: %s", e)
            verified_ids = set()
    input_dir = Path(input_dir) if input_dir else DEFAULT_INPUT_DIR

    children = goal_store.get_children(parent_id)
    lines: List[str] = []
    lines.append(f"# {parent.description}")
    generated = time.strftime("%Y-%m-%d %H:%M")
    deadline = getattr(parent, "deadline", None)
    deadline_s = (
        time.strftime("%Y-%m-%d", time.localtime(deadline)) if deadline else "-"
    )
    lines.append(
        f"Wygenerowano: {generated} | Termin projektu: {deadline_s} | "
        f"Podcele: {len(children)}"
    )
    lines.append("")

    total_files = 0
    total_verified = 0
    for child in children:
        meta = child.metadata or {}
        file_ids = list(meta.get("market_file_ids") or [])
        target_n = meta.get("provenance_target_n")
        child_verified = [f for f in file_ids if f in verified_ids]
        total_files += len(file_ids)
        total_verified += len(child_verified)

        lines.append(f"## {child.description}")
        target_s = f"/{target_n}" if target_n else ""
        lines.append(
            f"Status: {child.status.value} | zebrane: {len(file_ids)}{target_s} "
            f"| zweryfikowane niezaleznym egzaminem: {len(child_verified)}"
        )
        lines.append("")
        if not file_ids:
            lines.append("(spizarnia pusta - brak zebranych materialow)")
            lines.append("")
            continue

        entries = []
        for fid in file_ids:
            info = _parse_article_file(input_dir / fid) or {}
            entries.append((
                info.get("fetched") or _date_from_file_id(fid),
                fid,
                info,
            ))
        entries.sort(key=lambda e: (e[0], e[1]))

        for fetched, fid, info in entries:
            title = info.get("title") or fid
            badge = "[ZWERYFIKOWANY]" if fid in verified_ids else "[zebrany]"
            src = _domain(info.get("url", "")) or info.get("source", "")
            src_s = f" ({src})" if src else ""
            lines.append(f"**{fetched or '????-??-??'} {badge} {title}{src_s}**")
            lead = info.get("lead")
            if lead:
                lines.append(lead)
            url = info.get("url")
            if url:
                lines.append(f"- {url}")
            lines.append("")

    lines.append("---")
    lines.append(
        f"Razem: {total_files} materialow rynkowych, "
        f"{total_verified} zweryfikowanych niezaleznym egzaminem. "
        f"Do raportu wchodza WYLACZNIE pliki ze stempla provenance "
        f"(market_file_ids) - zaden luzny token-match."
    )
    return "\n".join(lines)
