"""Self-development board: a read-only, advisory mirror of Maria's own
self-improvement ideas.

The creative subsystem (K13) already generates "meta-goals" -- ideas for how
Maria could improve herself. It does so continuously, and the same handful of
themes recur thousands of times because nothing ever closes the loop (the
meta-goal -> real action bridge is broken; see R1 advisory invariant).

This package does NOT generate or act on ideas. It only AGGREGATES the
existing meta-goals into a curated board: ~5-7 distinct themes, how many times
each was asked, since when, and whether anything ever came of it. The point is
visibility for the operator -- turning a 6000-row loop into one honest picture.
"""

from agent_core.self_development.board import SelfDevJournal
from agent_core.self_development.bridge import SelfDevBridge
from agent_core.self_development.model import SelfDevTheme

__all__ = ["SelfDevJournal", "SelfDevBridge", "SelfDevTheme"]
