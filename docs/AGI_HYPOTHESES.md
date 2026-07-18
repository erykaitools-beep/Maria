# Two Hypotheses — Maria 1.0 vs Maria 2.0 — parallel paths to AGI

> Eryk (2026-04-22): *"Maria 1.0 is a concept based on the known paradigm;
> Maria 2.0 is my own personal vision of how I see it and want it personally.
> we have a map for Maria 1.0 ... Maria 2.0 [needs] its own roadmap, plus
> let's immediately roll out a map from Maria 1.0 to AGI, not just a
> rewrite ... I want to check which concept is correct"*

This document describes a **parallel experiment**. Two independent paths,
the same goal (AGI), the same operational data base (a living Maria 1.0).

## Hypothesis 1 — Maria 1.0: the known paradigm scaled to AGI

**Principle:** the existing paradigm (pre-trained LLMs + agent
architecture + memory + learning) is sufficient for AGI, provided the
systems around the LLM are rich enough, coherent, and good at learning.

**Foundational architecture:**
- LLM as the **primary brain** (ollama locally, glm-5.1 via NIM)
- Agent core (K1-K13) as decision-supporting systems
- Memory systems (beliefs, semantic, episodic, tracing)
- Homeostasis tick loop as metabolism
- Bulletin + auditor as a self-regulation layer
- Digital Human phases as an increasingly deep rooting in the world

**Maria does not train weights herself.** She uses pre-trained LLMs.
Learning means:
- new knowledge → `knowledge_index.jsonl` + `semantic_memory`
- new experiences → `beliefs.jsonl`, `personality_experiences.jsonl`
- new patterns → `bulletin` / audit trails

This is consistent with Eryk's rejection of the weight-training
paradigm — Maria 1.0 **does not train** weights, she only develops the
**systems around** a frozen LLM.

**Path to AGI in this hypothesis:**
1. Stabilization (COMPLETE — phases A/B/C, Stabilization Roadmap)
2. Filling out the K modules (K14 Critic done, K15 Manifest done,
   K16+ TBD)
3. Better LLMs (glm-5.1 → frontier models as they become available
   locally)
4. Expanding Digital Human (Phase 7 WIRED done, Phases 8+ TBD)
5. Richer sensors (vision v2, smart home, audio)
6. Deeper learning from humans (Telegram, expert bridge, bulletin)
7. **D-boards** — iterative defragmentation fixes (D1-D3 done/planned)
8. After years: a system that, within its niche, reaches AGI-capable
   behavior

**AGI-capable criteria for Maria 1.0:**
- maintains a coherent identity across months of uptime (already
  partly true)
- learns from every interaction and embeds it into her operational
  memory
- plans in multiple steps, self-corrects errors, recognizes her own
  gaps
- reasons in cause-and-effect terms over her own history
- can explain *why* she did what she did
- swapping her LLM (model swap) does not break her core identity —
  because identity lives in the surrounding systems, not in the LLM

**Risks of this hypothesis:**
- If the LLM is a **fundamental** limitation (not merely a scaling
  problem), then no amount of surrounding systems will fix it
- Dependence on frozen weights — when the LLM paradigm changes, it has
  to be rebuilt
- Fragmentation between subsystems (K1-K15) — which we are actively
  addressing (D1.5b) — is a natural tax of this path

## Hypothesis 2 — Maria 2.0: a new paradigm from the ground up

**Principle:** the known paradigm (LLM-centric) has fundamental
limitations that cannot be fixed by scaling. AGI requires a different
foundation — 4 pillars + code as emergence, with the LLM as a
replaceable parser.

**Path to AGI in this hypothesis:**
Z1 corpus → Z2 mathematics → Z3 5D logic → Z4 linguistics → Z5
cryptology → Z6 integration → Z7 shadow mode → Z8 beta → Z9
production/AGI-capable.

**AGI-capable criteria for Maria 2.0:**
- makes decisions without invoking an LLM in the reasoning layer
- the program library grows through experience without fine-tuning
- swapping the LLM parser (layer 1) does not touch the core identity
- 32GB RAM is enough within her niche
- can read her own code and describe what is happening inside her
- adapts on the fly (neuroplasticity via program synthesis)

**Risks of this hypothesis:**
- It may turn out that the 4 pillars do not fit together as easily as
  in the vision
- Program synthesis without an LLM may be insufficient for open
  domains
- It may take years before it matches Maria 1.0 on core tasks
- Monetization gate — without a monetization path, it burns out in year 2-3

## Comparison criteria

The dimensions along which we compare, to answer "which path wins":

1. **Coherence** — whether Maria keeps a consistent identity across
   long uptime without drift
2. **Learning velocity** — how fast she absorbs new knowledge and how
   durably
3. **Model-swap stability** — whether changing the LLM breaks the
   system
4. **Self-awareness depth** — how deeply Maria understands herself
5. **Resource efficiency** — how much RAM/CPU she needs for a given
   scope
6. **Decision quality** — on a benchmark set (Maria 1.0 corpus),
   comparable decision quality
7. **Planning horizon** — how many steps ahead she can plan coherently
8. **Failure recovery** — how she reacts when one subsystem fails

Both hypotheses are tested against the **same** criteria. At yearly
intervals: a comparative report.

## Experiment setup

- **Maria 1.0** — a living production system on `refactor/homeostasis`.
  It evolves through D-boards + phases + Digital Human. Every tick
  generates data.
- **Maria 2.0** — is being built in the git worktree `../maria-2.0/` on
  branch `maria-2.0`. It uses the Maria 1.0 corpus as its dataset. It
  never merges into Maria 1.0 (a separate trajectory).
- **Reporting** — every N months, a comparison against the criteria.
  Initially Maria 1.0 will clearly win (because Maria 2.0 is only just
  being built). It gets interesting after a year — once Maria 2.0
  matures, we will see whether it converges or diverges.

## The decision is not static

Eryk is explicit: *"I want to check which concept is correct"*.
This is a **falsifiable** thesis. Possible outcomes:

1. **Maria 1.0 wins** — we do not need a new paradigm; fragmentation is
   a natural cost, but a coherent architecture + D-boards deliver
   AGI-capable behavior
2. **Maria 2.0 wins** — the known paradigm has a ceiling that cannot be
   broken through; a new foundation is required
3. **Convergence** — the two paths meet in the middle (e.g., Maria 1.0
   absorbs ideas from 2.0, Maria 2.0 uses the K modules from 1.0)
4. **Both fail** — AGI requires a third thing; both paradigms are
   partial

Eryk accepts any of these outcomes as long as it is **empirically
justified**. He does not cling to the Maria 2.0 vision if the data say
Maria 1.0 is better. And vice versa.

This is a scientific stance, not an ideological one.

## Role of this document

This file is a **meta-map** — it describes both paths, their
relationships, and the comparison criteria. No file of Maria 1.0 or 2.0
is changed. We add a reference to this document into the existing
roadmaps.

**Update cadence:** quarterly, with a short progress report for each
hypothesis.

---

*Two paths. The same goal. The data will decide.*
