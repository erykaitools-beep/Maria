"""Documentation drift-guard immune test (plank 10, 2026-06-06).

Auto-runs scripts/doc_lint.py against the live docs so a future change that
desyncs an authoritative doc from the code -- a stale tick-phase count, a moved
code path, a module added/removed without touching the CLAUDE.md tree -- fails
the suite instead of misleading the next reader (human or Maria). If
`test_no_doc_drift` fails, run `python scripts/doc_lint.py` for the per-doc
detail.

The remaining tests prove the lint's detection actually fires -- a linter that
silently passes everything is worse than none.
"""
import importlib.util
import os

import pytest

_LINT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "doc_lint.py"
)
_spec = importlib.util.spec_from_file_location("doc_lint", _LINT_PATH)
doc_lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doc_lint)


def test_no_doc_drift():
    issues = doc_lint.run_lint()
    assert issues == [], "doc_lint found issues:\n" + "\n".join(
        f"  {n} [{k}] {d}" for n, k, d in issues
    )


# --- check A: tick-phase count -------------------------------------------------

def test_canonical_count_collapses_subphases():
    # 8.5 / 9.5 are additions WITHIN a top-level phase -> collapse onto integers
    text = "# PHASE 1: A\n  # PHASE 8.5: B\n# PHASE 9: C\n# PHASE 9.6: D\n# PHASE 19: E\n"
    nums = {int(n) for n in doc_lint._PHASE_MARKER.findall(text)}
    assert nums == {1, 8, 9, 19}


def test_live_phase_count_parses():
    # the marker still matches the live loop; 19 top-level phases as of plank 10
    count, nums = doc_lint.canonical_phase_count()
    assert count == len(nums)
    assert count >= 19


def test_phase_decl_extracts_count():
    assert doc_lint._PHASE_DECL.findall("Homeostasis tick loop (19 faz)") == ["19"]
    assert doc_lint._PHASE_DECL.findall("tick loop 19 phases") == ["19"]


def test_meta_lines_are_not_read_as_declarations():
    # sentences ABOUT the drift history must be skipped, not read as current claims
    assert doc_lint._META_MARKERS.search("kod ma 19 faz, nie 11 jak kiedys")
    assert doc_lint._META_MARKERS.search("CLAUDE.md '17 faz' -> 19")
    assert doc_lint._META_MARKERS.search("ARCHITECTURE mowi 11 faz (kwiecien)")
    # a genuine declaration carries no meta marker -> it IS checked
    assert not doc_lint._META_MARKERS.search("Homeostasis tick loop (19 faz)")


def test_phase_claim_requires_tick_context():
    # a "N faz" count only counts as a tick claim when tied to the loop
    assert doc_lint._TICK_CONTEXT.search("tick loop has 19 faz")
    assert doc_lint._TICK_CONTEXT.search("petla 1Hz z 19 fazami")
    assert not doc_lint._TICK_CONTEXT.search("5 faz eksperymentu (K11)")


# --- check B: stale code paths -------------------------------------------------

def test_code_path_regexes():
    assert doc_lint._CODE_FILE.findall("see `agent_core/homeostasis/core.py` here") == [
        "agent_core/homeostasis/core.py"
    ]
    assert doc_lint._CODE_DIR.findall("the agent_core/planner/ module") == [
        "agent_core/planner"
    ]


# --- check C: module tree <-> filesystem --------------------------------------

def test_tree_modules_parses_nested_only():
    src = (
        "```\n"
        "project/\n"
        "|-- maria.py          # launcher\n"
        "|-- agent_core/       # subsystems\n"
        "│   ├── homeostasis/  # tick loop\n"
        "│   ├── llm/          # routing (tools/invoke noted)\n"
        "│   └── tests/        # suite\n"
        "```\n"
    )
    # only rail-prefixed (nested) lines are agent_core modules; the comment's
    # "tools/invoke" must not leak in, and top-level entries are skipped
    assert doc_lint.tree_modules(src) == {"homeostasis", "llm", "tests"}


@pytest.mark.skipif(not os.path.isfile(doc_lint.CLAUDE_MD),
                    reason="CLAUDE.md is gitignored; tree check needs it present")
def test_tree_matches_filesystem():
    # the live invariant check C enforces, stated explicitly
    tree = doc_lint.tree_modules(doc_lint._read(doc_lint.CLAUDE_MD))
    assert tree == doc_lint.fs_modules()


# --- scope ---------------------------------------------------------------------

def test_non_living_docs_excluded():
    living = {os.path.basename(p).lower() for p in doc_lint.living_docs()}
    assert "changelog.md" not in living
    assert not any("_plan" in n or "_spec" in n or "_tasks" in n for n in living)
    if os.path.isfile(doc_lint.CLAUDE_MD):
        assert "claude.md" in living  # current-state doc IS checked (when present)
