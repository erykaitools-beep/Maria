"""Held-out bank author (Option C / C1, 2026-07-12).

Authors frozen answer-key rows for freshly fetched market files at the FETCH
seam -- BEFORE the student ever sees the material. The key is then immutable
and grading is mechanical (exam_agent.grade_heldout), so the exam's verdict
cannot drift toward whoever authored the questions: the author LLM never
grades, and the grader is not an LLM at all.

Scope: ONLY goals with metadata verification_mode='heldout' get bank rows --
never bare market provenance (red-team 2026-07-11 CRITICAL #2: authoring
Kronika's pantry would have armed the mechanical grader for her files).

Two call sites:
  * make_fetch_handler -- right after stamp_market_provenance, best-effort,
    capped at MAX_FILES_PER_BATCH files per fetch (tick-duration bound);
  * planner B4 coverage peek -- backfills ONE missing file per scan, so files
    beyond the fetch-seam cap still get covered (no coverage hole).

Author model policy: NIM-ONLY, no local fallback. Authoring is retryable (the
B4 backfill runs again after the goal's cooldown), so a NIM outage just delays
coverage -- while a local qwen3 fallback would stall the synchronous tick for
minutes under the heavy mutex for a task that can simply wait. This is a
deliberate deviation from the exam-path examiner factory (which MUST answer
now and therefore falls back).

Flag: HELDOUT_BANK_AUTHOR_ENABLED, read AT CALL TIME (the ".env leaks into
tests" lesson -- import-time reads freeze a polluted value).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BANK_VERSION = "v3"
TARGET_ROWS_PER_FILE = 5
# Mirrors exam_agent.HELDOUT_MIN_BANK_ROWS (import avoided at module import
# time to keep this module cheap; validated equal in tests).
MIN_ROWS_PER_FILE = 3
# Tick-duration bound: authoring runs inside the synchronous tick (fetch
# handler / planner phase); each file is one NIM call (<= NIM_AUTHOR_TIMEOUT).
MAX_FILES_PER_BATCH = 3
NIM_AUTHOR_TIMEOUT = 90
# Source bodies shorter than this carry too little to author 3 grounded rows.
MIN_SOURCE_CHARS = 300
# Prompt cap: validation always runs against the FULL source; only the prompt
# excerpt is capped (NIM input cost + focus).
PROMPT_SOURCE_MAX_CHARS = 8000

_ALLOWED_MATCH = {"contains", "exact", "numeric"}
_BANK_LOCK = threading.Lock()

PROMPT_AUTHOR_BANK = """Jestes egzaminatorem przygotowujacym bank pytan kontrolnych.
Na podstawie PONIZSZEGO TEKSTU ZRODLOWEGO przygotuj {num_rows} pytan z zamknietym kluczem odpowiedzi.

ZASADY (scisle):
- Odpowiedz kanoniczna ("canonical") MUSI byc krotkim faktem wystepujacym DOSLOWNIE w tekscie: nazwa, termin, liczba, nazwisko (1-4 slowa).
- Odpowiedz NIE MOZE pojawiac sie w tresci pytania.
- Dla liczb: "match": "numeric", "canonical" = sama liczba, "tolerance" = ok. 0.5% wartosci (0 dla malych liczb calkowitych).
- Dla faktow tekstowych: "match": "contains".
- Pytania o NAJWAZNIEJSZE fakty tekstu, kazde o inny fakt.

TEKST ZRODLOWY:
--------------------
{source}
--------------------

