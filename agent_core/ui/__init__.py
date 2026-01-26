"""
UI Module - Telemetry API and operator controls

Components:
- telemetry_api.py: Read-only dashboard data
- operator_controls.py: Safe operator commands

Spec reference: homeostasis_spec.md section 6.2 (lines 820-875)
"""

from .telemetry_api import TelemetryAPI
from .operator_controls import OperatorControls

__all__ = [
    "TelemetryAPI",
    "OperatorControls",
]
