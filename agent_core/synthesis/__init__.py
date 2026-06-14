"""
Synthesis - Etap 2b: Maria composes NEW cross-source knowledge.

Flow (option A, 2026-06-11): gather material for a topic from longterm
memory -> NIM synthesizes a concept record -> the record goes into an
ISOLATED sandbox session -> independent exam INSIDE the sandbox ->
promote() (the K2 bridge, ADR-010) merges it into production only on a
pass. From there the existing chain takes over: the trust gate admits
the independently-verified file and BeliefBuilder mints beliefs on the
next source-watermark rebuild.

Kontrakt: docs/CONTRACTS.md - Kontrakt 2 (Sandbox) + Kontrakt 6 (World Model)
"""

from agent_core.synthesis.synthesis_agent import (
    SynthesisAgent,
    append_synthesis_review,
    build_synthesis_record,
    eligible_topics,
    gather_material,
    read_synthesis_reviews,
)

__all__ = [
    "SynthesisAgent",
    "append_synthesis_review",
    "build_synthesis_record",
    "eligible_topics",
    "gather_material",
    "read_synthesis_reviews",
]
