"""
Model Registry - Static configuration for M.A.R.I.A.'s multi-organ model stack.

Translates docs/MODEL_REGISTRY.md into Python dataclasses.
Each model has a role, RAM estimate, concurrency class, and loading policy.

Hardware: NiPoGi Mini PC | Ryzen 5 7430U | 32 GB RAM | Ubuntu 22.04
Runtime: Ollama (primary) | NVIDIA NIM (external)
"""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from maria_core.sys.config import DEFAULT_NIM_MODEL


class ModelRole(Enum):
    """Logical role a model fulfills in M.A.R.I.A.'s architecture."""
    PLANNER = "planner"       # MODEL-01: Strategic reasoning, multi-step planning
    EXECUTOR = "executor"     # MODEL-02: General tasks, chat, fallback brain
    CODER = "coder"           # MODEL-03: Code generation, patches, refactoring
    TRIAGE = "triage"         # MODEL-04: Intent classification, cheap routing
    MEMORY = "memory"         # MODEL-05: Summarization, fact extraction
    EXTERNAL = "external"     # MODEL-06: NIM API (cloud, model via config.DEFAULT_NIM_MODEL)
    ENCYCLOPEDIA = "encyclopedia"  # MODEL-07: Codex CLI (ChatGPT), interactive knowledge
    ANALYST = "analyst"       # MODEL-08: K12 evening shift, strongest model this box runs


class ConcurrencyClass(Enum):
    """How a model interacts with the heavy-model mutex."""
    HEAVY = "heavy"            # MODEL-01, MODEL-03: mutex-protected, max 1 at a time
    LIGHT_MAIN = "light_main"  # MODEL-02: can coexist with anything
    LIGHT_GATE = "light_gate"  # MODEL-04: can coexist with anything
    BACKGROUND = "background"  # MODEL-05: paused during heavy jobs
    NONE = "none"              # MODEL-06: external, no local RAM


class WarmState(Enum):
    """Default loading policy."""
    WARM = "warm"        # Keep loaded during active sessions
    COLD = "cold"        # Load on demand, unload after idle timeout
    EXTERNAL = "external"  # Not an Ollama model


@dataclass(frozen=True)
class ModelSpec:
    """Specification for a registered model."""
    model_id: str                          # Human ID, e.g. "qwen2.5-14b-instruct"
    role: ModelRole
    ollama_tag: str                        # Tag for ollama pull/chat, e.g. "qwen2.5:14b"
    ram_estimate_gb: float                 # Estimated RAM when loaded
    latency_budget_s: float                # Max acceptable inference time
    concurrency_class: ConcurrencyClass
    warm_state: WarmState
    idle_unload_s: float                   # Seconds before auto-unload (0 = keep warm)
    min_free_ram_gb: float                 # Minimum free RAM required before loading
    fallback_role: Optional[ModelRole]     # Fallback if this model can't load
    block_if_heavy_active: bool            # Block loading if another heavy model is active


# --- Static registry (source of truth) ---

