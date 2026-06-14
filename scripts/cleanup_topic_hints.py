#!/usr/bin/env python3
"""One-time cleanup for meta_data/topic_hints.jsonl backlog (R2.1, 2026-04-29).

Before R2.1's filter+lifecycle landed, K12 self-analysis appended every
recommendation as a pending hint without quality filtering or deduplication.
By 2026-04-28 the file held ~199 pending entries, only ~30-40 were genuinely
wikipedia-searchable, the rest were architecture-meta strings like
"Obsługa błędów i fallback dla akcji 'learn'" or three near-duplicate variants
of the same topic. Wikipedia search returned 0 for all of them, the fetcher
spammed `saturation_meta_fetch` ~30x/day wasting 17s/cycle.

This script applies the production filter+dedup retroactively to the existing
jsonl so the runtime starts with a clean queue. New hints written by the
patched RecommendationApplier are already filtered+deduped at write time.

Usage:
    python3 scripts/cleanup_topic_hints.py            # dry-run (default)
    python3 scripts/cleanup_topic_hints.py --apply    # overwrite jsonl
                                                      # (.bak created first)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
HINTS_PATH = ROOT / "meta_data" / "topic_hints.jsonl"

sys.path.insert(0, str(ROOT))
from agent_core.self_analysis.recommendation_applier import (  # noqa: E402
    _is_searchable_topic,
)


def _display_path(path: Path) -> str:
    """Show path relative to ROOT when possible, else absolute."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_hints(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def cleanup(hints: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Apply quality filter + dedup to pending hints.

    Already-consumed hints pass through untouched (audit trail). For pending
    hints: reject unsearchable shapes, then keep the highest-priority entry
    per lowercase-stripped topic. Rejected entries become consumed=True with
    a reason, so the audit trail explains why they're no longer suggested.
    """
    stats = {
        "total": len(hints),
        "already_consumed": 0,
        "filtered_unsearchable": 0,
        "deduplicated": 0,
        "kept_pending": 0,
    }

    # Pass 1: split consumed (preserve as-is) vs pending (cleanup candidates)
    consumed: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    for h in hints:
        if h.get("consumed", False):
            consumed.append(h)
            stats["already_consumed"] += 1
        else:
            pending.append(h)

    # Pass 2: filter unsearchable shapes
    now = time.time()
    survivors: List[Dict[str, Any]] = []
    for h in pending:
        topic = h.get("topic", "")
        if not _is_searchable_topic(topic):
            h["consumed"] = True
            h["consumed_reason"] = "filter_unsearchable_2026-04-29"
            h["consumed_at"] = now
            consumed.append(h)
            stats["filtered_unsearchable"] += 1
        else:
            survivors.append(h)

    # Pass 3: dedup by lowercase topic, keep highest priority
    by_topic: Dict[str, Dict[str, Any]] = {}
    for h in survivors:
        key = (h.get("topic") or "").lower().strip()
        existing = by_topic.get(key)
        if existing is None or h.get("priority", 0) > existing.get("priority", 0):
            if existing is not None:
                existing["consumed"] = True
                existing["consumed_reason"] = "dedup_lower_priority_2026-04-29"
                existing["consumed_at"] = now
                consumed.append(existing)
                stats["deduplicated"] += 1
            by_topic[key] = h
        else:
            h["consumed"] = True
            h["consumed_reason"] = "dedup_lower_priority_2026-04-29"
            h["consumed_at"] = now
            consumed.append(h)
            stats["deduplicated"] += 1

    kept = list(by_topic.values())
    stats["kept_pending"] = len(kept)

    # Final order: consumed first (chronological by audit), pending last
    return consumed + kept, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Overwrite topic_hints.jsonl in place. A .bak copy is written first.",
    )
    parser.add_argument(
        "--path", type=Path, default=HINTS_PATH,
        help=f"Hints file (default: {_display_path(HINTS_PATH)})",
    )
    args = parser.parse_args()

    if not args.path.exists():
        print(f"No file at {args.path} — nothing to clean.")
        return 0

    hints = load_hints(args.path)
    new_hints, stats = cleanup(hints)

    print("=" * 64)
    print(f"R2.1 hint cleanup — {_display_path(args.path)}")
    print("=" * 64)
    print(f"  Total entries:           {stats['total']}")
    print(f"  Already consumed:        {stats['already_consumed']}")
    print(f"  Filtered (unsearchable): {stats['filtered_unsearchable']}")
    print(f"  Deduplicated:            {stats['deduplicated']}")
    print(f"  Kept pending:            {stats['kept_pending']}")
    print("=" * 64)

    if not args.apply:
        print("DRY-RUN — no files modified. Re-run with --apply to write.")
        # Show top kept-pending so operator can sanity-check
        kept_pending = [h for h in new_hints if not h.get("consumed", False)]
        kept_pending.sort(key=lambda x: x.get("priority", 0), reverse=True)
        print("\nTop 10 kept (would survive cleanup):")
        for h in kept_pending[:10]:
            print(f"  {h.get('priority',0):.2f}  {h.get('topic','?')[:60]}")
        return 0

    # Apply: backup then overwrite
    backup = args.path.with_suffix(args.path.suffix + ".bak")
    shutil.copy2(args.path, backup)
    print(f"Backup: {_display_path(backup)}")

    tmp = args.path.with_suffix(args.path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for h in new_hints:
            f.write(json.dumps(h, ensure_ascii=False) + "\n")
    tmp.replace(args.path)

    print(f"Wrote {len(new_hints)} entries to {_display_path(args.path)}")
    print(f"  ({stats['kept_pending']} pending, "
          f"{len(new_hints) - stats['kept_pending']} consumed/audit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
