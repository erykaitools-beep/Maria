#!/usr/bin/env python3
"""Schedule the D4 7d-soak recheck reminder.

Adds a one-shot reminder for 2026-05-03 09:00 Europe/Berlin that fires
``scripts/verify_d4.py`` via the new on_fire_command path and pipes
the verdict back via Telegram + REPL channels. Idempotent — uses a
stable ``external_id`` and skips if a matching reminder already lives
in the store.

Usage:
    venv/bin/python scripts/schedule_d4_recheck.py            # dry-run
    venv/bin/python scripts/schedule_d4_recheck.py --commit   # actually add
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_core.reminders.reminder_model import Reminder  # noqa: E402
from agent_core.reminders.reminder_store import ReminderStore  # noqa: E402


EXTERNAL_ID = "d4-recheck-2026-05-03"
SCHEDULED_AT_BERLIN = datetime(2026, 5, 3, 9, 0, 0, tzinfo=ZoneInfo("Europe/Berlin"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually persist to the store. Without this flag, dry-run only.",
    )
    args = parser.parse_args()

    ts = SCHEDULED_AT_BERLIN.timestamp()
    text = (
        "D4 7d-soak recheck — pelny 7d od deploy 2026-04-26. "
        "Maria sama odpali verify_d4.py i posle verdict ponizej."
    )
    cmd = {
        "argv": [str(ROOT / "venv" / "bin" / "python"), "scripts/verify_d4.py"],
        "cwd": str(ROOT),
        "timeout": 60,
    }

    rem = Reminder(
        text=text,
        scheduled_at=ts,
        notify_telegram=True,
        metadata={
            "on_fire_command": cmd,
            "external_id": EXTERNAL_ID,
            "context": "D4 full 7d soak verification (D_BOARDS PASS-A early check on 2026-04-28)",
        },
    )

    print("Reminder spec:")
    print(f"  id (will assign):  {rem.id}")
    print(f"  text:              {rem.text}")
    print(f"  scheduled_at:      {SCHEDULED_AT_BERLIN.isoformat()}  (= {ts:.0f} unix)")
    print(f"  on_fire_command:   {cmd}")
    print(f"  external_id:       {EXTERNAL_ID}")

    if not args.commit:
        print("\n(dry-run; pass --commit to actually add)")
        return 0

    store = ReminderStore()
    for existing in store.get_all():
        meta = existing.metadata or {}
        if meta.get("external_id") == EXTERNAL_ID:
            print(
                f"\nAlready in store: {existing.id} "
                f"(status={existing.status.value}). Skipping."
            )
            return 0

    added = store.add(rem)
    print(f"\nAdded reminder {added.id} to meta_data/reminders.jsonl.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
