"""
Escalation handling for K7 Autonomy Policy.

Decides what happens when an action is blocked or requires escalation.
Current implementation: log + block. Full HITL will come with Web UI integration.

Kontrakt: docs/CONTRACTS.md - Kontrakt 7: Autonomy Policy
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_META_DIR = Path(__file__).resolve().parents[2] / "meta_data"
_DEFAULT_LOG_PATH = _META_DIR / "autonomy_decisions.jsonl"


@dataclass
class EscalationRecord:
    """A logged autonomy decision."""
    timestamp: float
    action_type: str
    decision: str         # PolicyDecision.value
    reasons: List[str]
    rule_name: Optional[str] = None
    goal_id: Optional[str] = None
    context_snapshot: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.timestamp,
            "action_type": self.action_type,
            "decision": self.decision,
            "reasons": self.reasons,
            "rule_name": self.rule_name,
            "goal_id": self.goal_id,
            "context": self.context_snapshot,
        }


class EscalationHandler:
    """
    Handles non-ALLOW policy decisions.

    Current behavior:
    - BLOCK / RATE_LIMITED: log and return blocked result
    - ESCALATE: log and block (HITL placeholder - will prompt human in future)

    All decisions are logged to autonomy_decisions.jsonl for analysis.
    """

    def __init__(self, log_path: Optional[Path] = None):
        self._log_path = Path(log_path) if log_path else _DEFAULT_LOG_PATH
        self._recent: List[EscalationRecord] = []
        self._max_recent = 50

    def handle(
        self,
        action_type: str,
        decision: str,
        reasons: List[str],
        rule_name: Optional[str] = None,
        goal_id: Optional[str] = None,
        context_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process a non-ALLOW decision.

        Args:
            action_type: ActionType.value
            decision: PolicyDecision.value
            reasons: Why the action was blocked/escalated
            rule_name: Which rule triggered
            goal_id: Associated goal
            context_snapshot: Compact context for logging

        Returns:
            Dict suitable as action result: {"success": False, "blocked_by": ...}
        """
        record = EscalationRecord(
            timestamp=time.time(),
            action_type=action_type,
            decision=decision,
            reasons=reasons,
            rule_name=rule_name,
            goal_id=goal_id,
            context_snapshot=context_snapshot or {},
        )

        self._log(record)
        self._recent.append(record)
        if len(self._recent) > self._max_recent:
            self._recent = self._recent[-self._max_recent:]

        logger.info(
            f"[AUTONOMY] {decision}: {action_type} - "
            f"{'; '.join(reasons)}"
        )

        return {
            "success": False,
            "blocked_by": "autonomy_policy",
            "decision": decision,
            "reasons": reasons,
            "rule_name": rule_name,
        }

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent escalation records."""
        return [r.to_dict() for r in self._recent[-limit:]]

    def _log(self, record: EscalationRecord) -> None:
        """Append record to JSONL log."""
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except IOError as e:
            logger.warning(f"Could not write autonomy log: {e}")
