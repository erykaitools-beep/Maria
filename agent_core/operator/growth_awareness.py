"""
GrowthAwareness (K15.3) - Limitations as identified growth targets.

Maria identifies what she cannot do, estimates the cost/benefit
of closing each gap, and tracks progress toward improvement.
Targets are auto-generated from actual system state.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TARGETS_FILE = Path("meta_data/growth_targets.jsonl")


@dataclass
class GrowthTarget:
    """A concrete improvement Maria could make."""

    target_id: str
    category: str  # capability, knowledge, resource, reliability
    description: str
    current_state: str  # what Maria can do now
    desired_state: str  # what she would be able to do
    estimated_cost: str  # low / medium / high
    estimated_benefit: str  # low / medium / high
    source: str  # where this target was identified
    status: str = "identified"  # identified, in_progress, achieved, deferred
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "category": self.category,
            "description": self.description,
            "current_state": self.current_state,
            "desired_state": self.desired_state,
            "estimated_cost": self.estimated_cost,
            "estimated_benefit": self.estimated_benefit,
            "source": self.source,
            "status": self.status,
            "created_at": self.created_at,
        }


# Cost/benefit for static hardware limitations
_HARDWARE_TARGETS = [
    GrowthTarget(
        target_id="hw-gpu",
        category="resource",
        description="Brak GPU - inference na CPU",
        current_state="LLM inference 5-30s per call (CPU only)",
        desired_state="LLM inference <1s (GPU accelerated)",
        estimated_cost="high",  # ~2000+ PLN
        estimated_benefit="high",  # 10x faster
        source="hardware",
    ),
]


class GrowthAwareness:
    """
    Identifies limitations as growth targets with cost/benefit.

    Auto-generates targets from:
    - Unavailable capabilities (CapabilityManifest)
    - Low-confidence actions (HonestyProtocol)
    - Knowledge gaps (KnowledgeAnalyzer)
    - Hardware limitations (static)
    """

    def __init__(self, targets_path: Optional[Path] = None):
        self._targets_path = targets_path or _TARGETS_FILE
        self._capability_manifest = None
        self._honesty_protocol = None
        self._knowledge_analyzer = None
        self._targets: List[GrowthTarget] = []
        self._loaded = False

    # -- DI setters --

    def set_capability_manifest(self, manifest) -> None:
        self._capability_manifest = manifest

    def set_honesty_protocol(self, protocol) -> None:
        self._honesty_protocol = protocol

    def set_knowledge_analyzer(self, analyzer) -> None:
        self._knowledge_analyzer = analyzer

    # -- Core API --

    # Descriptive fields recomputed on every refresh (status/created_at are NOT).
    _MUTABLE_FIELDS = (
        "description",
        "current_state",
        "desired_state",
        "estimated_cost",
        "estimated_benefit",
        "source",
    )

    def refresh(self) -> int:
        """Re-scan all sources: add new targets AND update existing ones in place.

        Returns the count of newly added targets. Operator-set status
        (deferred/achieved/in_progress) and created_at are preserved across
        refreshes; only the descriptive fields (description, current_state,
        cost/benefit, ...) are recomputed so the live numbers stay current
        instead of freezing at first scan.

        Note: a target whose source no longer regenerates it (e.g. the
        knowledge backlog drops below threshold) is intentionally NOT
        auto-resolved here -- a transient source error returning empty would
        wrongly mark it achieved. Closure stays an explicit mark_achieved().
        """
        self._ensure_loaded()
        by_id = {t.target_id: t for t in self._targets}

        generated: List[GrowthTarget] = []
        generated.extend(self._targets_from_capabilities())
        generated.extend(self._targets_from_reliability())
        generated.extend(self._targets_from_knowledge())
        # Hardware targets are static module globals -- copy so we never mutate
        # the shared instances (the old code set created_at on the global).
        generated.extend(replace(t) for t in _HARDWARE_TARGETS)

        new_count = 0
        dirty = False
        for fresh in generated:
            existing = by_id.get(fresh.target_id)
            if existing is None:
                if not fresh.created_at:
                    fresh.created_at = time.time()
                self._targets.append(fresh)
                by_id[fresh.target_id] = fresh
                new_count += 1
                dirty = True
                continue
            # Update descriptive fields in place; never touch status/created_at.
            for f in self._MUTABLE_FIELDS:
                if getattr(existing, f) != getattr(fresh, f):
                    setattr(existing, f, getattr(fresh, f))
                    dirty = True

        if dirty:
            self._save()

        return new_count

    def get_targets(self, status: Optional[str] = None) -> List[GrowthTarget]:
        """Get targets with optional status filter."""
        self._ensure_loaded()
        if status:
            return [t for t in self._targets if t.status == status]
        return list(self._targets)

    def get_top_targets(self, n: int = 5) -> List[GrowthTarget]:
        """Get top N targets sorted by benefit/cost ratio."""
        self._ensure_loaded()
        active = [t for t in self._targets if t.status == "identified"]
        return sorted(active, key=self._score_target, reverse=True)[:n]

    def mark_achieved(self, target_id: str) -> bool:
        """Mark a target as achieved."""
        self._ensure_loaded()
        for t in self._targets:
            if t.target_id == target_id:
                t.status = "achieved"
                self._save()
                return True
        return False

    def mark_deferred(self, target_id: str) -> bool:
        """Mark a target as deferred."""
        self._ensure_loaded()
        for t in self._targets:
            if t.target_id == target_id:
                t.status = "deferred"
                self._save()
                return True
        return False

    def get_summary_text(self) -> str:
        """Polish human-readable growth summary."""
        top = self.get_top_targets(5)
        if not top:
            return "Nie zidentyfikowalam jeszcze kierunkow rozwoju."

        lines = ["*Kierunki rozwoju (top 5):*", ""]
        for t in top:
            cost_icon = {"low": "L", "medium": "M", "high": "H"}.get(
                t.estimated_cost, "?"
            )
            benefit_icon = {"low": "L", "medium": "M", "high": "H"}.get(
                t.estimated_benefit, "?"
            )
            lines.append(
                f"  [{t.category}] {t.description}"
            )
            lines.append(
                f"    koszt={cost_icon} korzysci={benefit_icon} ({t.source})"
            )

        total = len(self.get_targets(status="identified"))
        achieved = len(self.get_targets(status="achieved"))
        if achieved > 0:
            lines.append(f"\nOsiagniete: {achieved}, aktywne: {total}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Full data for API."""
        self._ensure_loaded()
        return {
            "targets": [t.to_dict() for t in self._targets],
            "total": len(self._targets),
            "identified": len(self.get_targets("identified")),
            "achieved": len(self.get_targets("achieved")),
            "deferred": len(self.get_targets("deferred")),
        }

    # -- Target generators --

    def _targets_from_capabilities(self) -> List[GrowthTarget]:
        """Generate targets from unavailable capabilities."""
        targets = []
        if not self._capability_manifest:
            return targets

        try:
            unavailable = self._capability_manifest.get_unavailable()
            for cap in unavailable:
                tid = f"cap-{cap.name}"
                targets.append(GrowthTarget(
                    target_id=tid,
                    category="capability",
                    description=f"Niedostepna: {cap.description}",
                    current_state=f"Niedostepne: {cap.reason_unavailable}",
                    desired_state=f"Zdolnosc: {cap.description}",
                    estimated_cost="medium",
                    estimated_benefit="medium",
                    source="capability_manifest",
                    created_at=time.time(),
                ))
        except Exception as e:
            logger.debug("GrowthAwareness: capability scan error: %s", e)
        return targets

    def _targets_from_reliability(self) -> List[GrowthTarget]:
        """Generate targets from low-confidence actions."""
        targets = []
        if not self._honesty_protocol:
            return targets

        try:
            stats = self._honesty_protocol.get_action_stats()
            for action, data in stats.items():
                count = data.get("count", 0)
                success = data.get("success", 0)
                if count >= 5 and success / count < 0.6:
                    rate = success / count
                    tid = f"rel-{action}"
                    targets.append(GrowthTarget(
                        target_id=tid,
                        category="reliability",
                        description=f"Niska skutecznosc: {action} ({rate:.0%})",
                        current_state=f"{success}/{count} udanych ({rate:.0%})",
                        desired_state=f"Skutecznosc >= 80%",
                        estimated_cost="low",
                        estimated_benefit="high",
                        source="honesty_protocol",
                        created_at=time.time(),
                    ))
        except Exception as e:
            logger.debug("GrowthAwareness: reliability scan error: %s", e)
        return targets

    def _targets_from_knowledge(self) -> List[GrowthTarget]:
        """Generate targets from knowledge gaps."""
        targets = []
        if not self._knowledge_analyzer:
            return targets

        try:
            snap = self._knowledge_analyzer.get_knowledge_snapshot()
            by_status = snap.get("files_by_status", {})
            new_files = by_status.get("new", [])

            if len(new_files) > 3:
                tid = "kn-backlog"
                targets.append(GrowthTarget(
                    target_id=tid,
                    category="knowledge",
                    description=f"{len(new_files)} plikow czeka na nauke",
                    current_state=f"{len(new_files)} nowych plikow w input/",
                    desired_state="Wszystkie pliki przetworzone",
                    estimated_cost="low",
                    estimated_benefit="medium",
                    source="knowledge_analyzer",
                    created_at=time.time(),
                ))

            hard = by_status.get("hard_topic", [])
            if hard:
                tid = "kn-hard"
                targets.append(GrowthTarget(
                    target_id=tid,
                    category="knowledge",
                    description=f"{len(hard)} trudnych tematow do powtorzenia",
                    current_state=f"Hard topics: {len(hard)}",
                    desired_state="Opanowane - zdane egzaminy",
                    estimated_cost="medium",
                    estimated_benefit="medium",
                    source="knowledge_analyzer",
                    created_at=time.time(),
                ))
        except Exception as e:
            logger.debug("GrowthAwareness: knowledge scan error: %s", e)
        return targets

    # -- Persistence --

    def _ensure_loaded(self) -> None:
        """Load targets from JSONL if not yet loaded."""
        if self._loaded:
            return
        self._loaded = True
        if not self._targets_path.exists():
            return
        try:
            lines = self._targets_path.read_text(encoding="utf-8").strip().split("\n")
            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    self._targets.append(GrowthTarget(**data))
                except (json.JSONDecodeError, TypeError):
                    continue
        except Exception as e:
            logger.debug("GrowthAwareness: load error: %s", e)

    def _save(self) -> None:
        """Save all targets to JSONL."""
        try:
            self._targets_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._targets_path, "w", encoding="utf-8") as f:
                for t in self._targets:
                    f.write(json.dumps(t.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("GrowthAwareness: save error: %s", e)

    @staticmethod
    def _score_target(t: GrowthTarget) -> float:
        """Score a target by benefit/cost ratio for prioritization."""
        benefit_map = {"high": 3, "medium": 2, "low": 1}
        cost_map = {"high": 3, "medium": 2, "low": 1}
        benefit = benefit_map.get(t.estimated_benefit, 1)
        cost = cost_map.get(t.estimated_cost, 2)
        return benefit / cost
