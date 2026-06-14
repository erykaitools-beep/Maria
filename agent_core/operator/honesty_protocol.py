"""
HonestyProtocol (K15.2) - Evidence-based capability claims.

Maria NEVER claims she can do something without evidence.
"Nie wiem" is always a valid answer.

Uses actual execution history (planner_decisions.jsonl) to compute
data-driven confidence instead of static guesses.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.planner.decision_filters import is_real_action

logger = logging.getLogger(__name__)

_DECISIONS_FILE = Path("meta_data/planner_decisions.jsonl")

# Confidence qualifiers (Polish)
_QUALIFIERS = {
    "high": "",  # no qualifier needed
    "medium": "prawdopodobnie",
    "low": "nie jestem pewna, ale",
    "none": "nie wiem",
}


@dataclass
class HonestyCheck:
    """Result of verifying a capability claim."""

    action: str
    verified: bool  # has evidence backing it
    confidence: float  # 0.0-1.0
    evidence_source: str  # where evidence comes from
    attempts: int  # total executions found
    successes: int  # successful executions
    qualifier: str  # Polish qualifier to prepend


class HonestyProtocol:
    """
    Evidence-based capability verification.

    Replaces static confidence guesses with data from actual execution history.
    """

    def __init__(self, decisions_path: Optional[Path] = None, lookback_records: int = 200):
        self._decisions_path = decisions_path or _DECISIONS_FILE
        self._capability_manifest = None
        self._lookback = lookback_records
        # Cache action stats with TTL
        self._stats_cache: Optional[Dict[str, Dict]] = None
        self._stats_cached_at: float = 0.0
        self._stats_ttl: float = 60.0  # 1 minute

    def set_capability_manifest(self, manifest) -> None:
        self._capability_manifest = manifest

    # -- Core API --

    def check_capability_claim(self, action_name: str) -> HonestyCheck:
        """Verify whether Maria can honestly claim capability for an action."""
        # Step 1: Is the handler registered and subsystems present?
        handler_available = False
        if self._capability_manifest:
            handler_available = self._capability_manifest.can_do(action_name)

        # Step 2: What does execution history say?
        stats = self._get_action_stats()
        action_stats = stats.get(action_name, {})
        attempts = action_stats.get("count", 0)
        successes = action_stats.get("success", 0)

        # Step 3: Compute evidence-based confidence
        confidence = self._compute_confidence(
            handler_available, attempts, successes
        )

        # Step 4: Determine qualifier
        qualifier = self._qualifier_for_confidence(confidence)

        # Step 5: Determine evidence source
        if attempts > 0:
            evidence_source = f"planner_decisions ({attempts} executions, {successes} ok)"
        elif handler_available:
            evidence_source = "handler registered, no execution history"
        else:
            evidence_source = "not available"

        verified = handler_available and (attempts == 0 or confidence >= 0.4)

        return HonestyCheck(
            action=action_name,
            verified=verified,
            confidence=confidence,
            evidence_source=evidence_source,
            attempts=attempts,
            successes=successes,
            qualifier=qualifier,
        )

    def get_evidence_based_confidence(self, action_name: str) -> float:
        """Get data-driven confidence for a capability.

        Used by CapabilityManifest to replace static confidence estimates.
        """
        check = self.check_capability_claim(action_name)
        return check.confidence

    def qualify_statement(self, text: str, confidence: float) -> str:
        """Add appropriate qualifier to a statement based on confidence.

        Returns text unchanged if confidence is high.
        """
        qualifier = self._qualifier_for_confidence(confidence)
        if not qualifier:
            return text
        if qualifier == "nie wiem":
            return "Nie wiem."
        # Prepend qualifier, lowercase the first char of text
        if text and text[0].isupper():
            text = text[0].lower() + text[1:]
        return f"{qualifier.capitalize()}, {text}"

    def get_action_stats(self) -> Dict[str, Dict]:
        """Get execution stats per action type. Public API for other modules."""
        return self._get_action_stats()

    def get_summary(self) -> str:
        """Human-readable honesty summary."""
        stats = self._get_action_stats()
        if not stats:
            return "Brak historii wykonan - nie moge ocenic swoich mozliwosci."

        lines = ["*Ocena uczciwosci (na podstawie historii wykonan):*", ""]
        for action, data in sorted(stats.items()):
            count = data.get("count", 0)
            success = data.get("success", 0)
            rate = success / count if count > 0 else 0
            conf = self._compute_confidence(True, count, success)
            qualifier = self._qualifier_for_confidence(conf)
            q_str = f" [{qualifier}]" if qualifier else ""
            lines.append(
                f"  {action}: {success}/{count} ok ({rate:.0%}), "
                f"pewnosc {conf:.0%}{q_str}"
            )
        return "\n".join(lines)

    # -- Internal --

    def _get_action_stats(self) -> Dict[str, Dict]:
        """Read and cache action distribution from planner_decisions.jsonl."""
        now = time.time()
        if self._stats_cache is not None and (now - self._stats_cached_at) < self._stats_ttl:
            return self._stats_cache

        stats: Dict[str, Dict] = {}
        try:
            if not self._decisions_path.exists():
                self._stats_cache = stats
                self._stats_cached_at = now
                return stats

            lines = self._decisions_path.read_text(encoding="utf-8").strip().split("\n")
            # Take last N records
            recent = lines[-self._lookback:] if len(lines) > self._lookback else lines

            for line in recent:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # T-LEARN-003: capability evidence must come from real attempts.
                # Planner idle markers and skipped actions are not attempts and
                # would otherwise understate (or fabricate) capability history.
                if not is_real_action(record):
                    continue

                action = record.get("action_type", "")
                if not action:
                    continue

                if action not in stats:
                    stats[action] = {"count": 0, "success": 0, "failed": 0}

                stats[action]["count"] += 1
                result = record.get("result", {})
                if result.get("success"):
                    stats[action]["success"] += 1
                if record.get("status") == "failed":
                    stats[action]["failed"] += 1

        except Exception as e:
            logger.debug("HonestyProtocol: error reading decisions: %s", e)

        self._stats_cache = stats
        self._stats_cached_at = now
        return stats

    @staticmethod
    def _compute_confidence(
        handler_available: bool, attempts: int, successes: int
    ) -> float:
        """Compute evidence-based confidence.

        Rules:
        - No handler: 0.0
        - Handler but no history: 0.6 (benefit of the doubt, but not 1.0)
        - History available: success_rate weighted by sample size
        - Minimum 3 attempts before history significantly affects confidence
        """
        if not handler_available:
            return 0.0

        if attempts == 0:
            return 0.6  # registered but untested

        success_rate = successes / attempts if attempts > 0 else 0.0

        # Blend with prior (0.6) weighted by sample size
        # More attempts -> more weight to actual data
        weight = min(attempts / 10.0, 1.0)  # full weight at 10+ attempts
        blended = (1.0 - weight) * 0.6 + weight * success_rate

        return round(min(max(blended, 0.0), 1.0), 2)

    @staticmethod
    def _qualifier_for_confidence(confidence: float) -> str:
        """Get Polish qualifier for a confidence level."""
        if confidence >= 0.8:
            return ""
        elif confidence >= 0.5:
            return "prawdopodobnie"
        elif confidence > 0.0:
            return "nie jestem pewna, ale"
        else:
            return "nie wiem"
