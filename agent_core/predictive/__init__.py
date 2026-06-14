"""Predictive layer (B0 / B0.1).

STATUS (2026-05-29): RESEARCH_ONLY — zamrożone w czasie. Maria 2.0 / JEPA
paradygmat odłożony, fokus na dojrzewanie 1.0. Kod + testy zachowane, ale NIE
wired do daemon spine: 0 importów z maria.py/core.py. Wróci gdy 1.0 da dane.
Zob. docs/SYSTEM_STATUS.md.

Cross-cutting module that watches state transitions for surprise.
First commit: StateSnapshot foundation only — no scorer, no calibrator,
no bulletin emit yet (those land in subsequent commits).

Design: docs/MARIA_2.0/B0_IMPLEMENTATION_SHORTLIST.md (rev 4)
Paradigm: docs/MARIA_2.0/JEPA_MAPPING.md
"""

from agent_core.predictive.action_baseline import ActionBaseline
from agent_core.predictive.bulletin_adapter import SurpriseBulletinAdapter
from agent_core.predictive.state_snapshot import StateSnapshot
from agent_core.predictive.threshold_calibrator import (
    DistributionStats,
    ThresholdCalibrator,
)

__all__ = [
    "ActionBaseline",
    "DistributionStats",
    "StateSnapshot",
    "SurpriseBulletinAdapter",
    "ThresholdCalibrator",
]
