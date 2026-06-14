#!/usr/bin/env python3
"""One-time cleanup for orphan escalated_to_goal tags (2026-05-06).

A bug in BulletinEscalator (fixed in commit 2655e63) caused
GoalStore.propose() to mark goals dirty without persisting them.
When the process exited, the goals were lost but the bulletin entries
kept their escalated_to_goal tags pointing to non-existent goal IDs.

This script finds bulletin entries whose escalated_to_goal references
a goal that does NOT exist in goals.jsonl and removes those tags so
the entries become eligible for re-escalation by the (now fixed)
escalator on the next tick.

The cleanup uses MERGE semantics: tag-less entries are _appended back
to cognitive_bulletin.jsonl. On next BulletinStore load, the latest
record per entry_id wins, so the tag-less version supersedes the
orphaned one. The running daemon's in-memory state is NOT modified —
restart is required for the daemon to pick up the cleanup.

Usage:
    python3 scripts/cleanup_escalator_orphan_tags.py            # dry-run
    python3 scripts/cleanup_escalator_orphan_tags.py --apply    # write
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_core.bulletin.bulletin_store import BulletinStore  # noqa: E402
from agent_core.goals.store import GoalStore  # noqa: E402

BULLETIN_PATH = ROOT / "meta_data" / "cognitive_bulletin.jsonl"
GOALS_PATH = ROOT / "meta_data" / "goals.jsonl"


def find_orphan_tags(
    bulletin: BulletinStore, goals: GoalStore
) -> List[tuple]:
    """Return [(entry_id, orphan_goal_id, topic), ...] for orphan tags."""
    bulletin._ensure_loaded()
    assert bulletin._entries is not None

    known_goal_ids = {g.id for g in goals.get_all()}
    orphans = []
    for entry in bulletin._entries.values():
        tag = entry.metadata.get("escalated_to_goal")
        if not tag:
            continue
        if tag not in known_goal_ids:
            orphans.append((entry.entry_id, tag, entry.topic[:60]))
    return orphans


def cleanup_orphan(
    bulletin: BulletinStore, entry_id: str
) -> bool:
    """Remove escalated_to_goal tag and re-append entry. Returns True on success."""
    assert bulletin._entries is not None
    entry = bulletin._entries.get(entry_id)
    if entry is None:
        return False
    if "escalated_to_goal" not in entry.metadata:
        return False
    del entry.metadata["escalated_to_goal"]
    entry.updated_at = time.time()
    bulletin._append(entry)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write tag-less entries (default: dry-run)",
    )
    args = parser.parse_args()

    bulletin = BulletinStore(path=BULLETIN_PATH)
    goals = GoalStore(GOALS_PATH)
    goals.load()

    print(f"[INFO] Loaded {len(goals.get_all())} goals from {GOALS_PATH.name}")
    bulletin._ensure_loaded()
    print(f"[INFO] Loaded {len(bulletin._entries or {})} entries from {BULLETIN_PATH.name}")

    orphans = find_orphan_tags(bulletin, goals)
    if not orphans:
        print("[OK] No orphan tags found.")
        return 0

    # Group orphans by goal_id for readable output
    by_goal: Dict[str, List[tuple]] = {}
    for entry_id, gid, topic in orphans:
        by_goal.setdefault(gid, []).append((entry_id, topic))

    print(f"\n[FOUND] {len(orphans)} orphan tags across {len(by_goal)} goal IDs:")
    for gid, items in by_goal.items():
        print(f"  goal {gid} (NOT in goals.jsonl): {len(items)} entries")
        for entry_id, topic in items[:3]:
            print(f"    - {entry_id[:12]}... topic: {topic!r}")
        if len(items) > 3:
            print(f"    ... and {len(items) - 3} more")

    if not args.apply:
        print("\n[DRY-RUN] Re-run with --apply to remove orphan tags.")
        print("[DRY-RUN] Daemon restart required for cleanup to take effect.")
        return 0

    print(f"\n[APPLY] Removing orphan tags from {len(orphans)} entries...")
    removed = 0
    for entry_id, _, _ in orphans:
        if cleanup_orphan(bulletin, entry_id):
            removed += 1
    print(f"[APPLY] Removed {removed}/{len(orphans)} tags.")
    print("[APPLY] Daemon restart required for in-memory state to refresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
