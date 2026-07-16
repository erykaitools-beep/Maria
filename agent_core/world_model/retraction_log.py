"""
Retraction Log - durable append-only audit ledger for conscious unlearning.

Records every quarantine / unquarantine / retract operation on the belief
layer (K6) as one JSONL line: who, why, when, what-it-touched, and the rollout
mode (observe|armed). This is the durable who/why trail that beliefs.jsonl
tombstones cannot provide -- meta_data/retractions.jsonl is NEVER compacted, so
it survives every belief-store maintenance pass and restart.

Pure I/O, no store coupling: the caller (WorldModel facade) builds the record
from live Belief objects; this module only stamps + writes + reads. Modeled on
synthesis_agent.append_synthesis_review / read_synthesis_reviews.

Rollback/quarantine (2026-06-14). Soul files are sacred (guardrail #1) and
append-only mutation needs a trail -- this is that trail.
ADR-001 (JSONL source of truth), ADR-023 (provenance).
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Canonical filename; the concrete path (meta_data/) is supplied by the caller,
# sibling to synthesis_review.jsonl / action_audit.jsonl.
RETRACTIONS_FILENAME = "retractions.jsonl"

# Operations recorded in the ledger.
OP_QUARANTINE = "quarantine"
OP_UNQUARANTINE = "unquarantine"
OP_RETRACT = "retract"
VALID_OPS = (OP_QUARANTINE, OP_UNQUARANTINE, OP_RETRACT)

# Denylist scopes (the durable do-not-readd record). 'source' = an originating
# file_id/synthesis_id (blocks the file belief + every concept belief derived
# from it -- the /forget_source root-and-branch cut). 'entity' = a specific
# belief entity (blocks just that belief's re-mint -- the by-id /retract case
# the adversarial review caught, where the source still satisfies the build
# gate so source scope alone would let it resurrect).
DENYLIST_FILENAME = "retraction_denylist.jsonl"
SCOPE_SOURCE = "source"
SCOPE_ENTITY = "entity"
VALID_SCOPES = (SCOPE_SOURCE, SCOPE_ENTITY)

# Rollout flag for the FUTURE autonomous path (faithfulness-CONTRADICTED ->
# auto-quarantine proposal). FROZEN: operator-MANUAL retraction (Telegram /
# facade) is gated by the caller's authority, NOT by this flag, and is always
# available. The flag gates only the auto path, which is deliberately NOT wired
# yet (post-observe, mirroring SYNTH_ENABLED). off/observe/armed, read live from
# os.environ but the daemon freezes env from systemd at start -> arming needs a
# .env edit + restart. MAX_RETRACTIONS_PER_RUN caps the auto path's blast radius;
# operator-manual by-source bulk is exempt (atomic).
RETRACTION_FLAG = "RETRACTION_ENABLED"
MAX_RETRACTIONS_PER_RUN = 20
_TRUTHY = {"1", "true", "yes", "on", "armed"}


def retraction_mode() -> str:
    """Resolve the auto-path rollout mode: 'off' | 'observe' | 'armed'.
    (Consumed by the future autonomous retraction path; manual ops ignore it.)"""
    import os
    raw = os.environ.get(RETRACTION_FLAG, "").strip().lower()
    if raw in ("observe", "dry_run", "dry-run"):
        return "observe"
    if raw in _TRUTHY:
        return "armed"
    return "off"


def new_retraction_id() -> str:
    """Mint a retraction id (ret-<uuid12>)."""
    return f"ret-{uuid.uuid4().hex[:12]}"


def append_retraction(
    log_path: Path,
    record: Dict[str, Any],
    now_ts: Optional[float] = None,
) -> bool:
    """Append one retraction record to the ledger (append-only).

    Stamps ``timestamp`` + ``iso`` + ``retraction_id`` when the caller did not
    supply them, then writes one JSON line. Defensive: never raises into the
    caller (an audit-logging failure must not abort or corrupt a retraction,
    just as it must not for synthesis). Returns True on a successful write.
    """
    try:
        ts = float(now_ts) if now_ts is not None else (
            float(record["timestamp"]) if record.get("timestamp") is not None
            else time.time()
        )
    except (TypeError, ValueError, KeyError):
        ts = time.time()

    out = dict(record)
    out.setdefault("retraction_id", new_retraction_id())
    out["timestamp"] = ts
    out["iso"] = (
        datetime.fromtimestamp(ts, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
        return True
    except OSError as exc:
        logger.warning("[Retraction] ledger append failed: %s", exc)
        return False


def read_retractions(
    log_path: Path, limit: int = 20,
) -> List[Dict[str, Any]]:
    """Read the most recent retractions (newest first), at most ``limit``.

    Read-only, defensive: a missing/corrupt log yields an empty list rather
    than raising. Skips malformed lines so one bad write never blinds the rest.
    """
    path = Path(log_path)
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError:
        return []
    rows.sort(key=lambda r: r.get("timestamp") or 0.0, reverse=True)
    return rows[: max(0, int(limit))]


# ---------------------------------------------------------------------------
# Denylist -- the durable "do-not-readd" record (resurrection guard).
# Append-only with net resolution: each line is {scope, value, ts, reason,
# active}; the last write per (scope, value) wins, so a deny can be lifted by
# appending active=False (un-quarantine-by-source re-allows the rebuild).
# Consulted at belief-build time, so a retracted/quarantined belief is not
# re-minted by the next build_all pass (build_all is a pure projection of the
# source JSONLs -- without this, a store-only retract is undone in one cycle).
# knowledge_index.jsonl stays immutable (ADR-001); the denylist is the gate.
# ---------------------------------------------------------------------------


def append_denylist_entry(
    log_path: Path,
    scope: str,
    value: str,
    reason: str = "",
    active: bool = True,
    now_ts: Optional[float] = None,
) -> bool:
    """Append one denylist mutation (deny when active=True, lift when False).

    Defensive: never raises into the caller. Returns True on a successful write.
    """
    if scope not in VALID_SCOPES or not value:
        return False
    try:
        ts = float(now_ts) if now_ts is not None else time.time()
    except (TypeError, ValueError):
        ts = time.time()
    record = {
        "scope": scope,
        "value": value,
        "active": bool(active),
        "reason": reason,
        "timestamp": ts,
        "iso": datetime.fromtimestamp(ts, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except OSError as exc:
        logger.warning("[Retraction] denylist append failed: %s", exc)
        return False


def load_denylist(log_path: Path) -> Dict[str, set]:
    """Resolve the net ACTIVE denylist into {'source': set, 'entity': set}.

    Read-only, defensive: a missing/corrupt log yields empty sets rather than
    raising. Last write per (scope, value) wins, so a lifted entry (active=False)
    drops out. Malformed lines are skipped.
    """
    result: Dict[str, set] = {SCOPE_SOURCE: set(), SCOPE_ENTITY: set()}
    path = Path(log_path)
    if not path.is_file():
        return result
    # (scope, value) -> active, last-writer-wins by file order (append order).
    net: Dict[tuple, bool] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(obj, dict):
                    continue
                scope = obj.get("scope")
                value = obj.get("value")
                if scope in VALID_SCOPES and value:
                    net[(scope, value)] = bool(obj.get("active", True))
    except OSError:
        return result
    for (scope, value), active in net.items():
        if active:
            result[scope].add(value)
    return result
