"""Tests for Most #1: BulletinEscalator (k12_strategy_change → PROPOSED goal).

Covers:
- classify_theme() taxonomy + ordering precedence
- threshold + 7d window semantics
- scope filter (only k12_strategy_change)
- dedup against active PROPOSED/PENDING/ACTIVE goals from us
- entry tagging (escalated_to_goal)
- "other" bucket never escalates
"""

import time
import pytest

from agent_core.bulletin.bulletin_model import (
    BulletinEntry,
    EntryStatus,
    EntryType,
    create_entry,
)
from agent_core.bulletin.bulletin_store import BulletinStore
from agent_core.bulletin.escalator import (
    BulletinEscalator,
    ESCALATION_THRESHOLD,
    ESCALATION_WINDOW_SEC,
    ESCALATOR_CREATED_BY,
    SCOPE_REASON_CODE,
    THEME_OTHER,
    classify_theme,
)
from agent_core.goals.goal_model import GoalStatus, GoalType, create_goal
from agent_core.goals.store import GoalStore


# ──────────────────────────────────────
# classify_theme() — taxonomy
# ──────────────────────────────────────


def _entry(topic: str, summary: str, **md) -> BulletinEntry:
    return create_entry(
        entry_type=EntryType.IMPROVEMENT,
        topic=topic,
        reason_code=SCOPE_REASON_CODE,
        summary=summary,
        requested_by="self_analysis",
        priority=0.7,
        metadata=md or {},
    )


class TestClassifyTheme:
    def test_skip_overuse_english_token(self):
        e = _entry("Akcja 'skip'", "Agent używa skip 77 razy.")
        assert classify_theme(e) == "skip_overuse"

    def test_skip_overuse_polish_stem(self):
        e = _entry("Nadmierne pomijanie", "Agent ignoruje materiał, pomija go.")
        assert classify_theme(e) == "skip_overuse"

    def test_learn_failures(self):
        e = _entry("akcja 'learn'", "Akcja learn ma 0% sukcesu.")
        assert classify_theme(e) == "learn_failures"

    def test_validate_failures(self):
        e = _entry("walidacja", "Walidacja zawodzi systematycznie (0% success).")
        assert classify_theme(e) == "validate_failures"

    def test_exam_failures(self):
        e = _entry("egzaminowanie", "Skuteczność egzaminów 10%.")
        assert classify_theme(e) == "exam_failures"

    def test_stale_goals_takes_precedence_over_learn(self):
        # Real-world entry: contains both "stale goals" terms and "learn"
        e = _entry(
            "Zarządzanie starymi celami",
            "Cel goal-meta-learn jest nieaktywny od 64 dni, zablokowane cele",
        )
        # stale_goals comes before learn_failures in taxonomy
        assert classify_theme(e) == "stale_goals"

    def test_passive_drift(self):
        e = _entry("Stagnacja", "Agent jest pasywny, brak aktywności.")
        assert classify_theme(e) == "passive_drift"

    def test_loop_detection(self):
        e = _entry("Pętla nauki", "Powtarzające się cykle, nie ma postępu.")
        assert classify_theme(e) == "loop_detection"

    def test_retention_low(self):
        e = _entry("retention", "Nie potrafi utrwalić wiedzy.")
        assert classify_theme(e) == "retention_low"

    def test_mode_thrashing(self):
        e = _entry("Tryb pracy", "Częste przejścia trybu, mode fluctuation.")
        assert classify_theme(e) == "mode_thrashing"

    def test_other_fallback_when_no_pattern_matches(self):
        e = _entry("xyz", "Coś tam całkiem niepasującego do żadnej kategorii.")
        assert classify_theme(e) == THEME_OTHER

    def test_classifier_is_case_insensitive(self):
        e = _entry("AKCJA SKIP", "AGENT POMIJA WSZYSTKO.")
        assert classify_theme(e) == "skip_overuse"

    def test_skip_word_boundary_avoids_substring_noise(self):
        # "ski" is not "skip" — no false-positive match.
        e = _entry("xyz", "ski jazda po stoku zupełnie obca tematyce.")
        assert classify_theme(e) == THEME_OTHER


# ──────────────────────────────────────
# Escalator integration — fixtures
# ──────────────────────────────────────


@pytest.fixture
def stores(tmp_path):
    bulletin = BulletinStore(path=tmp_path / "bulletin.jsonl")
    goals = GoalStore(tmp_path / "goals.jsonl")
    return bulletin, goals


