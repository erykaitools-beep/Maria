"""
Specced mocks - the antidote to mock-hidden bugs (audit 2026-06-12).

A bare MagicMock() silently swallows calls to nonexistent methods and
wrong kwargs. That is exactly how three real bugs stayed invisible:
the bulletin ``add_entry`` phantom, the dead ``auto_promotion`` wiring
and the synthesis promote() bridge. Standard for new/updated tests:

    from agent_core.tests.spec_helpers import specced
    store = specced(BulletinStore)

``create_autospec`` enforces BOTH method names and call signatures.
Instance attributes that only exist after __init__ (so the class spec
does not know them) can be attached via kwargs:

    store = specced(BulletinStore, entries=[])

Use plain MagicMock only for external boundaries (requests, subprocess)
or genuinely shapeless objects.
"""
from unittest.mock import create_autospec


def specced(cls, _instance=True, **attrs):
    """Return create_autospec(cls, instance=_instance) with extra attrs set."""
    m = create_autospec(cls, instance=_instance)
    for name, value in attrs.items():
        setattr(m, name, value)
    return m
