"""Tests for SurpriseBulletinAdapter (B0 output sink, 2026-05-09)."""

import pytest

from agent_core.bulletin.bulletin_model import (
    BulletinEntry,
    EntryStatus,
    EntryType,
)
from agent_core.predictive.bulletin_adapter import (
    REASON_B0_1_ACTION,
    REASON_B0_GLOBAL,
    REQUESTED_BY,
    SurpriseBulletinAdapter,
)


def _make_adapter():
    """Return (adapter, captured_list) -- the list collects posted entries."""
    posted = []
    adapter = SurpriseBulletinAdapter(post_fn=posted.append)
    return adapter, posted


def _b0_global_kwargs(**overrides):
    base = dict(
        semantic_distance=0.42,
        numeric_distance=1.7,
        combined_surprise=0.42,
        source="b0_global",
        numeric_features_used=["cpu_percent", "ram_gb", "mode_index"],
        state_t_summary="mode=ACTIVE active_goals=4",
        state_t1_summary="mode=ACTIVE active_goals=4",
    )
    base.update(overrides)
    return base


def _b0_1_action_kwargs(**overrides):
    base = _b0_global_kwargs(
        source="b0_1_action",
        action_type="learn",
        z_semantic=2.7,
        z_numeric=1.4,
        combined_surprise=2.7,
    )
    base.update(overrides)
    return base


# --- happy paths -----------------------------------------------------


def test_emit_b0_global_posts_entry():
    adapter, posted = _make_adapter()
    entry = adapter.emit_surprise(**_b0_global_kwargs(timestamp=100.0))

    assert len(posted) == 1
    assert posted[0] is entry
    assert isinstance(entry, BulletinEntry)
    assert entry.entry_type == EntryType.SURPRISE
    assert entry.status == EntryStatus.OPEN
    assert entry.requested_by == REQUESTED_BY
    assert entry.reason_code == REASON_B0_GLOBAL
    assert entry.created_at == 100.0
    assert entry.updated_at == 100.0
    assert entry.entry_id.startswith("surp-")


def test_emit_b0_1_action_posts_entry_with_action_topic():
    adapter, posted = _make_adapter()
    entry = adapter.emit_surprise(**_b0_1_action_kwargs(timestamp=200.0))

    assert entry.reason_code == REASON_B0_1_ACTION
    assert "learn" in entry.topic
    assert entry.topic == "surprise:b0_1:learn"


def test_b0_global_topic_is_stable_label():
    adapter, _ = _make_adapter()
    entry = adapter.emit_surprise(**_b0_global_kwargs())
    assert entry.topic == "surprise:b0_global"


# --- payload fidelity -------------------------------------------------


def test_payload_contains_all_required_b0_global_fields():
    """Schema from B0_IMPLEMENTATION_SHORTLIST punkt 6."""
    adapter, _ = _make_adapter()
    entry = adapter.emit_surprise(
        **_b0_global_kwargs(
            timestamp=1234.5,
            episode_id="ep-xyz",
            health_score=0.83,
        )
    )
    p = entry.metadata
    # Raw sub-scores always present
    assert p["semantic_distance"] == 0.42
    assert p["numeric_distance"] == 1.7
    assert p["combined_surprise"] == 0.42
    # B0 global must explicitly carry None for z-scores (not absent)
    assert "z_semantic" in p and p["z_semantic"] is None
    assert "z_numeric" in p and p["z_numeric"] is None
    # Audit context
    assert p["source"] == "b0_global"
    assert p["action_type"] is None
    assert p["numeric_features_used"] == ["cpu_percent", "ram_gb", "mode_index"]
    assert p["health_score"] == 0.83
    assert p["state_t_summary"] == "mode=ACTIVE active_goals=4"
    assert p["state_t1_summary"] == "mode=ACTIVE active_goals=4"
    assert p["timestamp"] == 1234.5
    assert p["episode_id"] == "ep-xyz"


