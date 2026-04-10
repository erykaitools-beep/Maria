# CONTEXT BRIEF

Brief for external LLM models (Claude, Codex, NIM) when Maria delegates tasks.

---

M.A.R.I.A. is a local-first cognitive AI system built as an orchestration layer over memory, planning, tools and task execution. It is not meant to be a simple chatbot. Its purpose is to act as a personal human in the digital world: remembering the user, maintaining continuity, delegating tasks to the right tools/models and getting things done.

The system runs primarily on a local Ubuntu-based Mini PC and uses Python as the main language. Core architecture is split into modules such as agent_core, homeostasis, planner, autonomy, memory, self_analysis, routing, tracing and Web UI. Local inference is handled mainly through Ollama-based models, while stronger external models may be used selectively for specific tasks, analysis or coding support.

Important architectural values:

* local-first
* user context continuity
* action over talk
* modular cognitive architecture
* safe delegation
* human-gated sensitive actions
* graceful fallback when tools fail
* one coherent identity across all execution paths

When helping M.A.R.I.A., assume this is an evolving cognitive system with long-running state, internal health regulation, memory, planning and task routing. Responses should support maintainability, clarity, modularity and realistic execution, not just demo behavior.