def _seed(bulletin: BulletinStore, topic: str, summary: str,
          age_days: float = 0.0,
          reason_code: str = SCOPE_REASON_CODE,
          escalated_to_goal: str = "",
          priority: float = 0.7) -> BulletinEntry:
    """Create + post an IMPROVEMENT entry, optionally backdated."""
    md = {}
    if escalated_to_goal:
        md["escalated_to_goal"] = escalated_to_goal
    entry = bulletin.create_and_post(
        entry_type=EntryType.IMPROVEMENT,
        topic=topic,
        reason_code=reason_code,
        summary=summary,
        requested_by="self_analysis",
        priority=priority,
        metadata=md,
    )
    if age_days > 0:
        entry.created_at = time.time() - age_days * 86400
        bulletin._append(entry)  # persist backdating
    return entry


# ──────────────────────────────────────
# Escalator core flow
# ──────────────────────────────────────


class TestScanAndEscalate:
    def test_three_skip_entries_create_proposed_goal(self, stores):
        bulletin, goals = stores
        e1 = _seed(bulletin, "Akcja skip nr 1", "Agent skip 77 razy.")
        e2 = _seed(bulletin, "skip dominuje", "Skip 155 z 200 akcji.")
        e3 = _seed(bulletin, "pomijanie", "Nadmierne pomijanie materiału.")

        esc = BulletinEscalator(bulletin, goals)
        created = esc.scan_and_escalate()

        assert len(created) == 1
        goal = goals.get(created[0])
        assert goal is not None
        assert goal.status == GoalStatus.PROPOSED
        assert goal.created_by == ESCALATOR_CREATED_BY
        assert goal.type == GoalType.MAINTENANCE
        assert goal.metadata["theme_tag"] == "skip_overuse"
        assert goal.metadata["source_count"] == 3
        assert set(goal.metadata["source_entry_ids"]) == {
            e1.entry_id, e2.entry_id, e3.entry_id,
        }
        assert goal.metadata["risk_level"] == "medium"

    def test_below_threshold_no_goal(self, stores):
        bulletin, goals = stores
        _seed(bulletin, "Akcja skip nr 1", "Skip 77 razy.")
        _seed(bulletin, "skip dominuje", "Skip 155 z 200.")

        esc = BulletinEscalator(bulletin, goals)
        assert esc.scan_and_escalate() == []
        assert len(goals.get_all()) == 0

    def test_entries_get_tagged_with_goal_id(self, stores):
        bulletin, goals = stores
        ids = [
            _seed(bulletin, f"skip nr {i}", "skip dominuje").entry_id
            for i in range(3)
        ]

        esc = BulletinEscalator(bulletin, goals)
        created = esc.scan_and_escalate()
        assert len(created) == 1

        for entry_id in ids:
            entry = bulletin.get(entry_id)
            assert entry is not None
            assert entry.metadata.get("escalated_to_goal") == created[0]
            # Status MUST stay OPEN — operator decides via PROPOSED gate.
            assert entry.status == EntryStatus.OPEN

    def test_already_escalated_entries_skipped(self, stores):
        bulletin, goals = stores
        # Two fresh + one already-escalated → only 2 left, below threshold.
        _seed(bulletin, "skip 1", "Skip dominuje.",
              escalated_to_goal="goal-existing")
        _seed(bulletin, "skip 2", "Pomijanie nadmierne.")
        _seed(bulletin, "skip 3", "Akcja skip 50%.")

        esc = BulletinEscalator(bulletin, goals)
        assert esc.scan_and_escalate() == []

    def test_outside_7d_window_excluded(self, stores):
        bulletin, goals = stores
        _seed(bulletin, "skip 1", "skip dominuje", age_days=8.0)
        _seed(bulletin, "skip 2", "pomijanie", age_days=10.0)
        _seed(bulletin, "skip 3", "skip 50%")  # fresh

        esc = BulletinEscalator(bulletin, goals)
        # Only 1 within window — below threshold.
        assert esc.scan_and_escalate() == []

    def test_only_k12_strategy_change_in_scope(self, stores):
        bulletin, goals = stores
        # Three improvement entries but with different reason_code — out of scope.
        for i in range(3):
            _seed(
                bulletin, f"mode pattern {i}", "Tryb się zmienia czesto.",
                reason_code="mode_aware_pattern",
            )

        esc = BulletinEscalator(bulletin, goals)
        assert esc.scan_and_escalate() == []

    def test_active_proposed_blocks_re_escalation(self, stores):
        bulletin, goals = stores
        # First scan creates a PROPOSED goal.
        for i in range(3):
            _seed(bulletin, f"skip {i}", "skip dominuje")
        esc = BulletinEscalator(bulletin, goals)
        first = esc.scan_and_escalate()
        assert len(first) == 1

        # Add 3 more skip-themed entries (not yet escalated).
        for i in range(3, 6):
            _seed(bulletin, f"skip {i}", "skip ciągle dominuje")

        # Re-scan: PROPOSED is still active → no new goal for same theme.
        second = esc.scan_and_escalate()
        assert second == []

    def test_active_pending_also_blocks(self, stores):
        bulletin, goals = stores
        # Pre-existing PENDING goal from us with theme_tag=skip_overuse.
        existing = create_goal(
            goal_type=GoalType.MAINTENANCE,
            description="prev",
            priority=0.7,
            status=GoalStatus.PENDING,
            created_by=ESCALATOR_CREATED_BY,
            metadata={"theme_tag": "skip_overuse"},
        )
        goals.create(existing)
        for i in range(3):
            _seed(bulletin, f"skip {i}", "skip dominuje")

        esc = BulletinEscalator(bulletin, goals)
        assert esc.scan_and_escalate() == []

    def test_terminal_goal_does_not_block(self, stores):
        bulletin, goals = stores
        # Pre-existing ABANDONED goal — should NOT block.
        prev = create_goal(
            goal_type=GoalType.MAINTENANCE,
            description="prev abandoned",
            priority=0.7,
            status=GoalStatus.ABANDONED,
            created_by=ESCALATOR_CREATED_BY,
            metadata={"theme_tag": "skip_overuse"},
        )
        goals.create(prev)
        for i in range(3):
            _seed(bulletin, f"skip {i}", "skip dominuje")

        esc = BulletinEscalator(bulletin, goals)
        created = esc.scan_and_escalate()
        assert len(created) == 1

    def test_other_bucket_never_escalates(self, stores):
        bulletin, goals = stores
        # 5 entries that don't match any theme — would-be cluster of "other".
        for i in range(5):
            _seed(
                bulletin, f"xyz {i}",
                "Zupełnie nietypowe odniesienie do niczego konkretnego.",
            )
        esc = BulletinEscalator(bulletin, goals)
        assert esc.scan_and_escalate() == []

    def test_two_themes_create_two_goals(self, stores):
        bulletin, goals = stores
        for i in range(3):
            _seed(bulletin, f"skip {i}", "skip dominuje, pomijanie")
        for i in range(3):
            _seed(bulletin, f"validate {i}", "walidacja zawodzi 0%")

        esc = BulletinEscalator(bulletin, goals)
        created = esc.scan_and_escalate()
        assert len(created) == 2
        themes = {goals.get(gid).metadata["theme_tag"] for gid in created}
        assert themes == {"skip_overuse", "validate_failures"}

    def test_priority_uses_max_of_cluster(self, stores):
        bulletin, goals = stores
        _seed(bulletin, "skip 1", "skip dominuje", priority=0.5)
        _seed(bulletin, "skip 2", "skip dominuje", priority=0.95)
        _seed(bulletin, "skip 3", "skip dominuje", priority=0.7)

        esc = BulletinEscalator(bulletin, goals)
        created = esc.scan_and_escalate()
        goal = goals.get(created[0])
        assert goal.priority == pytest.approx(0.95)

    def test_proposed_goal_not_auto_confirmed(self, stores):
        # MAINTENANCE + created_by="bulletin_escalator" must NOT trigger
        # GoalStore.AUTO_CONFIRM_SOURCES path (which is only LEARNING/META
        # from creative/critic/self_analysis).
        bulletin, goals = stores
        for i in range(3):
            _seed(bulletin, f"skip {i}", "skip dominuje")
        esc = BulletinEscalator(bulletin, goals)
        created = esc.scan_and_escalate()
        goal = goals.get(created[0])
        # Must stay PROPOSED — operator gate required (ADR-020).
        assert goal.status == GoalStatus.PROPOSED


