"""Autonomous effector-undo SUGGEST side (DH-A live-rung follow-up).

The undo journal + ``/undo_action`` give the operator the manual undo. This
package adds the missing autonomous side: a conservative detector that scans the
journal for an action Maria has a reason to regret, and -- through the same
STOP-AT-PENDING gate as self-repair (ADR-030/031) -- proposes undoing it. Maria
only RAISES HER HAND; the bounded, journaled, post-verified inverse runs only on
operator ``/approve_undo``. Nothing in this package executes anything itself.
"""

from agent_core.undo_suggest.detector import (
    SUGGEST_COOLDOWN_SECONDS,
    UndoSuggestionCandidate,
    detect_orphaned_reversible_actions,
)
from agent_core.undo_suggest.suggestion_creator import (
    UNDO_SUGGEST_PHASE,
    UNDO_SUGGEST_TTL_SECONDS,
    UndoSuggestionCreator,
)
from agent_core.undo_suggest.monitor import UndoSuggestionMonitor, undo_suggest_enabled
from agent_core.undo_suggest.expiry import expire_stale_undo_suggestions

__all__ = [
    "SUGGEST_COOLDOWN_SECONDS",
    "UndoSuggestionCandidate",
    "detect_orphaned_reversible_actions",
    "UNDO_SUGGEST_PHASE",
    "UNDO_SUGGEST_TTL_SECONDS",
    "UndoSuggestionCreator",
    "UndoSuggestionMonitor",
    "undo_suggest_enabled",
    "expire_stale_undo_suggestions",
]