Odpowiedz w JSON (bez markdown):
{{"rows": [
  {{"q": "pytanie o fakt tekstowy?", "match": "contains", "canonical": "krotki fakt"}},
  {{"q": "pytanie o liczbe?", "match": "numeric", "canonical": "68250", "tolerance": 300}}
]}}"""


def author_enabled() -> bool:
    """Call-time flag read; default OFF."""
    return os.environ.get(
        "HELDOUT_BANK_AUTHOR_ENABLED", ""
    ).strip().lower() in {"1", "true", "yes", "on"}


def _is_heldout_goal(goal) -> bool:
    meta = getattr(goal, "metadata", None) or {}
    return str(meta.get("verification_mode") or "").strip().lower() == "heldout"


def source_body_path(file_id: str, input_dir: Optional[Path] = None) -> Path:
    if input_dir is None:
        from maria_core.sys.config import INPUT_DIR
        input_dir = INPUT_DIR
    return Path(input_dir) / file_id


def compute_source_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()[:16]


def _default_bank_path() -> Path:
    from maria_core.sys.config import HELDOUT_BANK
    return Path(HELDOUT_BANK)


def _existing_rows(file_id: str, shash: str, bank_path: Path) -> List[Dict[str, Any]]:
    from maria_core.learning.exam_agent import load_heldout_bank
    return [
        r for r in load_heldout_bank(bank_path)
        if (r.get("file") or r.get("file_id")) == file_id
        and r.get("source_hash") == shash
    ]


def validate_row(
    row: Dict[str, Any], source_text: str, file_id: str,
) -> Tuple[bool, str]:
    """Mechanical acceptance check for ONE authored row (fail -> drop).

    Guards the degenerate-row classes the red-team called out: answer leaked in
    the question, trivially-matchable short canonicals, file-stem tokens (any
    on-topic sentence contains them), facts not grounded in the source, and
    numeric rows without an explicit tolerance.
    """
    from maria_core.learning.exam_agent import (
        _normalize_match_text, _all_numbers, _first_number,
    )

    if not isinstance(row, dict):
        return False, "not a dict"
    match = str(row.get("match") or "contains").strip().lower()
    if match not in _ALLOWED_MATCH:
        # The author must not emit regex (too easy to author an always-match);
        # regex rows remain valid in the bank only when a human wrote them.
        return False, f"match '{match}' not allowed for authored rows"
    q = str(row.get("q") or "").strip()
    if len(q) < 10:
        return False, "question too short"
    canonical = str(row.get("canonical") or "").strip()
    if not canonical:
        return False, "missing canonical"

    norm_canonical = _normalize_match_text(canonical)
    norm_q = _normalize_match_text(q)
    norm_source = _normalize_match_text(source_text)

    if match in ("contains", "exact"):
        if len(norm_canonical) < 4:
            return False, "canonical too short (trivially matchable)"
        if norm_canonical in norm_q:
            return False, "answer leaked in question text"
        stem_tokens = {
            t for t in _normalize_match_text(
                Path(file_id).stem.replace("_", " ")
            ).split() if len(t) > 3
        }
        if norm_canonical in stem_tokens:
            return False, "canonical is a file-stem token"
        if norm_canonical not in norm_source:
            return False, "canonical not grounded in source"
        return True, "ok"

    # numeric
    value = _first_number(canonical)
    if value is None:
        return False, "numeric canonical does not parse"
    # Year-shaped canonicals are trivially passable: concise answers open with
    # dates, and ANY-number matching (C10) means every answer quoting a date
    # passes a year row with zero knowledge (diff-review 2026-07-12).
    if 1900 <= value <= 2100 and float(value).is_integer():
        return False, "year-shaped canonical (trivially parroted)"
    tolerance = row.get("tolerance")
    try:
        tolerance = float(tolerance)
    except (TypeError, ValueError):
        return False, "numeric row without explicit tolerance"
    if tolerance < 0:
        return False, "negative tolerance"
    if tolerance == 0 and abs(value) >= 1000:
        # Prices/large quantities get paraphrased ("okolo 68 tys.") -- a zero
        # tolerance turns every such row into a chronic false-FAIL.
        return False, "price-shaped value requires tolerance > 0"
    if not any(abs(n - value) <= tolerance for n in _all_numbers(source_text)):
        return False, "numeric value not grounded in source"
    return True, "ok"


def _parse_author_response(response: str) -> List[Dict[str, Any]]:
    from maria_core.learning.llm_utils import extract_json_from_response
    parsed = extract_json_from_response(response, expected_keys={"rows"})
    rows = parsed.get("rows") if isinstance(parsed, dict) else None
    return rows if isinstance(rows, list) else []


def _make_nim_author_fn() -> Optional[Tuple[Any, str]]:
    """(callable, model_name) on a configured NIM, else None. NIM-only."""
    try:
        from maria_core.sys.config import (
            NVIDIA_NIM_API_KEY, NVIDIA_NIM_MODEL, NVIDIA_NIM_BASE_URL,
        )
        if not NVIDIA_NIM_API_KEY:
            return None
        from agent_core.llm.nim_client import NIMClient
        nim = NIMClient(
            api_key=NVIDIA_NIM_API_KEY,
            model=NVIDIA_NIM_MODEL,
            base_url=NVIDIA_NIM_BASE_URL or None,
            timeout=NIM_AUTHOR_TIMEOUT,
            system_prompt=(
                "Jestes precyzyjnym egzaminatorem. "
                "Zwracasz WYLACZNIE poprawny JSON, bez komentarzy."
            ),
        )
    except Exception as exc:  # construction guard -- authoring just waits
        logger.warning("[BANK-AUTHOR] NIM unavailable (%s); skipping", exc)
        return None

    def _run(prompt: str) -> str:
        return nim._ask_once(
            prompt, temperature=0.3, max_tokens=4096, force_json=True,
        )

    return _run, f"nim:{nim.model}"


def _append_rows(rows: List[Dict[str, Any]], bank_path: Path) -> int:
    """Append rows, one JSON line per single O_APPEND write, under a lock.

    load_heldout_bank re-reads the file uncached on every exam and skips torn
    lines; a whole-line single write keeps a concurrent reader from ever seeing
    a half row (the in-process lock serializes our own two author seams).
    """
    written = 0
    with _BANK_LOCK:
        fd = os.open(
            str(bank_path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644,
        )
        try:
            for row in rows:
                line = json.dumps(row, ensure_ascii=False) + "\n"
                os.write(fd, line.encode("utf-8"))
                written += 1
        finally:
            os.close(fd)
    return written


def author_rows_for_file(
    file_id: str,
    *,
    author_fn=None,
    author_model: str = "unknown",
    input_dir: Optional[Path] = None,
    bank_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Author + validate + append bank rows for ONE fetched file.

    Idempotent on (file, source_hash): if the bank already holds >= MIN rows
    for the CURRENT body, this is a no-op (re-fetch/feed-rot safe). Existing
    rows below the minimum are topped up with q-deduped new rows. Never raises.
    """
    bank_path = bank_path or _default_bank_path()
    try:
        body_path = source_body_path(file_id, input_dir)
        try:
            body = body_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"file": file_id, "written": 0,
                    "skipped": f"source unreadable: {exc}"}
        if len(body) < MIN_SOURCE_CHARS:
            return {"file": file_id, "written": 0, "skipped": "source too short"}
        shash = compute_source_hash(body)

        existing = _existing_rows(file_id, shash, bank_path)
        if len(existing) >= MIN_ROWS_PER_FILE:
            return {"file": file_id, "written": 0, "skipped": "already covered",
                    "existing": len(existing)}

        if author_fn is None:
            made = _make_nim_author_fn()
            if made is None:
                return {"file": file_id, "written": 0, "skipped": "nim_unavailable"}
            author_fn, author_model = made

        prompt = PROMPT_AUTHOR_BANK.format(
            num_rows=TARGET_ROWS_PER_FILE,
            source=body[:PROMPT_SOURCE_MAX_CHARS],
        )
        try:
            response = author_fn(prompt)
        except Exception as exc:
            logger.warning("[BANK-AUTHOR] author call failed for %s: %s",
                           file_id, exc)
            return {"file": file_id, "written": 0, "skipped": f"author failed: {exc}"}

        candidates = _parse_author_response(response or "")
        from maria_core.learning.exam_agent import _normalize_match_text
        seen_q = {
            _normalize_match_text(str(r.get("q") or "")) for r in existing
        }
        now = time.time()
        accepted: List[Dict[str, Any]] = []
        for cand in candidates:
            ok, reason = validate_row(cand, body, file_id)
            if not ok:
                logger.info("[BANK-AUTHOR] row dropped (%s): %s",
                            reason, str(cand)[:120])
                continue
            norm_q = _normalize_match_text(str(cand.get("q")))
            if norm_q in seen_q:
                continue
            seen_q.add(norm_q)
            row = {
                "file": file_id,
                "q": str(cand.get("q")).strip(),
                "match": str(cand.get("match") or "contains").strip().lower(),
                "canonical": str(cand.get("canonical")).strip(),
                "bank_version": BANK_VERSION,
                "author_model": author_model,
                "created_at": now,
                "source_hash": shash,
            }
            if row["match"] == "numeric":
                row["tolerance"] = float(cand.get("tolerance"))
            accepted.append(row)
            if len(existing) + len(accepted) >= TARGET_ROWS_PER_FILE:
                break

        if not accepted:
            logger.warning(
                "[BANK-AUTHOR] 0 valid rows authored for %s "
                "(%d candidates, %d already banked)",
                file_id, len(candidates), len(existing),
            )
            return {"file": file_id, "written": 0, "skipped": "no valid rows"}

        written = _append_rows(accepted, bank_path)
        total = len(existing) + written
        level = logger.info if total >= MIN_ROWS_PER_FILE else logger.warning
        level(
            "[BANK-AUTHOR] %s: +%d rows (total %d for source %s)%s",
            file_id, written, total, shash,
            "" if total >= MIN_ROWS_PER_FILE else " -- BELOW exam minimum",
        )
        return {"file": file_id, "written": written, "total": total,
                "source_hash": shash}
    except Exception as exc:  # belt: the fetch/planner path must never break
        logger.warning("[BANK-AUTHOR] unexpected error for %s: %s", file_id, exc)
        return {"file": file_id, "written": 0, "skipped": f"error: {exc}"}


