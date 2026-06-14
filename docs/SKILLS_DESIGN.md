# Skills as artifact — design (Hermes-inspired)

> Inspirowane: Hermes Agent (Nous Research, MIT, luty 2026). Format SKILL.md
> kompatybilny z agentskills.io. **Promote() flow Maria-style** (sandbox-first,
> human gate) — NIE Hermes autonomous create.
>
> Decyzja: 2026-05-15 (Eryk wybór "zaczynamy od Skills as artifact, pelna Faza 1").
> Postmortem 24h autonomy test (2026-05-14) zostaje w pamięci — wszystko co
> zmienia stan produkcji idzie przez sandbox→promote z PROPOSED flow.

## Po co Mariji Skills

Maria ma już:
- **Goals as data** (4 typy, audit trail, PROPOSED flow z human gate) — *co* chcemy osiągnąć
- **Action audit** (action_audit.jsonl per record) — *co* się stało
- **Decision traces** (episode-based) — *jak* się decydowało
- **Bulletin board** (cognitive_bulletin.jsonl) — *fakty/notatki*
- **Knowledge index** (knowledge_index.jsonl, MERGE on id) — *wiedza zewnętrzna*

Czego brakuje: **procedural memory**. Workflow `fetch → learn → exam → review`
co cykl planner ReAct zgaduje od zera. Bulletin notuje że "tak się robi" jako
fakt, ale to nie jest *reusable procedure* z when-to-use / steps / pitfalls.

Skill = **kondensat udanej procedury** którą planner może później przywołać
zamiast wymyślać od zera.

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

- **L0** — tylko YAML frontmatter (~200 tokenów). Załadowane do planner *zawsze*
  jako catalog: "Maria wie że ten skill istnieje, do czego, jaki status".
- **L1** — pełen SKILL.md (~2-5K tokenów). On-demand kiedy planner decyduje
  że ten skill jest relevantny dla bieżącego goal.
- **L2** — zewnętrzne pliki referenced (np. `examples/`, `tests/`). Opcjonalne,
  ładowane tylko jak planner explicitly request.

## Storage layout

```
meta_data/skills/
  index.jsonl                          # L0 catalog (one line per skill)
  <skill_id>/
    SKILL.md                           # L1 full content
    examples/                          # L2 optional
    tests/                             # L2 optional (np. expected outputs)
  archive/                             # archived skills (rollback path)
    <timestamp>/
      <skill_id>/
        SKILL.md
```

**index.jsonl** jest derived/cache (ADR-001 pattern). Single source = SKILL.md
files. Index rebuilt z files na startup + on save.

## SkillStatus lifecycle

```
DRAFT --(human approve)--> SANDBOX --(N sandbox successes)--> PRODUCTION
  |                            |                                 |
  +-- delete                   +-- demote                         +-- archive
                                    (sandbox failure)                 (stale 90d)
```

- **DRAFT** — utworzone (przez teacher z N successful executions, albo manually
  przez Eryka). NIE używane przez planner. Czeka na human review.
- **SANDBOX** — Eryk approved jako "spróbuj". Planner może użyć w sandbox sessions
  (K2 sandbox). NIE w production.
- **PRODUCTION** — sandbox success rate przekroczył threshold (np. 3/3 lub 5/7).
  Eryk approve drugiego gate'a — promote() do production. Planner używa w real
  workflows.
- **ARCHIVED** — stale (default 90d bez używania) lub explicit Eryk archive.
  Rollback path: tar.gz snapshot w `archive/<ts>/`.

**Każde przejście wymaga human gate.** To zachowuje ADR-010 (sandbox-first) i
ADR-011 (goals as data, audit trail) z extension na skills.

## Trigger: kiedy teacher tworzy DRAFT skill

Hermes: po 5+ tool calls, error recovery, user correction, non-trivial workflow.

Maria: po **N successful executions tego samego goal-action sequence** w trace
log. Konkretnie:
- N=5 successful executions w ostatnich 30 dniach
- Sekwencja co najmniej 2 actions (single action = nie skill, to już prosty)
- Episode traces dostępne (ADR-022)

Implementacja: `agent_core/teacher/skill_extractor.py` (Faza 2/3).
Czyta `meta_data/decision_traces.jsonl`, znajduje powtarzalne wzorce, generuje
DRAFT SKILL.md przez NIM (nie cloud, per ADR-008). Eryk dostaje notification.

## Skill schema (JSON Schema dla YAML frontmatter)

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

