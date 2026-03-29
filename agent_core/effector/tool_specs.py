"""
Tool Specifications - Argument schemas for OpenClaw tools.

Defines which tools Maria is allowed to use, their required/optional
arguments, and K7 classification hints. Validates args before sending
to OpenClaw gateway to prevent malformed requests.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class ToolSpec:
    """Specification for an OpenClaw tool."""
    name: str
    description: str
    required_args: Set[str]
    optional_args: Set[str] = field(default_factory=set)
    dangerous: bool = False  # if True, K7 may block in certain modes


# Tools Maria is allowed to invoke via HTTP
TOOL_SPECS: Dict[str, ToolSpec] = {
    "exec": ToolSpec(
        name="exec",
        description="Execute shell command",
        required_args={"command"},
        optional_args={"workdir", "timeout", "env"},
        dangerous=True,
    ),
    "web_fetch": ToolSpec(
        name="web_fetch",
        description="Fetch URL content as markdown/text",
        required_args={"url"},
        optional_args={"extractMode", "maxChars"},
    ),
    "web_search": ToolSpec(
        name="web_search",
        description="Search the web",
        required_args={"query"},
        optional_args={"count", "country", "language", "freshness"},
    ),
    "message": ToolSpec(
        name="message",
        description="Send message via Telegram/Slack/Discord",
        required_args={"content"},
        optional_args={"channel", "silent"},
        dangerous=True,
    ),
    "read": ToolSpec(
        name="read",
        description="Read file contents",
        required_args={"path"},
        optional_args={"encoding"},
    ),
    "write": ToolSpec(
        name="write",
        description="Write content to file",
        required_args={"path", "content"},
        optional_args={"encoding", "append"},
        dangerous=True,
    ),
    "cron": ToolSpec(
        name="cron",
        description="Schedule recurring tasks",
        required_args={"action"},
        optional_args={"name", "schedule", "command"},
    ),
}

# Tools explicitly denied (blocked by OpenClaw HTTP policy or too dangerous)
DENIED_TOOLS: Set[str] = {
    "browser",          # Blocked by OpenClaw HTTP default policy
    "sessions_spawn",   # Hard-denied over HTTP
    "sessions_send",    # Hard-denied over HTTP
    "gateway",          # Hard-denied over HTTP
    "whatsapp_login",   # Hard-denied over HTTP
}

ALLOWED_TOOLS: Set[str] = set(TOOL_SPECS.keys())


def is_tool_allowed(tool_name: str) -> bool:
    """Check if a tool is in the whitelist and not denied."""
    return tool_name in ALLOWED_TOOLS and tool_name not in DENIED_TOOLS


def validate_args(tool_name: str, args: Dict) -> Tuple[bool, str]:
    """
    Validate arguments for a tool before sending to OpenClaw.

    Args:
        tool_name: Name of the tool
        args: Arguments dict to validate

    Returns:
        (valid, reason) tuple
    """
    spec = TOOL_SPECS.get(tool_name)
    if spec is None:
        return False, f"Unknown tool: {tool_name}"

    # Check required args
    missing = spec.required_args - set(args.keys())
    if missing:
        return False, f"Missing required args: {', '.join(sorted(missing))}"

    # Check for unknown args (warn but don't block)
    known = spec.required_args | spec.optional_args
    unknown = set(args.keys()) - known
    if unknown:
        # Don't block - OpenClaw may accept additional args
        pass

    return True, "OK"


def get_tool_spec(tool_name: str) -> Optional[ToolSpec]:
    """Get spec for a tool. Returns None if unknown."""
    return TOOL_SPECS.get(tool_name)


def is_tool_dangerous(tool_name: str) -> bool:
    """Check if a tool is marked as dangerous. Unknown tools are dangerous."""
    spec = TOOL_SPECS.get(tool_name)
    if spec is None:
        return True  # unknown = dangerous by default
    return spec.dangerous
