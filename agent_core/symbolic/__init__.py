"""
Symbolic World Model — derived property graph + forward chaining rules.

STATUS (2026-05-29): RESEARCH_ONLY — zamrożone w czasie. Maria 2.0 paradygmat
odłożony, fokus na dojrzewanie 1.0. Kod + testy zachowane, ale NIE wired do
daemon spine: 0 importów z maria.py/core.py, flaga SYMBOLIC_WORLD_MODEL_ENABLED
nigdy nie czytana w runtime. Wróci gdy 1.0 da dane. Zob. docs/SYSTEM_STATUS.md.

Faza K Deska #3 (M15). Layer OBOK K6 BeliefStore — beliefs zostają source of
truth, symbolic graph derives structured relationships + inferred facts.

Werdykt Fazy J 2026-05-16 (MIXED) motivated this layer: reasoning bez LLM
w pętli dla rutyny (stuck-loop reduction, exam failure patterns, goal
dependency tracking).

Design: docs/plans/DESIGN_SYMBOLIC_WORLD_MODEL.md
ADR target: ADR-031 (after Phase 3 cutover)

Feature flag: SYMBOLIC_WORLD_MODEL_ENABLED (default false)
"""

from agent_core.symbolic.builder import SymbolicBuilder
from agent_core.symbolic.edge_model import SymbolicEdge
from agent_core.symbolic.engine import ForwardChainingEngine
from agent_core.symbolic.graph import SymbolicGraph
from agent_core.symbolic.node_model import SymbolicNode

# Auto-import bootstrap rules to register them in module registry.
# Order doesn't matter for registration; engine sorts by priority.
from agent_core.symbolic.rules import goal_rules as _goal_rules  # noqa: F401
from agent_core.symbolic.rules import learning_rules as _learning_rules  # noqa: F401
from agent_core.symbolic.rules import planner_rules as _planner_rules  # noqa: F401

__all__ = [
    "ForwardChainingEngine",
    "SymbolicBuilder",
    "SymbolicEdge",
    "SymbolicGraph",
    "SymbolicNode",
]