**Wymagane sekcje markdown** (po YAML frontmatter):
- `## When to Use` (1+ paragraph)
- `## Procedure` (numbered list, 1+ items)
- `## Pitfalls` (optional, ale recommended)
- `## Verification` (1+ paragraph)

Validator: jeśli któraś required section pusta → skill INVALID, nie ładuje się do
runtime, ale plik na disk zostaje (manual fix path).

## Integration points (Faza 2/3, nie dziś)

| Moduł | Co robi z Skills |
|-------|------------------|
| `agent_core/teacher/skill_extractor.py` | Czyta decision_traces, generuje DRAFT |
| `agent_core/planner/` | Wczytuje L0 catalog na start, request L1 on-demand |
| `agent_core/sandbox/` | Wykonuje SANDBOX skills w sandbox session |
| `agent_core/bulletin/` | Notify Eryk gdy DRAFT/SANDBOX czeka na approval |
| `agent_core/critic/` | Audit skill output (analogiczne do current critique) |
| `agent_core/telegram/` | Komendy: `/skills`, `/skill_approve <id>`, `/skill_archive <id>` |
| `maria_ui/` | Skills view, approve/reject UI buttons |

## ADR-030 (LANDED 2026-05-16 jako Faza M w ROADMAP v2.2, entry w ARCHITECTURE.md ADR table)

**ADR-030: Skills as artifact (procedural memory, Hermes-inspired, Maria-gated)**
- Skills = procedural memory wypełniający lukę między goals (cel) i traces (jak było)
- Format SKILL.md compatible z agentskills.io (cross-agent portability)
- L0/L1/L2 progressive disclosure (Hermes pattern, sensible)
- Lifecycle DRAFT→SANDBOX→PRODUCTION→ARCHIVED, **każde przejście human gate**
- NIE adoptujemy Hermes autonomous create (kłóci się z ADR-010/011)
- NIE adoptujemy Hermes GEPA cloud-heavy (kłóci się z ADR-008)
- Storage `meta_data/skills/`, JSONL index derived from SKILL.md files (ADR-001)

## Faza 1 scope (DZISIAJ 2026-05-15)

**W zakresie:**
- ✓ Design doc (ten plik)
- ✓ `agent_core/skills/__init__.py`
- ✓ `agent_core/skills/skill_model.py` — Skill dataclass, SkillStatus enum, parser
- ✓ `agent_core/skills/schema.py` — JSON Schema validator
- ✓ `agent_core/skills/skill_store.py` — load/save z storage layout, L0 catalog
- ✓ `agent_core/skills/skill_manager.py` — create_draft, patch, promote (human gate)
- ✓ Tests dla każdego modułu (~30 unit tests)
- ✓ Commit Phase 1

**Poza zakresem (Faza 2/3):**
- skill_extractor.py (teacher trigger po N successes)
- Planner integration (L0 catalog read, L1 on-demand)
- Sandbox K2 integration (execute SANDBOX skills in sandbox session)
- Telegram commands (/skills, /skill_approve)
- Web UI Skills view
- ADR-030 entry w ARCHITECTURE.md (LANDED 2026-05-16 Faza M, ROADMAP v2.2)

## Open questions — answered 2026-05-15 (Eryk gate review)

1. **N threshold dla DRAFT extraction**: **5 successful w 30d** (default trzymamy).
2. **Sandbox success rate dla promote**: **5/7 zero critical failures + explicit Eryk approval**. Dla skills krytycznych/safety-affecting: **3/3 zero failures + manual log review**.
3. **Stale archive threshold**: **90d** dla PRODUCTION skills; **30d** dla SANDBOX/DRAFT które nigdy nie zostały użyte.
4. **Kto może tworzyć DRAFT**: **teacher + manual** teraz. K12 może proponować później — przez tę samą DRAFT gate. Eryk z chat/manual może tworzyć drafty.
5. **Język SKILL.md**: **EN** dla frontmatter/name/tags (interop z agentskills.io); body bilingual dozwolony dla Maria internal skills (PL notes OK), ale `description` musi być EN ≤140 znaków.

Zastosowane w batchu 2026-05-15 (24 DRAFTs → 1 canonical + 7 SANDBOX + 17 archived) przez `scripts/apply_skills_review_2026_05_15.py`. Mapping audyt: `meta_data/skills/review_2026-05-15_mapping.txt`.

Follow-up (osobny commit): refactor `goal_pattern_to_candidate` w `agent_core/teacher/skill_extractor.py` żeby generował EN-only slugs (`goal-pattern-<dominant_actions>-<episode_band>`) zamiast slugify PL `goal_description`. Aktualne PL slugi w storze są historical artifact tej batch i zostają jako-są.
