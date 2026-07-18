# Glossary

Maria borrows words from biology, cognitive science, and systems engineering.
This page defines every term a newcomer meets in the [README](README.md) and
[QUICKSTART](QUICKSTART.md), in one or two plain sentences each. For the formal,
deep version of the cognitive terms, see [docs/CONTRACTS.md](docs/CONTRACTS.md)
and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

**Belief** — A single unit of what Maria "knows," stored with a confidence score
that decays over time unless reinforced. Beliefs live in an append-only log (the
world model, K6) and are periodically compacted so the store stays bounded.

**Chat ID** — Your personal Telegram conversation identifier. Maria uses it to
know which chat to message. Optional — only needed if you enable the Telegram
bot.

**Cognitive contracts (K1–K13)** — The 13 formal module contracts that define how
Maria's mind is built. Each contract fixes the responsibility and boundaries of
one subsystem, so parts can evolve without stepping on each other. Full detail in
[docs/CONTRACTS.md](docs/CONTRACTS.md). In short:

| Contract | Does |
|----------|------|
| K1 Perception | Aggregates events from every source into one stream |
| K2 Sandbox | Isolated space to learn safely; `promote()` is the only bridge to production |
| K3 Goals | Goal lifecycle with an audit trail (proposed → active → achieved) |
| K4 Evaluation | Read-only metrics, zero LLM |
| K5 Planner | The ReAct decision loop |
| K6 World Model | The belief store |
| K7 Autonomy | Classifies how much freedom an action gets |
| K8 Deliberation | Multi-step strategies |
| K9 Meta-Cognition | Confidence tracking, assumptions, "do I need a human?" |
| K10 Action Safety | Audit log, effect validation, safe-by-default |
| K11 Experiments | Autonomous parameter tuning behind a gate |
| K12 Self-Analysis | Reflection via an external LLM |
| K13 Creative | Tension detection and self-set meta-goals |

**Daemon** — A program that runs continuously in the background. Maria's daemon is
the always-on process (`maria.py`) that ticks once a second, whether or not you
have the Web UI open.

**Embeddings** — Numeric "fingerprints" of text (a list of 768 numbers) produced
by the `nomic-embed-text` model. They let Maria find related knowledge by
*meaning* rather than by matching keywords. See **Semantic memory**.

**Health score** — A 0-to-1 measure of how well the system is doing, computed
every tick from resource and activity signals. A score below 0.7 raises an
internal alert and can push Maria into a lower mode.

**Homeostasis** — The biological idea of a system keeping itself in balance.
Maria's core loop constantly senses her own state (CPU, memory, activity) and
adjusts her operating mode to stay stable — the same way a body regulates
temperature.

**K1–K13** — See **Cognitive contracts**.

**Mode regulator (ACTIVE / REDUCED / SLEEP / SURVIVAL)** — The component that
picks Maria's current operating mode from her health and resources, and controls
how she can move between them:

- **ACTIVE** — Full capability. The default when resources are fine (roughly:
  plenty of free RAM and CPU below ~70%).
- **REDUCED** — Throttled. Entered under memory pressure or when CPU stays high
  (~90%+) for several ticks in a row — for example during a burst of LLM
  inference.
- **SLEEP** — Low-power rest. Entered after ~30 minutes idle; the LLM is unloaded
  from RAM and Maria only does light consolidation.
- **SURVIVAL** — Emergency floor. Entered on a critical alert (e.g. RAM nearly
  exhausted); only the core loop runs until the pressure clears.

**NIM** — NVIDIA NIM, an **optional** cloud LLM API. When you supply a key, Maria
can route heavier analysis to a stronger (70B-class) model. Everything works
without it — NIM only makes some reflection deeper.

**Operator** — You, the human Maria works for. She keeps an *operator model* —
your name, interests, schedule, and preferences — and personalizes to it across
sessions.

**PIN** — The short code that locks the Web UI. The installer generates a random
one into your `.env`; you enter it when you open `http://localhost:5000`. Find it
with `grep MARIA_PIN .env`.

**Promote-to-production** — The single gate that moves something Maria learned in
the sandbox into her real, permanent knowledge. Nothing enters production
knowledge except through `promote()` — this keeps experiments from contaminating
what she actually believes (K2).

**ReAct loop** — Short for "Reason + Act." The planner's decision cycle:
**OBSERVE → THINK → ACT → EVALUATE**, repeated on each planner tick. In Maria's
first-generation planner this is rule-based and deterministic — no LLM in the
loop (K5).

**Sandbox** — An isolated scratch space where Maria learns and experiments
without touching production knowledge. Results cross over only via
**promote-to-production** (K2).

**Semantic memory** — Memory you can search by *meaning*. Using **embeddings**,
Maria retrieves related facts even when the wording differs from your query.
Requires the `nomic-embed-text` model (`ollama pull nomic-embed-text`).

**Spaced repetition** — A study schedule that re-tests material at growing
intervals so it sticks. Maria exams her own learned knowledge this way, revisiting
weaker items more often.

**Tick / Tick loop** — One pass of the homeostasis loop. Maria "ticks" about once
per second (1 Hz): she senses, interprets, decides, and acts, then sleeps until
the next tick. A rising tick count on the dashboard is the clearest sign she's
alive.

**World model** — Maria's store of **beliefs** about herself and the world, held
as append-only JSONL and bounded by importance-based compaction (K6).
