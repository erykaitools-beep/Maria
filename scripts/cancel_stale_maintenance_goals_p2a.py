"""One-time cleanup: cancel 6 stale maintenance goals from 2026-05-06 escalator.

Context (P2a fix, 2026-05-08):
The plain MAINTENANCE action handler is a NO-OP — it returns success without
doing anything substantive. This caused 6 escalator-created goals to be stuck
in PENDING forever, because every "maintenance" run just bumped progress
by 0 while K12 kept emitting "100% failure" advisory.

Planner mapping fix in this commit reroutes maintenance goals to real action
handlers (LEARN/REVIEW/EVALUATE/VALIDATE) based on theme_tag. But the existing
6 goals were created BEFORE the fix, so cancel them; the next escalator fire
(every 1800 ticks ~30 min) will recreate them with the new mapping.

USAGE:
    sudo systemctl stop maria
    cd /home/maria/maria && ./venv/bin/python scripts/cancel_stale_maintenance_goals_p2a.py
    sudo systemctl start maria

DO NOT run while maria is live (race on goals.jsonl).
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import GoalStatus

STALE_GOAL_IDS = {
    "goal-3c4a5a0ec3af": "learn_failures",
    "goal-f1001fda16ea": "passive_drift",
    "goal-eeee247b571d": "retention_low",
    "goal-0e748582a46d": "skip_overuse",
    "goal-f0cda78285f0": "stale_goals",
    "goal-146cb181be21": "validate_failures",
}

REASON = "P2a maintenance NO-OP cleanup; escalator will recreate with new theme→action mapping"
ACTOR = "operator"


def main() -> int:
    goals_path = Path("/home/maria/maria/meta_data/goals.jsonl")
    if not goals_path.exists():
        print(f"ERROR: {goals_path} not found", file=sys.stderr)
        return 1

    store = GoalStore(goals_path)
    store.load()

    cancelled = 0
    skipped = 0
    not_found = 0

    for gid, expected_theme in STALE_GOAL_IDS.items():
        goal = store._goals.get(gid)
        if goal is None:
            print(f"  [skip] {gid} ({expected_theme}) — not found in store")
            not_found += 1
            continue

        if goal.status in {GoalStatus.CANCELLED, GoalStatus.ABANDONED, GoalStatus.ACHIEVED, GoalStatus.FAILED}:
            print(f"  [skip] {gid} ({expected_theme}) — already terminal: {goal.status.value}")
            skipped += 1
            continue

        actual_theme = (goal.metadata or {}).get("theme_tag", "?")
        if actual_theme != expected_theme:
            print(f"  [warn] {gid} theme mismatch: expected={expected_theme}, actual={actual_theme}")

        ok = store.update_status(gid, GoalStatus.CANCELLED, REASON, ACTOR)
        if ok:
            print(f"  [cancel] {gid} ({actual_theme}) — was {goal.status.value}")
            cancelled += 1
        else:
            print(f"  [error] {gid} update_status failed")

    store.save()
    print()
    print(f"Done: cancelled={cancelled}, skipped_terminal={skipped}, not_found={not_found}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
