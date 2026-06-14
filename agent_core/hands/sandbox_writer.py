"""
Sandbox writer -- the safe mechanism behind the FS_WRITE effector primitive (B2).

A single, dedicated, size-capped write into ONE sandbox directory. This is the
narrowest possible "real action on the world": it changes filesystem state that
K10 then verifies externally (file-exists re-stat). No shell, no symlinks, no
path escape -- a deliberately tiny first hand.

SSoT: both the CapabilityRouter handler (production) and the ActionExecutor
fallback (tests / no-router) call sandbox_write() so the write lives in one
place (the #4 P2 pattern -- one function, two callers).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Union

logger = logging.getLogger(__name__)

# Dedicated sandbox dir lives under meta_data/ (gitignored runtime state).
DEFAULT_SANDBOX_SUBDIR = "fs_sandbox"

# Rung 2 (TIER 2 hands): the operator-visible "outbox" -- a REAL (non-sandbox)
# dir where Maria writes useful artifacts. Same guards as the sandbox; the only
# differences are WHERE (a dedicated, never-an-existing-data dir) and that
# outbox writes are no_overwrite (there is no undo, so we never clobber).
DEFAULT_OUTBOX_SUBDIR = "maria_outbox"

# A deliberately tiny first hand: <1 KiB.
MAX_WRITE_BYTES = 1024

# Chars that must never appear in a sandbox filename (incl. path separators ->
# this is the primary traversal guard; '/' becoming '_' makes '../x' inert).
_UNSAFE_FILENAME_CHARS = " /\\:*?\"<>|()[]{}!@#$%^&+="


def default_sandbox_root(base_dir: Union[str, Path]) -> str:
    """The canonical sandbox root: ``<base_dir>/meta_data/fs_sandbox``."""
    return str(Path(base_dir) / "meta_data" / DEFAULT_SANDBOX_SUBDIR)


def default_outbox_root(base_dir: Union[str, Path]) -> str:
    """The canonical outbox root: ``<base_dir>/meta_data/maria_outbox`` (Rung 2)."""
    return str(Path(base_dir) / "meta_data" / DEFAULT_OUTBOX_SUBDIR)


def _sanitize_filename(name: str) -> str:
    """Reduce an arbitrary name to one safe, single-component filename."""
    safe = (name or "").strip()
    for ch in _UNSAFE_FILENAME_CHARS:
        safe = safe.replace(ch, "_")
    # Drop control chars (incl. NUL) -- they survive the table above and a NUL
    # would otherwise make Path.resolve() raise ValueError out of the engine.
    safe = "".join(c for c in safe if 31 < ord(c) != 127)
    while "__" in safe:
        safe = safe.replace("__", "_")
    safe = safe.strip("_.")
    return safe[:80] or "maria_action"


def sandbox_write(
    filename: str,
    content: str,
    *,
    sandbox_root: str,
    max_bytes: int = MAX_WRITE_BYTES,
    no_overwrite: bool = False,
) -> Dict[str, Any]:
    """Write ``content`` to ``filename`` inside ``sandbox_root``.

    Returns ``{"success": True, "path", "size", "action": "fs_write"}`` on
    success, else ``{"success": False, "error", "action": "fs_write"}``.

    Refuses: content larger than ``max_bytes``, any path that resolves outside
    ``sandbox_root``, and symlink targets. With ``no_overwrite=True`` it also
    refuses if the target already exists (used for the real outbox, where there
    is no undo -- we never clobber an existing file). The only side effect is
    one file written (or nothing).
    """
    safe_name = _sanitize_filename(filename)
    if not safe_name.endswith(".txt"):
        safe_name += ".txt"

    data = (content or "").encode("utf-8")
    if len(data) > max_bytes:
        return {
            "success": False,
            "error": f"content {len(data)}B exceeds max {max_bytes}B",
            "action": "fs_write",
        }

    try:
        root = Path(sandbox_root)
        root.mkdir(parents=True, exist_ok=True)
        root_res = root.resolve()
        target = root / safe_name

        # Never write through a symlink -- reject regardless of where it points
        # (checked before resolve(), so a symlink-to-outside reports as a symlink
        # rather than as a containment escape).
        if target.is_symlink():
            return {
                "success": False,
                "error": "target is a symlink (rejected)",
                "action": "fs_write",
            }
        # Containment: the resolved target must sit inside the resolved root.
        target_res = target.resolve()
        if target_res != root_res and root_res not in target_res.parents:
            return {
                "success": False,
                "error": "path escapes sandbox_root",
                "action": "fs_write",
            }

        # Write. With no_overwrite the no-clobber guard is ATOMIC via O_EXCL
        # (open 'xb'): no check-then-act window, so the "there is no undo, never
        # clobber" guarantee holds even against a racing writer.
        if no_overwrite:
            try:
                with open(target, "xb") as f:
                    f.write(data)
            except FileExistsError:
                return {
                    "success": False,
                    "error": "target exists (no_overwrite)",
                    "action": "fs_write",
                }
        else:
            target.write_bytes(data)
        size = target.stat().st_size
        logger.info("[fs_write] wrote %s (%dB)", target_res, size)
        return {
            "success": True,
            "ok": True,
            "path": str(target_res),
            "size": size,
            "action": "fs_write",
        }
    except (OSError, ValueError) as exc:
        return {"success": False, "error": str(exc), "action": "fs_write"}