# ──────────────────────────────────────
# BulletinStore.tag_escalated()
# ──────────────────────────────────────


class TestTagEscalated:
    def test_tags_existing_entry(self, tmp_path):
        store = BulletinStore(path=tmp_path / "bulletin.jsonl")
        e = store.create_and_post(
            entry_type=EntryType.IMPROVEMENT,
            topic="t", reason_code="k12_strategy_change",
            summary="s", requested_by="self_analysis",
        )
        assert store.tag_escalated(e.entry_id, "goal-abc") is True
        reloaded = store.get(e.entry_id)
        assert reloaded.metadata["escalated_to_goal"] == "goal-abc"
        assert reloaded.status == EntryStatus.OPEN  # unchanged

    def test_returns_false_for_unknown(self, tmp_path):
        store = BulletinStore(path=tmp_path / "bulletin.jsonl")
        assert store.tag_escalated("nonexistent", "goal-x") is False

    def test_persists_across_reload(self, tmp_path):
        path = tmp_path / "bulletin.jsonl"
        s1 = BulletinStore(path=path)
        e = s1.create_and_post(
            entry_type=EntryType.IMPROVEMENT, topic="t",
            reason_code="k12_strategy_change", summary="s",
            requested_by="self_analysis",
        )
        s1.tag_escalated(e.entry_id, "goal-xyz")

        s2 = BulletinStore(path=path)
        reloaded = s2.get(e.entry_id)
        assert reloaded is not None
        assert reloaded.metadata["escalated_to_goal"] == "goal-xyz"


