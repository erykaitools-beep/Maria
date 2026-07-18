# M.A.R.I.A. - Architecture Decision Records (ADR)
> Version: 0.2 | Last updated: 2026-01-26

## ADR Format

```
### ADR-XXX: Decision title
**Date:** YYYY-MM-DD
**Status:** PROPOSED | ACCEPTED | DEPRECATED | SUPERSEDED

**Context:** Description of the situation and the problem

**Decision:** What we decided

**Alternatives:**
1. Alternative A - why it was rejected
2. Alternative B - why it was rejected

**Consequences:**
- Positive: ...
- Negative: ...

**Refs:** links to related documents/issues
```

---

## Accepted Decisions

### ADR-001: JSONL as the memory format
**Date:** ~2024 (pre-existing)
**Status:** ACCEPTED

**Context:** The system needs durable data storage (knowledge index, memory, exam results).

**Decision:** Use the JSONL (JSON Lines) format - one JSON object per line.

**Alternatives:**
1. SQLite - rejected: extra dependency, more complex
2. Single JSON file - rejected: append problems, whole file held in memory

**Consequences:**
- Positive: simple append, readable format, easy debugging
- Negative: slow lookups (scanning the whole file), no indexes

---

### ADR-002: Ollama as the LLM backend
**Date:** ~2024 (pre-existing)
**Status:** ACCEPTED

**Context:** The system needs a local LLM for text analysis, question generation, and grading.

**Decision:** Use Ollama with the llama3.1:8b model.

**Alternatives:**
1. OpenAI API - rejected: requires internet, costs, privacy
2. Other local options (llama.cpp directly) - rejected: Ollama has a simpler API

**Consequences:**
- Positive: offline-first, free, control over the data
- Negative: requires a GPU or a strong CPU, slower than cloud

---

### ADR-003: Adaptive chunking with overlap
**Date:** ~2024 (pre-existing)
**Status:** ACCEPTED

**Context:** Learning texts can be long. The LLM has a limited context window.

**Decision:** Split text into ~1200-character chunks with a 150-character overlap. Look for natural boundaries (paragraphs, sentences).

**Consequences:**
- Positive: context preserved at boundaries, better summaries
- Negative: fragment duplication, higher token usage

---

### ADR-004: JSONL and SemanticGraph synchronization
**Date:** 2026-01-26
**Status:** ACCEPTED

**Context:** The system has two memory subsystems:
1. JSONL files (memory_store.py) - raw data
2. SemanticGraph (semantic_graph.py) - knowledge graph

They are currently not synchronized.

**Options:**
A) JSONL as source of truth, graph only an in-memory cache
B) Graph as source of truth, JSONL as backup/log
C) Both equal, two-way synchronization

**Decision:** Option A - JSONL is the source of truth, the graph is a derived index/cache.

**Rationale (from the project owner):** The semantic graph is meant to be an in-memory cache built from JSONL at startup. JSONL always holds the complete data; the graph is only a representation of it for fast lookups.

**Consequences:**
- Positive: clear data hierarchy, simpler recovery (rebuild the graph from JSONL)
- Negative: startup time may be longer with large datasets (building the graph)

**Refs:** Q-005

---

## Pending Decisions (PROPOSED)

*None currently.*

---

## Resolved Questions (answers from the project owner)

### Q-001: Is the archive/ folder used?
**Date:** 2026-01-26
**Status:** RESOLVED

**Context:** The `archive/` folder contains old code (brain/, tools/, perception.py). It is not imported by any active module.

**Answer:** The `archive/` folder is NOT used. It should be marked as deprecated and ignored during refactoring.

**Action:** Add `archive/` to `.gitignore` or remove it in refactoring Stage 5.

---

### Q-002: Intent behind two entry points (main.py vs run_maria.py)
**Date:** 2026-01-26
**Status:** RESOLVED

**Context:**
- `main.py` - interactive REPL with many commands
- `run_maria.py` - daemon running the learning cycle

**Answer:** Option A - MUTUALLY EXCLUSIVE. The user picks one of the entry points:
- `main.py` for interactive work
- `run_maria.py` for batch learning

They are NOT meant to run in parallel.

**Action:** Add validation in both files - check whether the other process is already running (PID file or port check).

---

### Q-003: orchestrator.py main() with max_iterations=0
**Date:** 2026-01-26
**Status:** RESOLVED

**Context:** In `orchestrator.py:191-195`:
```python
def main():
    maria_learning_cycle(max_iterations=0, ...)  # Zero iterations?
```

**Answer:** `max_iterations=0` means an INFINITE LOOP. This is intentional behavior.

**Action:** Change the parameter to `None` or `-1` for readability. Add an explanatory comment.

---

### Q-004: Should maria_web_learning.py and maria_api_bridge.py be implemented?
**Date:** 2026-01-26
**Status:** RESOLVED

**Context:** main.py tries to import these modules, but they do not exist in the repo.

**Answer:** Do NOT implement them now. These are planned future features (roadmap), but not part of the current scope.

**Action:** Keep the imports optional (try/except) with a "TODO: future feature" comment. Add to ROADMAP.md as Phase C or D.

---

### Q-005: Target integration graph <-> JSONL
**Date:** 2026-01-26
**Status:** RESOLVED → ADR-004

**Context:** The semantic graph and JSONL storage are two separate systems.

**Answer:** Option A - JSONL is the source of truth, the graph is a derived index/cache built from JSONL at startup.

**Action:** Implement a `rebuild_from_jsonl()` method in `agent_core/memory/semantic_store.py`.

---

## Open Questions (questions for the project owner)

*No open questions currently.*

---

*Add new questions and decisions as work progresses.*
