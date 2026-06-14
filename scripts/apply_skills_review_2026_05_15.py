"""Apply Eryk Skills gate review (2026-05-15 batch).

Idempotent executor: creates canonical meta-goal skill, promotes 7
DRAFTs to SANDBOX, archives 17 duplicates. Matches review IDs by
slug-prefix (review IDs have random uuid suffixes from yesterday's
in-memory smoke; actual store IDs are different but slug prefixes
align deterministically).

Run from repo root:
    python -m scripts.apply_skills_review_2026_05_15
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from agent_core.skills.skill_manager import SkillManager
from agent_core.skills.skill_model import Skill, SkillStatus
from agent_core.skills.skill_store import SkillStore


REVIEW_DATE = "2026-05-15"
APPROVER = "eryk"
SKILLS_ROOT = Path("meta_data/skills")

# IDs as quoted by Eryk's review file. Goal-patterns include the
# random uuid suffix from yesterday's smoke; actions are just names.
PROMOTE_SANDBOX_REVIEW_IDS: List[str] = [
    "goal-pattern-autoanaliza-stanu-d0e89062",
    "goal-pattern-nauka-nowego-materialu-b4014b71",
    "action-creative-reliable",
    "action-review-reliable",
    "action-evaluate-reliable",
    "action-noop-reliable",
    "action-self-analyze-reliable",
]

ARCHIVE_DUPLICATES: List[Tuple[str, str]] = [
    ("goal-pattern-przerwij-stagnacje-poprzez-wprowadzen-7de1767c",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
    ("goal-pattern-stymulacja-postepu-poprzez-nowe-wyzwa-e443610a",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
    ("goal-pattern-nauka-autonomous-learning-strategies-3edc0997",
     "duplicate: creative/noop meta-goal variant, not a concrete autonomous-learning procedure"),
    ("goal-pattern-aktywacja-procesu-uczenia-sie-przez-w-e9447ac2",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
    ("goal-pattern-aktywacja-nowych-zrodel-danych-dla-re-e7ef1d50",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
    ("goal-pattern-wprowadz-nowe-bodzce-uczenia-sie-aby-ed292faa",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
    ("goal-pattern-break-stagnation-via-targeted-explora-3e58bd4e",
     "duplicate: English variant of same stagnation-breaking creative pattern"),
    ("goal-pattern-zwiekszenie-roznorodnosci-danych-tren-bee6327b",
     "duplicate: too metric-specific, belongs inside generic meta-goal skill"),
    ("goal-pattern-dynamic-knowledge-reconfiguration-to-30ce9f1e",
     "duplicate: English variant, too abstract as standalone skill"),
    ("goal-pattern-reaktywacja-procesu-uczenia-sie-643f3142",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
    ("goal-pattern-reaktywacja-uczenia-sie-poprzez-ident-8a6ea893",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
    ("goal-pattern-aktywuj-protokol-rozwoju-dynamicznego-a2127ea2",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
    ("goal-pattern-wprowadz-nowe-dane-do-systemu-aby-prz-70de6982",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
    ("goal-pattern-reintrodukcja-dynamicznych-bodzcow-uc-f17fea48",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
    ("goal-pattern-aktywacja-postepu-przez-optymalizacje-424fd0b2",
     "noisy: NOOP-optimization phrasing is dangerous as standalone skill"),
    ("goal-pattern-wprowadz-nowe-dane-i-wyzwania-bb10ec4c",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
    ("goal-pattern-wprowadz-nowosci-aby-zainicjowac-post-ef9428fc",
     "duplicate: merged into meta-goal-creative-stagnation-breaker"),
]


CANONICAL_NAME = "meta-goal-creative-stagnation-breaker"
CANONICAL_DESCRIPTION = (
    "Break learning stagnation with bounded novelty, creative "
    "exploration, and explicit verification."
)
CANONICAL_SECTIONS: Dict[str, str] = {
    "When to Use": (
        "Use this skill when Maria detects repeated low novelty, "
        "repeated goal loops, stalled learning velocity, or meta-goals "
        "such as breaking stagnation, adding new learning stimuli, "
        "increasing data diversity, or reactivating learning.\n\n"
        "Do not use this skill as a substitute for concrete task "
        "execution. It is a recovery/planning procedure for stagnation, "
        "not a generic progress marker."
    ),
    "Procedure": (
        "1. Identify the stagnation signal: repeated goal, repeated "
        "action type, low novelty, low learning velocity, failed "
        "exam/learn loop, or no meaningful state change.\n"
        "2. Select one bounded novelty source: new local file group, "
        "new safe knowledge domain, new test scenario, new evaluation "
        "question, or new comparison against existing beliefs.\n"
        "3. Propose exactly one concrete sandbox action that can create "
        "measurable novelty.\n"
        "4. If observation is required before acting, perform a "
        "deliberate NOOP/wait only with an explicit reason and expected "
        "observation.\n"
        "5. Execute the bounded action in sandbox.\n"
        "6. Record the result in action audit / decision trace.\n"
        "7. Verify whether novelty or progress actually increased.\n"
        "8. If no improvement occurs, escalate to user or propose a "
        "different source; do not repeat the same pattern endlessly."
    ),
    "Pitfalls": (
        "- Do not count NOOP as progress by itself.\n"
        "- Do not create endless creative loops with no external data "
        "or verification.\n"
        "- Do not promote generated skills directly to production.\n"
        "- Do not use this skill to bypass learning/exam parser "
        "failures; fix the underlying bug first.\n"
        "- Avoid creating many near-duplicate goal-pattern skills from "
        "wording variants."
    ),
    "Verification": (
        "The skill worked if at least one measurable state change "
        "occurred: new knowledge indexed, new test/evaluation "
        "generated, a stale loop broken, a different action path "
        "selected, or a clear needs_human/failure reason recorded "
        "instead of repeating the same cycle."
    ),
}


_HEX_SUFFIX = re.compile(r"-[0-9a-f]{8}$")


def review_id_to_name(review_id: str) -> str:
    """Strip yesterday's random uuid suffix to recover stable name."""
    return _HEX_SUFFIX.sub("", review_id)


