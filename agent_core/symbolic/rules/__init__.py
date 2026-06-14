"""Rule registry for forward chaining engine.

@rule decorator registers inference rules. Higher priority runs first.
Maintained as module-level registry so importing rules modules auto-registers.
"""

import logging
from typing import Callable, List, Tuple

logger = logging.getLogger(__name__)


# Registry: list of (priority, name, fn) tuples
_REGISTERED_RULES: List[Tuple[int, str, Callable]] = []


def rule(priority: int = 50, name: str = ""):
    """Decorator — register inference rule.

    Higher priority runs first. Rule fn signature: `fn(graph: SymbolicGraph) -> None`.
    Rules should be idempotent (engine iterates to fixpoint).
    """

    def deco(fn: Callable) -> Callable:
        rule_name = name or fn.__name__
        _REGISTERED_RULES.append((priority, rule_name, fn))
        _REGISTERED_RULES.sort(key=lambda x: (-x[0], x[1]))
        return fn

    return deco


def get_registered_rules() -> List[Tuple[int, str, Callable]]:
    """Return all registered rules sorted by priority desc."""
    return list(_REGISTERED_RULES)


def clear_registry() -> None:
    """Clear registry — for testing only. Production code never calls this."""
    _REGISTERED_RULES.clear()
