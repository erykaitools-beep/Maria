"""
CapabilitySpec - frozen metadata for a registered capability.

Each capability describes one dispatchable action type (cognitive organ endpoint).
Used by CapabilityRouter for registry-based dispatch and discovery.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilitySpec:
    """Metadata for a registered capability."""

    name: str
    """ActionType.value, e.g. 'learn', 'fetch', 'effector'."""

    description: str
    """Human-readable description of what this capability does."""

    required_subsystems: tuple
    """Names of subsystems needed, e.g. ('teacher_agent', 'knowledge_analyzer')."""

    k7_classification: str
    """Autonomy classification: 'free', 'guarded', 'restricted', 'forbidden'."""

    tags: tuple = ()
    """Grouping tags for discovery, e.g. ('learning', 'teacher')."""


# Default capability specs for all known action types.
# Combines data from K7 action_class.py classifications.
DEFAULT_CAPABILITY_SPECS = {
    "learn": CapabilitySpec(
        name="learn",
        description="Learn new knowledge chunks from input files",
        required_subsystems=("teacher_agent",),
        k7_classification="free",
        tags=("learning", "teacher"),
    ),
    "exam": CapabilitySpec(
        name="exam",
        description="Run exam on learned material",
        required_subsystems=("teacher_agent",),
        k7_classification="free",
        tags=("learning", "teacher"),
    ),
    "review": CapabilitySpec(
        name="review",
        description="Spaced repetition review of learned material",
        required_subsystems=("teacher_agent",),
        k7_classification="free",
        tags=("learning", "teacher"),
    ),
    "evaluate": CapabilitySpec(
        name="evaluate",
        description="Generate evaluation report with metrics",
        required_subsystems=("evaluation_observer",),
        k7_classification="free",
        tags=("monitoring",),
    ),
    "noop": CapabilitySpec(
        name="noop",
        description="No operation (idle)",
        required_subsystems=(),
        k7_classification="free",
        tags=(),
    ),
    "maintenance": CapabilitySpec(
        name="maintenance",
        description="Check and update maintenance goal metrics",
        required_subsystems=("homeostasis_core",),
        k7_classification="guarded",
        tags=("system",),
    ),
    "fetch": CapabilitySpec(
        name="fetch",
        description="Fetch web content (Wikipedia PL, RSS)",
        required_subsystems=("knowledge_analyzer",),
        k7_classification="guarded",
        tags=("web", "learning"),
    ),
    "experiment": CapabilitySpec(
        name="experiment",
        description="Run K11 parameter experiment",
        required_subsystems=("experiment_system",),
        k7_classification="guarded",
        tags=("tuning",),
    ),
    "effector": CapabilitySpec(
        name="effector",
        description="Execute tool via OpenClaw (ADR-016)",
        required_subsystems=("openclaw_client",),
        k7_classification="restricted",
        tags=("external", "effector"),
    ),
    "self_analyze": CapabilitySpec(
        name="self_analyze",
        description="K12 self-analysis cognitive loop",
        required_subsystems=("self_analysis",),
        k7_classification="guarded",
        tags=("meta", "analysis"),
    ),
    "creative": CapabilitySpec(
        name="creative",
        description="K13 creative reflection cycle",
        required_subsystems=("creative_module",),
        k7_classification="guarded",
        tags=("meta", "creative"),
    ),
    "ask_expert": CapabilitySpec(
        name="ask_expert",
        description="Ask ChatGPT/Codex for knowledge",
        required_subsystems=("llm_router",),
        k7_classification="guarded",
        tags=("external", "learning"),
    ),
    "validate": CapabilitySpec(
        name="validate",
        description="Cross-validate learned knowledge (Faza F)",
        required_subsystems=("cross_validator",),
        k7_classification="guarded",
        tags=("validation", "learning"),
    ),
}
