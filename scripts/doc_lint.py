#!/usr/bin/env python3
"""
M.A.R.I.A. Documentation Linter (drift guard)

Static checks for docs drifting from code -- the single most persistent defect
across all four project audits. The pattern: a refactor changes the code, the
docs keep describing the old shape, and nobody notices until the docs actively
mislead a future reader (human or Maria herself). This lint is the immune
response: a change that desyncs an authoritative doc from the code fails here
instead of rotting silently. Mirror of scripts/ui_lint.py
(DEVELOPMENT_SEQUENCE.md plank 10).

Scope = "living" docs only -- the ones that claim to describe the system AS IT
IS NOW. History (CHANGELOG, session summaries, snapshots) and plans/specs
(ROADMAP, *_PLAN, *_SPEC, *_TASKS, proposals) legitimately reference past or
future code, so they are NOT checked (see _NON_LIVING). A drift guard that
trips on a changelog entry is noise; nobody would keep it on.

Checks every living doc for:

  A. Tick-phase drift -- the homeostasis tick loop has N distinct top-level
     phases (the `# PHASE N:` markers in core.py; sub-phases like 8.5 / 9.5 are
     additions WITHIN a top-level phase, not separate phases, so they collapse
     onto their integer). Any living doc that declares a tick-phase count
     (e.g. "tick loop (19 faz)") must match. Sentences ABOUT the drift history
     ("kod ma 19 faz, nie 11", "CLAUDE.md '17 faz' -> 19") are skipped via
     _META_MARKERS so the guard does not trip on prose discussing the past.
     (CLAUDE.md said "17 faz" while code ran 19 -- exactly this class.)

  B. Stale code path -- an `agent_core/.../x.py` (or maria_core / maria_ui /
     scripts) file path, or an `agent_core/<pkg>/` directory, mentioned in a
     living doc that does not exist on disk. Catches a "key files" list that
     points at a moved / renamed / deleted file.

  C. Module tree <-> filesystem -- the agent_core/ package list in CLAUDE.md's
     "Struktura projektu" tree must match the real agent_core/*/ packages (dirs
     with __init__.py). Flags both phantom (in tree, not on disk) and
     undocumented (on disk, not in tree).

Out of scope: prose accuracy, semantic staleness, anything beyond the three
mechanical desyncs above. Heuristic flags (esp. A's meta-skip) can misfire on
unusual phrasing -- read the context before "fixing".

Exit codes: 0 = clean, 1 = issues found, 2 = lint could not run.

Usage:
    python scripts/doc_lint.py            # full report
    python scripts/doc_lint.py --quiet    # print only if issues (CI / suite)
"""

import re
import os
import sys
import glob
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PY = os.path.join(ROOT, "agent_core", "homeostasis", "core.py")
CLAUDE_MD = os.path.join(ROOT, "CLAUDE.md")
DOCS_DIR = os.path.join(ROOT, "docs")
AGENT_CORE = os.path.join(ROOT, "agent_core")

# Docs that do NOT describe the current state -> excluded from every check.
# History (changelog / summaries / snapshots) and plans / specs / proposals
# reference past or future code by design, so a mismatch there is not drift.
_NON_LIVING = re.compile(
    r"(changelog|session_summary|snapshot|roadmap|_plan|_tasks|codex_tasks"
    r"|proposal|_spec|_brief|incoming)",
    re.IGNORECASE,
)

# A line is DISCUSSING a phase count (history / correction) rather than
# DECLARING the current one -> skip it in check A.
_META_MARKERS = re.compile(
    r"(nie\s+\d|kwiec|histor|m[oó]wi|says|stale|outdated|drift|regen"
    r"|wcze[sś]niej|by[lł][oa]|->|→|['\"]\s*\d)",
    re.IGNORECASE,
)

# A declaration is only a TICK-phase claim if the line ties it to the tick loop.
_TICK_CONTEXT = re.compile(r"tick|p[eę]tl|loop|homeostas|1hz", re.IGNORECASE)

_PHASE_DECL = re.compile(r"(\d+)\s*(?:faz\w*|phase\w*)", re.IGNORECASE)
_PHASE_MARKER = re.compile(r"^\s*#\s*PHASE\s+(\d+)(?:\.\d+)?\s*:", re.MULTILINE)

