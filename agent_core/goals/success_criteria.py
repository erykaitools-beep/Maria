"""
Success-criteria evaluator (Plank B3).

Pure, side-effect-free evaluation of a goal's machine-checkable acceptance
criteria. This is the foundation the effector keystone (B2) and the goal
reconcile loop consume to decide "is this goal *actually* done" against an
externally-checkable fact -- not a self-reported log line.

(DEVELOPMENT_SEQUENCE guardrail #4, upgraded after the 2026-05-31 external
review: DONE = externally-checkable evidence, not a line we wrote ourselves.)

A criterion is a dict with a "type" and type-specific keys:

    {"type": "file_exists",  "path": "meta_data/fs_sandbox/x.txt"}
    {"type": "regex_in_log", "path": "meta_data/homeostasis_events.jsonl",
                             "pattern": "first_action_ok"}
    {"type": "exam_passed",  ...}   # delegated to an injected checker

Design notes:
  - No mutation, no network, no LLM. Read-only filesystem checks only.
  - ``file_exists`` can be confined to a ``sandbox_root`` (realpath prefix +
    symlink rejection) so a criterion cannot point outside an allowed directory.
  - ``exam_passed`` is the learning-goal criterion; its truth already lives in
    the learning closer (handlers.update_learning_goal / completed_file_ids), so
    it is evaluated via an injected ``exam_checker`` callable rather than
    duplicated here.
  - Every evaluation returns an evidence string -> the "evidence" a goal records
    on closure.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

CRITERION_FILE_EXISTS = "file_exists"
CRITERION_REGEX_IN_LOG = "regex_in_log"
CRITERION_EXAM_PASSED = "exam_passed"
CRITERION_EXAM_INDEPENDENT = "exam_independent"

KNOWN_CRITERION_TYPES = frozenset({
    CRITERION_FILE_EXISTS,
    CRITERION_REGEX_IN_LOG,
    CRITERION_EXAM_PASSED,
    CRITERION_EXAM_INDEPENDENT,
})

# Cap how much of a log we read for regex_in_log (avoid loading a huge JSONL).
# We read the tail, where recent events live.
_REGEX_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB
# Same tail cap for exam_results.jsonl when resolving exam_independent.
_RESULTS_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB
# Mirror of maria_core.sys.config.EXAM_PASS_THRESHOLD; used only when a criterion
# omits an explicit min_score. Kept as a literal so this module stays import-pure.
_DEFAULT_EXAM_PASS = 0.6


def _contained(path: Path, sandbox_root: Optional[str]) -> Tuple[bool, str]:
    """True if ``path`` resolves inside ``sandbox_root`` (no symlink escape)."""
    if sandbox_root is None:
        return True, ""
    try:
        root = Path(sandbox_root).resolve()
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        return False, f"path-resolve-error: {exc}"
    inside = resolved == root or root in resolved.parents
    if not inside:
        return False, f"escapes sandbox_root ({resolved} not under {root})"
    return True, ""


def _eval_file_exists(
    criterion: Dict[str, Any], sandbox_root: Optional[str]
) -> Tuple[bool, str]:
    raw = criterion.get("path")
    if not raw:
        return False, "file_exists: missing 'path'"
    path = Path(raw)
    ok, why = _contained(path, sandbox_root)
    if not ok:
        return False, f"file_exists: {why}"
    # Reject symlinks outright (safe-by-default; we want a real file present).
    if path.is_symlink():
        return False, f"file_exists: '{raw}' is a symlink (rejected)"
    if path.is_file():
        try:
            size = path.stat().st_size
        except OSError as exc:
            return False, f"file_exists: stat failed: {exc}"
        return True, f"file_exists: '{raw}' present ({size} bytes)"
    return False, f"file_exists: '{raw}' not found"


def _eval_regex_in_log(criterion: Dict[str, Any]) -> Tuple[bool, str]:
    raw = criterion.get("path")
    pattern = criterion.get("pattern")
    if not raw or pattern is None:
        return False, "regex_in_log: missing 'path' or 'pattern'"
    path = Path(raw)
    if not path.is_file():
        return False, f"regex_in_log: '{raw}' not found"
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return False, f"regex_in_log: bad pattern: {exc}"
    try:
        size = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            if size > _REGEX_MAX_BYTES:
                fh.seek(size - _REGEX_MAX_BYTES)
            text = fh.read()
    except OSError as exc:
        return False, f"regex_in_log: read failed: {exc}"
    if rx.search(text):
        return True, f"regex_in_log: '{pattern}' matched in '{raw}'"
    return False, f"regex_in_log: '{pattern}' not found in '{raw}'"


def _eval_exam_independent(criterion: Dict[str, Any]) -> Tuple[bool, str]:
    """Pass IFF the latest INDEPENDENT exam on record for ``file`` cleared the bar.

    This is the learning keystone (B4): a learning goal is "done" only when an
    examiner that is NOT the student (grader_independent == True, e.g. the static
    held-out grader ``heldout:static@v1``) scored the file's recall at or above
    ``min_score``. Read-only, pure-Python, no LLM, no network: it re-reads the
    recorded evidence in exam_results.jsonl rather than trusting a "completed"
    status flag a self-grading LLM could have set. Latest entry wins (JSONL is
    append-ordered), so a fresh failure correctly un-closes the goal.
    """
    file_id = criterion.get("file") or criterion.get("file_id")
    if not file_id:
        return False, "exam_independent: missing 'file'"
    min_score = criterion.get("min_score", _DEFAULT_EXAM_PASS)
    try:
        min_score = float(min_score)
    except (TypeError, ValueError):
        return False, f"exam_independent: bad min_score {min_score!r}"

    raw_path = criterion.get("results_path")
    if raw_path:
        path = Path(raw_path)
    else:
        try:
            from maria_core.sys.config import EXAM_RESULTS
            path = Path(EXAM_RESULTS)
        except Exception as exc:  # config import must never crash a tick
            return False, f"exam_independent: no results_path and config unavailable: {exc}"
    if not path.is_file():
        return False, f"exam_independent: results file '{path}' not found"

    latest: Optional[Dict[str, Any]] = None
    try:
        size = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            if size > _RESULTS_MAX_BYTES:
                fh.seek(size - _RESULTS_MAX_BYTES)
                fh.readline()  # discard the partial line the seek landed in
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("file") != file_id:
                    continue
                if not rec.get("grader_independent"):
                    continue
                latest = rec  # append-order -> last independent entry wins
    except OSError as exc:
        return False, f"exam_independent: read failed: {exc}"

    if latest is None:
        return False, f"exam_independent: no independent exam on record for '{file_id}'"
    score = latest.get("score")
    if not isinstance(score, (int, float)):
        return False, f"exam_independent: record for '{file_id}' has non-numeric score {score!r}"
    grader = latest.get("grader_model", "?")
    if score >= min_score:
        return True, (
            f"exam_independent: '{file_id}' scored {score:.2f} by {grader} "
            f"(>= {min_score})"
        )
    return False, (
        f"exam_independent: '{file_id}' scored {score:.2f} < {min_score} "
        f"(grader {grader})"
    )


def _resolve_exam_results_path(results_path: Optional[str] = None) -> Optional[Path]:
    """Path to exam_results.jsonl: explicit override, else the config default."""
    if results_path:
        return Path(results_path)
    try:
        from maria_core.sys.config import EXAM_RESULTS
        return Path(EXAM_RESULTS)
    except Exception:  # config import must never crash a tick
        return None


def independently_verified_file_ids(
    min_score: float = _DEFAULT_EXAM_PASS,
    results_path: Optional[str] = None,
) -> set:
    """File ids whose LATEST independent exam scored at/above ``min_score``.

    The single source of truth for "this file's knowledge is externally
    verified": a file is here IFF an examiner that is NOT the student
    (``grader_independent == True``, e.g. the static held-out grader) most
    recently scored its recall at/above the bar. Consumed by the learning-goal
    closer (reconciliation / update_learning_goal) AND the belief + semantic
    index trust gates, so none of them trust a self-graded ``completed`` status
    flag a self-grading LLM could have set ("read"/"self-graded" != "verified").

    Reads the FULL exam_results.jsonl once -- NOT the per-criterion tail cap used
    by ``_eval_exam_independent`` -- so an older independent pass is never missed
    and a genuinely-verified file is never wrongly demoted. Pure-Python,
    read-only, no LLM, no network. Returns an empty set if the file is absent.
    """
    try:
        min_score = float(min_score)
    except (TypeError, ValueError):
        min_score = _DEFAULT_EXAM_PASS
    path = _resolve_exam_results_path(results_path)
    if path is None or not path.is_file():
        return set()
    latest: Dict[str, Dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict) or not rec.get("grader_independent"):
                    continue
                fid = rec.get("file") or rec.get("file_id")
                if fid:
                    latest[fid] = rec  # append-order: latest independent wins
    except OSError:
        return set()
    return {
        fid for fid, rec in latest.items()
        if isinstance(rec.get("score"), (int, float)) and rec["score"] >= min_score
    }


def is_independently_verified(
    file_id: str,
    min_score: float = _DEFAULT_EXAM_PASS,
    results_path: Optional[str] = None,
) -> bool:
    """True IFF ``file_id``'s latest independent exam cleared ``min_score``.

    Single-file convenience over :func:`independently_verified_file_ids`; see it
    for the trust rationale. Re-reads the results file each call, so prefer the
    set form when checking many files at once.
    """
    if not file_id:
        return False
    return file_id in independently_verified_file_ids(min_score, results_path)


def evaluate_criterion(
    criterion: Any,
    *,
    sandbox_root: Optional[str] = None,
    exam_checker: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> Tuple[bool, str]:
    """Evaluate ONE criterion. Returns ``(passed, evidence)``."""
    if not isinstance(criterion, dict):
        return False, f"criterion not a dict: {criterion!r}"
    ctype = criterion.get("type")
    if ctype == CRITERION_FILE_EXISTS:
        return _eval_file_exists(criterion, sandbox_root)
    if ctype == CRITERION_REGEX_IN_LOG:
        return _eval_regex_in_log(criterion)
    if ctype == CRITERION_EXAM_INDEPENDENT:
        return _eval_exam_independent(criterion)
    if ctype == CRITERION_EXAM_PASSED:
        if exam_checker is None:
            return False, "exam_passed: no exam_checker provided (delegated to learning path)"
        try:
            passed = bool(exam_checker(criterion))
        except Exception as exc:  # defensive: a bad checker must not crash the tick
            return False, f"exam_passed: checker raised: {exc}"
        return passed, f"exam_passed: checker -> {passed}"
    return False, f"unknown criterion type: {ctype!r}"


def evaluate_criteria(
    criteria: Optional[List[Dict[str, Any]]],
    *,
    sandbox_root: Optional[str] = None,
    exam_checker: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Evaluate ALL criteria (logical AND). Returns ``(all_passed, evidence_list)``.

    An empty / None criteria list returns ``(False, ...)`` -- a goal with no
    machine-checkable criterion is NEVER auto-achieved by this evaluator; it
    falls back to the legacy learning/progress closure path.
    """
    if not criteria:
        return False, [{"type": None, "passed": False, "detail": "no success_criteria"}]
    evidence: List[Dict[str, Any]] = []
    all_passed = True
    for crit in criteria:
        passed, detail = evaluate_criterion(
            crit, sandbox_root=sandbox_root, exam_checker=exam_checker
        )
        evidence.append({
            "type": crit.get("type") if isinstance(crit, dict) else None,
            "passed": passed,
            "detail": detail,
        })
        if not passed:
            all_passed = False
    return all_passed, evidence
