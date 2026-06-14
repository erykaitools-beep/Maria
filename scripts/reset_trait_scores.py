#!/usr/bin/env python3
"""Reset trait_scores in consciousness_identity.json to catalog defaults.

Background: pre-C6 (2026-04-25) trait scoring received a firehose of
``session_completed`` / ``greeting_generated`` signals, saturating
``systematyczna`` / ``refleksyjna`` / ``spoleczna`` to 1.0 while traits
that lacked any source decayed toward 0. After C6 wired the missing
signals, the historical scores are misleading — every value is either
saturated or decay-only.

This script resets ``trait_scores`` to ``initial_score`` from the
catalog so the next 7d of evolution shows real signal. Other identity
fields (birth, sessions, summary) are preserved.

The change only takes effect after Maria restarts: ConsciousnessCore
loads the file at init and overwrites it from in-memory state on every
checkpoint. Run this BEFORE a restart, or restart immediately after.

Usage:
    python3 scripts/reset_trait_scores.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_PATH = ROOT / "meta_data" / "consciousness_identity.json"

# Allow running from anywhere — agent_core lives at project root.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset trait_scores to catalog defaults")
    parser.add_argument("--dry-run", action="store_true", help="show diff, do not write")
    args = parser.parse_args()

    if not IDENTITY_PATH.exists():
        print(f"ERROR: {IDENTITY_PATH} not found", file=sys.stderr)
        return 1

    from agent_core.consciousness.trait_catalog import TRAIT_CATALOG

    with open(IDENTITY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    old_scores = data.get("trait_scores", {})
    new_scores = {}
    for trait_name, trait_def in TRAIT_CATALOG.items():
        new_scores[trait_name] = {
            "score": float(trait_def["initial_score"]),
            "evidence_count": 0,
            "last_updated": "",
        }

    print("Trait reset preview:")
    print(f"{'Trait':<16} {'Old score':>10} {'Old evid':>10} -> {'New score':>10} {'New evid':>10}")
    print("-" * 64)
    for trait, new in new_scores.items():
        old = old_scores.get(trait, {})
        print(
            f"{trait:<16} {old.get('score', 0):>10.4f} {old.get('evidence_count', 0):>10} "
            f"-> {new['score']:>10.4f} {new['evidence_count']:>10}"
        )

    if args.dry_run:
        print("\n--dry-run set; nothing written.")
        return 0

    backup_path = IDENTITY_PATH.with_suffix(
        f".bak-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    shutil.copy2(IDENTITY_PATH, backup_path)
    print(f"\nBackup written to {backup_path}")

    data["trait_scores"] = new_scores
    with open(IDENTITY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"trait_scores reset in {IDENTITY_PATH}")
    print(
        "\nIMPORTANT: restart Maria for the reset to take effect "
        "(ConsciousnessCore overwrites this file on every checkpoint)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