def find_by_name(store: SkillStore, name: str) -> List[Skill]:
    return [s for s in store.list_all() if s.frontmatter.name == name]


def main() -> int:
    SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    store = SkillStore(root=SKILLS_ROOT)
    store.load()
    mgr = SkillManager(store=store)

    report: Dict[str, List[str]] = {
        "canonical": [],
        "promoted": [],
        "promote_skipped": [],
        "promote_unmatched": [],
        "archived": [],
        "archive_skipped": [],
        "archive_unmatched": [],
        "mapping": [],
    }

    print(f"\n=== Apply Skills Review {REVIEW_DATE} ===\n")
    print(f"Approver: {APPROVER}")
    print(f"Store root: {SKILLS_ROOT}")
    print(f"Initial skills loaded: {len(store.list_all())}\n")

    # ----------------------------------------------------------------
    # 1. Canonical skill: create as DRAFT then promote to SANDBOX
    # ----------------------------------------------------------------
    existing_canonical = find_by_name(store, CANONICAL_NAME)
    if existing_canonical:
        skill = existing_canonical[0]
        if skill.frontmatter.status == SkillStatus.SANDBOX:
            print(f"[skip] canonical '{CANONICAL_NAME}' already SANDBOX "
                  f"(id={skill.skill_id})")
            report["canonical"].append(f"already-sandbox:{skill.skill_id}")
        else:
            print(f"[promote] canonical '{CANONICAL_NAME}' "
                  f"{skill.frontmatter.status.value} -> sandbox")
            promoted = mgr.promote(skill.skill_id, approved_by=APPROVER)
            report["canonical"].append(f"promoted:{promoted.skill_id}")
    else:
        print(f"[create] canonical '{CANONICAL_NAME}' as DRAFT then promote")
        draft = mgr.create_draft(
            name=CANONICAL_NAME,
            description=CANONICAL_DESCRIPTION,
            sections=CANONICAL_SECTIONS,
            created_by="manual",
            tags=["meta-goal", "stagnation", "creative", "novelty", "sandbox"],
        )
        promoted = mgr.promote(draft.skill_id, approved_by=APPROVER)
        report["canonical"].append(f"created+promoted:{promoted.skill_id}")
        print(f"        created skill_id={promoted.skill_id} "
              f"status={promoted.frontmatter.status.value}")

    # ----------------------------------------------------------------
    # 2. Promote 7 DRAFTs -> SANDBOX
    # ----------------------------------------------------------------
    print("\n--- Promote DRAFT -> SANDBOX ---")
    for review_id in PROMOTE_SANDBOX_REVIEW_IDS:
        name = review_id_to_name(review_id)
        matches = find_by_name(store, name)
        if not matches:
            print(f"[unmatched] review_id={review_id} (name={name}) not in store")
            report["promote_unmatched"].append(review_id)
            continue
        # Should be exactly 1 unless extractor produced collisions
        for skill in matches:
            report["mapping"].append(f"{review_id} -> {skill.skill_id}")
            if skill.frontmatter.status == SkillStatus.SANDBOX:
                print(f"[skip] {skill.skill_id} already SANDBOX")
                report["promote_skipped"].append(skill.skill_id)
                continue
            if skill.frontmatter.status != SkillStatus.DRAFT:
                print(f"[skip] {skill.skill_id} status="
                      f"{skill.frontmatter.status.value} (expected DRAFT)")
                report["promote_skipped"].append(skill.skill_id)
                continue
            promoted = mgr.promote(skill.skill_id, approved_by=APPROVER)
            print(f"[promote] {skill.skill_id} DRAFT -> "
                  f"{promoted.frontmatter.status.value}")
            report["promoted"].append(promoted.skill_id)

    # ----------------------------------------------------------------
    # 3. Archive 17 duplicates
    # ----------------------------------------------------------------
    print("\n--- Archive duplicates ---")
    for review_id, reason in ARCHIVE_DUPLICATES:
        name = review_id_to_name(review_id)
        matches = find_by_name(store, name)
        if not matches:
            print(f"[unmatched] review_id={review_id} (name={name}) not in store")
            report["archive_unmatched"].append(review_id)
            continue
        for skill in matches:
            report["mapping"].append(f"{review_id} -> {skill.skill_id}")
            if skill.frontmatter.status == SkillStatus.ARCHIVED:
                print(f"[skip] {skill.skill_id} already ARCHIVED")
                report["archive_skipped"].append(skill.skill_id)
                continue
            mgr.archive(skill.skill_id, approved_by=APPROVER, reason=reason)
            print(f"[archive] {skill.skill_id} -> ARCHIVED ({reason[:60]}...)")
            report["archived"].append(skill.skill_id)

    # ----------------------------------------------------------------
    # 4. Final summary
    # ----------------------------------------------------------------
    print("\n=== Summary ===")
    print(f"Canonical: {report['canonical']}")
    print(f"Promoted ({len(report['promoted'])}): {report['promoted']}")
    print(f"Promote skipped (already done): {report['promote_skipped']}")
    print(f"Promote unmatched: {report['promote_unmatched']}")
    print(f"Archived ({len(report['archived'])}): "
          f"{[a for a in report['archived']]}")
    print(f"Archive skipped: {report['archive_skipped']}")
    print(f"Archive unmatched: {report['archive_unmatched']}")
    print(f"\nFinal store skills: {len(store.list_all())}")
    print(f"  - DRAFT: {sum(1 for s in store.list_all() if s.frontmatter.status == SkillStatus.DRAFT)}")
    print(f"  - SANDBOX: {sum(1 for s in store.list_all() if s.frontmatter.status == SkillStatus.SANDBOX)}")
    print(f"  - PRODUCTION: {sum(1 for s in store.list_all() if s.frontmatter.status == SkillStatus.PRODUCTION)}")
    print(f"  - ARCHIVED: {sum(1 for s in store.list_all() if s.frontmatter.status == SkillStatus.ARCHIVED)}")

    # Write mapping log for audit trail. Append-only to preserve earlier runs.
    # First run gets the initial header; subsequent runs append a separator.
    mapping_log = SKILLS_ROOT / f"review_{REVIEW_DATE}_mapping.txt"
    new_section = (
        f"\n\n# --- run at {datetime.now(timezone.utc).isoformat()} "
        f"(approver={APPROVER}) ---\n"
        + "\n".join(report["mapping"])
    )
    if mapping_log.exists():
        with mapping_log.open("a", encoding="utf-8") as fp:
            fp.write(new_section)
    else:
        mapping_log.write_text(
            "# Eryk skills review mapping (review_id -> store_id)\n"
            f"# First applied: {datetime.now(timezone.utc).isoformat()}\n"
            f"# Approver: {APPROVER}\n"
            f"# Source: scripts/apply_skills_review_2026_05_15.py"
            + new_section,
            encoding="utf-8",
        )
    print(f"\nMapping log: {mapping_log}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
