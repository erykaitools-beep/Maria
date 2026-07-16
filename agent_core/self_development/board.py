"""Curated self-development board.

Read-only aggregation of the meta-goals the creative subsystem already
generates. Produces a small list of SelfDevTheme objects and a plain-text
rendering for Telegram. Does NOT create goals or post bulletins (R1: advisory).

This is distinct from creative/creative_journal.py: that is a reflection diary
(one entry per reflection session). This is a curated, de-duplicated board of
WHAT Maria keeps asking to improve in herself, across all sessions.
"""

import json
import logging
import os
import threading
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from agent_core.self_development.model import (
    JOIN_BRIDGE_BROKEN,
    JOIN_LIVE,
    STUCK_MIN_ASKED,
    STUCK_MIN_DAYS,
    WHITELIST_REALIZED_REASONS,
    SelfDevTheme,
)
from agent_core.self_development.title_normalizer import normalize_title

logger = logging.getLogger(__name__)

# Terminal statuses that survive later-wins dedup (draft/proposed are interim).
_TERMINAL_STATUSES = ("accepted", "rejected")

# Default number of themes to surface on the board (top by ask-count).
DEFAULT_TOP_N = 5


class SelfDevJournal:
    """Builds and renders the curated self-development board.

    INC-1 scope: raw scan + later-wins dedup + normalization grouping +
    plain-text rendering. Embedding-based theme clustering (INC-4) and the
    realized/stuck join (INC-2) extend this without changing the public shape.
    """

    def __init__(self, data_dir: str, embedding_model=None):
        self._data_dir = data_dir
        self._embedding_model = embedding_model
        self._meta_goals_path = os.path.join(data_dir, "creative_meta_goals.jsonl")
        self._bulletin_path = os.path.join(data_dir, "cognitive_bulletin.jsonl")
        # Artifact: one live snapshot Maria regenerates (the doc she "writes").
        self._board_md_path = os.path.join(data_dir, "self_dev_board.md")
        # Audit: append-only history of regenerations (loop trend over time).
        self._audit_path = os.path.join(data_dir, "self_dev_journal.jsonl")
        # Cache populated by the tick (Phase 21, INC-5); read by the Telegram
        # command. Lock serializes the off-thread refresh vs command reads.
        self._lock = threading.Lock()
        self._cached_board: Optional[List[SelfDevTheme]] = None
        self._cached_at: float = 0.0

    # --- INC-1: raw read + dedup ------------------------------------------

    def read_meta_goals_raw(self) -> Dict[str, dict]:
        """Scan creative_meta_goals.jsonl, dedup by goal_id (later-wins).

        Reads the RAW file rather than CreativeStore, because the store caps at
        the newest 500 by created_ts -- which would destroy oldest_ts ("od kiedy
        prosi"). Keeps only the 4 fields we need per id to stay light as the
        file grows.

        Returns: {goal_id: {"title", "created_ts", "status"}}
        """
        out: Dict[str, dict] = {}
        if not os.path.exists(self._meta_goals_path):
            return out
        with open(self._meta_goals_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                gid = row.get("goal_id")
                if not gid:
                    continue
                # later-wins: last line for a goal_id is its current state
                out[gid] = {
                    "title": row.get("title", ""),
                    "created_ts": row.get("created_ts", 0.0),
                    "status": row.get("status", ""),
                }
        return out

    # --- INC-2: realized signal -------------------------------------------

    def _load_realized_meta_goal_ids(self) -> Dict[str, List[str]]:
        """Map meta_goal_id -> [bulletin entry_id] for REAL closes only.

        Reads the raw bulletin (merge-on-entry_id, later-wins) because the
        public BulletinStore API filters RESOLVED entries out. A close counts
        as "real" only when status is resolved AND metadata.last_status_reason
        is whitelisted. The reason lives in metadata["last_status_reason"]
        (not entry.reason_code, which is the CREATION reason e.g.
        "creative_architectural_meta" and never whitelisted). Skip/expire
        reasons deliberately do NOT count (anti false-comfort).
        """
        realized: Dict[str, List[str]] = defaultdict(list)
        if not os.path.exists(self._bulletin_path):
            return realized
        entries: Dict[str, dict] = {}
        with open(self._bulletin_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except (ValueError, TypeError):
                    continue
                eid = d.get("entry_id")
                if eid:
                    entries[eid] = d  # later-wins
        for eid, d in entries.items():
            if str(d.get("status", "")).lower() != "resolved":
                continue
            meta = d.get("metadata") or {}
            if meta.get("last_status_reason") not in WHITELIST_REALIZED_REASONS:
                continue
            mgid = meta.get("meta_goal_id")
            if mgid:
                realized[mgid].append(eid)
        return realized

    # --- INC-1: grouping + board build ------------------------------------

    def build_board(
        self,
        top_n: int = DEFAULT_TOP_N,
        now: Optional[float] = None,
    ) -> List[SelfDevTheme]:
        """Aggregate deduped meta-goals into the top-N self-development themes.

        INC-1 groups by normalized title (cheap, deterministic, no embedding).
        Synonym merging (treningowych/szkoleniowych) arrives with INC-4.
        """
        if now is None:
            now = time.time()
        goals = self.read_meta_goals_raw()
        realized_map = self._load_realized_meta_goal_ids()

        # group goal_ids by normalized title key
        groups: Dict[str, List[str]] = defaultdict(list)
        for gid, g in goals.items():
            key = normalize_title(g.get("title", ""))
            if not key:
                continue
            groups[key].append(gid)

        # join_status reflects the WHOLE board: if nothing anywhere has a real
        # close, the realized column mirrors a broken R1 bridge, not Maria's
        # self-assessment -- the header must say so honestly.
        any_realized = any(
            gid in realized_map
            for gids in groups.values() for gid in gids
        )
        join_status = JOIN_LIVE if any_realized else JOIN_BRIDGE_BROKEN

        themes: List[SelfDevTheme] = []
        for key, gids in groups.items():
            rows = [goals[gid] for gid in gids]
            tss = [r["created_ts"] for r in rows if r["created_ts"]]
            oldest = min(tss) if tss else now
            newest = max(tss) if tss else now
            days_old = max(0.0, (now - oldest) / 86400.0)
            # display title = most common RAW title in this group
            raw_titles = Counter(r["title"] for r in rows if r["title"])
            display = raw_titles.most_common(1)[0][0] if raw_titles else key
            status_breakdown = dict(
                Counter(
                    r["status"] for r in rows
                    if r["status"] in _TERMINAL_STATUSES
                )
            )
            asked = len(gids)
            evidence = [e for gid in gids for e in realized_map.get(gid, [])]
            realized = bool(evidence)
            # stuck = keeps asking, long enough, and nothing ever came of it
            stuck = (
                not realized
                and asked >= STUCK_MIN_ASKED
                and days_old >= STUCK_MIN_DAYS
            )
            themes.append(
                SelfDevTheme(
                    theme_id="norm:" + key,
                    display_title=display,
                    asked_count=asked,
                    oldest_ts=oldest,
                    newest_ts=newest,
                    days_old=days_old,
                    norm_aliases=[key],
                    status_breakdown=status_breakdown,
                    realized=realized,
                    realized_evidence=evidence,
                    stuck=stuck,
                    realized_join_status=join_status,
                )
            )

        themes.sort(key=lambda t: t.asked_count, reverse=True)
        return themes[:top_n]

    # --- INC-1: rendering --------------------------------------------------

    def format_for_telegram(self, themes: List[SelfDevTheme]) -> str:
        """Compact plain-text PL rendering for the phone -- one line per theme
        (no Markdown, no emoji in fixed strings -- ADR-005)."""
        if not themes:
            return "Brak pomyslow na samorozwoj do pokazania."
        stuck_count = sum(1 for t in themes if t.stuck)
        lines = [f"Samorozwoj: {len(themes)} tematow, {stuck_count} utknelo"]
        # Honest one-liner: when nothing closed via a real reason, the "utknal"
        # column reflects a broken pomysl->akcja bridge, not Maria's judgement.
        if themes[0].realized_join_status == JOIN_BRIDGE_BROKEN:
            lines.append("(nikt nie domyka tych pomyslow - to fakt z danych)")
        lines.append("")
        for i, t in enumerate(themes, 1):
            if t.realized:
                mark = "zrealizowane"
            elif t.stuck:
                mark = "UTKNAL"
            else:
                mark = "swiezy"
            lines.append(
                f"{i}. {t.display_title} - {t.asked_count}x, "
                f"{t.days_old:.0f}d - {mark}"
            )
        return "\n".join(lines)

    # --- cache + command entry point --------------------------------------

    def get_cached_board(self) -> List[SelfDevTheme]:
        """Return the last refreshed board, building one lazily if none cached.

        The tick (Phase 21, INC-5) refreshes the cache off-thread so the
        Telegram command reads instantly. Before the tick is wired, or on the
        first call, we build on demand so the command always answers.
        """
        with self._lock:
            if self._cached_board is not None:
                return self._cached_board
        board = self.build_board()
        with self._lock:
            self._cached_board = board
            self._cached_at = time.time()
        return board

    def render_board(self) -> str:
        """Plain-text board for the Telegram command (reads cache)."""
        return self.format_for_telegram(self.get_cached_board())

    def invalidate_cache(self) -> None:
        """Drop the cached board so the next read rebuilds from source.

        Used after an acknowledgement (/approve_dev) so a theme that just got
        resolved flips from UTKNAL to zrealizowane on the next /samorozwoj.
        """
        with self._lock:
            self._cached_board = None

    # --- INC-5: artifact write + tick orchestration -----------------------

    def _render_markdown(self, themes: List[SelfDevTheme], now: float) -> str:
        """Markdown snapshot of the board (the document Maria regenerates)."""
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
        lines = [
            "# Tablica samorozwoju Marii",
            "",
            f"_Zaktualizowano: {stamp}_",
            "",
        ]
        if themes and themes[0].realized_join_status == JOIN_BRIDGE_BROKEN:
            lines += [
                "> Uwaga: zaden pomysl nie zostal domkniety realnym dzialaniem.",
                "> Most pomysl->akcja jest przerwany -- 'utknal' to fakt z danych,",
                "> nie samoocena Marii.",
                "",
            ]
        for i, t in enumerate(themes, 1):
            since = time.strftime("%Y-%m-%d", time.localtime(t.oldest_ts))
            if t.realized:
                mark = "zrealizowane"
            elif t.stuck:
                mark = "UTKNAL"
            else:
                mark = "swiezy"
            lines.append(
                f"{i}. **{t.display_title}** -- prosze {t.asked_count}x, "
                f"od {since} ({t.days_old:.0f} dni) -- {mark}"
            )
        lines.append("")
        return "\n".join(lines)

    def write_artifact(self, themes: List[SelfDevTheme], now: float) -> None:
        """Regenerate the .md snapshot (atomic) + append one audit record.

        self_dev_board.md is rewritten via os.replace -> always exactly one
        current document (no append-dump; one live file per docs-cleanup norm).
        self_dev_journal.jsonl appends a small record per regeneration so the
        stuck-count trend over time is observable.
        """
        md = self._render_markdown(themes, now)
        tmp = self._board_md_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(md)
        os.replace(tmp, self._board_md_path)

        rec = {
            "ts": now,
            "theme_count": len(themes),
            "stuck_count": sum(1 for t in themes if t.stuck),
            "themes": [
                {
                    "theme_id": t.theme_id,
                    "asked_count": t.asked_count,
                    "oldest_ts": t.oldest_ts,
                    "stuck": t.stuck,
                    "realized": t.realized,
                }
                for t in themes
            ],
        }
        with open(self._audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def refresh_and_write(self) -> List[SelfDevTheme]:
        """Tick entry point (Phase 21): rebuild board, refresh cache, write.

        Runs off the tick thread (embedding/IO would overrun the 1.0s budget).
        Builds the board, swaps the command cache under the lock, then writes
        the artifact + audit. Read-only over the meta-goal/bulletin sources
        (R1: never creates goals or posts bulletins).
        """
        now = time.time()
        themes = self.build_board(now=now)
        with self._lock:
            self._cached_board = themes
            self._cached_at = now
        self.write_artifact(themes, now)
        return themes