_CODE_FILE = re.compile(
    r"(?<![\w./])((?:agent_core|maria_core|maria_ui|scripts)/[\w./-]+\.py)"
)
_CODE_DIR = re.compile(r"(?<![\w./])(agent_core/[a-z_][a-z0-9_]*)/")
_TREE_MODULE = re.compile(r"([a-z_][a-z0-9_]*)/")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def living_docs():
    """CLAUDE.md (if present) + docs/*.md, minus history / plan / spec docs.

    CLAUDE.md is gitignored (machine-local), so it is included only when it
    exists -- on a bare checkout checks A/B still run over the tracked docs.
    """
    paths = [CLAUDE_MD] if os.path.isfile(CLAUDE_MD) else []
    paths += sorted(glob.glob(os.path.join(DOCS_DIR, "*.md")))
    return [p for p in paths if not _NON_LIVING.search(os.path.basename(p))]


def canonical_phase_count():
    """(count, set) of distinct top-level integer tick phases in core.py."""
    nums = {int(n) for n in _PHASE_MARKER.findall(_read(CORE_PY))}
    return len(nums), nums


def fs_modules():
    """agent_core/* packages (dirs carrying __init__.py)."""
    return {
        os.path.basename(os.path.dirname(p))
        for p in glob.glob(os.path.join(AGENT_CORE, "*", "__init__.py"))
    }


def tree_modules(claude_src):
    """agent_core submodules listed in CLAUDE.md 'Struktura projektu' tree.

    Only nested lines (prefixed with the box-drawing '|' rail) are agent_core
    submodules; top-level entries (maria.py, docs/, ...) have no rail and are
    skipped. The module name is the first 'word/' on the line, before any '#'.
    """
    blocks = re.findall(r"```[^\n]*\n(.*?)```", claude_src, re.DOTALL)
    tree = next((b for b in blocks if "agent_core/" in b), "")
    mods = set()
    for line in tree.splitlines():
        if "│" not in line and "|" not in line:
            continue  # not nested under agent_core
        head = line.split("#", 1)[0]
        m = _TREE_MODULE.search(head)
        if m:
            mods.add(m.group(1))
    mods.discard("agent_core")  # the package root, never its own submodule
    return mods


def run_lint():
    """Run all checks. Returns a list of (doc_name, klass, detail) tuples."""
    if not os.path.isfile(CORE_PY):
        raise FileNotFoundError(f"core.py not found: {CORE_PY}")

    issues = []
    n_phases, _ = canonical_phase_count()

    for path in living_docs():
        name = os.path.relpath(path, ROOT)
        text = _read(path)

        # A. tick-phase drift
        for lineno, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if "faz" not in low and "phase" not in low:
                continue
            if not _TICK_CONTEXT.search(line) or _META_MARKERS.search(line):
                continue
            for m in _PHASE_DECL.finditer(line):
                declared = int(m.group(1))
                if declared != n_phases:
                    issues.append((name, "A:phase-drift",
                                   f"L{lineno}: says {declared} tick phases, "
                                   f"code has {n_phases}"))

        # B. stale code paths (files + agent_core dirs)
        for rel in sorted(set(_CODE_FILE.findall(text))):
            if not os.path.exists(os.path.join(ROOT, rel)):
                issues.append((name, "B:stale-file", f"{rel} does not exist"))
        for rel in sorted(set(_CODE_DIR.findall(text))):
            if not os.path.isdir(os.path.join(ROOT, rel)):
                issues.append((name, "B:stale-dir", f"{rel}/ does not exist"))

    # C. module tree <-> filesystem (CLAUDE.md is the authoritative tree).
    # CLAUDE.md is gitignored; on a bare checkout there is no tree to check, so
    # C is skipped rather than failing the whole lint.
    if os.path.isfile(CLAUDE_MD):
        tree = tree_modules(_read(CLAUDE_MD))
        fs = fs_modules()
        for mod in sorted(tree - fs):
            issues.append(("CLAUDE.md", "C:phantom-module",
                           f"tree lists agent_core/{mod}/ but it is not on disk"))
        for mod in sorted(fs - tree):
            issues.append(("CLAUDE.md", "C:undocumented-module",
                           f"agent_core/{mod}/ exists but is missing from the tree"))

    return issues


def main():
    parser = argparse.ArgumentParser(description="M.A.R.I.A. documentation linter")
    parser.add_argument("--quiet", action="store_true",
                        help="print only if issues found (CI / suite)")
    args = parser.parse_args()

    try:
        issues = run_lint()
    except Exception as exc:  # noqa: BLE001 - report any lint failure clearly
        print(f"[doc_lint] ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    if not issues:
        if not args.quiet:
            print("[doc_lint] OK -- docs and code agree "
                  "(tick phases, code paths, module tree).")
        sys.exit(0)

    print(f"[doc_lint] {len(issues)} issue(s) found:")
    for name, klass, detail in issues:
        print(f"  {name:<28} [{klass}] {detail}")
    sys.exit(1)


if __name__ == "__main__":
    main()
