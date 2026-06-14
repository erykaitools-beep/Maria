"""
Mock-hygiene ratchet -- anti-regrowth guard for the spec= sweep (audyt 2026-06-13).

A bare ``MagicMock()`` / ``Mock()`` silently answers calls to nonexistent
methods and swallows wrong kwargs. That is how a whole family of dead/renamed
production paths stayed invisible for months (auto_promotion, the synthesis
promote() bridge, code_agent, and the 2026-06-13 batch: analysis_text,
get_stats, classify_action, _current_mode, WikiClient.fetch, get_uptime_hours).

The sweep replaced internal-class mocks with ``specced(Cls)`` (create_autospec),
which enforces method names and signatures. Bare mocks that remain are
legitimate external boundaries (requests / subprocess / cv2 / datetime / HTTP
response shapes) or genuinely shapeless stand-ins.

This is a RATCHET, not a hard ban: the count may only go DOWN. If you add a new
bare mock for a real external boundary, that's fine -- but bump _CEILING here in
the same commit (a deliberate, reviewed choice). If the new mock stands in for an
internal agent_core class, use ``specced()`` instead. Either way the regrowth is
never silent.
"""
import re
from pathlib import Path

# Post-sweep count of bare `= MagicMock()` / `= Mock()` across agent_core/tests/.
# RATCHET DOWN ONLY. Lower it as more get converted; bump it (with justification)
# only when adding a genuine external-boundary mock.
_CEILING = 212

_BARE_MOCK = re.compile(r"=\s*(?:MagicMock|Mock)\(\)")
_TESTS_DIR = Path(__file__).parent


def _count_bare_mocks() -> dict:
    counts = {}
    for path in sorted(_TESTS_DIR.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue  # don't count this audit file's own regex/docstring text
        src = path.read_text(encoding="utf-8", errors="replace")
        n = len(_BARE_MOCK.findall(src))
        if n:
            counts[path.name] = n
    return counts


def test_bare_mock_count_does_not_grow():
    counts = _count_bare_mocks()
    total = sum(counts.values())
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:10]
    assert total <= _CEILING, (
        f"Bare mock count grew to {total} (ceiling {_CEILING}). "
        f"Use specced(Cls) for internal agent_core classes; only bump _CEILING in "
        f"agent_core/tests/test_mock_hygiene_audit.py for a real external boundary. "
        f"Top offenders: {top}"
    )


def test_specced_helper_enforces_contract():
    """specced() must reject phantom methods/signatures -- the whole point."""
    from agent_core.tests.spec_helpers import specced
    from agent_core.bulletin.bulletin_store import BulletinStore

    store = specced(BulletinStore)
    # A real method is callable...
    assert hasattr(store, "create_and_post")
    # ...a phantom one raises (this is what a bare MagicMock would have hidden).
    import pytest
    with pytest.raises(AttributeError):
        store.add_entry  # noqa: B018 -- historical phantom (see CLAUDE.md bulletin notes)