_REGISTRY: Dict[ModelRole, ModelSpec] = {
    ModelRole.PLANNER: ModelSpec(
        model_id="qwen3-8b",
        role=ModelRole.PLANNER,
        ollama_tag="qwen3:8b",
        ram_estimate_gb=5.5,
        latency_budget_s=60.0,
        concurrency_class=ConcurrencyClass.HEAVY,
        warm_state=WarmState.COLD,
        idle_unload_s=300.0,   # 5 min
        min_free_ram_gb=8.0,
        fallback_role=ModelRole.EXECUTOR,
        block_if_heavy_active=True,
    ),
    ModelRole.EXECUTOR: ModelSpec(
        model_id="llama-3.1-8b-instruct",
        role=ModelRole.EXECUTOR,
        ollama_tag="llama3.1:8b",
        ram_estimate_gb=5.0,
        latency_budget_s=20.0,
        concurrency_class=ConcurrencyClass.LIGHT_MAIN,
        warm_state=WarmState.WARM,
        idle_unload_s=0.0,     # keep warm
        min_free_ram_gb=8.0,
        fallback_role=ModelRole.TRIAGE,
        block_if_heavy_active=False,
    ),
    ModelRole.CODER: ModelSpec(
        model_id="qwen2.5-coder-7b-instruct",
        role=ModelRole.CODER,
        ollama_tag="qwen2.5-coder:7b",
        ram_estimate_gb=5.0,
        latency_budget_s=30.0,
        concurrency_class=ConcurrencyClass.HEAVY,
        warm_state=WarmState.COLD,
        idle_unload_s=300.0,   # 5 min
        min_free_ram_gb=10.0,
        fallback_role=ModelRole.EXECUTOR,
        block_if_heavy_active=True,
    ),
    ModelRole.TRIAGE: ModelSpec(
        model_id="rule-based-classifier",
        role=ModelRole.TRIAGE,
        ollama_tag="",         # no LLM - rule-based heuristic_classify() won benchmark
        ram_estimate_gb=0.0,
        latency_budget_s=0.001,
        concurrency_class=ConcurrencyClass.LIGHT_GATE,
        warm_state=WarmState.WARM,  # always available (code, not model)
        idle_unload_s=0.0,
        min_free_ram_gb=0.0,
        fallback_role=None,    # no fallback needed - always available
        block_if_heavy_active=False,
    ),
    ModelRole.MEMORY: ModelSpec(
        model_id="bge-m3",
        role=ModelRole.MEMORY,
        # Swapped from nomic-embed-text 2026-07-25: measured on this store's
        # Polish corpus, nomic put the right memory in the top 5 for only 42.9%
        # of probe questions (median rank 42/1500) vs 100% for bge-m3. Cost:
        # ~2.1 s/text on this CPU vs ~0.8, and 1.2GB instead of 274MB.
        ollama_tag="bge-m3:latest",  # 1.2GB, 1024-dim embeddings
        ram_estimate_gb=1.5,
        latency_budget_s=20.0,  # a batch of MAX_BATCH_SIZE=8 costs ~17s
        concurrency_class=ConcurrencyClass.BACKGROUND,
        warm_state=WarmState.COLD,  # load on demand, unload after idle
        idle_unload_s=300.0,        # 5min idle -> unload
        min_free_ram_gb=2.0,
        fallback_role=ModelRole.EXECUTOR,
        block_if_heavy_active=False,
    ),
    ModelRole.EXTERNAL: ModelSpec(
        model_id=DEFAULT_NIM_MODEL,
        role=ModelRole.EXTERNAL,
        ollama_tag="",             # not an Ollama model
        ram_estimate_gb=0.0,
        latency_budget_s=30.0,
        concurrency_class=ConcurrencyClass.NONE,
        warm_state=WarmState.EXTERNAL,
        idle_unload_s=0.0,
        min_free_ram_gb=0.0,
        fallback_role=ModelRole.EXECUTOR,
        block_if_heavy_active=False,
    ),
    ModelRole.ENCYCLOPEDIA: ModelSpec(
        model_id="codex-chatgpt",
        role=ModelRole.ENCYCLOPEDIA,
        ollama_tag="",             # not an Ollama model - Codex CLI subprocess
        ram_estimate_gb=0.0,       # external, no local RAM
        latency_budget_s=120.0,    # CLI can be slow (30-120s)
        concurrency_class=ConcurrencyClass.NONE,
        warm_state=WarmState.EXTERNAL,
        idle_unload_s=0.0,
        min_free_ram_gb=0.0,
        fallback_role=ModelRole.EXTERNAL,  # NIM fallback, then EXECUTOR
        block_if_heavy_active=False,
    ),
    ModelRole.ANALYST: ModelSpec(
        # MODEL-08: the K12 evening shift's head. The NIM key expires
        # 2026-08-18, after which the analyst seat would fall through to
        # qwen3:8b -- a demotion for the one job that reads the whole system.
        #
        # Deliberately empty by default: which tag belongs here is decided by
        # scripts/bench_k12_analyst.py on this box, not by assumption. An empty
        # tag drops out of get_local_models() and the cascade skips this tier,
        # so the socket exists before the bulb is chosen.
        #
        # On a CPU-only box the wall clock is memory bandwidth per token, which
        # is why the candidates are MoE (few active parameters) rather than the
        # dense model of the same size class.
        model_id=os.getenv("K12_ANALYST_MODEL", "") or "unset",
        role=ModelRole.ANALYST,
        ollama_tag=os.getenv("K12_ANALYST_MODEL", ""),
        ram_estimate_gb=float(os.getenv("K12_ANALYST_RAM_GB", "19.0")),
        # Not a chat latency. One shift pass on a 30B MoE running on this CPU is
        # minutes, and the real ceiling is the shift's own daily budget.
        latency_budget_s=1800.0,
        concurrency_class=ConcurrencyClass.HEAVY,
        warm_state=WarmState.COLD,
        idle_unload_s=600.0,   # release the RAM soon after the shift ends
        min_free_ram_gb=float(os.getenv("K12_ANALYST_MIN_FREE_RAM_GB", "21.0")),
        fallback_role=ModelRole.PLANNER,  # today's behaviour, unchanged
        block_if_heavy_active=True,
    ),
}


