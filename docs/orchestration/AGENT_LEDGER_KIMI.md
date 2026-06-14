# Agent Ledger — Kimi 2.6

Append-only journal of Kimi 2.6's observed behaviour. Master writes here after every Kimi-involving task that produces a signal worth keeping.

**Worker:** Kimi 2.6 (Moonshot AI).
**Access:** to be confirmed during T-002 — possible paths: Moonshot API directly, a local CLI wrapper, or routing through M.A.R.I.A.'s NIM-style infrastructure as a separate provider.
**Rate limit:** TBD.
**Billing:** token-flat under Eryk's subscription (to be verified).
**Native cross-check features:** TBD; if absent, cross-check is done by master running two parallel sessions.

---

## Skill profile (running summary)

Maintained by the master; rewrite the bullets as evidence accumulates.

**Strengths (working hypothesis):**
- Long-context tasks (Kimi has historically had large context windows).
- Tasks where Codex underperforms — useful as a different-perspective second opinion.

**Weaknesses (working hypothesis):**
- Unknown for now. Common failure modes for large-context models: rephrasing names, drifting toward generic patterns over project-specific conventions, hallucinating imports.

**Preferred task types (working hypothesis):**
- Tasks where a lot of code or documentation must be in context simultaneously.
- Tasks requiring synthesis across many files.

**Anti-recommended task types (working hypothesis):**
- Tasks with strict naming or style invariants that the worker must not deviate from.

These bullets are placeholders until the first 5–10 ledger entries refine them.

---

## Log format

Each entry:

```
### YYYY-MM-DD — T-NNN — <one-line outcome>
- Result: accepted | rejected | cross-check-winner | cross-check-loser
- Surprise: <one line; what was unexpected, good or bad>
- Pattern: <one line; tag if this fits a known pattern; or "new pattern: <name>">
- Cost in master time: <quick / medium / heavy>
- Cross-check pair: <T-NNN id if cross-check, otherwise n/a>
- Notes: <free text, brief>
```

Order: most recent first.

---

## Log

*(empty — first entry will land when T-002 runs)*

---

## Cross-check tally

Track Kimi vs the other worker on directly comparable tasks.

| Date | T-NNN | Other worker | Kimi result | Other result | Pick | Why |
|------|-------|--------------|-------------|--------------|------|-----|

*(empty)*

---

## Hallucination patterns observed

Catalogue of recurring hallucinations so the master can pre-empt them in future briefs.

| Pattern | First observed | Trigger | Mitigation in brief |
|---------|----------------|---------|---------------------|

*(empty)*

---

*Append, never edit history. Skill profile section is exempt — it is a running summary, not history.*
