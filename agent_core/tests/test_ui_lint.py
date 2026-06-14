"""Web UI immune test (split-brain/Tor-C follow-up, 2026-05-30).

Auto-runs scripts/ui_lint.py against the live Web UI so a future refactor that
breaks a rarely-opened page (dead `moFetch` helper, stale element id, dead
/api endpoint -- the classes the Web UI v2 extraction left behind) fails the
suite instead of rotting in production. If `test_no_ui_breakage` fails, run
`python scripts/ui_lint.py` for the per-file detail.

The remaining tests prove the lint's detection actually fires -- a linter that
silently passes everything is worse than none.
"""
import importlib.util
import os

_LINT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "ui_lint.py"
)
_spec = importlib.util.spec_from_file_location("ui_lint", _LINT_PATH)
ui_lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui_lint)


def test_no_ui_breakage():
    issues = ui_lint.run_lint()
    assert issues == [], "Web UI lint found issues:\n" + "\n".join(
        f"  {n} [{k}] {d}" for n, k, d in issues
    )


def test_lint_detects_dead_helper():
    # moFetch used but not defined -> flagged; defining it (profile.js alias) -> ok
    assert ui_lint._MOFETCH_USE.search("moFetch('/api/x')")
    assert not ui_lint._MOFETCH_DEF.search("moFetch('/api/x')")
    assert ui_lint._MOFETCH_DEF.search("const moFetch = (u, o) => MariaUI.apiFetch(u, o);")


def test_lint_counts_created_ids_to_avoid_false_positive():
    # getElementById ref is detected...
    assert ui_lint._js_id_refs("document.getElementById('ghost')") == {"ghost"}
    # ...but a `.id = 'x'` assignment counts as created (the chat.js typingIndicator case),
    # so a dynamically-built element is not falsely flagged as stale.
    assert "typingIndicator" in ui_lint._js_created_ids("ind.id = 'typingIndicator';")


def test_lint_detects_dead_endpoint():
    assert not ui_lint._url_known("/api/does-not-exist", {"/api/status"})
    assert ui_lint._url_known("/api/status/full", {"/api/status"})
