# Skills as artifact — design (Hermes-inspired)

> Inspired by: Hermes Agent (Nous Research, MIT, February 2026). SKILL.md format
> compatible with agentskills.io. **Maria-style promote() flow** (sandbox-first,
> human gate) — NOT Hermes autonomous create.
>
> Decision: 2026-05-15 (the project owner chose to start with Skills as artifact,
> full Phase 1). The 24h autonomy test postmortem (2026-05-14) informs this:
> everything that changes production state goes through sandbox→promote with the
> PROPOSED flow.

## Why Maria needs Skills

Maria already has:
- **Goals as data** (4 types, audit trail, PROPOSED flow with a human gate) — *what* we want to achieve
- **Action audit** (action_audit.jsonl per record) — *what* happened
- **Decision traces** (episode-based) — *how* decisions were made
- **Bulletin board** (cognitive_bulletin.jsonl) — *facts/notes*
- **Knowledge index** (knowledge_index.jsonl, MERGE on id) — *external knowledge*

What's missing: **procedural memory**. The `fetch → learn → exam → review`
workflow is guessed from scratch by the planner's ReAct loop every cycle. The
bulletin records that "this is how it's done" as a fact, but that is not a
*reusable procedure* with when-to-use / steps / pitfalls.

A Skill = **a condensate of a successful procedure** that the planner can later
recall instead of reinventing it from scratch.

## Format SKILL.md (agentskills.io compatible)

```markdown
---
name: example-workflow
description: One-line summary (<140 chars)
version: 1
status: production           # draft | sandbox | production | archived
platforms: [maria]           # interop hint - "maria", "hermes", "*"
created_at: 2026-05-15T19:30:00+02:00
updated_at: 2026-05-15T19:30:00+02:00
created_by: teacher          # teacher | user | k12 | manual
source_episode_ids:          # decision_traces.jsonl episodes that birthed this
  - ep-abc123-def456
trigger_count: 5             # how many successful runs led to extraction
tags: [learning, fetch]
---

## When to Use

[Concrete trigger conditions. When does this skill apply?]

## Procedure

[Step-by-step. Each step is a planner-actionable item or a sub-skill reference.]
1. ...
2. ...
3. ...

## Pitfalls

[Known failure modes from past runs. Defensive checks.]

## Verification

[How to know the skill worked. Concrete observables.]
```

## L0 / L1 / L2 progressive disclosure (Hermes idea)

- **L0** — YAML frontmatter only (~200 tokens). Loaded into the planner *always*
  as a catalog: "Maria knows this skill exists, what it's for, and its status".
- **L1** — the full SKILL.md (~2-5K tokens). On-demand when the planner decides
  this skill is relevant to the current goal.
- **L2** — referenced external files (e.g. `examples/`, `tests/`). Optional,
  loaded only when the planner explicitly requests them.

## Storage layout

```
meta_data/skills/
  index.jsonl                          # L0 catalog (one line per skill)
  <skill_id>/
    SKILL.md                           # L1 full content
    examples/                          # L2 optional
    tests/                             # L2 optional (e.g. expected outputs)
  archive/                             # archived skills (rollback path)
    <timestamp>/
      <skill_id>/
        SKILL.md
```

**index.jsonl** is derived/cache (ADR-001 pattern). Single source = SKILL.md
files. The index is rebuilt from the files on startup and on save.

## SkillStatus lifecycle

```
DRAFT --(human approve)--> SANDBOX --(N sandbox successes)--> PRODUCTION
  |                            |                                 |
  +-- delete                   +-- demote                         +-- archive
                                    (sandbox failure)                 (stale 90d)
```

- **DRAFT** — created (by the teacher from N successful executions, or manually
  by the project owner). NOT used by the planner. Awaits human review.
- **SANDBOX** — the project owner approved it as "give it a try". The planner may
  use it in sandbox sessions (K2 sandbox). NOT in production.
- **PRODUCTION** — the sandbox success rate exceeded a threshold (e.g. 3/3 or 5/7).
  The project owner approves a second gate — promote() to production. The planner
  uses it in real workflows.
- **ARCHIVED** — stale (default 90d without use) or explicitly archived by the
  project owner. Rollback path: a tar.gz snapshot in `archive/<ts>/`.

**Every transition requires a human gate.** This preserves ADR-010 (sandbox-first)
and ADR-011 (goals as data, audit trail), extended to skills.

## Trigger: when the teacher creates a DRAFT skill

Hermes: after 5+ tool calls, error recovery, user correction, a non-trivial workflow.

