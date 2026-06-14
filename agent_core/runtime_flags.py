"""
Runtime flags shared across subsystems within the Maria process.

Currently exposes a single flag: whether the operator (via Telegram /restart
or Web UI) asked the process to relaunch itself. The launcher (maria.py)
checks this flag after graceful_shutdown and chooses the exit code:
  - True  -> exit 1, systemd Restart=on-failure picks us back up
  - False -> exit 0, the operator wanted a real stop

Keep this module dependency-free. It is imported from both the launcher
and from inside subsystems, so cycles must be avoided.
"""

import threading

_lock = threading.Lock()
_restart_requested = False


def request_restart() -> None:
    """Mark that a graceful restart was requested."""
    global _restart_requested
    with _lock:
        _restart_requested = True


def restart_requested() -> bool:
    """True if request_restart() was called this run."""
    with _lock:
        return _restart_requested


def clear_restart_request() -> None:
    """Reset the flag — useful for tests."""
    global _restart_requested
    with _lock:
        _restart_requested = False
