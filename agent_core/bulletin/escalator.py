"""
Most #1: BulletinEscalator — auto-escalates k12_strategy_change advisory
entries to PROPOSED maintenance goals when >=3 same-theme entries appear
in a 7-day window.

Closes the "K12 critiques but doesn't react" loop:
- 51 advisory entries since 2026-04-26 with status:open and zero ever
  resolved/escalated (snapshot 2026-05-05).
- LLM-generated topics make literal-string dedup impossible (same theme,
  different words each call).

Strategy: deterministic keyword-based theme classifier over topic+summary
+ rolling window count + active-PROPOSED dedup so the same theme is not
proposed twice while operator is still deciding.

Out-of-scope (intentional, KISS v1):
- mode_aware_pattern / creative_loop_suppression entries — they have
  their own loops (D3/D4) and small volumes
- Embedding-based similarity — revisit if keyword classifier proves too
  rigid in practice
- Auto-resolve of source entries on escalation — status stays OPEN until
  the goal is accepted/rejected (full audit trail)

ADR alignment:
- ADR-020 (K12 PROPOSED goals z human gate) — same path
- ADR-011 (Goals as data, audit trail)
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from agent_core.bulletin.bulletin_model import BulletinEntry, EntryType
from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.goals.goal_model import (
    GoalStatus,
    GoalType,
    create_goal,
)

logger = logging.getLogger(__name__)


# Lookback window for theme counting (7 days)
ESCALATION_WINDOW_SEC = 7 * 24 * 3600

# Minimum same-theme entries to trigger escalation
ESCALATION_THRESHOLD = 3

# Only this reason_code is in scope (mode_aware/creative loops have D3/D4)
SCOPE_REASON_CODE = "k12_strategy_change"

# Theme tag fallback when no keyword pattern matches
THEME_OTHER = "other"

# Marker for goals created by this module (used for dedup)
ESCALATOR_CREATED_BY = "bulletin_escalator"


# Theme patterns. First match wins, so the order here matters: most
# specific themes are listed first so they capture entries that also
# mention generic action tokens (e.g. an entry about "stale goals related
# to akcji 'learn'" classifies as stale_goals, not learn_failures).
#
# Patterns mix:
# - English tokens used as Maria-internal action names (skip/learn/...)
#   are matched as whole words (\b ... \b) to avoid sub-word noise.
# - Polish stems (pomija/walidac/nieaktywn) are matched as substrings to
#   cover inflections (pomijanie / pomijam / pomijajacy / ...).
_THEME_PATTERNS: List[Tuple[str, List[str]]] = [
    ("stale_goals", [
        r"stale\s*goal",
        r"stałe\s*cel",
        r"nieaktywn",
        r"zablokowan",
    ]),
    ("retention_low", [
        r"\bretention\b",
        r"utrwal",
        r"przyswaja",
    ]),
    ("loop_detection", [
        r"pętl",
        r"\bloop\b",
        r"powtarz",
    ]),
    ("passive_drift", [
        r"pasywn",
        r"stagnacj",
        r"uśpion",
    ]),
    ("mode_thrashing", [
        r"\btryb(?:ie|y|ow)?\b",
        r"\bmode\b",
        r"fluctuation",
    ]),
    ("exam_failures", [
        r"\bexam\b",
        r"egzamin",
    ]),
    ("validate_failures", [
        r"\bvalidate\b",
        r"walidac",
    ]),
    ("learn_failures", [
        r"\blearn\b",
        r"akcj.{0,8}nauk",
    ]),
    ("skip_overuse", [
        r"\bskip\b",
        r"pomija",
    ]),
]

# Pre-compile for hot path
_COMPILED_PATTERNS: List[Tuple[str, List[re.Pattern]]] = [
    (theme, [re.compile(p, re.IGNORECASE) for p in patterns])
    for theme, patterns in _THEME_PATTERNS
]


def classify_theme(entry: BulletinEntry) -> str:
    """Return single theme_tag matching first pattern over topic+summary.

    Falls back to THEME_OTHER if no pattern matches. Patterns are checked
    in declared order — most specific themes first.
    """
    text = f"{entry.topic} {entry.summary}"
    for theme, patterns in _COMPILED_PATTERNS:
        for pat in patterns:
            if pat.search(text):
                return theme
    return THEME_OTHER


class BulletinEscalator:
    """Escalates k12_strategy_change advisory entries to PROPOSED goals."""

    def __init__(
        self,
        bulletin_store: BulletinStore,
        goal_store: Any,  # GoalStore (avoid circular import in type hint)
        threshold: int = ESCALATION_THRESHOLD,
        window_sec: float = ESCALATION_WINDOW_SEC,
    ):
        self._bulletin = bulletin_store
        self._goals = goal_store
        self._threshold = threshold
        self._window = float(window_sec)

    def scan_and_escalate(self, now: Optional[float] = None) -> List[str]:
        """Single scan pass. Returns list of newly created goal IDs.

        Persistence order matters: GoalStore.propose() only marks goals
        dirty in memory, so we MUST call goal_store.save() before tagging
        bulletin entries. Otherwise a process crash after tag_escalated()
        leaves the bulletin pointing to goal IDs that were never persisted
        (orphan tags). Tests prior to 2026-05-06 used in-memory get() and
        missed this — see test_goals_persisted_to_disk.
        """
        if now is None:
            now = time.time()

        candidates = self._collect_candidates(now)
        if not candidates:
            return []

        by_theme: Dict[str, List[BulletinEntry]] = {}
        for entry in candidates:
            theme = classify_theme(entry)
            by_theme.setdefault(theme, []).append(entry)

        active_themes = self._active_proposed_themes()

        # Phase 1: propose all goals (in-memory, dirty)
        proposals: List[Tuple[str, List[BulletinEntry]]] = []
        for theme, entries in sorted(by_theme.items()):
            if theme == THEME_OTHER:
                # Generic bucket — don't auto-escalate, would mix unrelated topics.
                continue
            if len(entries) < self._threshold:
                continue
            if theme in active_themes:
                logger.info(
                    f"[ESCALATOR] Skip theme={theme}: active PROPOSED/PENDING goal exists"
                )
                continue
            goal_id = self._propose_goal(theme, entries)
            if goal_id is None:
                logger.info(
                    f"[ESCALATOR] propose() returned None for theme={theme} "
                    f"(displaced or capacity)"
                )
                continue
            proposals.append((goal_id, entries))

        if not proposals:
            return []

        # Phase 2: persist goals BEFORE tagging entries.
        # If save() fails (logged inside GoalStore), tags are not written
        # and goals stay dirty for the next save cycle.
        self._goals.save()

        # Phase 3: tag bulletin entries (each tag_escalated _appends to file)
        created: List[str] = []
        for goal_id, entries in proposals:
            created.append(goal_id)
            for e in entries:
                self._bulletin.tag_escalated(e.entry_id, goal_id)

        logger.info(
            f"[ESCALATOR] Created {len(created)} PROPOSED goals: {created}"
        )
        return created

    # --- Internals ---

    def _collect_candidates(self, now: float) -> List[BulletinEntry]:
        """Open IMPROVEMENT entries: k12_strategy_change, in-window, unescalated."""
        cutoff = now - self._window
        entries = self._bulletin.get_by_type(EntryType.IMPROVEMENT)
        out = []
        for e in entries:
            if e.reason_code != SCOPE_REASON_CODE:
                continue
            if e.created_at < cutoff:
                continue
            if e.metadata.get("escalated_to_goal"):
                continue
            out.append(e)
        return out

    def _active_proposed_themes(self) -> Set[str]:
        """Themes already covered by a non-terminal goal we created earlier."""
        out: Set[str] = set()
        active_statuses = {
            GoalStatus.PROPOSED,
            GoalStatus.PENDING,
            GoalStatus.ACTIVE,
        }
        for g in self._goals.get_all():
            if g.created_by != ESCALATOR_CREATED_BY:
                continue
            if g.status not in active_statuses:
                continue
            tag = g.metadata.get("theme_tag")
            if tag:
                out.add(tag)
        return out

    def _propose_goal(
        self, theme: str, entries: List[BulletinEntry]
    ) -> Optional[str]:
        """Create + propose() the goal. Returns goal_id or None if displaced."""
        max_pri = max((e.priority for e in entries), default=0.7)
        # Sample up to 3 distinct topic prefixes for human-readable description
        sample_topics = sorted({e.topic[:60] for e in entries if e.topic})[:3]
        sample_str = "; ".join(sample_topics) if sample_topics else "—"
        description = (
            f"K12 advisory escalation: {theme} "
            f"({len(entries)}x w 7d). Próbki: {sample_str}"
        )
        goal = create_goal(
            goal_type=GoalType.MAINTENANCE,
            description=description,
            priority=max_pri,
            status=GoalStatus.PROPOSED,
            created_by=ESCALATOR_CREATED_BY,
            metadata={
                "theme_tag": theme,
                "source_entry_ids": [e.entry_id for e in entries],
                "source_count": len(entries),
                "risk_level": "medium",
                "scope_reason_code": SCOPE_REASON_CODE,
            },
        )
        return self._goals.propose(goal)
