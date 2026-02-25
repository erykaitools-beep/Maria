"""
Awareness - Maria's self-awareness context for chat.

Aggregates data from multiple sources (learning files, memory,
code self-model, system metrics) into a compact string injected
into the system prompt so Maria can answer questions about herself.

Usage:
    from agent_core.awareness import ContextBuilder

    builder = ContextBuilder()
    context = builder.build()
    # "[Swiadomosc: Mam 7 plikow do nauki (1 ukonczone, 5 nowych).
    #   Tagi: decyzje, pytania. Kod: 92 pliki. RAM 45%, CPU 12%.]"
"""

from agent_core.awareness.context_builder import ContextBuilder

__all__ = ["ContextBuilder"]
