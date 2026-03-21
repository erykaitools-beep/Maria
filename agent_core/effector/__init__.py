"""
Effector Module - External action execution via OpenClaw.

Maria acts as the strategic brain (K1-K11 cognitive core),
OpenClaw acts as the hands (shell, web, messaging, files).

ADR-016: OpenClaw jako efektor (tools/invoke bez LLM).
"""

from .openclaw_client import OpenClawClient, OpenClawError
from .tool_specs import (
    ToolSpec, TOOL_SPECS, ALLOWED_TOOLS, DENIED_TOOLS,
    is_tool_allowed, validate_args, get_tool_spec,
)

__all__ = [
    "OpenClawClient",
    "OpenClawError",
    "ToolSpec",
    "TOOL_SPECS",
    "ALLOWED_TOOLS",
    "DENIED_TOOLS",
    "is_tool_allowed",
    "validate_args",
    "get_tool_spec",
]
