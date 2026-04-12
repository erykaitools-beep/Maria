"""
Operator Understanding module (K14).

5-dimensional model of the operator:
- Durable Facts: structured knowledge with confidence + source
- Preferences: communication and autonomy settings
- Day Rhythm: temporal patterns from interaction history
- Current Context: volatile state ("deadline today", "on vacation")
- Privacy Boundaries: hard limits, operator-defined, non-overridable

Part of Digital Human Roadmap, Faza 1.
"""

from agent_core.operator.capability_manifest import CapabilityManifest
from agent_core.operator.operator_model import OperatorModel
from agent_core.operator.privacy_guard import PrivacyGuard
from agent_core.operator.rhythm_detector import RhythmDetector

__all__ = ["CapabilityManifest", "OperatorModel", "PrivacyGuard", "RhythmDetector"]