def test_b0_1_action_payload_includes_z_scores_and_action():
    adapter, _ = _make_adapter()
    entry = adapter.emit_surprise(**_b0_1_action_kwargs())
    p = entry.metadata
    assert p["source"] == "b0_1_action"
    assert p["action_type"] == "learn"
    assert p["z_semantic"] == 2.7
    assert p["z_numeric"] == 1.4
    # Raw sub-scores still present (decision #1: never replaced by z-scores)
    assert p["semantic_distance"] == 0.42
    assert p["numeric_distance"] == 1.7


def test_numeric_features_used_is_copied_not_aliased():
    """Mutating the caller's list afterward must not affect the entry."""
    adapter, _ = _make_adapter()
    features = ["cpu_percent", "ram_gb"]
    entry = adapter.emit_surprise(**_b0_global_kwargs(numeric_features_used=features))
    features.append("ram_gb_2")
    assert entry.metadata["numeric_features_used"] == ["cpu_percent", "ram_gb"]


def test_health_score_default_is_none():
    adapter, _ = _make_adapter()
    entry = adapter.emit_surprise(**_b0_global_kwargs())
    assert entry.metadata["health_score"] is None


def test_episode_id_default_is_none():
    adapter, _ = _make_adapter()
    entry = adapter.emit_surprise(**_b0_global_kwargs())
    assert entry.metadata["episode_id"] is None


# --- summary text ----------------------------------------------------


def test_summary_b0_global_mentions_distances():
    adapter, _ = _make_adapter()
    entry = adapter.emit_surprise(**_b0_global_kwargs())
    s = entry.summary
    assert "Global surprise" in s
    assert "0.42" in s
    assert "0.420" in s or "0.42" in s
    assert "1.7" in s


def test_summary_b0_1_action_mentions_action_name():
    adapter, _ = _make_adapter()
    entry = adapter.emit_surprise(**_b0_1_action_kwargs())
    assert "learn" in entry.summary
    assert "Action-aware surprise" in entry.summary


# --- validation ------------------------------------------------------


def test_invalid_source_raises():
    adapter, _ = _make_adapter()
    with pytest.raises(ValueError, match="source"):
        adapter.emit_surprise(**_b0_global_kwargs(source="b0_random"))


def test_b0_1_action_without_action_type_raises():
    adapter, _ = _make_adapter()
    kwargs = _b0_1_action_kwargs()
    kwargs["action_type"] = None
    with pytest.raises(ValueError, match="action_type"):
        adapter.emit_surprise(**kwargs)


def test_b0_1_action_without_z_semantic_raises():
    adapter, _ = _make_adapter()
    kwargs = _b0_1_action_kwargs()
    kwargs["z_semantic"] = None
    with pytest.raises(ValueError):
        adapter.emit_surprise(**kwargs)


def test_b0_1_action_without_z_numeric_raises():
    adapter, _ = _make_adapter()
    kwargs = _b0_1_action_kwargs()
    kwargs["z_numeric"] = None
    with pytest.raises(ValueError):
        adapter.emit_surprise(**kwargs)


# --- entry serialization roundtrip (SURPRISE enum coverage) ----------


def test_surprise_entry_serializes_and_deserializes():
    """SURPRISE enum survives BulletinEntry.to_dict/from_dict cycle."""
    adapter, _ = _make_adapter()
    entry = adapter.emit_surprise(**_b0_global_kwargs(timestamp=42.0))
    d = entry.to_dict()
    assert d["entry_type"] == "surprise"
    rebuilt = BulletinEntry.from_dict(d)
    assert rebuilt.entry_type == EntryType.SURPRISE
    assert rebuilt.entry_id == entry.entry_id
    assert rebuilt.metadata["semantic_distance"] == 0.42


# --- integration: post_fn injection contract -------------------------


def test_post_fn_is_called_exactly_once():
    """A successful emit calls post_fn once; no retries, no duplicate posts."""
    calls = {"count": 0}

    def counting_post(entry):
        calls["count"] += 1

    adapter = SurpriseBulletinAdapter(post_fn=counting_post)
    adapter.emit_surprise(**_b0_global_kwargs())
    assert calls["count"] == 1