def author_bank_for_goal(
    goal,
    fetched_files,
    *,
    core=None,
    input_dir: Optional[Path] = None,
    bank_path: Optional[Path] = None,
    author_fn=None,
    author_model: str = "unknown",
) -> Dict[str, Any]:
    """Fetch-seam entry: author rows for a heldout-mode goal's fresh files.

    Best-effort and bounded: at most MAX_FILES_PER_BATCH files per call (each
    one NIM call <= NIM_AUTHOR_TIMEOUT); files beyond the cap are logged and
    left to the planner B4 backfill. ``core`` (when given) provides
    external_op_lease so the tick watchdog knows the stall is intentional.
    """
    if not author_enabled():
        return {"skipped": "flag_off"}
    if goal is None or not _is_heldout_goal(goal):
        return {"skipped": "not_heldout_goal"}
    files = [f for f in (fetched_files or []) if f]
    if not files:
        return {"skipped": "no_files"}
    batch, deferred = files[:MAX_FILES_PER_BATCH], files[MAX_FILES_PER_BATCH:]
    if deferred:
        logger.warning(
            "[BANK-AUTHOR] goal %s: %d files beyond the per-fetch cap -- "
            "left to B4 backfill: %s",
            getattr(goal, "id", "?"), len(deferred), deferred,
        )

    lease = None
    if core is not None and hasattr(core, "external_op_lease"):
        lease = core.external_op_lease(
            seconds=(NIM_AUTHOR_TIMEOUT + 10) * len(batch),
            label="heldout_bank_author",
        )
    results = []
    try:
        if lease is not None:
            lease.__enter__()
        for fid in batch:
            results.append(author_rows_for_file(
                fid, author_fn=author_fn, author_model=author_model,
                input_dir=input_dir, bank_path=bank_path,
            ))
    finally:
        if lease is not None:
            try:
                lease.__exit__(None, None, None)
            except Exception:
                pass
    return {"authored": results, "deferred": deferred}
