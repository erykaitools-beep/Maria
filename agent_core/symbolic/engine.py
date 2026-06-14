"""ForwardChainingEngine — applies registered rules until fixpoint."""

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent_core.symbolic.graph import SymbolicGraph

logger = logging.getLogger(__name__)


MAX_ITERATIONS = 10  # safeguard against non-terminating rules


class ForwardChainingEngine:
    """Apply rules to graph until fixpoint or MAX_ITERATIONS reached.

    Rules are idempotent — engine iterates until no new edges added, or limit.
    """

    def __init__(self, graph: SymbolicGraph, rules: Optional[List[Tuple[int, str, Callable]]] = None):
        self._graph = graph
        self._rules = rules  # None means lazy-load from registry on apply

    def _get_rules(self) -> List[Tuple[int, str, Callable]]:
        if self._rules is not None:
            return self._rules
        from agent_core.symbolic.rules import get_registered_rules
        return get_registered_rules()

    def apply_all(self) -> Dict[str, Any]:
        """Run all rules until fixpoint. Returns stats."""
        stats: Dict[str, Any] = {
            "iterations": 0,
            "edges_added_total": 0,
            "rule_fires": {},
            "duration_ms": 0.0,
        }
        t0 = time.monotonic()
        rules = self._get_rules()

        for iteration in range(MAX_ITERATIONS):
            edges_before = len(self._graph._edges)
            for priority, name, fn in rules:
                edges_pre = len(self._graph._edges)
                try:
                    fn(self._graph)
                except Exception as e:
                    logger.warning(f"[Engine] rule {name} raised: {e}")
                    continue
                edges_post = len(self._graph._edges)
                if edges_post > edges_pre:
                    stats["rule_fires"][name] = stats["rule_fires"].get(name, 0) + (edges_post - edges_pre)
            edges_after = len(self._graph._edges)
            stats["iterations"] += 1
            stats["edges_added_total"] += (edges_after - edges_before)
            if edges_after == edges_before:
                break  # fixpoint

        stats["duration_ms"] = (time.monotonic() - t0) * 1000
        return stats