# ──────────────────────────────────────
# Persistence regression: scan_and_escalate() must save goals
# before tagging bulletin entries (else orphan tags on crash).
# Bug found 2026-05-06 — earlier tests only used in-memory get().
# ──────────────────────────────────────


class TestPersistenceContract:
    def test_goals_persisted_to_disk(self, tmp_path):
        """Created goals must reach goals.jsonl, not just in-memory dict."""
        bulletin = BulletinStore(path=tmp_path / "bulletin.jsonl")
        goals = GoalStore(tmp_path / "goals.jsonl")

        for i in range(3):
            _seed(bulletin, f"skip {i}", "skip dominuje")

        esc = BulletinEscalator(bulletin, goals)
        created = esc.scan_and_escalate()
        assert len(created) == 1

        # Reload from disk — goals MUST be there.
        goals2 = GoalStore(tmp_path / "goals.jsonl")
        goals2.load()
        reloaded = goals2.get(created[0])
        assert reloaded is not None, (
            "Goal not persisted to goals.jsonl — orphan tags will result"
        )
        assert reloaded.status == GoalStatus.PROPOSED
        assert reloaded.created_by == ESCALATOR_CREATED_BY

    def test_no_orphan_tags_when_proposals_made(self, tmp_path):
        """Every escalated_to_goal tag must reference a persisted goal."""
        bulletin = BulletinStore(path=tmp_path / "bulletin.jsonl")
        goals = GoalStore(tmp_path / "goals.jsonl")

        ids = [
            _seed(bulletin, f"skip {i}", "skip dominuje").entry_id
            for i in range(3)
        ]
        esc = BulletinEscalator(bulletin, goals)
        created = esc.scan_and_escalate()
        assert len(created) == 1
        target_goal = created[0]

        # Reload BOTH stores from disk and cross-check
        goals2 = GoalStore(tmp_path / "goals.jsonl")
        goals2.load()
        bulletin2 = BulletinStore(path=tmp_path / "bulletin.jsonl")

        for entry_id in ids:
            tag = bulletin2.get(entry_id).metadata.get("escalated_to_goal")
            assert tag == target_goal
            # Tag must reference a goal that actually exists on disk
            assert goals2.get(tag) is not None, (
                f"Orphan tag: bulletin entry {entry_id} -> goal {tag} "
                f"(goal not in goals.jsonl)"
            )

    def test_no_save_called_when_nothing_to_propose(self, tmp_path):
        """No-op scans should not write to goals.jsonl (no churn)."""
        bulletin = BulletinStore(path=tmp_path / "bulletin.jsonl")
        goals = GoalStore(tmp_path / "goals.jsonl")
        # Below threshold — no proposals.
        _seed(bulletin, "skip 1", "skip dominuje")
        _seed(bulletin, "skip 2", "skip dominuje")

        esc = BulletinEscalator(bulletin, goals)
        assert esc.scan_and_escalate() == []
        # File should not exist (or be empty) — no goals were saved.
        goals_file = tmp_path / "goals.jsonl"
        if goals_file.exists():
            assert goals_file.read_text().strip() == ""
