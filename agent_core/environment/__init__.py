"""
Environment Adaptation (Faza 6) - pluggable context modes.

Maria adapts behavior based on environment mode while keeping core identity stable.
K1-K13 + identity NEVER change between modes - only tools and priorities.
"""

from agent_core.environment.environment_model import (
    EnvironmentMode,
    EnvironmentProfile,
    ENVIRONMENT_PROFILES,
)
from agent_core.environment.mode_detector import ModeDetector
from agent_core.environment.environment_manager import EnvironmentManager

__all__ = [
    "EnvironmentMode",
    "EnvironmentProfile",
    "ENVIRONMENT_PROFILES",
    "ModeDetector",
    "EnvironmentManager",
]