# --- RAM tier thresholds (from MODEL_REGISTRY.md) ---

RAM_TIER_SAFE = 10.0        # < 10 GB total model RAM
RAM_TIER_NORMAL = 16.0      # 10-16 GB
RAM_TIER_WATCH = 18.0       # 16-18 GB
RAM_TIER_DANGER = 26.0      # 22-26 GB
RAM_EMERGENCY_FREE = 7.0    # minimum free RAM GB before emergency actions
LATENCY_UNHEALTHY_COUNT = 3  # mark model unhealthy after N violations


# --- Public API ---

def get_model(role: ModelRole) -> Optional[ModelSpec]:
    """Get model spec by role. Returns None if role not registered."""
    return _REGISTRY.get(role)


def list_models() -> List[ModelSpec]:
    """List all registered model specs."""
    return list(_REGISTRY.values())


def get_warm_models() -> List[ModelSpec]:
    """Get models that should be kept warm (EXECUTOR, TRIAGE)."""
    return [s for s in _REGISTRY.values()
            if s.warm_state == WarmState.WARM and s.ollama_tag and s.ollama_tag != "TBD"]


def get_heavy_models() -> List[ModelSpec]:
    """Get heavy models that require mutex (PLANNER, CODER)."""
    return [s for s in _REGISTRY.values()
            if s.concurrency_class == ConcurrencyClass.HEAVY]


def get_local_models() -> List[ModelSpec]:
    """Get all models that run locally via Ollama (excludes EXTERNAL)."""
    return [s for s in _REGISTRY.values()
            if s.warm_state != WarmState.EXTERNAL and s.ollama_tag and s.ollama_tag != "TBD"]


def is_triage_configured() -> bool:
    """Check if MODEL-04 triage has been benchmarked and configured.

    Since Stage 2 benchmark (2026-03-22), triage is rule-based
    (heuristic_classify in routing_rules.py) - always available.
    """
    return True


def set_triage_model(ollama_tag: str, ram_estimate_gb: float) -> None:
    """
    Set the triage model after Stage 2 benchmark.

    Replaces the TBD placeholder with the benchmark winner.

    Args:
        ollama_tag: Ollama tag of the winner (e.g. "qwen2.5:3b")
        ram_estimate_gb: Measured RAM usage in GB
    """
    global _REGISTRY
    _REGISTRY[ModelRole.TRIAGE] = ModelSpec(
        model_id=ollama_tag,
        role=ModelRole.TRIAGE,
        ollama_tag=ollama_tag,
        ram_estimate_gb=ram_estimate_gb,
        latency_budget_s=3.0,
        concurrency_class=ConcurrencyClass.LIGHT_GATE,
        warm_state=WarmState.WARM,
        idle_unload_s=0.0,
        min_free_ram_gb=8.0,
        fallback_role=ModelRole.EXECUTOR,
        block_if_heavy_active=False,
    )
