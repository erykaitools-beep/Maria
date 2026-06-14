"""Tests for StateSnapshot (B0 foundation, 2026-05-09)."""

from agent_core.predictive.state_snapshot import (
    NUMERIC_FEATURE_ORDER,
    StateSnapshot,
)


# --- from_context: happy path ----------------------------------------


def test_from_context_full_input_populates_all_features():
    snap = StateSnapshot.from_context(
        timestamp=1234.0,
        homeostasis_summary={
            "cpu_percent": 17.5,
            "ram_gb": 5.2,
            "error_count_window": 2,
            "mode": "ACTIVE",
            "health_score": 0.91,
        },
        n_active_goals=4,
        last_decision={"action_type": "learn"},
        episode_id="ep-abc123",
    )
    assert snap.timestamp == 1234.0
    assert snap.mode == "ACTIVE"
    assert snap.last_action_type == "learn"
    assert snap.health_score == 0.91
    assert snap.episode_id == "ep-abc123"
    assert set(snap.numeric_features_used) == set(NUMERIC_FEATURE_ORDER)


def test_from_context_numeric_vector_stable_order():
    snap = StateSnapshot.from_context(
        timestamp=0,
        homeostasis_summary={
            "cpu_percent": 10.0,
            "ram_gb": 4.0,
            "error_count_window": 1,
            "mode": "ACTIVE",
        },
        n_active_goals=3,
    )
    # Order MUST match NUMERIC_FEATURE_ORDER: cpu, ram, errors, goals, mode
    assert snap.numeric_vector() == [10.0, 4.0, 1.0, 3.0, 0.0]


def test_from_context_semantic_text_includes_known_fields():
    snap = StateSnapshot.from_context(
        timestamp=0,
        homeostasis_summary={"mode": "REDUCED", "health_score": 0.75},
        n_active_goals=2,
        last_decision={"action_type": "skip"},
    )
    text = snap.semantic_text
    assert "mode=REDUCED" in text
    assert "active_goals=2" in text
    assert "last_action=skip" in text
    assert "health=0.75" in text


# --- from_context: missing-feature contract --------------------------


def test_from_context_missing_features_excluded_not_zero_filled():
    """A feature with no upstream value must be omitted entirely.

    Decision #9: missing -> skip (no crash, no fake default). This is
    load-bearing for the scorer, which aligns vectors by intersection
    rather than padding.
    """
    snap = StateSnapshot.from_context(
        timestamp=0,
        homeostasis_summary={"cpu_percent": 5.0, "mode": "ACTIVE"},
        n_active_goals=1,
        # ram_gb missing, error_count_window missing
    )
    # Vector is shorter -- only available features
    assert snap.numeric_vector() == [5.0, 1.0, 0.0]
    # And the audit list reflects exactly that subset
    assert snap.numeric_features_used == [
        "cpu_percent", "n_active_goals", "mode_index",
    ]


def test_from_context_unknown_mode_skips_mode_index():
    snap = StateSnapshot.from_context(
        timestamp=0,
        homeostasis_summary={"cpu_percent": 5.0, "mode": "WAT_TO"},
        n_active_goals=1,
    )
    # mode is preserved verbatim for audit, but mode_index is omitted
    assert snap.mode == "WAT_TO"
    assert "mode_index" not in snap.numeric_features
    assert "mode_index" not in snap.numeric_features_used


def test_from_context_no_homeostasis_summary_safe():
    snap = StateSnapshot.from_context(
        timestamp=0,
        homeostasis_summary=None,
        n_active_goals=0,
    )
    # Only n_active_goals is available
    assert snap.numeric_features_used == ["n_active_goals"]
    assert snap.numeric_vector() == [0.0]
    assert snap.mode is None
    assert snap.last_action_type is None
    assert snap.health_score is None


def test_from_context_no_last_decision_means_none_action():
    snap = StateSnapshot.from_context(
        timestamp=0,
        homeostasis_summary={"mode": "ACTIVE"},
        n_active_goals=1,
        last_decision=None,
    )
    assert snap.last_action_type is None
    assert "last_action" not in snap.semantic_text


# --- mode index mapping ----------------------------------------------


def test_mode_index_mapping_distinct_for_known_modes():
    """All four known modes must map to distinct integers."""
    indices = []
    for mode in ("ACTIVE", "ANALYTICAL", "REDUCED", "SLEEP"):
        snap = StateSnapshot.from_context(
            timestamp=0,
            homeostasis_summary={"mode": mode, "cpu_percent": 0.0},
            n_active_goals=0,
        )
        indices.append(snap.numeric_features["mode_index"])
    assert len(set(indices)) == 4, f"modes collided: {indices}"


def test_mode_index_case_insensitive():
    snap = StateSnapshot.from_context(
        timestamp=0,
        homeostasis_summary={"mode": "active", "cpu_percent": 0.0},
        n_active_goals=0,
    )
    assert "mode_index" in snap.numeric_features


# --- semantic_embedding: DI contract ---------------------------------


def test_semantic_embedding_calls_injected_function_with_text():
    captured = []

    def fake_embed(text: str):
        captured.append(text)
        return [0.1, 0.2, 0.3]

    snap = StateSnapshot.from_context(
        timestamp=0,
        homeostasis_summary={"mode": "ACTIVE"},
        n_active_goals=2,
    )
    vec = snap.semantic_embedding(fake_embed)
    assert vec == [0.1, 0.2, 0.3]
    assert len(captured) == 1
    assert captured[0] == snap.semantic_text


# --- immutability ----------------------------------------------------


def test_snapshot_is_frozen():
    """Snapshots must be immutable so cached references stay trustworthy."""
    import dataclasses

    snap = StateSnapshot.from_context(
        timestamp=0,
        homeostasis_summary={"mode": "ACTIVE"},
        n_active_goals=1,
    )
    try:
        snap.timestamp = 999.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("StateSnapshot must be a frozen dataclass")


# --- extra semantic lines (extension hook) ---------------------------


def test_extra_semantic_lines_appended_in_order():
    snap = StateSnapshot.from_context(
        timestamp=0,
        homeostasis_summary={"mode": "ACTIVE"},
        n_active_goals=1,
        extra_semantic_lines=["pivot=true", "stale_count=3"],
    )
    text = snap.semantic_text
    # Extra lines come after the canonical fields
    idx_mode = text.index("mode=ACTIVE")
    idx_pivot = text.index("pivot=true")
    idx_stale = text.index("stale_count=3")
    assert idx_mode < idx_pivot < idx_stale