Maria: after **N successful executions of the same goal-action sequence** in the
trace log. Specifically:
- N=5 successful executions in the last 30 days
- A sequence of at least 2 actions (a single action = not a skill, that's already trivial)
- Episode traces available (ADR-022)

Implementation: `agent_core/teacher/skill_extractor.py` (Phase 2/3).
Reads `meta_data/decision_traces.jsonl`, finds recurring patterns, and generates
a DRAFT SKILL.md via NIM (not cloud, per ADR-008). The project owner gets a notification.

## Skill schema (JSON Schema for the YAML frontmatter)

```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "title": "Maria Skill Frontmatter",
  "type": "object",
  "required": ["name", "description", "version", "status", "created_at", "created_by"],
  "properties": {
    "name": {"type": "string", "pattern": "^[a-z0-9-]+$", "maxLength": 64},
    "description": {"type": "string", "maxLength": 140},
    "version": {"type": "integer", "minimum": 1},
    "status": {"enum": ["draft", "sandbox", "production", "archived"]},
    "platforms": {"type": "array", "items": {"type": "string"}},
    "created_at": {"type": "string", "format": "date-time"},
    "updated_at": {"type": "string", "format": "date-time"},
    "created_by": {"type": "string"},
    "source_episode_ids": {"type": "array", "items": {"type": "string"}},
    "trigger_count": {"type": "integer", "minimum": 0},
    "tags": {"type": "array", "items": {"type": "string"}}
  }
}
```

**Required markdown sections** (after the YAML frontmatter):
- `## When to Use` (1+ paragraph)
- `## Procedure` (numbered list, 1+ items)
- `## Pitfalls` (optional, but recommended)
- `## Verification` (1+ paragraph)

Validator: if any required section is empty → the skill is INVALID and won't load
into the runtime, but the file stays on disk (manual fix path).

## Integration points (Phase 2/3, future)

| Module | What it does with Skills |
|-------|------------------|
| `agent_core/teacher/skill_extractor.py` | Reads decision_traces, generates a DRAFT |
| `agent_core/planner/` | Loads the L0 catalog at startup, requests L1 on-demand |
| `agent_core/sandbox/` | Executes SANDBOX skills in a sandbox session |
| `agent_core/bulletin/` | Notifies the project owner when a DRAFT/SANDBOX awaits approval |
| `agent_core/critic/` | Audits skill output (analogous to the current critique) |
| `agent_core/telegram/` | Commands: `/skills`, `/skill_approve <id>`, `/skill_archive <id>` |
| `maria_ui/` | Skills view, approve/reject UI buttons |

## ADR-030 (LANDED 2026-05-16 as Phase M in ROADMAP v2.2, entry in the ARCHITECTURE.md ADR table)

**ADR-030: Skills as artifact (procedural memory, Hermes-inspired, Maria-gated)**
- Skills = procedural memory filling the gap between goals (the objective) and traces (how it went)
- SKILL.md format compatible with agentskills.io (cross-agent portability)
- L0/L1/L2 progressive disclosure (a sensible Hermes pattern)
- Lifecycle DRAFT→SANDBOX→PRODUCTION→ARCHIVED, **every transition a human gate**
- We do NOT adopt Hermes autonomous create (conflicts with ADR-010/011)
- We do NOT adopt Hermes GEPA cloud-heavy (conflicts with ADR-008)
- Storage in `meta_data/skills/`, JSONL index derived from SKILL.md files (ADR-001)

## Phase 1 scope (2026-05-15)

**In scope:**
- ✓ Design doc (this file)
- ✓ `agent_core/skills/__init__.py`
- ✓ `agent_core/skills/skill_model.py` — Skill dataclass, SkillStatus enum, parser
- ✓ `agent_core/skills/schema.py` — JSON Schema validator
- ✓ `agent_core/skills/skill_store.py` — load/save with the storage layout, L0 catalog
- ✓ `agent_core/skills/skill_manager.py` — create_draft, patch, promote (human gate)
- ✓ Tests for each module (~30 unit tests)
- ✓ Commit Phase 1

**Out of scope (Phase 2/3):**
- skill_extractor.py (teacher trigger after N successes)
- Planner integration (L0 catalog read, L1 on-demand)
- Sandbox K2 integration (execute SANDBOX skills in a sandbox session)
- Telegram commands (/skills, /skill_approve)
- Web UI Skills view
- ADR-030 entry in ARCHITECTURE.md (LANDED 2026-05-16, Phase M, ROADMAP v2.2)

## Open questions — answered 2026-05-15 (project owner gate review)

1. **N threshold for DRAFT extraction**: **5 successful in 30d** (we keep the default).
2. **Sandbox success rate for promote**: **5/7 with zero critical failures + explicit project-owner approval**. For critical/safety-affecting skills: **3/3 with zero failures + manual log review**.
3. **Stale archive threshold**: **90d** for PRODUCTION skills; **30d** for SANDBOX/DRAFT skills that were never used.
4. **Who can create a DRAFT**: **teacher + manual** for now. K12 may propose later — through the same DRAFT gate. The project owner can create drafts from chat or manually.
5. **SKILL.md language**: **EN** for frontmatter/name/tags (interop with agentskills.io); a bilingual body is allowed for Maria-internal skills (PL notes OK), but `description` must be EN, ≤140 characters.
