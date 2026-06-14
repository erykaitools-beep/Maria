#!/usr/bin/env python3
"""One-shot JSONL compaction utility for runtime stores.

Usage:
    python scripts/compact_jsonl.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
META_DIR = ROOT / "meta_data"


@dataclass
class CompactResult:
    file_name: str
    before: int
    after: int

    @property
    def saved(self) -> int:
        return max(0, self.before - self.after)


def _read_nonempty_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line for line in f if line.strip()]


def _atomic_write_lines(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    tmp_path.replace(path)


def _compact_merge(path: Path, key_field: str) -> CompactResult:
    lines = _read_nonempty_lines(path)
    merged: Dict[str, str] = {}
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = record.get(key_field)
        if not key:
            continue
        merged[str(key)] = json.dumps(record, ensure_ascii=False) + "\n"

    out_lines = list(merged.values())
    _atomic_write_lines(path, out_lines)
    return CompactResult(file_name=path.name, before=len(lines), after=len(out_lines))


def _truncate_tail(path: Path, keep_last: int) -> CompactResult:
    lines = _read_nonempty_lines(path)
    out_lines = lines[-keep_last:] if keep_last >= 0 else lines
    _atomic_write_lines(path, out_lines)
    return CompactResult(file_name=path.name, before=len(lines), after=len(out_lines))


def main() -> int:
    tasks: List[Tuple[str, CompactResult]] = []

    tasks.append((
        "goals merge by id",
        _compact_merge(META_DIR / "goals.jsonl", key_field="id"),
    ))
    tasks.append((
        "beliefs merge by belief_id",
        _compact_merge(META_DIR / "beliefs.jsonl", key_field="belief_id"),
    ))
    tasks.append((
        "web fetch registry merge by url",
        _compact_merge(META_DIR / "web_fetch_registry.jsonl", key_field="url"),
    ))
    tasks.append((
        "critique reports keep last 200",
        _truncate_tail(META_DIR / "critique_reports.jsonl", keep_last=200),
    ))
    tasks.append((
        "decision traces keep last 500",
        _truncate_tail(META_DIR / "decision_traces.jsonl", keep_last=500),
    ))

    total_before = sum(res.before for _, res in tasks)
    total_after = sum(res.after for _, res in tasks)
    total_saved = sum(res.saved for _, res in tasks)

    print("JSONL compaction report")
    print("=" * 60)
    for label, res in tasks:
        print(
            f"- {label}: {res.file_name} | "
            f"before={res.before}, after={res.after}, saved={res.saved}"
        )
    print("-" * 60)
    print(f"TOTAL: before={total_before}, after={total_after}, saved={total_saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
